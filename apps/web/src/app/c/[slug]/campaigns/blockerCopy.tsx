import { type ReactNode } from "react";

import type { NoticeTone } from "@/components/ui";
import { type CampaignSummary, type PauseReason } from "@/lib/api/campaigns";

/**
 * WHAT THE GATE REFUSED, IN THE CLIENT'S WORDS, and where each refusal is fixed.
 *
 * Keyed by the compliance gate's own rule names. The same table serves the launch
 * checklist (`LaunchGate`) and a running campaign's "Not calling" notice
 * (`CampaignStateNotice`), because both render the server's `blockers` for one campaign.
 *
 * This table wins over the server's `reason` because the server writes for an operator
 * ("The agent must be published first.") and this says what the client does next and whose
 * desk it is on. A rule with no entry falls back to the server's sentence, which is terse
 * but true. `tests/campaignBlockerCopy.test.ts` fails on a key the gate no longer emits.
 *
 * Rules whose server sentence carries the state (KYC, the pledge, the consent
 * age) have no entry: rule-keyed copy would flatten the state the client needs.
 */
export type BlockerNote = { text: ReactNode; owner?: "calevate" | "client" };

export const BLOCKER_COPY: Record<string, BlockerNote> = {
  status: { text: "This campaign has already been launched." },
  agent_not_live: { text: "Your agent has to be published before it can make calls.", owner: "client" },
  agent_archived: {
    text: "The agent on this campaign has been archived. Restore it, or edit the campaign to use another agent.",
    owner: "client",
  },
  agent_missing: {
    text: "The agent on this campaign has been deleted. Edit the campaign to use another agent.",
    owner: "client",
  },
  agent_inbound_only: {
    text: "This agent only answers calls. Choose an agent that makes calls, or change this one in Agents.",
    owner: "client",
  },
  disclosure_missing: {
    text: "The agent needs its AI disclosure line, which every call carries.",
    owner: "client",
  },
  classification_not_campaignable: {
    text: "This campaign is filed as transactional, which a campaign can't be. Edit it and choose Service or Promotional.",
    owner: "client",
  },
  no_contacts: { text: "Add the people to call.", owner: "client" },
  all_contacts_dnc: {
    text: "Everyone on this list is on your do-not-call list, so nobody is left to call. Add other people.",
    owner: "client",
  },
  number_not_bound_to_agent: {
    text: "The number you chose is not set up on this campaign's agent, so calls would not show it. Give it to the agent on the Phone number page, or choose another number.",
    owner: "client",
  },
  number_not_on_carrier: {
    text: "The number you chose can't make calls through Calevate. Choose another number, or none to use your agent's own.",
    owner: "client",
  },
  number_inbound_only: {
    text: "The number you chose only receives calls. Choose a number that can make calls, or none to use your agent's own.",
    owner: "client",
  },
  trial_campaigns_unavailable: {
    text: "Campaigns open once you add credit. During your free trial you can try your agents with test calls from your dashboard.",
    owner: "client",
  },
  // An empty wallet silences answering as well as dialling (D-551), so this says both
  // halves and that one payment undoes both.
  no_credits: {
    text:
      "Your calling credit has run out, so outgoing calls have stopped and your agents " +
      "are no longer answering incoming ones. Add credit and both start again straight away.",
    owner: "client",
  },
  spend_cap: {
    text:
      "This account has spent up to its monthly limit, so outgoing calls have stopped " +
      "until the limit is raised or the month turns over. People ringing you still get through.",
    owner: "client",
  },
  platform_fee_overdue: {
    text: "The monthly platform fee is unpaid, so outgoing calls are paused. Pay it from Billing and calls start again.",
    owner: "client",
  },
  payment_dispute: {
    text: "A payment on this account is disputed, so outgoing calls are paused while we sort it out with you.",
    owner: "calevate",
  },
  agreements_not_accepted: {
    text: "Accept the updated terms before this campaign can call.",
    owner: "client",
  },
  account_suspended: {
    text: "This account is suspended, so it can't make calls. Contact us to find out why.",
    owner: "calevate",
  },
  account_closed: { text: "This account is closed, so it can't make calls.", owner: "calevate" },
  national_dnd_scrub_missing: {
    text: "Promotional calls go out only after the list is checked against the national do-not-disturb register that day, and that check has not been recorded for this list. A service campaign does not need it.",
    owner: "calevate",
  },
  national_dnd_scrub_expired: {
    text: "The check against the national do-not-disturb register lasts until midnight, and today's has not been recorded for this list yet.",
    owner: "calevate",
  },
  big_red_switch: {
    text: "Calevate has paused outgoing calls for everyone for a while. There is nothing for you to do; calls continue when it lifts.",
    owner: "calevate",
  },
  consent_provenance_missing: {
    text: "Tell us where this list came from and when these people agreed to be called. A list we can't trace to a consent can't be called.",
    owner: "client",
  },
  consent_source_refused: {
    text:
      "This list is recorded as bought or rented. Calevate doesn't call purchased lists, " +
      "because nobody on them agreed to hear from you. If that answer was a mistake, correct it below.",
    owner: "client",
  },
};

/** The consent rules answered by the form under the checklist (`ConsentProvenanceAnswer`). */
export const PROVENANCE_RULES = [
  "consent_provenance_missing",
  "consent_source_refused",
  "consent_too_old",
] as const;

/**
 * The same two consent rules, sized for a list row. Two entries, never one "needs
 * attention": a missing answer is a question the client can answer, a bought list is a
 * decision no answer clears.
 */
export const LIST_PROVENANCE_COPY: Record<
  NonNullable<CampaignSummary["consent_provenance_blocker"]>,
  { badge: string; tone: NoticeTone }
> = {
  consent_provenance_missing: { badge: "Needs where the list came from", tone: "warn" },
  consent_source_refused: { badge: "Can't be launched: bought list", tone: "stop" },
};

export const OWNER_BADGE: Record<NonNullable<BlockerNote["owner"]>, string> = {
  calevate: "We handle this",
  client: "You can fix this",
};

const KYC_BLOCKERS = [
  "kyc_missing",
  "kyc_not_verified",
  "kyc_digilocker_required",
  "outbound_pledge_missing",
  "outbound_pledge_outdated",
];

/**
 * Where a client goes to clear a rule whose fix lives on another screen. `at` turns a path
 * under `/c/{slug}` into a link that keeps a view-as session.
 */
export function blockerDestination(
  rule: string,
  at: (path: string) => string,
  campaignId: string,
): { href: string; label: string } | undefined {
  if (rule === "no_credits" || rule === "trial_campaigns_unavailable")
    return { href: at("/billing?tab=credits"), label: "Add credit" };
  if (rule === "spend_cap") return { href: at("/billing?tab=usage"), label: "See your monthly spending limit" };
  if (rule === "platform_fee_overdue") return { href: at("/billing"), label: "Go to Billing" };
  if (rule === "agreements_not_accepted") return { href: at("/agreements"), label: "Read and accept" };
  if (KYC_BLOCKERS.includes(rule)) return { href: at("/verify-business"), label: "Verify your business" };
  if (rule.startsWith("number_")) return { href: at("/phone-number"), label: "Go to Phone number" };
  if (rule === "agent_not_live" || rule === "agent_inbound_only" || rule === "disclosure_missing")
    return { href: at("/agents"), label: "Go to Agents" };
  if (rule === "agent_archived" || rule === "agent_missing" || rule === "classification_not_campaignable")
    return { href: at(`/campaigns/${campaignId}/edit`), label: "Edit the campaign" };
  return undefined;
}

/**
 * Why a paused campaign is paused, one line each (`ProgressOut.pause_reason`). Every
 * automatic pause names itself; a person's pause is the plain word.
 */
export const PAUSE_COPY: Record<PauseReason, { title: string; text: string }> = {
  person: { title: "Paused", text: "Someone on your account paused it. Resume to carry on where it stopped." },
  maintenance: {
    title: "Paused for maintenance",
    text: "Calevate paused calls while it carries out planned work. It resumes by itself when the work ends.",
  },
  healer: {
    title: "Paused while we fix a problem",
    text: "We found a problem with calling and paused this campaign while we fix it. It resumes by itself once it is fixed.",
  },
  complaint_spike: {
    title: "Paused: too many people asked not to be called",
    text: "Read what they said below, then confirm you have reviewed it. Resume works after that.",
  },
  out_of_credit: {
    title: "Paused: out of credit",
    text: "It resumes by itself as soon as you add credit.",
  },
  spend_cap: {
    title: "Paused: monthly spending limit reached",
    text: "Raise the limit, or wait for the new month, then resume it.",
  },
};
