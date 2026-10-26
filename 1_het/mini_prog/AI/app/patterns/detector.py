from collections import defaultdict
from dataclasses import dataclass, field

from app.patterns.knowledge_base import STATUS_ORDER, KnowledgeBase, PatternDefinition, Rule
from app.patterns.signals import Signal

STATUS_BY_RANK = {rank: status for status, rank in STATUS_ORDER.items()}


@dataclass
class Detection:
    pattern: PatternDefinition
    kind: str
    status: str
    anchor: str
    rule: Rule
    signals: list[Signal] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    boosted_by: list[str] = field(default_factory=list)
    counter_indications: list[str] = field(default_factory=list)

    @property
    def files(self) -> list[str]:
        files: list[str] = []
        for signal in self.signals:
            for location in signal.locations:
                if location.path not in files:
                    files.append(location.path)
        return files

    def detail(self, key: str, default=None):
        for signal in self.signals:
            if key in signal.detail:
                return signal.detail[key]
        return default


def group_signals(signals: list[Signal]) -> dict[str, dict[str, list[Signal]]]:
    grouped: dict[str, dict[str, list[Signal]]] = defaultdict(lambda: defaultdict(list))
    for signal in signals:
        grouped[signal.anchor][signal.id].append(signal)
    return grouped


def _raise(status: str, cap: str) -> str:
    return STATUS_BY_RANK[min(STATUS_ORDER[status] + 1, STATUS_ORDER[cap])]


def _cap(status: str, cap: str) -> str:
    return STATUS_BY_RANK[min(STATUS_ORDER[status], STATUS_ORDER[cap])]


def _evaluate(pattern: PatternDefinition, kind: str, rules: list[Rule], grouped, change_kinds: set[str]) -> list[Detection]:
    best: dict[str, Detection] = {}
    for rule in rules:
        if rule.requires_change and not set(rule.requires_change) & change_kinds:
            continue
        for anchor, present in grouped.items():
            matched = [s for s in rule.all if s in present]
            if not matched:
                continue
            complete = len(matched) == len(rule.all)
            if complete:
                status = rule.status
            elif rule.partial_status:
                status = rule.partial_status
            else:
                continue
            boosts = [b for b in rule.boost if b in present] if complete else []
            if boosts:
                status = _raise(status, pattern.max_status)
            status = _cap(status, pattern.max_status)
            avoid = [a for a in pattern.detection.avoid_signals if a in present]
            detection = Detection(
                pattern=pattern, kind=kind, status=status, anchor=anchor, rule=rule,
                signals=[s for sid in matched + boosts for s in present[sid]],
                missing=[s for s in rule.all if s not in present],
                boosted_by=boosts,
                counter_indications=[present[a][0].why for a in avoid],
            )
            current = best.get(anchor)
            if current is None or STATUS_ORDER[detection.status] > STATUS_ORDER[current.status]:
                best[anchor] = detection
    return list(best.values())


def detect(kb: KnowledgeBase, signals: list[Signal], change_kinds: list[str] | None = None) -> tuple[list[Detection], list[Detection]]:
    grouped = group_signals(signals)
    kinds = set(change_kinds or [])
    existing: list[Detection] = []
    opportunities: list[Detection] = []
    for pattern in kb.patterns:
        existing += _evaluate(pattern, "existing", pattern.detection.existing, grouped, kinds)
        opportunities += _evaluate(pattern, "opportunity", pattern.detection.opportunities, grouped, kinds)
    order = lambda d: (-STATUS_ORDER[d.status], d.pattern.id, d.anchor)
    return sorted(existing, key=order), sorted(opportunities, key=order)


def subject_label(anchor: str) -> str:
    if "::" in anchor and not anchor.startswith("subsystem:"):
        path, _, symbol = anchor.rpartition("::")
        return f"{symbol} ({path})"
    if anchor.startswith("subsystem:"):
        return "subsystem " + anchor.removeprefix("subsystem:").replace("+", ", ")
    return anchor.replace("+", ", ")
