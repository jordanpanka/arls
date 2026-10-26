import operator
from typing import Annotated, TypedDict

from app.evidence.store import merge_evidence_maps


class AgentState(TypedDict, total=False):
    run_id: str
    experiment_id: str | None
    mode: str
    ablation: str | None
    config: dict

    user_id: int
    investigation_id: int
    project_id: int
    repository_snapshot: str
    snapshot_source: str

    question: str
    question_en: str
    language: str
    language_name: str
    question_type: str
    classification: dict
    route: dict
    analysis: dict
    complexity: str

    pending_calls: list[dict]
    planner_done: bool
    planner_log: Annotated[list[dict], operator.add]
    iteration: int
    tool_calls: int
    call_signatures: list[str]
    tool_log: Annotated[list[dict], operator.add]

    seed_hits: list[dict]
    seeded_evidence: int
    evidence: Annotated[dict, merge_evidence_maps]
    aliases: dict
    new_evidence_count: int
    rejected_evidence: Annotated[list[dict], operator.add]

    sufficiency: dict
    sufficiency_history: Annotated[list[dict], operator.add]
    evidence_sufficient: bool
    missing_information: list[str]

    llm_calls: Annotated[int, operator.add]
    input_tokens: Annotated[int, operator.add]
    output_tokens: Annotated[int, operator.add]
    retrieval_time_ms: Annotated[float, operator.add]
    generation_time_ms: Annotated[float, operator.add]
    started_at: float
    deadline: float

    context: str
    open_gaps: list[str]
    answer_en: str
    answer: str
    cited_aliases: list[str]
    verification_result: dict | None
    verification_history: Annotated[list[dict], operator.add]
    revise: bool
    revisions: int

    pattern_analysis: dict
    pattern_operations: Annotated[list[str], operator.add]

    status: str
    stop_reason: str
    execution: dict
