import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CampaignReviewPage from "@/app/c/[slug]/campaign-review/page";
import {
  FIRST_CAMPAIGN_REVIEW_PENDING,
  FIRST_CAMPAIGN_REVIEW_REJECTED,
  FIRST_CAMPAIGN_REVIEW_PATH,
  type FirstCampaignHold,
} from "@/lib/api/firstCampaign";

import { expectTextCount, problem, renderClientPage } from "./harness";

/**
 * What a held client is actually shown — the half of `firstCampaignState` that lives
 * in the DOM.
 *
 * The predicate has its own file; this one asserts what the predicate cannot: that a
 * refusal renders the REVIEWER'S NOTE and not the server's composed `reason` (which
 * contains the note, so rendering both prints it twice), that an unrecognised rule still
 * reaches the client as held, and — the two added with the design pass — that a request
 * which never landed produces a refusal rather than a verdict, and that the page has
 * nothing to press.
 *
 * The last one is the load-bearing absence on this screen. The only write is
 * `POST /v1/admin/tenants/{id}/first-campaign-review` (`admin:tenants`, admin realm,
 * audited), because the whole control exists for accounts we have never met — an account
 * that could release itself would be marking the gate green on a review nobody performed.
 * A control here would be a 403 dressed as a fault, which is the failure mode this
 * mitigation exists to avoid creating.
 */

const NOTE = "The contact list has no consent evidence. Send us where it came from.";

/** How `first_campaign_rejected_reason` composes it: our sentence plus the note. */
const COMPOSED = `The first campaign on this account was reviewed and refused: ${NOTE}`;

function hold(over: Partial<FirstCampaignHold> = {}): FirstCampaignHold {
  return {
    held: true,
    rule: FIRST_CAMPAIGN_REVIEW_PENDING,
    reason: "Your first campaign is waiting for a compliance review.",
    status: null,
    decision_note: null,
    decided_at: null,
    reviewed_campaign_id: null,
    ...over,
  };
}

async function renderWith(data: FirstCampaignHold) {
  return await renderClientPage(<CampaignReviewPage />, { [FIRST_CAMPAIGN_REVIEW_PATH]: data });
}

describe("campaign review screen", () => {
  it("prints the reviewer's note ONCE and never the composed reason around it", async () => {
    const { container } = await renderWith(
      hold({
        rule: FIRST_CAMPAIGN_REVIEW_REJECTED,
        status: "rejected",
        decision_note: NOTE,
        reason: COMPOSED,
        decided_at: "2026-08-01T09:00:00Z",
      }),
    );

    await screen.findByText(/did not release it for campaign calling/);

    // The note reaches the client — a refusal they cannot read is a ticket nobody can
    // close — and reaches them exactly once. The composed reason carries the note
    // inside it, so rendering both is how the note gets printed twice.
    expectTextCount(container, NOTE, 1);
    expect(container.textContent).not.toContain("was reviewed and refused:");
  });

  it("falls back to the composed reason only when there is no note", async () => {
    // The schema says a rejection always carries a note (`ck` on the row). This is the
    // case that cannot happen — and if it ever does, an unexplained refusal is worse
    // than a clumsy sentence, so the fallback is the server's own words, not silence.
    const { container } = await renderWith(
      hold({ rule: FIRST_CAMPAIGN_REVIEW_REJECTED, status: "rejected", reason: COMPOSED }),
    );

    await screen.findByText(/did not release it for campaign calling/);
    expectTextCount(container, NOTE, 1);
  });

  it("tells a client held on an unknown rule that they are held", async () => {
    // The fail-closed default, seen from the client's side. A future gate name must not
    // render as "cleared for campaign calling", and must not get invented next steps.
    const { container } = await renderWith(
      hold({ rule: "a_gate_this_build_predates", reason: "Held pending a compliance check." }),
    );

    await screen.findByText("Your campaigns are held for review.");
    expect(container.textContent).toContain("Held pending a compliance check.");
    expect(container.textContent).not.toContain("cleared for campaign calling");
  });

  it("does not show a refusal box to an account that is merely waiting", async () => {
    const { container } = await renderWith(hold());

    await screen.findByText("Your campaigns are with our compliance team.");
    expect(container.textContent).not.toContain("What the reviewer said:");
  });

  it("keeps a released account clear even though its status row still exists", async () => {
    const { container } = await renderWith(
      hold({ held: false, rule: null, reason: null, status: "approved", decision_note: NOTE }),
    );

    await screen.findByText("Your account is cleared for campaign calling.");
    // The release note is an AUDIT record of what an operator read, not client copy —
    // it names our internal checks and must not leak onto the client's screen.
    expect(container.textContent).not.toContain(NOTE);
  });

  it("reassures every held state that inbound calling is unaffected", async () => {
    // D-38: the receptionist is the headline product, and "have my phones stopped?" is
    // the fear a blocked client arrives with.
    const { container } = await renderWith(hold());
    await waitFor(() =>
      expect(container.textContent).toContain("Calls coming IN are unaffected"),
    );
  });

  it("does not tell a managed account it is in a queue", async () => {
    // `never_applied` is not `pending`: this account was set up by a person here, and
    // nothing of theirs is held. Rendering the hold cards under that headline would have
    // a client waiting for a release that is never coming, and building no campaigns.
    const { container } = await renderWith(
      hold({ held: false, rule: null, reason: null, status: null }),
    );

    await screen.findByText("This review does not apply to your account.");
    expect(screen.queryByText("What is being held, and for how long")).toBeNull();
    expect(screen.queryByText("What you can do meanwhile")).toBeNull();
    expect(container.textContent).not.toContain("every campaign on the account is held");
    expect(container.textContent).not.toContain("with our compliance team");
  });

  it("refuses to state a verdict when the request did not land", async () => {
    // Every verdict on this screen is actionable, and each of them is wrong for somebody:
    // "cleared" sends a held client to a launch button that will refuse them, "held"
    // sends a clear one to their account manager. On a failed read the screen says only
    // that it could not find out — and it must not go blank either, because a blank page
    // on the screen a refused client just opened reads as "nothing is holding you".
    const { container } = await renderClientPage(<CampaignReviewPage />, {
      [FIRST_CAMPAIGN_REVIEW_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "We could not read the review queue.",
        retryable: true,
      }),
    });

    const alert = await screen.findByRole("alert");
    expect(container.textContent).not.toContain("cleared for campaign calling");
    expect(container.textContent).not.toContain("does not apply to your account");
    expect(container.textContent).not.toContain("with our compliance team");
    expect(container.textContent).not.toContain("held for review");
    // Not a dead end: the screen has to pass `onRetry` for this to exist.
    expect(within(alert).getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("offers no control that would release the account", async () => {
    // Asserted as "no button at all" rather than as "no button called Release": naming
    // them individually is how the next one arrives unnoticed. The screen says out loud
    // that the absence is deliberate, so the sentence is pinned with it — a client who
    // cannot find the control otherwise opens a ticket to be told there is none.
    const { container } = await renderWith(hold());

    await screen.findByText("Your campaigns are with our compliance team.");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(container.querySelectorAll("form")).toHaveLength(0);
    expect(container.textContent).toContain(
      "There is deliberately no control on this page that releases your own account",
    );
  });
});
