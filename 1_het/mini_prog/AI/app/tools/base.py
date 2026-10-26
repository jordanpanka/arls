import asyncio
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Protocol

from pydantic import BaseModel, ValidationError

from app.agents.config import AgentConfig
from app.evidence.schemas import Evidence
from app.metrics.provider import MetricsProvider
from app.services.evidence_service import normalize_path

ToolErrorKind = Literal["not_found", "unavailable", "invalid_input", "timeout", "budget", "forbidden"]

SAFE_PATH = re.compile(r"^[\w .@+\-/\[\]()]+$")
SYMBOL_NAME = re.compile(r"^[\w.:$<>@/\-~]+$")


class ToolFailure(Exception):
    def __init__(self, kind: ToolErrorKind, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class ToolError(BaseModel):
    kind: ToolErrorKind
    message: str


class ToolResult(BaseModel):
    evidence: list[Evidence] = []
    summary: str = ""
    error: ToolError | None = None
    truncated: bool = False
    metadata: dict = {}


def safe_relative_path(value: str) -> str:
    raw = (value or "").strip()
    if not raw or "\x00" in raw:
        raise ValueError("path is empty")
    if re.match(r"^[A-Za-z]:", raw) or raw.startswith(("/", "\\", "~")):
        raise ValueError("absolute paths are not allowed")
    path = normalize_path(raw)
    while path.startswith("./"):
        path = path[2:]
    segments = path.split("/")
    if any(segment in ("..", "") for segment in segments):
        raise ValueError("path traversal is not allowed")
    if not SAFE_PATH.match(path) or len(path) > 400:
        raise ValueError("path contains unsupported characters")
    return path


def safe_symbol(value: str) -> str:
    symbol = (value or "").strip().strip("`'\"").removesuffix("()")
    if not symbol or len(symbol) > 300 or not SYMBOL_NAME.match(symbol):
        raise ValueError("symbol contains unsupported characters")
    return symbol


@dataclass(frozen=True)
class Scope:
    user_id: int
    investigation_id: int
    project_id: int


class SourceClient(Protocol):
    async def snapshot(self, scope: Scope) -> dict: ...

    async def read(self, scope: Scope, path: str, start_line: int | None, end_line: int | None, max_lines: int) -> dict: ...

    async def search(self, scope: Scope, pattern: str, is_regex: bool, path_glob: str | None,
                     extensions: list[str], max_results: int) -> dict: ...


@dataclass
class ToolDeps:
    embed: Callable[[str], Awaitable[list[float]]]
    vector_search: Callable[[Scope, str, list[float], int], Awaitable[list[dict]]]
    payload_lookup: Callable[[Scope, dict], Awaitable[list[dict]]]
    graph_loader: Callable[[Scope], Awaitable[Any]]
    source: SourceClient
    metrics: MetricsProvider


@dataclass
class ToolContext:
    scope: Scope
    snapshot: str
    config: AgentConfig
    deps: ToolDeps
    question: str = ""
    cache: dict = field(default_factory=dict)
    deadline: float | None = None

    def remaining(self) -> float | None:
        if self.deadline is None:
            return None
        return self.deadline - time.perf_counter()


Handler = Callable[[ToolContext, BaseModel], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Handler
    category: Literal["retrieval", "code", "graph", "metrics", "history", "patterns"]
    cacheable: bool = True


class ResultCache:
    def __init__(self, max_entries: int = 256):
        self.max_entries = max_entries
        self.entries: OrderedDict[str, ToolResult] = OrderedDict()

    def get(self, key: str) -> ToolResult | None:
        value = self.entries.get(key)
        if value is not None:
            self.entries.move_to_end(key)
        return value

    def put(self, key: str, value: ToolResult):
        self.entries[key] = value
        self.entries.move_to_end(key)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)


RESULT_CACHE = ResultCache()


def canonical_args(args: dict | BaseModel) -> str:
    data = args.model_dump() if isinstance(args, BaseModel) else args
    return json.dumps(data, sort_keys=True, default=str)


def call_signature(tool: str, args: dict | BaseModel) -> str:
    return f"{tool}:{canonical_args(args)}"


def _truncate(result: ToolResult, max_chars: int) -> ToolResult:
    with_content = [e for e in result.evidence if e.content]
    if not with_content:
        return result
    total = sum(len(e.content) for e in with_content)
    if total <= max_chars:
        return result
    per_item = max(200, max_chars // len(with_content))
    evidence = []
    for item in result.evidence:
        if item.content and len(item.content) > per_item:
            item = item.model_copy(update={
                "content": item.content[:per_item] + "\n[... truncated]",
                "metadata": {**item.metadata, "truncated": True},
            })
        evidence.append(item)
    return result.model_copy(update={"evidence": evidence, "truncated": True})


async def execute_tool(spec: ToolSpec, ctx: ToolContext, raw_args: dict | None, cache: ResultCache | None = RESULT_CACHE) -> tuple[ToolResult, BaseModel | None]:
    try:
        args = spec.args_schema.model_validate(raw_args or {})
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()[:5])
        return ToolResult(error=ToolError(kind="invalid_input", message=problems)), None

    key = f"{ctx.scope.project_id}|{ctx.snapshot}|{call_signature(spec.name, args)}"
    if spec.cacheable and cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached.model_copy(update={"metadata": {**cached.metadata, "cached": True}}), args

    timeout = ctx.config.tool_timeout_s
    remaining = ctx.remaining()
    if remaining is not None:
        if remaining <= 0:
            return ToolResult(error=ToolError(kind="budget", message="execution deadline reached")), args
        timeout = min(timeout, remaining)

    try:
        result = await asyncio.wait_for(spec.handler(ctx, args), timeout=timeout)
    except asyncio.TimeoutError:
        return ToolResult(error=ToolError(kind="timeout", message=f"{spec.name} exceeded {timeout:.0f}s")), args
    except ToolFailure as e:
        return ToolResult(error=ToolError(kind=e.kind, message=e.message[:300])), args
    except Exception as e:
        return ToolResult(error=ToolError(kind="unavailable", message=f"{type(e).__name__}: {str(e)[:200]}")), args

    stamped = [
        e.model_copy(update={"produced_by": e.produced_by or [spec.name]})
        for e in result.evidence
    ]
    result = _truncate(result.model_copy(update={"evidence": stamped}), ctx.config.max_tool_output_chars)

    if spec.cacheable and cache is not None and result.error is None:
        cache.put(key, result)
    return result, args
