"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FIELD, NoticeBox, ProblemNotice } from "@/components/ui";
import {
  useAdminBusinessType,
  useBusinessTypePoll,
  useConfirmBusinessType,
  useSuggestBusinessTypeAgain,
} from "@/lib/api/businessType";
import type { BusinessType } from "@/lib/businessTypes";

/**
 * "Business type not confirmed" (D-722), as one quiet bar: the line, the AI's suggestion,
 * and the picker with Confirm inline. Why it matters sits behind the ⓘ. Nothing changes
 * until Confirm is pressed. "Suggest again" asks the AI once more (ops:manage, audited,
 * our cost) and polls for the answer.
 *
 * Renders nothing while loading, for an account with a chosen type, or on a failed read:
 * the tenant page carries on without it.
 */
export function BusinessTypeBanner({ tenantId }: { tenantId: string }) {
  const state = useAdminBusinessType(tenantId);
  const confirm = useConfirmBusinessType(tenantId);
  const suggest = useSuggestBusinessTypeAgain(tenantId);
  const confirmFeedback = useActionFeedback(confirm, { errorDisplay: "inline" });
  const suggestFeedback = useActionFeedback(suggest, { errorDisplay: "inline" });
  const [askedAt, setAskedAt] = useState<number | null>(null);
  useBusinessTypePoll(tenantId, askedAt);
  const write = useAdminAccess("admin:tenants", "confirm a client's business type");
  const ask = useAdminAccess("ops:manage", "ask the AI for a business type again");
  const [picked, setPicked] = useState<string | null>(null);

  if (state.isPending || state.isError) return null;
  const pending = state.data.unconfirmed;
  if (!pending) {
    return confirm.isSuccess ? (
      <p className="text-body text-ink-muted" role="status">
        Business type confirmed as {state.data.business_type_label}. Agents collect its lead
        details from the next call.
      </p>
    ) : null;
  }

  const choice = picked ?? pending.suggested ?? "";
  const waiting =
    askedAt !== null &&
    Date.now() - askedAt < 60_000 &&
    !(pending.suggested_at && Date.parse(pending.suggested_at) >= askedAt);
  return (
    <div className="space-y-2">
      <NoticeBox
        tone="warn"
        title="Business type not confirmed"
        info={
          <>
            <p>
              This account was set up as “{pending.given_label}” without anyone choosing it.
            </p>
            <p>
              Until a type is confirmed, calls collect only the standard details: name, what
              they want, preferred time, other number, language and notes.
            </p>
          </>
        }
        action={
          <form
            noValidate
            className="flex w-full items-center gap-2 sm:w-auto"
            onSubmit={(event) => {
              event.preventDefault();
              if (!choice) return;
              confirm.mutate({ business_type: choice as BusinessType });
            }}
          >
            <label className="sr-only" htmlFor={`business-type-${tenantId}`}>
              Business type
            </label>
            <select
              id={`business-type-${tenantId}`}
              className={FIELD.replace("mt-1 w-full", "min-w-0 flex-1 sm:w-auto sm:min-w-48 sm:flex-none")}
              value={choice}
              onChange={(event) => setPicked(event.target.value)}
              disabled={!write.allowed || confirm.isPending}
            >
              <option value="" disabled>
                Choose a type
              </option>
              {state.data.choices.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <ActionButton
              type="submit"
              status={confirmFeedback.status}
              pendingLabel="Confirming…"
              successLabel="Confirmed"
              disabled={!write.allowed || !choice}
            >
              Confirm
            </ActionButton>
          </form>
        }
      >
        <p>Calls collect standard details until you choose one.</p>
        <p className="flex flex-wrap items-center gap-x-3">
          <span>
            {waiting ? (
              <span className="text-shimmer">Asking for a suggestion…</span>
            ) : pending.suggested_label ? (
              <>
                Suggested: <span className="font-medium text-ink">{pending.suggested_label}</span>
                {pending.reason ? ` (${pending.reason})` : ""}
              </>
            ) : (
              "No suggestion yet."
            )}
          </span>
          {ask.allowed && !waiting && (
            <ActionButton
              variant="secondary-sm"
              status={suggestFeedback.status}
              successLabel="Asked"
              onClick={() =>
                suggest.mutate(undefined, { onSuccess: () => setAskedAt(Date.now()) })
              }
            >
              Suggest again
            </ActionButton>
          )}
        </p>
        {!write.allowed && write.reason && <p>{write.reason}</p>}
      </NoticeBox>
      <ProblemNotice error={confirm.error} />
      <ProblemNotice error={suggest.error} />
    </div>
  );
}
