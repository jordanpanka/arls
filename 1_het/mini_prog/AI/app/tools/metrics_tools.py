from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.evidence.schemas import Evidence, MetricMeasurement, MetricValue
from app.metrics.provider import MetricsQuery, SymbolRef
from app.models.models import MetricEvidence
from app.services.evidence_service import build_metric_evidence, normalize_path
from app.tools.base import ToolContext, ToolFailure, ToolResult, ToolSpec, safe_relative_path, safe_symbol
from app.tools.code_graph import get_code_graph

GRAPH_METRIC_KEYS = {
    "fanIn", "fanOut", "importCount", "dependencyCount", "cycleCount",
    "averageFanIn", "averageFanOut", "maxFanIn", "maxFanOut", "maxDependencyDepth",
}

MetricFocus = Literal["complexity", "maintainability", "dependency", "size", "general"]


class CodeMetricsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(default_factory=list, max_length=10, description="Repository-relative file paths.")
    symbols: list[str] = Field(default_factory=list, max_length=10, description="Function/method names or symbol_ids.")

    @field_validator("paths")
    @classmethod
    def _paths(cls, values: list[str]) -> list[str]:
        return [safe_relative_path(v) for v in values]

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, values: list[str]) -> list[str]:
        return [safe_symbol(v) for v in values]

    @model_validator(mode="after")
    def _non_empty(self):
        if not self.paths and not self.symbols:
            raise ValueError("give at least one path or symbol")
        return self


class HotspotsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: MetricFocus = "complexity"
    limit: int = Field(default=5, ge=1, le=10)


class ModuleQualityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=400)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return safe_relative_path(value)


def analyzer_for(key: str) -> str:
    return "neo4j-graph" if key in GRAPH_METRIC_KEYS else "lizard"


def to_unified(item: MetricEvidence, tool: str) -> Evidence:
    measurement = MetricMeasurement(
        scope=item.scope,
        title=item.title,
        symbol=item.symbol,
        items=[
            MetricValue(
                key=m.key, label=m.label, value=m.value, unit=m.unit,
                category=m.category, analyzer=analyzer_for(m.key),
            )
            for m in item.items
        ],
        analysis_id=item.analysisId,
        analyzed_at=item.analyzedAt,
        commit_sha=item.commitSha,
    )
    return Evidence(
        source_type="metric",
        file_path=item.filePath,
        symbol_name=item.symbol,
        symbol_kind="function" if item.scope == "function" else item.scope,
        start_line=item.startLine,
        end_line=item.endLine,
        produced_by=[tool],
        metric=measurement,
        metadata={"hotspot": False},
    )


async def _fetch(ctx: ToolContext, query: MetricsQuery) -> dict:
    try:
        result = await ctx.deps.metrics.fetch(query)
    except Exception as e:
        raise ToolFailure("unavailable", f"metrics backend unavailable: {type(e).__name__}")
    if not result:
        raise ToolFailure("unavailable", "no completed code-metrics analysis is available for this project")
    return result


def _query(ctx: ToolContext, **kwargs) -> MetricsQuery:
    return MetricsQuery(
        user_id=ctx.scope.user_id,
        investigation_id=ctx.scope.investigation_id,
        project_id=ctx.scope.project_id,
        **kwargs,
    )


def _describe(evidence: list[Evidence]) -> str:
    parts = []
    for e in evidence[:10]:
        if not e.metric:
            continue
        values = ", ".join(
            f"{m.key}={m.value}" for m in e.metric.items
            if m.key in ("cyclomaticComplexity", "nloc", "fanIn", "fanOut", "maxComplexity", "averageComplexity")
        )
        parts.append(f"{e.metric.scope} {e.metric.title}" + (f" [{values}]" if values else ""))
    return "; ".join(parts)


async def _symbol_refs(ctx: ToolContext, names: list[str]) -> tuple[list[SymbolRef], list[str]]:
    refs: list[SymbolRef] = []
    missing: list[str] = []
    graph = None
    try:
        graph = await get_code_graph(ctx)
    except ToolFailure:
        graph = None
    for name in names:
        if "::" in name:
            path, _, rest = name.partition("::")
            label = rest.split("::")[-1]
            symbol, _, line = label.partition("@")
            refs.append(SymbolRef(path=normalize_path(path), name=symbol.split(".")[-1], startLine=int(line) if line.isdigit() and int(line) > 0 else None))
            continue
        nodes = [n for n in graph.find(name) if n.kind in ("function", "method")] if graph else []
        if not nodes:
            missing.append(name)
            continue
        for node in nodes[:3]:
            refs.append(SymbolRef(path=node.path, name=node.name, startLine=node.start_line))
    return refs, missing


async def get_code_metrics(ctx: ToolContext, args: CodeMetricsArgs) -> ToolResult:
    refs, missing = await _symbol_refs(ctx, args.symbols)
    if not args.paths and not refs:
        raise ToolFailure("not_found", f"could not resolve symbols for metrics: {', '.join(missing)}")
    data = await _fetch(ctx, _query(ctx, paths=args.paths, symbols=refs, include_repository=False, limit=10))
    items = build_metric_evidence(data, max_files=10, max_functions=10)
    evidence = [to_unified(i, "get_code_metrics") for i in items if i.scope != "repository"]
    if not evidence:
        raise ToolFailure("not_found", "the stored analysis has no metrics for the requested entities")
    summary = _describe(evidence)
    if missing:
        summary += f" | unresolved symbols: {', '.join(missing)}"
    return ToolResult(evidence=evidence, summary=summary)


async def find_quality_hotspots(ctx: ToolContext, args: HotspotsArgs) -> ToolResult:
    data = await _fetch(ctx, _query(ctx, include_repository=True, focus=args.focus, limit=args.limit))
    hotspot_data = {
        "analysis": data.get("analysis"),
        "repository": data.get("repository"),
        "hotspotFiles": data.get("hotspotFiles") or [],
        "hotspotFunctions": data.get("hotspotFunctions") or [],
    }
    items = build_metric_evidence(hotspot_data, max_files=args.limit, max_functions=args.limit)
    evidence = []
    for rank_source in items:
        unified = to_unified(rank_source, "find_quality_hotspots")
        if unified.metric and unified.metric.scope != "repository":
            unified.metadata = {"hotspot": True, "focus": args.focus}
        evidence.append(unified)
    for rank, item in enumerate([e for e in evidence if e.metadata.get("hotspot") and e.metric.scope == "function"], start=1):
        item.metadata["rank"] = rank
    for rank, item in enumerate([e for e in evidence if e.metadata.get("hotspot") and e.metric.scope == "file"], start=1):
        item.metadata["rank"] = rank
    if not evidence:
        raise ToolFailure("not_found", "the stored analysis lists no hotspots")
    thresholds = data.get("thresholds") or {}
    return ToolResult(
        evidence=evidence,
        summary=f"{args.focus} hotspots: " + _describe(evidence),
        metadata={"thresholds": thresholds},
    )


async def get_module_quality_summary(ctx: ToolContext, args: ModuleQualityArgs) -> ToolResult:
    refs: list[SymbolRef] = []
    try:
        graph = await get_code_graph(ctx)
        refs = [
            SymbolRef(path=n.path, name=n.name, startLine=n.start_line)
            for n in graph.in_file(args.path) if n.kind in ("function", "method")
        ][:10]
    except ToolFailure:
        refs = []
    data = await _fetch(ctx, _query(ctx, paths=[args.path], symbols=refs, include_repository=False, limit=10))
    items = build_metric_evidence(data, max_files=1, max_functions=10)
    evidence = [to_unified(i, "get_module_quality_summary") for i in items if i.scope != "repository"]
    if not evidence:
        raise ToolFailure("not_found", f"no metrics stored for {args.path}")
    return ToolResult(evidence=evidence, summary=_describe(evidence))


METRICS_TOOLS = [
    ToolSpec(
        name="get_code_metrics",
        description="Measured metrics (cyclomatic complexity, NLOC, parameters, fan-in/fan-out) for given files and/or functions from the stored analysis.",
        args_schema=CodeMetricsArgs,
        handler=get_code_metrics,
        category="metrics",
    ),
    ToolSpec(
        name="find_quality_hotspots",
        description="Repository-wide ranking of the worst files and functions for a focus (complexity, maintainability, dependency, size), plus repository summary metrics.",
        args_schema=HotspotsArgs,
        handler=find_quality_hotspots,
        category="metrics",
    ),
    ToolSpec(
        name="get_module_quality_summary",
        description="Metrics of one file and of the functions it contains.",
        args_schema=ModuleQualityArgs,
        handler=get_module_quality_summary,
        category="metrics",
    ),
]
