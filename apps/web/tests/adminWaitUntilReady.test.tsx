import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { KnowledgeQueue } from "@/app/admin/tenants/[tenantId]/KnowledgeQueue";
import ClosurePage from "@/app/admin/tenants/[tenantId]/closure/page";
import FeatureFlagsPage from "@/app/admin/tenants/[tenantId]/feature-flags/page";
import { KycReviewPanel } from "@/app/admin/tenants/[tenantId]/kyc/KycReviewPanel";
import type { AdminKyc } from "@/lib/api/kycReview";
import type { KbSource, TenantSummary } from "@/lib/api/admin";
import type { Closure } from "@/lib/api/closure";
import { featureFlagPath, featureFlagsPath, type FeatureFlag } from "@/lib/api/featureFlags";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { adminBusinessProfileFixture, OWNER_JOINED } from "./businessProfileFixture";
import { problem, renderAdminPage, stillLoading, type Routes } from "./harness";

/**
 * Admin controls while a write is out (founder, 1 Nov 2026: "buttons should stay greyed out
 * and only come back to clickable once that process is done").
 *
 * 1. Editing a field mid-request must not hand the button back: `reset()` on a pending
 *    mutation detaches it, and the next press sends a second destructive write.
 * 2. Where several buttons share one write, the ones not carrying it wait, with the reason.
 * 3. A failed write releases every control.
 */

const TENANT = "0192f0aa-9999-7000-8000-0000000000a1";
const SLUG = "sri-traders";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;

const OPERATOR: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-9999-7000-8000-0000000000a2",
  role: "operator",
  permissions: ["org:read", "admin:tenants", "kb:write"],
};

const SUMMARY: TenantSummary = {
  id: TENANT,
  name: "Sri Traders",
  slug: SLUG,
  status: "active",
  plan_tier: "prepaid",
  vertical_template: "real_estate",
  live_agents: 1,
  calls_7d: 0,
  leads: 0,
  last_call_at: null,
  holds: [],
  capped: false,
};

const OPEN: Closure = {
  tenant_id: TENANT,
  status: "active",
  closed_at: null,
  erase_after: null,
  reason: null,
  closed_by: null,
  erased_at: null,
  restorable: false,
  days_remaining: null,
  forfeited_credit_inr: "0.00",
};

describe("closing an account while the close is out", () => {
  it("keeps the button busy when the reason is edited mid-request, and sends one close", async () => {
    const { calls } = await renderAdminRoute(<ClosurePage params={routeParams({ tenantId: TENANT })} />, {
      [ADMIN_ME_PATH]: OPERATOR,
      [TENANT_PATH]: SUMMARY,
      [`${TENANT_PATH}/business-profile`]: adminBusinessProfileFixture(),
      [`${TENANT_PATH}/owner-status`]: OWNER_JOINED,
      [`${TENANT_PATH}/closure`]: OPEN,
      [`POST ${TENANT_PATH}/closure`]: stillLoading(),
    });

    const reason = await screen.findByLabelText(/Why this account is closing/);
    fireEvent.change(reason, { target: { value: "Not renewing after the pilot." } });
    fireEvent.change(screen.getByLabelText(/Type CLOSE to confirm/), { target: { value: "CLOSE" } });
    const button = screen.getByRole("button", { name: /Close this account/ });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute("aria-busy")).toBe("true"));

    fireEvent.change(reason, { target: { value: "Not renewing after the pilot, per the owner." } });
    expect(button.getAttribute("aria-busy")).toBe("true");
    fireEvent.click(button);
    await new Promise((settle) => setTimeout(settle, 50));
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);
  });
});

function flag(name: string): FeatureFlag {
  return {
    flag: name,
    declared: true,
    description: `The ${name} switch.`,
    consumed_by: "apps.api.crm.calls",
    platform_default: false,
    override: null,
    enabled: false,
    source: "platform_default",
    reason: null,
    set_by_admin_id: null,
    set_at: null,
  };
}

function renderFlags(routes: Routes) {
  return renderAdminRoute(<FeatureFlagsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: SUMMARY,
    [ADMIN_ME_PATH]: OPERATOR,
    [featureFlagsPath(TENANT)]: { tenant_id: TENANT, items: [flag("first_switch"), flag("second_switch")] },
    ...routes,
  });
}

/** Arms both cards and presses Save on the first. */
async function saveFirstFlag() {
  const onRadios = await screen.findAllByRole("radio", { name: /On for this client/ });
  const reasons = screen.getAllByLabelText("Why");
  for (const [index, radio] of onRadios.entries()) {
    fireEvent.click(radio);
    fireEvent.change(reasons[index]!, { target: { value: "Trial for the week." } });
  }
  const [first, second] = screen.getAllByRole("button", { name: "Save this flag" });
  fireEvent.click(first!);
  return { first: first!, second: second! };
}

describe("feature flags sharing one write", () => {
  it("holds the other flag's Save, with the reason, while one flag saves", async () => {
    const { calls } = await renderFlags({
      [`PUT ${featureFlagPath(TENANT, "first_switch")}`]: stillLoading(),
    });
    const { first, second } = await saveFirstFlag();

    await waitFor(() => expect(first.getAttribute("aria-busy")).toBe("true"));
    expect(second.getAttribute("aria-disabled")).toBe("true");
    screen.getByText("Waiting for the other flag to save.");
    fireEvent.click(second);
    await new Promise((settle) => setTimeout(settle, 50));
    expect(calls.filter((call) => call.method === "PUT")).toHaveLength(1);
  });

  it("gives the other flag's Save back once the first save is refused", async () => {
    await renderFlags({
      [`PUT ${featureFlagPath(TENANT, "first_switch")}`]: problem(503, { title: "Upstream unavailable" }),
    });
    const { second } = await saveFirstFlag();

    await screen.findByText("Upstream unavailable");
    expect(second.getAttribute("aria-disabled")).toBeNull();
    expect(screen.queryByText("Waiting for the other flag to save.")).toBeNull();
  });
});

const SUBMITTED_KYC: AdminKyc = {
  tenant_id: TENANT,
  recorded: true,
  status: "submitted",
  kyc_path: "digilocker",
  entity_type: null,
  legal_business_name: "Sri Traders",
  gst_registered: false,
  gstin: null,
  owner_name: "Owner Name",
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
  submitted_at: "2026-10-30T05:30:00Z",
  verified_at: null,
  is_verified: false,
  digilocker_required: false,
  digilocker_required_reason: null,
  digilocker_required_at: null,
  digilocker_verified_at: null,
  digilocker_outstanding: false,
  documents: [],
  pledge_accepted_version: 1,
  pledge_accepted_at: "2026-10-30T05:30:00Z",
  pledge_current_version: 1,
};

describe("a KYC review's two decisions", () => {
  it("holds Reject, with the reason, while the approval is out", async () => {
    const { calls } = renderAdminPage(
      <KycReviewPanel tenantId={TENANT} access={{ allowed: true, refused: false, reason: null }} />,
      {
        [ADMIN_ME_PATH]: OPERATOR,
        [`${TENANT_PATH}/kyc`]: SUBMITTED_KYC,
        [`POST ${TENANT_PATH}/kyc/review`]: stillLoading(),
      },
    );
    fireEvent.change(await screen.findByLabelText(/Reason \(required to reject/), {
      target: { value: "The name does not match." },
    });
    const approve = screen.getByRole("button", { name: "Approve" });
    fireEvent.click(approve);
    await waitFor(() => expect(approve.getAttribute("aria-busy")).toBe("true"));
    const reject = screen.getByRole("button", { name: "Reject" });
    expect(reject.getAttribute("aria-disabled")).toBe("true");
    screen.getByText("Waiting for the approval to save.");
    fireEvent.click(reject);
    await new Promise((settle) => setTimeout(settle, 50));
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);
  });
});

function source(id: string, name: string): KbSource {
  return {
    id,
    name,
    kind: "text",
    status: "pending_approval",
    version: 1,
    chunks: 4,
    is_active: false,
    published_at: null,
  };
}

const FIRST = "0192f0aa-9999-7000-8000-0000000000b1";
const SECOND = "0192f0aa-9999-7000-8000-0000000000b2";

function renderQueue(approve: unknown) {
  return renderAdminPage(<KnowledgeQueue tenantId={TENANT} slug={SLUG} />, {
    [ADMIN_ME_PATH]: OPERATOR,
    "/v1/kb/sources?status=pending_approval": [source(FIRST, "Price list"), source(SECOND, "Opening hours")],
    "/v1/kb/sources?status=approved": [],
    [`POST ${TENANT_PATH}/kb/${FIRST}/approve`]: approve,
  });
}

function rowOf(name: string): HTMLElement {
  return screen.getByText(name).closest("li")!;
}

describe("the knowledge queue's one decision at a time", () => {
  it("holds every other decision, the same row's reject too, while an approval is out", async () => {
    const { calls } = renderQueue(stillLoading());
    await screen.findByText("Price list");
    const approve = within(rowOf("Price list")).getByRole("button", { name: "Approve" });
    fireEvent.click(approve);
    await waitFor(() => expect(approve.getAttribute("aria-busy")).toBe("true"));

    const other = within(rowOf("Opening hours")).getByRole("button", { name: "Approve" });
    expect(other.getAttribute("aria-disabled")).toBe("true");
    within(rowOf("Opening hours")).getByText("Waiting for the other decision to save.");
    fireEvent.click(other);
    await new Promise((settle) => setTimeout(settle, 50));
    expect(calls.filter((call) => call.method === "POST" && call.path.includes("/kb/"))).toHaveLength(1);
  });

  it("gives every decision back once the approval is refused", async () => {
    renderQueue(problem(409, { title: "Already decided" }));
    await screen.findByText("Price list");
    fireEvent.click(within(rowOf("Price list")).getByRole("button", { name: "Approve" }));
    await screen.findByText("Already decided");
    const other = within(rowOf("Opening hours")).getByRole("button", { name: "Approve" });
    expect(other.getAttribute("aria-disabled")).toBeNull();
    expect(screen.queryByText("Waiting for the other decision to save.")).toBeNull();
  });
});
