"use client";

import { useState } from "react";

import { StatusPill } from "@/components/admin/kit";
import { ActionButton } from "@/components/actionButton";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import { adminSession } from "@/lib/api/admin";
import {
  feeMonth,
  feeStatusCopy,
  useAdminPlatformFee,
  useRecordFeePayment,
  useSetFeeWaiver,
  type AdminPlatformFee,
  type PlatformFeeCharge,
} from "@/lib/api/platformFee";

/**
 * The monthly platform fee for ONE client (D-707).
 *
 * The fee itself is a platform-wide switch in the ops console — never per client — so
 * this panel does not set an amount. What an operator does here is the per-client half:
 * waive the fee with a reason (audited), withdraw a waiver, and record a fee the client
 * paid by bank transfer (audited). Every status is the server's word.
 */
export function PlatformFeePanel({ tenantId }: { tenantId: string }) {
  const fee = useAdminPlatformFee(adminSession(), tenantId);
  return (
    <Section
      title="Monthly platform fee"
      info="Switched on or off, with its amount, for every client at once in the ops console (Billing, Prices). It is paid separately from calling credit; unpaid past its grace period, the client's outgoing calls pause and incoming calls carry on."
    >
      {fee.isLoading ? (
        <Skeleton rows={3} />
      ) : fee.error || !fee.data ? (
        <ProblemNotice error={fee.error} onRetry={() => void fee.refetch()} />
      ) : (
        <FeeDetail tenantId={tenantId} fee={fee.data} />
      )}
    </Section>
  );
}

function FeeDetail({ tenantId, fee }: { tenantId: string; fee: AdminPlatformFee }) {
  return (
    <div className="space-y-6">
      <p className="text-body text-ink-muted">
        {fee.enabled && fee.amount_inr
          ? `On for the platform: ${formatINR(fee.amount_inr)} a month, ${fee.grace_days} days to pay.`
          : fee.enabled
            ? "Switched on with no amount set, so no fee is being raised for anybody."
            : "Switched off for the platform. No client is raised a fee."}
        {fee.exemption === "trial" && " This client is on a free trial, so it is not charged."}
      </p>
      {fee.moved_to_credits_at && (
        <NoticeBox tone="neutral" title="Moved from an invoiced retainer to credits">
          On {formatIST(fee.moved_to_credits_at)}. Invoices issued before then stay
          on record and are honoured; no new retainer invoice is raised.
        </NoticeBox>
      )}
      {fee.outbound_paused && (
        <NoticeBox tone="stop" title="Outgoing calls are paused for an unpaid fee">
          Incoming calls are unaffected. Recording the payment, or waiving the fee, lifts the
          pause at the next dial.
        </NoticeBox>
      )}
      <WaiverForm tenantId={tenantId} fee={fee} />
      {fee.charges.length > 0 && (
        <ul className="divide-y divide-line border-y border-line">
          {fee.charges.map((charge) => (
            <ChargeRow key={charge.id} tenantId={tenantId} charge={charge} />
          ))}
        </ul>
      )}
    </div>
  );
}

function WaiverForm({ tenantId, fee }: { tenantId: string; fee: AdminPlatformFee }) {
  const waiver = useSetFeeWaiver(adminSession(), tenantId);
  const write = useAdminAccess("admin:tenants", "waive this client's platform fee");
  const [reason, setReason] = useState("");
  const tooShort = reason.trim().length < 3;

  if (fee.waiver) {
    return (
      <div className="space-y-2">
        <NoticeBox tone="ok" title="Waived for this client">
          {fee.waiver.reason} — since {formatIST(fee.waiver.waived_at)}.
        </NoticeBox>
        <RestrictionNote reason={write.reason} />
        <ActionButton
          type="button"
          loading={waiver.isPending}
          disabled={!write.allowed}
          onClick={() => waiver.mutate(null)}
        >
          Withdraw the waiver
        </ActionButton>
        {waiver.error != null && <ProblemNotice error={waiver.error} />}
      </div>
    );
  }
  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        waiver.mutate(reason.trim());
      }}
    >
      <RestrictionNote reason={write.reason} />
      <div>
        <label htmlFor="fee-waiver-reason" className={FIELD_LABEL}>
          Waive the fee for this client — why
        </label>
        <div className="mt-1">
          <textarea
            id="fee-waiver-reason"
            rows={2}
            maxLength={280}
            value={reason}
            disabled={!write.allowed}
            onChange={(event) => setReason(event.target.value)}
            className={FIELD}
          />
        </div>
        <span className={FIELD_HINT}>Recorded verbatim in the audit log.</span>
      </div>
      <ActionButton type="submit" loading={waiver.isPending} disabled={tooShort || !write.allowed}>
        Waive the platform fee
      </ActionButton>
      {waiver.error != null && <ProblemNotice error={waiver.error} />}
    </form>
  );
}

function ChargeRow({ tenantId, charge }: { tenantId: string; charge: PlatformFeeCharge }) {
  const record = useRecordFeePayment(adminSession(), tenantId);
  const write = useAdminAccess("admin:tenants", "record a platform fee payment");
  const [reference, setReference] = useState("");
  const copy = feeStatusCopy(charge.status);
  const open = charge.status === "due" || charge.status === "overdue";
  const inputId = `fee-ref-${charge.id}`;

  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">
          {feeMonth(charge.period)} · <span className="tabular-nums">{formatINR(charge.amount_inr)}</span>
        </span>
        <StatusPill tone={copy.tone}>
          {copy.label}
        </StatusPill>
      </div>
      <p className="text-meta text-ink-muted">
        Raised {formatIST(charge.issued_at)}; grace ends {formatIST(charge.grace_ends_at)}.
        {charge.paid_at &&
          ` Paid ${formatIST(charge.paid_at)}${charge.payment_method === "manual" ? " by bank transfer" : " online"}.`}
      </p>
      {open && (
        <form
          className="flex flex-wrap items-end gap-2"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            record.mutate({ chargeId: charge.id, reference: reference.trim() });
          }}
        >
          <div>
            <label htmlFor={inputId} className={FIELD_LABEL}>
              Bank transfer reference
            </label>
            <input
              id={inputId}
              value={reference}
              disabled={!write.allowed}
              maxLength={120}
              onChange={(event) => setReference(event.target.value)}
              className={FIELD}
            />
          </div>
          <ActionButton
            type="submit"
            loading={record.isPending}
            disabled={reference.trim().length < 3 || !write.allowed}
          >
            Record bank transfer
          </ActionButton>
          {record.error != null && <ProblemNotice error={record.error} />}
        </form>
      )}
    </li>
  );
}
