import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import CodeIcon from "@mui/icons-material/Code";
import InsightsIcon from "@mui/icons-material/Insights";
import { Box, ButtonBase, Typography } from "@mui/material";
import type { ComponentChildren } from "preact";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import "./evidence.css";
import { summarizeGraph, summarizeMetric } from "./panelState";
import { formatRange, isCodeEvidence, isGraphEvidence, isMetricEvidence, type Evidence } from "./types";

type EvidenceListProps = {
    evidence: Evidence[],
    onOpen: (evidenceId: string) => void
}

const CITE_PREFIX = "#cite-";

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
    const metrics = evidence.filter(isMetricEvidence);
    if (code.length === 0 && graphs.length === 0 && metrics.length === 0) return null;

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
            {metrics.length > 0 && <SectionLabel>Metrics</SectionLabel>}
            {metrics.map(metric => (
                <ButtonBase key={metric.id} sx={rowSx} onClick={() => onOpen(metric.id)} title={metric.filePath ?? metric.title}>
                    <InsightsIcon sx={{ fontSize: 16, color: "#0077B6" }} />
                    <Typography sx={{ fontSize: 13, fontWeight: 500, whiteSpace: "nowrap" }}>
                        {metric.title}
                    </Typography>
                    <Typography sx={{ fontSize: 12, color: "text.secondary", ml: "auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {summarizeMetric(metric)}
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

/** Renders the answer as markdown and turns [SOURCE_n] citations into links; ids the answer invented stay plain text. */
export function AnswerText({ content, evidence, onOpen }: AnswerTextProps) {
    const titles = new Map<string, string>([
        ...evidence.filter(isCodeEvidence).map(e => [e.id, e.fileName] as [string, string]),
        ...evidence.filter(isMetricEvidence).map(e => [e.id, `Metrics: ${e.title}`] as [string, string]),
        ...evidence.filter(isGraphEvidence).map(e => [e.id, `Graph: ${summarizeGraph(e)}`] as [string, string])
    ]);

    const components = {
        a: ({ href, children }: { href?: string, children?: ComponentChildren }) => {
            const id = href?.startsWith(CITE_PREFIX) ? href.slice(CITE_PREFIX.length) : undefined;
            const title = id && titles.get(id);
            if (id && title) return <Citation id={id} title={title} onOpen={onOpen} />;
            return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
        },
        code: ({ className, children }: { className?: string, children?: ComponentChildren }) => (
            <code className={className}>
                {typeof children === "string"
                    ? splitCitations(children, titles).map((node, index) => {
                        if (!isCitation(node)) return node.value;
                        const id = node.url!.slice(CITE_PREFIX.length);
                        return <Citation key={index} id={id} title={titles.get(id)!} onOpen={onOpen} />;
                    })
                    : children}
            </code>
        )
    };

    return (
        <Typography component="div" className="answer-markdown" sx={{ margin: "10px" }}>
            <Markdown remarkPlugins={[remarkGfm, [remarkCitations, titles]]} components={components as Components}>{content}</Markdown>
        </Typography>
    );
}

type CitationProps = {
    id: string,
    title: string,
    onOpen: (evidenceId: string) => void
}

function Citation({ id, title, onOpen }: CitationProps) {
    const [kind, number] = id.split("_");
    return (
        <button type="button" className={kind === "METRIC" ? "evidence-cite evidence-cite-metric" : kind === "GRAPH" ? "evidence-cite evidence-cite-graph" : "evidence-cite"} title={title} onClick={() => onOpen(id)}>
            {kind === "METRIC" ? `M${number}` : kind === "GRAPH" ? `G${number}` : number}
        </button>
    );
}

type MarkdownNode = {
    type: string,
    value?: string,
    url?: string,
    children?: MarkdownNode[]
}

function isCitation(node: MarkdownNode) {
    return node.type === "link" && !!node.url?.startsWith(CITE_PREFIX);
}

function splitCitations(text: string, known: Map<string, string>): MarkdownNode[] {
    const nodes: MarkdownNode[] = [];
    let last = 0;

    for (const match of text.matchAll(/\[((?:SOURCE|METRIC|GRAPH)_\d+)\]/g)) {
        if (!known.has(match[1])) continue;
        nodes.push({ type: "text", value: text.slice(last, match.index) });
        nodes.push({ type: "link", url: `${CITE_PREFIX}${match[1]}`, children: [{ type: "text", value: match[1] }] });
        last = match.index + match[0].length;
    }
    nodes.push({ type: "text", value: text.slice(last) });

    return nodes;
}

function remarkCitations(known: Map<string, string>) {
    const visit = (node: MarkdownNode) => {
        node.children = node.children?.flatMap(child => {
            if (child.type === "text") return splitCitations(child.value ?? "", known);
            visit(child);
            return child.type === "link" && child.children?.some(isCitation) ? child.children : [child];
        });
    };
    return visit;
}
