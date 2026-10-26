import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.agents.config import AgentConfig, config_for
from app.agents.graph import run_agent
from app.agents.requirements import analyze_question
from app.evidence.schemas import Evidence
from app.evidence.store import EvidenceStore
from app.evidence.verifier import verify_answer
from app.models.models import ChatRequest
from app.patterns.analyzer import AnalysisRequest, analyze
from app.patterns.detector import detect
from app.patterns.knowledge_base import DEFAULT_PATH, SIGNALS, KnowledgeBase, default_knowledge_base, load_knowledge_base
from app.patterns.recommender import classify_change
from app.patterns.signals import build_index, structural_signals
from app.patterns.structure import parse_source, parse_type_text
from app.services import chat_service
from app.tools.base import execute_tool
from app.tools.code_graph import CodeGraphData
from app.tools.pattern_tools import PATTERN_TOOLS
from app.tools.registry import build_registry

from app.tests import pattern_fixtures as F
from app.tests.agent_fakes import SCOPE, FakeSource, GraphLoader, ScriptedLLM, agent_deps

TOOLS = {spec.name: spec for spec in PATTERN_TOOLS}


async def run_analysis(sources, paths, change=None, **kwargs):
    ctx = F.pattern_context(sources, **kwargs)
    outcome = await analyze(ctx, AnalysisRequest(paths=paths, change_request=change), "recommend_design_patterns")
    return outcome, ctx


def statuses(findings):
    return {(f.pattern, f.status) for f in findings}


def test_knowledge_base_is_valid_and_complete():
    kb = default_knowledge_base()
    assert {p.id for p in kb.patterns} == {"strategy", "observer", "factory_method", "adapter", "facade", "decorator", "repository"}
    for pattern in kb.patterns:
        assert pattern.benefits and pattern.drawbacks and pattern.avoid_when and pattern.confidence_notes
        assert pattern.detection.existing or pattern.detection.opportunities


def test_knowledge_base_rejects_unknown_signals_and_duplicates():
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    broken = json.loads(json.dumps(data))
    broken["patterns"][0]["detection"]["existing"][0]["all"] = ["made_up_signal"]
    with pytest.raises(ValidationError, match="unknown signals"):
        KnowledgeBase.model_validate(broken)
    duplicated = json.loads(json.dumps(data))
    duplicated["patterns"].append(duplicated["patterns"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        KnowledgeBase.model_validate(duplicated)


def test_a_new_pattern_is_detected_from_configuration_only(tmp_path):
    data = default_knowledge_base().model_dump()
    template = next(p for p in data["patterns"] if p["id"] == "observer")
    custom = {**template, "id": "event_bus", "name": "Event Bus", "detection": {
        "existing": [{"all": ["event_declared", "event_raised"], "boost": [], "status": "likely", "partial_status": None,
                      "requires_change": [], "explanation": "Events are declared and raised."}],
        "opportunities": [], "avoid_signals": []}}
    data["patterns"] = [custom]
    path = tmp_path / "patterns.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    kb = load_knowledge_base(path)
    structure = parse_source("src/Orders/Order.cs", "\n".join(F.OBSERVER["src/Orders/Order.cs"]))
    existing, _ = detect(kb, structural_signals([structure], build_index([structure])))
    assert [(d.pattern.id, d.status) for d in existing] == [("event_bus", "likely")]


@pytest.mark.parametrize("text,name,element", [
    ("List<IListener>", "List", "IListener"), ("list[Listener]", "list", "Listener"), ("Listener[]", "Array", "Listener"),
    ("Optional[Shipping]", "Shipping", None), ("Shipping | None", "Shipping", None), ("System.IO.Stream", "Stream", None),
])
def test_type_text_parsing(text, name, element):
    parsed = parse_type_text(text)
    assert (parsed.name, parsed.element) == (name, element)


def test_structure_extraction_across_languages():
    cs = parse_source("src/Export/Exporters.cs", "\n".join(F.FACTORY["src/Export/Exporters.cs"]))
    assert [(t.name, t.kind, t.bases) for t in cs.types][:2] == [("IExporter", "interface", []), ("CsvExporter", "class", ["IExporter"])]
    service = parse_source("src/Export/ExportService.cs", "\n".join(F.FACTORY["src/Export/ExportService.cs"]))
    dispatch = service.types[0].methods[0].dispatches[0]
    assert (dispatch.discriminator, len(dispatch.branches), dispatch.has_default) == ("format", 3, True)
    assert dispatch.created_types == ["CsvExporter", "PdfExporter", "XmlExporter"]
    py = parse_source("src/shipping/calculator.py", "\n".join(F.STRATEGY["src/shipping/calculator.py"]))
    chain = py.types[0].method("cost").dispatches[0]
    assert (chain.discriminator, len(chain.branches)) == ("order.method", 4)
    ts = parse_source("src/cart/cart.ts", "\n".join(F.EXISTING_STRATEGY["src/cart/cart.ts"]))
    assert ts.types[0].field_types()["rule"].name == "DiscountRule"
    java = parse_source("src/pay/LoggingPaymentService.java", "\n".join(F.DECORATOR["src/pay/LoggingPaymentService.java"]))
    assert java.types[0].bases == ["PaymentService"]
    assert parse_source("main.go", "package main") is None


async def test_strategy_candidate_with_many_cases_prefers_refactoring():
    outcome, _ = await run_analysis(F.STRATEGY, ["src/shipping/calculator.py"], "How can I add a new shipping method for drones?")
    analysis = outcome.analysis
    assert ("strategy", "likely") in statuses(analysis.detected_opportunities)
    assert [(r.pattern, r.mode, r.confidence) for r in analysis.recommended_patterns] == [("strategy", "introduce", "medium")]
    assert analysis.preferred_alternative == "pattern_refactoring"
    assert analysis.alternatives.minimal_change.affected_files == ["src/shipping/calculator.py"]
    assert any(e.startswith("Proposed:") for e in analysis.alternatives.pattern_refactoring.new_elements)
    assert {r.basis for r in analysis.comparison} >= {"planned", "qualitative"}


async def test_two_variants_do_not_justify_a_pattern():
    outcome, _ = await run_analysis(F.FEW_VARIANTS, ["src/shipping/labels.py"], "Add a new order kind label")
    analysis = outcome.analysis
    assert analysis.no_pattern_needed and analysis.recommended_patterns == []
    assert analysis.preferred_alternative == "minimal_change"
    assert any(c.pattern == "strategy" and "only two cases" in c.reason for c in analysis.considered_patterns)


async def test_simple_change_needs_no_pattern():
    outcome, _ = await run_analysis(F.NO_PATTERN, ["src/users/names.py"], "Add support for middle names in full_name")
    analysis = outcome.analysis
    assert analysis.no_pattern_needed
    assert analysis.existing_patterns == [] and analysis.detected_opportunities == []
    assert analysis.preferred_alternative == "minimal_change"
    assert "No design pattern is justified" in analysis.justification
    assert analysis.alternatives.pattern_refactoring is None


async def test_factory_candidate_uses_measured_complexity():
    metrics = F.PatternMetrics(F.complexity("src/Export/ExportService.cs", "Run", 3, 15, 12, "High"))
    outcome, _ = await run_analysis(F.FACTORY, ["src/Export/ExportService.cs"], "How can I add a new export format for JSON?", metrics=metrics)
    analysis = outcome.analysis
    assert "src/Export/Exporters.cs" in analysis.scope.files
    factory = next(f for f in analysis.detected_opportunities if f.pattern == "factory_method")
    assert factory.status == "likely" and factory.boosted_by == ["high_complexity"]
    assert analysis.recommended_patterns[0].pattern == "factory_method"
    assert any(r.dimension.startswith("Cyclomatic complexity") and r.minimal_change == "12 (Lizard)" and r.basis == "measured" for r in analysis.comparison)
    assert analysis.preferred_alternative == "minimal_change"
    assert "regression risk" in analysis.justification
    assert analysis.diagnostics.metrics_used
    assert any(r.source == "metrics" for r in analysis.evidence)


async def test_factory_candidate_without_metrics_stays_weak():
    outcome, _ = await run_analysis(F.FACTORY, ["src/Export/ExportService.cs"], "How can I add a new export format for JSON?",
                                    metrics=F.PatternMetrics(available=False))
    analysis = outcome.analysis
    assert analysis.no_pattern_needed
    assert {"strategy", "factory_method"} <= {c.pattern for c in analysis.considered_patterns}
    assert any("No stored code-metrics analysis" in l for l in analysis.limitations)
    assert not analysis.diagnostics.metrics_used


async def test_adapter_is_extended_for_an_integration():
    outcome, _ = await run_analysis(F.ADAPTER, ["src/payments/gateway.py"], "How can I integrate the Stripe SDK as a new payment provider?")
    analysis = outcome.analysis
    assert ("adapter", "likely") in statuses(analysis.existing_patterns)
    assert analysis.recommended_patterns[0].pattern == "adapter" and analysis.recommended_patterns[0].mode == "extend_existing"
    assert analysis.preferred_alternative == "minimal_change"
    assert not any(f.pattern == "strategy" for f in analysis.existing_patterns)


async def test_adapter_opportunity_only_for_integration_requests():
    outcome, _ = await run_analysis(F.ADAPTER, ["src/payments/gateway.py"], "Add support for refunds")
    assert not any(f.pattern == "adapter" for f in outcome.analysis.detected_opportunities)


async def test_facade_candidate_from_graph_call_sequences():
    outcome, _ = await run_analysis(F.FACADE, ["src/orders/checkout.py", "src/orders/reorder.py"],
                                    "How can I simplify placing orders? There are too many calls to the subsystems.", graph=F.facade_graph())
    analysis = outcome.analysis
    facade = next(f for f in analysis.detected_opportunities if f.pattern == "facade")
    assert facade.status == "likely" and facade.boosted_by == ["fan_out_hub"]
    assert analysis.recommended_patterns[0].pattern == "facade"
    assert any(r.source == "graph" for r in analysis.evidence)


async def test_existing_strategy_is_extended_instead_of_reintroduced():
    outcome, _ = await run_analysis(F.EXISTING_STRATEGY, ["src/cart/cart.ts"], "How do I add a new discount type?")
    analysis = outcome.analysis
    assert ("strategy", "likely") in statuses(analysis.existing_patterns)
    recommendation = analysis.recommended_patterns[0]
    assert (recommendation.pattern, recommendation.mode) == ("strategy", "extend_existing")
    assert any("DiscountRule" in c for c in recommendation.architectural_changes)
    assert analysis.alternatives.pattern_refactoring is None
    assert analysis.preferred_alternative == "minimal_change"


async def test_existing_observer_decorator_and_repository_are_detected():
    observer, _ = await run_analysis(F.OBSERVER, list(F.OBSERVER))
    subjects = {(f.pattern, f.status, f.subject) for f in observer.analysis.existing_patterns}
    assert ("observer", "confirmed", "Order") in subjects
    assert ("observer", "confirmed", "Warehouse._listeners") in subjects
    assert not any("BatchJob" in f.subject for f in observer.analysis.existing_patterns)
    decorator, _ = await run_analysis(F.DECORATOR, ["src/pay/LoggingPaymentService.java"])
    assert ("decorator", "confirmed") in statuses(decorator.analysis.existing_patterns)
    service, _ = await run_analysis(F.SERVICE_AND_REPOSITORY, ["src/Orders/OrderService.cs"])
    assert statuses(service.analysis.existing_patterns) == {("repository", "likely")}
    assert service.analysis.recommended_patterns == [] and service.analysis.preferred_alternative is None


async def test_missing_graph_is_reported_and_analysis_continues():
    outcome, _ = await run_analysis(F.STRATEGY, ["src/shipping/calculator.py"], "How can I add a new shipping method?", graph_fails=True)
    analysis = outcome.analysis
    assert any("Knowledge graph unavailable" in l for l in analysis.limitations)
    assert not analysis.diagnostics.graph_used
    assert analysis.recommended_patterns


async def test_unsupported_languages_are_skipped_gracefully():
    sources = {"src/main.go": ["package main"], **F.NO_PATTERN}
    outcome, _ = await run_analysis(sources, ["src/main.go", "src/users/names.py"])
    assert outcome.analysis.scope.skipped == ["src/main.go"]
    assert any("skipped: src/main.go" in l for l in outcome.analysis.limitations)


async def test_no_parsable_files_is_a_typed_error():
    result, _ = await execute_tool(TOOLS["detect_design_patterns"], F.pattern_context({"src/main.go": ["package main"]}), {"paths": ["src/main.go"]}, cache=None)
    assert result.error.kind == "not_found"


async def test_evidence_references_resolve_to_real_locations():
    outcome, ctx = await run_analysis(F.EXISTING_STRATEGY, ["src/cart/cart.ts"], "How do I add a new discount type?")
    analysis = outcome.analysis
    store = EvidenceStore(project_id=SCOPE.project_id, snapshot=ctx.snapshot)
    for item in outcome.evidence.values():
        store.add(item)
    referenced = {i for r in analysis.recommended_patterns for i in r.evidence_ids}
    assert referenced and referenced <= set(store.items)
    for ref in analysis.evidence:
        assert ref.id in store.items
        lines = F.EXISTING_STRATEGY[ref.file_path]
        assert 1 <= ref.start_line <= (ref.end_line or ref.start_line) <= len(lines)


async def test_evidence_ids_are_scoped_to_the_project():
    outcome, ctx = await run_analysis(F.DECORATOR, ["src/pay/LoggingPaymentService.java"])
    source = ctx.deps.source
    assert source.reads and all(scope == SCOPE for scope, *_ in source.reads)
    other = EvidenceStore(project_id=99, snapshot=ctx.snapshot)
    foreign = next(iter(outcome.evidence.values())).model_copy(update={"project_id": SCOPE.project_id})
    with pytest.raises(Exception):
        other.add(foreign)


async def test_repeated_and_excess_analyses_are_bounded():
    ctx = F.pattern_context({**F.STRATEGY, **F.NO_PATTERN, **F.DECORATOR})
    first, _ = await execute_tool(TOOLS["detect_design_patterns"], ctx, {"paths": ["src/shipping/calculator.py"]}, cache=None)
    again, _ = await execute_tool(TOOLS["find_pattern_opportunities"], ctx, {"paths": ["src/shipping/calculator.py"]}, cache=None)
    reads = len(ctx.deps.source.reads)
    second, _ = await execute_tool(TOOLS["detect_design_patterns"], ctx, {"paths": ["src/users/names.py"]}, cache=None)
    third, _ = await execute_tool(TOOLS["detect_design_patterns"], ctx, {"paths": ["src/pay/LoggingPaymentService.java"]}, cache=None)
    assert first.error is None and again.error is None and second.error is None
    assert again.metadata["operation"] == "find_pattern_opportunities"
    assert reads == 1
    assert third.error.kind == "budget"


@pytest.mark.parametrize("args", [{"paths": ["../etc/passwd"]}, {}, {"symbols": ["x; DROP"]}])
async def test_pattern_tool_inputs_are_validated(args):
    result, _ = await execute_tool(TOOLS["detect_design_patterns"], F.pattern_context(F.STRATEGY), args, cache=None)
    assert result.error.kind == "invalid_input"


@pytest.mark.parametrize("question", [
    "How can I add a new payment method?",
    "What would be the best way to extend this component?",
    "How should the OrderService class be refactored?",
    "Is there a design pattern that could simplify this code?",
    "How can I integrate a new API without rewriting the legacy subsystem?",
    "Milyen tervezési mintát alkalmazzak a PaymentService átszervezéséhez?",
])
def test_pattern_analysis_is_requested_for_design_questions(question):
    assert "pattern_analysis" in [r.kind for r in analyze_question(question).requirements]


@pytest.mark.parametrize("question", [
    "What does the process_payment method do?",
    "Where is the PaymentService class defined?",
    "Which function calls process_payment?",
    "Explain the total_amount variable.",
    "Show the implementation of validate_input.",
])
def test_pattern_analysis_is_not_requested_for_lookups(question):
    assert "pattern_analysis" not in [r.kind for r in analyze_question(question).requirements]


@pytest.mark.parametrize("text,kind", [
    ("How can I add a new payment method?", "new_variant"),
    ("Integrate the Stripe SDK", "integration"),
    ("Add caching around the price lookup", "cross_cutting"),
    ("Notify the warehouse when an order changes", "notification"),
    ("Refactor this class", "refactor"),
])
def test_change_classification(text, kind):
    assert kind in classify_change(text)


def test_feature_flag_controls_the_tools():
    assert set(TOOLS) <= set(build_registry(AgentConfig()))
    assert not set(TOOLS) & set(build_registry(replace(AgentConfig(), enable_pattern_analysis=False)))
    assert not config_for("evidence_aware_agentic_rag", "no_patterns", base=AgentConfig()).enable_pattern_analysis


def test_proposed_pattern_sections_pass_verification():
    store = EvidenceStore(project_id=3, snapshot="commit:1")
    store.add(Evidence(source_type="code_range", file_path="src/shipping/calculator.py", start_line=6, end_line=14,
                       symbol_name="ShippingCalculator.cost", content="...", produced_by=["recommend_design_patterns"]))
    answer = (
        "## Recommended approach\n`ShippingCalculator.cost` selects the price in 4 cases [SOURCE_1].\n"
        "### Pattern-based refactoring\n- `ShippingStrategy` interface in src/shipping/strategies.py with `DroneShipping`.\n"
    )
    assert verify_answer(answer, store).passed


CALCULATOR_GRAPH = CodeGraphData(
    classes=[{"id": "k", "name": "ShippingCalculator", "path": "src/shipping/calculator.py", "startLine": 1, "endLine": 14}],
    functions=[{"id": "f", "name": "cost", "path": "src/shipping/calculator.py", "startLine": 5, "endLine": 14}],
)


def pattern_answer():
    return ("## Existing patterns\nNone detected.\n## Recommended approach\n"
            "`ShippingCalculator.cost` selects the price by order.method in 4 cases [SOURCE_1].")


async def test_agent_runs_pattern_analysis_for_design_questions():
    llm = ScriptedLLM(plans=["not json"] * 6, answers=[pattern_answer()])
    deps, trace = agent_deps(llm, source=FakeSource(F.STRATEGY), graph=GraphLoader(CALCULATOR_GRAPH), metrics=F.PatternMetrics())
    request = ChatRequest(prompt="Is there a design pattern that could simplify ShippingCalculator.cost?", userId=1, investigationId=2,
                          projectId=3, mode="evidence_aware_agentic_rag")
    response = await chat_service.run_chat(request, deps=deps)

    tools = [step["tool"] for step in response.execution["trace"]]
    assert "recommend_design_patterns" in tools
    assert llm.count("PATTERN ANALYSIS:") >= 1
    diagnostics = response.execution["patternAnalysis"]
    assert diagnostics["invoked"] and diagnostics["patternsRecommended"] == ["strategy"]
    assert response.patternAnalysis["preferred_alternative"] == "pattern_refactoring"
    shown = {e.id for e in response.evidence}
    assert all(ref["alias"] in shown for ref in response.patternAnalysis["evidence"])
    record = trace.records[0]
    assert record["patternAnalysis"]["invoked"]
    assert "content" not in json.dumps(record["patternAnalysis"])


async def test_agent_skips_pattern_analysis_for_lookups_and_when_disabled():
    llm = ScriptedLLM(plans=["not json"] * 4, answers=["`process_payment` is defined in src/payment/service.py [SOURCE_1]."])
    deps, _ = agent_deps(llm)
    state = await run_agent("What does the process_payment function do?", SCOPE, "evidence_aware_agentic_rag",
                            config_for("evidence_aware_agentic_rag", base=AgentConfig()), deps, run_id="r1")
    assert not {e["tool"] for e in state["tool_log"]} & set(TOOLS)
    assert state["execution"]["patternAnalysis"]["invoked"] is False

    llm = ScriptedLLM(plans=["not json"] * 6, answers=[pattern_answer()])
    deps, _ = agent_deps(llm, source=FakeSource(F.STRATEGY), graph=GraphLoader(CALCULATOR_GRAPH))
    disabled = config_for("evidence_aware_agentic_rag", "no_patterns", base=AgentConfig())
    state = await run_agent("Is there a design pattern that could simplify ShippingCalculator.cost?", SCOPE,
                            "evidence_aware_agentic_rag", disabled, deps, run_id="r2")
    assert not {e["tool"] for e in state["tool_log"]} & set(TOOLS)
    assert "pattern_analysis" not in [r["kind"] for r in state["analysis"]["requirements"]]
    assert not any("pattern" in gap for gap in state.get("open_gaps") or [])
    assert llm.count("PATTERN ANALYSIS:") == 0


def test_signal_vocabulary_is_documented():
    used = {s for p in default_knowledge_base().patterns for r in p.detection.existing + p.detection.opportunities for s in r.all + r.boost}
    assert used <= set(SIGNALS)
