"use client";

import { useState } from "react";
import { AlertTriangle, CalendarClock, CheckCircle2, Undo2 } from "lucide-react";

import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import {
  Card,
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { useAdminAccess } from "@/app/admin/access";
import { useCachedTenant } from "@/lib/api/admin";
import { useClosure, useCloseAccount, useRestoreAccount, type Closure } from "@/lib/api/closure";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { TonePill } from "../tonePill";
import { ErasurePanel } from "./ErasurePanel";

/**
 * Closing a client business, taking it back, and — once closed — erasing it (D-538, D-546).
 *
 * The screen's job beyond its buttons is to say WHAT HAPPENS NEXT AND BY WHEN. The deadline
 * and the countdown (`erase_after`, `days_remaining`) are the server's, read off the same
 * clock as the hourly erasure sweep, and are never recomputed here: a countdown to
 * destruction derived on the viewer's laptop disagrees with the sweep.
 *
 * Reopening is one click with no confirmation, matching the API: the step-up exists to stop
 * an unattended console ENDING a relationship, and a second factor on the recovery path
 * means the operator who closed the wrong client cannot fix it from where they stand.
 *
 * It does not promise the client's telephone number stops ringing, because it does not:
 * the provider still points it at the agent until that is arranged.
 */
export function ClosureScreen({ tenantId }: { tenantId: string }) {
  // The cache only: on an erased client the layout's read is a 404 it deliberately mounts past.
  const tenantQuery = useCachedTenant(tenantId);
  const closure = useClosure(tenantId);
  const restore = useRestoreAccount(tenantId);
  const write = useAdminAccess("admin:tenants", "close or reopen a client account");
  // `ops:manage` is the superadmin marker the API checks IN ADDITION to `admin:tenants`
  // before it will erase; previewed so the reason is on screen before anything is typed.
  const erase = useAdminAccess("ops:manage", "erase a client's data");

  /*
   * No fields: every control here ends a relationship (and starts a clock that ends in the
   * destruction of records), reverses one, or erases. The closure REASON is declared as a
   * fact because "why was this closed" is what an operator asking is here for, and it was
   * written by us.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/closure",
    title: "Closing the account",
    realm: "admin",
    fields: [],
    facts: closure.data
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "client", label: "Client", value: tenantQuery.data?.name ?? "could not be read" },
          { key: "status", label: "Account status", value: closure.data.status },
          { key: "closed_at", label: "Closed at", value: closure.data.closed_at ?? "not closed" },
          { key: "reason", label: "Why it was closed", value: closure.data.reason ?? "none recorded" },
          {
            key: "erase_after",
            label: "Records are erased on",
            value: closure.data.erase_after ?? "no erasure scheduled",
          },
          {
            key: "days_remaining",
            label: "Whole days until the erasure is due",
            value:
              closure.data.days_remaining == null
                ? "not applicable"
                : String(closure.data.days_remaining),
          },
          {
            key: "restorable",
            label: "Can this close still be undone (nothing has been erased)",
            value: closure.data.restorable ? "yes" : "no",
          },
          { key: "erased_at", label: "Records were erased at", value: closure.data.erased_at ?? "not erased" },
          {
            key: "may_close",
            label: "May this operator close or reopen the account",
            value: write.allowed ? "yes" : "no",
          },
          {
            key: "may_erase",
            label: "May this operator erase the account's data (needs ops:manage too)",
            value: erase.allowed ? "yes" : "no",
          },
        ]
      : [
          {
            key: "closure",
            label: "This account's closure state",
            value: closure.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  if (closure.isLoading) return <Skeleton rows={5} />;
  // §52: "Not closed" printed over a 503, next to a Close button, is how an account gets
  // closed twice — or how an operator concludes a closure they filed never took.
  if (closure.error) return <ProblemNotice error={closure.error} onRetry={() => closure.refetch()} />;
  if (!closure.data) return <EmptyState message="This client's closure state was not found." />;

  const record = closure.data;
  const name = tenantQuery.data?.name ?? "this client";
  const reopenable = record.closed_at != null && record.erased_at == null && record.restorable;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Closing the account"
        status={<ClosureStatus record={record} />}
        description={
          record.closed_at == null
            ? "End this client's relationship. It can be undone until their records are erased."
            : undefined
        }
        actions={
          reopenable ? (
            <ActionButton
              type="button"
              loading={restore.isPending}
              disabled={!write.allowed}
              onClick={() => restore.mutate()}
            >
              <Undo2 className="mr-1.5 h-4 w-4" aria-hidden />
              Reopen the account
            </ActionButton>
          ) : undefined
        }
      />

      {/* Outside the closed branch on purpose: the successful reopen re-reads the closure,
          which swaps the branch, and the confirmation must survive that swap. */}
      {restore.data != null && restore.data.closed_at == null && (
        <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
          <p className="text-xs">
            This account is active again and the scheduled erasure is cancelled. The client
            has been emailed.
          </p>
        </NoticeBox>
      )}

      {record.erased_at != null ? (
        <>
          <ErasedNotice erasedAt={record.erased_at} />
          <ErasurePanel tenantId={tenantId} tenantName={name} access={erase} />
        </>
      ) : record.closed_at != null ? (
        <>
          {reopenable && (
            <div className="space-y-3">
              <p className="text-sm text-ink-muted">
                Reopening puts the account back to active, cancels the scheduled erasure and
                emails the client.{" "}
                <InfoTip label="reopening">
                  <p>
                    One click and no confirmation, deliberately: reopening destroys nothing,
                    and it is the way back from the mistake the closing confirmation exists
                    to prevent.
                  </p>
                </InfoTip>
              </p>
              <RestrictionNote reason={write.reason} />
              {restore.error != null && <ProblemNotice error={restore.error} />}
            </div>
          )}
          <ClosedPanel record={record} />
          <ErasurePanel tenantId={tenantId} tenantName={name} access={erase} />
        </>
      ) : (
        <CloseForm tenantId={tenantId} tenantName={name} write={write} />
      )}
    </div>
  );
}

/** The state in a few words, off the server's clock. */
function ClosureStatus({ record }: { record: Closure }) {
  if (record.erased_at != null) return <TonePill tone="stop">Erased</TonePill>;
  if (record.closed_at == null) return null;
  const left =
    record.days_remaining == null
      ? null
      : record.days_remaining === 0
        ? "erasure due today"
        : `${record.days_remaining} day${record.days_remaining === 1 ? "" : "s"} to undo`;
  return <TonePill tone="stop">{left ? `Closed · ${left}` : "Closed"}</TonePill>;
}

/** Past the point of any undo. Said once, plainly, with nothing to press. */
function ErasedNotice({ erasedAt }: { erasedAt: string }) {
  return (
    <NoticeBox
      tone="stop"
      icon={<AlertTriangle className="h-5 w-5" />}
      title="This client's records have been erased"
    >
      <p className="mt-1 text-xs opacity-90">
        The erasure ran on {formatIST(erasedAt)}. It cannot be undone and the account cannot
        be reopened. What remains is the erasure certificate, below.
      </p>
    </NoticeBox>
  );
}

/**
 * A closed account: what happens next and by when. The deadline is stated as the date
 * (what the client was told) and the whole days left (what makes it a decision).
 */
function ClosedPanel({ record }: { record: Closure }) {
  return (
    <NoticeBox
      tone="stop"
      icon={<CalendarClock className="h-5 w-5" />}
      title={
        record.erase_after
          ? `Closed. Records are erased on ${formatIST(record.erase_after)}`
          : "Closed. No erasure is scheduled"
      }
    >
      <dl className="mt-2 space-y-1 text-xs opacity-90">
        <div>
          <dt className="inline font-medium">Closed at: </dt>
          <dd className="inline">{record.closed_at ? formatIST(record.closed_at) : "—"}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Reason given to the client: </dt>
          <dd className="inline">{record.reason ?? "none recorded"}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Time left to undo: </dt>
          <dd className="inline">
            {!record.restorable
              ? "none — this close can no longer be undone"
              : record.days_remaining == null
                ? "no erasure is scheduled, so there is no deadline"
                : record.days_remaining === 0
                  ? "due today — the next hourly sweep will file the erasure"
                  : `${record.days_remaining} day${record.days_remaining === 1 ? "" : "s"}`}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-xs opacity-90">
        Their telephone number is still pointed at the agent by the telephony provider, so a
        caller dialling it may still be answered until that is arranged. The client&apos;s
        notice says so too.
      </p>
    </NoticeBox>
  );
}

/**
 * The close itself. What it does is stated ABOVE the controls, verbatim, because it is the
 * consequence of the button. The typed word is not the guard (the `X-Confirm-Action` header
 * and `admin:tenants` are); it stops a mis-click and proves the sentence was in front of
 * the operator.
 */
function CloseForm({
  tenantId,
  tenantName,
  write,
}: {
  tenantId: string;
  tenantName: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const close = useCloseAccount(tenantId);
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const reasonMissing = reason.trim().length < 3;
  const wordMissing = !confirmationMatches(typed, "CLOSE");
  const blocked = reasonMissing || wordMissing;

  return (
    <Card title={`Close ${tenantName}`}>
      <form
        className="max-w-xl space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          // `graceDays: null` sends no `grace_days`, so the server's GRACE_DAYS stays the
          // one place the window is decided.
          close.mutate({ reason: reason.trim(), graceDays: null });
        }}
      >
        <p className="text-sm text-ink">
          Closing stops the account at once — nobody at the client can sign in, no outbound
          call or campaign runs, no agent can be published and no invitation can be issued
          or redeemed — and sets the date their call records, transcripts and leads are
          permanently erased. The client is emailed, and messaged on WhatsApp where they
          have opted in. Nothing is deleted on the day you close: until that date it can be
          undone from this screen.
        </p>

        <RestrictionNote reason={write.reason} />

        <div>
          <label htmlFor="closure-reason" className={FIELD_LABEL}>
            Why this account is closing
          </label>
          <textarea
            id="closure-reason"
            rows={3}
            maxLength={500}
            value={reason}
            disabled={!write.allowed}
            onChange={(event) => {
              setReason(event.target.value);
              close.reset();
            }}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            Required, recorded verbatim in the audit log AND quoted in the email the client
            receives. Write it as something they can read: it is the only answer their notice
            gives to the only question it raises.
          </span>
        </div>

        <TypedConfirmation
          phrase="CLOSE"
          hint={`Bound to ${tenantName}. Closing sets the date their records are destroyed; it is undoable until that date and not after it.`}
          value={typed}
          onChange={(value) => {
            setTyped(value);
            close.reset();
          }}
          disabled={!write.allowed}
        />

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={close.isPending || blocked || !write.allowed}
            className={`${DANGER_BUTTON} max-sm:w-full max-sm:justify-center`}
          >
            {close.isPending ? "Closing…" : "Close this account"}
          </button>
          {blocked && (
            <span className="text-xs text-warn">
              {reasonMissing
                ? "A reason is required — the client is sent it."
                : "Type CLOSE above to confirm before this can be applied."}
            </span>
          )}
        </div>
      </form>

      {close.error != null && <ProblemNotice error={close.error} />}
    </Card>
  );
}
