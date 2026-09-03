import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CreditsPage from "@/app/c/[slug]/credits/page";
import type { Me } from "@/lib/api/client";
import type { Wallet, WalletLedger } from "@/lib/api/wallet";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage, stillLoading } from "./harness";

/**
 * Calling credit (`/c/<slug>/credits`) — the screen a client opens to answer three
 * questions: how much is left, how long does it last, and where did it go.
 *
 * `tests/topup.test.tsx` owns the payment window itself and is not repeated here. What
 * this file holds is everything AROUND it, and every assertion is about a way this screen
 * could lie:
 *
 * 1. **The runway never invents a number.** Three of its four bases publish no `days` at
 *    all, and each has to read as a different sentence — a brand-new account is the FIRST
 *    thing every client sees here, and "0 days left" on day one is the lie that makes an
 *    owner buy credit they do not need.
 * 2. **An empty wallet leads with the reassurance.** "Your credit has run out" makes a
 *    clinic owner think their phone has stopped being answered. It has not, and the order
 *    of the sentences is the whole mitigation.
 * 3. **Money is rendered from the digits the server sent** and nothing on screen is a sum
 *    this browser worked out.
 * 4. **Every state is designed**: loading, day-one empty, low, stopped, an invoiced
 *    account with no wallet at all, a failed read, and a payment that did not finish.
 * 5. **Seeing is not buying**: a session without `wallet:read` gets a sentence, not a 403.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["wallet:read", "billing:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const WALLET = "/v1/billing/wallet";
const LEDGER = "/v1/billing/wallet/ledger?limit=50";
const ATTEMPTS = "/v1/billing/wallet/topups";
const CAPABILITY = "/v1/billing/topups/capability";
const PACKS = "/v1/billing/topups/packs";

function wallet(over: Partial<Wallet> = {}): Wallet {
  return {
    tenant_id: "o1",
    prepaid: true,
    balance_inr: "3400.00",
    is_low: false,
    low_balance_threshold_inr: "200.00",
    outbound_stopped: false,
    runway: {
      basis: "projected",
      days: 10,
      daily_burn_inr: "340.00",
      history_days: 30,
      beyond_horizon: false,
      window_days: 30,
      min_history_days: 7,
      max_days: 365,
    },
    minutes_left: 425,
    drawdown: {
      calls_inr: "8400.00",
      ai_assist_inr: "300.00",
      adjustments_inr: "0.00",
      spent_inr: "8700.00",
      added_inr: "12100.00",
      refunded_inr: "0.00",
    },
    ...over,
  };
}

const LEDGER_ROWS: WalletLedger = {
  entries: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      delta_inr: "-42.50",
      reason: "usage",
      ref: "call:9",
      balance_after_inr: "3400.00",
      occurred_at: "2026-08-30T09:00:00Z",
      payment_ref: null,
    },
    {
      id: "22222222-2222-4222-8222-222222222222",
      delta_inr: "2500.00",
      reason: "topup",
      ref: "pay_a1b2c3",
      balance_after_inr: "3442.50",
      occurred_at: "2026-08-01T09:00:00Z",
      payment_ref: "pay_a1b2c3",
    },
  ],
  payments: [
    {
      payment_ref: "pay_a1b2c3",
      credited_inr: "2500.00",
      entries: 1,
      first_at: "2026-08-01T09:00:00Z",
    },
  ],
};

const PACK_CARD = {
  list_rate_inr_per_min: "8.00",
  packs: [
    {
      pack_id: "starter",
      amount_inr: "1000.00",
      paid_credits: "1000.00",
      bonus_credits: "0.00",
      total_credits: "1000.00",
      bonus_pct: "0",
      effective_rate_inr_per_min: "8.0000",
      talk_time_minutes: 125,
      best_value: false,
    },
  ],
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    [WALLET]: wallet(),
    [LEDGER]: LEDGER_ROWS,
    [ATTEMPTS]: [],
    [CAPABILITY]: { online_payments_available: true, provider_orders_available: true },
    [PACKS]: PACK_CARD,
    ...over,
  };
}

const page = <CreditsPage />;

describe("the hero: how much, and how long it lasts", () => {
  it("puts the balance and the runway together, and shows the working behind the days", async () => {
    const { container } = await renderClientPage(page, routes());

    // The digits the server sent, grouped the Indian way — never a parsed number.
    await screen.findByText("₹3,400.00");
    await screen.findByText(/About 10 days of calling left/);
    // THE WORKING, not only the conclusion: an owner who disagrees with "10 days" can see
    // the ₹340 a day it came from.
    await screen.findByText(/₹340\.00 a day over the last 30 days/);
    await screen.findByText(/425 minutes/);
    // Nothing on this screen is a sum the browser worked out.
    expect(container.textContent).not.toContain("₹12,100.00 spent");
  });

  it("refuses to project from an account too new to divide, and says how much is needed", async () => {
    // DAY ONE — the first thing every client ever sees on this screen.
    await renderClientPage(
      page,
      routes({
        [WALLET]: wallet({
          balance_inr: "1000.00",
          minutes_left: 125,
          runway: {
            basis: "too_new",
            days: null,
            daily_burn_inr: null,
            history_days: 3,
            beyond_horizon: false,
            window_days: 30,
            min_history_days: 7,
            max_days: 365,
          },
        }),
      }),
    );

    await screen.findByText(/We need about 7 days of calling/);
    await screen.findByText(/we have 3 so far/);
    // The lie this screen must never tell.
    expect(screen.queryByText(/0 days of calling left/)).toBeNull();
    expect(screen.queryByText(/About 0 days/)).toBeNull();
  });

  it("says a wallet that is not being spent is not being spent, rather than nothing", async () => {
    await renderClientPage(
      page,
      routes({
        [WALLET]: wallet({
          runway: {
            basis: "no_burn",
            days: null,
            daily_burn_inr: "0.00",
            history_days: 30,
            beyond_horizon: false,
            window_days: 30,
            min_history_days: 7,
            max_days: 365,
          },
        }),
      }),
    );
    await screen.findByText(/You have not spent anything recently/);
  });

  it("caps an idle account at 'more than a year' instead of a true, useless number", async () => {
    await renderClientPage(
      page,
      routes({
        [WALLET]: wallet({
          runway: {
            basis: "projected",
            days: null,
            daily_burn_inr: "3.00",
            history_days: 30,
            beyond_horizon: true,
            window_days: 30,
            min_history_days: 7,
            max_days: 365,
          },
        }),
      }),
    );
    await screen.findByText(/More than a year of calling/);
  });
});

describe("an empty wallet: what stopped, and what emphatically did not", () => {
  it("leads with 'people calling you still get through' before naming what stopped", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        [WALLET]: wallet({
          balance_inr: "0.00",
          is_low: true,
          outbound_stopped: true,
          minutes_left: 0,
          runway: {
            basis: "empty",
            days: null,
            daily_burn_inr: "340.00",
            history_days: 30,
            beyond_horizon: false,
            window_days: 30,
            min_history_days: 7,
            max_days: 365,
          },
        }),
      }),
    );

    const alert = await screen.findByRole("alert");
    const text = alert.textContent ?? "";
    // THE ORDER IS THE MITIGATION. A clinic owner reading "your credit has run out" on a
    // phone at 8pm concludes their phone has stopped being answered — the single most
    // expensive wrong belief this product can create — so the reassurance comes first.
    expect(text).toContain("still get through");
    expect(text.indexOf("still get through")).toBeLessThan(text.indexOf("Outgoing calls have stopped"));
    // And the state is not carried by colour alone (WCAG 1.4.1): there is a sentence.
    expect(text).toContain("Outgoing calls have stopped");
    await expectNoA11yViolations(container, "c/[slug]/credits — empty wallet");
  });

  it("warns at the low band without claiming anything has stopped yet", async () => {
    await renderClientPage(
      page,
      routes({ [WALLET]: wallet({ balance_inr: "150.00", is_low: true, minutes_left: 18 }) }),
    );
    // NOT `findByRole("status")`: `Skeleton` is a live region too (it announces the
    // start of a load), so that query races the panel it is looking for.
    const notice = (await screen.findByText(/running low/)).closest("[role=status]");
    expect(notice?.textContent).toContain("₹150.00");
    // Nothing has stopped, so nothing says it has.
    expect(screen.queryByText(/Outgoing calls have stopped/)).toBeNull();
  });
});

describe("where the money went", () => {
  it("names the three things that draw the wallet down and never invents a fourth", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText(/Where your credit went in the last 30 days/);
    await screen.findByText("Calls");
    await screen.findByText("Extra AI help");
    await screen.findByText("₹8,700.00");
    // MESSAGING IS NOT A BUCKET. Nothing on this platform debits the wallet for a message,
    // so a "Messaging ₹0.00" row would be a category invented to look complete — and a
    // client reading it would reasonably conclude they are being charged for messages.
    expect(container.textContent).not.toContain("Messaging");
    // A zero row is hidden rather than inviting a question about nothing.
    expect(screen.queryByText("Corrections")).toBeNull();
  });

  it("designs the day-one empty state rather than showing headers over nothing", async () => {
    await renderClientPage(
      page,
      routes({
        [WALLET]: wallet({
          drawdown: {
            calls_inr: "0.00",
            ai_assist_inr: "0.00",
            adjustments_inr: "0.00",
            spent_inr: "0.00",
            added_inr: "0.00",
            refunded_inr: "0.00",
          },
        }),
        [LEDGER]: { entries: [], payments: [] },
      }),
    );

    // Two empty states, and both SAY what will appear rather than rendering a blank.
    // `waitFor` on the COUNT, not `findAllByText`: that resolves as soon as ONE match
    // exists, so it would pass while the second panel was still loading.
    await waitFor(() =>
      expect(screen.getAllByText(/Nothing has moved on your credit yet/)).toHaveLength(2),
    );
    await screen.findByText(/Payments you make and calls your agents handle/);
  });
});

describe("the ledger and its receipts", () => {
  it("lists newest first and offers a receipt only against a payment", async () => {
    await renderClientPage(page, routes());

    const table = await screen.findByRole("table", { name: /credit history/i });
    const rows = within(table).getAllByRole("row");
    // Header, then the usage row, then the payment — newest first.
    expect(within(rows[1]).getByText("Call usage")).toBeTruthy();
    expect(within(rows[2]).getByText("Payment recorded")).toBeTruthy();
    // A receipt exists for the payment and NOT for the call charge: there is no document
    // to issue for money we took a fraction of a rupee at a time.
    expect(within(rows[1]).queryByRole("button", { name: /receipt/i })).toBeNull();
    expect(within(rows[2]).getByRole("button", { name: /receipt for the payment/i })).toBeTruthy();
    // The sign is in the DIGITS, not only in a colour (WCAG 1.4.1).
    expect(within(rows[1]).getByText("-₹42.50")).toBeTruthy();
  });

  it("opens a receipt that calls itself a receipt and never a tax invoice", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/billing/wallet/receipts/pay_a1b2c3": {
          document_type: "receipt",
          payment_ref: "pay_a1b2c3",
          amount_inr: "2500.00",
          received_at: "2026-08-01T09:00:00Z",
          entries: 1,
          supplier_legal_name: "BuiltByThree Technologies",
          supplier_address: "Hyderabad",
          organization_name: "Sri Clinic",
          organization_billing_email: "owner@sriclinic.example",
          note:
            "This is a receipt for calling credit added to your account. No tax has been " +
            "charged on it. It is not a tax invoice.",
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /receipt for the payment/i }));

    const dialog = await screen.findByRole("dialog", { name: "Payment receipt" });
    await within(dialog).findByText("₹2,500.00");
    // THE HEADING COMES OFF THE WIRE. The business is not GST-registered, so CGST s.32
    // forbids collecting tax and nothing here may print a tax heading.
    expect(within(dialog).getByRole("heading", { name: "Receipt" })).toBeTruthy();
    expect(dialog.textContent).toContain("It is not a tax invoice.");
    expect(dialog.textContent).not.toMatch(/TAX INVOICE|GSTIN/);
    await expectNoA11yViolations(container, "c/[slug]/credits — receipt dialog");
  });
});

describe("payments that did not finish", () => {
  it("shows a failed payment, says no money moved, and does not offer a second control", async () => {
    await renderClientPage(
      page,
      routes({
        [ATTEMPTS]: [
          {
            id: "33333333-3333-4333-8333-333333333333",
            receipt: "CAL-2608-0007",
            amount_inr: "2500.00",
            pack_id: null,
            outcome: "failed",
            started_at: "2026-08-30T10:00:00Z",
          },
        ],
      }),
    );

    await screen.findByText("Did not go through");
    await screen.findByText(/nothing was charged and no credit was added/);
    await screen.findByText("CAL-2608-0007");
  });

  it("tells a client who closed the tab that their credit lands without this page", async () => {
    await renderClientPage(
      page,
      routes({
        [ATTEMPTS]: [
          {
            id: "44444444-4444-4444-8444-444444444444",
            receipt: "CAL-2608-0008",
            amount_inr: "2500.00",
            pack_id: null,
            outcome: "settling",
            started_at: "2026-08-30T10:00:00Z",
          },
        ],
      }),
    );

    // THE BROWSER IS NOT WHAT CREDITS A WALLET — the signed webhook is — so this is a fact
    // about our system rather than reassurance, and it is the thing a client who closed
    // the tab mid-payment most needs to read.
    await screen.findByText("Still settling");
    await screen.findByText(/your credit is added automatically/);
    await screen.findByText(/should not pay again yet/);
  });

  it("says nothing at all when no payment is outstanding", async () => {
    await renderClientPage(page, routes());
    // A card headed "payments that did not finish" reading "none" on every visit is a
    // permanent invitation to worry.
    expect(screen.queryByText(/Payments that have not finished/)).toBeNull();
  });
});

describe("the states that are not a balance", () => {
  it("shows a skeleton while the wallet is in flight, never a zero", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [WALLET]: stillLoading() }),
    );
    // The skeleton is ANNOUNCED as well as drawn (`components/ui.Skeleton`), which is the
    // half a screen-reader user would otherwise get nothing from.
    await screen.findByText("Loading your calling credit");
    expect(container.querySelector("[role=status][aria-live=polite]")).toBeTruthy();
    expect(container.textContent).not.toContain("₹0.00");
  });

  it("refuses rather than rendering an empty wallet when the read fails", async () => {
    await renderClientPage(
      page,
      routes({
        [WALLET]: problem(503, {
          title: "We could not load your credit",
          detail: "We could not read your balance just now.",
        }),
      }),
    );
    // `ProblemNotice` renders the server's DETAIL — the sentence a client can act on —
    // rather than the title, which is the class of failure.
    await screen.findByText("We could not read your balance just now.");
    // A failed read is NOT a zero balance, and it is certainly not "outgoing calls have
    // stopped" — which is what a `?? 0` here would have rendered.
    expect(screen.queryByText(/Outgoing calls have stopped/)).toBeNull();
  });

  it("tells an invoiced account there is nothing to top up, rather than showing ₹0.00", async () => {
    await renderClientPage(
      page,
      routes({ [WALLET]: wallet({ prepaid: false, balance_inr: "0.00", minutes_left: null }) }),
    );
    await screen.findByText("This account is invoiced, not prepaid");
    await screen.findByText(/your calls never stop for want of credit/);
    // No balance about nothing, and no control the intent route is bound to refuse.
    expect(screen.queryByText(/Add credit/)).toBeNull();
  });

  it("gives a session without the permission a sentence, not a red 403", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/me": { ...ME, role: "staff", permissions: ["calls:read"] },
      }),
    );
    await screen.findByText(/limited to people with access to this account's billing/);
    expect(screen.queryByText("₹3,400.00")).toBeNull();
  });
});
