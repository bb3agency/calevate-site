"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import {
  Card,
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { WriteFailure } from "@/app/admin/writeFailure";
import type { useAdminAccess } from "@/app/admin/access";
import { adminSession } from "@/lib/api/admin";
import { erasureConfirmation, useEraseTenant, useTenantErasures } from "@/lib/api/erasure";

/**
 * The offboarding trigger (SURFACES §1, the last step of FLOWS §9), and the certificate it
 * leaves. Rendered only for a CLOSED account, because the API refuses any other
 * (`409 tenant_not_closed`). It sits on the Closing screen because erasure is the end of the
 * clock that screen starts: close, countdown, reopen or erase, certificate — one place.
 *
 * THE TYPED CONFIRMATION IS NOT THE GUARD. The guard is the `X-Confirm-Action` header the
 * API demands and the superadmin role (`ops:manage`) it checks first; a field that exists
 * only here is absent from curl. What the typing buys is that the most destructive request
 * in the product cannot be sent by a mis-click, and that the operator has read the sentence
 * describing what goes. It is an EXACT match, because it is an id, not a word.
 */
export function ErasurePanel({
  tenantId,
  tenantName,
  access,
}: {
  tenantId: string;
  tenantName: string;
  access: ReturnType<typeof useAdminAccess>;
}) {
  const session = adminSession();
  const filed = useTenantErasures(session, tenantId);
  const erase = useEraseTenant(session, tenantId);
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const confirmation = erasureConfirmation(tenantId);
  const blocked = reason.trim().length < 3 || typed.trim() !== confirmation;

  // §52 at its most expensive: `filed.data` is undefined while loading AND after a failure,
  // and reading that as "none filed" would offer an irreversible erasure that may already be
  // running. So the ladder sits ABOVE the `existing` branch, and both arms keep the card.
  if (filed.isLoading) {
    return (
      <Card title="Data erasure">
        <Skeleton rows={3} />
      </Card>
    );
  }
  if (filed.error) {
    return (
      <Card title="Data erasure">
        <ProblemNotice error={filed.error} onRetry={() => void filed.refetch()} />
        <p className="mt-3 text-sm text-ink-muted">
          Until this reads, we cannot tell you whether this client&apos;s data has already
          been erased — so the erasure form stays closed. Filing a second one would start a
          destructive job over the top of a running one.
        </p>
      </Card>
    );
  }

  const existing = filed.data?.[0];

  if (existing) {
    return (
      <Card title="Data erasure">
        <p className="text-sm text-ink-muted">
          {existing.status === "completed"
            ? `This client's data was erased on ${formatIST(existing.completed_at ?? existing.requested_at)}. The certificate below is the record.`
            : "An erasure has been filed for this client and is running. It cannot be cancelled."}
        </p>
        <p className="mt-2 text-xs text-ink-muted">Reason recorded: {existing.reason}</p>
        {existing.proof && (
          <ul className="mt-3 space-y-1 text-xs text-ink-muted">
            <li>Calls stripped: {existing.proof.scope.calls_erased ?? "not recorded"}</li>
            <li>Leads anonymised: {existing.proof.scope.leads_erased ?? "not recorded"}</li>
            <li>
              Recordings destroyed: {existing.proof.scope.recordings_destroyed ?? "not recorded"}
              {/* An ISO instant, so IST like every other: a browser-zone date can move a
                  retention deadline by a day. */}
              {existing.proof.recording_hold_until
                ? ` — the rest are destroyed by ${formatIST(existing.proof.recording_hold_until)}`
                : ""}
            </li>
            <li>Engine-side copies: {existing.proof.engine_deletion}</li>
          </ul>
        )}
        {existing.limitations.length > 0 && (
          <details className="mt-3">
            <summary className="cursor-pointer text-xs font-medium text-ink touch:min-h-11">
              What this erasure did not remove ({existing.limitations.length})
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-muted">
              {existing.limitations.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        )}
      </Card>
    );
  }

  return (
    <Card title="Erase this client's data">
      <form
        className="max-w-xl space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          erase.mutate({ reason: reason.trim() });
        }}
      >
        <RestrictionNote reason={access.reason} />
        <NoticeBox tone="stop" icon={<AlertTriangle className="h-5 w-5" />}>
          <p className="text-xs">
            This destroys every caller record {tenantName} holds — call numbers, summaries,
            transcripts, extracted fields, CRM leads, the records we sent to their CRM and
            the audio past its 90-day legal retention floor — and marks the client deleted.
            It cannot be undone. Export their data first: nothing here produces the bundle.
            Billing ledgers, consent records, do-not-call entries and the knowledge base are
            kept, and the certificate says so.
          </p>
        </NoticeBox>

        <div>
          <label htmlFor="erase-reason" className={FIELD_LABEL}>
            Why
          </label>
          <textarea
            id="erase-reason"
            rows={2}
            maxLength={500}
            value={reason}
            disabled={!access.allowed}
            onChange={(event) => {
              setReason(event.target.value);
              erase.reset();
            }}
            className={FIELD}
          />
          <span className={FIELD_HINT}>Recorded verbatim in the audit log, beside who asked for it.</span>
        </div>

        <div>
          <label htmlFor="erase-confirm" className={FIELD_LABEL}>
            Type the confirmation
          </label>
          <input
            id="erase-confirm"
            value={typed}
            disabled={!access.allowed}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => {
              setTyped(event.target.value);
              erase.reset();
            }}
            className={`${FIELD} font-mono`}
          />
          <span className={FIELD_HINT}>
            <code className="break-all">{confirmation}</code> — the same string the API demands
            as a header, so a request cannot arrive from a screen that did not mean to send it.
          </span>
        </div>

        {/* DANGER_BUTTON: the rose fill is reserved for exactly this, the most
            irreversible control in the product (ux-audit F-2). */}
        <button
          type="submit"
          disabled={erase.isPending || blocked || !access.allowed}
          className={`${DANGER_BUTTON} max-sm:w-full max-sm:justify-center`}
        >
          {erase.isPending ? "Erasing…" : "Erase this client's data"}
        </button>
      </form>
      {erase.error != null && (
        <WriteFailure error={erase.error} actionLabel="Erase this client’s data" />
      )}
    </Card>
  );
}
