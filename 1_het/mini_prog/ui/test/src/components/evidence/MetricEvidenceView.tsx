import CodeIcon from "@mui/icons-material/Code";
import { Box, Button, Chip, Typography } from "@mui/material";
import { Fragment } from "preact";
import { useEffect, useRef } from "preact/hooks";
import type { MetricEvidence, MetricItem } from "./types";

type MetricEvidenceViewProps = {
    metrics: MetricEvidence[],
    activeId?: string | null,
    onOpenCode: (metric: MetricEvidence) => void
}

const SCOPE_LABEL: Record<MetricEvidence["scope"], string> = {
    repository: "Repository",
    file: "File",
    function: "Function"
};

export function formatMetricValue(item: MetricItem): string {
    if (item.value === null || item.value === undefined) return "Not available";
    const value = Number.isInteger(item.value) ? item.value.toLocaleString("en-US") : item.value.toFixed(2);
    return item.unit ? `${value} ${item.unit}` : value;
}

function MetricCard({ metric, active, onOpenCode }: { metric: MetricEvidence, active: boolean, onOpenCode: () => void }) {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const card = ref.current;
        const scroller = card?.parentElement;
        if (!active || !card || !scroller) return;
        const top = card.offsetTop - scroller.offsetTop;
        const bottom = top + card.offsetHeight;
        if (top < scroller.scrollTop) scroller.scrollTop = top - 16;
        else if (bottom > scroller.scrollTop + scroller.clientHeight) scroller.scrollTop = bottom - scroller.clientHeight + 16;
    }, [active]);

    const location = metric.filePath
        ? `${metric.filePath}${metric.startLine ? `:${metric.startLine}–${metric.endLine ?? metric.startLine}` : ""}`
        : null;

    return (
        <Box
            ref={ref}
            data-testid={`metric-card-${metric.id}`}
            sx={{ border: "1px solid", borderColor: active ? "#88B8F9" : "#e5e7eb", borderRadius: 2, p: 1.5, bgcolor: "white" }}
        >
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.5 }}>
                <Chip label={metric.id} size="small" sx={{ height: 20, fontSize: 11, fontWeight: 600, bgcolor: "#e3effa", color: "#03045e" }} />
                <Typography sx={{ fontWeight: 600, fontSize: 14, color: "#03045e", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {metric.title}
                </Typography>
                <Typography sx={{ fontSize: 12, color: "text.secondary", ml: "auto" }}>{SCOPE_LABEL[metric.scope]}</Typography>
            </Box>
            {location && <Typography sx={{ fontSize: 12, color: "#5b6b7f", mb: 1, wordBreak: "break-all" }}>{location}</Typography>}
            <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "1fr auto", columnGap: 2, rowGap: 0.5, m: 0 }}>
                {metric.items.map(item => (
                    <Fragment key={item.key}>
                        <Typography component="dt" sx={{ fontSize: 13, color: "#475569" }}>{item.label}</Typography>
                        <Typography component="dd" sx={{ fontSize: 13, m: 0, textAlign: "right", fontVariantNumeric: "tabular-nums", color: item.value === null ? "text.secondary" : "#334155" }}>
                            {formatMetricValue(item)}
                            {item.category && <Typography component="span" sx={{ fontSize: 11, color: "text.secondary", ml: 0.75 }}>{item.category}</Typography>}
                        </Typography>
                    </Fragment>
                ))}
            </Box>
            {metric.fileId && (
                <Button size="small" startIcon={<CodeIcon />} onClick={onOpenCode} sx={{ mt: 1, height: "auto", textTransform: "none", color: "#0077B6" }}>
                    Open in code
                </Button>
            )}
        </Box>
    );
}

export function MetricEvidenceView({ metrics, activeId, onOpenCode }: MetricEvidenceViewProps) {
    const first = metrics[0];
    const analyzed = first?.analyzedAt ? new Date(first.analyzedAt).toLocaleString() : null;

    return (
        <Box sx={{ height: "100%", overflow: "auto", p: 2, display: "flex", flexDirection: "column", gap: 1.5, bgcolor: "#f8fafc" }}>
            <Typography sx={{ fontSize: 12, color: "#5b6b7f" }}>
                Measured by static analysis and the knowledge graph{first?.analysisId ? ` (analysis #${first.analysisId}` : ""}
                {analyzed ? `, ${analyzed}` : ""}{first?.analysisId ? ")" : ""}. Categories are indicators, not verdicts.
            </Typography>
            {metrics.map(metric => (
                <MetricCard key={metric.id} metric={metric} active={metric.id === activeId} onOpenCode={() => onOpenCode(metric)} />
            ))}
        </Box>
    );
}
