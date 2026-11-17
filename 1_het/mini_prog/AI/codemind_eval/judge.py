import asyncio
import hashlib
import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel, Field, ValidationError

from codemind_eval.runner import append_record, latest_runs, read_runs
from codemind_eval.schema import Benchmark

JUDGE_SCHEMA = "codemind-eval-judgement/1"
MAX_CONTEXT_CHARS = 16000

JUDGE_PROMPT = """You are an impartial expert reviewer of answers to questions about a software repository.
You will see a QUESTION, an optional REFERENCE ANSWER written by a human annotator, the EVIDENCE that was given to the
answering system, and the CANDIDATE ANSWER. Evidence blocks are labelled like [SOURCE_1], [GRAPH_1], [METRIC_1];
the candidate cites them with the same labels. Judge only what is written; do not reward length or style.

Score the candidate:
- factual_correctness: integer 0-3 against the REFERENCE ANSWER.
  3 = fully correct, 2 = mostly correct with minor errors or omissions, 1 = partially correct with significant errors,
  0 = incorrect or does not answer. Use null when no reference answer is given.
- completeness: number 0-1, the share of the key points of the REFERENCE ANSWER covered by the candidate.
  Use null when no reference answer is given.
- faithfulness: number 0-1, the share of the candidate's factual claims about the code that are supported by the EVIDENCE.
- citation_correctness: number 0-1, the share of the candidate's citations whose cited evidence actually supports the
  sentence they are attached to. Use 0 when the candidate makes code claims but cites nothing; use null when the
  candidate makes no claims that need a citation.

Return only a JSON object with exactly these keys:
{{"factual_correctness": <0-3 or null>, "completeness": <0-1 or null>, "faithfulness": <0-1>,
  "citation_correctness": <0-1 or null>, "rationale": "<at most three sentences>"}}

QUESTION:
{question}

REFERENCE ANSWER:
{reference}

EVIDENCE:
{evidence}

CANDIDATE ANSWER:
{answer}
"""

PROMPT_VERSION = hashlib.sha256(JUDGE_PROMPT.encode("utf-8")).hexdigest()[:12]

STRATEGY_TERMS = re.compile(
    r"\b(vector_rag|selective_rag|hybrid_rag|agentic_rag|evidence_aware_agentic_rag|adaptive_rag|"
    r"semantic_code_search|keyword_code_search|find_symbol|read_code|get_callers|get_callees|trace_dependencies|"
    r"find_call_path|get_related_symbols|find_type_usages|get_code_metrics|find_quality_hotspots|"
    r"get_module_quality_summary|find_similar_implementations|find_extension_points|find_tests_for)\b",
    re.IGNORECASE,
)
MATCHED_VECTOR = re.compile(r"^Matched vector:.*$\n?", re.MULTILINE)
VIA_TOOL = re.compile(r" (?:via|from) \(?[a-z_]+(?:, [a-z_]+)*\)?(?=\s|$)")
MEASURED_BY = re.compile(r" \[measured by [^\]]+\]")
REPO_MARKERS = re.compile(r"<<<REPO_CONTENT|REPO_CONTENT>>>")


class JudgeScores(BaseModel):
    factual_correctness: int | None = Field(default=None, ge=0, le=3)
    completeness: float | None = Field(default=None, ge=0, le=1)
    faithfulness: float = Field(ge=0, le=1)
    citation_correctness: float | None = Field(default=None, ge=0, le=1)
    rationale: str = ""


class JudgeParseError(ValueError):
    pass


def blind_text(text: str | None) -> str:
    text = text or ""
    text = MATCHED_VECTOR.sub("", text)
    text = VIA_TOOL.sub("", text)
    text = MEASURED_BY.sub("", text)
    text = REPO_MARKERS.sub("", text)
    return STRATEGY_TERMS.sub("[tool]", text)


def build_prompt(question: str, reference: str | None, answer: str, context: str | None) -> str:
    evidence = blind_text(context).strip() or "(no evidence was provided to the system)"
    if len(evidence) > MAX_CONTEXT_CHARS:
        evidence = evidence[:MAX_CONTEXT_CHARS] + "\n[evidence truncated]"
    return JUDGE_PROMPT.format(
        question=question.strip(),
        reference=(reference or "").strip() or "(none)",
        evidence=evidence,
        answer=blind_text(answer).strip() or "(empty answer)",
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def parse_judgement(text: str, has_reference: bool) -> JudgeScores:
    try:
        data = json.loads(_strip_fences(text or ""))
    except json.JSONDecodeError as e:
        raise JudgeParseError(f"judge output is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise JudgeParseError("judge output is not a JSON object")
    if isinstance(data.get("factual_correctness"), float) and data["factual_correctness"].is_integer():
        data["factual_correctness"] = int(data["factual_correctness"])
    try:
        scores = JudgeScores.model_validate(data)
    except ValidationError as e:
        raise JudgeParseError(f"judge output failed validation: {e.errors()[0]['msg']}") from e
    if not has_reference:
        scores = scores.model_copy(update={"factual_correctness": None, "completeness": None})
    elif scores.factual_correctness is None or scores.completeness is None:
        raise JudgeParseError("judge omitted correctness or completeness although a reference answer was given")
    return scores


def judge_item_id(run_key: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}|{run_key}".encode("utf-8")).hexdigest()[:16]


JudgeFn = Callable[[str], Awaitable[object]]


@dataclass
class JudgeConfig:
    model: str
    base_url: str | None = None
    temperature: float = 0.0
    seed: int = 7
    retries: int = 2
    timeout_s: float = 300.0
    order_seed: int = 13


def ollama_judge(config: JudgeConfig) -> JudgeFn:
    from app.services.ollama_call import call_llm_with_usage

    async def call(prompt: str):
        return await call_llm_with_usage(
            prompt, json_mode=True, timeout=config.timeout_s, model=config.model, base_url=config.base_url,
            options={"temperature": config.temperature, "seed": config.seed},
        )
    return call


def judge_config_from_env(model: str | None = None, base_url: str | None = None) -> JudgeConfig:
    model = model or os.getenv("JUDGE_MODEL")
    if not model:
        raise ValueError("Set JUDGE_MODEL (or pass --judge-model). The judge never falls back to the generator model silently.")
    return JudgeConfig(model=model, base_url=base_url or os.getenv("JUDGE_BASE_URL") or None)


async def judge_run(record: dict, question, config: JudgeConfig, llm: JudgeFn, salt: str) -> dict:
    has_reference = bool(question.reference_answer)
    prompt = build_prompt(question.question, question.reference_answer, record.get("answer") or "", record.get("contextText"))
    out = {
        "schema": JUDGE_SCHEMA,
        "judgeItemId": judge_item_id(record["runKey"], salt),
        "runKey": record["runKey"],
        "questionId": record["questionId"],
        "judgeModel": config.model,
        "promptVersion": PROMPT_VERSION,
        "temperature": config.temperature,
        "seed": config.seed,
        "hasReference": has_reference,
        "evidenceAvailable": bool(record.get("contextText")),
    }
    errors: list[str] = []
    for attempt in range(1, config.retries + 2):
        try:
            result = await llm(prompt)
            scores = parse_judgement(getattr(result, "text", result), has_reference)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
            continue
        return {
            **out,
            **scores.model_dump(),
            "status": "ok",
            "attempts": attempt,
            "errors": errors,
            "judgeInputTokens": getattr(result, "input_tokens", None),
            "judgeOutputTokens": getattr(result, "output_tokens", None),
            "judgedAt": datetime.now(timezone.utc).isoformat(),
        }
    return {**out, "status": "judge_error", "attempts": config.retries + 1, "errors": errors,
            "judgedAt": datetime.now(timezone.utc).isoformat()}


def read_judgements(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in read_runs(path):
        key = record.get("runKey")
        if key and (key not in latest or record.get("status") == "ok" or latest[key].get("status") != "ok"):
            latest[key] = record
    return latest


async def judge_experiment(out_dir: Path, benchmark: Benchmark, config: JudgeConfig, llm: JudgeFn | None = None,
                           log=print) -> dict:
    llm = llm or ollama_judge(config)
    runs = [r for r in latest_runs(read_runs(out_dir / "runs.jsonl")).values() if r.get("status") == "ok"]
    path = out_dir / "judgements.jsonl"
    done = {k for k, j in read_judgements(path).items() if j.get("status") == "ok"}
    questions = benchmark.by_id()
    pending = [r for r in runs if r["runKey"] not in done and r.get("questionId") in questions]
    random.Random(config.order_seed).shuffle(pending)
    salt = out_dir.name
    counts = {"pending": len(pending), "ok": 0, "judge_error": 0, "skipped": len(done)}
    for index, record in enumerate(pending, start=1):
        judgement = await judge_run(record, questions[record["questionId"]], config, llm, salt)
        append_record(path, judgement)
        counts[judgement["status"]] += 1
        log(f"[judge {index}/{len(pending)}] {judgement['judgeItemId']}: {judgement['status']}")
    return counts


def run_judge(out_dir: Path, benchmark: Benchmark, config: JudgeConfig) -> dict:
    return asyncio.run(judge_experiment(out_dir, benchmark, config))
