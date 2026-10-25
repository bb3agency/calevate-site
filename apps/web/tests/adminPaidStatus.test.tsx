import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantCreditsPage from "@/app/admin/tenants/[tenantId]/credits/page";
import type { TenantSummary } from "@/lib/api/admin";
import { LEDGER_LIMIT, creditsPath, type Credits } from "@/lib/api/credits";
import {
  makePaidConfirmation,
  paidPath,
  type MakePaidResult,
  type PaidStatus,
} from "@/lib/api/paidStatus";
import { trialPath, type TrialStatus } from "@/lib/api/trials";

import { expectNoA11yViolations } from "./a11y";
import { renderAdminRoute, routeParams } from "./adminRoute";
import type { Routes } from "./harness";

/**
 * Making a client account paid with no payment behind it (D-890).
 *
 * What these pin: the act is a super admin's alone, an operator sees why rather than a
 * missing button; the step-up is the route's own string, bound to the client and to any
 * credit given with it; the re-typed credit amount gates the button; and ending a trial as
 * "converted" (which makes the account paid) is closed to operators too.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000a1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const CREDITS_READ = `${creditsPath(TENANT)}?limit=${LEDGER_LIMIT}`;
const PAID = paidPath(TENANT);

const SUPER: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000a2",
  role: "superadmin",
  permissions: ["org:read", "billing:read", "admin:tenants", "billing:comp"],
};

const OPERATOR: AdminMe = {
  ...SUPER,
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

function credits(): Credits {
  return {
    tenant_id: TENANT,
    balance_inr: "0.00",
    is_low: true,
    low_balance_threshold_inr: "200.00",
    granted_inr: "0.00",
    paid_inr: "0.00",
    entries: [],
    payments: [],
    lots: [],
    override_packs: [],
  };
}

function status(over: Partial<PaidStatus> = {}): PaidStatus {
  return {
    tenant_id: TENANT,
    paid: false,
    paid_at: null,
    via: null,
    reason: null,
    trial: "running",
    ...over,
  };
}

function runningTrial(): TrialStatus {
  return {
    tenant_id: TENANT,
    trial_id: "0192f0aa-7777-7000-8000-0000000000b1",
    status: "active",
    active: true,
    days: 14,
    started_at: "2026-10-20T05:30:00Z",
    ends_at: "2026-11-03T05:30:00Z",
    days_remaining: 8,
    ended_at: null,
    ended_reason: null,
    erase_after: "2026-12-03T05:30:00Z",
    erasure_filed_at: null,
    started_by: null,
    cost_to_us_inr: "0.00",
    free_minutes: 30,
    minutes_used: 0,
  };
}

function made(over: Partial<MakePaidResult> = {}): MakePaidResult {
  return {
    status: status({
      paid: true,
      paid_at: "2026-10-26T05:30:00Z",
      via: "complimentary",
      reason: "pilot partner",
      trial: "ended",
    }),
    trial_converted: true,
    workspace_queued: true,
    grant: null,
    ...over,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantCreditsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: SUPER,
    [CREDITS_READ]: credits(),
    [trialPath(TENANT)]: null,
    [PAID]: status(),
    ...routes,
  });
}

const SUBMIT = { name: /^Make paid/ };

function submit(): HTMLButtonElement {
  return within(screen.getByRole("dialog")).getByRole("button", SUBMIT) as HTMLButtonElement;
}

async function openForm() {
  fireEvent.click(await screen.findByRole("button", { name: "Make paid" }));
  await screen.findByRole("dialog");
  fireEvent.change(screen.getByLabelText("Why (required)"), {
    target: { value: "pilot partner" },
  });
}

describe("making an account paid", () => {
  it("sends the reason with the step-up bound to the client and no credit", async () => {
    const { calls } = await render({ [`POST ${PAID}`]: made() });

    await openForm();
    await waitFor(() => expect(submit().disabled).toBe(false));
    fireEvent.click(submit());

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === PAID)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === PAID);
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ reason: "pilot partner", grant: null });
    expect(post?.headers["X-Confirm-Action"]).toBe(`convert_to_paid:${TENANT}:0.00`);
    expect(await screen.findByText("Sri Traders is now a paid account")).toBeDefined();
  });

  it("binds the step-up to the credit given with it, once the amount is typed again", async () => {
    const { calls } = await render({ [`POST ${PAID}`]: made() });

    await openForm();
    fireEvent.change(screen.getByLabelText("Also give credit (optional)"), {
      target: { value: "75000" },
    });
    expect(submit().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Type the credit amount again"), {
      target: { value: "75000.00" },
    });
    await waitFor(() => expect(submit().disabled).toBe(false));
    fireEvent.click(submit());

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === PAID)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === PAID);
    const body = JSON.parse(post?.body ?? "{}");
    expect(body.grant.amount_inr).toBe("75000");
    expect(body.grant.amount_confirmation).toBe("75000.00");
    expect(body.grant.reason).toBe("pilot partner");
    expect(post?.headers["X-Confirm-Action"]).toBe(makePaidConfirmation(TENANT, "75000"));
    expect(makePaidConfirmation(TENANT, "75000")).toBe(`convert_to_paid:${TENANT}:75000.00`);
  });

  it("is closed to an operator, with the reason beside it", async () => {
    const { calls } = await render({ [ADMIN_ME_PATH]: OPERATOR, [`POST ${PAID}`]: made() });

    fireEvent.click(await screen.findByRole("button", { name: "Make paid" }));
    expect(await screen.findByText(/make a client account paid/)).toBeDefined();
    expect(submit().disabled).toBe(true);
    fireEvent.click(submit());
    expect(calls.some((c) => c.method === "POST" && c.path === PAID)).toBe(false);
  });

  it("says how a paid account became paid, and offers no second conversion", async () => {
    await render({
      [PAID]: status({
        paid: true,
        paid_at: "2026-10-26T05:30:00Z",
        via: "complimentary",
        reason: "pilot partner",
        trial: "ended",
      }),
    });

    await screen.findByText(/a super admin, with no payment/);
    expect(document.body.textContent).toContain("pilot partner");
    expect(screen.queryByRole("button", { name: "Make paid" })).toBeNull();
  });

  it("has no axe violations with credit being given", async () => {
    await render();

    await openForm();
    fireEvent.change(screen.getByLabelText("Also give credit (optional)"), {
      target: { value: "500" },
    });
    await expectNoA11yViolations(screen.getByRole("dialog"), "admin credits (make paid open)");
  });
});

describe("ending a trial as converted", () => {
  it("is a super admin's choice; an operator may only stop one", async () => {
    await render({ [ADMIN_ME_PATH]: OPERATOR, [trialPath(TENANT)]: runningTrial() });

    fireEvent.click(await screen.findByRole("button", { name: "End trial" }));
    const option = (await screen.findByRole("option", {
      name: "Converted — super admins only",
    })) as HTMLOptionElement;
    expect(option.disabled).toBe(true);
    const stopped = screen.getByRole("option", { name: /We ended it/ }) as HTMLOptionElement;
    expect(stopped.disabled).toBe(false);
  });
});
