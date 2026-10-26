import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations, islice

from app.evidence.schemas import Evidence
from app.patterns.structure import NOT_PRODUCTS, REGISTRATION_METHODS, FileStructure, Method, TypeDecl

HIGH_COMPLEXITY_CATEGORIES = {"high", "very high", "veryhigh", "critical"}
HIGH_COMPLEXITY_FALLBACK = 15
LONG_FUNCTION_NLOC = 50
HIGH_FAN_IN = 5
MIN_DISPATCH_BRANCHES = 3
MANY_VARIANTS = 4
CRUD_PREFIXES = ("get", "find", "add", "save", "update", "delete", "remove", "list", "query", "insert", "fetch", "exists", "count", "upsert")
DATA_ACCESS_TYPES = re.compile(
    r"(DbContext|DbSet|DbConnection|SqlConnection|IDbConnection|NpgsqlConnection|Session|AsyncSession|EntityManager|"
    r"JdbcTemplate|Connection|Cursor|Engine|Database|MongoClient|IMongoCollection|IMongoDatabase|Pool|QueryRunner|DataSource)$"
)
GENERIC_METHODS = {
    "append", "add", "get", "set", "toString", "ToString", "Add", "log", "info", "debug", "error", "warn", "warning",
    "format", "join", "split", "strip", "write", "print", "push", "map", "filter", "keys", "values", "items", "equals",
    "Equals", "GetHashCode", "Dispose", "close", "Close", "then", "catch", "commit", "flush",
}
EVENT_BASES = {"EventEmitter", "EventTarget"}
PRIMITIVES = {
    "String", "Int32", "Int64", "Boolean", "Decimal", "Double", "Object", "DateTime", "Guid", "TimeSpan", "Integer", "Long",
    "Number", "Date", "Any", "Optional", "ILogger", "Logger", "CancellationToken", "IConfiguration", "IOptions",
}


def symbol_tail(symbol: str | None) -> str:
    return re.split(r"[.:]+", symbol or "")[-1]


@dataclass
class Location:
    path: str
    start_line: int | None
    end_line: int | None
    role: str
    source: str
    symbol: str | None = None
    relation: tuple[str, str, str] | None = None
    metric: Evidence | None = None

    @property
    def key(self) -> tuple:
        return (self.source, self.path, self.start_line, self.end_line, self.relation, self.metric.evidence_id if self.metric else None)


@dataclass
class Signal:
    id: str
    anchor: str
    source: str
    why: str
    locations: list[Location] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def method_anchor(path: str, owner: TypeDecl | None, method: Method) -> str:
    return f"{path}::{owner.name + '.' if owner else ''}{method.name}"


def _decl_location(decl: TypeDecl, role: str) -> Location:
    return Location(decl.path, decl.start_line, decl.end_line, role, "ast", symbol=decl.name)


def _method_location(path: str, owner: TypeDecl | None, method: Method, role: str) -> Location:
    symbol = f"{owner.name}.{method.name}" if owner else method.name
    return Location(path, method.start_line, method.end_line, role, "ast", symbol=symbol)


@dataclass
class TypeIndex:
    declared: dict[str, list[TypeDecl]]
    implementers: dict[str, list[tuple[str, str, int | None, str]]]
    graph_classes: set[str]

    def is_abstraction(self, name: str) -> bool:
        decls = self.declared.get(name) or []
        if decls:
            return any(d.is_abstraction for d in decls)
        return len(self.concrete_implementers(name)) >= 2 or (name not in self.graph_classes and len(self.implementers.get(name, [])) >= 1 and bool(re.match(r"^I[A-Z]", name)))

    def is_known(self, name: str) -> bool:
        return name in self.declared or name in self.implementers or name in self.graph_classes

    def concrete_implementers(self, name: str) -> list[tuple[str, str, int | None, str]]:
        result = []
        for entry in self.implementers.get(name, []):
            decls = self.declared.get(entry[0]) or []
            if decls and all(d.is_abstraction for d in decls):
                continue
            result.append(entry)
        return result

    def implements(self, type_name: str, abstraction: str) -> bool:
        return any(entry[0] == type_name for entry in self.implementers.get(abstraction, []))


def build_index(structures: list[FileStructure], graph=None) -> TypeIndex:
    declared: dict[str, list[TypeDecl]] = defaultdict(list)
    implementers: dict[str, list[tuple[str, str, int | None, str]]] = defaultdict(list)
    for structure in structures:
        for decl in structure.types:
            declared[decl.name].append(decl)
            for base in decl.bases:
                implementers[base].append((decl.name, decl.path, decl.start_line, "ast"))
    graph_classes: set[str] = set()
    if graph is not None:
        for node in graph.classes:
            graph_classes.add(node.name)
            for base in node.bases:
                if not any(entry[0] == node.name and entry[1] == node.path for entry in implementers[base]):
                    implementers[base].append((node.name, node.path, node.start_line, "graph"))
    return TypeIndex(dict(declared), dict(implementers), graph_classes)


def structural_signals(structures: list[FileStructure], index: TypeIndex) -> list[Signal]:
    signals: list[Signal] = []
    signals += _abstraction_signals(index)
    for structure in structures:
        for decl in structure.types:
            signals += _composition_signals(decl, index)
            signals += _observer_signals(decl)
            signals += _facade_signal(decl, index)
            signals += _repository_signals(decl, index)
        for owner, method in structure.all_methods():
            signals += _method_signals(structure.path, owner, method, index)
    signals += _creator_overridden(structures, index)
    signals += _scattered_creation(structures, index)
    signals += _similar_variants(structures, index)
    signals += _override_chains(index)
    return signals


def _abstraction_signals(index: TypeIndex) -> list[Signal]:
    signals = []
    for name in sorted(index.implementers):
        if not index.is_abstraction(name):
            continue
        concrete = index.concrete_implementers(name)
        locations = [_decl_location(d, "abstraction") for d in index.declared.get(name, [])[:1]]
        for impl_name, path, line, source in concrete[:6]:
            decls = [d for d in index.declared.get(impl_name, []) if d.path == path]
            if decls:
                locations.append(_decl_location(decls[0], "implementation"))
            else:
                locations.append(Location(path, line, line, "implementation", "graph", symbol=impl_name, relation=(impl_name, name, "EXTENDS")))
        sources = {loc.source for loc in locations}
        source = "graph" if sources == {"graph"} else "ast"
        if len(concrete) >= 2:
            signals.append(Signal("abstraction_with_implementations", name, source,
                                  f"{name} has {len(concrete)} implementations", locations,
                                  {"implementations": [c[0] for c in concrete]}))
        elif len(concrete) == 1:
            signals.append(Signal("abstraction_single_implementation", name, source,
                                  f"{name} has a single implementation", locations,
                                  {"implementations": [concrete[0][0]]}))
    return signals


def _calls_on(decl: TypeDecl, field_name: str) -> list[tuple[Method, object]]:
    return [(m, c) for m in decl.methods if not m.is_constructor for c in m.calls if c.receiver_is_field and c.receiver == field_name]


def _product_fields(decl: TypeDecl) -> list:
    return [
        f for f in decl.fields
        if f.type is not None and not f.type.is_collection and f.type.name[:1].isupper()
        and f.type.name != decl.name and f.type.name not in PRIMITIVES
    ]


def _adapter_signal(decl: TypeDecl, index: TypeIndex) -> list[Signal]:
    collaborators = _product_fields(decl)
    if not collaborators or len({f.type.name for f in collaborators}) > 2:
        return []
    methods = [m for m in decl.methods if not m.is_constructor and not m.abstract and not m.name.startswith("_")]
    if not methods:
        return []
    for base in decl.bases:
        if not index.is_abstraction(base):
            continue
        for member in collaborators:
            held = member.type.name
            if (held in decl.bases or index.implements(held, base) or index.is_abstraction(held) or index.is_known(held)
                    or held in NOT_PRODUCTS or DATA_ACCESS_TYPES.search(held)):
                continue
            translating = [(m, c) for m in methods for c in m.calls if c.receiver_is_field and c.receiver == member.name and c.method != m.name]
            translated_methods = {m.name for m, _ in translating}
            if translating and len(translated_methods) / len(methods) >= 0.6:
                m, c = translating[0]
                return [Signal("adapter_delegation", base, "ast",
                               f"{decl.name} implements {base} by translating calls to {held}.{c.method}",
                               [_decl_location(decl, "adapter"),
                                Location(decl.path, member.line, member.line, "adaptee field", "ast", symbol=f"{decl.name}.{member.name}"),
                                Location(decl.path, c.line, c.line, "translated call", "ast", symbol=f"{decl.name}.{m.name}")],
                               {"adapter": decl.name, "adaptee": held, "external_adaptee": not index.is_known(held)})]
    return []


def _composition_signals(decl: TypeDecl, index: TypeIndex) -> list[Signal]:
    signals = _adapter_signal(decl, index)
    own_bases = set(decl.bases)
    for member in decl.fields:
        if member.type is None or member.type.is_collection:
            continue
        held = member.type.name
        if held == decl.name or not index.is_known(held):
            continue
        calls = _calls_on(decl, member.name)
        field_loc = Location(decl.path, member.line, member.line, "field", "ast", symbol=f"{decl.name}.{member.name}")
        if held in own_bases and index.is_abstraction(held):
            forwarding = [(m, c) for m, c in calls if c.method == m.name]
            if forwarding:
                m, c = forwarding[0]
                signals.append(Signal("wrapper_same_interface", held, "ast",
                                      f"{decl.name} implements {held} and forwards {m.name} to the wrapped {held}",
                                      [_decl_location(decl, "wrapper"), field_loc, Location(decl.path, c.line, c.line, "forwarding call", "ast", symbol=f"{decl.name}.{m.name}")],
                                      {"wrapper": decl.name}))
            continue
        if index.is_abstraction(held) and not index.implements(decl.name, held):
            if calls:
                m, c = calls[0]
                signals.append(Signal("context_holds_abstraction", held, "ast",
                                      f"{decl.name} holds a {held} and delegates to it",
                                      [_decl_location(decl, "context"), field_loc, Location(decl.path, c.line, c.line, "delegating call", "ast", symbol=f"{decl.name}.{m.name}")],
                                      {"context": decl.name, "field": member.name}))
            if member.from_constructor or any(p.type and p.type.name == held for m in decl.methods if m.is_constructor for p in m.params):
                signals.append(Signal("abstraction_injected", held, "ast", f"{held} is passed into the constructor of {decl.name}",
                                      [field_loc], {"context": decl.name}))
    return signals


def _observer_signals(decl: TypeDecl) -> list[Signal]:
    signals = []
    collections = {f.name: f for f in decl.fields if f.type is not None and f.type.is_collection}
    for method in decl.methods:
        params = {p.name for p in method.params}
        for call in method.calls:
            if call.receiver_is_field and call.receiver in collections and call.method in REGISTRATION_METHODS and params & set(call.args):
                signals.append(Signal("subscriber_registration", f"{decl.name}.{call.receiver}", "ast",
                                      f"{decl.name}.{method.name} stores received objects in {call.receiver}",
                                      [Location(decl.path, method.start_line, method.end_line, "registration", "ast", symbol=f"{decl.name}.{method.name}")],
                                      {"subject": decl.name}))
        for loop in method.loops:
            if loop.collection_is_field and loop.calls and loop.collection in collections:
                signals.append(Signal("collection_notification", f"{decl.name}.{loop.collection}", "ast",
                                      f"{decl.name}.{method.name} calls {loop.calls[0].method} on every element of {loop.collection}",
                                      [Location(decl.path, loop.line, loop.calls[-1].line, "notification loop", "ast", symbol=f"{decl.name}.{method.name}")],
                                      {"subject": decl.name, "method": loop.calls[0].method}))
    events = set(decl.events)
    if events or EVENT_BASES & set(decl.bases):
        signals.append(Signal("event_declared", decl.name, "ast", f"{decl.name} declares events", [_decl_location(decl, "event source")],
                              {"events": sorted(events)}))
    for method in decl.methods:
        for call in method.calls:
            raised = (call.receiver in events and call.method == "Invoke") or (not call.receiver and call.method in events) or (
                call.receiver_is_self and call.method in ("emit", "dispatchEvent"))
            if raised:
                signals.append(Signal("event_raised", decl.name, "ast", f"{decl.name}.{method.name} raises an event",
                                      [Location(decl.path, call.line, call.line, "event raised", "ast", symbol=f"{decl.name}.{method.name}")]))
                break
    return signals


def _facade_signal(decl: TypeDecl, index: TypeIndex) -> list[Signal]:
    if decl.is_abstraction:
        return []
    collaborators = {f.name: f.type.name for f in _product_fields(decl)}
    if len(set(collaborators.values())) < 3:
        return []
    methods = [m for m in decl.methods if not m.is_constructor and not m.abstract]
    if len(methods) < 3:
        return []
    delegating = [m for m in methods if m.length <= 15 and any(c.receiver_is_field and c.receiver in collaborators for c in m.calls)]
    used = {collaborators[c.receiver] for m in delegating for c in m.calls if c.receiver_is_field and c.receiver in collaborators}
    if len(delegating) / len(methods) < 0.6 or len(used) < 3:
        return []
    return [Signal("facade_delegation", decl.name, "ast",
                   f"{len(delegating)} of {len(methods)} methods of {decl.name} forward to {len(used)} collaborator types",
                   [_decl_location(decl, "facade candidate")], {"collaborators": sorted(used)})]


def _repository_signals(decl: TypeDecl, index: TypeIndex) -> list[Signal]:
    signals = []
    crud = [m for m in decl.methods if not m.is_constructor and m.name.lower().startswith(CRUD_PREFIXES)]
    if len(crud) >= 3:
        signals.append(Signal("repository_interface", decl.name, "ast", f"{decl.name} offers {len(crud)} data access style operations",
                              [_decl_location(decl, "repository candidate")], {"operations": [m.name for m in crud[:8]]}))
    access = [f for f in decl.fields if f.type is not None and DATA_ACCESS_TYPES.search(f.type.name)]
    access += [p for m in decl.methods if m.is_constructor for p in m.params if p.type is not None and DATA_ACCESS_TYPES.search(p.type.name)]
    if access or any(DATA_ACCESS_TYPES.search(b) for b in decl.bases):
        location = Location(decl.path, access[0].line if access else decl.start_line, access[0].line if access else decl.start_line,
                            "persistence dependency", "ast", symbol=decl.name)
        for anchor in [decl.name, *decl.bases]:
            signals.append(Signal("data_access_dependency", anchor, "ast", f"{decl.name} depends on a persistence API", [location],
                                  {"type": access[0].type.name if access else ", ".join(decl.bases)}))
    return signals


def _method_signals(path: str, owner: TypeDecl | None, method: Method, index: TypeIndex) -> list[Signal]:
    signals = []
    anchor = method_anchor(path, owner, method)
    symbol = f"{owner.name}.{method.name}" if owner else method.name
    value_dispatches = [d for d in method.dispatches if d.kind == "value"]
    for dispatch in value_dispatches:
        location = Location(path, dispatch.start_line, dispatch.end_line, "conditional chain", "ast", symbol=symbol)
        detail = {"discriminator": dispatch.discriminator, "branches": len(dispatch.branches), "labels": [b.label for b in dispatch.branches][:8],
                  "has_default": dispatch.has_default, "function": symbol, "path": path}
        if len(dispatch.branches) >= MIN_DISPATCH_BRANCHES:
            signals.append(Signal("conditional_dispatch", anchor, "ast",
                                  f"{symbol} selects behaviour by {dispatch.discriminator} in {len(dispatch.branches)} cases", [location], detail))
        if len(dispatch.branches) >= MANY_VARIANTS:
            signals.append(Signal("many_variants", anchor, "ast",
                                  f"{symbol} already distinguishes {len(dispatch.branches)} cases of {dispatch.discriminator}", [location], detail))
        elif len(dispatch.branches) == 2 and not any(len(d.branches) >= MIN_DISPATCH_BRANCHES for d in value_dispatches):
            signals.append(Signal("few_variants", anchor, "ast", f"{symbol} distinguishes only two cases of {dispatch.discriminator}", [location], detail))
    for dispatch in method.dispatches:
        if dispatch.kind == "type" and len(dispatch.branches) >= 2:
            signals.append(Signal("type_dispatch", anchor, "ast", f"{symbol} checks the runtime type of {dispatch.discriminator} in {len(dispatch.branches)} branches",
                                  [Location(path, dispatch.start_line, dispatch.end_line, "type checks", "ast", symbol=symbol)],
                                  {"discriminator": dispatch.discriminator, "branches": len(dispatch.branches), "function": symbol, "path": path}))
        creating = [b for b in dispatch.branches if b.creations]
        if len(creating) >= 2 and len(dispatch.created_types) >= 2:
            signals.append(Signal("type_dependent_creation", anchor, "ast",
                                  f"{symbol} creates {', '.join(dispatch.created_types[:4])} depending on {dispatch.discriminator}",
                                  [Location(path, dispatch.start_line, dispatch.end_line, "conditional creation", "ast", symbol=symbol)],
                                  {"created": dispatch.created_types, "discriminator": dispatch.discriminator, "function": symbol, "path": path,
                                   "branches": len(dispatch.branches)}))
    returned = method.return_type.name if method.return_type else None
    if returned and not method.abstract and (index.is_abstraction(returned) or index.concrete_implementers(returned)):
        created = [name for name, _ in method.creations if index.implements(name, returned)]
        if created:
            signals.append(Signal("creator_returns_abstraction", returned, "ast",
                                  f"{symbol} returns {returned} and creates {', '.join(sorted(set(created))[:4])}",
                                  [_method_location(path, owner, method, "creation method")], {"creator": symbol, "created": sorted(set(created))}))
    receivers: dict[str, set[str]] = defaultdict(set)
    loop_lines = {c.line for loop in method.loops for c in loop.calls}
    for call in method.calls:
        if call.receiver_is_field and call.method not in GENERIC_METHODS and call.line not in loop_lines:
            receivers[call.method].add(call.receiver)
    for name, targets in receivers.items():
        if len(targets) >= 3:
            signals.append(Signal("repeated_receiver_notification", anchor, "ast",
                                  f"{symbol} calls {name} on {len(targets)} different collaborators",
                                  [_method_location(path, owner, method, "manual notification")], {"method": name, "receivers": sorted(targets)}))
            break
    return signals


def _creator_overridden(structures: list[FileStructure], index: TypeIndex) -> list[Signal]:
    signals = []
    for structure in structures:
        for decl in structure.types:
            for method in decl.methods:
                returned = method.return_type.name if method.return_type else None
                if not returned or not (method.abstract or method.virtual) or not (index.is_abstraction(returned) or index.implementers.get(returned)):
                    continue
                overriding = []
                for sub_name, _, _, _ in index.implementers.get(decl.name, []):
                    for sub in index.declared.get(sub_name, []):
                        override = sub.method(method.name)
                        if override is not None and override.creations:
                            overriding.append((sub, override))
                if overriding:
                    locations = [_method_location(decl.path, decl, method, "abstract creator")]
                    locations += [_method_location(sub.path, sub, override, "overriding creator") for sub, override in overriding[:4]]
                    signals.append(Signal("abstract_creator_overridden", returned, "ast",
                                          f"{decl.name}.{method.name} returns {returned} and is overridden by {', '.join(s.name for s, _ in overriding[:4])}",
                                          locations, {"creator": f"{decl.name}.{method.name}"}))
    return signals


def _scattered_creation(structures: list[FileStructure], index: TypeIndex) -> list[Signal]:
    sites: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for structure in structures:
        for owner, method in structure.all_methods():
            for name in {n for n, _ in method.creations}:
                line = next(l for n, l in method.creations if n == name)
                sites[name].append((structure.path, method_anchor(structure.path, owner, method), line))
    products = {impl for base, entries in index.implementers.items() if index.is_abstraction(base) for impl, _, _, _ in entries}
    signals = []
    for name, places in sorted(sites.items()):
        files = {p for p, _, _ in places}
        if name in products and len(places) >= 3 and len(files) >= 2:
            signals.append(Signal("scattered_creation", name, "ast", f"{name} is constructed in {len(places)} functions across {len(files)} files",
                                  [Location(p, l, l, "construction site", "ast", symbol=name) for p, _, l in places[:6]],
                                  {"sites": len(places), "files": sorted(files)}))
    return signals


def _similar_variants(structures: list[FileStructure], index: TypeIndex) -> list[Signal]:
    groups: dict[tuple[str, frozenset], list[TypeDecl]] = defaultdict(list)
    for structure in structures:
        for decl in structure.types:
            if decl.is_abstraction or decl.bases:
                continue
            names = frozenset(m.name for m in decl.methods if not m.is_constructor and not m.name.startswith("_"))
            if names:
                groups[(os.path.dirname(decl.path), names)].append(decl)
    signals = []
    for (_, names), decls in groups.items():
        if len(decls) >= 3 or (len(decls) == 2 and len(names) >= 2):
            anchor = "+".join(sorted(d.name for d in decls))
            signals.append(Signal("similar_variants", anchor, "ast",
                                  f"{', '.join(d.name for d in decls)} expose the same operations ({', '.join(sorted(names)[:4])}) without a shared abstraction",
                                  [_decl_location(d, "variant") for d in decls[:5]], {"classes": [d.name for d in decls], "operations": sorted(names)}))
    return signals


def _override_chains(index: TypeIndex) -> list[Signal]:
    signals = []
    for base_name, decls in index.declared.items():
        base = decls[0]
        if base.is_abstraction:
            continue
        for method in base.methods:
            wrappers = []
            for sub_name, _, _, _ in index.implementers.get(base_name, []):
                for sub in index.declared.get(sub_name, []):
                    override = sub.method(method.name)
                    if override is not None and override.calls_super:
                        wrappers.append((sub, override))
            if len(wrappers) >= 3:
                signals.append(Signal("subclass_override_chain", base_name, "ast",
                                      f"{len(wrappers)} subclasses of {base_name} override {method.name} and call the base implementation",
                                      [_decl_location(base, "base class")] + [_method_location(s.path, s, o, "extending override") for s, o in wrappers[:4]],
                                      {"method": method.name, "subclasses": [s.name for s, _ in wrappers]}))
                break
    return signals


def graph_signals(structures: list[FileStructure], graph, max_pairs: int = 400) -> list[Signal]:
    if graph is None:
        return []
    signals: list[Signal] = []
    functions = [n for s in structures for n in graph.in_file(s.path) if n.kind in ("function", "method")]
    callees: dict[str, set[str]] = {}
    for node in functions:
        targets = set(graph.out_edges.get(node.id, {}))
        callees[node.id] = targets
        callers = graph.in_edges.get(node.id, {})
        if len(callers) >= HIGH_FAN_IN:
            owner = node.class_name
            anchor = f"{node.path}::{owner + '.' if owner else ''}{node.name.split('.')[-1]}"
            caller_nodes = [graph.nodes[c] for c in list(callers)[:5]]
            locations = [Location(node.path, node.start_line, node.end_line, "frequently called", "graph", symbol=node.qualified_name)]
            locations += [Location(c.path, c.start_line, c.end_line, "caller", "graph", symbol=c.qualified_name,
                                   relation=(c.qualified_name, node.qualified_name, "CALLS")) for c in caller_nodes]
            for target_anchor in {anchor, owner} - {None}:
                signals.append(Signal("high_fan_in", target_anchor, "graph", f"{node.qualified_name} has {len(callers)} callers", locations,
                                      {"callers": len(callers)}))
    clients = [n for n in functions if len(callees[n.id]) >= 3]
    for (a, b) in islice(combinations(clients, 2), max_pairs):
        if a.path == b.path:
            continue
        shared = callees[a.id] & callees[b.id]
        shared_files = {graph.nodes[t].path for t in shared}
        if len(shared) >= 3 and len(shared_files) >= 2:
            names = sorted(graph.nodes[t].qualified_name for t in shared)
            anchor = "subsystem:" + "+".join(names[:4])
            locations = [Location(n.path, n.start_line, n.end_line, "client", "graph", symbol=n.qualified_name) for n in (a, b)]
            locations += [Location(graph.nodes[t].path, graph.nodes[t].start_line, graph.nodes[t].start_line, "subsystem call", "graph",
                                   symbol=graph.nodes[t].qualified_name, relation=(a.qualified_name, graph.nodes[t].qualified_name, "CALLS"))
                          for t in sorted(shared)[:4]]
            signals.append(Signal("shared_call_sequence", anchor, "graph",
                                  f"{a.qualified_name} and {b.qualified_name} both call {', '.join(names[:4])}", locations,
                                  {"clients": [a.qualified_name, b.qualified_name], "subsystem": names}))
            for client in (a, b):
                files = {graph.nodes[t].path for t in callees[client.id]} - {client.path}
                if len(files) >= 4:
                    signals.append(Signal("fan_out_hub", anchor, "graph", f"{client.qualified_name} calls into {len(files)} files",
                                          [Location(client.path, client.start_line, client.end_line, "fan-out", "graph", symbol=client.qualified_name)],
                                          {"files": len(files)}))
    return signals


def metric_signals(structures: list[FileStructure], metrics: list[Evidence]) -> list[Signal]:
    signals: list[Signal] = []
    functions = [e for e in metrics if e.metric is not None and e.metric.scope == "function"]
    for structure in structures:
        for owner, method in structure.all_methods():
            match = next((e for e in functions if e.file_path == structure.path and e.start_line is not None
                          and method.start_line - 1 <= e.start_line <= method.end_line
                          and symbol_tail(e.metric.symbol) == method.name), None)
            if match is None:
                continue
            values = {m.key: m for m in match.metric.items}
            anchor = method_anchor(structure.path, owner, method)
            location = Location(structure.path, match.start_line, match.end_line, "measured metrics", "metrics", symbol=match.metric.symbol, metric=match)
            complexity = values.get("cyclomaticComplexity")
            if complexity is not None and complexity.value is not None:
                category = (complexity.category or "").lower()
                high = category in HIGH_COMPLEXITY_CATEGORIES if category else complexity.value >= HIGH_COMPLEXITY_FALLBACK
                if high:
                    signals.append(Signal("high_complexity", anchor, "metrics",
                                          f"{match.metric.symbol} has cyclomatic complexity {complexity.value:g}" + (f" ({complexity.category})" if complexity.category else ""),
                                          [location], {"cyclomaticComplexity": complexity.value, "category": complexity.category}))
            nloc = values.get("nloc")
            if nloc is not None and nloc.value is not None and nloc.value >= LONG_FUNCTION_NLOC:
                signals.append(Signal("long_function", anchor, "metrics", f"{match.metric.symbol} has {nloc.value:g} NLOC", [location], {"nloc": nloc.value}))
    return signals


def measured(metrics: list[Evidence], path: str, start: int | None, end: int | None, name: str) -> dict[str, float]:
    for e in metrics:
        if e.metric is None or e.metric.scope != "function" or e.file_path != path or e.start_line is None:
            continue
        if symbol_tail(e.metric.symbol) == name and (start is None or start - 1 <= e.start_line <= (end or e.start_line)):
            return {m.key: m.value for m in e.metric.items if m.value is not None}
    return {}
