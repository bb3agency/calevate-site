import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProposalReview } from "@/app/c/[slug]/agents/[agentId]/script/ProposalReview";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";

const CURRENT: CallScript = { ...EMPTY_SCRIPT, goal: "Take orders." };
const PROPOSAL: CallScript = {
  ...CURRENT,
  goal: "Take orders and the delivery area.",
  stages: [
    {
      id: "price",
      name: "Price objection",
      mode: "guide",
      instruction: "Acknowledge it, explain the quality, then ask what they need.",
      sounds_like: "",
      branches: [],
      otherwise: "",
      collect: [],
      position: null,
    },
  ],
};

describe("the AI helper's suggested changes", () => {
  it("counts the changes, names each kind quietly and keeps the action in reach", () => {
    const onApply = vi.fn();
    render(<ProposalReview current={CURRENT} proposal={PROPOSAL} onApply={onApply} onDiscard={() => undefined} />);

    expect(screen.getByRole("heading", { name: "2 suggested changes" })).toBeTruthy();
    expect(screen.getByText("Price objection")).toBeTruthy();
    expect(screen.getByText("New step")).toBeTruthy();
    expect(screen.getByText("Changed")).toBeTruthy();

    const add = screen.getByRole("button", { name: "Add all 2 to my draft" });
    expect(add.closest("div.sticky")).toBeTruthy();

    const boxes = screen.getAllByRole("checkbox");
    fireEvent.click(boxes[0]);
    expect(boxes[0].closest("label")?.className).toContain("opacity-55");
    fireEvent.click(screen.getByRole("button", { name: "Add 1 of 2 to my draft" }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("opens a long suggestion in full without ticking or unticking it", () => {
    const long = "Explain where the chilli is grown and how it is dried. ".repeat(6).trim();
    render(
      <ProposalReview
        current={CURRENT}
        proposal={{ ...CURRENT, goal: long }}
        onApply={() => undefined}
        onDiscard={() => undefined}
      />,
    );
    const box = screen.getByRole("checkbox") as HTMLInputElement;
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getByRole("button", { name: "Show less" })).toBeTruthy();
    expect(box.checked).toBe(true);
  });
});
