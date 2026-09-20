"use client";

/**
 * THE CLIENT'S OWN EXCEPTION TO THE ORDINARY-NUMBER REFUSAL, ASKED WHERE THE NUMBER IS.
 *
 * TRAI direction RG-25/(18)/2023-QoS (E-10291), 18 Jun 2024 forbids a SENDER from making
 * promotional, service or transactional voice calls from an ordinary 10-digit number, and
 * names the delegation chain so the obligation cannot be handed to a vendor
 * (`docs/evidence/primary-legal-findings-2026-09-20.md` §1). Under Model B (D-474) the
 * client holds the carrier account and is that sender, so the refusal is the default and
 * this is their exception to it — not ours to take for them.
 *
 * ## Why it lives beside the number and not on the campaign
 *
 * The launch gate refuses the campaign, and the campaign is where a client meets the
 * problem — but the thing being accepted is a fact about ONE NUMBER, it outlives every
 * campaign that dials from it, and it is withdrawn here too. Asking on the campaign screen
 * would record a per-number statement in a per-campaign place and would ask again for the
 * next campaign on the same line. `LaunchGate` links here instead.
 *
 * ## The statement is the server's words, rendered and never re-worded
 *
 * What was agreed to is the sentence the person read, and the row stores which version of
 * it. A screen that paraphrased would make the record evidence of words nobody showed.
 * The same reason the version travels back on the POST and a stale one is refused.
 *
 * ## The withdrawal is not a deletion, and the copy may not imply one
 *
 * `DELETE` is the route's verb; what it writes is another row (hard rule 4). A client who
 * believed withdrawing erased the earlier confirmation would be wrong about their own
 * record, so the button says what actually happens.
 */

import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import {
  NOTICE_TONES,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useActAccess, useWriteAccess } from "@/lib/api/hooks";
import {
  SENDER_ATTESTATION_ACT,
  STALE_STATEMENT_CODE,
  useSenderAttestation,
  useSetSenderAttestation,
} from "@/lib/api/senderAttestation";
import { useClientSession } from "@/lib/api/session";
import { Term } from "@/lib/glossary";

function problemCode(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const code = (error as { code?: unknown }).code;
  return typeof code === "string" ? code : null;
}

export function SenderAttestation({ numberId }: { numberId: string }) {
  const session = useClientSession();
  const state = useSenderAttestation(session, numberId);
  const record = useSetSenderAttestation(session, numberId);
  const [readStatement, setReadStatement] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);

  /* CONFIRMING is withheld from a view-as session and WITHDRAWING is not, and that
     asymmetry is the API's (`sender_attestation_routes.py`): the direction binds the
     sender, so a statement an operator made would evidence nothing about what the client
     accepted — while refusing to let anyone step OUT of an obligation because of who is
     signed in would hold a business to it for longer than it agreed. */
  const confirm = useActAccess(
    session,
    "org:manage",
    SENDER_ATTESTATION_ACT,
    "confirm that this business is the sender of its outbound calls",
  );
  const withdraw = useWriteAccess(
    session,
    "org:manage",
    "withdraw this confirmation",
  );

  if (state.isLoading) return <Skeleton rows={2} />;
  if (state.error || !state.data) {
    return <ProblemNotice error={state.error} onRetry={() => state.refetch()} />;
  }
  // A registered voice header needs no exception, and the API refuses one recorded
  // against it. Offering the control here would be offering a refusal.
  if (!state.data.applicable) return null;

  const { attested, statement, statement_version: version } = state.data;
  const stale = problemCode(record.error) === STALE_STATEMENT_CODE;

  return (
    <div className="mt-3 rounded-card border border-line bg-app p-4">
      <p className="text-sm font-medium text-ink">
        Calling out from this number
      </p>
      <p className="mt-1 text-sm text-ink-muted">
        This is an ordinary phone number, not a registered{" "}
        <Term id="series140" term="140-series" /> or{" "}
        <Term id="series160" term="160-series" /> voice header. TRAI requires
        promotional, service and transactional calls to a customer to be made from
        one of those, and says so to the business whose calls they are — including
        where its employees, partners or a call centre place them on its behalf. Your
        business holds this connection with your telephone operator, so those calls
        are yours and the requirement is addressed to you, not to Calevate.
      </p>

      {attested ? (
        <>
          <p
            className={`mt-3 flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES.ok}`}
          >
            <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              Confirmed. Service and reminder campaigns may dial from this number.
              Marketing campaigns may not — they need a{" "}
              <Term id="series140" term="140-series" /> number, and no confirmation
              changes that.
            </span>
          </p>
          <p className="mt-3 rounded-lg border border-line p-3 text-sm text-ink">
            {statement}
          </p>
          <div className="mt-3">
            <RestrictionNote reason={withdraw.reason} />
          </div>
          <button
            type="button"
            className={`mt-3 ${SECONDARY_BUTTON_SM}`}
            disabled={!withdraw.allowed || record.isPending}
            title={withdraw.reason ?? undefined}
            onClick={() => setWithdrawing(true)}
          >
            Withdraw this confirmation
          </button>
          <p className="mt-2 text-xs text-ink-muted">
            You can withdraw at any time. Withdrawing records that you have changed
            your mind from that moment and stops this number carrying new campaigns.
            It does not remove the confirmation you gave — both stay on your
            account&apos;s record.
          </p>
        </>
      ) : (
        <>
          <p className="mt-3 text-sm text-ink-muted">
            If you want service and reminder campaigns to dial from this number,
            confirm the statement below. It records, against this number and your
            name, that your business is the sender and accepts responsibility for
            calls made from it. Marketing campaigns stay blocked either way. If you
            are not sure whether this is right for your business, take your own
            advice before confirming — and you can withdraw it later.
          </p>
          <p className="mt-3 rounded-lg border border-line p-3 text-sm text-ink">
            {statement}
          </p>
          <div className="mt-3">
            <RestrictionNote reason={confirm.reason} />
          </div>

          {/* The wording moved while this page was open, so the click would record
              today's version against yesterday's sentence. Re-reading the statement is
              the remedy, and it is a smaller one than losing the page. */}
          {stale ? (
            <p
              className={`mt-3 flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm ${NOTICE_TONES.warn}`}
            >
              <span>
                The statement on this page is out of date. Load the current wording
                and read it before confirming.
              </span>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                onClick={() => {
                  setReadStatement(false);
                  record.reset();
                  void state.refetch();
                }}
              >
                Reload the confirmation
              </button>
            </p>
          ) : (
            record.error && <ProblemNotice error={record.error} />
          )}

          <label className="mt-3 flex items-start gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-0.5"
              disabled={!confirm.allowed}
              checked={readStatement}
              onChange={(event) => setReadStatement(event.target.checked)}
            />
            <span>I have read this and confirm it is true of my business.</span>
          </label>
          <button
            type="button"
            className={`mt-3 ${PRIMARY_BUTTON}`}
            disabled={!confirm.allowed || !readStatement || record.isPending}
            title={confirm.reason ?? undefined}
            onClick={() =>
              record.mutate({ withdraw: false, statementVersion: version })
            }
          >
            {record.isPending ? "Recording…" : "Confirm and accept"}
          </button>
        </>
      )}

      {withdrawing && (
        <ConfirmDialog
          title="Withdraw the sender confirmation for this number"
          confirmLabel="Withdraw it"
          pendingLabel="Withdrawing…"
          pending={record.isPending}
          error={record.error}
          onCancel={() => setWithdrawing(false)}
          onConfirm={() =>
            record.mutate(
              { withdraw: true, statementVersion: version },
              { onSuccess: () => setWithdrawing(false) },
            )
          }
        >
          Campaigns will stop being able to dial from this number, and any campaign
          waiting to start from it will be refused. Your earlier confirmation is not
          removed — this is recorded beside it as a change of mind, and you can
          confirm again later.
        </ConfirmDialog>
      )}
    </div>
  );
}
