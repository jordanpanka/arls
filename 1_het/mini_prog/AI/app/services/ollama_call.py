import httpx

from app.config import GEN_MODEL, GEN_MODEL_CLOUD, OLLAMA_API_KEY, OLLAMA_BASE_URL

async def call_llm(prompt: str) -> str:

    # A local Ollama needs no auth, and httpx rejects a bare "Bearer " header,
    # so only send Authorization when a key is actually configured.
    headers = {}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    async with httpx.AsyncClient(timeout=300) as client:

        response = await client.post(
            f"{OLLAMA_BASE_URL}/generate",
            headers=headers,
            json={
                "model": GEN_MODEL_CLOUD,
                "prompt": prompt,
                "stream": False
            }
        )

        response.raise_for_status()

        data = response.json()

        return data["response"]