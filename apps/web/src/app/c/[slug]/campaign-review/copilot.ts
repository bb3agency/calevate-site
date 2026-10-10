"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import { firstCampaignState, type FirstCampaignHold } from "@/lib/api/firstCampaign";
import { formatISTStamp } from "@/components/ui";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

export function useCampaignReviewCopilot(hold: UseQueryResult<FirstCampaignHold>): void {
  /*
   * WHERE THIS ACCOUNT STANDS, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * Above the §52 branches, because a hook cannot be conditional — and the `state` fact
   * distinguishes the loaded screen from the refusal, which on THIS screen is the whole
   * point: a blank page here reads as "nothing is holding your campaigns", and an
   * assistant that repeated that from a failed read would make the same claim out loud.
   *
   * `firstCampaignState` is the same predicate the box below renders from, not a second
   * test — `held` decides, never `status`, and a rule name this build does not recognise
   * stays held. THE REVIEWER'S NOTE IS NOT SENT: it is a human's sentence about this
   * business, written for them, and the screen already puts it in front of the reader.
   */
  useCopilotSurface({
    route: "/c/{slug}/campaign-review",
    title: "Campaign review",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: hold.data
          ? "the review status below has loaded"
          : hold.error
            ? "the review status failed to load — this is NOT evidence that nothing is held"
            : "still loading",
      },
      ...(hold.data
        ? [
            {
              key: "verdict",
              label: "Where this account stands on the first-campaign review",
              value: firstCampaignState(hold.data),
            },
            {
              key: "held",
              label: "Are outgoing campaign calls held?",
              value: hold.data.held ? "yes" : "no",
            },
            { key: "rule", label: "Which rule applied", value: hold.data.rule ?? "none" },
            { key: "status", label: "Review status", value: hold.data.status ?? "nobody has reviewed it" },
            {
              key: "decided_at",
              label: "When it was decided (IST)",
              value: formatISTStamp(hold.data.decided_at, "not decided"),
            },
            {
              key: "reviewed_campaign_id",
              label: "Campaign id under review",
              value: hold.data.reviewed_campaign_id ?? "none",
            },
            {
              key: "has_reviewer_note",
              label: "Is there a reviewer's note on screen?",
              value: hold.data.decision_note ? "yes — the reader can see it; it is not sent to the assistant" : "no",
            },
          ]
        : []),
    ],
    apply: noFill,
  });
}
