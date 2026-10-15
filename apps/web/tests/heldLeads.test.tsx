import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HeldLeads } from "@/app/c/[slug]/lead-sources/HeldLeads";

const NOOP = () => undefined;

function renderHeld(held: Parameters<typeof HeldLeads>[0]["held"], holding: boolean) {
  return render(
    <HeldLeads
      held={held}
      holding={holding}
      canWrite
      busyId={null}
      actionError={null}
      onRelease={NOOP}
      onDrop={NOOP}
    />,
  );
}

describe("leads held after hours", () => {
  it("shows a failed read even when the account no longer holds leads", () => {
    renderHeld({ isLoading: false, error: new Error("The held leads did not load.") }, false);
    expect(screen.getByText("Waiting for you")).toBeTruthy();
    expect(screen.getByText(/Try again in a moment/)).toBeTruthy();
    expect(screen.queryByText(/No leads waiting/)).toBeNull();
  });

  it("stays out of the way when nothing is held and the account does not hold leads", () => {
    const { container } = renderHeld({ isLoading: false, error: null, data: { items: [] } }, false);
    expect(container.textContent).toBe("");
  });
});
