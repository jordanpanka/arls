import pytest
from tree_sitter import Parser as TSParser
from tree_sitter_languages import get_language

from app.models.models import ChatResponse
from app.services import chat_service, rag_graph
from app.services.evidence_service import (
    build_code_evidence,
    build_graph_evidence,
    language_for_path,
    merge_highlights,
)
from app.services.file_service import FileService
from app.services.node_creator import NodeCreator
from app.services.parse_service import CodeParser
from app.models.models import ChatRequest


def result(path, start, end, score=0.8, vector="code", name="fn", kind="function"):
    return {
        "score": score,
        "matched_vector": vector,
        "payload": {
            "docName": path.split("/")[-1],
            "path": path,
            "kind": kind,
            "name": name,
            "code": f"code of {name}",
            "start_line": start,
            "end_line": end,
            "userId": 1,
            "investigationId": 2,
            "projectId": 3,
        },
    }


def raw_node(node_id, labels, **props):
    return {"id": node_id, "labels": labels, "props": props}


def test_tree_sitter_function_metadata_has_line_ranges():
    source = b"import os\n\n\ndef first():\n    return 1\n\n\ndef second(a):\n    x = a\n    return x\n"
    parser = TSParser()
    parser.set_language(get_language("python"))
    tree = parser.parse(source)

    code_parser = CodeParser()
    code_parser.select_language("src/sample.py")
    _, functions = code_parser.extract_class_function_nodes(tree.root_node)

    creator = NodeCreator()
    nodes = [n for fn in functions for n in creator.ts_node_to_llamaindex_node_function(fn, source, "src/sample.py")]

    ranges = {n.metadata["name"]: (n.metadata["start_line"], n.metadata["end_line"]) for n in nodes}
    assert ranges == {"first": (4, 5), "second": (8, 10)}


def test_doc_chunks_have_line_ranges():
    text = "line1\nline2\nline3\nline4\nline5\n"

    chunks = FileService().chunk_text_with_lines(text, chunk_length=12, redundance=0)

    assert chunks[0] == ("line1\nline2\n", 1, 2)
    assert chunks[1][1:] == (3, 4)


def test_language_for_path():
    assert language_for_path("src/Services/UserService.cs") == "csharp"
    assert language_for_path("app/main.py") == "python"
    assert language_for_path("Dockerfile") == "dockerfile"
    assert language_for_path("notes.unknownext") == "plaintext"


def test_code_evidence_groups_chunks_from_same_file():
    evidence, source_ids = build_code_evidence([
        result("src/UserService.cs", 42, 55, score=0.9, name="GetUser"),
        result("src/UserRepository.cs", 18, 25, score=0.7, name="GetById"),
        result("src/UserService.cs", 78, 91, score=0.6, vector="summary", name="Save"),
    ])

    assert [e.filePath for e in evidence] == ["src/UserService.cs", "src/UserRepository.cs"]
    first = evidence[0]
    assert first.id == "SOURCE_1"
    assert first.language == "csharp"
    assert [(h.startLine, h.endLine) for h in first.highlights] == [(42, 55), (78, 91)]
    assert first.symbols == ["GetUser", "Save"]
    assert first.retrievalType == "code, summary"
    assert first.score == 0.9
    assert source_ids == {"src/UserService.cs": "SOURCE_1", "src/UserRepository.cs": "SOURCE_2"}


def test_duplicate_highlights_are_removed():
    evidence, _ = build_code_evidence([
        result("a.py", 10, 20),
        result("a.py", 10, 20, vector="summary"),
        result("a.py", 10, 20),
    ])

    assert [(h.startLine, h.endLine) for h in evidence[0].highlights] == [(10, 20)]


def test_merge_highlights_joins_overlaps_but_keeps_nested_ranges():
    merged = merge_highlights([(42, 55), (50, 60), (61, 65), (1, 100), (70, 80), (None, None)])

    assert [(h.startLine, h.endLine) for h in merged] == [(1, 100), (42, 65), (70, 80)]


def test_code_evidence_without_lines_has_no_highlights():
    evidence, _ = build_code_evidence([result("docs/guide.pdf", None, None, kind="documentation")])

    assert evidence[0].highlights == []


def test_graph_evidence_contains_only_relevant_nodes_and_edges():
    subgraph = {
        "root": "fn",
        "nodes": [
            raw_node("fn", ["Function"], name="GetUser", filePath="src/UserService.cs", startLine=42, endLine=55),
            raw_node("callee", ["Function"], name="GetById", filePath="src/UserRepository.cs", startLine=18, endLine=25),
            raw_node("file", ["File"], path="src/UserService.cs", name="UserService.cs"),
        ],
        "edges": [
            {"source": "fn", "target": "callee", "type": "CALLS"},
            {"source": "file", "target": "fn", "type": "CONTAINS"},
            {"source": "fn", "target": "not-in-fragment", "type": "CALLS"},
        ],
    }

    graph = build_graph_evidence([subgraph, subgraph])

    assert graph.id == "GRAPH_1"
    assert {n.id for n in graph.nodes} == {"fn", "callee", "file"}
    assert {(e.source, e.target, e.type) for e in graph.edges} == {("fn", "callee", "CALLS"), ("file", "fn", "CONTAINS")}

    nodes = {n.id: n for n in graph.nodes}
    assert nodes["fn"].usedAsEvidence is True
    assert nodes["callee"].usedAsEvidence is False
    assert (nodes["callee"].filePath, nodes["callee"].startLine, nodes["callee"].endLine) == ("src/UserRepository.cs", 18, 25)
    assert nodes["file"].label == "UserService.cs"


def test_graph_evidence_node_seen_as_neighbor_and_root_is_evidence():
    a = {"root": "a", "nodes": [raw_node("a", ["Function"], name="a"), raw_node("b", ["Function"], name="b")],
         "edges": [{"source": "a", "target": "b", "type": "CALLS"}]}
    b = {"root": "b", "nodes": [raw_node("b", ["Function"], name="b")], "edges": []}

    graph = build_graph_evidence([a, b])

    assert all(n.usedAsEvidence for n in graph.nodes)


def test_graph_evidence_is_none_without_nodes():
    assert build_graph_evidence([]) is None


@pytest.mark.asyncio
async def test_prepare_evidence_and_build_context_share_source_ids():
    state = {
        "top_results": [result("src/a.py", 3, 9, name="alpha"), result("src/b.py", 1, 4, score=0.5, name="beta")],
        "graph_subgraphs": [],
    }

    state = await rag_graph.prepare_evidence(state)
    state = await rag_graph.build_context(state)

    assert [e["id"] for e in state["evidence"]] == ["SOURCE_1", "SOURCE_2"]
    assert state["graph_evidence"] is None
    assert "[SOURCE_1]\nFile: src/a.py\nLines: 3-9\nSymbol: alpha" in state["context"]
    assert "[SOURCE_2]\nFile: src/b.py" in state["context"]


@pytest.mark.asyncio
async def test_search_knowledge_graph_keeps_structured_subgraph(monkeypatch):
    subgraph = {
        "root": "fn",
        "nodes": [raw_node("fn", ["Function"], name="alpha", filePath="src/a.py"),
                  raw_node("x", ["Function"], name="beta", filePath="src/b.py")],
        "edges": [{"source": "fn", "target": "x", "type": "CALLS"}],
    }

    class FakeNeo4j:
        calls = []

        def get_function_subgraph(self, *args):
            FakeNeo4j.calls.append(args)
            return subgraph

        def get_class_subgraph(self, *args):
            return None

        def close(self):
            pass

    monkeypatch.setattr(rag_graph, "Neo4jService", FakeNeo4j)

    state = await rag_graph.search_knowledge_graph({
        "top_results": [result("src/a.py", 1, 2, name="alpha"), result("src/a.py", 1, 2, name="alpha", vector="summary")]
    })

    assert FakeNeo4j.calls == [(1, 2, 3, "alpha", "src/a.py")]
    assert state["graph_subgraphs"] == [subgraph]
    assert "alpha -[CALLS]-> beta" in state["graph_context"][0]


@pytest.mark.asyncio
async def test_chat_response_serializes_evidence(monkeypatch):
    async def fake_invoke(state):
        code, _ = build_code_evidence([result("src/a.py", 3, 9)])
        graph = build_graph_evidence([{"root": "n", "nodes": [raw_node("n", ["Class"], name="A")], "edges": []}])
        return {"answer": "It works [SOURCE_1].", "evidence": [code[0].model_dump(), graph.model_dump()]}

    monkeypatch.setattr(chat_service.rag_graph, "ainvoke", fake_invoke)

    response = await chat_service.send_message_async_langgraph(
        ChatRequest(prompt="?", userId=1, investigationId=2, projectId=3)
    )

    data = response.data
    assert data["answer"] == "It works [SOURCE_1]."
    code, graph = data["evidence"]
    assert code["type"] == "code"
    assert code["fileId"] is None
    assert code["highlights"] == [{"startLine": 3, "endLine": 9}]
    assert graph["type"] == "graph"
    assert graph["nodes"][0]["usedAsEvidence"] is True
    assert ChatResponse.model_validate(data).evidence[1].type == "graph"
