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

const SPEND = {
  by_agent: [],
  by_unit: [],
  calls: 2,
  top_calls: [call(ON_OUR_MODEL), call(ON_THEIRS)],
  top_calls_truncated: false,
} as unknown as TenantSpend;

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
    fireEvent.click(screen.getByRole("radio", { name: /Costliest calls/ }));
    expect(await screen.findByText("62% cached")).toBeTruthy();
    expect(screen.getByTitle("6,200 of 10,000 input tokens cached")).toBeTruthy();
  });
});
