import asyncio
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Awaitable, Callable

from app.agents.requirements import QuestionAnalysis, analyze_question
from app.evidence.sufficiency import name_matches
from app.services.ollama_call import LlmResult, usage_counts
from app.services.rag_graph import FALLBACK_CLASSIFICATION, NOT_FOUND_EN, build_classifier_prompt, parse_classification

ADAPTIVE_MODE = "adaptive_rag"
PIPELINE_MODE = "selective_rag"
AGENT_MODE = "evidence_aware_agentic_rag"

RELATION_KINDS = {"dependency_relations", "impact_relations", "call_path", "change_impact"}
CHANGE_KINDS = {"analogous_feature", "extension_point", "test_conventions", "change_risk"}
GRAPH_LOOKUP_KINDS = {"symbol_resolved", "definition_code", "dependency_relations"}
GRAPH_LOOKUP_OVERRIDES = {"use_graph": True}
MULTI_HOP_INTENTS = {"impact", "call_path"}
ANSWER_GAP_PATTERN = re.compile(
    r"\b(i (could not|couldn't|cannot|can't) find|not (shown|included|present|visible) in the (provided |given )?"
    r"(context|sources|snippets|code)|the (provided |given )?(context|sources|snippets) (do|does) not (show|include|contain)|"
    r"does not contain (the|any|enough)|nem (található|szerepel) a (megadott |kapott )?(kontextusban|forrásokban))",
    re.IGNORECASE,
)

LlmFn = Callable[[str, bool, float], Awaitable[LlmResult]]


@dataclass
class RouteDecision:
    mode: str
    reason: str
    complexity: str
    requirements: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    overrides: dict = field(default_factory=dict)
    analysis: QuestionAnalysis | None = None

    def to_dict(self) -> dict:
        return {
            "requested": ADAPTIVE_MODE,
            "chosen": self.mode,
            "reason": self.reason,
            "complexity": self.complexity,
            "requirements": self.requirements,
            "intents": self.intents,
        }


def is_graph_lookup(analysis: QuestionAnalysis, kinds: list[str]) -> bool:
    return (
        len(analysis.targets) == 1
        and not analysis.files
        and not analysis.mentions_class
        and not MULTI_HOP_INTENTS & set(analysis.intents)
        and "dependency_relations" in kinds
        and set(kinds) <= GRAPH_LOOKUP_KINDS
    )


def choose_strategy(analysis: QuestionAnalysis) -> RouteDecision:
    kinds = list(dict.fromkeys(r.kind for r in analysis.requirements))

    def decide(mode: str, reason: str, overrides: dict | None = None) -> RouteDecision:
        return RouteDecision(mode, reason, analysis.complexity, kinds, list(analysis.intents), dict(overrides or {}), analysis)

    if "change_planning" in analysis.intents or CHANGE_KINDS & set(kinds):
        return decide(AGENT_MODE, "change_planning_question")
    if "design_pattern" in analysis.intents or "pattern_analysis" in kinds:
        return decide(AGENT_MODE, "design_pattern_question")
    if "architecture" in analysis.intents:
        return decide(AGENT_MODE, "architecture_question")
    if is_graph_lookup(analysis, kinds):
        return decide(PIPELINE_MODE, "graph_lookup_question", GRAPH_LOOKUP_OVERRIDES)
    if RELATION_KINDS & set(kinds):
        return decide(AGENT_MODE, "relationship_question")
    if "file_context" in kinds:
        return decide(AGENT_MODE, "file_question")
    if analysis.complexity == "complex":
        return decide(AGENT_MODE, "complex_question")
    return decide(PIPELINE_MODE, f"{analysis.complexity}_question")


def _variants(target: str) -> set[str]:
    short = target.split(".")[-1]
    variants = {target, short}
    if len(short) > 3 and short.endswith("s"):
        variants |= {target[:-1], short[:-1]}
    return variants


def _mentions(target: str, hit: dict) -> bool:
    payload = hit.get("payload") or {}
    variants = _variants(target)
    name = payload.get("symbolName") or payload.get("name") or ""
    if name and any(name_matches(v, name) for v in variants):
        return True
    path = payload.get("path") or payload.get("filePath") or ""
    if isinstance(path, str) and PurePosixPath(path.replace("\\", "/")).stem in variants:
        return True
    text = payload.get("code") or payload.get("content") or payload.get("text") or ""
    return isinstance(text, str) and any(v.split(".")[-1] in text for v in variants)


def escalation_reason(analysis: QuestionAnalysis | None, result: dict) -> str | None:
    hits = result.get("top_results") or []
    if not hits:
        return "no_retrieval_results"
    answer = (result.get("answer_en") or result.get("answer") or "").strip()
    if not answer or answer.startswith(NOT_FOUND_EN):
        return "pipeline_not_found"
    if ANSWER_GAP_PATTERN.search(answer):
        return "answer_reports_gaps"
    if analysis is None:
        return None
    if analysis.targets and not any(_mentions(t, h) for t in analysis.targets for h in hits):
        return "targets_not_retrieved"
    kinds = {r.kind for r in analysis.requirements}
    if kinds & {"metrics", "hotspots"} and not result.get("metrics_results"):
        return "metrics_missing"
    if "dependency_relations" in kinds and result.get("use_graph") and not result.get("graph_subgraphs"):
        return "graph_relations_missing"
    return None


async def classify_once(question: str, llm: LlmFn, timeout: float) -> tuple[dict, dict]:
    classification = {**FALLBACK_CLASSIFICATION, "question_en": question}
    try:
        result = await asyncio.wait_for(llm(build_classifier_prompt(question), True, timeout), timeout=timeout)
    except Exception:
        return classification, usage_counts(None)
    usage = usage_counts(result)
    try:
        classification = parse_classification(result.text, question)
    except Exception:
        pass
    return classification, usage


async def route_question(question: str, llm: LlmFn, timeout: float) -> tuple[RouteDecision, dict, dict]:
    classification, usage = await classify_once(question, llm, timeout)
    analysis = analyze_question(question, classification["question_en"])
    return choose_strategy(analysis), classification, usage
