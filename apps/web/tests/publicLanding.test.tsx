import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "@/app/page";

import { stubApi } from "./harness";

/**
 * The landing page — the other screen a stranger sees, and the one with the most room to
 * lie on it.
 *
 * Rendered directly: it is a server component in the app, but a synchronous one with no
 * data fetching and no provider, so React Testing Library renders it as-is. There is no
 * realm, no session and no QueryClient to supply — which is the point of it.
 *
 * These assertions are almost entirely NEGATIVE, because the failure mode of a marketing
 * page is not a crash. Every line on a public page is a promise, and the promises that
 * cost the most are the ones nobody notices being added: a plan price, a customer count,
 * an uptime figure, a turnaround. The product cannot keep any of those today —
 * D-11's pricing is negotiated per client, there is no client #1 in production
 * (ROADMAP M2), and the console itself refuses to print a latency figure because
 * migration `f1a7c39d5be2` dropped the column (SURFACES §2c). A test is the only thing
 * that notices when one is quietly reintroduced.
 */
describe("the landing page's claims", () => {
  it("names no price, plan or fee", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("₹");
    expect(text).not.toMatch(/\bRs\.?\b/);
    expect(text).not.toMatch(/\/mo\b|per month|per minute|\bfree\b|\btrial\b/i);
    expect(text).not.toMatch(/pricing|no setup fee/i);
  });

  it("claims no customers, logos or testimonials", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/trusted by|customers use|businesses use|join \d/i);
    expect(text).not.toMatch(/\d+\+?\s*(businesses|clients|companies)/i);
    // No third-party imagery either: a logo wall is a claim in picture form, and an
    // external image is also a request to a host we do not control (the reason
    // `Avatar` replaced dicebear in ui.tsx).
    expect(container.querySelectorAll("img").length).toBe(0);
  });

  it("claims no uptime, accuracy or answer-rate figure", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\d+(\.\d+)?\s*%/);
    expect(text).not.toMatch(/uptime|99\.9|accuracy|instantly|milliseconds/i);
  });

  it("does not advertise a self-serve door the deployment has switched off", () => {
    const { container } = render(<Home />);
    // `self_serve_signup_enabled` defaults OFF and the tests run with it unset, so the
    // page must say accounts are opened by hand. "Sign up free" over a closed door is
    // the exact shape this migration bans: a claim dressed as a button.
    expect(container.textContent).toContain("does not open accounts online");
    expect(screen.queryByRole("link", { name: /Create a workspace/i })).toBeNull();
    // The door is still a real destination — `/signup` explains and hands over the
    // contact address — so the link stays, honestly labelled.
    const link = screen.getByRole("link", { name: /How to get one/i });
    expect(link.getAttribute("href")).toBe("/signup");
  });

  it("makes no network request", () => {
    const calls = stubApi({});
    render(<Home />);
    expect(calls).toEqual([]);
  });

  it("hands the document its scrollbar back, without reaching the app shells", () => {
    // THE MECHANISM CHANGED AND THE INVARIANT DID NOT (D-161). This used to assert an
    // `overflow-y-auto` container, because `globals.css` pins
    // `html, body { overflow: hidden }` for the `fixed inset-0` shells under /c and
    // /admin, and a marketing page that simply grew was silently clipped.
    //
    // Lenis drives the WINDOW scroller, so an inner scrolling div would break smooth
    // scroll, ScrollTrigger's defaults, browser scroll restoration and the mobile
    // address-bar collapse all at once. The page now scrolls the document, and the
    // override in globals.css is scoped by `:has([data-marketing-root])` — so it is
    // structurally unable to reach a route that does not render this attribute.
    //
    // Asserted on the attribute rather than on a class: the attribute is the actual
    // contract with the stylesheet, and a class name is a detail either side could
    // rename without the other noticing.
    const { container } = render(<Home />);
    const root = container.querySelector("[data-marketing-root]");
    expect(root).not.toBeNull();
    // And it must be the OUTERMOST element, because `:has()` on <html> only frees the
    // document when the marketing root is genuinely in this page's tree.
    expect(container.firstElementChild?.hasAttribute("data-marketing-root")).toBe(true);
  });
});
