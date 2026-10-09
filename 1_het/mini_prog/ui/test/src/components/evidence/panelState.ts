import { isCodeEvidence, isGraphEvidence, isMetricEvidence, nodeLocation, type CodeEvidence, type Evidence, type GraphEvidence, type GraphNode, type Highlight, type MetricEvidence } from "./types";

export type PanelView = "code" | "graph" | "metric";

export type PanelState = {
    evidence: Evidence[],
    sources: CodeEvidence[],
    activeSourceId: string | null,
    activeHighlight: number,
    activeMetricId?: string | null,
    view: PanelView
}

export function openPanel(evidence: Evidence[], targetId: string): PanelState {
    const sources = evidence.filter(isCodeEvidence);
    const target = evidence.find(e => e.id === targetId);
    const metrics = evidence.filter(isMetricEvidence);
    return {
        evidence,
        sources,
        activeSourceId: target && isCodeEvidence(target) ? target.id : sources[0]?.id ?? null,
        activeHighlight: 0,
        activeMetricId: target && isMetricEvidence(target) ? target.id : metrics[0]?.id ?? null,
        view: target && isGraphEvidence(target) ? "graph" : target && isMetricEvidence(target) ? "metric" : "code"
    };
}

export function panelMetrics(state: PanelState): MetricEvidence[] {
    return state.evidence.filter(isMetricEvidence);
}

export function panelGraph(state: PanelState): GraphEvidence | undefined {
    return state.evidence.find(isGraphEvidence);
}

export function activeSource(state: PanelState): CodeEvidence | undefined {
    return state.sources.find(s => s.id === state.activeSourceId) ?? state.sources[0];
}

export function selectSource(state: PanelState, sourceId: string): PanelState {
    return { ...state, activeSourceId: sourceId, activeHighlight: 0, view: "code" };
}

type Location = { key: string, fileId?: string | null, filePath?: string | null, label: string, range: Highlight | null };

function openLocation(state: PanelState, location: Location): PanelState {
    if (!location.fileId) return state;
    const range = location.range;
    const existing = state.sources.find(s => s.fileId === location.fileId);

    if (existing) {
        let index = range
            ? existing.highlights.findIndex(h => h.startLine === range.startLine && h.endLine === range.endLine)
            : 0;
        let updated = existing;
        if (range && index === -1) {
            updated = { ...existing, highlights: [...existing.highlights, range] };
            index = updated.highlights.length - 1;
        }
        return {
            ...state,
            sources: state.sources.map(s => s.id === existing.id ? updated : s),
            activeSourceId: existing.id,
            activeHighlight: Math.max(index, 0),
            view: "code"
        };
    }

    const path = location.filePath ?? "";
    const source: CodeEvidence = {
        type: "code",
        id: location.key,
        fileId: location.fileId,
        fileName: path.split("/").pop() || location.label,
        filePath: path,
        language: "plaintext",
        highlights: range ? [range] : [],
        symbols: [location.label]
    };
    return {
        ...state,
        sources: [...state.sources, source],
        activeSourceId: source.id,
        activeHighlight: 0,
        view: "code"
    };
}

/** Opens a graph node's source range, reusing the file's tab when it is already evidence. */
export function focusNode(state: PanelState, node: GraphNode): PanelState {
    return openLocation(state, { key: `NODE_${node.id}`, fileId: node.fileId, filePath: node.filePath, label: node.label, range: nodeLocation(node) });
}

export function focusMetric(state: PanelState, metric: MetricEvidence): PanelState {
    const range = metric.startLine ? { startLine: metric.startLine, endLine: metric.endLine ?? metric.startLine } : null;
    return openLocation(state, { key: `METRIC_SRC_${metric.id}`, fileId: metric.fileId, filePath: metric.filePath, label: metric.symbol ?? metric.title, range });
}

export function summarizeMetric(metric: MetricEvidence): string {
    const lead = metric.items.filter(i => i.value !== null).slice(0, 2);
    return lead.map(i => `${i.label}: ${i.value}`).join(" · ");
}

export function summarizeGraph(graph: GraphEvidence): string {
    const labels = new Map(graph.nodes.map(n => [n.id, n.label]));
    const calls = graph.edges.filter(e => e.type === "CALLS");
    const edges = calls.length ? calls : graph.edges;
    if (!edges.length) return `${graph.nodes.length} node${graph.nodes.length === 1 ? "" : "s"}`;

    const targets = new Set(edges.map(e => e.target));
    const start = edges.find(e => !targets.has(e.source))?.source ?? edges[0].source;
    const chain = [start];
    while (chain.length < 4) {
        const next = edges.find(e => e.source === chain[chain.length - 1] && !chain.includes(e.target));
        if (!next) break;
        chain.push(next.target);
    }

    const text = chain.map(id => labels.get(id) ?? "?").join(" → ");
    const extra = graph.nodes.length - chain.length;
    return extra > 0 ? `${text} (+${extra} more)` : text;
}
