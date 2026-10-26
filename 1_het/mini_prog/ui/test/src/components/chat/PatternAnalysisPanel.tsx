import { Box, Typography } from "@mui/material";
import type { AlternativeInfo, PatternAnalysisInfo, PatternEvidenceRef } from "../evidence/types";

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

const buttonStyle = {
    fontSize: 11,
    lineHeight: "18px",
    padding: "0 6px",
    borderRadius: 4,
    border: "none",
    background: "#eef4fb",
    color: "#03045e",
    cursor: "pointer",
    marginLeft: 4
};

const CONFIDENCE_COLORS: Record<string, string> = { high: "#2e7d32", medium: "#ed6c02", low: "#6b7280" };
const summaryStyle = { fontSize: 12, cursor: "pointer", color: "#0077B6" };
const textSx = { fontSize: 12 };

function label(value: string) {
    return value.replace(/_/g, " ");
}

function range(ref: PatternEvidenceRef) {
    if (!ref.start_line) return ref.file_path;
    return ref.end_line && ref.end_line !== ref.start_line ? `${ref.file_path}:${ref.start_line}-${ref.end_line}` : `${ref.file_path}:${ref.start_line}`;
}

function List({ items, prefix }: { items: string[], prefix?: string }) {
    if (!items.length) return null;
    return (
        <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
            {items.map(item => <li key={item}><Typography component="span" sx={textSx}>{prefix ? `${prefix}${item}` : item}</Typography></li>)}
        </Box>
    );
}

function EvidenceButtons({ ids, refs, onOpen }: { ids: string[], refs: PatternEvidenceRef[], onOpen?: (alias: string) => void }) {
    const aliases = [...new Set(refs.filter(r => ids.includes(r.id) && r.alias).map(r => r.alias as string))];
    if (!aliases.length) return null;
    return (
        <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mt: 0.25 }}>
            {aliases.map(alias => (
                <button key={alias} type="button" onClick={() => onOpen?.(alias)} style={buttonStyle} aria-label={`Open ${alias}`}>
                    {alias}
                </button>
            ))}
        </Box>
    );
}

function AlternativeColumn({ title, alternative, preferred }: { title: string, alternative?: AlternativeInfo | null, preferred: boolean }) {
    return (
        <Box sx={{ flex: "1 1 220px", minWidth: 0, p: 1, borderRadius: 1, border: "1px solid", borderColor: preferred ? "#2e7d32" : "#d6e4f0" }}
            aria-label={title}>
            <Typography sx={{ fontSize: 12, fontWeight: 600 }}>{title}{preferred ? " · preferred" : ""}</Typography>
            {alternative ? (
                <>
                    <Typography sx={textSx}>{alternative.summary}</Typography>
                    <List items={alternative.changes} />
                    {alternative.affected_files.length > 0 && <Typography sx={textSx}>{`Files: ${alternative.affected_files.join(", ")}`}</Typography>}
                    <List items={alternative.technical_debt} prefix="Debt: " />
                    <List items={alternative.risks.slice(0, 3)} prefix="Risk: " />
                </>
            ) : (
                <Typography sx={{ ...textSx, color: "text.secondary" }}>Not proposed</Typography>
            )}
        </Box>
    );
}

export function PatternAnalysisPanel({ analysis, onOpen }: { analysis: PatternAnalysisInfo, onOpen?: (alias: string) => void }) {
    const preferred = analysis.preferred_alternative;
    const found = [...analysis.existing_patterns.map(f => ({ ...f, kind: "existing" })), ...analysis.detected_opportunities.map(f => ({ ...f, kind: "opportunity" }))];

    return (
        <Box sx={{ mx: "10px", mb: "8px", display: "flex", flexDirection: "column", gap: 0.5 }} aria-label="Design pattern analysis">
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, alignItems: "center" }}>
                <Box component="span" sx={{ ...chipSx, fontWeight: 600 }}>Design analysis</Box>
                {preferred && <Box component="span" sx={{ ...chipSx, bgcolor: "#2e7d32", color: "white" }}>{`preferred: ${label(preferred)}`}</Box>}
                {analysis.no_pattern_needed && <Box component="span" sx={chipSx}>no pattern needed</Box>}
                {analysis.recommended_patterns.map(r => <Box key={r.pattern} component="span" sx={chipSx}>{r.name}</Box>)}
            </Box>

            {(preferred || analysis.justification) && (
                <details open>
                    <summary style={summaryStyle}>Recommended approach</summary>
                    <Typography sx={textSx}>{analysis.justification}</Typography>
                </details>
            )}

            {(analysis.recommended_patterns.length > 0 || found.length > 0 || analysis.considered_patterns.length > 0) && (
                <details>
                    <summary style={summaryStyle}>Pattern recommendations</summary>
                    {analysis.recommended_patterns.map(r => (
                        <Box key={r.pattern} sx={{ mb: 0.75 }}>
                            <Box sx={{ display: "flex", gap: 0.5, alignItems: "center", flexWrap: "wrap" }}>
                                <Typography sx={{ fontSize: 12, fontWeight: 600 }}>{r.name}</Typography>
                                <Box component="span" sx={chipSx}>{label(r.mode)}</Box>
                                <Box component="span" sx={{ ...chipSx, bgcolor: CONFIDENCE_COLORS[r.confidence] ?? "#6b7280", color: "white" }}>
                                    {`${r.confidence} confidence`}
                                </Box>
                            </Box>
                            <Typography sx={textSx}>{r.reason}</Typography>
                            <List items={r.benefits} prefix="+ " />
                            <List items={r.tradeoffs} prefix="− " />
                            <EvidenceButtons ids={r.evidence_ids} refs={analysis.evidence} onOpen={onOpen} />
                        </Box>
                    ))}
                    {found.length > 0 && (
                        <>
                            <Typography sx={{ fontSize: 12, fontWeight: 600 }}>Detected in the code</Typography>
                            <List items={found.map(f => `${f.name} (${f.kind === "existing" ? f.status : `${f.status} opportunity`}) at ${f.subject}`)} />
                        </>
                    )}
                    {analysis.considered_patterns.length > 0 && (
                        <>
                            <Typography sx={{ fontSize: 12, fontWeight: 600 }}>Considered, not recommended</Typography>
                            <List items={analysis.considered_patterns.map(c => `${c.name}: ${c.reason}`)} />
                        </>
                    )}
                </details>
            )}

            {(analysis.alternatives.minimal_change || analysis.alternatives.pattern_refactoring) && (
                <details>
                    <summary style={summaryStyle}>Implementation alternatives</summary>
                    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, mt: 0.5 }}>
                        <AlternativeColumn title="Minimal change" alternative={analysis.alternatives.minimal_change} preferred={preferred === "minimal_change"} />
                        <AlternativeColumn title="Pattern-based refactoring" alternative={analysis.alternatives.pattern_refactoring} preferred={preferred === "pattern_refactoring"} />
                    </Box>
                    {analysis.comparison.length > 0 && (
                        <Box sx={{ overflowX: "auto", mt: 0.5 }}>
                            <Box component="table" sx={{ borderCollapse: "collapse", fontSize: 12, "& td, & th": { borderBottom: "1px solid #e5edf5", p: 0.5, textAlign: "left", verticalAlign: "top" } }}>
                                <thead>
                                    <tr><th>Dimension</th><th>Minimal change</th><th>Pattern-based</th><th>Basis</th></tr>
                                </thead>
                                <tbody>
                                    {analysis.comparison.map(row => (
                                        <tr key={row.dimension}>
                                            <td>{row.dimension}</td><td>{row.minimal_change}</td><td>{row.pattern_refactoring}</td><td>{row.basis}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </Box>
                        </Box>
                    )}
                </details>
            )}

            {analysis.evidence.length > 0 && (
                <details>
                    <summary style={summaryStyle}>Affected code</summary>
                    <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                        {analysis.evidence.map(ref => (
                            <li key={ref.id}>
                                <Typography component="span" sx={textSx}>{`${range(ref)}${ref.symbol ? ` · ${ref.symbol}` : ""} · ${ref.role} (${ref.source}) — ${ref.why}`}</Typography>
                                {ref.alias && (
                                    <button type="button" onClick={() => onOpen?.(ref.alias as string)} style={buttonStyle} aria-label={`Open ${ref.alias}`}>
                                        {ref.alias}
                                    </button>
                                )}
                            </li>
                        ))}
                    </Box>
                </details>
            )}

            {analysis.limitations.length > 0 && (
                <details>
                    <summary style={summaryStyle}>Limitations</summary>
                    <List items={analysis.limitations} />
                </details>
            )}
        </Box>
    );
}
