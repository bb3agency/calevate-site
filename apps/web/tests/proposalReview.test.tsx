import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, onTestFinished, vi } from "vitest";

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

describe("a suggestion's changes, kept one by one", () => {
  it("lists the changes against the script it was made from and applies them to the working copy", () => {
    const onApply = vi.fn();
    // The owner changed the goal after the suggestion was written from CURRENT.
    const working: CallScript = { ...CURRENT, goal: "Take orders by phone." };
    render(
      <ProposalReview
        current={working}
        base={CURRENT}
        proposal={{ ...CURRENT, ending: "Thank them." }}
        onApply={onApply}
        onDiscard={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "1 suggested change" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add it to my draft" }));
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ goal: "Take orders by phone.", ending: "Thank them." }));
  });

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
    expect(boxes[0].closest("li")?.className).toContain("opacity-55");
    fireEvent.click(screen.getByRole("button", { name: "Add 1 of 2 to my draft" }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("opens a long suggestion in full without ticking or unticking it", () => {
    // jsdom lays nothing out, so give the clamped text the overflow a browser would measure.
    const scroll = vi
      .spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockImplementation(function (this: HTMLElement) {
        return (this.textContent?.length ?? 0) > 220 ? 200 : 0;
      });
    const client = vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(80);
    onTestFinished(() => {
      scroll.mockRestore();
      client.mockRestore();
    });
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

describe("a suggestion reworded before it is kept (D-831)", () => {
  const STEP = PROPOSAL.stages[0];

  it("ticks a row when its suggestion is edited and adds the edited words", () => {
    const onApply = vi.fn();
    render(<ProposalReview current={CURRENT} proposal={PROPOSAL} onApply={onApply} onDiscard={() => undefined} />);
    const goal = screen.getByRole("checkbox", { name: "The goal" }) as HTMLInputElement;
    fireEvent.click(goal);
    expect(goal.checked).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Edit The goal" }));
    fireEvent.change(screen.getByLabelText("The goal", { selector: "textarea" }), {
      target: { value: "Take the order and the delivery area, then confirm it." },
    });
    expect(goal.checked).toBe(true);
    expect(screen.getByText("Edited by you")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Edit Price objection" }));
    fireEvent.change(screen.getByLabelText("Example line"), { target: { value: "Rate ekkuva ani anipistunda andi?" } });

    fireEvent.click(screen.getByRole("button", { name: "Add all 2 to my draft" }));
    const kept = onApply.mock.calls[0][0] as CallScript;
    expect(kept.goal).toBe("Take the order and the delivery area, then confirm it.");
    expect(kept.stages[0]).toMatchObject({ id: "price", sounds_like: "Rate ekkuva ani anipistunda andi?" });
  });

  it("holds the draft and shows the builder's own message on the row until it is fixed", () => {
    const onApply = vi.fn();
    render(<ProposalReview current={CURRENT} proposal={PROPOSAL} onApply={onApply} onDiscard={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Price objection" }));
    const name = screen.getByLabelText("Step name");
    fireEvent.change(name, { target: { value: " " } });
    expect(screen.getByText("Give this step a name.")).toBeTruthy();
    expect(name.getAttribute("aria-invalid")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Add all 2 to my draft" }));
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("Fix “Price objection” first");

    fireEvent.change(name, { target: { value: "Too costly" } });
    fireEvent.click(screen.getByRole("button", { name: "Add all 2 to my draft" }));
    expect((onApply.mock.calls[0][0] as CallScript).stages[0].name).toBe("Too costly");
  });

  it("holds a business line over the builder's limit", () => {
    const onApply = vi.fn();
    render(
      <ProposalReview
        current={CURRENT}
        proposal={{ ...CURRENT, business_line: "An organic produce shop." }}
        onApply={onApply}
        onDiscard={() => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit Your business in one line" }));
    const line = screen.getByRole("textbox", { name: "Your business in one line" });
    // The input's maxLength stops typing; a paste through the model is what reaches this.
    fireEvent.change(line, { target: { value: "x".repeat(201) } });
    expect(screen.getByText("Keep this under 200 letters.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add it to my draft" }));
    expect(onApply).not.toHaveBeenCalled();
  });

  it("puts the suggestion's own words back on reset", () => {
    const onApply = vi.fn();
    render(<ProposalReview current={CURRENT} proposal={PROPOSAL} onApply={onApply} onDiscard={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Price objection" }));
    fireEvent.change(screen.getByLabelText("What it does here"), { target: { value: "Just say sorry." } });
    fireEvent.click(screen.getByRole("button", { name: "Reset to suggestion" }));
    expect((screen.getByLabelText("What it does here") as HTMLTextAreaElement).value).toBe(STEP.instruction);
    expect(screen.queryByText("Edited by you")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add all 2 to my draft" }));
    expect((onApply.mock.calls[0][0] as CallScript).stages[0].instruction).toBe(STEP.instruction);
  });
});
