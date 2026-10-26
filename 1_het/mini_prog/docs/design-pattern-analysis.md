# Design pattern analyzer and recommender

The analyzer is part of the agent workflow (`docs/agentic-retrieval.md`). When a question asks for a
change, an extension, a refactoring or a design pattern, it:

- detects design patterns that already exist in the code;
- finds refactoring opportunities;
- compares the smallest change with a pattern-based refactoring and decides which one to recommend.

It can conclude that no pattern is needed, and it does so whenever the evidence does not support one.

## Pipeline

```
paths / symbols / change request
  -> scope (requested files, graph symbols, or semantic search as a fallback)
  -> bounded source reads (RagApi source/content, 400-line pages, PATTERN_MAX_FILE_LINES)
  -> Tree-sitter structure (app/patterns/structure.py)
  -> one expansion round: definitions of referenced types and implementers of abstractions
     (code graph, else at most two keyword searches)
  -> signals: AST + Neo4j graph + stored metrics (app/patterns/signals.py)
  -> rule-based detection against the knowledge base (app/patterns/detector.py)
  -> recommendation and comparison (app/patterns/recommender.py)
  -> PatternAnalysis + evidence with stable evidence ids (app/patterns/analyzer.py)
```

The analyzer makes no LLM calls. The LLM only writes the final answer from the structured analysis
(`PATTERN_REVIEW_PROMPT`, or `CHANGE_PLAN_PROMPT` with `PATTERN_PLAN_BLOCK` added), and the verifier
checks that answer. A pattern never comes from the LLM alone.

## Knowledge base

The pattern definitions live in `app/patterns/knowledge/patterns.json` and are validated by the Pydantic
models in `app/patterns/knowledge_base.py`. Each pattern defines:

- intent, use cases and applicability;
- structural indicators and the code smells it addresses;
- benefits, drawbacks and when not to use it;
- implementation steps and examples;
- confidence notes;
- the kinds of change it suits (`change_affinity`);
- declarative detection rules.

A rule names the signals it needs (`all`), the signals that raise its status by one level (`boost`),
an optional `partial_status`, and optional change kinds it requires (`requires_change`).
`max_status` caps a pattern whose structure is ambiguous: Strategy, State and Bridge look the same,
so Strategy is reported as at most "likely".

A new pattern can be added by combining existing signals in JSON. The engine does not change; there is
a test that shows this. A new kind of structural fact needs a new signal in `signals.py` and an entry
in `SIGNALS`.

Supported patterns: Strategy, Observer, Factory Method, Adapter, Facade, Decorator, Repository.

## Signals

| Source | Signals |
|---|---|
| AST (Python, C#, Java, TypeScript, JavaScript) | abstraction with implementations, context holding an abstraction, constructor injection, wrapper of the same interface, adapter delegation, creator methods, overridden creators, listener registration and notification loops, events, delegating classes, collection-like data access, persistence dependencies, conditional dispatch (3+ cases, 4+ cases, only 2 cases), type checks, type-dependent creation, scattered creation, similar classes without an abstraction, repeated notification, subclasses extending a base method |
| Neo4j code graph | stored base types (`Class.bases`), high fan-in, shared call sequences, fan-out hubs, callers of the changed function |
| Stored metrics (Lizard) | high cyclomatic complexity (the stored category, else CC ≥ 15), long functions (NLOC ≥ 50) |

Detection results are labelled confirmed, likely or possible. Names alone never produce a finding.
Repository operation names are only accepted together with a dependency on a persistence API.

## Recommendation and comparison

`classify_change` maps the request to change kinds such as new variant, integration, cross-cutting
concern, notification, creation, simpler access, data access, refactoring or extension. The rules for
each pattern, in order:

1. **Extend the existing pattern.** If the pattern already exists and fits the change kind, it is
   recommended in `extend_existing` mode. Confidence is high when the structure is confirmed in the
   touched files, otherwise medium. The minimal change and the pattern-conforming change are then the
   same.
2. **Introduce the pattern.** If an opportunity fits the change kind, the pattern is recommended in
   `introduce` mode. Confidence is medium when a boost signal supports the opportunity (measured high
   complexity, a long function, 4+ cases, fan-out), otherwise low. A low-confidence pattern is listed
   as considered, not recommended. Counter-indications such as "only two cases" lower the confidence.
3. **Nothing fits.** Otherwise `no_pattern_needed` is set and the minimal change is preferred.

Confidence is qualitative. There are no percentages, because no calibration exists.

The comparison has two alternatives (`minimal_change` and `pattern_refactoring`) and labels every row:

- **measured:** caller counts from the graph and the stored cyclomatic complexity;
- **planned:** counts of files to change, new abstractions and cases;
- **qualitative:** coupling, cohesion, extensibility, regression risk and legacy compatibility.

The pattern-based refactoring is preferred only when the recommendation is at least medium, there is
pressure to restructure (4+ cases, measured high complexity, or an explicit refactoring request), and
the regression risk is not high (fewer than 5 callers and no high-complexity band). Otherwise the
minimal change is preferred, with the reason stated. The analyzer never claims post-refactoring metric
values.

## Agent integration

- **Tools** (category `patterns`): `detect_design_patterns`, `find_pattern_opportunities`,
  `recommend_design_patterns`, `compare_change_strategies`. They share one cached analysis per scope
  and request. Distinct analyses are capped at `PATTERN_MAX_RUNS`; further calls return a typed
  `budget` error. Duplicate calls are blocked by the planner.
- **Routing:** the `design_pattern` intent (refactor, design pattern, simplify, best way to extend,
  integrate without rewriting, and the Hungarian equivalents) and `change_planning` add a
  `pattern_analysis` requirement. Lookup and comprehension questions never get it.
- **Planner fallback:** for change questions, `recommend_design_patterns` waits until the similar
  feature is known, then runs with its files plus the named symbols.
- **State:** `pattern_analysis` holds the structured result.
  - The response carries it as `patternAnalysis`, with every evidence reference resolved to its alias
    (for example `SOURCE_n`).
  - `execution.patternAnalysis` and the trace record diagnostics: invoked or not, operations, patterns
    considered, detected and recommended, evidence sources, latency, files parsed, and whether the
    graph and metrics were used. No source code goes into these.
- **Evidence:** AST findings become `code_range` evidence, graph findings `graph_relation` or
  `graph_node`, and metrics `metric`. Their ids come from the shared evidence store, so citations,
  the verifier and the evidence viewer work unchanged. Lines under "Pattern-based refactoring" or
  prefixed with `Proposed:` may name classes that don't exist yet.
- **Feature flag:** `ENABLE_DESIGN_PATTERN_ANALYSIS` (default `true`) or `ablation=no_patterns`.
  When off, the tools are not registered and the requirement is dropped, so retrieval behaves exactly
  as without the feature.
- **UI:** `PatternAnalysisPanel` appears under the answer with expandable sections: recommended
  approach, pattern recommendations, implementation alternatives side by side with the comparison
  table, affected code (buttons open the existing evidence viewer), and limitations.

## Graph schema extension

Indexing stores the base types of each type as `Class.bases` and as `INHERITS` edges, via
`type_relations` and `Neo4jService.save_type_relations`; interfaces are stored as `Class` nodes with
`typeKind = interface`. Repositories indexed earlier have no such data. For them the analyzer
derives inheritance from the parsed files plus one keyword search, and reports this as a
limitation. The full schema is in `docs/agentic-retrieval.md`.

## Limitations

- Structural analysis covers Python, C#, Java, TypeScript and JavaScript. Other languages are skipped
  and listed.
- The analysis is bounded:
  - at most `PATTERN_MAX_FILES` files, each read up to `PATTERN_MAX_FILE_LINES`;
  - one expansion round;
  - pattern evidence capped at `PATTERN_MAX_EVIDENCE` items.
  Patterns spread over files outside this scope can be missed.
- Some facts are inferred heuristically:
  - Python constructors are recognised by capitalised call names.
  - An unanalysed C# base type whose name starts with `I` counts as an interface only when it has an
    implementer.
- Adapters are reported only for adaptees that are not defined in the repository, because services
  delegating to their own repositories look identical.
- Strategy, State and Bridge cannot be told apart. Facade and Repository are reported as at most
  "likely".
- Test coverage is not analyzed. Regression risk relies on graph callers and stored complexity, and
  every risk list says that tests were not checked.
- Pattern descriptions are not retrieved semantically from Qdrant. Selection is rule-based.
