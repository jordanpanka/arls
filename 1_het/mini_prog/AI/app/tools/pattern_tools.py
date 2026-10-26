from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.patterns.analyzer import AnalysisOutcome, AnalysisRequest, analyze
from app.tools.base import ToolContext, ToolFailure, ToolResult, ToolSpec, safe_relative_path, safe_symbol

PATTERN_TOOL_NAMES = {"detect_design_patterns", "find_pattern_opportunities", "recommend_design_patterns", "compare_change_strategies"}


class PatternScopeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(default_factory=list, max_length=8, description="Repository-relative files to analyze.")
    symbols: list[str] = Field(default_factory=list, max_length=5, description="Classes or functions whose files should be analyzed.")

    @field_validator("paths")
    @classmethod
    def _paths(cls, values: list[str]) -> list[str]:
        return [safe_relative_path(v) for v in values]

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, values: list[str]) -> list[str]:
        return [safe_symbol(v) for v in values]

    @model_validator(mode="after")
    def _scope(self):
        if not self.paths and not self.symbols:
            raise ValueError("give at least one path or symbol")
        return self


class ChangeStrategyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_request: str = Field(min_length=5, max_length=500, description="The requested feature or modification, in English.")
    paths: list[str] = Field(default_factory=list, max_length=8, description="Files the change touches, e.g. from find_similar_implementations.")
    symbols: list[str] = Field(default_factory=list, max_length=5, description="Classes or functions the change touches.")

    @field_validator("paths")
    @classmethod
    def _paths(cls, values: list[str]) -> list[str]:
        return [safe_relative_path(v) for v in values]

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, values: list[str]) -> list[str]:
        return [safe_symbol(v) for v in values]


async def _outcome(ctx: ToolContext, request: AnalysisRequest, tool: str) -> AnalysisOutcome:
    analyses = ctx.cache.setdefault("pattern_analyses", {})
    if request.key in analyses:
        return analyses[request.key]
    if len(analyses) >= ctx.config.pattern_max_runs:
        raise ToolFailure("budget", f"design pattern analysis already ran {len(analyses)} times in this investigation; reuse its result")
    outcome = await analyze(ctx, request, tool)
    analyses[request.key] = outcome
    return outcome


def _result(outcome: AnalysisOutcome, operation: str, evidence_ids: list[str], summary: str) -> ToolResult:
    analysis = outcome.analysis.model_copy(deep=True)
    analysis.diagnostics.operations = [operation]
    chosen = [i for i in dict.fromkeys(evidence_ids) if i in outcome.evidence] or list(outcome.evidence)
    evidence = [outcome.evidence[i].model_copy(update={"produced_by": [operation]}) for i in chosen]
    return ToolResult(evidence=evidence, summary=summary, metadata={"patternAnalysis": analysis.model_dump(), "operation": operation})


def _status_list(findings) -> str:
    return "; ".join(f"{f.name} ({f.status}) at {f.subject}" for f in findings[:6]) or "none"


async def detect_design_patterns(ctx: ToolContext, args: PatternScopeArgs) -> ToolResult:
    outcome = await _outcome(ctx, AnalysisRequest(paths=args.paths, symbols=args.symbols), "detect_design_patterns")
    found = outcome.analysis.existing_patterns
    ids = [i for f in found for i in f.evidence_ids]
    return _result(outcome, "detect_design_patterns", ids,
                   f"existing patterns: {_status_list(found)} | files analyzed: {len(outcome.analysis.scope.files)}")


async def find_pattern_opportunities(ctx: ToolContext, args: PatternScopeArgs) -> ToolResult:
    outcome = await _outcome(ctx, AnalysisRequest(paths=args.paths, symbols=args.symbols), "find_pattern_opportunities")
    found = outcome.analysis.detected_opportunities
    ids = [i for f in found for i in f.evidence_ids]
    return _result(outcome, "find_pattern_opportunities", ids,
                   f"refactoring opportunities (hypotheses): {_status_list(found)}")


def _recommendation_summary(outcome: AnalysisOutcome) -> str:
    analysis = outcome.analysis
    if analysis.recommended_patterns:
        recs = "; ".join(f"{r.name} ({r.mode.replace('_', ' ')}, {r.confidence})" for r in analysis.recommended_patterns[:3])
    else:
        recs = "no design pattern needed"
    return f"recommended: {recs} | preferred: {analysis.preferred_alternative} | {analysis.justification[:300]}"


async def recommend_design_patterns(ctx: ToolContext, args: ChangeStrategyArgs) -> ToolResult:
    outcome = await _outcome(ctx, AnalysisRequest(paths=args.paths, symbols=args.symbols, change_request=args.change_request), "recommend_design_patterns")
    ids = [i for r in outcome.analysis.recommended_patterns for i in r.evidence_ids]
    return _result(outcome, "recommend_design_patterns", ids, _recommendation_summary(outcome))


async def compare_change_strategies(ctx: ToolContext, args: ChangeStrategyArgs) -> ToolResult:
    outcome = await _outcome(ctx, AnalysisRequest(paths=args.paths, symbols=args.symbols, change_request=args.change_request), "compare_change_strategies")
    alternatives = outcome.analysis.alternatives
    ids = [i for a in (alternatives.minimal_change, alternatives.pattern_refactoring) if a for i in a.evidence_ids]
    return _result(outcome, "compare_change_strategies", ids, _recommendation_summary(outcome))


PATTERN_TOOLS = [
    ToolSpec(
        name="detect_design_patterns",
        description="Detect design patterns already used in given files or symbols (Strategy, Observer, Factory Method, Adapter, Facade, Decorator, Repository) from AST structure, inheritance and the code graph. Reports confirmed/likely/possible with code locations.",
        args_schema=PatternScopeArgs,
        handler=detect_design_patterns,
        category="patterns",
    ),
    ToolSpec(
        name="find_pattern_opportunities",
        description="Find refactoring opportunities (long conditional dispatch, type-dependent creation, repeated notification, shared call sequences) in given files or symbols. Results are hypotheses with evidence, not proof.",
        args_schema=PatternScopeArgs,
        handler=find_pattern_opportunities,
        category="patterns",
    ),
    ToolSpec(
        name="recommend_design_patterns",
        description="For a requested change: recommend a design pattern or conclude that none is needed, and compare a minimal change with a pattern-based refactoring using structure, graph and measured metrics. Call once, after the touched files are known.",
        args_schema=ChangeStrategyArgs,
        handler=recommend_design_patterns,
        category="patterns",
    ),
    ToolSpec(
        name="compare_change_strategies",
        description="Compare the minimal modification with a pattern-based refactoring for a requested change (affected files, callers, measured complexity, coupling, regression risk) and pick the better one.",
        args_schema=ChangeStrategyArgs,
        handler=compare_change_strategies,
        category="patterns",
    ),
]
