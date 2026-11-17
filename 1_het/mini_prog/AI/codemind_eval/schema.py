import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from codemind_eval.evidence_ids import file_id, norm_path, symbol_id

AnnotationStatus = Literal["draft", "verified", "legacy"]


class Scope(BaseModel):
    user_id: int
    investigation_id: int
    project_id: int


class GoldEvidence(BaseModel):
    kind: Literal["file", "symbol"]
    path: str | None = None
    symbol: str | None = None
    lines: tuple[int, int] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def check(self):
        if self.kind == "file" and not norm_path(self.path):
            raise ValueError("file evidence needs a path")
        if self.kind == "symbol" and not (self.symbol or "").strip():
            raise ValueError("symbol evidence needs a symbol")
        return self

    @property
    def id(self) -> str:
        return file_id(self.path) if self.kind == "file" else symbol_id(self.path, self.symbol)


class Question(BaseModel):
    id: str
    question: str
    category: str = "uncategorized"
    reference_answer: str | None = None
    gold_evidence: list[GoldEvidence] = Field(default_factory=list)
    impact_files: list[str] = Field(default_factory=list)
    annotation_status: AnnotationStatus = "draft"
    expected_strategy: str | None = None
    expected_commit_sha: str | None = None
    scope: Scope | None = None
    notes: str | None = None

    @field_validator("reference_answer")
    @classmethod
    def blank_is_missing(cls, value: str | None) -> str | None:
        return value if value and value.strip() else None

    def gold_files(self) -> list[GoldEvidence]:
        return [g for g in self.gold_evidence if g.kind == "file"]

    def gold_symbols(self) -> list[GoldEvidence]:
        return [g for g in self.gold_evidence if g.kind == "symbol"]

    def gold_file_paths(self) -> list[str]:
        paths: list[str] = []
        for g in self.gold_evidence:
            path = norm_path(g.path)
            if path and path not in paths:
                paths.append(path)
        return paths


class Repository(BaseModel):
    id: str
    url: str | None = None
    commit_sha: str | None = None
    reference: str | None = None
    language: str | None = None


class Benchmark(BaseModel):
    name: str
    version: str = "1"
    description: str | None = None
    repository: Repository
    questions: list[Question]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [q.id for q in self.questions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate question ids: {', '.join(duplicates)}")
        return self

    def by_id(self) -> dict[str, Question]:
        return {q.id: q for q in self.questions}


class ImpactCase(BaseModel):
    id: str
    base_sha: str
    target_sha: str
    message: str
    question: str
    changed_files: list[str]
    annotation_status: AnnotationStatus = "draft"
    scope: Scope | None = None

    def to_question(self) -> Question:
        return Question(
            id=self.id,
            question=self.question,
            category="change_impact",
            impact_files=self.changed_files,
            gold_evidence=[GoldEvidence(kind="file", path=p) for p in self.changed_files],
            annotation_status=self.annotation_status,
            expected_commit_sha=self.base_sha,
            scope=self.scope,
            notes=f"{self.base_sha[:12]} -> {self.target_sha[:12]}: {self.message}",
        )


class ImpactSet(BaseModel):
    repository: Repository
    cases: list[ImpactCase] = Field(default_factory=list)


def file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _legacy_question(raw: dict) -> Question:
    gold = [GoldEvidence(kind="file", path=p) for p in raw.get("expected_files") or []]
    gold += [GoldEvidence(kind="symbol", symbol=s) for s in raw.get("expected_symbols") or []]
    return Question(
        id=raw["id"],
        question=raw["question"],
        category=raw.get("category") or "uncategorized",
        reference_answer=raw.get("ground_truth"),
        gold_evidence=gold,
        annotation_status="legacy",
        expected_strategy=raw.get("expected_route"),
    )


def parse_benchmark(data: dict, name: str = "benchmark") -> Benchmark:
    if "repository" in data:
        return Benchmark.model_validate(data)
    questions = data.get("questions")
    if not isinstance(questions, list):
        raise ValueError("benchmark must contain a 'questions' list")
    return Benchmark(
        name=name,
        description=data.get("description"),
        repository=Repository(id=data.get("repository_id") or "codemind"),
        questions=[_legacy_question(q) for q in questions],
    )


def load_benchmark(path: str | Path) -> Benchmark:
    path = Path(path)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return parse_benchmark(data, name=path.stem)


def load_impact_set(path: str | Path) -> ImpactSet:
    with open(path, encoding="utf-8") as handle:
        return ImpactSet.model_validate(json.load(handle))


def impact_benchmark(impact: ImpactSet, name: str = "change-impact") -> Benchmark:
    return Benchmark(name=name, repository=impact.repository, questions=[c.to_question() for c in impact.cases])
