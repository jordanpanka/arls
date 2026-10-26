from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]
Basis = Literal["measured", "planned", "qualitative"]
EvidenceSource = Literal["ast", "graph", "metrics", "vector"]


class EvidenceRef(BaseModel):
    id: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    symbol: str | None = None
    source: EvidenceSource
    role: str
    why: str
    alias: str | None = None


class PatternFinding(BaseModel):
    pattern: str
    name: str
    kind: Literal["existing", "opportunity"]
    status: Literal["confirmed", "likely", "possible"]
    subject: str
    explanation: str
    signals: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    boosted_by: list[str] = Field(default_factory=list)
    counter_indications: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class PatternRecommendation(BaseModel):
    pattern: str
    name: str
    category: str
    mode: Literal["extend_existing", "introduce"]
    confidence: Confidence
    reason: str
    subject: str
    evidence_ids: list[str] = Field(default_factory=list)
    architectural_changes: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ConsideredPattern(BaseModel):
    pattern: str
    name: str
    reason: str


class Alternative(BaseModel):
    kind: Literal["minimal_change", "pattern_refactoring"]
    summary: str
    changes: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    new_elements: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    disadvantages: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    technical_debt: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class Alternatives(BaseModel):
    minimal_change: Alternative | None = None
    pattern_refactoring: Alternative | None = None


class ComparisonRow(BaseModel):
    dimension: str
    minimal_change: str
    pattern_refactoring: str
    basis: Basis


class AnalysisScope(BaseModel):
    files: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    selection: str = "requested"


class Diagnostics(BaseModel):
    operations: list[str] = Field(default_factory=list)
    patterns_considered: list[str] = Field(default_factory=list)
    patterns_detected: list[str] = Field(default_factory=list)
    patterns_recommended: list[str] = Field(default_factory=list)
    signal_counts: dict[str, int] = Field(default_factory=dict)
    evidence_sources: dict[str, int] = Field(default_factory=dict)
    files_parsed: int = 0
    source_reads: int = 0
    keyword_searches: int = 0
    graph_used: bool = False
    metrics_used: bool = False
    llm_calls: int = 0
    latency_ms: float = 0.0


class PatternAnalysis(BaseModel):
    analysis_type: Literal["change_recommendation", "pattern_detection", "opportunity_detection"]
    change_request: str | None = None
    change_kinds: list[str] = Field(default_factory=list)
    scope: AnalysisScope = Field(default_factory=AnalysisScope)
    existing_patterns: list[PatternFinding] = Field(default_factory=list)
    detected_opportunities: list[PatternFinding] = Field(default_factory=list)
    recommended_patterns: list[PatternRecommendation] = Field(default_factory=list)
    considered_patterns: list[ConsideredPattern] = Field(default_factory=list)
    no_pattern_needed: bool = False
    alternatives: Alternatives = Field(default_factory=Alternatives)
    comparison: list[ComparisonRow] = Field(default_factory=list)
    preferred_alternative: Literal["minimal_change", "pattern_refactoring"] | None = None
    justification: str = ""
    evidence: list[EvidenceRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)
