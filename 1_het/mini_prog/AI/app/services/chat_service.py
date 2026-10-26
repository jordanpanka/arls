import asyncio
import time
import uuid

import httpx

from app.models.models import ServiceResult, ChatRequest, ChatResponse
from app.services.file_service import FileService
from app.config import CHAT_DEFAULT_MODE, QDRANT_URL, QDRANT_COLLECTION, ROUTER_ESCALATION
from app.services.ollama_call import call_llm
from app.services.rag_graph import rag_graph
from app.agents.config import AGENT_MODES, AgentConfig, UnknownAblationError, config_for
from app.agents.graph import AgentDeps, default_llm, run_agent
from app.agents.router import AGENT_MODE, ROUTED_MODE, escalation_reason, route_question
from app.evaluation.trace_collector import TraceCollector
from app.evidence.projection import build_citations, project_evidence, raw_evidence
from app.evidence.store import EvidenceStore
from app.tools.base import Scope
from app.tools.defaults import default_tool_deps

#langgraph nélküli válaszgenerálás
async def send_message_async(prompt: ChatRequest) -> ServiceResult:
    async with httpx.AsyncClient(timeout=10000) as http_client:
        # text -> embedding
        #JAVITAS
        file_service=FileService()
        vec = await file_service.embed(http_client, prompt.prompt)
        
        results_sum=await search_vector("summary",vec,http_client)
        results_code=await search_vector("code",vec,http_client)
        results_text=await search_vector("text",vec,http_client)
        print(f"code: {len(results_code)}")
        print(f"sum: {len(results_sum)}")
        print(f"text: {len(results_text)}")
        #print("még jóóóó 1")

        if len(results_sum)+len(results_code)+len(results_text) == 0:
            return ServiceResult.success({
                "answer": "Nem találom a dokumentumokban."
            })

        # context összeállítása
        all_results = results_sum + results_code + results_text
        
        for r in all_results:
            print(r.get("score", 0))

        # score alapján csökkenő sorrend, bizonyos score felett rakom cak bele JAVITAS
        top_results = sorted(
            [r for r in all_results if r.get("score", 0) >= 0.35],
            #all_results,
            key=lambda r: r.get("score", 0),
            reverse=True
        )[:5]
        print("TOP EREDMÉNYEK SZÁMA:")
        print(len(top_results))
        if not top_results:
            return ServiceResult.success({
                "answer": "Nem találom a dokumentumokban."
            })
        context_parts = []
        create_context(top_results,context_parts)
        #create_context(results_code,context_parts)
        
        #create_context(results_sum,context_parts)
        #create_context(results_text,context_parts)

        context = "\n\n---\n\n".join(context_parts)
        print("CONTEXT")
        print(context)
        print("context vége")
        #print("még jóóóó 2")

        # prompt
        final_prompt = f"""Te egy asszisztens vagy, aki KIZÁRÓLAG az alábbi KONTEKSZTUS alapján válaszol.
        Mindig azon a nyelven válaszolj, amilyen nyelven a kérdés elhangzott.
        A szavak közé tegyél szóközöket, ha kell, úgy hogy értelmesen legyenek elválasztva.
        Ha a válasz nem található a kontextusban, mondd: "Nem találom a dokumentumokban."

        KONTEKSZTUS:
        {context}

        KÉRDÉS:
        {prompt}
        """

        answer = await call_llm(final_prompt) or " "

        print("A válasz:", answer)

        return ServiceResult.success({
            "answer": answer
        })
LEGACY_MODES: dict[str, dict] = {
    "adaptive_rag": {},
    "vector_rag": {"use_graph": False, "needs_rerank": False, "use_metrics": False},
    "hybrid_rag": {"use_graph": True, "needs_rerank": True, "use_metrics": True},
}
MODE_ALIASES = {"langgraph": "adaptive_rag", "rag": "adaptive_rag", "agentic": "evidence_aware_agentic_rag", "auto": ROUTED_MODE}
SUPPORTED_MODES = (*LEGACY_MODES, *AGENT_MODES, ROUTED_MODE)

trace_collector = TraceCollector()


class UnknownModeError(ValueError):
    pass


def resolve_mode(mode: str | None) -> str:
    name = (mode or CHAT_DEFAULT_MODE or "adaptive_rag").strip().lower()
    name = MODE_ALIASES.get(name, name)
    if name not in SUPPORTED_MODES:
        raise UnknownModeError(f"Unknown retrieval mode '{mode}'. Supported: {', '.join(SUPPORTED_MODES)}")
    return name


def default_agent_deps(trace=None) -> AgentDeps:
    return AgentDeps(tools=default_tool_deps(), trace=trace if trace is not None else trace_collector)


async def _run_legacy(prompt: ChatRequest, mode: str, run_id: str, trace,
                      classification: dict | None = None, route: dict | None = None, started: float | None = None,
                      overrides: dict | None = None) -> ChatResponse:
    response, _ = await _run_pipeline(prompt, mode, run_id, trace, classification, route, started, overrides)
    return response


async def _run_pipeline(prompt: ChatRequest, mode: str, run_id: str, trace,
                        classification: dict | None = None, route: dict | None = None, started: float | None = None,
                        overrides: dict | None = None) -> tuple[ChatResponse, dict]:
    started = started or time.perf_counter()
    state = {
        "question": prompt.prompt,
        "user_id": prompt.userId,
        "investigation_id": prompt.investigationId,
        "project_id": prompt.projectId
    }
    if classification:
        state.update(classification)
    strategy_overrides = {**LEGACY_MODES[mode], **(overrides or {})}
    if strategy_overrides:
        state["strategy_overrides"] = strategy_overrides
    result = await rag_graph.ainvoke(state)
    latency_ms = (time.perf_counter() - started) * 1000

    evidence = result.get("evidence") or []
    execution = {
        "runId": run_id,
        "strategy": mode,
        "experimentId": prompt.experimentId,
        "latencyMs": round(latency_ms, 1),
        "retrievalLatencyMs": round(result.get("retrieval_time_ms") or 0, 1),
        "generationLatencyMs": round(result.get("generation_time_ms") or 0, 1),
        "retrievedCount": result.get("retrieved_count"),
    }
    if route:
        execution["route"] = route
    if trace is not None:
        trace.write({
            "kind": "legacy_run",
            **execution,
            "question": prompt.prompt,
            "questionEn": result.get("question_en"),
            "usedGraph": result.get("use_graph"),
            "usedMetrics": result.get("use_metrics"),
            "answer": result.get("answer"),
            "retrievedEvidence": [
                {
                    "path": (r.get("payload") or {}).get("path"),
                    "symbol": (r.get("payload") or {}).get("name"),
                    "start": (r.get("payload") or {}).get("start_line"),
                    "end": (r.get("payload") or {}).get("end_line"),
                    "score": r.get("score"),
                }
                for r in result.get("top_results") or []
            ],
            "evidenceIds": [e.get("id") for e in evidence if isinstance(e, dict)],
        })

    return ChatResponse(
        answer=result.get("answer", "Nem találom a dokumentumokban."),
        evidence=evidence,
        execution=execution,
    ), result


async def _run_agentic(prompt: ChatRequest, mode: str, run_id: str, trace, deps: AgentDeps | None,
                       classification: dict | None = None, route: dict | None = None, usage: dict | None = None,
                       seed_hits: list[dict] | None = None) -> ChatResponse:
    config = config_for(mode, prompt.ablation)
    scope = Scope(prompt.userId, prompt.investigationId, prompt.projectId)
    deps = deps or default_agent_deps(trace)
    backstop = config.timeout_s + 3 * config.llm_timeout_s + 30
    routing = {"classification": classification, "route": route, "usage": usage} if route else {}
    if seed_hits:
        routing["seed_hits"] = seed_hits

    try:
        final = await asyncio.wait_for(
            run_agent(prompt.prompt, scope, mode, config, deps, run_id, prompt.ablation, prompt.experimentId, **routing),
            timeout=backstop,
        )
    except asyncio.TimeoutError:
        execution = {"runId": run_id, "strategy": mode, "ablation": prompt.ablation, "stopReason": "timeout", "latencyMs": backstop * 1000}
        if route:
            execution["route"] = route
        if deps.trace is not None:
            deps.trace.write({"kind": "agent_run", **execution, "question": prompt.prompt})
        return ChatResponse(
            answer="The investigation exceeded its time limit before an answer could be produced.",
            status="insufficient_evidence",
            execution=execution,
        )

    store = EvidenceStore.from_state(final)
    cited = final.get("cited_aliases") or []
    pattern_ids = [ref["id"] for ref in (final.get("pattern_analysis") or {}).get("evidence") or []]
    shown = list(dict.fromkeys(cited + [a for a in (store.alias_for(i) for i in pattern_ids) if a]))
    return ChatResponse(
        answer=final.get("answer") or final.get("answer_en") or "",
        evidence=project_evidence(store, shown, config.max_response_evidence),
        status=final.get("status"),
        citations=build_citations(store, cited),
        rawEvidence=raw_evidence(store, shown, config.max_response_evidence),
        execution=final.get("execution"),
        patternAnalysis=pattern_response(final.get("pattern_analysis"), store),
    )


def pattern_response(analysis: dict | None, store: EvidenceStore) -> dict | None:
    if not analysis:
        return None
    response = {**analysis, "evidence": [{**ref, "alias": store.alias_for(ref["id"])} for ref in analysis.get("evidence") or []]}
    response.pop("diagnostics", None)
    return response


async def run_chat(prompt: ChatRequest, trace=None, deps: AgentDeps | None = None) -> ChatResponse:
    mode = resolve_mode(prompt.mode)
    run_id = uuid.uuid4().hex
    trace = trace if trace is not None else trace_collector
    if mode == ROUTED_MODE:
        return await _run_routed(prompt, run_id, trace, deps)
    if mode in AGENT_MODES:
        return await _run_agentic(prompt, mode, run_id, trace, deps)
    return await _run_legacy(prompt, mode, run_id, trace)


async def _run_routed(prompt: ChatRequest, run_id: str, trace, deps: AgentDeps | None) -> ChatResponse:
    started = time.perf_counter()
    llm = deps.llm if deps is not None else default_llm
    decision, classification, usage = await route_question(prompt.prompt, llm, AgentConfig.from_env().llm_timeout_s)
    route = {**decision.to_dict(), "routingMs": round((time.perf_counter() - started) * 1000, 1)}
    if decision.mode in AGENT_MODES:
        return await _run_agentic(prompt, decision.mode, run_id, trace, deps, classification, route, usage)
    response, result = await _run_pipeline(prompt, decision.mode, run_id, trace, classification, route, started, decision.overrides)
    reason = escalation_reason(decision.analysis, result) if ROUTER_ESCALATION else None
    if reason is None:
        return response
    route = {
        **route,
        "escalatedTo": AGENT_MODE,
        "escalationReason": reason,
        "pipelineMs": response.execution.get("latencyMs"),
    }
    return await _run_agentic(prompt, AGENT_MODE, run_id, trace, deps, classification, route, usage,
                              seed_hits=result.get("top_results") or [])


async def send_message_async_langgraph(prompt: ChatRequest) -> ServiceResult:
    try:
        response = await run_chat(prompt)
    except (UnknownModeError, UnknownAblationError) as e:
        return ServiceResult.fail(str(e))
    return ServiceResult.success(response.model_dump())
