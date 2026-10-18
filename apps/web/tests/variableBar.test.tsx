import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VariableBar } from "@/app/c/[slug]/agents/[agentId]/script/ScriptSections";

const STANDARD = [{ key: "lead_name", label: "Caller's name" }];

function hint(): string {
  fireEvent.click(screen.getByRole("button", { name: /fields/i }));
  return document.body.textContent ?? "";
}

describe("the script's fields say when they are filled", () => {
  it("on an agent that answers calls, only for a caller who has called before", () => {
    render(<VariableBar standard={STANDARD} custom={[]} direction="inbound" onInsert={() => undefined} />);
    const text = hint();
    expect(text).toContain("filled only when the caller has called before");
    expect(text).not.toContain("filled from the lead");
  });

  it("on an agent that places calls, from the lead", () => {
    render(<VariableBar standard={STANDARD} custom={[]} direction="outbound" onInsert={() => undefined} />);
    const text = hint();
    expect(text).toContain("filled from the lead");
    expect(text).not.toContain("called before");
  });

  it("offers the caller's name and the client's own fields, and inserts the key", () => {
    const onInsert = vi.fn();
    render(
      <VariableBar
        standard={STANDARD}
        custom={[{ key: "order_id", label: "Order id" }]}
        direction="both"
        onInsert={onInsert}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Caller's name" }));
    expect(onInsert).toHaveBeenCalledWith("lead_name");
    expect(screen.getByRole("button", { name: "Order id" })).toBeTruthy();
  });
});
