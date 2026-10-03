"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert, Lock } from "lucide-react";

import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import {
  useAttestTtsPlanFee,
  useTtsPlanFees,
  type TtsPlanFeeSlot,
} from "@/app/admin/ops/ttsPlanFee";
import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useFormValidation } from "@/components/formValidation";
import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";

type Access = { allowed: boolean; reason: string | null };

/** Rupees with at most two decimals, greater than zero. The server re-checks both. */
const RUPEES = "^(?:0*[1-9]\\d*(?:\\.\\d{1,2})?|0*\\.(?:0[1-9]|[1-9]\\d?))$";

/**
 * What a voice vendor on a monthly plan billed us for one month, read off the invoice.
 *
 * The spend board's voice cost model sets this against what our own meter attributed; until
 * a month's fee is recorded the board shows no plan row for that month. It is never an input
 * to what a call is metered at. A correction is a new attestation for the same month.
 */
export function TtsPlanFeePanel({ access }: { access: Access }) {
  const [month, setMonth] = useState<string | null>(null);
  const fees = useTtsPlanFees(month);

  if (isForbidden(fees.error)) {
    return (
      <WithheldPanel
        title="Voice plan fee"
        reason={
          forbiddenReason(fees.error) ??
          "The API refused this read: your admin account may not change platform pricing."
        }
        subject="This panel would show what each voice vendor on a monthly plan billed us for a month, and the invoice it was read from."
      />
    );
  }

  const shown = fees.data?.month ?? month ?? "";

  return (
    <Card title="Voice plan fee">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          What a voice vendor on a monthly plan billed us for a month, from its invoice. The
          spend board compares it with what our calls used.
        </p>

        <label className="block max-w-xs">
          <span className={FIELD_LABEL}>Billing month</span>
          <input
            type="month"
            value={shown}
            onChange={(e) => setMonth(e.target.value || null)}
            className={FIELD}
          />
        </label>

        {fees.error && <ProblemNotice error={fees.error} onRetry={() => fees.refetch()} />}
        {fees.isLoading && <Skeleton rows={2} />}

        {!access.allowed && access.reason && (
          <p className="flex items-start gap-2 text-xs text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {access.reason}
          </p>
        )}

        {fees.data &&
          fees.data.fees.map((slot) => (
            <PlanFeeSlot key={slot.provider} slot={slot} month={shown} access={access} />
          ))}
      </div>
    </Card>
  );
}

function PlanFeeSlot({
  slot,
  month,
  access,
}: {
  slot: TtsPlanFeeSlot;
  month: string;
  access: Access;
}) {
  const attest = useAttestTtsPlanFee();
  const valid = useFormValidation();
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState("");
  const [confirm, setConfirm] = useState("");
  const current = slot.attested;
  const vendor = `${slot.tier_label} voice (${slot.provider})`;
  const actionLabel = current ? "Record the corrected fee" : "Record the fee";

  return (
    <section className="space-y-3 border-t border-line pt-4" aria-label={vendor}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">{vendor}</h3>
        {!editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={!access.allowed}
            title={access.reason ?? undefined}
            className={SECONDARY_BUTTON_SM}
          >
            {current ? "Correct this month's fee" : "Record this month's fee"}
          </button>
        )}
      </div>

      {!current && (
        <NoticeBox
          tone="warn"
          icon={<CircleAlert aria-hidden className="h-5 w-5" />}
          title={`No fee recorded for ${month}`}
        >
          <p className="mt-1">The spend board shows no plan row for this month until one is.</p>
        </NoticeBox>
      )}

      {current && (
        <dl className="grid gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-xs font-medium text-ink-faint">Billed for {current.month}</dt>
            <dd className="mt-0.5 text-sm font-semibold text-ink">{formatINR(current.plan_inr)}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-ink-faint">Read from</dt>
            <dd className="mt-0.5 text-sm break-words text-ink">{current.source_note}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-ink-faint">Recorded</dt>
            <dd className="mt-0.5 text-sm text-ink">{formatIST(current.attested_at)}</dd>
          </div>
        </dl>
      )}

      {attest.error && <WriteFailure error={attest.error} actionLabel={actionLabel} />}
      {attest.isSuccess && !editing && (
        <p className="flex items-start gap-2 text-sm text-ink-muted">
          <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
          <span>Recorded. The spend board now compares this fee with the month&apos;s usage.</span>
        </p>
      )}

      {editing && (
        <form
          className="space-y-3"
          noValidate
          onSubmit={valid.onSubmit(() => {
            if (!confirmationMatches(confirm, month) || attest.isPending) return;
            attest.mutate(
              {
                provider: slot.provider,
                month,
                // The exact string typed: no Number(), no rounding (hard rule 7).
                planInr: amount.trim(),
                sourceNote: source.trim(),
              },
              {
                onSuccess: () => {
                  setEditing(false);
                  setAmount("");
                  setSource("");
                  setConfirm("");
                },
              },
            );
          })}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className={FIELD_LABEL}>Rupees for the whole month</span>
              <input
                {...valid.field("plan_inr", "Enter the invoice total in rupees, like 440.00.")}
                required
                inputMode="decimal"
                pattern={RUPEES}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder={`${slot.reference_plan_inr} (our estimate — check the invoice)`}
                className={`${FIELD} font-mono`}
              />
              {valid.error("plan_inr")}
            </label>
            <label className="block sm:col-span-2">
              <span className={FIELD_LABEL}>Read from</span>
              <input
                {...valid.field("source_note", "Name the plan and the invoice (at least 3 characters).")}
                required
                minLength={3}
                maxLength={500}
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="e.g. Cartesia Pro plan, invoice INV-2026-09-014"
                className={FIELD}
              />
              {valid.error("source_note")}
              <span className={FIELD_HINT}>The plan, the invoice number and its date.</span>
            </label>
          </div>

          {/* The month, because it is what the fee is filed under and what the step-up
              header binds; a fixed word would be typed by reflex. */}
          <TypedConfirmation
            id={`confirm-plan-fee-${slot.provider}`}
            phrase={month}
            value={confirm}
            onChange={setConfirm}
            hint="A correction is added as a new entry; nothing is overwritten."
          />

          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              title={access.reason ?? undefined}
              disabled={
                !access.allowed || attest.isPending || !confirmationMatches(confirm, month)
              }
              className={PRIMARY_BUTTON}
            >
              {attest.isPending ? "Recording…" : actionLabel}
            </button>
            <button
              type="button"
              disabled={attest.isPending}
              onClick={() => {
                setEditing(false);
                setConfirm("");
                valid.reset();
              }}
              className={SECONDARY_BUTTON}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
