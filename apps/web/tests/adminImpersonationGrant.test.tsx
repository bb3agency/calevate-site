import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH } from "@/app/admin/access";
import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import { IMPERSONATION_GRANT_PATH, clearImpersonationGrants } from "@/lib/api/admin";
import { apiRequest, type Session } from "@/lib/api/client";
import type { Routes } from "./harness";

import { problem, stubApi } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The console's half of D-22's session-start seam.
 *
 * The API now refuses `X-Impersonate-Org` unless a signed, tenant-bound grant comes with
 * it (`apps/api/core/auth.py`), and minting that grant is what writes
 * `admin.impersonation_started` — the row that was absent for every real session, because
 * nothing forced an operator through the endpoint that wrote it and this console never
 * called it. So the assertions here are about the seam, not about cosmetics: a console
 * that still only set the header would be refused on every client read, and every panel
 * on this screen would be an error state.
 *
 * `harness.tsx` answers the mint by default so the other ~10 suites keep their premise.
 * This file is where it is asserted rather than assumed.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const SLUG = "sri-traders";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;

/** The impersonated reads this screen makes — the ones that need the grant. */
const IMPERSONATED = [
  "/v1/kb/sources?status=pending_approval",
  "/v1/kb/sources?status=approved",
  "/v1/agents",
  "/v1/campaigns/numbers",
  "/v1/campaigns/templates",
  "/v1/billing/caps",
];

function routes(): Routes {
  return {
    [ADMIN_ME_PATH]: {
      realm: "admin",
      user_id: "0192f0aa-7777-7000-8000-0000000000cc",
      role: "operator",
      permissions: ["org:read", "billing:read", "agents:read", "kb:write", "admin:tenants"],
    },
    [TENANT_PATH]: {
      id: TENANT,
      name: "Sri Traders",
      slug: SLUG,
      status: "active",
      vertical_template: "clinic",
      live_agents: 2,
      calls_7d: 412,
      leads: 96,
      last_call_at: "2026-08-12T09:15:00Z",
      holds: [],
      capped: false,
    },
    [`${TENANT_PATH}/margin`]: {
      month: "2026-08",
      minutes_used: "1204.5",
      calls: 412,
      revenue_inr: "1015900.00",
      cost_inr: "402350.50",
      margin_inr: "613549.50",
      margin_pct: "60.39",
    },
    "/v1/kb/sources?status=pending_approval": [],
    "/v1/kb/sources?status=approved": [],
    "/v1/agents": [],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    "/v1/billing/caps": {
      month: "2026-08",
      plan_cap_minutes: 5000,
      plan_cap_spend_inr: "40000.00",
      client_cap_minutes: null,
      client_cap_spend_inr: null,
      effective_cap_minutes: 5000,
      effective_cap_spend_inr: "40000.00",
      minutes_used: "812.00",
      spend_used_inr: "5002.40",
      capped: false,
    },
  };
}

function page() {
  return <TenantDetailPage params={routeParams({ tenantId: TENANT })} />;
}

/**
 * Wait until the screen has stopped talking to the network.
 *
 * `renderAdminRoute` resolves once the route's params promise has settled, which is well
 * before six TanStack queries have issued their requests — the other suites on this
 * screen wait implicitly, by awaiting the sentence they assert on. These tests assert on
 * the REQUESTS, so the wait has to be explicit or they pass by inspecting an empty list.
 */
async function settled(calls: { path: string }[]): Promise<void> {
  await vi.waitFor(() => {
    expect(calls.some((call) => call.path === IMPERSONATION_GRANT_PATH)).toBe(true);
  });
  await vi.waitFor(() => {
    expect(calls.filter((call) => IMPERSONATED.includes(call.path))).toHaveLength(
      IMPERSONATED.length,
    );
  });
}

describe("view-as sends a grant, and mints it once", () => {
  it("puts a grant on every impersonated read and on none of the admin-realm ones", async () => {
    const { calls } = await renderAdminRoute(page(), routes());
    await settled(calls);

    const impersonated = calls.filter((call) => call.headers["X-Impersonate-Org"]);
    expect(impersonated.length, "this screen reads through impersonation").toBeGreaterThan(0);
    for (const call of impersonated) {
      expect(call.headers["X-Impersonate-Org"]).toBe(SLUG);
      // The pair travels together or not at all: the org header is ADDRESSING and the
      // grant is AUTHORISATION, and the API refuses the first without the second.
      expect(call.headers["X-Impersonation-Grant"], `${call.path} carried no grant`).toBe(
        "stub-view-as-grant",
      );
    }
    expect(new Set(impersonated.map((call) => call.path))).toEqual(
      new Set(IMPERSONATED.map((path) => path)),
    );

    // The admin realm's own reads are NOT impersonated and must not carry a grant —
    // they are cross-tenant, and attaching one would be claiming a scope they do not use.
    const adminRealm = calls.filter((call) => !call.headers["X-Impersonate-Org"]);
    for (const call of adminRealm) {
      expect(call.headers["X-Impersonation-Grant"], `${call.path} carried a grant`).toBeUndefined();
    }
  });

  it("mints ONE grant for a screen that opens six impersonated reads at once", async () => {
    const { calls } = await renderAdminRoute(page(), routes());
    await settled(calls);

    const mints = calls.filter((call) => call.path === IMPERSONATION_GRANT_PATH);
    // The ledger reason, not a performance one: every mint writes an
    // `admin.impersonation_started` row into an INSERT-ONLY table, so a mint per query
    // would put six rows in the audit log for one operator opening one page. The promise
    // is cached, not the result, which is what makes the six concurrent reads share it.
    expect(mints).toHaveLength(1);
    expect(mints[0]?.method).toBe("POST");
    expect(JSON.parse(mints[0]?.body ?? "{}")).toEqual({ slug: SLUG });
    // Minted with the ADMIN-realm session: a mint made from inside another account's
    // session is refused server-side (no chained delegation), and would be a regress here.
    expect(mints[0]?.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("surfaces a refused mint instead of reading without one", async () => {
    // The seam's failure mode. If the mint is refused there is no grant, so the reads
    // MUST NOT go out with a bare org header — that request can only be a 403, and a
    // console that sent it anyway would turn one explainable refusal into six.
    const { calls } = await renderAdminRoute(page(), {
      ...routes(),
      [`POST ${IMPERSONATION_GRANT_PATH}`]: problem(403, {
        title: "Forbidden",
        detail: "This account may not view client accounts.",
        type: "https://calevate.tech/problems/forbidden",
      }),
    });

    await vi.waitFor(() => {
      expect(calls.some((call) => call.path === IMPERSONATION_GRANT_PATH)).toBe(true);
    });
    for (const call of calls) {
      if (call.headers["X-Impersonate-Org"]) {
        expect(call.headers["X-Impersonation-Grant"], `${call.path} read without a grant`).toBe(
          undefined,
        );
      }
    }
    // The screen says something rather than rendering empty panels, which is the whole
    // argument of `adminTenantDetail.test.tsx`: an empty state after a failed read is the
    // most expensive sentence this console can print.
    expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
  });
});

describe("a session that names a tenant with no grant source", () => {
  it("is refused in this browser rather than sent as a request that can only 403", async () => {
    // A session hand-built the old way: the org header, no grant. Before this change that
    // was the WHOLE impersonation mechanism; now it is a programming error, and it is
    // caught here — with a sentence — rather than becoming a 403 an operator has to
    // interpret as "the API is down".
    stubApi({});
    clearImpersonationGrants();
    const broken: Session = { token: () => "dev:admin:me", orgSlug: SLUG, impersonateOrg: SLUG };

    await expect(apiRequest(broken, "/v1/agents")).rejects.toMatchObject({
      code: "impersonation_grant_missing",
      kind: "auth",
    });
  });
});
