from app.evidence.schemas import Evidence, GraphRelation, MetricMeasurement, MetricValue
from app.evidence.store import EvidenceStore
from app.evidence.verifier import verify_answer


def build_store() -> EvidenceStore:
    store = EvidenceStore(project_id=3, snapshot="commit:1")
    store.add(Evidence(source_type="code_range", file_path="src/payment/service.py", start_line=10, end_line=40,
                       symbol_name="PaymentService.process_payment", content="...", produced_by=["read_code"]))
    store.add(Evidence(
        source_type="graph_relation", file_path="src/api/checkout.py", start_line=5, group="callers",
        produced_by=["get_callers"], certainty="direct",
        relation=GraphRelation(source="src/api/checkout.py::function::checkout@5",
                               target="src/payment/service.py::method::PaymentService.process_payment@10",
                               type="CALLS", source_label="checkout", target_label="PaymentService.process_payment",
                               source_path="src/api/checkout.py", source_line=5),
    ))
    store.add(Evidence(
        source_type="metric", file_path="src/payment/service.py", start_line=10, end_line=40, produced_by=["get_code_metrics"],
        metric=MetricMeasurement(scope="function", title="process_payment()", symbol="process_payment", analysis_id=7,
                                 items=[MetricValue(key="cyclomaticComplexity", label="CC", value=14),
                                        MetricValue(key="nloc", label="NLOC", value=28.37, unit="lines")]),
    ))
    return store


def test_supported_answer_passes():
    answer = (
        "`process_payment` in src/payment/service.py:10-40 validates and charges the order [SOURCE_1].\n"
        "`checkout` calls `process_payment` [GRAPH_1].\n"
        "Its cyclomatic complexity is 14 and it has 28.4 NLOC (Lizard) [METRIC_1].\n"
        "Missing evidence:\n- the tests of `process_payment` were not inspected."
    )
    result = verify_answer(answer, build_store())
    assert result.passed, result.feedback()
    assert result.cited_aliases == ["SOURCE_1", "GRAPH_1", "METRIC_1"]
    assert result.unsupported_rate == 0.0


def test_unknown_citation_is_flagged():
    result = verify_answer("`process_payment` retries three times [SOURCE_7].", build_store())
    assert result.unknown_aliases == ["SOURCE_7"]
    assert not result.passed


def test_wrong_line_range_is_flagged():
    result = verify_answer("The check is in src/payment/service.py:90-95 [SOURCE_1].", build_store())
    assert [i.kind for i in result.errors] == ["line_range"]


def test_unknown_path_is_flagged():
    result = verify_answer("Payments are also handled in src/billing/legacy.py [SOURCE_1].", build_store())
    assert "unknown_path" in [i.kind for i in result.errors]


def test_fabricated_relation_is_flagged():
    result = verify_answer("`refund` calls `process_payment` [GRAPH_1].", build_store())
    assert [i.kind for i in result.errors] == ["unsupported_relation"]


def test_wrong_metric_value_is_flagged():
    result = verify_answer("`process_payment` has a cyclomatic complexity of 21 [METRIC_1].", build_store())
    assert [i.kind for i in result.errors] == ["metric_mismatch"]


def test_uncited_repository_claims_are_reported():
    result = verify_answer("`process_payment` also writes an audit log.\nGeneral advice without code.", build_store())
    assert result.unsupported_claims == ["`process_payment` also writes an audit log."]
    assert not result.passed
    assert result.unsupported_rate == 1.0


def test_hypotheses_are_not_counted_as_unsupported():
    answer = "Hypothesis: `process_payment` might be retried by a scheduler.\nMissing evidence:\n- `scheduler` was not found."
    result = verify_answer(answer, build_store())
    assert result.passed
