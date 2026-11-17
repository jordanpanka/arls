import re
import subprocess
from pathlib import Path

from codemind_eval.evidence_ids import norm_symbol
from codemind_eval.schema import Benchmark


def _read_at(repo: Path, commit: str | None, path: str) -> str | None:
    if commit:
        result = subprocess.run(["git", "-C", str(repo), "cat-file", "-p", f"{commit}:{path}"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        return result.stdout if result.returncode == 0 else None
    file = repo / path
    return file.read_text(encoding="utf-8", errors="replace") if file.is_file() else None


def _symbol_pattern(symbol: str) -> re.Pattern:
    return re.compile(rf"\b{re.escape(symbol.split('(', 1)[0].split('.')[-1].strip())}\b")


def validate_gold(benchmark: Benchmark, repo: Path, commit: str | None = None) -> list[dict]:
    commit = commit or benchmark.repository.commit_sha
    if commit:
        check = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True)
        if check.returncode != 0:
            return [{"questionId": None, "evidence": commit, "status": "error",
                     "detail": f"commit {commit} is not available in {repo} (git fetch --tags?)"}]
    report = []
    for question in benchmark.questions:
        if not question.gold_evidence:
            report.append({"questionId": question.id, "evidence": None, "status": "no_gold", "detail": ""})
        for gold in question.gold_evidence:
            entry = {"questionId": question.id, "evidence": gold.id}
            if not gold.path:
                report.append({**entry, "status": "unchecked", "detail": "symbol without path cannot be located"})
                continue
            content = _read_at(repo, commit, gold.path)
            if content is None:
                report.append({**entry, "status": "missing_file", "detail": gold.path})
                continue
            if gold.kind == "symbol" and not _symbol_pattern(gold.symbol).search(content):
                report.append({**entry, "status": "missing_symbol", "detail": f"{norm_symbol(gold.symbol)} not in {gold.path}"})
                continue
            if gold.lines:
                count = content.count("\n") + 1
                if gold.lines[0] < 1 or gold.lines[1] > count or gold.lines[0] > gold.lines[1]:
                    report.append({**entry, "status": "bad_lines", "detail": f"{gold.lines} outside 1-{count}"})
                    continue
            report.append({**entry, "status": "ok", "detail": ""})
    return report
