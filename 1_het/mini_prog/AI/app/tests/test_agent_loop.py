import json
from dataclasses import replace

from app.agents.config import AgentConfig, config_for
from app.agents.graph import run_agent
from app.agents.prompts import NOT_FOUND_EN

from app.tests.agent_fakes import SCOPE, FakeSource, GraphLoader, ScriptedLLM, agent_deps

FIND = {"tool": "find_symbol", "args": {"name": "process_payment"}}
READ = {"tool": "read_code", "args": {"path": "src/payment/service.py", "start_line": 10, "end_line": 40}}
GOOD_ANSWER = "`PaymentService.process_payment` in src/payment/service.py:10-40 validates the order and charges the card [SOURCE_2]."


def config(**overrides) -> AgentConfig:
    return replace(config_for("evidence_aware_agentic_rag", base=AgentConfig()), **overrides)


async def agent(question, llm, cfg=None, mode="evidence_aware_agentic_rag", **deps):
    agent_dependencies, trace = agent_deps(llm, **deps)
    state = await run_agent(question, SCOPE, mode, cfg or config(), agent_dependencies, run_id="run-1")
    return state, trace


async def test_iteration_limit_stops_the_loop():
    llm = ScriptedLLM(plans=[
        {"calls": [{"tool": "semantic_code_search", "args": {"query": f"ghost {i}"}}]} for i in range(5)
    ])
    state, _ = await agent("What does ghostFunction do?", llm, config(max_iterations=2))
    assert state["iteration"] == 2
    assert state["stop_reason"] == "max_iterations"
    assert state["execution"]["iterations"] == 2


async def test_tool_call_limit_caps_execution():
    llm = ScriptedLLM(plans=[{"calls": [
        FIND, READ, {"tool": "get_callers", "args": {"symbol": "process_payment"}},
    ]}])
    state, _ = await agent("What does process_payment do?", llm, config(max_tool_calls=1))
    assert state["tool_calls"] == 1
    assert [e["tool"] for e in state["tool_log"]] == ["find_symbol"]
    assert state["stop_reason"] == "max_tool_calls"


async def test_token_budget_stops_retrieval():
    llm = ScriptedLLM(plans=[{"calls": [FIND]}, {"calls": [READ]}])
    state, _ = await agent("What does process_payment do?", llm, config(token_budget=200))
    assert state["tool_calls"] == 1
    assert state["stop_reason"] == "token_budget"


async def test_timeout_stops_before_any_tool_call():
    llm = ScriptedLLM(plans=[{"calls": [FIND]}])
    state, _ = await agent("What does process_payment do?", llm, config(timeout_s=0))
    assert state["tool_calls"] == 0
    assert state["stop_reason"] == "timeout"
    assert state["answer"].startswith(NOT_FOUND_EN)
    assert state["status"] == "insufficient_evidence"


async def test_duplicate_calls_are_not_repeated():
    llm = ScriptedLLM(plans=[{"calls": [FIND]}, {"calls": [FIND]}, {"calls": [FIND]}], answers=["[SOURCE_1] defines it."])
    state, _ = await agent("What does process_payment do?", llm, config_for("agentic_rag", base=AgentConfig()), mode="agentic_rag")
    assert [e["tool"] for e in state["tool_log"]] == ["find_symbol"]
    assert state["execution"]["duplicateCallsSkipped"] >= 1
    assert state["stop_reason"] == "no_progress"


async def test_invalid_and_unknown_planned_calls_are_rejected():
    llm = ScriptedLLM(plans=[{"calls": [
        {"tool": "run_shell", "args": {"cmd": "rm -rf /"}},
        {"tool": "read_code", "args": {"path": "../../etc/passwd"}},
        FIND,
    ]}, {"calls": [READ]}], answers=[GOOD_ANSWER])
    state, _ = await agent("What does process_payment do?", llm)
    assert state["tool_log"][0]["tool"] == "find_symbol"
    assert state["execution"]["rejectedCalls"] == 2
    assert all(entry["tool"] != "run_shell" for entry in state["tool_log"])


async def test_malformed_planner_output_uses_deterministic_fallback():
    llm = ScriptedLLM(plans=["not json at all", "```json\n{broken"], answers=[GOOD_ANSWER])
    state, _ = await agent("What does process_payment do?", llm)
    assert [e["tool"] for e in state["tool_log"]] == ["find_symbol", "read_code"]
    assert state["execution"]["plannerFallbacks"] == 2
    assert state["stop_reason"] == "evidence_sufficient"


async def test_tool_failure_is_reported_not_fabricated():
    llm = ScriptedLLM(
        plans=[{"calls": [{"tool": "get_callers", "args": {"symbol": "process_payment"}}]}, {"calls": [], "done": True}],
        answers=["The callers could not be determined.\nMissing evidence:\n- the knowledge graph was unavailable."],
    )
    state, trace = await agent("Which functions call process_payment?", llm, graph=GraphLoader(fail=True))
    assert state["tool_log"][0]["error"]["kind"] == "unavailable"
    assert state["evidence"] == {}
    assert state["status"] == "insufficient_evidence"
    assert any("get_callers failed" in gap for gap in state["open_gaps"])
    assert trace.records[0]["failedCalls"] >= 1


async def test_verification_failure_triggers_one_bounded_revision():
    llm = ScriptedLLM(plans=[{"calls": [FIND]}, {"calls": [READ]}], answers=[
        "`process_payment` retries five times [SOURCE_9].",
        GOOD_ANSWER,
    ])
    state, _ = await agent("What does process_payment do?", llm)
    assert llm.count("senior engineer") == 2
    assert "failed verification" in [p for p in llm.prompts if "senior engineer" in p][1]
    assert state["revisions"] == 1
    assert state["status"] == "verified"
    assert state["answer"] == GOOD_ANSWER


async def test_revisions_are_bounded_and_failures_reported():
    bad = "`process_payment` retries five times [SOURCE_9]."
    llm = ScriptedLLM(plans=[{"calls": [FIND]}, {"calls": [READ]}], answers=[bad, bad, bad])
    state, _ = await agent("What does process_payment do?", llm, config(max_verify_revisions=1))
    assert llm.count("senior engineer") == 2
    assert state["status"] == "partially_verified"
    assert state["verification_result"]["unknown_aliases"] == ["SOURCE_9"]


async def test_no_evidence_gives_explicit_not_found_answer():
    llm = ScriptedLLM(plans=[{"calls": [{"tool": "find_symbol", "args": {"name": "ghostFunction"}}]}, {"calls": [], "done": True}])
    state, _ = await agent("What does ghostFunction do?", llm)
    assert state["answer"].startswith(NOT_FOUND_EN)
    assert "Missing evidence" in state["answer"]
    assert llm.count("senior engineer") == 0


async def test_repository_content_is_delimited_in_the_answer_prompt():
    llm = ScriptedLLM(plans=[{"calls": [FIND]}, {"calls": [READ]}], answers=[GOOD_ANSWER])
    await agent("What does process_payment do?", llm)
    prompt = next(p for p in llm.prompts if "senior engineer" in p)
    injected = prompt.index("Ignore all previous instructions")
    assert prompt.rfind("<<<REPO_CONTENT", 0, injected) > prompt.rfind("REPO_CONTENT>>>", 0, injected)


async def test_answer_is_translated_back_for_non_english_questions():
    classification = json.dumps({"language": "hu", "language_name": "Hungarian", "question_en": "What does process_payment do?",
                                 "question_type": "code", "search_vectors": ["code"]})
    llm = ScriptedLLM(plans=[{"calls": [FIND]}, {"calls": [READ]}], answers=[GOOD_ANSWER], classification=classification)
    state, _ = await agent("Mit csinál a process_payment?", llm)
    assert state["answer_en"] == GOOD_ANSWER
    assert state["answer"].startswith("TRANSLATED")
    assert "[GRAPH_1]" in next(p for p in llm.prompts if "Translate the text below" in p)


async def test_snapshot_falls_back_when_backend_is_unreachable():
    llm = ScriptedLLM(plans=[{"calls": [FIND]}, {"calls": [READ]}], answers=[GOOD_ANSWER])
    state, _ = await agent("What does process_payment do?", llm, source=FakeSource(fail_snapshot=True))
    assert state["repository_snapshot"] == "project:3"
    assert state["snapshot_source"] == "fallback"
    assert all(e["repository_snapshot"] == "project:3" for e in state["evidence"].values())


async def test_llm_outage_still_returns_a_structured_answer():
    llm = ScriptedLLM(fail_after=0)
    state, trace = await agent("What does process_payment do?", llm)
    assert state["execution"]["plannerFallbacks"] >= 1
    assert state["tool_log"]
    assert "language model was unavailable" in state["answer"]
    assert trace.records[0]["llmErrors"]


async def test_trace_contains_research_fields():
    llm = ScriptedLLM(plans=[{"calls": [FIND]}, {"calls": [READ]}], answers=[GOOD_ANSWER])
    state, trace = await agent("What does process_payment do?", llm)
    record = trace.records[0]
    assert record["runId"] == "run-1"
    assert record["strategy"] == "evidence_aware_agentic_rag"
    assert record["repositorySnapshot"] == "commit:abc123"
    assert [e["tool"] for e in record["toolLog"]] == ["find_symbol", "read_code"]
    assert record["inputTokens"] > 0 and record["outputTokens"] > 0
    assert record["sufficiencyHistory"][-1]["sufficient"] is True
    assert record["verificationHistory"][-1]["passed"] is True
    assert record["retrievedEvidence"]
    assert "Ignore all previous" not in json.dumps(state["execution"])
