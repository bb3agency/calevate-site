import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AdminLayout from "@/app/admin/layout";
import AdminClientsPage from "@/app/admin/page";
import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import type { TenantSummary } from "@/lib/api/admin";
import { HOLDS_PATH } from "@/lib/api/holds";

import { problem, renderAdminPage, type Routes } from "./harness";

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
 * 2. **The unknown is not a refusal — in EITHER direction.** While the identity read is
 *    in flight, and if it fails outright, every entry stays live: the API is the
 *    enforcement, and a console that locks an operator out of the ops surface because a
 *    read was slow is worse than one that lets them meet the server's own answer. The
 *    other side of the same rule is that nothing appears or disappears once the answer
 *    lands, so no entry flashes in or out under the pointer.
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
  } as AdminMe;
}

const OPERATOR = me();
const SUPERADMIN = me({
  role: "superadmin",
  permissions: ["admin:tenants", "agents:read", "billing:read", "ops:manage", "org:read"],
});

/** The shell's own reads: the identity and the header's hold count. */
function shell(over: Routes = {}): Routes {
  return { [ADMIN_ME_PATH]: OPERATOR, [HOLDS_PATH]: [], ...over };
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
  } as TenantSummary;
}

/** The Operations entry as the sidebar renders it — a link, or a dead label. */
function operationsEntry(container: HTMLElement): HTMLElement | null {
  return (
    Array.from(container.querySelectorAll<HTMLElement>("a, span")).find(
      (node) => node.textContent?.trim() === "Operations",
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
    expect(container.textContent).not.toContain("ops:manage");
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
    expect(container.textContent).toContain("ops:manage");
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

  it("keeps every entry live while the identity read is still in flight", () => {
    // Rendered WITHOUT awaiting: this is the first paint, before any response. Nothing
    // may be withdrawn here and then given back — an entry that flashes out and in is
    // indistinguishable from a bug, and the API refuses the request anyway.
    const { container } = renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      shell(),
    );

    expect(container.querySelector('a[href="/admin/ops"]')).not.toBeNull();
    expect(container.textContent).not.toContain("ops:manage");
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
    expect(container.textContent).not.toContain("does not have the ops:manage permission");
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
    expect(identity[0]?.headers["X-Org-Slug"]).toBe("");
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

    await screen.findByText(/does not have the admin:tenants permission/);
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
    expect(container.textContent).not.toContain("does not have the admin:tenants permission");
  });

  it("offers nothing and explains nothing until an answer is in hand", () => {
    const { container } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: OPERATOR,
      [TENANTS_PATH]: [tenant()],
    });

    expect(screen.queryByRole("link", { name: /New client/ })).toBeNull();
    expect(container.textContent).not.toContain("does not have the admin:tenants permission");
    expect(container.textContent).not.toContain("could not be read");
  });
});
