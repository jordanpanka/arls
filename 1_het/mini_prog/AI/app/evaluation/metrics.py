from collections import defaultdict
from statistics import mean

from app.services.evidence_service import normalize_path, short_symbol_name


def _path_match(expected: str, actual: str | None) -> bool:
    if not actual:
        return False
    expected_n = normalize_path(expected).lower()
    actual_n = normalize_path(actual).lower()
    return actual_n == expected_n or actual_n.endswith("/" + expected_n) or expected_n.endswith("/" + actual_n)


def _symbol_match(expected: str, actual: str | None) -> bool:
    if not actual:
        return False
    return short_symbol_name(expected).lower() == short_symbol_name(actual).lower()


def ranked_keys(retrieved: list[dict]) -> list[dict]:
    seen = set()
    ranked = []
    for item in retrieved:
        key = (normalize_path(item.get("path")), item.get("symbol"))
        if key in seen or not key[0]:
            continue
        seen.add(key)
        ranked.append({"path": key[0], "symbol": key[1]})
    return ranked


def _relevant_items(expected_files: list[str], expected_symbols: list[str]) -> list[tuple[str, str]]:
    return [("file", f) for f in expected_files] + [("symbol", s) for s in expected_symbols]


def _hit(target: tuple[str, str], item: dict) -> bool:
    kind, value = target
    return _path_match(value, item.get("path")) if kind == "file" else _symbol_match(value, item.get("symbol"))


def retrieval_scores(retrieved: list[dict], expected_files: list[str], expected_symbols: list[str], k: int = 5) -> dict:
    targets = _relevant_items(expected_files or [], expected_symbols or [])
    ranked = ranked_keys(retrieved)
    if not targets:
        return {"evaluated": False, "retrievedCount": len(ranked)}

    found = [t for t in targets if any(_hit(t, item) for item in ranked)]
    found_at_k = [t for t in targets if any(_hit(t, item) for item in ranked[:k])]
    relevant_items = [item for item in ranked if any(_hit(t, item) for t in targets)]

    reciprocal = 0.0
    for index, item in enumerate(ranked, start=1):
        if any(_hit(t, item) for t in targets):
            reciprocal = 1 / index
            break

    return {
        "evaluated": True,
        "retrievedCount": len(ranked),
        "evidenceRecall": round(len(found) / len(targets), 3),
        "evidencePrecision": round(len(relevant_items) / len(ranked), 3) if ranked else 0.0,
        f"recall@{k}": round(len(found_at_k) / len(targets), 3),
        "mrr": round(reciprocal, 3),
    }


def answer_scores(record: dict, expected_answer_terms: list[str] | None = None) -> dict:
    scores: dict = {}
    verification = record.get("verification") or {}
    if verification:
        scores["unsupportedClaimRate"] = verification.get("unsupportedRate")
        checked = verification.get("claims_checked") or 0
        scores["groundedRatio"] = round((verification.get("claims_supported") or 0) / checked, 3) if checked else None
    answer = (record.get("answer") or "").lower()
    if expected_answer_terms:
        hits = [t for t in expected_answer_terms if t.lower() in answer]
        scores["answerTermCoverage"] = round(len(hits) / len(expected_answer_terms), 3)
    return scores


def efficiency(record: dict) -> dict:
    return {
        "latencyMs": record.get("latencyMs"),
        "retrievalLatencyMs": record.get("retrievalLatencyMs"),
        "toolCalls": record.get("toolCalls", 0),
        "iterations": record.get("iterations", 0),
        "llmCalls": record.get("llmCalls"),
        "inputTokens": record.get("inputTokens"),
        "outputTokens": record.get("outputTokens"),
        "estimatedCost": record.get("estimatedCost"),
    }


def behaviour(record: dict) -> dict:
    return {
        "stopReason": record.get("stopReason"),
        "status": record.get("status"),
        "toolsUsed": ",".join(record.get("toolsUsed") or []),
        "toolSequence": ">".join(e.get("tool", "") for e in record.get("toolLog") or []),
        "failedCalls": record.get("failedCalls"),
        "duplicateCallsSkipped": record.get("duplicateCallsSkipped"),
        "replans": record.get("replans"),
        "plannerFallbacks": record.get("plannerFallbacks"),
        "sufficient": (record.get("sufficiency") or {}).get("sufficient"),
        "coverage": (record.get("sufficiency") or {}).get("effective_coverage"),
    }


def score_run(record: dict, question: dict, k: int = 5) -> dict:
    route = record.get("route") or {}
    row = {
        "questionId": question.get("id"),
        "mode": route.get("requested") or record.get("strategy"),
        "ablation": record.get("ablation"),
        "runId": record.get("runId"),
    }
    if route:
        row["routedTo"] = route.get("chosen")
        row["routeReason"] = route.get("reason")
        row["routingMs"] = route.get("routingMs")
        row["escalatedTo"] = route.get("escalatedTo")
        row["escalationReason"] = route.get("escalationReason")
        if question.get("expected_route"):
            row["routeCorrect"] = int(route.get("chosen") == question["expected_route"])
    row.update(retrieval_scores(
        record.get("retrievedEvidence") or [],
        question.get("expected_files") or [],
        question.get("expected_symbols") or [],
        k,
    ))
    row.update(answer_scores(record, question.get("expected_answer_terms")))
    row.update(efficiency(record))
    row.update(behaviour(record))
    return row


def aggregate(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row.get("mode"), row.get("ablation"))].append(row)

    summary = []
    for (mode, ablation), items in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        entry = {"mode": mode, "ablation": ablation, "runs": len(items)}
        numeric = {key for row in items for key, value in row.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
        for key in sorted(numeric):
            values = [row[key] for row in items if isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool)]
            if values:
                entry[f"mean_{key}"] = round(mean(values), 4)
        stops = defaultdict(int)
        for row in items:
            stops[row.get("stopReason")] += 1
        entry["stopReasons"] = dict(stops)
        summary.append(entry)
    return summary
