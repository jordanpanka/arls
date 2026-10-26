import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.agents.requirements import QuestionAnalysis
from app.evidence.schemas import Evidence
from app.evidence.sufficiency import RequirementStatus, analog_evidence, analog_files, touches
from app.services.evidence_service import short_symbol_name
from app.tools.base import ToolSpec, call_signature


@dataclass
class PlannedCall:
    tool: str
    args: dict
    purpose: str
    signature: str


@dataclass
class PlanOutcome:
    calls: list[PlannedCall] = field(default_factory=list)
    done: bool = False
    rejected: list[dict] = field(default_factory=list)
    duplicates: int = 0
    fallback: bool = False
    reason: str = ""


def parse_plan(raw: str) -> tuple[list[dict], bool]:
    text = (raw or "").strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("planner returned no JSON object")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("planner JSON is not an object")
    calls = data.get("calls") or []
    if not isinstance(calls, list):
        raise ValueError("planner 'calls' is not a list")
    return [c for c in calls if isinstance(c, dict)], bool(data.get("done"))


def validate_calls(raw_calls: list[dict], registry: dict[str, ToolSpec], executed: set[str], limit: int) -> tuple[list[PlannedCall], list[dict], int]:
    accepted: list[PlannedCall] = []
    rejected: list[dict] = []
    duplicates = 0
    seen = set(executed)
    for raw in raw_calls:
        name = str(raw.get("tool") or "")
        spec = registry.get(name)
        if spec is None:
            rejected.append({"tool": name[:60], "error": "unknown or disabled tool"})
            continue
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        try:
            validated = spec.args_schema.model_validate(args)
        except ValidationError as e:
            rejected.append({"tool": name, "error": "; ".join(err["msg"] for err in e.errors()[:3])})
            continue
        signature = call_signature(name, validated)
        if signature in seen:
            duplicates += 1
            continue
        if len(accepted) >= limit:
            break
        seen.add(signature)
        accepted.append(PlannedCall(
            tool=name,
            args=validated.model_dump(exclude_none=True),
            purpose=str(raw.get("purpose") or "")[:160],
            signature=signature,
        ))
    return accepted, rejected, duplicates


def _resolved(target: str, evidence: list[Evidence]) -> list[Evidence]:
    return [e for e in evidence if e.source_type == "symbol" and touches(target, e)]


def _symbol_arg(target: str, evidence: list[Evidence]) -> str:
    resolved = _resolved(target, evidence)
    ids = {e.symbol_id for e in resolved if e.symbol_id}
    return next(iter(ids)) if len(ids) == 1 else target


def _is_type_target(target: str, evidence: list[Evidence], analysis: QuestionAnalysis) -> bool:
    kinds = {e.symbol_kind for e in _resolved(target, evidence)}
    return "class" in kinds or (not kinds and analysis.mentions_class)


def _attempted(tool_log: list[dict], tool: str, key: str, value: str) -> bool:
    return any(entry.get("tool") == tool and (entry.get("args") or {}).get(key) == value for entry in tool_log)


def pattern_call_args(analysis: QuestionAnalysis, statuses: list[RequirementStatus], evidence: list[Evidence], question_en: str) -> dict | None:
    paths = list(dict.fromkeys(analysis.files + analog_files(evidence)))[:6]
    symbols = [short_symbol_name(t) for t in analysis.targets[:3]]
    if not paths and not symbols and "change_planning" in analysis.intents:
        analog = next((s for s in statuses if s.kind == "analogous_feature"), None)
        if analog is not None and analog.status == "missing":
            return None
    args = {"change_request": question_en[:500]}
    if paths:
        args["paths"] = paths
    if symbols:
        args["symbols"] = symbols
    return args


def fallback_calls(
    analysis: QuestionAnalysis,
    statuses: list[RequirementStatus] | None,
    evidence: list[Evidence],
    tool_log: list[dict],
    question_en: str,
    max_read_lines: int,
) -> list[dict]:
    calls: list[dict] = []

    def add(tool: str, args: dict, purpose: str):
        calls.append({"tool": tool, "args": args, "purpose": purpose})

    if statuses is None:
        if not evidence and "change_planning" in analysis.intents:
            add("find_similar_implementations", {"description": question_en[:500]}, "find an existing feature to use as a template")
            add("find_extension_points", {"area": question_en[:300]}, "find where such features are wired in")
        elif not evidence:
            add("semantic_code_search", {"query": question_en[:400]}, "find relevant code")
            for target in analysis.targets[:2]:
                add("find_symbol", {"name": target}, f"locate {target}")
        if not evidence and "design_pattern" in analysis.intents and (analysis.targets or analysis.files):
            add("recommend_design_patterns", pattern_call_args(analysis, [], evidence, question_en), "design pattern analysis of the named code")
        return calls

    for status in statuses:
        if status.status != "missing":
            continue
        target = status.target
        kind = status.kind

        if kind == "symbol_resolved" and target:
            if _attempted(tool_log, "find_symbol", "name", target):
                add("semantic_code_search", {"query": target}, f"search for {target} semantically")
                add("keyword_code_search", {"pattern": short_symbol_name(target)}, f"search for {target} literally")
            else:
                add("find_symbol", {"name": target}, f"locate {target}")

        elif kind == "definition_code" and target:
            resolved = _resolved(target, evidence)
            if resolved:
                for location in resolved[:2]:
                    start = location.start_line or 1
                    end = location.end_line or start + 40
                    add("read_code", {
                        "path": location.file_path,
                        "start_line": start,
                        "end_line": min(end, start + max_read_lines - 1),
                    }, f"read {location.symbol_name}")
            else:
                add("find_symbol", {"name": target}, f"locate {target}")

        elif kind == "dependency_relations":
            if target:
                symbol = _symbol_arg(target, evidence)
                if _is_type_target(target, evidence, analysis):
                    add("find_type_usages", {"symbol": symbol}, f"where {target} is instantiated, held, passed or extended")
                add("get_callers", {"symbol": symbol}, f"who calls {target}")
                add("get_callees", {"symbol": symbol}, f"what {target} calls")
            else:
                hotspots = [e for e in evidence if e.metric is not None and e.metadata.get("hotspot") and e.metric.scope == "function"]
                for item in hotspots[:3]:
                    add("get_callers", {"symbol": item.metric.symbol}, f"dependents of hotspot {item.metric.symbol}")
                if not hotspots:
                    add("semantic_code_search", {"query": question_en[:400]}, "find the component in question")

        elif kind == "impact_relations":
            if target:
                symbol = _symbol_arg(target, evidence)
                if _is_type_target(target, evidence, analysis):
                    add("find_type_usages", {"symbol": symbol}, f"code that depends on the type {target}")
                add("get_callers", {"symbol": symbol, "depth": 2}, f"transitive callers of {target}")
                add("trace_dependencies", {"target": symbol, "direction": "incoming"}, f"files depending on {target}")
            else:
                add("semantic_code_search", {"query": question_en[:400]}, "find the component in question")

        elif kind == "call_path" and target and "->" in target:
            source, destination = target.split("->", 1)
            add("find_call_path", {"from_symbol": source, "to_symbol": destination}, "connect the two symbols")

        elif kind == "metrics":
            symbols = []
            for t in analysis.targets:
                symbols.append(_symbol_arg(t, evidence))
            for e in evidence:
                if e.relation is not None and e.relation.type == "CALLS":
                    for endpoint in (e.relation.source, e.relation.target):
                        if endpoint not in symbols:
                            symbols.append(endpoint)
            if symbols:
                add("get_code_metrics", {"symbols": symbols[:10]}, "measured metrics of the involved functions")
            else:
                add("find_quality_hotspots", {"focus": analysis.metrics_focus}, "measured metrics")

        elif kind == "hotspots":
            focus = target if target in ("complexity", "maintainability", "dependency", "size", "general") else "complexity"
            add("find_quality_hotspots", {"focus": focus}, f"{focus} ranking")

        elif kind == "file_context" and target:
            add("read_code", {"path": target, "start_line": 1, "end_line": max_read_lines}, f"read {target}")

        elif kind == "analogous_feature":
            add("find_similar_implementations", {"description": question_en[:500]}, "find an existing feature to use as a template")

        elif kind == "extension_point":
            add("find_extension_points", {"area": question_en[:300], "near_paths": analog_files(evidence)}, "find where such features are wired in")

        elif kind == "test_conventions":
            subjects = [_symbol_arg(t, evidence) for t in analysis.targets[:1]]
            analogs = analog_evidence(evidence)
            if not subjects and analogs:
                top = analogs[0]
                subjects = [top.symbol_name if top.symbol_name and top.symbol_kind == "class" else top.file_path]
            for subject in subjects:
                if subject:
                    add("find_tests_for", {"target": subject}, f"tests that cover {subject}")

        elif kind == "change_impact":
            for path in analog_files(evidence, limit=2):
                add("trace_dependencies", {"target": path, "direction": "incoming"}, f"code depending on {path}")

        elif kind == "change_risk":
            files = analog_files(evidence) + [p for p in analysis.files if p not in analog_files(evidence)]
            symbols = [_symbol_arg(t, evidence) for t in analysis.targets[:3]]
            if files or symbols:
                add("get_code_metrics", {"paths": files[:5], "symbols": symbols}, "complexity of the code the change touches")

        elif kind == "pattern_analysis":
            args = pattern_call_args(analysis, statuses, evidence, question_en)
            if args is not None:
                add("recommend_design_patterns", args, "decide between a minimal change and a design-pattern-based refactoring")

        elif kind == "semantic_context":
            add("semantic_code_search", {"query": question_en[:400]}, "find relevant code")
            for target in analysis.targets[:1]:
                add("keyword_code_search", {"pattern": short_symbol_name(target)}, f"literal search for {target}")

    return calls
