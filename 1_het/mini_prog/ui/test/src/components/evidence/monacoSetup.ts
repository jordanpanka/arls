import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor/editor/editor.api";
import "monaco-editor/editor/contrib/folding/browser/folding";
import "monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching";
import "monaco-editor/features/find/register";
import "monaco-editor/languages/definitions/register.all";
// The package's exports map only exposes .js files, so the icon font is imported by path.
import "../../../node_modules/monaco-editor/esm/vs/base/browser/ui/codicons/codicon/codicon.css";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";

// Syntax highlighting only: the TS/JSON language services would add workers
// and diagnostics that make no sense for a read-only viewer.
(globalThis as unknown as { MonacoEnvironment: object }).MonacoEnvironment = {
    getWorker: () => new EditorWorker()
};

loader.config({ monaco: monaco as never });
