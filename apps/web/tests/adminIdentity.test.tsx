import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AdminLayout from "@/app/admin/layout";
import AdminClientsPage from "@/app/admin/page";
import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import type { TenantSummary } from "@/lib/api/admin";
import { HOLDS_PATH } from "@/lib/api/holds";

import { act } from "@testing-library/react";

import { problem, renderAdminPage, stillLoading, type Routes } from "./harness";

/**
 * What the admin realm's identity read drives — the nav and the screens' own gates.
 *
 * `GET /v1/admin/me` (apps/api/admin/routes.py) is new, and it exists because the console
 * previously had no way to ask who it was: `/v1/me` reaches the admin realm only when
 * `X-Impersonate-Org` is present (core/auth.py), so this shell either impersonated some
 * client to find out, or guessed from a 403 on whatever the current screen happened to
 * read. This file pins the behaviour that one endpoint now owns, worst failure first:
 *
 * 1. **An entry the session cannot use is never a live link, and never merely missing.**
 *    `/admin/ops` needs `ops:manage`, which only `superadmin` holds (core/rbac.py), so an
 *    `operator` following it got a page that is entirely a 403. Shown-and-dead WITH the
 *    reason is the console's existing doctrine for controls (`useWriteAccess` +
 *    `RestrictionNote`), and the sidebar now follows it.
 * 1b. **EXACTLY ONE ENTRY IS THE OTHER WAY, AND IT IS PINNED AS AN EXCEPTION RATHER THAN
 *    AS THE RULE.** Platform configuration (`/admin/ops/config`, `platform:config`) is
 *    ABSENT for a session that may not use it — the founder's instruction when they drew
 *    the tier boundary, and `layout.tsx::renderItem` weighs it against the doctrine's own
 *    three reasons. The cases below assert both halves: this entry vanishes and every
 *    other refused entry does not, so a future edit that "tidied up" by hiding the rest
 *    fails here.
 * 2. **The unknown is not a refusal — in EITHER direction.** While the identity read is
 *    in flight, and if it fails outright, every entry stays live: the API is the
 *    enforcement, and a console that locks an operator out of the ops surface because a
 *    read was slow is worse than one that lets them meet the server's own answer. The
 *    other side of the same rule is that nothing appears or disappears once the answer
 *    lands, so no entry flashes in or out under the pointer.
 *    - The hidden entry falls on the OPPOSITE side of the unknown, and has to: `refused`
 *      is false while the read is in flight and after it fails, so an entry rendered on
 *      `!refused` would be shown to every normal admin for the whole of that window.
 *      It renders on `allowed` instead — absent until the server has said yes.
 * 3. **A screen's own gate comes from the same answer.** The directory's "New client"
 *    used to be gated on a 403 from the directory read itself — one of three mechanisms
 *    for one question; there is now one.
 */

const TENANTS_PATH = "/v1/admin/tenants";

function me(over: Partial<AdminMe> = {}): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-7777-7000-8000-0000000000a1",
    role: "operator",
    permissions: ["admin:tenants", "agents:read", "billing:read", "org:read"],
    ...over,
  };
}

const OPERATOR = me();
const SUPERADMIN = me({
  role: "superadmin",
  permissions: [
    "admin:tenants",
    "agents:read",
    "billing:read",
    "ops:manage",
    "org:read",
    // The two the ops config screen is gated on. Present here because `superadmin` holds
    // every permission by derivation (`core/rbac.SUPERADMIN_PERMISSIONS`), so a fixture
    // calling itself a superadmin while missing them describes a session the server
    // cannot issue — and it is what the hidden-entry cases below turn on.
    "platform:config",
    "platform:secrets",
  ],
});

/**
 * Render the shell with the session restored and `/v1/admin/me` still open.
 *
 * Two reads, two states, and only the second one is what this file is about. `act` lets
 * the gate resolve; `stillLoading()` keeps the identity query pending for as long as the
 * assertion needs.
 */
async function renderShellWithIdentityInFlight(): Promise<HTMLElement> {
  let container!: HTMLElement;
  await act(async () => {
    container = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell({ [ADMIN_ME_PATH]: stillLoading() }),
    ).container;
  });
  return container;
}

/** The shell's own reads: the identity and the header's hold count. */
function shell(over: Routes = {}): Routes {
  return {
    [ADMIN_ME_PATH]: OPERATOR,
    [HOLDS_PATH]: [],
    ...over,
  };
}

function tenant(over: Partial<TenantSummary> = {}): TenantSummary {
  return {
    id: "0192f0aa-7777-7000-8000-0000000000b1",
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 12,
    leads: 4,
    last_call_at: null,
    holds: [],
    capped: false,
    ...over,
  };
}

/** The Operations entry as the sidebar renders it — a link, or a dead label. */
function operationsEntry(container: HTMLElement): HTMLElement | null {
  return navEntry(container, "Operations");
}

/** Any sidebar entry by its label — a link, a dead label, or null when it is not there. */
function navEntry(container: HTMLElement, label: string): HTMLElement | null {
  return (
    Array.from(container.querySelectorAll<HTMLElement>("a, span")).find(
      (node) => node.textContent?.trim() === label,
    ) ?? null
  );
}

describe("the admin nav, once the console knows who it is", () => {
  it("offers Operations to a superadmin as a real link", async () => {
    const { container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell({ [ADMIN_ME_PATH]: SUPERADMIN }),
    );

    await waitFor(() => expect(operationsEntry(container)?.tagName).toBe("A"));
    expect(operationsEntry(container)?.getAttribute("href")).toBe("/admin/ops");
    expect(container.textContent).not.toContain("does not have permission");
  });

  it("leaves Operations dead for an operator, and says which permission is missing", async () => {
    const { container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell(),
    );

    // Not a link — the click that only ever produced a 403 is no longer offered.
    await waitFor(() => expect(operationsEntry(container)?.tagName).toBe("SPAN"));
    expect(operationsEntry(container)?.getAttribute("aria-disabled")).toBe("true");
    expect(container.querySelector('a[href="/admin/ops"]')).toBeNull();

    // Dead AND explained, in the DOM rather than only in a `title` a mouse discovers:
    // the permission is what the operator has to go and ask a superadmin for.
    expect(container.textContent).toContain("open the operations console");
    expect(container.textContent).toContain("open the operations console");
    expect(container.textContent).toContain("Ask a superadmin");
  });

  it("does NOT hide the entry it refuses", async () => {
    // The deliberate half of the choice (see the doctrine note in layout.tsx): a console
    // whose shape depends on the viewer cannot be talked about between two operators, and
    // an absent entry reads as a broken build rather than as a permission answer.
    const { container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell(),
    );

    await waitFor(() => expect(operationsEntry(container)?.tagName).toBe("SPAN"));
    expect(container.textContent).toContain("Operations");
    // And the entries this session CAN use are untouched — one refusal, not a blanket.
    for (const label of ["Clients", "Client health", "Held accounts", "New client"]) {
      const entry = Array.from(container.querySelectorAll("a")).find(
        (node) => node.textContent?.trim() === label,
      );
      expect(entry, `${label} must still be a link`).toBeDefined();
    }
  });

  it("offers Platform configuration to a superadmin as a real link", async () => {
    // The founder's ask, at the seam it was asked for: "only super admin has access to
    // ops config panel and it should be added to the sidebar in the super admin login".
    // Before this it had no entry at all — the panel was the bottom third of Operations.
    const { container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell({ [ADMIN_ME_PATH]: SUPERADMIN }),
    );

    await waitFor(() =>
      expect(navEntry(container, "Platform configuration")?.tagName).toBe("A"),
    );
    expect(navEntry(container, "Platform configuration")?.getAttribute("href")).toBe(
      "/admin/ops/config",
    );
  });

  it("does not show Platform configuration to an operator AT ALL — absent, not dead", async () => {
    // The ONE exception to the shell's shown-and-dead doctrine, and the assertions are
    // deliberately in both directions: this entry is gone, and the other refused entry on
    // the same screen is still there with its reason. A future change that hid every
    // refused entry would pass the first assertion and fail the second.
    const { container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell(),
    );

    await waitFor(() => expect(operationsEntry(container)?.tagName).toBe("SPAN"));
    expect(navEntry(container, "Platform configuration")).toBeNull();
    expect(container.querySelector('a[href="/admin/ops/config"]')).toBeNull();
    // Not hidden AND explained — hidden means hidden. A leftover sentence naming the
    // permission would be the entry back in a costume.
    expect(container.textContent).not.toContain("platform:config");
    // The doctrine still holds for everything else.
    expect(container.textContent).toContain("Operations");
    expect(container.textContent).toContain("open the operations console");
  });

  it("keeps Platform configuration hidden while the identity read is in flight", async () => {
    // THE INVERTED UNKNOWN, and it is the whole reason the flag keys on `allowed` rather
    // than on `!refused`. `refused` is false until the server answers, so an entry
    // rendered on `!refused` would be visible to every normal admin for the entire
    // in-flight window — the exact state the entry exists to prevent. Meanwhile the
    // entries that fail OPEN are untouched, which is what keeps an unreadable identity
    // from locking anybody out of the ops surface (BACKEND-PATTERNS §6).
    const container = await renderShellWithIdentityInFlight();

    expect(container.querySelector('a[href="/admin/ops/config"]')).toBeNull();
    expect(container.querySelector('a[href="/admin/ops"]')).not.toBeNull();
  });

  it("keeps every entry live while the identity read is still in flight", async () => {
    // The IDENTITY read is what must not withdraw an entry — an entry that flashes out
    // and in is indistinguishable from a bug, and the API refuses the request anyway.
    //
    // The session restore is a DIFFERENT read and is awaited first (D-177): before it
    // answers there is no console at all, only the gate, so "the nav is still complete"
    // is not a question that can be asked. `/v1/admin/me` is held open by
    // `stillLoading()` so the state under test is the one this test is named for.
    const container = await renderShellWithIdentityInFlight();

    expect(container.querySelector('a[href="/admin/ops"]')).not.toBeNull();
    expect(container.textContent).not.toContain("does not have permission");
  });

  it("keeps Operations reachable when the identity itself cannot be read", async () => {
    // The load-shed rule in the browser (BACKEND-PATTERNS §6): `/v1/ops` is never shed
    // because an operator must not be able to lock themselves out. A nav that went dark
    // on an unreadable identity would undo that from the other end — and mid-incident is
    // exactly when the identity read is most likely to be the thing that failed.
    const { container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell({ [ADMIN_ME_PATH]: problem(503, { title: "Service unavailable", retryable: true }) }),
    );

    await waitFor(() => expect(screen.getByText("Admin realm")).toBeDefined());
    expect(container.querySelector('a[href="/admin/ops"]')).not.toBeNull();
    // And no invented refusal: "we could not ask" is not "you may not".
    expect(container.textContent).not.toContain("does not have permission to");
  });

  it("names the role the server reported, and never one it did not", async () => {
    const { container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell({ [ADMIN_ME_PATH]: SUPERADMIN }),
    );

    await waitFor(() => expect(container.textContent).toContain("superadmin"));
    expect(container.textContent).toContain("signed in across every client");
  });

  it("asks for its identity ONCE for the whole shell, with no tenant attached", async () => {
    const { calls, container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell(),
    );

    await waitFor(() => expect(operationsEntry(container)?.tagName).toBe("SPAN"));
    const identity = calls.filter((call) => call.path === ADMIN_ME_PATH);
    // The sidebar and the identity footer both read it; one request answers both.
    expect(identity).toHaveLength(1);
    // The whole point of the endpoint: no impersonation, so no client is entered and no
    // `admin:impersonate` is spent to find out who we are.
    expect(identity[0]?.headers["X-Impersonate-Org"]).toBeUndefined();
    // ABSENT, not empty, and the change is a strengthening of this same claim.
    // `apiRequest` used to send `X-Org-Slug` unconditionally, so an admin session — which
    // has no slug — put an empty one on every request. It is now omitted when there is no
    // account to name, the way `Authorization` already was, which is what lets `/c` ask
    // `/v1/me` "which account is mine" before the answer is known. "No tenant attached"
    // is exactly what this asserted before; it can now assert it literally.
    expect(identity[0]?.headers["X-Org-Slug"]).toBeUndefined();
  });
});

describe("the client directory's create gate", () => {
  it("offers New client to a session that holds admin:tenants", async () => {
    renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: OPERATOR,
      [TENANTS_PATH]: [tenant()],
    });

    const link = await screen.findByRole("link", { name: /New client/ });
    expect(link.getAttribute("href")).toBe("/admin/new");
  });

  it("refuses it from the identity read, not from a 403 on the directory", async () => {
    // The directory answers 200 here, which is the case the old mechanism could not see
    // at all: it could only refuse once its OWN read had failed.
    const { container } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: me({ permissions: ["org:read", "agents:read"] }),
      [TENANTS_PATH]: [tenant()],
    });

    await screen.findByText(/does not have permission to/);
    expect(screen.queryByRole("link", { name: /New client/ })).toBeNull();
    expect(container.textContent).toContain("create clients");
    // The list still renders: reading is not what was refused.
    expect(container.textContent).toContain("Sri Traders");
  });

  it("still disables creation when the directory could not be read", async () => {
    // Unchanged and NOT a permission fact: a directory we could not read is one whose
    // slug collisions we cannot see, so the wizard stays shut whatever the role.
    const { container } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: OPERATOR,
      [TENANTS_PATH]: problem(503, { title: "Service unavailable", retryable: false }),
    });

    await screen.findByText(/the directory could not be read/);
    expect(screen.queryByRole("link", { name: /New client/ })).toBeNull();
    // …and it must not read as a refusal aimed at the operator.
    expect(container.textContent).not.toContain("does not have permission to");
  });

  it("offers nothing and explains nothing until an answer is in hand", () => {
    const { container } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: OPERATOR,
      [TENANTS_PATH]: [tenant()],
    });

    expect(screen.queryByRole("link", { name: /New client/ })).toBeNull();
    expect(container.textContent).not.toContain("does not have permission to");
    expect(container.textContent).not.toContain("could not be read");
  });
});
