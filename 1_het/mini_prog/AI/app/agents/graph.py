import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from app.agents.config import AgentConfig
from app.agents.planner import PlanOutcome, fallback_calls, parse_plan, validate_calls
from app.agents.prompts import (
    ANSWER_PROMPT,
    CHANGE_PLAN_PROMPT,
    NOT_FOUND_EN,
    PATTERN_PLAN_BLOCK,
    PATTERN_REVIEW_PROMPT,
    PLANNER_PROMPT,
    REVISION_BLOCK,
    evidence_line,
    render_block,
    render_pattern_analysis,
)
from app.agents.requirements import PATTERN_TOOLS
from app.agents.requirements import QuestionAnalysis, analyze_question as analyze_requirements
from app.agents.state import AgentState
from app.evaluation.trace_collector import summarize_tool_log
from app.evidence.store import EvidenceScopeError, EvidenceStore
from app.evidence.sufficiency import (
    RequirementStatus,
    evaluate_sufficiency,
    llm_assessment_prompt,
    parse_llm_hints,
)
from app.evidence.verifier import CITATION, llm_verification_prompt, verify_answer
from app.services.ollama_call import LlmResult, call_llm_with_usage
from app.services.rag_graph import (
    FALLBACK_CLASSIFICATION,
    METRICS_RULES,
    build_classifier_prompt,
    build_translation_prompt,
    parse_classification,
)
from app.tools.base import Scope, ToolContext, ToolDeps, ToolSpec, execute_tool
from app.tools.registry import build_registry, catalogue_text
from app.tools.vector_tools import hit_to_evidence

LlmFn = Callable[[str, bool, float], Awaitable[LlmResult]]


async def default_llm(prompt: str, json_mode: bool, timeout: float) -> LlmResult:
    return await call_llm_with_usage(prompt, json_mode=json_mode, timeout=timeout)


@dataclass
class AgentDeps:
    tools: ToolDeps
    llm: LlmFn = default_llm
    trace: object | None = None


@dataclass
class AgentRuntime:
    deps: AgentDeps
    config: AgentConfig
    registry: dict[str, ToolSpec]
    tool_ctx: ToolContext
    llm_errors: list[str] = field(default_factory=list)


def _runtime(config: RunnableConfig) -> AgentRuntime:
    return config["configurable"]["runtime"]


def _tokens(state: AgentState) -> int:
    return (state.get("input_tokens") or 0) + (state.get("output_tokens") or 0)


def _remaining(state: AgentState) -> float:
    deadline = state.get("deadline")
    return float("inf") if deadline is None else deadline - time.perf_counter()


async def _ask(runtime: AgentRuntime, state: AgentState, prompt: str, json_mode: bool, bounded: bool = True) -> tuple[LlmResult | None, dict]:
    timeout = runtime.config.llm_timeout_s
    if bounded:
        timeout = min(timeout, max(_remaining(state), 1.0))
    try:
        result = await asyncio.wait_for(runtime.deps.llm(prompt, json_mode, timeout), timeout=timeout)
    except Exception as e:
        runtime.llm_errors.append(type(e).__name__)
        return None, {"llm_calls": 1}
    return result, {
        "llm_calls": 1,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def _budget_stop(state: AgentState, config: AgentConfig) -> str | None:
    if (state.get("iteration") or 0) >= config.effective_max_iterations:
        return "max_iterations"
    if (state.get("tool_calls") or 0) >= config.max_tool_calls:
        return "max_tool_calls"
    if _tokens(state) >= config.token_budget:
        return "token_budget"
    if _remaining(state) <= 0:
        return "timeout"
    return None


def _analysis(state: AgentState) -> QuestionAnalysis:
    return QuestionAnalysis.from_dict(state.get("analysis") or {})


def _statuses(state: AgentState) -> list[RequirementStatus] | None:
    data = state.get("sufficiency")
    if not data:
        return None
    return [RequirementStatus(**{k: v for k, v in r.items()}) for r in data.get("requirements", [])]


def _current_sufficiency(state: AgentState, runtime: AgentRuntime, store: EvidenceStore):
    return evaluate_sufficiency(
        analysis=_analysis(state),
        evidence=store.all(),
        tool_log=state.get("tool_log") or [],
        snapshot=store.snapshot,
        thresholds=runtime.config.sufficiency,
        available_tools=set(runtime.registry),
        budget_left=True,
        made_progress=True,
    )


async def init_context(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    scope = runtime.tool_ctx.scope
    snapshot = f"project:{scope.project_id}"
    source = "fallback"
    try:
        info = await asyncio.wait_for(runtime.deps.tools.source.snapshot(scope), timeout=min(10.0, runtime.config.tool_timeout_s))
        if info.get("commitSha"):
            snapshot, source = f"commit:{info['commitSha']}", "commit"
        elif info.get("fileSetHash"):
            snapshot, source = f"fs:{str(info['fileSetHash'])[:16].lower()}", "file_set_hash"
    except Exception:
        pass
    runtime.tool_ctx.snapshot = snapshot
    store = EvidenceStore(scope.project_id, snapshot, capacity=runtime.config.max_evidence_items)
    for hit in state.get("seed_hits") or []:
        evidence = hit_to_evidence(hit, scope.project_id, "semantic_code_search")
        if evidence is None:
            continue
        try:
            store.add(evidence)
        except EvidenceScopeError:
            continue
    return {
        "repository_snapshot": snapshot,
        "snapshot_source": source,
        "iteration": 0,
        "tool_calls": 0,
        "call_signatures": [],
        "evidence": store.items,
        "aliases": store.aliases_state(),
        "seeded_evidence": len(store.items),
        "revisions": 0,
    }


async def analyze_question(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    question = state["question"]
    classification = state.get("classification")
    usage: dict = {}
    if not classification:
        result, usage = await _ask(runtime, state, build_classifier_prompt(question), json_mode=True)
        classification = {**FALLBACK_CLASSIFICATION, "question_en": question}
        if result is not None:
            try:
                classification = parse_classification(result.text, question)
            except Exception:
                pass
    analysis = analyze_requirements(question, classification["question_en"])
    if not runtime.config.enable_pattern_analysis:
        analysis.requirements = [r for r in analysis.requirements if r.kind != "pattern_analysis"]
    runtime.tool_ctx.question = classification["question_en"]
    return {
        **usage,
        "question_en": classification["question_en"],
        "language": classification["language"],
        "language_name": classification["language_name"],
        "question_type": classification["question_type"],
        "analysis": analysis.to_dict(),
        "complexity": analysis.complexity,
    }


def _needs_section(state: AgentState, runtime: AgentRuntime, statuses: list[RequirementStatus] | None) -> str:
    if not runtime.config.enable_sufficiency or statuses is None:
        return ""
    lines = ["OPEN NEEDS (from the evidence check):"]
    for status in statuses:
        if status.status == "satisfied":
            continue
        note = f" - {status.note}" if status.note else ""
        lines.append(f"- [{status.status}] {status.description}{note}")
    hints = state.get("missing_information") or []
    lines += [f"- [hint] {h}" for h in hints if h not in lines]
    return "\n".join(lines) if len(lines) > 1 else "OPEN NEEDS: none"


def _calls_section(tool_log: list[dict]) -> str:
    if not tool_log:
        return "(none)"
    lines = []
    for entry in tool_log[-20:]:
        outcome = f"error {entry['error']['kind']}: {entry['error']['message'][:120]}" if entry.get("error") else entry.get("summary", "")[:300]
        lines.append(f"- {entry['tool']} {entry.get('argsText', '')} -> {outcome}")
    return "\n".join(lines)


def _evidence_section(store: EvidenceStore, limit: int = 40) -> str:
    lines = []
    for alias in list(store.by_alias)[:limit]:
        items = store.evidence_for(alias)
        if items:
            lines.append(evidence_line(alias, items[0]) + (f" (+{len(items) - 1} more)" if len(items) > 1 else ""))
    return "\n".join(lines) if lines else "(none)"


async def plan_tools(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    cfg = runtime.config
    stop = _budget_stop(state, cfg)
    if stop:
        return {"pending_calls": [], "stop_reason": stop}

    store = EvidenceStore.from_state(state)
    analysis = _analysis(state)
    statuses = None
    if cfg.enable_sufficiency:
        statuses = _statuses(state) or _current_sufficiency(state, runtime, store).requirements

    limit = min(cfg.max_calls_per_iteration, cfg.max_tool_calls - (state.get("tool_calls") or 0))
    prompt = PLANNER_PROMPT.format(
        max_calls=limit,
        question=state.get("question_en") or state["question"],
        question_type=state.get("question_type", "general"),
        targets=", ".join(analysis.targets + analysis.files) or "none detected",
        needs=_needs_section(state, runtime, statuses),
        evidence=_evidence_section(store),
        calls=_calls_section(state.get("tool_log") or []),
        iterations=cfg.effective_max_iterations - (state.get("iteration") or 0),
        tool_calls=cfg.max_tool_calls - (state.get("tool_calls") or 0),
        catalogue=catalogue_text(runtime.registry),
    )
    result, usage = await _ask(runtime, state, prompt, json_mode=True)
    executed = set(state.get("call_signatures") or [])
    outcome = PlanOutcome()

    try:
        if result is None:
            raise ValueError("planner LLM unavailable")
        raw_calls, outcome.done = parse_plan(result.text)
        outcome.calls, outcome.rejected, outcome.duplicates = validate_calls(raw_calls, runtime.registry, executed, limit)
    except (ValueError, TypeError) as e:
        outcome.fallback, outcome.reason = True, str(e)[:200]

    needs_fallback = outcome.fallback or (not outcome.calls and not outcome.done) or (not outcome.calls and not store.items)
    if needs_fallback:
        raw = fallback_calls(
            analysis, statuses, store.all(), state.get("tool_log") or [],
            state.get("question_en") or state["question"], cfg.max_read_lines,
        )
        calls, rejected, duplicates = validate_calls(raw, runtime.registry, executed, limit)
        outcome.calls = calls
        outcome.rejected += rejected
        outcome.duplicates += duplicates
        outcome.fallback = True
        outcome.reason = outcome.reason or "planner proposed no executable calls"

    entry = {
        "iteration": (state.get("iteration") or 0) + 1,
        "proposed": [c.tool for c in outcome.calls],
        "done": outcome.done,
        "fallback": outcome.fallback,
        "reason": outcome.reason,
        "rejected": outcome.rejected,
        "duplicates": outcome.duplicates,
    }

    if not outcome.calls:
        if outcome.done:
            stop_reason = "planner_done"
        elif outcome.duplicates:
            stop_reason = "no_progress"
        else:
            stop_reason = "no_applicable_tools"
        return {**usage, "pending_calls": [], "planner_done": outcome.done, "planner_log": [entry], "stop_reason": stop_reason}

    return {
        **usage,
        "pending_calls": [c.__dict__ for c in outcome.calls],
        "planner_done": False,
        "planner_log": [entry],
    }


def route_after_plan(state: AgentState) -> str:
    return "execute_tools" if state.get("pending_calls") else "build_context"


async def execute_tools(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    ctx = runtime.tool_ctx
    ctx.deadline = state.get("deadline")
    calls = state.get("pending_calls") or []
    iteration = (state.get("iteration") or 0) + 1
    started = time.perf_counter()

    async def run(call: dict):
        spec = runtime.registry[call["tool"]]
        t0 = time.perf_counter()
        result, args = await execute_tool(spec, ctx, call["args"])
        return call, spec, result, args, (time.perf_counter() - t0) * 1000

    outcomes = await asyncio.gather(*(run(call) for call in calls))

    store = EvidenceStore.from_state(state, capacity=runtime.config.max_evidence_items)
    before = set(store.items)
    changed: dict[str, dict] = {}
    log: list[dict] = []
    rejected: list[dict] = []
    new_count = 0
    pattern_update: dict = {}

    for call, spec, result, args, latency in outcomes:
        if result.error is None and result.metadata.get("patternAnalysis"):
            pattern_update = {
                "pattern_analysis": result.metadata["patternAnalysis"],
                "pattern_operations": (pattern_update.get("pattern_operations") or []) + [result.metadata.get("operation") or spec.name],
            }
        ids = []
        for item in result.evidence:
            try:
                evidence_id, is_new = store.add(item)
            except EvidenceScopeError as e:
                rejected.append({"tool": spec.name, "reason": str(e)})
                continue
            if evidence_id is None:
                continue
            ids.append(evidence_id)
            changed[evidence_id] = store.items[evidence_id]
            new_count += int(is_new)
        rejected += [{"tool": spec.name, **r} for r in store.rejected]
        store.rejected = []
        args_dump = args.model_dump(exclude_none=True) if args is not None else call["args"]
        log.append({
            "iteration": iteration,
            "tool": spec.name,
            "category": spec.category,
            "args": args_dump,
            "argsText": ", ".join(f"{k}={v}" for k, v in args_dump.items())[:200],
            "signature": call["signature"],
            "purpose": call.get("purpose", ""),
            "latencyMs": round(latency, 1),
            "evidenceIds": ids,
            "aliases": sorted({store.alias_for(i) for i in ids if store.alias_for(i)}),
            "newEvidence": len([i for i in ids if i not in before]),
            "summary": result.summary[:600],
            "truncated": result.truncated,
            "cached": bool(result.metadata.get("cached")),
            "error": result.error.model_dump() if result.error else None,
        })

    return {
        **pattern_update,
        "evidence": changed,
        "aliases": store.aliases_state(),
        "tool_log": log,
        "rejected_evidence": rejected,
        "tool_calls": (state.get("tool_calls") or 0) + len(calls),
        "call_signatures": (state.get("call_signatures") or []) + [c["signature"] for c in calls],
        "iteration": iteration,
        "new_evidence_count": new_count,
        "pending_calls": [],
        "retrieval_time_ms": (time.perf_counter() - started) * 1000,
    }


async def check_sufficiency(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    cfg = runtime.config
    store = EvidenceStore.from_state(state)
    budget_reason = _budget_stop(state, cfg)
    result = evaluate_sufficiency(
        analysis=_analysis(state),
        evidence=store.all(),
        tool_log=state.get("tool_log") or [],
        snapshot=store.snapshot,
        thresholds=cfg.sufficiency,
        available_tools=set(runtime.registry),
        budget_left=budget_reason is None,
        made_progress=(state.get("new_evidence_count") or 0) > 0,
    )

    usage: dict = {}
    hints = list(state.get("missing_information") or [])
    if cfg.enable_sufficiency and cfg.sufficiency.use_llm and not result.sufficient and budget_reason is None:
        evidence_lines = [evidence_line(a, store.evidence_for(a)[0]) for a in list(store.by_alias)[:30] if store.evidence_for(a)]
        requirement_lines = [f"- {r.description}: {r.status}" for r in result.requirements]
        response, usage = await _ask(runtime, state, llm_assessment_prompt(
            state.get("question_en") or state["question"], requirement_lines, evidence_lines,
        ), json_mode=True)
        if response is not None:
            result.llm_hints = parse_llm_hints(response.text)
            hints = result.llm_hints

    data = result.to_dict()
    update = {
        **usage,
        "sufficiency": data,
        "sufficiency_history": [{"iteration": state.get("iteration"), **{k: data[k] for k in (
            "coverage", "effective_coverage", "relevance", "traceability", "consistent",
            "sufficient", "should_continue", "reason", "satisfied", "missing", "unavailable",
        )}}],
        "evidence_sufficient": result.sufficient,
        "missing_information": hints,
    }

    if cfg.enable_sufficiency:
        if result.sufficient:
            update["stop_reason"] = "evidence_sufficient"
        elif not result.should_continue:
            if budget_reason:
                update["stop_reason"] = budget_reason
            elif (state.get("new_evidence_count") or 0) == 0:
                update["stop_reason"] = "no_progress"
            else:
                update["stop_reason"] = "evidence_insufficient"
        else:
            update["stop_reason"] = ""
    elif budget_reason:
        update["stop_reason"] = budget_reason
    return update


def route_after_sufficiency(state: AgentState, config: RunnableConfig) -> str:
    runtime = _runtime(config)
    if runtime.config.enable_sufficiency:
        return "plan_tools" if (state.get("sufficiency") or {}).get("should_continue") else "build_context"
    return "build_context" if _budget_stop(state, runtime.config) else "plan_tools"


def _ranked_aliases(store: EvidenceStore, statuses: list[RequirementStatus] | None) -> list[str]:
    priority: dict[str, int] = {}
    for status in statuses or []:
        for evidence_id in status.evidence_ids:
            alias = store.alias_for(evidence_id)
            if alias:
                priority[alias] = min(priority.get(alias, 9), 0)
    order = list(store.by_alias)

    def score(alias: str) -> tuple:
        items = store.evidence_for(alias)
        best = max((e.retrieval_score or 0) for e in items) if items else 0
        weak_semantic = all(e.source_type == "code_chunk" for e in items) and best < 0.35
        return priority.get(alias, 1), int(weak_semantic), order.index(alias)

    return sorted(order, key=score)


def _gaps(state: AgentState) -> list[str]:
    gaps = []
    for r in (state.get("sufficiency") or {}).get("requirements", []):
        if r["status"] != "satisfied":
            gaps.append(f"{r['description']} ({r['status']}{': ' + r['note'] if r.get('note') else ''})")
    errors = {}
    for entry in state.get("tool_log") or []:
        if entry.get("error") and entry["error"]["kind"] in ("unavailable", "forbidden", "timeout"):
            errors[entry["tool"]] = entry["error"]["message"]
    gaps += [f"{tool} failed: {message}" for tool, message in errors.items()]
    gaps += [f"open question: {h}" for h in state.get("missing_information") or []]
    return gaps


async def build_context(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    store = EvidenceStore.from_state(state)
    statuses = _statuses(state)
    if statuses is None and store.items:
        statuses = _current_sufficiency(state, runtime, store).requirements
    budget = runtime.config.max_context_chars
    blocks: list[str] = []
    used = 0
    for alias in _ranked_aliases(store, statuses):
        items = store.evidence_for(alias)
        if not items:
            continue
        block = render_block(alias, items, max(400, min(4000, budget - used)))
        if used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block) + 2
    return {"context": "\n\n".join(blocks), "open_gaps": _gaps(state)}


async def generate_answer(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    started = time.perf_counter()
    context = state.get("context") or ""
    gaps = state.get("open_gaps") or []

    if not context.strip():
        lines = [NOT_FOUND_EN]
        if gaps:
            lines += ["", "Missing evidence:"] + [f"- {g}" for g in gaps]
        return {"answer_en": "\n".join(lines), "generation_time_ms": (time.perf_counter() - started) * 1000}

    revision = ""
    verification = state.get("verification_result") or {}
    if state.get("revise") and verification:
        revision = REVISION_BLOCK.format(feedback=verification.get("feedback", ""), previous=state.get("answer_en", ""))

    intents = _analysis(state).intents
    pattern_text = ""
    if state.get("pattern_analysis"):
        store = EvidenceStore.from_state(state)
        pattern_text = render_pattern_analysis(state["pattern_analysis"], store.alias_for)
    values = dict(
        metrics_rules=METRICS_RULES if "[METRIC_" in context else "",
        revision=revision,
        question=state.get("question_en") or state["question"],
        evidence=context,
        gaps="\n".join(f"- {g}" for g in gaps) or "(none)",
    )
    if "change_planning" in intents:
        if pattern_text:
            values["revision"] = PATTERN_PLAN_BLOCK.format(pattern_analysis=pattern_text) + revision
        prompt = CHANGE_PLAN_PROMPT.format(**values)
    elif "design_pattern" in intents and pattern_text:
        prompt = PATTERN_REVIEW_PROMPT.format(pattern_analysis=pattern_text, **values)
    else:
        prompt = ANSWER_PROMPT.format(**values)
    result, usage = await _ask(runtime, state, prompt, json_mode=False, bounded=False)
    if result is None or not result.text.strip():
        answer = state.get("answer_en") if state.get("revise") and state.get("answer_en") else \
            "The answer could not be generated because the language model was unavailable."
    else:
        answer = result.text.strip()
    return {**usage, "answer_en": answer, "revise": False, "generation_time_ms": (time.perf_counter() - started) * 1000}


async def verify(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    answer = state.get("answer_en") or ""
    cited = list(dict.fromkeys(m.group(1) for m in CITATION.finditer(answer)))
    if not runtime.config.enable_verification:
        return {"verification_result": None, "cited_aliases": cited, "revise": False}

    store = EvidenceStore.from_state(state)
    result = verify_answer(answer, store)
    usage: dict = {}
    if runtime.config.llm_claim_verification and store.items:
        evidence_text = (state.get("context") or "")[:12000]
        response, usage = await _ask(runtime, state, llm_verification_prompt(answer, evidence_text), json_mode=True, bounded=False)
        if response is not None:
            result.llm_judgement = {"raw": response.text[:1000], "note": "LLM judgement is advisory, not proof"}

    data = {**result.to_dict(), "feedback": result.feedback()}
    revisions = state.get("revisions") or 0
    has_evidence = bool(store.items)
    revise = (
        not result.passed and has_evidence
        and revisions < runtime.config.max_verify_revisions
        and _remaining(state) > 0 and _tokens(state) < runtime.config.token_budget
    )
    return {
        **usage,
        "verification_result": data,
        "verification_history": [{"revision": revisions, **{k: data[k] for k in ("passed", "errorCount", "unsupportedRate", "claims_checked", "claims_supported")}}],
        "cited_aliases": result.cited_aliases,
        "revise": revise,
        "revisions": revisions + (1 if revise else 0),
    }


def route_after_verify(state: AgentState) -> str:
    return "generate_answer" if state.get("revise") else "translate_answer"


async def translate_answer(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    answer_en = (state.get("answer_en") or "").strip() or NOT_FOUND_EN
    language = (state.get("language") or "en").lower()
    if language.startswith("en"):
        return {"answer": answer_en}
    prompt = build_translation_prompt(answer_en, state.get("language_name") or "English", "[SOURCE_1], [GRAPH_1] and [METRIC_1]")
    result, usage = await _ask(runtime, state, prompt, json_mode=False, bounded=False)
    translated = result.text.strip() if result is not None and result.text.strip() else answer_en
    return {**usage, "answer": translated}


def _pattern_diagnostics(state: AgentState, config: AgentConfig, tool_log: list[dict]) -> dict:
    entries = [e for e in tool_log if e["tool"] in PATTERN_TOOLS]
    analysis = state.get("pattern_analysis") or {}
    diagnostics = analysis.get("diagnostics") or {}
    return {
        "enabled": config.enable_pattern_analysis,
        "invoked": bool(entries),
        "operations": [e["tool"] for e in entries],
        "toolCalls": len(entries),
        "failedCalls": sum(1 for e in entries if e.get("error")),
        "latencyMs": round(sum(e.get("latencyMs") or 0 for e in entries), 1),
        "patternsConsidered": diagnostics.get("patterns_considered") or [],
        "patternsDetected": diagnostics.get("patterns_detected") or [],
        "patternsRecommended": diagnostics.get("patterns_recommended") or [],
        "preferredAlternative": analysis.get("preferred_alternative"),
        "noPatternNeeded": analysis.get("no_pattern_needed"),
        "evidenceSources": diagnostics.get("evidence_sources") or {},
        "filesParsed": diagnostics.get("files_parsed", 0),
        "graphUsed": diagnostics.get("graph_used", False),
        "metricsUsed": diagnostics.get("metrics_used", False),
        "analyzerLlmCalls": diagnostics.get("llm_calls", 0),
    }


def _status(state: AgentState, config: AgentConfig) -> str:
    if not state.get("evidence"):
        return "insufficient_evidence"
    sufficiency = state.get("sufficiency") or {}
    gaps = bool(sufficiency.get("missing") or sufficiency.get("unavailable"))
    insufficient = config.enable_sufficiency and not sufficiency.get("sufficient") and gaps
    verification = state.get("verification_result")
    if insufficient:
        return "insufficient_evidence"
    if verification is None:
        return "unverified"
    return "verified" if verification.get("passed") else "partially_verified"


async def finalize(state: AgentState, config: RunnableConfig) -> dict:
    runtime = _runtime(config)
    cfg = runtime.config
    status = _status(state, cfg)
    stop_reason = state.get("stop_reason") or ("planner_done" if state.get("planner_done") else "completed")
    latency_ms = (time.perf_counter() - state["started_at"]) * 1000 if state.get("started_at") else None
    cost = (state.get("input_tokens") or 0) / 1000 * cfg.price_in_per_1k + (state.get("output_tokens") or 0) / 1000 * cfg.price_out_per_1k
    tool_log = state.get("tool_log") or []
    planner_log = state.get("planner_log") or []
    summary = summarize_tool_log(tool_log)
    sufficiency = state.get("sufficiency") or {}
    verification = state.get("verification_result") or {}

    execution = {
        "runId": state.get("run_id"),
        "strategy": state.get("mode"),
        "route": state.get("route"),
        "ablation": state.get("ablation"),
        "experimentId": state.get("experiment_id"),
        "repositorySnapshot": state.get("repository_snapshot"),
        "snapshotSource": state.get("snapshot_source"),
        "status": status,
        "toolCalls": state.get("tool_calls") or 0,
        "iterations": state.get("iteration") or 0,
        "llmCalls": state.get("llm_calls") or 0,
        "inputTokens": state.get("input_tokens") or 0,
        "outputTokens": state.get("output_tokens") or 0,
        "estimatedCost": round(cost, 6),
        "latencyMs": round(latency_ms, 1) if latency_ms is not None else None,
        "retrievalLatencyMs": round(state.get("retrieval_time_ms") or 0, 1),
        "generationLatencyMs": round(state.get("generation_time_ms") or 0, 1),
        "stopReason": stop_reason,
        "questionComplexity": state.get("complexity"),
        "toolsUsed": summary["toolsUsed"],
        "failedCalls": summary["failedCalls"],
        "duplicateCallsSkipped": sum(p.get("duplicates", 0) for p in planner_log),
        "rejectedCalls": sum(len(p.get("rejected", [])) for p in planner_log),
        "plannerFallbacks": sum(1 for p in planner_log if p.get("fallback")),
        "replans": max(0, len(planner_log) - 1),
        "evidenceCount": len(state.get("evidence") or {}),
        "seededEvidence": state.get("seeded_evidence") or 0,
        "sufficiency": {k: sufficiency.get(k) for k in (
            "sufficient", "coverage", "effective_coverage", "relevance", "traceability",
            "consistent", "satisfied", "missing", "unavailable", "reason",
        )} if sufficiency else None,
        "verification": {k: verification.get(k) for k in (
            "passed", "errorCount", "unsupportedRate", "claims_checked", "claims_supported", "unknown_aliases",
        )} if verification else None,
        "patternAnalysis": _pattern_diagnostics(state, cfg, tool_log),
        "trace": [
            {
                "iteration": e["iteration"],
                "tool": e["tool"],
                "args": e["args"],
                "latencyMs": e["latencyMs"],
                "evidence": e["aliases"],
                "newEvidence": e["newEvidence"],
                "cached": e["cached"],
                "error": e["error"],
            }
            for e in tool_log
        ],
    }

    trace = runtime.deps.trace
    if trace is not None:
        trace.write({
            "kind": "agent_run",
            **{k: v for k, v in execution.items() if k != "trace"},
            "question": state.get("question"),
            "questionEn": state.get("question_en"),
            "analysis": state.get("analysis"),
            "config": cfg.to_dict(),
            "toolLog": [{k: v for k, v in e.items() if k != "argsText"} for e in tool_log],
            "plannerLog": planner_log,
            "sufficiencyHistory": state.get("sufficiency_history") or [],
            "verificationHistory": state.get("verification_history") or [],
            "verificationIssues": (verification or {}).get("issues"),
            "unsupportedClaims": (verification or {}).get("unsupported_claims"),
            "rejectedEvidence": state.get("rejected_evidence") or [],
            "llmErrors": runtime.llm_errors,
            "citedAliases": state.get("cited_aliases") or [],
            "answer": state.get("answer"),
            "retrievedEvidence": [
                {"id": eid, "type": e.get("source_type"), "path": e.get("file_path"), "symbol": e.get("symbol_name"),
                 "start": e.get("start_line"), "end": e.get("end_line"), "producedBy": e.get("produced_by")}
                for eid, e in (state.get("evidence") or {}).items()
            ],
        })

    return {"status": status, "stop_reason": stop_reason, "execution": execution}


def build_agent_graph():
    builder = StateGraph(AgentState)
    builder.add_node("init_context", init_context)
    builder.add_node("analyze_question", analyze_question)
    builder.add_node("plan_tools", plan_tools)
    builder.add_node("execute_tools", execute_tools)
    builder.add_node("check_sufficiency", check_sufficiency)
    builder.add_node("build_context", build_context)
    builder.add_node("generate_answer", generate_answer)
    builder.add_node("verify_answer", verify)
    builder.add_node("translate_answer", translate_answer)
    builder.add_node("finalize", finalize)

    builder.set_entry_point("init_context")
    builder.add_edge("init_context", "analyze_question")
    builder.add_edge("analyze_question", "plan_tools")
    builder.add_conditional_edges("plan_tools", route_after_plan, {
        "execute_tools": "execute_tools",
        "build_context": "build_context",
    })
    builder.add_edge("execute_tools", "check_sufficiency")
    builder.add_conditional_edges("check_sufficiency", route_after_sufficiency, {
        "plan_tools": "plan_tools",
        "build_context": "build_context",
    })
    builder.add_edge("build_context", "generate_answer")
    builder.add_edge("generate_answer", "verify_answer")
    builder.add_conditional_edges("verify_answer", route_after_verify, {
        "generate_answer": "generate_answer",
        "translate_answer": "translate_answer",
    })
    builder.add_edge("translate_answer", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


agent_graph = build_agent_graph()


def make_runtime(deps: AgentDeps, config: AgentConfig, scope: Scope) -> AgentRuntime:
    registry = build_registry(config)
    tool_ctx = ToolContext(scope=scope, snapshot=f"project:{scope.project_id}", config=config, deps=deps.tools)
    return AgentRuntime(deps=deps, config=config, registry=registry, tool_ctx=tool_ctx)


def initial_state(run_id: str, mode: str, ablation: str | None, experiment_id: str | None,
                  question: str, scope: Scope, config: AgentConfig,
                  classification: dict | None = None, route: dict | None = None, usage: dict | None = None,
                  seed_hits: list[dict] | None = None) -> AgentState:
    started = time.perf_counter()
    state: AgentState = {
        "run_id": run_id,
        "mode": mode,
        "ablation": ablation,
        "experiment_id": experiment_id,
        "config": config.to_dict(),
        "question": question,
        "user_id": scope.user_id,
        "investigation_id": scope.investigation_id,
        "project_id": scope.project_id,
        "started_at": started,
        "deadline": started + config.timeout_s,
    }
    if classification:
        state["classification"] = classification
    if route:
        state["route"] = route
    if seed_hits:
        state["seed_hits"] = seed_hits
    if usage:
        state.update({k: usage[k] for k in ("llm_calls", "input_tokens", "output_tokens") if k in usage})
    return state


async def run_agent(question: str, scope: Scope, mode: str, config: AgentConfig, deps: AgentDeps,
                    run_id: str, ablation: str | None = None, experiment_id: str | None = None,
                    classification: dict | None = None, route: dict | None = None, usage: dict | None = None,
                    seed_hits: list[dict] | None = None) -> AgentState:
    runtime = make_runtime(deps, config, scope)
    state = initial_state(run_id, mode, ablation, experiment_id, question, scope, config, classification, route, usage, seed_hits)
    recursion_limit = 12 + 3 * config.effective_max_iterations + 3 * config.max_verify_revisions
    return await agent_graph.ainvoke(state, config={"configurable": {"runtime": runtime}, "recursion_limit": recursion_limit})
