import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { PatternAnalysisPanel } from "../components/chat/PatternAnalysisPanel";
import { sanitizePatternAnalysis } from "../components/evidence/types";

const payload = {
  preferred_alternative: "pattern_refactoring",
  justification: "Strategy is preferred because ShippingCalculator.cost already handles 4 cases.",
  no_pattern_needed: false,
  existing_patterns: [],
  detected_opportunities: [{ pattern: "strategy", name: "Strategy", status: "likely", subject: "ShippingCalculator.cost (src/shipping/calculator.py)", explanation: "x" }],
  recommended_patterns: [{
    pattern: "strategy", name: "Strategy", mode: "introduce", confidence: "medium", reason: "Behaviour is selected by a conditional chain.",
    subject: "ShippingCalculator.cost", evidence_ids: ["code:1"], architectural_changes: ["Proposed: introduce one interface"],
    benefits: ["Each variant lives in its own class"], tradeoffs: ["Adds an interface"], risks: []
  }],
  considered_patterns: [{ pattern: "factory_method", name: "Factory Method", reason: "No structure it would simplify." }],
  alternatives: {
    minimal_change: { kind: "minimal_change", summary: "Add one more case to ShippingCalculator.cost", changes: ["Add a branch"], affected_files: ["src/shipping/calculator.py"], technical_debt: ["grows from 4 to 5 cases"] },
    pattern_refactoring: { kind: "pattern_refactoring", summary: "Introduce Strategy", changes: [], affected_files: [], new_elements: ["Proposed: Strategy interface"] }
  },
  comparison: [{ dimension: "New abstractions", minimal_change: "0", pattern_refactoring: "2", basis: "planned" }],
  evidence: [{ id: "code:1", alias: "SOURCE_3", file_path: "src/shipping/calculator.py", start_line: 6, end_line: 14, symbol: "ShippingCalculator.cost", source: "ast", role: "conditional chain", why: "4 cases" }],
  limitations: ["No stored code-metrics analysis is available"]
};

describe("design pattern analysis", () => {
  it("drops malformed or empty payloads", () => {
    expect(sanitizePatternAnalysis(null)).toBeNull();
    expect(sanitizePatternAnalysis({ justification: "x" })).toBeNull();
    const info = sanitizePatternAnalysis({ ...payload, recommended_patterns: [payload.recommended_patterns[0], "bad"], evidence: [{ id: "x" }] });
    expect(info?.recommended_patterns).toHaveLength(1);
    expect(info?.evidence).toHaveLength(0);
    expect(info?.alternatives.minimal_change?.advantages).toEqual([]);
  });

  it("shows the preferred approach, recommendations and both alternatives", () => {
    render(<PatternAnalysisPanel analysis={sanitizePatternAnalysis(payload)!} />);
    expect(screen.getByText("preferred: pattern refactoring")).toBeTruthy();
    expect(screen.getByText(payload.justification)).toBeTruthy();
    expect(screen.getByText("medium confidence")).toBeTruthy();
    expect(screen.getByLabelText("Minimal change")).toBeTruthy();
    expect(screen.getByText("Pattern-based refactoring · preferred")).toBeTruthy();
    expect(screen.getByText("planned")).toBeTruthy();
    expect(screen.getByText("Factory Method: No structure it would simplify.")).toBeTruthy();
  });

  it("states when no pattern is needed", () => {
    const info = sanitizePatternAnalysis({ ...payload, preferred_alternative: "minimal_change", no_pattern_needed: true, recommended_patterns: [] })!;
    render(<PatternAnalysisPanel analysis={info} />);
    expect(screen.getByText("no pattern needed")).toBeTruthy();
    expect(screen.getByText("Minimal change · preferred")).toBeTruthy();
  });

  it("opens the cited evidence from the affected code", () => {
    const onOpen = vi.fn();
    render(<PatternAnalysisPanel analysis={sanitizePatternAnalysis(payload)!} onOpen={onOpen} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Open SOURCE_3", hidden: true })[0]);
    expect(onOpen).toHaveBeenCalledWith("SOURCE_3");
  });
});
