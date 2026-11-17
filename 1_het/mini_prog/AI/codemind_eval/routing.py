from collections import Counter, defaultdict
from statistics import mean, median

from codemind_eval.stats import is_number

FIXED = ("vector_rag", "selective_rag", "hybrid_rag", "evidence_aware_agentic_rag")
ROUTER_CHOICES = ("selective_rag", "evidence_aware_agentic_rag")
ADAPTIVE = "adaptive_rag"
BASELINE = "evidence_aware_agentic_rag"
EPSILON = 1e-9
TIE_TOLERANCE = 0.12


def _mean_or_none(values: list) -> float | None:
    numbers = [v for v in values if is_number(v)]
    return mean(numbers) if numbers else None


def per_question_strategy(rows: list[dict], quality_key: str, metrics: str = "default") -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("status") == "ok" and row.get("metrics") == metrics:
            grouped[row["questionId"]][row["strategy"]].append(row)
    table: dict[str, dict[str, dict]] = {}
    for question, strategies in grouped.items():
        table[question] = {}
        for strategy, items in strategies.items():
            choices = Counter(r.get("effectiveStrategy") for r in items if r.get("effectiveStrategy"))
            table[question][strategy] = {
                "quality": _mean_or_none([r.get(quality_key) for r in items]),
                "tokens": _mean_or_none([r.get("totalTokens") for r in items]),
                "latency": _mean_or_none([r.get("latencyTotalMs") for r in items]),
                "routingMs": _mean_or_none([r.get("latencyRoutingMs") for r in items]),
                "effective": choices.most_common(1)[0][0] if choices else None,
                "selected": Counter(r.get("selectedStrategy") for r in items).most_common(1)[0][0],
                "escalated": _mean_or_none([float(bool(r.get("escalated"))) for r in items]),
            }
    return table


def _sort_key(entry: tuple[str, dict]) -> tuple:
    _, stats = entry
    tokens = stats["tokens"] if stats["tokens"] is not None else float("inf")
    latency = stats["latency"] if stats["latency"] is not None else float("inf")
    return -stats["quality"], tokens, latency


def oracle(results: dict[str, dict], candidates: tuple[str, ...],
           tolerance: float = EPSILON) -> tuple[str | None, list[str], float | None]:
    scored = [(s, results[s]) for s in candidates if s in results and results[s]["quality"] is not None]
    if not scored:
        return None, [], None
    best = max(stats["quality"] for _, stats in scored)
    optimal = [s for s, stats in scored if stats["quality"] >= best - tolerance]
    pick = sorted([(s, stats) for s, stats in scored if s in optimal], key=_sort_key)[0][0]
    return pick, optimal, best


def better_choice(results: dict[str, dict], tolerance: float = TIE_TOLERANCE) -> str:
    selective, agent = ROUTER_CHOICES
    diff = results[agent]["quality"] - results[selective]["quality"]
    return "agent" if diff > tolerance else "selective" if diff < -tolerance else "tie"


def _cheaper(results: dict[str, dict]) -> str | None:
    selective, agent = ROUTER_CHOICES
    tokens = {s: results[s]["tokens"] for s in ROUTER_CHOICES}
    if None in tokens.values():
        return None
    if tokens[selective] != tokens[agent]:
        return min(tokens, key=tokens.get)
    latency = {s: results[s]["latency"] for s in ROUTER_CHOICES}
    if None in latency.values():
        return None
    return min(latency, key=latency.get)


def decision_correctness(rows: list[dict], quality_key: str, tolerance: float = TIE_TOLERANCE,
                         metrics: str = "default") -> list[dict]:
    table = per_question_strategy(rows, quality_key, metrics)
    adaptive_runs: dict[str, list[dict]] = defaultdict(list)
    meta: dict[str, dict] = {}
    for row in rows:
        if row.get("metrics") != metrics:
            continue
        info = meta.setdefault(row["questionId"], {"category": None, "experiment": None})
        for key in info:
            info[key] = info[key] or row.get(key)
        if row.get("strategy") == ADAPTIVE and row.get("status") == "ok":
            adaptive_runs[row["questionId"]].append(row)
    selective, agent = ROUTER_CHOICES
    decisions = []
    for question in sorted(adaptive_runs):
        runs = adaptive_runs[question]
        results = table.get(question, {})
        selected = Counter(r.get("selectedStrategy") for r in runs).most_common(1)[0][0]
        effective = Counter(r.get("effectiveStrategy") for r in runs).most_common(1)[0][0]
        entry = {
            "questionId": question,
            **meta[question],
            "adaptiveRuns": len(runs),
            "routerSelected": selected,
            "selectedAgentShare": sum(r.get("selectedStrategy") == agent for r in runs) / len(runs),
            "selectedConsistent": int(len({r.get("selectedStrategy") for r in runs}) == 1),
            "escalationRate": sum(bool(r.get("escalated")) for r in runs) / len(runs),
            "routerEffective": effective,
            "selectiveQuality": (results.get(selective) or {}).get("quality"),
            "agentQuality": (results.get(agent) or {}).get("quality"),
            "selectiveTokens": (results.get(selective) or {}).get("tokens"),
            "agentTokens": (results.get(agent) or {}).get("tokens"),
            "qualityDiff": None, "better": None, "cheaper": None, "correctChoice": None,
            "selectedCorrect": None, "effectiveCorrect": None, "effectiveOutcome": None,
            "effectiveQualityLoss": None, "effectiveExtraTokens": None, "effectiveExtraLatencyMs": None,
            "effectiveTokenRatio": None,
        }
        if any(s not in results for s in ROUTER_CHOICES):
            entry["status"] = "missing_strategy_runs"
        elif entry["selectiveQuality"] is None or entry["agentQuality"] is None:
            entry["status"] = "missing_quality"
        elif (cheaper := _cheaper(results)) is None:
            entry["status"] = "missing_cost"
        else:
            better = better_choice(results, tolerance)
            correct = cheaper if better == "tie" else selective if better == "selective" else agent
            entry.update({
                "status": "evaluated",
                "qualityDiff": entry["agentQuality"] - entry["selectiveQuality"],
                "better": better,
                "cheaper": cheaper,
                "correctChoice": correct,
                "selectedCorrect": int(selected == correct),
                "effectiveCorrect": int(effective == correct),
            })
            if effective in ROUTER_CHOICES:
                chosen, best = results[effective], results[correct]
                latency = (chosen["latency"] - best["latency"]
                           if chosen["latency"] is not None and best["latency"] is not None else None)
                entry.update({
                    "effectiveOutcome": "optimal" if effective == correct else "wasted_agent" if better == "tie"
                    else f"quality_loss_{'agent' if effective == agent else 'selective'}",
                    "effectiveQualityLoss": best["quality"] - chosen["quality"],
                    "effectiveExtraTokens": chosen["tokens"] - best["tokens"],
                    "effectiveExtraLatencyMs": latency,
                    "effectiveTokenRatio": chosen["tokens"] / best["tokens"] if best["tokens"] else None,
                })
        decisions.append(entry)
    return decisions


def summarize_decisions(decisions: list[dict], group: str | None = None) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        groups[d.get(group) if group else "all"].append(d)
    summary = []
    for key, items in groups.items():
        evaluated = [d for d in items if d["status"] == "evaluated"]
        n = len(evaluated)
        summary.append({
            "group": group or "all",
            "value": key,
            "questions": len(items),
            "evaluated": n,
            "notEvaluated": len(items) - n,
            "selectedSelective": sum(d["routerSelected"] == ROUTER_CHOICES[0] for d in items),
            "selectedAgent": sum(d["routerSelected"] == ROUTER_CHOICES[1] for d in items),
            "selectedCorrect": sum(d["selectedCorrect"] for d in evaluated),
            "selectedAccuracy": sum(d["selectedCorrect"] for d in evaluated) / n if n else None,
            "effectiveCorrect": sum(d["effectiveCorrect"] for d in evaluated),
            "effectiveAccuracy": sum(d["effectiveCorrect"] for d in evaluated) / n if n else None,
            "correctIsSelective": sum(d["correctChoice"] == ROUTER_CHOICES[0] for d in evaluated),
            "correctIsAgent": sum(d["correctChoice"] == ROUTER_CHOICES[1] for d in evaluated),
            "ties": sum(d["better"] == "tie" for d in evaluated),
            "alwaysSelectiveAccuracy": sum(d["correctChoice"] == ROUTER_CHOICES[0] for d in evaluated) / n if n else None,
            "alwaysAgentAccuracy": sum(d["correctChoice"] == ROUTER_CHOICES[1] for d in evaluated) / n if n else None,
            "escalatedQuestions": sum(d["escalationRate"] > 0 for d in items),
            "inconsistentQuestions": sum(1 - d["selectedConsistent"] for d in items),
        })
    return summary


NON_OPTIMAL_OUTCOMES = ("wasted_agent", "quality_loss_agent", "quality_loss_selective")


def summarize_non_optimal(decisions: list[dict]) -> list[dict]:
    evaluated = [d for d in decisions if d["effectiveOutcome"] is not None]
    summary = []
    for outcome in ("optimal", *NON_OPTIMAL_OUTCOMES):
        items = [d for d in evaluated if d["effectiveOutcome"] == outcome]
        if not items:
            continue
        losses = [d["effectiveQualityLoss"] for d in items]
        tokens = [d["effectiveExtraTokens"] for d in items]
        latency = [d["effectiveExtraLatencyMs"] for d in items if d["effectiveExtraLatencyMs"] is not None]
        ratios = [d["effectiveTokenRatio"] for d in items if d["effectiveTokenRatio"] is not None]
        summary.append({
            "outcome": outcome,
            "questions": len(items),
            "share": len(items) / len(evaluated),
            "qualityLossMean": mean(losses), "qualityLossMedian": median(losses),
            "qualityLossMax": max(losses),
            "qualityLossJudgePointsMean": mean(losses) * 3,
            "extraTokensMean": mean(tokens), "extraTokensMedian": median(tokens),
            "extraTokensTotal": sum(tokens),
            "extraLatencyMsMean": mean(latency) if latency else None,
            "extraLatencyMsMedian": median(latency) if latency else None,
            "tokenRatioMedian": median(ratios) if ratios else None,
        })
    return summary


def routing_analysis(rows: list[dict], quality_key: str, metrics: str = "default") -> tuple[list[dict], dict]:
    table = per_question_strategy(rows, quality_key, metrics)
    per_question = []
    for question, results in sorted(table.items()):
        adaptive = results.get(ADAPTIVE)
        if adaptive is None:
            continue
        pick, optimal, best = oracle(results, FIXED)
        r_pick, r_optimal, r_best = oracle(results, ROUTER_CHOICES)
        _, tie_optimal, _ = oracle(results, FIXED, TIE_TOLERANCE)
        _, r_tie_optimal, _ = oracle(results, ROUTER_CHOICES, TIE_TOLERANCE)
        if pick is None:
            continue
        effective = adaptive["effective"]
        baseline = results.get(BASELINE) or {}
        complete = all(s in results for s in FIXED)
        per_question.append({
            "questionId": question,
            "complete": complete,
            "routerSelected": adaptive["selected"],
            "routerEffective": effective,
            "escalationRate": adaptive["escalated"],
            "routingMs": adaptive["routingMs"],
            "oracle": pick,
            "oracleSet": "|".join(optimal),
            "oracleQuality": best,
            "restrictedOracle": r_pick,
            "restrictedOracleSet": "|".join(r_optimal),
            "adaptiveQuality": adaptive["quality"],
            "agreement": int(effective in optimal) if effective else None,
            "restrictedAgreement": int(effective in r_optimal) if effective and r_optimal else None,
            "toleranceAgreement": int(effective in tie_optimal) if effective else None,
            "restrictedToleranceAgreement": int(effective in r_tie_optimal) if effective and r_tie_optimal else None,
            "regret": best - adaptive["quality"] if adaptive["quality"] is not None else None,
            "restrictedRegret": r_best - adaptive["quality"] if adaptive["quality"] is not None and r_best is not None else None,
            "adaptiveTokens": adaptive["tokens"],
            "baselineTokens": baseline.get("tokens"),
            "oracleTokens": results[pick]["tokens"],
            "tokenSavings": baseline["tokens"] - adaptive["tokens"]
            if baseline.get("tokens") is not None and adaptive["tokens"] is not None else None,
            "adaptiveLatencyMs": adaptive["latency"],
            "baselineLatencyMs": baseline.get("latency"),
            "latencySavingsMs": baseline["latency"] - adaptive["latency"]
            if baseline.get("latency") is not None and adaptive["latency"] is not None else None,
        })
    return per_question, summarize_routing(per_question, rows, quality_key, metrics)


def summarize_routing(per_question: list[dict], rows: list[dict], quality_key: str, metrics: str) -> dict:
    adaptive_rows = [r for r in rows if r.get("strategy") == ADAPTIVE and r.get("status") == "ok" and r.get("metrics") == metrics]
    routing_ms = [r.get("latencyRoutingMs") for r in adaptive_rows if is_number(r.get("latencyRoutingMs"))]
    token_rows = [q for q in per_question if q["adaptiveTokens"] is not None and q["baselineTokens"] is not None]
    latency_rows = [q for q in per_question if q["adaptiveLatencyMs"] is not None and q["baselineLatencyMs"] is not None]
    base_tokens = sum(q["baselineTokens"] for q in token_rows)
    base_latency = sum(q["baselineLatencyMs"] for q in latency_rows)
    return {
        "qualityKey": quality_key,
        "metricsVariant": metrics,
        "questions": len(per_question),
        "completeQuestions": sum(1 for q in per_question if q["complete"]),
        "adaptiveRuns": len(adaptive_rows),
        "selectedDistribution": dict(Counter(r.get("selectedStrategy") for r in adaptive_rows)),
        "effectiveDistribution": dict(Counter(r.get("effectiveStrategy") for r in adaptive_rows)),
        "escalationRate": mean([float(bool(r.get("escalated"))) for r in adaptive_rows]) if adaptive_rows else None,
        "routeReasons": dict(Counter(r.get("routeReason") or (r.get("route") or {}).get("reason") for r in adaptive_rows)),
        "escalationReasons": dict(Counter(r.get("escalationReason") or (r.get("route") or {}).get("escalationReason")
                                          for r in adaptive_rows if r.get("escalated"))),
        "routingMsMean": mean(routing_ms) if routing_ms else None,
        "routingMsMedian": median(routing_ms) if routing_ms else None,
        "oracleDistribution": dict(Counter(q["oracle"] for q in per_question)),
        "oracleAgreement": _mean_or_none([q["agreement"] for q in per_question]),
        "restrictedOracleAgreement": _mean_or_none([q["restrictedAgreement"] for q in per_question]),
        "tieTolerance": TIE_TOLERANCE,
        "toleranceOracleAgreement": _mean_or_none([q["toleranceAgreement"] for q in per_question]),
        "restrictedToleranceOracleAgreement": _mean_or_none([q["restrictedToleranceAgreement"] for q in per_question]),
        "meanRegret": _mean_or_none([q["regret"] for q in per_question]),
        "meanRestrictedRegret": _mean_or_none([q["restrictedRegret"] for q in per_question]),
        "tokenSavingsTotal": sum(q["tokenSavings"] for q in token_rows) if token_rows else None,
        "tokenSavingsRelative": sum(q["tokenSavings"] for q in token_rows) / base_tokens if base_tokens else None,
        "tokenSavingsQuestions": len(token_rows),
        "latencySavingsMsMean": mean(q["latencySavingsMs"] for q in latency_rows) if latency_rows else None,
        "latencySavingsRelative": sum(q["latencySavingsMs"] for q in latency_rows) / base_latency if base_latency else None,
        "latencySavingsQuestions": len(latency_rows),
    }
