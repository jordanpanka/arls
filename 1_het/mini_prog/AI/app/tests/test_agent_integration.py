from app.models.models import ChatRequest
from app.services import chat_service

from app.tests.agent_fakes import ScriptedLLM, agent_deps


def request(prompt, mode="evidence_aware_agentic_rag", ablation=None):
    return ChatRequest(prompt=prompt, userId=1, investigationId=2, projectId=3, mode=mode, ablation=ablation)


async def ask(prompt, llm, mode="evidence_aware_agentic_rag", ablation=None):
    deps, trace = agent_deps(llm)
    response = await chat_service.run_chat(request(prompt, mode, ablation), deps=deps)
    return response, trace.records[0]


async def test_a_simple_comprehension_uses_few_relevant_tools():
    llm = ScriptedLLM(
        plans=[
            {"calls": [{"tool": "find_symbol", "args": {"name": "process_payment"}}]},
            {"calls": [{"tool": "read_code", "args": {"path": "src/payment/service.py", "start_line": 10, "end_line": 40}}]},
        ],
        answers=["`PaymentService.process_payment` (src/payment/service.py:10-40) validates the order and then charges the card [SOURCE_2]."],
    )
    response, record = await ask("What does the process_payment function do?", llm)

    assert response.status == "verified"
    assert record["toolCalls"] <= 3
    assert set(record["toolsUsed"]) == {"find_symbol", "read_code"}
    assert not {"get_callers", "get_callees", "get_code_metrics", "find_quality_hotspots"} & set(record["toolsUsed"])
    assert record["stopReason"] == "evidence_sufficient"
    assert [c.alias for c in response.citations] == ["SOURCE_2"]
    cited = next(e for e in response.evidence if e.id == "SOURCE_2")
    assert cited.filePath == "src/payment/service.py"
    assert cited.highlights[0].startLine == 10 and cited.highlights[0].endLine == 40
    assert response.execution["strategy"] == "evidence_aware_agentic_rag"
    assert response.execution["trace"][1]["tool"] == "read_code"


async def test_b_dependency_analysis_resolves_symbol_and_explores_graph():
    llm = ScriptedLLM(
        plans=[
            {"calls": [{"tool": "find_symbol", "args": {"name": "PaymentService"}}]},
            {"calls": [{"tool": "get_callers", "args": {"symbol": "PaymentService"}}]},
        ],
        answers=[
            "`checkout` calls `PaymentService.process_payment` directly [GRAPH_1].\n"
            "`refund` calls `PaymentService.process_payment`; this edge is inferred from the call name [GRAPH_1]."
        ],
    )
    response, record = await ask("Which components depend on the PaymentService class?", llm)

    assert record["toolLog"][0]["tool"] == "find_symbol"
    assert "get_callers" in record["toolsUsed"]
    assert "get_code_metrics" not in record["toolsUsed"]
    assert response.status == "verified", record["verificationIssues"]
    graph = next(e for e in response.evidence if e.id == "GRAPH_1")
    edges = {(edge.source.split("::")[-1], edge.certainty) for edge in graph.edges}
    assert edges == {("checkout@5", "direct"), ("refund@3", "inferred")}
    assert record["sufficiency"]["satisfied"] == ["symbol_resolved:PaymentService", "dependency_relations:PaymentService"]


async def test_c_quality_aware_impact_combines_graph_and_metrics():
    llm = ScriptedLLM(
        plans=[
            {"calls": [{"tool": "find_symbol", "args": {"name": "PaymentService"}}]},
            {"calls": [{"tool": "get_callers", "args": {"symbol": "PaymentService", "depth": 2}}]},
            {"calls": [{"tool": "get_code_metrics", "args": {"symbols": ["checkout", "refund"]}}]},
        ],
        answers=[
            "Changing `PaymentService` affects its callers `checkout` and `refund` [GRAPH_1].\n"
            "`checkout` is the most complex affected component with cyclomatic complexity 9 measured by Lizard [METRIC_1].\n"
            "`refund` has cyclomatic complexity 3 [METRIC_2].\n"
            "Hypothesis: indirect callers beyond depth 2 may also be affected."
        ],
    )
    response, record = await ask("Which complex components would be affected if PaymentService were modified?", llm)

    assert {"get_callers", "get_code_metrics"} <= set(record["toolsUsed"])
    assert record["stopReason"] == "evidence_sufficient"
    assert response.status == "verified", record["verificationIssues"]
    assert {c.alias for c in response.citations} == {"GRAPH_1", "METRIC_1", "METRIC_2"}
    metric = next(e for e in response.evidence if e.id == "METRIC_1")
    assert metric.symbol == "checkout"
    assert next(i.value for i in metric.items if i.key == "cyclomaticComplexity") == 9
    assert all(c.evidenceIds for c in response.citations)


async def test_c_wrong_metric_number_is_caught():
    llm = ScriptedLLM(
        plans=[
            {"calls": [{"tool": "find_symbol", "args": {"name": "PaymentService"}}]},
            {"calls": [{"tool": "get_callers", "args": {"symbol": "PaymentService"}}]},
            {"calls": [{"tool": "get_code_metrics", "args": {"symbols": ["checkout"]}}]},
        ],
        answers=["`checkout` has cyclomatic complexity 25 [METRIC_1]."] * 2,
    )
    response, record = await ask("Which complex components would be affected if PaymentService were modified?", llm)
    assert response.status == "partially_verified"
    assert any(i["kind"] == "metric_mismatch" for i in record["verificationIssues"])


async def test_metrics_ablation_reports_missing_metrics_instead_of_inventing_them():
    llm = ScriptedLLM(
        plans=[
            {"calls": [{"tool": "find_symbol", "args": {"name": "PaymentService"}}]},
            {"calls": [{"tool": "get_callers", "args": {"symbol": "PaymentService"}},
                       {"tool": "get_code_metrics", "args": {"symbols": ["checkout"]}}]},
        ],
        answers=["`checkout` calls `PaymentService.process_payment` [GRAPH_1].\nMissing evidence:\n- complexity metrics were not available."],
    )
    response, record = await ask("Which complex components would be affected if PaymentService were modified?", llm, ablation="no_metrics")
    assert "get_code_metrics" not in record["toolsUsed"]
    assert record["sufficiency"]["unavailable"] == ["metrics:*"]
    assert record["rejectedCalls"] == 1
    assert not any(e.type == "metric" for e in response.evidence)
