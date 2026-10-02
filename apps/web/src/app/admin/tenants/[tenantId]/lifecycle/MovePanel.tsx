"use client";

import { useState } from "react";

import { Card, FIELD, FIELD_HINT, FIELD_LABEL, RestrictionNote } from "@/components/ui";
import { ActionButton } from "@/components/actionButton";
import type { useAdminAccess } from "@/app/admin/access";
import {
  LIFECYCLE_COPY,
  type LifecycleStatus,
  type useSetTenantStatus,
} from "@/lib/api/commercials";

const CHOICES = Object.keys(LIFECYCLE_COPY) as LifecycleStatus[];

/**
 * The one move available from the account's current state.
 *
 * An active account can only be suspended and a suspended one only reactivated, so a
 * dropdown whose other option is the state the account is already in asks a question
 * nobody has. Any other status (`organizations.status` has five) keeps the choice, because
 * from there either move is real.
 *
 * Closing is not here and must not come back (D-546): it is on Closing the account, which
 * tells the client, sets the erasure date and can be undone. Both moves left here are
 * reversible, so neither carries a typed confirmation — ceremony on a reversible act
 * teaches operators to type past ceremony.
 */
export function MovePanel({
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
  const fixed: LifecycleStatus | null =
    currentStatus === "active" ? "suspended" : currentStatus === "suspended" ? "active" : null;
  const [chosen, setChosen] = useState<LifecycleStatus>("suspended");
  const status = fixed ?? chosen;
  const [reason, setReason] = useState("");
  const copy = LIFECYCLE_COPY[status];
  // The API refuses a reasonless suspension with a 422; this previews it.
  const blocked = copy.needsReason && reason.trim().length < 3;

  return (
    <Card title={fixed ? `${copy.action} ${tenantName}` : `Move ${tenantName}`}>
      <form
        className="max-w-xl space-y-4"
        // Our own refusals are written beside each control; `noValidate` keeps a rule added
        // later from being answered in the browser's language instead.
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          move.mutate({ status, reason: reason.trim() === "" ? null : reason.trim() });
        }}
      >
        <RestrictionNote reason={write.reason} />

        {fixed ? (
          <p className="text-sm text-ink">{copy.consequence}</p>
        ) : (
          <div>
            <label htmlFor="lifecycle-status" className={FIELD_LABEL}>
              New state
            </label>
            <select
              id="lifecycle-status"
              value={status}
              disabled={!write.allowed}
              onChange={(event) => {
                setChosen(event.target.value as LifecycleStatus);
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
            <span className={FIELD_HINT}>{copy.consequence}</span>
          </div>
        )}

        {copy.needsReason && (
          <div>
            <label htmlFor="lifecycle-reason" className={FIELD_LABEL}>
              Why
            </label>
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
            <span className={FIELD_HINT}>
              Required, and recorded verbatim in the audit log. Somebody will have to answer
              &quot;why is this account stopped&quot; later.
            </span>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          {/* The label stays mounted while pending so the button's accessible name never
              flickers to "Applying…" mid-request. */}
          <ActionButton
            type="submit"
            loading={move.isPending}
            disabled={blocked || !write.allowed}
            className="max-sm:w-full max-sm:justify-center"
          >
            {copy.action}
          </ActionButton>
          {blocked && (
            <span className="text-xs text-warn">A reason is required before this can be applied.</span>
          )}
        </div>
      </form>
    </Card>
  );
}
