from dataclasses import replace

import pytest

from app.agents.config import SufficiencyThresholds
from app.agents.requirements import analyze_question, extract_targets
from app.evidence.schemas import Evidence, GraphRelation, MetricMeasurement, MetricValue
from app.evidence.sufficiency import evaluate_sufficiency, parse_llm_hints

ALL_TOOLS = {
    "find_symbol", "read_code", "semantic_code_search", "keyword_code_search", "get_callers", "get_callees",
    "trace_dependencies", "find_call_path", "get_related_symbols", "get_code_metrics", "find_quality_hotspots",
    "get_module_quality_summary",
}
SNAP = "commit:1"


def kinds(analysis):
    return [(r.kind, r.target) for r in analysis.requirements]


def test_simple_comprehension_question_needs_only_definition():
    analysis = analyze_question("What does the validate_input function do?")
    assert analysis.targets == ["validate_input"]
    assert kinds(analysis) == [("symbol_resolved", "validate_input"), ("definition_code", "validate_input")]
    assert analysis.complexity == "simple"


def test_dependency_question():
    analysis = analyze_question("Which modules depend on the AuthenticationService?")
    assert ("dependency_relations", "AuthenticationService") in kinds(analysis)
    assert not any(k in ("metrics", "hotspots") for k, _ in kinds(analysis))


def test_maintainability_question_needs_hotspots():
    analysis = analyze_question("Which functions are the most difficult to maintain?")
    assert kinds(analysis) == [("hotspots", "maintainability")]


def test_complex_multi_source_question():
    analysis = analyze_question("Which highly complex functions are also critical dependencies for other modules?")
    found = kinds(analysis)
    assert ("hotspots", "complexity") in found
    assert ("dependency_relations", None) in found
    assert analysis.complexity in ("moderate", "complex")


def test_change_impact_question():
    analysis = analyze_question("What would be affected if processPayment were modified?")
    assert ("impact_relations", "processPayment") in kinds(analysis)
    assert ("symbol_resolved", "processPayment") in kinds(analysis)


def test_hungarian_question_uses_both_languages():
    analysis = analyze_question("Mit csinál a validate_input függvény?", "What does the validate_input function do?")
    assert ("definition_code", "validate_input") in kinds(analysis)
    impact = analyze_question("Mit érintene, ha módosítanám a processPayment függvényt?")
    assert ("impact_relations", "processPayment") in kinds(impact)


def test_identifier_extraction():
    targets, files = extract_targets("Does `PaymentService.process` call charge_card() in src/pay/service.py, e.g. retries?")
    assert "PaymentService.process" in targets
    assert "charge_card" in targets
    assert files == ["src/pay/service.py"]
    assert "e.g" not in targets


def symbol(name="PaymentService", path="src/payment.py", start=1, end=50, kind="class"):
    return Evidence(source_type="symbol", repository_snapshot=SNAP, file_path=path, start_line=start, end_line=end,
                    symbol_name=name, symbol_kind=kind, symbol_id=f"{path}::{kind}::{name}@{start}", produced_by=["find_symbol"])


def caller_relation(source="checkout", target="PaymentService"):
    return Evidence(
        source_type="graph_relation", repository_snapshot=SNAP, file_path="src/api.py", start_line=5,
        produced_by=["get_callers"], certainty="direct",
        relation=GraphRelation(source=f"src/api.py::function::{source}@5", target=f"src/payment.py::class::{target}@1",
                               type="CALLS", source_label=source, target_label=target, source_path="src/api.py", source_line=5),
    )


def complexity(symbol_name="checkout", value=12, analysis=7):
    return Evidence(
        source_type="metric", repository_snapshot=SNAP, file_path="src/api.py", start_line=5, produced_by=["get_code_metrics"],
        metric=MetricMeasurement(scope="function", title=f"{symbol_name}()", symbol=symbol_name, analysis_id=analysis,
                                 items=[MetricValue(key="cyclomaticComplexity", label="CC", value=value)]),
    )


QUESTION = "Which modules depend on PaymentService, and which have high complexity?"


def evaluate(evidence, tool_log=None, tools=ALL_TOOLS, thresholds=None, progress=True, budget=True):
    return evaluate_sufficiency(
        analyze_question(QUESTION), evidence, tool_log or [], SNAP,
        thresholds or SufficiencyThresholds(), tools, budget_left=budget, made_progress=progress,
    )


def test_dependencies_without_metrics_are_insufficient_and_name_the_gap():
    result = evaluate([symbol(), caller_relation()])
    assert not result.sufficient
    assert result.should_continue
    assert result.missing == ["metrics:*"]
    assert "symbol_resolved:PaymentService" in result.satisfied
    assert "dependency_relations:PaymentService" in result.satisfied


def test_full_multi_source_evidence_is_sufficient():
    result = evaluate([symbol(), caller_relation(), complexity()])
    assert result.sufficient
    assert not result.should_continue
    assert result.coverage == 1.0
    assert result.traceability == 1.0


def test_unavailable_metrics_stop_retrieval_and_are_reported():
    log = [{"tool": "get_code_metrics", "args": {}, "error": {"kind": "unavailable", "message": "no analysis"}}]
    result = evaluate([symbol(), caller_relation()], tool_log=log)
    assert result.unavailable == ["metrics:*"]
    assert result.sufficient
    assert "unavailable: metrics:*" in result.reason


def test_disabled_metrics_tools_make_the_requirement_unavailable():
    result = evaluate([symbol(), caller_relation()], tools=ALL_TOOLS - {"get_code_metrics", "find_quality_hotspots", "get_module_quality_summary"})
    assert result.unavailable == ["metrics:*"]


def test_no_progress_or_no_budget_stops_the_loop():
    assert not evaluate([symbol()], progress=False).should_continue
    stopped = evaluate([symbol()], budget=False)
    assert not stopped.should_continue
    assert stopped.reason.startswith("budget exhausted")


def test_inconsistent_metrics_are_detected():
    result = evaluate([symbol(), caller_relation(), complexity(value=12), complexity(value=30, analysis=8)])
    assert not result.consistent
    assert not result.sufficient
    assert any("conflicting" in issue for issue in result.consistency_issues)


def test_irrelevant_evidence_lowers_relevance():
    noise = [
        Evidence(source_type="code_chunk", repository_snapshot=SNAP, file_path=f"src/noise{i}.py", start_line=1,
                 symbol_name=f"noise{i}", retrieval_score=0.2, produced_by=["semantic_code_search"])
        for i in range(6)
    ]
    result = evaluate([symbol(), caller_relation(), complexity()] + noise)
    assert result.relevance < 0.5
    assert not result.sufficient


def test_thresholds_are_configurable():
    lenient = replace(SufficiencyThresholds(), min_coverage=0.5)
    assert evaluate([symbol(), caller_relation()], thresholds=lenient).sufficient


def test_symbol_not_found_after_search_is_unavailable():
    analysis = analyze_question("What does ghostFunction do?")
    log = [
        {"tool": "find_symbol", "args": {"name": "ghostFunction"}, "error": {"kind": "not_found", "message": "-"}},
        {"tool": "semantic_code_search", "args": {"query": "ghostFunction"}, "error": None},
    ]
    result = evaluate_sufficiency(analysis, [], log, SNAP, SufficiencyThresholds(), ALL_TOOLS, True, True)
    assert "symbol_resolved:ghostFunction" in result.unavailable
    assert not result.sufficient


@pytest.mark.parametrize("raw,expected", [
    ('{"missing": ["callers of X"]}', ["callers of X"]),
    ("no json", []),
    ('{"missing": "x"}', []),
])
def test_llm_hints_are_parsed_defensively(raw, expected):
    assert parse_llm_hints(raw) == expected
