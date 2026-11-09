/**
 * `Disclosure`'s `defaultOpen` opens the panel; it never shuts one the reader has open.
 *
 * It was passed straight to `<details open>`, which React re-applies whenever the value
 * changes, so a caller passing a condition closed the panel in the reader's hands the
 * moment the condition went false: the leads screen's "More filters" opens itself while a
 * filter is in use (`defaultOpen={inUse > 0}`), and clearing the last filter from inside it
 * snapped the panel shut under the owner's finger.
 */

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Disclosure } from "@/components/ui";

function panel(defaultOpen: boolean, variant: "card" | "inline" | "row" = "inline") {
  return (
    <Disclosure title="More filters" defaultOpen={defaultOpen} variant={variant}>
      <p>Assigned to me</p>
    </Disclosure>
  );
}

describe.each(["card", "inline", "row"] as const)("Disclosure (%s)", (variant) => {
  it("stays open when the condition that opened it goes away", () => {
    const view = render(panel(false, variant));
    const details = view.container.querySelector("details") as HTMLDetailsElement;
    details.open = true; // the owner opens it
    view.rerender(panel(true, variant)); // picks a filter
    view.rerender(panel(false, variant)); // clears it again
    expect(details.open).toBe(true);
  });

  it("opens itself when its condition becomes true", () => {
    const view = render(panel(false, variant));
    const details = view.container.querySelector("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    view.rerender(panel(true, variant));
    expect(details.open).toBe(true);
  });

  it("opens again on the next rise after the reader closed it", () => {
    const view = render(panel(true, variant));
    const details = view.container.querySelector("details") as HTMLDetailsElement;
    expect(details.open).toBe(true);
    details.open = false; // the reader closes it
    view.rerender(panel(false, variant));
    view.rerender(panel(true, variant));
    expect(details.open).toBe(true);
  });
});
