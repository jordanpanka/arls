import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from app.services.evidence_service import normalize_path

SourceType = Literal[
    "code_chunk",
    "code_range",
    "keyword_match",
    "symbol",
    "graph_relation",
    "graph_node",
    "metric",
    "history",
]
Certainty = Literal["direct", "inferred", "unresolved"]

CODE_TYPES = {"code_chunk", "code_range", "keyword_match"}
GRAPH_TYPES = {"graph_relation", "graph_node"}

ID_FAMILY = {
    "code_chunk": "code",
    "code_range": "code",
    "keyword_match": "code",
    "symbol": "sym",
    "graph_relation": "rel",
    "graph_node": "node",
    "metric": "metric",
    "history": "hist",
}

ALIAS_PREFIX = {
    "code": "SOURCE",
    "sym": "SOURCE",
    "rel": "GRAPH",
    "node": "GRAPH",
    "metric": "METRIC",
    "hist": "HISTORY",
}


class GraphRelation(BaseModel):
    source: str
    target: str
    type: str
    source_label: str
    target_label: str
    source_path: str | None = None
    target_path: str | None = None
    source_line: int | None = None
    target_line: int | None = None
    depth: int = 1


class MetricValue(BaseModel):
    key: str
    label: str
    value: float | int | None = None
    unit: str | None = None
    category: str | None = None
    analyzer: str = "lizard"


class MetricMeasurement(BaseModel):
    scope: Literal["repository", "file", "function"]
    title: str
    symbol: str | None = None
    items: list[MetricValue] = Field(default_factory=list)
    analysis_id: int | None = None
    analyzed_at: str | None = None
    commit_sha: str | None = None

    @property
    def analyzers(self) -> list[str]:
        return sorted({item.analyzer for item in self.items})


class Evidence(BaseModel):
    evidence_id: str = ""
    source_type: SourceType
    repository_snapshot: str = ""
    project_id: int | None = None

    file_path: str | None = None
    symbol_id: str | None = None
    symbol_name: str | None = None
    symbol_kind: str | None = None

    start_line: int | None = None
    end_line: int | None = None

    content: str | None = None
    language: str | None = None

    retrieval_score: float | None = None
    produced_by: list[str] = Field(default_factory=list)
    certainty: Certainty = "direct"

    relation: GraphRelation | None = None
    metric: MetricMeasurement | None = None

    group: str | None = None
    metadata: dict = Field(default_factory=dict)

    @property
    def family(self) -> str:
        return ID_FAMILY[self.source_type]

    @property
    def has_location(self) -> bool:
        return bool(self.file_path) and self.start_line is not None


def _identity_key(evidence: Evidence) -> dict:
    family = evidence.family
    key: dict = {
        "family": family,
        "project": evidence.project_id,
        "snapshot": evidence.repository_snapshot,
    }
    if family in ("code", "sym"):
        key.update(
            path=normalize_path(evidence.file_path),
            start=evidence.start_line,
            end=evidence.end_line,
        )
        if family == "sym":
            key["symbol"] = evidence.symbol_id
    elif family == "rel" and evidence.relation is not None:
        key.update(
            source=evidence.relation.source,
            target=evidence.relation.target,
            type=evidence.relation.type,
        )
    elif family == "node":
        key.update(symbol=evidence.symbol_id, path=normalize_path(evidence.file_path))
    elif family == "metric" and evidence.metric is not None:
        key.update(
            scope=evidence.metric.scope,
            path=normalize_path(evidence.file_path),
            symbol=evidence.metric.symbol,
            start=evidence.start_line,
            analysis=evidence.metric.analysis_id,
        )
    else:
        key.update(path=normalize_path(evidence.file_path), meta=evidence.metadata.get("key"))
    return key


def make_evidence_id(evidence: Evidence) -> str:
    raw = json.dumps(_identity_key(evidence), sort_keys=True, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{evidence.family}:{digest}"


def with_identity(evidence: Evidence) -> Evidence:
    normalized = normalize_path(evidence.file_path) or None
    updated = evidence.model_copy(update={"file_path": normalized})
    return updated.model_copy(update={"evidence_id": make_evidence_id(updated)})
