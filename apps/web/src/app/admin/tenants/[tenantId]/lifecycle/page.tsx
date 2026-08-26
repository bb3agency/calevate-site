"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2 } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { WriteFailure } from "@/app/admin/writeFailure";
import { adminSession, useTenant } from "@/lib/api/admin";
import { erasureConfirmation, useEraseTenant, useTenantErasures } from "@/lib/api/erasure";
import {
  LIFECYCLE_COPY,
  useSetTenantStatus,
  type LifecycleStatus,
} from "@/lib/api/commercials";

import { useAdminAccess } from "@/app/admin/access";

const CHOICES = Object.keys(LIFECYCLE_COPY) as LifecycleStatus[];

/**
 * Account lifecycle — suspend, reactivate, close (SURFACES §1).
 *
 * `organizations.status` had a five-value CHECK from the first migration, was read by
 * the health board's ended-account filter, and was written by NOTHING: there was no
 * suspend route in either realm. Worse than missing — had an operator set it by hand it
 * would have changed nothing, because the dial gate never read it. Both halves land
 * together: this screen writes the status, and `compliance.check_dispatch` now refuses a
 * suspended or closed account, so suspending genuinely stops the campaigns.
 *
 * The screen's job beyond the button is to say what each move DOES before it is made.
 * Suspension stops outbound and leaves inbound alone; closing an account also locks its
 * users out and cannot be undone here. Neither is guessable from a dropdown.
 */
export default function LifecyclePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const move = useSetTenantStatus(adminSession(), tenantId);
  const write = useAdminAccess("admin:tenants", "change an account's state");
  // `ops:manage` is the superadmin marker the API checks IN ADDITION to `admin:tenants`
  // before it will erase. Previewed here so an operator sees why the control is closed
  // to them, rather than discovering it as a 403 after typing a confirmation.
  const erase = useAdminAccess("ops:manage", "erase a client's data");

  if (tenantQuery.isLoading) return <Skeleton rows={5} />;
  // §52: a failed read is a refusal, never a screen that reports a state it could not
  // fetch. "Active" printed over a 503 is exactly how somebody suspends the wrong client.
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
  if (!tenantQuery.data) return <EmptyState title="Client not found" />;

  const tenant = tenantQuery.data;

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {tenant.name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">Account state</h1>
        <p className="text-sm text-ink-muted">
          Currently <span className="font-medium text-ink">{tenant.status}</span>. Suspending
          or closing an account stops its outbound dialling at the next dial — campaigns
          included. Inbound answering is never affected: their own customers still get
          through.
        </p>
      </div>

      {tenant.status === "churned" ? (
        /* Terminal, and said plainly rather than by a row of disabled buttons: reopening
           a closed account is a new agreement, not a click. The API answers 409 naming
           the state, so this is a preview of a real refusal. */
        <>
          <NoticeBox
            tone="stop"
            icon={<AlertTriangle className="h-5 w-5" />}
            title="This account is closed"
          >
            <p className="mt-1 text-xs opacity-90">
              Closed accounts cannot be reopened here. Their users have no access, their
              data is on the retention clock, and restarting the relationship means a new
              account with its own commercial terms.
            </p>
          </NoticeBox>
          <ErasurePanel tenantId={tenantId} tenantName={tenant.name} access={erase} />
        </>
      ) : (
        <MoveForm move={move} currentStatus={tenant.status} tenantName={tenant.name} write={write} />
      )}

      {move.error != null && <ProblemNotice error={move.error} />}
      {move.data && (
        <NoticeBox
          tone={move.data.changed ? "ok" : "neutral"}
          icon={<CheckCircle2 className="h-5 w-5" />}
        >
          <p className="text-xs">
            {move.data.changed
              ? `This account is now ${move.data.status}. The dial gate reads it from the next request.`
              : `This account was already ${move.data.status} — nothing changed, and no audit row was written.`}
          </p>
        </NoticeBox>
      )}
    </div>
  );
}

function MoveForm({
  move,
  currentStatus,
  tenantName,
  write,
}: {
  move: ReturnType<typeof useSetTenantStatus>;
  currentStatus: string;
  tenantName: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const [status, setStatus] = useState<LifecycleStatus>(
    currentStatus === "active" ? "suspended" : "active",
  );
  const [reason, setReason] = useState("");
  const copy = LIFECYCLE_COPY[status];
  // The API refuses a reasonless suspension with a 422. Previewed here so an operator is
  // told before the click rather than after — and the server still enforces it.
  const blocked = copy.needsReason && reason.trim().length < 3;

  return (
    <Card title={`Move ${tenantName}`}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          move.mutate({ status, reason: reason.trim() === "" ? null : reason.trim() });
        }}
      >
        <RestrictionNote reason={write.reason} />

        <div>
          <label htmlFor="lifecycle-status" className={FIELD_LABEL}>
            New state
          </label>
          <div className="mt-1">
            <select
              id="lifecycle-status"
              value={status}
              disabled={!write.allowed}
              onChange={(event) => {
                setStatus(event.target.value as LifecycleStatus);
                move.reset();
              }}
              className={FIELD}
            >
              {CHOICES.map((choice) => (
                <option key={choice} value={choice}>
                  {LIFECYCLE_COPY[choice].action}
                </option>
              ))}
            </select>
          </div>
          <span className={FIELD_HINT}>{copy.consequence}</span>
        </div>

        {copy.needsReason && (
          <div>
            <label htmlFor="lifecycle-reason" className={FIELD_LABEL}>
              Why
            </label>
            <div className="mt-1">
              <textarea
                id="lifecycle-reason"
                rows={3}
                maxLength={500}
                value={reason}
                disabled={!write.allowed}
                onChange={(event) => {
                  setReason(event.target.value);
                  move.reset();
                }}
                className={FIELD}
              />
            </div>
            <span className={FIELD_HINT}>
              Required, and recorded verbatim in the audit log. Somebody will have to
              answer &quot;why is this account stopped&quot; later.
            </span>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          {/* Shared primary CTA: the action label (copy.action) stays mounted so the
              button's accessible name never flickers to "Applying…" mid-request; the
              spinner rides `loading`, and the two non-pending disable reasons are
              unchanged. The erase control below keeps its own typed-confirm button. */}
          <ActionButton type="submit" loading={move.isPending} disabled={blocked || !write.allowed}>
            {copy.action}
          </ActionButton>
          {blocked && (
            <span className="text-xs text-amber-700 dark:text-amber-400">
              A reason is required before this can be applied.
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}

/**
 * The offboarding trigger SURFACES §1 has promised since v1.0, and the last step of
 * FLOWS §9. Only ever rendered for a CLOSED account, because the API refuses any other
 * (`409 tenant_not_closed`) — `deleted_at` only ever refines `churned`.
 *
 * THE TYPED CONFIRMATION IS NOT THE GUARD, and the difference matters. The guard is the
 * `X-Confirm-Action` header the API demands and the superadmin role it checks first; a
 * dialog that only exists in this component is absent from curl. What the typing buys is
 * that the most destructive request in the product cannot be sent by a mis-click, and
 * that the operator has read the sentence describing what goes.
 */
function ErasurePanel({
  tenantId,
  tenantName,
  access,
}: {
  tenantId: string;
  tenantName: string;
  access: ReturnType<typeof useAdminAccess>;
}) {
  const session = adminSession();
  const filed = useTenantErasures(session, tenantId);
  const erase = useEraseTenant(session, tenantId);
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const confirmation = erasureConfirmation(tenantId);
  const blocked = reason.trim().length < 3 || typed.trim() !== confirmation;

  // §52, and the most expensive instance of it this console has held. `filed.data` is
  // undefined while the read is in flight AND after it fails, and the branch below reads
  // that undefined as "no erasure has ever been filed" — so both states fell through to
  // the FORM. A screen that offers an irreversible, tenant-wide DPDP erasure while
  // stating that none has been filed is worse than a blank one: the erasure it is
  // offering to start may already be running, and the operator has been told the
  // opposite by the only screen that could have told them otherwise.
  //
  // The ladder therefore sits ABOVE the `existing` branch, not beside it, and both arms
  // keep the card so the panel does not silently disappear out of the page either.
  if (filed.isLoading) {
    return (
      <Card title="Data erasure">
        <Skeleton rows={3} />
      </Card>
    );
  }
  if (filed.error) {
    return (
      <Card title="Data erasure">
        <ProblemNotice error={filed.error} onRetry={() => void filed.refetch()} />
        <p className="mt-3 text-sm text-ink-muted">
          Until this reads, we cannot tell you whether this client&apos;s data has already
          been erased — so the erasure form stays closed. Filing a second one would start a
          destructive job over the top of a running one.
        </p>
      </Card>
    );
  }

  const existing = filed.data?.[0];

  if (existing) {
    // Already filed or already done. The certificate stays readable here forever — every
    // OTHER admin screen 404s an erased client, which is exactly why this one does not
    // go through the live-tenant predicate.
    return (
      <Card title="Data erasure">
        <p className="text-sm text-ink-muted">
          {/* `formatIST`, like every other instant in both consoles. A bare
              `toLocaleString()` takes the BROWSER's zone AND the browser's locale, so
              this line — the date on a DPDP erasure certificate, the one record that
              answers "when was this destroyed" — read "8/19/2026, 8:00:00 PM" on an
              operator's machine and named the previous day outside IST. Times are stored
              UTC and shown IST at the edge (CLAUDE.md conventions); this was the one
              place in the app that opted out. */}
          {existing.status === "completed"
            ? `This client's data was erased on ${formatIST(existing.completed_at ?? existing.requested_at)}. The certificate below is the record.`
            : "An erasure has been filed for this client and is running. It cannot be cancelled."}
        </p>
        <p className="mt-2 text-xs text-ink-muted">Reason recorded: {existing.reason}</p>
        {existing.proof && (
          <ul className="mt-3 space-y-1 text-xs text-ink-muted">
            <li>Calls stripped: {existing.proof.scope.calls_erased ?? "not recorded"}</li>
            <li>Leads anonymised: {existing.proof.scope.leads_erased ?? "not recorded"}</li>
            <li>
              Recordings destroyed: {existing.proof.scope.recordings_destroyed ?? "not recorded"}
              {/* An ISO INSTANT (`compliance/deletion.py::HOLD_UNTIL_KEY`), not a
                  calendar date, so it gets the same IST rendering as the line above —
                  `toLocaleDateString()` dropped the time AND took the browser's zone,
                  which can move a retention deadline by a day. */}
              {existing.proof.recording_hold_until
                ? ` — the rest are destroyed by ${formatIST(existing.proof.recording_hold_until)}`
                : ""}
            </li>
            <li>Engine-side copies: {existing.proof.engine_deletion}</li>
          </ul>
        )}
        {existing.limitations.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer text-xs font-medium text-ink">
              What this erasure did not remove
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-muted">
              {existing.limitations.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        )}
      </Card>
    );
  }

  return (
    <Card title="Erase this client's data">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          erase.mutate({ reason: reason.trim() });
        }}
      >
        <RestrictionNote reason={access.reason} />
        <NoticeBox tone="stop" icon={<AlertTriangle className="h-5 w-5" />}>
          <p className="text-xs">
            This destroys every caller record {tenantName} holds — call numbers, summaries,
            transcripts, extracted fields, CRM leads, the records we sent to their CRM and
            the audio past its 90-day legal retention floor — and marks the client deleted.
            It cannot
            be undone. Export their data first: nothing here produces the bundle. Billing
            ledgers, consent records, do-not-call entries and the knowledge base are kept,
            and the certificate says so.
          </p>
        </NoticeBox>

        <div>
          <label htmlFor="erase-reason" className={FIELD_LABEL}>
            Why
          </label>
          <div className="mt-1">
            <textarea
              id="erase-reason"
              rows={2}
              maxLength={500}
              value={reason}
              disabled={!access.allowed}
              onChange={(event) => {
                setReason(event.target.value);
                erase.reset();
              }}
              className={FIELD}
            />
          </div>
          <span className={FIELD_HINT}>
            Recorded verbatim in the audit log, beside who asked for it.
          </span>
        </div>

        <div>
          <label htmlFor="erase-confirm" className={FIELD_LABEL}>
            Type the confirmation
          </label>
          <div className="mt-1">
            <input
              id="erase-confirm"
              value={typed}
              disabled={!access.allowed}
              autoComplete="off"
              onChange={(event) => {
                setTyped(event.target.value);
                erase.reset();
              }}
              className={FIELD}
            />
          </div>
          <span className={FIELD_HINT}>
            <code>{confirmation}</code> — the same string the API demands as a header, so a
            request cannot arrive from a screen that did not mean to send it.
          </span>
        </div>

        <button
          type="submit"
          disabled={erase.isPending || blocked || !access.allowed}
          className={PRIMARY_BUTTON}
        >
          {erase.isPending ? "Erasing…" : "Erase this client's data"}
        </button>
      </form>
      {erase.error != null && (
        <WriteFailure error={erase.error} actionLabel="Erase this client’s data" />
      )}
    </Card>
  );
}
