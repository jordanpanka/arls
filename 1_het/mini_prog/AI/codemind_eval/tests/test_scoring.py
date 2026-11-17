import json

import pytest

from codemind_eval.routing import (decision_correctness, oracle, routing_analysis, summarize_decisions,
                                   summarize_non_optimal)
from codemind_eval.scoring import combine_experiments, composite_scores, read_csv, score_experiment, write_csv
from codemind_eval.schema import Benchmark, GoldEvidence, Question, Repository
from codemind_eval.stats import bootstrap_ci, paired_differences, summarize


def row(question, strategy, quality, tokens=100, latency=1000.0, metrics="default", effective=None, rep=1, status="ok"):
    return {"questionId": question, "strategy": strategy, "metrics": metrics, "repetition": rep, "status": status,
            "q": quality, "totalTokens": tokens, "latencyTotalMs": latency, "latencyRoutingMs": 5.0 if strategy == "adaptive_rag" else None,
            "effectiveStrategy": effective or strategy, "selectedStrategy": effective or strategy, "escalated": False}


def test_oracle_picks_best_quality_then_cheapest():
    results = {"a": {"quality": 0.9, "tokens": 500, "latency": 10}, "b": {"quality": 0.9, "tokens": 100, "latency": 50},
               "c": {"quality": 0.2, "tokens": 10, "latency": 1}}
    pick, optimal, best = oracle(results, ("a", "b", "c"))
    assert pick == "b" and set(optimal) == {"a", "b"} and best == 0.9
    assert oracle({"a": {"quality": None, "tokens": 1, "latency": 1}}, ("a",)) == (None, [], None)


def test_routing_agreement_regret_and_savings():
    rows = [
        row("q1", "vector_rag", 0.2), row("q1", "selective_rag", 0.8, tokens=200, latency=2000),
        row("q1", "hybrid_rag", 0.8, tokens=400), row("q1", "evidence_aware_agentic_rag", 0.8, tokens=1000, latency=9000),
        row("q1", "adaptive_rag", 0.8, tokens=250, latency=2500, effective="selective_rag"),
        row("q2", "vector_rag", 0.0), row("q2", "selective_rag", 0.4, tokens=200),
        row("q2", "hybrid_rag", 0.5, tokens=400), row("q2", "evidence_aware_agentic_rag", 1.0, tokens=1200, latency=8000),
        row("q2", "adaptive_rag", 0.4, tokens=260, latency=3000, effective="selective_rag"),
        row("q2", "adaptive_rag", 0.9, metrics="off"),
        row("q3", "vector_rag", 1.0, status="error"),
    ]
    per_question, summary = routing_analysis(rows, "q")
    by = {r["questionId"]: r for r in per_question}
    assert by["q1"]["oracle"] == "selective_rag" and by["q1"]["agreement"] == 1 and by["q1"]["regret"] == 0
    assert by["q2"]["oracle"] == "evidence_aware_agentic_rag" and by["q2"]["agreement"] == 0
    assert by["q2"]["regret"] == pytest.approx(0.6)
    assert by["q2"]["restrictedOracle"] == "evidence_aware_agentic_rag"
    assert by["q1"]["tokenSavings"] == 750 and by["q2"]["latencySavingsMs"] == 5000
    assert summary["oracleAgreement"] == 0.5
    assert summary["meanRegret"] == pytest.approx(0.3)
    assert summary["tokenSavingsRelative"] == pytest.approx((750 + 940) / 2200)
    assert summary["effectiveDistribution"] == {"selective_rag": 2}
    assert "q3" not in by


def test_routing_tolerance_agreement_and_reasons():
    rows = [
        row("q1", "vector_rag", 0.9), row("q1", "selective_rag", 0.8), row("q1", "hybrid_rag", 0.5),
        row("q1", "evidence_aware_agentic_rag", 0.6),
        {**row("q1", "adaptive_rag", 0.8, effective="selective_rag"), "routeReason": "simple_question"},
        {**row("q1", "adaptive_rag", 0.8, effective="evidence_aware_agentic_rag", rep=2),
         "routeReason": "simple_question", "escalated": True, "escalationReason": "targets_not_retrieved"},
    ]
    per_question, summary = routing_analysis(rows, "q")
    assert per_question[0]["agreement"] == 0 and per_question[0]["toleranceAgreement"] == 1
    assert summary["toleranceOracleAgreement"] == 1
    assert summary["routeReasons"] == {"simple_question": 2}
    assert summary["escalationReasons"] == {"targets_not_retrieved": 1}


def test_decision_correctness_prefers_cheaper_on_tie_and_separates_escalation():
    rows = [
        row("q1", "selective_rag", 0.70, tokens=300), row("q1", "evidence_aware_agentic_rag", 0.75, tokens=1500),
        {**row("q1", "adaptive_rag", 0.7, effective="evidence_aware_agentic_rag"), "selectedStrategy": "selective_rag",
         "escalated": True, "category": "comprehension"},
        row("q2", "selective_rag", 0.30, tokens=300), row("q2", "evidence_aware_agentic_rag", 0.90, tokens=1500),
        {**row("q2", "adaptive_rag", 0.9, effective="evidence_aware_agentic_rag"), "category": "architecture"},
        {**row("q2", "adaptive_rag", 0.9, effective="evidence_aware_agentic_rag", rep=2), "category": "architecture"},
        row("q3", "selective_rag", None), row("q3", "evidence_aware_agentic_rag", 0.5),
        {**row("q3", "adaptive_rag", 0.5, effective="selective_rag"), "category": "code_quality"},
    ]
    by = {d["questionId"]: d for d in decision_correctness(rows, "q")}
    assert by["q1"]["better"] == "tie" and by["q1"]["correctChoice"] == "selective_rag"
    assert by["q1"]["selectedCorrect"] == 1 and by["q1"]["effectiveCorrect"] == 0 and by["q1"]["escalationRate"] == 1
    assert by["q2"]["correctChoice"] == "evidence_aware_agentic_rag" and by["q2"]["selectedCorrect"] == 1
    assert by["q2"]["adaptiveRuns"] == 2 and by["q2"]["selectedConsistent"] == 1
    assert by["q1"]["effectiveOutcome"] == "wasted_agent" and by["q1"]["effectiveExtraTokens"] == 1200
    assert by["q1"]["effectiveQualityLoss"] == pytest.approx(-0.05) and by["q1"]["effectiveTokenRatio"] == 5
    assert by["q2"]["effectiveOutcome"] == "optimal"
    assert by["q3"]["status"] == "missing_quality" and by["q3"]["selectedCorrect"] is None
    severity = {r["outcome"]: r for r in summarize_non_optimal(list(by.values()))}
    assert severity["wasted_agent"]["questions"] == 1 and severity["optimal"]["share"] == 0.5
    overall = summarize_decisions(list(by.values()))[0]
    assert overall["evaluated"] == 2 and overall["notEvaluated"] == 1 and overall["selectedAccuracy"] == 1
    assert overall["effectiveAccuracy"] == 0.5 and overall["alwaysSelectiveAccuracy"] == 0.5
    assert {r["value"] for r in summarize_decisions(list(by.values()), "category")} == {
        "comprehension", "architecture", "code_quality"}


def test_composite_averages_dimensions_and_skips_missing():
    scores = composite_scores({"status": "ok", "judge_status": "ok", "judge_correctness_norm": 1 / 3,
                               "judge_completeness": 1.0, "judge_faithfulness": 1.0, "judge_citation_correctness": 0.5,
                               "ctx_file_recall@5": 0.5})
    assert scores["composite_answer"] == pytest.approx(2 / 3)
    assert scores["composite_grounding"] == pytest.approx(0.75)
    assert scores["composite_score"] == pytest.approx((2 / 3 + 0.75 + 0.5) / 3)
    no_reference = composite_scores({"status": "ok", "judge_status": "ok", "judge_faithfulness": 1.0,
                                     "judge_citation_correctness": 1.0, "ctx_file_recall@5": 0.0})
    assert no_reference["composite_answer"] is None and no_reference["composite_score"] == pytest.approx(0.5)
    assert composite_scores({"status": "ok", "judge_status": "judge_error", "ctx_file_recall@5": 1.0}) == {}
    assert composite_scores({"status": "error"}) == {}


def test_summary_averages_repetitions_before_questions():
    rows = [row("q1", "s", 1.0, rep=1), row("q1", "s", 0.0, rep=2), row("q2", "s", 1.0), row("q3", "s", None),
            row("q4", "s", 1.0, status="error")]
    entry = summarize(rows, ["q"], ("strategy",))[0]
    assert entry["n_questions"] == 2
    assert entry["mean"] == pytest.approx(0.75)
    assert entry["runs"] == 5 and entry["ok_runs"] == 4
    assert entry["within_question_std"] == pytest.approx(0.5)


def test_bootstrap_ci_is_reproducible_and_brackets_the_mean():
    values = [0.1, 0.4, 0.5, 0.9, 1.0]
    low, high = bootstrap_ci(values, seed=1)
    assert (low, high) == bootstrap_ci(values, seed=1)
    assert low < sum(values) / len(values) < high
    assert bootstrap_ci([0.3]) == (None, None)


def test_paired_differences_only_use_shared_questions():
    rows = [row("q1", "s", 0.9), row("q1", "s", 0.5, metrics="off"), row("q2", "s", 0.7), row("q2", "s", 0.7, metrics="off"),
            row("q3", "s", 1.0)]
    diff = paired_differences(rows, "q", "metrics", "default", "off", ("strategy",))[0]
    assert diff["n_questions"] == 2
    assert diff["mean_delta"] == pytest.approx(0.2)
    assert (diff["wins"], diff["losses"], diff["ties"]) == (1, 0, 1)


def run_record(question, strategy, context, metrics="default", status="ok", answer="a [SOURCE_1]"):
    key = f"exp|{question}|{strategy}|{metrics}|1"
    if status != "ok":
        return {"runKey": key, "questionId": question, "strategy": strategy, "metrics": metrics, "repetition": 1,
                "status": status, "errors": ["boom"]}
    return {
        "runKey": key, "questionId": question, "strategy": strategy, "metrics": metrics, "repetition": 1, "status": "ok",
        "selectedStrategy": "selective_rag" if strategy == "adaptive_rag" else strategy,
        "effectiveStrategy": "selective_rag" if strategy == "adaptive_rag" else strategy,
        "route": {"reason": "simple_question"} if strategy == "adaptive_rag" else None,
        "contextEvidence": context, "retrievedEvidence": context, "citedAliases": ["SOURCE_1"], "answer": answer,
        "contextText": "[SOURCE_1] code", "inputTokens": 100, "outputTokens": 20, "tokenUsageComplete": True,
        "toolCalls": 1 if "agentic" in strategy else 0, "iterations": 1,
        "toolSequence": ["find_symbol"] if "agentic" in strategy else [],
        "latency": {"totalMs": 1500.0, "routingMs": 5.0 if strategy == "adaptive_rag" else None},
        "snapshotMatches": True, "repositorySnapshot": "commit:base",
    }


@pytest.fixture
def experiment(tmp_path):
    out = tmp_path / "exp"
    out.mkdir()
    good = [{"alias": "SOURCE_1", "path": "src/A.java", "symbol": "run"}]
    bad = [{"alias": "SOURCE_1", "path": "src/Z.java", "symbol": "zz"}]
    records = []
    for question in ("q1", "q2"):
        for strategy in ("vector_rag", "selective_rag", "hybrid_rag", "evidence_aware_agentic_rag", "adaptive_rag"):
            context = good if strategy != "vector_rag" else bad
            records.append(run_record(question, strategy, context))
            if strategy != "vector_rag":
                records.append(run_record(question, strategy, bad, metrics="off"))
    records.append(run_record("impact-1", "evidence_aware_agentic_rag", good))
    records.append(run_record("q1", "hybrid_rag", good, metrics="off", status="error"))
    (out / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    judgements = [
        {"runKey": "exp|q1|selective_rag|default|1", "status": "ok", "factual_correctness": 3, "completeness": 1.0,
         "faithfulness": 1.0, "citation_correctness": 1.0, "judgeModel": "j", "promptVersion": "p"},
        {"runKey": "exp|q1|vector_rag|default|1", "status": "judge_error"},
    ]
    (out / "judgements.jsonl").write_text("\n".join(json.dumps(j) for j in judgements) + "\n", encoding="utf-8")
    bench = Benchmark(name="t", repository=Repository(id="r"), questions=[
        Question(id="q1", question="?", category="comprehension", reference_answer="ref",
                 gold_evidence=[GoldEvidence(kind="file", path="src/A.java"), GoldEvidence(kind="symbol", path="src/A.java", symbol="run")]),
        Question(id="q2", question="?", category="dependency", gold_evidence=[GoldEvidence(kind="file", path="src/A.java")]),
        Question(id="impact-1", question="?", category="change_impact", impact_files=["src/A.java", "src/B.java"],
                 gold_evidence=[GoldEvidence(kind="file", path="src/A.java"), GoldEvidence(kind="file", path="src/B.java")]),
    ])
    return out, bench


def test_score_experiment_writes_all_tables(experiment):
    out, bench = experiment
    result = score_experiment(out, bench)
    scores = out / "scores"
    for name in ("rows.csv", "status_counts.csv", "summary_by_strategy.csv", "summary_by_category.csv",
                 "tool_usage.csv", "ablation.csv", "impact.csv", "routing_questions.csv", "routing_summary.json"):
        assert (scores / name).exists(), name
    rows = {r["runKey"]: r for r in read_csv(scores / "rows.csv")}
    assert rows["exp|q1|hybrid_rag|default|1"]["ctx_file_recall@5"] == 1
    assert rows["exp|q1|vector_rag|default|1"]["ctx_file_recall@5"] == 0
    assert rows["exp|q1|hybrid_rag|off|1"]["status"] == "ok"
    assert rows["exp|q1|selective_rag|default|1"]["judge_correctness_norm"] == 1
    assert rows["exp|q1|vector_rag|default|1"]["judge_status"] == "judge_error"
    assert rows["exp|q1|vector_rag|default|1"]["judge_faithfulness"] is None
    assert rows["exp|q1|vector_rag|default|1"]["composite_score"] is None
    assert rows["exp|q1|selective_rag|default|1"]["composite_score"] == 1
    assert rows["exp|impact-1|evidence_aware_agentic_rag|default|1"]["impact_cited_recall"] == 0.5
    assert result["qualityKey"] == "judge_correctness_norm"
    assert (scores / "routing_questions_composite.csv").exists()
    assert result["routingComposite"]["qualityKey"] == "composite_score"
    summary = read_csv(scores / "summary_by_strategy.csv")
    hybrid = next(r for r in summary if r["strategy"] == "hybrid_rag" and r["metrics"] == "default"
                  and r["metric"] == "ctx_file_recall@5")
    assert hybrid["mean"] == 1 and hybrid["n_questions"] == 2
    ablation = read_csv(scores / "ablation.csv")
    entry = next(r for r in ablation if r["strategy"] == "selective_rag" and r["metric"] == "ctx_file_recall@5")
    assert entry["mean_delta"] == 1


def test_combine_pools_scored_experiments(experiment, tmp_path):
    out, bench = experiment
    single = score_experiment(out, bench)
    other = tmp_path / "other"
    renamed = []
    for r in read_csv(out / "scores" / "rows.csv"):
        _, question, rest = r["runKey"].split("|", 2)
        renamed.append({**r, "runKey": f"other|p-{question}|{rest}", "questionId": f"p-{r['questionId']}"})
    write_csv(other / "scores" / "rows.csv", renamed)

    result = combine_experiments([out, other], tmp_path / "combined")
    scores = tmp_path / "combined" / "scores"
    rows = read_csv(scores / "rows.csv")
    assert {r["experiment"] for r in rows} == {"exp", "other"}
    assert result["routing"]["questions"] == 2 * single["routing"]["questions"]
    summary = read_csv(scores / "summary_by_strategy.csv")
    hybrid = next(r for r in summary if r["strategy"] == "hybrid_rag" and r["metrics"] == "default"
                  and r["metric"] == "ctx_file_recall@5")
    assert hybrid["n_questions"] == 4
    with pytest.raises(ValueError):
        combine_experiments([out, out], tmp_path / "twice")


def test_errors_are_counted_not_scored(experiment):
    out, bench = experiment
    with open(out / "runs.jsonl", "a", encoding="utf-8") as handle:
        failed = run_record("q2", "hybrid_rag", [], metrics="off", status="error")
        failed.update(runKey="exp|q2|hybrid_rag|off|2", repetition=2)
        handle.write(json.dumps(failed) + "\n")
    score_experiment(out, bench)
    counts = {(r["strategy"], r["metrics"]): r for r in read_csv(out / "scores" / "status_counts.csv")}
    assert counts[("hybrid_rag", "off")]["error"] == 1
    assert counts[("hybrid_rag", "off")]["ok"] == 2
    summary = read_csv(out / "scores" / "summary_by_strategy.csv")
    entry = next(r for r in summary if r["strategy"] == "hybrid_rag" and r["metrics"] == "off"
                 and r["metric"] == "ctx_file_recall@5")
    assert entry["runs"] == 3 and entry["ok_runs"] == 2 and entry["n_questions"] == 2


def test_reports_render_png_figures(experiment):
    pytest.importorskip("matplotlib")
    from codemind_eval.reports import generate_reports
    out, bench = experiment
    score_experiment(out, bench, routing_quality="ctx_file_recall@5")
    produced = generate_reports(out)
    for name in ("retrieval_by_strategy", "quality_by_category", "latency_distribution", "tool_usage",
                 "routing_decisions", "metrics_ablation", "change_impact", "answer_quality_by_strategy",
                 "overall_score_by_strategy", "overall_score_by_category", "routing_decisions_composite",
                 "cost_vs_quality", "adaptive_savings_tradeoff"):
        assert produced[name], name
        assert (out / "figures" / f"{name}.png").stat().st_size > 1000
