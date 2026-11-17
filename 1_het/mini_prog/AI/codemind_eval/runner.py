import asyncio
import json
import os
import platform
import random
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from codemind_eval import SCHEMA_VERSION
from codemind_eval.records import RUN_SCHEMA, normalize_execution, run_key
from codemind_eval.schema import Benchmark, Question, Scope

REDUNDANT_VARIANTS = {("vector_rag", "off")}
ENV_KEYS = (
    "GEN_MODEL", "GEN_MODEL_CLOUD", "EMBED_MODEL", "EMBED_MODEL_CLOUD", "EMBED_DIM", "QDRANT_COLLECTION",
    "CHAT_DEFAULT_MODE", "ROUTER_ESCALATION", "SUFF_USE_LLM", "AGENT_LLM_CLAIM_VERIFICATION",
    "ENABLE_DESIGN_PATTERN_ANALYSIS", "AGENT_ENABLE_HISTORY_TOOLS", "AGENT_SEED_RETRIEVAL", "CODE_GRAPH_LIMIT",
)

Executor = Callable[[object, str, str], Awaitable[object]]
SnapshotFn = Callable[[Scope], Awaitable[dict]]


@dataclass
class RunSpec:
    question: Question
    strategy: str
    metrics: str
    repetition: int


@dataclass
class ExperimentConfig:
    experiment_id: str
    out_dir: Path
    strategies: list[str]
    metrics_variants: list[str] = field(default_factory=lambda: ["default"])
    repetitions: int = 1
    retries: int = 2
    backoff_s: float = 5.0
    run_timeout_s: float | None = None
    clear_caches: bool = True
    shuffle_seed: int | None = None
    default_scope: Scope | None = None
    ablation: str | None = None
    benchmark_path: str | None = None
    benchmark_hash: str | None = None
    keep_context_text: bool = True

    @property
    def runs_path(self) -> Path:
        return self.out_dir / "runs.jsonl"

    @property
    def manifest_path(self) -> Path:
        return self.out_dir / "manifest.json"


def plan_runs(benchmark: Benchmark, strategies: list[str], metrics_variants: list[str], repetitions: int,
              shuffle_seed: int | None = None) -> list[RunSpec]:
    specs = []
    for repetition in range(1, repetitions + 1):
        block = [
            RunSpec(q, s, m, repetition)
            for q in benchmark.questions
            for s in strategies
            for m in metrics_variants
            if (s, m) not in REDUNDANT_VARIANTS
        ]
        if shuffle_seed is not None:
            random.Random(shuffle_seed + repetition).shuffle(block)
        specs += block
    return specs


def read_runs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"warning: {path}:{number} is not valid JSON and was ignored", file=sys.stderr)
    return records


def latest_runs(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in records:
        key = record.get("runKey")
        if not key:
            continue
        previous = latest.get(key)
        if previous is None or record.get("status") == "ok" or previous.get("status") != "ok":
            latest[key] = record
    return latest


def completed_keys(path: Path) -> set[str]:
    return {k for k, r in latest_runs(read_runs(path)).items() if r.get("status") == "ok"}


def _git_state() -> dict:
    root = Path(__file__).resolve().parents[1]
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        if sha:
            return {"codemindCommit": sha, "codemindDirty": bool(dirty)}
        error = "not a git checkout"
    except Exception as e:
        error = str(e)
    commit = os.getenv("CODEMIND_COMMIT")
    dirty_flag = os.getenv("CODEMIND_DIRTY")
    return {
        "codemindCommit": commit or None,
        "codemindDirty": dirty_flag.lower() in ("1", "true", "yes") if dirty_flag else None,
        "codemindCommitSource": "env" if commit else None,
        "gitError": error,
    }


def _agent_config() -> dict | None:
    try:
        from app.agents.config import AgentConfig
        return AgentConfig.from_env().to_dict()
    except Exception as e:
        return {"error": str(e)}


def build_manifest(config: ExperimentConfig, benchmark: Benchmark, argv: list[str] | None = None) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "experimentId": config.experiment_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "benchmark": {
            "name": benchmark.name,
            "path": config.benchmark_path,
            "sha256": config.benchmark_hash,
            "questions": len(benchmark.questions),
            "repository": benchmark.repository.model_dump(),
            "annotationStatus": sorted({q.annotation_status for q in benchmark.questions}),
        },
        "strategies": config.strategies,
        "metricsVariants": config.metrics_variants,
        "repetitions": config.repetitions,
        "ablation": config.ablation,
        "retries": config.retries,
        "runTimeoutS": config.run_timeout_s,
        "clearCaches": config.clear_caches,
        "shuffleSeed": config.shuffle_seed,
        "scope": config.default_scope.model_dump() if config.default_scope else None,
        "environment": {k: os.getenv(k) for k in ENV_KEYS},
        "agentConfig": _agent_config(),
        "python": sys.version,
        "platform": platform.platform(),
        "argv": argv,
        **_git_state(),
    }


def ensure_manifest(config: ExperimentConfig, benchmark: Benchmark, argv: list[str] | None = None) -> dict:
    config.out_dir.mkdir(parents=True, exist_ok=True)
    if config.manifest_path.exists():
        with open(config.manifest_path, encoding="utf-8") as handle:
            existing = json.load(handle)
        previous_hash = (existing.get("benchmark") or {}).get("sha256")
        if previous_hash and config.benchmark_hash and previous_hash != config.benchmark_hash:
            raise RuntimeError(
                f"Experiment '{config.experiment_id}' was started with a different benchmark file "
                f"(sha256 {previous_hash[:12]} vs {config.benchmark_hash[:12]}). Use a new experiment id."
            )
        existing.setdefault("resumedAt", []).append(datetime.now(timezone.utc).isoformat())
        manifest = existing
    else:
        manifest = build_manifest(config, benchmark, argv)
    with open(config.manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest


class LlmUnavailable(RuntimeError):
    pass


def _llm_failures():
    from app.services.ollama_call import record_llm_failures
    return record_llm_failures()


def clear_tool_caches() -> None:
    from app.tools.base import RESULT_CACHE
    from app.tools.code_graph import GRAPH_CACHE
    RESULT_CACHE.entries.clear()
    GRAPH_CACHE.entries.clear()


def snapshot_matches(expected_sha: str | None, observed: str | None) -> bool | None:
    if not expected_sha or not observed:
        return None
    if not observed.startswith("commit:"):
        return False
    sha = observed.split(":", 1)[1].lower()
    expected = expected_sha.lower()
    return sha.startswith(expected) or expected.startswith(sha)


async def default_executor(request, strategy: str, metrics: str):
    from app.evaluation.eval_mode import run_evaluation
    return await run_evaluation(request, strategy, metrics)


async def default_snapshot(scope: Scope) -> dict:
    from app.evaluation.eval_mode import repository_snapshot
    from app.tools.base import Scope as ToolScope
    return await repository_snapshot(ToolScope(scope.user_id, scope.investigation_id, scope.project_id))


def _request(question: Question, scope: Scope, experiment_id: str, ablation: str | None):
    from app.models.models import ChatRequest
    return ChatRequest(
        prompt=question.question,
        userId=scope.user_id,
        investigationId=scope.investigation_id,
        projectId=scope.project_id,
        ablation=ablation,
        experimentId=experiment_id,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def execute_run(spec: RunSpec, config: ExperimentConfig, benchmark: Benchmark, executor: Executor,
                      snapshot: dict | None, sleep=asyncio.sleep) -> dict:
    question = spec.question
    scope = question.scope or config.default_scope
    key = run_key(config.experiment_id, question.id, spec.strategy, spec.metrics, spec.repetition)
    expected_sha = question.expected_commit_sha or benchmark.repository.commit_sha
    base = {
        "schema": RUN_SCHEMA,
        "runKey": key,
        "experimentId": config.experiment_id,
        "questionId": question.id,
        "category": question.category,
        "strategy": spec.strategy,
        "metrics": spec.metrics,
        "repetition": spec.repetition,
        "repositoryId": benchmark.repository.id,
        "expectedCommitSha": expected_sha,
        "scope": scope.model_dump() if scope else None,
        "startedAt": _now(),
    }
    if scope is None:
        return {**base, "status": "error", "attempts": 0, "errors": ["no project scope for question"], "finishedAt": _now()}

    errors: list[str] = []
    for attempt in range(1, config.retries + 2):
        if config.clear_caches:
            clear_tool_caches()
        request = _request(question, scope, config.experiment_id, config.ablation)
        try:
            with _llm_failures() as failures:
                call = executor(request, spec.strategy, spec.metrics)
                execution = await (asyncio.wait_for(call, timeout=config.run_timeout_s) if config.run_timeout_s else call)
            if failures:
                raise LlmUnavailable(f"{len(failures)} failed LLM call(s), last: {failures[-1][:300]}")
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
            base["lastTraceback"] = traceback.format_exc(limit=8)
            if attempt <= config.retries:
                await sleep(config.backoff_s * (2 ** (attempt - 1)))
            continue
        normalized = normalize_execution(execution.records, execution.wall_ms, execution.response)
        observed = normalized.get("repositorySnapshot") or (snapshot or {}).get("repositorySnapshot")
        if not config.keep_context_text:
            normalized.pop("contextText", None)
        base.pop("lastTraceback", None)
        return {
            **base,
            **normalized,
            "repositorySnapshot": observed,
            "commitSha": observed.split(":", 1)[1] if observed and observed.startswith("commit:") else None,
            "snapshotMatches": snapshot_matches(expected_sha, observed),
            "status": "ok",
            "attempts": attempt,
            "errors": errors,
            "traces": execution.records,
            "finishedAt": _now(),
        }
    return {**base, "status": "error", "attempts": config.retries + 1, "errors": errors, "finishedAt": _now()}


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        handle.flush()


async def run_experiment(config: ExperimentConfig, benchmark: Benchmark, executor: Executor | None = None,
                         snapshot_fn: SnapshotFn | None = None, argv: list[str] | None = None,
                         log=print, sleep=asyncio.sleep) -> dict:
    executor = executor or default_executor
    snapshot_fn = snapshot_fn or default_snapshot
    ensure_manifest(config, benchmark, argv)
    done = completed_keys(config.runs_path)
    specs = plan_runs(benchmark, config.strategies, config.metrics_variants, config.repetitions, config.shuffle_seed)
    snapshots: dict[tuple, dict] = {}
    counts = {"planned": len(specs), "skipped": 0, "ok": 0, "error": 0}

    for index, spec in enumerate(specs, start=1):
        key = run_key(config.experiment_id, spec.question.id, spec.strategy, spec.metrics, spec.repetition)
        if key in done:
            counts["skipped"] += 1
            continue
        scope = spec.question.scope or config.default_scope
        scope_key = tuple(scope.model_dump().values()) if scope else None
        if scope_key is not None and scope_key not in snapshots:
            snapshots[scope_key] = await snapshot_fn(scope)
        record = await execute_run(spec, config, benchmark, executor, snapshots.get(scope_key), sleep)
        append_record(config.runs_path, record)
        counts[record["status"]] += 1
        latency = (record.get("latency") or {}).get("totalMs")
        log(f"[{index}/{len(specs)}] {spec.question.id} {spec.strategy}/{spec.metrics} rep{spec.repetition}: "
            f"{record['status']}" + (f" {latency:.0f}ms" if isinstance(latency, (int, float)) else "")
            + (f" errors={record['errors'][-1]}" if record["status"] != "ok" and record.get("errors") else ""))
    return counts
