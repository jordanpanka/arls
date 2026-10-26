import httpx

from app.config import BACKEND_URL, INTERNAL_API_KEY
from app.tools.base import Scope, ToolFailure


class BackendSourceClient:
    def __init__(self, base_url: str = BACKEND_URL, api_key: str = INTERNAL_API_KEY, timeout: float = 20):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def _post(self, scope: Scope, endpoint: str, body: dict) -> dict:
        url = f"{self.base_url}/api/internal/projects/{scope.project_id}/source/{endpoint}"
        payload = {"userId": scope.user_id, "investigationId": scope.investigation_id, **body}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers={"X-Internal-Key": self.api_key})
        except httpx.HTTPError as e:
            raise ToolFailure("unavailable", f"source backend unreachable: {type(e).__name__}")

        if response.status_code == 404:
            raise ToolFailure("not_found", _error_text(response) or "file not found in this project")
        if response.status_code in (401, 403):
            raise ToolFailure("forbidden", "project access denied")
        if response.status_code == 400:
            raise ToolFailure("invalid_input", _error_text(response) or "rejected by the source backend")
        if response.status_code != 200:
            raise ToolFailure("unavailable", f"source backend error {response.status_code}")
        return response.json()

    async def snapshot(self, scope: Scope) -> dict:
        return await self._post(scope, "files", {"includeFiles": False})

    async def read(self, scope: Scope, path: str, start_line: int | None, end_line: int | None, max_lines: int) -> dict:
        return await self._post(scope, "content", {
            "path": path,
            "startLine": start_line,
            "endLine": end_line,
            "maxLines": max_lines,
        })

    async def search(self, scope: Scope, pattern: str, is_regex: bool, path_glob: str | None,
                     extensions: list[str], max_results: int) -> dict:
        return await self._post(scope, "search", {
            "pattern": pattern,
            "isRegex": is_regex,
            "pathGlob": path_glob,
            "extensions": extensions,
            "maxResults": max_results,
        })


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    if isinstance(data, dict):
        return str(data.get("error") or "")[:200]
    return ""
