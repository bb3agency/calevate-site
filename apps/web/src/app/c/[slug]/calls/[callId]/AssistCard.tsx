"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";

import {
  Card,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
} from "@/components/ui";
import { AcceptChargeDialog, extraUnavailableSentence } from "@/components/aiExtraDialog";
import { ApiProblem, type Session } from "@/lib/api/client";
import { useAiQuota, useBuyAiExtra } from "@/lib/api/aiQuota";
import { useCallAssist, useWriteAccess } from "@/lib/api/hooks";

/**
 * "Re-summarise this call" — the one place a client can spend the dashboard-AI allowance
 * on a call (D-127 G-2/G-5/G-6), and the surface the whole metering half of that decision
 * was built for.
 *
 * ## What it does and does not change
 *
 * The answer is a SECOND READING, shown beside the stored summary and never in place of
 * it. The stored one came from the raw transcript on the first post-call pass; this one
 * comes from the redacted copy through the assistant model (`apps/api/crm/assist.py`
 * argues why replacing one with the other would degrade the lead). So the card renders
 * both facts as what they are, and nothing on this screen is overwritten by pressing it.
 *
 * ## §52, and the three states that are not a number
 *
 * Loading is a `Skeleton`, failure is a `ProblemNotice`, and the assistant answering with
 * an EMPTY summary — which is a paid-for outcome, not an absence — is stated in words
 * rather than rendered as a blank card. There is no `?? ""` between the server and a
 * pixel here except the one the API itself guarantees is a string.
 *
 * ## The ceiling (G-5)
 *
 * `require_ai_assist` refuses with `ai_quota_exceeded`, and the browser is told to open
 * the wallet dialog on that code and on no other. The figures come from a re-read of
 * `GET /v1/billing/ai-quota` rather than from the error body, which is the server's own
 * instruction: one computation of what a block costs, so the amount a person accepts can
 * never be a stale copy carried in a refusal. That read is enabled only once the ceiling
 * has actually been met — an owner who never hits it never pays for the request.
 *
 * ## The disclosure (G-6)
 *
 * A fallback is never silent. When `disclosure` is non-null the answer was written by
 * Sarvam rather than the assistant model, and the sentence the server composed is shown
 * WITH the answer — not in a tooltip, not below the fold.
 */
export function AssistCard({ session, callId }: { session: Session; callId: string }) {
  const assist = useCallAssist(session, callId);
  /**
   * D-22 read-only, and the permission is the route's own. `POST /v1/calls/{id}/assist`
   * is `org:manage` — the same permission the purchase takes, because the AI surface is
   * owner-scoped throughout (SEC-COMP §5: spend is an owner's business) — and
   * `useWriteAccess` refuses it to an impersonating operator for free, which is right
   * here: an operator on a support call must not spend a client's allowance.
   */
  const write = useWriteAccess(session, "org:manage", "use AI help on this call");

  const atCeiling = assist.error instanceof ApiProblem && assist.error.code === "ai_quota_exceeded";
  const quota = useAiQuota(session, { enabled: atCeiling });
  const buy = useBuyAiExtra(session);
  const [asking, setAsking] = useState(false);

  return (
    <Card title="Ask the assistant">
      <div className="space-y-3">
        <p className="text-sm text-ink-muted">
          Read this call again with the AI assistant and write a fresh summary. It reads
          the redacted transcript only, and it does not change anything already saved
          against this call.
        </p>

        <RestrictionNote reason={write.reason} />

        <button
          type="button"
          className={PRIMARY_BUTTON}
          disabled={!write.allowed || assist.isPending}
          onClick={() => assist.mutate()}
        >
          <Sparkles className="mr-2 inline h-4 w-4" />
          {assist.isPending ? "Reading the call…" : "Re-summarise with AI"}
        </button>

        {/* Loading is a skeleton. Not a spinner in the button alone: the answer lands in
            the space below, and a card that stays the same height and then jumps is how a
            person misses that anything happened. */}
        {assist.isPending && <Skeleton rows={3} />}

        {/* Failure is a refusal — the server's own words, with its remediation. The
            ceiling is the ONE code that gets a different treatment, because it has an
            action attached; everything else is stated and offered a retry. */}
        {assist.error != null &&
          (atCeiling ? (
            <CeilingOffer
              quota={quota}
              buy={buy}
              asking={asking}
              onAsk={() => setAsking(true)}
              onClose={() => {
                buy.reset();
                setAsking(false);
              }}
              onBought={() => {
                setAsking(false);
                assist.reset();
              }}
            />
          ) : (
            <ProblemNotice error={assist.error} onRetry={() => assist.mutate()} />
          ))}

        {assist.data && <AssistAnswer answer={assist.data} />}
      </div>
    </Card>
  );
}

/** The answer, its provenance, and what it cost — three facts, none of them optional. */
function AssistAnswer({
  answer,
}: {
  answer: { summary: string; disclosure: string | null; metered: boolean };
}) {
  return (
    <div className="space-y-2 rounded-card border border-line bg-canvas p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        The assistant&apos;s summary
      </p>
      {answer.summary.trim() ? (
        <p className="text-sm text-ink">{answer.summary}</p>
      ) : (
        // A completed run that produced nothing is an OUTCOME, and §52 does not let an
        // empty state stand in for one. It is also not free — it is stated, not hidden.
        <p className="text-sm text-ink-muted">
          The assistant read the call and did not produce a summary for it. Nothing on this
          call was changed. You can try again.
        </p>
      )}
      {/* G-6: a fallback is ALWAYS disclosed, in the server's own sentence. */}
      {answer.disclosure !== null && (
        <NoticeBox tone="neutral" title="Written by a different model">
          <p className="mt-1">{answer.disclosure}</p>
        </NoticeBox>
      )}
      {!answer.metered && (
        <p className="text-xs text-ink-faint">
          This one did not use any of your AI allowance.
        </p>
      )}
    </div>
  );
}

/**
 * At the ceiling: the block, on the SERVER's terms, through the ONE dialog.
 *
 * The three states of the quota re-read are all handled, and that is the §52 point rather
 * than defensiveness: this component decides whether a control that spends money is
 * rendered, so "we have not got an answer" must not look like "there is nothing to buy".
 */
function CeilingOffer({
  quota,
  buy,
  asking,
  onAsk,
  onClose,
  onBought,
}: {
  quota: ReturnType<typeof useAiQuota>;
  buy: ReturnType<typeof useBuyAiExtra>;
  asking: boolean;
  onAsk: () => void;
  onClose: () => void;
  onBought: () => void;
}) {
  // Bound once so the dialog's `onAccept` closes over a value TypeScript has already
  // narrowed: `quota.data` is `AiQuota | undefined` at every later read, and a non-null
  // assertion inside the callback would be the browser promising something the query
  // envelope does not.
  const allowance = quota.data;

  return (
    <NoticeBox tone="warn" title="You have used this month's included AI help">
      <p className="mt-1">
        AI help in the console has stopped for this month. Everything else — your calls,
        campaigns and leads — carries on exactly as before.
      </p>

      {quota.error != null && (
        <div className="mt-3">
          <ProblemNotice error={quota.error} onRetry={() => void quota.refetch()} />
        </div>
      )}
      {quota.error == null && allowance === undefined && (
        <div className="mt-3">
          <Skeleton rows={2} />
        </div>
      )}
      {allowance !== undefined &&
        (allowance.extra_available ? (
          <button type="button" className={`${PRIMARY_BUTTON} mt-3`} onClick={onAsk}>
            See what more AI help costs
          </button>
        ) : (
          <p className="mt-3">{extraUnavailableSentence(allowance)}</p>
        ))}

      {asking && allowance !== undefined && (
        <AcceptChargeDialog
          quota={allowance}
          pending={buy.isPending}
          error={buy.error}
          onCancel={onClose}
          // The SERVER's figure, echoed back untouched. Nothing here computes an amount,
          // and a mismatch is refused rather than clamped.
          onAccept={() => buy.mutate(allowance.extra_block_inr, { onSuccess: onBought })}
        />
      )}

      {buy.data && !asking && (
        <div role="status" className="mt-3">
          <p>
            AI help is available again for the rest of {buy.data.month}. Press
            &ldquo;Re-summarise with AI&rdquo; to try again.
          </p>
        </div>
      )}
    </NoticeBox>
  );
}
