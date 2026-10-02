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


class GraphEvidence(BaseModel):
    type: Literal["graph"] = "graph"
    id: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


Evidence = Annotated[CodeEvidence | GraphEvidence, Field(discriminator="type")]


class ChatResponse(BaseModel):
    answer: str
    evidence: list[Evidence] = Field(default_factory=list)
