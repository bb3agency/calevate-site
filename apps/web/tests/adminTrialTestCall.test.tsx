import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantCreditsPage from "@/app/admin/tenants/[tenantId]/credits/page";
import type { TenantSummary } from "@/lib/api/admin";
import { LEDGER_LIMIT, creditsPath, type Credits } from "@/lib/api/credits";
import { paidPath } from "@/lib/api/paidStatus";
import { trialPath, trialTestCallPath, type TrialStatus } from "@/lib/api/trials";

import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * The operator's trial test call (`POST /v1/admin/tenants/{id}/trial/test-call`), which
 * had no screen (journey audit E5; founder, 10 Nov 2026). It rings a real phone, so it is
 * confirmed first, carries one Idempotency-Key per attempt, and asks no step-up because
 * the route asks none.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000a1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const CREDITS_READ = `${creditsPath(TENANT)}?limit=${LEDGER_LIMIT}`;
const TRIAL_PATH = trialPath(TENANT);
const CALL_PATH = trialTestCallPath(TENANT);
const READY = "0192f0aa-7777-7000-8000-0000000000c1";
const DRAFT = "0192f0aa-7777-7000-8000-0000000000c2";

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

const OPERATOR: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000a2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

const READER: AdminMe = { ...OPERATOR, role: "support", permissions: ["org:read", "billing:read"] };

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

function trial(over: Partial<TrialStatus> = {}): TrialStatus {
  return {
    tenant_id: TENANT,
    trial_id: "0192f0aa-7777-7000-8000-0000000000b1",
    status: "active",
    active: true,
    days: 14,
    started_at: "2026-11-01T05:30:00Z",
    ends_at: "2026-11-15T05:30:00Z",
    days_remaining: 5,
    ended_at: null,
    ended_reason: null,
    erase_after: "2026-12-15T05:30:00Z",
    erasure_filed_at: null,
    started_by: OPERATOR.user_id,
    cost_to_us_inr: "12.50",
    free_minutes: 15,
    minutes_used: 2,
    ...over,
  };
}

const AGENTS = [
  { id: READY, name: "Front desk", status: "paused" },
  { id: DRAFT, name: "Half-built", status: "draft" },
];

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantCreditsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: OPERATOR,
    [CREDITS_READ]: credits(),
    [TRIAL_PATH]: trial(),
    [paidPath(TENANT)]: {
      tenant_id: TENANT,
      paid: false,
      paid_at: null,
      via: null,
      reason: null,
      trial: "running",
    },
    "/v1/agents": AGENTS,
    ...routes,
  });
}

function callButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: "Make a test call" }) as HTMLButtonElement;
}

async function fill(number = "98765 43210") {
  fireEvent.change(await screen.findByLabelText("Agent"), { target: { value: READY } });
  fireEvent.change(screen.getByLabelText("Number to ring"), { target: { value: number } });
}

async function confirm() {
  await waitFor(() => expect(callButton().disabled).toBe(false));
  fireEvent.click(callButton());
  const dialog = await screen.findByRole("dialog", { name: /Ring .* from Front desk/ });
  fireEvent.click(within(dialog).getByRole("button", { name: "Ring the phone" }));
}

describe("the operator's trial test call", () => {
  it("is offered to an operator holding admin:tenants while the trial runs", async () => {
    await render();
    expect(await screen.findByRole("button", { name: "Make a test call" })).toBeTruthy();
    // Only the agents the dial gate admits: ready or taking calls, never a draft.
    const agent = await screen.findByLabelText("Agent");
    expect(within(agent).queryByRole("option", { name: "Front desk" })).toBeTruthy();
    expect(within(agent).queryByRole("option", { name: "Half-built" })).toBeNull();
  });

  it("is hidden from a role the route does not permit", async () => {
    await render({ [ADMIN_ME_PATH]: READER });
    await screen.findByText(/free test-call minute/);
    expect(screen.queryByRole("button", { name: "Make a test call" })).toBeNull();
  });

  it("is hidden once the trial has ended", async () => {
    await render({
      [TRIAL_PATH]: trial({ active: false, status: "expired", ended_at: "2026-11-09T05:30:00Z" }),
    });
    await screen.findByText(/Their trial ended/);
    expect(screen.queryByRole("button", { name: "Make a test call" })).toBeNull();
  });

  it("refuses a number the server would refuse, before anything is sent", async () => {
    const { calls } = await render();
    await fill("+1 415 555 0100");
    expect(await screen.findByText(/Enter an Indian mobile or phone number/)).toBeTruthy();
    expect(callButton().disabled).toBe(true);
    expect(calls.some((c) => c.method === "POST" && c.path === CALL_PATH)).toBe(false);
  });

  it("confirms first, then sends the agent and the number with an Idempotency-Key and no step-up", async () => {
    const { calls } = await render({ [`POST ${CALL_PATH}`]: { status: "queued", call_handle: "h1" } });
    await fill();
    await waitFor(() => expect(callButton().disabled).toBe(false));
    fireEvent.click(callButton());
    // Pressing the button only opens the confirmation: nothing has rung yet.
    expect(await screen.findByRole("dialog", { name: /Ring .* from Front desk/ })).toBeTruthy();
    expect(calls.some((c) => c.method === "POST" && c.path === CALL_PATH)).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Ring the phone" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === CALL_PATH)).toBe(true),
    );
    const post = calls.find((c) => c.method === "POST" && c.path === CALL_PATH);
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ agent_id: READY, number: "+919876543210" });
    expect(post?.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(post?.headers["X-Confirm-Action"]).toBeUndefined();
  });

  it("says the phone is ringing and re-reads the trial and the wallet", async () => {
    const { calls } = await render({ [`POST ${CALL_PATH}`]: { status: "queued", call_handle: "h1" } });
    await fill();
    const before = (path: string) => calls.filter((c) => c.method === "GET" && c.path === path).length;
    const trialReads = before(TRIAL_PATH);
    const walletReads = before(CREDITS_READ);
    await confirm();
    expect(await screen.findByText("Calling now")).toBeTruthy();
    await waitFor(() => {
      expect(before(TRIAL_PATH)).toBeGreaterThan(trialReads);
      expect(before(CREDITS_READ)).toBeGreaterThan(walletReads);
    });
  });

  it("shows the dial gate's own sentence when the call is blocked", async () => {
    await render({
      [`POST ${CALL_PATH}`]: {
        status: "blocked",
        blocked_rule: "trial_daily_cap",
        blocked_reason: "Today's test calls are used up. Try again tomorrow.",
      },
    });
    await fill();
    await confirm();
    expect(await screen.findByText("This test call was not placed")).toBeTruthy();
    expect(screen.getByText("Today's test calls are used up. Try again tomorrow.")).toBeTruthy();
    expect(screen.queryByText(/trial_daily_cap/)).toBeNull();
  });

  it("shows a refusal's own words and remedy inside the confirmation", async () => {
    await render({
      [`POST ${CALL_PATH}`]: problem(503, {
        type: "https://calevate.tech/problems/trial_call_not_placed",
        title: "We couldn't place this test call",
        detail: "This is a problem on our side, not with your agent or the number you entered.",
        remediation: "Please try again later.",
        status: 503,
      }),
    });
    await fill();
    await confirm();
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("We couldn't place this test call")).toBeTruthy();
    expect(within(dialog).getByText(/Please try again later/)).toBeTruthy();
    expect(within(dialog).queryByText(/trial_call_not_placed/)).toBeNull();
  });
});
