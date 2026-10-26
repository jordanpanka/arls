# Adaptive evidence-aware agentic retrieval

The AI service answers repository questions with one of five retrieval strategies. The three
pipeline strategies reuse the original LangGraph workflow (`AI/app/services/rag_graph.py`); the two
agent strategies run a single LLM agent that selects tools (`AI/app/agents/graph.py`). A sixth mode,
`routed_rag`, picks between the pipeline and the agent for each question.

| Mode | Implementation |
|---|---|
| `routed_rag` | Chooses `adaptive_rag` or `evidence_aware_agentic_rag` per question. Default. Alias `auto`. |
| `vector_rag` | Original pipeline, graph, rerank and metrics forced off |
| `hybrid_rag` | Original pipeline, graph, rerank and metrics forced on |
| `adaptive_rag` | Original pipeline unchanged (question-type routing + regex metrics intent) |
| `agentic_rag` | Agent with iterative tool selection; no sufficiency check, no answer verification |
| `evidence_aware_agentic_rag` | Agent with sufficiency check, grounded generation and verification |

The mode comes from `ChatRequest.mode` (Python), `ChatRequest.mode` (RagApi), or `CHAT_DEFAULT_MODE`.
`ChatRequest.ablation` applies one of `full`, `no_sufficiency`, `no_graph`, `no_metrics`,
`no_iteration`, `no_verification`, `no_patterns` to an agent mode.

## Routing between pipeline and agent (`routed_rag`)

`AI/app/agents/router.py` runs the classifier prompt once (language, English translation, question
type), then derives the information requirements with `analyze_question` from
`AI/app/agents/requirements.py`, which uses no LLM. The first matching rule decides:

| Rule | Chosen mode | `route.reason` |
|---|---|---|
| change-planning intent or change requirements | agent | `change_planning_question` |
| design pattern intent or `pattern_analysis` requirement | agent | `design_pattern_question` |
| one function, direct callers/callees only, no class, file, impact or call path | `adaptive_rag` with `use_graph` forced | `graph_lookup_question` |
| dependency, impact, call path or change impact requirement | agent | `relationship_question` |
| a file is named (`file_context`) | agent | `file_question` |
| `complexity` is `complex` | agent | `complex_question` |
| `complexity` is `moderate` | `adaptive_rag` | `moderate_question` |
| otherwise | `adaptive_rag` | `simple_question` |

A `graph_lookup_question` is answered by the pipeline because its `search_knowledge_graph` node
already returns the direct callers and callees of every retrieved function; the agent would only add
LLM planning rounds. Class questions stay with the agent, since the pipeline's class subgraph holds
only members, not dependents.

The classification is passed on, so neither workflow calls the classifier again: `classify_question`
in the pipeline and `analyze_question` in the agent reuse it. Routing therefore adds no LLM call. If
the classifier fails, the question is routed from its original text with the fallback classification.

### Escalation

The router starts with the cheapest workflow that can plausibly answer, and `escalation_reason` in
`router.py` checks the pipeline result without an LLM call. The first failing check escalates the
question to `evidence_aware_agentic_rag`:

| Check | `route.escalationReason` |
|---|---|
| no retrieval hit passed the score filter | `no_retrieval_results` |
| the answer is empty or the not-found answer | `pipeline_not_found` |
| a named target is in no hit (by symbol name or code text) | `targets_not_retrieved` |
| metrics were required but none came back | `metrics_missing` |
| dependency relations were required, the graph was used, and no subgraph came back | `graph_relations_missing` |

The agent continues rather than restarting: the classification is reused, and the pipeline's top
hits are converted with `hit_to_evidence` and seeded into the evidence store in `init_context`
(`execution.seededEvidence`). `execution.route` then also has `escalatedTo`, `escalationReason`
and `pipelineMs`, and benchmark rows add `escalatedTo` and `escalationReason`. Set
`ROUTER_ESCALATION=false` to keep the pipeline answer as it is.

`execution.route` records `requested`, `chosen`, `reason`, `complexity`, `requirements`, `intents` and
`routingMs`, and `execution.strategy` is the mode that actually ran. The UI shows the reason as an
`auto: …` chip. In benchmark rows a routed run keeps `mode = routed_rag` and adds `routedTo`,
`routeReason` and `routingMs`. If a question has an `expected_route`, `routeCorrect` is added as
well. Ablations only affect routed runs that go to the agent.

## Agent workflow

```
init_context -> analyze_question -> plan_tools <-> execute_tools -> check_sufficiency
check_sufficiency --continue--> plan_tools
check_sufficiency --stop--> build_context -> generate_answer -> verify_answer
verify_answer --revise (bounded)--> generate_answer
verify_answer --done--> translate_answer -> finalize
plan_tools --no calls / budget reached--> build_context
```

- `init_context` resolves the repository snapshot (`commit:<sha>`, else `fs:<file-set hash>`, else
  `project:<id>`) from the RagApi internal source endpoint. Evidence from another snapshot is rejected.
- `analyze_question` reuses the original classifier prompt for language, English translation and type,
  then derives structured information requirements deterministically
  (`AI/app/agents/requirements.py`): `symbol_resolved`, `definition_code`, `dependency_relations`,
  `impact_relations`, `call_path`, `metrics`, `hotspots`, `file_context`, `semantic_context`.
  Feature requests ("how can I add…", "where should I put…", "új funkció", "hozzáadnám…") get the
  `change_planning` intent and the requirements `analogous_feature`, `extension_point`,
  `test_conventions`, `change_impact` (or `impact_relations` when a symbol is named) and `change_risk`.
- `plan_tools` asks the LLM for a JSON list of tool calls. Every call is validated against the tool's
  Pydantic schema; unknown tools, invalid arguments and repeated calls are dropped and counted. If the
  output cannot be parsed, a deterministic plan is built from the open requirements.
- `execute_tools` runs the calls concurrently with per-tool timeouts and stores normalized evidence.
- `check_sufficiency` (`AI/app/evidence/sufficiency.py`) evaluates each requirement
  (satisfied / missing / unavailable) and computes coverage, relevance, consistency and traceability
  against configurable thresholds. An optional LLM assessment can only add hints; it never marks
  evidence sufficient.
- `verify_answer` (`AI/app/evidence/verifier.py`) checks deterministically that cited ids exist and
  belong to the snapshot, cited paths and line ranges are inside collected evidence, `A calls B`
  claims exist as collected CALLS relations, numbers next to `METRIC_n` match measured values, and
  lines with repository identifiers carry a citation. Lines starting with `Proposed:` and lines under a
  `New code` / `Proposed` heading may name files and symbols that do not exist yet; their citations are
  still checked. Failures trigger at most
  `AGENT_MAX_VERIFY_REVISIONS` regenerations.

Budgets: iterations, tool calls, calls per iteration, tool output size, read lines, graph depth and
edges, context size, token budget, overall deadline, per-tool and per-LLM timeouts
(`AI/app/agents/config.py`, environment variables in `.env.example`).

## Tools

| Tool | Source | Notes |
|---|---|---|
| `semantic_code_search` | Qdrant (`search_vector`) | Returns the `code` payload for code chunks, not the summary |
| `keyword_code_search` | RagApi `source/search` | Literal or regex (200 ms match timeout), glob/extension filters |
| `find_symbol` | Neo4j code graph, Qdrant payload fallback | Stable `symbol_id = path::kind::Qualified.name@line`; ambiguous names list every match |
| `read_code` | RagApi `source/content` (MinIO) | Line-numbered, bounded; falls back to indexed chunks when the raw file is missing |
| `get_callers`, `get_callees` | Neo4j code graph | Depth 1-3; classes are explored through their methods |
| `trace_dependencies` | Neo4j code graph | File dependencies from cross-file calls and type usage (`viaCalls`, `viaTypes`); raw imports marked `inferred` |
| `find_call_path` | Neo4j code graph | Shortest resolved call chain, max 4 calls |
| `get_related_symbols` | Neo4j code graph | Enclosing class, members, base types, subtypes, typed fields, events, overridden and overriding methods, other symbols in the file |
| `find_type_usages` | Neo4j code graph | Everything depending on a class or interface: `INSTANTIATES`, `HAS_FIELD`, `TAKES`, `RETURNS`, `INHERITS`/`IMPLEMENTS`, plus calls to its methods; classes only |
| `get_code_metrics`, `find_quality_hotspots`, `get_module_quality_summary` | RagApi metrics evidence endpoint | Stored Lizard and graph metrics; analyzer recorded per value |
| `find_similar_implementations` | Qdrant + Neo4j code graph | Closest existing features to a requested one (tests excluded) and the neighbouring symbols in their files; works without the graph |
| `find_extension_points` | RagApi `source/search` | DI registrations, HTTP routes, routers, LangGraph nodes and registries; ranked by feature area and the folders of an analog |
| `find_tests_for` | RagApi `source/search` | Test files (`tests/`, `test_*`, `*.test.*`, `*Tests.cs`, …) referencing a symbol or file |
| `detect_design_patterns`, `find_pattern_opportunities`, `recommend_design_patterns`, `compare_change_strategies` | Tree-sitter on bounded source reads + code graph + stored metrics | Deterministic pattern detection and minimal-change vs. pattern-refactoring comparison; see `docs/design-pattern-analysis.md` |
| `get_file_history`, `get_code_churn`, `find_cochanged_files` | not available | Disabled by default; return a typed `unavailable` error because git history is not ingested |

The code graph is loaded with five fixed, parameterized, scope-filtered Cypher queries
(`Neo4jService.load_code_graph`) and cached per project and snapshot. Calls are resolved with the
same rules as the graph metrics: a located callee is `direct`, a unique short-name match is
`inferred`, anything else is listed as `unresolved` and never turned into an edge.

### Graph schema

| Node | Key |
|---|---|
| `File` | `path` |
| `Class` | `name`, `filePath`; `typeKind` (`class`, `abstract`, `interface`), `bases`, `events` |
| `Function` | `name`, `filePath`, `startLine`; `raises` (events it raises) |
| `Method` | `name`, `className`, `filePath` |
| `Module` | raw import text |
| `TypeRef` | type name as written in the source, resolved when the graph is loaded |

| Edge | Source |
|---|---|
| `File -[:CONTAINS]-> Class / Function`, `Class -[:CONTAINS]-> Method` | `CodeParser` |
| `Function -[:CALLS]-> Function` | `CodeParser`; callee by raw call text |
| `File -[:IMPORTS]-> Module` | `CodeParser` |
| `Class -[:INHERITS]-> TypeRef` | `type_relations` (`patterns/structure.py`) |
| `Class -[:HAS_FIELD {name, injected, collection}]-> TypeRef` | `type_relations`; element type for collections |
| `Function -[:INSTANTIATES / TAKES {name} / RETURNS]-> TypeRef` | `type_relations` |

Interfaces, records, structs and constructors get `Class` and `Function` nodes from `type_relations`,
also in languages whose `CodeParser` configuration only lists classes and methods. `startLine` is part
of the `Function` key, so methods with the same name in one file (a base method and its override)
are separate nodes. `TypeRef` targets are resolved like calls: a unique class of that name in the
same file is `direct`, a unique one elsewhere is `inferred`, anything else stays unresolved. An
`INHERITS` edge to an interface is reported as `IMPLEMENTS`. `OVERRIDES` is derived, not stored: a
method overrides the same-named method of the nearest resolved ancestor (up to three levels).
Repositories indexed before this change have no type edges until they are re-indexed;
`find_type_usages` says so in its summary.

## Evidence

`AI/app/evidence/schemas.py` defines one `Evidence` model for code chunks, code ranges, keyword
matches, symbols, graph nodes, graph relations, metrics and (future) history. Ids are
`<family>:<sha1 prefix>` of project, snapshot and location / relation / metric identity, so the same
fact found by two tools is stored once with both producers. The answer cites short aliases
(`SOURCE_n`, `GRAPH_n`, `METRIC_n`); `citations` in the response map each alias to stable evidence ids.
Evidence is projected onto the existing `code` / `graph` / `metric` viewer contract with optional
`evidenceIds`, `producedBy` and `certainty` fields.

## Change plans

For `change_planning` questions `generate_answer` uses `CHANGE_PLAN_PROMPT` instead of `ANSWER_PROMPT`.
The answer has fixed sections: Pattern to follow, Files to change, New code, Where to register it,
What could break, Risky areas, Tests. Existing code is cited as usual; new names are marked `Proposed:`.

## Response

`ChatResponse` keeps `answer` and `evidence` and adds optional `status`
(`verified`, `partially_verified`, `insufficient_evidence`, `unverified`), `citations`,
`rawEvidence` and `execution` (strategy, tool calls, iterations, tokens, cost, latency, stop reason,
sufficiency, verification and a sanitized tool trace). Pipeline modes return `execution` with
strategy and latency only. RagApi passes the new fields through unchanged.

## Traces and benchmarks

Every run appends one JSON line to `AI/eval/traces/traces-YYYYMMDD.jsonl` (`AGENT_TRACE_DIR`) with the
run id, experiment id, mode, ablation, snapshot, tool log, planner log, sufficiency and verification
history and the retrieved evidence list.

```
cd AI
python eval/run_benchmark.py --user-id 1 --investigation-id 1 --project-id 1 \
    --modes vector_rag,adaptive_rag,agentic_rag,evidence_aware_agentic_rag,routed_rag \
    --ablations full,no_sufficiency,no_graph,no_metrics,no_iteration --experiment-id exp1
```

`AI/eval/questions.json` holds the question set; `expected_files` and `expected_symbols` enable
evidence recall, precision, Recall@k and MRR (`AI/app/evaluation/metrics.py`). Outputs go to
`AI/eval/results/`.
