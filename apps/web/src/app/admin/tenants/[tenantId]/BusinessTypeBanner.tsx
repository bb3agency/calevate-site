"use client";

import { useState } from "react";
import { Store } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { FIELD, FIELD_LABEL, NoticeBox, PRIMARY_BUTTON, ProblemNotice } from "@/components/ui";
import { useAdminBusinessType, useConfirmBusinessType } from "@/lib/api/businessType";
import type { BusinessType } from "@/lib/businessTypes";

/**
 * "Confirm business type" (D-722). An account created while the wizard pre-selected a type
 * was given that type without anybody choosing it, and now runs on the neutral lead details
 * until an operator confirms one. The AI's suggestion is pre-selected and its reason shown;
 * nothing changes until Confirm is pressed.
 *
 * Renders nothing while loading, for an account with a chosen type, or on a failed read:
 * the tenant page carries on without it.
 */
export function BusinessTypeBanner({ tenantId }: { tenantId: string }) {
  const state = useAdminBusinessType(tenantId);
  const confirm = useConfirmBusinessType(tenantId);
  const write = useAdminAccess("admin:tenants", "confirm a client's business type");
  const [picked, setPicked] = useState<string | null>(null);

  if (state.isPending || state.isError) return null;
  const pending = state.data.unconfirmed;
  if (!pending) {
    return confirm.isSuccess ? (
      <p className="text-body text-ink-muted" role="status">
        Business type confirmed as {state.data.business_type_label}. Their agents now collect
        its lead details from the next call.
      </p>
    ) : null;
  }

  const choice = picked ?? pending.suggested ?? "";
  return (
    <NoticeBox
      tone="warn"
      icon={<Store aria-hidden className="h-5 w-5" />}
      title="Confirm business type"
    >
      <p className="mt-1">
        This account was set up as “{pending.given_label}” without anyone choosing it. Until you
        confirm a type, its calls collect only the standard details (name, what they want,
        preferred time, other number, language, notes).
      </p>
      {pending.suggested_label ? (
        <p className="mt-2">
          Suggested from what the business says about itself:{" "}
          <span className="font-medium text-ink">{pending.suggested_label}</span>
          {pending.reason ? ` (${pending.reason})` : ""}
        </p>
      ) : (
        <p className="mt-2 text-ink-muted">No suggestion yet. Choose the type yourself.</p>
      )}
      <form
        noValidate
        className="mt-3 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!choice) return;
          confirm.mutate({ business_type: choice as BusinessType });
        }}
      >
        <label className="w-full flex-1 sm:w-auto">
          <span className={FIELD_LABEL}>Business type</span>
          <select
            className={FIELD}
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
        </label>
        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={!write.allowed || !choice || confirm.isPending}
        >
          {confirm.isPending ? "Confirming…" : "Confirm"}
        </button>
      </form>
      {!write.allowed && write.reason && (
        <p className="mt-2 text-ink-muted">{write.reason}</p>
      )}
      {confirm.isError && (
        <div className="mt-3">
          <ProblemNotice error={confirm.error} />
        </div>
      )}
    </NoticeBox>
  );
}
