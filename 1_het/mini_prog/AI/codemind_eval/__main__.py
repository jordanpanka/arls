import argparse
import asyncio
import json
import sys
from pathlib import Path

from codemind_eval.schema import Benchmark, Scope, file_hash, impact_benchmark, load_benchmark, load_impact_set

AI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = AI_ROOT / "eval" / "results"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _load(args) -> tuple[Benchmark, Path]:
    if getattr(args, "impact", None):
        path = Path(args.impact)
        return impact_benchmark(load_impact_set(path), name=path.stem), path
    path = Path(args.benchmark)
    return load_benchmark(path), path


def _out_dir(args) -> Path:
    return Path(args.results) / args.experiment_id


def cmd_run(args) -> int:
    from app.evaluation.eval_mode import DEFAULT_STRATEGIES, METRICS_VARIANTS, validate_strategy
    from codemind_eval.runner import ExperimentConfig, run_experiment

    benchmark, path = _load(args)
    try:
        strategies = [validate_strategy(s) for s in (_csv(args.strategies) or list(DEFAULT_STRATEGIES))]
    except ValueError as e:
        raise SystemExit(str(e))
    variants = _csv(args.metrics_variants) or ["default"]
    for variant in variants:
        if variant not in METRICS_VARIANTS:
            raise SystemExit(f"unknown metrics variant {variant}; use {', '.join(METRICS_VARIANTS)}")
    if args.only:
        wanted = set(_csv(args.only))
        benchmark = benchmark.model_copy(update={"questions": [q for q in benchmark.questions if q.id in wanted]})
    if args.limit:
        benchmark = benchmark.model_copy(update={"questions": benchmark.questions[: args.limit]})
    scope = None
    if args.project_id is not None:
        scope = Scope(user_id=args.user_id, investigation_id=args.investigation_id, project_id=args.project_id)
    config = ExperimentConfig(
        experiment_id=args.experiment_id,
        out_dir=_out_dir(args),
        strategies=strategies,
        metrics_variants=variants,
        repetitions=args.repetitions,
        retries=args.retries,
        backoff_s=args.backoff,
        run_timeout_s=args.run_timeout,
        clear_caches=not args.keep_caches,
        shuffle_seed=args.shuffle_seed,
        default_scope=scope,
        ablation=args.ablation,
        benchmark_path=str(path),
        benchmark_hash=file_hash(path),
    )
    counts = asyncio.run(run_experiment(config, benchmark, argv=sys.argv))
    print(json.dumps(counts, indent=2))
    return 0 if counts["error"] == 0 else 2


def cmd_judge(args) -> int:
    from codemind_eval.judge import judge_config_from_env, run_judge

    benchmark, _ = _load(args)
    config = judge_config_from_env(args.judge_model, args.judge_base_url)
    config.retries = args.retries
    counts = run_judge(_out_dir(args), benchmark, config)
    print(json.dumps(counts, indent=2))
    return 0


def cmd_score(args) -> int:
    from codemind_eval.scoring import score_experiment

    benchmark, _ = _load(args)
    result = score_experiment(_out_dir(args), benchmark, require_snapshot=not args.allow_unverified_snapshot,
                              routing_quality=args.routing_quality)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_combine(args) -> int:
    from codemind_eval.scoring import combine_experiments

    sources = [Path(args.results) / name for name in _csv(args.experiments)]
    if len(sources) < 2:
        raise SystemExit("--experiments needs at least two experiment ids")
    result = combine_experiments(sources, _out_dir(args), routing_quality=args.routing_quality)
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_report(args) -> int:
    from codemind_eval.reports import generate_reports

    produced = generate_reports(_out_dir(args))
    for name, path in produced.items():
        print(f"{name}: {path or 'skipped (no data)'}")
    return 0


def cmd_routing_report(args) -> int:
    from codemind_eval.reports import routing_correctness_report

    produced = routing_correctness_report(_out_dir(args), args.routing_quality)
    for name, path in produced.items():
        print(f"{name}: {path or 'skipped (no data)'}")
    return 0


def cmd_validate(args) -> int:
    from codemind_eval.validate import validate_gold

    benchmark, _ = _load(args)
    report = validate_gold(benchmark, Path(args.repo), args.commit)
    bad = [r for r in report if r["status"] not in ("ok", "no_gold", "unchecked")]
    for row in report:
        if row["status"] != "ok" or args.verbose:
            print(f"{row['status']:>15}  {row['questionId']}  {row['evidence']}  {row['detail']}")
    print(f"{len(report) - len(bad)} ok / {len(bad)} problems")
    return 1 if bad else 0


def cmd_impact_mine(args) -> int:
    from codemind_eval.impact import mine_commits

    impact = mine_commits(Path(args.repo), args.repository_id, args.url, args.range, args.max_cases,
                          args.min_files, args.max_files, tuple(_csv(args.extensions)), args.diff_filter,
                          args.exclude_tests)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(impact.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(impact.cases)} cases written to {args.out}")
    return 0


def _common(parser: argparse.ArgumentParser, experiment: bool = True) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--benchmark", help="benchmark JSON (new or legacy questions.json format)")
    source.add_argument("--impact", help="impact case JSON produced by impact-mine")
    if experiment:
        parser.add_argument("--experiment-id", required=True)
        parser.add_argument("--results", default=str(DEFAULT_RESULTS))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codemind_eval", description="CodeMind retrieval strategy evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="execute the benchmark against the live services")
    _common(run)
    run.add_argument("--user-id", type=int, default=None)
    run.add_argument("--investigation-id", type=int, default=None)
    run.add_argument("--project-id", type=int, default=None)
    run.add_argument("--strategies", default="", help="comma separated; default: the five evaluated strategies")
    run.add_argument("--metrics-variants", default="default", help="default,off for the code-metrics ablation")
    run.add_argument("--ablation", default=None, help="agent ablation applied to agent strategies")
    run.add_argument("--repetitions", type=int, default=1)
    run.add_argument("--retries", type=int, default=2)
    run.add_argument("--backoff", type=float, default=5.0)
    run.add_argument("--run-timeout", type=float, default=None)
    run.add_argument("--shuffle-seed", type=int, default=None)
    run.add_argument("--keep-caches", action="store_true", help="do not clear tool caches between runs")
    run.add_argument("--only", default="")
    run.add_argument("--limit", type=int, default=None)
    run.set_defaults(func=cmd_run)

    judge = sub.add_parser("judge", help="LLM-as-judge answer scoring (optional)")
    _common(judge)
    judge.add_argument("--judge-model", default=None)
    judge.add_argument("--judge-base-url", default=None)
    judge.add_argument("--retries", type=int, default=2)
    judge.set_defaults(func=cmd_judge)

    score = sub.add_parser("score", help="compute metrics and write CSV tables")
    _common(score)
    score.add_argument("--allow-unverified-snapshot", action="store_true")
    score.add_argument("--routing-quality", default=None, help="row column used as quality for the routing oracle")
    score.set_defaults(func=cmd_score)

    combine = sub.add_parser("combine", help="pool the scored rows of several experiments into one score set")
    combine.add_argument("--experiments", required=True, help="comma separated experiment ids, each already scored")
    combine.add_argument("--experiment-id", required=True)
    combine.add_argument("--results", default=str(DEFAULT_RESULTS))
    combine.add_argument("--routing-quality", default=None)
    combine.set_defaults(func=cmd_combine)

    report = sub.add_parser("report", help="render PNG figures from the score tables")
    report.add_argument("--experiment-id", required=True)
    report.add_argument("--results", default=str(DEFAULT_RESULTS))
    report.set_defaults(func=cmd_report)

    routing_report = sub.add_parser("routing-report", help="router decision correctness tables and figures")
    routing_report.add_argument("--experiment-id", required=True)
    routing_report.add_argument("--results", default=str(DEFAULT_RESULTS))
    routing_report.add_argument("--routing-quality", default=None)
    routing_report.set_defaults(func=cmd_routing_report)

    validate = sub.add_parser("validate-gold", help="check gold evidence against a local clone")
    _common(validate, experiment=False)
    validate.add_argument("--repo", required=True)
    validate.add_argument("--commit", default=None)
    validate.add_argument("--verbose", action="store_true")
    validate.set_defaults(func=cmd_validate)

    mine = sub.add_parser("impact-mine", help="build change-impact cases from historical commits")
    mine.add_argument("--repo", required=True)
    mine.add_argument("--repository-id", required=True)
    mine.add_argument("--url", default=None)
    mine.add_argument("--range", default="HEAD")
    mine.add_argument("--max-cases", type=int, default=20)
    mine.add_argument("--min-files", type=int, default=2)
    mine.add_argument("--max-files", type=int, default=10)
    mine.add_argument("--extensions", default=".java")
    mine.add_argument("--diff-filter", default="M")
    mine.add_argument("--exclude-tests", action="store_true")
    mine.add_argument("--out", required=True)
    mine.set_defaults(func=cmd_impact_mine)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) == "run" and args.project_id is not None and None in (args.user_id, args.investigation_id):
        raise SystemExit("--project-id requires --user-id and --investigation-id")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
