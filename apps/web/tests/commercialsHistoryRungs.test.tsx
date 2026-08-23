import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CommercialsPage from "@/app/admin/tenants/[tenantId]/commercials/page";
import type { TenantSummary } from "@/lib/api/admin";
import { commercialTermsPath, type CommercialTerms, type PlanRow } from "@/lib/api/commercials";

import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The agreement history prints BOTH rungs of the price, not one of them.
 *
 * THE DEFECT, and it is the browser half of a server-side one fixed in the same change.
 * `plans` carries two overage rates — `overage_rate` (premium voice) and
 * `overage_rate_value` (D-36's value rung) — and this table had a single "Rate / min"
 * column reading the first. An agreement that priced the VALUE rung and nothing else
 * therefore printed an em dash under a heading a reader takes for the whole price: the
 * console saying "no rate agreed" over a row that bills the account.
 *
 * The server told the same lie from the same cause — `PlanRecord.states_pricing` carried
 * a hand-written list of price columns that predated `overage_rate_value`, so
 * `read_terms` filed such a plan as `unpriced` and the banner read "No price agreed …
 * They are still invoiced nothing". Fixing one side and not the other would have left
 * this screen contradicting the API it renders, which is how the next reader concludes
 * the API is wrong.
 *
 * Why a value-only row is the fixture rather than a curiosity: `plans.overage_rate_value`
 * is NULL on every row today because the retail value-tier price is an OPEN FOUNDER
 * DECISION (`tests/value_tier_rate_test.py`). The first row that ever carries one is
 * written the day that decision is made — i.e. this table's first encounter with the
 * column is also the first time an operator checks the price they just recorded.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000d1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const TERMS_PATH = commercialTermsPath(TENANT);

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000d2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

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
  };
}

/** A plan priced on BOTH rungs — the shape the two-column table exists for. */
function twoRungPlan(over: Partial<PlanRow> = {}): PlanRow {
  return {
    id: "0192f0aa-7777-7000-8000-0000000000d3",
    setup_fee_inr: null,
    monthly_fee_inr: "9999.0000",
    included_minutes: 100,
    overage_rate_inr: "8.0000",
    overage_rate_value_inr: "5.5000",
    // D-455: what this client pays extra, per minute, for a model THEY chose.
    llm_model_surcharge_inr: null,
    hard_cap_minutes: null,
    hard_cap_spend_inr: null,
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

function terms(inEffect: PlanRow, history: PlanRow[]): CommercialTerms {
  return {
    tenant_id: TENANT,
    state: "set",
    in_effect: inEffect,
    history,
    loosening_confirmation: `raise_spend_ceiling:${TENANT}`,
  };
}

/** `renderAdminRoute` is async (it awaits the Next 15 params promise inside `act`). */
async function render(inEffect: PlanRow) {
  return renderAdminRoute(<CommercialsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    [TERMS_PATH]: terms(inEffect, [inEffect]),
  });
}

/**
 * The history table's one data row, as its cells.
 *
 * Asserting on cells rather than on `container.textContent` is what makes the em-dash
 * test mean anything: "—" also renders in the Until column of every open-ended agreement,
 * so a whole-document `toContain("—")` would pass over a table that printed no rates at
 * all — which is precisely the bug being guarded against.
 */
async function historyCells(): Promise<string[]> {
  await screen.findByText("Every agreement, newest first");
  const rows = within(screen.getByRole("table")).getAllByRole("row");
  // Header plus exactly one agreement — the fixtures below each supply one row, so more
  // than that means the render, not the columns, is what this test is looking at.
  expect(rows).toHaveLength(2);
  return within(rows[1])
    .getAllByRole("cell")
    .map((cell) => cell.textContent ?? "");
}

describe("the agreement history prints both rungs of the price", () => {
  it("shows the premium and the value rate as separate columns", async () => {
    const { container } = await render(twoRungPlan());
    await screen.findByText("Every agreement, newest first");

    expect(container.textContent).toContain("Premium / min");
    expect(container.textContent).toContain("Value / min");
    // Both rates, UNROUNDED. `rate()` prints the API's digits and never re-derives them:
    // ₹7.1250 shown as ₹7.13 would break `qty x unit = amount` on the invoice.
    const cells = await historyCells();
    expect(cells).toContain("₹8.0000");
    expect(cells).toContain("₹5.5000");
  });

  it("does not print an agreement priced only on the value rung as having no rate", async () => {
    // The row the single-column table got wrong: no premium rate, a real value rate. It
    // printed one em dash and nothing else, over an account being billed ₹5.50/min.
    const { container } = await render(
      twoRungPlan({
        monthly_fee_inr: null,
        included_minutes: null,
        overage_rate_inr: null,
        overage_rate_value_inr: "5.5000",
      }),
    );
    await screen.findByText("Every agreement, newest first");

    expect(await historyCells()).toContain("₹5.5000");
    // The banner is the server's word, and it must agree: this account HAS a price.
    expect(container.textContent).not.toContain("No price agreed");
  });

  it("prints an em dash for a rung a plan genuinely does not quote", async () => {
    // Unset is not zero, on either rung: "₹0/min" is free minutes and an absent rate is a
    // plan that quotes none. The dash is the only honest rendering of the second.
    await render(twoRungPlan({ overage_rate_value_inr: null }));
    const cells = await historyCells();

    expect(cells).toContain("₹8.0000");
    expect(cells).not.toContain("₹0.0000");
    // Three dashes now, and the third is the point of the change below: Until, Value /
    // min, and the model surcharge this fixture also does not quote. Counted rather than
    // located by index because the count is what caught the column being added without
    // its em-dash rule.
    expect(cells.filter((cell) => cell === "—")).toHaveLength(3);
  });

  /**
   * THE MODEL SURCHARGE IS A PRICE, SO IT IS IN THE PRICE HISTORY (D-455).
   *
   * It reached the form and the "in effect" list in the wave that added the column and
   * stopped there, so this table — the effective-dated record an invoice is re-derived
   * from — showed every term of an agreement except the one that had just been invented.
   * A client querying an "AI model upgrade" line on a statement from two months ago is
   * answered from the row that was in effect then, and until this column existed the only
   * way to answer them was psql.
   *
   * The same em-dash rule as the two rungs beside it, for the same reason: `plans
   * .llm_model_surcharge` is NULL on every row today because the number is an open founder
   * decision, and "₹0.0000" would read as a decided price of zero rather than as a term
   * nobody has agreed.
   */
  it("prints the model surcharge that was in effect, unrounded", async () => {
    const { container } = await render(twoRungPlan({ llm_model_surcharge_inr: "1.5000" }));
    await screen.findByText("Every agreement, newest first");

    expect(container.textContent).toContain("Model surcharge / min");
    const cells = await historyCells();
    expect(cells).toContain("₹1.5000");
    // The rungs are untouched by it: a surcharge is ADDED to whichever rate a minute
    // landed on, and a table that replaced one with the other would be describing a
    // different plan from the one `billing/rates.py` prices.
    expect(cells).toContain("₹8.0000");
    expect(cells).toContain("₹5.5000");
  });
});
