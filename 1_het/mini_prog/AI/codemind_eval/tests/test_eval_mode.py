import pytest

from app.agents.router import RouteDecision
from app.evaluation import eval_mode
from app.evaluation.eval_mode import DEFAULT_STRATEGIES, UnknownStrategyError, run_evaluation
from app.models.models import ChatRequest
from app.services import chat_service
from app.services.ollama_call import LlmResult, _record
from app.tests.agent_fakes import FakeSource, ScriptedLLM, agent_deps

FIND = {"tool": "find_symbol", "args": {"name": "process_payment"}}
READ = {"tool": "read_code", "args": {"path": "src/payment/service.py", "start_line": 10, "end_line": 40}}
GOOD_ANSWER = "`PaymentService.process_payment` in src/payment/service.py:10-40 validates the order [SOURCE_2]."


def request(ablation=None):
    return ChatRequest(prompt="What does process_payment do?", userId=1, investigationId=2, projectId=3, ablation=ablation)


def pipeline_result(**extra):
    return {
        "answer": "It validates the order [SOURCE_1].",
        "answer_en": "It validates the order [SOURCE_1].",
        "evidence": [],
        "retrieval_time_ms": 5.0,
        "graph_time_ms": 2.5,
        "context_time_ms": 1.0,
        "generation_time_ms": 9.0,
        "retrieved_count": 1,
        "top_results": [{"payload": {"path": "src/payment/service.py", "name": "process_payment",
                                     "start_line": 10, "end_line": 40}, "score": 0.9}],
        "context_evidence": [{"alias": "SOURCE_1", "source": "vector", "path": "src/payment/service.py",
                              "symbol": "process_payment", "start": 10, "end": 40}],
        "context": "[SOURCE_1]\nFile: src/payment/service.py",
        **extra,
    }


@pytest.fixture
def pipeline(monkeypatch):
    states = []

    async def fake_invoke(state):
        states.append(state)
        _record(LlmResult("c", 120, 30), "gen")
        _record(LlmResult("a", 80, 20), "gen")
        return pipeline_result()

    monkeypatch.setattr(chat_service.rag_graph, "ainvoke", fake_invoke)
    return states


@pytest.fixture
def router_calls(monkeypatch):
    calls = []
    real = chat_service.route_question

    async def spy(question, llm, timeout):
        calls.append(question)
        return await real(question, llm, timeout)

    monkeypatch.setattr(chat_service, "route_question", spy)
    return calls


def deps(plans=None, answers=None, **tools):
    llm = ScriptedLLM(plans=plans if plans is not None else [{"calls": [FIND]}, {"calls": [READ]}],
                      answers=answers if answers is not None else [GOOD_ANSWER])
    return agent_deps(llm, **tools)[0]


def test_default_strategy_set_is_the_five_evaluated_modes():
    assert DEFAULT_STRATEGIES == ("vector_rag", "selective_rag", "hybrid_rag", "evidence_aware_agentic_rag", "adaptive_rag")


async def test_unknown_strategy_is_rejected():
    with pytest.raises(UnknownStrategyError):
        await run_evaluation(request(), "graph_rag")


@pytest.mark.parametrize("strategy,overrides", [
    ("vector_rag", {"use_graph": False, "needs_rerank": False, "use_metrics": False}),
    ("selective_rag", None),
    ("hybrid_rag", {"use_graph": True, "needs_rerank": True, "use_metrics": True}),
])
async def test_pipeline_strategies_bypass_the_router(pipeline, router_calls, strategy, overrides):
    execution = await run_evaluation(request(), strategy)
    assert router_calls == []
    assert pipeline[0].get("strategy_overrides") == overrides
    assert [r["kind"] for r in execution.records] == ["legacy_run"]
    assert execution.records[0]["strategy"] == strategy
    assert execution.wall_ms >= 0


async def test_metrics_off_forces_metrics_out_of_the_pipeline(pipeline):
    await run_evaluation(request(), "hybrid_rag", metrics="off")
    assert pipeline[0]["strategy_overrides"]["use_metrics"] is False
    assert pipeline[0]["strategy_overrides"]["use_graph"] is True


async def test_agent_strategy_bypasses_the_router_and_traces_context(router_calls):
    execution = await run_evaluation(request(), "evidence_aware_agentic_rag", deps=deps())
    assert router_calls == []
    record = execution.records[-1]
    assert record["kind"] == "agent_run"
    assert record["strategy"] == "evidence_aware_agentic_rag"
    assert record["contextEvidence"] and all("alias" in e and "path" in e for e in record["contextEvidence"])
    assert record["contextText"]
    assert record["tokenUsageComplete"] is True and record["inputTokens"] > 0
    assert record["contextLatencyMs"] is not None


async def test_metrics_off_uses_the_no_metrics_ablation_for_agents():
    execution = await run_evaluation(request(), "evidence_aware_agentic_rag", metrics="off", deps=deps())
    record = execution.records[-1]
    assert record["ablation"] == "no_metrics"
    assert record["config"]["enable_metrics_tools"] is False


async def test_metrics_off_cannot_be_mixed_with_another_ablation():
    with pytest.raises(ValueError):
        await run_evaluation(request(ablation="no_graph"), "evidence_aware_agentic_rag", metrics="off", deps=deps())


async def test_routed_strategy_calls_the_router(router_calls, pipeline, monkeypatch):
    monkeypatch.setattr(chat_service, "ROUTER_ESCALATION", False)
    execution = await run_evaluation(request(), "adaptive_rag", deps=deps())
    assert router_calls == ["What does process_payment do?"]
    record = execution.records[-1]
    assert record["route"]["requested"] == "adaptive_rag"
    assert record["route"]["routingMs"] is not None


async def test_routed_pipeline_choice_receives_the_metrics_override(pipeline, monkeypatch):
    async def decide(question, llm, timeout):
        return RouteDecision("selective_rag", "simple_question", "simple", overrides={"use_graph": True}), {}, \
            {"llm_calls": 1, "input_tokens": 40, "output_tokens": 10, "llm_calls_without_usage": 0}

    monkeypatch.setattr(chat_service, "route_question", decide)
    monkeypatch.setattr(chat_service, "ROUTER_ESCALATION", False)
    execution = await run_evaluation(request(), "adaptive_rag", metrics="off", deps=deps())
    assert pipeline[0]["strategy_overrides"] == {"use_graph": True, "use_metrics": False}
    record = execution.records[-1]
    assert record["inputTokens"] == 120 + 80 + 40
    assert record["route"]["routingInputTokens"] == 40


async def test_snapshot_lookup_reports_commit_and_failures():
    from app.tools.base import Scope
    ok = await eval_mode.repository_snapshot(Scope(1, 2, 3), FakeSource())
    assert ok["repositorySnapshot"] == "commit:abc123"
    failed = await eval_mode.repository_snapshot(Scope(1, 2, 3), FakeSource(fail_snapshot=True))
    assert failed["repositorySnapshot"] is None and "backend down" in failed["snapshotError"]
