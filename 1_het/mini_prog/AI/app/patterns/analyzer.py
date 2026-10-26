import re
import time
from dataclasses import dataclass, field

from app.evidence.schemas import Evidence, GraphRelation, with_identity
from app.metrics.provider import MetricsQuery, SymbolRef
from app.patterns.detector import Detection, detect, group_signals, subject_label
from app.patterns.knowledge_base import KnowledgeBase, default_knowledge_base
from app.patterns.models import AnalysisScope, Diagnostics, EvidenceRef, PatternAnalysis, PatternFinding
from app.patterns.recommender import Facts, classify_change, compare, recommend
from app.patterns.signals import (
    PRIMITIVES,
    Location,
    Signal,
    build_index,
    graph_signals,
    metric_signals,
    structural_signals,
)
from app.patterns.structure import FileStructure, language_for, parse_source
from app.services.evidence_service import build_metric_evidence, language_for_path, normalize_path
from app.tools.base import ToolContext, ToolFailure
from app.tools.change_tools import is_test_path
from app.tools.code_graph import get_code_graph

SNIPPET_LINES = 30
PAGE_LINES = 400


@dataclass
class AnalysisRequest:
    paths: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    change_request: str | None = None

    @property
    def key(self) -> str:
        return "|".join([",".join(sorted(self.paths)), ",".join(sorted(self.symbols)), (self.change_request or "").strip().lower()])


@dataclass
class AnalysisOutcome:
    analysis: PatternAnalysis
    evidence: dict[str, Evidence]
    existing: list[Detection]
    opportunities: list[Detection]


@dataclass
class _Run:
    ctx: ToolContext
    tool: str
    limitations: list[str] = field(default_factory=list)
    sources: dict[str, list[str]] = field(default_factory=dict)
    reads: int = 0
    searches: int = 0


async def _read_file(run: _Run, path: str) -> list[str] | None:
    cache = run.ctx.cache.setdefault("pattern_sources", {})
    if path in cache:
        return cache[path]
    limit = run.ctx.config.pattern_max_file_lines
    lines: list[str] = []
    start = 1
    while start <= limit:
        try:
            data = await run.ctx.deps.source.read(run.ctx.scope, path, start, min(start + PAGE_LINES - 1, limit), PAGE_LINES)
        except ToolFailure as e:
            if not lines:
                run.limitations.append(f"{path} could not be read ({e.kind})")
                cache[path] = None
                return None
            break
        run.reads += 1
        page = data.get("lines") or []
        lines += page
        total = int(data.get("totalLines") or 0)
        if not page or len(lines) >= total:
            break
        start += len(page)
    if len(lines) >= limit:
        run.limitations.append(f"{path} was analyzed up to line {limit} only")
    cache[path] = lines
    return lines


async def _parse(run: _Run, path: str) -> FileStructure | None:
    cache = run.ctx.cache.setdefault("pattern_structures", {})
    if path in cache:
        lines = run.ctx.cache.get("pattern_sources", {}).get(path)
        if lines is not None:
            run.sources[path] = lines
        return cache[path]
    if language_for(path) is None:
        cache[path] = None
        return None
    lines = await _read_file(run, path)
    if lines is None:
        return None
    run.sources[path] = lines
    try:
        structure = parse_source(path, "\n".join(lines))
    except Exception as e:
        run.limitations.append(f"{path} could not be parsed ({type(e).__name__})")
        structure = None
    cache[path] = structure
    return structure


async def _search_paths(run: _Run, pattern: str) -> list[str]:
    try:
        data = await run.ctx.deps.source.search(run.ctx.scope, pattern, True, None, [], 30)
    except ToolFailure as e:
        run.limitations.append(f"keyword search for related types failed ({e.kind})")
        return []
    run.searches += 1
    paths: list[str] = []
    for match in data.get("matches") or []:
        path = normalize_path(match.get("path"))
        if path and path not in paths and not is_test_path(path) and language_for(path):
            paths.append(path)
    return paths


async def _seed_paths(run: _Run, request: AnalysisRequest, graph) -> tuple[list[str], str]:
    seeds = [normalize_path(p) for p in request.paths]
    for symbol in request.symbols:
        nodes = graph.find(symbol) if graph is not None else []
        if nodes:
            seeds += [n.path for n in nodes[:3]]
            continue
        try:
            hits = await run.ctx.deps.payload_lookup(run.ctx.scope, {"name": symbol.split("::")[0].split(".")[-1]})
        except Exception:
            hits = []
        seeds += [normalize_path((h.get("payload") or {}).get("path")) for h in hits[:3]]
    seeds = [s for s in dict.fromkeys(seeds) if s]
    if seeds:
        return seeds, "requested"
    if not request.change_request:
        return [], "none"
    from app.tools.vector_tools import SemanticSearchArgs, semantic_code_search

    try:
        result = await semantic_code_search(run.ctx, SemanticSearchArgs(query=request.change_request[:500], top_k=6))
    except ToolFailure as e:
        run.limitations.append(f"no files were given and semantic search failed ({e.kind})")
        return [], "none"
    paths = [e.file_path for e in result.evidence if e.file_path and not is_test_path(e.file_path)]
    run.limitations.append("No files or symbols were given; the analyzed files were selected by semantic similarity to the request")
    return list(dict.fromkeys(paths))[:3], "semantic"


def _referenced_types(structures: list[FileStructure]) -> set[str]:
    names: set[str] = set()
    for structure in structures:
        for decl in structure.types:
            names |= set(decl.bases)
            for member in decl.fields:
                if member.type is not None:
                    names.add(member.type.element or member.type.name)
            for method in decl.methods:
                if method.return_type is not None:
                    names.add(method.return_type.name)
        for _, method in structure.all_methods():
            names |= {name for name, _ in method.creations}
    return {n for n in names if n and n[:1].isupper() and n not in PRIMITIVES and re.fullmatch(r"\w+", n)}


def _abstractions(structures: list[FileStructure]) -> set[str]:
    names = {d.name for s in structures for d in s.types if d.is_abstraction}
    names |= {b for s in structures for d in s.types for b in d.bases}
    return {n for n in names if re.fullmatch(r"\w+", n) and n not in PRIMITIVES}


async def _expand(run: _Run, structures: list[FileStructure], graph, budget: int) -> list[str]:
    if budget <= 0:
        return []
    parsed = {s.path for s in structures}
    declared = {d.name for s in structures for d in s.types}
    candidates: list[str] = []
    unresolved = sorted(_referenced_types(structures) - declared)
    for name in unresolved:
        nodes = [n for n in graph.find(name, "class") if n.kind == "class"] if graph is not None else []
        candidates += [n.path for n in nodes[:1]]
    abstractions = sorted(_abstractions(structures))
    if graph is not None:
        for name in abstractions:
            candidates += [n.path for n in graph.subclasses_of(name)[:4]]
    missing = [n for n in unresolved if not any(n == m.name for m in (graph.find(n, "class") if graph is not None else []))][:6]
    if missing:
        candidates += await _search_paths(run, rf"\b(class|interface|protocol|record|struct)\s+({'|'.join(missing)})\b")
    if abstractions and (graph is None or not graph.has_inheritance_data()):
        candidates += await _search_paths(run, rf"\bclass\s+\w+[^\n{{]*\b({'|'.join(abstractions[:6])})\b")
    return [p for p in dict.fromkeys(candidates) if p not in parsed][:budget]


async def _metrics(run: _Run, structures: list[FileStructure], signals: list[Signal], seeds: set[str]) -> list[Evidence]:
    from app.tools.metrics_tools import to_unified

    if not run.ctx.config.enable_metrics_tools:
        run.limitations.append("Code metrics are disabled for this run")
        return []
    anchored = {s.anchor for s in signals if "::" in s.anchor}
    refs: list[SymbolRef] = []
    for structure in structures:
        for owner, method in structure.all_methods():
            anchor = f"{structure.path}::{owner.name + '.' if owner else ''}{method.name}"
            if anchor in anchored or (structure.path in seeds and method.dispatches):
                refs.append(SymbolRef(path=structure.path, name=method.name, startLine=method.start_line))
    query = MetricsQuery(user_id=run.ctx.scope.user_id, investigation_id=run.ctx.scope.investigation_id, project_id=run.ctx.scope.project_id,
                         paths=sorted(seeds)[:5], symbols=refs[:10], include_repository=False, limit=10)
    try:
        data = await run.ctx.deps.metrics.fetch(query)
    except Exception as e:
        data = None
        run.limitations.append(f"Metrics backend unavailable ({type(e).__name__})")
    if not data:
        run.limitations.append("No stored code-metrics analysis is available; recommendations use structural evidence only")
        return []
    items = build_metric_evidence(data, max_files=5, max_functions=10)
    return [to_unified(i, run.tool) for i in items if i.scope != "repository"]


def _snippet(lines: list[str], start: int | None, end: int | None) -> str | None:
    if not lines or not start:
        return None
    last = min(end or start, start + SNIPPET_LINES - 1, len(lines))
    width = len(str(last))
    return "\n".join(f"{str(n).rjust(width)} | {lines[n - 1]}" for n in range(start, last + 1))


def _symbol_id(path: str, kind: str, name: str, line: int | None) -> str:
    return f"{path}::{kind}::{name}@{line or 0}"


def _evidence_for(run: _Run, location: Location, signal: Signal) -> Evidence | None:
    tool = run.tool
    if location.metric is not None:
        return location.metric.model_copy(update={"produced_by": [tool]})
    if location.source == "graph" and location.relation is not None:
        source_label, target_label, relation_type = location.relation
        source_id = _symbol_id(location.path, "class" if relation_type == "EXTENDS" else "function", source_label, location.start_line)
        target_id = f"type::{target_label}" if relation_type == "EXTENDS" else f"symbol::{target_label}"
        return Evidence(
            source_type="graph_relation", file_path=location.path, symbol_name=source_label, start_line=location.start_line,
            end_line=location.end_line, produced_by=[tool], group=f"pattern:{signal.id}:{signal.anchor}", certainty="direct",
            relation=GraphRelation(source=source_id, target=target_id, type=relation_type, source_label=source_label,
                                   target_label=target_label, source_path=location.path, source_line=location.start_line),
            metadata={"patternSignal": signal.id},
        )
    if location.source == "graph":
        return Evidence(
            source_type="graph_node", file_path=location.path, symbol_id=_symbol_id(location.path, "function", location.symbol or "?", location.start_line),
            symbol_name=location.symbol, symbol_kind="function", start_line=location.start_line, end_line=location.end_line,
            produced_by=[tool], group=f"pattern:{signal.id}:{signal.anchor}", metadata={"patternSignal": signal.id},
        )
    lines = run.sources.get(location.path) or []
    return Evidence(
        source_type="code_range", file_path=location.path, symbol_name=location.symbol, start_line=location.start_line,
        end_line=location.end_line, content=_snippet(lines, location.start_line, location.end_line),
        language=language_for_path(location.path), produced_by=[tool],
        metadata={"patternSignal": signal.id, "patternRole": location.role},
    )


def _finding(detection: Detection, facts: Facts) -> PatternFinding:
    return PatternFinding(
        pattern=detection.pattern.id, name=detection.pattern.name, kind=detection.kind, status=detection.status,
        subject=subject_label(detection.anchor), explanation=detection.rule.explanation,
        signals=sorted({s.id for s in detection.signals}), missing_signals=detection.missing, boosted_by=detection.boosted_by,
        counter_indications=detection.counter_indications, files=detection.files, evidence_ids=facts.signal_ids(detection.signals),
    )


async def analyze(ctx: ToolContext, request: AnalysisRequest, tool: str, kb: KnowledgeBase | None = None) -> AnalysisOutcome:
    kb = kb or default_knowledge_base()
    started = time.perf_counter()
    run = _Run(ctx=ctx, tool=tool)

    graph = None
    if ctx.config.enable_graph_tools:
        try:
            graph = await get_code_graph(ctx)
        except ToolFailure as e:
            run.limitations.append(f"Knowledge graph unavailable ({e.message}); callers, dependencies and stored inheritance were not used")
    else:
        run.limitations.append("Knowledge graph tools are disabled for this run")
    if graph is not None and graph.classes and not graph.has_inheritance_data():
        run.limitations.append("The code graph stores no inheritance data for this project (indexed before base types were recorded); inheritance was derived from the parsed files")

    seeds, selection = await _seed_paths(run, request, graph)
    if not seeds:
        raise ToolFailure("not_found", "no files to analyze: give paths or symbols, or a change request that matches indexed code")

    max_files = ctx.config.pattern_max_files
    structures: list[FileStructure] = []
    skipped: list[str] = []
    for path in seeds[:max_files]:
        structure = await _parse(run, path)
        if structure is None:
            if language_for(path) is None:
                skipped.append(path)
            continue
        structures.append(structure)
    if skipped:
        run.limitations.append(f"Structural analysis supports Python, C#, Java, TypeScript and JavaScript; skipped: {', '.join(skipped)}")
    if not structures:
        raise ToolFailure("not_found", "none of the selected files could be parsed for structural analysis")

    for path in await _expand(run, structures, graph, max_files - len(structures)):
        structure = await _parse(run, path)
        if structure is not None:
            structures.append(structure)

    change_kinds = classify_change(request.change_request)
    index = build_index(structures, graph)
    signals = structural_signals(structures, index) + graph_signals(structures, graph)
    seed_set = {s.path for s in structures if s.path in set(seeds)}
    metrics = await _metrics(run, structures, signals, seed_set)
    signals += metric_signals(structures, metrics)

    evidence_by_key: dict[tuple, Evidence] = {}
    ids: dict[tuple, str] = {}
    refs: dict[str, EvidenceRef] = {}
    for signal in signals:
        for location in signal.locations:
            if location.key in ids:
                continue
            item = _evidence_for(run, location, signal)
            if item is None:
                continue
            stamped = with_identity(item.model_copy(update={"project_id": ctx.scope.project_id, "repository_snapshot": ctx.snapshot}))
            ids[location.key] = stamped.evidence_id
            evidence_by_key[location.key] = item
            refs.setdefault(stamped.evidence_id, EvidenceRef(
                id=stamped.evidence_id, file_path=location.path, start_line=location.start_line, end_line=location.end_line,
                symbol=location.symbol, source=location.source, role=location.role, why=signal.why,
            ))

    facts = Facts(signals=signals, grouped=group_signals(signals), metrics=metrics, seed_files=seed_set, graph=graph, evidence_ids=ids)
    existing, opportunities = detect(kb, signals, change_kinds)

    analysis = PatternAnalysis(
        analysis_type="change_recommendation" if request.change_request else "pattern_detection",
        change_request=request.change_request,
        change_kinds=change_kinds,
        scope=AnalysisScope(files=[s.path for s in structures], languages=sorted({s.language for s in structures}), skipped=skipped, selection=selection),
        existing_patterns=[_finding(d, facts) for d in existing],
        detected_opportunities=[_finding(d, facts) for d in opportunities],
    )

    if request.change_request:
        recommendations, considered, basis = recommend(kb, change_kinds, existing, opportunities, facts)
        alternatives, rows, preferred, justification = compare(kb, change_kinds, recommendations, basis, facts)
        analysis.recommended_patterns = recommendations
        analysis.considered_patterns = considered
        analysis.no_pattern_needed = not recommendations
        analysis.alternatives = alternatives
        analysis.comparison = rows
        analysis.preferred_alternative = preferred
        analysis.justification = justification

    selected = _select_evidence(analysis, ctx.config.pattern_max_evidence)
    by_id = {ids[k]: e for k, e in evidence_by_key.items()}
    _restrict(analysis, set(selected))
    analysis.evidence = [refs[i] for i in selected]
    analysis.limitations = list(dict.fromkeys(run.limitations))
    analysis.diagnostics = Diagnostics(
        patterns_considered=[p.id for p in kb.patterns],
        patterns_detected=sorted({f.pattern for f in analysis.existing_patterns}),
        patterns_recommended=[r.pattern for r in analysis.recommended_patterns],
        signal_counts=_count(s.id for s in signals),
        evidence_sources=_count(r.source for r in analysis.evidence),
        files_parsed=len(structures),
        source_reads=run.reads,
        keyword_searches=run.searches,
        graph_used=graph is not None,
        metrics_used=bool(metrics),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return AnalysisOutcome(analysis=analysis, evidence={i: by_id[i] for i in selected if i in by_id}, existing=existing, opportunities=opportunities)


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _select_evidence(analysis: PatternAnalysis, limit: int) -> list[str]:
    ordered: list[str] = []
    groups = [
        [i for r in analysis.recommended_patterns for i in r.evidence_ids],
        [i for a in (analysis.alternatives.minimal_change, analysis.alternatives.pattern_refactoring) if a for i in a.evidence_ids],
        [i for f in analysis.existing_patterns for i in f.evidence_ids],
        [i for f in analysis.detected_opportunities for i in f.evidence_ids],
    ]
    for group in groups:
        for evidence_id in group:
            if evidence_id not in ordered and len(ordered) < limit:
                ordered.append(evidence_id)
    return ordered


def _restrict(analysis: PatternAnalysis, allowed: set[str]):
    for item in [*analysis.existing_patterns, *analysis.detected_opportunities, *analysis.recommended_patterns]:
        item.evidence_ids = [i for i in item.evidence_ids if i in allowed]
    for alternative in (analysis.alternatives.minimal_change, analysis.alternatives.pattern_refactoring):
        if alternative is not None:
            alternative.evidence_ids = [i for i in alternative.evidence_ids if i in allowed]
