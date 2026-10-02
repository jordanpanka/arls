import Editor, { type OnMount } from "@monaco-editor/react";
import { Box, CircularProgress } from "@mui/material";
import { useEffect, useRef, useState } from "preact/hooks";
import "./monacoSetup";
import "./evidence.css";
import type { Highlight } from "./types";

type MonacoEditor = Parameters<OnMount>[0];

type CodeViewerProps = {
    path: string,
    content: string,
    language: string,
    highlights: Highlight[],
    activeHighlight: number
}

const REVEAL_SETTLE_MS = 600;

const LANGUAGE_ALIASES: Record<string, string> = { json: "javascript" };

export function buildDecorations(highlights: Highlight[], activeIndex: number, lineCount = Number.MAX_SAFE_INTEGER) {
    return highlights
        .filter(h => h.startLine <= lineCount)
        .map((h, index) => ({
            range: {
                startLineNumber: h.startLine,
                startColumn: 1,
                endLineNumber: Math.min(Math.max(h.endLine, h.startLine), lineCount),
                endColumn: 1
            },
            options: {
                isWholeLine: true,
                className: index === activeIndex ? "evidence-highlight evidence-highlight-active" : "evidence-highlight",
                linesDecorationsClassName: "evidence-marker",
                overviewRuler: { color: "#0077B6", position: 4 }
            }
        }));
}

export function CodeViewer(props: CodeViewerProps) {
    const [editor, setEditor] = useState<MonacoEditor | null>(null);
    const decorations = useRef<ReturnType<MonacoEditor["createDecorationsCollection"]> | null>(null);

    const onMount: OnMount = (mounted) => {
        decorations.current = mounted.createDecorationsCollection([]);
        setEditor(mounted);
    };

    useEffect(() => {
        if (!editor || !decorations.current) return;
        const lineCount = editor.getModel()?.getLineCount();
        decorations.current.set(buildDecorations(props.highlights, props.activeHighlight, lineCount) as never);
    }, [editor, props.highlights, props.activeHighlight, props.content]);

    useEffect(() => {
        const target = props.highlights[props.activeHighlight];
        if (!editor || !target) return;
        const reveal = () => editor.revealLineInCenter(target.startLine);
        reveal();

        // The editor mounts lazily and the sidebars animate closed, so the first
        // reveal can run against a stale size; repeat it while the layout settles.
        const layout = editor.onDidLayoutChange(reveal);
        const settle = setTimeout(() => layout.dispose(), REVEAL_SETTLE_MS);
        return () => {
            clearTimeout(settle);
            layout.dispose();
        };
    }, [editor, props.highlights, props.activeHighlight, props.path]);

    return (
        <Editor
            height="100%"
            path={props.path}
            value={props.content}
            language={LANGUAGE_ALIASES[props.language] ?? props.language}
            theme="vs"
            onMount={onMount}
            loading={<Box sx={{ p: 3 }}><CircularProgress size={24} /></Box>}
            options={{
                readOnly: true,
                domReadOnly: true,
                lineNumbers: "on",
                minimap: { enabled: true },
                folding: true,
                scrollBeyondLastLine: false,
                renderLineHighlight: "none",
                wordWrap: "off",
                fontSize: 13,
                automaticLayout: true
            }}
        />
    );
}
