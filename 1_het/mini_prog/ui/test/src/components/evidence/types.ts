export type Highlight = {
    startLine: number,
    endLine: number
}

export type CodeEvidence = {
    type: "code",
    id: string,
    fileId?: string | null,
    fileName: string,
    filePath: string,
    language: string,
    highlights: Highlight[],
    symbols?: string[],
    retrievalType?: string | null,
    score?: number | null,
    evidenceIds?: string[] | null,
    producedBy?: string[] | null,
    certainty?: string | null
}

export type GraphNode = {
    id: string,
    label: string,
    type: string,
    fileId?: string | null,
    filePath?: string | null,
    startLine?: number | null,
    endLine?: number | null,
    usedAsEvidence?: boolean
}

export type GraphEdge = {
    source: string,
    target: string,
    type: string,
    certainty?: string | null
}

export type GraphEvidence = {
    type: "graph",
    id: string,
    nodes: GraphNode[],
    edges: GraphEdge[],
    evidenceIds?: string[] | null,
    producedBy?: string[] | null
}

export type MetricItem = {
    key: string,
    label: string,
    value: number | null,
    unit?: string | null,
    category?: string | null
}

export type MetricEvidence = {
    type: "metric",
    id: string,
    scope: "repository" | "file" | "function",
    title: string,
    fileId?: string | null,
    fileName?: string | null,
    filePath?: string | null,
    symbol?: string | null,
    startLine?: number | null,
    endLine?: number | null,
    analysisId?: number | null,
    analyzedAt?: string | null,
    commitSha?: string | null,
    items: MetricItem[],
    evidenceIds?: string[] | null,
    producedBy?: string[] | null
}

export type Evidence = CodeEvidence | GraphEvidence | MetricEvidence;

export type ProjectFile = {
    fileId: string,
    fileName: string,
    filePath: string,
    language: string,
    content: string
}

export function isCodeEvidence(e: Evidence): e is CodeEvidence {
    return e.type === "code";
}

export function isGraphEvidence(e: Evidence): e is GraphEvidence {
    return e.type === "graph";
}

export function isMetricEvidence(e: Evidence): e is MetricEvidence {
    return e.type === "metric";
}

export function formatRange(h: Highlight) {
    return h.startLine === h.endLine ? `Line ${h.startLine}` : `Lines ${h.startLine}–${h.endLine}`;
}

export function nodeLocation(node: GraphNode): Highlight | null {
    if (!node.startLine) return null;
    return { startLine: node.startLine, endLine: node.endLine ?? node.startLine };
}

/** Evidence can come from stored messages, so anything malformed is dropped instead of crashing the chat. */
export function sanitizeEvidence(value: unknown): Evidence[] {
    if (!Array.isArray(value)) return [];
    return value.filter((e): e is Evidence =>
        !!e && typeof e === "object" && typeof e.id === "string" &&
        ((e.type === "code" && typeof e.filePath === "string" && Array.isArray(e.highlights)) ||
            (e.type === "graph" && Array.isArray(e.nodes) && Array.isArray(e.edges)) ||
            (e.type === "metric" && typeof e.title === "string" && Array.isArray(e.items))));
}

export type ExecutionStep = {
    iteration: number,
    tool: string,
    latencyMs: number,
    evidence?: string[],
    newEvidence?: number,
    cached?: boolean,
    error?: { kind: string, message: string } | null
}

export type RouteInfo = {
    chosen: string,
    reason: string
}

export type ExecutionInfo = {
    runId?: string,
    strategy: string,
    route?: RouteInfo | null,
    status?: string | null,
    toolCalls?: number,
    iterations?: number,
    latencyMs?: number | null,
    inputTokens?: number,
    outputTokens?: number,
    stopReason?: string | null,
    trace?: ExecutionStep[]
}

export type PatternEvidenceRef = {
    id: string,
    alias?: string | null,
    file_path: string,
    start_line?: number | null,
    end_line?: number | null,
    symbol?: string | null,
    source: string,
    role: string,
    why: string
}

export type PatternFindingInfo = {
    pattern: string,
    name: string,
    status: string,
    subject: string,
    explanation: string,
    counter_indications?: string[]
}

export type PatternRecommendationInfo = {
    pattern: string,
    name: string,
    mode: string,
    confidence: string,
    reason: string,
    subject: string,
    evidence_ids: string[],
    architectural_changes: string[],
    benefits: string[],
    tradeoffs: string[],
    risks: string[]
}

export type AlternativeInfo = {
    kind: string,
    summary: string,
    changes: string[],
    affected_files: string[],
    new_elements: string[],
    advantages: string[],
    disadvantages: string[],
    risks: string[],
    technical_debt: string[],
    evidence_ids: string[]
}

export type ComparisonRowInfo = {
    dimension: string,
    minimal_change: string,
    pattern_refactoring: string,
    basis: string
}

export type PatternAnalysisInfo = {
    preferred_alternative?: string | null,
    justification: string,
    no_pattern_needed: boolean,
    existing_patterns: PatternFindingInfo[],
    detected_opportunities: PatternFindingInfo[],
    recommended_patterns: PatternRecommendationInfo[],
    considered_patterns: { pattern: string, name: string, reason: string }[],
    alternatives: { minimal_change?: AlternativeInfo | null, pattern_refactoring?: AlternativeInfo | null },
    comparison: ComparisonRowInfo[],
    evidence: PatternEvidenceRef[],
    limitations: string[]
}

function objects<T>(value: unknown, required: string): T[] {
    return Array.isArray(value)
        ? value.filter((v): v is T => !!v && typeof v === "object" && typeof (v as Record<string, unknown>)[required] === "string")
        : [];
}

function strings(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function alternative(value: unknown): AlternativeInfo | null {
    if (!value || typeof value !== "object") return null;
    const raw = value as Record<string, unknown>;
    if (typeof raw.summary !== "string") return null;
    return {
        kind: typeof raw.kind === "string" ? raw.kind : "",
        summary: raw.summary,
        changes: strings(raw.changes),
        affected_files: strings(raw.affected_files),
        new_elements: strings(raw.new_elements),
        advantages: strings(raw.advantages),
        disadvantages: strings(raw.disadvantages),
        risks: strings(raw.risks),
        technical_debt: strings(raw.technical_debt),
        evidence_ids: strings(raw.evidence_ids)
    };
}

/** The design pattern analysis is optional; anything malformed is dropped so the answer still renders. */
export function sanitizePatternAnalysis(value: unknown): PatternAnalysisInfo | null {
    if (!value || typeof value !== "object") return null;
    const raw = value as Record<string, unknown>;
    const alternatives = (raw.alternatives && typeof raw.alternatives === "object" ? raw.alternatives : {}) as Record<string, unknown>;
    const recommended = objects<PatternRecommendationInfo>(raw.recommended_patterns, "name").map(r => ({
        ...r,
        evidence_ids: strings(r.evidence_ids),
        architectural_changes: strings(r.architectural_changes),
        benefits: strings(r.benefits),
        tradeoffs: strings(r.tradeoffs),
        risks: strings(r.risks)
    }));
    const info: PatternAnalysisInfo = {
        preferred_alternative: typeof raw.preferred_alternative === "string" ? raw.preferred_alternative : null,
        justification: typeof raw.justification === "string" ? raw.justification : "",
        no_pattern_needed: raw.no_pattern_needed === true,
        existing_patterns: objects<PatternFindingInfo>(raw.existing_patterns, "name"),
        detected_opportunities: objects<PatternFindingInfo>(raw.detected_opportunities, "name"),
        recommended_patterns: recommended,
        considered_patterns: objects(raw.considered_patterns, "name"),
        alternatives: { minimal_change: alternative(alternatives.minimal_change), pattern_refactoring: alternative(alternatives.pattern_refactoring) },
        comparison: objects<ComparisonRowInfo>(raw.comparison, "dimension"),
        evidence: objects<PatternEvidenceRef>(raw.evidence, "file_path"),
        limitations: strings(raw.limitations)
    };
    const empty = !info.preferred_alternative && !info.existing_patterns.length && !info.detected_opportunities.length && !info.recommended_patterns.length;
    return empty ? null : info;
}

export function sanitizeExecution(value: unknown, status?: unknown): ExecutionInfo | null {
    if (!value || typeof value !== "object") return null;
    const raw = value as Record<string, unknown>;
    if (typeof raw.strategy !== "string") return null;
    const trace = Array.isArray(raw.trace)
        ? raw.trace.filter((s): s is ExecutionStep => !!s && typeof s === "object" && typeof (s as ExecutionStep).tool === "string")
        : [];
    const number = (v: unknown) => typeof v === "number" ? v : undefined;
    const rawRoute = raw.route && typeof raw.route === "object" ? raw.route as Record<string, unknown> : null;
    const route = rawRoute && typeof rawRoute.chosen === "string" && typeof rawRoute.reason === "string"
        ? { chosen: rawRoute.chosen, reason: rawRoute.reason }
        : null;
    return {
        runId: typeof raw.runId === "string" ? raw.runId : undefined,
        strategy: raw.strategy,
        route,
        status: typeof status === "string" ? status : typeof raw.status === "string" ? raw.status : null,
        toolCalls: number(raw.toolCalls),
        iterations: number(raw.iterations),
        latencyMs: number(raw.latencyMs) ?? null,
        inputTokens: number(raw.inputTokens),
        outputTokens: number(raw.outputTokens),
        stopReason: typeof raw.stopReason === "string" ? raw.stopReason : null,
        trace
    };
}
