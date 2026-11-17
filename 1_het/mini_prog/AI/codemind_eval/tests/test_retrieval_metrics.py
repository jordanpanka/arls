import pytest

from codemind_eval.evidence_ids import file_id, file_units, norm_symbol, path_matches, symbol_id, symbol_units
from codemind_eval.retrieval_metrics import ranked_scores, retrieval_metrics, level_scores
from codemind_eval.schema import GoldEvidence, Question


def question(files=(), symbols=()):
    gold = [GoldEvidence(kind="file", path=p) for p in files]
    gold += [GoldEvidence(kind="symbol", path=p, symbol=s) for p, s in symbols]
    return Question(id="q1", question="?", gold_evidence=gold)


def item(path, symbol=None):
    return {"path": path, "symbol": symbol}


def test_canonical_ids_normalise_paths_and_symbols():
    assert file_id("\\Src\\Main\\Foo.java") == "file:src/main/foo.java"
    assert symbol_id("src/Foo.java", "Foo.bar(int, String)") == "symbol:src/foo.java::bar"
    assert symbol_id(None, "Foo::bar") == "symbol:*::bar"
    assert norm_symbol("List<String>.size()") == "size"


def test_path_matching_tolerates_repository_prefixes_but_not_partial_names():
    assert path_matches("src/main/Foo.java", "junit4-r4.13.2/src/main/Foo.java")
    assert path_matches("src/main/Foo.java", "src/main/foo.java")
    assert not path_matches("src/main/Foo.java", "src/main/BarFoo.java")
    assert not path_matches("src/main/Foo.java", None)


def test_chunks_of_the_same_file_collapse_into_one_ranked_unit():
    items = [item("a.java", "x"), item("a.java", "y"), item("b.java", "z"), item(None, "w"), item("a.java", "x")]
    assert file_units(items) == ["a.java", "b.java"]
    assert symbol_units(items) == [("a.java", "x"), ("a.java", "y"), ("b.java", "z"), ("", "w")]


def test_hand_computed_file_level_scores():
    items = [item("x.java"), item("a.java"), item("y.java"), item("b.java"), item("z.java"), item("c.java")]
    scores = level_scores(items, question(files=["a.java", "b.java", "c.java", "d.java"]), "file")
    assert scores["recall@5"] == pytest.approx(2 / 4)
    assert scores["precision@5"] == pytest.approx(2 / 5)
    assert scores["recall@10"] == pytest.approx(3 / 4)
    assert scores["precision@10"] == pytest.approx(3 / 10)
    assert scores["mrr"] == pytest.approx(1 / 2)
    assert scores["coverage"] == pytest.approx(3 / 4)
    assert scores["retrieved"] == 6


def test_precision_at_k_divides_by_k_when_fewer_items_are_retrieved():
    scores = level_scores([item("a.java")], question(files=["a.java"]), "file")
    assert scores["precision@5"] == pytest.approx(1 / 5)
    assert scores["recall@5"] == 1.0
    assert scores["mrr"] == 1.0


def test_symbol_level_requires_matching_path_when_gold_has_one():
    gold = question(symbols=[("src/A.java", "run"), (None, "evaluate")])
    items = [item("src/B.java", "run"), item("src/C.java", "Statement.evaluate"), item("src/A.java", "A.run")]
    scores = level_scores(items, gold, "symbol")
    assert scores["mrr"] == pytest.approx(1 / 2)
    assert scores["recall@5"] == 1.0
    assert scores["precision@5"] == pytest.approx(2 / 5)


def test_files_of_symbol_gold_count_for_file_coverage():
    gold = question(symbols=[("src/A.java", "run")])
    assert level_scores([item("src/A.java")], gold, "file")["coverage"] == 1.0


def test_no_gold_gives_no_score_instead_of_zero():
    assert ranked_scores(["a"], [], lambda g, u: True) == {}
    row = retrieval_metrics({"contextEvidence": [item("a.java")], "retrievedEvidence": []}, question())
    assert row["ctx_file_recall@5"] is None
    assert row["ctx_file_mrr"] is None


def test_missing_trace_data_is_unavailable_not_zero():
    row = retrieval_metrics({"retrievedEvidence": [item("a.java")]}, question(files=["a.java"]))
    assert row["ctx_file_recall@5"] is None
    assert row["ret_file_recall@5"] == 1.0
