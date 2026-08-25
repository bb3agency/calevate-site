"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  CloudOff,
  ListPlus,
  Pause,
  PhoneCall,
  PhoneOff,
  Play,
  Plus,
  Repeat,
  Rocket,
  CalendarClock,
  Users,
} from "lucide-react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  StatTile,
  TermGloss,
  formatCount,
  formatIST,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  consentCollectedAt,
  parseContactCsv,
  useAddContacts,
  useCampaignNumbers,
  useCampaignProgress,
  useCampaigns,
  useCreateCampaign,
  useDeclareConsentProvenance,
  useDltTemplates,
  useLaunchCampaign,
  useLaunchCheck,
  usePauseCampaign,
  recurrenceUntil,
  scheduleStartAt,
  useScheduleCampaign,
  useSetRecurrence,
  useUnscheduleCampaign,
  type CampaignRecurrence,
  type CampaignSummary,
  type Classification,
  type ConsentSource,
} from "@/lib/api/campaigns";
import { FIRST_CAMPAIGN_BLOCKERS } from "@/lib/api/firstCampaign";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { canDialOut, isAssignable } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";

import { LaunchConfirm } from "./LaunchConfirm";

/**
 * Outbound campaigns (FLOWS §5, SURFACES §2b).
 *
 * The screen is built around one rule: **the launch button is disabled with its
 * reasons on screen, not after a click.** The API's `/launch-check` returns named
 * blockers precisely so this page can list them as a to-do; a generic "launch failed"
 * toast would send the client to support instead of to the fix. Every blocker below
 * is a real TRAI/DLT requirement, so the copy explains rather than apologises.
 *
 * The client never sees a bypass, because there isn't one: `POST /launch` re-runs the
 * identical gate server-side (hard rule 5).
 *
 * **The SCHEDULE and REPEAT forms are the one place that rule does not extend to, and the
 * exception is the SERVER's rather than this screen's.** Arming a schedule runs no
 * compliance gate — the gate runs when it FIRES, on every occurrence, which is what makes
 * a registration that lapses in week three refuse week three (D-79,
 * `campaigns/scheduling.py` decision 3). So both forms render on both verdicts, with the
 * blocker list still above them and the fire-time consequence stated beside them. The
 * reasoning, and the reason hiding either half would be worse than the defect it replaced,
 * is at their call site.
 *
 * ## What the design pass changed, and what it deliberately did not
 *
 * Restyled to the console's design language (globals.css tokens, `Card`, lucide icons as
 * affordances) with the gate's BEHAVIOUR untouched: `ready` is still the server's verdict
 * and never `blockers.length === 0`, `PLATFORM_BLOCKER` is still split out before
 * anything is counted, and every blocker still carries its `owner`. Three things that
 * were wrong underneath the old styling are fixed here rather than carried across, all
 * of them the same defect — a number or an assertion this screen made up:
 *
 * - **The four tiles rendered `0` for a campaign we could not read.** `contacts`,
 *   `connected` and `dnc_blocked` all defaulted (`?? 0`, `?? parsed.length`) and the row
 *   was unconditional, so a failed or in-flight `GET /v1/campaigns/{id}` painted
 *   "Contacts 0 · Connected 0 · Not called 0" over a campaign that might be mid-dial.
 *   Loading is a `Skeleton` now, failure is the `ProblemNotice` above and nothing else,
 *   and the tiles render only from a response that arrived.
 * - **"Start another campaign" carried the previous campaign's consent declaration into
 *   the next form.** See the reset handler: that is an audited statement about a
 *   SPECIFIC list, and pre-filling it is exactly what the `consentSource` initialiser
 *   below says must never happen.
 * - **The launch control could sit dead under "Everything checks out." with its reason
 *   a screenful away.** `leads:dispatch` is the permission `POST /launch` requires, and
 *   a `staff` user or an impersonating operator (D-22) does not hold it — so the control
 *   now carries the refusal itself, the way the leads Export button does.
 *
 * The screen renders no `<h1>`: the shell prints the page title from the nav list
 * (layout.tsx), and a second "Campaigns" beside it is a visible duplicate.
 */

/**
 * The screen's field and control styling, written once.
 *
 * Local constants rather than a fifth trip to `ui.tsx`: this is the only screen in the
 * console with a real FORM on it, so a `Field`/`PrimaryButton` primitive would be
 * generalised from one caller. They belong in `ui.tsx` the moment a second screen needs
 * them — which is a note for whoever builds `/agents`, not a reason to move them today.
 */

/**
 * A radio rendered as a card.
 *
 * Selection is a brand ring plus a tick, NOT a brand fill. `--brand-soft` has no dark
 * value by design (it is the medallion tint, and `ui.tsx` uses it with a fixed dark-green
 * foreground), so a filled card would need its own text colour in each theme to stay
 * readable — a two-colour pair that the next person to add an option will get wrong. A
 * ring changes nothing about the text.
 */
/*
 * The FOCUS ring, on the card rather than on the input.
 *
 * The `<input type="radio">` inside each of these cards is `sr-only`, which deletes the
 * browser's own focus indicator — WCAG 2.4.7 Focus Visible (AA), failure technique F78,
 * exactly. `has-[:focus-visible]` puts it back on the label that hides it, so a keyboard
 * user tabbing into the group can see where they are; `focus-visible` rather than `focus`
 * so a mouse click does not leave a ring behind. `ring-offset-2` separates it from
 * `CHOICE_ON`'s selection ring, so "focused" and "chosen" stay two readable states.
 * `tests/contrast.test.ts` guards this at the source, because axe cannot evaluate a focus
 * indicator and jsdom has no layout to evaluate one in.
 */
const CHOICE_CARD =
  "relative block cursor-pointer rounded-card border p-3 transition-colors " +
  "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app";
const CHOICE_ON = "border-brand ring-1 ring-brand bg-surface";
const CHOICE_OFF = "border-line bg-surface hover:border-ink-faint";

/**
 * A blocker in the client's words, plus WHOSE desk it lands on.
 *
 * `owner` exists because the DLT blockers are the first ones on this screen that the
 * client cannot act on at all. "Your DLT Principal Entity registration is not active"
 * reads like a to-do, so a client who is told only that will go looking for a setting
 * they do not have, then call support to be told we were already handling it. Naming
 * the desk turns a dead end into a wait with someone to ask.
 */
type BlockerNote = { text: ReactNode; owner?: "calevate" | "client" };

/**
 * WHY THIS TABLE STILL WINS OVER THE SERVER'S OWN `reason`, and what makes that safe.
 *
 * The objection is real: this is a second copy of a server rule, and the render below
 * prefers it (`note?.text ?? blocker.reason`). Two spellings of one fact is where drift
 * starts. Two fixes were on the table and only one of them is right here.
 *
 * REJECTED — invert the precedence, render `blocker.reason` and let this table only add
 * the owner badge. It trades a hypothetical drift for a certain regression, because
 * these sentences are not a paraphrase of the server's: they exist BECAUSE the server's
 * are wrong for this audience. `launch_blockers` writes for an operator reading an API
 * response — "The agent must be published first.", "Campaign is running, not draft." —
 * sentences that report system state rather than tell this client what to do next. The
 * three DLT-entity blockers are the sharpest case: the server says the
 * registration is not active, which reads like a to-do, and this table is the only place
 * that says WHOSE desk it is on. Making the server's sentence primary puts every one of
 * those back.
 *
 * CHOSEN — machine-check the KEY SET instead, because the key is the part that can go
 * stale silently. This table is not a copy of the server's sentence; it is a translation
 * keyed by the server's own identifier, and a translation only becomes a lie when the
 * thing it is keyed to is renamed, removed or split. `tests/campaignBlockerCopy.test.ts`
 * asserts every key here is still a rule the compliance gate emits, and fails naming the
 * key that is not. The reverse direction stays deliberately unchecked: a rule with no
 * copy falls through to `blocker.reason`, which is terse but true, and that fail-open is
 * the behaviour we want on the day the API grows a blocker this build has never seen.
 *
 * The END STATE is neither of those and needs no test at all — `BlockerOut.rule` typed
 * as a `Literal[...]` union in `campaigns/routes.py`, so `openapi.json` carries the enum
 * and this becomes `Record<Blocker["rule"], BlockerNote>` with `tsc` checking it. That is
 * exactly how `LIST_PROVENANCE_COPY` sixty lines below is already checked, and it is a
 * BACKEND change, so it is reported rather than made here.
 */
const BLOCKER_COPY: Record<string, BlockerNote> = {
  status: { text: "This campaign has already been launched." },
  agent_not_live: {
    text: "Your agent has to be published before it can make calls.",
  },
  disclosure_missing: {
    text: "The agent needs its AI disclosure line — required on every call.",
  },
  dlt_template_missing: {
    text: (
      <>
        Attach the{" "}
        <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss> voice template
        this campaign speaks under.
      </>
    ),
  },
  dlt_template_not_approved: {
    text: (
      <>
        The <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss> template is
        still with the registrar.
      </>
    ),
  },
  dlt_template_mismatch: {
    text: "The template's category doesn't match this campaign's.",
  },
  number_missing: { text: "Choose the number these calls will come from." },
  number_series_mismatch: {
    text: (
      <>
        Promotional calls need a{" "}
        <TermGloss term="140">India&apos;s marketing-call number range</TermGloss> number;
        service calls need a{" "}
        <TermGloss term="160">India&apos;s service-call number range</TermGloss> one.
      </>
    ),
  },
  no_contacts: { text: "Upload the contact list." },

  // The DLT entity registrations (SEC-COMP §3). Three separate registrations, none
  // implying another, and all three are OUR paperwork — an operator records them in
  // the admin console. The copy says the same thing the badge does, because a badge
  // alone is easy to miss and this is the difference between waiting and hunting.
  pe_registration_missing: {
    text: (
      <>
        Your business isn&apos;t registered with{" "}
        <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss> yet — that&apos;s
        the government register every business must be on before an automated call can go out in
        its name. We do this registration for you; ask your account manager where it&apos;s up
        to. Calls coming IN are unaffected and keep working.
      </>
    ),
    owner: "calevate",
  },
  pe_registration_not_active: {
    text: (
      <>
        Your business&apos;s{" "}
        <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss> registration
        isn&apos;t active — it&apos;s either still with the registrar or it has lapsed. Only an
        active registration may place campaign calls. We chase this with the registrar; your
        account manager can tell you where it stands. Calls coming IN are unaffected.
      </>
    ),
    owner: "calevate",
  },
  tm_link_not_active: {
    text: (
      <>
        Your <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss> registration
        hasn&apos;t authorised Calevate to call on your behalf yet. It&apos;s a one-time link
        between your business and us on the register, and we set it up — your account manager
        will confirm when it&apos;s live.
      </>
    ),
    owner: "calevate",
  },

  // Provenance — the one blocker on this list only the client can clear, because only
  // the client knows the answer. Both point at the form rendered directly below them.
  consent_provenance_missing: {
    text:
      "Tell us where this list came from and when these people agreed to be called. " +
      "Only you can answer that, and a list we can't trace to a consent can't be dialled. " +
      "Record it below and this clears straight away.",
    owner: "client",
  },
  consent_source_refused: {
    text:
      "This list is recorded as bought or rented. Calevate doesn't dial purchased lists — " +
      "nobody on them agreed to hear from you, so there's no consent behind the call. This " +
      "campaign can't launch. If that answer was a mistake, correct it below; otherwise build " +
      "the list from your own customers and enquiries.",
    owner: "client",
  },
};

/**
 * The same two rules again, sized for a LIST ROW rather than a launch panel.
 *
 * Two separate entries, never one "needs attention" — the values mean different things
 * and end differently, and the list is where a client decides what to open next:
 *
 *  - `consent_provenance_missing` is a question with an answer. The row is one click
 *    from the form that clears it, and nothing about the campaign is wrong yet.
 *  - `consent_source_refused` is a decision. The list is bought or rented, Calevate
 *    will not dial it, and no amount of opening the campaign changes that — the only
 *    thing behind the click is correcting a mis-answer, so that is what the link says.
 *    Sending a client to "fix" it would be a lie; letting them think the first message
 *    applies would waste a trip.
 *
 * Keyed by the API's own rule names so the list, `/launch-check` and the panel below
 * are all describing one fact. The names themselves stay out of the DOM.
 */
const LIST_PROVENANCE_COPY: Record<
  NonNullable<CampaignSummary["consent_provenance_blocker"]>,
  { badge: string; badgeClass: string; text: string; action: string }
> = {
  consent_provenance_missing: {
    badge: "Needs one answer",
    badgeClass:
      "border-amber-300 text-amber-700 dark:border-amber-700/60 dark:text-amber-400",
    text:
      "This campaign can't go out until you say where the list came from and when those " +
      "people agreed to be called. Your contacts stay as they are.",
    action: "Answer it",
  },
  consent_source_refused: {
    badge: "Can't be launched",
    badgeClass:
      "border-rose-300 text-rose-700 dark:border-rose-800 dark:text-rose-400",
    text:
      "This list is recorded as bought or rented, and Calevate doesn't dial purchased " +
      "lists — nobody on them agreed to hear from you. The campaign stays here but can't " +
      "be launched.",
    action: "If that was a mistake, correct it",
  },
};

const OWNER_BADGE: Record<NonNullable<BlockerNote["owner"]>, string> = {
  calevate: "We handle this",
  client: "You can fix this",
};

/**
 * The one blocker that is not this client's list at all.
 *
 * `tm_registration_missing` means CALEVATE's own telemarketer registration is not live.
 * It is platform-wide: every tenant's campaign is refused at the same instant, for a
 * reason no business can act on, cannot escalate to their account manager as their
 * case, and will not clear by doing anything on this screen. It is our outage.
 *
 * It is DELIBERATELY absent from `BLOCKER_COPY` above, and that absence is the
 * mechanism: the list below renders one `<li>` per entry in that map, so a future edit
 * cannot accidentally turn this into a bullet in a to-do list beside "upload your
 * contacts". The page pulls it out of the blocker list before rendering and gives it
 * its own notice — a different shape, no owner badge, no position in the count.
 *
 * "We handle this" would be the wrong badge too: the PE blockers that carry it are a
 * queue an account manager can report progress on. This one is not paperwork with a
 * desk attached — it is the product being unable to make outbound calls at all.
 */
const PLATFORM_BLOCKER = "tm_registration_missing";

/**
 * The two blockers that have a whole screen behind them.
 *
 * They are deliberately NOT in `BLOCKER_COPY`. `compliance.service.kyc_blocker` returns
 * a reason that already names the state the record is in — "nothing on file" and
 * "submitted / in review / rejected / expired" send the client to different places, and
 * the API interpolates the status precisely so the difference survives. Writing copy
 * keyed on the rule name alone would flatten the two back into one sentence and lose
 * the part that decides what to do next, so the server's reason is what renders.
 *
 * What was missing is not words, it is a destination: the reason explains the refusal
 * and then leaves the client on a campaign screen with nothing to press. This adds the
 * link, and nothing else.
 */
const KYC_BLOCKERS = ["kyc_missing", "kyc_not_verified"];

/**
 * The first-campaign hold — same treatment, same reasoning, one screen behind it.
 *
 * `FIRST_CAMPAIGN_BLOCKERS` is the API's own pair of rule names, imported rather than
 * retyped. Like the KYC pair above, they are deliberately absent from `BLOCKER_COPY`:
 * `first_campaign_hold_blocker` returns a reason that already distinguishes "nobody has
 * looked yet" from "a reviewer looked and said no", and the second interpolates the
 * reviewer's own words. Rule-keyed copy would flatten the two into one sentence and
 * throw away the half that decides whether the client waits or acts.
 *
 * What is added is the destination and ONE fact the server's reason cannot carry in a
 * bullet: this hold is on the account, so it is not a step every campaign will repeat.
 * A client who believes otherwise stops building campaigns, which is the outcome the
 * whole mitigation is trying not to cause.
 */
const FIRST_CAMPAIGN_REVIEW_LABEL = "Why your first campaign is being reviewed";

function PlatformOutageNotice({ reason }: { reason: string }) {
  return (
    <div
      role="status"
      // Deliberately QUIET — `bg-app` inside a `bg-surface` card, the same recessed
      // treatment `RestrictionNote` uses. Rose would paint our own outage as this
      // client's fault, and amber would put it in the same visual class as the to-do
      // bullets it was pulled out of.
      className="flex gap-3 rounded-card border border-line bg-app p-4 text-sm"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-black/5 text-ink-muted dark:bg-white/10">
        <CloudOff aria-hidden className="h-4 w-4" />
      </span>
      <div className="min-w-0">
        <p className="font-semibold text-ink">
          Outbound calling is paused across Calevate — nothing for you to do
          here.
        </p>
        <p className="mt-1 text-ink-muted">
          Our own{" "}
          <TermGloss term="telemarketer (TM)">
            the company registered to place calls on a business&apos;s behalf
          </TermGloss>{" "}
          registration with the{" "}
          <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss> registrar is
          not live at the moment, so no campaign on Calevate can launch — not just yours. This
          is on us and there is no setting on your side that changes it. We are on it, and this
          campaign will be launchable again the moment it is restored. Calls coming IN are
          unaffected and keep being answered.
        </p>
        {/* The server's own sentence, kept but demoted: it is the precise reason support
            and the audit trail will quote, and it should not be the headline a business
            owner reads first. */}
        <p className="mt-2 text-xs text-ink-faint">{reason}</p>
      </div>
    </div>
  );
}

/**
 * The five answers, in the client's language.
 *
 * `purchased_list` sits in this list at the same size, in the same order it appears in
 * the API's enum, with the same plain description as the other four and NO warning
 * attached. That is deliberate, and it is the whole reason the option exists: the
 * policy is that a purchased list is refused IN WRITING, and a refusal can only be
 * written against an answer somebody actually gave. Labelling it "not allowed" here,
 * greying it out, or hiding it behind a disclosure would not stop anyone dialling a
 * bought list — it would only teach them to pick the nearest acceptable-sounding
 * neighbour ("existing customers"), which loses the refusal AND corrupts the record we
 * would need if a complaint ever landed. So the form asks a neutral question, and the
 * consequence arrives from the server, by name, rendered as its own blocker above.
 */
const CONSENT_SOURCES: { value: ConsentSource; label: string; hint: string }[] =
  [
    {
      value: "existing_customer",
      label: "Our existing customers",
      hint: "People who have bought from us or hold an account with us.",
    },
    {
      value: "inbound_enquiry",
      label: "People who contacted us",
      hint: "Enquiries by phone, message or walk-in that we're following up.",
    },
    {
      value: "web_form_optin",
      label: "Signed up on our website",
      hint: "Filled in a form online and agreed to be contacted.",
    },
    {
      value: "offline_form_optin",
      label: "Signed up on paper",
      hint: "A form, register or slip filled in at our shop, office or an event.",
    },
    {
      value: "purchased_list",
      label: "Bought or rented list",
      hint: "Contacts supplied by a data vendor, broker or another business.",
    },
  ];

/**
 * Today, in the browser's own timezone, as a `<input type="date">` value.
 *
 * `toISOString().slice(0,10)` alone is a day early for half of every IST evening. Used
 * only as the picker's `max` — a soft affordance, not validation. The server is the
 * authority on "not in the future" and its refusal renders through ProblemNotice; this
 * just stops the calendar offering next month as if it were a sensible answer.
 */
function todayInputValue(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 10);
}

/**
 * The days of the week, in the server's own numbering (ISO: 1 = Monday).
 *
 * Not `Date.getDay()`'s numbering, which starts at Sunday = 0. One vocabulary from the
 * checkbox to the stored rule to the dispatch tick; a second one is an off-by-one that
 * dials on the wrong day, which on this product means calling strangers on a Sunday.
 */
const WEEKDAYS: { value: number; label: string; short: string }[] = [
  { value: 1, label: "Monday", short: "Mon" },
  { value: 2, label: "Tuesday", short: "Tue" },
  { value: 3, label: "Wednesday", short: "Wed" },
  { value: 4, label: "Thursday", short: "Thu" },
  { value: 5, label: "Friday", short: "Fri" },
  { value: 6, label: "Saturday", short: "Sat" },
  { value: 7, label: "Sunday", short: "Sun" },
];

/**
 * An occurrence in the words a client can check against their own calendar.
 *
 * `formatIST` (ui.tsx) gives "14 Aug, 10:00", which is right everywhere else on this
 * console and NOT enough here: the one thing a repeat has to survive is the client
 * asking "is that this Tuesday?". So the weekday is spelled out — "Tuesday 14 Aug, 10:00
 * IST" — and only for schedule times. A local helper rather than a second export from
 * `ui.tsx`, because the weekday matters exactly where a repeat rule is read and nowhere
 * else on the console.
 */
function formatOccurrence(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "long",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "every Tuesday and Friday at 10:00" — the rule, read back as a sentence. */
function describeRepeat(recurrence: CampaignRecurrence): string {
  const chosen = WEEKDAYS.filter((day) => recurrence.days.includes(day.value));
  if (chosen.length === WEEKDAYS.length) return `every day at ${recurrence.at}`;
  const names = chosen.map((day) => day.label);
  const listed =
    names.length <= 1
      ? (names[0] ?? "no day")
      : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  return `every ${listed} at ${recurrence.at}`;
}

/**
 * Why an occurrence did not run, in the client's words.
 *
 * `missed` is the only reason the server records today, and it is the one that most
 * needs explaining: a client who sees "we skipped Tuesday" and no reason assumes we
 * dropped their campaign. The truth — we would have dialled at the wrong time of day, so
 * we waited for the next slot — is both better and reassuring, and it is the promise
 * `campaigns/scheduling.py` decision 2 makes on their behalf.
 */
const SKIP_COPY: Record<string, string> = {
  missed: [
    "We could not start it close enough to the time you picked, so we waited for the",
    "next one rather than calling people at a different time of day.",
  ].join(" "),
};

/**
 * **The fire-time refusal, said in advance** — what a schedule will do about the blockers
 * this campaign has RIGHT NOW.
 *
 * The two forms this appears in are deliberately reachable with blockers outstanding: the
 * server runs NO compliance gate when a schedule is armed, only when it FIRES
 * (`campaigns/scheduling.py` decision 3, D-79), so a client waiting on the registrar can
 * legitimately put next Tuesday on a campaign that would not launch today.
 *
 * The cost of that reachability is real, and this is the payment. A client CAN arm a start
 * on a campaign that would dial nobody, and a screen that let them do it in silence would
 * have swapped a confusing form for a dangerous one — a schedule that looks armed and
 * produces a quiet nothing on Tuesday morning. `when` is the difference between the two
 * moments that silence would fall in, and both need saying:
 *
 * - `arming` — a form the client is filling in. The point to make is that setting a time is
 *   allowed and is not a promise.
 * - `armed` — a start or repeat already on the campaign, before the tick has tried it even
 *   once. Without this the campaign says "Starts Monday, 10:00 IST" and nothing else until
 *   the first attempt fails, which is the discovery-by-silence this note exists to prevent.
 *   (Once an attempt HAS failed, the schedule carries `last_blocked` and the cards say so
 *   from the server's own record instead — a stronger statement, so this one stands down.)
 *
 * `kind` is the consequence, and the two genuinely differ — they are the server's, not a
 * turn of phrase:
 *
 * - a ONE-TIME start is retried for `GRACE` (24h) and then given up on: the schedule is
 *   cleared and the campaign returns to draft (`scheduling._expire`);
 * - an OCCURRENCE of a repeat is retried only inside `RECURRENCE_CATCHUP` (1h) and is then
 *   abandoned rather than fired into a different time of day — the repeat itself survives
 *   and the next run is checked afresh (`scheduling._skip_occurrence`, decision 2).
 *
 * Every call site guards on the launch check having ANSWERED and answered "not ready". A
 * warning that is always on screen is a warning nobody reads, and one derived from a
 * verdict we do not have is the §52 defect itself.
 */
function FireTimeRefusal({
  kind,
  when,
}: {
  kind: "start" | "repeat";
  when: "arming" | "armed";
}) {
  return (
    <p className="flex gap-2.5 text-sm text-ink-muted">
      <CircleAlert
        aria-hidden
        className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
      />
      <span>
        As things stand{" "}
        {kind === "start"
          ? "this campaign would not start"
          : "the next run would not start"}
        .{" "}
        {when === "arming"
          ? "You can still set a time — the same check runs again at the moment it does, so anything you clear before then is enough. If the reasons above are still outstanding then, "
          : "The reasons are listed below. Clear them before the time comes and it goes ahead as planned; if they are still outstanding then, "}
        {kind === "start"
          ? "no calls go out, and after a day of trying the campaign goes back to draft."
          : "that run is skipped rather than dialled at a different time of day, and the repeat itself carries on."}
      </span>
    </p>
  );
}

const CLASSIFICATIONS: {
  value: Classification;
  label: string;
  hint: ReactNode;
}[] = [
  {
    value: "promotional",
    label: "Promotional",
    hint: (
      <>
        Offers and marketing — dials from a{" "}
        <TermGloss term="140">India&apos;s marketing-call number range</TermGloss> number
      </>
    ),
  },
  {
    value: "service",
    label: "Service",
    hint: (
      <>
        Updates to existing customers —{" "}
        <TermGloss term="160">India&apos;s service-call number range</TermGloss> or standard
      </>
    ),
  },
  {
    value: "transactional",
    label: "Transactional",
    hint: (
      <>
        Order and appointment updates —{" "}
        <TermGloss term="160">India&apos;s service-call number range</TermGloss> or standard
      </>
    ),
  },
];

export default function CampaignsPage() {
  const session = useClientSession();
  // In-realm links must carry the D-22 view-as marker; `href()` is the one place that
  // rule lives.
  const { href } = useClientRealm();
  const agents = useAgents(session);

  const numbers = useCampaignNumbers(session);
  const templates = useDltTemplates(session);
  const campaigns = useCampaigns(session);

  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [agentId, setAgentId] = useState("");
  const [name, setName] = useState("");
  const [classification, setClassification] =
    useState<Classification>("service");
  const [concurrency, setConcurrency] = useState(3);
  const [numberId, setNumberId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [csv, setCsv] = useState("");
  // Asked at creation, not deferred to the launch check: the client is holding the
  // list in their hand at this moment, which is the only moment they can answer
  // cheaply. Empty string, never a default source — there is no sensible default for
  // "where did these five thousand numbers come from", and a pre-selected one would
  // put an assertion nobody made into an audited record.
  const [consentSource, setConsentSource] = useState<ConsentSource | "">("");
  const [consentDate, setConsentDate] = useState("");
  // Off by default, and "off" means null — not 09:00-21:00 echoed back. The platform
  // window is enforced by the per-dial compliance gate whether or not a campaign
  // carries one of its own, so sending it as a campaign setting would misrepresent
  // a legal bound as something this form chose.
  const [restrictHours, setRestrictHours] = useState(false);
  const [windowStart, setWindowStart] = useState("10:00");
  const [windowEnd, setWindowEnd] = useState("18:00");

  /**
   * D-22 read-only, applied to the controls rather than discovered on click. All four
   * mutating steps on this screen — create, add contacts, launch, pause/resume — are
   * `leads:dispatch` (campaigns/routes.py), which is a MUTATING permission: `staff`
   * does not hold it, and an impersonating operator is refused it however senior they
   * are. The note is rendered once at the top rather than four times, because the
   * reason is the same one every time; the launch control is the single exception and
   * says why at its own call site. The server still refuses; every ProblemNotice below
   * stays.
   */
  const write = useWriteAccess(
    session,
    "leads:dispatch",
    "start or run campaigns",
  );
  /** The refusal as a control attribute, so a dead button explains itself on hover. */
  const refusal = write.allowed ? undefined : (write.reason ?? undefined);

  const create = useCreateCampaign(session);
  const addContacts = useAddContacts(session, campaignId);
  const check = useLaunchCheck(session, campaignId);
  const launch = useLaunchCampaign(session, campaignId);
  const progress = useCampaignProgress(session, campaignId);
  const setStatus = usePauseCampaign(session, campaignId);
  const schedule = useScheduleCampaign(session, campaignId);
  const unschedule = useUnscheduleCampaign(session, campaignId);
  const repeat = useSetRecurrence(session, campaignId);

  // Two fields, not one datetime-local: a date picker and a time picker are what a
  // phone renders usefully, and most of these clients are on one. Empty by default —
  // there is no sensible default start, and a pre-filled "tomorrow 10am" is a date
  // nobody chose sitting one click from dialling a list.
  const [startDate, setStartDate] = useState("");
  const [startTime, setStartTime] = useState("10:00");
  const startIso = scheduleStartAt(startDate, startTime);

  // The repeat form. Days empty by default and no day pre-ticked: "every Monday" is a
  // standing instruction to call strangers, and a default one is an instruction nobody
  // gave. The time defaults to 10:00 only because the control needs a value at all — it
  // is inside the calling window either way, which is the part the server enforces.
  const [repeatDays, setRepeatDays] = useState<number[]>([]);
  const [repeatTime, setRepeatTime] = useState("10:00");
  const [repeatEnds, setRepeatEnds] = useState("");
  const toggleRepeatDay = (day: number) =>
    setRepeatDays((days) =>
      days.includes(day)
        ? days.filter((value) => value !== day)
        : [...days, day].sort(),
    );

  const parsed = useMemo(() => parseContactCsv(csv), [csv]);
  // Both or neither, decided here so the two halves cannot be sent apart: the API
  // takes provenance as one nested object and refuses a half-filled one.
  const consentIso = consentCollectedAt(consentDate);
  const provenanceAnswered = Boolean(consentSource) && consentIso !== null;
  // Which of the two provenance blockers is on this campaign, if either — the answer
  // form is the same either way, but the question it asks is not ("record" vs
  // "correct"), and neither should appear when the launch check is clean.
  // Our outage is split off from the client's list BEFORE anything is rendered, so it
  // can never be counted, bulleted or badged alongside things this business can
  // actually do. See PLATFORM_BLOCKER.
  const allBlockers = check.data?.blockers ?? [];
  const platformOutage = allBlockers.find((b) => b.rule === PLATFORM_BLOCKER);
  const clientBlockers = allBlockers.filter((b) => b.rule !== PLATFORM_BLOCKER);
  const provenanceBlocker = clientBlockers.find(
    (b) =>
      b.rule === "consent_provenance_missing" ||
      b.rule === "consent_source_refused",
  )?.rule;
  const blockedOnKyc = clientBlockers.some((b) =>
    KYC_BLOCKERS.includes(b.rule),
  );
  const blockedOnFirstCampaign = clientBlockers.some((b) =>
    FIRST_CAMPAIGN_BLOCKERS.includes(b.rule),
  );
  /**
   * Which agent dials decides the script, the voice and the disclosure line, so the
   * choice is ALWAYS on screen — not only when there is more than one. A campaign that
   * silently bound `agents[0]` was a campaign whose caller nobody chose, and with the
   * agents console able to mint a second agent in a minute, "there is only one" stopped
   * being a safe assumption the moment the form rendered.
   *
   * ARCHIVED AGENTS ARE NOT OFFERED, and that is the server's rule rather than taste:
   * `lifecycle.ASSIGNABLE_STATUSES` refuses one outright, because no amount of waiting
   * makes a campaign bound to a retired agent launchable. Every other state IS offered —
   * a draft agent is a legitimate choice while its script is being written, and
   * `launch_blockers` refuses the LAUNCH with `agent_not_live` until it is published,
   * which is a wait a client can act on rather than a dead end.
   */
  const agentOptions = (agents.data ?? []).filter(isAssignable);
  const selectedAgentId = agentId || agentOptions[0]?.id || "";
  const selectedAgent = agentOptions.find((option) => option.id === selectedAgentId);
  /**
   * This account has no agent — as a FACT FROM THE SERVER, not as "the list is empty
   * right now". `agentOptions` is also empty while `/v1/agents` is in flight and after
   * it has FAILED, and the sentence below it used to gate ("your account manager builds
   * one before campaigns can run") is a claim about this business's setup, on the screen
   * where an owner decides whether their campaigns can run at all. Rendered over a 503
   * it sends them to their account manager for an agent they already have.
   *
   * `!agents.isLoading` was not enough: a settled-and-failed query is not loading.
   * Same spelling as `hasNoAgents` two screens away in `/c/<slug>/knowledge` — the
   * repo already solved this and a fourth spelling is where the drift starts.
   */
  const hasNoAgents = Boolean(agents.data) && agentOptions.length === 0;
  // Null, not "draft", until the server says: defaulting to draft renders the
  // contact-upload and launch cards over a campaign that is already running.
  const status = progress.data?.status ?? null;
  const counts = progress.data?.contacts ?? {};
  // The repeat, only ever from a response that ARRIVED. Undefined while the request is in
  // flight or after it failed, which is why nothing below defaults it to "no repeat":
  // telling a client their campaign does not repeat is a claim, and a 503 did not make it.
  const recurrence = progress.data?.recurrence ?? null;

  /**
   * Would this ALREADY-ARMED schedule be refused if it came due right now?
   *
   * The armed cards below used to say nothing about a refusal until the tick had tried
   * and failed at least once (`schedule_blocked_rules`), so between arming and the first
   * attempt a doomed schedule read as "Starts Monday, 10:00 IST" and nothing else. That
   * is the same discovery-by-silence the arming forms now avoid, one moment later.
   *
   * Three conditions, each load-bearing:
   *
   * - `status === "scheduled"` — the only status `due_schedules` reads. On a RUNNING
   *   campaign `launch_blockers` correctly reports its own `status` blocker ("already
   *   launched"), which is true and is NOT a statement about the next occurrence; a
   *   repeat card that read it as one would warn about a campaign that is dialling fine.
   * - `check.data !== undefined` — an unanswered launch check has no verdict, and a
   *   warning derived from one we do not have is §52's defect rather than its remedy.
   * - no `schedule_blocked_rules` — once the server has actually refused, its own record
   *   of WHICH rules refused is the stronger statement and says so in its own words.
   */
  const armedScheduleWouldRefuse =
    status === "scheduled" &&
    check.data !== undefined &&
    !check.data.ready &&
    (progress.data?.schedule_blocked_rules?.length ?? 0) === 0;

  /**
   * Back to the list, with the audited answer CLEARED.
   *
   * The bug this closes: `consentSource`/`consentDate` used to survive the reset, so the
   * create form re-opened with the previous campaign's declaration pre-selected and
   * "Create campaign" already live. A client clicking straight through would then have
   * stated, on the record, that a list they have not described yet came from the same
   * place on the same date as the last one — the exact "assertion nobody made" the
   * `consentSource` initialiser above forbids, written into a record whose whole purpose
   * is to answer a complaint later.
   *
   * The number, template, classification and concurrency deliberately DO survive: they
   * are settings the gate re-checks on every launch, not statements about a list, and a
   * client running a second campaign from the same number should not have to say so
   * twice.
   */
  const startAnother = () => {
    setCampaignId(null);
    setName("");
    setCsv("");
    setConsentSource("");
    setConsentDate("");
  };

  return (
    <div className="space-y-5 pb-12">
      <p className="max-w-2xl text-sm text-ink-muted">
        Call a list of people. Calls go out between 9am and 9pm, numbers on the
        do-not-call list are never dialled, and anyone who doesn&apos;t answer
        is tried again later.
      </p>

      <RestrictionNote reason={write.reason} />

      {campaigns.error && (
        <ProblemNotice
          error={campaigns.error}
          onRetry={() => campaigns.refetch()}
        />
      )}
      {/* THE THREE READS THAT FAILED IN SILENCE.
          `campaigns`, `progress`, `check`, `create` all surfaced their refusals; the
          three lists the create form is BUILT FROM did not, so each failure degraded
          into something the screen stated as fact. Agents: the empty-state sentence
          above (see `hasNoAgents`). Numbers and templates: two `<select>`s holding
          nothing but "Choose a number…" / "Choose a template…", a client concluding
          their account has neither, and no refusal anywhere on the page to contradict
          it. A picker that cannot be filled is a dead form, and a dead form needs the
          reason next to it — the same argument `/c/<slug>/knowledge` makes for its own
          agents notice. Retryable, because all three are plain GETs. */}
      {agents.error && (
        <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />
      )}
      {numbers.error && (
        <ProblemNotice
          error={numbers.error}
          onRetry={() => numbers.refetch()}
        />
      )}
      {templates.error && (
        <ProblemNotice
          error={templates.error}
          onRetry={() => templates.refetch()}
        />
      )}
      {progress.error && (
        <ProblemNotice
          error={progress.error}
          onRetry={() => progress.refetch()}
        />
      )}
      {addContacts.error && <ProblemNotice error={addContacts.error} />}
      {launch.error && <ProblemNotice error={launch.error} />}
      {setStatus.error && <ProblemNotice error={setStatus.error} />}
      {/* A refused schedule is a refusal, never a silently unchanged form: the server
          names the reason (a start in the past, one beyond the horizon, a campaign that
          has already launched) and the client can only act on it if it is on screen. */}
      {schedule.error && <ProblemNotice error={schedule.error} />}
      {unschedule.error && <ProblemNotice error={unschedule.error} />}
      {/* A refused repeat is a refusal with something to do about it: a time outside
          calling hours, no day chosen, an end date before the first run. All three are
          named by the server and none of them is guessable from a form that simply does
          nothing. */}
      {repeat.error && <ProblemNotice error={repeat.error} />}

      {/* A skeleton, not an empty list: "you have no campaigns" is a claim about this
          business, and the request had not answered yet. */}
      {!campaignId && campaigns.isLoading && (
        <Card title="Your campaigns">
          <Skeleton rows={3} />
        </Card>
      )}

      {/* The third state the skeleton above does not cover. `isLoading` is
          `isPending && isFetching`, so it is FALSE for a query TanStack has PAUSED rather
          than started — which is what it does while the browser is offline. A paused
          query also has `error === null`, so the notice at the top of this screen renders
          nothing, and the list card below is simply absent: a client with ten campaigns
          saw a screen offering to create their first. */}
      {!campaignId &&
        !campaigns.isLoading &&
        !campaigns.error &&
        !campaigns.data && (
          <Card title="Your campaigns">
            <ProblemNotice
              error={new Error("Your campaigns did not load.")}
              onRetry={() => campaigns.refetch()}
            />
          </Card>
        )}

      {!campaignId && (campaigns.data?.length ?? 0) > 0 && (
        <Card title="Your campaigns" bodyClassName="px-4 py-2 sm:px-6">
          {/* SYMPTOM this fixed: a draft built before the provenance rule existed is
              now blocked, and nothing on the landing view said so — the client saw a
              normal-looking draft, opened it, and met a refusal with no hint it was
              answerable. This used to be one general notice above the list, because the
              summary carried no consent field and the list genuinely could not tell
              WHICH drafts were affected. It can now: `consent_provenance_blocker` names
              the exact rule per row, so the warning moved onto the rows it is about and
              the rows it is not about say nothing. */}
          <ul className="divide-y divide-line">
            {(campaigns.data ?? []).map((campaign) => {
              const blocker = campaign.consent_provenance_blocker ?? null;
              // The worst-behaved of the copy tables, because `note` is tested for
              // TRUTH rather than for a property: `LIST_PROVENANCE_COPY["constructor"]`
              // is the `Object` function, which is truthy, so the row rendered a badge
              // with no text, a paragraph with no text, and a CLICKABLE BUTTON with no
              // label — an empty control on a compliance row. `lookup` returns
              // `undefined` for anything the table does not own (lib/lookup.ts).
              const note = lookup(LIST_PROVENANCE_COPY, blocker);
              return (
                <li key={campaign.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setCampaignId(campaign.id)}
                      className="text-sm font-semibold text-ink underline-offset-2 hover:underline"
                    >
                      {campaign.name}
                    </button>
                    <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs font-medium capitalize text-ink-muted dark:bg-white/10">
                      {campaign.status}
                    </span>
                    <span className="text-xs capitalize text-ink-faint">
                      {campaign.classification}
                    </span>
                    {/* The badge is the rule in the client's words. The enum name itself
                        is never rendered — it is the launch gate's vocabulary, not a
                        sentence anyone reading this list can act on. */}
                    {note && (
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${note.badgeClass}`}
                      >
                        {note.badge}
                      </span>
                    )}
                    <span className="ml-auto text-xs tabular-nums text-ink-faint">
                      {formatCount(campaign.connected)}/
                      {formatCount(campaign.contacts)} reached ·{" "}
                      {campaign.launched_at
                        ? formatIST(campaign.launched_at)
                        : "not launched"}
                    </span>
                  </div>
                  {note && (
                    <p className="mt-1 max-w-2xl text-xs text-ink-muted">
                      {note.text}{" "}
                      <button
                        type="button"
                        onClick={() => setCampaignId(campaign.id)}
                        className="font-semibold text-ink underline underline-offset-2"
                      >
                        {note.action}
                      </button>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      {!campaignId ? (
        <Card title="New campaign">
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault();
              if (!selectedAgentId) return;
              create.mutate(
                {
                  agent_id: selectedAgentId,
                  name,
                  classification,
                  concurrency,
                  number_id: numberId || null,
                  dlt_template_id: templateId || null,
                  calling_hours: restrictHours
                    ? { start: windowStart, end: windowEnd }
                    : null,
                  consent_provenance:
                    consentSource && consentIso
                      ? { source: consentSource, collected_at: consentIso }
                      : null,
                },
                { onSuccess: (data) => setCampaignId(data.id) },
              );
            }}
          >
            <label className="block max-w-sm">
              <span className={FIELD_LABEL}>Name</span>
              <input
                required
                minLength={2}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Diwali service reminder"
                className={FIELD}
              />
            </label>

            {/* Rendered whenever the server has ANSWERED with at least one assignable
                agent — never off a list that is empty because the read is in flight or
                failed, which is the same `Boolean(agents.data)` test `hasNoAgents` uses
                four lines up. */}
            {Boolean(agents.data) && agentOptions.length > 0 && (
              <label className="block max-w-sm">
                <span className={FIELD_LABEL}>
                  Which agent makes these calls
                </span>
                <select
                  value={selectedAgentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  className={FIELD}
                >
                  {agentOptions.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {/* The state travels WITH the name. An agent that cannot dial yet
                          is a legal choice here and an `agent_not_live` blocker at
                          launch; saying so at the point of choosing turns a refusal
                          nobody expected into a wait somebody planned. */}
                      {agent.name}
                      {canDialOut(agent) ? "" : " — not able to call out yet"}
                    </option>
                  ))}
                </select>
                <span className={FIELD_HINT}>
                  Its script and voice are what your customers will hear.
                  {selectedAgent &&
                    !canDialOut(selectedAgent) &&
                    " This one cannot make calls yet — you can still build the campaign, but it will not launch until the agent is switched on and able to dial out."}
                </span>
              </label>
            )}

            <fieldset>
              <legend className={FIELD_LABEL}>
                What kind of calls are these?
              </legend>
              {/* Not a cosmetic choice: the category decides which number series may
                  dial (DATA-MODEL §6), so it is asked in plain language up front
                  rather than discovered as a launch blocker. */}
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                {CLASSIFICATIONS.map((option) => (
                  <label
                    key={option.value}
                    className={`${CHOICE_CARD} ${
                      classification === option.value ? CHOICE_ON : CHOICE_OFF
                    }`}
                  >
                    <input
                      type="radio"
                      name="classification"
                      className="sr-only"
                      checked={classification === option.value}
                      onChange={() => setClassification(option.value)}
                    />
                    {classification === option.value && (
                      <CheckCircle2
                        aria-hidden
                        className="absolute right-2 top-2 h-4 w-4 text-brand"
                      />
                    )}
                    <span className="block pr-6 text-sm font-semibold text-ink">
                      {option.label}
                    </span>
                    <span className="mt-0.5 block text-xs text-ink-faint">
                      {option.hint}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className={FIELD_LABEL}>Calling from</span>
                <select
                  value={numberId}
                  onChange={(e) => setNumberId(e.target.value)}
                  className={FIELD}
                >
                  <option value="">Choose a number…</option>
                  {(numbers.data ?? []).map((number) => (
                    <option key={number.id} value={number.id}>
                      {number.e164} ({number.series} series)
                    </option>
                  ))}
                </select>
                {/* "No numbers yet" is a claim about this account, so it is only made
                    from a list the server actually sent: `numbers.data?.length === 0` is
                    false while the answer is missing, which left an empty picker with no
                    explanation under a paused or failed read. */}
                {!numbers.data ? (
                  !numbers.isLoading && (
                    <span className={FIELD_HINT}>
                      Your numbers could not be read, so this picker is empty.
                      That is not &ldquo;you have none&rdquo;.
                    </span>
                  )
                ) : numbers.data.length === 0 ? (
                  <span className={FIELD_HINT}>
                    No numbers yet — your account manager sets these up.
                  </span>
                ) : null}
              </label>

              <label className="block">
                <span className={FIELD_LABEL}>
                  <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss> template
                </span>
                <select
                  value={templateId}
                  onChange={(e) => setTemplateId(e.target.value)}
                  className={FIELD}
                >
                  <option value="">Choose a template…</option>
                  {(templates.data ?? []).map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.classification} —{" "}
                      {template.status === "approved"
                        ? "approved"
                        : template.status}
                    </option>
                  ))}
                </select>
                {/* Same rule as the number picker beside it: "none registered" is a
                    compliance claim about this client's DLT position, and only a list the
                    server sent is evidence for it. */}
                {!templates.data ? (
                  !templates.isLoading && (
                    <span className={FIELD_HINT}>
                      Your{" "}
                      <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss>{" "}
                      templates could not be read, so this picker is empty. That is not
                      &ldquo;you have none&rdquo;.
                    </span>
                  )
                ) : templates.data.length === 0 ? (
                  <span className={FIELD_HINT}>
                    None registered yet. Calls can&apos;t go out without one.
                  </span>
                ) : null}
              </label>
            </div>

            <label className="block max-w-xs">
              <span className={FIELD_LABEL}>Calls at the same time</span>
              <input
                type="number"
                min={1}
                max={10}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
                className={FIELD}
              />
              <span className={FIELD_HINT}>
                Lower means the list takes longer. Lines are always kept free
                for people calling you.
              </span>
            </label>

            {/* The calling window NARROWS a bound that already exists; it does not set
                one. 9am-9pm is TRAI law applied to every dial (hard rule 5), so the
                caption says "never … before 9am or after 9pm" first and offers the
                narrowing second. Copy that read "choose your calling hours" would
                imply the client is picking the outer limit, and the first client who
                typed 08:00 would learn otherwise from a server rejection instead of
                from the form. */}
            <fieldset>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={restrictHours}
                  onChange={(e) => setRestrictHours(e.target.checked)}
                  className="h-4 w-4 rounded border-line accent-brand"
                />
                <span className="text-sm text-ink">
                  Only call during specific hours
                </span>
              </label>
              <p className="mt-1 text-xs text-ink-faint">
                Calls never go out before 9am or after 9pm — this narrows that
                further.
              </p>

              {restrictHours && (
                <div className="mt-2 grid max-w-xs gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className={FIELD_LABEL}>From</span>
                    <input
                      type="time"
                      required
                      value={windowStart}
                      onChange={(e) => setWindowStart(e.target.value)}
                      className={FIELD}
                    />
                  </label>
                  <label className="block">
                    <span className={FIELD_LABEL}>Until</span>
                    <input
                      type="time"
                      required
                      value={windowEnd}
                      onChange={(e) => setWindowEnd(e.target.value)}
                      className={FIELD}
                    />
                  </label>
                </div>
              )}
            </fieldset>

            {/* Consent provenance (SEC-COMP §3) — a compliance artefact, not a form
                field: the client is stating on the record where this list came from,
                and the statement is what a complaint would later be answered with.
                Required to submit, because a campaign created without it is a campaign
                that cannot launch, and finding that out at the launch check — after the
                list is uploaded — is a worse place to learn it. */}
            <ConsentProvenanceFields
              idPrefix="new"
              source={consentSource}
              collectedAt={consentDate}
              onSource={setConsentSource}
              onCollectedAt={setConsentDate}
            />

            {/* Kept next to the button that causes it: a window the server refuses
                (too wide, or start after end) comes back as a problem+json with copy
                that explains the law, and ProblemNotice already renders it. Repeating
                that rule as client-side validation would let the two drift. */}
            {create.error && <ProblemNotice error={create.error} />}

            <div className="space-y-2">
              <button
                type="submit"
                title={refusal}
                disabled={
                  !write.allowed ||
                  create.isPending ||
                  !selectedAgentId ||
                  name.length < 2 ||
                  !provenanceAnswered
                }
                className={PRIMARY_BUTTON}
              >
                <Plus aria-hidden className="h-4 w-4" />
                {create.isPending ? "Creating…" : "Create campaign"}
              </button>
              {/* A dead button needs a reason next to it — including this one, which is
                  dead until the provenance question is answered. */}
              {!provenanceAnswered && (
                <p className="text-xs text-ink-faint">
                  Answer both questions about your list above — a campaign
                  without them can&apos;t be launched.
                </p>
              )}
              {hasNoAgents && (
                <p className="text-xs text-ink-faint">
                  No agent is set up yet — your account manager builds one
                  before campaigns can run.
                </p>
              )}
            </div>
          </form>
        </Card>
      ) : (
        <>
          {/* EVERY FIGURE HERE IS THE SERVER'S OR IS NOT SHOWN.
              These four used to render unconditionally with `?? 0` and, for the contact
              count, `?? parsed.length` — so a campaign whose progress request was still
              in flight, or had failed, was described as "Contacts 0 · Connected 0 · Not
              called 0". On this screen that is not a cosmetic zero: a client reading it
              during an outage concludes their campaign dialled nobody. Loading is a
              skeleton, failure is the notice above and nothing else. */}
          {progress.isLoading ? (
            <Card>
              <Skeleton rows={3} />
            </Card>
          ) : progress.data ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatTile
                label="Status"
                value={progress.data.status.replace(/_/g, " ")}
                icon={<Activity className="h-5 w-5" />}
              />
              <StatTile
                label="Contacts"
                value={formatCount(progress.data.total)}
                icon={<Users className="h-5 w-5" />}
              />
              {/* `contacts` is a complete GROUP BY over this campaign's rows, so a key
                  the response omits genuinely means zero — unlike the leads board, where
                  an absent stage means the server did not say. That is the whole reason
                  `?? 0` is honest HERE and only inside this branch. */}
              <StatTile
                label="Connected"
                value={formatCount(lookup(counts, "connected") ?? 0)}
                hint="calls answered"
                icon={<PhoneCall className="h-5 w-5" />}
              />
              <StatTile
                label="Not called"
                value={formatCount(lookup(counts, "dnc_blocked") ?? 0)}
                hint="on the do-not-call list"
                icon={<PhoneOff className="h-5 w-5" />}
              />
            </div>
          ) : null}

          {status === "draft" && (
            <Card title="Contact list">
              <div className="space-y-3">
                <textarea
                  rows={6}
                  value={csv}
                  onChange={(e) => setCsv(e.target.value)}
                  aria-label="Contact list, as CSV"
                  placeholder={"phone,name\n9876543210,Priya\n9876501234,Ravi"}
                  className="w-full rounded-md border border-line bg-surface px-3 py-2 font-mono text-xs text-ink placeholder:text-ink-faint"
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-ink-faint">
                    {parsed.length > 0
                      ? `${formatCount(parsed.length)} rows ready. Numbers we can't read are counted and skipped — never guessed.`
                      : "Paste your CSV, or one number per line."}
                  </p>
                  <button
                    type="button"
                    title={refusal}
                    disabled={
                      !write.allowed ||
                      addContacts.isPending ||
                      parsed.length === 0
                    }
                    onClick={() =>
                      addContacts.mutate(parsed, {
                        onSuccess: () => setCsv(""),
                      })
                    }
                    className={SECONDARY_BUTTON}
                  >
                    <ListPlus aria-hidden className="h-4 w-4" />
                    {addContacts.isPending ? "Adding…" : "Add contacts"}
                  </button>
                </div>
                {addContacts.data && (
                  <p className="rounded-md border border-line bg-app p-2 text-xs text-ink-muted">
                    Added {formatCount(addContacts.data.added)}.{" "}
                    {addContacts.data.duplicate > 0 &&
                      `${formatCount(addContacts.data.duplicate)} ${
                        addContacts.data.duplicate === 1 ? "was" : "were"
                      } already on the list. `}
                    {addContacts.data.malformed > 0 &&
                      `${formatCount(addContacts.data.malformed)} ${
                        addContacts.data.malformed === 1 ? "number" : "numbers"
                      } couldn't be read and ${
                        addContacts.data.malformed === 1 ? "was" : "were"
                      } skipped.`}
                  </p>
                )}
              </div>
            </Card>
          )}

          {/* THE REPEAT, at any status.
              A one-time start is spent the moment it fires, so its card is keyed on
              `scheduled`. A repeat is not: a campaign dialling right now still repeats
              next Tuesday, and the client needs both that fact and the button that stops
              it wherever they are looking. Rendered only from a response that arrived —
              the loading and failure states are the skeleton and the notice above, and
              "this campaign does not repeat" is a claim neither of them supports. */}
          {recurrence && (
            <Card title="Repeats">
              <div className="space-y-3">
                <p className="flex items-center gap-2 text-sm font-medium text-ink">
                  <Repeat aria-hidden className="h-4 w-4 shrink-0" />
                  Calls {describeRepeat(recurrence)} IST
                </p>
                {/* The sentence this whole card exists for: a schedule a client cannot
                    read against their own calendar is a schedule they cannot trust. */}
                <p className="text-sm text-ink-muted">
                  Next: {formatOccurrence(recurrence.next_occurrence_at)} IST
                  {recurrence.until &&
                    ` · stops repeating after ${formatIST(recurrence.until)}`}
                </p>
                {/* An occurrence that did not run, and why. Without this the campaign
                    simply says "scheduled" on a week it never dialled, which is the
                    silence §52 is about. */}
                {recurrence.last_skipped_at && (
                  <p className="flex gap-2.5 text-sm text-ink-muted">
                    <CircleAlert
                      aria-hidden
                      className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                    />
                    <span>
                      We skipped the run due{" "}
                      {formatOccurrence(recurrence.last_skipped_at)} IST.{" "}
                      {lookup(SKIP_COPY, recurrence.last_skipped_reason) ??
                        "The next one is unaffected."}
                    </span>
                  </p>
                )}
                {/* Same wording the one-time card uses, because it is the same fact: the
                    gate refused the last attempt to start. */}
                {(progress.data?.schedule_blocked_rules?.length ?? 0) > 0 && (
                  <p className="flex gap-2.5 text-sm text-ink-muted">
                    <CircleAlert
                      aria-hidden
                      className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                    />
                    <span>
                      We tried to start this run and could not. The reasons are
                      listed below — fix them and it will start on the next
                      attempt.
                    </span>
                  </p>
                )}
                {/* …and the same fact BEFORE the first attempt, which is where this card
                    used to be silent: a repeat armed against a lapsed registration read
                    as a next occurrence and nothing else. */}
                {armedScheduleWouldRefuse && (
                  <FireTimeRefusal kind="repeat" when="armed" />
                )}
                <button
                  type="button"
                  title={refusal}
                  disabled={!write.allowed || unschedule.isPending}
                  onClick={() => unschedule.mutate()}
                  className={SECONDARY_BUTTON}
                >
                  {unschedule.isPending ? "Stopping…" : "Stop repeating"}
                </button>
                <p className={FIELD_HINT}>
                  Stopping ends the repeat only. Calls already going out are not
                  affected — pause the campaign for that.
                </p>
              </div>
            </Card>
          )}

          {status === "scheduled" && !recurrence && (
            <Card title="Scheduled">
              {/* §52: loading is a skeleton, failure is the notice above — neither is a
                  date and neither is the word "scheduled" on its own. */}
              {progress.isLoading ? (
                <Skeleton rows={2} />
              ) : (
                <div className="space-y-3">
                  <p className="flex items-center gap-2 text-sm font-medium text-ink">
                    <CalendarClock aria-hidden className="h-4 w-4 shrink-0" />
                    Starts {formatIST(progress.data?.scheduled_start_at)} IST
                  </p>
                  {/* The gate refused the last attempt to start it. Without this the
                      campaign sits here saying "scheduled" for a day and then quietly
                      becomes a draft again — a start that never happened and never said
                      so. The rules are the launch gate's own names, so the list above
                      already explains each one in the client's words. */}
                  {(progress.data?.schedule_blocked_rules?.length ?? 0) > 0 && (
                    <p className="flex gap-2.5 text-sm text-ink-muted">
                      <CircleAlert
                        aria-hidden
                        className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                      />
                      <span>
                        We tried to start this campaign and could not. The
                        reasons are listed below — fix them and it will start on
                        the next attempt. If they are still outstanding a day
                        after the start time, the campaign goes back to draft.
                      </span>
                    </p>
                  )}
                  {/* …and the same fact BEFORE the first attempt. Without it a start
                      armed against an outstanding blocker says only "Starts Monday,
                      10:00 IST" until the day it does not. */}
                  {armedScheduleWouldRefuse && (
                    <FireTimeRefusal kind="start" when="armed" />
                  )}
                  <button
                    type="button"
                    title={refusal}
                    disabled={!write.allowed || unschedule.isPending}
                    onClick={() => unschedule.mutate()}
                    className={SECONDARY_BUTTON}
                  >
                    {unschedule.isPending
                      ? "Cancelling…"
                      : "Cancel scheduled start"}
                  </button>
                </div>
              )}
            </Card>
          )}

          {/* `scheduled` shares this card with `draft`: a campaign waiting for Monday
              has not launched, its blockers are still the launch gate's, and the server
              re-runs exactly this check when the schedule fires. Rendering it only for
              `draft` would leave a scheduled campaign with no card at all — a status and
              nothing else, which §52 says a screen may not stop at. */}
          {(status === "draft" || status === "scheduled") && (
            <Card
              title={
                status === "scheduled"
                  ? "Before it starts"
                  : "Before you launch"
              }
            >
              {check.isLoading ? (
                <Skeleton rows={3} />
              ) : check.error ? (
                /* Without this the card renders an empty blocker list under a
                   dead button: "you cannot launch, and we will not say why". */
                <ProblemNotice
                  error={check.error}
                  onRetry={() => check.refetch()}
                />
              ) : check.data?.ready ? (
                <div className="space-y-3">
                  <p className="flex items-center gap-2 text-sm font-medium text-brand-strong dark:text-brand-bright">
                    <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0" />
                    Everything checks out.
                  </p>
                  {/* NOT a bare button. Launching dials real Indian phone numbers under
                      TRAI and a placed call cannot be recalled, so it gets the same
                      three-beat gate as every other irreversible control in this product
                      — review, restatement, type-the-count — rather than being the one
                      with none. `LaunchConfirm` carries the full argument, including why
                      it has no size threshold where `BulkActionBar` has one. */}
                  <LaunchConfirm
                    contacts={progress.data?.total}
                    concurrency={progress.data?.concurrency}
                    callingHours={progress.data?.calling_hours}
                    numberE164={progress.data?.number_e164}
                    canWrite={write.allowed}
                    writeReason={refusal}
                    pending={launch.isPending}
                    onLaunch={() => launch.mutate()}
                  />

                  {/* THE ONE PLACE THE TOP-OF-SCREEN RESTRICTION NOTE IS REPEATED, and
                      the exception is earned: this is the only branch where the sentence
                      immediately above a dead control says everything is fine. A `staff`
                      user or an impersonating operator (D-22) reads "Everything checks
                      out", presses nothing, and has to scroll past the tiles and the
                      contact list to find out why — which is how a working compliance
                      gate gets reported as a broken button. The other three controls
                      keep the single note; they sit under a reason of their own. */}
                  {!write.allowed && write.reason && (
                    <p className="text-xs text-ink-muted">{write.reason}</p>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Above the list, in its own shape, and never inside it. */}
                  {platformOutage && (
                    <PlatformOutageNotice reason={platformOutage.reason} />
                  )}

                  {/* A campaign blocked ONLY by our outage has an empty to-do list, and
                      an empty list under "Before you launch" reads as "we will not say
                      why". Say the true thing: your side is done. */}
                  {clientBlockers.length === 0 ? (
                    <p className="text-sm text-ink-muted">
                      Everything on your side is ready. There is nothing else to
                      do here.
                    </p>
                  ) : (
                    <ul className="space-y-2.5">
                      {clientBlockers.map((blocker) => {
                        // The server's own `reason` is the fallback, never dropped: a
                        // blocker this build has no copy for is still a blocker, and an
                        // unnamed one would read as "you cannot launch, and we will not
                        // say why" — the exact failure this card exists to prevent.
                        const note = lookup(BLOCKER_COPY, blocker.rule);
                        return (
                          <li
                            key={blocker.rule}
                            className="flex gap-2.5 text-sm"
                          >
                            <CircleAlert
                              aria-hidden
                              className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                            />
                            <span className="text-ink-muted">
                              {note?.text ?? blocker.reason}
                              {note?.owner && (
                                <span className="ml-2 whitespace-nowrap rounded-full border border-line px-1.5 py-0.5 text-[11px] font-medium text-ink-faint">
                                  {OWNER_BADGE[note.owner]}
                                </span>
                              )}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  )}

                  {/* The reason above says WHY; this says where to go. Carries the
                      view-as marker like every other in-realm link, so an operator
                      following it from a "view as client" session does not drop back
                      to a client token two pages in (lib/api/session.tsx). */}
                  {blockedOnKyc && (
                    <p className="text-sm">
                      <Link
                        href={href(`/c/${session.orgSlug}/verification`)}
                        className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                      >
                        See what we need to verify your business
                      </Link>{" "}
                      <span className="text-ink-muted">
                        — incoming calls are unaffected while this is
                        outstanding.
                      </span>
                    </p>
                  )}

                  {/* Same shape as the KYC link above, and for the same reason: the
                      bullet says WHY, this says where to go. The trailing sentence is
                      the one thing the server's per-campaign reason structurally cannot
                      say — the hold is on the ACCOUNT, so it is not a gate this client
                      will meet again on their next campaign. */}
                  {blockedOnFirstCampaign && (
                    <p className="text-sm">
                      <Link
                        href={href(`/c/${session.orgSlug}/campaign-review`)}
                        className="font-semibold text-brand-strong underline underline-offset-2 dark:text-brand-bright"
                      >
                        {FIRST_CAMPAIGN_REVIEW_LABEL}
                      </Link>{" "}
                      <span className="text-ink-muted">
                        — it is a one-off check on your account, not on each
                        campaign, and incoming calls are unaffected.
                      </span>
                    </p>
                  )}

                  {/* The one blocker with a control attached, rendered under the
                      sentence that asks for it. `consent_source_refused` gets the form
                      too — a client who mis-answered must be able to correct the record
                      without rebuilding the campaign, and a client who answered truly
                      simply leaves it and the refusal stands. */}
                  {campaignId && provenanceBlocker && (
                    <ConsentProvenanceAnswer
                      campaignId={campaignId}
                      correcting={
                        provenanceBlocker === "consent_source_refused"
                      }
                    />
                  )}

                  {/* Disabled WITH the reasons above it — SURFACES §2b. A blocked
                      feature that is merely missing teaches the client nothing. */}
                  <button
                    type="button"
                    disabled
                    className="inline-flex cursor-not-allowed items-center gap-2 rounded-md border border-line bg-app px-4 py-2 text-sm font-semibold text-ink-faint"
                  >
                    <Rocket aria-hidden className="h-4 w-4" />
                    Launch campaign
                  </button>
                </div>
              )}

              {/* THE ARMING CONTROLS, OUTSIDE THE VERDICT — and that placement is the
                  fix, not a layout preference.

                  Both forms used to render only inside the `ready` branch, so a campaign
                  with an outstanding blocker could not arm a start or a repeat at all. That
                  was the SCREEN inventing a rule the server does not have: `POST /schedule`
                  and `POST /recurrence` run no compliance gate (campaigns/routes.py says so
                  in both docstrings, `campaigns/scheduling.py` decision 3 says why, D-79
                  records it). The gate runs at FIRE time, on every occurrence, through the
                  same `launch_campaign` the Launch button calls — which is exactly what
                  makes a DLT registration that lapses in week three refuse week three. A
                  client waiting on the registrar today can therefore set next Tuesday's
                  start today, and refusing them was refusing today for a condition Tuesday
                  will have fixed.

                  What the screen owes them instead of a hidden form is the other half of
                  that truth, and it is directly above and beside these controls: the
                  blocker list is still rendered in full by the branch above, and
                  `ArmingConsequence` says in advance what the fire-time check will do. A
                  form reachable with the blockers HIDDEN would be the dangerous version of
                  this fix rather than the fix.

                  Guarded on `check.data` rather than rendered unconditionally: a loading or
                  failed launch check reaches the skeleton or the refusal above and never
                  gets here, so nothing below ever states a consequence derived from a
                  verdict we do not have (§52). */}
              {check.data && (
                <div className="mt-3 space-y-3">
                  {/* Schedule, in the SAME card as Launch, because it is the same
                      action with a delay on it — and the gate that guards Launch runs
                      again when this fires. The green tick above is about right now;
                      the hint below says plainly that it is not a promise about the
                      start, and `ArmingConsequence` says what happens when it is not
                      even true about right now.

                      Still keyed on `draft`: a campaign that is already `scheduled`
                      shows its start (and the way out of it) in the "Scheduled" card
                      above, which is where changing one's mind about a date belongs. */}
                  {status === "draft" && (
                    <div className="space-y-2 border-t border-line pt-3">
                      <p className={FIELD_LABEL}>Or start it later</p>
                      {!check.data.ready && (
                        <FireTimeRefusal kind="start" when="arming" />
                      )}
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          type="date"
                          aria-label="Start date"
                          value={startDate}
                          onChange={(e) => setStartDate(e.target.value)}
                          className={FIELD}
                        />
                        <input
                          type="time"
                          aria-label="Start time (IST)"
                          value={startTime}
                          onChange={(e) => setStartTime(e.target.value)}
                          className={FIELD}
                        />
                        <button
                          type="button"
                          title={refusal}
                          disabled={
                            !write.allowed || !startIso || schedule.isPending
                          }
                          onClick={() => startIso && schedule.mutate(startIso)}
                          className={SECONDARY_BUTTON}
                        >
                          <CalendarClock aria-hidden className="h-3.5 w-3.5" />
                          {schedule.isPending
                            ? "Scheduling…"
                            : "Schedule start"}
                        </button>
                      </div>
                      <p className={FIELD_HINT}>
                        Times are IST. We check every one of these requirements
                        again at the moment it starts — a campaign that stops
                        being allowed to dial between now and then will not
                        start.
                      </p>
                    </div>
                  )}

                  {/* REPEAT, in the same card and for the same reason as the schedule
                      form above: it is the Launch button with a calendar on it, and the
                      gate that guards Launch runs again on every single occurrence. Both
                      `draft` and `scheduled` can set one — a client who picked Monday and
                      then decided they want it weekly should not have to cancel first —
                      which is the whole of the card's own guard, so it carries no second
                      copy of it here. */}
                  <div className="space-y-2 border-t border-line pt-3">
                    <p className={FIELD_LABEL}>Or repeat it every week</p>
                    {!check.data.ready && (
                      <FireTimeRefusal kind="repeat" when="arming" />
                    )}
                    <fieldset>
                      <legend className={FIELD_HINT}>Which days</legend>
                      <div className="mt-1 flex flex-wrap gap-3">
                        {WEEKDAYS.map((day) => (
                          <label
                            key={day.value}
                            className="flex items-center gap-1.5 text-sm text-ink"
                          >
                            <input
                              type="checkbox"
                              checked={repeatDays.includes(day.value)}
                              onChange={() => toggleRepeatDay(day.value)}
                              className="h-4 w-4 rounded border-line accent-brand"
                            />
                            {/* The full day name for a screen reader, the short one on
                                screen: seven visible "Wednesday"s wrap onto three lines
                                on a phone, and an icon-only toggle would be a control
                                with no label at all. */}
                            <span aria-hidden>{day.short}</span>
                            <span className="sr-only">{day.label}</span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    <div className="flex flex-wrap items-end gap-2">
                      <label className="block">
                        <span className={FIELD_LABEL}>Time (IST)</span>
                        <input
                          type="time"
                          value={repeatTime}
                          onChange={(e) => setRepeatTime(e.target.value)}
                          className={FIELD}
                        />
                      </label>
                      <label className="block">
                        <span className={FIELD_LABEL}>
                          Stop repeating after (optional)
                        </span>
                        <input
                          type="date"
                          value={repeatEnds}
                          onChange={(e) => setRepeatEnds(e.target.value)}
                          className={FIELD}
                        />
                      </label>
                      <button
                        type="button"
                        title={refusal}
                        disabled={
                          !write.allowed ||
                          repeatDays.length === 0 ||
                          repeat.isPending
                        }
                        onClick={() =>
                          repeat.mutate({
                            days: repeatDays,
                            at: repeatTime,
                            until: recurrenceUntil(repeatEnds),
                          })
                        }
                        className={SECONDARY_BUTTON}
                      >
                        <Repeat aria-hidden className="h-3.5 w-3.5" />
                        {repeat.isPending ? "Setting…" : "Set repeat"}
                      </button>
                    </div>
                    {/* A dead button needs its reason beside it, like the create
                        form's provenance note — and this one is dead by default,
                        because no day is pre-ticked. */}
                    {repeatDays.length === 0 && (
                      <p className="text-xs text-ink-faint">
                        Choose at least one day for this campaign to repeat on.
                      </p>
                    )}
                    <p className={FIELD_HINT}>
                      Calls go out between 9am and 9pm, so a repeat has to sit
                      inside those hours. If a run is missed — a fault our side,
                      or a previous run still going — we skip it and wait for
                      the next one rather than calling people at a different
                      time of day.
                    </p>
                  </div>
                </div>
              )}
            </Card>
          )}

          {launch.data && (
            <Card title="Launched">
              <p className="text-sm text-ink-muted">
                Calling {formatCount(launch.data.dialable)}{" "}
                {launch.data.dialable === 1 ? "person" : "people"}.
                {launch.data.dnc_scrubbed > 0 &&
                  ` ${formatCount(launch.data.dnc_scrubbed)} were on the do-not-call list and won't be called.`}
              </p>
            </Card>
          )}

          {status !== null &&
            ["running", "paused", "completed"].includes(status) && (
              <Card
                title="Progress"
                action={
                  status !== "completed" ? (
                    <button
                      type="button"
                      title={refusal}
                      disabled={!write.allowed || setStatus.isPending}
                      onClick={() =>
                        setStatus.mutate(
                          status === "running" ? "pause" : "resume",
                        )
                      }
                      className={SECONDARY_BUTTON}
                    >
                      {status === "running" ? (
                        <Pause aria-hidden className="h-3.5 w-3.5" />
                      ) : (
                        <Play aria-hidden className="h-3.5 w-3.5" />
                      )}
                      {status === "running" ? "Pause" : "Resume"}
                    </button>
                  ) : null
                }
              >
                {progress.data?.total ? (
                  <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    {Object.entries(counts).map(([key, value]) => (
                      <div key={key}>
                        {/* The server's own contact-status vocabulary, humanised but not
                          renamed: inventing a label here would make the campaign screen
                          and the API disagree about what a row is called. */}
                        <dt className="text-[11px] uppercase tracking-wider text-ink-faint">
                          {key.replace(/_/g, " ")}
                        </dt>
                        <dd className="mt-0.5 text-lg font-semibold tabular-nums text-ink">
                          {formatCount(value)}
                        </dd>
                      </div>
                    ))}
                    <div className="col-span-2 text-xs text-ink-faint sm:col-span-4">
                      Launched {formatIST(progress.data.launched_at)} · up to{" "}
                      {formatCount(progress.data.concurrency)} calls at a time
                    </div>
                  </dl>
                ) : (
                  <EmptyState title="No contacts yet" />
                )}
              </Card>
            )}

          <button
            type="button"
            onClick={startAnother}
            className={SECONDARY_BUTTON}
          >
            <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
            Start another campaign
          </button>
        </>
      )}
    </div>
  );
}

/**
 * The provenance question itself — one set of fields, two places that ask it.
 *
 * Shared rather than written twice because the two callers must ask IDENTICALLY: a
 * client answering on the create form and a client answering a blocker on a
 * five-thousand-row draft are making the same statement, and it is a statement that
 * gets audited. Two copies would drift, and the drift would show up as two different
 * records of the same declaration.
 */
function ConsentProvenanceFields({
  idPrefix,
  source,
  collectedAt,
  onSource,
  onCollectedAt,
}: {
  idPrefix: string;
  source: ConsentSource | "";
  collectedAt: string;
  onSource: (value: ConsentSource) => void;
  onCollectedAt: (value: string) => void;
}) {
  return (
    <div className="space-y-4">
      <fieldset>
        <legend className={FIELD_LABEL}>Where did this list come from?</legend>
        <p className="mt-1 text-xs text-ink-faint">
          You&apos;re putting this on the record: it&apos;s how we can show,
          later, that the people on this list agreed to hear from you. Pick the
          one that&apos;s true.
        </p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {CONSENT_SOURCES.map((option) => (
            <label
              key={option.value}
              className={`${CHOICE_CARD} ${source === option.value ? CHOICE_ON : CHOICE_OFF}`}
            >
              <input
                type="radio"
                name={`${idPrefix}-consent-source`}
                className="sr-only"
                checked={source === option.value}
                onChange={() => onSource(option.value)}
              />
              {source === option.value && (
                <CheckCircle2
                  aria-hidden
                  className="absolute right-2 top-2 h-4 w-4 text-brand"
                />
              )}
              <span className="block pr-6 text-sm font-semibold text-ink">
                {option.label}
              </span>
              <span className="mt-0.5 block text-xs text-ink-faint">
                {option.hint}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <label className="block max-w-xs">
        <span className={FIELD_LABEL}>When did they agree?</span>
        <input
          type="date"
          value={collectedAt}
          max={todayInputValue()}
          onChange={(e) => onCollectedAt(e.target.value)}
          className={FIELD}
        />
        <span className={FIELD_HINT}>
          The date on the form, bill or enquiry. If the list was built up over
          time, use the day the most recent person was added.
        </span>
      </label>
    </div>
  );
}

/**
 * The answer path for a draft that is already blocked.
 *
 * SYMPTOM this fixes: a client opens a draft they built last month, the launch check
 * says "tell us where this list came from", and there is nowhere on the screen to tell
 * us — the only field that ever accepted the answer was on the create form, which is
 * behind them. Their options were to abandon the campaign or re-upload five thousand
 * rows into a new one. So the form is rendered where the blocker is read, not on a
 * different screen.
 *
 * Draft-only, matching the endpoint: this whole card only renders inside the
 * `status === "draft"` branch, and the server refuses anything else by name.
 */
function ConsentProvenanceAnswer({
  campaignId,
  correcting,
}: {
  campaignId: string;
  /** True when a refused answer is already on file — the ask is "correct it", not "answer it". */
  correcting: boolean;
}) {
  const session = useClientSession();
  const write = useWriteAccess(
    session,
    "leads:dispatch",
    "record where a list came from",
  );
  const declare = useDeclareConsentProvenance(session, campaignId);
  const [source, setSource] = useState<ConsentSource | "">("");
  const [collectedAt, setCollectedAt] = useState("");

  const iso = consentCollectedAt(collectedAt);

  return (
    <form
      className="space-y-4 rounded-card border border-line bg-app p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!source || !iso) return;
        declare.mutate({ source, collected_at: iso });
      }}
    >
      <p className="text-sm font-semibold text-ink">
        {correcting
          ? "Correct where this list came from"
          : "Record where this list came from"}
      </p>
      <p className="text-xs text-ink-faint">
        Your contacts stay as they are — this answers the question against this
        campaign.
      </p>

      <ConsentProvenanceFields
        idPrefix={`answer-${campaignId}`}
        source={source}
        collectedAt={collectedAt}
        onSource={setSource}
        onCollectedAt={setCollectedAt}
      />

      {/* Same gate as every other mutating control here, said before the click rather
          than discovered as a 403: `leads:dispatch` is a MUTATING permission, so an
          impersonating operator and a `staff` user are both refused it server-side. */}
      <RestrictionNote reason={write.reason} />
      {declare.error && <ProblemNotice error={declare.error} />}

      <button
        type="submit"
        title={write.allowed ? undefined : (write.reason ?? undefined)}
        disabled={!write.allowed || declare.isPending || !source || !iso}
        className={PRIMARY_BUTTON}
      >
        {declare.isPending ? "Recording…" : "Record this"}
      </button>
      {/* No success banner: the launch check is refetched on success and the blocker
          above either disappears or is replaced by the refusal. That IS the answer,
          and it is more honest than "Saved!" over a campaign still unable to launch. */}
    </form>
  );
}

/**
 * BACKEND GAP — CLOSED. Kept as the record of what the fix was.
 *
 * `CampaignSummaryOut` (GET /v1/campaigns) used to carry `status` but nothing about
 * consent, so this screen could not say WHICH drafts were missing provenance without
 * running the full launch gate once per draft; the list showed one general notice and
 * the specific answer arrived only after opening a campaign.
 *
 * It now carries `consent_provenance_blocker` — and it landed as the NAMED RULE rather
 * than the `needs_consent_provenance` boolean this note originally asked for, which is
 * the better shape: a boolean would have merged "answer this" with "this can never
 * launch", and the list would have sent a client with a purchased list to a form that
 * cannot help them. `LIST_PROVENANCE_COPY` above keeps the two apart for exactly that
 * reason.
 *
 * Nothing left open here. The remaining per-campaign detail (which of the DLT, agent
 * and contact blockers apply) still needs `/launch-check`, and correctly so — that is
 * the whole gate, not a list column.
 */
