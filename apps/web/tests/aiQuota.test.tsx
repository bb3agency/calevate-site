import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AiAssistPage from "@/app/c/[slug]/ai-assist/page";
import type { AiQuota } from "@/lib/api/aiQuota";
import type { Me } from "@/lib/api/client";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage, stillLoading } from "./harness";

/**
 * AI help: the allowance panel and the money dialog (D-127 — G-3, G-4, G-5).
 *
 * What this file exists to pin, in the order it would hurt to get wrong:
 *
 * 1. **Nothing is charged until a person accepts.** The button OPENS a dialog; it does
 *    not spend. No request reaches `/extra` until the accept button inside the dialog is
 *    pressed, and "Not now" leaves the wallet alone. That is G-5 in one assertion, and
 *    it is asserted on the NETWORK rather than on the screen, because a screen can look
 *    right while a request has already gone.
 * 2. **The dialog names the figure the SERVER sent**, as digits, and the same digits are
 *    echoed back in the body. A browser that formatted, parsed or re-derived the amount
 *    would be the money bug hard rule 7 is about, one step from the wallet.
 * 3. **§52.** Loading is a skeleton, failure is a refusal, and neither is a number: a
 *    screen about an allowance must never invent one, and a failed read must not render
 *    an allowance of zero — which reads as "you have none left" and is a lie in the
 *    expensive direction.
 * 4. **The offer is the server's decision.** `extra_available` gates the button and
 *    `extra_unavailable_reason` supplies the sentence; the browser never re-derives
 *    "are they at their ceiling" from three numbers.
 * 5. **The permission gate** — `billing:read` to see it at all, `org:manage` to spend —
 *    is a refusal with a reason rather than a 403 after a click.
 * 6. **The dialog is reachable by keyboard and named for a screen reader**, swept by axe
 *    while OPEN, which the page sweep in `a11y.test.tsx` cannot do.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["billing:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "self_serve" },
} as unknown as Me;

const STAFF: Me = { ...ME, permissions: ["calls:read"] } as unknown as Me;
const OWNER_NO_MANAGE: Me = { ...ME, permissions: ["billing:read"] } as unknown as Me;

function quota(over: Partial<AiQuota> = {}): AiQuota {
  return {
    month: "2026-08",
    plan_tier: "self_serve",
    state: "within",
    included_inr: "100.00",
    used_inr: "41.70",
    allowance_inr: "100.00",
    remaining_inr: "58.30",
    requests_used: 82,
    // Producible by the SERVER at today's price: ₹100 included ÷ the ₹0.75 nominal
    // is 133, and ₹58.30 remaining is 77. These were 200/116 while the nominal was
    // ₹0.50, and a fixture no server can answer with is a wrong number with a
    // fixture's authority.
    requests_included: 133,
    requests_remaining: 77,
    extra_purchased_inr: null,
    extra_block_inr: "500.00",
    extra_block_requests: 666,
    extra_available: false,
    extra_unavailable_reason: "not_at_ceiling",
    ...over,
  };
}

const AT_CEILING = quota({
  state: "ceiling_reached",
  used_inr: "100.00",
  remaining_inr: "0.00",
  requests_used: 214,
  requests_remaining: 0,
  extra_available: true,
  extra_unavailable_reason: null,
});

describe("the allowance panel", () => {
  it("shows both units, with the count labelled as an estimate", async () => {
    const { container } = await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": quota(),
    });

    // Awaited on the anchor first, so a wrong figure fails on the assertion that
    // explains itself rather than on a "could not find the text" timeout.
    await screen.findByText("How AI help is billed");
    // The count an owner plans around, and the word that keeps it honest.
    expect(screen.getByText("82")).toBeTruthy();
    expect(screen.getByText(/of about 133 this month/)).toBeTruthy();
    // The rupee figures as the SERVER's digits, grouped and never parsed — read off the
    // whole screen because the allowance legitimately appears twice (the tile and the
    // table), and `getByText` would fail on the duplication rather than on the digits.
    expect(container.textContent).toContain("₹58.30");
    expect(container.textContent).toContain("₹100.00");
    expect(container.textContent).toContain("₹41.70");
    // What a `Number()` on the way past would have produced.
    expect(container.textContent).not.toContain("41.7 ");
    expect(container.textContent).not.toContain("58.299");
  });

  it("is a skeleton while the read is in flight, never a figure", async () => {
    const { container } = await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": stillLoading(),
    });

    expect(container.querySelector(".animate-pulse")).toBeTruthy();
    // §52: not a zero, not an empty state, and not the sentence about a ceiling.
    expect(screen.queryByText(/of about/)).toBeNull();
    expect(screen.queryByText(/₹/)).toBeNull();
  });

  it("refuses rather than reporting an allowance it could not read", async () => {
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": problem(503, {
        title: "Service unavailable",
        detail: "The billing service is not answering.",
      }),
    });

    await screen.findByText("The billing service is not answering.");
    // A failed read that rendered ₹0.00 would say "you have none left" — the lie in the
    // expensive direction.
    expect(screen.queryByText(/of about/)).toBeNull();
    expect(screen.queryByText("₹0.00")).toBeNull();
  });

  it("is limited to the account owner, with the reason", async () => {
    const { calls } = await renderClientPage(<AiAssistPage />, {
      "/v1/me": STAFF,
      // The READ still goes out: hooks cannot be conditional, so the query is declared
      // before `/v1/me` has answered — the same shape (and the same comment) the usage
      // panel carries. What must never happen is the WRITE, and that is asserted.
      "/v1/billing/ai-quota": quota(),
    });

    await screen.findByText(/limited to the account owner/);
    expect(screen.queryByRole("button", { name: /what more AI help costs/i })).toBeNull();
    expect(calls.some((call) => call.path.includes("/ai-quota/extra"))).toBe(false);
  });
});

describe("at the ceiling", () => {
  it("says the feature has stopped and that calls are unaffected", async () => {
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": AT_CEILING,
    });

    await screen.findByText(/used this month's included AI help/i);
    expect(screen.getByText(/calls, campaigns and leads — carries on/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /what more AI help costs/i })).toBeTruthy();
  });

  it("offers nothing and explains why when the server says the block is unavailable", async () => {
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": quota({
        state: "ceiling_reached",
        plan_tier: "managed",
        extra_available: false,
        extra_unavailable_reason: "not_prepaid",
      }),
    });

    await screen.findByText(/arranged with your account manager/);
    expect(screen.queryByRole("button", { name: /what more AI help costs/i })).toBeNull();
  });

  it("says the month is nearly over rather than offering a block that expires with it", async () => {
    // `month_ending` is the server refusing to sell the last hour of an IST month: the
    // block does not carry over, so ₹500 for ten minutes is arithmetically the same
    // bargain the screen describes and not the same bargain at all. The refusal exists
    // on the POST (`ai_extra_month_ending`); this is it said BEFORE the click, which is
    // the whole reason `extra_unavailable_reason` is published at all.
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": quota({
        state: "ceiling_reached",
        extra_available: false,
        extra_unavailable_reason: "month_ending",
      }),
    });

    await screen.findByText(/This month is nearly over/);
    expect(screen.getByText(/comes back within the hour/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /what more AI help costs/i })).toBeNull();
  });

  it("disables the offer for a person who cannot spend, with the reason beside it", async () => {
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": OWNER_NO_MANAGE,
      "/v1/billing/ai-quota": AT_CEILING,
    });

    const button = await screen.findByRole("button", { name: /what more AI help costs/i });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/Only an account owner can add more AI help/)).toBeTruthy();
  });

  it("says the month is finished, with no second offer, once the block is spent", async () => {
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": quota({
        state: "exhausted",
        used_inr: "620.00",
        allowance_inr: "600.00",
        remaining_inr: "0.00",
        extra_purchased_inr: "500.00",
        extra_available: false,
        extra_unavailable_reason: "already_purchased",
      }),
    });

    await screen.findByText(/This month's AI help is finished/);
    expect(screen.queryByRole("button", { name: /what more AI help costs/i })).toBeNull();
  });

  it("says the platform paused it, and that nothing was charged", async () => {
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": quota({ state: "platform_paused" }),
    });

    await screen.findByText(/AI help is paused right now/);
    expect(screen.getByText(/nothing has been charged/i)).toBeTruthy();
  });
});

describe("the money dialog (G-5)", () => {
  it("opens without spending anything, and cancelling still spends nothing", async () => {
    const { calls } = await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": AT_CEILING,
    });

    const offer = await screen.findByRole("button", { name: /what more AI help costs/i });
    await act(async () => {
      fireEvent.click(offer);
    });

    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    // THE assertion this whole file is for: opening the dialog is not a purchase.
    expect(calls.some((call) => call.path.includes("/ai-quota/extra"))).toBe(false);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.some((call) => call.path.includes("/ai-quota/extra"))).toBe(false);
  });

  it("names the exact figure, what it buys, and that nothing has been charged yet", async () => {
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": AT_CEILING,
    });
    const offer = await screen.findByRole("button", { name: /what more AI help costs/i });
    await act(async () => {
      fireEvent.click(offer);
    });

    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("₹500.00");
    expect(dialog.textContent).toContain("about 666 more uses");
    expect(dialog.textContent).toContain("not refunded and does not carry into next month");
    expect(dialog.textContent).toContain("Nothing has been charged yet.");
    // The accept button quotes the amount too, so the last thing a person reads before
    // pressing it is the number.
    expect(screen.getByRole("button", { name: "Add ₹500.00" })).toBeTruthy();
  });

  it("sends the server's own digits back, untouched, only on accept", async () => {
    const bought = quota({
      state: "within",
      used_inr: "100.00",
      allowance_inr: "600.00",
      remaining_inr: "500.00",
      extra_purchased_inr: "500.00",
      extra_available: false,
      extra_unavailable_reason: "already_purchased",
    });
    const { calls } = await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": AT_CEILING,
      "POST /v1/billing/ai-quota/extra": bought,
    });

    const offer = await screen.findByRole("button", { name: /what more AI help costs/i });
    await act(async () => {
      fireEvent.click(offer);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add ₹500.00" }));
    });

    const post = calls.find((call) => call.path.includes("/ai-quota/extra"));
    expect(post).toBeTruthy();
    // A STRING, exactly as the server sent it. `500` or `500.0` would mean the browser
    // parsed a rupee amount, and the server compares this for equality.
    expect(JSON.parse(post!.body ?? "{}")).toEqual({ accept_amount_inr: "500.00" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps the refusal inside the dialog when the charge fails", async () => {
    await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": AT_CEILING,
      "POST /v1/billing/ai-quota/extra": problem(422, {
        title: "Request rejected by a business rule",
        detail: "This account does not have enough credit for that.",
        remediation: "Top up the credit balance and try again.",
      }),
    });

    const offer = await screen.findByRole("button", { name: /what more AI help costs/i });
    await act(async () => {
      fireEvent.click(offer);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add ₹500.00" }));
    });

    // Closing the dialog to show this elsewhere would leave a person unsure whether the
    // money moved — which is the one thing this screen must never be ambiguous about.
    const refusal = await screen.findByText("This account does not have enough credit for that.");
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(refusal)).toBe(true);
    expect(dialog.textContent).toContain("Top up the credit balance and try again.");
  });

  it("is reachable and named for a screen reader while it is open", async () => {
    const { container } = await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": AT_CEILING,
    });
    const offer = await screen.findByRole("button", { name: /what more AI help costs/i });
    await act(async () => {
      fireEvent.click(offer);
    });

    const dialog = screen.getByRole("dialog");
    // An accessible NAME, not just a heading somewhere inside it: axe's `aria-dialog-name`
    // is exactly this, and a dialog a screen reader announces as "dialog" is one nobody
    // can decide from.
    expect(dialog.getAttribute("aria-labelledby")).toBe("ai-extra-title");
    expect(document.getElementById("ai-extra-title")?.textContent).toContain(
      "Add more AI help this month",
    );
    expect(document.activeElement).toBe(dialog);

    await expectNoA11yViolations(container, "c/[slug]/ai-assist (dialog open)");
  });

  it("cancels on Escape without spending", async () => {
    const { calls } = await renderClientPage(<AiAssistPage />, {
      "/v1/me": ME,
      "/v1/billing/ai-quota": AT_CEILING,
    });
    const offer = await screen.findByRole("button", { name: /what more AI help costs/i });
    await act(async () => {
      fireEvent.click(offer);
    });
    await act(async () => {
      // On the DOCUMENT, which is where the handler lives — a person reaching for
      // Escape has not necessarily kept focus inside the panel.
      fireEvent.keyDown(document, { key: "Escape" });
    });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.some((call) => call.path.includes("/ai-quota/extra"))).toBe(false);
  });
});
