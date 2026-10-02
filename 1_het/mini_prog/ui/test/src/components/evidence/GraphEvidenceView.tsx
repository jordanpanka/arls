import { Alert, Box, Typography } from "@mui/material";
import cytoscape from "cytoscape";
import { useEffect, useRef, useState } from "preact/hooks";
import type { GraphEvidence, GraphNode } from "./types";

type GraphEvidenceViewProps = {
    graph: GraphEvidence | undefined,
    onOpenNode: (node: GraphNode) => void
}

const STYLE = [
    {
        selector: "node",
        style: {
            "shape": "round-rectangle",
            "label": "data(label)",
            "width": "label",
            "height": "label",
            "padding": "10px",
            "text-valign": "center",
            "text-halign": "center",
            "font-family": "Inter, sans-serif",
            "font-size": 12,
            "background-color": "#eef4fb",
            "border-width": 1,
            "border-color": "#88B8F9",
            "color": "#334155"
        }
    },
    {
        selector: "node.evidence",
        style: { "background-color": "#03045e", "border-color": "#03045e", "color": "#ffffff", "font-weight": 600 }
    },
    {
        selector: "node.unlocated",
        style: { "border-style": "dashed", "opacity": 0.75 }
    },
    {
        selector: "node:selected",
        style: { "border-width": 3, "border-color": "#0077B6" }
    },
    {
        selector: "edge",
        style: {
            "curve-style": "bezier",
            "width": 1.5,
            "line-color": "#9bb7d4",
            "target-arrow-color": "#9bb7d4",
            "target-arrow-shape": "triangle",
            "label": "data(label)",
            "font-size": 9,
            "color": "#5b6b7f",
            "text-background-color": "#ffffff",
            "text-background-opacity": 1,
            "text-background-padding": "2px"
        }
    }
];

export function GraphEvidenceView({ graph, onOpenNode }: GraphEvidenceViewProps) {
    const container = useRef<HTMLDivElement>(null);
    const openRef = useRef(onOpenNode);
    const [notice, setNotice] = useState<string | null>(null);
    openRef.current = onOpenNode;

    useEffect(() => {
        if (!container.current || !graph || graph.nodes.length === 0) return;
        const nodes = new Map(graph.nodes.map(n => [n.id, n]));

        const cy = cytoscape({
            container: container.current,
            elements: [
                ...graph.nodes.map(n => ({
                    data: { id: n.id, label: n.label },
                    classes: [n.usedAsEvidence ? "evidence" : "context", n.fileId ? "located" : "unlocated"].join(" ")
                })),
                ...graph.edges
                    .filter(e => nodes.has(e.source) && nodes.has(e.target))
                    .map((e, i) => ({ data: { id: `edge-${i}`, source: e.source, target: e.target, label: e.type } }))
            ],
            style: STYLE as never,
            layout: { name: "breadthfirst", directed: true, padding: 24, spacingFactor: 1.15 },
            wheelSensitivity: 0.2,
            maxZoom: 2.5,
            minZoom: 0.2
        });

        cy.on("tap", "node", event => {
            const node = nodes.get(event.target.id());
            if (!node) return;
            if (!node.fileId) {
                setNotice(`No source location is recorded for ${node.label}. The graph node may be outdated or point outside this project.`);
                return;
            }
            setNotice(null);
            openRef.current(node);
        });
        cy.on("mouseover", "node.located", () => { if (container.current) container.current.style.cursor = "pointer"; });
        cy.on("mouseout", "node", () => { if (container.current) container.current.style.cursor = "default"; });

        const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => cy.resize()) : null;
        observer?.observe(container.current);

        return () => {
            observer?.disconnect();
            cy.destroy();
        };
    }, [graph]);

    if (!graph || graph.nodes.length === 0) {
        return <Alert severity="info" sx={{ m: 2 }}>No knowledge-graph relationships were found for this answer.</Alert>;
    }

    return (
        <Box sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 2, px: 2, minHeight: 40, flexShrink: 0, borderBottom: "1px solid #e5e7eb", flexWrap: "wrap" }}>
                <Legend color="#03045e" label="Used as evidence" />
                <Legend color="#eef4fb" border="#88B8F9" label="Context" />
                <Typography sx={{ fontSize: 12, color: "text.secondary", ml: "auto" }}>Click a node to open its source</Typography>
            </Box>
            {graph.edges.length === 0 && (
                <Alert severity="info" sx={{ mx: 2, mt: 1 }}>No relationships connect these nodes.</Alert>
            )}
            {notice && <Alert severity="warning" onClose={() => setNotice(null)} sx={{ mx: 2, mt: 1 }}>{notice}</Alert>}
            <Box ref={container} data-testid="graph-canvas" sx={{ flex: 1, minHeight: 240 }} />
        </Box>
    );
}

function Legend({ color, border, label }: { color: string, border?: string, label: string }) {
    return (
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
            <Box sx={{ width: 12, height: 12, borderRadius: "3px", bgcolor: color, border: `1px solid ${border ?? color}` }} />
            <Typography sx={{ fontSize: 12 }}>{label}</Typography>
        </Box>
    );
}
