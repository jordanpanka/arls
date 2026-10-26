from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.evidence.schemas import Evidence, GraphRelation
from app.tools.base import ToolContext, ToolFailure, ToolResult, ToolSpec, call_signature, safe_relative_path, safe_symbol
from app.tools.code_graph import CallEdge, CodeGraph, SymbolNode, TypeEdge, get_code_graph

MAX_AMBIGUOUS_ROOTS = 3


class SymbolDepthArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=300, description="Symbol name, Class.method or symbol_id.")
    depth: int = Field(default=1, ge=1, le=3)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        return safe_symbol(value)


class TraceDependenciesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=400, description="Repository-relative file path or symbol name/symbol_id.")
    direction: Literal["incoming", "outgoing", "both"] = "both"
    depth: int = Field(default=1, ge=1, le=3)

    @field_validator("target")
    @classmethod
    def _target(cls, value: str) -> str:
        cleaned = value.strip()
        if "::" in cleaned:
            return safe_symbol(cleaned)
        if "/" in cleaned or "\\" in cleaned:
            return safe_relative_path(cleaned)
        return safe_symbol(cleaned)


class CallPathArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_symbol: str = Field(min_length=1, max_length=300)
    to_symbol: str = Field(min_length=1, max_length=300)
    max_depth: int = Field(default=4, ge=1, le=4)

    @field_validator("from_symbol", "to_symbol")
    @classmethod
    def _symbols(cls, value: str) -> str:
        return safe_symbol(value)


class RelatedSymbolsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=300)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        return safe_symbol(value)


def _roots(graph: CodeGraph, symbol: str, kinds: tuple[str, ...] = ("function", "method", "class")) -> list[SymbolNode]:
    nodes = [n for n in graph.find(symbol) if n.kind in kinds]
    if not nodes:
        raise ToolFailure("not_found", f"symbol '{symbol}' is not in the knowledge graph")
    return nodes


def _node_evidence(node: SymbolNode, tool: str, group: str, metadata: dict) -> Evidence:
    return Evidence(
        source_type="graph_node",
        file_path=node.path,
        symbol_id=node.symbol_id,
        symbol_name=node.qualified_name,
        symbol_kind=node.kind,
        start_line=node.start_line,
        end_line=node.end_line,
        produced_by=[tool],
        group=group,
        metadata=metadata,
    )


def _relation_evidence(graph: CodeGraph, edge: CallEdge, tool: str, group: str, relation_type: str = "CALLS") -> Evidence:
    source = graph.nodes[edge.source]
    target = graph.nodes[edge.target]
    return Evidence(
        source_type="graph_relation",
        file_path=source.path,
        symbol_id=source.symbol_id,
        symbol_name=source.qualified_name,
        symbol_kind=source.kind,
        start_line=source.start_line,
        end_line=source.end_line,
        certainty=edge.certainty,
        produced_by=[tool],
        group=group,
        relation=GraphRelation(
            source=source.symbol_id,
            target=target.symbol_id,
            type=relation_type,
            source_label=source.qualified_name,
            target_label=target.qualified_name,
            source_path=source.path,
            target_path=target.path,
            source_line=source.start_line,
            target_line=target.start_line,
            depth=edge.depth,
        ),
    )


def _type_evidence(graph: CodeGraph, edge: TypeEdge, tool: str, group: str) -> Evidence:
    evidence = _relation_evidence(graph, edge, tool, group, edge.type)
    details = {"member": edge.name, "line": edge.line, "injected": edge.injected or None, "collection": edge.collection or None}
    evidence.metadata.update({k: v for k, v in details.items() if v is not None})
    return evidence


TYPE_USAGE_LABELS = {
    "INSTANTIATES": "instantiations",
    "HAS_FIELD": "fields",
    "TAKES": "parameters",
    "RETURNS": "return types",
    "INHERITS": "subclasses",
    "IMPLEMENTS": "implementations",
}


def _ambiguity_note(roots: list[SymbolNode]) -> str:
    if len(roots) <= 1:
        return ""
    used = ", ".join(r.symbol_id for r in roots[:MAX_AMBIGUOUS_ROOTS])
    return f" (ambiguous name: {len(roots)} matches, explored {used})"


def _relation_lines(evidence: list[Evidence], limit: int = 12) -> str:
    lines = [
        f"{e.relation.source_label} -[{e.relation.type}]-> {e.relation.target_label} ({e.certainty}, depth {e.relation.depth})"
        for e in evidence if e.relation
    ]
    more = f"; +{len(lines) - limit} more" if len(lines) > limit else ""
    return "; ".join(lines[:limit]) + more


MAX_CLASS_MEMBERS = 12


def _callable_roots(graph: CodeGraph, symbol: str) -> tuple[list[SymbolNode], int]:
    nodes = _roots(graph, symbol)
    callables = [n for n in nodes if n.kind in ("function", "method")]
    if callables:
        return callables, MAX_AMBIGUOUS_ROOTS
    members = [m for cls in nodes if cls.kind == "class" for m in graph.members(cls)]
    if not members:
        raise ToolFailure("not_found", f"'{symbol}' has no functions or methods in the knowledge graph")
    return members, MAX_CLASS_MEMBERS


async def _neighbors(ctx: ToolContext, args: SymbolDepthArgs, tool: str, outgoing: bool) -> ToolResult:
    graph = await get_code_graph(ctx)
    roots, explore = _callable_roots(graph, args.symbol)
    via_class = explore == MAX_CLASS_MEMBERS
    depth = min(args.depth, ctx.config.max_graph_depth)
    group = call_signature(tool, args)
    evidence: list[Evidence] = []
    truncated = graph.truncated
    unresolved_names: list[str] = []
    counts = []

    for root in roots[:explore]:
        walk = graph.callees if outgoing else graph.callers
        edges, cut = walk(root.id, depth, ctx.config.max_graph_edges)
        truncated = truncated or cut
        relations = [_relation_evidence(graph, edge, tool, group) for edge in edges]
        unresolved = [u for u in graph.unresolved.get(root.id, [])] if outgoing else []
        unresolved_names += [u.name for u in unresolved]
        evidence.append(_node_evidence(root, tool, group, {
            "direction": "callees" if outgoing else "callers",
            "depth": depth,
            "relationCount": len(relations),
            "unresolvedCalls": [
                {"name": u.name, "candidates": u.candidates} for u in unresolved[:20]
            ],
        }))
        evidence.extend(relations)
        counts.append(f"{root.qualified_name}: {len(relations)} {'callees' if outgoing else 'callers'}")

    summary = "; ".join(counts)
    if via_class:
        summary = f"class {args.symbol} explored through its methods: " + summary
    else:
        summary += _ambiguity_note(roots)
    relations_text = _relation_lines(evidence)
    if relations_text:
        summary += " | " + relations_text
    if unresolved_names:
        summary += f" | unresolved calls (no unique definition in the project): {', '.join(sorted(set(unresolved_names))[:10])}"
    return ToolResult(evidence=evidence, summary=summary, truncated=truncated)


async def get_callers(ctx: ToolContext, args: SymbolDepthArgs) -> ToolResult:
    return await _neighbors(ctx, args, "get_callers", outgoing=False)


async def get_callees(ctx: ToolContext, args: SymbolDepthArgs) -> ToolResult:
    return await _neighbors(ctx, args, "get_callees", outgoing=True)


async def trace_dependencies(ctx: ToolContext, args: TraceDependenciesArgs) -> ToolResult:
    graph = await get_code_graph(ctx)
    if graph.has_file(args.target):
        path = safe_relative_path(args.target)
    else:
        roots = _roots(graph, args.target)
        path = roots[0].path

    depth = min(args.depth, ctx.config.max_graph_depth)
    group = call_signature("trace_dependencies", args)
    edges, truncated = graph.file_dependencies(path, args.direction, depth, ctx.config.max_graph_edges)

    evidence: list[Evidence] = [Evidence(
        source_type="graph_node",
        file_path=path,
        symbol_id=f"{path}::file",
        symbol_name=path,
        symbol_kind="file",
        produced_by=["trace_dependencies"],
        group=group,
        metadata={"direction": args.direction, "depth": depth, "relationCount": len(edges)},
    )]
    for source, target, info, level in edges:
        evidence.append(Evidence(
            source_type="graph_relation",
            file_path=source,
            symbol_id=f"{source}::file",
            symbol_name=source,
            symbol_kind="file",
            certainty=info["certainty"],
            produced_by=["trace_dependencies"],
            group=group,
            relation=GraphRelation(
                source=f"{source}::file", target=f"{target}::file", type="DEPENDS_ON",
                source_label=source, target_label=target, source_path=source, target_path=target, depth=level,
            ),
            metadata={"viaCalls": info["calls"], "viaTypes": info.get("types", 0)},
        ))

    imports = graph.imports.get(path, []) if args.direction in ("outgoing", "both") else []
    for module in imports[:15]:
        evidence.append(Evidence(
            source_type="graph_relation",
            file_path=path,
            symbol_id=f"{path}::file",
            symbol_name=path,
            symbol_kind="file",
            certainty="inferred",
            produced_by=["trace_dependencies"],
            group=group,
            relation=GraphRelation(
                source=f"{path}::file", target=f"module::{module}", type="IMPORTS",
                source_label=path, target_label=module, source_path=path,
            ),
            metadata={"note": "raw import statement; target not resolved to a project file"},
        ))

    summary = f"{path}: {len(edges)} file dependencies ({args.direction}, depth {depth}), {len(imports)} import statements"
    lines = _relation_lines(evidence)
    if lines:
        summary += " | " + lines
    return ToolResult(evidence=evidence, summary=summary, truncated=truncated or graph.truncated)


async def find_call_path(ctx: ToolContext, args: CallPathArgs) -> ToolResult:
    graph = await get_code_graph(ctx)
    sources = _roots(graph, args.from_symbol, ("function", "method"))
    targets = _roots(graph, args.to_symbol, ("function", "method"))
    depth = min(args.max_depth, ctx.config.max_graph_depth + 1)
    group = call_signature("find_call_path", args)

    for source in sources[:MAX_AMBIGUOUS_ROOTS]:
        for target in targets[:MAX_AMBIGUOUS_ROOTS]:
            path = graph.call_path(source.id, target.id, depth)
            if path:
                evidence = [_relation_evidence(graph, edge, "find_call_path", group) for edge in path]
                chain = " -> ".join([graph.nodes[path[0].source].qualified_name] + [graph.nodes[e.target].qualified_name for e in path])
                certainty = "inferred" if any(e.certainty != "direct" for e in path) else "direct"
                return ToolResult(evidence=evidence, summary=f"call path ({certainty}): {chain}")

    evidence = [
        _node_evidence(sources[0], "find_call_path", group, {"pathFound": False, "role": "from", "maxDepth": depth}),
        _node_evidence(targets[0], "find_call_path", group, {"pathFound": False, "role": "to", "maxDepth": depth}),
    ]
    return ToolResult(
        evidence=evidence,
        summary=f"no resolved call path from {args.from_symbol} to {args.to_symbol} within {depth} calls",
    )


async def get_related_symbols(ctx: ToolContext, args: RelatedSymbolsArgs) -> ToolResult:
    graph = await get_code_graph(ctx)
    roots = _roots(graph, args.symbol)
    root = roots[0]
    group = call_signature("get_related_symbols", args)
    evidence = [_node_evidence(root, "get_related_symbols", group, {"role": "root"})]

    def contains(owner: SymbolNode, member: SymbolNode) -> Evidence:
        return Evidence(
            source_type="graph_relation",
            file_path=owner.path,
            symbol_id=owner.symbol_id,
            symbol_name=owner.qualified_name,
            symbol_kind=owner.kind,
            start_line=owner.start_line,
            end_line=owner.end_line,
            produced_by=["get_related_symbols"],
            group=group,
            relation=GraphRelation(
                source=owner.symbol_id, target=member.symbol_id, type="CONTAINS",
                source_label=owner.qualified_name, target_label=member.qualified_name,
                source_path=owner.path, target_path=member.path,
                source_line=owner.start_line, target_line=member.start_line,
            ),
        )

    owner = graph.owner_of(root)
    if root.kind == "class":
        members = graph.members(root)
    elif owner is not None:
        members = [m for m in graph.members(owner) if m.id != root.id]
        evidence.append(contains(owner, root))
    else:
        members = []

    container = owner or root
    for member in members[: ctx.config.max_graph_edges]:
        evidence.append(contains(container, member))

    structural: list[TypeEdge] = []
    if root.kind == "class":
        structural += [e for e in graph.type_out.get(root.id, []) if e.type in ("INHERITS", "IMPLEMENTS", "HAS_FIELD")]
        structural += [e for e in graph.type_in.get(root.id, []) if e.type in ("INHERITS", "IMPLEMENTS")]
    elif root.kind == "method":
        structural += graph.overrides(root.id) + graph.overridden_by(root.id)
    for edge in structural[: ctx.config.max_graph_edges]:
        evidence.append(_type_evidence(graph, edge, "get_related_symbols", group))

    def labels(edges: list[TypeEdge], outgoing: bool) -> str:
        return ", ".join(graph.nodes[e.target if outgoing else e.source].qualified_name for e in edges[:10])

    outgoing = [e for e in structural if e.source == root.id]
    incoming = [e for e in structural if e.target == root.id]
    bases = [e for e in outgoing if e.type in ("INHERITS", "IMPLEMENTS")]
    fields = [e for e in outgoing if e.type == "HAS_FIELD"]
    subtypes = [e for e in incoming if e.type in ("INHERITS", "IMPLEMENTS")]
    overridden = [e for e in outgoing if e.type == "OVERRIDES"]
    overriding = [e for e in incoming if e.type == "OVERRIDES"]

    siblings = [n for n in graph.in_file(root.path) if n.id != root.id and n.kind in ("class", "function")][:15]
    kind = root.type_kind if root.kind == "class" and root.type_kind else root.kind
    summary = (
        f"{root.qualified_name} ({kind}) in {root.path}"
        + (f"; class {owner.qualified_name}" if owner else "")
        + (f"; extends/implements: {labels(bases, True)}" if bases else "")
        + (f"; extended/implemented by: {labels(subtypes, False)}" if subtypes else "")
        + (f"; fields: {', '.join(f'{e.name}: {graph.nodes[e.target].qualified_name}' for e in fields[:10])}" if fields else "")
        + (f"; events: {', '.join(root.events)}" if root.events else "")
        + (f"; overrides: {labels(overridden, True)}" if overridden else "")
        + (f"; overridden by: {labels(overriding, False)}" if overriding else "")
        + (f"; raises events: {', '.join(root.raises)}" if root.raises else "")
        + (f"; members: {', '.join(m.qualified_name for m in members[:12])}" if members else "")
        + (f"; other top-level symbols in file: {', '.join(s.qualified_name for s in siblings)}" if siblings else "")
        + _ambiguity_note(roots)
    )
    evidence[0].metadata["fileSymbols"] = [s.symbol_id for s in siblings]
    truncated = len(members) > ctx.config.max_graph_edges or len(structural) > ctx.config.max_graph_edges
    return ToolResult(evidence=evidence, summary=summary, truncated=truncated)


async def find_type_usages(ctx: ToolContext, args: RelatedSymbolsArgs) -> ToolResult:
    graph = await get_code_graph(ctx)
    matches = graph.find(args.symbol)
    roots = [n for n in matches if n.kind == "class"]
    if not roots:
        if matches:
            raise ToolFailure("not_found", f"'{args.symbol}' is not a class or interface in the knowledge graph; use get_callers for functions")
        raise ToolFailure("not_found", f"symbol '{args.symbol}' is not in the knowledge graph")

    group = call_signature("find_type_usages", args)
    budget = ctx.config.max_graph_edges
    truncated = graph.truncated
    evidence: list[Evidence] = []
    counts: list[str] = []

    for root in roots[:MAX_AMBIGUOUS_ROOTS]:
        usages = graph.type_usages(root.id)
        member_calls = [
            CallEdge(source=caller, target=member.id, certainty=certainty)
            for member in graph.members(root)
            for caller, certainty in sorted(graph.in_edges.get(member.id, {}).items())
            if graph.nodes[caller].owner_id != root.id
        ]
        if len(usages) + len(member_calls) > budget:
            truncated = True
        kept_usages = usages[:budget]
        kept_calls = member_calls[: max(0, budget - len(kept_usages))]
        by_kind = {kind: sum(1 for u in usages if u.type == kind) for kind in TYPE_USAGE_LABELS}
        evidence.append(_node_evidence(root, "find_type_usages", group, {
            "role": "root",
            "typeKind": root.type_kind,
            "usageCounts": {k: v for k, v in by_kind.items() if v},
            "memberCallers": len(member_calls),
        }))
        evidence += [_type_evidence(graph, u, "find_type_usages", group) for u in kept_usages]
        evidence += [_relation_evidence(graph, c, "find_type_usages", group) for c in kept_calls]
        parts = [f"{v} {TYPE_USAGE_LABELS[k]}" for k, v in by_kind.items() if v] + [f"{len(member_calls)} calls to its methods"]
        counts.append(f"{root.qualified_name}: " + ", ".join(parts))

    summary = "; ".join(counts) + _ambiguity_note(roots)
    if not graph.has_type_data():
        summary += " | type relations are not indexed for this project (re-index to add them); only calls to its methods are known"
    lines = _relation_lines(evidence)
    if lines:
        summary += " | " + lines
    return ToolResult(evidence=evidence, summary=summary, truncated=truncated)


GRAPH_TOOLS = [
    ToolSpec(
        name="get_callers",
        description="Functions/methods that call the given symbol (incoming CALLS), up to depth 3. Use for 'who uses X' and change-impact questions.",
        args_schema=SymbolDepthArgs,
        handler=get_callers,
        category="graph",
    ),
    ToolSpec(
        name="get_callees",
        description="Functions/methods the given symbol calls (outgoing CALLS), up to depth 3; also lists unresolved (library/ambiguous) calls.",
        args_schema=SymbolDepthArgs,
        handler=get_callees,
        category="graph",
    ),
    ToolSpec(
        name="trace_dependencies",
        description="File-level dependencies derived from cross-file calls (incoming, outgoing or both) plus raw import statements of a file or of the file containing a symbol.",
        args_schema=TraceDependenciesArgs,
        handler=trace_dependencies,
        category="graph",
    ),
    ToolSpec(
        name="find_call_path",
        description="Shortest resolved call chain from one function to another (max 4 calls).",
        args_schema=CallPathArgs,
        handler=find_call_path,
        category="graph",
    ),
    ToolSpec(
        name="get_related_symbols",
        description="Structural neighbourhood of a symbol: enclosing class, members, base classes and interfaces, subclasses and implementations, typed fields, events, and the methods a method overrides or is overridden by.",
        args_schema=RelatedSymbolsArgs,
        handler=get_related_symbols,
        category="graph",
    ),
    ToolSpec(
        name="find_type_usages",
        description="Everything that depends on a class or interface: where it is instantiated, held as a field, taken as a parameter or returned, which types extend or implement it, and which functions call its methods. Use for 'who uses class X' and class change-impact questions.",
        args_schema=RelatedSymbolsArgs,
        handler=find_type_usages,
        category="graph",
    ),
]
