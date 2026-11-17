from app.tools.registry import ALL_TOOLS

RUN_SCHEMA = "codemind-eval-run/1"
VECTOR_TOOL_CATEGORIES = {"retrieval"}
GRAPH_TOOL_CATEGORIES = {"graph"}


def _tool_categories() -> dict[str, str]:
    return {spec.name: spec.category for spec in ALL_TOOLS}


def run_key(experiment_id: str, question_id: str, strategy: str, metrics: str, repetition: int) -> str:
    return f"{experiment_id}|{question_id}|{strategy}|{metrics}|{repetition}"


def _sum_optional(values: list) -> float | None:
    if not values or any(v is None for v in values):
        return None
    return sum(values)


def _tool_time(tool_log: list[dict], categories: set[str]) -> float | None:
    names = _tool_categories()
    values = [e.get("latencyMs") for e in tool_log if names.get(e.get("tool")) in categories]
    if not values:
        return 0.0 if tool_log is not None else None
    return round(sum(v or 0 for v in values), 1)


def _pick(records: list[dict], kind: str) -> dict | None:
    matches = [r for r in records if r.get("kind") == kind]
    return matches[-1] if matches else None


def _tokens(pipeline: dict | None, agent: dict | None, route: dict) -> tuple[int | None, int | None, bool]:
    parts = [r for r in (pipeline, agent) if r is not None]
    if not parts:
        return None, None, False
    inputs = [r.get("inputTokens") for r in parts]
    outputs = [r.get("outputTokens") for r in parts]
    complete = all(r.get("tokenUsageComplete") is True for r in parts)
    total_in = _sum_optional(inputs)
    total_out = _sum_optional(outputs)
    if pipeline is not None and agent is not None:
        routing_in = route.get("routingInputTokens")
        routing_out = route.get("routingOutputTokens")
        total_in = None if total_in is None or routing_in is None else total_in - routing_in
        total_out = None if total_out is None or routing_out is None else total_out - routing_out
    return total_in, total_out, complete and total_in is not None and total_out is not None


def normalize_execution(records: list[dict], wall_ms: float | None, response=None) -> dict:
    pipeline = _pick(records, "legacy_run")
    agent = _pick(records, "agent_run")
    final = agent or pipeline or {}
    route = final.get("route") or (pipeline or {}).get("route") or {}
    tool_log = (agent or {}).get("toolLog") if agent else None

    input_tokens, output_tokens, complete = _tokens(pipeline, agent, route)
    effective = route.get("escalatedTo") or route.get("chosen") or final.get("strategy")

    if agent is not None:
        vector_ms = _tool_time(tool_log or [], VECTOR_TOOL_CATEGORIES)
        graph_ms = _tool_time(tool_log or [], GRAPH_TOOL_CATEGORIES)
    else:
        vector_ms = (pipeline or {}).get("vectorLatencyMs")
        graph_ms = (pipeline or {}).get("graphLatencyMs")

    answer = final.get("answer")
    if answer is None and response is not None:
        answer = response.answer

    return {
        "selectedStrategy": route.get("chosen") or final.get("strategy"),
        "effectiveStrategy": effective,
        "escalated": bool(route.get("escalatedTo")),
        "route": route or None,
        "repositorySnapshot": (agent or {}).get("repositorySnapshot"),
        "responseStatus": final.get("status") or (getattr(response, "status", None) if response else None),
        "stopReason": (agent or {}).get("stopReason"),
        "answer": answer,
        "retrievedEvidence": final.get("retrievedEvidence"),
        "contextEvidence": final.get("contextEvidence"),
        "contextText": final.get("contextText"),
        "citedAliases": final.get("citedAliases"),
        "toolCalls": (agent or {}).get("toolCalls", 0 if agent is None and pipeline is not None else None),
        "iterations": (agent or {}).get("iterations", 0 if agent is None and pipeline is not None else None),
        "toolsUsed": (agent or {}).get("toolsUsed") or [],
        "toolSequence": [e.get("tool") for e in tool_log or []],
        "failedToolCalls": (agent or {}).get("failedCalls"),
        "llmCalls": _sum_optional([r.get("llmCalls") for r in (pipeline, agent) if r is not None]),
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "tokenUsageComplete": complete,
        "latency": {
            "totalMs": wall_ms,
            "routingMs": route.get("routingMs"),
            "vectorMs": vector_ms,
            "graphMs": graph_ms,
            "retrievalMs": _sum_optional([r.get("retrievalLatencyMs") for r in (pipeline, agent) if r is not None]),
            "contextMs": _sum_optional([r.get("contextLatencyMs") for r in (pipeline, agent) if r is not None]),
            "generationMs": _sum_optional([r.get("generationLatencyMs") for r in (pipeline, agent) if r is not None]),
            "pipelineMs": route.get("pipelineMs"),
        },
        "verification": (agent or {}).get("verification"),
        "sufficiency": (agent or {}).get("sufficiency"),
        "traceKinds": [r.get("kind") for r in records],
    }
