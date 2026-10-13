import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantKycPage from "@/app/admin/tenants/[tenantId]/kyc/page";
import type { TenantSummary } from "@/lib/api/admin";
import { KYC_PATH, type KycRecord } from "@/lib/api/kyc";
import type { AdminKyc } from "@/lib/api/kycReview";
import type { TenantWorkspace } from "@/lib/api/engineWorkspaces";

import { type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The approval for phone numbers on the tenant's Identity page (D-693): the voice platform's
 * answer to the business details sent to the client's own workspace, shown read-only with a
 * "Check again now" that re-reads it. Where the deployment has no client workspaces there is
 * nothing to approve and the panel does not show.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000c1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const WORKSPACE_PATH = `/v1/admin/engine-workspaces/tenants/${TENANT}`;

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
    holds: [],
    last_call_at: null,
    capped: false,
  };
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000c2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

/** A read-only support session: `org:read` and no `admin:tenants`. */
const READER: AdminMe = { ...ME, role: "support", permissions: ["org:read"] };

/** The KYC record the identity panel above this one reads. Not what this file is about. */
function kyc(): KycRecord {
  return {
    recorded: false,
    status: null,
    entity_type: null,
    document_kind: null,
    document_ref: null,
    signatory_name: null,
    evidence_ref: null,
    rejection_reason: null,
    submitted_at: null,
    verified_at: null,
    is_verified: false,
    number_purchase_available: false,
    verification_source: null,
    verification_provider: null,
    verification_reference: null,
    verified_name: null,
    self_verification_available: false,
    kyc_path: null,
    legal_business_name: null,
    gst_registered: null,
    gstin: null,
    owner_id_type: null,
    owner_id_masked: null,
    name_match: null,
    digilocker_required: false,
    digilocker_required_reason: null,
    digilocker_outstanding: false,
    documents: [],
  };
}

/** The D-692 review panel's own read, mounted above the panel this file is about. */
function adminKyc(): AdminKyc {
  return {
    tenant_id: TENANT,
    recorded: false,
    status: null,
    kyc_path: null,
    entity_type: null,
    legal_business_name: null,
    gst_registered: null,
    gstin: null,
    owner_name: null,
    owner_id_type: null,
    owner_id_masked: null,
    owner_pan_checked: false,
    owner_pan_checked_at: null,
    owner_pan_checked_by: null,
    verified_name: null,
    name_match: null,
    verification_provider: null,
    verification_reference: null,
    rejection_reason: null,
    submitted_at: null,
    verified_at: null,
    is_verified: false,
    digilocker_required: false,
    digilocker_required_reason: null,
    digilocker_required_at: null,
    digilocker_verified_at: null,
    digilocker_outstanding: false,
    documents: [],
    pledge_accepted_version: null,
    pledge_accepted_at: null,
    pledge_current_version: 1,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantKycPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    [KYC_PATH]: kyc(),
    [`/v1/admin/tenants/${TENANT}/kyc`]: adminKyc(),
    [WORKSPACE_PATH]: workspace(),
    ...routes,
  });
}

function workspace(over: Partial<TenantWorkspace> = {}): TenantWorkspace {
  return {
    available: true,
    status: "active",
    workspace_id: "org_3fKq9TzQ1mN8vB2xR7cLpA",
    last_error_code: null,
    attempts: 1,
    provisioned_at: "2026-10-08T09:00:00Z",
    business_details: {
      status: "submitted",
      can_rent: false,
      review_note: null,
      submitted_at: "2026-10-08T09:41:12Z",
      checked_at: "2026-10-08T09:45:00Z",
    },
    purchase_step: "business_details",
    purchase_blockers: ["business_details_not_approved"],
    client_inr_per_month: "499.00",
    numbers: { own_workspace: 0, platform_held: 0 },
    agents_in_platform_account: 0,
    ...over,
  };
}

describe("the number approval on a per-client voice workspace (D-693)", () => {
  it("shows the voice platform's answer read-only, with its note on what to correct", async () => {
    const { container } = await render({
      [WORKSPACE_PATH]: workspace({
        business_details: {
          status: "rejected",
          can_rent: false,
          review_note: "The name on the certificate does not match the business name provided.",
          submitted_at: "2026-10-08T09:41:12Z",
          checked_at: "2026-10-08T10:00:00Z",
        },
      }),
    });

    expect(await screen.findByText("Approval for phone numbers")).toBeTruthy();
    expect(container.textContent).toContain("Rejected — correct it and send again");
    expect(container.textContent).toContain(
      "The name on the certificate does not match the business name provided.",
    );
  });

  it("reads the status again on request, from the voice platform", async () => {
    const { calls } = await render({
      [WORKSPACE_PATH]: workspace(),
      [`POST ${WORKSPACE_PATH}/business-details/refresh`]: {
        status: "accepted",
        can_rent: true,
        review_note: null,
        submitted_at: "2026-10-08T09:41:12Z",
        checked_at: "2026-10-08T09:50:00Z",
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Check again now" }));
    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "POST" && c.path === `${WORKSPACE_PATH}/business-details/refresh`),
      ).toBe(true),
    );
  });

  it("keeps the re-read closed to a session that may not use it", async () => {
    await render({ [ADMIN_ME_PATH]: READER });
    const button = await screen.findByRole("button", { name: "Check again now" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true));
  });

  it("shows no approval where the deployment has no client workspaces", async () => {
    await render({ [WORKSPACE_PATH]: { available: false } });
    await screen.findByText(/Identity verification/);
    await waitFor(() => expect(screen.queryByText("Approval for phone numbers")).toBeNull());
  });
});
