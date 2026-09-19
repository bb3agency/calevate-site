import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CommercialsPage from "@/app/admin/tenants/[tenantId]/commercials/page";
import { planTierPath, type TenantSummary } from "@/lib/api/admin";
import { commercialTermsPath, type CommercialTerms } from "@/lib/api/commercials";
import type { Routes } from "./harness";

import { problem } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The billing motion — the control `POST /v1/admin/tenants/{id}/plan-tier` shipped without.
 *
 * The route was audited, reason-required, idempotent and covered by
 * `tests/plan_tier_split_test.py` from the day it landed, and NOTHING in this console
 * called it: moving a client between prepaid credit and an invoiced retainer could only be
 * done with a hand-assembled request against production. What these tests pin:
 *
 * 1. **The control exists and reaches the route**, with the tier and the operator's reason
 *    on an ADMIN-realm request — the half that was missing.
 * 2. **A reason is required in both directions**, refused here before the API refuses it,
 *    because `plan_tier` keeps no history and that audit row is the only record of why a
 *    business is invoiced rather than credit-gated.
 * 3. **The dangerous direction says what it does.** Moving an account on to `prepaid`
 *    stops outbound dialling AND inbound answering the moment the wallet is empty (D-551);
 *    a dropdown reading "prepaid" says none of that.
 * 4. **No confirmation header**, which is the API's own line: both directions are
 *    reversible by this same call, and ceremony on a reversible act teaches operators to
 *    type past ceremony.
 * 5. **An unchanged result is reported as unchanged**, never as a move that happened.
 * 6. **The panel survives a failed terms read.** The motion comes off the directory row,
 *    not off `plans`, so withholding it with the agreement form would hide a control on
 *    exactly the screen that failed.
 * 7. **A session without `admin:tenants` gets a disabled control with the reason**, not a
 *    button that 403s.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000e1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const TERMS_PATH = commercialTermsPath(TENANT);
const TIER_PATH = planTierPath(TENANT);
const SUBMIT = { name: /Change billing motion/ };

function tenant(planTier = "prepaid"): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: planTier,
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

/** A read-only support session: `org:read` and no `admin:tenants`. */
const READER: AdminMe = { ...ME, role: "support", permissions: ["org:read"] };

function terms(): CommercialTerms {
  return {
    tenant_id: TENANT,
    state: "none",
    in_effect: null,
    history: [],
    loosening_confirmation: `raise_spend_ceiling:${TENANT}`,
  };
}

function render(routes: Partial<Routes> = {}, planTier = "prepaid") {
  return renderAdminRoute(<CommercialsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(planTier),
    [ADMIN_ME_PATH]: ME,
    [TERMS_PATH]: terms(),
    ...routes,
  });
}

function moved(over: Record<string, unknown> = {}) {
  return {
    [`POST ${TIER_PATH}`]: {
      tenant_id: TENANT,
      plan_tier: "managed",
      previous_plan_tier: "prepaid",
      changed: true,
      ...over,
    },
  };
}

describe("the billing motion panel", () => {
  it("sends the tier and the reason to the plan-tier route on an admin session", async () => {
    const { calls } = await render(moved());

    const why = (await screen.findByLabelText(/Why/)) as HTMLTextAreaElement;
    fireEvent.change(why, { target: { value: "invoiced on a retainer from October" } });
    fireEvent.click(screen.getByRole("button", SUBMIT));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === TIER_PATH)).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST" && call.path === TIER_PATH);
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      plan_tier: "managed",
      reason: "invoiced on a retainer from October",
    });
    // D-22: `admin:tenants` is a MUTATING permission, so this never rides an
    // impersonating session.
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("will not send a motion change with no reason", async () => {
    const { calls } = await render(moved());

    const button = await screen.findByRole("button", SUBMIT);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.some((call) => call.method === "POST" && call.path === TIER_PATH)).toBe(false);

    // And it says so, rather than leaving a dead button to be discovered.
    expect(screen.getByText(/A reason is required/)).toBeDefined();
  });

  it("says what moving an account on to prepaid does — including to INBOUND", async () => {
    // A managed account, so the control opens on the move towards prepaid.
    const { container } = await render({}, "managed");

    await screen.findByText("Billing motion");
    expect(container.textContent).toContain("stops this client's outbound dialling");
    // The half nobody guesses from the word "prepaid" (D-551).
    expect(container.textContent).toContain("answering incoming calls");
  });

  it("names the motion the client is on now", async () => {
    const { container } = await render({}, "managed");

    await screen.findByText("Billing motion");
    expect(container.textContent).toContain("Managed — invoiced on a retainer");
  });

  it("sends no confirmation header — both directions are reversible", async () => {
    const { calls } = await render(moved());

    fireEvent.change(await screen.findByLabelText(/Why/), {
      target: { value: "moving them off credit gating" },
    });
    fireEvent.click(screen.getByRole("button", SUBMIT));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === TIER_PATH)).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST" && call.path === TIER_PATH);
    expect(post?.headers["X-Confirm-Action"]).toBeUndefined();
  });

  it("reports an already-on-this-motion result as unchanged", async () => {
    const { container } = await render(
      moved({ plan_tier: "managed", previous_plan_tier: null, changed: false }),
    );

    fireEvent.change(await screen.findByLabelText(/Why/), {
      target: { value: "tidying the billing record" },
    });
    fireEvent.click(screen.getByRole("button", SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("was already managed");
    });
    expect(container.textContent).not.toContain("Moved from");
  });

  it("renders a refusal, not a silent no-op, when the write fails", async () => {
    const { container } = await render({
      [`POST ${TIER_PATH}`]: problem(503, {
        title: "Upstream unavailable",
        detail: "The database is unreachable.",
        retryable: true,
      }),
    });

    fireEvent.change(await screen.findByLabelText(/Why/), {
      target: { value: "moving them on to credit" },
    });
    fireEvent.click(screen.getByRole("button", SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("The database is unreachable.");
    });
  });

  it("stays reachable when the commercial terms read fails", async () => {
    // The agreement form is withheld over a failed read, on purpose. The MOTION is not
    // part of that agreement — it is on the directory row — so hiding it here would take
    // a working control off the screen an operator came to because something was wrong.
    const { container } = await render({
      [TERMS_PATH]: problem(503, { title: "Upstream unavailable", retryable: true }),
    });

    await screen.findByText("Billing motion");
    expect(screen.getByRole("button", SUBMIT)).toBeDefined();
    expect(container.textContent).toContain(
      "Cannot record terms while the current agreement is unreadable",
    );
  });

  it("disables the control, with its reason, for a session that may not use it", async () => {
    const { calls } = await render({ [ADMIN_ME_PATH]: READER, ...moved() });

    const button = await screen.findByRole("button", SUBMIT);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/change how this client is billed/)).toBeDefined();
    fireEvent.click(button);
    expect(calls.some((call) => call.method === "POST" && call.path === TIER_PATH)).toBe(false);
  });
});
