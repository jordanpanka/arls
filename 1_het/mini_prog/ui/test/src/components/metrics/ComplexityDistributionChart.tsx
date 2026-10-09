import { Box, Typography } from "@mui/material";
import { useState } from "preact/hooks";
import { CATEGORY_COLORS, CATEGORY_LABELS, MUTED, NAVY, formatNumber } from "./format";
import type { DistributionBucket } from "./types";

const WIDTH = 480;
const HEIGHT = 220;
const PAD = { top: 24, right: 8, bottom: 44, left: 8 };

export function ComplexityDistributionChart({ buckets }: { buckets: DistributionBucket[] }) {
    const [hover, setHover] = useState<number | null>(null);
    const total = buckets.reduce((sum, b) => sum + b.count, 0);
    const max = Math.max(1, ...buckets.map(b => b.count));
    const plotHeight = HEIGHT - PAD.top - PAD.bottom;
    const slot = (WIDTH - PAD.left - PAD.right) / Math.max(buckets.length, 1);
    const barWidth = Math.min(72, slot * 0.6);

    if (total === 0) {
        return <Typography sx={{ fontSize: 13, color: MUTED }}>No functions were found to measure.</Typography>;
    }

    return (
        <Box sx={{ position: "relative" }}>
            <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" role="img" aria-label="Number of functions per cyclomatic complexity band" style={{ display: "block", maxHeight: 260 }}>
                <line x1={PAD.left} x2={WIDTH - PAD.right} y1={HEIGHT - PAD.bottom} y2={HEIGHT - PAD.bottom} stroke="#d7e3f1" strokeWidth={1} />
                {buckets.map((bucket, i) => {
                    const h = (bucket.count / max) * plotHeight;
                    const x = PAD.left + slot * i + (slot - barWidth) / 2;
                    const y = HEIGHT - PAD.bottom - h;
                    const r = Math.min(4, h / 2);
                    const path = h > 0
                        ? `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + barWidth - r},${y} Q${x + barWidth},${y} ${x + barWidth},${y + r} L${x + barWidth},${y + h} Z`
                        : "";
                    const share = Math.round((bucket.count / total) * 100);
                    return (
                        <g key={bucket.category} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} data-testid={`bucket-${bucket.category}`}>
                            <rect x={PAD.left + slot * i} y={PAD.top - 20} width={slot} height={plotHeight + 20} fill="transparent" />
                            {path && <path d={path} fill={CATEGORY_COLORS[bucket.category]} opacity={hover === null || hover === i ? 1 : 0.55} />}
                            <text x={x + barWidth / 2} y={y - 6} textAnchor="middle" fontSize={13} fontWeight={600} fill={NAVY} style={{ fontVariantNumeric: "tabular-nums" }}>
                                {formatNumber(bucket.count)}
                            </text>
                            <text x={x + barWidth / 2} y={HEIGHT - PAD.bottom + 18} textAnchor="middle" fontSize={12} fill="#334155">CCN {bucket.label}</text>
                            <text x={x + barWidth / 2} y={HEIGHT - PAD.bottom + 34} textAnchor="middle" fontSize={11} fill={MUTED}>{CATEGORY_LABELS[bucket.category]}</text>
                            <title>{`${CATEGORY_LABELS[bucket.category]} (CCN ${bucket.label}): ${bucket.count} functions, ${share}%`}</title>
                        </g>
                    );
                })}
            </svg>
            {hover !== null && (
                <Box role="status" sx={{ position: "absolute", top: 0, right: 0, bgcolor: "white", border: "1px solid #d7e3f1", borderRadius: 1.5, px: 1.25, py: 0.5, fontSize: 12, color: "#334155", pointerEvents: "none" }}>
                    {CATEGORY_LABELS[buckets[hover].category]} · {formatNumber(buckets[hover].count)} functions ({Math.round((buckets[hover].count / total) * 100)}%)
                </Box>
            )}
        </Box>
    );
}
