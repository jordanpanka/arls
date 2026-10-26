from dataclasses import dataclass

import httpx

from app.config import GEN_MODEL, GEN_MODEL_CLOUD, OLLAMA_API_KEY, OLLAMA_BASE_URL, OLLAMA_URL


@dataclass
class LlmResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


async def call_llm_with_usage(prompt: str, json_mode: bool = False, timeout: float = 300) -> LlmResult:
    if not OLLAMA_API_KEY:
        return await _generate(OLLAMA_BASE_URL, GEN_MODEL_CLOUD or GEN_MODEL, {}, prompt, json_mode, timeout)

    try:
        return await _generate(
            OLLAMA_BASE_URL,
            GEN_MODEL_CLOUD or GEN_MODEL,
            {"Authorization": f"Bearer {OLLAMA_API_KEY}"},
            prompt,
            json_mode,
            timeout,
        )
    except httpx.HTTPError as e:
        print("Ollama Cloud hiba, helyi modellre váltás:", e)
        return await _generate(f"{OLLAMA_URL.rstrip('/')}/api", GEN_MODEL, {}, prompt, json_mode, timeout)


async def _generate(base_url: str, model: str, headers: dict, prompt: str, json_mode: bool, timeout: float) -> LlmResult:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    if json_mode:
        body["format"] = "json"

    async with httpx.AsyncClient(timeout=timeout) as client:

        response = await client.post(
            f"{base_url.rstrip('/')}/generate",
            headers=headers,
            json=body
        )

        response.raise_for_status()

        data = response.json()

        return LlmResult(
            text=data["response"],
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )


async def call_llm(prompt: str) -> str:
    return (await call_llm_with_usage(prompt)).text
