import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminLayout from "@/app/admin/layout";
import ClientRealmLayout from "@/app/c/[slug]/layout";
import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { HOLDS_PATH } from "@/lib/api/holds";
import {
  sidebarFadeClass,
  sidebarPanelClass,
} from "@/components/sidebarCollapse";

import { renderAdminPage, type Routes } from "./harness";
import { blankComments } from "./sourceScan";

/**
 * The desktop sidebar collapses as ONE gesture, and it does not move at all for a reader
 * who asked for less motion.
 *
 * ## What this file can and cannot measure
 *
 * jsdom implements no layout, no compositor and no CSS cascade, so it cannot watch a
 * transition run, cannot resolve `@media (prefers-reduced-motion: no-preference)` and
 * cannot tell you the panel is 72px wide. Asserting otherwise would be the vacuous pass
 * `tests/a11y.ts` and `tests/responsive.test.ts` both refuse at length.
 *
 * So the properties pinned here are the ones that are actually decidable in this
 * environment, and each of them is a defect that was really shipped rather than a
 * restatement of the code:
 *
 * 1. **Nothing unmounts.** The collapse used to be `{!isCollapsed && <span>{label}</span>}`
 *    in both shells, which is what made a width transition read as a bug (labels gone in
 *    one frame, panel sliding afterwards) AND what took every destination name out of the
 *    accessibility tree on the collapsed rail. Both halves are one assertion: after
 *    collapsing, the same links are still there with the same accessible names.
 * 2. **Every transition is `motion-safe:`-gated.** This is the only honest way to test
 *    `prefers-reduced-motion` without a browser: the preference is expressed in CSS, so
 *    what is checked is that no class in the shared module can emit a transition outside
 *    that variant. A browser would then have to be wrong about `motion-safe` for the
 *    reduced-motion state to animate.
 * 3. **The width is one expression with an unprefixed base width.** `tests/responsive.
 *    test.ts` owns that rule (it is a mobile-drawer property, not an animation one); what
 *    is checked here is that the two states differ at all, so a "smooth collapse" that
 *    collapses to nothing cannot pass.
 *
 * WHAT NOBODY HAS MEASURED, said plainly rather than left to a green tick: the transition
 * has NOT been watched in a browser from this container, so no assertion here or anywhere
 * else in this repo would catch a bad easing curve, a duration that feels wrong, or the
 * main column beside the panel juddering as it reflows. Those are eyes-on-a-screen
 * properties and this suite is not the instrument for them — `tests/responsive.test.ts`
 * makes the same distinction at length about layout.
 */

const MODULE = join(process.cwd(), "src", "components", "sidebarCollapse.tsx");

/**
 * The module with every comment line blanked — the prose above explains `motion-safe:`
 * and names `transition-property`, `ease-out` and `duration-200` in sentences, and a
 * scanner that reads its own documentation as code is a guard nobody can trust.
 */
function moduleCode(): string {
  return blankComments(readFileSync(MODULE, "utf8").split("\n")).join("\n");
}

const ADMIN_ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000a1",
  role: "superadmin",
  permissions: ["admin:tenants", "org:read", "ops:manage"],
};

const ADMIN_ROUTES: Routes = {
  [ADMIN_ME_PATH]: ADMIN_ME,
  [HOLDS_PATH]: [],
  "/v1/admin/tenants": [],
};

/**
 * The desktop viewport, which is the only one this control exists at — its button is
 * `lg:flex`. jsdom has no `matchMedia`, and `NavDrawer` asks for one width query; anything
 * else means the shell started asking a question this stub is not modelling.
 */
function stubDesktopViewport(): void {
  const noopList = (query: string, matches: boolean) => ({
    media: query,
    matches,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
    onchange: null,
  });
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => {
      if (query.startsWith("(prefers-reduced-motion")) return noopList(query, false);
      if (query !== "(max-width: 1023.98px)") {
        throw new Error(`unexpected media query in the shell: ${query}`);
      }
      return noopList(query, false);
    }),
  );
}

async function renderAdminShell(): Promise<HTMLElement> {
  let container!: HTMLElement;
  await act(async () => {
    container = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      ADMIN_ROUTES,
    ).container;
  });
  return container;
}

async function renderClientShell(): Promise<HTMLElement> {
  // Not `renderClientPage`: this layout mounts its OWN `ClientRealmProvider`, and the
  // harness would nest a second one around it — a composition the app never has.
  const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
  const { stubApi } = await import("./harness");
  stubApi({
    "/v1/me": { organization: { name: "Acme" }, role: "owner" },
    "/v1/attention": { total: 0 },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let container!: HTMLElement;
  await act(async () => {
    const ui: ReactElement = (
      <QueryClientProvider client={client}>
        <ClientRealmLayout params={Promise.resolve({ slug: "acme" })}>
          <p>screen</p>
        </ClientRealmLayout>
      </QueryClientProvider>
    );
    container = render(ui).container;
  });
  return container;
}

/** The nav links in the panel, by accessible name — how a screen reader meets them. */
function sidebarLinkNames(container: HTMLElement): string[] {
  const aside = container.querySelector("aside");
  if (!aside) throw new Error("no <aside> in the shell — the sidebar moved");
  return Array.from(aside.querySelectorAll("a")).map((a) => (a.textContent ?? "").trim());
}

function collapse(): void {
  act(() => {
    screen.getByLabelText("Collapse sidebar").click();
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe.each([
  ["admin realm", renderAdminShell],
  ["client realm", renderClientShell],
])("collapsing the sidebar — %s", (_realm, renderShell) => {
  it("keeps every destination's name after it collapses", async () => {
    stubDesktopViewport();
    const container = await renderShell();
    const before = sidebarLinkNames(container);
    // The premise: a shell with no links would satisfy the equality below trivially.
    expect(before.length).toBeGreaterThan(3);
    expect(before.every((name) => name.length > 0)).toBe(true);

    collapse();

    // NOT "the labels are hidden": they are visually gone and still readable. This is the
    // exact assertion the old `{!isCollapsed && <span>}` failed.
    expect(sidebarLinkNames(container)).toEqual(before);
  });

  it("keeps the way out reachable on the collapsed rail", async () => {
    stubDesktopViewport();
    await renderShell();
    collapse();
    // `getByLabelText` resolves an accessible name, so this fails if the label is deleted
    // rather than faded — the one control a person must always be able to find.
    expect(screen.getByLabelText("Sign out")).toBeTruthy();
  });

  it("offers one toggle whose state and name follow the panel", async () => {
    stubDesktopViewport();
    await renderShell();
    const toggle = screen.getByLabelText("Collapse sidebar");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    collapse();

    // The SAME element, renamed — not a second button that appeared while the first was
    // removed, which is what the two shells used to do and is a pop in the middle of the
    // gesture.
    const expanded = screen.getByLabelText("Expand sidebar");
    expect(expanded).toBe(toggle);
    expect(expanded.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByLabelText("Collapse sidebar")).toBeNull();
  });

  it("changes the panel's width classes when it collapses", async () => {
    stubDesktopViewport();
    const container = await renderShell();
    const aside = container.querySelector("aside")!;
    const before = aside.className;
    collapse();
    expect(aside.className).not.toEqual(before);
    expect(aside.className).toContain("lg:w-[72px]");
  });
});

describe("prefers-reduced-motion", () => {
  /**
   * The reduced-motion branch, checked where it actually lives.
   *
   * `motion-safe:` compiles to `@media (prefers-reduced-motion: no-preference)`, so a
   * transition utility that is NOT behind it runs for everyone. jsdom cannot evaluate the
   * media query, so what is enforced is the invariant that makes the browser's answer the
   * only one that matters.
   */
  it("puts every transition in the shared module behind motion-safe:", () => {
    const source = moduleCode();
    const offenders = Array.from(
      source.matchAll(/[\w:[\]-]*\btransition-[\w[\]().,-]+/g),
      (m) => m[0],
    ).filter((token) => !token.includes("motion-safe:"));
    expect(
      offenders,
      `these transition utilities run even for a reader who asked for reduced motion:\n  ` +
        `${offenders.join("\n  ")}`,
    ).toEqual([]);
  });

  it("gates every duration, delay and easing on it too", () => {
    const source = moduleCode();
    const offenders = Array.from(
      source.matchAll(/[\w:[\]-]*\b(?:duration|delay|ease)-[\w[\]().,-]+/g),
      (m) => m[0],
    ).filter((token) => !token.includes("motion-safe:"));
    expect(offenders, `ungated timing utilities:\n  ${offenders.join("\n  ")}`).toEqual([]);
  });

  it("still reaches the correct final state with motion off", () => {
    // The classes that decide WHERE things end up carry no `motion-safe:` — only the ones
    // that decide how they get there do. A reduced-motion reader must get the collapsed
    // rail instantly, not a sidebar stuck half open.
    const collapsed = sidebarPanelClass(true).split(/\s+/);
    const expandedPanel = sidebarPanelClass(false).split(/\s+/);
    expect(collapsed).toContain("lg:w-[72px]");
    expect(expandedPanel).not.toContain("lg:w-[72px]");
    expect(collapsed).toContain("w-[255px]");
    expect(expandedPanel).toContain("w-[255px]");

    expect(sidebarFadeClass(true).split(/\s+/)).toContain("lg:opacity-0");
    expect(sidebarFadeClass(false).split(/\s+/)).toContain("lg:opacity-100");
  });

  it("never hides a label below lg, whatever the collapse state holds", () => {
    // `isCollapsed` is desktop-only state that SURVIVES A RESIZE (the bug
    // `tests/responsive.test.ts` pins for the width). If the fade were unprefixed, a
    // reader who collapsed the sidebar on a laptop and then opened the mobile drawer on a
    // narrow window would find a 255px drawer full of invisible text.
    for (const state of [true, false]) {
      for (const token of sidebarFadeClass(state).split(/\s+/)) {
        expect(
          token.startsWith("lg:"),
          `"${token}" applies below lg, where the drawer is always fully expanded`,
        ).toBe(true);
      }
    }
  });
});
