"use client";

import { useState } from "react";
import { CircleAlert } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Drawer } from "@/components/console/drawer";
import { Section } from "@/components/console/section";
import {
  FIELD,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useAdminAccess } from "@/app/admin/access";
import { adminSession } from "@/lib/api/admin";
import {
  grantAmountProblem,
  grantCeilingProblem,
  mintGrantRef,
  toTwoDecimals,
} from "@/lib/api/credits";
import { useMakePaid, usePaidStatus, type MakePaidResult, type PaidStatus } from "@/lib/api/paidStatus";

import { Field, describedBy } from "./fields";

/** How the account became paid, in the operator's words. Keyed by `first_paid_via`. */
const PAID_VIA: Record<string, string> = {
  wallet_topup: "their first top-up",
  manual_topup: "a payment we recorded",
  operator_conversion: "a trial we marked converted",
  complimentary: "a super admin, with no payment",
  before_d697: "a payment from before we recorded how",
};

const TRIAL_LINE: Record<PaidStatus["trial"], string> = {
  running: "Their trial is running.",
  ended: "Their trial has ended.",
  none: "They have never had a trial.",
};

/**
 * PAID OR NOT, and the super admin's act that makes an account paid without a payment
 * (D-890).
 *
 * The read is shown to every operator, because "has this client paid?" decides what the
 * rest of this screen means. The write is `billing:comp`: an operator sees why the form
 * is closed to them rather than a button that is missing.
 */
export function PaidStatusPanel({
  tenantId,
  clientName,
}: {
  tenantId: string;
  clientName: string;
}) {
  const status = usePaidStatus(adminSession(), tenantId);
  const [open, setOpen] = useState(false);

  if (status.isLoading) {
    return (
      <Section title="Paid account">
        <Skeleton rows={1} />
      </Section>
    );
  }
  if (status.isError || !status.data) {
    return (
      <Section title="Paid account">
        <ProblemNotice error={status.error} onRetry={() => status.refetch()} />
      </Section>
    );
  }
  const state = status.data;

  return (
    <Section
      title="Paid account"
      action={
        state.paid ? undefined : (
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen(true)}>
            Make paid
          </button>
        )
      }
    >
      {state.paid ? (
        <p className="text-body text-ink">
          Paid since {state.paid_at ? formatIST(state.paid_at) : "an unrecorded date"}, through{" "}
          {PAID_VIA[state.via ?? ""] ?? "an unrecorded route"}.
          {state.reason && <span className="text-ink-muted"> “{state.reason}”</span>}
        </p>
      ) : (
        <p className="text-body text-ink-muted">
          {clientName} has not paid yet. {TRIAL_LINE[state.trial]}
        </p>
      )}

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Make this account paid"
        description={clientName}
        width="lg"
      >
        <MakePaidForm tenantId={tenantId} clientName={clientName} trial={state.trial} />
      </Drawer>
    </Section>
  );
}

function MakePaidForm({
  tenantId,
  clientName,
  trial,
}: {
  tenantId: string;
  clientName: string;
  trial: PaidStatus["trial"];
}) {
  const make = useMakePaid(adminSession(), tenantId);
  const feedback = useActionFeedback(make, { errorDisplay: "inline" });
  const write = useAdminAccess("billing:comp", "make a client account paid");
  const [reason, setReason] = useState("");
  const [amountInr, setAmountInr] = useState("");
  const [confirm, setConfirm] = useState("");
  // One reference per opened form: a second click converges on it, so a retried request
  // cannot give the credit twice.
  const [grantRef] = useState(mintGrantRef);

  const amount = amountInr.trim();
  const amountProblem =
    amount === "" ? null : (grantAmountProblem(amount) ?? grantCeilingProblem(amount));
  const giving = amount !== "" && amountProblem === null;
  const confirmWord = giving ? toTwoDecimals(amount) : "";
  const confirmed = !giving || confirm.trim() === confirmWord;
  const reasonReady = reason.trim().length >= 3;
  const ready =
    write.allowed && reasonReady && amountProblem === null && confirmed && !make.data;

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) return;
        make.mutate({
          reason,
          grant: giving ? { amountInr: amount, amountConfirmation: confirm, grantRef } : null,
        });
      }}
    >
      <RestrictionNote reason={write.reason} />

      <Field
        label="Why (required)"
        id="paid-reason"
        hint="Kept on the account and sent to every super admin."
        error={null}
      >
        <textarea
          id="paid-reason"
          rows={2}
          maxLength={500}
          value={reason}
          disabled={!write.allowed}
          onChange={(event) => {
            setReason(event.target.value);
            make.reset();
          }}
          aria-describedby={describedBy("paid-reason", false)}
          className={FIELD}
        />
      </Field>

      <Field
        label="Also give credit (optional)"
        id="paid-amount"
        hint="Rupees. Leave empty to change the status only."
        error={amountProblem}
      >
        <input
          id="paid-amount"
          type="text"
          inputMode="decimal"
          value={amountInr}
          disabled={!write.allowed}
          onChange={(event) => {
            setAmountInr(event.target.value);
            setConfirm("");
            make.reset();
          }}
          aria-describedby={describedBy("paid-amount", amountProblem !== null)}
          className={FIELD}
        />
      </Field>

      {giving && (
        <Field
          label="Type the credit amount again"
          id="paid-amount-confirm"
          hint={`Type ${confirmWord}.`}
          error={null}
        >
          <input
            id="paid-amount-confirm"
            type="text"
            inputMode="decimal"
            value={confirm}
            disabled={!write.allowed}
            onChange={(event) => setConfirm(event.target.value)}
            aria-describedby={describedBy("paid-amount-confirm", false)}
            className={FIELD}
          />
        </Field>
      )}

      <div className="flex gap-3 border-l-2 border-danger py-1 pl-4 text-body">
        <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" />
        <div className="min-w-0">
          <p className="font-semibold text-ink">
            {clientName} becomes a paid account now, with no payment behind it
          </p>
          <p className="mt-1 text-ink-muted">
            {trial === "none"
              ? "Paid-only features open and their workspace is set up."
              : "Their trial is converted, nothing of theirs is erased, and their workspace is set up."}{" "}
            It is recorded as complimentary, never as money received, and cannot be undone
            here. {clientName} and every super admin are emailed.
          </p>
        </div>
      </div>

      {make.error != null && <WriteFailure error={make.error} actionLabel="Make paid" />}
      {make.data && <MadePaid result={make.data} clientName={clientName} />}

      <ActionButton
        type="submit"
        status={feedback.status}
        pendingLabel="Making paid…"
        successLabel="Paid"
        disabled={!ready}
      >
        {giving ? `Make paid and give ${formatINR(confirmWord)}` : "Make paid"}
      </ActionButton>
    </form>
  );
}

function MadePaid({ result, clientName }: { result: MakePaidResult; clientName: string }) {
  return (
    <NoticeBox tone="ok" title={`${clientName} is now a paid account`}>
      <p className="mt-1">
        {result.trial_converted ? "Their trial is converted. " : ""}
        {result.workspace_queued ? "Their workspace is being set up. " : ""}
        {result.grant ? `${formatINR(result.grant.amount_inr)} given; balance ${formatINR(result.grant.balance_inr)}.` : ""}
      </p>
    </NoticeBox>
  );
}
