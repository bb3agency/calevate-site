import { act, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminError from "@/app/admin/error";
import ClientRealmError from "@/app/c/[slug]/error";
import RootError from "@/app/error";
import GlobalError from "@/app/global-error";
import LegalDocumentRoute from "@/app/legal/[slug]/page";
import NotFound from "@/app/not-found";
import { failureCopy } from "@/components/failureScreen";
import { OfflineBanner } from "@/components/offline";
import { ApiProblem } from "@/lib/api/client";

import { expectNoA11yViolations } from "./a11y";
import { browserOffline } from "./harness";

/**
 * THE GLOBAL STATES the app shipped without: a crash, a 404, and a lost connection.
 *
 * The audit (`docs/ux-audit/entry-auth-crosscutting.md`, F-21/F-22) measured all three as
 * absent — no `error.tsx`, no `global-error.tsx` and no `not-found.tsx` anywhere under
 * `src/app`, and nothing in `src` reading the browser's online state. These are the
 * assertions whose absence let that ship, and they are deliberately about behaviour a
 * reviewer cannot see in a diff:
 *
 *  - a crash NEVER renders the thrown message, because that message is an internal;
 *  - a crash always renders a way out, because a screen with no exit is the defect;
 *  - a 404 renders OUR page, including for the one `notFound()` call the product makes.
 *
 * `next/navigation` is re-mocked for this file because the pathname is an INPUT here
 * rather than scenery: the realm a failed address belongs to is read from it, and
 * `notFound()` — which `tests/setup.ts` does not stub at all, since no other suite reaches
 * it — is the framework signal the legal route raises. `vi.hoisted` is what lets the
 * factory reach a mutable box; a plain `let` would be read before initialisation, because
 * `vi.mock` is hoisted above it.
 */
const nav = vi.hoisted(() => ({
  pathname: "/",
  notFound: vi.fn(() => {
    // The shape Next signals a 404 with: a throw the router catches and answers by
    // rendering `app/not-found.tsx`.
    throw new Error("NEXT_HTTP_ERROR_FALLBACK;404");
  }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  notFound: nav.notFound,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

beforeEach(() => {
  nav.pathname = "/";
  nav.notFound.mockClear();
});

/** The shape Next passes an error boundary: a real Error, optionally carrying a digest. */
function crash(message: string, digest?: string): Error & { digest?: string } {
  const error: Error & { digest?: string } = new Error(message);
  if (digest) error.digest = digest;
  return error;
}

describe("the root error boundary", () => {
  let logged: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // The operator's half of the contract is a log line; it is asserted below, and the spy
    // also keeps the expected noise out of the suite's output.
    logged = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => logged.mockRestore());

  it("never renders the thrown message, and never a stack", () => {
    render(
      <RootError
        error={crash("TypeError: e.reduce is not a function at /_next/static/chunks/9f2.js")}
        reset={vi.fn()}
      />,
    );

    expect(document.body.textContent).not.toContain("reduce is not a function");
    expect(document.body.textContent).not.toContain("_next/static");
    // What it says instead is something a person can act on.
    expect(screen.getAllByText("Something went wrong on this page.").length).toBe(1);
  });

  it("gives the operator the log line the user does not get", () => {
    render(<RootError error={crash("boom", "d1g35t")} reset={vi.fn()} />);
    expect(logged).toHaveBeenCalledWith(
      "[calevate] uncaught render error",
      expect.objectContaining({ digest: "d1g35t", message: "boom" }),
    );
  });

  it("shows a digest as a quotable support reference", () => {
    render(<RootError error={crash("boom", "d1g35t")} reset={vi.fn()} />);
    expect(screen.getAllByText("d1g35t").length).toBe(1);
    expect(document.body.textContent).toContain("Support reference");
  });

  it("offers a working retry and a way out of the screen", async () => {
    const reset = vi.fn();
    const { container } = render(<RootError error={crash("boom")} reset={reset} />);

    screen.getByRole("button", { name: "Try again" }).click();
    expect(reset).toHaveBeenCalledTimes(1);

    // F-21 in one line: Next's default error screen has no anchor at all.
    const links = Array.from(container.querySelectorAll("a[href]"));
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/", "/c"]);
    await expectNoA11yViolations(container, "app/error.tsx");
  });

  it("unwraps an ApiProblem rather than flattening it to 'something went wrong'", () => {
    const problem = new ApiProblem(422, {
      type: "https://calevate.tech/problems/dnc-listed",
      detail: "That number is on the do-not-call list.",
      remediation: "Remove it from the campaign, or ask the client to re-consent.",
      trace_id: "trace-77",
      retryable: false,
    });
    render(<RootError error={problem as Error & { digest?: string }} reset={vi.fn()} />);

    expect(screen.getAllByText("That number is on the do-not-call list.").length).toBe(1);
    expect(screen.getAllByText(/Remove it from the campaign/).length).toBe(1);
    expect(screen.getAllByText("trace-77").length).toBe(1);
  });

  it("reports a reference only when there is one, and never the raw message", () => {
    expect(failureCopy(crash("boom")).reference).toBeNull();
    expect(failureCopy(crash("boom", "abc")).reference).toBe("abc");
    expect(failureCopy(crash("boom")).detail).not.toContain("boom");
  });
});

describe("the realm error boundaries", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("return an operator to the operator console, not to the marketing site", () => {
    const { container } = render(<AdminError error={crash("boom")} reset={vi.fn()} />);
    const links = Array.from(container.querySelectorAll("a[href]"));
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/admin"]);
  });

  it("return a client to their own dashboard, using the slug in the path", () => {
    nav.pathname = "/c/kirana-mart/leads";
    const { container } = render(<ClientRealmError error={crash("boom")} reset={vi.fn()} />);
    expect(container.querySelector("a[href]")?.getAttribute("href")).toBe("/c/kirana-mart");
  });

  it("fall back to the /c junction when the path carries no usable slug", () => {
    nav.pathname = "/";
    const { container } = render(<ClientRealmError error={crash("boom")} reset={vi.fn()} />);
    expect(container.querySelector("a[href]")?.getAttribute("href")).toBe("/c");
  });
});

describe("global-error, the boundary for the root layout itself", () => {
  /**
   * Rendered to STATIC MARKUP rather than into a container, because that is the only way to
   * see the thing under test: React Testing Library mounts into a `<div>`, and a component
   * whose root is `<html>` cannot go there. Server rendering is also how this boundary is
   * produced when the root layout fails during SSR.
   */
  const markup = (): string =>
    renderToStaticMarkup(<GlobalError error={crash("boom", "d1g35t")} reset={vi.fn()} />);

  it("renders its own html and body, because it replaces the root layout", () => {
    const html = markup();
    expect(html.startsWith("<html")).toBe(true);
    expect(html).toContain("<body");
    expect(html).toContain("</html>");
  });

  it("ships no theme switching at all, and falls back to LIGHT colours", () => {
    // D-471: the product is light-only. This screen replaces the root layout, so it is the
    // one place that could smuggle a theme back in — it used to re-stamp `.dark` from a
    // media query. It must not, and its inline fallbacks (for the case where the stylesheet
    // itself failed to load, which is why this screen exists) must be the LIGHT ones: a
    // black last-resort page on a light-only product is a bug that only ever shows itself
    // during an outage, when nobody is looking for it.
    const html = markup();
    expect(html).not.toContain("prefers-color-scheme");
    expect(html).not.toContain("localStorage");
    expect(html).toContain("#fafafa");
  });

  it("still says something a user can act on, and still quotes the reference", () => {
    const html = markup();
    expect(html).toContain("Calevate could not finish loading.");
    expect(html).toContain("d1g35t");
    expect(html).not.toContain("boom");
  });
});

describe("the 404", () => {
  it("renders our page, with a heading and a real way back", async () => {
    const { container } = render(<NotFound />);
    expect(screen.getAllByRole("heading", { level: 1 }).length).toBe(1);
    expect(document.body.textContent).toContain("could not connect you to that page");
    // Plain language: the reader may be a procurement reviewer following a stale link.
    expect(document.body.textContent).not.toContain("404");
    expect(document.body.textContent).not.toContain("NOT_FOUND");

    const links = Array.from(container.querySelectorAll("a[href]"));
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/", "/c", "/legal"]);
    await expectNoA11yViolations(container, "app/not-found.tsx");
  });

  it("carries a decorative illustration the copy does not depend on", () => {
    const { container } = render(<NotFound />);
    const svg = container.querySelector("svg");
    expect(svg, "the 404 renders an inline SVG, never an <img>").not.toBeNull();
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelectorAll("img").length).toBe(0);
    // Remove the figure and the page still says everything it needs to.
    svg?.remove();
    expect(container.textContent).toContain("could not connect you to that page");
  });

  it("colours the illustration from tokens only, so it is correct in both themes", () => {
    const { container } = render(<NotFound />);
    const coloured = Array.from(container.querySelectorAll("svg *"))
      .flatMap((el) => [el.getAttribute("fill"), el.getAttribute("stroke")])
      .filter((value): value is string => value !== null && value !== "none");
    expect(coloured.length).toBeGreaterThan(8);
    // A literal hex here would be right in one theme and wrong in the other, which is
    // exactly what `--brand*` / `--surface` exist to prevent.
    expect(coloured.filter((value) => !value.startsWith("var(--"))).toEqual([]);
  });

  it("offers a realm-appropriate exit when the failed address was inside a realm", () => {
    nav.pathname = "/admin/tenants/nope";
    const { container } = render(<NotFound />);
    expect(container.querySelector("a[href]")?.getAttribute("href")).toBe("/admin");

    nav.pathname = "/c/kirana-mart/leads/nope";
    const client = render(<NotFound />);
    expect(client.container.querySelector("a[href]")?.getAttribute("href")).toBe("/c");
  });

  it("is what an unknown legal slug now reaches", async () => {
    // `legal/[slug]/page.tsx:38` is the product's ONLY `notFound()` call, and its docstring
    // says an unknown slug "should tell the reader there is no such document". Until this
    // change it reached Next's unstyled default. The framework signals a 404 by THROWING,
    // which the router catches and answers with `app/not-found.tsx` — the screen the cases
    // above cover. So what is asserted here is the hand-off: the route raises the signal.
    vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      await act(async () => {
        render(<LegalDocumentRoute params={Promise.resolve({ slug: "gdpr" })} />);
      });
    } catch {
      // The framework signal, propagating because there is no router above this render.
    }
    // Called, not called ONCE: React re-renders a component that threw before it gives up,
    // so the count is an implementation detail of the renderer and not of this route.
    expect(nav.notFound).toHaveBeenCalled();
  });

  it("still resolves a REAL legal slug to its document rather than to the 404", async () => {
    // The other half of the same rule: a route that 404s everything would pass the case
    // above and break the product.
    await act(async () => {
      render(<LegalDocumentRoute params={Promise.resolve({ slug: "privacy" })} />);
    });
    expect(nav.notFound).not.toHaveBeenCalled();
  });
});

describe("the offline strip", () => {
  it("renders nothing at all while the browser is online", () => {
    const { container } = render(<OfflineBanner />);
    expect(container.innerHTML).toBe("");
  });

  it("says so, politely, once the browser goes offline", () => {
    browserOffline();
    render(<OfflineBanner />);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("You are offline");
    // `status`, not `alert`: losing a connection must not cut across whatever a screen
    // reader is currently saying.
    expect(status.getAttribute("role")).toBe("status");
  });
});
