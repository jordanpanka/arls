import pytest

from app.agents.config import AgentConfig
from app.models.models import ChatRequest, ChatResponse
from app.services import chat_service, rag_graph


def request(mode=None, ablation=None):
    return ChatRequest(prompt="Mi ez?", userId=1, investigationId=2, projectId=3, mode=mode, ablation=ablation)


@pytest.fixture
def legacy(monkeypatch):
    states = []

    async def fake_invoke(state):
        states.append(state)
        return {"answer": "Valasz [SOURCE_1].", "evidence": [], "retrieval_time_ms": 5.0, "top_results": []}

    monkeypatch.setattr(chat_service.rag_graph, "ainvoke", fake_invoke)
    return states


@pytest.fixture
def agentic(monkeypatch):
    calls = []

    async def fake_run_agent(question, scope, mode, config, deps, run_id, ablation=None, experiment_id=None, **routing):
        calls.append({"mode": mode, "config": config, "ablation": ablation, "scope": scope})
        return {"answer": "ok", "status": "verified", "cited_aliases": [], "evidence": {}, "aliases": {},
                "project_id": scope.project_id, "repository_snapshot": "s",
                "execution": {"strategy": mode, "toolCalls": 0}}

    monkeypatch.setattr(chat_service, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_service, "default_tool_deps", lambda: None)
    return calls


def test_default_mode_routes_per_question():
    assert chat_service.resolve_mode(None) == "routed_rag"


async def test_adaptive_mode_keeps_the_existing_pipeline_unchanged(legacy):
    result = await chat_service.send_message_async_langgraph(request("adaptive_rag"))
    assert result.is_success
    assert legacy == [{"question": "Mi ez?", "user_id": 1, "investigation_id": 2, "project_id": 3}]
    data = result.data
    assert data["answer"] == "Valasz [SOURCE_1]."
    assert data["evidence"] == []
    assert data["execution"]["strategy"] == "adaptive_rag"
    assert ChatResponse.model_validate(data).answer == data["answer"]


@pytest.mark.parametrize("mode,overrides", [
    ("vector_rag", {"use_graph": False, "needs_rerank": False, "use_metrics": False}),
    ("hybrid_rag", {"use_graph": True, "needs_rerank": True, "use_metrics": True}),
    ("langgraph", None),
])
async def test_legacy_modes_pass_strategy_overrides(legacy, mode, overrides):
    await chat_service.run_chat(request(mode))
    assert legacy[0].get("strategy_overrides") == overrides


async def test_search_plan_applies_overrides_on_top_of_question_routing():
    base = {"question": "What does foo do?", "question_type": "code"}
    plain = await rag_graph.search_plan(base)
    vector = await rag_graph.search_plan({**base, "strategy_overrides": {"use_graph": False, "needs_rerank": False, "use_metrics": False}})
    assert plain["use_graph"] is True and plain["needs_rerank"] is True
    assert vector["use_graph"] is False and vector["needs_rerank"] is False and vector["use_metrics"] is False


@pytest.mark.parametrize("mode,sufficiency,verification", [
    ("agentic_rag", False, False),
    ("evidence_aware_agentic_rag", True, True),
    ("agentic", True, True),
])
async def test_agent_modes_dispatch_with_their_presets(agentic, mode, sufficiency, verification):
    result = await chat_service.send_message_async_langgraph(request(mode))
    assert result.is_success
    config: AgentConfig = agentic[0]["config"]
    assert config.enable_sufficiency is sufficiency
    assert config.enable_verification is verification
    assert agentic[0]["scope"].project_id == 3
    assert result.data["status"] == "verified"


async def test_ablation_presets_reach_the_agent(agentic):
    await chat_service.run_chat(request("evidence_aware_agentic_rag", "no_graph"))
    assert agentic[0]["config"].enable_graph_tools is False
    assert agentic[0]["ablation"] == "no_graph"


@pytest.mark.parametrize("mode,ablation", [("magic_rag", None), ("agentic_rag", "no_brain")])
async def test_unknown_mode_or_ablation_fails_cleanly(mode, ablation):
    result = await chat_service.send_message_async_langgraph(request(mode, ablation))
    assert not result.is_success
    assert "Unknown" in result.message


def test_supported_modes():
    assert set(chat_service.SUPPORTED_MODES) == {
        "vector_rag", "hybrid_rag", "adaptive_rag", "agentic_rag", "evidence_aware_agentic_rag", "routed_rag",
    }
