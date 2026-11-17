import subprocess
from pathlib import Path

from codemind_eval.evidence_ids import norm_path, path_matches
from codemind_eval.schema import ImpactCase, ImpactSet, Repository

DEFAULT_EXTENSIONS = (".java",)
QUESTION_TEMPLATE = (
    "We want to make the following change to this repository: \"{message}\". "
    "Which existing files would have to be modified to implement it? List the affected files and explain why."
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def changed_files(repo: Path, base: str, target: str, extensions=DEFAULT_EXTENSIONS, diff_filter: str = "M") -> list[str]:
    out = _git(repo, "diff", "--name-only", f"--diff-filter={diff_filter}", base, target)
    files = [line.strip() for line in out.splitlines() if line.strip()]
    return [f for f in files if not extensions or f.lower().endswith(tuple(extensions))]


def mine_commits(repo: Path, repository_id: str, url: str | None = None, rev_range: str = "HEAD", max_cases: int = 20,
                 min_files: int = 2, max_files: int = 10, extensions=DEFAULT_EXTENSIONS, diff_filter: str = "M",
                 exclude_tests: bool = False) -> ImpactSet:
    log = _git(repo, "log", "--no-merges", "--format=%H%x1f%P%x1f%s", rev_range)
    cases: list[ImpactCase] = []
    for line in log.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        sha, parents, subject = parts
        parent_list = parents.split()
        if len(parent_list) != 1 or not subject.strip():
            continue
        files = changed_files(repo, parent_list[0], sha, extensions, diff_filter)
        if exclude_tests:
            files = [f for f in files if "/test/" not in norm_path(f) and not norm_path(f).startswith("test/")]
        if not (min_files <= len(files) <= max_files):
            continue
        cases.append(ImpactCase(
            id=f"impact-{sha[:10]}",
            base_sha=parent_list[0],
            target_sha=sha,
            message=subject.strip(),
            question=QUESTION_TEMPLATE.format(message=subject.strip()),
            changed_files=files,
        ))
        if len(cases) >= max_cases:
            break
    return ImpactSet(repository=Repository(id=repository_id, url=url), cases=cases)


def predicted_files(record: dict, source: str) -> list[str] | None:
    items = record.get("contextEvidence")
    if items is None:
        return None
    if source == "cited":
        cited = set(record.get("citedAliases") or [])
        items = [i for i in items if i.get("alias") in cited]
    files: list[str] = []
    for item in items:
        path = norm_path(item.get("path"))
        if path and path not in files:
            files.append(path)
    return files


def set_scores(predicted: list[str] | None, gold: list[str]) -> dict:
    if predicted is None or not gold:
        return {"precision": None, "recall": None, "f1": None, "tp": None, "fp": None, "fn": None, "predicted": None}
    tp_pred = [p for p in predicted if any(path_matches(g, p) for g in gold)]
    found = [g for g in gold if any(path_matches(g, p) for p in predicted)]
    precision = len(tp_pred) / len(predicted) if predicted else None
    recall = len(found) / len(gold)
    if precision is None:
        f1 = 0.0 if recall == 0 else None
    else:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": len(found),
        "fp": len(predicted) - len(tp_pred),
        "fn": len(gold) - len(found),
        "predicted": len(predicted),
    }


def impact_metrics(record: dict, gold_files: list[str], require_snapshot: bool = True) -> dict:
    if not gold_files:
        return {}
    matches = record.get("snapshotMatches")
    valid = matches is True or (matches is None and not require_snapshot)
    row: dict = {"impact_valid": valid, "impact_snapshot": record.get("repositorySnapshot")}
    for source in ("cited", "context"):
        scores = set_scores(predicted_files(record, source) if valid else None, gold_files)
        row.update({f"impact_{source}_{k}": v for k, v in scores.items()})
    return row
