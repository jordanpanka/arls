import re
from dataclasses import dataclass, field

from app.evidence.schemas import Evidence
from app.patterns.detector import Detection, subject_label
from app.patterns.knowledge_base import STATUS_ORDER, KnowledgeBase, PatternDefinition
from app.patterns.models import (
    Alternative,
    Alternatives,
    ComparisonRow,
    ConsideredPattern,
    PatternRecommendation,
)
from app.patterns.signals import HIGH_FAN_IN, Signal, measured, symbol_tail

CHANGE_PATTERNS: dict[str, list[str]] = {
    "new_variant": [
        r"\bnew (\w+ )?(payment|shipping|pricing|export|import|delivery|notification|discount|tax|report|auth\w*|login|storage|provider|format|channel|algorithm|strategy|variant|type|kind|mode|method|option|rule|handler|backend|engine)s?\b",
        r"\banother (\w+ )?(payment|shipping|provider|format|channel|type|kind|variant|method|option|backend)\b",
        r"\bsupport (for )?(a |an )?(new|another|additional)\b", r"\badditional (\w+ )?(provider|format|type|method|channel)s?\b",
        r"\búj (\w+ )?(fizetési|szállítási|export|formátum|típus|mód|szolgáltató|csatorna|algoritmus)\w*", r"\btovábbi (\w+ )?(típus|mód|szolgáltató)\w*",
    ],
    "extend": [r"\bextend\w*\b", r"\bextensib\w*\b", r"\badd\w* (a |an )?(new )?(feature|function\w*|capabilit\w*)\b", r"\bbővít\w*\b", r"\bhozzáad\w*\b"],
    "refactor": [r"\brefactor\w*\b", r"\bdesign pattern\w*\b", r"\bpattern\w*\b", r"\bsimplif\w*\b", r"\bclean ?up\b", r"\brestructur\w*\b",
                 r"\brefaktor\w*\b", r"\btervezési mint\w*\b", r"\begyszerűsít\w*\b", r"\bátszervez\w*\b"],
    "integration": [r"\bintegrat\w*\b", r"\bthird[- ]party\b", r"\bexternal (api|service|system|library|sdk)\b", r"\blegacy\b", r"\bsdk\b",
                    r"\bwrap\w*\b", r"\bwithout rewriting\b", r"\bconnect\w* to\b", r"\bintegrál\w*\b", r"\billeszt\w*\b", r"\bkülső\b", r"\bhagyaték\w*\b"],
    "cross_cutting": [r"\blog(ging)?\b", r"\bcach\w*\b", r"\bretr(y|ies)\b", r"\baudit\w*\b", r"\btiming\b", r"\bmetrics? (around|for every|to all)\b",
                      r"\bauthori[sz]\w*\b", r"\brate[- ]limit\w*\b", r"\bnaplóz\w*\b", r"\bgyorsítótár\w*\b", r"\bújrapróbál\w*\b"],
    "notification": [r"\bnotif\w*\b", r"\bevents?\b", r"\bsubscri\w*\b", r"\blisten\w*\b", r"\bwhen .{1,40} changes?\b", r"\breact\w* to\b",
                     r"\bértesít\w*\b", r"\besemény\w*\b", r"\bfeliratkoz\w*\b"],
    "creation": [r"\binstantiat\w*\b", r"\bfactory\b", r"\bconstruct(ion|ing)? (of )?(objects|instances)\b", r"\bcreat\w* (the right|different|objects|instances)\b",
                 r"\bpéldányosít\w*\b"],
    "simplify_access": [r"\btoo many (calls|steps|classes|dependencies)\b", r"\bhard to use\b", r"\bsingle entry\b", r"\bunified (api|interface|entry)\b",
                        r"\bsimpler (api|interface)\b", r"\begységes (felület|belépési)\w*\b"],
    "data_access": [r"\bdatabase\b", r"\bpersist\w*\b", r"\brepositor(y|ies)\b", r"\bquer(y|ies)\b", r"\bstorage\b", r"\bstore (data|records)\b",
                    r"\bdata access\b", r"\badatbázis\w*\b", r"\blekérdez\w*\b"],
}


def classify_change(text: str | None) -> list[str]:
    lowered = (text or "").lower()
    return [kind for kind, patterns in CHANGE_PATTERNS.items() if any(re.search(p, lowered) for p in patterns)]


@dataclass
class Facts:
    signals: list[Signal]
    grouped: dict
    metrics: list[Evidence]
    seed_files: set[str]
    graph: object | None = None
    evidence_ids: dict = field(default_factory=dict)

    def signal_ids(self, signals: list[Signal]) -> list[str]:
        ids: list[str] = []
        for signal in signals:
            for location in signal.locations:
                evidence_id = self.evidence_ids.get(location.key)
                if evidence_id and evidence_id not in ids:
                    ids.append(evidence_id)
        return ids

    def callers(self, path: str | None, symbol: str | None) -> list | None:
        if self.graph is None or not symbol:
            return None
        nodes = [n for n in self.graph.find(symbol_tail(symbol), "function", path) if n.kind in ("function", "method")]
        if not nodes:
            return None
        callers = []
        for node in nodes[:2]:
            for caller_id in self.graph.in_edges.get(node.id, {}):
                caller = self.graph.nodes[caller_id]
                if caller not in callers:
                    callers.append(caller)
        return callers

    def in_scope(self, detection: Detection) -> bool:
        return bool(set(detection.files) & self.seed_files)


def _rank(detections: list[Detection], facts: Facts) -> list[Detection]:
    return sorted(detections, key=lambda d: (not facts.in_scope(d), -STATUS_ORDER[d.status], d.anchor))


CONFIDENCE_DOWN = {"high": "medium", "medium": "low", "low": "low"}


def recommend(kb: KnowledgeBase, change_kinds: list[str], existing: list[Detection], opportunities: list[Detection],
              facts: Facts) -> tuple[list[PatternRecommendation], list[ConsideredPattern], dict[str, Detection]]:
    kinds = set(change_kinds)
    recommendations: list[PatternRecommendation] = []
    considered: list[ConsideredPattern] = []
    basis: dict[str, Detection] = {}
    few_variants = [s for s in facts.signals if s.id == "few_variants" and s.locations and s.locations[0].path in facts.seed_files]

    for pattern in kb.patterns:
        found = _rank([d for d in existing if d.pattern.id == pattern.id and d.status in ("confirmed", "likely")], facts)
        options = _rank([d for d in opportunities if d.pattern.id == pattern.id], facts)
        fit = bool(set(pattern.change_affinity) & kinds) or ("refactor" in kinds and bool(options or found))
        if found and fit:
            top = found[0]
            confidence = "high" if top.status == "confirmed" and facts.in_scope(top) else "medium"
            recommendations.append(_recommendation(pattern, top, "extend_existing", confidence, facts))
            basis[pattern.id] = top
            continue
        if options and fit:
            top = options[0]
            confidence = "medium" if top.status in ("likely", "confirmed") else "low"
            if top.counter_indications:
                confidence = CONFIDENCE_DOWN[confidence]
            if not facts.in_scope(top) and facts.seed_files:
                confidence = CONFIDENCE_DOWN[confidence]
            if confidence == "low":
                considered.append(ConsideredPattern(pattern=pattern.id, name=pattern.name, reason=(
                    f"Weak evidence only: {top.signals[0].why}" + (" (outside the code that the change touches)" if not facts.in_scope(top) else "")
                    + ("; " + "; ".join(top.counter_indications) if top.counter_indications else "")
                    + (" - no measured complexity supports a refactoring" if not top.boosted_by else ""))))
                continue
            recommendations.append(_recommendation(pattern, top, "introduce", confidence, facts))
            basis[pattern.id] = top
            continue
        if pattern.id == "strategy" and few_variants and fit:
            considered.append(ConsideredPattern(pattern=pattern.id, name=pattern.name,
                                                reason=f"{few_variants[0].why}; {pattern.avoid_when[0].lower()} does not justify a new abstraction"))
        elif fit:
            considered.append(ConsideredPattern(pattern=pattern.id, name=pattern.name,
                                                reason="The requested kind of change matches this pattern, but the analyzed code shows no structure it would simplify."))
        elif found or options:
            evidence = (found or options)[0]
            considered.append(ConsideredPattern(pattern=pattern.id, name=pattern.name,
                                                reason=f"{evidence.signals[0].why}, but the requested change is not of a kind this pattern addresses."))
    creating = {pid for pid, d in basis.items() if any(s.id in CREATION_SIGNALS for s in d.signals)}
    recommendations.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}[r.confidence], r.mode != "extend_existing", r.pattern not in creating))
    return recommendations, considered, basis


CREATION_SIGNALS = {"type_dependent_creation", "scattered_creation", "creator_returns_abstraction", "abstract_creator_overridden"}


def _recommendation(pattern: PatternDefinition, detection: Detection, mode: str, confidence: str, facts: Facts) -> PatternRecommendation:
    subject = subject_label(detection.anchor)
    reasons = [s.why for s in detection.signals]
    if mode == "extend_existing":
        reason = f"{pattern.name} is already used here ({detection.status}): {'; '.join(reasons[:3])}. Extending it follows the existing design."
        changes = _extend_changes(pattern, detection)
    else:
        reason = f"{detection.rule.explanation} {'; '.join(reasons[:3])}."
        changes = _introduce_changes(pattern, detection)
    risks = _risks(detection, facts)
    return PatternRecommendation(
        pattern=pattern.id, name=pattern.name, category=pattern.category, mode=mode, confidence=confidence,
        reason=reason, subject=subject, evidence_ids=facts.signal_ids(detection.signals),
        architectural_changes=changes, benefits=pattern.benefits[:3],
        tradeoffs=pattern.drawbacks[:3] + [f"Not appropriate when: {pattern.avoid_when[0].lower()}"], risks=risks,
    )


def _extend_changes(pattern: PatternDefinition, detection: Detection) -> list[str]:
    anchor = detection.anchor
    implementations = detection.detail("implementations") or []
    if pattern.id in ("strategy", "factory_method", "adapter", "decorator"):
        model = f", modelled on {implementations[0]}" if implementations else ""
        steps = [f"Proposed: add one class implementing {anchor}{model}"]
        creator = detection.detail("creator")
        if creator:
            steps.append(f"Return the new class from {creator}")
        context = detection.detail("context")
        if context:
            steps.append(f"Pass the new implementation to {context} where it is wired today")
        return steps
    if pattern.id == "observer":
        return [f"Proposed: implement the notification method ({detection.detail('method') or 'update'}) in a new observer",
                f"Register it with {detection.detail('subject') or anchor} at start-up"]
    return [f"Follow the existing {pattern.name} around {subject_label(anchor)}"]


def _introduce_changes(pattern: PatternDefinition, detection: Detection) -> list[str]:
    function = detection.detail("function")
    path = detection.detail("path")
    branches = detection.detail("branches")
    discriminator = detection.detail("discriminator")
    if pattern.id == "strategy" and function:
        return [
            f"Proposed: introduce one interface for the behaviour that {function} selects by {discriminator}",
            f"Proposed: move each of the {branches} branches of {function} ({path}) into its own implementation",
            "Proposed: add the new variant as one more implementation",
            f"Replace the conditional in {function} with a lookup or an injected implementation",
        ]
    if pattern.id == "factory_method" and detection.detail("created"):
        created = ", ".join(detection.detail("created")[:4])
        return [
            f"Proposed: move the creation of {created} into one creator method returning their common abstraction",
            "Replace the construction sites with calls to the creator",
            "Proposed: add the new product to the creator only",
        ]
    if pattern.id == "facade" and detection.detail("subsystem"):
        return [f"Proposed: create a facade with one method for the sequence {', '.join(detection.detail('subsystem')[:4])}",
                f"Move {', '.join(detection.detail('clients') or [])} to the facade one by one"]
    if pattern.id == "observer" and detection.detail("receivers"):
        return [f"Proposed: define an observer interface with {detection.detail('method')}",
                f"Register {', '.join(detection.detail('receivers'))} as observers instead of calling them directly"]
    if pattern.id == "adapter":
        return [f"Proposed: create an adapter class that implements {detection.anchor}",
                "Hold the new external component in the adapter and translate each call",
                f"Register the adapter where the other {detection.anchor} implementations are wired"]
    return [f"Proposed: {step}" if i == 0 else step for i, step in enumerate(pattern.implementation.steps)]


def _risks(detection: Detection, facts: Facts) -> list[str]:
    risks: list[str] = []
    function = detection.detail("function")
    path = detection.detail("path")
    if function:
        callers = facts.callers(path, function)
        if callers is not None:
            risks.append(f"{function} has {len(callers)} caller(s) in the code graph" + (" - changes to it propagate widely" if len(callers) >= HIGH_FAN_IN else ""))
        values = measured(facts.metrics, path, None, None, symbol_tail(function))
        if values.get("cyclomaticComplexity") is not None:
            risks.append(f"{function} has measured cyclomatic complexity {values['cyclomaticComplexity']:g} (Lizard); restructuring it needs regression tests")
    for signal in facts.signals:
        if signal.id == "high_fan_in" and signal.anchor == detection.anchor:
            risks.append(signal.why)
    risks.append("Test coverage of the affected code was not analyzed")
    return risks


def _dispatch_signal(facts: Facts, basis: Detection | None) -> Signal | None:
    if basis is not None:
        for signal in basis.signals:
            if signal.id in ("conditional_dispatch", "type_dispatch", "type_dependent_creation"):
                return signal
    candidates = [s for s in facts.signals if s.id in ("conditional_dispatch", "few_variants", "type_dispatch", "type_dependent_creation")]
    in_scope = [s for s in candidates if s.locations and s.locations[0].path in facts.seed_files]
    ranked = sorted(in_scope or [], key=lambda s: -(s.detail.get("branches") or 0))
    return ranked[0] if ranked else None


def _risk_level(callers: int, complexity: float | None, high_complexity: bool) -> str:
    if callers >= HIGH_FAN_IN or high_complexity:
        return "high"
    if callers >= 2 or (complexity or 0) >= 8:
        return "medium"
    return "low"


def compare(kb: KnowledgeBase, change_kinds: list[str], recommendations: list[PatternRecommendation],
            basis: dict[str, Detection], facts: Facts) -> tuple[Alternatives, list[ComparisonRow], str, str]:
    top = recommendations[0] if recommendations else None
    seed = sorted(facts.seed_files)
    if top is not None and top.mode == "extend_existing":
        detection = basis[top.pattern]
        creation_files = [loc.path for s in facts.signals if s.id in ("scattered_creation", "type_dependent_creation", "creator_returns_abstraction")
                          for loc in s.locations]
        affected = list(dict.fromkeys(creation_files + [f for f in detection.files if f in facts.seed_files]))[:6]
        minimal = Alternative(
            kind="minimal_change",
            summary=f"Add a new implementation to the existing {top.name} around {top.subject}",
            changes=top.architectural_changes,
            affected_files=affected,
            new_elements=[c for c in top.architectural_changes if c.startswith("Proposed:")],
            advantages=["Follows the abstraction that is already in place", "Existing implementations stay untouched"],
            disadvantages=["The new class must respect the contract of the existing abstraction"],
            risks=top.risks,
            evidence_ids=top.evidence_ids,
        )
        rows = [
            ComparisonRow(dimension="Approach", minimal_change="Extend the existing pattern", pattern_refactoring="Not needed: the pattern already exists", basis="qualitative"),
            ComparisonRow(dimension="Existing files to modify", minimal_change=str(len(affected)), pattern_refactoring="-", basis="planned"),
        ]
        justification = (f"{top.name} is already present ({detection.status} structural evidence), so the minimal change and the pattern-conforming "
                         "change are the same: add one implementation and wire it where the others are wired.")
        return Alternatives(minimal_change=minimal), rows, "minimal_change", justification

    dispatch = _dispatch_signal(facts, basis.get(top.pattern) if top else None)
    function = dispatch.detail.get("function") if dispatch else None
    path = dispatch.detail.get("path") if dispatch else None
    branches = dispatch.detail.get("branches") if dispatch else None
    found_callers = facts.callers(path, function) if function else None
    callers = found_callers or []
    values = measured(facts.metrics, path, None, None, symbol_tail(function)) if function else {}
    complexity = values.get("cyclomaticComplexity")
    high_complexity = any(s.id == "high_complexity" and function and s.anchor.endswith(function) for s in facts.signals)

    if dispatch is not None:
        location = dispatch.locations[0]
        minimal = Alternative(
            kind="minimal_change",
            summary=f"Add one more case to {function} for the requested change",
            changes=[f"Add a branch for the new case to {function} ({path}:{location.start_line}-{location.end_line})",
                     "Implement the new behaviour in that branch or in a helper function next to it"],
            affected_files=[path],
            advantages=["Smallest diff; follows the current structure", "No new abstractions to review"],
            disadvantages=["Every future variant edits the same function"],
            technical_debt=[f"{function} grows from {branches} to {branches + 1} cases" if branches else f"{function} keeps growing"]
                           + ([f"Each new branch adds at least one decision point to a function measured at cyclomatic complexity {complexity:g} (Lizard)"] if complexity is not None else []),
            risks=["Low: existing branches are not modified"],
            evidence_ids=facts.signal_ids([dispatch]),
        )
    else:
        minimal = Alternative(
            kind="minimal_change",
            summary="Change the existing code in place without new abstractions",
            changes=[f"Modify {f} directly" for f in seed[:3]] or ["Modify the code identified by the retrieval steps directly"],
            affected_files=seed[:3],
            advantages=["Smallest diff", "No new abstractions to review"],
            disadvantages=["Does not prepare the code for further variants"],
            risks=["Depends on the callers of the changed code"],
        )

    pattern_alt = None
    if top is not None:
        definition = kb.get(top.pattern)
        caller_files = sorted({c.path for c in callers} - {path})[:5]
        pattern_files = list(dict.fromkeys([f for f in [path] if f] + caller_files + [f for f in basis[top.pattern].files if f in facts.seed_files]))[:8]
        pattern_alt = Alternative(
            kind="pattern_refactoring",
            summary=f"Introduce {top.name} for {top.subject}",
            changes=top.architectural_changes,
            affected_files=pattern_files,
            new_elements=[f"Proposed: {name}" for name in definition.implementation.new_abstractions],
            advantages=top.benefits,
            disadvantages=top.tradeoffs[:2],
            risks=top.risks,
            evidence_ids=top.evidence_ids,
        )

    risk = _risk_level(len(callers), complexity, high_complexity)
    rows = _rows(minimal, pattern_alt, function, branches, callers, complexity, risk, found_callers is not None)
    preferred, justification = _decide(top, branches, complexity, high_complexity, risk, change_kinds, function)
    return Alternatives(minimal_change=minimal, pattern_refactoring=pattern_alt), rows, preferred, justification


def _rows(minimal: Alternative, pattern: Alternative | None, function, branches, callers, complexity, risk, graph_available) -> list[ComparisonRow]:
    none = "not proposed"
    rows = [
        ComparisonRow(dimension="Existing files to modify", minimal_change=str(len(minimal.affected_files)),
                      pattern_refactoring=str(len(pattern.affected_files)) if pattern else none, basis="planned"),
        ComparisonRow(dimension="New abstractions", minimal_change="0",
                      pattern_refactoring=str(len(pattern.new_elements)) if pattern else none, basis="planned"),
    ]
    if function:
        caller_text = f"{len(callers)}" if graph_available else "unknown (not in the code graph)"
        rows.append(ComparisonRow(dimension=f"Callers of {function}", minimal_change=f"{caller_text}, signature unchanged",
                                  pattern_refactoring=f"{caller_text}, wiring may change" if pattern else none, basis="measured"))
        rows.append(ComparisonRow(dimension=f"Cyclomatic complexity of {function} today",
                                  minimal_change=f"{complexity:g} (Lizard)" if complexity is not None else "not measured",
                                  pattern_refactoring=f"{complexity:g} (Lizard)" if complexity is not None and pattern else (none if not pattern else "not measured"),
                                  basis="measured"))
    if branches:
        rows.append(ComparisonRow(dimension=f"Cases handled in {function}", minimal_change=f"{branches} -> {branches + 1}",
                                  pattern_refactoring=f"{branches} -> moved into {branches + 1} classes" if pattern else none, basis="planned"))
    rows += [
        ComparisonRow(dimension="Coupling", minimal_change="The client keeps knowing every variant",
                      pattern_refactoring="The client depends on one abstraction" if pattern else none, basis="qualitative"),
        ComparisonRow(dimension="Cohesion", minimal_change="All variants stay in one place",
                      pattern_refactoring="Each variant lives in its own class" if pattern else none, basis="qualitative"),
        ComparisonRow(dimension="Extensibility", minimal_change="Each new variant edits existing code",
                      pattern_refactoring="New variants are added as new classes" if pattern else none, basis="qualitative"),
        ComparisonRow(dimension="Regression risk", minimal_change="Low: existing behaviour untouched",
                      pattern_refactoring=f"{risk.capitalize()}: existing behaviour is moved" if pattern else none, basis="qualitative"),
        ComparisonRow(dimension="Compatibility with legacy code", minimal_change="No structural change",
                      pattern_refactoring="Changes how the code is wired" if pattern else none, basis="qualitative"),
    ]
    return rows


def _decide(top: PatternRecommendation | None, branches, complexity, high_complexity, risk, change_kinds, function) -> tuple[str, str]:
    if top is None:
        return "minimal_change", ("No design pattern is justified by the analyzed code: no structural evidence links the requested change "
                                  "to a pattern, so the smallest change in the existing structure is preferred.")
    pressure = (branches or 0) >= 4 or high_complexity or "refactor" in change_kinds
    if top.confidence in ("high", "medium") and pressure and risk != "high":
        reasons = []
        if (branches or 0) >= 4:
            reasons.append(f"{function} already handles {branches} cases")
        if high_complexity:
            reasons.append(f"{function} is in the high measured complexity band")
        if "refactor" in change_kinds:
            reasons.append("the request asks for a restructuring")
        return "pattern_refactoring", (f"{top.name} is preferred because {' and '.join(reasons)}; the expected benefit outweighs the "
                                       f"{risk} regression risk of moving existing behaviour.")
    reasons = []
    if branches and branches < 4:
        reasons.append(f"{function} handles only {branches} cases")
    if not high_complexity:
        reasons.append("no measured complexity in the high band")
    if risk == "high":
        reasons.append("the regression risk of restructuring is high")
    return "minimal_change", (f"The minimal change is preferred: {', '.join(reasons) or 'the evidence for the pattern is not strong enough'}. "
                              f"{top.name} remains an option to revisit when more variants are added.")
