import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CommercialsPage from "@/app/admin/tenants/[tenantId]/commercials/page";
import type { TenantSummary } from "@/lib/api/admin";
import {
  commercialTermsPath,
  type CommercialTerms,
  type PlanRow,
} from "@/lib/api/commercials";
import type { Routes } from "./harness";

import { problem } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * Commercials — the screen behind the numbers on the invoice.
 *
 * `plans` had NO writer in this product: every figure the invoice printed rested on a
 * row somebody had inserted by hand against production. What the tests pin, worst first:
 *
 * 1. **A failed read must never render as "no commercial terms".** That sentence is also
 *    a REAL state with a real remedy, so §52's rule bites hardest here: an operator who
 *    reads it over a 503 sets a price for an account that already has one, and the write
 *    they make supersedes a spend ceiling nobody could see.
 * 2. **The absence, when it IS the absence, is stated plainly** — not as ₹0, not as an
 *    empty panel. Onboarding deliberately seeds no plan row.
 * 3. **Money is never re-derived on the screen.** Fees are formatted from the API's
 *    digits; a RATE is printed unrounded, because ₹7.1250 shown as ₹7.12 breaks the
 *    invoice's own arithmetic in our favour.
 * 4. **The dangerous direction announces itself and carries its confirmation.** Raising
 *    or removing a spend ceiling is a superadmin action with a step-up header bound to
 *    the tenant; tightening one is ordinary work and must not ask for either.
 * 5. **No default is invented for the value-tier rate**, which is an open founder
 *    decision — the field ships empty and stays empty.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000c1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const TERMS_PATH = commercialTermsPath(TENANT);
const CONFIRMATION = `raise_spend_ceiling:${TENANT}`;

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  } as TenantSummary;
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000c2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
} as AdminMe;

function plan(over: Partial<PlanRow> = {}): PlanRow {
  return {
    id: "0192f0aa-7777-7000-8000-0000000000c3",
    setup_fee_inr: "5000.0000",
    monthly_fee_inr: "9999.0000",
    included_minutes: 100,
    overage_rate_inr: "7.1250",
    overage_rate_value_inr: null,
    hard_cap_minutes: 500,
    hard_cap_spend_inr: "20000.0000",
    client_cap_minutes: null,
    client_cap_spend_inr: null,
    concurrency_ceiling: 10,
    effective_from: null,
    effective_to: null,
    created_at: "2026-08-01T05:00:00Z",
    states_pricing: true,
    ...over,
  };
}

function terms(over: Partial<CommercialTerms> = {}): CommercialTerms {
  const inEffect = over.in_effect === undefined ? plan() : over.in_effect;
  return {
    tenant_id: TENANT,
    state: "set",
    in_effect: inEffect,
    history: inEffect ? [inEffect] : [],
    loosening_confirmation: CONFIRMATION,
    ...over,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<CommercialsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    [TERMS_PATH]: terms(),
    ...routes,
  });
}

describe("the commercials screen", () => {
  it("withholds the form entirely when the current agreement could not be read", async () => {
    const { container } = await render({
      [TERMS_PATH]: problem(503, {
        title: "Upstream unavailable",
        detail: "We could not read this client's commercial terms.",
        retryable: true,
      }),
    });

    await screen.findByText("Cannot record terms while the current agreement is unreadable");
    expect(screen.queryByRole("button", { name: /Record new terms/ })).toBeNull();
    // The one sentence that must NOT appear over a failed read: it is also a real state.
    expect(container.textContent).not.toContain("No commercial terms set");
    expect(container.textContent).not.toContain("₹0");
  });

  it("states the absence of terms as a state to resolve, not as a zero", async () => {
    const { container } = await render({
      [TERMS_PATH]: terms({ state: "none", in_effect: null, history: [] }),
    });

    await screen.findByText("No commercial terms set");
    expect(container.textContent).toContain("invoiced nothing");
    expect(container.textContent).toContain("no spend ceiling stops their dialling");
    // The form is still offered — this is the screen that fixes it.
    expect(screen.getByRole("button", { name: /Record new terms/ })).toBeDefined();
  });

  it("prints a lapsed window as a misconfiguration rather than as no terms", async () => {
    const { container } = await render({
      [TERMS_PATH]: terms({
        state: "lapsed",
        in_effect: null,
        history: [plan({ effective_to: "2026-08-01T00:00:00Z" })],
      }),
    });

    await screen.findByText("Terms have lapsed");
    expect(container.textContent).toContain("end date was set with no successor");
  });

  it("formats a fee and leaves a rate unrounded", async () => {
    const { container } = await render();

    await screen.findByText("In effect now");
    expect(container.textContent).toContain("₹9,999.00");
    // The invoice multiplies by this number; ₹7.12 would break `qty x unit = amount`.
    expect(container.textContent).toContain("₹7.1250");
  });

  it("offers no default for the value-tier rate", async () => {
    await render();

    const field = (await screen.findByLabelText(/Value-tier rate/)) as HTMLInputElement;
    expect(field.value).toBe("");
  });

  it("records a tightened ceiling with no confirmation header", async () => {
    const { calls } = await render({
      [`POST ${TERMS_PATH}`]: { plan_id: "p", changed: true, superseded_plan_id: null, state: "set" },
    });

    const cap = (await screen.findByLabelText(/Spend ceiling/)) as HTMLInputElement;
    fireEvent.change(cap, { target: { value: "10000.00" } });
    fireEvent.click(screen.getByRole("button", { name: /Record new terms/ }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === TERMS_PATH)).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST" && call.path === TERMS_PATH);
    expect(post?.headers["X-Confirm-Action"]).toBeUndefined();
    expect(JSON.parse(post?.body ?? "{}").hard_cap_spend_inr).toBe("10000.00");
  });

  it("warns before a raise and sends the confirmation bound to THIS tenant", async () => {
    const { calls, container } = await render({
      [`POST ${TERMS_PATH}`]: { plan_id: "p", changed: true, superseded_plan_id: "q", state: "set" },
    });

    const cap = (await screen.findByLabelText(/Spend ceiling/)) as HTMLInputElement;
    fireEvent.change(cap, { target: { value: "90000.00" } });

    await waitFor(() => {
      expect(container.textContent).toContain("superadmin action");
    });
    expect(container.textContent).toContain("spend ceiling");

    fireEvent.click(screen.getByRole("button", { name: /Record new terms/ }));
    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path === TERMS_PATH)).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST" && call.path === TERMS_PATH);
    expect(post?.headers["X-Confirm-Action"]).toBe(CONFIRMATION);
    // The admin session, never the impersonating one: `admin:tenants` is a MUTATING
    // permission and D-22 refuses those to an acting-as session.
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("treats REMOVING a ceiling as the same dangerous direction as raising it", async () => {
    const { container } = await render();

    const cap = (await screen.findByLabelText(/Spend ceiling/)) as HTMLInputElement;
    fireEvent.change(cap, { target: { value: "" } });

    await waitFor(() => {
      expect(container.textContent).toContain("superadmin action");
    });
  });

  it("reports an unchanged write as unchanged instead of claiming a new agreement", async () => {
    const { container } = await render({
      [`POST ${TERMS_PATH}`]: {
        plan_id: "p",
        changed: false,
        superseded_plan_id: null,
        state: "set",
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: /Record new terms/ }));

    await waitFor(() => {
      expect(container.textContent).toContain("already the terms in effect");
    });
    expect(container.textContent).toContain("no audit row was added");
  });

  it("disables the write, with its reason, for a session that may not make it", async () => {
    await render({
      [ADMIN_ME_PATH]: { ...ME, permissions: ["org:read", "billing:read"] },
    });

    const button = (await screen.findByRole("button", {
      name: /Record new terms/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/record commercial terms/)).toBeDefined();
  });
});
