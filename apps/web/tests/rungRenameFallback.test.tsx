import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import CommercialsPage from "@/app/admin/tenants/[tenantId]/commercials/page";
import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import type { Margin, TenantSummary } from "@/lib/api/admin";
import { commercialTermsPath, type CommercialTerms, type PlanRow } from "@/lib/api/commercials";

import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * THE CONSOLE STILL RENDERS AGAINST AN API THAT HAS NOT BEEN REDEPLOYED (D-558).
 *
 * ## What this is a test OF, and why it cannot be one of the fixtures above
 *
 * D-558 renamed the overage-rung fields on the wire under hard rule 8's two step:
 * `minutes_base_rung` / `cost_second_rung_inr` / `overage_rate_second_inr` are the names,
 * the deprecated `minutes_premium` / `cost_value_inr` / `overage_rate_value_inr` are
 * emitted beside them for one release, and the screens read the new name with `??` back to
 * the old one. **That `??` is the whole point of a two-step, and every other fixture in
 * this suite is typed against the CURRENT contract — where both names are present — so
 * not one of them ever takes the fallback arm.** A fallback nothing exercises is a
 * fallback nobody knows is broken.
 *
 * ## Why the fallback is real and not defensive decoration
 *
 * `scripts/vps-deploy.sh::components_for_paths` maps `apps/web/*` to the `web` component
 * and `apps/api/*` to `api` + `workers`, and the components restart independently — so a
 * bundle and the API it talks to are genuinely out of step for the length of a deploy, and
 * a change like this one touches both. A console that read only the new names would print
 * an empty margin card and an em dash over a real agreed rate for that window.
 *
 * ## How the legacy payload is spelled, and why there is no `as` in this file
 *
 * The generated types describe the API as it is TODAY, which is the state where both names
 * are present; there is no type for "the API of the previous release". The obvious
 * spelling — build a current payload and `as` it — is exactly what
 * `tests/wireFixtureGuard.test.ts` bans, and correctly: an assertion onto a wire type does
 * not make a fixture right, it makes it UNCHECKED, and five margin fixtures once drifted
 * behind one.
 *
 * So the omission is stated in the TYPE. `Omit<Margin["tiers"], "minutes_base_rung" | …>`
 * is an annotation, not an assertion: every remaining field is still checked against the
 * generated schema, a field the server cannot send is still rejected, and the values flow
 * into the route map (`Record<string, unknown>`) without anything being asserted at all —
 * which is the guard's own prescription for a deliberately off-contract payload.
 *
 * `Omit` earns its place twice over: it stops compiling the day step 2 removes those names
 * from the contract, which is precisely when this file should be deleted rather than
 * quietly kept.
 *
 * **STEP 2 DELETES THIS FILE**, in the same change that stops emitting the old names and
 * removes the `??` operators — not before, and not after.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000f1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const MARGIN_PATH = `${TENANT_PATH}/margin`;
const TERMS_PATH = commercialTermsPath(TENANT);

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000f2",
  role: "operator",
  permissions: ["org:read", "billing:read", "agents:read", "kb:write", "admin:tenants"],
};

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "managed",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

/** The rung split as the previous release sent it: the deprecated names and no others. */
type LegacyTiers = Omit<
  Margin["tiers"],
  "minutes_base_rung" | "minutes_second_rung" | "cost_base_rung_inr" | "cost_second_rung_inr"
>;

/** One dated agreement without the field that replaced `overage_rate_value_inr`. */
type LegacyPlanRow = Omit<PlanRow, "overage_rate_second_inr">;

/**
 * The margin card as an API one release BEHIND this bundle would send it: the deprecated
 * rung names only, because the names that replace them did not exist yet.
 */
function legacyMargin(): Omit<Margin, "tiers"> & { tiers: LegacyTiers } {
  return {
    month: "2026-08",
    minutes_used: "1204.5",
    calls: 412,
    revenue_inr: "1015900.00",
    cost_inr: "402350.50",
    margin_inr: "613549.50",
    margin_pct: "60.39",
    tiers: {
      minutes_premium: "900.00",
      minutes_value: "280.00",
      minutes_unattributed: "24.50",
      cost_premium_inr: "300000.00",
      cost_value_inr: "90000.00",
      cost_unattributed_inr: "12350.50",
    },
  };
}

/** One dated agreement, priced on both rungs, as the previous release's API sent it. */
function legacyPlan(): LegacyPlanRow {
  return {
    id: "0192f0aa-7777-7000-8000-0000000000f3",
    setup_fee_inr: null,
    monthly_fee_inr: "9999.0000",
    included_minutes: 100,
    overage_rate_inr: "8.0000",
    overage_rate_value_inr: "5.5000",
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
    margin: {
      effective_committed_rate_inr_per_min: "99.99",
      committed_gross_margin: "0.9631",
      overage_rate_inr_per_min: "8.0000",
      overage_gross_margin: "0.5375",
      below_target_margin: [],
      min_gross_margin: "0.20",
      cost_floor_inr_per_min: "3.70",
      cost_floor_basis: "assumed 540 chars/call-min (TRD 10.1, unmeasured - pilot gate 12)",
    },
  };
}

function legacyTerms(): Omit<CommercialTerms, "in_effect" | "history"> & {
  in_effect: LegacyPlanRow;
  history: LegacyPlanRow[];
} {
  const row = legacyPlan();
  return {
    tenant_id: TENANT,
    state: "set",
    in_effect: row,
    history: [row],
    loosening_confirmation: `raise_spend_ceiling:${TENANT}`,
  };
}

describe("the console reads the deprecated rung names when the API has not moved yet", () => {
  it("still splits the margin's cost by rung", async () => {
    const { container } = await renderAdminRoute(
      <TenantDetailPage params={routeParams({ tenantId: TENANT })} />,
      {
        [TENANT_PATH]: tenant(),
        [ADMIN_ME_PATH]: ME,
        [MARGIN_PATH]: legacyMargin(),
        [`${TENANT_PATH}/kb/sources?status=pending_approval`]: [],
        [`${TENANT_PATH}/kb/sources?status=approved`]: [],
        [`${TENANT_PATH}/agents`]: [],
        [`${TENANT_PATH}/numbers`]: [],
        [`${TENANT_PATH}/dlt-templates`]: [],
        [`${TENANT_PATH}/caps`]: {
          month: "2026-08",
          plan_cap_minutes: null,
          plan_cap_spend_inr: null,
          client_cap_minutes: null,
          client_cap_spend_inr: null,
          effective_cap_minutes: null,
          effective_cap_spend_inr: null,
          minutes_used: "812.00",
          spend_used_inr: "5002.40",
          capped: false,
        },
      },
    );

    await screen.findByText("Base overage rate");
    // The FIGURES, not merely the labels: a card that rendered its two rows with empty
    // cells would satisfy a label assertion and would be exactly the failure this guards.
    expect(container.textContent).toContain("900.00");
    expect(container.textContent).toContain("280.00");
  });

  it("still prints the second overage rate an operator agreed", async () => {
    const { container } = await renderAdminRoute(
      <CommercialsPage params={routeParams({ tenantId: TENANT })} />,
      {
        [TENANT_PATH]: tenant(),
        [ADMIN_ME_PATH]: ME,
        [TERMS_PATH]: legacyTerms(),
      },
    );

    await screen.findByText("Every agreement, newest first");
    // Both the "in effect" summary and the history row read through the same helper, so
    // one assertion over the document covers both — and an em dash in place of the rate is
    // the specific wrong answer (`—` over an account billed ₹5.50/min).
    expect(container.textContent).toContain("₹5.5000");

    const rows = within(screen.getByRole("table")).getAllByRole("row");
    const cells = within(rows[1])
      .getAllByRole("cell")
      .map((cell) => cell.textContent ?? "");
    expect(cells).toContain("₹5.5000");
  });
});
