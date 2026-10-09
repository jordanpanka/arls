import InsightsIcon from "@mui/icons-material/Insights";
import RefreshIcon from "@mui/icons-material/Refresh";
import { Alert, Box, Button, CircularProgress, Typography } from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { ArchitecturePanel } from "./ArchitecturePanel";
import { ComplexFilesTable } from "./ComplexFilesTable";
import { ComplexityDistributionChart } from "./ComplexityDistributionChart";
import { FileMetricsDrawer } from "./FileMetricsDrawer";
import { HotspotTreemap } from "./HotspotTreemap";
import { MUTED, NAVY, formatDate, formatDuration, formatNumber } from "./format";
import { isNoAnalysis, metricsApi } from "./metricsApi";
import { Section } from "./Section";
import { SummaryCards } from "./SummaryCards";
import type { FileMetric, Hotspots, MetricsAnalysis, RepositoryMetrics } from "./types";

export const POLL_MS = 3000;

type Props = { projectId: number, projectName?: string };

type Loaded = { metrics: RepositoryMetrics, files: FileMetric[], dependencies: Hotspots };

type DashboardState =
    | { status: "loading" }
    | { status: "empty" }
    | { status: "error", message: string }
    | { status: "loaded", data: Loaded };

const IN_FLIGHT = ["Queued", "Running"];

const primaryButton = {
    height: "auto",
    textTransform: "none",
    fontWeight: 600,
    borderRadius: "10px",
    bgcolor: NAVY,
    px: 2,
    "&:hover": { bgcolor: "#0077B6" }
};

export function MetricsDashboard({ projectId, projectName }: Props) {
    const [state, setState] = useState<DashboardState>({ status: "loading" });
    const [running, setRunning] = useState<MetricsAnalysis | null>(null);
    const [lastFailure, setLastFailure] = useState<MetricsAnalysis | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);
    const [openPath, setOpenPath] = useState<string | null>(null);
    const timer = useRef<number | null>(null);

    const loadMetrics = useCallback(async () => {
        try {
            const [metrics, files, dependencies] = await Promise.all([
                metricsApi.repository(projectId),
                metricsApi.files(projectId),
                metricsApi.hotspots(projectId, "dependencies", 8)
            ]);
            setState({ status: "loaded", data: { metrics, files, dependencies } });
        } catch (error) {
            if (isNoAnalysis(error)) setState({ status: "empty" });
            else setState({ status: "error", message: (error as Error).message });
        }
    }, [projectId]);

    const refresh = useCallback(async (reloadMetrics: boolean) => {
        try {
            const status = await metricsApi.status(projectId);
            const latest = status.latest;
            const inFlight = latest && IN_FLIGHT.includes(latest.status) ? latest : null;
            setRunning(inFlight);
            setLastFailure(latest?.status === "Failed" ? latest : null);

            if (!status.latestUsable) setState({ status: "empty" });
            else if (reloadMetrics || !inFlight) await loadMetrics();
        } catch (error) {
            setState({ status: "error", message: (error as Error).message });
        }
    }, [projectId, loadMetrics]);

    useEffect(() => {
        setState({ status: "loading" });
        setRunning(null);
        setLastFailure(null);
        setActionError(null);
        setOpenPath(null);
        refresh(true);
    }, [projectId, refresh]);

    useEffect(() => {
        if (!running) return;
        timer.current = window.setTimeout(() => refresh(false), POLL_MS);
        return () => { if (timer.current) window.clearTimeout(timer.current); };
    }, [running, refresh]);

    async function analyze() {
        setActionError(null);
        try {
            const hasMetrics = state.status === "loaded";
            const response = await metricsApi.analyze(projectId, hasMetrics);
            if (IN_FLIGHT.includes(response.status)) {
                setRunning({ analysisId: response.analysisId, status: response.status } as MetricsAnalysis);
            } else {
                await refresh(true);
            }
        } catch (error) {
            setActionError((error as Error).message);
        }
    }

    const analysis = state.status === "loaded" ? state.data.metrics.analysis : null;

    return (
        <Box sx={{ flex: 1, minWidth: 0, height: "100%", overflow: "auto", bgcolor: "#f5f7fb" }}>
            <Box sx={{ maxWidth: 1400, mx: "auto", px: { xs: 2, md: 4 }, py: 3, display: "flex", flexDirection: "column", gap: 2.5 }}>
                <Box component="header" sx={{ display: "flex", alignItems: "flex-start", gap: 2, flexWrap: "wrap" }}>
                    <Box sx={{ minWidth: 0 }}>
                        <Typography component="h1" sx={{ fontFamily: "'Inter', sans-serif", fontWeight: 600, fontSize: 26, color: NAVY }}>Code Metrics</Typography>
                        <Typography sx={{ fontSize: 14, color: "#334155", mt: 0.25 }}>
                            {projectName ?? `Project ${projectId}`}
                            {analysis?.branch ? ` · ${analysis.branch}` : ""}
                            {analysis?.commitSha ? ` · ${analysis.commitSha.slice(0, 10)}` : ""}
                        </Typography>
                        {analysis && (
                            <Typography sx={{ fontSize: 12, color: MUTED, mt: 0.25 }}>
                                Last analyzed {formatDate(analysis.completedAt)} · {formatNumber(analysis.filesAnalyzed)} files analyzed, {formatNumber(analysis.filesSkipped)} skipped · {formatDuration(analysis.totalDurationMs)}
                            </Typography>
                        )}
                    </Box>
                    <Box sx={{ ml: "auto", display: "flex", alignItems: "center", gap: 1.5 }}>
                        {running && (
                            <Box role="status" sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                                <CircularProgress size={18} />
                                <Typography sx={{ fontSize: 13, color: "#334155" }}>Analysis {running.status === "Queued" ? "queued" : "running"}…</Typography>
                            </Box>
                        )}
                        {(state.status === "loaded" || state.status === "error") && (
                            <Button variant="contained" disableElevation startIcon={<RefreshIcon />} onClick={analyze} disabled={!!running} sx={primaryButton}>
                                Re-analyze
                            </Button>
                        )}
                    </Box>
                </Box>

                {actionError && <Alert severity="error" onClose={() => setActionError(null)}>{actionError}</Alert>}
                {lastFailure && !running && (
                    <Alert severity="error">The last analysis failed: {lastFailure.errorMessage ?? "unknown error"}. Previously stored metrics, if any, are still shown.</Alert>
                )}

                {state.status === "loading" && (
                    <Box role="status" sx={{ display: "flex", gap: 1.5, alignItems: "center", py: 6, justifyContent: "center" }}>
                        <CircularProgress size={22} /><Typography>Loading code metrics…</Typography>
                    </Box>
                )}

                {state.status === "error" && <Alert severity="error">{state.message}</Alert>}

                {state.status === "empty" && (
                    <Box sx={{ bgcolor: "white", border: "1px solid #e5e7eb", borderRadius: "14px", py: 8, px: 3, textAlign: "center" }}>
                        <InsightsIcon sx={{ fontSize: 40, color: "#88B8F9" }} />
                        <Typography sx={{ fontSize: 16, fontWeight: 600, color: NAVY, mt: 1 }}>No code metrics analysis has been run for this repository.</Typography>
                        <Typography sx={{ fontSize: 13, color: MUTED, mt: 0.5, mb: 2.5 }}>
                            The analysis measures complexity and size with Lizard and dependencies from the knowledge graph. It does not change the indexed data.
                        </Typography>
                        <Button variant="contained" disableElevation onClick={analyze} disabled={!!running} sx={primaryButton}>
                            {running ? "Analysis running…" : "Analyze Repository"}
                        </Button>
                    </Box>
                )}

                {state.status === "loaded" && (
                    <LoadedDashboard data={state.data} onOpenFile={setOpenPath} />
                )}
            </Box>

            <FileMetricsDrawer projectId={projectId} path={openPath} onClose={() => setOpenPath(null)} />
        </Box>
    );
}

function LoadedDashboard({ data, onOpenFile }: { data: Loaded, onOpenFile: (path: string) => void }) {
    const { metrics, files, dependencies } = data;
    const graphAvailable = metrics.analysis.graphStatus === "Completed";

    return (
        <>
            {metrics.analysis.status === "Partial" && (
                <Alert severity="warning">
                    Graph metrics could not be calculated ({metrics.analysis.errorMessage ?? "knowledge graph unavailable"}). Complexity and size metrics are complete.
                </Alert>
            )}

            <SummaryCards summary={metrics.summary} thresholds={metrics.thresholds} />

            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 2fr) minmax(0, 3fr)" }, gap: 2.5 }}>
                <Section title="Complexity distribution" subtitle="Functions per cyclomatic complexity band">
                    <ComplexityDistributionChart buckets={metrics.complexityDistribution} />
                </Section>
                <Section title="Architecture" subtitle="Call dependencies between files, from the knowledge graph">
                    <ArchitecturePanel summary={metrics.summary} graphAvailable={graphAvailable} connected={dependencies.files} onOpenFile={onOpenFile} />
                </Section>
            </Box>

            <Section title="Repository hotspots" subtitle="Click a file to see its function-level metrics">
                <HotspotTreemap files={files} onOpenFile={onOpenFile} />
            </Section>

            <Section title="Most complex files" subtitle="Sorted by maximum cyclomatic complexity; click a column to re-sort">
                <ComplexFilesTable files={files} onOpenFile={onOpenFile} />
            </Section>
        </>
    );
}
