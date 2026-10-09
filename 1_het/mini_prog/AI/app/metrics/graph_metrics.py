"""Structural metrics computed from the existing Tree-sitter knowledge graph.

Only ``CALLS`` edges define a dependency. ``CONTAINS`` is structural (a file
or class owning a member) and ``IMPORTS`` points at raw import text that often
names external packages, so imports are reported separately as ``importCount``
and never mixed into fan-in/fan-out.

``save_call_relation`` stores a callee by its raw call text (``self.helper``)
without a location, so a target is resolved the same way the evidence graph
does it (``Neo4jService._resolve_call_targets``): a callee that already is a
located definition is used directly, otherwise its short name must match
exactly one located ``Function`` in the project. Ambiguous names are excluded
rather than guessed, and unmatched names (library calls) count as unresolved.

Definitions:
- function fan-out: distinct resolved project functions it calls (self-calls excluded)
- function fan-in:  distinct project functions that call it (self-calls excluded)
- file fan-out:     distinct other project files whose functions this file's functions call
- file fan-in:      distinct other project files whose functions call into this file
- dependency count: distinct file -> file edges
- cycles:           strongly connected components of the file graph with more than one file
- dependency depth: longest path, in edges, of the file graph after collapsing cycles
"""
import time
from collections import defaultdict
from dataclasses import dataclass

from app.metrics.models import FileGraphMetrics, FunctionGraphMetrics, GraphMetricsResult
from app.services.evidence_service import normalize_path, short_symbol_name

# Cycles are listed for the dashboard and the context; the count is always complete.
MAX_REPORTED_CYCLES = 20


@dataclass
class GraphFunction:
    id: str
    name: str
    path: str
    start_line: int | None = None


@dataclass
class GraphCall:
    caller_id: str
    callee_id: str
    callee_name: str
    callee_path: str | None


@dataclass
class GraphFile:
    path: str
    import_count: int = 0


def resolve_calls(functions: list[GraphFunction], calls: list[GraphCall]):
    """Returns (resolved caller->callee id pairs, unresolved count per caller id, ambiguous count)."""
    by_id = {f.id: f for f in functions}
    by_short_name: dict[str, list[str]] = defaultdict(list)
    for f in functions:
        by_short_name[short_symbol_name(f.name)].append(f.id)

    resolved: set[tuple[str, str]] = set()
    unresolved: dict[str, int] = defaultdict(int)
    ambiguous = 0

    for call in calls:
        if call.caller_id not in by_id:
            continue

        if call.callee_path and call.callee_id in by_id:
            target = call.callee_id
        else:
            candidates = by_short_name.get(short_symbol_name(call.callee_name), [])
            if len(candidates) != 1:
                if candidates:
                    ambiguous += 1
                unresolved[call.caller_id] += 1
                continue
            target = candidates[0]

        if target != call.caller_id:
            resolved.add((call.caller_id, target))

    return resolved, unresolved, ambiguous


def strongly_connected_components(nodes: list[str], edges: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan, so long dependency chains cannot hit the recursion limit.

    Components come out in reverse topological order (successors first).
    """
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0

    def visit(node: str):
        nonlocal counter
        index_of[node] = low[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)

    for root in nodes:
        if root in index_of:
            continue
        visit(root)
        work = [(root, iter(sorted(edges.get(root, ()))))]

        while work:
            node, children = work[-1]
            descended = False
            for child in children:
                if child not in index_of:
                    visit(child)
                    work.append((child, iter(sorted(edges.get(child, ())))))
                    descended = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index_of[child])
            if descended:
                continue

            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])

            if low[node] == index_of[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))

    return components


def longest_path_length(components: list[list[str]], edges: dict[str, set[str]]) -> int:
    component_of = {node: i for i, component in enumerate(components) for node in component}
    dag: dict[int, set[int]] = defaultdict(set)
    for source, targets in edges.items():
        for target in targets:
            a, b = component_of[source], component_of[target]
            if a != b:
                dag[a].add(b)

    # Successors precede their predecessors in Tarjan order, so one pass suffices.
    depth = [0] * len(components)
    for i in range(len(components)):
        depth[i] = max((depth[j] + 1 for j in dag.get(i, ())), default=0)
    return max(depth, default=0)


def compute_graph_metrics(
    functions: list[GraphFunction],
    calls: list[GraphCall],
    files: list[GraphFile],
) -> GraphMetricsResult:
    functions = [
        GraphFunction(f.id, f.name, normalize_path(f.path), f.start_line)
        for f in functions if f.path
    ]
    by_id = {f.id: f for f in functions}
    resolved, unresolved, ambiguous = resolve_calls(functions, calls)

    callees: dict[str, set[str]] = defaultdict(set)
    callers: dict[str, set[str]] = defaultdict(set)
    file_edges: dict[str, set[str]] = defaultdict(set)
    for caller, callee in resolved:
        callees[caller].add(callee)
        callers[callee].add(caller)
        source, target = by_id[caller].path, by_id[callee].path
        if source != target:
            file_edges[source].add(target)

    file_in: dict[str, set[str]] = defaultdict(set)
    for source, targets in file_edges.items():
        for target in targets:
            file_in[target].add(source)

    import_counts = {normalize_path(f.path): f.import_count for f in files if f.path}
    all_paths = sorted(set(import_counts) | {f.path for f in functions})

    components = strongly_connected_components(all_paths, file_edges)
    cycles = [c for c in components if len(c) > 1]

    return GraphMetricsResult(
        analyzer="neo4j-knowledge-graph",
        files=[
            FileGraphMetrics(
                path=path,
                fanIn=len(file_in.get(path, ())),
                fanOut=len(file_edges.get(path, ())),
                importCount=import_counts.get(path, 0),
            )
            for path in all_paths
        ],
        functions=[
            FunctionGraphMetrics(
                path=f.path,
                name=f.name,
                startLine=f.start_line,
                fanIn=len(callers.get(f.id, ())),
                fanOut=len(callees.get(f.id, ())),
                unresolvedCalls=unresolved.get(f.id, 0),
            )
            for f in functions
        ],
        dependencyCount=sum(len(targets) for targets in file_edges.values()),
        cycleCount=len(cycles),
        cycles=sorted(cycles, key=len, reverse=True)[:MAX_REPORTED_CYCLES],
        maxDependencyDepth=longest_path_length(components, file_edges),
        ambiguousCalls=ambiguous,
        unresolvedCalls=sum(unresolved.values()),
    )


FUNCTIONS_QUERY = """
MATCH (fn:Function {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
WHERE fn.filePath IS NOT NULL
RETURN elementId(fn) AS id, fn.name AS name, fn.filePath AS path, fn.startLine AS startLine
"""

CALLS_QUERY = """
MATCH (caller:Function {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
      -[:CALLS]->(callee:Function)
WHERE caller.filePath IS NOT NULL
RETURN elementId(caller) AS callerId, elementId(callee) AS calleeId,
       callee.name AS calleeName, callee.filePath AS calleePath
"""

FILES_QUERY = """
MATCH (f:File {user_id: $user_id, investigation_id: $investigation_id, projectId: $project_id})
OPTIONAL MATCH (f)-[:IMPORTS]->(m:Module)
RETURN f.path AS path, count(DISTINCT m) AS importCount
"""


class Neo4jGraphMetricsAnalyzer:
    name = "neo4j-knowledge-graph"

    def __init__(self, driver_factory=None):
        self._driver_factory = driver_factory

    def _driver(self):
        if self._driver_factory:
            return self._driver_factory()
        from neo4j import GraphDatabase
        from app.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
        return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    def analyze(self, user_id: int, investigation_id: int, project_id: int) -> GraphMetricsResult:
        started = time.perf_counter()
        params = {"user_id": user_id, "investigation_id": investigation_id, "project_id": project_id}

        driver = self._driver()
        try:
            with driver.session() as session:
                functions = [
                    GraphFunction(r["id"], r["name"] or "", r["path"], r["startLine"])
                    for r in session.run(FUNCTIONS_QUERY, params)
                ]
                calls = [
                    GraphCall(r["callerId"], r["calleeId"], r["calleeName"] or "", r["calleePath"])
                    for r in session.run(CALLS_QUERY, params)
                ]
                files = [
                    GraphFile(r["path"], r["importCount"] or 0)
                    for r in session.run(FILES_QUERY, params)
                ]
        finally:
            driver.close()

        result = compute_graph_metrics(functions, calls, files)
        result.durationMs = (time.perf_counter() - started) * 1000
        return result
