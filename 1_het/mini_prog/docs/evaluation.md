# Evaluating retrieval strategies

`AI/codemind_eval/` is a standalone package that runs a fixed benchmark against the real CodeMind services
and turns the traces into metrics, CSV tables and figures. It compares the retrieval strategies that already
exist in the AI service. Fixed strategies bypass the router; `adaptive_rag` keeps the production routing
(including escalation).

| Strategy | Kind | What it does |
|---|---|---|
| `vector_rag` | fixed pipeline | Qdrant search only; no graph, rerank or code metrics |
| `selective_rag` | fixed pipeline | LLM question-type classifier decides graph and rerank; metrics by intent |
| `hybrid_rag` | fixed pipeline | Qdrant + Neo4j expansion of the top hits + rerank + code metrics |
| `evidence_aware_agentic_rag` | fixed agent | Tool loop with sufficiency checks and answer verification |
| `adaptive_rag` | adaptive | Router picks `selective_rag` or the agent; escalates weak pipeline results |

`agentic_rag` and the agent ablations can be added with `--strategies` / `--ablation`.

Every command below is run from `AI/` with the service environment (`.env`) loaded. Report rendering needs
`pip install -r requirements-eval.txt` (matplotlib).

The commands can also run inside the `ai` container, which already has the same configuration the repository
was indexed with. Prefix them with `docker compose exec ai` from the repository root, and pass the judge model
with `-e JUDGE_MODEL=...`. `eval/results` is mounted from `AI/eval/results`, so results land on the host. The
image has no matplotlib, so run `report` on the host. Code changes need `docker compose up -d --build ai`.
The image has no git metadata, so pass the CodeMind commit for the manifest with
`-e CODEMIND_COMMIT=<sha> -e CODEMIND_DIRTY=<true|false>`.

## 1. Index a repository at a pinned commit

Retrieval is only comparable when every strategy reads the same snapshot.

1. Create a project in the UI (or through the backend API) and note its `userId`, `investigationId` and
   `projectId`.
2. Import the repository with an explicit reference, preferably the full commit SHA:
   `POST /api/investigations/projects/repositories/add` with
   `{"invId": 1, "projectId": 7, "owner": "junit-team", "repo": "junit4", "reference": "890f3c972647de378f25e7271d8fbbd9d3456b79"}`.
   The backend resolves the reference, stores the commit SHA, and sends the files to the AI service for
   Qdrant and Neo4j indexing.
3. Wait until the import status is completed, and run the metrics analysis if the code-metrics ablation is
   part of the experiment.
4. Put the same SHA into the benchmark's `repository.commit_sha`. The runner records the snapshot that the
   backend reports for every run and sets `snapshotMatches`. A mismatch is visible in `status_counts.csv`.

Use one project per snapshot. Never re-import a different commit into a project that an experiment is
still using.

Shipped benchmarks (40 questions, 8 categories × 5, draft annotations, gold evidence validated with
`validate-gold` against the pinned commit):

| Benchmark | Import (`owner` / `repo` / `reference`) | Notes |
|---|---|---|
| `eval/benchmarks/junit4/benchmark.json` | `junit-team` / `junit4` / `890f3c972647de378f25e7271d8fbbd9d3456b79` | r4.13.2 + 50 commits |
| `eval/benchmarks/ant/benchmark.json` | `apache` / `ant` / `dbb01a2d528568b1d7ba0c2d84e533577f7f0876` | master after rel/1.10.15; 1937 indexable files, under the 2000-file import cap |
| `eval/benchmarks/bottle/benchmark.json` | `bottlepy` / `bottle` / `aba0c1a7ee59ed851db001d100b6a792b54a94a3` | master (0.14-dev); single module, so use symbol-level retrieval metrics |

Use the full SHA as the reference: the GitHub commits endpoint does not accept tags that contain a slash,
such as `rel/1.10.15`. In every benchmark, the `code_quality` questions that need measured rankings have no
reference answer and are scored without correctness and completeness.

## 2. Prepare the gold standard

A benchmark file looks like `eval/benchmarks/junit4/benchmark.json`:

```json
{
  "name": "junit4-sample",
  "repository": {"id": "junit4", "url": "...", "reference": "r4.13.2-50-g890f3c97", "commit_sha": "890f3c9..."},
  "questions": [{
    "id": "junit4-03",
    "question": "How are methods annotated with @Before executed before each test?",
    "category": "comprehension",
    "reference_answer": null,
    "annotation_status": "draft",
    "gold_evidence": [
      {"kind": "file", "path": "src/main/java/org/junit/internal/runners/statements/RunBefores.java"},
      {"kind": "symbol", "path": "src/main/java/org/junit/runners/BlockJUnit4ClassRunner.java", "symbol": "withBefores"}
    ]
  }]
}
```

The fields mean:

- `gold_evidence` lists the files and symbols that a correct answer must be grounded in.
  - Paths are repository-relative.
  - Symbols use the short name. Overloads are matched by name within the given file.
  - A symbol without a path matches that name in any file.
- `reference_answer` is the manually written answer. Leave it `null` until an annotator writes it. The
  judge then skips correctness and completeness for that question, and scores nothing it cannot check.
- `annotation_status` is one of three values:
  - `draft`: proposed but not reviewed
  - `verified`: reviewed by the annotator
  - `legacy`: imported from the old `questions.json` format
  The manifest records which statuses an experiment used.
- `expected_strategy` is optional. It is the strategy an expert expects the router to choose.

The old `eval/questions.json` format is accepted as is: `expected_files` and `expected_symbols` are
converted to gold evidence, and `ground_truth` becomes the reference answer.

Check that every gold entry exists at the pinned commit (needs a local clone):

```
git clone https://github.com/junit-team/junit4 ../junit4
python -m codemind_eval validate-gold --benchmark eval/benchmarks/junit4/benchmark.json --repo ../junit4
```

The validator checks existence only (files, symbol names, line ranges). Whether the evidence is the
*right* evidence is a manual review step. The JUnit 4 sample gold is a draft that passes the existence
check and still needs that review. Its reference answers are deliberately empty.

## 3. Run all strategies

```
python -m codemind_eval run --benchmark eval/benchmarks/junit4/benchmark.json \
    --experiment-id junit4-main --user-id 1 --investigation-id 1 --project-id 7 \
    --repetitions 3 --metrics-variants default,off
```

- Execution is sequential. Tool caches are cleared before every run (`--keep-caches` disables this), so
  runs do not share cached tool results.
- `--metrics-variants default,off` adds the code-metrics ablation. In the `off` variant:
  - pipeline strategies get `use_metrics=False`
  - the agent gets the `no_metrics` ablation
  - `adaptive_rag` gets both
  `vector_rag/off` is skipped because it never uses metrics.
- `--shuffle-seed N` randomises the order within each repetition. This is reproducible from the seed.
- `--retries` / `--backoff` retry a failing run with exponential backoff. A run that still fails is written
  with `status: "error"` and its error messages. It is never scored as zero.
- **Resuming:** re-running the same command skips every run that already succeeded and retries the failed
  ones. The benchmark file hash is stored in `manifest.json`. Resuming with a changed benchmark is refused;
  start a new experiment id instead.

Outputs go to `eval/results/<experiment-id>/` (git-ignored):

- `manifest.json`:
  - the CodeMind commit and dirty flag
  - model names, agent configuration, strategies, repetitions, seeds
  - the benchmark hash and the command line
- `runs.jsonl`: one record per execution, with these fields:
  - **Run identity:** `runKey`, `repositoryId`, `expectedCommitSha`, `repositorySnapshot`, `commitSha`,
    `snapshotMatches`, `questionId`
  - **Strategy:** `strategy` (requested), `selectedStrategy` (router choice), `effectiveStrategy` (after
    escalation)
  - **Evidence and answer:**
    - `retrievedEvidence`: everything retrieved
    - `contextEvidence`: what was rendered into the LLM prompt, in prompt order
    - `contextText`: the rendered context
    - `citedAliases`, `answer`
  - **Tools:** `toolCalls`, `iterations`, `toolSequence`
  - **Latency:** `latency.{totalMs, routingMs, vectorMs, graphMs, retrievalMs, contextMs, generationMs}`
  - **Tokens:** `inputTokens`, `outputTokens`, `tokenUsageComplete`
  - **Outcome and raw data:** `status`, `errors`, and the raw service `traces`

**Unavailable values are `null`, never zero.**

- **Tokens:** when Ollama does not report token counts for a call, `tokenUsageComplete` is `false`.
  The token totals become `null` only when no call reported any counts.
- **Tool time:** for the agent, `vectorMs` and `graphMs` are cumulative tool time per tool category.
  Tools can run concurrently, so these can exceed the wall-clock time.
- **Escalated `adaptive_rag` runs:** these produce a pipeline trace and an agent trace. Their tokens are
  summed, with the routing call counted once.

## 4. Calculate scores

Optional LLM-as-judge (`JUDGE_MODEL` must be set; it never falls back to the generator model):

```
JUDGE_MODEL=qwen3:32b python -m codemind_eval judge --benchmark eval/benchmarks/junit4/benchmark.json \
    --experiment-id junit4-main
```

How the judge works:

- **What it sees:** the question, the reference answer, the evidence context and the answer.
- **Blinding:** strategy names, tool names and pipeline-specific markers are removed. Runs are judged in a
  seeded random order.
- **Output:** a JSON object, validated against these ranges:
  - `factual_correctness` 0-3
  - `completeness` 0-1
  - `faithfulness` 0-1
  - `citation_correctness` 0-1
- **Failures:** invalid output is retried. A run whose judging keeps failing is stored as `judge_error`.
- **Storage:** judgements go to `judgements.jsonl` with the judge model, temperature, seed and prompt
  version. They are automated scores, kept separate from the manually written gold standard.

Then compute every table:

```
python -m codemind_eval score --benchmark eval/benchmarks/junit4/benchmark.json --experiment-id junit4-main
```

`scores/` contains:

| File | Content |
|---|---|
| `rows.csv` | one row per run: retrieval, judge, latency, token, tool and impact columns |
| `summary_by_strategy.csv` | mean, std, median, 95% bootstrap CI and n per strategy and metrics variant |
| `summary_by_category.csv` | the same per question category |
| `status_counts.csv` | ok / error runs, snapshot mismatches, runs without token data, judge errors |
| `tool_usage.csv` | calls per tool and strategy |
| `ablation.csv` | paired per-question differences, with metrics minus without (mean, CI, wins/losses) |
| `routing_questions.csv`, `routing_summary.json` | per-question oracle and adaptive routing analysis |
| `routing_questions_composite.csv`, `routing_summary_composite.json` | the same analysis with `composite_score` as quality |
| `impact.csv` | change-impact precision, recall and F1 |

### Retrieval metrics

Evidence is compared on normalised units, so chunking strategies are comparable:

- **File level:** each strategy's ranked evidence is reduced to its first occurrence per file. Paths are
  normalised and matched by suffix, so a zipball prefix such as `junit4-r4.13.2/` does not matter.
- **Symbol level:** the ranking is reduced to its first occurrence per `(file, short symbol name)`.
- **Gold set:** the gold files are the listed files plus the files of the listed symbols.

The metrics are defined as follows:

- `recall@k`: share of gold units found in the first k units
- `precision@k`: relevant units in the first k divided by k. It is still k when fewer units were
  retrieved, so a pipeline that returns five chunks can reach at most 0.5 at k=10.
- `mrr`: reciprocal rank of the first relevant unit
- `coverage`: recall over the whole list

Each metric is computed on two lists:

- `ctx_*` uses the evidence actually passed to the LLM. This is the primary measure.
- `ret_*` uses everything retrieved.

Questions without gold evidence get empty cells, not zeros.

### Composite score

Correctness alone does not show whether an answer is grounded in the retrieved code. `composite_score` is the
equal-weight mean of three dimensions, each the mean of its metrics:

- `composite_answer`: `judge_correctness_norm`, `judge_completeness`
- `composite_grounding`: `judge_faithfulness`, `judge_citation_correctness`
- `composite_retrieval`: `ctx_file_recall@5`

A dimension without any value is left out of the mean, not counted as zero. Runs whose judging failed get no
composite score. Cost is not part of the score; it stays a separate measure and the oracle tie-breaker.

### Aggregation

Repetitions of a question are averaged first. The confidence intervals are then bootstrapped over
questions (2000 resamples, fixed seed). `within_question_std` reports run-to-run variation.

### Adaptive routing

The oracle is computed offline per question from the four fixed strategies:

- **Choosing the oracle:** it is the highest quality strategy, with ties broken by fewer tokens, then lower
  latency. Quality is the judge's scaled correctness when judgements exist, otherwise `ctx_file_recall@5`
  (override with `--routing-quality <column>`).
- **Agreement:**
  - `oracleAgreement`: the router's effective strategy is in the optimal set.
  - `restrictedOracleAgreement`: the same, considering only the two options the router can actually
    choose (`selective_rag`, `evidence_aware_agentic_rag`).
- **Regret:** oracle quality minus `adaptive_rag` quality.
- **Savings:** token and latency savings are measured against always running `evidence_aware_agentic_rag`.
- **Also reported:** selection and escalation distribution, route reasons, and router latency.
- **Composite variant:** when composite scores exist and the primary quality key is not already
  `composite_score`, the whole analysis is repeated with `composite_score` as quality.

### Router decision correctness

`python -m codemind_eval routing-report --experiment-id <id>` reads `scores/rows.csv` and writes
`scores/routing_decision_correctness.csv`, `scores/routing_correctness_summary.csv` and three figures
(`routing_accuracy_donut`, `routing_decisions_by_category`, `routing_accuracy_by_category`, PNG and SVG).
It does not rewrite the other score files.

- **Per question:** quality, tokens and latency of `selective_rag` and `evidence_aware_agentic_rag` are the
  means over the repetitions of their own fixed runs (`metrics = default`, `status = ok`).
- **Correct choice:** with `d = q(agent) − q(selective)` and `TIE_TOLERANCE = 0.12`, the agent is correct when
  `d > 0.12`, the selective pipeline when `d < −0.12`, otherwise the strategy with fewer mean `totalTokens`
  (then lower latency).
- **Router decision:** the majority `selectedStrategy` of the `adaptive_rag` repetitions, before escalation.
  `selectedCorrect` scores it; `effectiveCorrect` scores the path after escalation. The accuracy figures use
  `effectiveCorrect`; `routing_decisions_by_category` shows the router decision before escalation.
- **Not evaluated:** questions without a quality score for either strategy (`missing_quality`), without one of
  the two strategy runs (`missing_strategy_runs`) or without token and latency data (`missing_cost`).
- **Severity:** for the path after escalation, `effectiveOutcome` is `optimal`, `wasted_agent` (tie, agent
  chosen), `quality_loss_agent` or `quality_loss_selective`. `effectiveQualityLoss`, `effectiveExtraTokens`,
  `effectiveExtraLatencyMs` and `effectiveTokenRatio` compare the chosen strategy with the correct one.
  `scores/routing_nonoptimal_summary.csv` and `routing_nonoptimal_severity` summarize them per outcome.
- **Summary:** overall, per category and per experiment, with the always-selective and always-agent baselines,
  plus a sensitivity row for tolerances 0 and 0.34. Categories with fewer than 10 evaluated questions are
  hatched in the figure.

## 5. Generate research reports

```
python -m codemind_eval report --experiment-id junit4-main
```

The command writes 300 dpi PNGs to `figures/`:

- `retrieval_by_strategy`
- `answer_quality_by_strategy`
- `overall_score_by_strategy`
- `quality_by_category`
- `overall_score_by_category`
- `latency_distribution`
- `tool_usage`
- `routing_decisions`
- `routing_decisions_composite`
- `metrics_ablation`
- `change_impact`

A figure is skipped, and reported as skipped, when its data does not exist. Every figure has a
corresponding CSV table.

## Change-impact evaluation on historical commits

1. Mine cases from a full local clone. Each case uses a non-merge commit, its parent as `base_sha`, and the
   files it modified as the gold set:

   ```
   python -m codemind_eval impact-mine --repo ../junit4 --repository-id junit4 \
       --range r4.12..r4.13.2 --max-cases 15 --min-files 2 --max-files 8 --exclude-tests \
       --out eval/benchmarks/junit4/impact_cases.json
   ```

   The question is generated from the commit subject. Review the cases and drop commits whose message
   gives away the files.
2. Index every `base_sha` as its own project (step 1). The post-change code must never be indexed. Write
   the project into each case as `"scope": {"user_id": 1, "investigation_id": 1, "project_id": 12}`.
3. Run `run`, `judge` and `score` with `--impact eval/benchmarks/junit4/impact_cases.json` instead of
   `--benchmark`. Then run `report` as usual.

Predicted files come from the run itself, with no prompt changes:

- `impact_cited_*`: files of the evidence the answer cites
- `impact_context_*`: all files in the LLM context

A run counts only when its recorded snapshot is `commit:<base_sha>`. Runs on any other or an unknown
snapshot are marked `impact_valid=false` and are not scored. Use `--allow-unverified-snapshot` only for
debugging. When a run predicts no files, its precision is undefined (empty) and its F1 is 0.

## Code changes made for the evaluation

All of these are additive; production answers are unchanged.

- `app/services/ollama_call.py`: missing token counts are `None` instead of `0`, and a contextvar usage
  recorder lets the pipeline report LLM usage. It also gains optional `model`, `base_url` and `options`
  parameters for the judge.
- `app/services/rag_graph.py`: `graph_time_ms`, `context_time_ms` and `context_evidence`.
- `app/services/chat_service.py`: the pipeline trace gains tokens, latency breakdown, context evidence and
  cited aliases. The router's token usage is recorded, and `_run_adaptive` accepts `extra_overrides`.
- `app/agents/graph.py`: context latency, the ranked context evidence, and unavailable-token tracking.
- `app/evaluation/eval_mode.py`: `run_evaluation(request, strategy, metrics)` dispatches a forced strategy.

## Tests

```
cd AI
pytest codemind_eval/tests
```

The tests cover:

- metric formulas (hand-computed)
- normalisation
- benchmark and judge JSON parsing
- strategy dispatch and router bypass
- trace fields and unavailable tokens
- retries, resume and failed-run handling
- the routing oracle
- aggregation and the full score/report path on synthetic runs
