import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, field

from app.services.evidence_service import normalize_path, short_symbol_name


@dataclass
class SymbolNode:
    id: str
    name: str
    kind: str
    path: str
    start_line: int | None = None
    end_line: int | None = None
    class_name: str | None = None
    bases: list[str] = field(default_factory=list)
    type_kind: str | None = None
    owner_id: str | None = None
    events: list[str] = field(default_factory=list)
    raises: list[str] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        if self.class_name and self.kind == "method":
            return f"{self.class_name}.{short_symbol_name(self.name)}"
        return self.name

    @property
    def symbol_id(self) -> str:
        return f"{self.path}::{self.kind}::{self.qualified_name}@{self.start_line or 0}"


@dataclass
class CallEdge:
    source: str
    target: str
    certainty: str
    depth: int = 1


@dataclass
class TypeEdge:
    source: str
    target: str
    type: str
    certainty: str
    name: str | None = None
    line: int | None = None
    injected: bool = False
    collection: bool = False
    depth: int = 1


TYPE_USAGE_KINDS = ("INSTANTIATES", "HAS_FIELD", "TAKES", "RETURNS", "INHERITS", "IMPLEMENTS")
CONSTRUCTOR_NAMES = {"__init__", "constructor"}
MAX_ANCESTOR_DEPTH = 3


@dataclass
class UnresolvedCall:
    caller: str
    name: str
    candidates: int


@dataclass
class CodeGraphData:
    functions: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    classes: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    type_relations: list[dict] = field(default_factory=list)
    truncated: bool = False


class CodeGraph:
    def __init__(self, data: CodeGraphData):
        self.truncated = data.truncated
        self.nodes: dict[str, SymbolNode] = {}
        self.classes: list[SymbolNode] = []

        for row in data.classes:
            if not row.get("path"):
                continue
            node = SymbolNode(
                id=str(row["id"]), name=row.get("name") or "?", kind="class",
                path=normalize_path(row["path"]), start_line=row.get("startLine"), end_line=row.get("endLine"),
                bases=[b for b in (row.get("bases") or []) if b],
                type_kind=row.get("typeKind"), events=[e for e in (row.get("events") or []) if e],
            )
            self.nodes[node.id] = node
            self.classes.append(node)

        for row in data.functions:
            if not row.get("path"):
                continue
            path = normalize_path(row["path"])
            node = SymbolNode(
                id=str(row["id"]), name=row.get("name") or "?", kind="function",
                path=path, start_line=row.get("startLine"), end_line=row.get("endLine"),
                raises=[e for e in (row.get("raises") or []) if e],
            )
            owner = self._enclosing_class(node)
            if owner is not None:
                node.kind = "method"
                node.class_name = owner.name
                node.owner_id = owner.id
            self.nodes[node.id] = node

        self.imports: dict[str, list[str]] = {
            normalize_path(row["path"]): [m for m in (row.get("imports") or []) if m]
            for row in data.files if row.get("path")
        }

        by_short: dict[str, list[str]] = defaultdict(list)
        for node in self.nodes.values():
            if node.kind != "class":
                by_short[short_symbol_name(node.name)].append(node.id)

        self.out_edges: dict[str, dict[str, str]] = defaultdict(dict)
        self.in_edges: dict[str, dict[str, str]] = defaultdict(dict)
        self.unresolved: dict[str, list[UnresolvedCall]] = defaultdict(list)

        for call in data.calls:
            caller = str(call.get("callerId"))
            if caller not in self.nodes:
                continue
            callee_id = str(call.get("calleeId"))
            if call.get("calleePath") and callee_id in self.nodes:
                target, certainty = callee_id, "direct"
            else:
                candidates = by_short.get(short_symbol_name(call.get("calleeName")), [])
                if len(candidates) != 1:
                    self.unresolved[caller].append(UnresolvedCall(
                        caller=caller, name=call.get("calleeName") or "?", candidates=len(candidates),
                    ))
                    continue
                target, certainty = candidates[0], "inferred"
            if target == caller:
                continue
            if self.out_edges[caller].get(target) != "direct":
                self.out_edges[caller][target] = certainty
                self.in_edges[target][caller] = certainty

        self.type_out: dict[str, list[TypeEdge]] = defaultdict(list)
        self.type_in: dict[str, list[TypeEdge]] = defaultdict(list)
        self.unresolved_types: dict[str, list[str]] = defaultdict(list)
        self._classes_by_name: dict[str, list[SymbolNode]] = defaultdict(list)
        for cls in self.classes:
            self._classes_by_name[cls.name].append(cls)

        for row in data.type_relations:
            source = str(row.get("sourceId"))
            name = row.get("target")
            if source not in self.nodes or not name:
                continue
            resolved = self._resolve_type(name, self.nodes[source].path)
            if resolved is None:
                self.unresolved_types[source].append(name)
                continue
            target, certainty = resolved
            if target == source:
                continue
            kind = row.get("type") or "USES"
            if kind == "INHERITS" and self.nodes[target].type_kind == "interface":
                kind = "IMPLEMENTS"
            self._add_type_edge(TypeEdge(
                source=source, target=target, type=kind, certainty=certainty, name=row.get("name"),
                line=row.get("line"), injected=bool(row.get("injected")), collection=bool(row.get("collection")),
            ))

        self._derive_overrides()

    def _resolve_type(self, name: str, from_path: str) -> tuple[str, str] | None:
        candidates = self._classes_by_name.get(short_symbol_name(name), [])
        local = [c for c in candidates if c.path == from_path]
        if len(local) == 1:
            return local[0].id, "direct"
        if len(candidates) == 1:
            return candidates[0].id, "inferred"
        return None

    def _add_type_edge(self, edge: TypeEdge):
        if any(e.target == edge.target and e.type == edge.type and e.name == edge.name for e in self.type_out[edge.source]):
            return
        self.type_out[edge.source].append(edge)
        self.type_in[edge.target].append(edge)

    def _member_index(self) -> dict[str, dict[str, SymbolNode]]:
        index: dict[str, dict[str, SymbolNode]] = defaultdict(dict)
        for node in self.nodes.values():
            if node.kind == "method" and node.owner_id:
                index[node.owner_id].setdefault(short_symbol_name(node.name), node)
        return index

    def ancestors(self, class_id: str, depth: int = MAX_ANCESTOR_DEPTH) -> list[tuple[str, int]]:
        found: list[tuple[str, int]] = []
        seen = {class_id}
        queue = deque([(class_id, 0)])
        while queue:
            node, level = queue.popleft()
            if level >= depth:
                continue
            for edge in self.type_out.get(node, []):
                if edge.type in ("INHERITS", "IMPLEMENTS") and edge.target not in seen:
                    seen.add(edge.target)
                    found.append((edge.target, level + 1))
                    queue.append((edge.target, level + 1))
        return found

    def _derive_overrides(self):
        members = self._member_index()
        for cls in self.classes:
            ancestors = self.ancestors(cls.id)
            if not ancestors:
                continue
            for name, method in members.get(cls.id, {}).items():
                if name in CONSTRUCTOR_NAMES or name == cls.name:
                    continue
                for ancestor, _ in ancestors:
                    base = members.get(ancestor, {}).get(name)
                    if base is not None:
                        self._add_type_edge(TypeEdge(source=method.id, target=base.id, type="OVERRIDES", certainty="inferred"))
                        break

    def type_usages(self, class_id: str) -> list[TypeEdge]:
        return [e for e in self.type_in.get(class_id, []) if e.type in TYPE_USAGE_KINDS]

    def type_dependencies(self, node_id: str) -> list[TypeEdge]:
        return [e for e in self.type_out.get(node_id, []) if e.type in TYPE_USAGE_KINDS]

    def overrides(self, method_id: str) -> list[TypeEdge]:
        return [e for e in self.type_out.get(method_id, []) if e.type == "OVERRIDES"]

    def overridden_by(self, method_id: str) -> list[TypeEdge]:
        return [e for e in self.type_in.get(method_id, []) if e.type == "OVERRIDES"]

    def has_type_data(self) -> bool:
        return any(self.type_out.values())

    def _enclosing_class(self, node: SymbolNode) -> SymbolNode | None:
        best = None
        for cls in self.classes:
            if cls.path != node.path or cls.start_line is None or cls.end_line is None or node.start_line is None:
                continue
            if cls.start_line <= node.start_line and (node.end_line or node.start_line) <= cls.end_line:
                if best is None or cls.start_line >= best.start_line:
                    best = cls
        return best

    def find(self, name: str, kind: str = "any", path_hint: str | None = None) -> list[SymbolNode]:
        query = name.strip()
        if "::" in query:
            node = next((n for n in self.nodes.values() if n.symbol_id == query), None)
            return [node] if node else []

        class_part, _, member = query.rpartition(".")
        hint = normalize_path(path_hint) if path_hint else None

        def kind_ok(node: SymbolNode) -> bool:
            if kind == "any":
                return True
            if kind == "function":
                return node.kind in ("function", "method")
            return node.kind == kind

        def hint_ok(node: SymbolNode) -> bool:
            return not hint or hint in node.path

        exact = [
            n for n in self.nodes.values()
            if kind_ok(n) and hint_ok(n) and (n.name == query or n.qualified_name == query)
        ]
        if exact:
            return self._sorted(exact)

        if class_part:
            qualified = [
                n for n in self.nodes.values()
                if kind_ok(n) and hint_ok(n) and short_symbol_name(n.name) == member
                and (n.class_name == class_part or n.class_name == short_symbol_name(class_part))
            ]
            if qualified:
                return self._sorted(qualified)

        short = short_symbol_name(query)
        loose = [
            n for n in self.nodes.values()
            if kind_ok(n) and hint_ok(n) and short_symbol_name(n.name) == short
        ]
        if loose:
            return self._sorted(loose)

        lowered = short.lower()
        return self._sorted([
            n for n in self.nodes.values()
            if kind_ok(n) and hint_ok(n) and short_symbol_name(n.name).lower() == lowered
        ])

    @staticmethod
    def _sorted(nodes: list[SymbolNode]) -> list[SymbolNode]:
        return sorted(nodes, key=lambda n: (n.path, n.start_line or 0, n.name))

    def resolve(self, symbol: str) -> list[SymbolNode]:
        return self.find(symbol)

    def _walk(self, start: str, adjacency: dict[str, dict[str, str]], depth: int, limit: int, outgoing: bool) -> tuple[list[CallEdge], bool]:
        edges: list[CallEdge] = []
        seen = {start}
        queue = deque([(start, 0)])
        truncated = False
        while queue:
            node, level = queue.popleft()
            if level >= depth:
                continue
            for neighbor, certainty in sorted(adjacency.get(node, {}).items()):
                if len(edges) >= limit:
                    truncated = True
                    break
                source, target = (node, neighbor) if outgoing else (neighbor, node)
                edges.append(CallEdge(source=source, target=target, certainty=certainty, depth=level + 1))
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, level + 1))
        return edges, truncated

    def callees(self, node_id: str, depth: int, limit: int) -> tuple[list[CallEdge], bool]:
        return self._walk(node_id, self.out_edges, depth, limit, outgoing=True)

    def callers(self, node_id: str, depth: int, limit: int) -> tuple[list[CallEdge], bool]:
        return self._walk(node_id, self.in_edges, depth, limit, outgoing=False)

    def call_path(self, source: str, target: str, max_depth: int) -> list[CallEdge] | None:
        previous: dict[str, str | None] = {source: None}
        queue = deque([(source, 0)])
        while queue:
            node, level = queue.popleft()
            if node == target:
                break
            if level >= max_depth:
                continue
            for neighbor in sorted(self.out_edges.get(node, {})):
                if neighbor not in previous:
                    previous[neighbor] = node
                    queue.append((neighbor, level + 1))
        if target not in previous:
            return None
        path: list[CallEdge] = []
        node = target
        while previous[node] is not None:
            parent = previous[node]
            path.append(CallEdge(source=parent, target=node, certainty=self.out_edges[parent][node]))
            node = parent
        path.reverse()
        for index, edge in enumerate(path, start=1):
            edge.depth = index
        return path

    def file_graph(self) -> dict[str, dict[str, dict]]:
        files: dict[str, dict[str, dict]] = defaultdict(dict)
        for caller, targets in self.out_edges.items():
            source_path = self.nodes[caller].path
            for callee, certainty in targets.items():
                target_path = self.nodes[callee].path
                if source_path == target_path:
                    continue
                entry = files[source_path].setdefault(target_path, {"calls": 0, "types": 0, "certainty": "inferred"})
                entry["calls"] += 1
                if certainty == "direct":
                    entry["certainty"] = "direct"
        for edges in self.type_out.values():
            for edge in edges:
                if edge.type not in TYPE_USAGE_KINDS:
                    continue
                source_path = self.nodes[edge.source].path
                target_path = self.nodes[edge.target].path
                if source_path == target_path:
                    continue
                entry = files[source_path].setdefault(target_path, {"calls": 0, "types": 0, "certainty": "inferred"})
                entry["types"] += 1
                if edge.certainty == "direct":
                    entry["certainty"] = "direct"
        return files

    def file_dependencies(self, path: str, direction: str, depth: int, limit: int) -> tuple[list[tuple[str, str, dict, int]], bool]:
        graph = self.file_graph()
        reverse: dict[str, dict[str, dict]] = defaultdict(dict)
        for source, targets in graph.items():
            for target, info in targets.items():
                reverse[target][source] = info

        results: list[tuple[str, str, dict, int]] = []
        truncated = False
        for adjacency, outgoing in ((graph, True), (reverse, False)):
            if direction == "outgoing" and not outgoing or direction == "incoming" and outgoing:
                continue
            seen = {path}
            queue = deque([(path, 0)])
            while queue:
                node, level = queue.popleft()
                if level >= depth:
                    continue
                for neighbor, info in sorted(adjacency.get(node, {}).items()):
                    if len(results) >= limit:
                        truncated = True
                        break
                    edge = (node, neighbor) if outgoing else (neighbor, node)
                    results.append((edge[0], edge[1], info, level + 1))
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append((neighbor, level + 1))
        return results, truncated

    def members(self, class_node: SymbolNode) -> list[SymbolNode]:
        return self._sorted([
            n for n in self.nodes.values()
            if n.kind == "method" and n.class_name == class_node.name and n.path == class_node.path
            and class_node.start_line is not None and n.start_line is not None
            and class_node.start_line <= n.start_line <= (class_node.end_line or n.start_line)
        ])

    def owner_of(self, node: SymbolNode) -> SymbolNode | None:
        if node.kind != "method":
            return None
        return self._enclosing_class(node)

    def subclasses_of(self, name: str) -> list[SymbolNode]:
        short = short_symbol_name(name)
        return self._sorted([c for c in self.classes if short in c.bases])

    def has_inheritance_data(self) -> bool:
        return any(c.bases for c in self.classes)

    def in_file(self, path: str) -> list[SymbolNode]:
        path = normalize_path(path)
        return self._sorted([n for n in self.nodes.values() if n.path == path])

    def has_file(self, path: str) -> bool:
        path = normalize_path(path)
        return path in self.imports or any(n.path == path for n in self.nodes.values())


class GraphCache:
    def __init__(self, max_entries: int = 8, ttl_s: float = 600):
        self.max_entries = max_entries
        self.ttl_s = ttl_s
        self.entries: OrderedDict[str, tuple[float, CodeGraph]] = OrderedDict()

    def get(self, key: str) -> CodeGraph | None:
        entry = self.entries.get(key)
        if entry is None:
            return None
        created, graph = entry
        if time.monotonic() - created > self.ttl_s:
            self.entries.pop(key, None)
            return None
        self.entries.move_to_end(key)
        return graph

    def put(self, key: str, graph: CodeGraph):
        self.entries[key] = (time.monotonic(), graph)
        self.entries.move_to_end(key)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)


GRAPH_CACHE = GraphCache()


async def get_code_graph(ctx) -> CodeGraph:
    from app.tools.base import ToolFailure

    graph = ctx.cache.get("code_graph")
    if graph is not None:
        return graph
    key = f"{ctx.scope.user_id}|{ctx.scope.investigation_id}|{ctx.scope.project_id}|{ctx.snapshot}"
    graph = GRAPH_CACHE.get(key)
    if graph is None:
        try:
            data = await ctx.deps.graph_loader(ctx.scope)
        except ToolFailure:
            raise
        except Exception as e:
            raise ToolFailure("unavailable", f"knowledge graph unavailable: {type(e).__name__}")
        if not isinstance(data, CodeGraphData):
            data = CodeGraphData(**data)
        graph = CodeGraph(data)
        GRAPH_CACHE.put(key, graph)
    ctx.cache["code_graph"] = graph
    return graph
