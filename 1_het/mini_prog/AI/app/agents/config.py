import os
from dataclasses import asdict, dataclass, field, fields, replace


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class SufficiencyThresholds:
    min_coverage: float = 1.0
    min_relevance: float = 0.5
    min_traceability: float = 0.6
    min_semantic_score: float = 0.35
    use_llm: bool = False


@dataclass(frozen=True)
class AgentConfig:
    max_iterations: int = 4
    max_tool_calls: int = 12
    max_calls_per_iteration: int = 4
    max_tool_output_chars: int = 6000
    max_read_lines: int = 200
    max_graph_depth: int = 3
    max_graph_edges: int = 40
    max_context_chars: int = 24000
    max_evidence_items: int = 80
    max_response_evidence: int = 30
    token_budget: int = 60000
    timeout_s: float = 180.0
    tool_timeout_s: float = 20.0
    llm_timeout_s: float = 120.0
    max_verify_revisions: int = 1
    price_in_per_1k: float = 0.0
    price_out_per_1k: float = 0.0
    enable_sufficiency: bool = True
    enable_graph_tools: bool = True
    enable_metrics_tools: bool = True
    enable_iteration: bool = True
    enable_verification: bool = True
    enable_history_tools: bool = False
    enable_pattern_analysis: bool = True
    pattern_max_files: int = 10
    pattern_max_file_lines: int = 1600
    pattern_max_runs: int = 2
    pattern_max_evidence: int = 24
    llm_claim_verification: bool = False
    sufficiency: SufficiencyThresholds = field(default_factory=SufficiencyThresholds)

    @property
    def effective_max_iterations(self) -> int:
        return self.max_iterations if self.enable_iteration else 1

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict | None) -> "AgentConfig":
        if not data:
            return AgentConfig()
        known = {f.name for f in fields(AgentConfig)}
        values = {k: v for k, v in data.items() if k in known and k != "sufficiency"}
        sufficiency = SufficiencyThresholds(**(data.get("sufficiency") or {}))
        return AgentConfig(**values, sufficiency=sufficiency)

    @staticmethod
    def from_env() -> "AgentConfig":
        return AgentConfig(
            max_iterations=_int("AGENT_MAX_ITERATIONS", 4),
            max_tool_calls=_int("AGENT_MAX_TOOL_CALLS", 12),
            max_calls_per_iteration=_int("AGENT_MAX_CALLS_PER_ITERATION", 4),
            max_tool_output_chars=_int("AGENT_MAX_TOOL_OUTPUT_CHARS", 6000),
            max_read_lines=_int("AGENT_MAX_READ_LINES", 200),
            max_graph_depth=_int("AGENT_MAX_GRAPH_DEPTH", 3),
            max_graph_edges=_int("AGENT_MAX_GRAPH_EDGES", 40),
            max_context_chars=_int("AGENT_MAX_CONTEXT_CHARS", 24000),
            max_evidence_items=_int("AGENT_MAX_EVIDENCE_ITEMS", 80),
            max_response_evidence=_int("AGENT_MAX_RESPONSE_EVIDENCE", 30),
            token_budget=_int("AGENT_TOKEN_BUDGET", 60000),
            timeout_s=_float("AGENT_TIMEOUT_S", 180.0),
            tool_timeout_s=_float("AGENT_TOOL_TIMEOUT_S", 20.0),
            llm_timeout_s=_float("AGENT_LLM_TIMEOUT_S", 120.0),
            max_verify_revisions=_int("AGENT_MAX_VERIFY_REVISIONS", 1),
            price_in_per_1k=_float("LLM_PRICE_IN_PER_1K", 0.0),
            price_out_per_1k=_float("LLM_PRICE_OUT_PER_1K", 0.0),
            enable_history_tools=_bool("AGENT_ENABLE_HISTORY_TOOLS", False),
            enable_pattern_analysis=_bool("ENABLE_DESIGN_PATTERN_ANALYSIS", True),
            pattern_max_files=_int("PATTERN_MAX_FILES", 10),
            pattern_max_file_lines=_int("PATTERN_MAX_FILE_LINES", 1600),
            pattern_max_runs=_int("PATTERN_MAX_RUNS", 2),
            pattern_max_evidence=_int("PATTERN_MAX_EVIDENCE", 24),
            llm_claim_verification=_bool("AGENT_LLM_CLAIM_VERIFICATION", False),
            sufficiency=SufficiencyThresholds(
                min_coverage=_float("SUFF_MIN_COVERAGE", 1.0),
                min_relevance=_float("SUFF_MIN_RELEVANCE", 0.5),
                min_traceability=_float("SUFF_MIN_TRACEABILITY", 0.6),
                min_semantic_score=_float("SUFF_MIN_SEMANTIC_SCORE", 0.35),
                use_llm=_bool("SUFF_USE_LLM", False),
            ),
        )


AGENT_MODES = ("agentic_rag", "evidence_aware_agentic_rag")

MODE_PRESETS: dict[str, dict] = {
    "agentic_rag": {"enable_sufficiency": False, "enable_verification": False},
    "evidence_aware_agentic_rag": {},
}

ABLATIONS: dict[str, dict] = {
    "full": {},
    "no_sufficiency": {"enable_sufficiency": False},
    "no_graph": {"enable_graph_tools": False},
    "no_metrics": {"enable_metrics_tools": False},
    "no_iteration": {"enable_iteration": False},
    "no_verification": {"enable_verification": False},
    "no_patterns": {"enable_pattern_analysis": False},
}


class UnknownAblationError(ValueError):
    pass


def config_for(mode: str, ablation: str | None = None, base: AgentConfig | None = None) -> AgentConfig:
    config = base or AgentConfig.from_env()
    config = replace(config, **MODE_PRESETS.get(mode, {}))
    if ablation:
        if ablation not in ABLATIONS:
            raise UnknownAblationError(f"Unknown ablation '{ablation}'. Known: {', '.join(ABLATIONS)}")
        config = replace(config, **ABLATIONS[ablation])
    return config
