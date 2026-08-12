"use client";

/**
 * The first-campaign hold, as the client sees it (BRD §245, FLOWS §2, D-34;
 * `apps/api/compliance/first_campaign.py`, `first_campaign_routes.py`).
 *
 * Calevate reads the first campaign of every self-serve account before it dials. The
 * gate shipped in `d07d4fc` with `GET /v1/compliance/first-campaign-review` and no
 * screen, so a client's launch was refused and nothing on their side said a human was
 * involved. This module is the shared half of that screen and of the campaigns panel
 * that links to it.
 *
 * Four properties of the API this module KEEPS rather than smooths over:
 *
 * - **The hold is on the ACCOUNT, not on a campaign.** `first_campaign_hold_blocker`
 *   asks one question per tenant, so while it stands *every* campaign is refused, and
 *   once released *no* campaign is refused on this rule again. Nothing here is keyed by
 *   campaign id, and the copy that renders from it says so — a client who believes each
 *   campaign needs a review will not build a second one.
 * - **Absence is the held state.** There is no `pending` row and no request path: a
 *   tenant nobody has reviewed has no row at all, and the route turns that into
 *   `held: true` with a null `status` and a 200. So `held` is the fact, `status` is only
 *   ever the record of a decision that HAS been made, and no caller may read a null
 *   `status` as "nothing to see".
 * - **`held` is the SERVER's predicate, never re-derived here.** The route calls the
 *   same `first_campaign_hold_blocker` the launch preview and the dispatch tick call, so
 *   this screen cannot tell a client they are clear while the launch button disagrees.
 *   Same doctrine as `is_verified` in `kyc.ts` and `messageable` in
 *   `messagingConsent.ts`.
 * - **The client can read and cannot release.** The only write is
 *   `POST /v1/admin/tenants/{tenant_id}/first-campaign-review` (`admin:tenants`,
 *   audited, admin realm). There is deliberately no mutation in this module, so no
 *   screen built on it can render a control whose only outcome is a 403 — the rule the
 *   closed-signup page and `/verification` already follow.
 *
 * `org:read` is not in `MUTATING_PERMISSIONS`, so everything here stays usable inside a
 * D-22 read-only "view as client" session — which is the session a support person is in
 * at exactly the moment this account is the thing being discussed.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The tenant's own state. Every field but `held` is genuinely nullable. */
export type FirstCampaignHold = Schemas["FirstCampaignHoldOut"];

/** One path string for the one endpoint. */
export const FIRST_CAMPAIGN_REVIEW_PATH = "/v1/compliance/first-campaign-review";

/**
 * The launch gate's own names for this hold (`compliance/service.py`).
 *
 * Exported so the campaigns launch panel can recognise its blockers and offer the
 * destination, WITHOUT writing rule-keyed copy for them — the same decision that screen
 * already made for `kyc_missing` / `kyc_not_verified`, and for the same reason: the
 * server's `reason` interpolates the state (the rejection carries the reviewer's own
 * words), so copy keyed on the rule name alone would flatten "we will look" and "we
 * looked and said no" into one sentence and lose the half that decides what to do next.
 *
 * The names themselves never reach the DOM. They are the gate's vocabulary.
 */
export const FIRST_CAMPAIGN_REVIEW_PENDING = "first_campaign_review_pending";
export const FIRST_CAMPAIGN_REVIEW_REJECTED = "first_campaign_review_rejected";
export const FIRST_CAMPAIGN_BLOCKERS: readonly string[] = [
  FIRST_CAMPAIGN_REVIEW_PENDING,
  FIRST_CAMPAIGN_REVIEW_REJECTED,
];

/** `first_campaign_reviews.status` when a human released the account. */
const APPROVED = "approved";

/**
 * The five states a screen can be in, named once.
 *
 * Split this finely because each one ends somewhere different, and merging any two
 * sends a client to the wrong place:
 *
 * - `pending` — nobody has looked yet. Nothing for the client to do but wait; the whole
 *   point of the screen is that waiting is a state, not a fault.
 * - `rejected` — a person looked and refused. There is a reason and a next move, and it
 *   is not "wait".
 * - `held_unknown` — held on a rule this build has never heard of. Render the server's
 *   own `reason` and invent no next action: a future rule described with today's
 *   "we will get to it shortly" would be a confident lie.
 * - `released` — a human cleared this account. Worth saying explicitly, because the
 *   thing a client most needs to know is that it will not happen to their next campaign.
 * - `never_applied` — not held, and no decision on file. Managed accounts, which the
 *   gate exempts by tier (`SELF_SERVE_TIERS`): their identity was verified by a person
 *   before we bought their number. NOT the same as `released`, and not the same as
 *   `pending` either — reading a null `status` as "waiting" would tell a managed client
 *   their campaigns are held when they are not.
 */
export type FirstCampaignState =
  | "pending"
  | "rejected"
  | "held_unknown"
  | "released"
  | "never_applied";

/**
 * Which state this response describes — one predicate, so two screens cannot disagree.
 *
 * `held` decides first and alone. An unrecognised `rule` therefore stays HELD rather
 * than falling through to a cleared state: this build not knowing a rule's name is not
 * evidence that the account may dial, and failing closed here matches the API, where
 * `read_first_campaign_review` returns "not reviewed" for a read that finds nothing.
 */
export function firstCampaignState(hold: FirstCampaignHold): FirstCampaignState {
  if (!hold.held) return hold.status === APPROVED ? "released" : "never_applied";
  if (hold.rule === FIRST_CAMPAIGN_REVIEW_REJECTED) return "rejected";
  if (hold.rule === FIRST_CAMPAIGN_REVIEW_PENDING) return "pending";
  return "held_unknown";
}

/**
 * The operator's decision — the admin-realm write, shaped here and SENT from `admin.ts`.
 *
 * Same split as `kyc.ts`: the vocabulary and the pre-flight checks live beside the type
 * they describe, and the call that carries an admin session is built in the one module
 * that builds admin sessions. There is deliberately no mutation hook in this file, so
 * nothing that imports it can render a control the client realm would be refused.
 */
export type FirstCampaignDecisionIn = Schemas["FirstCampaignDecisionIn"];
export type FirstCampaignDecisionOut = Schemas["FirstCampaignDecisionOut"];
export type FirstCampaignDecision = FirstCampaignDecisionIn["decision"];

/** The API's own cap on the note (`FirstCampaignDecisionIn.note`, `max_length=2000`). */
export const DECISION_NOTE_MAX = 2000;
/** The DATABASE's floor: `ck` `length(btrim(decision_note)) >= 3` (c4d9e18a72b6). */
export const DECISION_NOTE_MIN = 3;

export interface DecisionCopy {
  /** What the operator is choosing, in the form. */
  label: string;
  /** What it does to the account — the consequence, not the verb. */
  effect: string;
  /** What the note is FOR under this decision, said where it is typed. */
  noteLabel: string;
  noteHint: string;
}

/**
 * The two decisions, keyed off the generated union so a third one cannot be added
 * server-side without this file failing to compile.
 *
 * The halves that matter are the ones an operator gets wrong from the verb alone:
 * `approved` is not "this campaign is fine", it releases the ACCOUNT and no campaign of
 * theirs is held on this rule again; `rejected` is not a deletion, it keeps the account
 * held and shows the client the note verbatim on `/c/[slug]/campaign-review`.
 */
export const DECISION_COPY: Record<FirstCampaignDecision, DecisionCopy> = {
  approved: {
    label: "Release the account",
    effect:
      "Campaign calling opens, and this rule never holds another of their campaigns. " +
      "The other gates — identity, DLT template, number, wallet — are untouched.",
    noteLabel: "What you read",
    noteHint:
      "For the audit record: the contact list and where it came from, the script, and " +
      "the disclosure line. This is the answer to “why was this account released”, " +
      "asked after a reversal has overwritten the row — so write it for a stranger.",
  },
  rejected: {
    label: "Refuse — keep the account held",
    effect:
      "Campaigns stay blocked and the client is shown your note. Nothing is deleted: " +
      "they fix what you name, and a reviewer looks again.",
    noteLabel: "What the client will read",
    noteHint:
      "Goes to the client VERBATIM on their own campaign-review screen. Write it to " +
      "them, not about them: what was wrong, and what to change so the next reviewer " +
      "can release it.",
  },
};

/**
 * Why this decision cannot be recorded yet, or `null` when it can.
 *
 * A PREVIEW of the refusal, never the enforcement — the doctrine `recordBlockReason`
 * already follows on the KYC form. Behind it stand the route, which pre-empts a short
 * note with `first_campaign_review_note_required` problem+json, and
 * `decision_says_what_was_reviewed`, which refuses the row underneath that. The point of
 * asking here is that an operator finds out before the round-trip, with the field named.
 */
export function decisionBlockReason(body: FirstCampaignDecisionIn): string | null {
  const note = body.note.trim();
  if (note.length < DECISION_NOTE_MIN) {
    return body.decision === "rejected"
      ? "A refusal has to say what was wrong — it is what the client is shown, and nothing else explains the block."
      : "A release has to record what was reviewed, or nobody can account for it afterwards.";
  }
  if (note.length > DECISION_NOTE_MAX) {
    return `The note is ${note.length} characters; the API accepts ${DECISION_NOTE_MAX}.`;
  }
  return null;
}

/**
 * The draft as the API wants it: trimmed, with no campaign sent as `null`.
 *
 * `null` here does NOT clear the evidence. `record_first_campaign_decision` COALESCEs
 * `reviewed_campaign_id` against what is stored, precisely so a later reversal that
 * names no campaign cannot erase the record of what the first reviewer read.
 */
export function toDecisionBody(body: FirstCampaignDecisionIn): FirstCampaignDecisionIn {
  return {
    decision: body.decision,
    note: body.note.trim(),
    reviewed_campaign_id: body.reviewed_campaign_id ?? null,
  };
}

/**
 * This account's own hold state — client realm, `org:read`, non-mutating.
 *
 * No `refetchInterval`, for the reason `useKycRecord` states: the answer changes when a
 * person at Calevate decides something, which is minutes-to-days, not seconds, and a
 * client sitting on a blocked screen refreshing it is the expected behaviour. TanStack
 * Query v5 leaves `refetchOnWindowFocus` at `true` by default
 * (https://tanstack.com/query/v5/docs/framework/react/guides/important-defaults), and
 * that covers the case that actually matters — the client coming back to the tab after
 * we emailed to say it had cleared. Our QueryClient's 10s `staleTime` (app/providers.tsx)
 * keeps that from firing on every tab switch.
 *
 * Keyed by org slug, like every other client-realm query, so a D-22 operator switching
 * accounts never reads the previous tenant's answer out of the cache.
 */
export function useFirstCampaignHold(session: Session): UseQueryResult<FirstCampaignHold> {
  return useQuery({
    queryKey: ["first-campaign-review", session.orgSlug],
    queryFn: () => apiRequest<FirstCampaignHold>(session, FIRST_CAMPAIGN_REVIEW_PATH),
  });
}
