"""Analyzer-agnostic metric models.

These are the only shapes that leave the metrics package: the .NET backend
persists them and nothing downstream needs to know which tool produced a value.
"""
from pydantic import BaseModel, Field


class FunctionMetrics(BaseModel):
    name: str
    longName: str
    className: str | None = None
    startLine: int
    endLine: int
    nloc: int
    cyclomaticComplexity: int
    tokenCount: int
    parameterCount: int
    # Physical lines from start to end, comments and blanks included.
    length: int


class FileMetrics(BaseModel):
    path: str
    language: str
    nloc: int
    tokenCount: int
    # Tree-sitter class-like declarations; None when the language has no grammar configured.
    classCount: int | None = None
    functions: list[FunctionMetrics] = Field(default_factory=list)


class SkippedFile(BaseModel):
    path: str
    reason: str


class StaticAnalysisResult(BaseModel):
    analyzer: str
    files: list[FileMetrics] = Field(default_factory=list)
    skipped: list[SkippedFile] = Field(default_factory=list)
    durationMs: float = 0


class FileGraphMetrics(BaseModel):
    path: str
    fanIn: int
    fanOut: int
    importCount: int


class FunctionGraphMetrics(BaseModel):
    path: str
    name: str
    startLine: int | None = None
    fanIn: int
    fanOut: int
    unresolvedCalls: int


class GraphMetricsResult(BaseModel):
    analyzer: str
    files: list[FileGraphMetrics] = Field(default_factory=list)
    functions: list[FunctionGraphMetrics] = Field(default_factory=list)
    # Distinct file -> file dependencies (resolved CALLS between different files).
    dependencyCount: int = 0
    cycleCount: int = 0
    # Largest cycles first, capped; cycleCount is always the full number.
    cycles: list[list[str]] = Field(default_factory=list)
    maxDependencyDepth: int = 0
    ambiguousCalls: int = 0
    unresolvedCalls: int = 0
    durationMs: float = 0


class GraphMetricsRequest(BaseModel):
    userId: int
    investigationId: int
    projectId: int
