import re
from dataclasses import asdict, dataclass, field

from app.metrics.intent import detect_metrics_intent

FILE_PATTERN = re.compile(r"(?<![\w/])((?:[\w.-]+/)*[\w.-]+\.(?:py|cs|js|jsx|ts|tsx|java|go|rs|php|cpp|c|h|hpp))\b")
QUOTED_PATTERN = re.compile(r"[`'\"]([A-Za-z_][\w.:]*?)(?:\(\))?[`'\"]")
CALL_PATTERN = re.compile(r"\b([A-Za-z_][\w.]*)\(\)")
DOTTED_PATTERN = re.compile(r"\b([A-Za-z_]\w+(?:\.[A-Za-z_]\w+)+)\b")
CAMEL_PATTERN = re.compile(r"\b([a-z][a-z0-9]*[A-Z]\w*)\b")
PASCAL_PATTERN = re.compile(r"\b([A-Z][a-z0-9]+[A-Z]\w*)\b")
SNAKE_PATTERN = re.compile(r"\b([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+)\b")

STOPWORDS = {"e.g", "i.e", "etc", "vs", "a.k.a"}
CLASS_PATTERN = re.compile(r"\b(class|classes|osztály\w*)\b")

INTENT_PATTERNS: dict[str, list[str]] = {
    "dependency": [
        r"\bdepend(s|ed|ent|ents|ency|encies)?\b", r"\bcall(s|ed|ers?|ing)?\b", r"\binvok\w*\b",
        r"\bused by\b", r"\buses?\b", r"\busing\b", r"\bimports?\b", r"\breferenc\w*\b", r"\bcoupl\w*\b",
        r"\bfügg(?!vény)\w*\b", r"\bhív\w*\b", r"\bhasznál(?!hat)\w*\b", r"\bimportál\w*\b",
    ],
    "impact": [
        r"\baffect\w*\b", r"\bimpact\w*\b", r"\bbreak\w*\b", r"\bripple\b", r"\bside[- ]effects?\b",
        r"\b(modif(y|ied|ying|ication)|chang(e|ed|ing))\b.*\b(what|which|who)\b",
        r"\b(what|which|who)\b.*\b(modif(y|ied|ying|ication)|chang(e|ed|ing))\b",
        r"\bérint\w*\b", r"\bhatás\w*\b", r"\bmódosít\w*\b", r"\bváltoztat\w*\b", r"\bmegváltoz\w*\b",
    ],
    "call_path": [
        r"\bcall (path|chain)\b", r"\bpath from\b", r"\bhow does .+ reach\b", r"\bflow from\b.+\bto\b",
        r"\bhívási (lánc|út)\b",
    ],
    "comprehension": [
        r"\bwhat (does|is|are)\b", r"\bexplain\w*\b", r"\bhow (does|do|is)\b.*\bwork\b", r"\bpurpose\b",
        r"\bdescribe\b", r"\bresponsib\w*\b", r"\bimplement(ed|ation|ations|s)\b",
        r"\bmit csinál\w*\b", r"\bmire (való|szolgál)\b", r"\bhogyan működik\b", r"\bmagyaráz\w*\b",
        r"\bmi a (feladata|szerepe|célja)\b", r"\bimplementál(va|ták|t)\b",
    ],
    "change_planning": [
        r"\bhow (do|can|should|would|could) (i|we|you)\b.*\b(implement|add|build|create|integrate|extend|support|introduce)\b",
        r"\bwhere (should|do|can|would|could) (i|we)\b.*\b(put|add|implement|place|register|hook|plug)\b",
        r"\b(i|we) (want|would like|need|plan) to (add|implement|build|create|introduce|extend|support)\b",
        r"\b(add|adding|introduce|introducing) (a |an |the )?(new )?\w*\s?(feature|function\w*|endpoint|tool|command|option|page|field|method|class|mode|setting|button|report|export|import)\b",
        r"\bnew (feature|function\w*|endpoint|tool|command|option|page|field|method|class|mode|setting)\b",
        r"\bimplement (a|an|new|support)\b", r"\bextend\b.*\b(with|to support)\b",
        r"\bhozzáad\w*\b", r"\bhozzá(adni|adnék|tenni|tennék)\b", r"\búj (funkci\w*|függvény\w*|végpont\w*|eszköz\w*|mező\w*|oldal\w*|képesség\w*|metódus\w*|osztály\w*)\b",
        r"\bbővít\w*\b", r"\bbeépít\w*\b", r"\bhogyan (implementáljam|valósítsam meg|adjak hozzá|tudnék hozzáadni|lehetne hozzáadni)\b",
        r"\bhova (tegyem|kell|érdemes|kerüljön|írjam)\b",
    ],
    "design_pattern": [
        r"\bdesign patterns?\b", r"\bpatterns?\b.*\b(use|apply|fit|simplif\w*|refactor\w*|suit\w*|recommend\w*)\b",
        r"\b(use|apply|recommend|suggest)\w*\b.*\bpatterns?\b", r"\brefactor\w*\b",
        r"\bsimplif\w*\b.*\b(code|class|function|method|component|module|logic|this)\b",
        r"\bbest way to (extend|structure|organi[sz]e|restructure)\b", r"\bextend (this|the|that) (component|class|module|service|subsystem)\b",
        r"\bintegrate\b.*\bwithout (rewriting|changing|modifying|touching)\b",
        r"\btoo many (if|ifs|switch|case|cases|conditions|conditionals)\b", r"\b(if[- ]else|switch) (chain|statement|block)s?\b",
        r"\btervezési mint\w*\b", r"\bmint(a|át|ák|ákat)\b.*\b(alkalmaz|használ|javasol)\w*", r"\brefaktor\w*\b",
        r"\begyszerűsít\w*\b", r"\bátszervez\w*\b", r"\bátír\w* nélkül\b",
    ],
}

RELATION_TOOLS = {"get_callers", "get_callees", "trace_dependencies", "find_call_path", "get_related_symbols", "find_type_usages"}
IMPACT_TOOLS = {"get_callers", "trace_dependencies", "find_type_usages"}
METRIC_TOOLS = {"get_code_metrics", "find_quality_hotspots", "get_module_quality_summary"}
ANALOG_TOOLS = {"find_similar_implementations", "semantic_code_search"}
EXTENSION_TOOLS = {"find_extension_points", "keyword_code_search"}
TEST_TOOLS = {"find_tests_for", "keyword_code_search"}
CHANGE_KINDS = {"analogous_feature", "extension_point", "test_conventions", "change_impact", "change_risk"}
PATTERN_TOOLS = {"detect_design_patterns", "find_pattern_opportunities", "recommend_design_patterns", "compare_change_strategies"}


@dataclass
class Requirement:
    kind: str
    target: str | None = None
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.target or '*'}"


@dataclass
class QuestionAnalysis:
    targets: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    metrics_focus: str = "general"
    metrics_scope: str = "none"
    requirements: list[Requirement] = field(default_factory=list)
    complexity: str = "simple"
    mentions_class: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "QuestionAnalysis":
        data = dict(data or {})
        data["requirements"] = [Requirement(**r) for r in data.get("requirements", [])]
        return QuestionAnalysis(**data)


def _clean(token: str) -> str | None:
    token = token.strip().strip(".:").removesuffix("()")
    if len(token) < 3 or token.lower() in STOPWORDS:
        return None
    parts = token.split(".")
    if len(parts) > 1 and any(len(p) <= 1 for p in parts):
        return None
    return token


def extract_targets(*texts: str) -> tuple[list[str], list[str]]:
    targets: list[str] = []
    files: list[str] = []

    def add(collection: list[str], value: str | None):
        if value and value not in collection:
            collection.append(value)

    for text in texts:
        if not text:
            continue
        for match in FILE_PATTERN.finditer(text):
            add(files, match.group(1).replace("\\", "/"))
        stripped = FILE_PATTERN.sub(" ", text)
        for pattern in (QUOTED_PATTERN, CALL_PATTERN, DOTTED_PATTERN, PASCAL_PATTERN, CAMEL_PATTERN, SNAKE_PATTERN):
            for match in pattern.finditer(stripped):
                add(targets, _clean(match.group(1)))

    deduped = [t for t in targets if not any(t != other and other.endswith("." + t) for other in targets)]
    return deduped, files


def detect_intents(*texts: str) -> list[str]:
    intents = []
    for intent, patterns in INTENT_PATTERNS.items():
        if any(re.search(p, (text or "").lower()) for text in texts for p in patterns):
            intents.append(intent)
    return intents


def analyze_question(question: str, question_en: str | None = None) -> QuestionAnalysis:
    english = question_en or question
    targets, files = extract_targets(english, question)
    intents = detect_intents(english, question)
    metrics = detect_metrics_intent(english)
    if not metrics.use_metrics and question != english:
        metrics = detect_metrics_intent(question)

    requirements: list[Requirement] = []

    def need(kind: str, target: str | None, description: str):
        requirement = Requirement(kind=kind, target=target, description=description)
        if requirement.key not in {r.key for r in requirements}:
            requirements.append(requirement)

    change = "change_planning" in intents
    pattern = "design_pattern" in intents

    for target in targets[:3]:
        need("symbol_resolved", target, f"locate the definition of {target}")

    if "comprehension" in intents or not intents or change or pattern:
        for target in targets[:2]:
            need("definition_code", target, f"read the implementation of {target}")

    if change:
        need("analogous_feature", None, "an existing feature similar to the requested change, to use as a template")
        need("extension_point", None, "where functionality of this kind is registered, routed or wired in")
        need("test_conventions", None, "tests covering the analogous code, whose conventions the change should follow")
        if targets:
            for target in targets[:2]:
                need("impact_relations", target, f"callers and dependents affected by changing {target}")
        else:
            need("change_impact", None, "code that depends on the files the change would touch")
        need("change_risk", None, "measured complexity of the files the change would touch")

    if "dependency" in intents and "impact" not in intents:
        for target in targets[:2] or [None]:
            need("dependency_relations", target, f"call/dependency relationships of {target or 'the relevant component'}")

    if "impact" in intents:
        for target in targets[:2] or [None]:
            need("impact_relations", target, f"callers and dependents affected by changing {target or 'the component'}")

    if "call_path" in intents and len(targets) >= 2:
        need("call_path", f"{targets[0]}->{targets[1]}", f"call chain from {targets[0]} to {targets[1]}")

    if metrics.use_metrics:
        if targets or files:
            need("metrics", None, f"measured {metrics.focus} metrics of the relevant code")
        else:
            need("hotspots", metrics.focus, f"repository-wide {metrics.focus} ranking from measured metrics")

    for path in files[:2]:
        need("file_context", path, f"content or structure of {path}")

    if change or pattern:
        need("pattern_analysis", None, "design pattern analysis: existing patterns, opportunities and minimal change versus pattern-based refactoring")

    if not targets and not files and not change and not pattern and not any(r.kind in ("hotspots",) for r in requirements):
        need("semantic_context", None, "relevant code located by semantic or keyword search")

    kinds = {r.kind for r in requirements}
    data_sources = sum([
        bool(kinds & {"symbol_resolved", "definition_code", "semantic_context", "file_context", "analogous_feature", "extension_point", "test_conventions"}),
        bool(kinds & {"dependency_relations", "impact_relations", "call_path", "change_impact"}),
        bool(kinds & {"metrics", "hotspots", "change_risk"}),
        bool(kinds & {"pattern_analysis"}),
    ])
    complexity = "simple" if data_sources <= 1 and len(requirements) <= 2 else "complex" if data_sources >= 3 or len(requirements) >= 5 else "moderate"

    return QuestionAnalysis(
        targets=targets[:5],
        files=files[:3],
        intents=intents,
        metrics_focus=metrics.focus,
        metrics_scope=metrics.scope,
        requirements=requirements,
        complexity=complexity,
        mentions_class=any(CLASS_PATTERN.search((text or "").lower()) for text in (english, question)),
    )
