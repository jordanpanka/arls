import asyncio

import httpx

from app.config import QDRANT_COLLECTION, QDRANT_URL
from app.tools.base import Scope, ToolDeps
from app.tools.code_graph import CodeGraphData
from app.tools.source_client import BackendSourceClient


def scope_filter(scope: Scope) -> list[dict]:
    return [
        {"key": "userId", "match": {"value": scope.user_id}},
        {"key": "investigationId", "match": {"value": scope.investigation_id}},
        {"key": "projectId", "match": {"value": scope.project_id}},
    ]


async def embed_text(text: str) -> list[float]:
    from app.services.file_service import FileService

    async with httpx.AsyncClient(timeout=60) as http_client:
        return await FileService().embed(http_client, text)


async def qdrant_vector_search(scope: Scope, vector_name: str, vector: list[float], limit: int) -> list[dict]:
    from app.services.rag_graph import search_vector

    state = {
        "user_id": scope.user_id,
        "investigation_id": scope.investigation_id,
        "project_id": scope.project_id,
    }
    async with httpx.AsyncClient(timeout=30) as http_client:
        return await search_vector(vector_name, vector, http_client, state, limit=limit)


async def qdrant_payload_lookup(scope: Scope, match: dict) -> list[dict]:
    must = scope_filter(scope) + [{"key": key, "match": {"value": value}} for key, value in match.items()]
    async with httpx.AsyncClient(timeout=30) as http_client:
        response = await http_client.post(
            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/scroll",
            json={"filter": {"must": must}, "limit": 50, "with_payload": True, "with_vector": False},
        )
        response.raise_for_status()
    points = (response.json().get("result") or {}).get("points") or []
    return [{"payload": p.get("payload") or {}, "score": None} for p in points]


async def neo4j_graph_loader(scope: Scope) -> CodeGraphData:
    from app.services.neo4j_service import Neo4jService

    def load() -> dict:
        service = Neo4jService()
        try:
            return service.load_code_graph(scope.user_id, scope.investigation_id, scope.project_id)
        finally:
            service.close()

    return CodeGraphData(**await asyncio.to_thread(load))


def default_tool_deps() -> ToolDeps:
    from app.metrics.provider import BackendMetricsProvider

    return ToolDeps(
        embed=embed_text,
        vector_search=qdrant_vector_search,
        payload_lookup=qdrant_payload_lookup,
        graph_loader=neo4j_graph_loader,
        source=BackendSourceClient(),
        metrics=BackendMetricsProvider(),
    )
