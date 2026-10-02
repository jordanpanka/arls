import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import CloseIcon from "@mui/icons-material/Close";
import CodeIcon from "@mui/icons-material/Code";
import FullscreenIcon from "@mui/icons-material/Fullscreen";
import FullscreenExitIcon from "@mui/icons-material/FullscreenExit";
import { Box, CircularProgress, IconButton, Paper, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from "@mui/material";
import { lazy, Suspense } from "preact/compat";
import { CodeEvidenceView } from "./CodeEvidenceView";
import { activeSource, focusNode, panelGraph, selectSource, type PanelState, type PanelView } from "./panelState";

type EvidencePanelProps = {
    projectId: number,
    state: PanelState,
    fullscreen: boolean,
    onChange: (state: PanelState) => void,
    onToggleFullscreen: () => void,
    onClose: () => void
}

const HEADER_H = 48;
const iconButton = { width: 32, height: 32, color: "#03045e" };
const toggleButton = {
    height: 30,
    px: 1.25,
    gap: 0.75,
    textTransform: "none",
    fontSize: 13,
    lineHeight: 1,
    color: "#475569",
    border: 0,
    borderRadius: "6px !important",
    // A globális button stílusok (hover keret, fókusz outline) ne rajzoljanak keretet.
    "&:hover": { borderColor: "transparent", bgcolor: "#eef2f7" },
    "&:focus": { outline: "none" },
    "&.Mui-focusVisible": { outline: "2px solid #88B8F9" },
    "&.Mui-selected": { bgcolor: "#e3effa", color: "#03045e", fontWeight: 600 },
    "&.Mui-selected:hover": { bgcolor: "#d6e7f7" }
};

const GraphEvidenceView = lazy(() => import("./GraphEvidenceView").then(m => ({ default: m.GraphEvidenceView })));

export function EvidencePanel({ projectId, state, fullscreen, onChange, onToggleFullscreen, onClose }: EvidencePanelProps) {
    const graph = panelGraph(state);
    const source = activeSource(state);

    return (
        <Paper
            square
            elevation={0}
            role="complementary"
            aria-label="Evidence panel"
            sx={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, bgcolor: "white" }}
        >
            <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, px: 2, height: HEADER_H, flexShrink: 0, borderBottom: "1px solid #e5e7eb", bgcolor: "#f8fafc" }}>
                <Typography sx={{ fontWeight: 600, fontSize: 15, lineHeight: 1, color: "#03045e", fontFamily: "'Inter', sans-serif" }}>
                    Evidence
                </Typography>
                <Box aria-hidden sx={{ width: "1px", height: 24, bgcolor: "#d7e3f1", flexShrink: 0 }} />
                <ToggleButtonGroup
                    size="small"
                    exclusive
                    sx={{ gap: 0.5, "& .MuiToggleButtonGroup-grouped": { border: 0, ml: 0 } }}
                    value={state.view}
                    onChange={(_, view: PanelView | null) => view && onChange({ ...state, view })}
                    aria-label="Evidence view"
                >
                    <ToggleButton value="code" disabled={state.sources.length === 0} sx={toggleButton}>
                        <CodeIcon sx={{ fontSize: 16 }} />Code
                    </ToggleButton>
                    <ToggleButton value="graph" disabled={!graph} sx={toggleButton}>
                        <AccountTreeOutlinedIcon sx={{ fontSize: 16 }} />Graph
                    </ToggleButton>
                </ToggleButtonGroup>
                <Box sx={{ flex: 1 }} />
                <Tooltip title={fullscreen ? "Exit fullscreen" : "Fullscreen"}>
                    <IconButton size="small" aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen"} onClick={onToggleFullscreen} sx={iconButton}>
                        {fullscreen ? <FullscreenExitIcon fontSize="small" /> : <FullscreenIcon fontSize="small" />}
                    </IconButton>
                </Tooltip>
                <Tooltip title="Close">
                    <IconButton size="small" aria-label="Close evidence panel" onClick={onClose} sx={iconButton}>
                        <CloseIcon fontSize="small" />
                    </IconButton>
                </Tooltip>
            </Box>
            <Box sx={{ flex: 1, minHeight: 0 }}>
                {state.view === "code" ? (
                    <CodeEvidenceView
                        projectId={projectId}
                        sources={state.sources}
                        source={source}
                        activeHighlight={state.activeHighlight}
                        onSelectSource={id => onChange(selectSource(state, id))}
                        onHighlightChange={index => onChange({ ...state, activeHighlight: index })}
                    />
                ) : (
                    <Suspense fallback={<Box sx={{ p: 3 }}><CircularProgress size={20} /></Box>}>
                        <GraphEvidenceView graph={graph} onOpenNode={node => onChange(focusNode(state, node))} />
                    </Suspense>
                )}
            </Box>
        </Paper>
    );
}
