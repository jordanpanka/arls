import asyncio
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.evidence.schemas import Evidence
from app.services.evidence_service import language_for_path, normalize_path, short_symbol_name
from app.tools.base import ToolContext, ToolFailure, ToolResult, ToolSpec, safe_relative_path, safe_symbol
from app.tools.code_graph import get_code_graph
from app.tools.vector_tools import SemanticSearchArgs, semantic_code_search

MAX_ANALOG_FILES = 3
MAX_SIBLINGS = 6
MAX_TEST_MATCHES = 15

EXTENSION_PATTERNS: dict[str, str] = {
    "dependency_injection": r"[Ss]ervices\.Add(Scoped|Singleton|Transient|HostedService|DbContext|HttpClient)\b",
    "http_route": r"\[(Http(Get|Post|Put|Delete|Patch)|Route)\b|@\w+\.(get|post|put|delete|patch|route)\(|app\.Map(Get|Post|Put|Delete|Controllers)\b",
    "router": r"include_router\(|<Route\b|createBrowserRouter|router\.(get|post|put|delete|use)\(|app\.use\(",
    "workflow_node": r"\.add_node\(|\.add_edge\(|\.add_conditional_edges\(",
    "registry": r"\bToolSpec\(|\bregister\w*\(|\b[A-Z][A-Z_]*(REGISTRY|HANDLERS|ROUTES|TOOLS|PLUGINS|COMMANDS)\b\s*(:[^=]+)?=",
}

TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$|Tests?\.\w+$",
    re.IGNORECASE,
)

STOPWORDS = {
    "that", "this", "with", "from", "into", "would", "should", "could", "where", "which", "what", "when",
    "have", "like", "want", "need", "make", "able", "there", "their", "some", "also", "feature", "function",
    "functionality", "implement", "implementation", "add", "adding", "new", "support", "change", "code",
}


def area_terms(text: str | None) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", text or "")
    terms = []
    for word in words:
        for part in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", word) or [word]:
            lowered = part.lower()
            if len(lowered) >= 4 and lowered not in STOPWORDS and lowered not in terms:
                terms.append(lowered)
    return terms[:12]


def is_test_path(path: str | None) -> bool:
    return bool(path) and bool(TEST_PATH.search(normalize_path(path)))


class SimilarImplementationsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=3, max_length=500, description="What the new feature should do, in English.")
    top_k: int = Field(default=5, ge=1, le=10)


class ExtensionPointsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: str | None = Field(default=None, max_length=300, description="Words describing the feature area, used to rank matches.")
    near_paths: list[str] = Field(default_factory=list, max_length=5, description="Files of an analogous feature; matches in the same folders rank first.")
    max_results: int = Field(default=15, ge=1, le=30)

    @field_validator("near_paths")
    @classmethod
    def _paths(cls, values: list[str]) -> list[str]:
        return [safe_relative_path(v) for v in values]


class TestsForArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=2, max_length=400, description="Symbol name, symbol_id or repository-relative file path of the code under test.")

    @field_validator("target")
    @classmethod
    def _target(cls, value: str) -> str:
        cleaned = value.strip()
        if "::" not in cleaned and ("/" in cleaned or "\\" in cleaned):
            return safe_relative_path(cleaned)
        return safe_symbol(cleaned)


def _graph_allowed(ctx: ToolContext) -> bool:
    return bool(getattr(ctx.config, "enable_graph_tools", True))


async def find_similar_implementations(ctx: ToolContext, args: SimilarImplementationsArgs) -> ToolResult:
    search = await semantic_code_search(ctx, SemanticSearchArgs(query=args.description, top_k=args.top_k))
    hits = [
        e.model_copy(update={"produced_by": ["find_similar_implementations"], "group": "analog"})
        for e in search.evidence
        if e.symbol_kind in ("function", "method", "class") and not is_test_path(e.file_path)
    ]
    if not hits:
        raise ToolFailure("not_found", "no existing implementation resembles the requested feature")

    files: list[str] = []
    for hit in hits:
        if hit.file_path not in files:
            files.append(hit.file_path)
    files = files[:MAX_ANALOG_FILES]

    siblings: list[Evidence] = []
    if _graph_allowed(ctx):
        try:
            graph = await get_code_graph(ctx)
        except ToolFailure:
            graph = None
        if graph is not None:
            taken = {(h.file_path, short_symbol_name(h.symbol_name or "")) for h in hits}
            for path in files:
                nodes = [n for n in graph.in_file(path) if (n.path, short_symbol_name(n.name)) not in taken]
                for node in nodes[:MAX_SIBLINGS]:
                    siblings.append(Evidence(
                        source_type="graph_node",
                        file_path=node.path,
                        symbol_id=node.symbol_id,
                        symbol_name=node.qualified_name,
                        symbol_kind=node.kind,
                        start_line=node.start_line,
                        end_line=node.end_line,
                        produced_by=["find_similar_implementations"],
                        group="analog_structure",
                        metadata={"analogFile": path},
                    ))

    ranked = [
        f"{h.file_path}:{h.start_line or '?'}-{h.end_line or '?'} {h.symbol_kind} {h.symbol_name or ''} (score {h.retrieval_score or 0:.2f})"
        for h in hits
    ]
    summary = "closest existing implementations: " + "; ".join(ranked)
    if siblings:
        summary += f"; {len(siblings)} neighbouring symbols in {', '.join(files)}"
    return ToolResult(evidence=hits + siblings, summary=summary, metadata={"analogFiles": files})


def _directories(paths: list[str]) -> list[str]:
    return [normalize_path(p).rsplit("/", 1)[0] for p in paths if "/" in normalize_path(p)]


def _rank(match: Evidence, terms: list[str], folders: list[str]) -> tuple:
    path = (match.file_path or "").lower()
    text = (match.content or "").lower()
    near = any(path.startswith(folder.lower() + "/") for folder in folders)
    overlap = sum(1 for t in terms if t in path or t in text)
    return (-int(near), -overlap, path, match.start_line or 0)


async def find_extension_points(ctx: ToolContext, args: ExtensionPointsArgs) -> ToolResult:
    async def search(kind: str, pattern: str):
        try:
            return kind, await ctx.deps.source.search(ctx.scope, pattern, True, None, [], 25), None
        except ToolFailure as e:
            return kind, None, e

    outcomes = await asyncio.gather(*(search(k, p) for k, p in EXTENSION_PATTERNS.items()))
    failures = [e for _, data, e in outcomes if e is not None]
    if len(failures) == len(outcomes):
        raise failures[0]

    matches: dict[tuple, Evidence] = {}
    for kind, data, _ in outcomes:
        for match in (data or {}).get("matches") or []:
            path = normalize_path(match.get("path"))
            line = match.get("line")
            if not path or not line or is_test_path(path) or (path, int(line)) in matches:
                continue
            matches[(path, int(line))] = Evidence(
                source_type="keyword_match",
                file_path=path,
                start_line=int(line),
                end_line=int(line),
                content=f"{line} | {(match.get('text') or '')[:300]}",
                language=language_for_path(path),
                produced_by=["find_extension_points"],
                group="extension_point",
                metadata={"extensionKind": kind},
            )

    if not matches:
        raise ToolFailure("not_found", "no registration, routing or dependency-injection sites were found")

    terms = area_terms(args.area)
    folders = _directories(args.near_paths)
    ranked = sorted(matches.values(), key=lambda m: _rank(m, terms, folders))[: args.max_results]

    by_file: dict[str, list[str]] = {}
    for item in ranked:
        by_file.setdefault(item.file_path, [])
        kind = item.metadata["extensionKind"]
        if kind not in by_file[item.file_path]:
            by_file[item.file_path].append(kind)
    summary = "extension points: " + "; ".join(f"{path} ({', '.join(kinds)})" for path, kinds in list(by_file.items())[:8])
    return ToolResult(evidence=ranked, summary=summary, truncated=len(matches) > len(ranked))


def _search_token(target: str) -> str:
    if target.count("::") >= 2:
        return short_symbol_name(target.split("::")[2].split("@")[0])
    if "/" in target:
        stem = target.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return re.sub(r"^(test_|Test)|(_test|Tests?)$", "", stem) or stem
    return short_symbol_name(target)


async def find_tests_for(ctx: ToolContext, args: TestsForArgs) -> ToolResult:
    token = _search_token(args.target)
    if len(token) < 2:
        raise ToolFailure("invalid_input", f"cannot derive a searchable name from '{args.target}'")
    data = await ctx.deps.source.search(ctx.scope, token, False, None, [], 50)
    evidence = []
    for match in data.get("matches") or []:
        path = normalize_path(match.get("path"))
        line = match.get("line")
        if not path or not line or not is_test_path(path):
            continue
        evidence.append(Evidence(
            source_type="keyword_match",
            file_path=path,
            start_line=int(line),
            end_line=int(line),
            content=f"{line} | {(match.get('text') or '')[:300]}",
            language=language_for_path(path),
            produced_by=["find_tests_for"],
            group="tests",
            metadata={"testedName": token},
        ))
    if not evidence:
        raise ToolFailure("not_found", f"no test file references '{token}'")
    files = sorted({e.file_path for e in evidence})
    return ToolResult(
        evidence=evidence[:MAX_TEST_MATCHES],
        summary=f"{len(evidence)} test references to '{token}' in {', '.join(files[:6])}",
        truncated=len(evidence) > MAX_TEST_MATCHES,
    )


CHANGE_TOOLS = [
    ToolSpec(
        name="find_similar_implementations",
        description="Find existing features that most resemble a feature the user wants to add, plus the neighbouring symbols in their files. Use first for 'how do I add / where should I implement' questions.",
        args_schema=SimilarImplementationsArgs,
        handler=find_similar_implementations,
        category="retrieval",
    ),
    ToolSpec(
        name="find_extension_points",
        description="Find where new functionality is wired in: dependency-injection registrations, HTTP routes, routers, workflow nodes and registries. Rank by feature area and the folders of an analogous feature.",
        args_schema=ExtensionPointsArgs,
        handler=find_extension_points,
        category="code",
    ),
    ToolSpec(
        name="find_tests_for",
        description="Find test files that reference a symbol or file, to show which tests a change must follow or extend.",
        args_schema=TestsForArgs,
        handler=find_tests_for,
        category="code",
    ),
]
