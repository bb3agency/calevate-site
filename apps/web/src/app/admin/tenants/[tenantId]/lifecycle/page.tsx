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
} from "@/components/ui";
import { adminSession, useTenant } from "@/lib/api/admin";
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
          <button type="submit" disabled={move.isPending || blocked || !write.allowed} className={PRIMARY_BUTTON}>
            {move.isPending ? "Applying…" : copy.action}
          </button>
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
