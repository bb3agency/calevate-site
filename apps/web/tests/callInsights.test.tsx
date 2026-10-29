import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InsightsCard } from "@/app/c/[slug]/calls/[callId]/InsightsCard";
import { TURN_DETECTION_LABELS } from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/sections/turnDetection";
import type { CallDetail } from "@/lib/api/client";

/**
 * D-940. The call's reading in short lines (how it ended, objections, problems, next step)
 * naming no provider; and Timer v2 offered to an operator in plain words.
 */

type Insights = NonNullable<CallDetail["insights"]>;

const READING: Insights = {
  outcome: "not_interested",
  no_reason: "price",
  objections: [{ text: "The EMI is too high", kind: "price" }],
  issues: [{ text: "Payment link does not open", kind: "payment" }],
  next_step: {
    kind: "callback",
    at: "2026-10-31T04:30:00Z",
    note: "After salary day",
    status: "open",
  },
};

describe("InsightsCard", () => {
  it("shows how it ended, the objections, the problems and the next step", () => {
    render(<InsightsCard insights={READING} />);
    expect(screen.getByText("Not interested (price)")).toBeTruthy();
    expect(screen.getByText("The EMI is too high")).toBeTruthy();
    expect(screen.getByText("Payment link does not open")).toBeTruthy();
    expect(screen.getByText(/Call back, /)).toBeTruthy();
    expect(screen.getByText("After salary day")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/thinnest/i);
  });

  it("leaves out what the call did not settle", () => {
    render(
      <InsightsCard insights={{ ...READING, outcome: "interested", objections: [], issues: [], next_step: null }} />,
    );
    expect(screen.getByText("Interested")).toBeTruthy();
    expect(screen.queryByText("Objections")).toBeNull();
    expect(screen.queryByText("Next step")).toBeNull();
  });
});

describe("turn detection options", () => {
  it("offers Timer v2 in plain words", () => {
    expect(TURN_DETECTION_LABELS.timer_v2).toBe("Silence + check");
  });
});
