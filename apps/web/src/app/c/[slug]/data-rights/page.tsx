"use client";

import { useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  FileDown,
  ShieldAlert,
  Trash2,
} from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  TermGloss,
  DANGER_BUTTON,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  DELETION_REQUEST_LIST_LIMIT,
  downloadJson,
  useDeletionRequest,
  useDeletionRequests,
  useFileErasure,
  useSubjectExport,
  type DeletionRequest,
  type DeletionRequestSummary,
  type ErasureProof,
} from "@/lib/api/dataRights";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import { type Session } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";

/**
 * Data rights (DPDP §11, SEC-COMP §4) — the screen for the two requests a data principal
 * can make of a client, and the certificate that answers the second one.
 *
 * All three endpoints behind this shipped built, audited, worker-backed and producing
 * proof certificates, with ZERO callers. A client honouring someone's rights therefore
 * did it by curl or by emailing us — for an obligation that has a statutory clock on it.
 * That is what this closes; it is a compliance surface, not a convenience.
 *
 * ## What the screen refuses to do
 *
 * - **It does not render the subject access document.** The export is a file the client
 *   hands to the person who asked for it, and it is that person's whole record — every
 *   call, the redacted transcripts, the lead row and the consent history. Painting it
 *   into a console that is screen-shared on support calls and left open on a reception
 *   desk adds a copy nobody asked for, and the document already travels by a channel the
 *   client chooses. So the screen produces the file and says so, and the file is the only
 *   place the contents exist.
 * - **It states the document's COUNTS and nothing else about it.** That much is now
 *   possible — the endpoint has a response model (`SubjectExportOut`), where it used to
 *   answer an opaque JSON object the screen could say nothing about. Counts are the part
 *   a client needs before handing the file over ("does this look like the right person?")
 *   and the part that is not itself personal data.
 * - **It never echoes the number back.** It appears in the input the user typed it into
 *   and in the POST body, and nowhere else — not in a URL, not in a heading, not in a
 *   filename (hard rule 6). Every response on this surface speaks `subject_ref`, a
 *   one-way hash, and so does this screen.
 *
 * ## Erasure is irreversible, so the control is shaped like one
 *
 * A typed confirmation plus the consequences stated ABOVE the button, which is the ops
 * console's big-red-switch idiom (`admin/ops/page.tsx`) and the right shape for the same
 * reason: the decision has to be made before the click, not discovered after it. A filed
 * request is then tracked rather than forgotten — status, and the proof certificate the
 * moment the worker writes one — because "did the erasure actually happen?" is the
 * question the client will be asked and must be able to answer in writing.
 *
 * Filed requests are then read back from the account's own register
 * (`GET /v1/compliance/deletion-requests`), not from component state. The card below used
 * to list only what this browser session had filed, with a paste-the-id box for anything
 * else and the gap stated on screen; a legal obligation with a statutory clock on it does
 * not belong in a scratchpad that a closed tab empties. The register carries hashes,
 * statuses and timestamps — never a number — and each certificate is fetched only when
 * someone opens that request.
 */

/** Typed to arm the erasure. Uppercase and unambiguous — nobody types this by accident. */
const ERASE_CONFIRMATION = "ERASE";

/**
 * May this session build a subject access export?
 *
 * `calls:read_raw`, which is `owner` only in the client realm (`core/rbac.py`), and the
 * permission `export_routes.py` chose deliberately: this response is a strictly greater
 * disclosure than any call or lead surface, assembled into one file that then leaves the
 * building.
 *
 * Local and not `useWriteAccess`, on the precedent the call detail screen already set for
 * this exact permission (`useRawTranscriptAccess`): the export is a READ, `calls:read_raw`
 * is not in `MUTATING_PERMISSIONS`, so an impersonating operator is not refused it by the
 * server — and `useWriteAccess`'s impersonation clause would tell them to "do it from the
 * admin console instead", which is advice about a screen that does not exist. Refused
 * while `/v1/me` is in flight so the control never offers an action it is about to
 * withdraw, and a FAILED `/v1/me` says we could not check rather than implying a refusal
 * nobody made.
 */
function useSubjectExportAccess(session: Session): { allowed: boolean; reason: string | null } {
  const me = useMe(session);
  if (me.error) {
    return {
      allowed: false,
      reason: "We could not check what you are allowed to see. Reload the page to try again.",
    };
  }
  if (!me.data) return { allowed: false, reason: null };
  if (!me.data.permissions.includes("calls:read_raw")) {
    return {
      allowed: false,
      reason:
        "Only an account owner can build a subject access export. Ask them to run it, or to give you owner access.",
    };
  }
  return { allowed: true, reason: null };
}

export default function DataRightsPage() {
  const session = useClientSession();

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Under India&rsquo;s data protection law a person can ask you what you hold about
        them, and can ask you to erase it. You are the{" "}
        <TermGloss term="data fiduciary">
          the business responsible for this data under India&apos;s privacy law
        </TermGloss>{" "}
        and Calevate holds the records on your behalf, so both requests are answered from
        here. Every request below is recorded against your account, so there is a lasting
        record of who asked and when.
      </p>

      <SubjectExportCard session={session} />
      <ErasureCard session={session} />
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────────────────
   Subject access
   ──────────────────────────────────────────────────────────────────────────────── */

function SubjectExportCard({ session }: { session: Session }) {
  const access = useSubjectExportAccess(session);
  const exportDocument = useSubjectExport(session);
  const [phone, setPhone] = useState("");

  const ready = phone.trim().length >= 8;

  return (
    <Card title="What we hold about a person">
      <p className="text-sm text-ink-muted">
        Builds one file containing everything this account holds against a phone number:
        their calls, the redacted transcripts, their record in your CRM and their consent
        history. Hand that file to the person who asked for it.
      </p>

      <div className="mt-3">
        <RestrictionNote reason={access.reason} />
      </div>

      <form
        className="mt-3 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          exportDocument.mutate(phone.trim());
        }}
      >
        <Field
          id="subject-export-phone"
          label="Their phone number"
          hint="Ten digits, or the full number starting with +. It is sent in the request body and never appears in a web address."
        >
          <input
            required
            id="subject-export-phone"
            aria-describedby="subject-export-phone-hint"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value);
              // A file prepared for the previous number, sitting beside a changed one, is
              // how the wrong person's record gets handed over.
              exportDocument.reset();
            }}
            minLength={8}
            maxLength={20}
            inputMode="tel"
            autoComplete="off"
            disabled={!access.allowed}
            className={`${FIELD} font-mono`}
          />
        </Field>

        <button
          type="submit"
          title={access.reason ?? undefined}
          disabled={!access.allowed || !ready || exportDocument.isPending}
          className={PRIMARY_BUTTON_SM}
        >
          <FileDown aria-hidden className="h-4 w-4" />
          {exportDocument.isPending ? "Building…" : "Build the export"}
        </button>
      </form>

      {exportDocument.error != null && (
        <div className="mt-3">
          <ProblemNotice error={exportDocument.error} />
        </div>
      )}

      {/* The document is held here and NOT rendered — see the module note. `data` is the
          narrowed success value, so nothing on this branch is a stand-in for an answer we
          do not have. */}
      {exportDocument.data !== undefined && exportDocument.error == null && (
        <div className="mt-4">
          <NoticeBox
            tone="ok"
            icon={<CheckCircle2 aria-hidden className="h-5 w-5" />}
            title="The export is ready"
          >
            <p className="mt-1">
              Save it and send it to the person who asked. We do not show it on screen:
              it is their whole record with us, and the fewer copies of it exist, the
              better. If we hold nothing about that number the file says exactly that,
              which is a complete answer to their request.
            </p>
            {/* Counts, and deliberately only counts: they let a client check the file
                is about the person they meant before handing it over, and they are the
                one part of the document that is not itself that person's data. */}
            <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
              <Fact label="Calls" value={formatCount(exportDocument.data.counts.calls)} />
              <Fact
                label="Transcript turns"
                value={formatCount(exportDocument.data.counts.transcript_turns)}
              />
              <Fact
                label="CRM records"
                value={formatCount(exportDocument.data.counts.leads)}
              />
              <Fact
                label="Consent records"
                value={formatCount(exportDocument.data.counts.consent_records)}
              />
            </dl>
            {/* An erasure empties every column that carries the number, so a subject who
                has already been erased gets a file of zeros — which reads as "we never
                had anything" and is not what happened. This says which of the two it is,
                and whether any audio is still lawfully held. It is a fact about our
                processing, not the person's data, so it belongs beside the counts. */}
            {exportDocument.data.erasure !== null && (
              <p className="mt-3 text-xs text-ink-muted">
                An erasure for this number completed on{" "}
                {formatIST(exportDocument.data.erasure.completed_at)}, which is why the
                counts above are what they are.
                {exportDocument.data.erasure.recordings_pending_destruction > 0 &&
                  exportDocument.data.erasure.recordings_destroyed_by !== null &&
                  ` ${formatCount(exportDocument.data.erasure.recordings_pending_destruction)} recording(s) are still held under the mandatory retention period and are destroyed by ${formatIST(exportDocument.data.erasure.recordings_destroyed_by)}.`}
              </p>
            )}
            <button
              type="button"
              onClick={() =>
                downloadJson(
                  exportDocument.data,
                  // Named for the day, never for the number (hard rule 6): filenames end
                  // up in mail clients, chat threads and shared folders.
                  `subject-access-export-${new Date().toISOString().slice(0, 10)}.json`,
                )
              }
              className={`${SECONDARY_BUTTON_SM} mt-3`}
            >
              <Download aria-hidden className="h-4 w-4" />
              Save the file
            </button>
          </NoticeBox>
        </div>
      )}
    </Card>
  );
}

/* ────────────────────────────────────────────────────────────────────────────────────
   Erasure
   ──────────────────────────────────────────────────────────────────────────────── */

function ErasureCard({ session }: { session: Session }) {
  // `org:manage`, and `useWriteAccess` is exactly right here: filing an erasure IS a
  // mutation, so D-22's refusal of every mutating permission to an impersonating operator
  // is the feature rather than the obstacle (deletion_routes.py says so).
  const access = useWriteAccess(session, "org:manage", "file an erasure request");
  const file = useFileErasure(session);

  const [phone, setPhone] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const armed = phone.trim().length >= 8 && confirmation === ERASE_CONFIRMATION;

  return (
    <>
      <Card title="Erase a person's data">
        <NoticeBox
          tone="stop"
          icon={<AlertTriangle aria-hidden className="h-5 w-5" />}
          title="This cannot be undone"
        >
          <p className="mt-1">
            Every call, transcript, extracted field and CRM record we hold for this number
            is erased, and the calls themselves survive only as rows with the personal
            details stripped out. Nothing restores them. If this person is still a
            customer, you are erasing your own record of them too.
          </p>
          <p className="mt-1">
            Some things are kept, and the certificate names each one with the rule that
            required it — the consent ledger that proves the calls were lawful, the
            billing ledger, any do-not-call entry, and the call audio, which Indian
            telecom rules require to be retained.
          </p>
        </NoticeBox>

        <div className="mt-3">
          <RestrictionNote reason={access.reason} />
        </div>

        <form
          className="mt-3 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            file.mutate(phone.trim(), {
              onSuccess: () => {
                // The filed request arrives from the register, which the mutation
                // invalidates — nothing is remembered here.
                setPhone("");
                setConfirmation("");
              },
            });
          }}
        >
          {/* Not "Their phone number", which the export field above already carries: two
              controls with one accessible name is a screen reader announcing the erasure
              field as the export field, on the one screen where confusing the two is
              unrecoverable. */}
          <Field
            id="erasure-phone"
            label="Number to erase permanently"
            hint="Check it twice. We erase whoever this number belongs to, and there is no undo."
          >
            <input
              required
              id="erasure-phone"
              aria-describedby="erasure-phone-hint"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              minLength={8}
              maxLength={20}
              inputMode="tel"
              autoComplete="off"
              disabled={!access.allowed}
              className={`${FIELD} font-mono`}
            />
          </Field>

          <Field id="erasure-confirmation" label={`Type ${ERASE_CONFIRMATION} to confirm`}>
            <input
              id="erasure-confirmation"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="off"
              disabled={!access.allowed}
              className={`${FIELD} font-mono`}
            />
          </Field>

          <button
            type="submit"
            title={access.reason ?? undefined}
            disabled={!access.allowed || !armed || file.isPending}
            className={DANGER_BUTTON}
          >
            <Trash2 aria-hidden className="h-4 w-4" />
            {file.isPending ? "Filing…" : "Erase this person's data"}
          </button>
        </form>

        {file.error != null && (
          <div className="mt-3">
            <ProblemNotice error={file.error} />
          </div>
        )}

        {/* `already_open` is on the body precisely so this sentence does not have to be
            inferred from a status line: a second ask for someone already being erased is
            not an error, and telling the client it was would send them chasing a fault
            that does not exist. */}
        {file.data?.already_open === true && (
          <p className="mt-3 text-sm text-ink-muted">
            An erasure for this person was already running, so nothing new was filed. Its
            progress is below.
          </p>
        )}
      </Card>

      <RegisterCard session={session} />
    </>
  );
}

/**
 * The account's register of erasure requests.
 *
 * §52 in full, and it matters more here than anywhere else on the screen: an empty list
 * means "this account has been asked to erase nobody", and a failed read means "we do not
 * know what you have been asked to erase". The first is an answer a client could repeat
 * to a regulator; the second is not. So the failure branch renders the refusal and
 * NOTHING that could be read as a register — no rows, no count, and not the empty-state
 * sentence either.
 */
function RegisterCard({ session }: { session: Session }) {
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

      <details className="mt-3">
        <summary className="cursor-pointer text-xs font-medium text-ink-muted">
          What an erasure cannot do ({formatCount(request.limitations.length)})
        </summary>
        <ul className="mt-2 list-inside list-disc space-y-1.5 text-xs text-ink-muted">
          {request.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </details>
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
        Copies held by the calling system:{" "}
        <MonoValue>{proof.engine_deletion.replace(/_/g, " ")}</MonoValue>.
      </p>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="mt-0.5 font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}

/**
 * A form control with a PERSISTENT visible label, and a hint the control is described by.
 *
 * Both halves matter and only one of them is checkable by machine. axe accepts a
 * `placeholder` as an accessible name (tests/a11y.ts says so out loud), so a placeholder
 * "label" passes the gate and still disappears the moment someone starts typing — which
 * is WCAG 3.3.2's whole complaint, and on this screen the vanished text is the difference
 * between the export field and the erasure field. The hint sits OUTSIDE the label element
 * and is linked with `aria-describedby`, so the control's NAME stays two or three words
 * instead of a paragraph a screen reader has to read out before every keystroke.
 */
function Field({
  id,
  label,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className ?? "max-w-sm"}>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {children}
      {hint && (
        <span id={`${id}-hint`} className={FIELD_HINT}>
          {hint}
        </span>
      )}
    </div>
  );
}
