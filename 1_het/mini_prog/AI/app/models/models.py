from pydantic import BaseModel, Field
from dataclasses import dataclass
from typing import Annotated, Any, Literal


@dataclass
class ServiceResult:
    is_success: bool
    message: str | None = None
    data: Any = None

    @staticmethod
    def success(data: Any = None) -> "ServiceResult":
        return ServiceResult(is_success=True, data=data)

    @staticmethod
    def fail(message: str) -> "ServiceResult":
        return ServiceResult(is_success=False, message=message)


class Ids(BaseModel):
    inv_id: int
    project_id: int

class ChatRequest(BaseModel):
    prompt: str
    userId:int
    investigationId:int
    projectId:int
    mode: str | None = None
    ablation: str | None = None
    experimentId: str | None = None


class Highlight(BaseModel):
    startLine: int
    endLine: int


class CodeEvidence(BaseModel):
    type: Literal["code"] = "code"
    id: str
    # A backend (C#) tolti ki: a Python csak az utvonalat ismeri, az MSSQL file ID-t nem.
    fileId: str | None = None
    fileName: str
    filePath: str
    language: str
    highlights: list[Highlight] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    retrievalType: str | None = None
    score: float | None = None
    evidenceIds: list[str] | None = None
    producedBy: list[str] | None = None
    certainty: str | None = None


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    fileId: str | None = None
    filePath: str | None = None
    startLine: int | None = None
    endLine: int | None = None
    usedAsEvidence: bool = False


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    certainty: str | None = None


class GraphEvidence(BaseModel):
    type: Literal["graph"] = "graph"
    id: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    evidenceIds: list[str] | None = None
    producedBy: list[str] | None = None


class MetricItem(BaseModel):
    key: str
    label: str
    value: float | int | None = None
    unit: str | None = None
    category: str | None = None


class MetricEvidence(BaseModel):
    """Measured values from a stored metrics analysis, never estimated by the LLM."""
    type: Literal["metric"] = "metric"
    id: str
    scope: Literal["repository", "file", "function"]
    title: str
    fileId: str | None = None
    fileName: str | None = None
    filePath: str | None = None
    symbol: str | None = None
    startLine: int | None = None
    endLine: int | None = None
    analysisId: int | None = None
    analyzedAt: str | None = None
    commitSha: str | None = None
    items: list[MetricItem] = Field(default_factory=list)
    evidenceIds: list[str] | None = None
    producedBy: list[str] | None = None


Evidence = Annotated[CodeEvidence | GraphEvidence | MetricEvidence, Field(discriminator="type")]


class Citation(BaseModel):
    alias: str
    type: str
    evidenceIds: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    evidence: list[Evidence] = Field(default_factory=list)
    status: str | None = None
    citations: list[Citation] | None = None
    rawEvidence: list[dict] | None = None
    execution: dict | None = None
    patternAnalysis: dict | None = None
