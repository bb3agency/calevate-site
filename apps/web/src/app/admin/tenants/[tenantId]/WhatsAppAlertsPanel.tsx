"use client";

import { useState } from "react";
import { BellOff, BellRing } from "lucide-react";

import {
  Card,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import {
  useRecordTenantAlertOptIn,
  useTenantAlertOptIn,
} from "@/lib/api/whatsappAlerts";

/**
 * WhatsApp hot-lead alerts for this client's owner — the opt-in given OFF the screen.
 *
 * ## Why an operator surface exists at all
 *
 * The client's own control is `/c/[slug]/settings/alerts`, and it is the better path:
 * the person agreeing is the person clicking, which is what makes a self-serve grant
 * self-evidencing (a CHECK constraint requires the subject and the recorder to be the
 * same user). This panel is for the other case, which is most of them at our size — the
 * owner agreed on the onboarding call, or on a signed form, and somebody has to write
 * that down. So a grant here MUST carry the reference of the document it rests on, and
 * the row names the operator rather than the owner as its recorder.
 *
 * ## The read is the part that makes the write safe to offer
 *
 * `GET .../whatsapp-alerts` (admin realm) exists so this panel can show the owner's
 * CURRENT state before an operator records a month-old form over a withdrawal made last
 * week. The ledger is append-only, so that mistake is not editable — it is another row,
 * and the alerts went out in between. The client-realm read cannot answer here: a view-as
 * session has no `users` row of its own and deliberately reports no subject state.
 *
 * ## What it does not do
 *
 * No step-up header, unlike the ops console's global do-not-call writes. This names ONE
 * tenant and one owner and demands a document reference; the typed-confirmation
 * discipline is spent where a single POST binds every tenant at once.
 */
export function WhatsAppAlertsPanel({ tenantId }: { tenantId: string }) {
  const state = useTenantAlertOptIn(tenantId);
  const record = useRecordTenantAlertOptIn(tenantId);
  const write = useAdminAccess("admin:tenants", "record this client's WhatsApp opt-in");
  const [reference, setReference] = useState("");

  const current = state.data;
  // The document reference is what makes an operator's claim evidence rather than an
  // assertion — the service and a CHECK both refuse a grant without one, so the button
  // is dead until it is typed rather than sending a request that cannot succeed.
  const ready = write.allowed && reference.trim().length > 0 && !record.isPending;

  return (
    <Card title="WhatsApp alerts to the owner">
      <p className="-mt-2 text-xs text-ink-muted">
        Hot-lead alerts go to the owner&apos;s mobile only if they have agreed to receive
        them. Record an agreement given during onboarding here; the client can turn it on
        or off themselves on their own Alerts screen.
      </p>

      <div className="mt-4">
        <RestrictionNote reason={write.reason} />
      </div>

      {/* Loading is a skeleton and a failure is a refusal — never "not opted in", which
          is the sentence an operator answers by recording one they have no document for. */}
      {state.isLoading ? (
        <div className="mt-4">
          <Skeleton rows={2} />
        </div>
      ) : state.error ? (
        <div className="mt-4">
          <ProblemNotice error={state.error} onRetry={() => state.refetch()} />
        </div>
      ) : !current ? null : (
        <div className="mt-4 space-y-4">
          <NoticeBox
            tone={current.messageable ? "ok" : "neutral"}
            icon={
              current.messageable ? (
                <BellRing aria-hidden className="h-5 w-5" />
              ) : (
                <BellOff aria-hidden className="h-5 w-5" />
              )
            }
            title={
              current.messageable
                ? "The owner receives WhatsApp hot-lead alerts"
                : current.status === "withdrawn"
                  ? "The owner has WITHDRAWN — do not record an older agreement over this"
                  : "Nobody on this account has agreed to WhatsApp alerts"
            }
          >
            <p className="mt-1">
              {current.captured_at
                ? `Recorded ${formatIST(current.captured_at)} · ${current.channel ?? "unknown channel"}`
                : "Nothing has been recorded for this owner and this number."}
              {!current.delivery_available && (
                <>
                  {" "}
                  We cannot send WhatsApp messages on this account yet
                  {current.delivery_unavailable_reason
                    ? ` (${current.delivery_unavailable_reason.replace(/_/g, " ")})`
                    : ""}
                  , so nothing is sent whatever is recorded here.
                </>
              )}
            </p>
          </NoticeBox>

          {record.error && <ProblemNotice error={record.error} />}

          <label className="block">
            <span className={FIELD_LABEL}>Where the agreement is filed</span>
            <input
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              disabled={!write.allowed}
              placeholder="e.g. ONB-2026-0042, or a ticket id"
              className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint"
            />
            <span className="mt-1 block text-xs text-ink-faint">
              A reference, never the document itself. A grant without one is refused by the
              service and by the database.
            </span>
          </label>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!ready}
              title={write.reason ?? undefined}
              onClick={() =>
                record.mutate(
                  { status: "granted", evidence: { reference: reference.trim() } },
                  { onSuccess: () => setReference("") },
                )
              }
              className="inline-flex items-center gap-2 rounded-md bg-brand-strong px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-50"
            >
              <BellRing aria-hidden className="h-4 w-4" />
              Record that the owner agreed
            </button>
            {/* Withdrawing needs no document — nobody has to prove that somebody asked to
                stop, and requiring evidence for it would be a reason to delay stopping. */}
            <button
              type="button"
              disabled={!write.allowed || record.isPending}
              title={write.reason ?? undefined}
              onClick={() => record.mutate({ status: "withdrawn", evidence: null })}
              className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/5"
            >
              <BellOff aria-hidden className="h-4 w-4" />
              Record a withdrawal
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
