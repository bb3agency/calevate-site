import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminLayout from "@/app/admin/layout";
import ClientRealmLayout from "@/app/c/[slug]/layout";
import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { MAIN_CONTENT_ID } from "@/components/ui";
import { HOLDS_PATH } from "@/lib/api/holds";
import { CLIENT_ACCOUNT_PATH } from "@/lib/authn/clientAuthn";
import { currentNavItem } from "@/lib/nav";

import { browserOffline, renderAdminPage, stubApi, type Routes } from "./harness";

/**
 * The two things every screen in the product inherits from its shell: a way past the
 * navigation, and an answer to "where am I".
 *
 * ## Neither is checkable by the a11y sweep, and that is why this file exists
 *
 * `tests/a11y.ts` says so itself: `bypass`, `region`, `landmark-one-main` and
 * `page-has-heading-one` are properties of a DOCUMENT, and the sweep scans a detached
 * container, so axe reports them inapplicable and stays green whether a skip link exists
 * or not. Adding `bypass` to the sweep would be a rule that silently never runs — the
 * exact "confident PASS on a check that never ran" that file refuses. So the skip link is
 * asserted here, on the shells, as markup: an anchor whose target exists and can take
 * focus.
 *
 * ## What the "you are here" tests are really pinning
 *
 * Each shell used to compute the header title by longest-prefix match and the sidebar
 * highlight by exact match, four lines apart, with `aria-current="page"` bound to the
 * exact-match one. On every detail route in the product — `/c/<slug>/calls/<id>`,
 * `/c/<slug>/leads/<id>`, `/admin/tenants/<id>` and its seven children,
 * `/admin/qa-sampling/<id>` — the header named a section and NO element in the document
 * carried `aria-current` at all.
 *
 * The assertions are therefore about AGREEMENT, not about a particular label: the element
 * marked current and the heading on screen must name the same screen. A test that only
 * checked "some link has aria-current" would pass on a shell that highlighted the wrong
 * one, which is the half of the defect that is invisible.
 */

let pathname = "/";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => pathname,
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

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
 * Async since D-177: the shell sits behind the admin realm's own session gate, so a
 * synchronous render returns with the gate still deciding and no sidebar in the tree.
 * `stubApi` answers the restore by default; this is what waits for it. Same shape as
 * navDrawer.test.tsx's.
 */
async function renderAdminShell(at: string): Promise<HTMLElement> {
  pathname = at;
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

/**
 * The client shell mounts its OWN `ClientRealmProvider`, so `renderClientPage` would nest
 * a second one — a composition the app never has. Same reasoning as navDrawer.test.tsx.
 */
async function renderClientShell(at: string): Promise<HTMLElement> {
  pathname = at;
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

beforeEach(() => {
  pathname = "/";
});

/**
 * The skip link, checked as the BEHAVIOUR rather than as a string.
 *
 * Three things have to hold together and each one alone is a skip link that does nothing:
 * the anchor is first in the tab order (a bypass control after the nav bypasses nothing),
 * its fragment resolves to an element that exists, and that element can take focus —
 * following a fragment scrolls to a non-focusable target but leaves focus where it was, so
 * the next Tab walks straight back into the 21 links the reader just asked to skip.
 */
function assertSkipLink(container: HTMLElement): void {
  const focusables = Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  );
  const first = focusables[0];
  expect(first, "nothing focusable in the shell at all").toBeTruthy();
  expect(first.tagName, "the first focusable thing in the shell is not a link").toBe("A");
  expect(first.getAttribute("href")).toBe(`#${MAIN_CONTENT_ID}`);
  expect(first.textContent).toMatch(/skip to main content/i);

  const target = container.querySelector(`#${MAIN_CONTENT_ID}`);
  expect(target, "the skip link points at an id no element carries").toBeTruthy();
  expect(target!.tagName, "the skip target is not the main landmark").toBe("MAIN");
  // -1 and not 0: reachable by a fragment, never a stop on the way there.
  expect(target!.getAttribute("tabindex")).toBe("-1");
}

describe("skip to main content", () => {
  it("is the first thing a keyboard reaches — client realm", async () => {
    assertSkipLink(await renderClientShell("/c/acme"));
  });

  it("is the first thing a keyboard reaches — admin realm", async () => {
    assertSkipLink(await renderAdminShell("/admin"));
  });
});

/** The one element the document says is the current screen, or null. */
function currentLink(container: HTMLElement): HTMLElement | null {
  const marked = container.querySelectorAll<HTMLElement>('[aria-current="page"]');
  expect(marked.length, "more than one element claims to be the current page").toBeLessThan(2);
  return marked[0] ?? null;
}

describe("where am I", () => {
  /**
   * Detail routes, which is where the split showed. `/c/acme` and `/admin` were always
   * fine — an exact match and a prefix match agree on an exact path — so a test that only
   * visited section roots would have been green throughout the defect.
   */
  const CLIENT_DETAIL_ROUTES = [
    "/c/acme/calls/018f3c00-0000-7000-8000-000000000001",
    "/c/acme/leads/018f3c00-0000-7000-8000-000000000002",
    // The agents console has two routes under its nav entry (D-440): one agent, and the
    // form that builds one. Both must carry the section up to "Agents" — a detail screen
    // that highlights nothing is the exact defect this block exists for, and these are the
    // newest two places to reintroduce it.
    "/c/acme/agents/018f3c00-0000-7000-8000-000000000005",
    "/c/acme/agents/new",
  ];
  const ADMIN_DETAIL_ROUTES = [
    "/admin/tenants/018f3c00-0000-7000-8000-000000000003",
    "/admin/tenants/018f3c00-0000-7000-8000-000000000003/kyc",
    "/admin/tenants/018f3c00-0000-7000-8000-000000000003/credits",
    "/admin/qa-sampling/018f3c00-0000-7000-8000-000000000004",
  ];

  it.each(CLIENT_DETAIL_ROUTES)(
    "marks the section a client detail route belongs to — %s",
    async (route) => {
      const container = await renderClientShell(route);
      const link = currentLink(container);
      expect(link, `no aria-current anywhere on ${route}`).toBeTruthy();
      // The heading the shell prints and the entry it marked must be the same screen.
      // Two rules four lines apart is how they came to differ in the first place.
      const heading = container.querySelector("h1");
      expect(heading?.textContent?.trim()).toBe(link!.textContent?.trim());
    },
  );

  it.each(ADMIN_DETAIL_ROUTES)(
    "marks the section an admin detail route belongs to — %s",
    async (route) => {
      const container = await renderAdminShell(route);
      const link = currentLink(container);
      expect(link, `no aria-current anywhere on ${route}`).toBeTruthy();
      const heading = container.querySelector("h1");
      expect(heading?.textContent?.trim()).toBe(link!.textContent?.trim());
    },
  );

  it("names the section 'Agents', not 'Voice agents'", async () => {
    // The rename is copy, and copy regresses silently. It is pinned HERE rather than in a
    // screen test because the nav list is the ONE place the word is written — the shell
    // prints the page title from it, so this assertion covers the sidebar entry and the
    // header of every screen in the section at once.
    const container = await renderClientShell("/c/acme/agents");
    const link = currentLink(container);
    expect(link?.textContent?.trim()).toBe("Agents");
    expect(container.textContent).not.toContain("Voice agents");
  });

  it("marks nothing on a path no nav entry owns", async () => {
    // Fail-closed the other way: inventing a highlight for an unknown path would tell a
    // reader they are somewhere they are not. A DIFFERENT SLUG is the honest way to reach
    // that state here, because every entry in this shell's list is under `/c/acme` — so
    // `/c/acme/anything-at-all` legitimately belongs to the dashboard, and asserting
    // otherwise would be asserting a bug.
    const container = await renderClientShell("/c/other-tenant/leads");
    expect(currentLink(container)).toBeNull();
  });
});

/**
 * The rule itself, at the unit — the shells above prove it is WIRED, this proves it is
 * RIGHT. Both are needed: a correct rule nobody reads and a read rule that is wrong fail
 * in ways the other test cannot see.
 */
describe("currentNavItem", () => {
  const NAV = [
    { href: "/admin" },
    { href: "/admin/new" },
    { href: "/admin/ops" },
    { href: "/admin/ops/dnc" },
    // The newest child of `/admin/ops` (the founder's correction to D-457 gave the ops
    // config panel its own screen), and the one that makes the longest-prefix rule pay
    // for itself twice: it is a sibling of `/admin/ops/dnc` AND a child of `/admin/ops`.
    { href: "/admin/ops/config" },
  ];

  it("prefers the longest matching prefix, not list order", () => {
    // The admin shell's own comment relies on this: `/admin/ops/dnc` keeps its own name
    // instead of inheriting "Operations".
    expect(currentNavItem(NAV, "/admin/ops/dnc")?.href).toBe("/admin/ops/dnc");
    expect(currentNavItem(NAV, "/admin/ops/dnc/anything")?.href).toBe("/admin/ops/dnc");
    expect(currentNavItem(NAV, "/admin/ops")?.href).toBe("/admin/ops");
    // Platform configuration keeps its own name rather than inheriting "Operations",
    // which is the whole reason it could not have been an anchor on `/admin/ops`.
    expect(currentNavItem(NAV, "/admin/ops/config")?.href).toBe("/admin/ops/config");
  });

  it("matches on a path SEGMENT, so a longer sibling name cannot borrow the prefix", () => {
    // Without the `/` boundary `/admin/newsletter` would resolve to `/admin/new`.
    expect(currentNavItem(NAV, "/admin/newsletter")?.href).toBe("/admin");
  });

  it("carries a detail route up to its section", () => {
    expect(currentNavItem(NAV, "/admin/tenants/abc/kyc")?.href).toBe("/admin");
  });

  it("answers undefined rather than guessing", () => {
    expect(currentNavItem(NAV, "/somewhere-else")).toBeUndefined();
    expect(currentNavItem([], "/admin")).toBeUndefined();
  });
});

/**
 * THE ONE CONTROL ON THIS SHELL THAT IS ABOUT THE PERSON, NOT THE BUSINESS.
 *
 * `POST /password/change` shipped with a form on `/auth/account` and no door to it from
 * inside the console: the only link in the product was in the marketing header, which
 * nobody sees once they are working. A feature reachable only by typing a URL is the
 * half-wired defect at its quietest — every test green, and no client ever finds it.
 *
 * Asserted as REACHABILITY (an anchor to that path, with a name a person can act on)
 * rather than as a position or a label, because where it sits is a design decision and
 * whether it exists is not.
 */
/**
 * A TRUNCATED VALUE NOBODY CAN READ IS NOT INFORMATION THE SCREEN IS SHOWING.
 *
 * The client shell's identity block names the account you are signed into, inside a fixed
 * 255px panel with `truncate` and — until 9 Sep 2026 — no `title`, no tooltip and no
 * expanded view. A real Indian SMB name ("Sri Lakshmi Multispeciality Dental Clinic") is
 * cut, and on the one line in the console that answers "whose data am I about to change"
 * there was no way to find out.
 *
 * The truncation itself STAYS, and deliberately: the panel width is fixed and no honest
 * short form of an arbitrary business name exists. What changed is that the full value is
 * reachable, which is the minimum this defect class demands.
 */
describe("the account name is readable, not merely present", () => {
  it("puts the whole organisation name within reach when the panel clips it", async () => {
    const container = await renderClientShell("/c/acme");
    const named = [...container.querySelectorAll<HTMLElement>("[title]")].find(
      (el) => el.getAttribute("title") === "Acme",
    );
    expect(named, "the sidebar's account name is truncated with no way to read it").toBeTruthy();
    expect(named?.className).toContain("truncate");
  });
});

describe("your own account", () => {
  it("is reachable from the client console", async () => {
    const container = await renderClientShell("/c/acme");
    const account = [...container.querySelectorAll("a[href]")].filter(
      (a) => a.getAttribute("href") === CLIENT_ACCOUNT_PATH,
    );
    expect(account, "no link from the console to /auth/account").toHaveLength(1);
    // The accessible name survives the collapsed rail, so it is asserted on the element
    // rather than on the expanded label alone.
    expect(account[0].textContent).toMatch(/account/i);
  });
});

/**
 * AN OPERATOR MUST NEVER BELIEVE THEY ARE IN A CLIENT ACCOUNT.
 *
 * The two shells were the same shell — same header height and surface, same nav
 * highlight, same green — and the only thing separating them was TEXT: the words "Admin
 * realm" in the sidebar footer and a `hidden sm:inline-block` badge in the header, one at
 * each end of the window and one of them not rendered at all on a phone. Peripheral vision
 * does not read words, and every action in the admin realm is cross-tenant.
 *
 * So the assertions below are deliberately about the difference SURVIVING the words: the
 * markers are stripped of their text and the shells must still be told apart. A future
 * change that swapped the colour treatment back for a label would pass a "does it say
 * Admin" test and fail this one, which is the point.
 */
describe("the two consoles do not look like each other", () => {
  it("renders NO rail across the top of the admin window, and no leftover of one", async () => {
    // THE RAIL IS GONE (founder, 9 Sep 2026). It was an `h-1.5` slate bar above the
    // sidebar and the content — which is why this shell was a COLUMN where the client
    // shell is a row — and the founder removed it on the ground that the sidebar already
    // says "Calevate admin / Operator console" and the identity block already says who
    // you are signed in as, so the realm is stated twice in words before any chrome.
    //
    // This asserts the ABSENCE and the SHAPE together, because half a removal is the
    // likelier regression: a re-added rail, or a column wrapper left behind with one
    // child in it. The outermost shell element must be the same expression the client
    // shell uses.
    const admin = await renderAdminShell("/admin");
    expect(admin.querySelector("[data-admin-realm-rail]")).toBeNull();
    expect(admin.querySelector(".h-1\\.5.bg-slate-900")).toBeNull();

    const adminShell = admin.querySelector("[data-app-shell]");
    const clientShell = (await renderClientShell("/c/acme")).querySelector("[data-app-shell]");
    expect(adminShell?.className).not.toContain("flex-col");
    expect(adminShell?.className).toBe(clientShell?.className);
  });

  it("still tells the two shells apart without reading a word", async () => {

    // The identity block is what survives the rail's removal, and it is now the shell's
    // ONLY realm marker that is not a word — so it is asserted harder than it was, on
    // both the treatment and the absence of that treatment in the client shell.
    const admin = await renderAdminShell("/admin");
    const identity = admin.querySelector(".bg-slate-900.text-white");
    expect(identity, "the admin identity block is dressed like a client's").toBeTruthy();
    expect(identity?.textContent).toContain("Admin realm");

    const client = await renderClientShell("/c/acme");
    expect(client.querySelector(".bg-slate-900.text-white")).toBeNull();
  });
});

/**
 * THE OFFLINE STRIP IS MOUNTED IN BOTH SIGNED-IN SHELLS, not only on the auth pages.
 *
 * `components/offline.tsx` exists because TEN screens each hand-wrote their own
 * explanation of a paused TanStack query. The console it most needs to be in is the one a
 * clinic uses on a patchy mobile connection all day — a panel that stalls with no banner
 * saying why is the defect that component was written to end. `globalStates.test.tsx`
 * proves the strip renders when the browser goes offline; nothing proved anybody had put
 * it on screen, which is the half that can be deleted by accident.
 */
describe("the offline strip", () => {
  it("is above the content in the client shell", async () => {
    browserOffline();
    const container = await renderClientShell("/c/acme");
    const strip = container.querySelector('[role="status"]');
    expect(strip?.textContent).toContain("You are offline");
  });

  it("is above the content in the admin shell", async () => {
    browserOffline();
    const container = await renderAdminShell("/admin");
    const strip = container.querySelector('[role="status"]');
    expect(strip?.textContent).toContain("You are offline");
  });
});
