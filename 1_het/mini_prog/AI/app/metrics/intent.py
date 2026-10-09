"""Decides whether code metrics are useful evidence for a question.

Deliberately simple and rule-based: it only has to keep metrics out of prompts
where they add nothing ("What does getUserName() return?") and bring them in
for quality/structure questions. It is isolated here so an adaptive router can
replace it later; it encodes no assumption about which retrieval strategy fits
which kind of repository.
"""
import re
from dataclasses import dataclass, field

FOCUS_PATTERNS: dict[str, list[str]] = {
    "complexity": [
        r"\bcomplex(ity|ities)?\b", r"\bcyclomatic\b", r"\bccn\b", r"\bmccabe\b",
        r"\bconvoluted\b", r"\bbranch(ing|es)\b", r"\bdeeply nested\b",
    ],
    "maintainability": [
        r"\bmaintainab\w*\b", r"\bmaintenance\b",
        r"\b(hard|difficult|easy) to (maintain|change|understand|read)\b",
        r"\brefactor\w*\b", r"\btechnical debt\b", r"\bcode quality\b", r"\bquality\b",
        r"\bcode smells?\b", r"\b(long|lengthy|large|huge) (functions?|methods?)\b",
        r"\b(too )?many parameters\b", r"\bparameter count\b", r"\bfunction length\b",
    ],
    "dependency": [
        r"\bfan[- ]?(in|out)\b", r"\bcoupl(ed|ing)\b", r"\bdependenc(y|ies)\b",
        r"\b(most|highly|heavily|tightly) connected\b", r"\bconnectivity\b",
        r"\bcircular\b", r"\bcycles?\b", r"\bcalled the most\b", r"\bdepends? on the most\b",
        r"\barchitectur(e|al) (importance|hotspots?|risk)\b", r"\bcentral (component|class|file)s?\b",
    ],
    "size": [
        r"\blines of code\b", r"\b(n)?loc\b", r"\b(biggest|largest) (files?|classes?|functions?|components?)\b",
        r"\bhow (big|large)\b",
    ],
    "general": [r"\bhot ?spots?\b", r"\bmetrics?\b"],
}

# Ranking or repository-wide phrasing: the answer needs repository-level rankings,
# not only the metrics of whatever vector search happened to retrieve.
REPOSITORY_PATTERNS = [
    r"\bwhich (files?|classes|class|functions?|methods?|components?|modules?|services?|parts?)\b",
    r"\b(most|least|top|highest|lowest|biggest|largest|worst)\b",
    r"\bwhere (are|is|should)\b", r"\bhot ?spots?\b", r"\brank\w*\b",
    r"\b(whole|entire|overall) (repository|repo|codebase|project)\b",
    r"\b(repository|repo|codebase|project)[- ]wide\b",
    r"\bin (the|this) (repository|repo|codebase|project)\b",
]


@dataclass
class MetricsIntent:
    use_metrics: bool
    scope: str = "none"          # none | entity | repository
    focus: str = "general"       # complexity | maintainability | dependency | size | general
    matched: list[str] = field(default_factory=list)


def detect_metrics_intent(question: str) -> MetricsIntent:
    text = (question or "").lower()

    hits: dict[str, list[str]] = {}
    for focus, patterns in FOCUS_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                hits.setdefault(focus, []).append(match.group(0))

    if not hits:
        return MetricsIntent(use_metrics=False)

    specific = [f for f in hits if f != "general"]
    focus = max(specific, key=lambda f: len(hits[f])) if specific else "general"
    scope = "repository" if any(re.search(p, text) for p in REPOSITORY_PATTERNS) else "entity"

    return MetricsIntent(
        use_metrics=True,
        scope=scope,
        focus=focus,
        matched=[m for matches in hits.values() for m in matches],
    )
