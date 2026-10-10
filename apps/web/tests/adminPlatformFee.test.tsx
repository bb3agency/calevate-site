import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CommercialsPage from "@/app/admin/tenants/[tenantId]/commercials/page";
import type { TenantSummary } from "@/lib/api/admin";
import { commercialTermsPath, type CommercialTerms } from "@/lib/api/commercials";
import { adminPlatformFeePath, type AdminPlatformFee } from "@/lib/api/platformFee";
import type { Routes } from "./harness";

import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The monthly platform fee on a client's Commercials screen (D-707).
 *
 * One pricing model: the fee is a platform-wide switch, so this panel sets no amount. It
 * waives the fee for one client with a reason, withdraws a waiver, and records a fee paid
 * by bank transfer — each an admin-realm write — and the terms form no longer offers a
 * setup fee, a retainer, included minutes or an overage rate.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000e1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const TERMS_PATH = commercialTermsPath(TENANT);
const FEE_PATH = adminPlatformFeePath(TENANT);
const CHARGE = "0192f0aa-7777-7000-8000-0000000000f1";

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 4,
    leads: 2,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000e2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

function terms(): CommercialTerms {
  return {
    tenant_id: TENANT,
    state: "none",
    in_effect: null,
    history: [],
    loosening_confirmation: `raise_spend_ceiling:${TENANT}`,
  };
}

function fee(over: Partial<AdminPlatformFee> = {}): AdminPlatformFee {
  return {
    enabled: true,
    amount_inr: "1999.00",
    exemption: null,
    outbound_paused: true,
    grace_days: 7,
    charges: [
      {
        id: CHARGE,
        period: "2026-10",
        amount_inr: "1999.00",
        issued_at: "2026-10-01T00:00:00Z",
        grace_ends_at: "2026-10-08T00:00:00Z",
        status: "overdue",
        paid_at: null,
        payment_method: null,
      },
    ],
    waiver: null,
    moved_to_credits_at: null,
    ...over,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<CommercialsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    [TERMS_PATH]: terms(),
    [FEE_PATH]: fee(),
    ...routes,
  });
}

describe("the monthly platform fee panel", () => {
  it("says the fee is on, and that this client's outgoing calls are paused", async () => {
    const { container } = await render();
    await screen.findByText("Outgoing calls are paused for an unpaid fee");
    expect(container.textContent).toContain("Incoming calls are unaffected");
    expect(container.textContent).toContain("Overdue — outgoing calls paused");
  });

  it("waives the fee with the operator's reason, on an admin session", async () => {
    const { calls } = await render({ [`PUT ${FEE_PATH}/waiver`]: fee({ exemption: "waiver" }) });
    fireEvent.change(await screen.findByLabelText(/Waive the fee for this client/), {
      target: { value: "lighthouse client" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Waive the platform fee/ }));
    await waitFor(() => {
      expect(calls.some((call) => call.method === "PUT" && call.path === `${FEE_PATH}/waiver`)).toBe(
        true,
      );
    });
    const put = calls.find((call) => call.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ reason: "lighthouse client" });
    expect(put?.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("records a bank transfer against the unpaid fee", async () => {
    const path = `${FEE_PATH}/${CHARGE}/payments`;
    const { calls } = await render({
      [`POST ${path}`]: { charge_id: CHARGE, recorded: true, status: "paid" },
    });
    fireEvent.change(await screen.findByLabelText(/Bank transfer reference/), {
      target: { value: "UTR123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Record bank transfer/ }));
    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === path)).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST" && call.path === path);
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ reference: "UTR123456" });
  });

  it("offers no retainer terms on the agreement form", async () => {
    await render();
    fireEvent.click(await screen.findByRole("button", { name: /Agree new terms/ }));
    await screen.findByLabelText(/AI model surcharge/);
    expect(screen.queryByLabelText(/Setup fee/)).toBeNull();
    expect(screen.queryByLabelText(/Monthly retainer/)).toBeNull();
    expect(screen.queryByLabelText(/Included minutes/)).toBeNull();
    expect(screen.queryByLabelText(/overage rate/i)).toBeNull();
  });
});
