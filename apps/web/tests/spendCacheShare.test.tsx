import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Breakdown } from "@/app/admin/tenants/[tenantId]/spend/SpendBreakdown";
import type { TenantSpend } from "@/lib/api/spend";

import { renderAdminPage } from "./harness";

const TENANT = "7f0c2b1e-0000-4000-8000-000000000001";
const ON_OUR_MODEL = "0192f000-0000-7000-8000-000000000001";
const ON_THEIRS = "0192f000-0000-7000-8000-000000000002";

function call(callId: string) {
  return {
    call_id: callId,
    agent_id: "agent-1",
    agent_name: "Front desk",
    started_at: "2026-10-12T09:00:00Z",
    direction: "inbound",
    minutes: "3.0000",
    charged_inr: "18.00",
    cost_inr: "9.00",
    margin_inr: "9.00",
    cost_currency_assumed: false,
    trial_covered: false,
  };
}

const SPEND: TenantSpend = {
  unpriced_rows: 0,
  month: "2026-08",
  plan_tier: "prepaid",
  charge_basis: "wallet_debit",
  calls: 2,
  minutes_used: "0.00",
  retainer_inr: null,
  revenue_inr: "0.00",
  rental_revenue_inr: "0.00",
  cost_inr: "0.00",
  margin_inr: "0.00",
  margin_pct: null,
  cost_currency: "INR",
  cost_currency_stated: true,
  trial_cost_inr: "0.00",
  trial_in_month: false,
  paid_cost_inr: "0.00",
  paid_margin_inr: "0.00",
  paid_margin_pct: null,
  trial_calls: 0,
  trial_minutes: "0.00",
  period_charge_inr: "0.00",
  itemised_charge_inr: "0.00",
  itemisation_residual_inr: "0.00",
  residual_reason: null,
  unattributed: null,
  ai_assist: null,
  by_unit: [],
  by_agent: [],
  top_calls: [call(ON_OUR_MODEL), call(ON_THEIRS)],
  top_calls_truncated: false,
};

/**
 * D-839: the admin's call cost list shows how much of an own-model call's input the provider
 * served from its cache; a call not on our model shows a dash, never "0% cached".
 */
describe("the cache share on the costliest calls", () => {
  it("shows each own-model call's share and a dash for any other call", async () => {
    const path = `/v1/ops/voices/own-model/cache-shares?tenant_id=${TENANT}&call_id=${ON_OUR_MODEL}&call_id=${ON_THEIRS}`;
    renderAdminPage(<Breakdown data={SPEND} tenantId={TENANT} />, {
      [path]: {
        calls: [{ call_id: ON_OUR_MODEL, cached_input_tokens: 6200, input_tokens: 10000, share: "0.6200" }],
      },
    });
    fireEvent.click(screen.getByRole("radio", { name: /Costliest/ }));
    expect(await screen.findByText("62% cached")).toBeTruthy();
    expect(screen.getByTitle("6,200 of 10,000 input tokens cached")).toBeTruthy();
  });
});
