import { isCodeEvidence, isGraphEvidence, nodeLocation, type CodeEvidence, type Evidence, type GraphEvidence, type GraphNode } from "./types";

export type PanelView = "code" | "graph";

export type PanelState = {
    evidence: Evidence[],
    sources: CodeEvidence[],
    activeSourceId: string | null,
    activeHighlight: number,
    view: PanelView
}

export function openPanel(evidence: Evidence[], targetId: string): PanelState {
    const sources = evidence.filter(isCodeEvidence);
    const target = evidence.find(e => e.id === targetId);
    return {
        evidence,
        sources,
        activeSourceId: target && isCodeEvidence(target) ? target.id : sources[0]?.id ?? null,
        activeHighlight: 0,
        view: target && isGraphEvidence(target) ? "graph" : "code"
    };
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

/** Opens a graph node's source range, reusing the file's tab when it is already evidence. */
export function focusNode(state: PanelState, node: GraphNode): PanelState {
    if (!node.fileId) return state;
    const range = nodeLocation(node);
    const existing = state.sources.find(s => s.fileId === node.fileId);

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

    const path = node.filePath ?? "";
    const source: CodeEvidence = {
        type: "code",
        id: `NODE_${node.id}`,
        fileId: node.fileId,
        fileName: path.split("/").pop() || node.label,
        filePath: path,
        language: "plaintext",
        highlights: range ? [range] : [],
        symbols: [node.label]
    };
    return {
        ...state,
        sources: [...state.sources, source],
        activeSourceId: source.id,
        activeHighlight: 0,
        view: "code"
    };
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
