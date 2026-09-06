"use client";

import Link from "next/link";
import { use, useState } from "react";
import { AlertTriangle, ArrowLeft, CalendarClock, CheckCircle2, Undo2 } from "lucide-react";

import {
  Card,
  DANGER_BUTTON,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  TypedConfirmation,
  confirmationMatches,
  formatIST,
} from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import { useClosure, useCloseAccount, useRestoreAccount } from "@/lib/api/closure";
import { useTenant } from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { useAdminAccess } from "@/app/admin/access";

/**
 * Closing a client business, and taking it back (D-538, screened by D-545).
 *
 * The API shipped with D-538 — `GET`/`POST`/`DELETE /v1/admin/tenants/{id}/closure`, the
 * client's email and WhatsApp notice, the hourly erasure sweep, the undo — and NOTHING IN
 * THIS CONSOLE CALLED ANY OF IT. The founder opened a client and found the only reachable
 * way to end the relationship was the Account state dropdown, which wrote a status and
 * told nobody. So the requirement was met by an endpoint an operator had no way to press,
 * beside a screen that did the wrong thing. This is that screen; the dropdown's `churned`
 * option is gone.
 *
 * ## What this screen has to say, beyond offering a button
 *
 * A closed account must show WHAT HAPPENS NEXT AND BY WHEN. `days_remaining` and
 * `erase_after` are computed and shipped by the server precisely so the countdown and the
 * deadline are read off ONE clock — a number derived in the browser disagrees with the
 * sweep by whatever the viewer's laptop is wrong by, and this is a countdown to
 * destruction. Neither is recomputed here.
 *
 * The UNDO is on the screen and is one click, deliberately. It carries no typed word and
 * no confirmation header, matching the API: the step-up exists to stop an unattended
 * console ENDING a client relationship, and putting a second factor in front of the
 * recovery means the operator who closed the wrong client at a coffee shop cannot fix it
 * from the same coffee shop.
 *
 * ## The two things it deliberately does NOT do
 *
 * It does not erase. That is `ops:manage`, superadmin-only, and lives on the Account state
 * screen beside the state it requires; the sweep behind `erase_after` calls the same
 * function on a timer, so there is no second eraser anywhere in the product.
 *
 * It does not promise the client's telephone number stops ringing. It does not: the number
 * is still pointed at the agent by the telephony provider until that is arranged, the
 * client's own notice says so, and a screen that implied otherwise would be the one place
 * an operator learns it from a caller instead.
 */
export default function ClosurePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const closure = useClosure(tenantId);
  const write = useAdminAccess("admin:tenants", "close or reopen a client account");

  /*
   * CLOSING ONE ACCOUNT, DECLARED TO THE SCREEN ASSISTANT.
   *
   * NO FIELDS. Every control here either ends a client relationship and starts a clock
   * that ends in the destruction of their records, or reverses one; the assistant
   * explaining what those mean is useful, and the assistant being able to put a value near
   * the reason box — which is quoted verbatim into the client's own notice email — is not.
   *
   * The closure REASON is declared as a fact even though it is operator prose, because it
   * is the one thing on this screen an operator asking "why was this closed" is here for,
   * and it was written by us rather than by the client.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/closure",
    title: "Closing the account",
    realm: "admin",
    fields: [],
    facts: closure.data
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          {
            key: "client",
            label: "Client",
            value: tenantQuery.data?.name ?? "could not be read",
          },
          { key: "status", label: "Account status", value: closure.data.status },
          {
            key: "closed_at",
            label: "Closed at",
            value: closure.data.closed_at ?? "not closed",
          },
          {
            key: "reason",
            label: "Why it was closed",
            value: closure.data.reason ?? "none recorded",
          },
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
          {
            key: "erased_at",
            label: "Records were erased at",
            value: closure.data.erased_at ?? "not erased",
          },
          {
            key: "may_close",
            label: "May this operator close or reopen the account",
            value: write.allowed ? "yes" : "no",
          },
        ]
      : [
          {
            key: "closure",
            label: "This account's closure state",
            // §52: a state we could not read is never reported as a state.
            value: closure.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  if (closure.isLoading || tenantQuery.isLoading) return <Skeleton rows={5} />;
  // §52: a failed read is a refusal, never a screen reporting a state it could not fetch.
  // "Not closed" printed over a 503, next to a Close button, is how an account gets closed
  // twice — or how an operator concludes a closure they filed never took.
  if (closure.error)
    return <ProblemNotice error={closure.error} onRetry={() => closure.refetch()} />;
  if (!closure.data) return <EmptyState title="Client not found" />;

  const record = closure.data;
  const name = tenantQuery.data?.name ?? "this client";

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">Closing the account</h1>
        <p className="text-sm text-ink-muted">
          Closing stops the account at once — nobody at the client can sign in, no outbound
          call or campaign runs, no agent can be published and no invitation can be issued
          or redeemed — and sets the date their call records, transcripts and leads are
          permanently erased. The client is emailed, and messaged on WhatsApp where they
          have opted in. Nothing is deleted on the day you close: until that date it can be
          undone from this screen.
        </p>
      </div>

      {record.erased_at != null ? (
        <ErasedNotice erasedAt={record.erased_at} />
      ) : record.closed_at != null ? (
        <ClosedPanel tenantId={tenantId} record={record} write={write} />
      ) : (
        <CloseForm tenantId={tenantId} tenantName={name} write={write} />
      )}
    </div>
  );
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
        be reopened. What remains is the erasure certificate, on the Account state screen.
      </p>
    </NoticeBox>
  );
}

/**
 * A closed account: what happens next, by when, and the way back.
 *
 * The deadline is stated in BOTH forms on purpose — the date, which is what the client was
 * told and what an operator reads back to them, and the whole days remaining, which is what
 * makes it a decision. Both come from the server's own clock.
 */
function ClosedPanel({
  tenantId,
  record,
  write,
}: {
  tenantId: string;
  record: NonNullable<ReturnType<typeof useClosure>["data"]>;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const restore = useRestoreAccount(tenantId);

  return (
    <div className="space-y-5">
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
            <dd className="inline">{formatIST(record.closed_at)}</dd>
          </div>
          <div>
            <dt className="inline font-medium">Reason given to the client: </dt>
            <dd className="inline">{record.reason ?? "none recorded"}</dd>
          </div>
          <div>
            <dt className="inline font-medium">Time left to undo: </dt>
            <dd className="inline">
              {record.days_remaining == null
                ? "no erasure is scheduled, so there is no deadline"
                : record.days_remaining === 0
                  ? "due today — the next hourly sweep will file the erasure"
                  : `${record.days_remaining} day${record.days_remaining === 1 ? "" : "s"}`}
            </dd>
          </div>
        </dl>
        <p className="mt-2 text-xs opacity-90">
          Their telephone number is still pointed at the agent by the telephony provider, so
          a caller dialling it may still be answered until that is arranged. The client&apos;s
          notice says so too.
        </p>
      </NoticeBox>

      <Card title="Reopen this account">
        {record.restorable ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-muted">
              Puts the account back to active, cancels the scheduled erasure and emails the
              client to say so. One click and no confirmation, deliberately: this destroys
              nothing, and it is the way back from the mistake the closing confirmation
              exists to prevent.
            </p>
            <RestrictionNote reason={write.reason} />
            <ActionButton
              type="button"
              loading={restore.isPending}
              disabled={!write.allowed}
              onClick={() => restore.mutate()}
            >
              <Undo2 className="mr-1.5 h-4 w-4" aria-hidden />
              Reopen the account
            </ActionButton>
            {restore.error != null && <ProblemNotice error={restore.error} />}
            {restore.data != null && restore.data.closed_at == null && (
              <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
                <p className="text-xs">
                  This account is active again and the scheduled erasure is cancelled. The
                  client has been emailed.
                </p>
              </NoticeBox>
            )}
          </div>
        ) : (
          <p className="text-sm text-ink-muted">
            This close can no longer be undone — the erasure has run.
          </p>
        )}
      </Card>
    </div>
  );
}

/**
 * The close itself.
 *
 * THE TYPED WORD IS NOT THE GUARD, and the difference matters. The guard is the
 * `X-Confirm-Action` header the API demands and the `admin:tenants` permission it checks
 * first; a dialog that exists only in this component is absent from curl. What the typing
 * buys is that the request cannot be sent by a mis-click, and that the operator has read
 * the sentence describing what it starts.
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
        className="space-y-4"
        // No rule here the browser can refuse — only `maxLength`, enforced by not
        // accepting the keystroke — and our own refusals are written beside each control.
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          // `graceDays: null` sends no `grace_days` at all, so `closure.GRACE_DAYS` on the
          // server stays the ONE place the window is decided. A console that always sent a
          // number would be a second one, and they would drift.
          close.mutate({ reason: reason.trim(), graceDays: null });
        }}
      >
        <RestrictionNote reason={write.reason} />

        <div>
          <label htmlFor="closure-reason" className={FIELD_LABEL}>
            Why this account is closing
          </label>
          <div className="mt-1">
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
          </div>
          <span className={FIELD_HINT}>
            Required, recorded verbatim in the audit log AND quoted in the email the client
            receives. Write it as something they can read: it is the only answer their
            notice gives to the only question it raises.
          </span>
        </div>

        <TypedConfirmation
          phrase="CLOSE"
          binding={`Bound to ${tenantName}. Closing sets the date their records are destroyed; it is undoable until that date and not after it.`}
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
            className={DANGER_BUTTON}
          >
            {close.isPending ? "Closing…" : "Close this account"}
          </button>
          {blocked && (
            <span className="text-xs text-amber-700 dark:text-amber-400">
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
