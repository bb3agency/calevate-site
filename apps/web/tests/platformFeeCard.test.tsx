import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { PlatformFee } from "@/lib/api/platformFee";

import { hubUsageIdle, renderBillingHub } from "./billingHub";
import { PLATFORM_FEE_OFF, prepaidWallet } from "./fixtures/sharedReads";
import { problem } from "./harness";

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
    expect(container.textContent).toContain("Incoming calls still answered");
    expect(screen.getByRole("button", { name: /Pay ₹1,999/ })).toBeTruthy();
  });

  it("asks for the fee to the paisa, never rounded to the display rule", async () => {
    const owed = { ...OVERDUE, amount_inr: "1178.82", charges: [{ ...OVERDUE.charges[0]!, amount_inr: "1178.82" }] };
    await renderBillingHub(routes(owed));
    expect(await screen.findByRole("button", { name: /Pay ₹1,178.82/ })).toBeTruthy();
  });

  it("renders nothing while the fee is off and nothing is owed", async () => {
    const { container } = await renderBillingHub(routes(PLATFORM_FEE_OFF));
    await screen.findByText("Calling credit");
    expect(container.textContent).not.toContain("Monthly platform fee");
  });
});

const CHARGE_ID = OVERDUE.charges[0]!.id;
const FEE_ORDER = {
  charge_id: CHARGE_ID,
  amount_inr: "1999.00",
  amount_paise: 199900,
  currency: "INR",
  key_id: "rzp_test_TESTONLY",
  notes: {},
  provider_order_id: "order_FEETESTONLY1",
  provider_order_pending: false,
  receipt: "fee_TESTONLY1",
};
const CHECKOUT_RESPONSE = {
  razorpay_order_id: "order_FEETESTONLY1",
  razorpay_payment_id: "pay_FEETESTONLY1",
  razorpay_signature: "s1gnature",
};
const PAID = {
  ...OVERDUE,
  outbound_paused: false,
  charges: [
    { ...OVERDUE.charges[0]!, status: "paid", paid_at: "2026-10-09T05:00:00Z", payment_method: "upi" },
  ],
} satisfies PlatformFee;

type Handler = (response: Record<string, string>) => void;

/** `window.Razorpay`, recording the options each window was opened with. */
function stubRazorpay(): { handler: Handler }[] {
  const opened: { handler: Handler }[] = [];
  function FakeCheckout(options: { handler: Handler }) {
    opened.push(options);
    return { open: () => undefined, on: () => undefined };
  }
  window.Razorpay = FakeCheckout as unknown as typeof window.Razorpay;
  return opened;
}

afterEach(() => {
  delete window.Razorpay;
});

describe("after paying the fee in the checkout window", () => {
  it("keeps the month's Pay button off until the record says paid, then says paid", async () => {
    const opened = stubRazorpay();
    let paid = false;
    let readsAfterPaying = 0;
    await renderBillingHub({
      ...routes(OVERDUE),
      // The webhook settles the fee a little after the callback: the read the callback
      // and the first poll still say overdue, a later poll says paid.
      "/v1/billing/platform-fee": () => {
        if (!paid) return OVERDUE;
        readsAfterPaying += 1;
        return readsAfterPaying > 2 ? PAID : OVERDUE;
      },
      [`POST /v1/billing/platform-fee/${CHARGE_ID}/order`]: FEE_ORDER,
      "POST /v1/billing/topups/callback": () => {
        paid = true;
        return {
          verified: true,
          payment_id: CHECKOUT_RESPONSE.razorpay_payment_id,
          order_id: CHECKOUT_RESPONSE.razorpay_order_id,
          credit_pending: true,
        };
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: /Pay ₹1,999/ }));
    await waitFor(() => expect(opened).toHaveLength(1));
    await act(async () => opened[0]!.handler(CHECKOUT_RESPONSE));

    await screen.findByText("Shows as paid within about a minute.");
    expect(screen.getByRole("button", { name: /Pay ₹1,999|Paid/ }).matches(":disabled")).toBe(true);

    await waitFor(() => expect(screen.getByText("Fee paid.")).toBeTruthy(), { timeout: 8_000 });
    expect(screen.queryByRole("button", { name: /Pay ₹1,999/ })).toBeNull();
  }, 15_000);

  it("says not to pay again when the payment could not be confirmed, and offers no second try", async () => {
    const opened = stubRazorpay();
    const { container } = await renderBillingHub({
      ...routes(OVERDUE),
      [`POST /v1/billing/platform-fee/${CHARGE_ID}/order`]: FEE_ORDER,
      "POST /v1/billing/topups/callback": problem(401, {
        title: "Payment could not be verified",
        detail: "We could not confirm this payment was genuine.",
        kind: "auth",
        retryable: false,
      }),
    });

    fireEvent.click(await screen.findByRole("button", { name: /Pay ₹1,999/ }));
    await waitFor(() => expect(opened).toHaveLength(1));
    await act(async () => opened[0]!.handler(CHECKOUT_RESPONSE));

    await screen.findByText("We could not confirm this payment was genuine.");
    expect(container.textContent).toContain("Do not pay again");
    const pay = screen.getByRole("button", { name: /Pay ₹1,999/ });
    expect(pay.matches(":disabled")).toBe(true);
    expect(pay.getAttribute("data-status")).not.toBe("error");
  });
});
