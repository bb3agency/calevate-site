"use client";

import { useState } from "react";
import { CheckCircle2, Clock, Download, ShieldAlert } from "lucide-react";

import {
  Card,
  MonoValue,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  DELETION_REQUEST_LIST_LIMIT,
  downloadJson,
  useDeletionRequest,
  useDeletionRequests,
  type DeletionRequest,
  type DeletionRequestSummary,
  type ErasureProof,
} from "@/lib/api/dataRights";
import { lookup } from "@/lib/lookup";
import { type Session } from "@/lib/api/client";

import { Fact } from "./fields";

/**
 * The account's register of erasure requests, and the certificate that answers each one.
 *
 * A filed request is TRACKED rather than forgotten — status, and the proof certificate the
 * moment the worker writes one — because "did the erasure actually happen?" is the
 * question the client will be asked and must be able to answer in writing.
 *
 * Read back from the account's own register (`GET /v1/compliance/deletion-requests`), not
 * from component state. This card used to list only what the browser session had filed,
 * with a paste-the-id box for anything else; a legal obligation with a statutory clock on
 * it does not belong in a scratchpad that a closed tab empties. The register carries
 * hashes, statuses and timestamps — never a number — and each certificate is fetched only
 * when someone opens that request.
 *
 * §52 in full, and it matters more here than anywhere else on the screen: an empty list
 * means "this account has been asked to erase nobody", and a failed read means "we do not
 * know what you have been asked to erase". The first is an answer a client could repeat
 * to a regulator; the second is not. So the failure branch renders the refusal and
 * NOTHING that could be read as a register — no rows, no count, and not the empty-state
 * sentence either.
 */
export function Register({ session }: { session: Session }) {
  const requests = useDeletionRequests(session);
  // Certificates are fetched per request, so the panels mount only when opened rather
  // than pulling every proof on the account across the wire to render an index.
  const [opened, setOpened] = useState<string[]>([]);

  const toggle = (requestId: string) =>
    setOpened((current) =>
      current.includes(requestId)
        ? current.filter((id) => id !== requestId)
        : [...current, requestId],
    );

  return (
    <Card title="Erasure requests">
      <p className="text-sm text-ink-muted">
        Every erasure this account has been asked for, newest first. Numbers are never
        listed here — each request is identified by a one-way hash of the number it
        covers.
      </p>

      {requests.isPending && (
        <div className="mt-4">
          <Skeleton rows={3} />
        </div>
      )}

      {requests.isError && (
        <div className="mt-4">
          <ProblemNotice error={requests.error} onRetry={() => void requests.refetch()} />
        </div>
      )}

      {requests.isSuccess &&
        (requests.data.length === 0 ? (
          <p className="mt-4 text-sm text-ink-muted">
            No erasure requests have been filed for this account.
          </p>
        ) : (
          <>
            <ul className="mt-4 space-y-3">
              {requests.data.map((request) => (
                <li key={request.request_id}>
                  <RegisterRow
                    session={session}
                    request={request}
                    open={opened.includes(request.request_id)}
                    onToggle={() => toggle(request.request_id)}
                  />
                </li>
              ))}
            </ul>
            {requests.data.length === DELETION_REQUEST_LIST_LIMIT && (
              // A count that is a statement about our query, presented as a statement
              // about the client's obligations, is the defect the leads table already
              // fixed once. Say which this is.
              <p className="mt-3 text-xs text-ink-faint">
                Showing the {formatCount(DELETION_REQUEST_LIST_LIMIT)} most recent
                requests. There may be older ones.
              </p>
            )}
          </>
        ))}
    </Card>
  );
}

/**
 * One row of the register, and the certificate underneath it once someone asks for it.
 *
 * The heading distinguishes three states, not two: pending, complete with a certificate,
 * and complete WITHOUT one. The third is the state a client must never report to a data
 * principal as finished, and `has_certificate` is on the list precisely so the register
 * can say it without every proof being fetched.
 */
function RegisterRow({
  session,
  request,
  open,
  onToggle,
}: {
  session: Session;
  request: DeletionRequestSummary;
  open: boolean;
  onToggle: () => void;
}) {
  const done = request.status === "completed";
  const missingProof = done && !request.has_certificate;
  const panelId = `erasure-${request.request_id}`;

  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-ink">
            {missingProof ? (
              <ShieldAlert aria-hidden className="h-4 w-4 text-amber-600" />
            ) : done ? (
              <CheckCircle2 aria-hidden className="h-4 w-4 text-emerald-600" />
            ) : (
              <Clock aria-hidden className="h-4 w-4 text-amber-600" />
            )}
            {missingProof
              ? "Complete — no certificate recorded"
              : done
                ? "Erasure complete"
                : "Submitted — waiting to run"}
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            Filed {formatIST(request.requested_at)}
            {done ? ` · completed ${formatIST(request.completed_at)}` : ""}
          </p>
          {/* The two handles a client needs when they come back to this: the request id
              they can quote to us, and the subject hash that tells one row from another
              without naming anybody. */}
          <p className="mt-1 break-all text-xs text-ink-faint">
            <MonoValue>{request.request_id}</MonoValue>
          </p>
          <p className="break-all text-xs text-ink-faint">
            <MonoValue>{request.subject_ref}</MonoValue>
          </p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          className={SECONDARY_BUTTON_SM}
        >
          {open ? "Hide details" : done ? "Show the certificate" : "Show details"}
        </button>
      </div>

      {open && (
        <div id={panelId} className="mt-3">
          <RequestPanel session={session} requestId={request.request_id} />
        </div>
      )}
    </div>
  );
}

/**
 * One erasure request, in whichever of its states it is actually in.
 *
 * §52 in full: loading is a skeleton, failure is a refusal you can act on, and neither is
 * an empty state. The refusal branch renders the problem AND NOTHING ELSE — a panel that
 * fell back to "no certificate yet" over a failed read would be telling a client that an
 * erasure has not completed when we simply did not ask successfully, which is the one
 * sentence on this screen that could be repeated to a regulator.
 */
function RequestPanel({ session, requestId }: { session: Session; requestId: string }) {
  const request = useDeletionRequest(session, requestId);

  if (request.isPending) return <Skeleton rows={2} />;

  if (request.isError) {
    return <ProblemNotice error={request.error} onRetry={() => void request.refetch()} />;
  }

  return <RequestDetail request={request.data} />;
}

/**
 * The request, once the server has actually answered — the part the register cannot say.
 *
 * Status, timestamps and both identifiers are on the register row above this, so they are
 * deliberately NOT repeated here: one screen stating "Erasure complete" twice about one
 * request is how a client reads a partial answer as a whole one. What is left is what only
 * the detail read carries — the certificate, and the notice that names what an erasure
 * cannot do.
 *
 * The API models exactly two states — `pending` and `completed` — and this renders those
 * two rather than inventing a third. "In progress" would be a guess: nothing reports that
 * the worker has picked the job up, and a screen that says so on a timer is describing
 * its own clock rather than the erasure.
 */
function RequestDetail({ request }: { request: DeletionRequest }) {
  const done = request.status === "completed";

  return (
    <div>
      <p className="text-xs text-ink-faint">
        The subject reference above is a one-way hash of the number. It confirms the
        erasure to someone who already has the number and tells anyone else nothing.
      </p>

      {!done && (
        <p className="mt-3 text-sm text-ink-muted">
          The erasure runs in the background. This panel refreshes on its own, and the
          certificate appears here the moment it is written.
        </p>
      )}

      {done && request.proof === null && (
        <div className="mt-3">
          <NoticeBox
            tone="warn"
            icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
            title="Completed, but no certificate was recorded"
          >
            <p className="mt-1">
              The erasure is marked complete and the proof is missing, so we cannot show
              you what it did. Send us this request id before you answer the person who
              asked — do not tell them it is done on the strength of this panel alone.
            </p>
          </NoticeBox>
        </div>
      )}

      {request.proof !== null && <Certificate proof={request.proof} requestId={request.request_id} />}

      {/* NOT a disclosure, and that is UX-DOCTRINE §3/§8: what an erasure cannot do is
          the sentence that QUALIFIES the right this screen exercises, and a compliance
          sentence may never be folded behind a click. It was a hand-rolled
          `<details>/<summary>` here — a second disclosure mechanism (§7) hiding the one
          list a client must read before telling a data principal their data is gone.
          `Certificate` below already refuses the same shortcut in as many words. */}
      <h3 className="mt-3 text-xs font-semibold text-ink">
        What an erasure cannot do ({formatCount(request.limitations.length)})
      </h3>
      <ul className="mt-2 list-inside list-disc space-y-1.5 text-xs text-ink-muted">
        {request.limitations.map((limitation) => (
          <li key={limitation}>{limitation}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The proof certificate — the durable artifact, rendered as a document rather than as a
 * row.
 *
 * What was cleared and what survived are given EQUAL weight, because the certificate the
 * client files must not be a page of green ticks with the surviving audio in a footnote.
 * That is the server's own position (`deletion_proof.certificate` builds `not_erased`
 * from the limitation register for exactly this reason) and it would be undone by a
 * screen that showed one list and collapsed the other.
 */
function Certificate({ proof, requestId }: { proof: ErasureProof; requestId: string }) {
  return (
    <div className="mt-3 rounded-lg border border-line bg-app p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">Proof certificate</h3>
        <button
          type="button"
          onClick={() => downloadJson(proof, `erasure-certificate-${requestId}.json`)}
          className={SECONDARY_BUTTON_SM}
        >
          <Download aria-hidden className="h-4 w-4" />
          Save the certificate
        </button>
      </div>
      <p className="mt-1 text-xs text-ink-faint">
        Executed {formatIST(proof.executed_at)} · notice version {proof.limitations_version}
      </p>

      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <Fact label="Calls covered" value={formatCount(proof.scope.calls.length)} />
        <Fact label="CRM records covered" value={formatCount(proof.scope.leads.length)} />
        <Fact
          label="Transcript turns erased"
          value={formatCount(proof.scope.transcript_turns_erased)}
        />
        <Fact
          label="Extracted records erased"
          value={formatCount(proof.scope.call_extractions_erased)}
        />
        {/* Only when the proof RECORDED it. Rendering `0` for a certificate that never
            carried the figure would be this screen inventing a claim the server was
            careful not to make. */}
        {proof.scope.recordings_destroyed !== null && (
          <Fact
            label="Recordings destroyed"
            value={formatCount(proof.scope.recordings_destroyed)}
          />
        )}
      </dl>

      {/* `null` is not zero here, and the certificate says the two in different words:
          a number means "this many recordings were inside the retention floor", `null`
          means the erasure predates our recording that fact at all. When there is a
          schedule the DATE is the actionable half — a client answering a data principal
          needs to be able to say when, not merely that. */}
      <p className="mt-2 text-xs text-ink-muted">
        {proof.scope.recordings_within_trai_floor === null
          ? "This erasure ran before we started counting recordings inside the retention floor, so that figure is not on this certificate."
          : `${formatCount(proof.scope.recordings_within_trai_floor)} of these calls still had audio inside the mandatory retention period.`}
        {proof.scope.recording_hold_until !== null &&
          ` That audio is not kept: the last of it is destroyed on ${formatIST(proof.scope.recording_hold_until)}.`}
      </p>

      <h4 className="mt-3 text-xs font-semibold text-ink">Erased</h4>
      <ul className="mt-1 list-inside list-disc space-y-1 text-xs text-ink-muted">
        {proof.erased.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      <h4 className="mt-3 text-xs font-semibold text-ink">Not erased</h4>
      <ul className="mt-1 space-y-2 text-xs">
        {proof.not_erased.map((limitation) => (
          <li key={limitation.what} className="rounded-md border border-line bg-surface p-2">
            <p className="font-medium text-ink">{limitation.what}</p>
            <p className="mt-0.5 text-ink-muted">{limitation.why}</p>
            <p className="mt-0.5 text-ink-faint">{limitation.authority}</p>
            {limitation.count !== null && (
              <p className="mt-0.5 text-ink-faint">
                {formatCount(limitation.count)} affected.
              </p>
            )}
          </li>
        ))}
      </ul>

      <p className="mt-3 text-xs text-ink-muted">
        Copies held by the calling system: {engineDeletionCopy(proof.engine_deletion)}.
      </p>
    </div>
  );
}

// The proof carries an internal status token for the calling system's own copies
// (e.g. `unconfirmed_pending_vendor_api`). A data principal reading the certificate
// needs the meaning in plain words, not the token, so map it here and fall back to the
// honest "not yet confirmed" for any value we have not worded — never the raw code.
const ENGINE_DELETION_COPY: Record<string, string> = {
  unconfirmed_pending_vendor_api: "deletion requested, not yet confirmed",
};

function engineDeletionCopy(status: string): string {
  if (status === "") return "not recorded";
  return lookup(ENGINE_DELETION_COPY, status) ?? "not yet confirmed";
}
