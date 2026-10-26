from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.schemas import Evidence
from app.services.evidence_service import language_for_path, result_location
from app.tools.base import ToolContext, ToolFailure, ToolResult, ToolSpec

CODE_KINDS = {"function", "method", "class"}


class SemanticSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500, description="Natural-language or keyword query, in English.")
    top_k: int = Field(default=6, ge=1, le=10)
    vectors: list[Literal["code", "summary", "text"]] = Field(default_factory=lambda: ["code", "summary"], min_length=1, max_length=3)


def payload_text(payload: dict) -> str:
    kind = payload.get("kind")
    if kind in CODE_KINDS:
        return payload.get("code") or payload.get("content") or ""
    return payload.get("text") or payload.get("content") or payload.get("chunk") or payload.get("code") or ""


def hit_to_evidence(hit: dict, scope_project: int, produced_by: str, source_type: str = "code_chunk") -> Evidence | None:
    payload = hit.get("payload") or {}
    if payload.get("projectId") not in (None, scope_project):
        return None
    location = result_location(hit)
    if not location["filePath"]:
        return None
    content = payload_text(payload)
    return Evidence(
        source_type=source_type,
        file_path=location["filePath"],
        symbol_name=location["symbolName"] or None,
        symbol_kind=location["symbolType"] or None,
        start_line=location["startLine"],
        end_line=location["endLine"],
        content=content or None,
        language=location["language"] or language_for_path(location["filePath"]),
        retrieval_score=float(hit["score"]) if isinstance(hit.get("score"), (int, float)) else None,
        produced_by=[produced_by],
        metadata={
            "matchedVector": hit.get("matched_vector"),
            "summary": (payload.get("summary") or "")[:400] or None,
        },
    )


async def semantic_code_search(ctx: ToolContext, args: SemanticSearchArgs) -> ToolResult:
    try:
        vector = await ctx.deps.embed(args.query)
    except Exception as e:
        raise ToolFailure("unavailable", f"embedding service unavailable: {type(e).__name__}")

    hits: list[dict] = []
    for vector_name in args.vectors:
        try:
            results = await ctx.deps.vector_search(ctx.scope, vector_name, vector, args.top_k)
        except Exception as e:
            raise ToolFailure("unavailable", f"vector store unavailable: {type(e).__name__}")
        for hit in results:
            hits.append({**hit, "matched_vector": vector_name})

    best: dict[tuple, dict] = {}
    for hit in hits:
        location = result_location(hit)
        key = (location["filePath"], location["startLine"], location["endLine"])
        if key not in best or (hit.get("score") or 0) > (best[key].get("score") or 0):
            best[key] = hit

    ranked = sorted(best.values(), key=lambda h: h.get("score") or 0, reverse=True)[: args.top_k]
    evidence = [e for e in (hit_to_evidence(h, ctx.scope.project_id, "semantic_code_search") for h in ranked) if e]
    if not evidence:
        return ToolResult(summary="no semantically similar code found")

    lines = [
        f"{e.file_path}:{e.start_line or '?'}-{e.end_line or '?'} {e.symbol_kind or ''} {e.symbol_name or ''} (score {e.retrieval_score or 0:.2f})"
        for e in evidence
    ]
    return ToolResult(evidence=evidence, summary="; ".join(lines))


VECTOR_TOOLS = [
    ToolSpec(
        name="semantic_code_search",
        description="Semantic (embedding) search over indexed code chunks, summaries and docs. Use when the question names no exact symbol or to discover where a concept is implemented.",
        args_schema=SemanticSearchArgs,
        handler=semantic_code_search,
        category="retrieval",
    ),
]
