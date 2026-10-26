import { Box, Typography } from "@mui/material";
import type { ExecutionInfo } from "../evidence/types";

const STATUS_COLORS: Record<string, string> = {
    verified: "#2e7d32",
    partially_verified: "#ed6c02",
    insufficient_evidence: "#b71c1c",
    unverified: "#6b7280"
};

const chipSx = {
    display: "inline-block",
    fontSize: 11,
    lineHeight: "18px",
    px: 0.75,
    borderRadius: 1,
    bgcolor: "#eef4fb",
    color: "#03045e",
    whiteSpace: "nowrap"
};

function label(value: string) {
    return value.replace(/_/g, " ");
}

function seconds(ms?: number | null) {
    return ms == null ? null : `${(ms / 1000).toFixed(1)} s`;
}

export function ExecutionSummary({ execution }: { execution: ExecutionInfo }) {
    const chips = [
        label(execution.strategy),
        execution.route ? `auto: ${label(execution.route.reason)}` : null,
        execution.toolCalls != null ? `${execution.toolCalls} tool calls` : null,
        execution.iterations != null ? `${execution.iterations} iterations` : null,
        seconds(execution.latencyMs),
        execution.stopReason ? `stop: ${label(execution.stopReason)}` : null
    ].filter((c): c is string => !!c);
    const trace = execution.trace ?? [];

    return (
        <Box sx={{ mx: "10px", mb: "8px", display: "flex", flexDirection: "column", gap: 0.5 }} aria-label="Execution summary">
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, alignItems: "center" }}>
                {execution.status && (
                    <Box component="span" sx={{ ...chipSx, bgcolor: STATUS_COLORS[execution.status] ?? "#6b7280", color: "white" }}>
                        {label(execution.status)}
                    </Box>
                )}
                {chips.map(chip => <Box key={chip} component="span" sx={chipSx}>{chip}</Box>)}
            </Box>
            {trace.length > 0 && (
                <details>
                    <summary style={{ fontSize: 12, cursor: "pointer", color: "#0077B6" }}>Retrieval steps</summary>
                    <Box component="ol" sx={{ m: 0, pl: 3 }}>
                        {trace.map((step, index) => (
                            <li key={index}>
                                <Typography component="span" sx={{ fontSize: 12 }}>
                                    {`#${step.iteration} ${step.tool} · ${Math.round(step.latencyMs)} ms`}
                                    {step.error ? ` · ${step.error.kind}` : step.evidence?.length ? ` · ${step.evidence.join(", ")}` : " · no evidence"}
                                    {step.cached ? " · cached" : ""}
                                </Typography>
                            </li>
                        ))}
                    </Box>
                </details>
            )}
        </Box>
    );
}
