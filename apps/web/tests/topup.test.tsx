import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Me } from "@/lib/api/client";
import type { Wallet } from "@/lib/api/wallet";
import { RAZORPAY_CHECKOUT_SRC } from "@/lib/razorpayCheckout";

import { expectNoA11yViolations } from "./a11y";
import { renderBillingHub } from "./billingHub";
import { expectTextCount, problem } from "./harness";

/**
 * The top-up panel (D-98) — a control that must not exist unless it can work, and, since
 * the checkout landed, one that must take a payment all the way through.
 *
 * IT MOVED. The panel used to sit at the bottom of `/c/<slug>/usage`, behind
 * `billing:read`, so buying credit meant scrolling past a month's usage figures — and the
 * ledger, the receipts and a payment that had failed had nowhere at all. It is now the
 * "Add credit" card on `/c/<slug>/credits`; `tests/credits.test.tsx` holds that screen's
 * own states and this file follows the panel, unchanged.
 *
 * `tests/usage.test.tsx` holds the money formatting and the permission gate. This file
 * holds the capability states and the four ways a payment window can end, because each of
 * them is a different way this panel has been or could be wrong:
 *
 * 1. **Unavailable is a STATEMENT, not an empty state, and not an error.** This is the
 *    default configuration of every deployment (`PAYMENT_PROVIDER` unset), and the panel
 *    used to offer a form here whose only possible outcome was a red notice.
 * 2. **Loading is a skeleton** — never the form, and never the "not available" sentence,
 *    which would be an explanation about to be withdrawn (§52).
 * 3. **Failure is a refusal** — with no form under it, because a failed capability read
 *    means we do not know whether the form would work.
 * 4. **No order means no checkout.** The capability is a rendering HINT; the intent route
 *    is the authority, and when it answers with no order id the reference panel is the
 *    honest rendering however confident the hint was.
 * 5. **Every outcome of the payment window is distinct**, and exactly one of them may look
 *    like success. A dismissal is not a failure, a failure is not a refused signature, and
 *    a refused signature is not a payment.
 *
 * Money is asserted as the digit string the server sent, never as a number — and the paise
 * integer handed to the provider is asserted to be the server's own, because the failure
 * mode of arithmetic here is not a wrong pixel, it is a wrong charge.
 *
 * `window.Razorpay` is STUBBED throughout. No test here touches the network for it: the
 * script-load path is exercised by dispatching the events a real `<script>` would fire.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  // `wallet:read` is what the credits screen reads on and `org:manage` is what BUYING
  // needs — the founder's split (2 Sep 2026), and an owner holds both.
  permissions: ["billing:read", "wallet:read", "org:manage"],
  impersonating: false,
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

/**
 * A PREPAID wallet with credit on it — the only shape that renders the "Add credit" card.
 *
 * Healthy on purpose: this file is about the PAYMENT WINDOW, and a stopped or low wallet
 * would put a banner above the panel that has nothing to do with what these tests drive.
 * `tests/credits.test.tsx` holds those states.
 */
function wallet(over: Partial<Wallet> = {}): Wallet {
  return {
    tenant_id: "o1",
    prepaid: true,
    balance_inr: "1200.00",
    is_low: false,
    low_balance_threshold_inr: "200.00",
    granted_inr: "0.00",
    paid_inr: "2500.00",
    trial: null,
    outbound_stopped: false,
    runway: {
      basis: "projected",
      days: 9,
      daily_burn_inr: "130.00",
      history_days: 21,
      beyond_horizon: false,
      window_days: 30,
      min_history_days: 7,
      max_days: 365,
    },
    // Per QUALITY since D-547, because one balance divided by one live rate is a figure
    // that is wrong for every client whose lots were bought at anything but today's card.
    minutes_left: [
      { provider: "sarvam", label: "Clear", minutes: 240 },
      { provider: "cartesia", label: "Studio", minutes: 171 },
    ],
    drawdown: {
      calls_inr: "2730.00",
      ai_assist_inr: "0.00",
      adjustments_inr: "0.00",
      spent_inr: "2730.00",
      added_inr: "3930.00",
      refunded_inr: "0.00",
    },
    ...over,
  };
}

const WALLET = "/v1/billing/wallet";
const LEDGER = "/v1/billing/wallet/ledger?limit=50";
const ATTEMPTS = "/v1/billing/wallet/topups";

const CAPABILITY = "/v1/billing/topups/capability";
const PACKS = "/v1/billing/topups/packs";
const INTENT = "POST /v1/billing/topups/intent";
const CALLBACK = "POST /v1/billing/topups/callback";

/**
 * THE PACK RATE CARD, as the server sends it — the six-rung, two-rate card D-547 settled
 * (`apps/api/billing/credit_packs.py::PACK_CATALOGUE`, plan §2.2).
 *
 * All SIX packs, not a representative two, and that is the point of the fixture rather
 * than its size: the panel hardcodes no amount and no pack count, so the thing worth
 * pinning is that it renders whatever arrives. Every figure is the shape the server emits
 * — rupee amounts at 2dp, the rates at 4dp (a rate is not a rupee amount) — because the
 * panel formats digits and never parses them.
 *
 * The three DEPRECATED fields are here at the values the server actually sends for one
 * release (plan §10): `bonus_credits` / `bonus_pct` at zero, `effective_rate_inr_per_min`
 * and `talk_time_minutes` echoing the CHEAPER voice. They are in the fixture precisely so
 * a screen that went on reading them would be caught printing the wrong voice's figure as
 * though it were the pack's only one.
 *
 * `sarvam_tier_label` / `cartesia_tier_label` are what a CLIENT calls the two qualities.
 * They are the API's words (`billing/rates.py::VOICE_TIER_LABELS`) and the browser holds
 * no copy of them — which is why the panel is also driven WITHOUT them below, and asserted
 * to print no vendor name and no unattributed rate in that state.
 */
const PACK_CARD = {
  list_rate_inr_per_min: "5.00",
  from_inr_per_min: "4.50",
  from_sarvam_inr_per_min: "4.50",
  from_cartesia_inr_per_min: "6.00",
  sarvam_tier_label: "Clear",
  cartesia_tier_label: "Studio",
  packs: [
    {
      pack_id: "starter",
      amount_inr: "2000.00",
      paid_credits: "2000.00",
      bonus_credits: "0.00",
      total_credits: "2000.00",
      bonus_pct: "0",
      sarvam_inr_per_min: "5.0000",
      cartesia_inr_per_min: "8.0000",
      sarvam_minutes: 400,
      cartesia_minutes: 250,
      effective_rate_inr_per_min: "5.0000",
      talk_time_minutes: 400,
      best_value: false,
    },
    {
      pack_id: "growth",
      amount_inr: "5000.00",
      paid_credits: "5000.00",
      bonus_credits: "0.00",
      total_credits: "5000.00",
      bonus_pct: "0",
      sarvam_inr_per_min: "5.0000",
      cartesia_inr_per_min: "7.0000",
      sarvam_minutes: 1000,
      cartesia_minutes: 714,
      effective_rate_inr_per_min: "5.0000",
      talk_time_minutes: 1000,
      best_value: false,
    },
    {
      pack_id: "scale",
      amount_inr: "10000.00",
      paid_credits: "10000.00",
      bonus_credits: "0.00",
      total_credits: "10000.00",
      bonus_pct: "0",
      sarvam_inr_per_min: "4.8500",
      cartesia_inr_per_min: "6.7500",
      sarvam_minutes: 2061,
      cartesia_minutes: 1481,
      effective_rate_inr_per_min: "4.8500",
      talk_time_minutes: 2061,
      best_value: false,
    },
    {
      pack_id: "plus",
      amount_inr: "15000.00",
      paid_credits: "15000.00",
      bonus_credits: "0.00",
      total_credits: "15000.00",
      bonus_pct: "0",
      sarvam_inr_per_min: "4.7000",
      cartesia_inr_per_min: "6.5000",
      sarvam_minutes: 3191,
      cartesia_minutes: 2307,
      effective_rate_inr_per_min: "4.7000",
      talk_time_minutes: 3191,
      best_value: false,
    },
    {
      pack_id: "pro",
      amount_inr: "25000.00",
      paid_credits: "25000.00",
      bonus_credits: "0.00",
      total_credits: "25000.00",
      bonus_pct: "0",
      sarvam_inr_per_min: "4.6000",
      cartesia_inr_per_min: "6.2500",
      sarvam_minutes: 5434,
      cartesia_minutes: 4000,
      effective_rate_inr_per_min: "4.6000",
      talk_time_minutes: 5434,
      best_value: false,
    },
    {
      pack_id: "max",
      amount_inr: "50000.00",
      paid_credits: "50000.00",
      bonus_credits: "0.00",
      total_credits: "50000.00",
      bonus_pct: "0",
      sarvam_inr_per_min: "4.5000",
      cartesia_inr_per_min: "6.0000",
      sarvam_minutes: 11111,
      cartesia_minutes: 8333,
      effective_rate_inr_per_min: "4.5000",
      talk_time_minutes: 11111,
      best_value: true,
    },
  ],
};

/** The same card from an API build that has not started sending the two tier names. */
const UNNAMED_CARD = {
  ...PACK_CARD,
  sarvam_tier_label: undefined,
  cartesia_tier_label: undefined,
};

/**
 * An intent with a REAL order behind it — the shape a deployment holding the API secret
 * returns, and the only one that can open a payment window.
 *
 * ₹2,500.10 / 250010 paise deliberately: the amount whose last paisa a `Number()` drops.
 */
const ORDER_INTENT = {
  tenant_id: "o1",
  receipt: "clv_abc123",
  amount_inr: "2500.10",
  amount_paise: 250010,
  currency: "INR",
  notes: { calevate_tenant_id: "o1" },
  key_id: "rzp_test_publishable",
  provider_order_id: "order_TESTONLY0001",
  provider_order_pending: false,
  pack_id: null,
};

/** The three fields Checkout hands back, plus one the vendor might add tomorrow. */
const CHECKOUT_RESPONSE = {
  razorpay_order_id: "order_TESTONLY0001",
  razorpay_payment_id: "pay_TESTONLY0001",
  razorpay_signature: "b4d51gnatur3",
  razorpay_new_field_the_vendor_added: "surprise",
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    [WALLET]: wallet(),
    // Both are read by the screen AROUND the panel. Routed with the emptiest honest
    // answer, because an unrouted request throws in this harness — a hole in a test's
    // premise should say so rather than render an error state that happens to contain
    // the string it was looking for.
    [LEDGER]: { entries: [], payments: [] },
    [ATTEMPTS]: [],
    [CAPABILITY]: {
      online_payments_available: true,
      provider_orders_available: true,
    },
    [PACKS]: PACK_CARD,
    ...over,
  };
}

/**
 * The provider's global, as a stub that RECORDS rather than one that pretends.
 *
 * Every assertion about what we handed Checkout reads off `options` here, which is the
 * only place in this console where the amount actually charged is decided. The callbacks
 * are held rather than invoked, so each test drives the outcome it is about — which is the
 * only way to reach three of the four, none of which a real browser would produce on
 * demand.
 */
interface OpenedCheckout {
  options: {
    key: string;
    amount: number;
    currency: string;
    order_id: string;
    name: string;
    description: string;
    notes: Record<string, string>;
    handler: (response: Record<string, string>) => void;
    modal: { ondismiss: () => void };
    theme: { color: string };
  };
  onPaymentFailed: ((response: unknown) => void) | null;
  opens: number;
}

function stubRazorpay(): OpenedCheckout[] {
  const opened: OpenedCheckout[] = [];
  function FakeCheckout(options: OpenedCheckout["options"]) {
    const record: OpenedCheckout = { options, onPaymentFailed: null, opens: 0 };
    opened.push(record);
    return {
      open: () => {
        record.opens += 1;
      },
      on: (_event: string, handler: (response: unknown) => void) => {
        record.onPaymentFailed = handler;
      },
    };
  }
  window.Razorpay = FakeCheckout as unknown as typeof window.Razorpay;
  return opened;
}

afterEach(() => {
  // Module-scoped in the browser too: a stub left on `window` would let the NEXT test's
  // "the script did not load" case find a constructor and pass for the wrong reason.
  delete window.Razorpay;
  document.head.querySelectorAll("script[src]").forEach((tag) => tag.remove());
});

/** Start a ₹2,500.10 top-up from the custom-amount row and wait for the intent to land. */
async function payCustomAmount(): Promise<void> {
  const field = await screen.findByLabelText("Other amount");
  fireEvent.change(field, { target: { value: "2500.10" } });
  fireEvent.click(screen.getByText("Pay this amount"));
}

describe("the top-up panel", () => {
  it("states the bank-transfer path instead of offering a form that cannot work", async () => {
    // The DEFAULT configuration of every deployment. The form used to be offered here
    // and could only ever answer `payments_not_configured` — a control whose single
    // possible outcome is a red notice.
    const { container } = await renderBillingHub(
      routes({
        [CAPABILITY]: {
          online_payments_available: false,
          provider_orders_available: false,
        },
      }),
      "Credits",
    );

    // Awaited on the SENTENCE, not on the card around it: the panel renders a skeleton
    // until the capability lands, so asserting after the card would judge the loading
    // state and pass or fail on timing.
    await screen.findByText(/transfer the amount to us by bank/);
    expect(
      screen.queryByLabelText("Other amount"),
      "no form when it cannot work",
    ).toBeNull();
    expect(screen.queryByText("Get payment details")).toBeNull();
    expect(screen.queryByText("Pay this amount")).toBeNull();
    // Not an error either: this deployment is configured, not broken.
    expect(screen.queryByRole("alert")).toBeNull();

    // ...AND THE PRICES ARE STILL THERE. This branch used to `return` before the rate
    // card, so a client opening "Add credit" on any deployment without a provider account
    // — which is all of them until one exists — got a single sentence and no idea what
    // anything cost. They cannot decide what to transfer without knowing what a pack
    // buys. Removing the BUTTON must not remove the PRICE LIST: the catalogue reads no
    // tenant and no provider state, so it is exactly as true on a bank-transfer
    // deployment as on a card one.
    expect(screen.getByText("Best value"), "the rate card is gone").toBeTruthy();
    // BOTH RATES AND BOTH TALK TIMES, each under the name a client reads for that quality
    // (D-547). A pack is no longer one price: what a minute costs depends on the voice the
    // agent that takes the call speaks with, and a card that showed one number would be
    // showing the cheaper one to somebody who may choose the dearer voice.
    expect(container.textContent).toContain("₹4.5000/min · 11,111 min");
    expect(container.textContent).toContain("₹6.0000/min · 8,333 min");
    expect(container.textContent).toContain("Clear");
    expect(container.textContent).toContain("Studio");
    // THE "EXTRA CREDIT" COLUMN IS GONE, not emptied. `bonus_pct` and `bonus_credits` are
    // still on the wire at zero for one release, and a card that went on rendering them
    // would keep a retired idea on the screen a client buys from.
    expect(container.textContent).not.toContain("credits free");
    expect(container.textContent?.toLowerCase()).not.toContain("bonus");
    // And the button still names its amount even where it cannot pay — a grid of controls
    // all called "Select" is a list of identical names in a screen reader.
    expect(screen.getByRole("button", { name: "Select ₹50,000.00" })).toBeTruthy();
  });

  it("never names which of our secrets is missing", async () => {
    // `reason` is OUR configuration state and stays server-side. A client cannot act on
    // "no_webhook_secret" and telling them is an internals leak.
    const { container } = await renderBillingHub(
      routes({
        [CAPABILITY]: {
          online_payments_available: false,
          provider_orders_available: false,
        },
      }),
      "Credits",
    );

    await screen.findByText(/transfer the amount to us by bank/);
    const leaks = [
      "no_webhook_secret",
      "no_publishable_key",
      "no_payment_provider",
      "razorpay",
    ];
    for (const leak of leaks) {
      expect(container.textContent?.toLowerCase()).not.toContain(leak);
    }
  });

  it("refuses rather than guessing when the capability cannot be read", async () => {
    // We do not know whether payment works, so we offer nothing and say so. Rendering
    // the form optimistically would produce a refusal after the click; rendering the
    // "not available" sentence would state a fact we do not have.
    const { container } = await renderBillingHub(
      routes({ [CAPABILITY]: problem(503, { title: "Service unavailable" }) }),
      "Credits",
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByLabelText("Other amount")).toBeNull();
    expect(container.textContent).not.toContain(
      "transfer the amount to us by bank",
    );
  });

  it("offers the form and prices the top-up in the digits the server sent", async () => {
    // A deployment that can RECEIVE payments but cannot create orders (`no_api_secret`,
    // the state of every deployment before a Razorpay account exists). The label is the
    // consequence: this click produces a reference, not a payment window.
    const { container, calls } = await renderBillingHub(
      routes({
        [CAPABILITY]: {
          online_payments_available: true,
          provider_orders_available: false,
        },
        [INTENT]: { ...ORDER_INTENT, provider_order_id: null, provider_order_pending: true },
      }),
      "Credits",
    );

    const field = await screen.findByLabelText("Other amount");
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
    // THREE now, not two, and the third is the point of the change that added it: the
    // panel prints the amount as the headline, again inside the transfer instruction, and
    // again in the sentence saying which rates this amount buys at BEFORE the button. A
    // float anywhere on that path would drop the last paisa in one of the three, so the
    // count is asserted rather than mere presence — `toContain` is answered by any one of
    // them and a sabotage of the other two goes unnoticed.
    expectTextCount(container, "₹2,500.10", 3);
    // The two shapes a `Number()` leaves behind: the dropped trailing paisa, and the
    // ungrouped digits.
    expect(container.textContent).not.toMatch(/2,?500\.1(?!0)/);
    expect(container.textContent).not.toContain("2500.1");
    expect(container.textContent).toContain("clv_abc123");
    // The amount left as a STRING on the way out, too (hard rule 7).
    const sent = calls.find((c) => c.path === "/v1/billing/topups/intent");
    expect(sent?.body).toBe(JSON.stringify({ amount_inr: "2500.10" }));
  });

  it("renders an order id as a reference when the intent minted no order", async () => {
    // The capability said orders were available and the INTENT — which is the authority —
    // answered with none. The hint being stale costs a reference panel and can never cost
    // a payment: no window opens and no constructor is touched.
    const opened = stubRazorpay();
    const { container } = await renderBillingHub(
      routes({
        [INTENT]: { ...ORDER_INTENT, provider_order_id: null, provider_order_pending: true },
      }),
      "Credits",
    );

    await payCustomAmount();

    await screen.findByText(/nothing has been charged yet/);
    expect(container.textContent).toContain("to us by bank transfer quoting the reference");
    expect(opened, "no checkout without an order").toHaveLength(0);
  });

  it("renders the pack rate card and starts an intent priced by pack, not amount", async () => {
    stubRazorpay();
    const { container, calls } = await renderBillingHub(
      routes({
        [INTENT]: {
          ...ORDER_INTENT,
          receipt: "clv_pack_max",
          amount_inr: "50000.00",
          amount_paise: 5000000,
          notes: { calevate_tenant_id: "o1", calevate_pack_id: "max" },
          pack_id: "max",
        },
      }),
      "Credits",
    );

    // The rate card renders every pack with its server-priced figures — two rates, two
    // talk times, none of them computed in the browser.
    await screen.findByText("Best value");
    expect(container.textContent).toContain("₹4.5000/min · 11,111 min"); // max, cheaper voice
    expect(container.textContent).toContain("₹6.0000/min · 8,333 min"); // max, dearer voice
    expect(container.textContent).toContain("₹5.0000/min · 400 min"); // the entry rung
    expect(container.textContent).toContain("₹8.0000/min · 250 min");
    expect(container.textContent).toContain("₹50,000.00");
    // WHATEVER THE SERVER SENDS, however many: six rungs arrive and six buy controls
    // render, each named by its own amount. Nothing here knows what a pack costs, and the
    // ₹15,000 rung D-547 added needed no change here to appear.
    expect(screen.getAllByRole("button", { name: /^Pay ₹/ })).toHaveLength(6);
    expect(screen.getByRole("button", { name: "Pay ₹15,000.00" })).toBeTruthy();

    // Selecting a pack posts its id — never an amount — so the catalogue is the price.
    // Named by AMOUNT, because six buttons reading "Pay" are six identical names to a
    // screen reader and the row's price is what tells them apart.
    fireEvent.click(screen.getByRole("button", { name: "Pay ₹50,000.00" }));

    await screen.findByText(/is ready/);
    const sent = calls.find((c) => c.path === "/v1/billing/topups/intent");
    expect(sent?.body).toBe(JSON.stringify({ pack_id: "max" }));
  });

  it("lands the reader on a pack from the minutes they call, without doing money arithmetic", async () => {
    // THE QUESTION THE OLD TABLE MADE THE READER ANSWER THEMSELVES. Six columns of
    // arithmetic on a phone is not how somebody decides how much to put on their phone
    // system; "I call about this much" is. The recommendation is a comparison between two
    // figures the SERVER sent, and it prices nothing.
    //
    // IT MATCHES ON THE DEARER QUALITY, which is the property this test now pins and the
    // only direction that cannot mislead: a pack covering a month of Studio calling covers
    // it on Clear too, while the reverse would recommend a pack that falls short for
    // anybody who picks the dearer voice afterwards — on a different screen, later.
    const { container } = await renderBillingHub(routes(), "Credits");
    const suggestion = () =>
      screen.getByRole("status", { name: "Which pack covers your month" }).textContent ?? "";

    const field = await screen.findByLabelText(
      "Roughly how many minutes do you call in a month?",
    );

    // 200 minutes fits inside the entry pack on BOTH voices (250 on Studio) — the SMALLEST
    // that covers it, not the biggest that exists, which is the difference between a
    // recommendation and an upsell.
    fireEvent.change(field, { target: { value: "200" } });
    await waitFor(() => expect(suggestion()).toContain("₹2,000.00 covers it"));
    // Both figures, because the reader has not chosen a voice yet and one number would be
    // a promise that holds for only one of the two choices in front of them.
    expect(suggestion()).toContain("about 250 minutes on Studio and 400 on Clear");
    // The matched card says so where the reader is looking, not only in the sentence.
    expect(container.textContent).toContain("Covers your month");

    // 300 minutes still fits the entry pack on the CHEAPER voice (400) and does not on the
    // dearer one (250), so the answer moves up a rung. Reading the deprecated single
    // `talk_time_minutes` — which holds the cheaper figure — would have kept the ₹2,000
    // pack here and quietly under-bought for a Studio agent.
    fireEvent.change(field, { target: { value: "300" } });
    await waitFor(() => expect(suggestion()).toContain("₹5,000.00 covers it"));
    expect(suggestion()).toContain("about 714 minutes on Studio and 1,000 on Clear");

    // More than the whole catalogue can hold is answered honestly rather than by
    // recommending a pack that does not cover it.
    fireEvent.change(field, { target: { value: "40000" } });
    await waitFor(() => expect(suggestion()).toContain("more than one pack"));

    // Not a number: a sentence they can act on, and no recommendation invented from it.
    fireEvent.change(field, { target: { value: "lots" } });
    await waitFor(() =>
      expect(suggestion()).toContain("Enter the number of minutes as digits"),
    );
    expect(container.textContent).not.toContain("Covers your month");

    // NOTHING WAS BOUGHT AND NOTHING WAS ASKED OF THE SERVER. The matcher reads the
    // catalogue already on screen; a click on a pack is still the only thing that prices
    // anything.
    expect(
      screen.queryByRole("button", { name: /^Pay ₹2,500.10 now$/ }),
      "the matcher must not start an order",
    ).toBeNull();
  });

  it("says what a free-entry amount buys at before the payment button", async () => {
    // THE RATES A PURCHASE FREEZES ARE FROZEN THE MOMENT IT LANDS (D-547), so a client who
    // only learns them from the wallet afterwards has bought terms they never saw. The rule
    // is the server's (`billing/service.py::lot_rates_for_amount`: the largest pack the
    // amount reaches, floored at the smallest) and this panel states it in words.
    await renderBillingHub(routes(), "Credits");
    const field = await screen.findByLabelText("Other amount");
    const preview = () =>
      screen.getByRole("status", { name: "What this amount buys" }).textContent ?? "";

    fireEvent.change(field, { target: { value: "3400.00" } });
    // ₹3,400 does not reach the ₹5,000 rung, so it buys at the ₹2,000 pack's rates — and
    // it says the pack, because "why these rates" is the next question.
    await waitFor(() => expect(preview()).toContain("₹5.0000/min on Clear"));
    expect(preview()).toContain("₹8.0000/min on Studio");
    expect(preview()).toContain("₹2,000.00 pack");
    expect(preview()).toContain("₹3,400.00 buys calling");

    // A rung crossed changes the answer, and the figures are the catalogue's own digits —
    // no rate is interpolated between the rungs.
    fireEvent.change(field, { target: { value: "16000" } });
    await waitFor(() => expect(preview()).toContain("₹4.7000/min on Clear"));
    expect(preview()).toContain("₹6.5000/min on Studio");
    expect(preview()).toContain("₹15,000.00 pack");

    // BELOW THE FIRST RUNG IS NOT "NO RATES": the server floors it at the smallest pack,
    // and a client topping up ₹500 must not read that their credit is unpriced.
    fireEvent.change(field, { target: { value: "500" } });
    await waitFor(() => expect(preview()).toContain("₹5.0000/min on Clear"));

    // A half-typed amount states nothing rather than flickering a rate per keystroke.
    fireEvent.change(field, { target: { value: "16," } });
    await waitFor(() => expect(preview()).toBe(""));
  });

  it("prints no rate and no vendor name when the card carries no tier names", async () => {
    // THE NAMES ARE THE SERVER'S AND THERE IS NO FALLBACK. An API build that does not send
    // `sarvam_tier_label` / `cartesia_tier_label` leaves this panel with two rupee figures
    // it cannot attribute — and a reader shown an unnamed pair assigns the cheaper one to
    // whichever voice they had in mind. So the prices go, and the vendor's word is never
    // borrowed to keep them.
    const { container } = await renderBillingHub(
      routes({ [PACKS]: UNNAMED_CARD }),
      "Credits",
    );

    await screen.findByText("Best value");
    // The packs still render — a client can still buy — and every amount is still there.
    expect(screen.getAllByRole("button", { name: /^Pay ₹/ })).toHaveLength(6);
    expect(container.textContent).toContain("₹50,000.00");
    expect(container.textContent).toContain("50,000 credits of calling");
    // What is gone is every per-minute figure, on the cards and in the explainer.
    expect(container.textContent).not.toContain("/min");
    for (const vendor of ["sarvam", "cartesia", "Sarvam", "Cartesia"]) {
      expect(container.textContent).not.toContain(vendor);
    }
  });
});

describe("the payment window", () => {
  it("opens with the server's own values and charges no amount this browser computed", async () => {
    const opened = stubRazorpay();
    await renderBillingHub(routes({ [INTENT]: ORDER_INTENT }), "Credits");

    await payCustomAmount();
    await waitFor(() => expect(opened).toHaveLength(1));
    const { options, opens } = opened[0];

    // THE ASSERTION THIS FILE EXISTS FOR. `amount` is the integer the SERVER created the
    // order with, passed through untouched — identity, not equality-after-arithmetic. A
    // browser-side `Math.round(Number("2500.10") * 100)` returns 250010 here as well,
    // which is exactly why the guard is on the SOURCE of the number rather than on its
    // value: `toBe(ORDER_INTENT.amount_paise)` fails the moment anyone recomputes it from
    // a different field, and the two shapes below fail on the classic slips.
    expect(options.amount).toBe(ORDER_INTENT.amount_paise);
    expect(options.amount).not.toBe(2500.1); // rupees leaked through as the "amount"
    expect(options.amount).not.toBe(250010.00000000003); // the float route to paise
    expect(Number.isInteger(options.amount)).toBe(true);

    expect(options.key).toBe(ORDER_INTENT.key_id);
    expect(options.order_id).toBe(ORDER_INTENT.provider_order_id);
    expect(options.currency).toBe(ORDER_INTENT.currency);
    expect(options.notes).toEqual(ORDER_INTENT.notes);
    expect(options.description).toContain(ORDER_INTENT.receipt);
    expect(opens).toBe(1);

    // Prefill nothing we were not given: no email, no phone, no name of a person.
    expect(Object.keys(options)).not.toContain("prefill");
  });

  it("posts exactly the three signature fields and never asserts a balance itself", async () => {
    const opened = stubRazorpay();
    const { container, calls } = await renderBillingHub(
      routes({
        [INTENT]: ORDER_INTENT,
        [CALLBACK]: {
          verified: true,
          payment_id: CHECKOUT_RESPONSE.razorpay_payment_id,
          order_id: CHECKOUT_RESPONSE.razorpay_order_id,
          credit_pending: true,
        },
      }),
      "Credits",
    );

    await payCustomAmount();
    await waitFor(() => expect(opened).toHaveLength(1));
    await act(async () => {
      opened[0].options.handler(CHECKOUT_RESPONSE);
    });

    await screen.findByText("Payment received");

    // THE THREE, in the server's own field names, and NOTHING ELSE. `CheckoutCallbackIn`
    // forbids extra keys, so forwarding the provider's object whole would turn a vendor
    // adding a field into a 422 that reads, on this screen, like a payment that could not
    // be verified.
    const callback = calls.find((c) => c.path === "/v1/billing/topups/callback");
    expect(callback?.method).toBe("POST");
    expect(callback?.body).toBe(
      JSON.stringify({
        razorpay_order_id: CHECKOUT_RESPONSE.razorpay_order_id,
        razorpay_payment_id: CHECKOUT_RESPONSE.razorpay_payment_id,
        razorpay_signature: CHECKOUT_RESPONSE.razorpay_signature,
      }),
    );
    expect(callback?.body).not.toContain("razorpay_new_field_the_vendor_added");

    // The balance is REFETCHED, never computed: `credit_pending` is true on every
    // successful callback, so the only honest number is the server's next one.
    //
    // ASSERTED ON THE WALLET, which is the screen the panel now lives on. It used to
    // assert `/v1/usage`, and when the panel moved that assertion kept passing against a
    // read this screen does not make while the balance beside the button went stale — the
    // defect `useConfirmTopUp` now names in its own header.
    await waitFor(() =>
      expect(calls.filter((c) => c.path === WALLET).length).toBeGreaterThan(1),
    );
    // The unfinished-payments list is re-read too: the attempt just completed must stop
    // being listed as outstanding.
    expect(calls.filter((c) => c.path === ATTEMPTS).length).toBeGreaterThan(1);
    // ₹1,200.00 is the balance the fixture keeps returning. Nothing on screen may claim
    // ₹3,700.10 — the sum this browser could have worked out and has no right to.
    expect(container.textContent).not.toContain("₹3,700.10");
  });

  it("treats a dismissal as a cancellation, not a failure, and keeps the same order", async () => {
    const opened = stubRazorpay();
    const { container, calls } = await renderBillingHub(
      routes({ [INTENT]: ORDER_INTENT }),
      "Credits",
    );

    await payCustomAmount();
    await waitFor(() => expect(opened).toHaveLength(1));
    await act(async () => {
      opened[0].options.modal.ondismiss();
    });

    // Nothing was sent: a closed window is not a payment to verify.
    expect(calls.some((c) => c.path === "/v1/billing/topups/callback")).toBe(false);
    // Not an error, and not a spinner: the panel is usable and the SAME order is still
    // payable, so an accidental close does not mint a second order.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.textContent).not.toContain("did not go through");
    const retry = await screen.findByRole("button", { name: "Pay ₹2,500.10 now" });
    expect((retry as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(retry);
    await waitFor(() => expect(opened).toHaveLength(2));
    expect(opened[1].options.order_id).toBe(ORDER_INTENT.provider_order_id);
    // One intent, two openings — the order was reused, not replaced.
    expect(calls.filter((c) => c.path === "/v1/billing/topups/intent")).toHaveLength(1);
  });

  it("reports a failed payment in our words, never the provider's string", async () => {
    const opened = stubRazorpay();
    const { container, calls } = await renderBillingHub(
      routes({ [INTENT]: ORDER_INTENT }),
      "Credits",
    );

    await payCustomAmount();
    await waitFor(() => expect(opened).toHaveLength(1));
    await act(async () => {
      opened[0].onPaymentFailed?.({
        error: {
          code: "BAD_REQUEST_ERROR",
          description: "Your payment failed. Try another method — VENDOR SENTENCE.",
          source: "customer",
          step: "payment_authentication",
        },
      });
    });

    // `ProblemNotice` renders an `ApiProblem`'s DETAIL as its headline (the `message` the
    // constructor builds from it), which is why the detail is written to stand alone.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The payment was not completed");
    expect(alert.textContent).toContain("no credit has been added to your account");
    expect(alert.textContent).toContain("try again with the same or a different payment method");
    // The vendor's sentence and its error code are a third party's wording rendered to a
    // client of a client — the same judgement the server makes about `reason` codes.
    expect(container.textContent).not.toContain("VENDOR SENTENCE");
    expect(container.textContent).not.toContain("BAD_REQUEST_ERROR");
    expect(container.textContent).not.toContain("payment_authentication");
    // A failed attempt is not a payment to verify.
    expect(calls.some((c) => c.path === "/v1/billing/topups/callback")).toBe(false);
  });

  it("does not report a refused signature as success", async () => {
    // The one outcome that must never look like a payment. The client's money may well
    // have moved, which is why the sentence about the webhook has to be here and has to
    // be accurate: the wallet is credited by the signed webhook, not by this page.
    const opened = stubRazorpay();
    const { container } = await renderBillingHub(
      routes({
        [INTENT]: ORDER_INTENT,
        [CALLBACK]: problem(401, {
          type: "urn:calevate:auth/payment_signature_invalid",
          title: "Payment could not be verified",
          detail: "We could not confirm this payment was genuine.",
          remediation: "Do not retry the payment. Contact us if it was debited.",
          kind: "auth",
          retryable: false,
        }),
      }),
      "Credits",
    );

    await payCustomAmount();
    await waitFor(() => expect(opened).toHaveLength(1));
    await act(async () => {
      opened[0].options.handler(CHECKOUT_RESPONSE);
    });

    await screen.findByText("We could not confirm this payment was genuine.");
    // The server owns this wording; a paraphrase would be a second implementation of it.
    expect(container.textContent).toContain(
      "Do not retry the payment. Contact us if it was debited.",
    );
    expect(container.textContent).toContain("What happens next");
    expect(container.textContent).toContain(
      "your credit is still added automatically when the payment provider confirms",
    );
    // Nothing that reads as a completed payment.
    expect(screen.queryByText("Payment received")).toBeNull();
    expect(container.textContent).not.toContain("— paid.");
  });

  it("says so when the provider's script will not load, and offers a way through", async () => {
    // No `window.Razorpay`, so the loader really injects a tag; the `error` a blocked or
    // dropped request would fire is dispatched onto it. Nothing here reaches the network.
    const { calls } = await renderBillingHub(routes({ [INTENT]: ORDER_INTENT }), "Credits");

    await payCustomAmount();

    const tag = await waitFor(() => {
      const found = document.head.querySelector(`script[src="${RAZORPAY_CHECKOUT_SRC}"]`);
      expect(found, "checkout.js is fetched from the click, not from a layout").toBeTruthy();
      return found as HTMLScriptElement;
    });
    // Lazy, and lazy is the point: nothing loaded it before the client asked to pay.
    expect(document.head.querySelectorAll("script[src]")).toHaveLength(1);

    await act(async () => {
      tag.dispatchEvent(new Event("error"));
    });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The secure payment window did not load in this browser");
    expect(alert.textContent).toContain("nothing has been charged");
    // The way through that does not depend on this browser at all.
    expect(alert.textContent).toContain("bank transfer");
    expect(calls.some((c) => c.path === "/v1/billing/topups/callback")).toBe(false);
    // The dead tag is removed so a retry gets a fresh one — an errored `<script>` never
    // fires again, so leaving it would make every retry silent.
    expect(document.head.querySelector(`script[src="${RAZORPAY_CHECKOUT_SRC}"]`)).toBeNull();
  });

  it("keeps no secret in the browser and passes the accessibility floor", async () => {
    const opened = stubRazorpay();
    const { container } = await renderBillingHub(routes({ [INTENT]: ORDER_INTENT }), "Credits");

    await payCustomAmount();
    await waitFor(() => expect(opened).toHaveLength(1));
    // Back from the open window, which is the state a client spends time looking at: the
    // rate card, the form and a live pay control all on screen at once.
    await act(async () => {
      opened[0].options.modal.ondismiss();
    });
    await screen.findByRole("button", { name: "Pay ₹2,500.10 now" });

    // `key_id` is the PUBLISHABLE id and belongs in the browser. The key secret and the
    // webhook secret are the server's alone and must not be reachable from any surface
    // this screen renders or sends.
    const wire = JSON.stringify(opened[0].options);
    for (const secret of ["key_secret", "razorpay_api_secret", "webhook_secret"]) {
      expect(wire).not.toContain(secret);
      expect(container.textContent).not.toContain(secret);
    }

    // The panel in its most-rendered state: the rate card, the form and the live pay
    // control. The sweep in `a11y.test.tsx` renders rather than drives, so it cannot
    // reach this state at all.
    await expectNoA11yViolations(container, "c/[slug]/usage — top-up with a live order");
  });
});
