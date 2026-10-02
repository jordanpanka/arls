import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import CodeIcon from "@mui/icons-material/Code";
import { Box, ButtonBase, Typography } from "@mui/material";
import type { JSX } from "preact";
import "./evidence.css";
import { summarizeGraph } from "./panelState";
import { formatRange, isCodeEvidence, isGraphEvidence, type Evidence } from "./types";

type EvidenceListProps = {
    evidence: Evidence[],
    onOpen: (evidenceId: string) => void
}

const rowSx = {
    width: "100%",
    height: "auto",
    display: "flex",
    alignItems: "center",
    gap: 1,
    px: 1,
    py: 0.5,
    borderRadius: 1.5,
    justifyContent: "flex-start",
    textAlign: "left",
    "&:hover": { bgcolor: "#eef4fb" }
};

function SectionLabel({ children }: { children: string }) {
    return <Typography sx={{ fontSize: 11, fontWeight: 600, color: "text.secondary", textTransform: "uppercase", letterSpacing: 0.6, px: 1, mt: 0.5 }}>{children}</Typography>;
}

export function EvidenceList({ evidence, onOpen }: EvidenceListProps) {
    const code = evidence.filter(isCodeEvidence);
    const graphs = evidence.filter(isGraphEvidence);
    if (code.length === 0 && graphs.length === 0) return null;

    return (
        <Box sx={{ borderTop: "1px solid #e5e7eb", mx: "10px", mb: "8px", pt: 0.5 }} aria-label="Evidence">
            <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#03045e", px: 1, pt: 0.5 }}>Evidence</Typography>
            {code.length > 0 && <SectionLabel>Code</SectionLabel>}
            {code.map(item => {
                const [first, ...rest] = item.highlights;
                return (
                    <ButtonBase key={item.id} sx={rowSx} onClick={() => onOpen(item.id)} title={item.filePath}>
                        <CodeIcon sx={{ fontSize: 16, color: "#0077B6" }} />
                        <Typography sx={{ fontSize: 13, fontWeight: 500, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {item.fileName}
                        </Typography>
                        <Typography sx={{ fontSize: 12, color: "text.secondary", ml: "auto", whiteSpace: "nowrap" }}>
                            {first ? formatRange(first) : "Whole file"}{rest.length > 0 ? ` +${rest.length}` : ""}
                        </Typography>
                        {!item.fileId && <Typography sx={{ fontSize: 11, color: "warning.main", whiteSpace: "nowrap" }}>unavailable</Typography>}
                    </ButtonBase>
                );
            })}
            {graphs.length > 0 && <SectionLabel>Graph</SectionLabel>}
            {graphs.map(graph => (
                <ButtonBase key={graph.id} sx={rowSx} onClick={() => onOpen(graph.id)}>
                    <AccountTreeOutlinedIcon sx={{ fontSize: 16, color: "#0077B6" }} />
                    <Typography sx={{ fontSize: 13, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {summarizeGraph(graph)}
                    </Typography>
                </ButtonBase>
            ))}
        </Box>
    );
}

type AnswerTextProps = {
    content: string,
    evidence: Evidence[],
    onOpen: (evidenceId: string) => void
}

/** Turns [SOURCE_n] citations into links; ids the answer invented stay plain text. */
export function AnswerText({ content, evidence, onOpen }: AnswerTextProps) {
    const sources = new Map(evidence.filter(isCodeEvidence).map(e => [e.id, e]));
    const parts: (string | JSX.Element)[] = [];
    let last = 0;

    for (const match of content.matchAll(/\[(SOURCE_(\d+))\]/g)) {
        const source = sources.get(match[1]);
        if (!source) continue;
        parts.push(content.slice(last, match.index));
        parts.push(
            <button key={match.index} type="button" className="evidence-cite" title={`${source.fileName}`} onClick={() => onOpen(source.id)}>
                {match[2]}
            </button>
        );
        last = match.index! + match[0].length;
    }
    parts.push(content.slice(last));

    return <Typography sx={{ margin: "10px", whiteSpace: "pre-wrap" }}>{parts}</Typography>;
}
