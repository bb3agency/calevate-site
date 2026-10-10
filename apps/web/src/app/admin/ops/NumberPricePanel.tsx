"use client";

import { Section } from "@/components/console/section";
import { useState } from "react";
import { CheckCircle2, CircleAlert, Lock, Phone } from "lucide-react";

import { adminAccess, useAdminMe } from "@/app/admin/access";
import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import { useFormValidation } from "@/components/formValidation";
import {
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
import { useAttestNumberPrice, useNumberPrice } from "@/lib/api/numberPricing";

/**
 * Rupees with at most two decimals, greater than zero. The server's own bound is
 * `0 < inr_per_month <= 100000` (`NumberPriceIn`); the ceiling is checked below because a
 * pattern cannot express it, and the server re-checks both.
 */
const RUPEES = "^(?:0*[1-9]\\d*(?:\\.\\d{1,2})?|0*\\.(?:0[1-9]|[1-9]\\d?))$";
const MAX_INR = "100000";

/** Above the server's ceiling, compared on the digits so a typed figure is never rounded. */
export function exceedsCeiling(amount: string): boolean {
  const [whole = "", fraction = ""] = amount.trim().split(".");
  const digits = whole.replace(/^0+/, "");
  if (digits.length !== MAX_INR.length) return digits.length > MAX_INR.length;
  return digits > MAX_INR || (digits === MAX_INR && /[1-9]/.test(fraction));
}

/**
 * The monthly price a client pays for a phone number, and the document it was read from.
 *
 * The API refuses every client number purchase until this has been recorded once
 * (hard rule 7), so this panel is the switch that opens self-serve buying on the client's
 * Phone number screen. Recording a new figure is a new attestation: numbers already bought
 * keep the price they were sold at.
 */
export function NumberPricePanel() {
  const price = useNumberPrice();
  const attest = useAttestNumberPrice();
  const me = useAdminMe();
  const access = adminAccess(me, "admin:tenants", "record what a phone number costs a client");
  const valid = useFormValidation();
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState("");
  const [overCeiling, setOverCeiling] = useState(false);

  if (isForbidden(price.error)) {
    return (
      <WithheldPanel
        title="Phone number price"
        reason={
          forbiddenReason(price.error) ??
          "The API refused this read: your admin account may not manage client pricing."
        }
        subject="This panel would show what a client pays each month for a phone number, and the document that figure was read from."
      />
    );
  }

  const current = price.data;
  const actionLabel = current?.attested ? "Record the new price" : "Record the price";

  return (
    <Section
      title="Phone number price"
      action={
        editing || !current ? undefined : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={!access.allowed}
            title={access.reason ?? undefined}
            className={SECONDARY_BUTTON_SM}
          >
            {current.attested ? "Record a new price" : "Record a price"}
          </button>
        )
      }
    >
      <div className="space-y-4">
        <p className="text-body text-ink-muted">
          What a client is charged each month for a phone number they buy from their console.
        </p>

        {price.error && <ProblemNotice error={price.error} onRetry={() => price.refetch()} />}
        {price.isLoading && <Skeleton rows={2} />}

        {current && !current.attested && (
          <NoticeBox
            tone="warn"
            icon={<CircleAlert aria-hidden className="h-5 w-5" />}
            title="No price recorded — clients cannot buy a number"
          >
            <p className="mt-1">
              A client&apos;s Buy button stays refused until a price read from the carrier&apos;s
              order form or invoice is recorded here.
            </p>
          </NoticeBox>
        )}

        {current?.attested && (
          <dl className="grid gap-3 sm:grid-cols-3">
            <div>
              <dt className="text-meta font-medium text-ink-muted">Per number, per month</dt>
              <dd className="mt-0.5 text-body font-semibold text-ink">
                {formatINR(current.inr_per_month)}
              </dd>
            </div>
            <div>
              <dt className="text-meta font-medium text-ink-muted">Read from</dt>
              <dd className="mt-0.5 text-body break-words text-ink">{current.source ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-meta font-medium text-ink-muted">Recorded</dt>
              <dd className="mt-0.5 text-body text-ink">{formatIST(current.attested_at)}</dd>
            </div>
          </dl>
        )}

        {attest.error && <WriteFailure error={attest.error} actionLabel={actionLabel} />}
        {attest.isSuccess && !editing && (
          <p className="flex items-start gap-2 text-body text-ink-muted">
            <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
            <span>Recorded. New purchases are charged this price; numbers already bought keep theirs.</span>
          </p>
        )}

        {!editing && !access.allowed && access.reason && (
          <p className="flex items-start gap-2 text-meta text-ink-muted">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {access.reason}
          </p>
        )}

        {editing && (
          <form
            className="space-y-3 border-t border-line pt-4"
            noValidate
            onSubmit={valid.onSubmit(() => {
              const tooLarge = exceedsCeiling(amount);
              setOverCeiling(tooLarge);
              if (tooLarge) return;
              attest.mutate(
                { inr_per_month: amount.trim(), source: source.trim() },
                {
                  onSuccess: () => {
                    setEditing(false);
                    setAmount("");
                    setSource("");
                  },
                },
              );
            })}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="block">
                <span className={FIELD_LABEL}>Rupees per number, per month</span>
                <input
                  {...valid.field("inr_per_month", "Enter the monthly price in rupees, like 499 or 499.50.")}
                  required
                  inputMode="decimal"
                  pattern={RUPEES}
                  value={amount}
                  onChange={(e) => {
                    setAmount(e.target.value);
                    setOverCeiling(false);
                  }}
                  disabled={!access.allowed}
                  className={`${FIELD} font-mono`}
                />
                {valid.error("inr_per_month")}
                {overCeiling && (
                  <span role="alert" className="mt-1 block text-meta text-danger">
                    That is more than ₹1,00,000 a month. Check the figure on the document.
                  </span>
                )}
              </label>
              <label className="block sm:col-span-2">
                <span className={FIELD_LABEL}>Read from</span>
                <input
                  {...valid.field("source", "Name the document the price was read from (at least 4 characters).")}
                  required
                  minLength={4}
                  maxLength={400}
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  disabled={!access.allowed}
                  placeholder="e.g. 'Vobiz order form, 2 Oct 2026'"
                  className={FIELD}
                />
                {valid.error("source")}
                <span className={FIELD_HINT}>
                  The carrier&apos;s order form, invoice or quote, and its date.
                </span>
              </label>
            </div>

            <div className="flex gap-3 border-l-2 border-danger py-1 pl-4 text-body">
              <Phone aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" />
              <p className="text-ink-muted">
                Every client who buys a number from now on is charged this on the day they buy
                it and again on each monthly renewal date: from credit on a prepaid account, on
                the invoice for a managed one. Nothing is charged while an account is in its
                trial or after it is closed. Numbers already bought keep the price they were
                sold at.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                title={access.reason ?? undefined}
                disabled={!access.allowed || attest.isPending}
                className={PRIMARY_BUTTON}
              >
                {attest.isPending ? "Recording…" : actionLabel}
              </button>
              <button
                type="button"
                disabled={attest.isPending}
                onClick={() => {
                  setEditing(false);
                  setOverCeiling(false);
                  valid.reset();
                }}
                className={SECONDARY_BUTTON}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </Section>
  );
}
