import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.evidence.schemas import Evidence
from app.services.evidence_service import language_for_path, normalize_path
from app.tools.base import ToolContext, ToolFailure, ToolResult, ToolSpec, safe_relative_path, safe_symbol
from app.tools.code_graph import SymbolNode, get_code_graph
from app.tools.vector_tools import hit_to_evidence

MAX_SYMBOL_MATCHES = 10


class FindSymbolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=300, description="Symbol name, Class.method, or a symbol_id returned earlier.")
    kind: Literal["any", "function", "method", "class"] = "any"
    path_hint: str | None = Field(default=None, description="Optional part of the file path to disambiguate.")

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return safe_symbol(value)

    @field_validator("path_hint")
    @classmethod
    def _hint(cls, value: str | None) -> str | None:
        return safe_relative_path(value) if value else None


class ReadCodeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=400, description="Repository-relative file path.")
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return safe_relative_path(value)

    @model_validator(mode="after")
    def _range(self):
        if self.start_line and self.end_line and self.end_line < self.start_line:
            raise ValueError("end_line must not be smaller than start_line")
        return self


class KeywordSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str = Field(min_length=2, max_length=200, description="Exact text, identifier or error message; a regex when is_regex is true.")
    is_regex: bool = False
    path_glob: str | None = Field(default=None, max_length=200, description="Optional glob such as src/**/*.py")
    extensions: list[str] = Field(default_factory=list, max_length=10)
    max_results: int = Field(default=20, ge=1, le=50)

    @field_validator("pattern")
    @classmethod
    def _pattern(cls, value: str, info) -> str:
        if "\x00" in value:
            raise ValueError("pattern contains a null byte")
        return value

    @field_validator("path_glob")
    @classmethod
    def _glob(cls, value: str | None) -> str | None:
        if not value:
            return None
        if ".." in value or value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
            raise ValueError("path_glob must be repository-relative")
        if not re.match(r"^[\w .*?/\-\[\]{},]+$", value):
            raise ValueError("path_glob contains unsupported characters")
        return value.replace("\\", "/")

    @field_validator("extensions")
    @classmethod
    def _extensions(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            ext = value if value.startswith(".") else "." + value
            if not re.match(r"^\.[A-Za-z0-9]{1,8}$", ext):
                raise ValueError(f"invalid extension {value!r}")
            cleaned.append(ext.lower())
        return cleaned

    @model_validator(mode="after")
    def _regex(self):
        if self.is_regex:
            try:
                re.compile(self.pattern)
            except re.error as e:
                raise ValueError(f"invalid regex: {e}")
        return self


def symbol_evidence(node: SymbolNode, produced_by: str) -> Evidence:
    return Evidence(
        source_type="symbol",
        file_path=node.path,
        symbol_id=node.symbol_id,
        symbol_name=node.qualified_name,
        symbol_kind=node.kind,
        start_line=node.start_line,
        end_line=node.end_line,
        language=language_for_path(node.path),
        produced_by=[produced_by],
        metadata={"containingClass": node.class_name, "graphNodeId": node.id},
    )


def _payload_symbol(hit: dict) -> Evidence | None:
    payload = hit.get("payload") or {}
    path = normalize_path(payload.get("path"))
    name = payload.get("name")
    if not path or not name:
        return None
    kind = payload.get("kind") or "symbol"
    start = payload.get("start_line")
    return Evidence(
        source_type="symbol",
        file_path=path,
        symbol_id=f"{path}::{kind}::{name}@{start or 0}",
        symbol_name=name,
        symbol_kind=kind,
        start_line=start,
        end_line=payload.get("end_line"),
        language=payload.get("language") or language_for_path(path),
        produced_by=["find_symbol"],
        metadata={"resolvedFrom": "vector_payload"},
    )


async def find_symbol(ctx: ToolContext, args: FindSymbolArgs) -> ToolResult:
    graph_error = None
    matches: list[Evidence] = []
    try:
        graph = await get_code_graph(ctx)
        nodes = graph.find(args.name, args.kind, args.path_hint)
        matches = [symbol_evidence(n, "find_symbol") for n in nodes[:MAX_SYMBOL_MATCHES]]
        total = len(nodes)
    except ToolFailure as e:
        graph_error = e
        total = 0

    if not matches:
        short = args.name.split("::")[0].split(".")[-1]
        try:
            hits = await ctx.deps.payload_lookup(ctx.scope, {"name": short})
        except Exception:
            hits = []
        seen = set()
        for hit in hits:
            evidence = _payload_symbol(hit)
            if evidence and evidence.symbol_id not in seen:
                if args.path_hint and args.path_hint not in (evidence.file_path or ""):
                    continue
                seen.add(evidence.symbol_id)
                matches.append(evidence)
        total = len(matches)
        matches = matches[:MAX_SYMBOL_MATCHES]

    if not matches:
        if graph_error is not None and graph_error.kind == "unavailable":
            raise ToolFailure("unavailable", f"symbol index unavailable ({graph_error.message})")
        raise ToolFailure("not_found", f"no symbol named '{args.name}' in this project")

    listing = "; ".join(f"{m.symbol_id}" for m in matches)
    prefix = f"{total} symbols match '{args.name}' (ambiguous): " if total > 1 else ""
    return ToolResult(
        evidence=matches,
        summary=prefix + listing,
        truncated=total > len(matches),
        metadata={"matches": total},
    )


def _numbered(lines: list[str], start: int) -> str:
    width = len(str(start + len(lines)))
    return "\n".join(f"{str(start + i).rjust(width)} | {line}" for i, line in enumerate(lines))


async def read_code(ctx: ToolContext, args: ReadCodeArgs) -> ToolResult:
    max_lines = ctx.config.max_read_lines
    start = args.start_line
    end = args.end_line
    if start and end and end - start + 1 > max_lines:
        end = start + max_lines - 1

    try:
        data = await ctx.deps.source.read(ctx.scope, args.path, start, end, max_lines)
    except ToolFailure as e:
        if e.kind != "not_found":
            raise
        return await _read_from_index(ctx, args, e)

    lines = data.get("lines") or []
    first = int(data.get("startLine") or start or 1)
    last = first + len(lines) - 1 if lines else first
    symbol_name = None
    graph = ctx.cache.get("code_graph")
    if graph is not None:
        enclosing = [
            n for n in graph.in_file(args.path)
            if n.start_line and n.start_line >= first and (n.end_line or n.start_line) <= last
        ]
        if len(enclosing) == 1:
            symbol_name = enclosing[0].qualified_name

    evidence = Evidence(
        source_type="code_range",
        file_path=normalize_path(data.get("path") or args.path),
        symbol_name=symbol_name,
        start_line=first,
        end_line=last,
        content=_numbered(lines, first),
        language=language_for_path(args.path),
        produced_by=["read_code"],
        metadata={"totalLines": data.get("totalLines")},
    )
    total = data.get("totalLines")
    truncated = bool(data.get("truncated")) or (end is not None and args.end_line is not None and end < args.end_line)
    return ToolResult(
        evidence=[evidence],
        summary=f"read {evidence.file_path}:{first}-{last}" + (f" of {total} lines" if total else ""),
        truncated=truncated,
    )


async def _read_from_index(ctx: ToolContext, args: ReadCodeArgs, original: ToolFailure) -> ToolResult:
    try:
        hits = await ctx.deps.payload_lookup(ctx.scope, {"path": args.path})
    except Exception:
        hits = []
    evidence = []
    for hit in hits:
        item = hit_to_evidence(hit, ctx.scope.project_id, "read_code")
        if item is None or not item.content:
            continue
        if args.start_line and item.end_line and item.end_line < args.start_line:
            continue
        if args.end_line and item.start_line and item.start_line > args.end_line:
            continue
        evidence.append(item.model_copy(update={
            "retrieval_score": None,
            "metadata": {**item.metadata, "fallback": "indexed_chunks"},
        }))
    if not evidence:
        raise original
    evidence.sort(key=lambda e: e.start_line or 0)
    return ToolResult(
        evidence=evidence[:8],
        summary=f"raw file unavailable; returned {len(evidence[:8])} indexed chunks of {args.path}",
        truncated=len(evidence) > 8,
        metadata={"fallback": "indexed_chunks"},
    )


async def keyword_code_search(ctx: ToolContext, args: KeywordSearchArgs) -> ToolResult:
    data = await ctx.deps.source.search(
        ctx.scope, args.pattern, args.is_regex, args.path_glob, args.extensions, args.max_results,
    )
    evidence = []
    for match in (data.get("matches") or [])[: args.max_results]:
        path = normalize_path(match.get("path"))
        line = match.get("line")
        if not path or not line:
            continue
        evidence.append(Evidence(
            source_type="keyword_match",
            file_path=path,
            start_line=int(line),
            end_line=int(line),
            content=f"{line} | {(match.get('text') or '')[:300]}",
            language=language_for_path(path),
            produced_by=["keyword_code_search"],
            metadata={"pattern": args.pattern, "isRegex": args.is_regex},
        ))
    if not evidence:
        return ToolResult(summary=f"no matches for '{args.pattern}'", truncated=bool(data.get("truncated")))
    files = sorted({e.file_path for e in evidence})
    return ToolResult(
        evidence=evidence,
        summary=f"{len(evidence)} matches in {len(files)} files: {', '.join(files[:8])}",
        truncated=bool(data.get("truncated")),
    )


CODE_TOOLS = [
    ToolSpec(
        name="find_symbol",
        description="Resolve a function, method or class name to its definition(s): stable symbol_id, kind, file and line range. Lists every match when the name is ambiguous.",
        args_schema=FindSymbolArgs,
        handler=find_symbol,
        category="code",
    ),
    ToolSpec(
        name="read_code",
        description="Read a bounded, line-numbered range of a repository file. Use after find_symbol to inspect an implementation.",
        args_schema=ReadCodeArgs,
        handler=read_code,
        category="code",
    ),
    ToolSpec(
        name="keyword_code_search",
        description="Exact text or regex search over repository source files (identifiers, error messages, config keys). Returns file, line and matched text.",
        args_schema=KeywordSearchArgs,
        handler=keyword_code_search,
        category="retrieval",
    ),
]
