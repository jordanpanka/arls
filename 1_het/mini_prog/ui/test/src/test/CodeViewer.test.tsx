import { render } from "@testing-library/preact";
import { useEffect } from "preact/hooks";
import { describe, it, expect, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  editorProps: null as any,
  editor: null as any,
}));

vi.mock("../components/evidence/monacoSetup", () => ({}));

vi.mock("@monaco-editor/react", () => ({
  default: (p: any) => {
    mocks.editorProps = p;
    useEffect(() => { p.onMount(mocks.editor); }, []);
    return <div data-testid="monaco" />;
  },
}));

import { buildDecorations, CodeViewer } from "../components/evidence/CodeViewer";

function fakeEditor(lineCount = 100) {
  const collection = { set: vi.fn() };
  return {
    collection,
    createDecorationsCollection: vi.fn(() => collection),
    getModel: () => ({ getLineCount: () => lineCount }),
    revealLineInCenter: vi.fn(),
    layoutListeners: [] as (() => void)[],
    onDidLayoutChange(listener: () => void) {
      this.layoutListeners.push(listener);
      return { dispose: () => { this.layoutListeners = this.layoutListeners.filter(l => l !== listener); } };
    },
  };
}

describe("CodeViewer", () => {
  const highlights = [{ startLine: 42, endLine: 55 }, { startLine: 78, endLine: 91 }];

  it("passes the file read-only to Monaco, highlights every range and scrolls to the first", () => {
    mocks.editor = fakeEditor();

    render(<CodeViewer path="5/7/a.cs" content="class A {}" language="csharp" highlights={highlights} activeHighlight={0} />);

    expect(mocks.editorProps.value).toBe("class A {}");
    expect(mocks.editorProps.language).toBe("csharp");
    expect(mocks.editorProps.options).toMatchObject({ readOnly: true, lineNumbers: "on", minimap: { enabled: true }, renderLineHighlight: "none" });

    const decorations = mocks.editor.collection.set.mock.calls.at(-1)[0];
    expect(decorations.map((d: any) => [d.range.startLineNumber, d.range.endLineNumber])).toEqual([[42, 55], [78, 91]]);
    expect(decorations.every((d: any) => d.options.isWholeLine && d.options.linesDecorationsClassName === "evidence-marker")).toBe(true);
    expect(mocks.editor.revealLineInCenter).toHaveBeenCalledWith(42);
  });

  it("jumps to the selected range without dropping the other highlights", () => {
    mocks.editor = fakeEditor();
    const { rerender } = render(<CodeViewer path="p" content="x" language="csharp" highlights={highlights} activeHighlight={0} />);

    rerender(<CodeViewer path="p" content="x" language="csharp" highlights={highlights} activeHighlight={1} />);

    expect(mocks.editor.revealLineInCenter).toHaveBeenLastCalledWith(78);
    const decorations = mocks.editor.collection.set.mock.calls.at(-1)[0];
    expect(decorations).toHaveLength(2);
    expect(decorations[1].options.className).toContain("evidence-highlight-active");
    expect(decorations[0].options.className).not.toContain("evidence-highlight-active");
  });

  it("re-reveals the range when the editor is resized right after opening", () => {
    vi.useFakeTimers();
    mocks.editor = fakeEditor();
    render(<CodeViewer path="p" content="x" language="csharp" highlights={highlights} activeHighlight={0} />);
    mocks.editor.revealLineInCenter.mockClear();

    mocks.editor.layoutListeners.forEach((l: () => void) => l());
    expect(mocks.editor.revealLineInCenter).toHaveBeenCalledWith(42);

    vi.advanceTimersByTime(1000);
    expect(mocks.editor.layoutListeners).toHaveLength(0);
    vi.useRealTimers();
  });

  it("clamps ranges to the file length", () => {
    const decorations = buildDecorations([{ startLine: 8, endLine: 40 }, { startLine: 50, endLine: 60 }], 0, 10);

    expect(decorations.map(d => [d.range.startLineNumber, d.range.endLineNumber])).toEqual([[8, 10]]);
  });
});
