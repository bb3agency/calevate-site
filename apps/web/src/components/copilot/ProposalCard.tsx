"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, ShieldAlert } from "lucide-react";

import { DANGER_BUTTON, PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import { ApiProblem, type Session } from "@/lib/api/client";
import { useConfirmProposal, type CopilotConfirmOut } from "@/lib/api/copilot";
import { lookup } from "@/lib/lookup";
import type { CopilotProposal } from "@/lib/copilot/types";

/**
 * The confirmation card: what the assistant is OFFERING to change, and the one click that
 * makes it happen.
 *
 * ## The card's job is to be unmistakably a suggestion
 *
 * The server's write tools cannot mutate anything — they read, describe and return a
 * signed proposal (`apps/api/copilot/write_tools.py`). Everything below exists so that the
 * screen tells the same story the code does: the heading is a suggestion, the pair is
 * "this is what it is now → this is what it would become", the summary's last sentence is
 * the server's own "Nothing changes until you confirm", and no success state is drawn
 * until a 200 has actually come back. A card that read as a completed action would make
 * the whole human-in-the-loop design a lie told by the last layer.
 *
 * ## Every sentence a person reads here is the SERVER'S
 *
 * `title`, `summary`, `current`, `proposed` and — afterwards — `detail` are composed
 * server-side from what the tool read, and are rendered verbatim. The browser adds only
 * chrome: "Suggestion", "Now", "Confirm", "Dismiss". Re-deriving the sentence from `tool`
 * and `object_id` would be a second account of the change, drifting from the one the
 * signature actually binds, and it would be the one the person approved.
 *
 * ## Which refusals leave the button clickable — the rule, and why it is exact
 *
 * The server BURNS the proposal's `jti` immediately before executing, so almost every
 * refusal leaves the token spent whether or not anything changed. Clicking again would
 * then produce "this suggestion has already been confirmed" — a refusal about our own
 * retry. So Confirm comes back only for the two failures that provably did NOT burn it:
 *
 *  * `copilot_confirm_unavailable` — the replay guard itself was unreachable, and it fails
 *    CLOSED, so nothing ran; and
 *  * a failure that never became an `ApiProblem` at all — a dropped connection, which may
 *    have landed or may not have. Retrying is safe precisely BECAUSE of the burn: if the
 *    first attempt landed, the second is refused rather than doubled.
 *
 * Everything else — a forged, expired, replayed or foreign token, a permission refusal, a
 * campaign that is no longer running — is a decision that is over. The card keeps the
 * refusal on screen and offers only Dismiss. A refusal is never swallowed and the card is
 * never silently removed: the person asked for something and is owed the answer.
 *
 * ## Focus
 *
 * The card does NOT steal focus when it appears — the panel is deliberately not a focus
 * trap (`CopilotPanel`'s header says why) and a person may be mid-sentence in the ask box.
 * It announces itself instead, through the `aria-live` region it is rendered in. Focus IS
 * moved once, and only with cause: when Confirm resolves, the button the person was
 * standing on is replaced by the outcome, and focus would otherwise fall to `<body>`.
 */
export function ProposalCard({
  session,
  proposal,
  onDismiss,
}: {
  session: Session;
  proposal: CopilotProposal;
  onDismiss: () => void;
}) {
  const confirm = useConfirmProposal(session);
  const card = useRef<HTMLDivElement>(null);
  const [expired, setExpired] = useState(() => hasExpired(proposal.expires_at));

  // The token stops verifying at `expires_at`, so the button goes away at `expires_at`
  // rather than letting somebody click into a refusal the server has already decided.
  // A timer rather than a re-render on every tick: nothing else on this card changes with
  // the clock, and one wake-up at the deadline is the whole requirement.
  useEffect(() => {
    setExpired(hasExpired(proposal.expires_at));
    const remaining = Date.parse(proposal.expires_at) - Date.now();
    if (Number.isNaN(remaining) || remaining <= 0) return;
    // `setTimeout` STORES ITS DELAY IN A 32-BIT SIGNED INT, and a larger one does not
    // wait longer — it wraps and the callback runs on the NEXT TICK (WHATWG HTML, "timer
    // initialisation steps", and node prints `TimeoutOverflowWarning: … Timeout duration
    // was set to 1`). A real `PROPOSAL_TTL` is five minutes so this is unreachable in
    // production, but it is exactly reachable from a fixture with a far-future instant,
    // and the failure is the nastiest kind: the card silently declares itself expired
    // milliseconds after it appears and the Confirm button is never clickable.
    if (remaining > MAX_TIMEOUT_MS) return;
    const timer = setTimeout(() => setExpired(true), remaining);
    return () => clearTimeout(timer);
  }, [proposal.expires_at]);

  const outcome = confirm.data;
  // Whether the card is still offering a decision. Once it has an outcome it is a record
  // of what happened, and the two must never be on screen together.
  const decided = outcome !== undefined;

  useEffect(() => {
    if (!decided) return;
    card.current?.focus();
  }, [decided]);

  const consequential = lookup(CONSEQUENTIAL, proposal.tool) ?? false;
  const retryable = confirm.isError && canRetry(confirm.error);
  const confirmLabel = confirm.isPending ? "Confirming…" : retryable ? "Try again" : "Confirm";

  return (
    <div
      ref={card}
      tabIndex={-1}
      role="group"
      aria-label={decided ? "What the assistant changed" : `Suggestion: ${proposal.title}`}
      className="rounded-lg border border-line bg-app px-3 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
    >
      {decided ? (
        <Outcome outcome={outcome} onDismiss={onDismiss} />
      ) : (
        <>
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            {consequential && <ShieldAlert aria-hidden className="h-3.5 w-3.5" />}
            {/* Named before the change is described, because a person who reads the
                description first has already started deciding. "Suggestion" and the
                summary's own closing sentence say the same thing twice, deliberately. */}
            Suggestion — nothing has happened yet
          </p>
          <p className="mt-1 text-xs font-medium text-ink">{proposal.title}</p>
          <p className="mt-0.5 text-xs text-ink-muted">{proposal.summary}</p>

          {/* The pair, as two labelled values rather than a sentence: this is the half of
              the decision a person cannot make without, and the server sends it as two
              fields precisely so the browser never has to parse English to show it. */}
          <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
            {proposal.current !== null && (
              <>
                <span className="text-ink-faint">Now</span>
                <span className="font-medium text-ink">{proposal.current}</span>
                <ArrowRight aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
              </>
            )}
            <span className="text-ink-faint">Would become</span>
            <span className="font-medium text-ink">{proposal.proposed}</span>
          </p>

          {/* WHAT IT COSTS AND WHETHER IT COMES BACK (D-500). An approve/deny prompt with a
              verb on it gets a worse decision than one that states the consequence, and
              these are the two facts a person most needs in front of the two actions this
              field was added for — publishing an agent, launching a campaign.

              `cost` is skipped when null rather than rendered as "no cost": a line saying
              "Cost: none" makes a free action look like a priced one that happens to be
              zero. `reversal` is ALWAYS shown, including on the safe actions, because the
              panel offers an Undo for field fills and a person who has learned that this
              assistant's changes come back must be told, every time, when they do not. */}
          <dl className="mt-2 space-y-1 text-xs">
            {proposal.cost !== null && (
              <div className="flex gap-1.5">
                <dt className="shrink-0 text-ink-faint">Cost</dt>
                <dd className="text-ink-muted">{proposal.cost}</dd>
              </div>
            )}
            <div className="flex gap-1.5">
              <dt className="shrink-0 text-ink-faint">Undo</dt>
              <dd className="text-ink-muted">{proposal.reversal}</dd>
            </div>
          </dl>

          {expired ? (
            <p className="mt-2 text-xs text-ink-muted">
              This suggestion has expired. Ask the assistant again — nothing was changed.
            </p>
          ) : (
            (!confirm.isError || retryable) && (
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={confirm.isPending}
                  onClick={() => confirm.mutate(proposal.token)}
                  // The accessible name is the VISIBLE WORD plus the server's own title,
                  // and it is built from the same variable rather than typed out — WCAG
                  // 2.5.3 Label in Name requires the name to CONTAIN the visible text, so
                  // a hard-coded "Confirm — …" would quietly break the moment the button
                  // reads "Try again". What the pairing buys is that somebody arriving
                  // here by keyboard hears WHICH change they are about to make rather
                  // than a bare verb.
                  aria-label={`${confirmLabel} — ${proposal.title}`}
                  className={consequential ? DANGER_BUTTON : PRIMARY_BUTTON}
                >
                  {confirmLabel}
                </button>
                <button
                  type="button"
                  disabled={confirm.isPending}
                  onClick={onDismiss}
                  aria-label={`Dismiss — ${proposal.title}`}
                  className={SECONDARY_BUTTON}
                >
                  Dismiss
                </button>
              </div>
            )
          )}

          {confirm.isError && (
            <div className="mt-2 space-y-2">
              {/* The server's own refusal, in its own words — `ProblemNotice` renders the
                  `detail` and the `remediation`, which is where the sentence a person can
                  act on lives. Never summarised and never replaced by "that failed". */}
              <ProblemNotice error={confirm.error} />
              {!retryable && (
                <button type="button" onClick={onDismiss} className={SECONDARY_BUTTON}>
                  Dismiss
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/**
 * What the confirmed change did — the only place this component says something HAPPENED.
 *
 * `detail` is the server's sentence and it distinguishes the two outcomes a 200 can carry:
 * the change was made, or the world was already in that state and nothing was written.
 * Both are real answers (D-65), and flattening them into one "Done" would tell somebody
 * watching calls go out that they had stopped a campaign that was never running.
 */
function Outcome({
  outcome,
  onDismiss,
}: {
  outcome: CopilotConfirmOut;
  onDismiss: () => void;
}) {
  return (
    <>
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        <Check aria-hidden className="h-3.5 w-3.5" />
        {outcome.applied ? "Done" : "Nothing to change"}
      </p>
      <p className="mt-1 text-xs text-ink">{outcome.detail}</p>
      <button type="button" onClick={onDismiss} className={`${SECONDARY_BUTTON} mt-2`}>
        Close
      </button>
    </>
  );
}

/**
 * Which tools stop something happening in the real world, keyed by the wire's own name.
 *
 * UX-DOCTRINE §4: destructive and consequential actions take `DANGER_BUTTON`, never the
 * brand green — "an operator's eye should refuse to find it there". Adding a number to the
 * do-not-call list pulls back dials the vendor is already holding (D-428(b)) and pausing a
 * campaign stops live dialling; neither of those recalls can be un-made by removing the
 * row afterwards. Moving a lead's status is an ordinary edit and is styled as one — making
 * every proposal rose would spend the signal on the one that does not need it.
 *
 * Read through `lookup` because the key is a wire string (UX-DOCTRINE §10). A tool this
 * console has not learned about falls back to the ORDINARY styling rather than the alarming
 * one: the alternative is a screen that cries wolf on every future read-shaped tool, and
 * the destructive ones are the ones we know by name.
 */
const CONSEQUENTIAL: Record<string, boolean> = {
  lead_set_status: false,
  dnc_add: true,
  campaign_pause: true,
};

/** The longest delay `setTimeout` can hold: 2^31 − 1 ms, about 24.8 days. */
const MAX_TIMEOUT_MS = 2_147_483_647;

function hasExpired(expiresAt: string): boolean {
  const at = Date.parse(expiresAt);
  // An unparseable instant is NOT treated as expired: the token is what the server
  // verifies, and refusing to offer a button because we could not read a display string
  // would break a working proposal over a formatting change.
  return !Number.isNaN(at) && at <= Date.now();
}

/**
 * Whether this failure left the proposal still spendable — see the header's rule.
 *
 * Exported for the test that pins the rule, because getting it wrong is invisible on
 * screen: too generous and a person retries into "already confirmed" after a change that
 * really happened; too strict and a Redis blip becomes a dead card.
 */
export function canRetry(error: unknown): boolean {
  if (!(error instanceof ApiProblem)) return true;
  return error.code === "copilot_confirm_unavailable";
}
