from dataclasses import replace

import pytest

from app.agents.config import AgentConfig, SufficiencyThresholds, config_for
from app.agents.graph import run_agent
from app.agents.planner import fallback_calls
from app.agents.requirements import analyze_question
from app.evidence.schemas import Evidence
from app.evidence.store import EvidenceStore
from app.evidence.sufficiency import evaluate_sufficiency
from app.evidence.verifier import verify_answer
from app.tools.base import execute_tool
from app.tools.change_tools import CHANGE_TOOLS, area_terms, is_test_path

from app.tests.agent_fakes import (
    SCOPE,
    SOURCES,
    FakeSource,
    FakeVectors,
    GraphLoader,
    ScriptedLLM,
    agent_deps,
    qdrant_hit,
    tool_context,
)

TOOLS = {spec.name: spec for spec in CHANGE_TOOLS}
CHANGE_SOURCES = {
    **SOURCES,
    "src/Program.cs": ["var builder = WebApplication.CreateBuilder(args);", "builder.Services.AddScoped<PaymentService>();"],
    "src/api/routes.py": ["from fastapi import APIRouter", "app.include_router(checkout_router)", '@router.post("/refund")'],
    "tests/test_service.py": [
        "from payment.service import PaymentService",
        "def test_process_payment():",
        "    PaymentService().process_payment(order)",
        '@router.post("/fake")',
    ],
}
VECTOR_HITS = [
    qdrant_hit("tests/test_service.py", 2, 3, "test_process_payment", score=0.95),
    qdrant_hit("src/payment/service.py", 10, 40, "process_payment", score=0.82),
    qdrant_hit("src/api/refund.py", 3, 20, "refund", score=0.7),
]
ALL_TOOLS = {
    "find_symbol", "read_code", "semantic_code_search", "keyword_code_search", "get_callers", "get_callees",
    "trace_dependencies", "find_call_path", "get_related_symbols", "get_code_metrics", "find_quality_hotspots",
    "get_module_quality_summary", "find_similar_implementations", "find_extension_points", "find_tests_for",
    "recommend_design_patterns",
}
SNAP = "commit:1"


def kinds(analysis):
    return [(r.kind, r.target) for r in analysis.requirements]


def change_context(**deps):
    return tool_context(
        source=deps.pop("source", FakeSource(CHANGE_SOURCES)),
        vectors=deps.pop("vectors", FakeVectors(VECTOR_HITS)),
        **deps,
    )


async def run(name, args, ctx=None):
    result, _ = await execute_tool(TOOLS[name], ctx or change_context(), args, cache=None)
    return result


@pytest.mark.parametrize("question", [
    "How can I add a CSV export feature to the reports?",
    "Where should I put a new endpoint for refunds?",
    "I want to add rate limiting to the API.",
    "Hogyan adjak hozzá egy új végpontot a visszatérítéshez?",
    "Szeretném bővíteni az alkalmazást PDF exporttal.",
])
def test_feature_requests_are_classified_as_change_planning(question):
    analysis = analyze_question(question)
    assert "change_planning" in analysis.intents
    found = [k for k, _ in kinds(analysis)]
    assert {"analogous_feature", "extension_point", "test_conventions", "change_impact", "change_risk"} <= set(found)
    assert "semantic_context" not in found


@pytest.mark.parametrize("question", [
    "How is process_payment implemented?",
    "Explain the implementation of the PaymentService.",
    "What does validate_input do?",
])
def test_comprehension_questions_are_not_change_planning(question):
    analysis = analyze_question(question)
    assert "change_planning" not in analysis.intents
    assert "comprehension" in analysis.intents


def test_change_to_a_named_symbol_reads_it_and_checks_its_impact():
    analysis = analyze_question("How do I add retry support to process_payment?")
    found = kinds(analysis)
    assert ("definition_code", "process_payment") in found
    assert ("impact_relations", "process_payment") in found
    assert ("analogous_feature", None) in found
    assert ("change_impact", None) not in found


def test_area_terms_split_identifiers_and_drop_filler():
    assert area_terms("How can I add a new RefundExport feature for payments?") == ["refund", "export", "payments"]


@pytest.mark.parametrize("path,expected", [
    ("tests/test_service.py", True),
    ("RagApi/Tests/SourceAccessTests.cs", True),
    ("ui/src/test/AgentExecution.test.tsx", True),
    ("src/payment/service.py", False),
    ("src/contest/score.py", False),
])
def test_test_path_detection(path, expected):
    assert is_test_path(path) is expected


async def test_similar_implementations_skip_tests_and_include_neighbours():
    result = await run("find_similar_implementations", {"description": "process a refund payment"})
    assert result.error is None
    analogs = [e for e in result.evidence if e.group == "analog"]
    assert [e.file_path for e in analogs] == ["src/payment/service.py", "src/api/refund.py"]
    neighbours = {e.symbol_name for e in result.evidence if e.group == "analog_structure"}
    assert {"PaymentService", "PaymentService.validate_input"} <= neighbours
    assert all(e.produced_by == ["find_similar_implementations"] for e in result.evidence)


async def test_similar_implementations_work_without_the_graph():
    ctx = change_context(graph=GraphLoader(fail=True))
    result = await run("find_similar_implementations", {"description": "process a refund payment"}, ctx)
    assert result.error is None
    assert {e.group for e in result.evidence} == {"analog"}


async def test_similar_implementations_report_not_found():
    ctx = change_context(vectors=FakeVectors([qdrant_hit("tests/test_service.py", 2, 3, "test_process_payment")]))
    result = await run("find_similar_implementations", {"description": "anything"}, ctx)
    assert result.error.kind == "not_found"


async def test_extension_points_are_classified_ranked_and_skip_tests():
    result = await run("find_extension_points", {"area": "refund endpoint", "near_paths": ["src/api/refund.py"]})
    assert result.error is None
    kinds_by_line = {(e.file_path, e.start_line): e.metadata["extensionKind"] for e in result.evidence}
    assert kinds_by_line[("src/Program.cs", 2)] == "dependency_injection"
    assert kinds_by_line[("src/api/routes.py", 2)] == "router"
    assert kinds_by_line[("src/api/routes.py", 3)] == "http_route"
    assert not any(is_test_path(e.file_path) for e in result.evidence)
    assert result.evidence[0].file_path == "src/api/routes.py"


async def test_extension_points_not_found():
    result = await run("find_extension_points", {}, change_context(source=FakeSource(SOURCES)))
    assert result.error.kind == "not_found"


@pytest.mark.parametrize("target", ["src/payment/service.py", "PaymentService.process_payment",
                                    "src/payment/service.py::method::PaymentService.process_payment@10"])
async def test_tests_for_a_symbol_or_file(target):
    result = await run("find_tests_for", {"target": target})
    assert result.error is None
    assert {e.file_path for e in result.evidence} == {"tests/test_service.py"}


async def test_tests_for_reports_missing_tests():
    result = await run("find_tests_for", {"target": "charge_card"})
    assert result.error.kind == "not_found"


@pytest.mark.parametrize("name,args", [
    ("find_tests_for", {"target": "../secret.py"}),
    ("find_extension_points", {"near_paths": ["/etc/passwd"]}),
    ("find_similar_implementations", {"description": "x"}),
])
async def test_change_tool_inputs_are_validated(name, args):
    result = await run(name, args)
    assert result.error.kind == "invalid_input"


def analog(path="src/payment/service.py", name="process_payment", score=0.8):
    return Evidence(source_type="code_chunk", repository_snapshot=SNAP, file_path=path, start_line=10, end_line=40,
                    symbol_name=name, symbol_kind="function", retrieval_score=score, content="def x(): ...",
                    produced_by=["find_similar_implementations"])


def extension_point():
    return Evidence(source_type="keyword_match", repository_snapshot=SNAP, file_path="src/Program.cs", start_line=2, end_line=2,
                    content="2 | builder.Services.AddScoped<PaymentService>();", produced_by=["find_extension_points"])


def evaluate(evidence, tool_log=None):
    return evaluate_sufficiency(
        analyze_question("How can I add a refund export feature?"), evidence, tool_log or [], SNAP,
        SufficiencyThresholds(), ALL_TOOLS, budget_left=True, made_progress=True,
    )


def test_change_plan_needs_an_analog_and_an_extension_point():
    result = evaluate([extension_point()])
    assert "analogous_feature:*" in result.missing
    assert "extension_point:*" in result.satisfied
    assert result.should_continue


def test_failed_change_lookups_become_unavailable_gaps():
    log = [
        {"tool": "find_tests_for", "args": {"target": "src/payment/service.py"}, "error": {"kind": "not_found", "message": "-"}},
        {"tool": "trace_dependencies", "args": {}, "error": {"kind": "not_found", "message": "-"}},
        {"tool": "get_code_metrics", "args": {}, "error": {"kind": "unavailable", "message": "-"}},
        {"tool": "recommend_design_patterns", "args": {}, "error": None, "evidenceIds": []},
    ]
    result = evaluate([analog(), extension_point()], log)
    assert set(result.unavailable) == {"test_conventions:*", "change_impact:*", "change_risk:*"}
    assert result.sufficient


def test_missing_analog_makes_dependent_requirements_unavailable():
    log = [
        {"tool": "find_similar_implementations", "args": {}, "error": {"kind": "not_found", "message": "-"}},
        {"tool": "semantic_code_search", "args": {}, "error": {"kind": "not_found", "message": "-"}},
    ]
    result = evaluate([extension_point()], log)
    assert {"analogous_feature:*", "test_conventions:*", "change_impact:*", "change_risk:*"} <= set(result.unavailable)


def test_fallback_plan_builds_on_the_analog():
    analysis = analyze_question("How can I add a refund export feature?")
    evidence = [analog(), analog("src/api/refund.py", "refund", 0.7), extension_point()]
    statuses = evaluate(evidence).requirements
    calls = fallback_calls(analysis, statuses, evidence, [], "How can I add a refund export feature?", 120)
    by_tool = {c["tool"]: c["args"] for c in calls}
    assert by_tool["find_tests_for"] == {"target": "src/payment/service.py"}
    assert [c["args"]["target"] for c in calls if c["tool"] == "trace_dependencies"] == ["src/payment/service.py", "src/api/refund.py"]
    assert by_tool["get_code_metrics"]["paths"] == ["src/payment/service.py", "src/api/refund.py"]
    assert "find_similar_implementations" not in by_tool


def test_first_fallback_plan_without_sufficiency_starts_with_change_tools():
    analysis = analyze_question("How can I add a refund export feature?")
    calls = fallback_calls(analysis, None, [], [], "How can I add a refund export feature?", 120)
    assert [c["tool"] for c in calls] == ["find_similar_implementations", "find_extension_points"]


def change_store() -> EvidenceStore:
    store = EvidenceStore(project_id=3, snapshot=SNAP)
    store.add(analog())
    store.add(extension_point())
    return store


def test_proposed_lines_may_name_new_files():
    answer = (
        "## Pattern to follow\n"
        "`process_payment` in src/payment/service.py:10-40 is the closest template [SOURCE_1].\n"
        "## New code\n"
        "- `RefundExporter` in src/export/refund_exporter.py, modelled on `process_payment` [SOURCE_1].\n"
        "- `export_refunds()` returns CSV rows.\n"
        "## Where to register it\n"
        "Proposed: register `RefundExporter` next to src/Program.cs:2 [SOURCE_2].\n"
    )
    result = verify_answer(answer, change_store())
    assert result.passed, result.feedback()


def test_new_files_outside_proposals_are_still_flagged():
    answer = "## Files to change\n- Edit src/export/refund_exporter.py to add CSV output [SOURCE_1]."
    result = verify_answer(answer, change_store())
    assert "unknown_path" in [i.kind for i in result.errors]


def test_proposed_lines_cannot_cite_unknown_evidence():
    result = verify_answer("Proposed: add `RefundExporter` like `process_payment` [SOURCE_9].", change_store())
    assert result.unknown_aliases == ["SOURCE_9"]
    assert not result.passed


async def test_agent_answers_feature_requests_with_a_change_plan():
    llm = ScriptedLLM(plans=["not json"] * 6, answers=["## Pattern to follow\nUse the closest analog [SOURCE_1]."])
    cfg = replace(config_for("evidence_aware_agentic_rag", base=AgentConfig()), max_iterations=4)
    deps, _ = agent_deps(llm, source=FakeSource(CHANGE_SOURCES), vectors=FakeVectors(VECTOR_HITS))
    state = await run_agent("How can I add a refund export feature?", SCOPE, "evidence_aware_agentic_rag", cfg, deps, run_id="run-c")

    tools = [e["tool"] for e in state["tool_log"]]
    assert tools[:2] == ["find_similar_implementations", "find_extension_points"]
    assert {"find_tests_for", "trace_dependencies"} <= set(tools)
    assert llm.count("## Pattern to follow") == 1
    satisfied = state["sufficiency"]["satisfied"]
    assert {"analogous_feature:*", "extension_point:*", "test_conventions:*", "change_impact:*"} <= set(satisfied)
