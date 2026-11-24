import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CallStepsCard, STEPS_TITLE, type CallStep } from "@/app/c/[slug]/calls/[callId]/CallStepsCard";

/**
 * "Where the call got to" (founder, 24 Nov 2026): each step of the call's script by its
 * names, whether the person's words showed its outcome, and a jump to the line that did.
 */

const STEPS: CallStep[] = [
  { step: 1, name: "Remembers the app", state: "reached", turn_idx: 1 },
  { step: 2, name: "Installs it, Already has it", state: "not_reached", turn_idx: null },
  { step: 3, name: "Logs in", state: "unclear", turn_idx: null },
];

describe("Where the call got to", () => {
  it("lists every step by its names with what came of it", () => {
    render(<CallStepsCard steps={STEPS} turnsOnScreen={new Set([0, 1, 2])} />);
    const list = screen.getByRole("list", { name: STEPS_TITLE });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Remembers the app"),
      expect.stringContaining("Installs it, Already has it"),
      expect.stringContaining("Logs in"),
    ]);
    expect(within(rows[0] as HTMLElement).getByText("Done")).toBeTruthy();
    expect(within(rows[1] as HTMLElement).getByText("Not done")).toBeTruthy();
    expect(within(rows[2] as HTMLElement).getByText("Not clear")).toBeTruthy();
  });

  it("jumps to the person's line that shows a done step, and only to a line on screen", () => {
    const line = document.createElement("p");
    line.dataset.turn = "1";
    line.tabIndex = -1;
    line.scrollIntoView = vi.fn();
    document.body.appendChild(line);
    render(<CallStepsCard steps={STEPS} turnsOnScreen={new Set([1])} />);
    const buttons = screen.getAllByRole("button", { name: /Show where/ });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0] as HTMLElement);
    expect(document.activeElement).toBe(line);
    line.remove();
  });
});
