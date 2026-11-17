import asyncio
import time
import uuid
from dataclasses import dataclass, field

from app.agents.config import AGENT_MODES
from app.agents.graph import AgentDeps
from app.agents.router import ADAPTIVE_MODE
from app.evaluation.trace_collector import MemoryTraceCollector, MultiTraceCollector
from app.models.models import ChatRequest, ChatResponse
from app.services import chat_service
from app.tools.base import Scope

PIPELINE_STRATEGIES = ("vector_rag", "selective_rag", "hybrid_rag")
FIXED_STRATEGIES = (*PIPELINE_STRATEGIES, "evidence_aware_agentic_rag")
DEFAULT_STRATEGIES = (*FIXED_STRATEGIES, ADAPTIVE_MODE)
EVAL_STRATEGIES = (*PIPELINE_STRATEGIES, *AGENT_MODES, ADAPTIVE_MODE)
METRICS_VARIANTS = ("default", "off")


class UnknownStrategyError(ValueError):
    pass


@dataclass
class EvalExecution:
    strategy: str
    metrics: str
    response: ChatResponse | None
    records: list[dict]
    wall_ms: float
    snapshot: dict = field(default_factory=dict)


def validate_strategy(strategy: str) -> str:
    name = (strategy or "").strip().lower()
    if name not in EVAL_STRATEGIES:
        raise UnknownStrategyError(f"Unknown evaluation strategy '{strategy}'. Supported: {', '.join(EVAL_STRATEGIES)}")
    return name


def validate_metrics(metrics: str) -> str:
    if metrics not in METRICS_VARIANTS:
        raise ValueError(f"Unknown metrics variant '{metrics}'. Supported: {', '.join(METRICS_VARIANTS)}")
    return metrics


def _ablation(strategy: str, metrics: str, ablation: str | None) -> str | None:
    if metrics == "off":
        if ablation not in (None, "full", "no_metrics"):
            raise ValueError("The metrics ablation cannot be combined with another agent ablation.")
        return "no_metrics"
    return ablation


async def repository_snapshot(scope: Scope, source=None, timeout: float = 10.0) -> dict:
    if source is None:
        from app.tools.defaults import default_tool_deps
        source = default_tool_deps().source
    try:
        info = await asyncio.wait_for(source.snapshot(scope), timeout=timeout)
    except Exception as e:
        return {"repositorySnapshot": None, "commitSha": None, "fileSetHash": None, "snapshotError": f"{type(e).__name__}: {e}"}
    commit = info.get("commitSha")
    file_set = info.get("fileSetHash")
    if commit:
        snapshot = f"commit:{commit}"
    elif file_set:
        snapshot = f"fs:{str(file_set)[:16].lower()}"
    else:
        snapshot = None
    return {"repositorySnapshot": snapshot, "commitSha": commit, "fileSetHash": file_set}


async def run_evaluation(request: ChatRequest, strategy: str, metrics: str = "default", trace=None,
                         deps: AgentDeps | None = None, run_id: str | None = None) -> EvalExecution:
    strategy = validate_strategy(strategy)
    metrics = validate_metrics(metrics)
    memory = MemoryTraceCollector()
    sink = MultiTraceCollector(trace, memory) if trace is not None else memory
    if deps is not None:
        deps = AgentDeps(tools=deps.tools, llm=deps.llm, trace=sink)
    run_id = run_id or uuid.uuid4().hex
    request = request.model_copy(update={"mode": strategy, "ablation": _ablation(strategy, metrics, request.ablation)})
    overrides = {"use_metrics": False} if metrics == "off" else None

    started = time.perf_counter()
    if strategy == ADAPTIVE_MODE:
        response = await chat_service._run_adaptive(request, run_id, sink, deps, extra_overrides=overrides)
    elif strategy in AGENT_MODES:
        response = await chat_service._run_agentic(request, strategy, run_id, sink, deps)
    else:
        response, _ = await chat_service._run_pipeline(request, strategy, run_id, sink, overrides=overrides)
    wall_ms = (time.perf_counter() - started) * 1000

    return EvalExecution(
        strategy=strategy,
        metrics=metrics,
        response=response,
        records=list(memory.records),
        wall_ms=round(wall_ms, 1),
    )
