import { type ReactNode } from "react";
import { CloudOff } from "lucide-react";

import { Term } from "@/lib/glossary";
import { type CampaignSummary } from "@/lib/api/campaigns";

/**
 * WHAT THE LAUNCH GATE REFUSED, IN THE CLIENT'S WORDS — the copy tables and the one
 * notice that is not a bullet.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6: extract by SUBJECT). This subject is the
 * translation layer between `/launch-check`'s rule names and a sentence a business owner
 * can act on; the screen that renders them is `LaunchGate.tsx`. Nothing here was reworded
 * in the move — every sentence below is a compliance refusal or its remedy (hard rule 5),
 * and `tests/campaignBlockerCopy.test.ts` reads THIS file for `BLOCKER_COPY`'s keys.
 */
/**
 * A blocker in the client's words, plus WHOSE desk it lands on.
 *
 * `owner` exists because the DLT blockers are the first ones on this screen that the
 * client cannot act on at all. "Your DLT Principal Entity registration is not active"
 * reads like a to-do, so a client who is told only that will go looking for a setting
 * they do not have, then call support to be told we were already handling it. Naming
 * the desk turns a dead end into a wait with someone to ask.
 */
export type BlockerNote = { text: ReactNode; owner?: "calevate" | "client" };

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
export const BLOCKER_COPY: Record<string, BlockerNote> = {
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
        <Term id="dlt" /> voice template
        this campaign speaks under.
      </>
    ),
  },
  dlt_template_not_approved: {
    text: (
      <>
        The <Term id="dlt" /> template is
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
        <Term id="series140" /> number;
        service calls need a{" "}
        <Term id="series160" /> one.
      </>
    ),
  },
  no_contacts: { text: "Upload the contact list." },

  /*
   * THE TWO MONEY GATES, and the only two blockers on this list that stop calls the
   * client has ALREADY launched as well as this one.
   *
   * Both had no entry here at all, so both rendered the server's own sentence — "This
   * account has no calling credit left." — which is true, terse, and missing the two
   * things that decide what the reader does next: what their own callers now hear, and
   * where the fix is. That was survivable while almost every account was
   * invoiced against a retainer and neither gate could fire; prepaid is now what an
   * account gets unless an operator deliberately says otherwise, so `no_credits` goes
   * from a rule most clients could never meet to the single most likely reason a
   * campaign of theirs will not start.
   *
   * ⚠ **`no_credits` USED TO PUT INBOUND FIRST AS A REASSURANCE — "people ringing you
   * still get through" — AND D-551 WITHDREW IT (8 Sep 2026).** An empty wallet now
   * silences answering as well as dialling
   * (`agents/service.py::reconcile_inbound_answering`), so the reassurance would be the
   * most expensive false sentence in the product: the owner reads it, does nothing, and
   * their callers are turned away. It says both halves now, and that one payment undoes
   * both, matching `crm/attention.BLOCK_REMEDIES["no_credits"]` and `WalletHero` fact for
   * fact. `spend_cap` is UNCHANGED and still says it, because a cap stops outgoing calls
   * only — different condition, different truth.
   *
   * Both are `client`, and both are now the same screen: the balance is topped up and the
   * monthly limit is set on `/c/{slug}/billing`, on its Credits and Usage tabs (D-34 R-11,
   * D-525). Neither waits on us, so neither may carry the "we handle this" badge that
   * tells a client to sit and wait.
   */
  no_credits: {
    text:
      "Your calling credit has run out, so outgoing calls have stopped and your agents " +
      "are no longer answering incoming ones — callers hear a short apology that gives " +
      "no reason and says nothing about your account. Add credit and both start again " +
      "straight away, this campaign included.",
    owner: "client",
  },
  spend_cap: {
    text:
      "This account has spent up to the monthly limit set on it, so outgoing calls have " +
      "stopped until the limit is raised or the month turns over. People ringing you " +
      "still get through.",
    owner: "client",
  },

  // The DLT entity registrations (SEC-COMP §3). Three separate registrations, none
  // implying another, and all three are OUR paperwork — an operator records them in
  // the admin console. The copy says the same thing the badge does, because a badge
  // alone is easy to miss and this is the difference between waiting and hunting.
  pe_registration_missing: {
    text: (
      <>
        Your business isn&apos;t registered with{" "}
        <Term id="dlt" /> yet — that&apos;s
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
        <Term id="dlt" /> registration
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
        Your <Term id="dlt" /> registration
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
export const LIST_PROVENANCE_COPY: Record<
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

export const OWNER_BADGE: Record<NonNullable<BlockerNote["owner"]>, string> = {
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
export const PLATFORM_BLOCKER = "tm_registration_missing";

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
export const KYC_BLOCKERS = ["kyc_missing", "kyc_not_verified"];

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
export const FIRST_CAMPAIGN_REVIEW_LABEL = "Why your first campaign is being reviewed";

export function PlatformOutageNotice({ reason }: { reason: string }) {
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
          <Term id="tm" term="telemarketer (TM)" />{" "}
          registration with the{" "}
          <Term id="dlt" /> registrar is
          not live at the moment, so no campaign on Calevate can launch — not just yours. We
          are on it, and this campaign will be launchable again the moment it is restored.
          Calls coming IN are unaffected and keep being answered.
        </p>
        {/* The server's own sentence, kept but demoted: it is the precise reason support
            and the audit trail will quote, and it should not be the headline a business
            owner reads first. */}
        <p className="mt-2 text-xs text-ink-faint">{reason}</p>
      </div>
    </div>
  );
}
