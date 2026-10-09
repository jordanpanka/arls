import CloseIcon from "@mui/icons-material/Close";
import { Alert, Box, CircularProgress, Drawer, IconButton, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { lazy, Suspense } from "preact/compat";
import { useEffect, useState } from "preact/hooks";
import { loadProjectFile } from "../evidence/evidenceApi";
import type { ProjectFile } from "../evidence/types";
import { CATEGORY_COLORS, CATEGORY_LABELS, MUTED, NAVY, fileName, formatDecimal, formatNumber } from "./format";
import { metricsApi } from "./metricsApi";
import type { FileMetricsDetail, FunctionMetric } from "./types";

const CodeViewer = lazy(() => import("../evidence/CodeViewer").then(m => ({ default: m.CodeViewer })));

type Props = { projectId: number, path: string | null, onClose: () => void };

type DetailState =
    | { status: "loading" }
    | { status: "loaded", detail: FileMetricsDetail }
    | { status: "error", message: string };

type CodeState =
    | { status: "idle" }
    | { status: "loading" }
    | { status: "loaded", file: ProjectFile }
    | { status: "error", message: string };

const cellSx = { fontSize: 13, py: 0.75, borderColor: "#eef2f7", fontVariantNumeric: "tabular-nums" };

function Fact({ label, value }: { label: string, value: string }) {
    return (
        <Box sx={{ display: "flex", justifyContent: "space-between", gap: 2, py: 0.5, borderBottom: "1px solid #eef2f7" }}>
            <Typography sx={{ fontSize: 13, color: "#475569" }}>{label}</Typography>
            <Typography sx={{ fontSize: 13, fontWeight: 600, color: "#334155", fontVariantNumeric: "tabular-nums" }}>{value}</Typography>
        </Box>
    );
}

export function FileMetricsDrawer({ projectId, path, onClose }: Props) {
    const [state, setState] = useState<DetailState>({ status: "loading" });
    const [selected, setSelected] = useState<FunctionMetric | null>(null);
    const [code, setCode] = useState<CodeState>({ status: "idle" });

    useEffect(() => {
        if (!path) return;
        let cancelled = false;
        setState({ status: "loading" });
        setSelected(null);
        setCode({ status: "idle" });
        metricsApi.fileDetail(projectId, path)
            .then(detail => !cancelled && setState({ status: "loaded", detail }))
            .catch(error => !cancelled && setState({ status: "error", message: error.message }));
        return () => { cancelled = true; };
    }, [projectId, path]);

    function openFunction(fn: FunctionMetric) {
        setSelected(fn);
        if (fn.fileId === null) {
            setCode({ status: "error", message: "The source file is no longer stored for this project." });
            return;
        }
        if (code.status === "loaded" && code.file.fileId === String(fn.fileId)) return;
        setCode({ status: "loading" });
        loadProjectFile(projectId, String(fn.fileId))
            .then(file => setCode({ status: "loaded", file }))
            .catch(error => setCode({ status: "error", message: error.message }));
    }

    const detail = state.status === "loaded" ? state.detail : null;
    const file = detail?.file;

    return (
        <Drawer anchor="right" open={!!path} onClose={onClose} PaperProps={{ sx: { width: "min(760px, 92vw)" } }}>
            <Box role="dialog" aria-label="File metrics" sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1, px: 2.5, py: 1.5, borderBottom: "1px solid #e5e7eb", bgcolor: "#f8fafc" }}>
                    <Box sx={{ minWidth: 0 }}>
                        <Typography sx={{ fontFamily: "'Inter', sans-serif", fontWeight: 600, fontSize: 17, color: NAVY }}>{path ? fileName(path) : ""}</Typography>
                        <Typography sx={{ fontSize: 12, color: MUTED, wordBreak: "break-all" }}>{path}</Typography>
                    </Box>
                    <IconButton aria-label="Close file metrics" onClick={onClose} sx={{ ml: "auto", height: "auto", color: NAVY }}>
                        <CloseIcon />
                    </IconButton>
                </Box>

                <Box sx={{ flex: 1, overflow: "auto", p: 2.5 }}>
                    {state.status === "loading" && <Box sx={{ display: "flex", gap: 1.5, alignItems: "center" }}><CircularProgress size={20} /><Typography>Loading file metrics…</Typography></Box>}
                    {state.status === "error" && <Alert severity="error">{state.message}</Alert>}

                    {file && detail && (
                        <>
                            <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", columnGap: 4, mb: 3 }}>
                                <Box>
                                    <Fact label="Lines of code (NLOC)" value={formatNumber(file.nloc)} />
                                    <Fact label="Functions" value={formatNumber(file.functionCount)} />
                                    <Fact label="Class-like declarations" value={formatNumber(file.classCount)} />
                                    <Fact label="Average complexity" value={formatDecimal(file.averageComplexity)} />
                                    <Fact label="Maximum complexity" value={`${formatNumber(file.maxComplexity)}${file.complexityCategory ? ` (${CATEGORY_LABELS[file.complexityCategory]})` : ""}`} />
                                </Box>
                                <Box>
                                    <Fact label="High-complexity functions" value={formatNumber(file.highComplexityFunctionCount)} />
                                    <Fact label="Long functions" value={formatNumber(file.longFunctionCount)} />
                                    <Fact label="Functions with many parameters" value={formatNumber(file.manyParameterFunctionCount)} />
                                    <Fact label="Fan-in / fan-out" value={`${formatNumber(file.fanIn)} / ${formatNumber(file.fanOut)}`} />
                                    <Fact label="Import statements" value={formatNumber(file.importCount)} />
                                </Box>
                            </Box>

                            <Typography sx={{ fontWeight: 600, fontSize: 14, color: NAVY, mb: 1 }}>Functions</Typography>
                            {detail.functions.length === 0 ? (
                                <Typography sx={{ fontSize: 13, color: MUTED }}>Lizard found no functions in this file.</Typography>
                            ) : (
                                <Table size="small" aria-label="Function metrics">
                                    <TableHead>
                                        <TableRow>
                                            {["Function", "CC", "NLOC", "Params", "Fan-in", "Fan-out", "Lines"].map((h, i) => (
                                                <TableCell key={h} align={i === 0 ? "left" : "right"} sx={{ ...cellSx, fontWeight: 600, color: "#475569" }}>{h}</TableCell>
                                            ))}
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {detail.functions.map(fn => (
                                            <TableRow key={fn.id} hover selected={selected?.id === fn.id} onClick={() => openFunction(fn)} sx={{ cursor: "pointer" }} data-testid={`function-row-${fn.name}`}>
                                                <TableCell sx={{ ...cellSx, maxWidth: 260 }} title={fn.longName}>
                                                    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                                                        <Box aria-hidden sx={{ width: 10, height: 10, borderRadius: "3px", flexShrink: 0, bgcolor: CATEGORY_COLORS[fn.complexityCategory] }} />
                                                        <Typography sx={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                            {fn.className ? `${fn.className}.` : ""}{fn.name}()
                                                        </Typography>
                                                    </Box>
                                                </TableCell>
                                                <TableCell align="right" sx={{ ...cellSx, fontWeight: 600 }} title={CATEGORY_LABELS[fn.complexityCategory]}>{fn.cyclomaticComplexity}</TableCell>
                                                <TableCell align="right" sx={{ ...cellSx, color: fn.isLong ? NAVY : undefined, fontWeight: fn.isLong ? 600 : 400 }}>{fn.nloc}</TableCell>
                                                <TableCell align="right" sx={{ ...cellSx, color: fn.hasManyParameters ? NAVY : undefined, fontWeight: fn.hasManyParameters ? 600 : 400 }}>{fn.parameterCount}</TableCell>
                                                <TableCell align="right" sx={cellSx}>{formatNumber(fn.fanIn)}</TableCell>
                                                <TableCell align="right" sx={cellSx}>{formatNumber(fn.fanOut)}</TableCell>
                                                <TableCell align="right" sx={{ ...cellSx, color: MUTED }}>{fn.startLine}–{fn.endLine}</TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            )}

                            {selected && (
                                <Box sx={{ mt: 3 }}>
                                    <Typography sx={{ fontWeight: 600, fontSize: 14, color: NAVY, mb: 1 }}>
                                        {selected.className ? `${selected.className}.` : ""}{selected.name}() · lines {selected.startLine}–{selected.endLine}
                                    </Typography>
                                    {code.status === "loading" && <CircularProgress size={20} />}
                                    {code.status === "error" && <Alert severity="warning">{code.message}</Alert>}
                                    {code.status === "loaded" && (
                                        <Box sx={{ height: 420, border: "1px solid #e5e7eb", borderRadius: 2, overflow: "hidden" }}>
                                            <Suspense fallback={<CircularProgress size={20} />}>
                                                <CodeViewer
                                                    path={`${projectId}/${code.file.fileId}/${code.file.filePath}`}
                                                    content={code.file.content}
                                                    language={code.file.language}
                                                    highlights={[{ startLine: selected.startLine, endLine: selected.endLine }]}
                                                    activeHighlight={0}
                                                />
                                            </Suspense>
                                        </Box>
                                    )}
                                </Box>
                            )}
                        </>
                    )}
                </Box>
            </Box>
        </Drawer>
    );
}
