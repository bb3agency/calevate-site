import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MenuDisclosure } from "@/components/marketing/menuDisclosure";

/**
 * The header menu on a phone: open it, then leave it by Escape, by tapping the page, or by
 * following one of its links. Each must close it; the Escape path must hand focus back to
 * the trigger so a keyboard user is not left on a node that just disappeared.
 */
function setup() {
  const view = render(
    <div>
      <button type="button">elsewhere</button>
      <MenuDisclosure className="">
        <summary>Menu</summary>
        <nav aria-label="Pages menu">
          <a href="#pricing">Pricing</a>
        </nav>
      </MenuDisclosure>
    </div>,
  );
  const details = view.container.querySelector("details") as HTMLDetailsElement;
  details.open = true;
  return { view, details };
}

describe("the header menu closes the ways a phone visitor expects", () => {
  it("closes on Escape and returns focus to the trigger", () => {
    const { view, details } = setup();
    view.getByText("Pricing").focus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(details.open).toBe(false);
    expect(document.activeElement).toBe(view.getByText("Menu"));
  });

  it("leaves focus where it was when Escape is pressed outside the menu", () => {
    const { view, details } = setup();
    const elsewhere = view.getByText("elsewhere");
    elsewhere.focus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(details.open).toBe(false);
    expect(document.activeElement).toBe(elsewhere);
  });

  it("closes on a tap outside, and not on a tap inside", () => {
    const { view, details } = setup();
    fireEvent.pointerDown(view.getByText("Pricing"));
    expect(details.open).toBe(true);
    fireEvent.pointerDown(view.getByText("elsewhere"));
    expect(details.open).toBe(false);
  });

  it("closes when one of its links is followed", () => {
    const { view, details } = setup();
    fireEvent.click(view.getByText("Pricing"));
    expect(details.open).toBe(false);
  });
});
