"use client";

import { ServiceLogo } from "@/components/console/serviceLogo";
import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { ADMIN_PAGE, HAIRLINE_LIST, StatusPill, sentenceCase } from "@/components/admin/kit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { FileDrop } from "@/components/fileDrop";
import { lookup } from "@/lib/lookup";
import { CopyButton } from "@/components/interior/copy-button";
import {
  FIELD,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import {
  EVIDENCE_KINDS,
  type Dispute,
  useAcceptDispute,
  useContestDispute,
  useDisputes,
  usePaymentStatus,
  useRecentPayments,
  useRunReconciliation,
} from "@/lib/api/adminPayments";

/** `payment_admin_routes._EVIDENCE_TYPES` and `_EVIDENCE_MAX_BYTES`: what the API accepts. */
const EVIDENCE_ACCEPT = "application/pdf,image/jpeg,image/png";
const EVIDENCE_MAX_BYTES = 5 * 1024 * 1024;

/** The public API host Razorpay posts to; the path comes from the status read. */
const WEBHOOK_HOST = "https://api.calevate.tech";

/**
 * Payments (D-699): is Razorpay set up and in which mode, what to register as the webhook,
 * the payment alarms, the reconciliation, recent payments and every client's disputes.
 * Refunds stay on each client's credits page.
 *
 * Disputes come first after the set-up: an open dispute has a respond-by date and money
 * held against it, while reconciliation runs on its own every day.
 */
export function PaymentsScreen() {
  const access = useAdminAccess("org:read", "see payments");
  const operator = useAdminAccess("admin:tenants", "act on payments");
  const status = usePaymentStatus(!access.refused);
  const [showRecent, setShowRecent] = useState(false);
  const recent = useRecentPayments(showRecent && !access.refused);
  const [showClosed, setShowClosed] = useState(false);
  const disputes = useDisputes(showClosed, !access.refused);
  const reconcile = useRunReconciliation();

  if (access.refused) return <RestrictionNote reason={access.reason} />;

  return (
    <div className={ADMIN_PAGE}>
      <PageHeader description="Is Razorpay taking payments, and what needs an answer from us. Refunds are on each client's Credits page." />

      <Section
      title={
        <span className="inline-flex items-center gap-2">
          <ServiceLogo service="razorpay" className="h-5 w-5" />
          Razorpay set-up
        </span>
      }
    >
        {status.isLoading ? (
          <Skeleton rows={3} label="Reading the payment set-up" />
        ) : status.data ? (
          <div className="space-y-4">
            <NoticeBox
              tone={status.data.online_payments_available ? "ok" : "warn"}
              title={
                status.data.online_payments_available
                  ? `Taking payments in ${status.data.mode ?? "unset"} mode`
                  : "Payments are not available"
              }
            >
              {status.data.unavailable_reason && <p>Reason: {status.data.unavailable_reason}</p>}
              {status.data.mode && status.data.key_id_mode && status.data.mode !== status.data.key_id_mode && (
                <p>The key id belongs to {status.data.key_id_mode} mode, not {status.data.mode}.</p>
              )}
            </NoticeBox>
            <SettingRows className="border-y border-line">
              <SettingRow
                label="Key id"
                value={status.data.key_id_set ? `Set (${status.data.key_id_mode ?? "unknown mode"})` : "Not set"}
              />
              <SettingRow label="Key secret" value={status.data.key_secret_set ? "Set" : "Not set"} />
              <SettingRow label="Webhook secret" value={status.data.webhook_secret_set ? "Set" : "Not set"} />
              <SettingRow
                label="Orders"
                value={status.data.provider_orders_available ? "Can be created" : "Cannot be created"}
              />
              <SettingRow
                label="Webhook URL"
                info="Register this address in the Razorpay dashboard, with the events below ticked."
                value={<MonoValue>{`${WEBHOOK_HOST}${status.data.webhook_path}`}</MonoValue>}
                action={<CopyButton value={`${WEBHOOK_HOST}${status.data.webhook_path}`} label="Copy webhook URL" />}
              />
            </SettingRows>
            <details className="group">
              <summary className={`${TEXT_ACTION} cursor-pointer list-none`}>
                Events to tick in the Razorpay dashboard
              </summary>
              <p className="mt-2 font-mono text-xs text-ink-muted">{status.data.subscribed_events.join(", ")}</p>
            </details>
          </div>
        ) : (
          <ProblemNotice error={status.error} />
        )}
      </Section>

      <Section
        title="Disputes"
        description="Chargebacks on any client's payment. Answer before the respond-by date or the bank decides without us."
        action={
          <label className="flex items-center gap-2 text-meta text-ink-muted touch:min-h-11">
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
            Show resolved disputes
          </label>
        }
      >
        {disputes.isLoading ? (
          <Skeleton rows={2} label="Loading disputes" />
        ) : disputes.data && disputes.data.length > 0 ? (
          <ul aria-label="Disputes" className={HAIRLINE_LIST}>
            {disputes.data.map((d) => (
              <DisputeRow key={d.dispute_id} dispute={d} canAct={operator.allowed} />
            ))}
          </ul>
        ) : disputes.data ? (
          <EmptyState message="No disputes." />
        ) : (
          <ProblemNotice error={disputes.error} />
        )}
      </Section>

      <Section
        title="Reconciliation"
        info="Runs daily. Compares Razorpay's payments and refunds with the ledger, credits a payment whose webhook was lost, and raises an alarm for anything it cannot explain."
        description="Matches Razorpay against our ledger every day."
        action={
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!operator.allowed || reconcile.isPending}
            onClick={() => reconcile.mutate()}
          >
            {reconcile.isPending ? "Running…" : "Run reconciliation now"}
          </button>
        }
      >
        <div className="space-y-4">
          <ProblemNotice error={reconcile.error} />
          {reconcile.data && (
            <SettingRows className="border-y border-line">
              <SettingRow
                label="Checked"
                value={`${reconcile.data.payments_seen} payments and ${reconcile.data.refunds_seen} refunds over ${reconcile.data.window_days} days.`}
              />
              <SettingRow label="Credited late" value={reconcile.data.credited_late.join(", ") || "None"} />
              <SettingRow
                label="Refunds recorded late"
                value={reconcile.data.refunds_recorded_late.join(", ") || "None"}
              />
              <SettingRow label="Unexplained" value={reconcile.data.unexplained.join(", ") || "None"} />
              <SettingRow
                label="Settlements"
                value={`${reconcile.data.settlements}, ${formatINR(reconcile.data.settled_inr)}`}
              />
            </SettingRows>
          )}
          {status.data && status.data.alarms.length > 0 && (
            <div>
              <h3 className="text-body font-semibold text-ink">Payment alarms, last 7 days</h3>
              <ul className={`mt-2 ${HAIRLINE_LIST}`}>
                {status.data.alarms.map((alarm) => (
                  <li
                    key={`${alarm.code}-${alarm.last_seen_at}`}
                    className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-meta"
                  >
                    <span className="font-mono text-ink">{alarm.code}</span>
                    <span className="text-ink-muted">
                      {alarm.severity} · {alarm.occurrences}× · last {formatIST(alarm.last_seen_at)}
                      {alarm.open ? " · open" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Section>

      <Section
      title={
        <span className="inline-flex items-center gap-2">
          <ServiceLogo service="razorpay" className="h-5 w-5" />
          Recent payments at Razorpay
        </span>
      }
      description="Read live from Razorpay when you ask for it."
    >
        {showRecent ? (
          recent.data ? (
            recent.data.length === 0 ? (
              <EmptyState message="No payments in the last three days." />
            ) : (
              <ul aria-label="Recent payments" className={HAIRLINE_LIST}>
                {recent.data.map((p) => (
                  <li
                    key={p.payment_id}
                    className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-meta"
                  >
                    <span className="font-mono text-ink">{p.payment_id}</span>
                    <span className="text-ink-muted">
                      {p.status} · {formatINR(p.amount_inr)} · {p.method ?? "?"}
                      {p.international ? " · international" : ""} ·{" "}
                      {p.tenant_id ? `client ${p.tenant_id}` : "no order record"}
                    </span>
                  </li>
                ))}
              </ul>
            )
          ) : recent.isLoading ? (
            <Skeleton rows={3} label="Reading Razorpay" />
          ) : (
            <ProblemNotice error={recent.error} />
          )
        ) : (
          <button type="button" className={SECONDARY_BUTTON} onClick={() => setShowRecent(true)}>
            Load the last three days
          </button>
        )}
      </Section>
    </div>
  );
}

const DISPUTE_TONE: Record<string, "warn" | "stop" | "neutral" | "ok"> = {
  open: "stop",
  under_review: "warn",
  won: "ok",
  lost: "neutral",
  closed: "neutral",
};

function DisputeRow({ dispute, canAct }: { dispute: Dispute; canAct: boolean }) {
  const accept = useAcceptDispute();
  const contest = useContestDispute();
  const [responding, setResponding] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [summary, setSummary] = useState("");
  const [kind, setKind] = useState(EVIDENCE_KINDS[0]?.value ?? "billing_proof");
  const [files, setFiles] = useState<File[]>([]);
  const open = dispute.status === "open" || dispute.status === "under_review";
  const formId = `dispute-${dispute.dispute_id}`;

  return (
    <li className="py-3.5 sm:px-2">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-body font-medium text-ink">
            <span>
              {dispute.tenant_name ?? dispute.tenant_id} · {formatINR(dispute.amount_inr)}
            </span>
            <StatusPill tone={lookup(DISPUTE_TONE, dispute.status) ?? "neutral"}>{sentenceCase(dispute.status)}</StatusPill>
            {dispute.action_required && <StatusPill tone="warn">More evidence asked for</StatusPill>}
          </p>
          <p className="mt-0.5 text-meta text-ink-muted">
            Payment <span className="font-mono">{dispute.payment_id}</span> · held {formatINR(dispute.hold_inr)} ·
            reason {dispute.reason_code ?? "not given"}
            {dispute.respond_by ? ` · respond by ${formatIST(dispute.respond_by)}` : ""}
          </p>
        </div>
        {open && canAct && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <button
              type="button"
              className={TEXT_ACTION_DANGER}
              disabled={accept.isPending}
              onClick={() => setAccepting(true)}
            >
              Accept (refunds the customer; cannot be undone)
            </button>
            {!responding && (
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-expanded={false}
                aria-controls={formId}
                onClick={() => setResponding(true)}
              >
                Contest
              </button>
            )}
          </div>
        )}
      </div>
      {open && canAct && responding && (
        <div id={formId} className="mt-4 max-w-xl space-y-4">
          <label className="block">
            <span className={FIELD_LABEL}>Summary for the bank</span>
            <textarea className={FIELD} value={summary} onChange={(e) => setSummary(e.target.value)} />
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Evidence type</span>
            <select className={FIELD} value={kind} onChange={(e) => setKind(e.target.value)}>
              {EVIDENCE_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          <FileDrop
            label="Evidence documents"
            hint="PDF, JPEG or PNG, up to 5 MB each."
            accept={EVIDENCE_ACCEPT}
            maxBytes={EVIDENCE_MAX_BYTES}
            multiple
            disabled={contest.isPending}
            onFiles={(picked) => setFiles((held) => [...held, ...picked])}
            files={files}
            onRemove={(index) => setFiles((held) => held.filter((_, i) => i !== index))}
          />
          {contest.error ? <ProblemNotice error={contest.error} /> : null}
          <div className="flex flex-wrap items-center justify-end gap-3">
            <div className="flex flex-wrap gap-2">
              <button type="button" className={SECONDARY_BUTTON} onClick={() => setResponding(false)}>
                Cancel
              </button>
              <button
                type="button"
                className={PRIMARY_BUTTON}
                disabled={contest.isPending || summary.trim().length < 10 || files.length === 0}
                onClick={() =>
                  contest.mutate({
                    disputeId: dispute.dispute_id,
                    summary,
                    evidenceKind: kind,
                    files,
                    amountInr: "",
                  })
                }
              >
                Contest with evidence
              </button>
            </div>
          </div>
        </div>
      )}
      {/* The refund leaves the platform's account the moment the bank is told, so the
          operator sees the amount and the client once more before it goes. */}
      {accepting && (
        <ConfirmDialog
          title="Accept this dispute?"
          confirmLabel="Accept and refund"
          pendingLabel="Accepting…"
          cancelLabel="Keep the dispute open"
          pending={accept.isPending}
          error={accept.error}
          onCancel={() => {
            accept.reset();
            setAccepting(false);
          }}
          onConfirm={() => accept.mutate(dispute.dispute_id, { onSuccess: () => setAccepting(false) })}
        >
          <p>
            {formatINR(dispute.amount_inr)} goes back to {dispute.tenant_name ?? dispute.tenant_id}&apos;s
            customer. This cannot be undone.
          </p>
        </ConfirmDialog>
      )}
    </li>
  );
}
