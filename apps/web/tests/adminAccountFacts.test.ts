import { describe, expect, it } from "vitest";

import {
  accountFacts,
  lifecycleFact,
  onboardingRemaining,
  type AccountReads,
} from "@/app/admin/tenants/[tenantId]/accountFacts";
import type { TenantSummary } from "@/lib/api/admin";
import type { AdminKyc } from "@/lib/api/kycReview";
import { adminTenantOf } from "@/lib/copilot/adminTenant";
import type { CopilotSurface } from "@/lib/copilot/types";

import { adminBusinessProfileFixture } from "./businessProfileFixture";

const TENANT_ID = "0199c0de-0000-7000-8000-000000000001";

const tenant: TenantSummary = {
  id: TENANT_ID,
  name: "Raghava Organics",
  slug: "raghava-organics",
  status: "onboarding",
  vertical_template: "clinic",
  live_agents: 0,
  calls_7d: 0,
  leads: 0,
  last_call_at: null,
  capped: false,
  plan_tier: "prepaid",
  holds: [],
};

const VERIFIED_KYC: AdminKyc = {
  tenant_id: TENANT_ID,
  recorded: true,
  status: "verified",
  kyc_path: "manual",
  entity_type: null,
  legal_business_name: null,
  gst_registered: null,
  gstin: null,
  owner_name: "Raghava Rao",
  owner_id_type: "pan",
  owner_id_masked: "XXXXX1234X",
  owner_pan_checked: false,
  owner_pan_checked_at: null,
  owner_pan_checked_by: null,
  verified_name: null,
  name_match: null,
  verification_provider: null,
  verification_reference: null,
  rejection_reason: null,
  submitted_at: null,
  verified_at: "2026-10-09T10:00:00Z",
  is_verified: true,
  digilocker_required: false,
  digilocker_required_reason: null,
  digilocker_required_at: null,
  digilocker_verified_at: null,
  digilocker_outstanding: false,
  documents: [],
  pledge_accepted_version: 1,
  pledge_accepted_at: "2026-10-09T11:00:00Z",
  pledge_current_version: 1,
};

function reads(overrides: Partial<AccountReads> = {}): AccountReads {
  return {
    kyc: {
      data: VERIFIED_KYC,
    },
    readiness: { data: { tenant_id: TENANT_ID, may_operate: true, blocked_on_calevate: 0, rows: [] } },
    workspace: { isError: true },
    trial: { data: null },
    wallet: { data: undefined },
    owner: { data: { owner_present: true, invite_pending: false } },
    profile: {
      data: {
        ...adminBusinessProfileFixture(),
        blockers: [{ code: "branch_missing", step: "branches", message: "Add your address." }],
      },
    },
    ...overrides,
  };
}

describe("the admin client page's account facts", () => {
  it("states KYC and the pledge in words, never the owner's identity", () => {
    const facts = accountFacts(tenant, reads());
    const byKey = Object.fromEntries(facts.map((fact) => [fact.key, fact.value]));
    // FAILS IF the assistant is again left to say "the screen does not show KYC".
    expect(byKey.kyc).toBe("verified; path: document review; verified on 2026-10-09");
    expect(byKey.pledge).toBe("accepted on 2026-10-09");
    expect(byKey.outbound_blockers).toBe("nothing at account level is blocking outbound calls");
    // A failed read is said to be one, never reported as "none".
    expect(byKey.workspace).toBe("could not be read");
    const wire = JSON.stringify(facts);
    expect(wire).not.toContain("Raghava Rao");
    expect(wire).not.toContain("1234");
  });

  it("says what onboarding is still waiting for", () => {
    expect(lifecycleFact(tenant, reads())).toBe(
      "onboarding; still to do: business profile has no address",
    );
    const finished = reads({
      profile: { data: { ...adminBusinessProfileFixture(), blockers: [] } },
    });
    expect(onboardingRemaining(finished.owner, finished.profile)).toEqual([]);
    expect(lifecycleFact(tenant, finished)).toMatch(/^onboarding; setup is finished/);
  });
});

describe("which client an admin question is about", () => {
  const surface = { route: "/admin/tenants/{id}", title: "Client", realm: "admin" } as CopilotSurface;

  it("reads the client from the address on every page under it", () => {
    // FAILS IF the admin ask goes out without `tenant_id` again: the assistant then has
    // no account tools and no live account state on a client's own page.
    expect(adminTenantOf(surface, `/admin/tenants/${TENANT_ID}/kyc`)).toBe(TENANT_ID);
    expect(adminTenantOf(surface, "/admin/ops")).toBeUndefined();
  });

  it("never sends one from the client realm", () => {
    expect(
      adminTenantOf({ ...surface, realm: "client" }, `/admin/tenants/${TENANT_ID}`),
    ).toBeUndefined();
  });
});
