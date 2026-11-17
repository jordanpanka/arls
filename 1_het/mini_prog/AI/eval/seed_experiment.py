import argparse
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _rename(record: dict, source: str, target: str) -> dict:
    record = dict(record)
    record["runKey"] = record["runKey"].replace(f"{source}|", f"{target}|", 1)
    if "experimentId" in record:
        record["experimentId"] = target
    return record


def _write(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def seed(source: str, target: str, rerun: set[str], results: Path = RESULTS) -> dict:
    out = results / target
    if out.exists():
        raise SystemExit(f"{out} already exists")
    runs = _records(results / source / "runs.jsonl")
    keep = {r["runKey"] for r in runs if r.get("runKey") and r.get("strategy") not in rerun}
    judgements = _records(results / source / "judgements.jsonl")
    out.mkdir(parents=True)
    _write(out / "runs.jsonl", [_rename(r, source, target) for r in runs if r.get("runKey") in keep])
    _write(out / "judgements.jsonl", [_rename(j, source, target) for j in judgements if j.get("runKey") in keep])
    return {"runs": sum(1 for r in runs if r.get("runKey") in keep),
            "judgements": sum(1 for j in judgements if j.get("runKey") in keep)}


def main() -> None:
    parser = argparse.ArgumentParser(description="copy an experiment without the strategies that will be rerun")
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--rerun", default="adaptive_rag")
    args = parser.parse_args()
    counts = seed(args.source, args.target, {s.strip() for s in args.rerun.split(",") if s.strip()})
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
