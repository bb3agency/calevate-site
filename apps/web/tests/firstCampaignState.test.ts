import { describe, expect, it } from "vitest";

import {
  FIRST_CAMPAIGN_REVIEW_PENDING,
  FIRST_CAMPAIGN_REVIEW_REJECTED,
  firstCampaignState,
  type FirstCampaignHold,
} from "@/lib/api/firstCampaign";

/**
 * `firstCampaignState` FAILS CLOSED, and this file is the reason that stays true.
 *
 * The predicate decides whether a client is told their campaigns are held. Every state
 * it can return is a legal `FirstCampaignState`, so the type checker signs off on all
 * of them equally — including the two that would tell a held account it is clear. What
 * is actually load-bearing is the DIRECTION of the fallbacks, and only a test can hold
 * a direction still.
 */

/** A held-with-no-decision row, the shape the route returns for an unreviewed tenant. */
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

describe("firstCampaignState", () => {
  it("reads a held account with an unrecognised rule as HELD, not as cleared", () => {
    // The one that matters. A rule name shipped by a future API is not evidence that
    // this account may dial; a build that has never heard of it must still refuse.
    const state = firstCampaignState(hold({ rule: "some_gate_invented_next_quarter" }));

    expect(state).toBe("held_unknown");
    expect(state).not.toBe("released");
    expect(state).not.toBe("never_applied");
  });

  it("stays held when the rule is null, which the schema permits", () => {
    expect(firstCampaignState(hold({ rule: null }))).toBe("held_unknown");
  });

  it("lets `held` beat `status`, so an approval that has been reversed still holds", () => {
    // `status` is the record of a decision; `held` is the gate's live answer. A
    // reversal writes a new row while the old `approved` is still on the response, and
    // keying on `status` here would render green for an account the dispatcher refuses.
    expect(firstCampaignState(hold({ status: "approved", rule: FIRST_CAMPAIGN_REVIEW_REJECTED })))
      .toBe("rejected");
  });

  it("names the two rules the gate actually emits", () => {
    expect(firstCampaignState(hold({ rule: FIRST_CAMPAIGN_REVIEW_PENDING }))).toBe("pending");
    expect(firstCampaignState(hold({ rule: FIRST_CAMPAIGN_REVIEW_REJECTED }))).toBe("rejected");
  });

  it("separates a released account from one the rule never applied to", () => {
    // Both are `held: false` with nothing blocking them, and they are different
    // sentences on screen: a managed account must not be told it was "released", and a
    // self-serve account that was released must not be told the check never applied.
    const released = hold({ held: false, rule: null, reason: null, status: "approved" });
    const managed = hold({ held: false, rule: null, reason: null, status: null });

    expect(firstCampaignState(released)).toBe("released");
    expect(firstCampaignState(managed)).toBe("never_applied");
  });

  it("does not resurrect a stale rejection once the account is no longer held", () => {
    // `held: false` with `status: "rejected"` is a reversal in flight. The gate says
    // clear, so the screen says clear — showing the old refusal's copy would hand a
    // client a reason for a block that no longer exists.
    expect(firstCampaignState(hold({ held: false, status: "rejected" }))).toBe("never_applied");
  });
});
