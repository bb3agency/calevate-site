import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import AdminClientsPage from "@/app/admin/page";
import TenantActivityPage from "@/app/admin/tenants/[tenantId]/activity/page";
import TenantReadinessPage from "@/app/admin/tenants/[tenantId]/readiness/page";
import type { TenantSummary } from "@/lib/api/admin";
import type { ActivityEntry, ReadinessRow } from "@/lib/api/adminAccount";

import { problem, renderAdminPage, type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * THE THREE OPERATOR SURFACES FOR ONE CLIENT ACCOUNT: the roster, what is holding an
 * account up, and what has been done to it.
 *
 * What each test pins is the decision that is OURS rather than the server's, because the
 * server's own answers are pinned on its side (`tests/admin_account_management_test.py`):
 *
 * 1. **The directory is a window, and it must say so.** Every count on a paged screen is
 *    a chance to describe 25 rows as if they were a platform. The header, the pager and
 *    the two empty states are the three places that can go wrong, and each is asserted
 *    against a page whose total is deliberately larger than its rows.
 * 2. **Narrowing returns to the first page.** A filter applied while on page four asks
 *    for rows that the narrowed set does not have, and the operator is shown an empty
 *    table over a count that says otherwise.
 * 3. **Readiness is grouped by WHOSE MOVE, because that is the decision being made.**
 *    Not by severity — there is none, every row is blocking.
 * 4. **An act done through view-as is marked.** D-587 lets an operator change a client's
 *    account from inside the client's console; a trail that rendered those the same as
 *    the client's own acts would answer "did they do this or did we" wrongly.
 */

const TENANT = "0192f0aa-7777-7000-8000-00000000ad01";
const DIRECTORY = "/v1/admin/tenants";
const READINESS = `/v1/admin/tenants/${TENANT}/readiness`;
const ACTIVITY = `/v1/admin/tenants/${TENANT}/activity`;

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-00000000ad02",
  role: "operator",
  permissions: ["org:read", "admin:tenants"],
};

function tenant(over: Partial<TenantSummary> = {}): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 4,
    leads: 9,
    last_call_at: null,
    holds: [],
    capped: false,
    ...over,
  };
}

function page(rows: TenantSummary[], total = rows.length, offset = 0) {
  return { rows, total, limit: 25, offset };
}

function readinessRow(over: Partial<ReadinessRow> = {}): ReadinessRow {
  return {
    rule: "kyc_missing",
    title: "Identity not verified",
    reason: "This account has no verification on file.",
    actor: "calevate",
    next_step: "Record the verification on the Identity screen.",
    ...over,
  };
}

function entry(over: Partial<ActivityEntry> = {}): ActivityEntry {
  return {
    id: "0192f0aa-7777-7000-8000-00000000ae01",
    at: "2026-09-19T06:30:00Z",
    action: "admin.plan_tier_changed",
    object_type: "organization",
    object_id: TENANT,
    actor_type: "admin",
    actor_id: ME.user_id,
    actor_label: "Ops Anand",
    via_grant_id: null,
    ...over,
  };
}

const READINESS_ROUTES: Routes = {
  [ADMIN_ME_PATH]: ME,
  [`/v1/admin/tenants/${TENANT}`]: tenant(),
};

describe("the client directory scales", () => {
  it("prints the matching total rather than the size of the page", async () => {
    const { container } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: ME,
      [DIRECTORY]: page([tenant()], 312),
    });

    await screen.findByText(/Sri Traders/);
    // The number an operator reads back on a call. 312, not 1.
    expect(container.textContent).toContain("312 accounts");
    expect(container.textContent).toContain("Showing 1–1 of 312");
  });

  it("asks the server for the next page rather than slicing one it already has", async () => {
    const { calls } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: ME,
      [DIRECTORY]: page([tenant()], 312),
      [`${DIRECTORY}?offset=25&limit=25`]: page([tenant({ name: "Next Page Motors" })], 312, 25),
    });

    const next = await screen.findByRole("button", { name: /Next/ });
    fireEvent.click(next);

    await screen.findByText(/Next Page Motors/);
    expect(calls.some((call) => call.path.includes("offset=25"))).toBe(true);
  });

  it("sends the search to the server and goes back to the first page", async () => {
    const { calls } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: ME,
      [DIRECTORY]: page([tenant()], 312),
      [`${DIRECTORY}?offset=25&limit=25`]: page([tenant()], 312, 25),
      [`${DIRECTORY}?q=motors`]: page([tenant({ name: "Deccan Motors" })], 1),
    });

    fireEvent.click(await screen.findByRole("button", { name: /Next/ }));
    await waitFor(() => expect(calls.some((c) => c.path.includes("offset=25"))).toBe(true));

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "motors" } });

    await screen.findByText(/Deccan Motors/);
    const searched = calls.filter((call) => call.path.includes("q=motors"));
    expect(searched).not.toHaveLength(0);
    // The whole point: no request combines the new search with the old offset.
    expect(searched.every((call) => !call.path.includes("offset="))).toBe(true);
  });

  it("says nothing matched rather than that there are no clients", async () => {
    const { container } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: ME,
      [DIRECTORY]: page([tenant()], 312),
      [`${DIRECTORY}?q=zzz`]: page([], 0),
    });

    await screen.findByText(/Sri Traders/);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "zzz" } });

    await screen.findByText(/No account matches this search/);
    // The sentence that would be a lie: this platform has 312 clients.
    expect(container.textContent).not.toContain("No clients yet");
  });

  it("narrows by state through the server", async () => {
    const { calls } = renderAdminPage(<AdminClientsPage />, {
      [ADMIN_ME_PATH]: ME,
      [DIRECTORY]: page([tenant()], 312),
      [`${DIRECTORY}?status=suspended`]: page([tenant({ name: "Halted Traders" })], 1),
    });

    await screen.findByText(/Sri Traders/);
    fireEvent.click(screen.getByRole("button", { name: "suspended" }));

    await screen.findByText(/Halted Traders/);
    expect(calls.some((call) => call.path.includes("status=suspended"))).toBe(true);
  });
});

describe("readiness, as an operator reads it", () => {
  it("groups what is ours to clear apart from what is theirs, and counts ours", async () => {
    const { container } = await renderAdminRoute(
      <TenantReadinessPage params={routeParams({ tenantId: TENANT })} />,
      {
        ...READINESS_ROUTES,
        [READINESS]: {
          tenant_id: TENANT,
          may_operate: false,
          blocked_on_calevate: 1,
          rows: [
            readinessRow(),
            readinessRow({
              rule: "agreements_not_accepted",
              title: "Agreements not accepted",
              reason: "The account owner has not accepted the agreements.",
              actor: "client",
              next_step: "The owner accepts them on their own readiness screen.",
            }),
          ],
        },
      },
    );

    await screen.findByText("Ours to clear");
    expect(container.textContent).toContain("Theirs to clear");
    expect(container.textContent).toContain("1 of 2 are ours to clear");
    // The gate's own sentence, carried rather than paraphrased.
    expect(container.textContent).toContain("This account has no verification on file.");
    // And the row links to the screen that clears it.
    const link = screen.getByRole("link", { name: /Record verification/ });
    expect(link.getAttribute("href")).toBe(`/admin/tenants/${TENANT}/kyc`);
  });

  it("says plainly when nothing is in the way", async () => {
    const { container } = await renderAdminRoute(
      <TenantReadinessPage params={routeParams({ tenantId: TENANT })} />,
      {
        ...READINESS_ROUTES,
        [READINESS]: {
          tenant_id: TENANT,
          may_operate: true,
          blocked_on_calevate: 0,
          rows: [],
        },
      },
    );

    await screen.findByText(/Nothing is in the way/);
    expect(container.textContent).not.toContain("Ours to clear");
  });

  it("never renders a failed read as a clear account", async () => {
    const { container } = await renderAdminRoute(
      <TenantReadinessPage params={routeParams({ tenantId: TENANT })} />,
      {
        ...READINESS_ROUTES,
        [READINESS]: problem(503, { title: "Service unavailable", retryable: true }),
      },
    );

    await screen.findByText(/Service unavailable/);
    // The sentence that would send an operator to tell a client they are clear to dial.
    expect(container.textContent).not.toContain("Nothing is in the way");
  });
});

describe("the activity trail", () => {
  it("names the operator and marks an act done through view-as", async () => {
    const { container } = await renderAdminRoute(
      <TenantActivityPage params={routeParams({ tenantId: TENANT })} />,
      {
        ...READINESS_ROUTES,
        [`${ACTIVITY}?limit=25&offset=0`]: {
          tenant_id: TENANT,
          total: 2,
          limit: 25,
          offset: 0,
          entries: [
            entry(),
            entry({
              id: "0192f0aa-7777-7000-8000-00000000ae02",
              action: "leads.status_changed",
              via_grant_id: "0192f0aa-7777-7000-8000-00000000ae03",
            }),
          ],
        },
      },
    );

    await screen.findByText("admin.plan_tier_changed");
    expect(container.textContent).toContain("Ops Anand");
    // "One of us did this wearing the client's face" is a different fact from either
    // "we did this" or "they did this", and it has to be visible as one.
    expect(container.textContent).toContain("as the client");
  });

  it("asks the server to narrow by who acted", async () => {
    const { calls } = await renderAdminRoute(
      <TenantActivityPage params={routeParams({ tenantId: TENANT })} />,
      {
        ...READINESS_ROUTES,
        [`${ACTIVITY}?limit=25&offset=0`]: {
          tenant_id: TENANT,
          total: 1,
          limit: 25,
          offset: 0,
          entries: [entry()],
        },
        [`${ACTIVITY}?limit=25&offset=0&actor_type=user`]: {
          tenant_id: TENANT,
          total: 0,
          limit: 25,
          offset: 0,
          entries: [],
        },
      },
    );

    await screen.findByText("admin.plan_tier_changed");
    fireEvent.click(screen.getByRole("button", { name: "the client" }));

    await screen.findByText(/Nothing matches this filter/);
    expect(calls.some((call) => call.path.includes("actor_type=user"))).toBe(true);
  });
});
