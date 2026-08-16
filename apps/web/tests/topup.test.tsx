import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UsagePage from "@/app/c/[slug]/usage/page";
import type { Me } from "@/lib/api/client";
import type { Caps } from "@/lib/api/caps";
import type { UsagePanel } from "@/lib/api/hooks";

import { expectTextCount, problem, renderClientPage } from "./harness";

/**
 * The top-up panel (D-98) — a control that must not exist unless it can work.
 *
 * `tests/usage.test.tsx` holds the money formatting and the permission gate. This file
 * holds the four states of the capability, because each of them is a different way this
 * panel has been or could be wrong:
 *
 * 1. **Unavailable is a STATEMENT, not an empty state, and not an error.** This is the
 *    default configuration of every deployment (`PAYMENT_PROVIDER` unset), and the panel
 *    used to offer a form here whose only possible outcome was a red notice.
 * 2. **Loading is a skeleton** — never the form, and never the "not available" sentence,
 *    which would be an explanation about to be withdrawn (§52).
 * 3. **Failure is a refusal** — with no form under it, because a failed capability read
 *    means we do not know whether the form would work.
 * 4. **An order id is rendered as a reference, never as a payment in progress.** There is
 *    no checkout in this build, and a panel implying one produces a client who believes
 *    they have paid.
 *
 * Money is asserted as the digit string the server sent, never as a number.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["billing:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const CAPS: Caps = {
  capped: false,
  month: "2026-08",
  minutes_used: "0.00",
  spend_used_inr: "0.00",
  client_cap_minutes: null,
  client_cap_spend_inr: null,
  effective_cap_minutes: null,
  effective_cap_spend_inr: null,
  plan_cap_minutes: null,
  plan_cap_spend_inr: null,
};

/** A PREPAID tenant with a wallet — the only shape that renders the top-up panel. */
function usage(over: Partial<UsagePanel> = {}): UsagePanel {
  return {
    month: "2026-08",
    calls: 3,
    capped: false,
    cap_minutes: null,
    minutes_left: null,
    included_minutes: 0,
    minutes_used: "12.00",
    credit_balance_inr: "1200.00",
    monthly_fee_inr: "0.00",
    overage_cost_inr: "0.00",
    overage_minutes: "0.00",
    overage_minutes_premium: "0.00",
    overage_minutes_value: "0.00",
    overage_rate_inr: "6.0000",
    overage_rate_value_inr: null,
    plan_tier: "self_serve",
    spend_used_inr: "72.00",
    ...over,
  };
}

const CAPABILITY = "/v1/billing/topups/capability";
const INTENT = "POST /v1/billing/topups/intent";

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/usage": usage(),
    "/v1/billing/caps": CAPS,
    [CAPABILITY]: { online_payments_available: true, provider_orders_available: true },
    ...over,
  };
}

const page = <UsagePage />;

describe("the top-up panel", () => {
  it("states the bank-transfer path instead of offering a form that cannot work", async () => {
    // The DEFAULT configuration of every deployment. The form used to be offered here
    // and could only ever answer `payments_not_configured` — a control whose single
    // possible outcome is a red notice.
    await renderClientPage(
      page,
      routes({
        [CAPABILITY]: { online_payments_available: false, provider_orders_available: false },
      }),
    );

    // Awaited on the SENTENCE, not on the card around it: the panel renders a skeleton
    // until the capability lands, so asserting after the card would judge the loading
    // state and pass or fail on timing.
    await screen.findByText(/transfer the amount to us by bank/);
    expect(screen.queryByLabelText("Add credit"), "no form when it cannot work").toBeNull();
    expect(screen.queryByText("Get payment details")).toBeNull();
    // Not an error either: this deployment is configured, not broken.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("never names which of our secrets is missing", async () => {
    // `reason` is OUR configuration state and stays server-side. A client cannot act on
    // "no_webhook_secret" and telling them is an internals leak.
    const { container } = await renderClientPage(
      page,
      routes({
        [CAPABILITY]: { online_payments_available: false, provider_orders_available: false },
      }),
    );

    await screen.findByText(/transfer the amount to us by bank/);
    const leaks = ["no_webhook_secret", "no_publishable_key", "no_payment_provider", "razorpay"];
    for (const leak of leaks) {
      expect(container.textContent?.toLowerCase()).not.toContain(leak);
    }
  });

  it("refuses rather than guessing when the capability cannot be read", async () => {
    // We do not know whether payment works, so we offer nothing and say so. Rendering
    // the form optimistically would produce a refusal after the click; rendering the
    // "not available" sentence would state a fact we do not have.
    const { container } = await renderClientPage(
      page,
      routes({ [CAPABILITY]: problem(503, { title: "Service unavailable" }) }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByLabelText("Add credit")).toBeNull();
    expect(container.textContent).not.toContain("transfer the amount to us by bank");
  });

  it("offers the form and prices the top-up in the digits the server sent", async () => {
    const { container, calls } = await renderClientPage(
      page,
      routes({
        [INTENT]: {
          tenant_id: "o1",
          receipt: "clv_abc123",
          amount_inr: "2500.10",
          amount_paise: 250010,
          currency: "INR",
          notes: { calevate_tenant_id: "o1" },
          key_id: "rzp_test_x",
          provider_order_id: null,
          provider_order_pending: true,
        },
      }),
    );

    const field = await screen.findByLabelText("Add credit");
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(field, { target: { value: "2500.10" } });
    fireEvent.click(screen.getByText("Get payment details"));

    await screen.findByText(/nothing has been charged yet/);
    // The paise the server priced, on screen exactly as sent. `Number("2500.10")` on the
    // way past is how ₹2,500.10 becomes ₹2,500.1 beside a bank transfer it must match.
    //
    // COUNTED, not merely present, and this is the assertion's whole strength: the panel
    // prints the amount TWICE — once as the headline and once inside the transfer
    // instruction — so `toContain` was satisfied by either of them and a float in the
    // other went unnoticed. A sabotage of the headline alone proved that. Both, or neither.
    expectTextCount(container, "₹2,500.10", 2);
    // The two shapes a `Number()` leaves behind: the dropped trailing paisa, and the
    // ungrouped digits.
    expect(container.textContent).not.toMatch(/2,?500\.1(?!0)/);
    expect(container.textContent).not.toContain("2500.1");
    expect(container.textContent).toContain("clv_abc123");
    // The amount left as a STRING on the way out, too (hard rule 7).
    const sent = calls.find((c) => c.path === "/v1/billing/topups/intent");
    expect(sent?.body).toBe(JSON.stringify({ amount_inr: "2500.10" }));
  });

  it("renders an order id as a reference and never as a payment in progress", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        [INTENT]: {
          tenant_id: "o1",
          receipt: "clv_abc123",
          amount_inr: "2000.00",
          amount_paise: 200000,
          currency: "INR",
          notes: { calevate_tenant_id: "o1" },
          key_id: "rzp_test_x",
          provider_order_id: "order_TESTONLY0001",
          provider_order_pending: false,
        },
      }),
    );

    const field = await screen.findByLabelText("Add credit");
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(field, { target: { value: "2000" } });
    fireEvent.click(screen.getByText("Get payment details"));

    await screen.findByText(/is set up and waiting/);
    expect(container.textContent).toContain("order_TESTONLY0001");
    expect(container.textContent).toContain("nothing has been charged yet");
    // No checkout exists in this build, so nothing may imply one is opening.
    expect(container.textContent).not.toMatch(/redirect|opening|pay now/i);
  });
});
