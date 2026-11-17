import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from codemind_eval.impact import impact_metrics
from codemind_eval.judge import read_judgements
from codemind_eval.retrieval_metrics import retrieval_metrics
from codemind_eval.routing import routing_analysis
from codemind_eval.runner import latest_runs, read_runs
from codemind_eval.schema import Benchmark
from codemind_eval.stats import is_number, paired_differences, summarize

COMPOSITE_DIMENSIONS = {
    "composite_answer": ("judge_correctness_norm", "judge_completeness"),
    "composite_grounding": ("judge_faithfulness", "judge_citation_correctness"),
    "composite_retrieval": ("ctx_file_recall@5",),
}
COMPOSITE_QUALITY = "composite_score"
COMPOSITE_COLUMNS = [*COMPOSITE_DIMENSIONS, COMPOSITE_QUALITY]
RETRIEVAL_COLUMNS = [
    f"ctx_{level}_{m}" for level in ("file", "symbol")
    for m in ("recall@5", "recall@10", "precision@5", "precision@10", "mrr", "coverage")
] + [
    f"ret_{level}_{m}" for level in ("file", "symbol")
    for m in ("recall@5", "recall@10", "precision@5", "precision@10", "mrr", "coverage")
]
JUDGE_COLUMNS = ["judge_correctness_norm", "judge_factual_correctness", "judge_completeness", "judge_faithfulness",
                 "judge_citation_correctness"]
EFFICIENCY_COLUMNS = ["latencyTotalMs", "latencyRoutingMs", "latencyVectorMs", "latencyGraphMs", "latencyRetrievalMs",
                      "latencyContextMs", "latencyGenerationMs", "inputTokens", "outputTokens", "totalTokens",
                      "llmCalls", "toolCalls", "iterations"]
IMPACT_COLUMNS = [f"impact_{s}_{m}" for s in ("cited", "context") for m in ("precision", "recall", "f1")]
SUMMARY_COLUMNS = RETRIEVAL_COLUMNS + JUDGE_COLUMNS + COMPOSITE_COLUMNS + EFFICIENCY_COLUMNS + IMPACT_COLUMNS
ABLATION_COLUMNS = ["ctx_file_recall@5", "ctx_file_mrr", "ctx_symbol_recall@5", "judge_correctness_norm",
                    "judge_faithfulness", COMPOSITE_QUALITY, "totalTokens", "latencyTotalMs"]
FALLBACK_QUALITY = "ctx_file_recall@5"
PRIMARY_QUALITY = "judge_correctness_norm"


def _latency(record: dict, key: str):
    return (record.get("latency") or {}).get(key)


def _mean_present(values) -> float | None:
    numbers = [v for v in values if is_number(v)]
    return sum(numbers) / len(numbers) if numbers else None


def composite_scores(row: dict) -> dict:
    if row.get("status") != "ok" or row.get("judge_status") not in (None, "ok"):
        return {}
    dimensions = {name: _mean_present(row.get(c) for c in columns) for name, columns in COMPOSITE_DIMENSIONS.items()}
    return {**dimensions, COMPOSITE_QUALITY: _mean_present(dimensions.values())}


def score_row(record: dict, question, judgement: dict | None, require_snapshot: bool = True) -> dict:
    row = {
        "runKey": record.get("runKey"),
        "questionId": record.get("questionId"),
        "category": question.category if question else record.get("category"),
        "annotationStatus": question.annotation_status if question else None,
        "strategy": record.get("strategy"),
        "metrics": record.get("metrics"),
        "repetition": record.get("repetition"),
        "status": record.get("status"),
        "attempts": record.get("attempts"),
        "error": (record.get("errors") or [None])[-1] if record.get("status") != "ok" else None,
    }
    if record.get("status") != "ok":
        return row
    route = record.get("route") or {}
    tokens_in, tokens_out = record.get("inputTokens"), record.get("outputTokens")
    row.update({
        "selectedStrategy": record.get("selectedStrategy"),
        "effectiveStrategy": record.get("effectiveStrategy"),
        "escalated": record.get("escalated"),
        "routeReason": route.get("reason"),
        "escalationReason": route.get("escalationReason"),
        "repositorySnapshot": record.get("repositorySnapshot"),
        "snapshotMatches": record.get("snapshotMatches"),
        "responseStatus": record.get("responseStatus"),
        "stopReason": record.get("stopReason"),
        "toolCalls": record.get("toolCalls"),
        "iterations": record.get("iterations"),
        "toolsUsed": "|".join(record.get("toolsUsed") or []),
        "toolSequence": ">".join(record.get("toolSequence") or []),
        "llmCalls": record.get("llmCalls"),
        "inputTokens": tokens_in,
        "outputTokens": tokens_out,
        "totalTokens": tokens_in + tokens_out if tokens_in is not None and tokens_out is not None else None,
        "tokenUsageComplete": record.get("tokenUsageComplete"),
        "latencyTotalMs": _latency(record, "totalMs"),
        "latencyRoutingMs": _latency(record, "routingMs"),
        "latencyVectorMs": _latency(record, "vectorMs"),
        "latencyGraphMs": _latency(record, "graphMs"),
        "latencyRetrievalMs": _latency(record, "retrievalMs"),
        "latencyContextMs": _latency(record, "contextMs"),
        "latencyGenerationMs": _latency(record, "generationMs"),
        "citedCount": len(record.get("citedAliases") or []) if record.get("citedAliases") is not None else None,
    })
    if question is not None:
        row.update(retrieval_metrics(record, question))
        if question.impact_files:
            row.update(impact_metrics(record, question.impact_files, require_snapshot))
    if judgement is not None:
        row["judge_status"] = judgement.get("status")
        if judgement.get("status") == "ok":
            correctness = judgement.get("factual_correctness")
            row.update({
                "judge_factual_correctness": correctness,
                "judge_correctness_norm": correctness / 3 if correctness is not None else None,
                "judge_completeness": judgement.get("completeness"),
                "judge_faithfulness": judgement.get("faithfulness"),
                "judge_citation_correctness": judgement.get("citation_correctness"),
                "judge_model": judgement.get("judgeModel"),
                "judge_prompt_version": judgement.get("promptVersion"),
            })
    row.update(composite_scores(row))
    return row


def build_rows(out_dir: Path, benchmark: Benchmark, require_snapshot: bool = True) -> list[dict]:
    runs = latest_runs(read_runs(out_dir / "runs.jsonl"))
    judgements = read_judgements(out_dir / "judgements.jsonl")
    questions = benchmark.by_id()
    rows = []
    for key in sorted(runs):
        record = runs[key]
        rows.append(score_row(record, questions.get(record.get("questionId")), judgements.get(key), require_snapshot))
    return rows


def write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = []
        for row in rows:
            columns += [k for k in row if k not in columns]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in columns})
    return path


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [{k: _parse(v) for k, v in row.items()} for row in rows]


def _parse(value: str):
    if value == "":
        return None
    if value in ("True", "False"):
        return value == "True"
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() and "." not in value and "e" not in value.lower() else number


def tool_usage(rows: list[dict]) -> list[dict]:
    counts: dict[tuple, Counter] = defaultdict(Counter)
    runs: Counter = Counter()
    for row in rows:
        if row.get("status") != "ok":
            continue
        group = (row["strategy"], row["metrics"])
        runs[group] += 1
        for tool in (row.get("toolSequence") or "").split(">"):
            if tool:
                counts[group][tool] += 1
    out = []
    for group in sorted(runs):
        for tool, calls in sorted(counts[group].items(), key=lambda kv: -kv[1]):
            out.append({"strategy": group[0], "metrics": group[1], "tool": tool, "calls": calls,
                        "runs": runs[group], "calls_per_run": calls / runs[group]})
    return out


def status_counts(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, Counter] = defaultdict(Counter)
    for row in rows:
        group = groups[(row.get("strategy"), row.get("metrics"))]
        group[row.get("status")] += 1
        if row.get("snapshotMatches") is False:
            group["snapshot_mismatch"] += 1
        if row.get("tokenUsageComplete") is False and row.get("status") == "ok":
            group["tokens_unavailable"] += 1
        if row.get("judge_status") == "judge_error":
            group["judge_error"] += 1
    return [{"strategy": s, "metrics": m, **dict(c)} for (s, m), c in sorted(groups.items(), key=lambda kv: str(kv[0]))]


def quality_key(rows: list[dict]) -> str:
    if any(r.get(PRIMARY_QUALITY) is not None for r in rows):
        return PRIMARY_QUALITY
    return FALLBACK_QUALITY


def score_experiment(out_dir: Path, benchmark: Benchmark, require_snapshot: bool = True,
                     routing_quality: str | None = None, seed: int = 0) -> dict:
    rows = build_rows(out_dir, benchmark, require_snapshot)
    return write_scores(out_dir / "scores", rows, routing_quality, seed)


def combine_experiments(sources: list[Path], out_dir: Path, routing_quality: str | None = None, seed: int = 0) -> dict:
    rows = []
    for source in sources:
        scored = read_csv(source / "scores" / "rows.csv")
        if not scored:
            raise FileNotFoundError(f"{source / 'scores' / 'rows.csv'} is missing; run score first")
        rows += [{"experiment": source.name, **row} for row in scored]
    duplicates = [k for k, n in Counter(r.get("runKey", "").split("|", 1)[-1] for r in rows).items() if n > 1]
    if duplicates:
        raise ValueError(f"the experiments share runs, e.g. {duplicates[0]}")
    return write_scores(out_dir / "scores", rows, routing_quality, seed)


def write_scores(scores: Path, rows: list[dict], routing_quality: str | None = None, seed: int = 0) -> dict:
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    write_csv(scores / "rows.csv", rows)
    write_csv(scores / "status_counts.csv", status_counts(rows))
    write_csv(scores / "summary_by_strategy.csv", summarize(rows, SUMMARY_COLUMNS, ("strategy", "metrics"), seed))
    write_csv(scores / "summary_by_category.csv",
              summarize(rows, SUMMARY_COLUMNS, ("strategy", "metrics", "category"), seed))
    write_csv(scores / "tool_usage.csv", tool_usage(rows))

    variants = {r.get("metrics") for r in ok_rows}
    if {"default", "off"} <= variants:
        ablation = []
        for metric in ABLATION_COLUMNS:
            ablation += paired_differences(ok_rows, metric, "metrics", "default", "off", ("strategy",), seed)
        write_csv(scores / "ablation.csv", ablation)

    impact_rows = [r for r in ok_rows if "impact_valid" in r]
    if impact_rows:
        write_csv(scores / "impact.csv", impact_rows,
                  ["runKey", "questionId", "strategy", "metrics", "repetition", "impact_valid", "impact_snapshot"]
                  + [c for c in impact_rows[0] if c.startswith("impact_") and c not in ("impact_valid", "impact_snapshot")])

    key = routing_quality or quality_key(rows)
    per_question, routing_summary = routing_analysis(ok_rows, key)
    if per_question:
        write_csv(scores / "routing_questions.csv", per_question)
    with open(scores / "routing_summary.json", "w", encoding="utf-8") as handle:
        json.dump(routing_summary, handle, ensure_ascii=False, indent=2)
    result = {"rows": len(rows), "ok": len(ok_rows), "qualityKey": key, "routing": routing_summary}

    if key != COMPOSITE_QUALITY and any(r.get(COMPOSITE_QUALITY) is not None for r in ok_rows):
        composite_questions, composite_summary = routing_analysis(ok_rows, COMPOSITE_QUALITY)
        if composite_questions:
            write_csv(scores / "routing_questions_composite.csv", composite_questions)
        with open(scores / "routing_summary_composite.json", "w", encoding="utf-8") as handle:
            json.dump(composite_summary, handle, ensure_ascii=False, indent=2)
        result["routingComposite"] = composite_summary
    return result
