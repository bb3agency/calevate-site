/**
 * The step list: what a CLIENT sees of the assistant's tool calls.
 *
 * The founder's decision (10 Oct 2026) replaced the earlier one this file used to pin: no
 * machine tool names and no millisecond timings on a client's screen. Each step reads as
 * the server's plain label (`apps/api/copilot/step_labels.py`), the settled steps fold into
 * one quiet line under the answer, and a step's own sentence appears only when the list is
 * opened and only when the answer has not already said it.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StepList } from "../src/components/copilot/StepList";
import type { CopilotStep } from "../src/lib/copilot/types";

function step(over: Partial<CopilotStep> = {}): CopilotStep {
  return {
    id: "s1",
    tool: "search_calls",
    status: "done",
    args: '{"days": 7}',
    detail: "This account has no calls yet.",
    elapsed_ms: 120,
    label: "Searched your calls",
    ...over,
  };
}

const open = () => fireEvent.click(screen.getByRole("button", { expanded: false }));

describe("the assistant's steps, as the person sees them", () => {
  it("renders nothing at all when no tool has run", () => {
    const { container } = render(<StepList steps={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows a running step by its label with no machine name, args or timing", () => {
    render(<StepList steps={[step({ status: "running", detail: null, elapsed_ms: null, label: "Searching your calls…" })]} />);
    expect(screen.getByText("Searching your calls…")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/search_calls|\{"days"|ms\b/);
  });

  it("folds settled steps into one line, closed, that opens to their labels", () => {
    render(
      <StepList
        steps={[step(), step({ id: "s2", tool: "calls_recent", label: "Checked recent calls" })]}
      />,
    );
    expect(screen.getByText("Checked 2 things")).toBeTruthy();
    expect(screen.queryByText("Searched your calls")).toBeNull();
    open();
    expect(screen.getByText("Searched your calls")).toBeTruthy();
    expect(screen.getByText("Checked recent calls")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/search_calls|calls_recent|120 ms/);
  });

  it("says a sentence once, and not at all when the answer already said it", () => {
    const same = "This account has no calls yet.";
    const { rerender } = render(
      <StepList steps={[step(), step({ id: "s2", label: "Checked recent calls" })]} answer="Hello." />,
    );
    open();
    expect(screen.getAllByText(same)).toHaveLength(1);
    rerender(
      <StepList steps={[step(), step({ id: "s2", label: "Checked recent calls" })]} answer={`${same} Try again later.`} />,
    );
    expect(screen.queryByText(same)).toBeNull();
  });

  it("wraps a long result instead of pushing the panel sideways", () => {
    const detail = "x".repeat(200);
    const { container } = render(<StepList steps={[step({ detail })]} />);
    open();
    const rendered = [...container.querySelectorAll("span")].find((node) => node.textContent === detail);
    expect(rendered?.className).toContain("break-words");
  });

  it("says plainly when a step did not finish, with no stack trace", () => {
    render(<StepList steps={[step({ status: "failed", label: "Searching your calls…", detail: null })]} />);
    expect(screen.getByText("Could not finish what it tried")).toBeTruthy();
    open();
    expect(screen.getByText("Could not finish searching your calls")).toBeTruthy();
  });

  it("never echoes the machine name when the server sent no label", () => {
    render(<StepList steps={[{ id: "r1", tool: "leads_search", status: "refused", args: "" } as CopilotStep]} />);
    open();
    expect(document.body.textContent).not.toMatch(/leads_search|NaN/);
  });
});
