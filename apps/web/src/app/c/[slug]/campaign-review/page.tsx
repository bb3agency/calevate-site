"use client";

import Link from "next/link";
import type { ComponentType } from "react";
import { ArrowLeft, Clock, Info, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";

import {
  Card,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import {
  firstCampaignState,
  useFirstCampaignHold,
  type FirstCampaignHold,
  type FirstCampaignState,
} from "@/lib/api/firstCampaign";
import { useClientRealm, useClientSession } from "@/lib/api/session";

/**
 * Campaign review — the page somebody opens because their first launch was refused.
 *
 * BRD §245 ends the self-serve control list with "manual review of the first campaign
 * for any self-serve account", and `d07d4fc` built it: `launch_blockers` and
 * `dispatch_blockers` refuse with `first_campaign_review_pending` /
 * `first_campaign_review_rejected`, and `GET /v1/compliance/first-campaign-review`
 * reports it. What shipped with it was nothing on screen. A client launched, was
 * refused, and no part of the product said a human had to look — which reads as a broken
 * launch button, and a control that looks like a bug is the failure mode this whole
 * mitigation exists to avoid creating.
 *
 * Four things this screen has to get right, each of them a decision the API made first
 * (`apps/api/compliance/first_campaign.py`):
 *
 * 1. **The hold is on the ACCOUNT, and that is the headline, not a footnote.** Every
 *    campaign is refused while it stands, and releasing it releases the account for
 *    good. A client who reads this as "each campaign gets reviewed" concludes the
 *    product is unusable and never builds a second one — so both halves are said in the
 *    first card, in the client's words, in both directions.
 * 2. **Waiting is a STATE, rendered as one.** There is no `pending` row; the API answers
 *    the held state out of an absence. So there is no empty state and no "no data" on
 *    this screen — a blank page here would say "nothing is happening" at the exact
 *    moment the true answer is "you are in a queue".
 * 3. **Rejected is a different screen from pending.** Pending is "we will look" and the
 *    next move is nobody's; rejected is "we looked and said no", carries the reviewer's
 *    own words, and the next move is the client's. Collapsing them tells a refused
 *    client to keep waiting for a decision that already happened.
 * 4. **There is no release control here, and there never will be.** The only write is
 *    `POST /v1/admin/tenants/{tenant_id}/first-campaign-review` — admin realm,
 *    `admin:tenants`, audited on every call — because this control exists precisely for
 *    accounts we have never met, and an account that could release itself would be
 *    marking the gate green on a review nobody performed. A button whose only outcome is
 *    a 403 is a trap; the closed-signup page and `/verification` set that precedent, and
 *    the screen says out loud that the absence is deliberate.
 *
 * Read-only throughout: `org:read` is not a mutating permission and BOTH client roles
 * hold it (core/rbac.py), so every reader of this page may read all of it and there is
 * no control to gate. It therefore keeps working inside a D-22 "view as client" session
 * — the session a support person is in exactly when a held account is being discussed.
 *
 * DELIBERATELY NOT SAID: that a held account can still place single calls from a lead's
 * record. It is true — the gate is on the campaign paths only, and
 * `first_campaign.py` states that residual out loud rather than hiding it — but it is a
 * residual, not a feature, and printing "you can dial them one at a time" on the screen
 * that explains the hold would turn a documented gap into an advertised workaround.
 * Inbound being unaffected IS said, because that is the fear a blocked client arrives
 * with (D-38: the receptionist is the headline product).
 *
 * Restyled to the console's design language (globals.css tokens, `Card`, the shared
 * `NOTICE_TONES` verdict palette) WITHOUT re-deriving a single verdict client-side: the
 * box below renders `firstCampaignState`, which reads the SERVER's `held` predicate.
 * The screen's own `<h1>` is gone — the shell prints "Campaign review" from the nav list
 * (layout.tsx), and a second copy beside it is a visible duplicate.
 */

interface Verdict {
  headline: string;
  tone: NoticeTone;
  /** Whose move it is now — the sentence that separates waiting from acting. */
  next: string;
  /**
   * The state at a glance. Keyed on the STATE rather than on the tone: `warn` covers
   * both "queued" and "held on a rule we cannot name", and those are the two a client
   * most needs to tell apart before reading a word.
   */
  icon: ComponentType<{ className?: string }>;
}

const VERDICTS: Record<FirstCampaignState, Verdict> = {
  pending: {
    headline: "Your campaigns are with our compliance team.",
    tone: "warn",
    icon: Clock,
    next:
      "There is nothing to send and nothing to press — the review is already queued, and " +
      "we come to you when it is done.",
  },
  rejected: {
    headline: "We reviewed this account and did not release it for campaign calling.",
    tone: "stop",
    icon: XCircle,
    next:
      "This is not final: put right what is below and tell your account manager, and a " +
      "reviewer will look again.",
  },
  held_unknown: {
    headline: "Your campaigns are held for review.",
    tone: "warn",
    icon: ShieldAlert,
    next: "Ask your account manager where this stands.",
  },
  released: {
    headline: "Your account is cleared for campaign calling.",
    tone: "ok",
    icon: ShieldCheck,
    next:
      "This check runs once per account, and it is done — no campaign of yours will be " +
      "held for it again.",
  },
  never_applied: {
    headline: "This review does not apply to your account.",
    tone: "neutral",
    icon: Info,
    next:
      "It is a check on accounts that sign up online without us. Yours was set up with " +
      "you by someone here, so no campaign of yours is held for it.",
  },
};

export default function CampaignReviewPage() {
  const session = useClientSession();
  // In-realm links carry the D-22 view-as marker; `href()` is the one place that lives.
  const { href } = useClientRealm();
  const hold = useFirstCampaignHold(session);

  if (hold.isLoading) return <Skeleton rows={6} />;

  /**
   * A refusal we received, or an answer that never arrived — one branch, because to the
   * client they are the same sentence and it is not "you are fine".
   *
   * The second half used to `return null`. `isLoading` is false whenever the query is
   * pending but not FETCHING — which is what TanStack Query does while the browser is
   * offline (`fetchStatus: "paused"`) — so a client on a train got a blank page on the
   * one screen whose blankness reads as "nothing is holding your campaigns". There is no
   * `ApiProblem` to render in that case, and `ProblemNotice` says exactly the right
   * thing for it: we could not reach Calevate, here is a retry.
   */
  if (hold.error || !hold.data) {
    return (
      <ProblemNotice
        error={hold.error ?? new Error("The review status did not load.")}
        onRetry={() => void hold.refetch()}
      />
    );
  }

  const data = hold.data;
  const state = firstCampaignState(data);

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Before a new account makes its first campaign calls, someone at Calevate reads
        it. This is where your account stands.
      </p>

      <VerdictBox hold={data} state={state} />

      {/* The misconception that costs us the client, answered first and in both
          directions. Shown on every held state AND on the released one, because
          "it will not happen again" is only reassuring if you knew it applied to the
          account rather than to the campaign. */}
      {state !== "never_applied" && <WhatIsHeld state={state} />}

      {(state === "pending" || state === "held_unknown") && <WhileYouWait />}
      {state === "rejected" && <AfterARefusal />}

      {state !== "never_applied" && <WhoDecides state={state} />}

      <p className="text-sm text-ink-muted">
        <Link
          href={href(`/c/${session.orgSlug}/campaigns`)}
          className="inline-flex items-center gap-1.5 font-semibold text-brand-strong underline dark:text-brand-bright"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to your campaigns
        </Link>{" "}
        — the launch check there lists everything else a campaign is waiting on.
      </p>
    </div>
  );
}

/**
 * Where the account stands, in one box.
 *
 * `held` decides the colour, never `status`: `status` is null for an account nobody has
 * reviewed AND for a managed account the rule never touches, so a screen that keyed on
 * it would tell one of them the other's answer. `firstCampaignState` is the single
 * predicate, and it fails closed — a rule name this build does not recognise stays held.
 *
 * On a rejection the REVIEWER'S NOTE is what renders, not the server's composed
 * `reason`: `first_campaign_rejected_reason` builds that string as our sentence plus the
 * note, so printing both would print the note twice. The composed reason is the fallback
 * for the case the schema says cannot happen (a rejection with no note) rather than an
 * alternative to it — a refusal a client cannot read is a ticket nobody can close.
 */
function VerdictBox({ hold, state }: { hold: FirstCampaignHold; state: FirstCampaignState }) {
  const verdict = VERDICTS[state];
  const refusal = state === "rejected" ? (hold.decision_note ?? hold.reason) : null;
  const Icon = verdict.icon;
  return (
    <NoticeBox tone={verdict.tone} icon={<Icon className="h-5 w-5" />} title={verdict.headline}>
      <div className="min-w-0">
        <p className="mt-1">{verdict.next}</p>

        {refusal && (
          <p className="mt-2 rounded-md bg-white/60 p-2 dark:bg-black/20">
            <span className="font-semibold">What the reviewer said:</span> {refusal}
          </p>
        )}

        {/* An unrecognised rule gets the server's own sentence and no invented next step:
            this build cannot know what a future rule means, and "we will get to it
            shortly" would be a confident guess about somebody's stopped campaign. */}
        {state === "held_unknown" && hold.reason && <p className="mt-2">{hold.reason}</p>}

        {hold.decided_at && (
          <p className="mt-2 text-xs opacity-80">
            {state === "released" ? "Released" : "Decided"} {formatIST(hold.decided_at)}.
          </p>
        )}

        {/* The fear a blocked client actually arrives with. The gate is on the campaign
            paths only and an inbound call never reaches one, so their receptionist is
            answering the phone right now — and they will not believe that unless we say
            it. */}
        {state !== "released" && (
          <p className="mt-2 font-semibold">
            Calls coming IN are unaffected — your agent keeps answering the phone.
          </p>
        )}
      </div>
    </NoticeBox>
  );
}

/** The lead-in of a list item: the claim, before the paragraph that qualifies it. */
const LEAD_IN = "font-semibold text-ink";
const LIST = "space-y-3 text-sm text-ink-muted";

/**
 * The account/campaign distinction, which is the whole shape of this control.
 *
 * Both halves are stated because each one alone is misleading. "Every campaign is held"
 * without "and then never again" reads as a permanent tax on the product; "we only check
 * the first one" without "so this one blocks all of them" leaves a client deleting the
 * campaign and building another, which changes nothing (the review is keyed on the
 * tenant, and `reviewed_campaign_id` is `ON DELETE SET NULL` precisely so deleting it
 * cannot move the decision).
 */
function WhatIsHeld({ state }: { state: FirstCampaignState }) {
  const held = state !== "released";
  return (
    <Card title="What is being held, and for how long">
      <ul className={LIST}>
        <li>
          <span className={LEAD_IN}>It is your account that is reviewed, not each campaign.</span>{" "}
          {held
            ? "While this stands, every campaign on the account is held — not only the " +
              "first one — so building another one, or deleting this one and starting " +
              "again, changes nothing."
            : "One decision was made about the account, and it covered all of it."}
        </li>
        <li>
          <span className={LEAD_IN}>It happens once.</span>{" "}
          {held
            ? "Once we release the account, no campaign of yours is ever held for this " +
              "again. It is a review of your first campaign, not a signature on every " +
              "campaign you will ever run."
            : "No campaign of yours will be held for this again."}
        </li>
        <li>
          <span className={LEAD_IN}>What we read.</span> The contact list and where it came
          from, what the agent says, and the line that tells the person they are speaking
          to an AI. That is the check — it is about the calls, not about you.
        </li>
        <li>
          <span className={LEAD_IN}>The other checks are separate.</span> Your DLT template,
          your business verification and your credit balance each stop a launch on their
          own, and clearing this one does not clear those. Your campaign screen names
          whichever ones apply.
        </li>
      </ul>
    </Card>
  );
}

/** What a waiting client can usefully do — which is everything except dial. */
function WhileYouWait() {
  return (
    <Card title="What you can do meanwhile">
      <ul className={LIST}>
        <li>
          Finish the campaign — upload the contact list, choose the number and the DLT
          template, and answer where the list came from. All of that is what we read, so a
          campaign that is ready is a review that is quicker.
        </li>
        <li>
          Your agent keeps answering incoming calls, and everything else in Calevate keeps
          working. This holds outgoing campaigns and nothing else.
        </li>
        <li>
          If it has been longer than you expected, ask your account manager — they can see
          where it sits.
        </li>
      </ul>
    </Card>
  );
}

/** After a refusal, the next move is the client's — so it is spelled out. */
function AfterARefusal() {
  return (
    <Card title="What happens next">
      <ul className={LIST}>
        <li>
          <span className={LEAD_IN}>Put right what the reviewer named,</span> then tell your
          account manager it is done. Changing the campaign on its own does not start a new
          review — a person has to look again, and they need to know there is something to
          look at.
        </li>
        <li>
          <span className={LEAD_IN}>A refusal is not permanent.</span> Accounts are released
          after the thing that was wrong is fixed; this is a decision about a campaign we
          read, not a judgement about your business.
        </li>
        <li>
          <span className={LEAD_IN}>If the reason does not make sense, ask.</span> Quote it
          back to your account manager — the wording above is exactly what the reviewer
          recorded, so it is the fastest thing to answer.
        </li>
      </ul>
    </Card>
  );
}

/**
 * Why this page has no button — said plainly rather than left as an absence.
 *
 * A client who cannot find the control assumes they are looking in the wrong place and
 * opens a ticket to be told there is no control. One paragraph closes that ticket before
 * it is written, and it is the same argument `/verification` makes about self-verifying:
 * a review the reviewed party can wave through is worth nothing to anyone.
 */
function WhoDecides({ state }: { state: FirstCampaignState }) {
  return (
    <Card title="Who decides this">
      <p className="text-sm text-ink-muted">
        {state === "released"
          ? "A person at Calevate read this account's campaign and recorded the decision. "
          : "A person at Calevate reads the campaign and records the decision. "}
        There is deliberately no control on this page that releases your own account — a
        check you could wave through yourself would not be a check, and this one exists so
        that no new account starts dialling strangers without a human having looked. Every
        decision is written to our audit record — who made it and what they checked — and
        that record cannot be edited afterwards.
      </p>
    </Card>
  );
}
