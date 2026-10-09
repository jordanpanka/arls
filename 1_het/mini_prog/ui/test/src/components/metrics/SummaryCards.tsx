import { Box, Tooltip, Typography } from "@mui/material";
import { BORDER, MUTED, NAVY, formatDecimal, formatNumber } from "./format";
import type { MetricsThresholds, RepositorySummary } from "./types";

type Card = { label: string, value: string, detail: string, hint?: string };

function cards(summary: RepositorySummary, thresholds: MetricsThresholds): Card[] {
    return [
        {
            label: "Lines of code",
            value: formatNumber(summary.totalNloc),
            detail: `${formatNumber(summary.totalFiles)} files · ${formatNumber(summary.totalFunctions)} functions`,
            hint: "Non-comment, non-blank lines (NLOC) measured by Lizard."
        },
        {
            label: "Avg complexity",
            value: formatDecimal(summary.averageComplexity),
            detail: `max ${formatNumber(summary.maxComplexity)}`,
            hint: "Mean cyclomatic complexity over all functions."
        },
        {
            label: "High complexity functions",
            value: formatNumber(summary.highComplexityFunctionCount),
            detail: `CCN above ${thresholds.highComplexityAbove}`
        },
        {
            label: "Long functions",
            value: formatNumber(summary.longFunctionCount),
            detail: `more than ${thresholds.longFunctionNloc} NLOC`
        },
        {
            label: "File dependencies",
            value: formatNumber(summary.dependencyCount),
            detail: summary.cycleCount === null ? "graph metrics unavailable" : `${formatNumber(summary.cycleCount)} cycles`,
            hint: "Distinct file-to-file call dependencies from the knowledge graph."
        }
    ];
}

export function SummaryCards({ summary, thresholds }: { summary: RepositorySummary, thresholds: MetricsThresholds }) {
    return (
        <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 2 }}>
            {cards(summary, thresholds).map(card => {
                const body = (
                    <Box key={card.label} data-testid={`summary-${card.label}`} sx={{ bgcolor: "white", border: `1px solid ${BORDER}`, borderRadius: "14px", px: 2.5, py: 2 }}>
                        <Typography sx={{ fontSize: 12, fontWeight: 600, letterSpacing: 0.6, textTransform: "uppercase", color: MUTED }}>{card.label}</Typography>
                        <Typography sx={{ fontFamily: "'Inter', sans-serif", fontSize: 30, fontWeight: 600, color: NAVY, lineHeight: 1.2, mt: 0.5, fontVariantNumeric: "tabular-nums" }}>{card.value}</Typography>
                        <Typography sx={{ fontSize: 12, color: MUTED, mt: 0.5 }}>{card.detail}</Typography>
                    </Box>
                );
                return card.hint ? <Tooltip key={card.label} title={card.hint} placement="bottom-start">{body}</Tooltip> : body;
            })}
        </Box>
    );
}
