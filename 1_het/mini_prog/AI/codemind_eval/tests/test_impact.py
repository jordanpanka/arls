import subprocess

import pytest

from codemind_eval.impact import impact_metrics, mine_commits, predicted_files, set_scores


def test_set_scores_hand_computed():
    scores = set_scores(["src/a.java", "src/x.java", "src/b.java"], ["src/a.java", "src/b.java", "src/c.java", "src/d.java"])
    assert scores["precision"] == pytest.approx(2 / 3)
    assert scores["recall"] == pytest.approx(2 / 4)
    assert scores["f1"] == pytest.approx(2 * (2 / 3) * 0.5 / (2 / 3 + 0.5))
    assert (scores["tp"], scores["fp"], scores["fn"]) == (2, 1, 2)


def test_empty_prediction_has_undefined_precision_and_zero_f1():
    scores = set_scores([], ["a.java"])
    assert scores["precision"] is None
    assert scores["recall"] == 0 and scores["f1"] == 0.0


def test_unavailable_prediction_is_not_scored():
    assert set_scores(None, ["a.java"])["recall"] is None


def record(snapshot_matches=True):
    return {
        "snapshotMatches": snapshot_matches,
        "repositorySnapshot": "commit:base",
        "citedAliases": ["SOURCE_1"],
        "contextEvidence": [
            {"alias": "SOURCE_1", "path": "repo/src/A.java"},
            {"alias": "SOURCE_1", "path": "repo/src/A.java"},
            {"alias": "SOURCE_2", "path": "repo/src/B.java"},
        ],
    }


def test_predicted_files_from_citations_and_context():
    assert predicted_files(record(), "cited") == ["repo/src/a.java"]
    assert predicted_files(record(), "context") == ["repo/src/a.java", "repo/src/b.java"]
    assert predicted_files({}, "cited") is None


def test_impact_metrics_require_the_pre_change_snapshot():
    good = impact_metrics(record(True), ["src/A.java", "src/C.java"])
    assert good["impact_valid"] is True
    assert good["impact_cited_precision"] == 1.0 and good["impact_cited_recall"] == 0.5
    assert good["impact_context_precision"] == 0.5
    wrong = impact_metrics(record(False), ["src/A.java"])
    assert wrong["impact_valid"] is False and wrong["impact_cited_recall"] is None
    unknown = impact_metrics(record(None), ["src/A.java"])
    assert unknown["impact_valid"] is False
    assert impact_metrics(record(None), ["src/A.java"], require_snapshot=False)["impact_valid"] is True


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_mine_commits_uses_parent_as_base_and_modified_files_as_gold(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    for name in ("A.java", "B.java", "C.java", "notes.md"):
        (repo / name).write_text("v1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "initial")
    for name in ("A.java", "B.java", "notes.md"):
        (repo / name).write_text("v2\n", encoding="utf-8")
    (repo / "New.java").write_text("new\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "Change A and B")
    (repo / "C.java").write_text("v2\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "Only C")

    impact = mine_commits(repo, "demo", max_cases=10, min_files=2, max_files=5)
    assert len(impact.cases) == 1
    case = impact.cases[0]
    parent = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD~2"], capture_output=True, text=True).stdout.strip()
    assert case.base_sha == parent
    assert case.changed_files == ["A.java", "B.java"]
    assert "Change A and B" in case.question
