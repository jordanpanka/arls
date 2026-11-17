from collections import defaultdict
from statistics import mean, pstdev, stdev

import numpy as np

BOOTSTRAP_SAMPLES = 2000
CONFIDENCE = 0.95


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def bootstrap_ci(values: list[float], samples: int = BOOTSTRAP_SAMPLES, confidence: float = CONFIDENCE,
                 seed: int = 0) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    data = np.asarray(values, dtype=float)
    means = rng.choice(data, size=(samples, len(data)), replace=True).mean(axis=1)
    alpha = (1 - confidence) / 2
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))


def question_means(rows: list[dict], metric: str, group_keys: tuple[str, ...]) -> dict[tuple, dict[str, list[float]]]:
    grouped: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("status", "ok") != "ok":
            continue
        value = row.get(metric)
        if is_number(value):
            grouped[tuple(row.get(k) for k in group_keys)][row["questionId"]].append(float(value))
    return grouped


def summarize(rows: list[dict], metrics: list[str], group_keys: tuple[str, ...], seed: int = 0) -> list[dict]:
    totals: dict[tuple, dict] = defaultdict(lambda: {"runs": 0, "ok": 0})
    for row in rows:
        group = tuple(row.get(k) for k in group_keys)
        totals[group]["runs"] += 1
        totals[group]["ok"] += int(row.get("status") == "ok")

    out = []
    for metric in metrics:
        per_group = question_means(rows, metric, group_keys)
        for group in sorted(totals, key=lambda g: tuple(str(x) for x in g)):
            questions = per_group.get(group, {})
            values = [mean(v) for v in questions.values()]
            within = [pstdev(v) for v in questions.values() if len(v) > 1]
            low, high = bootstrap_ci(values, seed=seed)
            out.append({
                **dict(zip(group_keys, group)),
                "metric": metric,
                "n_questions": len(values),
                "runs": totals[group]["runs"],
                "ok_runs": totals[group]["ok"],
                "mean": mean(values) if values else None,
                "std": stdev(values) if len(values) > 1 else None,
                "ci_low": low,
                "ci_high": high,
                "median": float(np.median(values)) if values else None,
                "within_question_std": mean(within) if within else None,
            })
    return out


def paired_differences(rows: list[dict], metric: str, key: str, a: str, b: str, group_keys: tuple[str, ...],
                       seed: int = 0) -> list[dict]:
    out = []
    groups = sorted({tuple(r.get(k) for k in group_keys) for r in rows}, key=lambda g: tuple(str(x) for x in g))
    for group in groups:
        subset = [r for r in rows if tuple(r.get(k) for k in group_keys) == group]
        side_a = question_means([r for r in subset if r.get(key) == a], metric, ())[()]
        side_b = question_means([r for r in subset if r.get(key) == b], metric, ())[()]
        shared = sorted(set(side_a) & set(side_b))
        deltas = [mean(side_a[q]) - mean(side_b[q]) for q in shared]
        low, high = bootstrap_ci(deltas, seed=seed)
        out.append({
            **dict(zip(group_keys, group)),
            "metric": metric,
            "comparison": f"{a} - {b}",
            "n_questions": len(deltas),
            "mean_delta": mean(deltas) if deltas else None,
            "ci_low": low,
            "ci_high": high,
            "wins": sum(1 for d in deltas if d > 0),
            "losses": sum(1 for d in deltas if d < 0),
            "ties": sum(1 for d in deltas if d == 0),
        })
    return out
