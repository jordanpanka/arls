import { render, screen, fireEvent, waitFor, within } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => ({
  viewerProps: [] as any[],
  cyOptions: null as any,
  cyHandlers: {} as Record<string, (event: any) => void>,
}));

vi.mock("@mui/material", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@mui/material")>()),
  TextField: (props: any) => <input placeholder={props.placeholder} value={props.value} onInput={props.onChange} />,
}));

vi.mock("../components/evidence/CodeViewer", () => ({
  CodeViewer: (p: any) => {
    mocks.viewerProps.push(p);
    return <pre data-testid="code-viewer">{p.content}</pre>;
  },
}));

vi.mock("cytoscape", () => ({
  default: (options: any) => {
    mocks.cyOptions = options;
    return {
      on: (event: string, selector: string, handler: (e: any) => void) => { mocks.cyHandlers[`${event} ${selector}`] = handler; },
      resize: () => { },
      destroy: () => { },
    };
  },
}));

import { ChatArea } from "../components/chat/ChatArea";
import { clearFileCache } from "../components/evidence/evidenceApi";
import { focusNode, openPanel, summarizeGraph } from "../components/evidence/panelState";
import type { Evidence, GraphEvidence } from "../components/evidence/types";

const graph: GraphEvidence = {
  type: "graph",
  id: "GRAPH_1",
  nodes: [
    { id: "c", label: "UserController", type: "Function", fileId: "8", filePath: "src/UserController.cs", startLine: 5, endLine: 9 },
    { id: "s", label: "GetUser", type: "Function", fileId: "7", filePath: "src/UserService.cs", startLine: 42, endLine: 55, usedAsEvidence: true },
    { id: "r", label: "GetById", type: "Function", fileId: "9", filePath: "src/UserRepository.cs", startLine: 18, endLine: 25 },
    { id: "x", label: "log", type: "Function" },
  ],
  edges: [
    { source: "c", target: "s", type: "CALLS" },
    { source: "s", target: "r", type: "CALLS" },
    { source: "s", target: "x", type: "CALLS" },
  ],
};

const evidence: Evidence[] = [
  {
    type: "code", id: "SOURCE_1", fileId: "7", fileName: "UserService.cs", filePath: "src/UserService.cs", language: "csharp",
    highlights: [{ startLine: 42, endLine: 55 }, { startLine: 78, endLine: 91 }],
  },
  { type: "code", id: "SOURCE_2", fileId: null, fileName: "Gone.cs", filePath: "src/Gone.cs", language: "csharp", highlights: [{ startLine: 1, endLine: 3 }] },
  graph,
];

const files: Record<string, any> = {
  "7": { fileId: "7", fileName: "UserService.cs", filePath: "src/UserService.cs", language: "csharp", content: "class UserService {}" },
  "9": { fileId: "9", fileName: "UserRepository.cs", filePath: "src/UserRepository.cs", language: "csharp", content: "class UserRepository {}" },
};

function stubFetch(fileStatus = 200) {
  const fetchMock = vi.fn((url: string) => {
    const match = String(url).match(/\/api\/projects\/5\/files\/(\d+)/);
    if (match) {
      return Promise.resolve({
        ok: fileStatus === 200,
        status: fileStatus,
        json: () => Promise.resolve(files[match[1]]),
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(
        String(url).includes("messages/load")
          ? [
            { id: 1, role: "User", content: "How are users loaded?" },
            { id: 2, role: "AI", content: "The service delegates to the repository [SOURCE_1] [SOURCE_9].", evidence },
          ]
          : []
      ),
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderChat(onPanelOpenChange = vi.fn()) {
  return render(
    <ChatArea
      onPanelOpenChange={onPanelOpenChange}
      newChat={false}
      setNewChat={vi.fn()}
      selectedInvId={1}
      sellectedProjId={5}
      selectedCOnversationId={3}
      setSelectedConversationId={vi.fn()}
    />
  );
}

function fileRequests(fetchMock: ReturnType<typeof vi.fn>, fileId: string) {
  return fetchMock.mock.calls.filter(([url]) => String(url) === `/api/projects/5/files/${fileId}`).length;
}

describe("Evidence", () => {
  beforeEach(() => {
    clearFileCache();
    mocks.viewerProps.length = 0;
    mocks.cyOptions = null;
    mocks.cyHandlers = {};
    localStorage.setItem("token", "test-token");
  });

  it("lists code and graph evidence under the assistant answer", async () => {
    stubFetch();
    renderChat();

    expect(await screen.findByText("UserService.cs")).toBeInTheDocument();
    expect(screen.getByText("Lines 42–55 +1")).toBeInTheDocument();
    expect(screen.getByText("unavailable")).toBeInTheDocument();
    expect(screen.getByText("UserController → GetUser → GetById (+1 more)")).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Evidence panel" })).not.toBeInTheDocument();
  });

  it("opens the panel with the file content and highlighted ranges, and closes back to the chat", async () => {
    const fetchMock = stubFetch();
    renderChat();

    fireEvent.click(await screen.findByText("UserService.cs"));

    expect(screen.getByRole("complementary", { name: "Evidence panel" })).toBeInTheDocument();
    expect(await screen.findByTestId("code-viewer")).toHaveTextContent("class UserService {}");
    expect(fileRequests(fetchMock, "7")).toBe(1);

    const props = mocks.viewerProps[mocks.viewerProps.length - 1];
    expect(props.language).toBe("csharp");
    expect(props.highlights).toEqual([{ startLine: 42, endLine: 55 }, { startLine: 78, endLine: 91 }]);
    expect(props.activeHighlight).toBe(0);

    fireEvent.click(screen.getByLabelText("Next evidence"));
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.getByText("Lines 78–91")).toBeInTheDocument();
    expect(mocks.viewerProps[mocks.viewerProps.length - 1].activeHighlight).toBe(1);

    fireEvent.click(screen.getByLabelText("Close evidence panel"));
    expect(screen.queryByRole("complementary", { name: "Evidence panel" })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("What do you want to know?")).toBeVisible();
  });

  it("tells the layout when the panel opens and closes so the sidebars can make room", async () => {
    stubFetch();
    const onPanelOpenChange = vi.fn();
    renderChat(onPanelOpenChange);

    fireEvent.click(await screen.findByText("UserService.cs"));
    await waitFor(() => expect(onPanelOpenChange).toHaveBeenLastCalledWith(true));

    fireEvent.click(screen.getByLabelText("Close evidence panel"));
    await waitFor(() => expect(onPanelOpenChange).toHaveBeenLastCalledWith(false));
  });

  it("opens evidence from an inline citation and ignores invented source ids", async () => {
    stubFetch();
    renderChat();

    const cite = await screen.findByRole("button", { name: "1" });
    expect(screen.getByText(/\[SOURCE_9\]/)).toBeInTheDocument();

    fireEvent.click(cite);
    expect(await screen.findByTestId("code-viewer")).toBeInTheDocument();
  });

  it("reuses the cached file when a source is reopened", async () => {
    const fetchMock = stubFetch();
    renderChat();

    fireEvent.click(await screen.findByText("UserService.cs"));
    await screen.findByTestId("code-viewer");
    fireEvent.click(screen.getByLabelText("Close evidence panel"));
    fireEvent.click(screen.getByText("UserService.cs"));
    await screen.findByTestId("code-viewer");

    expect(fileRequests(fetchMock, "7")).toBe(1);
  });

  it("explains missing source locations and loading errors without breaking the chat", async () => {
    stubFetch(403);
    renderChat();

    fireEvent.click(await screen.findByText("Gone.cs"));
    expect(screen.getByText(/source location for src\/Gone.cs isn't available/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "UserService.cs" }));
    expect(await screen.findByText("You don't have access to this file.")).toBeInTheDocument();
    expect(screen.getByText(/The service delegates/)).toBeInTheDocument();
  });

  it("renders only the relevant subgraph and opens a node's source on click", async () => {
    const fetchMock = stubFetch();
    renderChat();

    fireEvent.click(await screen.findByText(/UserController → GetUser/));

    await waitFor(() => expect(mocks.cyOptions).not.toBeNull());
    const elements = mocks.cyOptions.elements;
    expect(elements.filter((e: any) => !e.data.source).map((e: any) => e.data.id)).toEqual(["c", "s", "r", "x"]);
    expect(elements.filter((e: any) => e.data.source).map((e: any) => e.data.label)).toEqual(["CALLS", "CALLS", "CALLS"]);
    expect(elements.find((e: any) => e.data.id === "s").classes).toContain("evidence");
    expect(elements.find((e: any) => e.data.id === "r").classes).toContain("context");

    mocks.cyHandlers["tap node"]({ target: { id: () => "x" } });
    expect(await screen.findByText(/No source location is recorded for log/)).toBeInTheDocument();

    mocks.cyHandlers["tap node"]({ target: { id: () => "r" } });

    expect(await screen.findByTestId("code-viewer")).toHaveTextContent("class UserRepository {}");
    expect(fileRequests(fetchMock, "9")).toBe(1);
    const props = mocks.viewerProps[mocks.viewerProps.length - 1];
    expect(props.highlights).toEqual([{ startLine: 18, endLine: 25 }]);
    const toggle = screen.getByRole("group", { name: "Evidence view" });
    expect(within(toggle).getByText("Code").closest("[aria-pressed]")).toHaveAttribute("aria-pressed", "true");
    expect(within(toggle).getByText("Graph").closest("[aria-pressed]")).toHaveAttribute("aria-pressed", "false");
  });

  it("shows a message when the graph has nothing to visualize", async () => {
    stubFetch();
    const empty: GraphEvidence = { type: "graph", id: "GRAPH_1", nodes: [], edges: [] };
    const { GraphEvidenceView } = await import("../components/evidence/GraphEvidenceView");

    render(<GraphEvidenceView graph={empty} onOpenNode={vi.fn()} />);

    expect(screen.getByText(/No knowledge-graph relationships/)).toBeInTheDocument();
  });
});

describe("panelState", () => {
  it("adds a graph node's range to an already open file instead of a new tab", () => {
    const state = openPanel(evidence, "GRAPH_1");
    expect(state.view).toBe("graph");

    const focused = focusNode(state, { id: "m", label: "Save", type: "Method", fileId: "7", filePath: "src/UserService.cs", startLine: 60, endLine: 70 });

    expect(focused.view).toBe("code");
    expect(focused.sources).toHaveLength(2);
    expect(focused.activeSourceId).toBe("SOURCE_1");
    expect(focused.sources[0].highlights).toHaveLength(3);
    expect(focused.activeHighlight).toBe(2);

    const again = focusNode(focused, { id: "s", label: "GetUser", type: "Function", fileId: "7", startLine: 42, endLine: 55 });
    expect(again.sources[0].highlights).toHaveLength(3);
    expect(again.activeHighlight).toBe(0);
  });

  it("ignores nodes without a file", () => {
    const state = openPanel(evidence, "GRAPH_1");
    expect(focusNode(state, { id: "x", label: "log", type: "Function" })).toBe(state);
  });

  it("summarizes graphs without calls by node count", () => {
    expect(summarizeGraph({ type: "graph", id: "g", nodes: [{ id: "a", label: "A", type: "Class" }], edges: [] })).toBe("1 node");
  });
});
