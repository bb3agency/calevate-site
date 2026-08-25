import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminLayout from "@/app/admin/layout";
import ClientRealmLayout from "@/app/c/[slug]/layout";
import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { HOLDS_PATH } from "@/lib/api/holds";

import { renderAdminPage, type Routes } from "./harness";

/**
 * The mobile navigation drawer, in BOTH shells, is gone when it is closed.
 *
 * The defect this pins: below `lg` the drawer is pushed off-screen with
 * `-translate-x-full` and nothing else, so its ~18 links and buttons stayed in the tab
 * order and in the accessibility tree. Sighted-mouse users never met it; a keyboard user
 * tabbing off the header's menu button walked an invisible menu, and a screen reader read
 * it out as page content.
 *
 * ## Why this counts elements instead of reading an attribute
 *
 * `expect(aside).toHaveAttribute("inert")` passes on a drawer that is OPEN, on a drawer
 * whose `inert` is the string `"false"` (what React 18 rendered for `inert={false}` —
 * a present attribute, therefore inert), and on a drawer that has been made inert at
 * every width including the desktop sidebar. All three are wrong, and only one of them is
 * the bug being fixed. The property under test is a BEHAVIOUR — "Tab cannot reach
 * anything in there" — so the assertion is the number of tabbable elements.
 *
 * `tabbablesWithin` below is this file's own model of that behaviour, deliberately NOT
 * imported from `components/navDrawer.tsx`: a test that measures the fix with the fix's
 * own helper cannot fail when that helper is wrong. It is the `tabbable` package's rule,
 * reduced to what jsdom can honestly answer — jsdom 30 implements no layout, so
 * visibility cannot be consulted, and it implements no `inert` semantics at all (an
 * element inside an `[inert]` subtree still takes `focus()` there), so the walk up the
 * ancestor chain is done here by hand exactly as a browser does it natively.
 */
const TABBABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function tabbablesWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(TABBABLE)).filter(
    (element) => element.closest("[inert]") === null && element.closest("[hidden]") === null,
  );
}

/** The drawer both shells render — found the way a user finds it, not by test id. */
function drawer(container: HTMLElement): HTMLElement {
  const aside = container.querySelector("aside");
  if (!aside) throw new Error("no <aside> in the shell — the drawer moved");
  return aside;
}

/**
 * Report a viewport, the way the drawer reads one.
 *
 * jsdom implements no `matchMedia`, so without this the component's
 * `useSyncExternalStore` snapshot is its "unknown width" answer (never an overlay) and
 * the mobile case cannot be reached at all. The stub evaluates the ONE width query the
 * drawer asks — anything else throws rather than quietly answering false, because a query
 * this stub does not understand means the test is no longer testing what it says it is.
 *
 * The shell also mounts the app-wide `ToastProvider`, whose motion layer reads
 * `(prefers-reduced-motion)`; that is a legitimate, benign a11y query (the whole component
 * library asks it, and `tests/setup.ts` answers it globally), so the stub answers it
 * "not requested" rather than throwing — it does not affect the drawer's tab order.
 */
function stubViewport(kind: "mobile" | "desktop"): void {
  const listeners = new Set<() => void>();
  const mediaListEntry = (query: string, matches: boolean) => ({
    media: query,
    matches,
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
    addListener: (listener: () => void) => listeners.add(listener),
    removeListener: (listener: () => void) => listeners.delete(listener),
    dispatchEvent: () => false,
    onchange: null,
  });
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => {
      if (query.startsWith("(prefers-reduced-motion")) {
        return mediaListEntry(query, false);
      }
      // The appearance toggle in both shell headers (`components/theme.tsx`) asks the
      // device preference while the choice is "follow my device", which is the default and
      // therefore every render here. Benign for the same reason as the line above: it is a
      // preference read, it answers "light", and it puts nothing in the tab order that the
      // drawer's counting could confuse. Answered rather than thrown, but still answered
      // EXPLICITLY — the throw below stays, so a genuinely unexpected query in the shell is
      // still a failure and not a silent false.
      if (query.startsWith("(prefers-color-scheme")) {
        return mediaListEntry(query, false);
      }
      if (query !== "(max-width: 1023.98px)") {
        throw new Error(`unexpected media query in the shell: ${query}`);
      }
      return {
        media: query,
        matches: kind === "mobile",
        addEventListener: (_: string, listener: () => void) => listeners.add(listener),
        removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
        addListener: (listener: () => void) => listeners.add(listener),
        removeListener: (listener: () => void) => listeners.delete(listener),
        dispatchEvent: () => false,
        onchange: null,
      };
    }),
  );
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
 * Async since D-177: the shell sits behind the admin realm's session gate, so a
 * synchronous render returns with the gate still deciding and the drawer not yet in the
 * tree. `stubApi` answers the restore by default; this is what waits for it.
 */
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
  stubApi({ "/v1/me": { organization: { name: "Acme" }, role: "owner" }, "/v1/attention": { total: 0 } });
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("mobile navigation drawer", () => {
  it("keeps nothing in the tab order while it is closed — admin realm", async () => {
    stubViewport("mobile");
    const container = await renderAdminShell();
    expect(tabbablesWithin(drawer(container))).toHaveLength(0);
  });

  it("keeps nothing in the tab order while it is closed — client realm", async () => {
    stubViewport("mobile");
    const container = await renderClientShell();
    expect(tabbablesWithin(drawer(container))).toHaveLength(0);
  });

  it("puts its links back in the tab order when it opens", async () => {
    stubViewport("mobile");
    const container = await renderAdminShell();
    act(() => {
      screen.getByLabelText("Open navigation").click();
    });
    // The premise of the two tests above: a drawer with nothing in it would satisfy them
    // for the wrong reason.
    expect(tabbablesWithin(drawer(container)).length).toBeGreaterThan(3);
  });

  it("never removes the desktop sidebar from the tab order", async () => {
    stubViewport("desktop");
    const container = await renderAdminShell();
    // Above `lg` the same element is the permanent sidebar and `isOpen` is false — the
    // regression a naive `inert={!isOpen}` would ship, unclickable and unfocusable.
    expect(tabbablesWithin(drawer(container)).length).toBeGreaterThan(3);
  });

  it("moves focus into the drawer on open and back to the trigger on Escape", async () => {
    stubViewport("mobile");
    const container = await renderAdminShell();
    const trigger = screen.getByLabelText("Open navigation");
    act(() => {
      // `focus()` before `click()`: a real click focuses the button it activates, and
      // jsdom's `click()` does not — without this the test would assert restoration to
      // `<body>`, which is not what any user does.
      trigger.focus();
      trigger.click();
    });
    const panel = drawer(container);
    expect(panel.contains(document.activeElement)).toBe(true);

    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(document.activeElement).toBe(trigger);
  });

  it("cycles Tab inside the open drawer instead of letting it escape", async () => {
    stubViewport("mobile");
    const container = await renderAdminShell();
    act(() => {
      screen.getByLabelText("Open navigation").click();
    });
    const panel = drawer(container);
    const items = tabbablesWithin(panel);
    act(() => {
      items[items.length - 1].focus();
      fireEvent.keyDown(document, { key: "Tab" });
    });
    expect(document.activeElement).toBe(items[0]);

    act(() => {
      fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    });
    expect(document.activeElement).toBe(items[items.length - 1]);
  });
});
