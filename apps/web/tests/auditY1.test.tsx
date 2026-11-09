import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProposalReview } from "@/app/c/[slug]/agents/[agentId]/script/ProposalReview";
import type { Section } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";

/**
 * Frontend audit 10 Nov 2026, lane Y1 (client agent screens: the script builder).
 */

function step(id: string, name: string, instruction: string, extra: Partial<Section> = {}): Section {
  return {
    id,
    name,
    mode: "guide",
    instruction,
    sounds_like: "",
    branches: [],
    otherwise: "",
    collect: [],
    procedure: [],
    position: null,
    ...extra,
  };
}

const GREET = step("greet", "Greet", "Say hello.");
const PRICE = step("price", "Price", "Say the price.");
const CLOSE = step("close", "Close", "Agree the next step.");
/** What Pip saw when it wrote the suggestion. */
const BASE: CallScript = { ...EMPTY_SCRIPT, schema_version: 2, stages: [GREET, PRICE, CLOSE] };

describe("a Pip suggestion reviewed after the owner changed the draft (Y1-01)", () => {
  it("does not offer a change to a step the owner deleted since, or count it as added", () => {
    const onApply = vi.fn();
    const proposal: CallScript = { ...BASE, stages: [GREET, { ...PRICE, instruction: "Say the price per kilo." }, CLOSE] };
    // The owner deleted Price while the suggestion was open.
    const current: CallScript = { ...BASE, stages: [GREET, CLOSE] };
    render(<ProposalReview current={current} base={BASE} proposal={proposal} onApply={onApply} onDiscard={() => undefined} />);

    const row = screen.getByText("Price").closest("li")!;
    expect(within(row).getByText("You deleted this step after Pip wrote this.")).toBeTruthy();
    const box = within(row).getByRole("checkbox") as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(box.disabled).toBe(true);
    // Nothing is left to add: the button cannot say it adds a change it would drop.
    expect(screen.queryByRole("button", { name: /Add it to my draft|Add all/ })).toBeNull();
    expect((screen.getByRole("button", { name: /to my draft/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("warns that keeping a change replaces what the owner wrote in that step since", () => {
    const onApply = vi.fn();
    const proposal: CallScript = { ...BASE, stages: [GREET, { ...PRICE, sounds_like: "It is 200 a kilo." }, CLOSE] };
    const current: CallScript = { ...BASE, stages: [GREET, { ...PRICE, instruction: "Say the price and the offer." }, CLOSE] };
    render(<ProposalReview current={current} base={BASE} proposal={proposal} onApply={onApply} onDiscard={() => undefined} />);

    const row = screen.getByText("Price").closest("li")!;
    expect(within(row).getByText("You changed this step since. Keeping this replaces your change.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add it to my draft" }));
    expect(onApply).toHaveBeenCalledOnce();
  });

  it("says nothing extra when the draft is still what Pip saw", () => {
    const proposal: CallScript = { ...BASE, stages: [GREET, { ...PRICE, instruction: "Say the price per kilo." }, CLOSE] };
    render(<ProposalReview current={BASE} base={BASE} proposal={proposal} onApply={() => undefined} onDiscard={() => undefined} />);
    expect(screen.queryByText(/after Pip wrote this|since\. Keeping/)).toBeNull();
    expect(screen.getByRole("button", { name: "Add it to my draft" })).toBeTruthy();
  });
});
