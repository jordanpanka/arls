import { render, screen, fireEvent } from "@testing-library/preact";
import { describe, it, expect, vi } from "vitest";

import { ExecutionSummary } from "../components/chat/ExecutionSummary";
import { AnswerText } from "../components/evidence/EvidenceList";
import { openPanel, panelGraph } from "../components/evidence/panelState";
import { sanitizeEvidence, sanitizeExecution, type Evidence, type GraphEvidence } from "../components/evidence/types";

const graph = (id: string, label: string): GraphEvidence => ({
  type: "graph",
  id,
  nodes: [{ id: `${id}-a`, label, type: "Function" }, { id: `${id}-b`, label: "process_payment", type: "Method" }],
  edges: [{ source: `${id}-a`, target: `${id}-b`, type: "CALLS", certainty: "inferred" }],
  evidenceIds: [`rel:${id}`],
  producedBy: ["get_callers"],
});

describe("agent execution", () => {
  it("accepts agent evidence with the extra traceability fields", () => {
    const evidence = sanitizeEvidence([graph("GRAPH_1", "checkout"), { type: "unknown", id: "X" }]);
    expect(evidence).toHaveLength(1);
    expect((evidence[0] as GraphEvidence).edges[0].certainty).toBe("inferred");
  });

  it("opens the cited graph instead of always the first one", () => {
    const evidence: Evidence[] = [graph("GRAPH_1", "checkout"), graph("GRAPH_2", "refund")];
    expect(panelGraph(openPanel(evidence, "GRAPH_2"))?.id).toBe("GRAPH_2");
    expect(panelGraph(openPanel(evidence, "GRAPH_1"))?.id).toBe("GRAPH_1");
  });

  it("turns graph citations into buttons", () => {
    const onOpen = vi.fn();
    render(<AnswerText content="checkout calls it [GRAPH_2] and [GRAPH_9]" evidence={[graph("GRAPH_2", "checkout")]} onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: "G2" }));
    expect(onOpen).toHaveBeenCalledWith("GRAPH_2");
    expect(screen.queryByRole("button", { name: "G9" })).toBeNull();
  });

  it("sanitizes the execution payload", () => {
    expect(sanitizeExecution(null)).toBeNull();
    expect(sanitizeExecution({ toolCalls: 2 })).toBeNull();
    const info = sanitizeExecution({ strategy: "evidence_aware_agentic_rag", toolCalls: 3, trace: [{ tool: "find_symbol", iteration: 1, latencyMs: 12 }, "bad"] }, "verified");
    expect(info?.status).toBe("verified");
    expect(info?.trace).toHaveLength(1);
  });

  it("shows status, strategy, stop reason and the tool sequence", () => {
    const execution = sanitizeExecution({
      strategy: "evidence_aware_agentic_rag",
      toolCalls: 2,
      iterations: 2,
      latencyMs: 4300,
      stopReason: "evidence_sufficient",
      trace: [
        { iteration: 1, tool: "find_symbol", latencyMs: 12.4, evidence: ["SOURCE_1"] },
        { iteration: 2, tool: "get_callers", latencyMs: 30, error: { kind: "unavailable", message: "down" } },
      ],
    }, "verified")!;
    render(<ExecutionSummary execution={execution} />);
    expect(screen.getByText("verified")).toBeTruthy();
    expect(screen.getByText("evidence aware agentic rag")).toBeTruthy();
    expect(screen.getByText("stop: evidence sufficient")).toBeTruthy();
    expect(screen.getByText("#1 find_symbol · 12 ms · SOURCE_1")).toBeTruthy();
    expect(screen.getByText("#2 get_callers · 30 ms · unavailable")).toBeTruthy();
    expect(screen.queryByText(/^auto:/)).toBeNull();
  });

  it("shows why the routed mode picked a workflow", () => {
    expect(sanitizeExecution({ strategy: "adaptive_rag", route: { chosen: 1 } })?.route).toBeNull();
    const execution = sanitizeExecution({
      strategy: "adaptive_rag",
      latencyMs: 2100,
      route: { requested: "routed_rag", chosen: "adaptive_rag", reason: "simple_question", complexity: "simple" },
    })!;
    expect(execution.route).toEqual({ chosen: "adaptive_rag", reason: "simple_question" });
    render(<ExecutionSummary execution={execution} />);
    expect(screen.getByText("adaptive rag")).toBeTruthy();
    expect(screen.getByText("auto: simple question")).toBeTruthy();
  });
});
