"use client";

import { useState } from "react";

import { FieldMessage, useFormValidation } from "@/components/formValidation";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import {
  FIELD_INLINE,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCallCap,
  formatINR,
} from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import { useSetCallCap, useTenantLanes, type PendingState } from "@/lib/api/publishing";

/**
 * The cost-runaway guard (§2b:107): the longest one call may run, and what that costs.
 *
 * It applies IMMEDIATELY — `set_call_cap` re-publishes a live agent in the same
 * transaction, so a cap that only landed in our table can never be shown as if the
 * engine were holding it — which is why this panel has no Apply step and says so.
 *
 * Seconds, not minutes, in the input: the column is seconds, the bounds published by
 * `/v1/agents/lanes` are seconds, and converting through minutes would silently
 * round a 330s cap set by anyone else. The minute reading is shown beside it, which
 * is the half an operator actually thinks in.
 *
 * No client-side range check beyond the input's own min/max: `call_cap_out_of_range`
 * is the server's refusal, with its own message, and a second copy of the rule here
 * is a rule that drifts.
 */
export function CallCapPanel({
  tenantId,
  agentId,
  slug,
  pending,
  write,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
  pending: PendingState | undefined;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const lanes = useTenantLanes(slug);
  const save = useSetCallCap({ tenantId, agentId, slug });
  // `null` means "not edited yet" — the field shows the server's effective cap. An
  // empty string is a real instruction (clear the override, fall back to the platform
  // default) and must not be confused with "unchanged".
  const [seconds, setSeconds] = useState<string | null>(null);
  const capValid = useFormValidation();

  const field =
    seconds ??
    (pending && !pending.call_cap_is_platform_default
      ? String(pending.effective_call_cap_s)
      : "");
  const parsed = field.trim() === "" ? null : Number(field);
  const worstCase = save.data?.worst_case_call_cost_inr ?? pending?.worst_case_call_cost_inr;
  const hasWorstCase = worstCase !== undefined && worstCase !== null;

  return (
    <div>
      <p className="max-w-prose text-body text-ink-muted">
        Applies immediately — a live agent is re-published with it, so there is nothing to
        apply. Clearing the box restores the platform default; it never means unlimited.
      </p>
      <div className="mt-4 space-y-5">
        <RestrictionNote reason={write.reason} />
        {save.error && <ProblemNotice error={save.error} />}

        {pending ? (
          <SettingRows className="border-y border-line">
            <SettingRow
              label="In force"
              value={
                <span className="tabular-nums">
                  {pending.effective_call_cap_s}s
                  <span className="ml-1 text-meta text-ink-muted">
                    ({formatCallCap(pending.effective_call_cap_s)}
                    {pending.call_cap_is_platform_default ? ", platform default" : ", set here"})
                  </span>
                </span>
              }
            />
            {/* Null is "no rate on the plan", not free: rendering ₹0 would be a lie the
                client then sees on their own screen. `formatINR` formats the digits and
                never parses them (hard rule 7). */}
            <SettingRow
              label="Worst case, one call"
              value={
                <span className="tabular-nums">
                  {hasWorstCase ? formatINR(worstCase) : "no rate on this plan"}
                </span>
              }
            />
          </SettingRows>
        ) : (
          <Skeleton rows={1} />
        )}

        <form
          className="flex flex-wrap items-end gap-3"
          noValidate
          onSubmit={capValid.onSubmit(() => {
            save.mutate({ max_call_duration_s: parsed });
          })}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="call-cap" className="text-meta text-ink-muted">
              Seconds
            </label>
            <input
              id="call-cap"
              {...capValid.track("seconds", "Enter how many seconds a call may run.")}
              type="number"
              inputMode="numeric"
              value={field}
              min={lanes.data?.call_cap_min_s}
              max={lanes.data?.call_cap_max_s}
              disabled={!write.allowed}
              onChange={(ev) => setSeconds(ev.target.value)}
              placeholder={
                lanes.data ? String(lanes.data.call_cap_default_s) : "platform default"
              }
              className={`w-32 tabular-nums ${FIELD_INLINE}`}
              aria-invalid={capValid.message("seconds") ? true : undefined}
              aria-describedby={capValid.message("seconds") ? "call-cap-error" : undefined}
            />
            {capValid.message("seconds") ? (
              <FieldMessage id="call-cap-error">{capValid.message("seconds")}</FieldMessage>
            ) : null}
          </div>
          <button
            type="submit"
            disabled={save.isPending || !write.allowed}
            className={PRIMARY_BUTTON}
          >
            {save.isPending ? "Saving…" : "Set cap"}
          </button>
          <span className="text-meta text-ink-muted">
            {parsed === null
              ? "Empty — restores the platform default."
              : `${formatCallCap(parsed)} per call.`}
            {/* Three states, not two. `lanes` supplies this input's `min`/`max`, so a
                FAILED read silently removes the bounds from a control that is still
                pressable — the operator types a value, the server refuses it, and nothing
                on the screen ever said the range was unknown. §52: failure is a refusal,
                and the refusal here is a sentence rather than a withdrawn control,
                because the server is the enforcement and blocking the field would stop
                work the operator can still legitimately do. */}
            {lanes.isError
              ? " The allowed range could not be read, so this box is unbounded here; the" +
                " server still enforces it."
              : lanes.data
                ? ` Allowed ${lanes.data.call_cap_min_s}–${lanes.data.call_cap_max_s}s; default ${lanes.data.call_cap_default_s}s.`
                : ""}
          </span>
        </form>

        {save.data && (
          <p className="text-meta text-ink-muted">
            Saved — {save.data.effective_call_cap_s}s per call
            {save.data.is_platform_default ? " (platform default)" : ""}.
            {save.data.engine_synced
              ? " The voice platform has it."
              : " The agent is not live, so nothing was sent to the voice platform."}
          </p>
        )}
      </div>
    </div>
  );
}
