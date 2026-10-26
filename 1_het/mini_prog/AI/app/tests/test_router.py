import pytest

from app.agents.requirements import analyze_question
from app.agents.router import AGENT_MODE, PIPELINE_MODE, ROUTED_MODE, choose_strategy, escalation_reason, route_question
from app.models.models import ChatRequest
from app.services import chat_service, rag_graph
from app.tests.agent_fakes import ScriptedLLM, agent_deps, qdrant_hit

CLASSIFIER = "Analyse a user's question"
PLANNER = "retrieval planner"


def request(prompt, mode=ROUTED_MODE):
    return ChatRequest(prompt=prompt, userId=1, investigationId=2, projectId=3, mode=mode)


def pipeline_result(*names, answer="ok", **extra):
    hits = [qdrant_hit("src/payment/service.py", 10, 40, name) for name in names]
    return {"answer": answer, "answer_en": answer, "evidence": [], "top_results": hits, **extra}


@pytest.fixture
def pipeline(monkeypatch):
    states = []
    results = []

    async def fake_invoke(state):
        states.append(state)
        return results.pop(0) if results else pipeline_result("validate_proxy", "process_payment")

    monkeypatch.setattr(chat_service.rag_graph, "ainvoke", fake_invoke)
    return states, results


@pytest.mark.parametrize("question,mode,reason", [
    ("What does validate_proxy do?", PIPELINE_MODE, "simple_question"),
    ("How do I configure the database?", PIPELINE_MODE, "simple_question"),
    ("Mit csinál a validate_proxy?", PIPELINE_MODE, "simple_question"),
    ("Mit csinál a parse_code_to_tree függvény?", PIPELINE_MODE, "simple_question"),
    ("Mire használható a Neo4j a projektben?", PIPELINE_MODE, "simple_question"),
    ("Mely függvények függenek a FileService osztálytól?", AGENT_MODE, "relationship_question"),
    ("Ki használja a FileService osztályt?", AGENT_MODE, "relationship_question"),
    ("Who calls process_payment?", PIPELINE_MODE, "graph_lookup_question"),
    ("Ki hívja a process_payment függvényt?", PIPELINE_MODE, "graph_lookup_question"),
    ("What does process_payment call?", PIPELINE_MODE, "graph_lookup_question"),
    ("Who calls process_payment and refund_order?", AGENT_MODE, "relationship_question"),
    ("Which functions call parse_code_to_tree and how complex are they?", AGENT_MODE, "relationship_question"),
    ("What is the call chain from checkout to process_payment?", AGENT_MODE, "relationship_question"),
    ("What breaks if I change PaymentService?", AGENT_MODE, "relationship_question"),
    ("How can I add a new export format?", AGENT_MODE, "change_planning_question"),
    ("Should ShippingCalculator use a design pattern?", AGENT_MODE, "design_pattern_question"),
    ("What is in src/payment/service.py?", AGENT_MODE, "file_question"),
    ("What does process_payment do and how complex is it?", PIPELINE_MODE, "moderate_question"),
])
def test_choose_strategy(question, mode, reason):
    decision = choose_strategy(analyze_question(question))
    assert (decision.mode, decision.reason) == (mode, reason)
    route = decision.to_dict()
    assert route["requested"] == ROUTED_MODE and route["chosen"] == mode


async def test_route_question_falls_back_when_the_classifier_fails():
    llm = ScriptedLLM(fail_after=0)
    decision, classification, usage = await route_question("What breaks if I change process_payment?", llm, 5.0)
    assert decision.mode == AGENT_MODE
    assert classification["question_en"] == "What breaks if I change process_payment?"
    assert classification["question_type"] == "general"
    assert usage["llm_calls"] == 1


async def test_pipeline_classifier_is_skipped_when_classification_is_given(monkeypatch):
    async def no_llm(prompt):
        raise AssertionError("classifier must not run")

    monkeypatch.setattr(rag_graph, "call_llm", no_llm)
    state = {"question": "Mi ez?", "question_en": "What is this?", "question_type": "code",
             "search_vectors": ["code"], "language": "hu", "language_name": "Hungarian"}
    assert await rag_graph.classify_question(state) == state


async def test_simple_question_goes_to_the_pipeline_with_one_classifier_call(pipeline):
    states, _ = pipeline
    llm = ScriptedLLM()
    deps, _ = agent_deps(llm)
    response = await chat_service.run_chat(request("What does validate_proxy do?"), deps=deps)

    assert llm.count(CLASSIFIER) == 1
    assert states[0]["question_en"] == "What does validate_proxy do?"
    assert states[0]["question_type"] == "code"
    assert response.execution["strategy"] == PIPELINE_MODE
    assert response.execution["route"]["chosen"] == PIPELINE_MODE
    assert response.execution["route"]["reason"] == "simple_question"
    assert "escalatedTo" not in response.execution["route"]
    assert llm.count(PLANNER) == 0


async def test_graph_lookup_question_goes_to_the_pipeline_with_the_graph_forced(pipeline):
    states, results = pipeline
    results.append(pipeline_result("process_payment", use_graph=True, graph_subgraphs=[{"root": "f1", "nodes": []}]))
    llm = ScriptedLLM()
    deps, _ = agent_deps(llm)
    response = await chat_service.run_chat(request("Who calls process_payment?"), deps=deps)

    assert llm.count(CLASSIFIER) == 1
    assert states[0]["strategy_overrides"] == {"use_graph": True}
    assert response.execution["strategy"] == PIPELINE_MODE
    assert response.execution["route"]["reason"] == "graph_lookup_question"


async def test_relationship_question_goes_to_the_agent_with_one_classifier_call():
    llm = ScriptedLLM(
        plans=[
            {"calls": [{"tool": "find_symbol", "args": {"name": "process_payment"}}]},
            {"calls": [{"tool": "get_callers", "args": {"symbol": "process_payment"}}]},
        ],
        answers=["`checkout` calls `process_payment` [GRAPH_1]."],
    )
    deps, trace = agent_deps(llm)
    response = await chat_service.run_chat(request("What breaks if I change process_payment?"), deps=deps)

    assert llm.count(CLASSIFIER) == 1
    assert response.execution["strategy"] == AGENT_MODE
    assert response.execution["route"]["chosen"] == AGENT_MODE
    assert response.execution["route"]["reason"] == "relationship_question"
    assert response.execution["llmCalls"] == len(llm.prompts)
    assert trace.records[0]["route"]["chosen"] == AGENT_MODE


async def test_explicit_modes_are_not_routed():
    llm = ScriptedLLM(answers=["`process_payment` validates the order [SOURCE_1]."])
    deps, _ = agent_deps(llm)
    response = await chat_service.run_chat(request("What does process_payment do?", AGENT_MODE), deps=deps)
    assert response.execution["route"] is None
    assert llm.count(CLASSIFIER) == 1


def test_auto_alias_resolves_to_routed_mode():
    assert chat_service.resolve_mode("auto") == ROUTED_MODE


@pytest.mark.parametrize("question,result,reason", [
    ("What does validate_proxy do?", pipeline_result("validate_proxy"), None),
    ("What does validate_proxy do?", {"answer": "ok", "top_results": []}, "no_retrieval_results"),
    ("What does validate_proxy do?", pipeline_result("validate_proxy", answer=rag_graph.NOT_FOUND_EN), "pipeline_not_found"),
    ("What does validate_proxy do?", pipeline_result("charge_card"), "targets_not_retrieved"),
    ("What does process_payment do and how complex is it?", pipeline_result("process_payment"), "metrics_missing"),
    ("What does process_payment do and how complex is it?",
     pipeline_result("process_payment", metrics_results={"available": True}), None),
    ("Who calls process_payment?", pipeline_result("process_payment", use_graph=True, graph_subgraphs=[]), "graph_relations_missing"),
    ("How do I configure the database?", pipeline_result("load_settings"), None),
])
def test_escalation_reason(question, result, reason):
    assert escalation_reason(analyze_question(question), result) == reason


async def test_weak_pipeline_answer_escalates_to_the_agent_with_seeded_evidence(pipeline):
    states, results = pipeline
    results.append(pipeline_result("charge_card"))
    llm = ScriptedLLM(
        plans=[{"calls": [{"tool": "find_symbol", "args": {"name": "validate_proxy"}}]}],
        answers=["`validate_proxy` is not in the repository [SOURCE_1]."],
    )
    deps, trace = agent_deps(llm)
    response = await chat_service.run_chat(request("What does validate_proxy do?"), deps=deps)

    assert len(states) == 1
    assert llm.count(CLASSIFIER) == 1
    route = response.execution["route"]
    assert route["chosen"] == PIPELINE_MODE
    assert route["escalatedTo"] == AGENT_MODE
    assert route["escalationReason"] == "targets_not_retrieved"
    assert response.execution["strategy"] == AGENT_MODE
    assert response.execution["seededEvidence"] == 1
    assert trace.records[-1]["route"]["escalatedTo"] == AGENT_MODE


async def test_escalation_can_be_disabled(pipeline, monkeypatch):
    _, results = pipeline
    results.append({"answer": "ok", "evidence": [], "top_results": []})
    monkeypatch.setattr(chat_service, "ROUTER_ESCALATION", False)
    llm = ScriptedLLM()
    deps, _ = agent_deps(llm)
    response = await chat_service.run_chat(request("What does validate_proxy do?"), deps=deps)

    assert response.execution["strategy"] == PIPELINE_MODE
    assert llm.count(PLANNER) == 0
