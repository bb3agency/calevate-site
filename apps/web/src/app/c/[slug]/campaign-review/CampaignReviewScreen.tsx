"use client";

import type { ComponentType } from "react";
import { Clock, Info, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { PageHeader } from "@/components/console/pageHeader";
import {
  Disclosure,
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
import { Term } from "@/lib/glossary";

import { useCampaignReviewCopilot } from "./copilot";

/**
 * Campaign review — the page somebody opens because their first launch was refused.
 *
 * BRD §245's "manual review of the first campaign for any self-serve account": the launch
 * gate refuses with `first_campaign_review_pending` / `_rejected`, and this screen says a
 * person has to look, so the refusal does not read as a broken launch button.
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
 * Layout: one status line (the verdict, the reviewer's note, the inbound reassurance),
 * then the review as three steps, then the reasoning behind one disclosure. No verdict is
 * re-derived client-side: everything renders `firstCampaignState`, which reads the
 * SERVER's `held` predicate. No `<h1>`: the shell prints "Campaign review".
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

export function CampaignReviewScreen() {
  const session = useClientSession();
  // In-realm links carry the D-22 view-as marker; `href()` is the one place that lives.
  const { href } = useClientRealm();
  const hold = useFirstCampaignHold(session);

  useCampaignReviewCopilot(hold);

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
    <div className="max-w-2xl space-y-10 pb-12">
      <PageHeader
        back={{ href: href(`/c/${session.orgSlug}/campaigns`), label: "Your campaigns" }}
        description="Your first campaign is read by a person at Calevate before it calls anyone."
      />
      <VerdictBox hold={data} state={state} />
      {state !== "never_applied" && <ReviewSteps hold={data} state={state} />}
      {/* The four answers to "what does this mean for me", word for word, behind one
          disclosure: the verdict and the inbound reassurance above are the facts a held
          client needs first; these are the reasoning around them. */}
      {state !== "never_applied" && (
        <Disclosure
          variant="inline"
          title="How this review works"
          subtitle="It happens once per account, a person decides, and the decision is recorded."
        >
          <div className="space-y-6">
            <WhatIsHeld state={state} />
            {(state === "pending" || state === "held_unknown") && <WhileYouWait />}
            {state === "rejected" && <AfterARefusal />}
            <WhoDecides state={state} />
          </div>
        </Disclosure>
      )}
    </div>
  );
}

/**
 * Where the review stands, as three steps built only from what the server returned:
 * submitted (held or decided), read by a person (waiting, refused, or done with its date),
 * cleared to call. No step is marked from a guess.
 */
function ReviewSteps({ hold, state }: { hold: FirstCampaignHold; state: FirstCampaignState }) {
  const decided = hold.decided_at ? formatIST(hold.decided_at) : undefined;
  const items: ChecklistItem[] = [
    { id: "submitted", label: "Campaign submitted for review", state: "done" },
    {
      id: "read",
      label: "Read by a person at Calevate",
      state: state === "released" || state === "rejected" ? (state === "rejected" ? "blocked" : "done") : "waiting",
      detail:
        state === "rejected"
          ? `Not released${decided ? ` · ${decided}` : ""}`
          : state === "released"
            ? decided
            : "Waiting for a reviewer",
    },
    {
      id: "cleared",
      label: "Cleared for campaign calls",
      state: state === "released" ? "done" : "todo",
    },
  ];
  return <Checklist label="Where the review stands" headingLevel={2} items={items} />;
}

function VerdictBox({ hold, state }: { hold: FirstCampaignHold; state: FirstCampaignState }) {
  const verdict = VERDICTS[state];
  // The reviewer's own note first; the composed reason only when there is none.
  const refusal = state === "rejected" ? (hold.decision_note ?? hold.reason) : null;
  const Icon = verdict.icon;
  return (
    <section aria-label="Review status" className="space-y-2">
      <p className="flex items-start gap-2.5 text-heading text-ink">
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${TONE_TEXT[verdict.tone]}`} />
        <span>{verdict.headline}</span>
      </p>
      <div className="space-y-2 pl-7 text-body text-ink-muted">
        <p>{verdict.next}</p>
        {refusal && (
          <p className="rounded-md border border-danger-line bg-danger-soft p-3 text-ink">
            <span className="font-semibold">What the reviewer said:</span> {refusal}
          </p>
        )}
        {/* An unrecognised rule gets the server's own sentence and no invented next step. */}
        {state === "held_unknown" && hold.reason && <p>{hold.reason}</p>}
        {hold.decided_at && (
          <p className="text-meta text-ink-faint">
            {state === "released" ? "Released" : "Decided"} {formatIST(hold.decided_at)}.
          </p>
        )}
        {/* The fear a held client arrives with: the gate is on campaigns only, and their
            receptionist is answering the phone right now. */}
        {state !== "released" && (
          <p className="font-semibold text-ink">
            Calls coming IN are unaffected — your agent keeps answering the phone.
          </p>
        )}
      </div>
    </section>
  );
}

const TONE_TEXT: Record<NoticeTone, string> = {
  ok: "text-brand-strong",
  warn: "text-warn",
  stop: "text-danger",
  neutral: "text-ink-muted",
};

const LEAD_IN = "font-semibold text-ink";
const LIST = "space-y-3 text-body text-ink-muted";

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
    <section>
      <h3 className="mb-2 text-body font-semibold text-ink">What is being held, and for how long</h3>
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
          <span className={LEAD_IN}>The other checks are separate.</span> Your{" "}
          <Term id="dlt" /> template, your
          business verification and your credit balance each stop a launch on their own, and
          clearing this one does not clear those. Your campaign screen names whichever ones
          apply.
        </li>
      </ul>
    </section>
  );
}

/** What a waiting client can usefully do — which is everything except dial. */
function WhileYouWait() {
  return (
    <section>
      <h3 className="mb-2 text-body font-semibold text-ink">What you can do meanwhile</h3>
      <ul className={LIST}>
        <li>
          Finish the campaign — upload the contact list, choose the number and the{" "}
          <Term id="dlt" /> template, and
          answer where the list came from. All of that is what we read, so a campaign that is
          ready is a review that is quicker.
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
    </section>
  );
}

/** After a refusal, the next move is the client's — so it is spelled out. */
function AfterARefusal() {
  return (
    <section>
      <h3 className="mb-2 text-body font-semibold text-ink">What happens next</h3>
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
    </section>
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
    <section>
      <h3 className="mb-2 text-body font-semibold text-ink">Who decides this</h3>
      <p className="text-body text-ink-muted">
        {state === "released"
          ? "A person at Calevate read this account's campaign and recorded the decision. "
          : "A person at Calevate reads the campaign and records the decision. "}
        There is deliberately no control on this page that releases your own account — a
        check you could wave through yourself would not be a check, and this one exists so
        that no new account starts dialling strangers without a human having looked. Every
        decision is written to our audit record — who made it and what they checked — and
        that record cannot be edited afterwards.
      </p>
    </section>
  );
}
