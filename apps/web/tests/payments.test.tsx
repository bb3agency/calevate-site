import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PaymentsScreen } from "@/app/admin/payments/PaymentsScreen";
import { AutoRechargePanel } from "@/app/c/[slug]/billing/AutoRechargePanel";
import { refundConfirmationHeader } from "@/lib/api/refunds";
import { disputeConfirmation } from "@/lib/api/adminPayments";
import { useClientRealm } from "@/lib/api/session";

import { expectNoA11yViolations } from "./a11y";
import { renderAdminPage, renderClientPage } from "./harness";

/**
 * D-699: the auto-recharge card (client) and the payments page (admin). Money arrives as
 * the server's digit strings and is printed as such.
 */

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["billing:read", "wallet:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const SETTINGS = {
  enabled: false,
  threshold_inr: "500.00",
  amount_inr: "2000.00",
  monthly_cap_inr: "6000.00",
  mandate_status: "none",
  mandate_method: null,
  mandate_max_inr: null,
  consecutive_failures: 0,
  disabled_reason: null,
  month_charged_inr: "0.00",
  pending_charge_inr: null,
  max_debit_inr: "15000.00",
  suggested_threshold_inr: "700.00",
};

function Panel() {
  const { session } = useClientRealm();
  return <AutoRechargePanel session={session} />;
}

describe("auto-recharge card", () => {
  it("says how long a top-up takes, the per-payment limit and the suggested threshold", async () => {
    const { container } = await renderClientPage(<Panel />, {
      "/v1/me": ME,
      "/v1/billing/auto-recharge": SETTINGS,
      "/v1/billing/auto-recharge/charges?limit=20": [],
    });
    expect(await screen.findByText(/No automatic payment method yet/)).toBeTruthy();
    expect(screen.getByText(/one to two days later/)).toBeTruthy();
    expect(screen.getByText(/At most ₹15,000/)).toBeTruthy();
    expect(screen.getByText(/at least ₹700/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Approve a payment method/ })).toBeTruthy();
    await expectNoA11yViolations(container, "auto-recharge card");
  });

  it("explains a paused approval and why auto-recharge went off", async () => {
    await renderClientPage(<Panel />, {
      "/v1/me": ME,
      "/v1/billing/auto-recharge": {
        ...SETTINGS,
        mandate_status: "paused",
        mandate_method: "upi",
        disabled_reason: "The automatic payment approval was paused in your UPI app.",
      },
      "/v1/billing/auto-recharge/charges?limit=20": [
        {
          amount_inr: "2000.00",
          status: "failed",
          failure_code: "insufficient_funds",
          created_at: "2026-10-09T05:00:00Z",
          settled_at: "2026-10-09T06:00:00Z",
        },
      ],
    });
    expect(await screen.findByText(/Resume it there/)).toBeTruthy();
    expect(screen.getByText(/Auto-recharge is off/)).toBeTruthy();
    expect(screen.getByText(/Did not go through/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Withdraw approval" })).toBeTruthy();
  });
});

describe("payments page", () => {
  const STATUS = {
    provider: "razorpay",
    mode: "live",
    key_id_mode: "test",
    key_id_set: true,
    key_secret_set: true,
    webhook_secret_set: true,
    online_payments_available: false,
    provider_orders_available: false,
    unavailable_reason: "payment_mode_mismatch",
    webhook_path: "/hooks/v1/razorpay",
    subscribed_events: ["payment.captured", "order.paid"],
    alarms: [],
  };

  it("names a key from the wrong mode and lists an open dispute with its hold", async () => {
    renderAdminPage(<PaymentsScreen />, {
      "/v1/admin/me": {
        user_id: "admin-1",
        realm: "admin",
        role: "superadmin",
        permissions: ["org:read", "admin:tenants"],
        impersonating: false,
      },
      "/v1/admin/payments/status": STATUS,
      "/v1/admin/payments/disputes?limit=200&include_closed=false": [
        {
          tenant_id: "t1",
          tenant_name: "Sri Clinic",
          dispute_id: "disp_1",
          payment_id: "pay_1",
          amount_inr: "390.00",
          hold_inr: "390.00",
          status: "open",
          phase: "chargeback",
          reason_code: "chargeback",
          respond_by: "2026-10-20T00:00:00Z",
          action_required: false,
          created_at: "2026-10-09T00:00:00Z",
        },
      ],
    });
    expect(await screen.findByText(/belongs to test mode, not live/)).toBeTruthy();
    expect(await screen.findByText(/Sri Clinic · ₹390/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Accept \(refunds the customer/ })).toBeTruthy();
  });

  it("binds each step-up confirmation to its payment or dispute", () => {
    expect(refundConfirmationHeader("t1", " pay_9 ")).toBe("refund_payment:t1:pay_9");
    expect(disputeConfirmation("disp_1", "accept")).toBe("dispute_accept:disp_1");
    expect(disputeConfirmation("disp_1", "contest")).toBe("dispute_contest:disp_1");
  });
});
