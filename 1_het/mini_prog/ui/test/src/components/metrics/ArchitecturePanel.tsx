import { Box, ButtonBase, Typography } from "@mui/material";
import { MUTED, NAVY, fileName, formatDecimal, formatNumber } from "./format";
import type { FileMetric, RepositorySummary } from "./types";

type Props = {
    summary: RepositorySummary,
    graphAvailable: boolean,
    connected: FileMetric[],
    onOpenFile: (path: string) => void
};

function Stat({ label, value }: { label: string, value: string }) {
    return (
        <Box>
            <Typography sx={{ fontSize: 12, color: MUTED }}>{label}</Typography>
            <Typography sx={{ fontSize: 20, fontWeight: 600, color: NAVY, fontVariantNumeric: "tabular-nums" }}>{value}</Typography>
        </Box>
    );
}

export function ArchitecturePanel({ summary, graphAvailable, connected, onOpenFile }: Props) {
    if (!graphAvailable) {
        return (
            <Typography sx={{ fontSize: 13, color: MUTED }}>
                Graph metrics are not available for this analysis. Static metrics above are still valid; run the analysis again once the knowledge graph is reachable.
            </Typography>
        );
    }

    const maxTotal = Math.max(1, ...connected.map(f => (f.fanIn ?? 0) + (f.fanOut ?? 0)));

    return (
        <Box>
            <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 2, mb: 2.5 }}>
                <Stat label="File dependencies" value={formatNumber(summary.dependencyCount)} />
                <Stat label="Avg fan-in" value={formatDecimal(summary.averageFanIn)} />
                <Stat label="Avg fan-out" value={formatDecimal(summary.averageFanOut)} />
                <Stat label="Dependency cycles" value={formatNumber(summary.cycleCount)} />
                <Stat label="Max depth" value={formatNumber(summary.maxDependencyDepth)} />
            </Box>

            <Typography sx={{ fontSize: 13, fontWeight: 600, color: "#334155", mb: 1 }}>Most connected components</Typography>
            {connected.length === 0 && <Typography sx={{ fontSize: 13, color: MUTED }}>No call dependencies between files were found.</Typography>}
            <Box component="ol" sx={{ listStyle: "none", p: 0, m: 0, display: "flex", flexDirection: "column", gap: 0.5 }}>
                {connected.map(file => {
                    const fanIn = file.fanIn ?? 0;
                    const fanOut = file.fanOut ?? 0;
                    return (
                        <li key={file.id}>
                            <ButtonBase onClick={() => onOpenFile(file.path)} title={file.path} sx={{ width: "100%", height: "auto", display: "grid", gridTemplateColumns: "minmax(0, 1fr) 140px auto", alignItems: "center", gap: 1.5, px: 1, py: 0.75, borderRadius: 1.5, textAlign: "left", "&:hover": { bgcolor: "#eef4fb" } }}>
                                <Typography sx={{ fontSize: 13, fontWeight: 500, color: "#334155", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{fileName(file.path)}</Typography>
                                <Box aria-hidden sx={{ display: "flex", gap: "2px", height: 8 }}>
                                    <Box sx={{ width: `${(fanIn / maxTotal) * 100}%`, bgcolor: "#0077b6", borderRadius: "4px 0 0 4px" }} />
                                    <Box sx={{ width: `${(fanOut / maxTotal) * 100}%`, bgcolor: "#9cc5ee", borderRadius: "0 4px 4px 0" }} />
                                </Box>
                                <Typography sx={{ fontSize: 12, color: "#334155", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                                    fan-in {fanIn} · fan-out {fanOut}
                                </Typography>
                            </ButtonBase>
                        </li>
                    );
                })}
            </Box>
            {connected.length > 0 && (
                <Box sx={{ display: "flex", gap: 2, mt: 1, alignItems: "center" }} aria-label="Legend">
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}><Box sx={{ width: 12, height: 8, bgcolor: "#0077b6", borderRadius: "2px" }} /><Typography sx={{ fontSize: 12, color: MUTED }}>Fan-in (files depending on it)</Typography></Box>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}><Box sx={{ width: 12, height: 8, bgcolor: "#9cc5ee", borderRadius: "2px" }} /><Typography sx={{ fontSize: 12, color: MUTED }}>Fan-out (files it depends on)</Typography></Box>
                </Box>
            )}
            {summary.cycles.length > 0 && (
                <Box sx={{ mt: 2 }}>
                    <Typography sx={{ fontSize: 13, fontWeight: 600, color: "#334155", mb: 0.5 }}>Dependency cycles</Typography>
                    {summary.cycles.slice(0, 5).map((cycle, i) => (
                        <Typography key={i} sx={{ fontSize: 12, color: "#475569", wordBreak: "break-all" }}>
                            {cycle.length} files: {cycle.map(fileName).join(", ")}
                        </Typography>
                    ))}
                </Box>
            )}
        </Box>
    );
}
