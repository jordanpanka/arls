import json

import pytest

from app.evaluation.eval_mode import EvalExecution
from codemind_eval import runner
from codemind_eval.runner import (
    ExperimentConfig, completed_keys, ensure_manifest, latest_runs, plan_runs, read_runs, run_experiment, snapshot_matches,
)
from codemind_eval.schema import Benchmark, GoldEvidence, Question, Repository, Scope

SCOPE = Scope(user_id=1, investigation_id=2, project_id=3)


def benchmark(commit=None) -> Benchmark:
    return Benchmark(name="t", repository=Repository(id="repo", commit_sha=commit), questions=[
        Question(id="q1", question="What does a do?", gold_evidence=[GoldEvidence(kind="file", path="a.py")]),
        Question(id="q2", question="What does b do?"),
    ])


def config(tmp_path, **overrides) -> ExperimentConfig:
    values = dict(experiment_id="exp", out_dir=tmp_path / "exp", strategies=["vector_rag", "adaptive_rag"],
                  default_scope=SCOPE, retries=1, backoff_s=0, benchmark_hash="h1")
    values.update(overrides)
    return ExperimentConfig(**values)


def execution(strategy, metrics="default"):
    record = {"kind": "legacy_run", "strategy": strategy, "inputTokens": 10, "outputTokens": 2, "tokenUsageComplete": True,
              "llmCalls": 1, "retrievedEvidence": [{"path": "a.py"}], "contextEvidence": [{"alias": "SOURCE_1", "path": "a.py"}],
              "answer": "ok"}
    return EvalExecution(strategy=strategy, metrics=metrics, response=None, records=[record], wall_ms=12.5)


class Executor:
    def __init__(self, fail=None):
        self.fail = fail or {}
        self.calls = []

    async def __call__(self, request, strategy, metrics):
        self.calls.append((request.prompt, strategy, metrics))
        remaining = self.fail.get(strategy, 0)
        if remaining:
            self.fail[strategy] = remaining - 1
            raise ConnectionError(f"{strategy} backend down")
        return execution(strategy, metrics)


async def snapshot(scope):
    return {"repositorySnapshot": "commit:abc123def"}


async def no_sleep(_):
    return None


def test_git_state_falls_back_to_environment_without_git(monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(runner.subprocess, "run", no_git)
    monkeypatch.setenv("CODEMIND_COMMIT", "abc123")
    monkeypatch.setenv("CODEMIND_DIRTY", "false")
    state = runner._git_state()
    assert state["codemindCommit"] == "abc123" and state["codemindDirty"] is False
    assert state["codemindCommitSource"] == "env" and state["gitError"] == "git"
    monkeypatch.delenv("CODEMIND_COMMIT")
    monkeypatch.delenv("CODEMIND_DIRTY")
    assert runner._git_state()["codemindCommit"] is None


def test_plan_covers_every_combination_and_skips_redundant_vector_ablation():
    specs = plan_runs(benchmark(), ["vector_rag", "hybrid_rag"], ["default", "off"], repetitions=2)
    keys = {(s.question.id, s.strategy, s.metrics, s.repetition) for s in specs}
    assert len(specs) == 2 * 2 * 3
    assert ("q1", "vector_rag", "off", 1) not in keys
    shuffled = plan_runs(benchmark(), ["vector_rag", "hybrid_rag"], ["default"], 1, shuffle_seed=3)
    assert sorted(s.question.id + s.strategy for s in shuffled) == sorted(s.question.id + s.strategy for s in
                                                                         plan_runs(benchmark(), ["vector_rag", "hybrid_rag"], ["default"], 1))


async def test_runs_are_logged_with_trace_and_snapshot(tmp_path):
    cfg = config(tmp_path)
    counts = await run_experiment(cfg, benchmark(commit="abc123"), Executor(), snapshot, log=lambda *_: None, sleep=no_sleep)
    assert counts == {"planned": 4, "skipped": 0, "ok": 4, "error": 0}
    records = read_runs(cfg.runs_path)
    first = records[0]
    assert first["runKey"] == "exp|q1|vector_rag|default|1"
    assert first["repositoryId"] == "repo"
    assert first["commitSha"] == "abc123def"
    assert first["snapshotMatches"] is True
    assert first["latency"]["totalMs"] == 12.5
    assert first["traces"][0]["kind"] == "legacy_run"
    manifest = json.loads(cfg.manifest_path.read_text(encoding="utf-8"))
    assert manifest["strategies"] == ["vector_rag", "adaptive_rag"]
    assert manifest["benchmark"]["sha256"] == "h1"


async def test_failures_are_retried_then_recorded_without_scores(tmp_path):
    cfg = config(tmp_path, retries=2)
    executor = Executor(fail={"adaptive_rag": 99, "vector_rag": 1})
    counts = await run_experiment(cfg, benchmark(), executor, snapshot, log=lambda *_: None, sleep=no_sleep)
    assert counts["error"] == 2 and counts["ok"] == 2
    runs = latest_runs(read_runs(cfg.runs_path))
    failed = runs["exp|q1|adaptive_rag|default|1"]
    assert failed["status"] == "error"
    assert failed["attempts"] == 3
    assert len(failed["errors"]) == 3 and "backend down" in failed["errors"][-1]
    assert "answer" not in failed and "inputTokens" not in failed
    recovered = runs["exp|q1|vector_rag|default|1"]
    assert recovered["status"] == "ok" and recovered["attempts"] == 2 and len(recovered["errors"]) == 1


async def test_a_run_whose_llm_call_failed_is_an_error_even_if_the_strategy_recovered(tmp_path, monkeypatch):
    import httpx
    from app.services import ollama_call

    async def quota_exceeded(*args, **kwargs):
        raise httpx.HTTPError("429 monthly usage limit")

    monkeypatch.setattr(ollama_call, "_generate", quota_exceeded)

    class SwallowingExecutor(Executor):
        async def __call__(self, request, strategy, metrics):
            try:
                await ollama_call.call_llm_with_usage("q")
            except Exception:
                pass
            return await super().__call__(request, strategy, metrics)

    cfg = config(tmp_path, strategies=["vector_rag"], retries=1)
    counts = await run_experiment(cfg, benchmark(), SwallowingExecutor(), snapshot, log=lambda *_: None, sleep=no_sleep)
    assert counts["error"] == 2 and counts["ok"] == 0
    failed = latest_runs(read_runs(cfg.runs_path))["exp|q1|vector_rag|default|1"]
    assert "LlmUnavailable" in failed["errors"][-1] and "429" in failed["errors"][-1]


async def test_resume_skips_completed_runs_and_retries_failed_ones(tmp_path):
    cfg = config(tmp_path, retries=0)
    await run_experiment(cfg, benchmark(), Executor(fail={"adaptive_rag": 99}), snapshot, log=lambda *_: None, sleep=no_sleep)
    assert len(completed_keys(cfg.runs_path)) == 2
    executor = Executor()
    counts = await run_experiment(cfg, benchmark(), executor, snapshot, log=lambda *_: None, sleep=no_sleep)
    assert counts["skipped"] == 2 and counts["ok"] == 2
    assert {c[1] for c in executor.calls} == {"adaptive_rag"}
    latest = latest_runs(read_runs(cfg.runs_path))
    assert all(r["status"] == "ok" for r in latest.values())


def test_latest_run_prefers_success_and_ignores_corrupt_lines(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text("\n".join([
        json.dumps({"runKey": "k", "status": "ok", "n": 1}),
        "{not json",
        json.dumps({"runKey": "k", "status": "error", "n": 2}),
    ]) + "\n", encoding="utf-8")
    assert latest_runs(read_runs(path))["k"]["n"] == 1


async def test_missing_scope_is_an_error_not_a_crash(tmp_path):
    cfg = config(tmp_path, default_scope=None, strategies=["vector_rag"])
    counts = await run_experiment(cfg, benchmark(), Executor(), snapshot, log=lambda *_: None, sleep=no_sleep)
    assert counts["error"] == 2


def test_manifest_refuses_a_changed_benchmark(tmp_path):
    ensure_manifest(config(tmp_path), benchmark())
    with pytest.raises(RuntimeError):
        ensure_manifest(config(tmp_path, benchmark_hash="h2"), benchmark())


@pytest.mark.parametrize("expected,observed,result", [
    ("abc123", "commit:abc123ffff", True),
    ("abc123ffff", "commit:abc123", True),
    ("abc123", "commit:999", False),
    ("abc123", "fs:1234", False),
    ("abc123", None, None),
    (None, "commit:abc", None),
])
def test_snapshot_matching(expected, observed, result):
    assert snapshot_matches(expected, observed) is result
