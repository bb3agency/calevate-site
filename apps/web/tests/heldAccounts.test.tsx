import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HeldAccountsPage from "@/app/admin/holds/page";
import { HOLDS_PATH, type HeldTenant } from "@/lib/api/holds";

import { problem, renderAdminPage } from "./harness";

/**
 * The ops hold queue, ranked fourth — an operator-facing screen, which caps the blast
 * radius, but the only screen that decides whether a held client is ever LOOKED AT.
 *
 * `holds.ts` already has a unit test for its predicates; this is the half that lives in
 * the DOM, and the three failures worth pinning are all failures of a row DISAPPEARING
 * rather than of a row being wrong:
 *
 * 1. **An unnameable rule must keep its account on the list.** `holdRule` fails VISIBLE
 *    on purpose — the opposite direction from `firstCampaignState`, which fails CLOSED
 *    — and the reason is that these are the only two ends of the same fact: the client
 *    is refused either way, so the console's job is to make sure a human is told. A row
 *    silently dropped for a rule added after this build shipped is an account that waits
 *    forever, and it is worst for the clients who never complain.
 * 2. **A failed read must not read as an empty queue.** "Nobody is waiting" is a claim
 *    about the world. An expired token is not evidence for it, and an operator told the
 *    queue is clear stops looking.
 * 3. **Empty is the GOOD state and must say so.** A queue rendering "no data" at its own
 *    success reads as a broken load, and the next thing an operator does with a broken
 *    load is reach for the curl this screen replaced.
 *
 * Hard rule 6 is asserted too: the payload carries no phone number and no reviewer
 * prose, and this screen must not acquire any.
 */

/**
 * Waits are expressed as an OFFSET from real now, not against a frozen clock.
 *
 * `vi.useFakeTimers()` is the obvious move and it deadlocks this file: React Query and
 * `findBy*` both resolve on timers, so freezing them means the queue never settles and
 * every test times out rather than failing. The screen reads `Date.now()` once per
 * render, a few milliseconds after these fixtures are built, and every assertion below
 * is on a whole-day boundary — so a real clock is stable here and a fake one is not.
 */
function daysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

function tenant(over: Partial<HeldTenant> = {}): HeldTenant {
  return {
    tenant_id: "0192f0aa-7777-7000-8000-000000000001",
    name: "Sri Traders",
    slug: "sri-traders",
    plan_tier: "growth",
    signed_up_at: daysAgo(1),
    holds: ["kyc_missing"],
    ...over,
  };
}

describe("the hold queue", () => {
  it("keeps an account held on a rule this build cannot name, and sends the operator somewhere real", async () => {
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: [tenant({ holds: ["a_gate_added_after_this_build"] })],
    });

    await screen.findByText("Sri Traders");
    // The row survives, and the rule is printed as itself — an operator who can read
    // the unfamiliar name can go and find out what it is.
    expect(container.textContent).toContain("a_gate_added_after_this_build");
    expect(container.textContent).toContain("This console does not know this rule");
    // No invented remedy: the fallback is the account itself, never a guessed screen.
    expect(screen.getByRole("link", { name: "Open the account" })).toBeDefined();
    expect(container.textContent).not.toContain("Nobody is waiting on us");
  });

  it("offers each remedy once, even when two rules share one screen", async () => {
    // `kyc_missing` and `kyc_not_verified` are separate FACTS (nothing filed at all
    // versus filed and not cleared) with the same remedy. Both are listed, because the
    // work behind them differs; the destination is offered once, because an operator
    // does not need the same page twice on one row.
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: [tenant({ holds: ["kyc_missing", "kyc_not_verified"] })],
    });

    await screen.findByText("Sri Traders");
    expect(container.textContent).toContain("Identity not filed");
    expect(container.textContent).toContain("Identity not verified");
    expect(screen.getAllByRole("link", { name: "Identity (KYC)" })).toHaveLength(1);
  });

  it("offers both remedies when an account is held by both gates", async () => {
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: [tenant({ holds: ["kyc_missing", "first_campaign_review_pending"] })],
    });

    await screen.findByText("Sri Traders");
    // A row that picked one gate would leave the other one's work invisible.
    expect(screen.getByRole("link", { name: "Identity (KYC)" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Review & release" })).toBeDefined();
    expect(container.textContent).not.toContain("Open the account");
  });

  it("refuses to call a failed read an empty queue", async () => {
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      // A real refusal, the way the API issues one. Not a malformed 200: that would
      // crash the render and prove nothing about the error branch.
      [HOLDS_PATH]: problem(401, {
        title: "Not authenticated",
        detail: "The admin token has expired.",
        status: 401,
      }),
    });

    await screen.findByText(/could not be read/);
    expect(container.textContent).toContain("we cannot say whether anyone is waiting");
    // The one sentence that must never appear on a failed load.
    expect(container.textContent).not.toContain("Nobody is waiting on us");
    // Nor the empty state's reassurance, which is the same claim in gentler words.
    expect(container.textContent).not.toContain("This list fills up on its own");
  });

  it("prints no headline count over a failed read", async () => {
    // The count sits ABOVE the table, so it is the one part of this screen that could
    // survive an error branch and go on asserting a number. "0 accounts waiting" over a
    // dead token is the queue's empty claim in its most trusted form — a figure — and it
    // is worse than the sentence, because a figure is what an operator scans for.
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: problem(503, { title: "Unavailable", status: 503, retryable: true }),
    });

    await screen.findByText(/could not be read/);
    expect(container.textContent).not.toContain("accounts waiting");
    expect(container.textContent).not.toContain("waiting over a week");
    expect(container.textContent).not.toContain("Longest wait");
  });

  it("says nobody is waiting, in words, when nobody is", async () => {
    const { container } = renderAdminPage(<HeldAccountsPage />, { [HOLDS_PATH]: [] });

    await screen.findByText("Nobody is waiting on us");
    expect(container.textContent).not.toContain("could not be read");
    // No headline count on an empty queue — "0 accounts waiting" beside "nobody is
    // waiting" is the same fact twice.
    expect(container.textContent).not.toContain("accounts waiting");
  });

  it("derives the longest wait from the rows rather than from their order", async () => {
    // The server orders oldest-first and this screen keeps that order. The headline is
    // computed anyway, so it cannot quietly become wrong if the order ever changes —
    // and the fixture is deliberately out of order to prove the computation happened.
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: [
        tenant({ tenant_id: "t-recent", name: "Recent Co", signed_up_at: daysAgo(1) }),
        tenant({ tenant_id: "t-old", name: "Old Co", signed_up_at: daysAgo(23) }),
      ],
    });

    await screen.findByText("Old Co");
    expect(container.textContent).toContain("2 accounts waiting");
    // 23 days, not the 1 day of the first row.
    expect(container.textContent).toContain("Longest wait: 23 days");
    expect(container.textContent).toContain("1 waiting over a week");
  });

  it("renders no phone number and no reviewer prose", async () => {
    // Hard rule 6 is a property of the payload — `admin/holds.py` drops the blockers'
    // `reason` strings because a rejection interpolates an operator's free text. This
    // screen must not fetch any of it back to fill the gap.
    const { container, calls } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: [tenant({ holds: ["first_campaign_review_rejected"] })],
    });

    await screen.findByText("Sri Traders");
    // One request, to the queue. A second one to a tenant's own screens would be this
    // page quietly widening what an ops list exposes.
    expect(calls.map((c) => c.path)).toEqual([HOLDS_PATH]);
    expect(container.textContent).toContain("First campaign refused");
    expect(container.textContent).not.toMatch(/\+?\d{10}/);
  });

  it("leaves the page title to the shell rather than printing a second one", async () => {
    // `app/admin/layout.tsx` derives the header from the SAME nav list the sidebar
    // renders, so a heading here would be the words "Held accounts" twice on one screen
    // and — the reason that matters — a second place for them to be renamed. The nav
    // entry is the one that decides where the link goes, so the page must not carry a
    // heading that can disagree with it.
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: [tenant()],
    });

    await screen.findByText("Sri Traders");
    expect(container.querySelector("h1")).toBeNull();
    expect(container.textContent).not.toContain("Held accounts");
  });

  it("is painted in design tokens, not in the shell palette it was written against", async () => {
    // The queue used to be `bg-slate-900` panels on a slate-950 admin shell, with its own
    // `rounded-xl` where the design language says `rounded-card`. Those are not style
    // preferences: a screen that hardcodes a colour is a screen the next brand change or
    // the dark-mode toggle silently leaves behind, which is the whole argument in
    // `globals.css`. Asserted by absence of the literals this migration removed rather
    // than by absence of `slate-` outright, because `NOTICE_TONES.neutral` legitimately
    // paints a fresh wait in slate and is shared with both realms.
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: [tenant()],
    });

    await screen.findByText("Sri Traders");
    const markup = container.innerHTML;
    expect(markup).not.toContain("rounded-xl");
    expect(markup).not.toContain("bg-slate-800");
    expect(markup).not.toContain("text-slate-400");
    expect(markup).not.toContain("text-slate-500");
    // And the tokens are actually reached, so this cannot pass by rendering nothing.
    expect(markup).toContain("border-line");
    expect(markup).toContain("text-ink-muted");
  });
});
