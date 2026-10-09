# Code Metrics

Code Mind measures every analyzed repository with two analyzers. It stores the results as analysis runs in MSSQL. The same stored numbers feed three consumers: the Code Metrics dashboard, the API, and the question-answering workflow, where they are a third evidence type next to source code and knowledge-graph evidence.

```
GitHub import finished / "Analyze Repository"
        │
        ▼
RagApi  MetricsAnalysisQueue ─► MetricsAnalysisWorker ─► MetricsAnalysisService
        │ reads code files from MinIO (missing file → skipped)
        ├─► AI  POST /api/metrics/static   Lizard (+ Tree-sitter class count)
        ├─► AI  POST /api/metrics/graph    Neo4j knowledge graph
        ▼
MetricsAggregator (thresholds, categories, aggregates) ─► MSSQL
        │
        ▼
MetricsService ─► /api/projects/{id}/metrics/...          dashboard
               └► /api/internal/projects/{id}/metrics/evidence  ◄─ RAG (retrieve_metrics)
```

MSSQL is the single source of truth. The Python analyzers are stateless and return analyzer-independent JSON (`AI/app/metrics/models.py`). Thresholds and categories are applied only on the .NET side.

## Static metrics: Lizard

Lizard (`lizard==1.24.0`) is called through its Python API, `lizard.analyze_file.analyze_source_code(path, code)`. Its console output is never parsed. The adapter is `AI/app/metrics/lizard_analyzer.py`. It implements the `StaticMetricsAnalyzer` protocol (`AI/app/metrics/analyzer.py`), so another analyzer can replace or join it without changing the API contract.

| Level | Metric | Source |
|---|---|---|
| Function | name, long name (signature), start/end line | Lizard |
| Function | cyclomatic complexity (CCN) | Lizard |
| Function | NLOC, token count, parameter count | Lizard |
| Function | length (physical lines, start to end) | Lizard |
| Function | class name | Tree-sitter class ranges (innermost class containing the function); falls back to Lizard's `Class::method` qualifier |
| File | NLOC, token count | Lizard |
| File | class-like declarations | Tree-sitter, using the node types configured in `CodeParser.code_parsers` (e.g. Rust structs, enums, traits and impls; C/C++ structs) |
| File / repository | everything else | aggregated on the .NET side, see below |

**Cyclomatic complexity.** Lizard computes McCabe complexity: 1 plus one for each decision point (`if`, `for`, `while`, `case`, `catch`, `&&`, `||`, `?:`; the exact set depends on the language reader).

**Parameter count** follows Lizard. Python's `self` and `cls` are counted as parameters.

### Supported languages

There is one definition of "code" per service:
- **Python service:** the Tree-sitter grammars in `CodeParser.code_parsers`. `FileService.code_sources` is derived from it.
- **.NET service:** `SourceLanguage.CodeExtensions`. `GitHubService` uses it.

Both list `.py .cs .js .jsx .ts .tsx .java .go .rs .php .c .h .cpp .hpp`. Lizard has a reader for each of these, and a test checks it (`test_code_extensions_are_in_sync_across_ingest_tree_sitter_and_lizard`). If the two sides ever diverge, the AI service reports the file as skipped; it never fails.

Paths that the ingest ignores (`node_modules`, `bin`, `dist`, …) are skipped with the reason `ignored_path`. Metrics therefore cover the same files as the index and the graph.

### Skipped files

Each run records every skipped file with a reason:

| Reason | Meaning |
|---|---|
| `missing_in_storage` | The original file is no longer in MinIO. |
| `unsupported_language` | Lizard cannot read this file type. |
| `ignored_path` | The ingest ignores this path. |
| `empty` | The file has no content. |
| `analyzer_error` | Lizard raised an exception on this file. |

## Aggregation

All aggregation happens in `RagApi/Services/MetricsAggregator.cs`.

**File level**
- Average complexity is the mean CCN of the file's functions; it is null when the file has no functions.
- Maximum complexity is the largest CCN in the file.
- The file also stores counts of high-complexity, long and many-parameter functions, and the average and maximum function NLOC.

**Repository level**
- **Totals:** NLOC and file counts are sums over analyzed files. The function total is the number of functions.
- **Class-like declarations:** the sum over files where Tree-sitter could count them; null when no file had a grammar.
- **Average complexity:** the mean over all functions in the repository, not the mean of the file averages.
- **Maximum complexity:** the largest CCN of any function.
- **Indicator counts:** functions above the respective thresholds.
- **Fan-in / fan-out:** the average and maximum over files that have graph values.

## Thresholds

The thresholds live in one place: `appsettings.json` → `Metrics:Thresholds`, bound to `MetricsThresholds`.

| Setting | Default | Meaning |
|---|---|---|
| `LowMax` | 5 | CCN 1–5 → Low |
| `ModerateMax` | 10 | CCN 6–10 → Moderate |
| `HighMax` | 20 | CCN 11–20 → High; above → VeryHigh |
| `LongFunctionNloc` | 50 | a function with more NLOC is "long" |
| `ManyParameters` | 5 | a function with more parameters has "many parameters" |

A **high-complexity function** is one with CCN above `ModerateMax`, i.e. in the High or VeryHigh band.

Each run stores the thresholds it used (`ThresholdsJson`), so its categories stay reproducible after the configuration changes. A configuration change also makes the next non-forced analysis run again instead of reusing the stored result.

The categories are **indicators** for ranking and attention, not a verdict on code quality. The UI and the LLM prompt both say so.

## Graph metrics: Neo4j

`AI/app/metrics/graph_metrics.py` reuses the knowledge graph the ingest already builds. Nothing is re-parsed. The analyzer makes three Cypher reads per project:
- located `Function` nodes;
- `CALLS` edges;
- `File` nodes with their `IMPORTS` count.

All metrics are then computed by pure functions, which are unit-tested on a known graph.

**Relationship types**
- **`CALLS`** is the only edge that counts as a dependency.
- **`CONTAINS`** (file → class/function, class → method) is structural and is never a dependency.
- **`IMPORTS`** points at raw import text, which is often an external package. It is reported separately as `importCount` and never mixed into fan-in/fan-out.

**Resolving call targets.** The ingest stores a callee by its raw call text (`self.helper`), usually without a file path. A target is resolved by the same rule the evidence graph uses (`Neo4jService._resolve_call_targets`):
- A callee that is already a located definition is used directly.
- Otherwise, its short name (after the last `.`, `::` or `->`) must match **exactly one** located `Function` in the project.
- Ambiguous names are excluded and counted as `ambiguousCalls`.
- Names with no match (library calls) are counted as `unresolvedCalls`.

| Metric | Definition |
|---|---|
| function fan-out | distinct resolved project functions it calls (self-calls excluded) |
| function fan-in | distinct project functions that call it (self-calls excluded) |
| file fan-out | distinct other project files whose functions this file's functions call |
| file fan-in | distinct other project files whose functions call into this file |
| dependency count | distinct file → file edges |
| cycles | strongly connected components of the file graph with more than one file (iterative Tarjan); at most 20 are listed, the count is complete |
| max dependency depth | longest path, in edges, of the file graph after collapsing each cycle into one node |

Graph values are merged into the static results:
- files by normalized path;
- functions by path and short name.

If a file has no graph node, its fan-in and fan-out stay `null`; they are never set to 0.

## Persistence

The migration `RagApi/Migrations/*_AddCodeMetrics.cs` creates three tables:

- **`MetricsAnalysis`**: one row per run.
  - Links: `ProjectID` with cascade delete; `RepositoryID` as a plain column.
  - Status and phase statuses (static, graph), error message, trigger (Manual or Import).
  - Branch, commit SHA, and a hash of the code file set.
  - Timestamps; total, static and graph durations; files analyzed and skipped, with skip reasons.
  - All repository aggregates, the cycle list, and the thresholds used.
- **`FileMetric`**: one row per analyzed file, indexed on `(AnalysisID, Path)`. `FileID` is resolved from `File.RelativePath` but is not a foreign key, so deleting a file never touches past runs.
- **`FunctionMetric`**: one row per function.

Runs are kept, not overwritten, so later work can compare commits. The dashboard and RAG always read the latest **usable** run, meaning status Completed or Partial.

## Running an analysis

**Automatic.** After a GitHub import reaches `Ready`, `RepositoryIngestService` queues an analysis when `Metrics:AutoAnalyzeAfterImport` is true. A failure here is logged and never fails the import.

**Manual.** The dashboard's *Analyze Repository* / *Re-analyze* button calls `POST /api/projects/{id}/metrics/analyze`.

**Reuse.**
- If a run is already in flight, it is returned instead of starting another.
- Without `force`, if the latest usable run has the same code file set (path and size), the same commit and the same thresholds, that run is reused.

**Partial failures.**
- If the static phase fails, the run is `Failed` and no metrics are stored.
- If only the graph phase fails (for example, Neo4j is down), the static metrics are stored and the run is `Partial`.
- Qdrant and Neo4j ingest data are never modified.
- On backend restart, interrupted runs are marked `Failed`.

**Performance logging.** Each run logs, and stores, the total duration, the Lizard (static) duration, the graph duration, and the number of files analyzed and skipped. The AI service also logs the time of each phase.

## API

All routes require a JWT and the user must own the project. A forbidden project returns 403; a missing analysis returns 404 with `{ "error": "no_analysis" }`.

| Method | Route |
|---|---|
| POST | `/api/projects/{projectId}/metrics/analyze` (body `{ "force": bool }`) → 202 `{ analysisId, status, reused }` |
| GET | `/api/projects/{projectId}/metrics/status` |
| GET | `/api/projects/{projectId}/metrics` (summary, distribution, thresholds, skipped files) |
| GET | `/api/projects/{projectId}/metrics/files?sort=&desc=&limit=` |
| GET | `/api/projects/{projectId}/metrics/files/detail?path=` |
| GET | `/api/projects/{projectId}/metrics/functions?path=&sort=&limit=` |
| GET | `/api/projects/{projectId}/metrics/hotspots/{complexity\|dependencies\|maintainability}?limit=` |
| POST | `/api/internal/projects/{projectId}/metrics/evidence`: AI service only, `X-Internal-Key` header |

**Hotspot rankings**

| Kind | Files ranked by | Functions ranked by |
|---|---|---|
| complexity | max CCN, then average CCN | CCN |
| dependencies | fan-in + fan-out | fan-in + fan-out |
| maintainability | number of indicators (high CCN + long + many parameters), then max CCN and NLOC | NLOC |

## Metrics in question answering

**1. Deciding whether metrics are needed.** `search_plan` calls `detect_metrics_intent` (`AI/app/metrics/intent.py`), a small rule-based detector. It is isolated so a future adaptive router can replace it. It sets three state fields:
- `use_metrics`
- `metrics_scope`: `entity` or `repository`
- `metrics_focus`: complexity, maintainability, dependency, size or general

Examples:
- *"What does getUserName() return?"*: metrics are not used.
- *"Why is UserService difficult to maintain?"*: entity scope.
- *"Which files are the most complex?"*: repository scope (ranking phrasing).

**2. `retrieve_metrics`.** This new LangGraph node runs after retrieval (vector search, graph search, rerank) and before `prepare_evidence`. It does nothing unless `use_metrics` is set.
- It asks the backend only for the files and functions that retrieval already found, plus the roots of the graph subgraphs.
- For repository scope, it also asks for the repository summary and the top hotspots for the detected focus. Such questions therefore work even when vector search finds nothing.
- The workflow depends on the `MetricsProvider` protocol only. The default implementation calls the backend's internal endpoint, so RAG and the dashboard see the same stored numbers.
- When metrics are unavailable, the answer proceeds without them.

**3. Context.** `prepare_evidence` turns the payload into `METRIC_n` evidence. `build_context` then appends a `===== CODE METRICS (measured, not estimated) =====` section after the source code and knowledge-graph sections. The section states:
- the analysis id, its date and commit;
- that categories are indicators;
- the thresholds.

Values that were not measured (for example graph metrics of a partial run) are left out, never filled in. Questions without metrics get exactly the previous prompt.

**4. Prompt rules.** These rules are added only when metrics are present:
- Every number about complexity, size, parameters or dependencies must be copied from the CODE METRICS section.
- Metrics are never estimated.
- Each statement cites its `[METRIC_n]`.
- The answer has a "Measured:" part followed by an "Interpretation:" part.

Translation keeps `[METRIC_n]` markers and all numbers unchanged.

**5. Evidence in the UI.** Metric evidence is a third evidence type (`type: "metric"`).
- It is listed under *Metrics* below the answer.
- `[METRIC_n]` citations are clickable.
- The evidence panel has a *Metrics* view with an *Open in code* action that highlights the function in the existing Monaco viewer.

## Future adaptive retrieval

`RagState` now carries `use_metrics`, `metrics_scope`, `metrics_focus` and `metrics_results`. `MetricsService` exposes per-entity and repository-level values: complexity, fan-in, fan-out, dependency depth and size.

These are available as input features for a future router that chooses between vector, graph-supported and agentic retrieval. No routing rule based on them is hard-coded: whether, for example, high connectivity favors graph retrieval is a hypothesis for experimental evaluation.

## Limitations

- **No maintainability index.** It needs Halstead volume, which Lizard does not measure (Radon would, for Python only), so it is not part of the metrics. Long, high-complexity and many-parameter functions are reported instead.
- **No class-level graph metrics.** Class membership is attached to functions, and file-level metrics cover classes in the usual one-class-per-file layout. The graph has no `INHERITS` edges, so inheritance does not count as a dependency.
- **Fan-in depends on call resolution.** It relies on the ingest's call extraction and on unique short names. Overloads in one file share one graph node (the ingest merges them by name), so they report the same fan values.
- **Language-dependent counts.** Python `self` and `cls` count as parameters. Class-like declarations follow the Tree-sitter node types per language, e.g. Rust `impl` blocks count.
- **Coverage.** Files uploaded manually are analyzed only when the user runs the analysis. Only files the ingest treats as code are measured.

## Future work

- A Semgrep analyzer as another `StaticMetricsAnalyzer` (quality findings).
- Git-history metrics (churn, change frequency) per file.
- Historical trends and commit comparison over the stored runs.
- Metrics-aware adaptive retrieval, evaluated experimentally.
