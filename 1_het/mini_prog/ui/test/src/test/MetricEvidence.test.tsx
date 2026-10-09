import { render, screen, fireEvent, within } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => ({ viewerProps: [] as any[] }));

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

import { ChatArea } from "../components/chat/ChatArea";
import { clearFileCache } from "../components/evidence/evidenceApi";
import { focusMetric, openPanel } from "../components/evidence/panelState";
import { sanitizeEvidence, type Evidence, type MetricEvidence } from "../components/evidence/types";

const functionMetric: MetricEvidence = {
  type: "metric", id: "METRIC_2", scope: "function", title: "UserService.CreateUser()",
  fileId: "7", fileName: "UserService.cs", filePath: "src/UserService.cs", symbol: "UserService.CreateUser",
  startLine: 120, endLine: 204, analysisId: 42, analyzedAt: "2026-10-03T10:00:00Z",
  items: [
    { key: "cyclomaticComplexity", label: "Cyclomatic complexity", value: 27, category: "VeryHigh" },
    { key: "parameterCount", label: "Parameters", value: 6 },
  ],
};

const repositoryMetric: MetricEvidence = {
  type: "metric", id: "METRIC_1", scope: "repository", title: "Repository summary", analysisId: 42,
  items: [
    { key: "totalNloc", label: "Lines of code (NLOC)", value: 15000, unit: "lines" },
    { key: "dependencyCount", label: "File dependencies", value: null },
  ],
};

const evidence: Evidence[] = [repositoryMetric, functionMetric];

function stubFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (String(url).includes("/api/projects/5/files/7")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ fileId: "7", fileName: "UserService.cs", filePath: "src/UserService.cs", language: "csharp", content: "class UserService {}" }) });
    }
    return Promise.resolve({
      ok: true, status: 200,
      json: () => Promise.resolve(String(url).includes("messages/load")
        ? [{ id: 1, role: "AI", content: "Measured: CC is 27 [METRIC_2] [METRIC_9].", evidence }]
        : []),
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderChat() {
  return render(
    <ChatArea onPanelOpenChange={vi.fn()} newChat={false} setNewChat={vi.fn()} selectedInvId={1}
      sellectedProjId={5} selectedCOnversationId={3} setSelectedConversationId={vi.fn()} />
  );
}

describe("Metric evidence", () => {
  beforeEach(() => {
    clearFileCache();
    mocks.viewerProps.length = 0;
    localStorage.setItem("token", "test-token");
  });

  it("keeps metric evidence from stored messages and drops malformed items", () => {
    const kept = sanitizeEvidence([functionMetric, { type: "metric", id: "METRIC_3" }, { type: "other", id: "x" }]);
    expect(kept).toEqual([functionMetric]);
  });

  it("lists metric evidence in its own section", async () => {
    stubFetch();
    renderChat();

    expect(await screen.findByText("Metrics")).toBeInTheDocument();
    expect(screen.getByText("UserService.CreateUser()")).toBeInTheDocument();
    expect(screen.getByText("Cyclomatic complexity: 27 · Parameters: 6")).toBeInTheDocument();
  });

  it("links only metric citations that exist", async () => {
    stubFetch();
    renderChat();

    const cite = await screen.findByRole("button", { name: "M2" });
    expect(screen.queryByRole("button", { name: "M9" })).not.toBeInTheDocument();

    fireEvent.click(cite);
    const panel = screen.getByRole("complementary", { name: "Evidence panel" });
    const toggle = within(panel).getByRole("group", { name: "Evidence view" });
    expect(within(toggle).getByText("Metrics").closest("[aria-pressed]")).toHaveAttribute("aria-pressed", "true");
  });

  it("shows measured values, marks unavailable ones, and opens the function in code", async () => {
    stubFetch();
    renderChat();

    fireEvent.click(await screen.findByText("UserService.CreateUser()"));

    const card = screen.getByTestId("metric-card-METRIC_2");
    expect(within(card).getByText("27")).toBeInTheDocument();
    expect(within(card).getByText("src/UserService.cs:120–204")).toBeInTheDocument();
    expect(within(screen.getByTestId("metric-card-METRIC_1")).getByText("Not available")).toBeInTheDocument();
    expect(within(screen.getByTestId("metric-card-METRIC_1")).getByText("15,000 lines")).toBeInTheDocument();

    fireEvent.click(within(card).getByText("Open in code"));

    expect(await screen.findByTestId("code-viewer")).toHaveTextContent("class UserService {}");
    expect(mocks.viewerProps.at(-1).highlights).toEqual([{ startLine: 120, endLine: 204 }]);
  });

  it("opens the metric view and focuses a metric's range in panel state", () => {
    const state = openPanel(evidence, "METRIC_2");
    expect(state.view).toBe("metric");
    expect(state.activeMetricId).toBe("METRIC_2");

    const focused = focusMetric(state, functionMetric);
    expect(focused.view).toBe("code");
    expect(focused.sources.at(-1)).toMatchObject({ fileId: "7", highlights: [{ startLine: 120, endLine: 204 }] });
    expect(focusMetric(state, repositoryMetric)).toBe(state);
  });
});
