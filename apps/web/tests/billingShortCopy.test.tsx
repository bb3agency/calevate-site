import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WALLET_LOTS_PATH } from "@/app/c/[slug]/billing/lots";
import { HERO_COPY } from "@/app/c/[slug]/billing/WalletHero";
import { TOPUP_COPY } from "@/app/c/[slug]/billing/TopUp";
import { OWNER_ONLY_SPENDING } from "@/app/c/[slug]/billing/UsageTab";

import {
  CREDIT_USAGE_PATH,
  HUB_SPEND_ROUTE,
  HUB_SPEND_SERIES_ROUTE,
  HUB_STATEMENTS_ROUTE,
  VOICE_TIERS_PATH,
  renderBillingHub,
} from "./billingHub";
import { prepaidWallet, walletLots } from "./fixtures/sharedReads";
import { SHORT_LINE } from "./shortCopy";

/**
 * "Buttons, not paragraphs": the billing screens' DEFAULT view carries no line longer than
 * a phone holds comfortably. Our clients are small-business owners reading English as a
 * second language, often on a 375px screen; an explanation belongs behind a "Why?" tap.
 *
 * A "line" is any text block a reader sees without opening anything: a paragraph, list
 * item, heading, cell, label, button or link. Text inside a closed `<details>` (other than
 * its summary), screen-reader-only text and the server's own prose (fixture strings here
 * are kept short) are not lines. The bound is 60 characters.
 */
const MAX = SHORT_LINE;
const BLOCKS = "p, li, h1, h2, h3, h4, dt, dd, th, td, button, label, summary, legend, a, caption";

function hiddenByClosedDetails(el: Element): boolean {
  for (let node = el.parentElement; node; node = node.parentElement) {
    if (node instanceof HTMLDetailsElement && !node.open) {
      const summary = node.querySelector(":scope > summary");
      if (!summary || !summary.contains(el)) return true;
    }
  }
  return false;
}

/** The visible text of one block, without its screen-reader-only or folded parts. */
function visibleText(el: Element): string {
  const copy = el.cloneNode(true) as Element;
  copy.querySelectorAll(".sr-only, [aria-hidden='true'], details:not([open]) > :not(summary)").forEach((node) => node.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

function longLines(root: ParentNode): string[] {
  const long: string[] = [];
  root.querySelectorAll(BLOCKS).forEach((el) => {
    if (el.closest(".sr-only, [hidden], [aria-hidden='true'], caption.sr-only")) return;
    if (hiddenByClosedDetails(el)) return;
    // A block holding other blocks is measured through them, not as one line.
    if (el.querySelector(BLOCKS)) return;
    const text = visibleText(el);
    if (text.length > MAX) long.push(`${text.length}: ${text}`);
  });
  return long;
}

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["wallet:read", "billing:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Traders", slug: "acme", status: "active" },
};

const pack = (id: string, amount: string, clear: string, studio: string, cm: number, sm: number) => ({
  pack_id: id,
  amount_inr: amount,
  paid_credits: amount,
  bonus_credits: "0.00",
  total_credits: amount,
  bonus_pct: "0",
  clear_inr_per_min: clear,
  studio_inr_per_min: studio,
  clear_minutes: cm,
  studio_minutes: sm,
  effective_rate_inr_per_min: clear,
  talk_time_minutes: cm,
  best_value: id === "plus",
});

const PACKS = {
  list_rate_inr_per_min: "5.00",
  from_inr_per_min: "4.70",
  from_clear_inr_per_min: "4.70",
  from_studio_inr_per_min: "6.50",
  clear_tier_label: "Clear",
  studio_tier_label: "Studio",
  voice_not_offered: null,
  voice_not_offered_notice: null,
  credit_expiry_months: 12,
  credit_lapses_on_if_bought_now: "2027-10-28",
  packs: [
    pack("starter", "2000.00", "5.0000", "8.0000", 400, 250),
    pack("growth", "5000.00", "5.0000", "7.0000", 1000, 714),
    pack("plus", "15000.00", "4.7000", "6.5000", 3191, 2307),
  ],
};

const MONTH = HUB_SPEND_ROUTE.slice(-7);

const USAGE = {
  month: MONTH,
  plan_tier: "prepaid",
  calls: 96,
  capped: true,
  cap_minutes: null,
  minutes_left: null,
  clear_minutes: "300.00",
  clear_charges_inr: "1500.00",
  clear_label: "Clear",
  studio_minutes: "112.50",
  studio_charges_inr: "810.00",
  studio_label: "Studio",
  included_minutes: 0,
  minutes_used: "412.50",
  credit_balance_inr: null,
  monthly_fee_inr: "0.00",
  overage_cost_inr: "0.00",
  overage_minutes: "0.00",
  overage_rate_inr: "0.00",
  llm_surcharge_rate_inr: null,
  llm_surcharge_minutes: "0.00",
  llm_surcharge_inr: "0.00",
  llm_surcharge_tiers: [],
  month_charges_inr: "2310.00",
};

const FIGURES = {
  calls_inr: "2310.00",
  number_rental_inr: "499.00",
  ai_assist_inr: "0.00",
  adjustments_inr: "0.00",
  spent_inr: "2809.00",
  added_inr: "2000.00",
};

function routes(over: Record<string, unknown> = {}, online = true) {
  return {
    "/v1/me": ME,
    "/v1/billing/wallet": prepaidWallet(),
    [WALLET_LOTS_PATH]: walletLots({
      lots: [
        { ...walletLots().lots[0]!, expires_at: "2027-08-20T09:00:00Z" },
      ],
    }),
    "/v1/billing/wallet/ledger?limit=50": {
      entries: [
        {
          id: "e1",
          delta_inr: "2000.00",
          reason: "topup",
          ref: null,
          label: null,
          balance_after_inr: "3400.00",
          lots: [],
          occurred_at: "2026-10-20T06:30:00Z",
          payment_ref: "pay_1",
        },
      ],
      payments: [],
    },
    "/v1/billing/wallet/topups": [
      { id: "t1", receipt: "CAL-1", amount_inr: "2000.00", pack_id: null, outcome: "failed", started_at: "2026-10-27T10:30:00Z" },
      { id: "t2", receipt: "CAL-2", amount_inr: "5000.00", pack_id: null, outcome: "settling", started_at: "2026-10-28T06:30:00Z" },
    ],
    "/v1/billing/topups/packs": PACKS,
    "/v1/billing/topups/capability": {
      online_payments_available: online,
      provider_orders_available: online,
      reason: online ? null : "no_webhook_secret",
    },
    "/v1/billing/platform-fee": {
      enabled: true,
      amount_inr: "999.00",
      exemption: null,
      outbound_paused: true,
      grace_days: 7,
      charges: [{ id: "f1", period: MONTH, amount_inr: "999.00", status: "overdue", grace_ends_at: "2026-10-07T18:29:59Z" }],
    },
    "/v1/billing/auto-recharge": {
      enabled: false,
      threshold_inr: "500.00",
      amount_inr: "2000.00",
      monthly_cap_inr: "10000.00",
      mandate_status: "none",
      mandate_method: null,
      mandate_max_inr: "0.00",
      max_debit_inr: "15000.00",
      month_charged_inr: "0.00",
      suggested_threshold_inr: "700.00",
      disabled_reason: null,
    },
    "/v1/billing/auto-recharge/charges?limit=20": [],
    "/v1/usage": USAGE,
    "/v1/billing/caps": {
      capped: true,
      trial_active: false,
      month: MONTH,
      minutes_used: "412.50",
      spend_used_inr: "2310.00",
      client_cap_minutes: null,
      client_cap_spend_inr: "2000.00",
      effective_cap_minutes: null,
      effective_cap_spend_inr: "2000.00",
      plan_cap_minutes: null,
      plan_cap_spend_inr: "50000.00",
    },
    [HUB_SPEND_ROUTE]: {
      month: MONTH,
      charge_basis: "wallet_debit",
      calls: 96,
      minutes_used: "412.50",
      retainer_inr: null,
      period_charge_inr: "2310.00",
      itemised_charge_inr: "2310.00",
      itemisation_residual_inr: "0.00",
      residual_reason: null,
      by_agent: [{ agent_id: "a1", agent_name: "Front desk", calls: 70, minutes: "300.00", charged_inr: "1500.00" }],
      top_calls: [],
      top_calls_truncated: false,
    },
    [HUB_SPEND_SERIES_ROUTE]: {
      basis: "wallet_debits",
      timezone: "Asia/Kolkata",
      from_date: "2026-10-27",
      to_date: "2026-10-28",
      days: [
        { date: "2026-10-27", calls_inr: "300.00", number_rental_inr: "0.00", ai_assist_inr: "0.00", adjustments_inr: "0.00", spent_inr: "300.00" },
        { date: "2026-10-28", calls_inr: "200.00", number_rental_inr: "0.00", ai_assist_inr: "0.00", adjustments_inr: "0.00", spent_inr: "200.00" },
      ],
      calls_inr: "500.00",
      number_rental_inr: "0.00",
      ai_assist_inr: "0.00",
      adjustments_inr: "0.00",
      spent_inr: "500.00",
      by_agent: [{ agent_id: "a1", agent_name: "Front desk", calls_inr: "500.00" }],
    },
    [CREDIT_USAGE_PATH]: { month: MONTH, this_month: FIGURES, all_time: FIGURES },
    [VOICE_TIERS_PATH]: {
      recommended: "clear",
      recommendation_reason: "Most calls are short questions.",
      not_offered_notice: null,
      tiers: [
        { tier: "clear", label: "Clear", offered: true, your_inr_per_min: "5.00", from_inr_per_min: "4.70", to_inr_per_min: "5.00", minutes_left: 720, minutes_this_month: "300.00", charged_this_month_inr: "1500.00", includes: ["Natural voice"], best_for: "Everyday calls" },
        { tier: "studio", label: "Studio", offered: true, your_inr_per_min: "8.00", from_inr_per_min: "6.50", to_inr_per_min: "8.00", minutes_left: 505, minutes_this_month: "112.50", charged_this_month_inr: "810.00", includes: ["Most lifelike voice"], best_for: "Sales calls" },
      ],
    },
    [HUB_STATEMENTS_ROUTE]: {
      statements: [
        { month: MONTH, closed: false, document_type: "bill_of_supply", invoice_number: "CAL-202610-0001", total_inr: "2809.00", credit_added_inr: "2000.00", wallet_spent_inr: "2809.00", calls: 96, minutes_used: "412.50" },
      ],
      next_before: null,
    },
    ...over,
  };
}

describe("billing copy: one short line per item", () => {
  it("measures what a reader sees and skips what is folded away", () => {
    const root = document.createElement("div");
    const long = "x".repeat(MAX + 1);
    root.innerHTML = `<p>${long}</p><details><summary>Why?</summary><p>${long}y</p></details><span class="sr-only"><p>${long}z</p></span>`;
    expect(longLines(root)).toEqual([`${MAX + 1}: ${long}`]);
  });

  it("keeps every named phrase to a phone line", () => {
    const phrases = [...Object.values(HERO_COPY), ...Object.values(TOPUP_COPY), OWNER_ONLY_SPENDING];
    // The "Why?" sentences are the explanation behind the tap, so they may run long.
    const shown = phrases.filter((phrase) => phrase !== HERO_COPY.stoppedWhy && phrase !== HERO_COPY.dayOneWhy);
    expect(shown.filter((phrase) => phrase.length > MAX)).toEqual([]);
  });

  it("the Usage view, with a cap hit, a fee unpaid and a payment unfinished", async () => {
    const { container } = await renderBillingHub(routes());
    await screen.findByText("Front desk");
    await screen.findByText("Outgoing calls paused. Spending limit reached.");
    await screen.findByText("Unfinished payments");
    await screen.findByRole("button", { name: /Pay ₹999/ });
    // Each problem carries a button that does something about it.
    expect(screen.getByRole("link", { name: "Raise my limit" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(longLines(container)).toEqual([]);
  });

  it("the run-out and day-one wallet headers", async () => {
    const stopped = prepaidWallet({ balance_inr: "0.00", is_low: true, outbound_stopped: true });
    const { container } = await renderBillingHub(routes({ "/v1/billing/wallet": stopped }));
    await screen.findByText(HERO_COPY.stoppedTitle);
    expect(longLines(container)).toEqual([]);
  });

  it("the Transactions and Statements views", async () => {
    const { container } = await renderBillingHub(routes(), "Transactions");
    await screen.findByText("Credit history");
    expect(longLines(container)).toEqual([]);
    fireEvent.click(screen.getByRole("radio", { name: "Statements" }));
    await screen.findByText("CAL-202610-0001");
    expect(longLines(container)).toEqual([]);
  });

  it("the Add credit drawer, paying online with a pack chosen", async () => {
    const { container } = await renderBillingHub(routes(), "Credits");
    fireEvent.click(await screen.findByRole("radio", { name: /^₹5,000/ }));
    await screen.findByRole("button", { name: "Continue" });
    expect(longLines(container)).toEqual([]);
  });

  it("the Add credit drawer when only a bank transfer works", async () => {
    const { container } = await renderBillingHub(routes({}, false), "Credits");
    await screen.findByText(TOPUP_COPY.bankTitle);
    await screen.findByText(TOPUP_COPY.bankOff);
    // No pay button is invented while no payment channel is chosen.
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
    expect(longLines(container)).toEqual([]);
  });
});
