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
 * `text` is the one line shown by default and must be TRUE ON ITS OWN: a fact the client
 * would act on differently (inbound stopping with outbound, a bought list never being
 * called) stays in it. `why` is the longer reason, shown only behind "Why?" (founder,
 * 28 Oct 2026: short lines and buttons, explanations behind a tap).
 *
 * Rules whose server sentence carries the state (KYC, the pledge, the consent
 * age) have no entry: rule-keyed copy would flatten the state the client needs.
 */
export type BlockerNote = { text: string; why?: string; owner?: "calevate" | "client" };

export const BLOCKER_COPY: Record<string, BlockerNote> = {
  status: { text: "This campaign has already started." },
  agent_not_live: { text: "Publish your agent first.", owner: "client" },
  agent_archived: {
    text: "This campaign's agent is archived.",
    why: "Restore the agent in Agents, or edit the campaign to use another agent.",
    owner: "client",
  },
  agent_missing: {
    text: "This campaign's agent was deleted.",
    why: "Edit the campaign and choose another agent.",
    owner: "client",
  },
  agent_inbound_only: {
    text: "This agent only answers calls.",
    why: "Choose an agent that makes calls, or change this one in Agents.",
    owner: "client",
  },
  disclosure_missing: {
    text: "Your agent needs its AI disclosure line.",
    why: "Every call carries a line saying the caller is speaking to an AI.",
    owner: "client",
  },
  classification_not_campaignable: {
    text: "Choose Service or Promotional for this campaign.",
    why: "It is filed as transactional, which a campaign can't be.",
    owner: "client",
  },
  no_contacts: { text: "Add the people to call.", owner: "client" },
  all_contacts_dnc: {
    text: "Everyone here is on your do-not-call list.",
    why: "Nobody is left to call. Add other people.",
    owner: "client",
  },
  number_not_bound_to_agent: {
    text: "Your number isn't set up on this agent.",
    why: "Give the number to the agent on the Phone number page, or choose another number.",
    owner: "client",
  },
  number_not_on_carrier: {
    text: "Your chosen number can't make calls.",
    why: "Choose another number, or none to use your agent's own.",
    owner: "client",
  },
  number_inbound_only: {
    text: "Your chosen number only receives calls.",
    why: "Choose a number that can make calls, or none to use your agent's own.",
    owner: "client",
  },
  trial_campaigns_unavailable: {
    text: "Add credit to use campaigns.",
    why: "During your free trial, try your agents with test calls from your dashboard.",
    owner: "client",
  },
  // An empty wallet silences answering as well as dialling (D-551), so the short line says
  // both halves; that one payment undoes both is in "Why?".
  no_credits: {
    text: "Out of credit. Calls in and out have stopped.",
    why: "Your agents are not answering incoming calls either. Add credit and both start again straight away.",
    owner: "client",
  },
  spend_cap: {
    text: "Monthly spending limit reached. Calls to you still work.",
    why: "Outgoing calls stop until the limit is raised or the month turns over.",
    owner: "client",
  },
  platform_fee_overdue: {
    text: "Platform fee unpaid. Outgoing calls paused.",
    why: "Pay it from Billing and calls start again.",
    owner: "client",
  },
  payment_dispute: {
    text: "A payment is disputed. Outgoing calls paused.",
    why: "We are sorting it out with you.",
    owner: "calevate",
  },
  agreements_not_accepted: { text: "Accept the updated terms.", owner: "client" },
  account_suspended: {
    text: "This account is suspended. It can't make calls.",
    why: "Contact us to find out why.",
    owner: "calevate",
  },
  account_closed: { text: "This account is closed. It can't make calls.", owner: "calevate" },
  national_dnd_scrub_missing: {
    text: "Waiting for today's national do-not-disturb check.",
    why:
      "Promotional calls go out only after the list is checked against the national " +
      "do-not-disturb register that day. A service campaign does not need it.",
    owner: "calevate",
  },
  national_dnd_scrub_expired: {
    text: "Today's national do-not-disturb check is due.",
    why: "The check lasts until midnight, and today's has not been recorded for this list yet.",
    owner: "calevate",
  },
  big_red_switch: {
    text: "Outgoing calls are paused for everyone. Nothing to do.",
    why: "Calevate paused outgoing calls for a while. Calls continue when it lifts.",
    owner: "calevate",
  },
  consent_provenance_missing: {
    text: "Say where this list came from.",
    why: "A list we can't trace to people agreeing to be called can't be called.",
    owner: "client",
  },
  consent_source_refused: {
    text: "We don't call bought or rented lists.",
    why: "Nobody on them agreed to hear from you. If that answer was a mistake, correct it below.",
    owner: "client",
  },
  // D-943: an offer in a service call makes the whole call promotional.
  script_promotional: {
    text: "The agent's script talks about offers.",
    why: "One offer or sales line makes every call promotional, and we place service calls only. Take it out, or let Pip rewrite it.",
    owner: "client",
  },
};

/** What "Ask Pip to rewrite it" writes in Pip's ask box. Names the agent, never a person. */
export function rewritePrompt(agentName: string): string {
  return (
    `Check the script of my agent "${agentName}" for offers and selling, then rewrite those ` +
    "lines as a service call about what the person asked for."
  );
}

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
 * under `/c/{slug}` into a link that keeps a view-as session. Labels are button words:
 * a verb and the thing, nothing more.
 */
export function blockerDestination(
  rule: string,
  at: (path: string) => string,
  campaignId: string,
): { href: string; label: string } | undefined {
  if (rule === "no_credits" || rule === "trial_campaigns_unavailable")
    return { href: at("/billing?tab=credits"), label: "Add credit" };
  if (rule === "spend_cap") return { href: at("/billing?tab=usage"), label: "Raise spending limit" };
  if (rule === "platform_fee_overdue") return { href: at("/billing"), label: "Pay in Billing" };
  if (rule === "agreements_not_accepted") return { href: at("/agreements"), label: "Read and accept" };
  if (KYC_BLOCKERS.includes(rule)) return { href: at("/verify-business"), label: "Verify your business" };
  if (rule.startsWith("number_")) return { href: at("/phone-number"), label: "Open Phone number" };
  if (rule === "agent_not_live" || rule === "agent_inbound_only" || rule === "disclosure_missing")
    return { href: at("/agents"), label: "Open Agents" };
  if (rule === "agent_archived" || rule === "agent_missing" || rule === "classification_not_campaignable")
    return { href: at(`/campaigns/${campaignId}/edit`), label: "Edit campaign" };
  return undefined;
}

/**
 * A rule fixed on the campaign's own page rather than another screen: the checklist row
 * gets a button that opens or jumps to the control that clears it.
 */
export function blockerInPage(rule: string): "add-people" | "list-source" | "rewrite" | undefined {
  if (rule === "no_contacts" || rule === "all_contacts_dnc") return "add-people";
  if (rule === "script_promotional") return "rewrite";
  if ((PROVENANCE_RULES as readonly string[]).includes(rule)) return "list-source";
  return undefined;
}

/**
 * Why a paused campaign is paused, one line each (`ProgressOut.pause_reason`). Every
 * automatic pause names itself; a person's pause is the plain word.
 */
export const PAUSE_COPY: Record<PauseReason, { title: string; text: string }> = {
  person: { title: "Paused", text: "Resume to carry on where it stopped." },
  maintenance: {
    title: "Paused for maintenance",
    text: "Planned work. It resumes by itself.",
  },
  healer: {
    title: "Paused while we fix a problem",
    text: "It resumes by itself once fixed.",
  },
  complaint_spike: {
    title: "Paused: too many people asked not to be called",
    text: "Read what they said, then confirm below.",
  },
  out_of_credit: {
    title: "Paused: out of credit",
    text: "It resumes by itself when you add credit.",
  },
  spend_cap: {
    title: "Paused: monthly spending limit reached",
    text: "Raise the limit, or wait for next month.",
  },
};
