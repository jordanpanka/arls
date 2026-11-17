import json
from dataclasses import replace

from app.agents.config import AgentConfig, config_for
from app.agents.graph import run_agent
from app.agents.planner import seed_anchors, seed_calls, seed_directions
from app.agents.requirements import analyze_question
from app.evidence.schemas import Evidence
from app.tools.code_graph import CodeGraph

from app.tests.agent_fakes import SCOPE, ScriptedLLM, agent_deps, graph_data

GRAPH_TOOLS = {"get_callers", "get_callees", "get_related_symbols", "find_type_usages", "trace_dependencies", "find_call_path"}


def config(**overrides) -> AgentConfig:
    return replace(config_for("evidence_aware_agentic_rag", base=AgentConfig()), **overrides)


async def agent(question, llm, cfg=None):
    deps, trace = agent_deps(llm)
    state = await run_agent(question, SCOPE, "evidence_aware_agentic_rag", cfg or config(), deps, run_id="seed-1")
    return state, trace.records[0]


def tools_by_iteration(state) -> dict[int, list[str]]:
    rounds: dict[int, list[str]] = {}
    for entry in state["tool_log"]:
        rounds.setdefault(entry["iteration"], []).append(entry["tool"])
    return rounds


async def test_seed_retrieval_uses_vectors_and_graph_before_the_planner():
    llm = ScriptedLLM(answers=["`process_payment` calls `charge_card` [GRAPH_1]."])
    state, record = await agent("Which functions does process_payment call?", llm)

    rounds = tools_by_iteration(state)
    assert set(rounds[1]) == {"semantic_code_search", "find_symbol"}
    assert {"get_callees", "get_callers"} <= set(rounds[2])
    assert llm.count("retrieval planner") == 1
    assert state["stop_reason"] == "evidence_sufficient"
    assert record["seedPhases"] == 2
    assert record["seedToolCalls"] == record["toolCalls"]
    assert [bool(p.get("seed")) for p in record["plannerLog"]] == [True, True, False]
    callees = [e for e in state["tool_log"] if e["tool"] == "get_callees"]
    assert len(callees) == 1


async def test_the_planner_reviews_seeded_evidence_once_and_can_extend_it():
    llm = ScriptedLLM(plans=[
        {"calls": [{"tool": "read_code", "args": {"path": "src/payment/gateway.py", "start_line": 1, "end_line": 12}}]},
    ])
    state, record = await agent("Which functions does process_payment call?", llm)

    assert llm.count("retrieval planner") >= 1
    assert "none found by the automatic check" in next(p for p in llm.prompts if "retrieval planner" in p)
    reads = [e for e in state["tool_log"] if e["tool"] == "read_code"]
    assert reads and reads[0]["args"]["path"] == "src/payment/gateway.py"
    assert record["toolCalls"] == record["seedToolCalls"] + 1


def test_role_phrases_name_single_word_classes():
    analysis = analyze_question("Trace the execution path from JUnitCore.run(Request) to the runner and the final Result object.")
    assert analysis.targets == ["JUnitCore.run", "Result"]
    assert ("call_path", "JUnitCore.run->Result") in [(r.kind, r.target) for r in analysis.requirements]
    assert analyze_question("Which classes use the Statement interface?").targets == ["Statement"]
    assert analyze_question("What does the runner do?").targets == []


async def test_seed_calls_do_not_consume_the_planner_budget():
    llm = ScriptedLLM(plans=[{"calls": [{"tool": "keyword_code_search", "args": {"pattern": "ghostFunction"}}]}])
    state, record = await agent("What does ghostFunction do?", llm, config(max_iterations=1, max_tool_calls=1))

    assert llm.count("retrieval planner") == 1
    assert "keyword_code_search" in [e["tool"] for e in state["tool_log"]]
    assert record["toolCalls"] == record["seedToolCalls"] + 1
    assert state["stop_reason"] in ("max_iterations", "max_tool_calls")


async def test_text_questions_follow_the_adaptive_plan_and_skip_the_graph():
    classification = json.dumps({"language": "en", "language_name": "English", "question_en": None,
                                 "question_type": "text", "search_vectors": ["text", "summary"]})
    llm = ScriptedLLM(classification=classification)
    state, _ = await agent("How do I install the payment module?", llm)

    search = next(e for e in state["tool_log"] if e["tool"] == "semantic_code_search")
    assert search["args"]["vectors"] == ["text", "summary"]
    seeded = [e["tool"] for e in state["tool_log"] if e["iteration"] <= 2]
    assert not GRAPH_TOOLS & set(seeded)


async def test_no_seed_ablation_leaves_the_first_round_to_the_planner():
    cfg = config_for("evidence_aware_agentic_rag", "no_seed", base=AgentConfig())
    assert not cfg.enable_seed_retrieval
    assert not config_for("agentic_rag", base=AgentConfig()).enable_seed_retrieval
    llm = ScriptedLLM(plans=[{"calls": [{"tool": "find_symbol", "args": {"name": "process_payment"}}]}])
    state, record = await agent("What does process_payment do?", llm, cfg)

    assert tools_by_iteration(state)[1] == ["find_symbol"]
    assert llm.count("retrieval planner") >= 1
    assert record["seedToolCalls"] == 0


def code_hit(path, name, kind="function", score=0.8):
    return Evidence(source_type="code_chunk", file_path=path, symbol_name=name, symbol_kind=kind,
                    start_line=1, end_line=10, content="...", retrieval_score=score, produced_by=["semantic_code_search"])


def resolved(path, name, kind):
    return Evidence(source_type="symbol", file_path=path, symbol_name=name, symbol_kind=kind, start_line=5, end_line=50,
                    symbol_id=f"{path}::{kind}::{name}@5", produced_by=["find_symbol"])


def test_named_targets_are_the_only_anchors_once_resolved():
    analysis = analyze_question("Which functions does process_payment call?")
    evidence = [code_hit("src/other.py", "unrelated", score=0.9), resolved("src/payment/service.py", "process_payment", "method")]
    assert [name for name, _ in seed_anchors(analysis, evidence)] == ["src/payment/service.py::method::process_payment@5"]


def test_test_code_hits_are_skipped_unless_the_question_is_about_tests():
    analysis = analyze_question("How is the payment total validated?")
    evidence = [code_hit("src/test/java/PaymentTest.java", "testTotal", score=0.95), code_hit("src/main/Payment.java", "validate")]
    assert [name for name, _ in seed_anchors(analysis, evidence)] == ["src/main/Payment.java::validate"]
    with_tests = seed_anchors(analysis, evidence, include_tests=True)
    assert with_tests[0][0] == "src/test/java/PaymentTest.java::testTotal"


def test_graph_direction_follows_the_question():
    assert seed_directions(analyze_question("In which order are the wrappers of Runner.run applied?")) == (True, False)
    assert seed_directions(analyze_question("What would be affected if processPayment were modified?")) == (False, True)
    assert seed_directions(analyze_question("Which modules depend on PaymentService?")) == (True, True)


def test_class_anchors_get_call_relations_only_for_relationship_questions():
    flow = analyze_question("In which order does PaymentService wrap its statements?")
    evidence = [resolved("src/payment/service.py", "PaymentService", "class")]
    tools = [c["tool"] for c in seed_calls(2, flow, "code", None, evidence, "In which order does PaymentService wrap its statements?")]
    assert tools == ["get_related_symbols", "get_callees"]
    plain = analyze_question("What is PaymentService?")
    tools = [c["tool"] for c in seed_calls(2, plain, "code", None, evidence, "What is PaymentService?")]
    assert tools == ["get_related_symbols"]


async def test_class_callees_start_with_the_most_connected_members():
    from app.tools.graph_tools import _callable_roots
    from app.tools.code_graph import CodeGraphData

    def fn(fid, name, line):
        return {"id": fid, "name": name, "path": "src/R.java", "startLine": line, "endLine": line + 3}

    def call(caller, callee, name):
        return {"callerId": caller, "calleeId": callee, "calleeName": name, "calleePath": "src/R.java"}

    graph = CodeGraph(CodeGraphData(
        classes=[{"id": "c", "name": "Runner", "path": "src/R.java", "startLine": 1, "endLine": 100}],
        functions=[fn("m1", "init", 10), fn("m2", "block", 20), fn("m3", "before", 30), fn("m4", "after", 40)],
        calls=[call("m2", "m3", "before"), call("m2", "m4", "after"), call("m1", "m3", "before")],
    ))
    roots, _ = _callable_roots(graph, "Runner", outgoing=True)
    assert [r.name for r in roots][:2] == ["block", "init"]


def test_a_class_name_shared_by_its_constructors_explores_the_class():
    from app.tools.graph_tools import _callable_roots
    from app.tools.code_graph import CodeGraphData

    def fn(fid, name, line):
        return {"id": fid, "name": name, "path": "src/R.java", "startLine": line, "endLine": line + 3}

    graph = CodeGraph(CodeGraphData(
        classes=[{"id": "c", "name": "Runner", "path": "src/R.java", "startLine": 1, "endLine": 100}],
        functions=[fn("k1", "Runner", 5), fn("k2", "Runner", 8), fn("m1", "block", 20), fn("m2", "before", 30)],
        calls=[{"callerId": "m1", "calleeId": "m2", "calleeName": "before", "calleePath": "src/R.java"}],
    ))
    roots, explore = _callable_roots(graph, "Runner", outgoing=True)
    assert roots[0].name == "block" and explore > 3
    assert {r.name for r in roots} == {"Runner", "block", "before"}


def test_graph_lookup_accepts_a_file_qualified_name():
    graph = CodeGraph(graph_data())
    found = graph.find("src/utils/validation.py::validate_input")
    assert [n.path for n in found] == ["src/utils/validation.py"]
    prefixed = graph.find("repo-abc123/src/payment/service.py::validate_input")
    assert [n.path for n in prefixed] == ["src/payment/service.py"]
    assert len(graph.find("validate_input")) == 2
