import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CampaignReviewPage from "@/app/c/[slug]/campaign-review/page";
import {
  FIRST_CAMPAIGN_REVIEW_PENDING,
  FIRST_CAMPAIGN_REVIEW_REJECTED,
  FIRST_CAMPAIGN_REVIEW_PATH,
  type FirstCampaignHold,
} from "@/lib/api/firstCampaign";

import { expectTextCount, renderClientPage } from "./harness";

/**
 * What a held client is actually shown — the half of `firstCampaignState` that lives
 * in the DOM.
 *
 * The predicate has its own file; this one asserts the two things the predicate cannot:
 * that a refusal renders the REVIEWER'S NOTE and not the server's composed `reason`
 * (which contains the note, so rendering both prints it twice), and that an
 * unrecognised rule still reaches the client as held.
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
});
