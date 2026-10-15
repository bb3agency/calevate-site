import { render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MarketingAccountNav } from "@/components/authn/marketingAccountNav";

import { stubApi } from "./harness";

/**
 * The marketing header's account slot learns whether the visitor is signed in only after a
 * round trip. Both states are rendered in one grid cell from the first paint, so the answer
 * cross-fades them in place rather than reflowing the header (a signed-in visitor saw the
 * header change after the page had loaded). These pin that shape and who sees what.
 */

const NAV = <MarketingAccountNav ctaHref="#how" ctaLabel="See how it works" />;

function layers(root: ParentNode): { out: Element; in: Element } {
  const nav = root.querySelector('nav[aria-label="Account"]');
  expect(nav, "the account landmark did not render").not.toBeNull();
  const children = [...(nav as Element).children];
  expect(children).toHaveLength(2);
  return { out: children[0] as Element, in: children[1] as Element };
}

describe("the marketing header's account slot", () => {
  it("serves the signed-out links, with the signed-in ones reserving their width unseen", () => {
    const doc = new DOMParser().parseFromString(renderToStaticMarkup(NAV), "text/html");
    const { out, in: signedIn } = layers(doc);
    // A crawler or a visitor without script gets working sign-in links.
    expect(out.hasAttribute("inert")).toBe(false);
    expect(out.getAttribute("aria-hidden")).toBeNull();
    expect(out.textContent).toContain("Sign in");
    // The other state is in the same cell, so it sizes the slot, but cannot be reached.
    expect(signedIn.hasAttribute("inert")).toBe(true);
    expect(signedIn.getAttribute("aria-hidden")).toBe("true");
    expect(signedIn.classList.contains("invisible")).toBe(true);
    for (const layer of [out, signedIn]) {
      expect(layer.classList.contains("col-start-1")).toBe(true);
      expect(layer.classList.contains("row-start-1")).toBe(true);
    }
  });

  it("swaps to the console link in place once the session is confirmed", async () => {
    stubApi({});
    const { container } = render(NAV);
    expect(await screen.findByRole("link", { name: /Go to your console/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Sign in" })).toBeNull();
    const { out, in: signedIn } = layers(container);
    expect(out.hasAttribute("inert")).toBe(true);
    expect(out.classList.contains("invisible")).toBe(true);
    expect(signedIn.hasAttribute("inert")).toBe(false);
    expect(signedIn.classList.contains("visible")).toBe(true);
  });
});
