/**
 * The step list: what a CLIENT sees of a tool call, in the states that are not the happy one.
 *
 * ## Why this file exists
 *
 * The rows are the only place a tool's own answer reaches the person VERBATIM — the server
 * puts up to `service.MAX_STEP_CHARS` of the result into `detail` — so every sentence
 * `copilot/tools.py` composes for an empty or partial result is read twice: once by the
 * model, and once here. That makes the empty-state wording a UI string, and it makes the
 * rendering of a long, blank or failed result something to pin rather than assume.
 *
 * ## What is deliberately NOT changed here
 *
 * The machine tool name and the timing are shown to a client on purpose (`StepList`'s own
 * header argues it: `agents_list` is what the server logs and what a person quoting this
 * panel in a support message needs to say, and a prose label per tool would be a second
 * naming of every tool kept in a different file from the registry). These tests pin that
 * decision so a later "friendlier" relabelling has to be a decision rather than a drift.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StepList } from "../src/components/copilot/StepList";
import type { CopilotStep } from "../src/lib/copilot/types";

function step(over: Partial<CopilotStep> = {}): CopilotStep {
  return {
    id: "s1",
    tool: "business_snapshot",
    status: "done",
    args: '{"days": 7}',
    detail: "This account has no calls yet.",
    elapsed_ms: 120,
    ...over,
  };
}

describe("a tool call, as the person sees it", () => {
  it("renders nothing at all when no tool has run", () => {
    const { container } = render(<StepList steps={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the tool's own sentence, which is what the empty-state wording is for", () => {
    render(<StepList steps={[step()]} />);
    expect(screen.getByText("This account has no calls yet.")).toBeTruthy();
    expect(screen.getByText("business_snapshot")).toBeTruthy();
    expect(screen.getByText("120 ms")).toBeTruthy();
  });

  it("renders a row with no detail rather than an empty paragraph", () => {
    // A `running` step has no result yet, and a terminal one can carry an empty string.
    // An empty `<p>` is a blank line of padding under the tool name that reads as a
    // rendering fault on the one screen whose job is to look competent.
    const { container } = render(
      <StepList steps={[step({ detail: null }), step({ id: "s2", detail: "" })]} />,
    );
    expect(container.querySelectorAll("p.text-ink-muted")).toHaveLength(0);
  });

  it("wraps a long result instead of pushing the panel sideways", () => {
    // The server truncates at 200 characters; it does not guarantee a space in them.
    const detail = "x".repeat(200);
    const { container } = render(<StepList steps={[step({ detail })]} />);
    const rendered = container.querySelector("p.text-ink-muted");
    expect(rendered?.textContent).toBe(detail);
    expect(rendered?.className).toContain("break-words");
  });

  it("shows the arguments only while the call is in flight", () => {
    const { rerender } = render(<StepList steps={[step({ status: "running", detail: null })]} />);
    expect(screen.getByText('{"days": 7}')).toBeTruthy();
    // Once the answer is on screen it is the more useful of the two, and the row has to
    // stay one or two lines — a step list taller than the answer has inverted the panel.
    rerender(<StepList steps={[step({ status: "done" })]} />);
    expect(screen.queryByText('{"days": 7}')).toBeNull();
  });

  it("says a lookup failed without the person having to read a stack trace", () => {
    render(
      <StepList
        steps={[step({ status: "failed", detail: "`calls_recent` could not be read just now." })]}
      />,
    );
    expect(screen.getByText("`calls_recent` could not be read just now.")).toBeTruthy();
  });

  it("keeps the machine tool name, deliberately (see this file's header)", () => {
    render(<StepList steps={[step({ tool: "leads_semantic_search" })]} />);
    expect(screen.getByText("leads_semantic_search")).toBeTruthy();
  });
});
