import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from codemind_eval.judge import JudgeParseError, blind_text, build_prompt, parse_judgement
from codemind_eval.schema import ImpactCase, ImpactSet, Repository, impact_benchmark, load_benchmark, parse_benchmark

AI_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("folder,repository", [("junit4", "junit4"), ("ant", "apache-ant"), ("bottle", "bottle")])
def test_shipped_benchmarks_load(folder, repository):
    benchmark = load_benchmark(AI_ROOT / "eval" / "benchmarks" / folder / "benchmark.json")
    assert benchmark.repository.id == repository
    assert len(benchmark.repository.commit_sha or "") == 40
    assert len(benchmark.questions) == 40
    assert all(q.annotation_status == "draft" and q.gold_evidence for q in benchmark.questions)
    unanswered = [q for q in benchmark.questions if q.reference_answer is None]
    assert unanswered and all(q.category == "code_quality" for q in unanswered)


def test_legacy_questions_load():
    legacy = load_benchmark(AI_ROOT / "eval" / "questions.json")
    assert legacy.questions and all(q.annotation_status == "legacy" for q in legacy.questions)


def test_legacy_format_is_converted_to_gold_evidence():
    benchmark = parse_benchmark({"questions": [{
        "id": "q1", "question": "?", "ground_truth": "  ", "category": "impact",
        "expected_files": ["a/B.java"], "expected_symbols": ["B.run"], "expected_route": "selective_rag",
    }]})
    q = benchmark.questions[0]
    assert q.reference_answer is None
    assert [g.id for g in q.gold_evidence] == ["file:a/b.java", "symbol:*::run"]
    assert q.expected_strategy == "selective_rag"


def test_benchmark_rejects_duplicate_ids_and_incomplete_gold():
    repo = {"id": "r"}
    with pytest.raises(ValidationError):
        parse_benchmark({"repository": repo, "name": "b", "questions": [{"id": "a", "question": "?"}, {"id": "a", "question": "?"}]})
    with pytest.raises(ValidationError):
        parse_benchmark({"repository": repo, "name": "b", "questions": [
            {"id": "a", "question": "?", "gold_evidence": [{"kind": "symbol", "path": "x.java"}]}]})


def test_impact_cases_become_questions_with_expected_commit():
    impact = ImpactSet(repository=Repository(id="r"), cases=[ImpactCase(
        id="impact-1", base_sha="aaa", target_sha="bbb", message="Fix x", question="Which files?",
        changed_files=["src/A.java", "src/B.java"])])
    q = impact_benchmark(impact).questions[0]
    assert q.category == "change_impact"
    assert q.expected_commit_sha == "aaa"
    assert q.impact_files == ["src/A.java", "src/B.java"]


def valid(**overrides):
    data = {"factual_correctness": 2, "completeness": 0.5, "faithfulness": 1, "citation_correctness": 0.75, "rationale": "ok"}
    return json.dumps({**data, **overrides})


def test_judge_output_is_validated():
    scores = parse_judgement("```json\n" + valid() + "\n```", has_reference=True)
    assert scores.factual_correctness == 2 and scores.citation_correctness == 0.75
    assert parse_judgement(valid(factual_correctness=3.0), True).factual_correctness == 3


@pytest.mark.parametrize("text", [
    "not json at all",
    "[1, 2]",
    valid(factual_correctness=4),
    valid(faithfulness=1.2),
    valid(completeness=-0.1),
    valid(factual_correctness=None),
    json.dumps({"factual_correctness": 2, "completeness": 1}),
])
def test_invalid_judge_output_is_rejected(text):
    with pytest.raises(JudgeParseError):
        parse_judgement(text, has_reference=True)


def test_reference_dependent_scores_are_dropped_without_reference():
    scores = parse_judgement(valid(), has_reference=False)
    assert scores.factual_correctness is None and scores.completeness is None
    assert scores.faithfulness == 1


def test_judge_prompt_does_not_reveal_the_strategy():
    context = ("[SOURCE_1] CODE src/A.java lines 1-5 symbol run via semantic_code_search\n<<<REPO_CONTENT\nx\nREPO_CONTENT>>>\n"
               "[SOURCE_2]\nFile: a.py\nMatched vector: code\n\nCode:\npass\n"
               "[GRAPH_1] GRAPH (from get_callers, trace_dependencies)\n- value 3 [measured by lizard]")
    prompt = build_prompt("Q?", None, "Used evidence_aware_agentic_rag and hybrid_rag [SOURCE_1].", context)
    for term in ("semantic_code_search", "Matched vector", "get_callers", "evidence_aware_agentic_rag", "hybrid_rag",
                 "REPO_CONTENT", "measured by"):
        assert term not in prompt
    assert "[SOURCE_1]" in prompt and "[GRAPH_1]" in prompt
    assert blind_text(None) == ""
