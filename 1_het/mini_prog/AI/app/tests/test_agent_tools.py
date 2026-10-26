import asyncio
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.agents.config import AgentConfig
from app.tools.base import ResultCache, ToolResult, ToolSpec, execute_tool, safe_relative_path
from app.tools.code_graph import CodeGraph
from app.tools.code_tools import CODE_TOOLS, ReadCodeArgs
from app.tools.graph_tools import GRAPH_TOOLS, SymbolDepthArgs
from app.tools.metrics_tools import METRICS_TOOLS
from app.tools.registry import as_langchain_tools, build_registry
from app.tools.vector_tools import VECTOR_TOOLS

from app.tests.agent_fakes import (
    SCOPE,
    FakeMetrics,
    FakeSource,
    FakeVectors,
    GraphLoader,
    graph_data,
    qdrant_hit,
    tool_context,
)

TOOLS = {spec.name: spec for spec in CODE_TOOLS + VECTOR_TOOLS + GRAPH_TOOLS + METRICS_TOOLS}


async def run(name, args, ctx=None, cache=None):
    ctx = ctx or tool_context()
    result, _ = await execute_tool(TOOLS[name], ctx, args, cache=cache)
    return result


@pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "C:\\Windows\\win.ini", "src/../../x.py", "~/.ssh/id_rsa", "src//a.py"])
def test_paths_outside_repository_are_rejected(path):
    with pytest.raises(ValueError):
        safe_relative_path(path)


def test_relative_paths_are_normalized():
    assert safe_relative_path(".\\src\\api\\checkout.py") == "src/api/checkout.py"


@pytest.mark.parametrize("name,args", [
    ("read_code", {"path": "../secret.py"}),
    ("read_code", {"path": "src/a.py", "start_line": 20, "end_line": 10}),
    ("get_callers", {"symbol": "process_payment", "depth": 4}),
    ("find_symbol", {"name": "x; MATCH (n) DETACH DELETE n"}),
    ("keyword_code_search", {"pattern": "([a-z", "is_regex": True}),
    ("keyword_code_search", {"pattern": "x", "path_glob": "../**"}),
    ("semantic_code_search", {"query": "auth", "top_k": 50}),
    ("get_code_metrics", {}),
    ("find_symbol", {"name": "a", "unexpected": True}),
])
async def test_invalid_tool_input_is_a_typed_error(name, args):
    source = FakeSource()
    result = await run(name, args, tool_context(source=source))
    assert result.error is not None
    assert result.error.kind == "invalid_input"
    assert result.evidence == []
    assert source.reads == [] and source.searches == []


def test_depth_schema_rejects_unbounded_traversal():
    with pytest.raises(ValidationError):
        SymbolDepthArgs(symbol="f", depth=10)
    with pytest.raises(ValidationError):
        ReadCodeArgs(path="/abs.py")


async def test_scope_ids_are_passed_to_every_backend():
    source, metrics, vectors, graph = FakeSource(), FakeMetrics(), FakeVectors(), GraphLoader()
    ctx = tool_context(source=source, metrics=metrics, vectors=vectors, graph=graph)
    await run("read_code", {"path": "src/api/checkout.py", "start_line": 1, "end_line": 5}, ctx)
    await run("keyword_code_search", {"pattern": "charge_card"}, ctx)
    await run("semantic_code_search", {"query": "payment"}, ctx)
    await run("get_callers", {"symbol": "process_payment"}, ctx)
    await run("find_quality_hotspots", {"focus": "complexity"}, ctx)

    assert {r[0] for r in source.reads} == {SCOPE}
    assert {s[0] for s in source.searches} == {SCOPE}
    assert {c[0] for c in vectors.calls} == {SCOPE}
    assert graph.loads == [SCOPE]
    assert {(q.user_id, q.investigation_id, q.project_id) for q in metrics.queries} == {(1, 2, 3)}


async def test_semantic_results_are_normalized_with_code_not_summary():
    vectors = FakeVectors(hits=[
        qdrant_hit("src/payment/service.py", 10, 40, "process_payment", score=0.9),
        qdrant_hit("src/other.py", 1, 5, "foreign", project=99),
    ])
    result = await run("semantic_code_search", {"query": "process a payment", "top_k": 5}, tool_context(vectors=vectors))

    assert result.error is None
    assert len(result.evidence) == 1
    item = result.evidence[0]
    assert item.source_type == "code_chunk"
    assert item.file_path == "src/payment/service.py"
    assert (item.start_line, item.end_line) == (10, 40)
    assert item.content == "def process_payment(): ..."
    assert item.metadata["summary"] == "summary of process_payment"
    assert item.retrieval_score == pytest.approx(0.9)
    assert item.produced_by == ["semantic_code_search"]


async def test_find_symbol_distinguishes_identical_names():
    result = await run("find_symbol", {"name": "validate_input"})

    ids = sorted(e.symbol_id for e in result.evidence)
    assert ids == [
        "src/payment/service.py::method::PaymentService.validate_input@42",
        "src/utils/validation.py::function::validate_input@1",
    ]
    assert "ambiguous" in result.summary
    method = next(e for e in result.evidence if e.symbol_kind == "method")
    assert method.metadata["containingClass"] == "PaymentService"


async def test_find_symbol_accepts_qualified_names_and_symbol_ids():
    qualified = await run("find_symbol", {"name": "PaymentService.validate_input"})
    assert [e.file_path for e in qualified.evidence] == ["src/payment/service.py"]

    by_id = await run("find_symbol", {"name": qualified.evidence[0].symbol_id})
    assert by_id.evidence[0].symbol_id == qualified.evidence[0].symbol_id


async def test_find_symbol_not_found_is_typed_and_falls_back_to_vector_payload():
    vectors = FakeVectors(hits=[qdrant_hit("src/legacy.py", 3, 9, "legacy_helper")])
    found = await run("find_symbol", {"name": "legacy_helper"}, tool_context(vectors=vectors))
    assert found.evidence[0].metadata["resolvedFrom"] == "vector_payload"

    missing = await run("find_symbol", {"name": "doesNotExist"})
    assert missing.error.kind == "not_found"


async def test_read_code_returns_bounded_line_numbered_source():
    config = replace(AgentConfig(), max_read_lines=5)
    result = await run("read_code", {"path": "src/payment/service.py", "start_line": 10, "end_line": 40}, tool_context(config=config))

    item = result.evidence[0]
    assert item.source_type == "code_range"
    assert (item.start_line, item.end_line) == (10, 14)
    assert item.content.splitlines()[0] == "10 |     def process_payment(self, order):"
    assert result.truncated is True


async def test_read_code_falls_back_to_indexed_chunks_when_raw_file_missing():
    vectors = FakeVectors(hits=[qdrant_hit("src/zipped.py", 1, 8, "zipped_fn")])
    result = await run("read_code", {"path": "src/zipped.py"}, tool_context(vectors=vectors))
    assert result.error is None
    assert result.evidence[0].metadata["fallback"] == "indexed_chunks"

    missing = await run("read_code", {"path": "src/none.py"})
    assert missing.error.kind == "not_found"


async def test_keyword_search_returns_locations():
    result = await run("keyword_code_search", {"pattern": "charge_card"})
    paths = {(e.file_path, e.start_line) for e in result.evidence}
    assert ("src/payment/service.py", 13) in paths
    assert ("src/payment/gateway.py", 1) in paths
    assert all(e.source_type == "keyword_match" for e in result.evidence)


def test_call_resolution_distinguishes_direct_inferred_and_unresolved():
    graph = CodeGraph(graph_data())
    assert graph.out_edges["f3"]["f1"] == "direct"
    assert graph.out_edges["f4"]["f1"] == "inferred"
    assert graph.out_edges["f1"]["f6"] == "inferred"
    unresolved = {u.name: u.candidates for u in graph.unresolved["f1"]}
    assert unresolved == {"self.validate_input": 2, "logger.info": 0}


async def test_get_callers_returns_relations_with_certainty():
    result = await run("get_callers", {"symbol": "process_payment"})

    relations = [e for e in result.evidence if e.relation]
    assert {(r.relation.source_label, r.certainty) for r in relations} == {("checkout", "direct"), ("refund", "inferred")}
    assert all(r.relation.target_label == "PaymentService.process_payment" for r in relations)
    root = next(e for e in result.evidence if e.source_type == "graph_node")
    assert root.metadata["relationCount"] == 2
    assert len({e.group for e in result.evidence}) == 1


async def test_get_callees_reports_unresolved_calls_without_inventing_targets():
    result = await run("get_callees", {"symbol": "process_payment"})
    targets = {e.relation.target_label for e in result.evidence if e.relation}
    assert targets == {"charge_card"}
    root = next(e for e in result.evidence if e.source_type == "graph_node")
    assert {u["name"] for u in root.metadata["unresolvedCalls"]} == {"self.validate_input", "logger.info"}


async def test_graph_depth_is_capped_by_configuration():
    config = replace(AgentConfig(), max_graph_depth=1)
    deep = await run("get_callees", {"symbol": "checkout", "depth": 3}, tool_context())
    shallow = await run("get_callees", {"symbol": "checkout", "depth": 3}, tool_context(config=config))
    assert max(e.relation.depth for e in deep.evidence if e.relation) == 2
    assert max(e.relation.depth for e in shallow.evidence if e.relation) == 1


async def test_trace_dependencies_marks_imports_as_inferred():
    result = await run("trace_dependencies", {"target": "src/payment/service.py", "direction": "both"})
    depends = {(e.relation.source, e.relation.target) for e in result.evidence if e.relation and e.relation.type == "DEPENDS_ON"}
    assert ("src/api/checkout.py::file", "src/payment/service.py::file") in depends
    assert ("src/payment/service.py::file", "src/payment/gateway.py::file") in depends
    imports = [e for e in result.evidence if e.relation and e.relation.type == "IMPORTS"]
    assert imports and all(e.certainty == "inferred" for e in imports)


async def test_find_call_path():
    found = await run("find_call_path", {"from_symbol": "checkout", "to_symbol": "charge_card"})
    chain = [e.relation.target_label for e in found.evidence]
    assert chain == ["PaymentService.process_payment", "charge_card"]

    none = await run("find_call_path", {"from_symbol": "charge_card", "to_symbol": "checkout"})
    assert all(e.metadata.get("pathFound") is False for e in none.evidence)


async def test_graph_unavailable_is_a_typed_error():
    result = await run("get_callers", {"symbol": "process_payment"}, tool_context(graph=GraphLoader(fail=True)))
    assert result.error.kind == "unavailable"
    assert result.evidence == []


async def test_metrics_are_returned_with_analyzer_and_never_fabricated():
    result = await run("get_code_metrics", {"symbols": ["process_payment"]})
    item = result.evidence[0]
    values = {m.key: (m.value, m.analyzer) for m in item.metric.items}
    assert values["cyclomaticComplexity"] == (14, "lizard")
    assert values["fanIn"] == (2, "neo4j-graph")
    assert item.metric.analysis_id == 7

    missing = await run("get_code_metrics", {"symbols": ["process_payment"]}, tool_context(metrics=FakeMetrics(available=False)))
    assert missing.error.kind == "unavailable"
    assert missing.evidence == []


async def test_hotspots_are_ranked():
    result = await run("find_quality_hotspots", {"focus": "complexity", "limit": 3})
    ranked = [(e.metric.symbol, e.metadata["rank"]) for e in result.evidence if e.metadata.get("rank") and e.metric.scope == "function"]
    assert ranked == [("PaymentService.process_payment", 1), ("checkout", 2)]


async def test_timeouts_and_crashes_become_typed_errors():
    async def slow(ctx, args):
        await asyncio.sleep(1)
        return ToolResult()

    async def boom(ctx, args):
        raise RuntimeError("secret connection string")

    spec = ToolSpec("slow", "", SymbolDepthArgs, slow, "graph")
    ctx = tool_context(config=replace(AgentConfig(), tool_timeout_s=0.01))
    timed_out, _ = await execute_tool(spec, ctx, {"symbol": "a"})
    assert timed_out.error.kind == "timeout"

    crashed, _ = await execute_tool(ToolSpec("boom", "", SymbolDepthArgs, boom, "graph"), tool_context(), {"symbol": "a"})
    assert crashed.error.kind == "unavailable"


async def test_large_outputs_are_truncated():
    config = replace(AgentConfig(), max_tool_output_chars=300, max_read_lines=200)
    result = await run("read_code", {"path": "src/payment/service.py"}, tool_context(config=config))
    assert result.truncated is True
    assert len(result.evidence[0].content) < 400


async def test_deterministic_results_are_cached_per_snapshot():
    graph = GraphLoader()
    cache = ResultCache()
    ctx = tool_context(graph=graph)
    first = await run("get_callers", {"symbol": "process_payment"}, ctx, cache=cache)
    second = await run("get_callers", {"symbol": "process_payment"}, ctx, cache=cache)
    assert second.metadata.get("cached") is True
    assert first.evidence == second.evidence


def test_registry_respects_ablation_flags():
    full = build_registry(AgentConfig())
    no_graph = build_registry(replace(AgentConfig(), enable_graph_tools=False, enable_metrics_tools=False))
    assert {"get_callers", "find_quality_hotspots"} <= set(full)
    assert "get_file_history" not in full
    assert not {"get_callers", "trace_dependencies", "get_code_metrics"} & set(no_graph)
    assert "get_file_history" in build_registry(replace(AgentConfig(), enable_history_tools=True))


async def test_tools_are_exposed_as_langchain_structured_tools():
    tools = {t.name: t for t in as_langchain_tools(build_registry(AgentConfig()), tool_context())}
    output = await tools["find_symbol"].ainvoke({"name": "checkout"})
    assert output["evidence"][0]["symbol_id"] == "src/api/checkout.py::function::checkout@5"
