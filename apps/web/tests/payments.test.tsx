import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StepUpPrompt } from "@/components/authn/stepUpPrompt";
import { PaymentsScreen } from "@/app/admin/payments/PaymentsScreen";
import { AutoRechargePanel } from "@/app/c/[slug]/billing/AutoRechargePanel";
import { refundConfirmationHeader } from "@/lib/api/refunds";
import { disputeConfirmation } from "@/lib/api/adminPayments";
import { useClientRealm } from "@/lib/api/session";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderAdminPage, renderClientPage } from "./harness";

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

function Panel({ available = true }: { available?: boolean }) {
  const { session } = useClientRealm();
  return <AutoRechargePanel session={session} available={available} />;
}

describe("auto top-up and the payment route it needs", () => {
  it("offers no payment method and no switch where online payment is off, and says why", async () => {
    const { container } = await renderClientPage(<Panel available={false} />, {
      "/v1/me": ME,
      "/v1/billing/auto-recharge": SETTINGS,
      "/v1/billing/auto-recharge/charges?limit=20": [],
    });
    expect(await screen.findByText(/Needs online payment, which isn't on yet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve a payment method/ })).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(container.textContent).not.toContain("UPI Autopay");
  });

  it("keeps an existing approval withdrawable but offers no switch while online payment is off", async () => {
    await renderClientPage(<Panel available={false} />, {
      "/v1/me": ME,
      "/v1/billing/auto-recharge": {
        ...SETTINGS,
        mandate_status: "confirmed",
        mandate_method: "upi",
        mandate_max_inr: "15000.00",
      },
      "/v1/billing/auto-recharge/charges?limit=20": [],
    });
    expect(await screen.findByRole("button", { name: "Withdraw approval" })).toBeTruthy();
    expect(screen.getByText(/Needs online payment/)).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("offers the method and the switch where online payment is on, and states the setting while closed", async () => {
    await renderClientPage(<Panel />, {
      "/v1/me": ME,
      "/v1/billing/auto-recharge": SETTINGS,
      "/v1/billing/auto-recharge/charges?limit=20": [],
    });
    expect(await screen.findByRole("button", { name: /Approve a payment method/ })).toBeTruthy();
    expect(screen.getByRole("switch", { name: /Top up automatically/ })).toBeTruthy();
    expect(screen.queryByText(/needs online payment/i)).toBeNull();
    // The closed row says what it is set to, and offers to set it up.
    const summary = screen.getByText("Auto top-up").closest("summary");
    expect(summary?.textContent).toContain("Off");
    expect(summary?.textContent).toContain("Set up");
  });
});

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
    expect(screen.getByText(/Auto top-up is off/)).toBeTruthy();
    expect(screen.getByText(/Did not go through/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Withdraw approval" })).toBeTruthy();
  });

  it("shows a refused approval start in words rather than dropping it", async () => {
    await renderClientPage(<Panel />, {
      "/v1/me": ME,
      "/v1/billing/auto-recharge": SETTINGS,
      "/v1/billing/auto-recharge/charges?limit=20": [],
      "POST /v1/billing/auto-recharge/mandate": problem(409, {
        title: "Conflict",
        detail: "Auto-recharge cannot be approved right now.",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /Approve a payment method/ }));
    expect(await screen.findByText(/Auto-recharge cannot be approved right now./)).toBeTruthy();
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

  it("says when the recent payments it lists are only the newest slice", async () => {
    const payments = Array.from({ length: 50 }, (_, index) => ({
      payment_id: `pay_${index}`,
      status: "captured",
      amount_inr: "500.00",
      method: "upi",
      international: false,
      tenant_id: "t1",
      created_at: "2026-10-09T00:00:00Z",
    }));
    renderAdminPage(<PaymentsScreen />, {
      "/v1/admin/me": {
        user_id: "admin-1",
        realm: "admin",
        role: "superadmin",
        permissions: ["org:read", "admin:tenants"],
        impersonating: false,
      },
      "/v1/admin/payments/status": STATUS,
      "/v1/admin/payments/disputes?limit=200&include_closed=false": [],
      "/v1/admin/payments/recent?limit=50": payments,
    });
    fireEvent.click(await screen.findByRole("button", { name: "Load the last three days" }));
    expect(await screen.findByText(/The newest 50 are shown/)).toBeTruthy();
  });

  it("takes at most five evidence files and says so before anything is uploaded", async () => {
    const { calls } = renderAdminPage(<PaymentsScreen />, {
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
    fireEvent.click(await screen.findByRole("button", { name: "Contest" }));
    expect(screen.getByText("Up to 5 files, PDF, JPEG or PNG, 5 MB each.")).toBeTruthy();
    const six = Array.from(
      { length: 6 },
      (_, i) => new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], `proof-${i + 1}.pdf`, { type: "application/pdf" }),
    );
    fireEvent.change(screen.getByLabelText("Evidence documents"), { target: { files: six } });
    expect(await screen.findByText(/at most 5 files, so 1 file was not added/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove proof-5.pdf" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove proof-6.pdf" })).toBeNull();
    expect(screen.getByText("5 of 5 files chosen. Remove one to add another.")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("asks for a code when accepting a dispute needs a fresh second factor, then retries", async () => {
    const acceptPath = "/v1/admin/payments/disputes/disp_1/accept";
    let refuse = true;
    const { calls } = renderAdminPage(
      <>
        <StepUpPrompt />
        <PaymentsScreen />
      </>,
      {
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
        [`POST ${acceptPath}`]: () =>
          refuse
            ? problem(403, {
                type: "https://calevate.tech/problems/reauthentication_required",
                title: "Confirm it is still you",
                detail: "This action needs a second factor proved in the last 30 minutes.",
                kind: "permission",
              })
            : { dispute_id: "disp_1", status: "lost" },
        "POST /v1/auth/admin/step-up": {},
        "POST /v1/auth/admin/step-up/verify": {
          realm: "admin",
          subject_id: "admin-1",
          mfa_complete: true,
          email_verified: true,
        },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: /Accept \(refunds the customer/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Accept and refund" }));
    expect(await screen.findByText(/Accepting this dispute and refunding the customer/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /email me a code/i }));
    await waitFor(() => {
      expect(calls.some((call) => call.path === "/v1/auth/admin/step-up")).toBe(true);
    });
    refuse = false;
    fireEvent.change(screen.getByLabelText(/six-digit code/i), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
    await waitFor(() => {
      expect(calls.filter((call) => call.path === acceptPath)).toHaveLength(2);
    });
    const sent = calls.filter((call) => call.path === acceptPath);
    expect(sent[1]?.headers["X-Confirm-Action"]).toBe("dispute_accept:disp_1");
  });

  it("binds each step-up confirmation to its payment or dispute", () => {
    expect(refundConfirmationHeader("t1", " pay_9 ")).toBe("refund_payment:t1:pay_9");
    expect(disputeConfirmation("disp_1", "accept")).toBe("dispute_accept:disp_1");
    expect(disputeConfirmation("disp_1", "contest")).toBe("dispute_contest:disp_1");
  });
});
