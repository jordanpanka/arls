"""Access to persisted metrics for the RAG workflow.

The RAG graph depends on the ``MetricsProvider`` protocol only. The default
implementation asks the .NET backend, which owns the stored analyses, so the
workflow never touches database tables and always sees the same numbers as
the dashboard.
"""
from dataclasses import asdict, dataclass, field
from typing import Protocol

import httpx

from app.config import BACKEND_URL, INTERNAL_API_KEY


@dataclass
class SymbolRef:
    path: str
    name: str
    startLine: int | None = None


@dataclass
class MetricsQuery:
    user_id: int
    investigation_id: int
    project_id: int
    paths: list[str] = field(default_factory=list)
    symbols: list[SymbolRef] = field(default_factory=list)
    include_repository: bool = False
    focus: str = "general"
    limit: int = 5


class MetricsProvider(Protocol):
    async def fetch(self, query: MetricsQuery) -> dict | None:
        """Metrics for the requested entities; None when no analysis is available."""
        ...


class BackendMetricsProvider:
    def __init__(self, base_url: str = BACKEND_URL, api_key: str = INTERNAL_API_KEY, timeout: float = 15):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def fetch(self, query: MetricsQuery) -> dict | None:
        body = {
            "userId": query.user_id,
            "investigationId": query.investigation_id,
            "paths": query.paths,
            "symbols": [asdict(s) for s in query.symbols],
            "includeRepository": query.include_repository,
            "focus": query.focus,
            "limit": query.limit,
        }
        url = f"{self.base_url}/api/internal/projects/{query.project_id}/metrics/evidence"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=body, headers={"X-Internal-Key": self.api_key})
        except httpx.HTTPError as e:
            # Metrics are supplementary evidence: answering without them beats failing.
            print("Metrics backend unreachable:", e)
            return None

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            print(f"Metrics backend error {response.status_code}: {response.text[:200]}")
            return None

        data = response.json()
        return data if data.get("available") else None
