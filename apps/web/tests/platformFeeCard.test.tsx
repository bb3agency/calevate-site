import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PlatformFee } from "@/lib/api/platformFee";

import { hubUsageIdle, renderBillingHub } from "./billingHub";
import { PLATFORM_FEE_OFF, prepaidWallet } from "./fixtures/sharedReads";

/**
 * The monthly platform fee card on the client's billing screen (D-707).
 *
 * A separate payment from calling credit: the card says so, says when outgoing calls pause
 * and that incoming calls never do, and prints nothing at all while the fee is switched
 * off and nothing is owed.
 */

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["wallet:read", "billing:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const OVERDUE = {
  enabled: true,
  amount_inr: "1999.00",
  exemption: null,
  outbound_paused: true,
  grace_days: 7,
  charges: [
    {
      id: "0192f0aa-7777-7000-8000-0000000000f1",
      period: "2026-10",
      amount_inr: "1999.00",
      issued_at: "2026-10-01T00:00:00Z",
      grace_ends_at: "2026-10-08T00:00:00Z",
      status: "overdue",
      paid_at: null,
      payment_method: null,
    },
  ],
} satisfies PlatformFee;

function routes(fee: PlatformFee) {
  return {
    ...hubUsageIdle(),
    "/v1/me": ME,
    "/v1/billing/wallet": prepaidWallet(),
    "/v1/billing/wallet/ledger?limit=50": { entries: [], payments: [] },
    "/v1/billing/wallet/topups": [],
    "/v1/billing/topups/packs": { packs: [] },
    "/v1/billing/platform-fee": fee,
  };
}

describe("the monthly platform fee card", () => {
  it("says outgoing calls are paused, incoming ones are not, and offers to pay", async () => {
    const { container } = await renderBillingHub(routes(OVERDUE));
    await screen.findByText("Monthly platform fee");
    expect(container.textContent).toContain("paid separately from your calling credit");
    expect(container.textContent).toContain("Outgoing calls are paused");
    expect(container.textContent).toContain("Incoming calls keep being answered");
    expect(screen.getByRole("button", { name: /Pay ₹1,999.00/ })).toBeTruthy();
  });

  it("renders nothing while the fee is off and nothing is owed", async () => {
    const { container } = await renderBillingHub(routes(PLATFORM_FEE_OFF));
    await screen.findByText("Calling credit");
    expect(container.textContent).not.toContain("Monthly platform fee");
  });
});
