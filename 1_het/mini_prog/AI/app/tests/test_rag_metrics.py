import pytest

from app.models.models import ChatResponse
from app.services import rag_graph


def result(path, start, end, name="fn", kind="function", score=0.8):
    return {
        "score": score,
        "matched_vector": "code",
        "payload": {
            "docName": path.split("/")[-1],
            "path": path,
            "kind": kind,
            "name": name,
            "code": f"code of {name}",
            "start_line": start,
            "end_line": end,
        },
    }


# What the .NET internal endpoint returns: values exactly as stored for the analysis.
STORED = {
    "available": True,
    "analysis": {"analysisId": 42, "status": "Completed", "completedAt": "2026-10-03T10:00:00Z", "commitSha": "abc123def4567890"},
    "thresholds": {
        "complexityBands": [
            {"category": "Low", "max": 5}, {"category": "Moderate", "max": 10},
            {"category": "High", "max": 20}, {"category": "VeryHigh", "max": None},
        ],
        "longFunctionNloc": 50,
        "manyParameters": 5,
    },
    "repository": None,
    "files": [{
        "path": "src/UserService.cs", "fileId": 7, "nloc": 846, "functionCount": 23,
        "averageComplexity": 8.2, "maxComplexity": 27, "complexityCategory": "VeryHigh",
        "fanIn": 21, "fanOut": 14, "highComplexityFunctionCount": 5,
    }],
    "functions": [{
        "filePath": "src/UserService.cs", "fileId": 7, "name": "CreateUser", "className": "UserService",
        "startLine": 120, "endLine": 204, "nloc": 84, "cyclomaticComplexity": 27,
        "complexityCategory": "VeryHigh", "parameterCount": 6, "tokenCount": 400, "length": 85,
    }],
    "hotspotFiles": [],
    "hotspotFunctions": [],
}


class FakeProvider:
    def __init__(self, payload=STORED):
        self.payload = payload
        self.queries = []

    async def fetch(self, query):
        self.queries.append(query)
        return self.payload


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(rag_graph, "metrics_provider", fake)
    return fake


async def run_tail(state):
    """retrieve_metrics -> prepare_evidence -> build_context, as wired in the graph."""
    state = {**state, **rag_graph.plan_metrics(state)}
    state = await rag_graph.retrieve_metrics(state)
    state = await rag_graph.prepare_evidence(state)
    return await rag_graph.build_context(state)


BASE = {"user_id": 1, "investigation_id": 2, "project_id": 3}


@pytest.mark.asyncio
async def test_non_metrics_question_never_queries_metrics(provider):
    state = await run_tail({
        **BASE,
        "question_en": "What does CreateUser return?",
        "top_results": [result("src/UserService.cs", 120, 204, name="CreateUser")],
    })

    assert provider.queries == []
    assert "CODE METRICS" not in state["context"]
    assert "SOURCE CODE" not in state["context"]
    assert all(e["type"] != "metric" for e in state["evidence"])


@pytest.mark.asyncio
async def test_entity_question_requests_only_retrieved_entities(provider):
    state = await run_tail({
        **BASE,
        "question_en": "Why is UserService difficult to maintain?",
        "top_results": [
            result("src/UserService.cs", 120, 204, name="CreateUser"),
            result("docs/README.md", 1, 10, name="", kind="documentation"),
        ],
    })

    query = provider.queries[0]
    assert query.include_repository is False
    assert query.paths == ["src/UserService.cs"]
    assert [(s.path, s.name, s.startLine) for s in query.symbols] == [("src/UserService.cs", "CreateUser", 120)]
    assert (query.user_id, query.investigation_id, query.project_id) == (1, 2, 3)


@pytest.mark.asyncio
async def test_metric_values_in_context_and_evidence_come_from_stored_analysis(provider):
    state = await run_tail({
        **BASE,
        "question_en": "Why is UserService difficult to maintain?",
        "top_results": [result("src/UserService.cs", 120, 204, name="CreateUser")],
    })

    context = state["context"]
    assert context.startswith("===== SOURCE CODE =====")
    assert "===== CODE METRICS" in context
    assert "[METRIC_1] File: UserService.cs (src/UserService.cs)" in context
    assert "- Maximum cyclomatic complexity: 27 (category: VeryHigh)" in context
    assert "- Fan-in (files depending on it): 21" in context
    assert "[METRIC_2] Function: UserService.CreateUser() in src/UserService.cs:120-204" in context
    assert "- Parameters: 6" in context
    assert "analysis #42" in context

    metrics = [e for e in state["evidence"] if e["type"] == "metric"]
    assert [m["id"] for m in metrics] == ["METRIC_1", "METRIC_2"]
    file_items = {i["key"]: i["value"] for i in metrics[0]["items"]}
    assert file_items["averageComplexity"] == 8.2 and file_items["fanOut"] == 14
    assert metrics[1]["startLine"] == 120 and metrics[1]["fileId"] == "7"

    # Serializes through the public response model (discriminated union).
    ChatResponse(answer="x", evidence=state["evidence"])


@pytest.mark.asyncio
async def test_repository_question_asks_for_rankings_even_without_vector_hits(monkeypatch):
    payload = {
        **STORED,
        "files": [], "functions": [],
        "repository": {"totalFiles": 120, "totalNloc": 15000, "averageComplexity": 3.456, "dependencyCount": None},
        "hotspotFiles": STORED["files"],
    }
    fake = FakeProvider(payload)
    monkeypatch.setattr(rag_graph, "metrics_provider", fake)

    state = await run_tail({**BASE, "question_en": "Which files are the most complex?", "top_results": []})

    assert fake.queries[0].include_repository is True
    assert fake.queries[0].focus == "complexity"
    assert "[METRIC_1] Repository: Repository summary" in state["context"]
    assert "- Average cyclomatic complexity: 3.46" in state["context"]
    assert "File dependencies" not in state["context"]
    assert "SOURCE CODE" not in state["context"]


@pytest.mark.asyncio
async def test_entity_question_without_retrieved_entities_skips_backend(provider):
    state = await run_tail({**BASE, "question_en": "Why is UserService difficult to maintain?", "top_results": []})

    assert provider.queries == []
    assert state["context"] == ""


@pytest.mark.asyncio
async def test_unavailable_metrics_leave_the_answer_path_untouched(monkeypatch):
    monkeypatch.setattr(rag_graph, "metrics_provider", FakeProvider(payload=None))

    state = await run_tail({
        **BASE,
        "question_en": "Why is UserService difficult to maintain?",
        "top_results": [result("src/UserService.cs", 120, 204, name="CreateUser")],
    })

    assert "CODE METRICS" not in state["context"]
    assert state["metrics_context"] == ""


def test_metrics_rules_only_reach_the_prompt_with_metrics():
    assert "CODE METRICS" in rag_graph.METRICS_RULES
    graph = rag_graph.rag_graph.get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("retrieve_metrics", "prepare_evidence") in edges
    assert ("rerank_results", "retrieve_metrics") in edges
