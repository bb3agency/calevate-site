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
