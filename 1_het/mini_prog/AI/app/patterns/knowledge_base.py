import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["confirmed", "likely", "possible"]
Category = Literal["behavioral", "creational", "structural", "architectural"]
ChangeKind = Literal[
    "new_variant", "extend", "refactor", "integration", "cross_cutting",
    "notification", "creation", "simplify_access", "data_access",
]

STATUS_ORDER: dict[str, int] = {"possible": 1, "likely": 2, "confirmed": 3}

SIGNALS: dict[str, str] = {
    "abstraction_with_implementations": "an interface, abstract class or protocol with at least two concrete implementations",
    "abstraction_single_implementation": "an abstraction with exactly one implementation",
    "context_holds_abstraction": "a class that does not implement an abstraction holds a field of it and delegates calls to it",
    "abstraction_injected": "an abstraction is passed into a constructor",
    "wrapper_same_interface": "a class implements an abstraction and wraps another instance of the same abstraction",
    "adapter_delegation": "a class implements an abstraction by delegating to a differently shaped collaborator",
    "creator_returns_abstraction": "a method declared to return an abstraction creates concrete implementations",
    "abstract_creator_overridden": "an abstract or virtual creation method returning an abstraction is overridden in subclasses",
    "subscriber_registration": "a method adds a received object to a collection field",
    "collection_notification": "a method iterates a collection field and calls a method on every element",
    "event_declared": "a class declares an event",
    "event_raised": "a class raises or emits an event",
    "facade_delegation": "a class whose methods mostly delegate to three or more collaborator types",
    "repository_interface": "a type exposing several collection-like data access operations",
    "data_access_dependency": "a type depends on a database or persistence API",
    "conditional_dispatch": "an if/else or switch chain selecting behaviour by comparing one value against three or more cases",
    "few_variants": "a conditional chain with only two cases",
    "many_variants": "a conditional chain with four or more cases",
    "type_dispatch": "a chain of type checks on the same value",
    "type_dependent_creation": "conditional branches that instantiate different concrete classes",
    "scattered_creation": "the same concrete class is instantiated in three or more places",
    "similar_variants": "classes without a shared abstraction that expose the same operations",
    "shared_call_sequence": "several clients call the same group of subsystem functions",
    "fan_out_hub": "a function calls into four or more different files",
    "repeated_receiver_notification": "a function calls the same method on three or more different objects",
    "subclass_override_chain": "three or more subclasses of a concrete class override the same method and call the base implementation",
    "high_complexity": "measured cyclomatic complexity in the high band",
    "long_function": "measured function length above the long-function threshold",
    "high_fan_in": "many callers in the code graph",
}


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all: list[str] = Field(min_length=1)
    boost: list[str] = Field(default_factory=list)
    status: Status
    partial_status: Status | None = None
    requires_change: list[ChangeKind] = Field(default_factory=list)
    explanation: str


class Detection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    existing: list[Rule] = Field(default_factory=list)
    opportunities: list[Rule] = Field(default_factory=list)
    avoid_signals: list[str] = Field(default_factory=list)


class Example(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str
    code: str


class Implementation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participants: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    new_abstractions: list[str] = Field(default_factory=list)


class PatternDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    category: Category
    intent: str
    use_cases: list[str] = Field(min_length=1)
    applicability: list[str] = Field(min_length=1)
    structural_indicators: list[str] = Field(min_length=1)
    code_smells: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(min_length=1)
    drawbacks: list[str] = Field(min_length=1)
    avoid_when: list[str] = Field(min_length=1)
    implementation: Implementation
    examples: list[Example] = Field(default_factory=list)
    confidence_notes: list[str] = Field(min_length=1)
    change_affinity: list[ChangeKind] = Field(min_length=1)
    max_status: Status = "confirmed"
    detection: Detection

    @model_validator(mode="after")
    def _signals_known(self):
        rules = self.detection.existing + self.detection.opportunities
        used = {s for r in rules for s in r.all + r.boost} | set(self.detection.avoid_signals)
        unknown = sorted(used - set(SIGNALS))
        if unknown:
            raise ValueError(f"pattern '{self.id}' uses unknown signals: {', '.join(unknown)}")
        return self


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    patterns: list[PatternDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self):
        ids = [p.id for p in self.patterns]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate pattern ids: {', '.join(duplicates)}")
        return self

    def get(self, pattern_id: str) -> PatternDefinition | None:
        return next((p for p in self.patterns if p.id == pattern_id), None)


DEFAULT_PATH = Path(__file__).parent / "knowledge" / "patterns.json"


def load_knowledge_base(path: Path | str | None = None) -> KnowledgeBase:
    with open(path or DEFAULT_PATH, encoding="utf-8") as handle:
        return KnowledgeBase.model_validate(json.load(handle))


@lru_cache(maxsize=1)
def default_knowledge_base() -> KnowledgeBase:
    return load_knowledge_base()
