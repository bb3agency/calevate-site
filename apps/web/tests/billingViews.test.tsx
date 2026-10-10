import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { barPercent, toPaise } from "@/app/c/[slug]/billing/SpendChart";
import { walletStatementCsv } from "@/app/c/[slug]/billing/statementCsv";
import { formatBillingMonth } from "@/lib/billingMonth";

import {
  HUB_SPEND_SERIES_ROUTE,
  HUB_STATEMENTS_ROUTE,
  renderBillingHub,
} from "./billingHub";
import { PLATFORM_FEE_OFF, prepaidWallet, walletLots } from "./fixtures/sharedReads";
import { stillLoading } from "./harness";

/**
 * The round-2 billing hub's new pieces: the wallet header's "You owe", the spend-over-time
 * chart drawn in integer paise, and the statement list. The older suites (credits, topup,
 * usage, spend, clientInvoice) keep pinning everything that existed before.
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

const SERIES = {
  basis: "wallet_debits",
  timezone: "Asia/Kolkata",
  from_date: "2026-09-29",
  to_date: "2026-10-01",
  days: [
    { date: "2026-09-29", calls_inr: "10159.00", number_rental_inr: "0.00", ai_assist_inr: "0.00", adjustments_inr: "0.00", spent_inr: "10159.00" },
    { date: "2026-09-30", calls_inr: "0.00", number_rental_inr: "0.00", ai_assist_inr: "0.00", adjustments_inr: "0.00", spent_inr: "0.00" },
    { date: "2026-10-01", calls_inr: "5079.50", number_rental_inr: "0.00", ai_assist_inr: "0.00", adjustments_inr: "0.00", spent_inr: "5079.50" },
  ],
  calls_inr: "15238.50",
  number_rental_inr: "0.00",
  ai_assist_inr: "0.00",
  adjustments_inr: "0.00",
  spent_inr: "15238.50",
  by_agent: [{ agent_id: "a1", agent_name: "Front desk", calls_inr: "15238.50" }],
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/billing/platform-fee": PLATFORM_FEE_OFF,
    "/v1/billing/wallet": prepaidWallet(),
    "/v1/billing/wallet/ledger?limit=50": { entries: [], payments: [] },
    "/v1/billing/wallet/topups": [],
    "/v1/billing/topups/packs": stillLoading(),
    ...over,
  };
}

describe("drawing spend in paise, never floats", () => {
  it("reads the server's decimal string as whole paise", () => {
    expect(toPaise("10159.00")).toBe(BigInt(1015900));
    expect(toPaise("0.5")).toBe(BigInt(50));
    expect(toPaise("12")).toBe(BigInt(1200));
    // A negative day draws as no bar rather than one below the baseline.
    expect(toPaise("-3.00")).toBe(BigInt(0));
  });

  it("sizes a bar from integer arithmetic, relative to the busiest day", () => {
    expect(barPercent(BigInt(507950), BigInt(1015900))).toBe(50);
    expect(barPercent(BigInt(0), BigInt(1015900))).toBe(0);
    expect(barPercent(BigInt(1), BigInt(0))).toBe(0);
  });

  it("draws the window the server sent, zero days included, with a table behind it", async () => {
    const { container } = await renderBillingHub(routes({ [HUB_SPEND_SERIES_ROUTE]: SERIES }));
    const table = await screen.findByRole("table", { name: "Spending by day (IST)" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(container.textContent).toContain("₹15,238.50");
    // The busiest day is the full height; the half day is half of it, exactly.
    const bars = [...container.querySelectorAll<HTMLElement>("[title$='₹10,159.00'] > div, [title$='₹5,079.50'] > div")];
    expect(bars.map((bar) => bar.style.height)).toEqual(["max(100%, 2px)", "max(50%, 2px)"]);
    await screen.findByText("Front desk");
    // A zero rental is not a metric.
    expect(container.textContent).not.toContain("Phone number rental");
  });

  it("shows phone number rental as its own figure when the window has one (D-665)", async () => {
    const withRental = {
      ...SERIES,
      days: SERIES.days.map((day, index) =>
        index === 0 ? { ...day, number_rental_inr: "499.00", spent_inr: "10658.00" } : day,
      ),
      number_rental_inr: "499.00",
      spent_inr: "15737.50",
    };
    await renderBillingHub(routes({ [HUB_SPEND_SERIES_ROUTE]: withRental }));
    const label = await screen.findByText("Phone number rental");
    expect(label.parentElement?.textContent).toContain("₹499.00");
  });
});

describe("the wallet header", () => {
  it("says what is owed when the wallet has run past zero", async () => {
    await renderBillingHub(
      routes({
        "/v1/billing/wallet": prepaidWallet({ balance_inr: "-120.00", outbound_stopped: true }),
        "/v1/billing/wallet/lots": walletLots({ lots: [], overdraft_inr: "120.00" }),
      }),
    );
    await screen.findByText("-₹120.00");
    await screen.findByText("You owe ₹120.00");
  });

  it("says nothing is owed on a wallet in credit", async () => {
    const { container } = await renderBillingHub(routes());
    await screen.findByText("₹3,400.00");
    expect(container.textContent).not.toContain("You owe");
  });
});

describe("the statement list", () => {
  it("lists months by name and opens one in a drawer", async () => {
    const month = "2026-09";
    await renderBillingHub(
      routes({
        [HUB_STATEMENTS_ROUTE]: {
          statements: [
            {
              month,
              closed: true,
              document_type: "bill_of_supply",
              invoice_number: "CAL-202609-0001",
              total_inr: "4999.00",
              credit_added_inr: "5000.00",
              wallet_spent_inr: "1200.00",
              calls: 12,
              minutes_used: "40.00",
            },
          ],
          next_before: null,
        },
        [`/v1/billing/invoice?month=${month}`]: stillLoading(),
      }),
      "Statements",
    );
    await screen.findByText(formatBillingMonth(month));
    expect(formatBillingMonth(month)).toBe("September 2026");
    fireEvent.click(
      screen.getByRole("button", { name: "Open the statement for September 2026" }),
    );
    expect(await screen.findByRole("dialog", { name: "Statement for September 2026" })).toBeTruthy();
  });
});

describe("the statement CSV", () => {
  it("names a rental row by the server's label, and a plain row by its reason", () => {
    const entry = {
      id: "e1",
      delta_inr: "-499.00",
      reason: "usage",
      ref: null,
      balance_after_inr: "2901.00",
      lots: [],
      occurred_at: "2026-09-01T09:00:00Z",
      payment_ref: null,
    };
    const csv = walletStatementCsv([
      { ...entry, label: "Phone number rental" },
      { ...entry, id: "e2", label: null },
    ]);
    const [, rental, call] = csv.split("\r\n");
    expect(rental).toContain('"Phone number rental"');
    expect(call).toContain('"Calls"');
    expect(rental).toContain('"-499.00"');
  });
});
