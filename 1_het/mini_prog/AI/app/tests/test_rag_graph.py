import pytest
from app.services.rag_graph import (
    search_plan,
    filter_results,
    build_context,
    generate_answer,
    rerank_results,
)


@pytest.mark.asyncio
async def test_search_plan_for_text_question_disables_graph():
    state = {
        "question": "README alapján hogyan kell telepíteni?",
        "question_type": "text"
    }

    result = await search_plan(state)

    assert result["use_graph"] is False
    assert result["needs_rerank"] is False


@pytest.mark.asyncio
async def test_filter_results_keeps_only_high_score_results():
    state = {
        "results": [
            {"score": 0.9, "payload": {"text": "jó találat"}},
            {"score": 0.2, "payload": {"text": "gyenge találat"}},
        ]
    }

    result = await filter_results(state)

    assert len(result["top_results"]) == 1
    assert result["top_results"][0]["score"] == 0.9


@pytest.mark.asyncio
async def test_build_context_creates_context_from_payload():
    state = {
        "top_results": [
            {
                "score": 0.8,
                "matched_vector": "summary",
                "payload": {
                    "docName": "test.py",
                    "path": "src/test.py",
                    "kind": "function",
                    "name": "hello",
                    "summary": "Ez egy teszt függvény."
                }
            }
        ]
    }

    result = await build_context(state)

    assert "Ez egy teszt függvény." in result["context"]
    assert result["retrieved_count"] == 1


@pytest.mark.asyncio
async def test_generate_answer_returns_not_found_when_context_empty():
    state = {
        "question": "Mi ez?",
        "context": "",
        "retrieval_time_ms": 0
    }

    result = await generate_answer(state)

    assert result["answer"] == "Nem találom a dokumentumokban."


@pytest.mark.asyncio
async def test_rerank_results_prioritizes_code_entities():
    state = {
        "top_results": [
            {"score": 0.9, "payload": {"kind": "text"}},
            {"score": 0.7, "payload": {"kind": "function"}},
        ]
    }

    result = await rerank_results(state)

    assert result["top_results"][0]["payload"]["kind"] == "function"