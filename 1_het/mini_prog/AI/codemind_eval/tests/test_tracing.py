import pytest

from app.models.models import ChatRequest
from app.services import chat_service, rag_graph
from app.services.ollama_call import LlmResult, _optional_count, _record, record_llm_usage, usage_counts
from app.tests.agent_fakes import ScriptedLLM, agent_deps
from app.agents.graph import run_agent
from app.agents.config import AgentConfig, config_for
from app.tests.agent_fakes import SCOPE
from codemind_eval.records import normalize_execution

REQUIRED_FIELDS = {
    "selectedStrategy", "effectiveStrategy", "retrievedEvidence", "contextEvidence", "toolCalls", "iterations",
    "inputTokens", "outputTokens", "tokenUsageComplete", "answer", "latency",
}
LATENCY_FIELDS = {"totalMs", "routingMs", "vectorMs", "graphMs", "retrievalMs", "contextMs", "generationMs"}


def test_missing_ollama_counts_stay_unavailable():
    assert _optional_count(None) is None
    assert _optional_count("12") == 12
    assert usage_counts(LlmResult("x", None, 3))["llm_calls_without_usage"] == 1
    assert usage_counts(None) == {"llm_calls": 1, "input_tokens": 0, "output_tokens": 0, "llm_calls_without_usage": 1}
    assert usage_counts(LlmResult("x", 5, 3))["llm_calls_without_usage"] == 0


def test_usage_recorder_only_records_inside_its_scope():
    _record(LlmResult("outside", 1, 1), "m")
    with record_llm_usage() as calls:
        _record(LlmResult("inside", 10, 2), "m")
        _record(LlmResult("inside", None, None), "m")
    assert calls == [{"model": "m", "inputTokens": 10, "outputTokens": 2},
                     {"model": "m", "inputTokens": None, "outputTokens": None}]


async def test_pipeline_trace_marks_partial_token_usage(monkeypatch):
    async def fake_invoke(state):
        _record(LlmResult("a", 100, 10), "gen")
        _record(LlmResult("b", None, None), "gen")
        return {"answer": "x [SOURCE_1] and [METRIC_2]", "evidence": [], "retrieval_time_ms": 3.0, "top_results": [],
                "context_evidence": [], "context": ""}

    monkeypatch.setattr(chat_service.rag_graph, "ainvoke", fake_invoke)
    from app.evaluation.trace_collector import MemoryTraceCollector
    memory = MemoryTraceCollector()
    request = ChatRequest(prompt="q", userId=1, investigationId=2, projectId=3)
    await chat_service._run_pipeline(request, "vector_rag", "run", memory)
    record = memory.records[0]
    assert record["inputTokens"] == 100
    assert record["tokenUsageComplete"] is False
    assert record["llmCallsWithoutUsage"] == 1
    assert record["graphLatencyMs"] is None
    assert record["citedAliases"] == ["SOURCE_1", "METRIC_2"]


async def test_pipeline_retrieved_evidence_includes_graph_and_metric_context(monkeypatch):
    async def fake_invoke(state):
        return {"answer": "x", "evidence": [], "context": "",
                "top_results": [{"payload": {"path": "src/a.py", "name": "run"}, "score": 0.9}],
                "context_evidence": [
                    {"alias": "SOURCE_1", "source": "vector", "path": "src/a.py", "symbol": "run"},
                    {"alias": "GRAPH_1", "source": "graph", "path": "src/c.py", "symbol": "helper"},
                    {"alias": "METRIC_1", "source": "metric", "path": "src/d.py", "symbol": "big"},
                ]}

    monkeypatch.setattr(chat_service.rag_graph, "ainvoke", fake_invoke)
    from app.evaluation.trace_collector import MemoryTraceCollector
    memory = MemoryTraceCollector()
    await chat_service._run_pipeline(ChatRequest(prompt="q", userId=1, investigationId=2, projectId=3), "hybrid_rag", "r", memory)
    paths = [e["path"] for e in memory.records[0]["retrievedEvidence"]]
    assert paths == ["src/a.py", "src/c.py", "src/d.py"]


async def test_pipeline_without_llm_usage_reports_no_tokens(monkeypatch):
    async def fake_invoke(state):
        return {"answer": "x", "evidence": [], "top_results": []}

    monkeypatch.setattr(chat_service.rag_graph, "ainvoke", fake_invoke)
    from app.evaluation.trace_collector import MemoryTraceCollector
    memory = MemoryTraceCollector()
    await chat_service._run_pipeline(ChatRequest(prompt="q", userId=1, investigationId=2, projectId=3), "vector_rag", "r", memory)
    assert memory.records[0]["inputTokens"] is None
    assert memory.records[0]["tokenUsageComplete"] is False


async def test_build_context_records_the_evidence_given_to_the_llm():
    state = {
        "top_results": [
            {"payload": {"path": "src/a.py", "name": "run", "kind": "function", "start_line": 3, "end_line": 9,
                         "code": "def run(): pass"}, "score": 0.8, "matched_vector": "code"},
            {"payload": {"path": "src/b.py", "name": "empty", "kind": "function"}, "score": 0.7},
        ],
        "graph_context": ["Knowledge graph around run"],
        "graph_subgraphs": [{"root": "n1", "nodes": [
            {"id": "n1", "labels": ["Function"], "props": {"name": "run", "filePath": "src/a.py", "startLine": 3}},
            {"id": "n2", "labels": ["Function"], "props": {"name": "helper", "filePath": "src/c.py"}},
        ], "edges": []}],
    }
    result = await rag_graph.build_context(state)
    evidence = result["context_evidence"]
    assert [(e["source"], e["path"], e["symbol"]) for e in evidence] == [
        ("vector", "src/a.py", "run"), ("graph", "src/a.py", "run"), ("graph", "src/c.py", "helper")]
    assert evidence[0]["alias"] == "SOURCE_1"
    assert result["context_time_ms"] >= 0


async def test_agent_marks_tokens_unavailable_when_the_llm_reports_none():
    class NoUsage(ScriptedLLM):
        async def __call__(self, prompt, json_mode, timeout):
            result = await super().__call__(prompt, json_mode, timeout)
            return LlmResult(result.text, None, None)

    llm = NoUsage(plans=[{"calls": [{"tool": "find_symbol", "args": {"name": "process_payment"}}]}], answers=["x [SOURCE_1]"])
    deps, trace = agent_deps(llm)
    state = await run_agent("What does process_payment do?", SCOPE, "evidence_aware_agentic_rag",
                            config_for("evidence_aware_agentic_rag", base=AgentConfig()), deps, run_id="r")
    record = trace.records[0]
    assert record["inputTokens"] is None and record["outputTokens"] is None
    assert record["tokenUsageComplete"] is False
    assert state["execution"]["llmCallsWithoutUsage"] == state["execution"]["llmCalls"]


def pipeline_record(**extra):
    return {"kind": "legacy_run", "strategy": "selective_rag", "inputTokens": 300, "outputTokens": 60,
            "tokenUsageComplete": True, "llmCalls": 3, "vectorLatencyMs": 10.0, "graphLatencyMs": 4.0,
            "contextLatencyMs": 1.0, "retrievalLatencyMs": 10.0, "generationLatencyMs": 50.0,
            "retrievedEvidence": [{"path": "a.py"}], "contextEvidence": [{"alias": "SOURCE_1", "path": "a.py"}],
            "citedAliases": ["SOURCE_1"], "answer": "pipeline answer", **extra}


def agent_record(**extra):
    return {"kind": "agent_run", "strategy": "evidence_aware_agentic_rag", "inputTokens": 900, "outputTokens": 100,
            "tokenUsageComplete": True, "llmCalls": 5, "toolCalls": 2, "iterations": 2, "repositorySnapshot": "commit:abc",
            "toolLog": [{"tool": "semantic_code_search", "latencyMs": 30.0}, {"tool": "get_callers", "latencyMs": 12.0},
                        {"tool": "read_code", "latencyMs": 5.0}],
            "toolsUsed": ["semantic_code_search", "get_callers", "read_code"], "retrievalLatencyMs": 47.0,
            "contextLatencyMs": 2.0, "generationLatencyMs": 80.0, "retrievedEvidence": [], "contextEvidence": [],
            "answer": "agent answer", **extra}


def test_normalized_record_has_all_required_fields():
    record = normalize_execution([pipeline_record()], 123.0)
    assert REQUIRED_FIELDS <= set(record)
    assert LATENCY_FIELDS <= set(record["latency"])
    assert record["latency"]["vectorMs"] == 10.0 and record["latency"]["graphMs"] == 4.0
    assert record["toolCalls"] == 0 and record["inputTokens"] == 300


def test_agent_tool_time_is_split_by_tool_category():
    record = normalize_execution([agent_record()], 200.0)
    assert record["latency"]["vectorMs"] == 30.0
    assert record["latency"]["graphMs"] == 12.0
    assert record["toolSequence"] == ["semantic_code_search", "get_callers", "read_code"]
    assert record["repositorySnapshot"] == "commit:abc"


def test_escalated_run_counts_routing_tokens_once():
    route = {"requested": "adaptive_rag", "chosen": "selective_rag", "escalatedTo": "evidence_aware_agentic_rag",
             "routingMs": 7.0, "routingInputTokens": 40, "routingOutputTokens": 10}
    record = normalize_execution([pipeline_record(route=route), agent_record(route=route)], 500.0)
    assert record["inputTokens"] == 300 + 900 - 40
    assert record["outputTokens"] == 60 + 100 - 10
    assert record["selectedStrategy"] == "selective_rag"
    assert record["effectiveStrategy"] == "evidence_aware_agentic_rag"
    assert record["escalated"] is True
    assert record["answer"] == "agent answer"
    assert record["latency"]["routingMs"] == 7.0


def test_unknown_routing_usage_makes_escalated_tokens_unavailable():
    route = {"chosen": "selective_rag", "escalatedTo": "evidence_aware_agentic_rag", "routingInputTokens": None,
             "routingOutputTokens": None}
    record = normalize_execution([pipeline_record(route=route), agent_record(route=route)], 1.0)
    assert record["inputTokens"] is None
    assert record["tokenUsageComplete"] is False


def test_old_trace_without_token_fields_is_unavailable():
    old = pipeline_record()
    for key in ("inputTokens", "outputTokens", "tokenUsageComplete", "llmCalls"):
        old.pop(key)
    record = normalize_execution([old], 1.0)
    assert record["inputTokens"] is None and record["llmCalls"] is None
    assert record["tokenUsageComplete"] is False


def test_empty_trace_list_yields_unavailable_values():
    record = normalize_execution([], 1.0)
    assert record["toolCalls"] is None and record["contextEvidence"] is None
    assert record["latency"]["generationMs"] is None


@pytest.mark.parametrize("calls,expected", [([], None), ([{"inputTokens": 3, "outputTokens": 1}], 3)])
def test_usage_totals(calls, expected):
    assert chat_service._usage_totals(calls)["inputTokens"] == expected
