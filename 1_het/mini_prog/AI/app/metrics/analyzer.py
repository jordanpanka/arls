"""Analyzer abstraction.

The rest of the application talks to these protocols only, so Lizard can be
replaced, or joined by e.g. a Semgrep or a language-specific analyzer, without
touching the router, the backend contract or the RAG workflow.
"""
from dataclasses import dataclass
from typing import Protocol

from app.metrics.models import GraphMetricsResult, StaticAnalysisResult


@dataclass
class SourceFile:
    path: str
    content: bytes


class StaticMetricsAnalyzer(Protocol):
    name: str

    def analyze(self, files: list[SourceFile]) -> StaticAnalysisResult: ...


class GraphMetricsAnalyzer(Protocol):
    name: str

    def analyze(self, user_id: int, investigation_id: int, project_id: int) -> GraphMetricsResult: ...
