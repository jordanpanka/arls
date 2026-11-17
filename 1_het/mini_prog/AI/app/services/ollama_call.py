from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx

from app.config import GEN_MODEL, GEN_MODEL_CLOUD, OLLAMA_API_KEY, OLLAMA_BASE_URL, OLLAMA_URL


@dataclass
class LlmResult:
    text: str
    input_tokens: int | None = 0
    output_tokens: int | None = 0


_usage_recorder: ContextVar[list | None] = ContextVar("llm_usage_recorder", default=None)
_failure_recorder: ContextVar[list | None] = ContextVar("llm_failure_recorder", default=None)


@contextmanager
def record_llm_usage():
    calls: list[dict] = []
    token = _usage_recorder.set(calls)
    try:
        yield calls
    finally:
        _usage_recorder.reset(token)


@contextmanager
def record_llm_failures():
    failures: list[str] = []
    token = _failure_recorder.set(failures)
    try:
        yield failures
    finally:
        _failure_recorder.reset(token)


def _record_failure(error: Exception, model: str | None) -> None:
    failures = _failure_recorder.get()
    if failures is not None:
        failures.append(f"{model}: {type(error).__name__}: {error}")


def _record(result: LlmResult, model: str) -> LlmResult:
    calls = _usage_recorder.get()
    if calls is not None:
        calls.append({"model": model, "inputTokens": result.input_tokens, "outputTokens": result.output_tokens})
    return result


def _optional_count(value) -> int | None:
    return None if value is None else int(value)


async def call_llm_with_usage(prompt: str, json_mode: bool = False, timeout: float = 300,
                              model: str | None = None, base_url: str | None = None,
                              options: dict | None = None) -> LlmResult:
    try:
        return await _call(prompt, json_mode, timeout, model, base_url, options)
    except Exception as e:
        _record_failure(e, model)
        raise


async def _call(prompt: str, json_mode: bool, timeout: float, model: str | None, base_url: str | None,
                options: dict | None) -> LlmResult:
    if base_url:
        headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else {}
        return await _generate(base_url, model or GEN_MODEL, headers, prompt, json_mode, timeout, options)

    if not OLLAMA_API_KEY:
        return await _generate(OLLAMA_BASE_URL, model or GEN_MODEL_CLOUD or GEN_MODEL, {}, prompt, json_mode, timeout, options)

    try:
        return await _generate(
            OLLAMA_BASE_URL,
            model or GEN_MODEL_CLOUD or GEN_MODEL,
            {"Authorization": f"Bearer {OLLAMA_API_KEY}"},
            prompt,
            json_mode,
            timeout,
            options,
        )
    except httpx.HTTPError as e:
        _record_failure(e, model or GEN_MODEL_CLOUD)
        print("Ollama Cloud hiba, helyi modellre váltás:", e)
        return await _generate(f"{OLLAMA_URL.rstrip('/')}/api", model or GEN_MODEL, {}, prompt, json_mode, timeout, options)


async def _generate(base_url: str, model: str, headers: dict, prompt: str, json_mode: bool, timeout: float,
                    options: dict | None = None) -> LlmResult:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    if json_mode:
        body["format"] = "json"
    if options:
        body["options"] = options

    async with httpx.AsyncClient(timeout=timeout) as client:

        response = await client.post(
            f"{base_url.rstrip('/')}/generate",
            headers=headers,
            json=body
        )

        response.raise_for_status()

        data = response.json()

        return _record(LlmResult(
            text=data["response"],
            input_tokens=_optional_count(data.get("prompt_eval_count")),
            output_tokens=_optional_count(data.get("eval_count")),
        ), model)


async def call_llm(prompt: str) -> str:
    return (await call_llm_with_usage(prompt)).text


def usage_counts(result: LlmResult | None) -> dict:
    input_tokens = result.input_tokens if result is not None else None
    output_tokens = result.output_tokens if result is not None else None
    return {
        "llm_calls": 1,
        "input_tokens": input_tokens or 0,
        "output_tokens": output_tokens or 0,
        "llm_calls_without_usage": int(input_tokens is None or output_tokens is None),
    }
