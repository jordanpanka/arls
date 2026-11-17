from codemind_eval.evidence_ids import file_units, path_matches, symbol_matches, symbol_units
from codemind_eval.schema import Question

K_VALUES = (5, 10)
LEVELS = ("file", "symbol")


def _file_hit(gold_path: str, unit: str) -> bool:
    return path_matches(gold_path, unit)


def _symbol_hit(gold: tuple[str | None, str], unit: tuple[str, str]) -> bool:
    return symbol_matches(gold[0], gold[1], unit[0], unit[1])


def ranked_scores(units: list, gold: list, hit, k_values=K_VALUES) -> dict:
    if not gold:
        return {}
    relevant = [any(hit(g, u) for g in gold) for u in units]
    scores: dict = {"retrieved": len(units)}
    for k in k_values:
        top = units[:k]
        found = sum(1 for g in gold if any(hit(g, u) for u in top))
        scores[f"recall@{k}"] = found / len(gold)
        scores[f"precision@{k}"] = sum(relevant[:k]) / k
    first = next((i for i, r in enumerate(relevant, start=1) if r), None)
    scores["mrr"] = 1 / first if first else 0.0
    scores["coverage"] = sum(1 for g in gold if any(hit(g, u) for u in units)) / len(gold)
    return scores


def gold_for_level(question: Question, level: str) -> list:
    if level == "file":
        return question.gold_file_paths()
    return [(g.path, g.symbol) for g in question.gold_symbols()]


def level_scores(items: list[dict], question: Question, level: str, k_values=K_VALUES) -> dict:
    gold = gold_for_level(question, level)
    if level == "file":
        return ranked_scores(file_units(items), gold, _file_hit, k_values)
    return ranked_scores(symbol_units(items), gold, _symbol_hit, k_values)


def retrieval_metrics(record: dict, question: Question, k_values=K_VALUES) -> dict:
    row: dict = {}
    for source, key in (("ctx", "contextEvidence"), ("ret", "retrievedEvidence")):
        items = record.get(key)
        for level in LEVELS:
            names = [f"{source}_{level}_{m}" for m in _metric_names(k_values)]
            if items is None:
                row.update({n: None for n in names})
                continue
            scores = level_scores(items, question, level, k_values)
            row.update({n: scores.get(n.split("_", 2)[2]) for n in names})
    return row


def _metric_names(k_values) -> list[str]:
    names = []
    for k in k_values:
        names += [f"recall@{k}", f"precision@{k}"]
    return names + ["mrr", "coverage", "retrieved"]
