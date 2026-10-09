from unittest.mock import MagicMock

from app.metrics.graph_metrics import (
    GraphCall,
    GraphFile,
    GraphFunction,
    Neo4jGraphMetricsAnalyzer,
    compute_graph_metrics,
    strongly_connected_components,
)

# Known graph:
#   a.py: run()      -> b.py: save()  (stub callee "self.save", resolved by unique name)
#   a.py: run()      -> c.py: load()  (callee already a located definition)
#   b.py: save()     -> c.py: load()
#   c.py: load()     -> b.py: save()  (b <-> c cycle)
#   a.py: run()      -> "print"       (external, unresolved)
#   a.py: run()      -> "validate"    (defined twice -> ambiguous)
#   a.py: run()      -> run()         (recursion, ignored)
FUNCTIONS = [
    GraphFunction("f-run", "run", "a.py", 1),
    GraphFunction("f-save", "save", "b.py", 3),
    GraphFunction("f-load", "load", "c.py", 5),
    GraphFunction("f-val1", "validate", "b.py", 10),
    GraphFunction("f-val2", "validate", "c.py", 12),
]
CALLS = [
    GraphCall("f-run", "stub-save", "self.save", None),
    GraphCall("f-run", "f-load", "load", "c.py"),
    GraphCall("f-save", "stub-load", "load", None),
    GraphCall("f-load", "stub-save2", "repo.save", None),
    GraphCall("f-run", "stub-print", "print", None),
    GraphCall("f-run", "stub-validate", "validate", None),
    GraphCall("f-run", "f-run", "run", "a.py"),
]
FILES = [GraphFile("a.py", 2), GraphFile("b.py", 0), GraphFile("c.py", 1), GraphFile("d.py", 0)]


def by_path(result):
    return {f.path: f for f in result.files}


def by_name(result):
    return {(f.path, f.name): f for f in result.functions}


def test_function_fan_in_and_fan_out_use_resolved_calls_only():
    result = compute_graph_metrics(FUNCTIONS, CALLS, FILES)
    functions = by_name(result)

    run = functions[("a.py", "run")]
    assert run.fanOut == 2              # save, load; print/validate/recursion excluded
    assert run.fanIn == 0
    assert run.unresolvedCalls == 2     # print + ambiguous validate

    assert functions[("b.py", "save")].fanIn == 2   # run, load
    assert functions[("c.py", "load")].fanIn == 2   # run, save
    assert result.ambiguousCalls == 1
    assert result.unresolvedCalls == 2


def test_file_fan_in_fan_out_and_imports():
    files = by_path(compute_graph_metrics(FUNCTIONS, CALLS, FILES))

    assert (files["a.py"].fanIn, files["a.py"].fanOut, files["a.py"].importCount) == (0, 2, 2)
    assert (files["b.py"].fanIn, files["b.py"].fanOut) == (2, 1)
    assert (files["c.py"].fanIn, files["c.py"].fanOut) == (2, 1)
    # Files without functions are still reported, with zero dependencies.
    assert (files["d.py"].fanIn, files["d.py"].fanOut) == (0, 0)


def test_dependency_count_cycles_and_depth():
    result = compute_graph_metrics(FUNCTIONS, CALLS, FILES)

    # a->b, a->c, b->c, c->b
    assert result.dependencyCount == 4
    assert result.cycleCount == 1
    assert result.cycles == [["b.py", "c.py"]]
    # a -> {b,c} collapsed into one component: one edge deep.
    assert result.maxDependencyDepth == 1


def test_depth_of_a_chain_without_cycles():
    components = strongly_connected_components(["a", "b", "c", "d"], {"a": {"b"}, "b": {"c"}, "c": {"d"}})
    assert all(len(c) == 1 for c in components)

    functions = [GraphFunction(f"f{i}", f"fn{i}", f"{p}.py") for i, p in enumerate("abcd")]
    calls = [GraphCall("f0", "f1", "fn1", "b.py"), GraphCall("f1", "f2", "fn2", "c.py"), GraphCall("f2", "f3", "fn3", "d.py")]
    result = compute_graph_metrics(functions, calls, [])

    assert result.maxDependencyDepth == 3
    assert result.cycleCount == 0


def test_empty_graph_produces_empty_metrics():
    result = compute_graph_metrics([], [], [])

    assert result.files == [] and result.functions == []
    assert result.dependencyCount == 0 and result.maxDependencyDepth == 0


def test_neo4j_analyzer_reads_the_project_subgraph():
    session = MagicMock()
    session.run.side_effect = [
        [{"id": "f1", "name": "run", "path": "a.py", "startLine": 1},
         {"id": "f2", "name": "save", "path": "b.py", "startLine": 2}],
        [{"callerId": "f1", "calleeId": "s1", "calleeName": "save", "calleePath": None}],
        [{"path": "a.py", "importCount": 3}],
    ]
    driver = MagicMock()
    driver.session.return_value.__enter__.return_value = session

    result = Neo4jGraphMetricsAnalyzer(driver_factory=lambda: driver).analyze(7, 8, 9)

    params = session.run.call_args_list[0].args[1]
    assert params == {"user_id": 7, "investigation_id": 8, "project_id": 9}
    assert by_path(result)["a.py"].fanOut == 1
    assert by_path(result)["a.py"].importCount == 3
    driver.close.assert_called_once()
