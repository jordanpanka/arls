import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.config import ABLATIONS, AGENT_MODES
from app.evaluation.metrics import aggregate, score_run
from app.evaluation.trace_collector import MemoryTraceCollector, MultiTraceCollector, TraceCollector
from app.models.models import ChatRequest
from app.services.chat_service import SUPPORTED_MODES, run_chat

HERE = os.path.dirname(os.path.abspath(__file__))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare retrieval strategies on a fixed question set and repository snapshot.")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--investigation-id", type=int, required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--questions", default=os.path.join(HERE, "questions.json"))
    parser.add_argument("--modes", default="adaptive_rag,evidence_aware_agentic_rag", help=f"comma separated: {', '.join(SUPPORTED_MODES)}")
    parser.add_argument("--ablations", default="", help=f"comma separated, applied to agent modes: {', '.join(ABLATIONS)}")
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", default="", help="comma separated question ids")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out", default=os.path.join(HERE, "results"))
    return parser.parse_args()


def runs_for(modes: list[str], ablations: list[str]) -> list[tuple[str, str | None]]:
    runs = []
    for mode in modes:
        if mode in AGENT_MODES and ablations:
            runs += [(mode, ablation) for ablation in ablations]
        else:
            runs.append((mode, None))
    return runs


async def main():
    args = parse_args()
    with open(args.questions, encoding="utf-8") as handle:
        questions = json.load(handle)["questions"]
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    ablations = [a.strip() for a in args.ablations.split(",") if a.strip()]
    experiment_id = args.experiment_id or datetime.now(timezone.utc).strftime("exp-%Y%m%d-%H%M%S")
    os.makedirs(args.out, exist_ok=True)

    rows = []
    records_path = os.path.join(args.out, f"{experiment_id}-runs.jsonl")
    for question in questions:
        for mode, ablation in runs_for(modes, ablations):
            memory = MemoryTraceCollector()
            request = ChatRequest(
                prompt=question["question"],
                userId=args.user_id,
                investigationId=args.investigation_id,
                projectId=args.project_id,
                mode=mode,
                ablation=ablation,
                experimentId=experiment_id,
            )
            try:
                response = await run_chat(request, trace=MultiTraceCollector(TraceCollector(), memory))
            except Exception as e:
                print(f"[{question['id']}] {mode}/{ablation}: failed {type(e).__name__}: {e}")
                rows.append({"questionId": question["id"], "mode": mode, "ablation": ablation, "error": f"{type(e).__name__}: {e}"})
                continue
            record = memory.records[-1] if memory.records else {**(response.execution or {}), "answer": response.answer}
            record.setdefault("answer", response.answer)
            row = score_run(record, question, args.k)
            row["groundTruth"] = question.get("ground_truth", "")
            row["answer"] = response.answer
            rows.append(row)
            with open(records_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"questionId": question["id"], **record}, ensure_ascii=False, default=str) + "\n")
            print(f"[{question['id']}] {mode}/{ablation or '-'}: {row.get('status') or ''} stop={row.get('stopReason')} tools={row.get('toolCalls')} recall={row.get('evidenceRecall')}")

    fields = sorted({key for row in rows for key in row})
    with open(os.path.join(args.out, f"{experiment_id}-rows.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = aggregate([r for r in rows if "error" not in r])
    with open(os.path.join(args.out, f"{experiment_id}-summary.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
