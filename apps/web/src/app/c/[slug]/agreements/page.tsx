"use client";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { useAgreementsReadiness } from "@/lib/api/agreements";
import { useClientSession } from "@/lib/api/session";

import { useAgreementsCopilot } from "./copilot";
import { Readiness } from "./Readiness";

/**
 * Agreements & readiness — the screen an owner opens because their calls will not go out.
 *
 * Eight published documents have existed at `/legal/<slug>` since the legal sweep and
 * nothing in this product had ever asked a client to accept one. Four of them BIND:
 * `legal.service.agreements_blocker` refuses the dial gate, both campaign gates and the
 * agent publish path until the owner has accepted them at their current version. This is
 * the only place that refusal can be cleared, so the page is written for the person who
 * arrived at it from a disabled button.
 *
 * ═══ THE SERVER DECIDES; THIS RENDERS ═══════════════════════════════════════════════
 *
 * Every verdict, every state word and every sentence on this screen arrives decided —
 * `may_operate`, `verdict`, each document's `state` and `headline`, each blocker's
 * `title`/`actor`/`next_step`, the acceptance wording, and whether THIS caller may
 * accept. Nothing here compares a version string or counts a list, and that is the
 * doctrine `lib/api/agreements.ts` states at length: whether an organisation may operate
 * is a compliance verdict four server-side gates already compute, and a browser that
 * re-derived it would eventually disagree with the gate that actually refuses the call.
 *
 * It is also why `can_accept` comes off the READ rather than out of `useWriteAccess`.
 * The permission preview would give the same answer today, and it would give it from a
 * SECOND rule: this endpoint's own answer already knows about the owner-only permission
 * AND the D-22 read-only session, and one of them is the reason on the day they differ.
 *
 * ═══ WHY ONE TICK AND FOUR ROWS ═════════════════════════════════════════════════════
 *
 * The acceptance statement is one sentence naming all four documents (the server owns the
 * text — `legal/statements.py`), and the ledger records one row per document, because an
 * acceptance is of a SPECIFIC text at a SPECIFIC version and a single row could not say
 * which. So the screen ticks once and posts once per outstanding document, in order,
 * stopping at the first refusal — a partially-accepted set is a truthful record of what
 * the owner got through, and the ones that landed do not need clicking again.
 *
 * The buttons are absent, not disabled, for a reader who cannot accept: `RestrictionNote`
 * says why instead. A disabled control with no explanation is the shape D-22 exists to
 * stop.
 *
 * BUILD-LOG §52 throughout: loading is a skeleton, a failure is a refusal, and neither is
 * a verdict. `may_operate` is never defaulted — a dead read renders the refusal, never
 * "nothing is holding up your calls".
 */

export default function AgreementsPage() {
  const session = useClientSession();
  const readiness = useAgreementsReadiness(session);
  // Above the §52 branches: a hook, and the early returns below would make it conditional.
  useAgreementsCopilot(readiness);

  if (readiness.isLoading) return <Skeleton rows={8} />;

  // A refusal we received, or an answer that never arrived — one branch, because to the
  // reader they are the same sentence and it is not "you are ready". `isLoading` is false
  // while a query is pending but not FETCHING (an offline browser parks at
  // `fetchStatus: "paused"`), which is how a client on a train gets a blank page.
  if (readiness.error || !readiness.data) {
    return (
      <ProblemNotice
        error={
          readiness.error ??
          new Error(
            "Your agreements did not load, so we cannot say where this account stands.",
          )
        }
        onRetry={() => void readiness.refetch()}
      />
    );
  }

  return <Readiness readiness={readiness.data} />;
}
