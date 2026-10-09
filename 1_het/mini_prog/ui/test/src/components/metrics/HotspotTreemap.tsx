import { Box, Typography } from "@mui/material";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { CATEGORY_COLORS, CATEGORY_LABELS, CATEGORY_TEXT, MUTED, fileName, formatNumber } from "./format";
import { squarify } from "./treemap";
import type { ComplexityCategory, FileMetric } from "./types";

const HEIGHT = 320;
const MAX_FILES = 80;
const GAP = 2;
const ORDER: ComplexityCategory[] = ["Low", "Moderate", "High", "VeryHigh"];

type Props = { files: FileMetric[], onOpenFile: (path: string) => void };

export function HotspotTreemap({ files, onOpenFile }: Props) {
    const container = useRef<HTMLDivElement>(null);
    const [width, setWidth] = useState(800);
    const [hover, setHover] = useState<FileMetric | null>(null);

    useEffect(() => {
        const element = container.current;
        if (!element || typeof ResizeObserver === "undefined") return;
        const observer = new ResizeObserver(entries => setWidth(Math.max(200, entries[0].contentRect.width)));
        observer.observe(element);
        return () => observer.disconnect();
    }, []);

    const largest = useMemo(() => [...files].sort((a, b) => b.nloc - a.nloc).slice(0, MAX_FILES), [files]);
    const rects = useMemo(
        () => squarify(largest.map(f => ({ value: f.nloc, item: f })), width, HEIGHT),
        [largest, width]
    );

    if (rects.length === 0) {
        return <Typography sx={{ fontSize: 13, color: MUTED }}>No files with code to display.</Typography>;
    }

    return (
        <Box>
            <Box ref={container} sx={{ position: "relative", width: "100%", height: HEIGHT }}>
                <svg width={width} height={HEIGHT} role="img" aria-label="Files sized by lines of code and colored by maximum cyclomatic complexity" style={{ display: "block" }}>
                    {rects.map(rect => {
                        const file = rect.item;
                        const category = file.complexityCategory ?? "Low";
                        const w = Math.max(0, rect.width - GAP);
                        const h = Math.max(0, rect.height - GAP);
                        const showLabel = w > 70 && h > 30;
                        return (
                            <g
                                key={file.id}
                                data-testid={`treemap-${file.path}`}
                                style={{ cursor: "pointer" }}
                                onClick={() => onOpenFile(file.path)}
                                onMouseEnter={() => setHover(file)}
                                onMouseLeave={() => setHover(null)}
                            >
                                <rect
                                    x={rect.x} y={rect.y} width={w} height={h} rx={4}
                                    fill={file.complexityCategory ? CATEGORY_COLORS[category] : "#e5e7eb"}
                                    stroke={hover?.id === file.id ? "#88B8F9" : "none"} strokeWidth={2}
                                />
                                {showLabel && (
                                    <>
                                        <text x={rect.x + 8} y={rect.y + 18} fontSize={12} fontWeight={600} fill={CATEGORY_TEXT[category]}>
                                            {fileName(file.path).slice(0, Math.floor(w / 7))}
                                        </text>
                                        {h > 46 && (
                                            <text x={rect.x + 8} y={rect.y + 34} fontSize={11} fill={CATEGORY_TEXT[category]} opacity={0.85}>
                                                {formatNumber(file.nloc)} LOC · max CC {formatNumber(file.maxComplexity)}
                                            </text>
                                        )}
                                    </>
                                )}
                                <title>{`${file.path}\n${formatNumber(file.nloc)} LOC, max CC ${formatNumber(file.maxComplexity)}`}</title>
                            </g>
                        );
                    })}
                </svg>
                {hover && (
                    <Box role="status" sx={{ position: "absolute", top: 8, right: 8, bgcolor: "white", border: "1px solid #d7e3f1", borderRadius: 1.5, px: 1.5, py: 1, pointerEvents: "none", maxWidth: 320, boxShadow: "0 2px 8px rgba(3,4,94,0.08)" }}>
                        <Typography sx={{ fontSize: 13, fontWeight: 600, color: "#03045e", wordBreak: "break-all" }}>{hover.path}</Typography>
                        <Typography sx={{ fontSize: 12, color: "#334155" }}>
                            {formatNumber(hover.nloc)} LOC · {formatNumber(hover.functionCount)} functions · max CC {formatNumber(hover.maxComplexity)}
                        </Typography>
                    </Box>
                )}
            </Box>
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2, mt: 1.5, alignItems: "center" }} aria-label="Legend">
                <Typography sx={{ fontSize: 12, color: MUTED }}>Size: lines of code. Color: highest function complexity (indicator).</Typography>
                {ORDER.map(category => (
                    <Box key={category} sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
                        <Box aria-hidden sx={{ width: 12, height: 12, borderRadius: "3px", bgcolor: CATEGORY_COLORS[category] }} />
                        <Typography sx={{ fontSize: 12, color: "#334155" }}>{CATEGORY_LABELS[category]}</Typography>
                    </Box>
                ))}
                {files.length > MAX_FILES && (
                    <Typography sx={{ fontSize: 12, color: MUTED }}>Showing the {MAX_FILES} largest of {files.length} files.</Typography>
                )}
            </Box>
        </Box>
    );
}
