import pytest

from app.evidence.projection import build_citations, project_evidence, raw_evidence
from app.evidence.schemas import Evidence, GraphRelation, MetricMeasurement, MetricValue, make_evidence_id, with_identity
from app.evidence.store import EvidenceScopeError, EvidenceStore, merge_evidence_maps
from app.models.models import ChatResponse, CodeEvidence, GraphEvidence, MetricEvidence


def code(path="src/a.py", start=1, end=9, content="x", tool="semantic_code_search", score=None, source_type="code_chunk"):
    return Evidence(source_type=source_type, file_path=path, start_line=start, end_line=end, content=content,
                    produced_by=[tool], retrieval_score=score)


def relation(source="a", target="b", group="g1", certainty="direct"):
    return Evidence(
        source_type="graph_relation", file_path="src/a.py", start_line=1, certainty=certainty, group=group,
        produced_by=["get_callers"],
        relation=GraphRelation(source=f"src/a.py::function::{source}@1", target=f"src/b.py::function::{target}@3",
                               type="CALLS", source_label=source, target_label=target,
                               source_path="src/a.py", target_path="src/b.py", source_line=1, target_line=3),
    )


def metric(value=14, analysis=7):
    return Evidence(
        source_type="metric", file_path="src/a.py", start_line=1, end_line=9, produced_by=["get_code_metrics"],
        metric=MetricMeasurement(scope="function", title="a()", symbol="a", analysis_id=analysis,
                                 analyzed_at="2026-10-01", items=[MetricValue(key="cyclomaticComplexity", label="CC", value=value)]),
    )


def stamped(e, snapshot="commit:1", project=3):
    return with_identity(e.model_copy(update={"repository_snapshot": snapshot, "project_id": project}))


def test_evidence_ids_are_stable_and_scoped():
    first = stamped(code())
    again = stamped(code(content="different content", tool="read_code"))
    other_snapshot = stamped(code(), snapshot="commit:2")
    other_project = stamped(code(), project=4)

    assert first.evidence_id == again.evidence_id
    assert first.evidence_id.startswith("code:")
    assert first.evidence_id != other_snapshot.evidence_id
    assert first.evidence_id != other_project.evidence_id
    assert stamped(code(path="src\\a.py")).evidence_id == first.evidence_id


def test_equivalent_evidence_is_deduplicated_and_merged():
    store = EvidenceStore(project_id=3, snapshot="commit:1")
    first_id, first_new = store.add(code(content="short", score=0.5))
    second_id, second_new = store.add(code(content="much longer content", tool="read_code", source_type="code_range", score=0.7))

    assert first_id == second_id
    assert (first_new, second_new) == (True, False)
    item = store.get(first_id)
    assert item.produced_by == ["semantic_code_search", "read_code"]
    assert item.content == "much longer content"
    assert item.retrieval_score == 0.7
    assert len(store) == 1
    assert store.alias_for(first_id) == "SOURCE_1"


def test_evidence_from_another_snapshot_or_project_is_rejected():
    store = EvidenceStore(project_id=3, snapshot="commit:1")
    with pytest.raises(EvidenceScopeError):
        store.add(code().model_copy(update={"repository_snapshot": "commit:2"}))
    with pytest.raises(EvidenceScopeError):
        store.add(code().model_copy(update={"project_id": 99}))
    assert len(store) == 0


def test_graph_evidence_from_one_call_shares_an_alias():
    store = EvidenceStore(project_id=3, snapshot="s")
    a, _ = store.add(relation("a", "b", group="call-1"))
    b, _ = store.add(relation("c", "b", group="call-1"))
    c, _ = store.add(relation("d", "e", group="call-2"))
    m, _ = store.add(metric())
    assert store.alias_for(a) == store.alias_for(b) == "GRAPH_1"
    assert store.alias_for(c) == "GRAPH_2"
    assert store.alias_for(m) == "METRIC_1"
    assert store.ids_for("GRAPH_1") == [a, b]


def test_capacity_limits_store_size():
    store = EvidenceStore(project_id=3, snapshot="s", capacity=1)
    store.add(code(path="src/a.py"))
    evidence_id, is_new = store.add(code(path="src/b.py"))
    assert evidence_id is None and not is_new
    assert store.rejected[0]["reason"] == "capacity"


def test_state_reducer_merges_by_id():
    store = EvidenceStore(project_id=3, snapshot="s")
    eid, _ = store.add(code(tool="semantic_code_search"))
    left = {eid: store.items[eid]}
    right = {eid: {**store.items[eid], "produced_by": ["read_code"]}}
    merged = merge_evidence_maps(left, right)
    assert merged[eid]["produced_by"] == ["semantic_code_search", "read_code"]


def test_projection_matches_the_existing_viewer_contract():
    store = EvidenceStore(project_id=3, snapshot="s")
    store.add(code(path="src/a.py", start=3, end=9))
    store.add(relation())
    store.add(metric())

    projected = project_evidence(store, ["SOURCE_1", "GRAPH_1", "METRIC_1"], limit=10)
    kinds = [type(p) for p in projected]
    assert kinds == [CodeEvidence, GraphEvidence, MetricEvidence]

    code_item, graph_item, metric_item = projected
    assert code_item.id == "SOURCE_1"
    assert code_item.highlights[0].startLine == 3
    assert code_item.evidenceIds == store.ids_for("SOURCE_1")
    assert {n.label for n in graph_item.nodes} == {"a", "b"}
    assert graph_item.edges[0].certainty == "direct"
    assert metric_item.items[0].value == 14
    assert metric_item.analysisId == 7

    citations = build_citations(store, ["SOURCE_1", "UNKNOWN_9"])
    assert [c.alias for c in citations] == ["SOURCE_1"]

    response = ChatResponse(answer="a", evidence=projected, citations=citations,
                            rawEvidence=raw_evidence(store, ["SOURCE_1"], 10))
    dumped = response.model_dump()
    assert dumped["evidence"][0]["type"] == "code"
    assert ChatResponse.model_validate(dumped).evidence[1].type == "graph"
    assert dumped["rawEvidence"][0]["alias"] == "SOURCE_1"


def test_projection_keeps_all_cited_items_even_above_the_limit():
    store = EvidenceStore(project_id=3, snapshot="s")
    for i in range(5):
        store.add(code(path=f"src/f{i}.py"))
    projected = project_evidence(store, ["SOURCE_5", "SOURCE_4"], limit=1)
    assert {p.id for p in projected} == {"SOURCE_4", "SOURCE_5"}


def test_make_evidence_id_differs_by_relation():
    assert make_evidence_id(relation("a", "b")) != make_evidence_id(relation("a", "c"))
