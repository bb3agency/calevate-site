import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Pagination } from "@/components/interior/pagination";

/**
 * A page number is a tap target on a phone, so on a coarse pointer each one is at least
 * 44 px wide as well as 44 px tall; on a mouse it keeps its compact 32 px slot.
 */

const realMatchMedia = window.matchMedia;

function pointer(coarse: boolean) {
  window.matchMedia = ((query: string) =>
    ({
      matches: query.includes("pointer: coarse") ? coarse : query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList) as typeof window.matchMedia;
}

afterEach(() => {
  window.matchMedia = realMatchMedia;
});

function slotWidth(name: string): string {
  const li = screen.getByRole("button", { name }).closest("li");
  return li?.style.width ?? "";
}

describe("Pagination tap targets", () => {
  it("gives each page number a 44 px slot on a touch screen", () => {
    pointer(true);
    render(<Pagination count={9} defaultPage={1} />);
    expect(slotWidth("Page 1")).toBe("44px");
    expect(slotWidth("Page 2")).toBe("44px");
  });

  it("keeps the compact 32 px slot under a mouse", () => {
    pointer(false);
    render(<Pagination count={9} defaultPage={1} />);
    expect(slotWidth("Page 1")).toBe("32px");
  });
});
