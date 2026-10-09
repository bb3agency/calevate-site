"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { FileDrop } from "@/components/fileDrop";
import {
  Card,
  DANGER_BUTTON,
  FIELD,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
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

/**
 * Payments (D-699): is Razorpay set up and in which mode, what to register as the webhook,
 * the payment alarms, the reconciliation, recent payments and every client's disputes.
 * Refunds stay on each client's credits page.
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
    <div className="space-y-6">
      <Card title="Razorpay set-up">
        {status.isLoading ? (
          <Skeleton rows={3} label="Reading the payment set-up" />
        ) : status.data ? (
          <div className="space-y-3 text-sm">
            <NoticeBox
              tone={status.data.online_payments_available ? "ok" : "warn"}
              title={
                status.data.online_payments_available
                  ? `Taking payments in ${status.data.mode ?? "unset"} mode`
                  : "Payments are not available"
              }
            >
              {status.data.unavailable_reason && (
                <p>Reason: {status.data.unavailable_reason}</p>
              )}
              {status.data.mode && status.data.key_id_mode && status.data.mode !== status.data.key_id_mode && (
                <p>The key id belongs to {status.data.key_id_mode} mode, not {status.data.mode}.</p>
              )}
            </NoticeBox>
            <ul className="grid gap-1 sm:grid-cols-2">
              <li>Key id: {status.data.key_id_set ? `set (${status.data.key_id_mode ?? "unknown mode"})` : "not set"}</li>
              <li>Key secret: {status.data.key_secret_set ? "set" : "not set"}</li>
              <li>Webhook secret: {status.data.webhook_secret_set ? "set" : "not set"}</li>
              <li>Orders: {status.data.provider_orders_available ? "can be created" : "cannot be created"}</li>
            </ul>
            <p>
              Webhook URL: <code>https://api.calevate.tech{status.data.webhook_path}</code>
            </p>
            <details>
              <summary className="cursor-pointer">Events to tick in the Razorpay dashboard</summary>
              <p className="mt-2 font-mono text-xs">{status.data.subscribed_events.join(", ")}</p>
            </details>
          </div>
        ) : (
          <ProblemNotice error={status.error} />
        )}
      </Card>

      <Card
        title="Reconciliation"
        info="Runs daily. Compares Razorpay's payments and refunds with the ledger, credits a payment whose webhook was lost, and raises an alarm for anything it cannot explain."
      >
        <div className="space-y-3 text-sm">
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={!operator.allowed || reconcile.isPending}
            onClick={() => reconcile.mutate()}
          >
            Run reconciliation now
          </button>
          <ProblemNotice error={reconcile.error} />
          {reconcile.data && (
            <ul>
              <li>
                {reconcile.data.payments_seen} payments and {reconcile.data.refunds_seen} refunds
                over {reconcile.data.window_days} days.
              </li>
              <li>Credited late: {reconcile.data.credited_late.join(", ") || "none"}</li>
              <li>Refunds recorded late: {reconcile.data.refunds_recorded_late.join(", ") || "none"}</li>
              <li>Unexplained: {reconcile.data.unexplained.join(", ") || "none"}</li>
              <li>
                Settlements: {reconcile.data.settlements}, {formatINR(reconcile.data.settled_inr)}
              </li>
            </ul>
          )}
          {status.data && status.data.alarms.length > 0 && (
            <div>
              <h3 className="font-semibold text-ink">Payment alarms, last 7 days</h3>
              <ul className="mt-1 space-y-1">
                {status.data.alarms.map((alarm) => (
                  <li key={`${alarm.code}-${alarm.last_seen_at}`}>
                    <span className="font-mono">{alarm.code}</span> · {alarm.severity} ·{" "}
                    {alarm.occurrences}× · last {formatIST(alarm.last_seen_at)}
                    {alarm.open ? " · open" : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Card>

      <Card title="Disputes">
        <div className="space-y-3 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
            Show resolved disputes
          </label>
          {disputes.isLoading ? (
            <Skeleton rows={2} label="Loading disputes" />
          ) : disputes.data && disputes.data.length > 0 ? (
            <ul className="space-y-4">
              {disputes.data.map((d) => (
                <DisputeRow key={d.dispute_id} dispute={d} canAct={operator.allowed} />
              ))}
            </ul>
          ) : disputes.data ? (
            <p>No disputes.</p>
          ) : (
            <ProblemNotice error={disputes.error} />
          )}
        </div>
      </Card>

      <Card title="Recent payments at Razorpay">
        {showRecent ? (
          recent.data ? (
            <ul className="space-y-1 text-sm">
              {recent.data.map((p) => (
                <li key={p.payment_id}>
                  <span className="font-mono">{p.payment_id}</span> · {p.status} ·{" "}
                  {formatINR(p.amount_inr)} · {p.method ?? "?"}
                  {p.international ? " · international" : ""} ·{" "}
                  {p.tenant_id ? `client ${p.tenant_id}` : "no order record"}
                </li>
              ))}
            </ul>
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
      </Card>
    </div>
  );
}

function DisputeRow({ dispute, canAct }: { dispute: Dispute; canAct: boolean }) {
  const accept = useAcceptDispute();
  const contest = useContestDispute();
  const [summary, setSummary] = useState("");
  const [kind, setKind] = useState(EVIDENCE_KINDS[0]?.value ?? "billing_proof");
  const [files, setFiles] = useState<File[]>([]);
  const open = dispute.status === "open" || dispute.status === "under_review";

  return (
    <li className="rounded border border-line p-3">
      <p className="font-semibold text-ink">
        {dispute.tenant_name ?? dispute.tenant_id} · {formatINR(dispute.amount_inr)} ·{" "}
        {dispute.status}
        {dispute.action_required ? " · more evidence asked for" : ""}
      </p>
      <p>
        Payment <span className="font-mono">{dispute.payment_id}</span> · held{" "}
        {formatINR(dispute.hold_inr)} · reason {dispute.reason_code ?? "not given"}
        {dispute.respond_by ? ` · respond by ${formatIST(dispute.respond_by)}` : ""}
      </p>
      {open && canAct && (
        <div className="mt-3 space-y-2">
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
          <div className="flex flex-wrap gap-2">
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
            <button
              type="button"
              className={DANGER_BUTTON}
              disabled={accept.isPending}
              onClick={() => accept.mutate(dispute.dispute_id)}
            >
              Accept (refunds the customer; cannot be undone)
            </button>
          </div>
          <ProblemNotice error={contest.error ?? accept.error} />
        </div>
      )}
    </li>
  );
}
