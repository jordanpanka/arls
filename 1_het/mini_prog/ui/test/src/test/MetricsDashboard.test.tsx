import { render, screen, fireEvent, within, waitFor } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@mui/material", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@mui/material")>()),
  Drawer: (p: any) => (p.open ? <div>{p.children}</div> : null),
}));

vi.mock("../components/evidence/CodeViewer", () => ({
  CodeViewer: (p: any) => <pre data-testid="code-viewer" data-highlights={JSON.stringify(p.highlights)}>{p.content}</pre>,
}));

import { MetricsDashboard } from "../components/metrics/MetricsDashboard";
import { squarify } from "../components/metrics/treemap";
import { clearFileCache } from "../components/evidence/evidenceApi";

const analysis = {
  analysisId: 4, projectId: 5, repositoryId: 1, status: "Completed", staticStatus: "Completed", graphStatus: "Completed",
  errorMessage: null, trigger: "Manual", branch: "main", commitSha: "abcdef1234567890", createdAt: "2026-10-03T10:00:00Z",
  startedAt: "2026-10-03T10:00:00Z", completedAt: "2026-10-03T10:00:05Z", totalDurationMs: 5300, staticDurationMs: 4000,
  graphDurationMs: 1300, filesAnalyzed: 2, filesSkipped: 1, staticAnalyzer: "lizard", graphAnalyzer: "neo4j-knowledge-graph",
};

const thresholds = {
  complexityBands: [
    { category: "Low", min: 1, max: 5, label: "1–5" }, { category: "Moderate", min: 6, max: 10, label: "6–10" },
    { category: "High", min: 11, max: 20, label: "11–20" }, { category: "VeryHigh", min: 21, max: null, label: "21+" },
  ],
  highComplexityAbove: 10, longFunctionNloc: 50, manyParameters: 5,
};

const repository = {
  analysis,
  summary: {
    totalFiles: 2, totalNloc: 18342, totalFunctions: 40, totalClasses: 6, averageComplexity: 4.73, maxComplexity: 27,
    maxComplexityCategory: "VeryHigh", highComplexityFunctionCount: 3, longFunctionCount: 2, manyParameterFunctionCount: 1,
    dependencyCount: 9, cycleCount: 1, averageFanIn: 1.5, averageFanOut: 1.5, maxFanIn: 3,
    maxFanOut: 2, maxDependencyDepth: 2, cycles: [["src/A.cs", "src/B.cs"]],
  },
  complexityDistribution: [
    { category: "Low", label: "1–5", count: 30 }, { category: "Moderate", label: "6–10", count: 7 },
    { category: "High", label: "11–20", count: 2 }, { category: "VeryHigh", label: "21+", count: 1 },
  ],
  thresholds,
  skippedFiles: [{ path: "src/Gone.cs", reason: "missing_in_storage" }],
};

const files = [
  { id: 1, fileId: 7, path: "src/UserService.cs", language: "csharp", nloc: 846, tokenCount: 5000, functionCount: 23, classCount: 1,
    averageComplexity: 8.2, maxComplexity: 27, complexityCategory: "VeryHigh", highComplexityFunctionCount: 5, averageFunctionNloc: 30,
    maxFunctionNloc: 84, longFunctionCount: 2, manyParameterFunctionCount: 1, fanIn: 21, fanOut: 14, importCount: 6 },
  { id: 2, fileId: 8, path: "src/Util.cs", language: "csharp", nloc: 120, tokenCount: 600, functionCount: 4, classCount: 1,
    averageComplexity: 2, maxComplexity: 3, complexityCategory: "Low", highComplexityFunctionCount: 0, averageFunctionNloc: 10,
    maxFunctionNloc: 20, longFunctionCount: 0, manyParameterFunctionCount: 0, fanIn: 1, fanOut: 0, importCount: 1 },
];

const detail = {
  analysis,
  file: files[0],
  functions: [
    { id: 11, fileId: 7, filePath: "src/UserService.cs", name: "CreateUser", longName: "UserService::CreateUser(...)", className: "UserService",
      startLine: 120, endLine: 204, nloc: 84, cyclomaticComplexity: 27, complexityCategory: "VeryHigh", tokenCount: 400,
      parameterCount: 6, length: 85, fanIn: 4, fanOut: 3, isLong: true, hasManyParameters: true },
  ],
};

type Routes = Record<string, { status?: number, body: any }>;

function stubFetch(routes: Routes) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const path = String(url);
    const key = Object.keys(routes).find(k => {
      const [method, route] = k.split(" ");
      return (init?.method ?? "GET") === method && path.split("?")[0] === route;
    });
    const route = key ? routes[key] : { status: 404, body: { error: "not_found" } };
    const status = route.status ?? 200;
    return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(route.body) });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const loadedRoutes: Routes = {
  "GET /api/projects/5/metrics/status": { body: { latest: analysis, latestUsable: analysis } },
  "GET /api/projects/5/metrics": { body: repository },
  "GET /api/projects/5/metrics/files": { body: files },
  "GET /api/projects/5/metrics/hotspots/dependencies": { body: { kind: "dependency", files: [files[0]], functions: [] } },
  "GET /api/projects/5/metrics/files/detail": { body: detail },
  "GET /api/projects/5/files/7": { body: { fileId: "7", fileName: "UserService.cs", filePath: "src/UserService.cs", language: "csharp", content: "class UserService {}" } },
};

describe("MetricsDashboard", () => {
  beforeEach(() => {
    clearFileCache();
    localStorage.setItem("token", "test-token");
  });

  it("shows a loading state first", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => { })));
    render(<MetricsDashboard projectId={5} projectName="Demo" />);
    expect(screen.getByText("Loading code metrics…")).toBeInTheDocument();
  });

  it("shows the empty state and starts an analysis", async () => {
    const fetchMock = stubFetch({
      "GET /api/projects/5/metrics/status": { body: { latest: null, latestUsable: null } },
      "POST /api/projects/5/metrics/analyze": { status: 202, body: { analysisId: 9, status: "Queued", reused: false } },
    });
    render(<MetricsDashboard projectId={5} projectName="Demo" />);

    expect(await screen.findByText("No code metrics analysis has been run for this repository.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Analyze Repository"));

    expect(await screen.findByText("Analysis queued…")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post![1]!.body))).toEqual({ force: false });
  });

  it("shows an error state when metrics cannot be loaded", async () => {
    stubFetch({ "GET /api/projects/5/metrics/status": { status: 403, body: { error: "forbidden" } } });
    render(<MetricsDashboard projectId={5} />);

    expect(await screen.findByText("You don't have access to this project.")).toBeInTheDocument();
  });

  it("renders stored metrics without inventing missing ones", async () => {
    stubFetch(loadedRoutes);
    render(<MetricsDashboard projectId={5} projectName="Demo" />);

    expect(await screen.findByText("18,342")).toBeInTheDocument();
    expect(screen.getByText("Demo · main · abcdef1234")).toBeInTheDocument();
    expect(within(screen.getByTestId("summary-Avg complexity")).getByText("4.7")).toBeInTheDocument();
    expect(screen.queryByTestId("summary-Maintainability")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("bucket-Moderate")).getByText("7")).toBeInTheDocument();
    expect(screen.getByText("fan-in 21 · fan-out 14")).toBeInTheDocument();

    const row = screen.getByTestId("file-row-src/UserService.cs");
    expect(within(row).getByText("27")).toBeInTheDocument();
    expect(within(row).getByText("8.2")).toBeInTheDocument();
  });

  it("opens file details and highlights a function in the code viewer", async () => {
    stubFetch(loadedRoutes);
    render(<MetricsDashboard projectId={5} projectName="Demo" />);

    fireEvent.click(await screen.findByTestId("file-row-src/UserService.cs"));

    const dialog = await screen.findByRole("dialog", { name: "File metrics" });
    fireEvent.click(await within(dialog).findByTestId("function-row-CreateUser"));

    const viewer = await screen.findByTestId("code-viewer");
    expect(viewer).toHaveTextContent("class UserService {}");
    expect(JSON.parse(viewer.getAttribute("data-highlights")!)).toEqual([{ startLine: 120, endLine: 204 }]);
  });

  it("warns when graph metrics are missing from a partial analysis", async () => {
    const partial = { ...analysis, status: "Partial", graphStatus: "Failed", errorMessage: "Neo4j unavailable" };
    stubFetch({
      ...loadedRoutes,
      "GET /api/projects/5/metrics/status": { body: { latest: partial, latestUsable: partial } },
      "GET /api/projects/5/metrics": { body: { ...repository, analysis: partial } },
    });
    render(<MetricsDashboard projectId={5} />);

    await waitFor(() => expect(screen.getByText(/Graph metrics could not be calculated \(Neo4j unavailable\)/)).toBeInTheDocument());
    expect(screen.getByText(/Graph metrics are not available for this analysis/)).toBeInTheDocument();
  });
});

describe("squarify", () => {
  it("fills the area proportionally to the values", () => {
    const rects = squarify([{ value: 6, item: "a" }, { value: 3, item: "b" }, { value: 1, item: "c" }, { value: 0, item: "d" }], 100, 50);

    expect(rects.map(r => r.item)).toEqual(["a", "b", "c"]);
    const area = (item: string) => { const r = rects.find(x => x.item === item)!; return r.width * r.height; };
    expect(area("a")).toBeCloseTo(3000);
    expect(area("b")).toBeCloseTo(1500);
    expect(area("c")).toBeCloseTo(500);
    for (const r of rects) {
      expect(r.x + r.width).toBeLessThanOrEqual(100.0001);
      expect(r.y + r.height).toBeLessThanOrEqual(50.0001);
    }
  });
});
