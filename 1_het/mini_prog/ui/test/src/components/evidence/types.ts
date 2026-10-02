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
    score?: number | null
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
    type: string
}

export type GraphEvidence = {
    type: "graph",
    id: string,
    nodes: GraphNode[],
    edges: GraphEdge[]
}

export type Evidence = CodeEvidence | GraphEvidence;

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
            (e.type === "graph" && Array.isArray(e.nodes) && Array.isArray(e.edges))));
}
