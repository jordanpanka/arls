import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { Alert, Box, CircularProgress, IconButton, MenuItem, Select, Tab, Tabs, Typography } from "@mui/material";
import { lazy, Suspense } from "preact/compat";
import { useEffect, useState } from "preact/hooks";
import { FileLoadError, loadProjectFile } from "./evidenceApi";
import { formatRange, type CodeEvidence, type ProjectFile } from "./types";

const MAX_TABS = 4;

const CodeViewer = lazy(() => import("./CodeViewer").then(m => ({ default: m.CodeViewer })));

type LoadState =
    | { status: "loading" }
    | { status: "loaded", file: ProjectFile }
    | { status: "error", message: string };

function Spinner({ label }: { label: string }) {
    return <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, p: 3 }}><CircularProgress size={20} /><Typography>{label}</Typography></Box>;
}

type FileSelectorProps = {
    sources: CodeEvidence[],
    activeId: string,
    onSelect: (id: string) => void
}

const TOOLBAR_H = 40;
const caption = { fontSize: 13, lineHeight: 1, whiteSpace: "nowrap" };

function FileSelector({ sources, activeId, onSelect }: FileSelectorProps) {
    const active = sources.find(s => s.id === activeId);

    if (sources.length <= 1) {
        return (
            <Typography title={active?.filePath} sx={{ ...caption, px: 2, color: "#334155", overflow: "hidden", textOverflow: "ellipsis" }}>
                {active?.filePath || active?.fileName}
            </Typography>
        );
    }

    if (sources.length <= MAX_TABS) {
        return (
            <Tabs
                value={activeId}
                onChange={(_, value: string) => onSelect(value)}
                variant="scrollable"
                scrollButtons={false}
                sx={{
                    minHeight: TOOLBAR_H,
                    height: TOOLBAR_H,
                    maxWidth: "100%",
                    "& .MuiTabs-scroller": { maskImage: "linear-gradient(to right, black calc(100% - 20px), transparent)" },
                    "& .MuiTabs-flexContainer": { height: TOOLBAR_H },
                    "& .MuiTab-root": { minHeight: TOOLBAR_H, height: TOOLBAR_H, py: 0, px: 2, minWidth: 0, textTransform: "none", fontSize: 13, lineHeight: 1 }
                }}
            >
                {sources.map(s => <Tab key={s.id} value={s.id} label={s.fileName} title={s.filePath} />)}
            </Tabs>
        );
    }

    return (
        <Select
            size="small"
            variant="standard"
            disableUnderline
            value={activeId}
            onChange={e => onSelect(String((e.target as { value: unknown }).value))}
            inputProps={{ "aria-label": "Evidence file" }}
            sx={{ mx: 2, fontSize: 13, maxWidth: "100%" }}
        >
            {sources.map(s => <MenuItem key={s.id} value={s.id} sx={{ fontSize: 13 }}>{s.filePath || s.fileName}</MenuItem>)}
        </Select>
    );
}

type EvidenceNavigatorProps = {
    source: CodeEvidence,
    index: number,
    onChange: (index: number) => void
}

function EvidenceNavigator({ source, index, onChange }: EvidenceNavigatorProps) {
    const count = source.highlights.length;
    const current = source.highlights[index];
    if (!current) return null;

    const arrow = { width: 28, height: 28 };
    return (
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, pl: 0.5, pr: 1, flexShrink: 0, height: 24, borderLeft: "1px solid #e5e7eb" }}>
            <Typography sx={{ ...caption, color: "#03045e", fontWeight: 500, px: 1 }}>{formatRange(current)}</Typography>
            {count > 1 && (
                <>
                    <IconButton size="small" aria-label="Previous evidence" disabled={index === 0} onClick={() => onChange(index - 1)} sx={arrow}>
                        <ChevronLeftIcon fontSize="small" />
                    </IconButton>
                    <Typography sx={{ ...caption, color: "text.secondary", minWidth: 36, textAlign: "center" }}>{index + 1} / {count}</Typography>
                    <IconButton size="small" aria-label="Next evidence" disabled={index === count - 1} onClick={() => onChange(index + 1)} sx={arrow}>
                        <ChevronRightIcon fontSize="small" />
                    </IconButton>
                </>
            )}
        </Box>
    );
}

type CodeEvidenceViewProps = {
    projectId: number,
    sources: CodeEvidence[],
    source: CodeEvidence | undefined,
    activeHighlight: number,
    onSelectSource: (id: string) => void,
    onHighlightChange: (index: number) => void
}

export function CodeEvidenceView(props: CodeEvidenceViewProps) {
    const { source } = props;
    const [load, setLoad] = useState<LoadState>({ status: "loading" });
    const fileId = source?.fileId;

    useEffect(() => {
        if (!fileId) return;
        let cancelled = false;
        setLoad({ status: "loading" });
        loadProjectFile(props.projectId, fileId)
            .then(file => { if (!cancelled) setLoad({ status: "loaded", file }); })
            .catch(error => {
                if (!cancelled) setLoad({ status: "error", message: error instanceof FileLoadError ? error.message : "The file could not be loaded." });
            });
        return () => { cancelled = true; };
    }, [props.projectId, fileId]);

    if (!source) {
        return <Alert severity="info" sx={{ m: 2 }}>This answer has no code evidence.</Alert>;
    }

    let body;
    if (!fileId) {
        body = (
            <Alert severity="warning" sx={{ m: 2 }}>
                The source location for {source.filePath || source.fileName} isn't available. The file may no longer be stored for this project, or it was indexed before evidence support was added.
            </Alert>
        );
    } else if (load.status === "loading" || (load.status === "loaded" && load.file.fileId !== fileId)) {
        body = <Spinner label={`Loading ${source.fileName}…`} />;
    } else if (load.status === "error") {
        body = <Alert severity="error" sx={{ m: 2 }}>{load.message}</Alert>;
    } else {
        body = (
            <Suspense fallback={<Spinner label="Loading editor…" />}>
                <CodeViewer
                    path={`${props.projectId}/${load.file.fileId}/${load.file.filePath}`}
                    content={load.file.content}
                    language={load.file.language || source.language}
                    highlights={source.highlights}
                    activeHighlight={props.activeHighlight}
                />
            </Suspense>
        );
    }

    return (
        <Box sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
            <Box sx={{ display: "flex", alignItems: "center", height: TOOLBAR_H, flexShrink: 0, borderBottom: "1px solid #e5e7eb" }}>
                <Box sx={{ flex: 1, minWidth: 0, height: "100%", display: "flex", alignItems: "center" }}>
                    <FileSelector sources={props.sources} activeId={source.id} onSelect={props.onSelectSource} />
                </Box>
                <EvidenceNavigator source={source} index={props.activeHighlight} onChange={props.onHighlightChange} />
            </Box>
            <Box sx={{ flex: 1, minHeight: 0 }}>{body}</Box>
        </Box>
    );
}
