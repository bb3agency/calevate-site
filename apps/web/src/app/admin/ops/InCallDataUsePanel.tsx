"use client";

import { useState } from "react";
import { BadgeCheck, ShieldCheck, TriangleAlert } from "lucide-react";

import { AttestForm } from "@/app/admin/ops/DashboardDataUsePanel";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { Section } from "@/components/console/section";
import { NoticeBox, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatIST } from "@/components/ui";
import { providerLabel } from "@/lib/api/llmModels";
import { useAttestInCallDataUse, useInCallDataUse, type InCallDataUse } from "@/lib/api/opsInCallDataUse";

type Access = { allowed: boolean; reason: string | null };

/**
 * The in-call data-use attestation (D-839): whether what callers say may go through our key
 * to a provider, when calls answer on our own model. Separate from the dashboard attestation
 * beside it, with its own statement and step-up; our own model's checklist reads this one.
 * Loading, unreadable, forbidden and read, as the dashboard panel renders them.
 */
export function InCallDataUsePanel({ access }: { access: Access }) {
  const query = useInCallDataUse();

  if (isForbidden(query.error)) {
    return (
      <WithheldPanel
        title="In-call data use"
        reason={
          forbiddenReason(query.error) ??
          "The API refused this read: your admin account may not manage platform configuration."
        }
        subject="This panel would show whether callers' speech may go through our own model's key, and the latest data-use attestation for it."
      />
    );
  }

  return (
    <Section title="In-call data use">
      <div className="space-y-4">
        <p className="text-body text-ink-muted">
          When our own model answers calls, what every caller says goes through our key on every
          turn. Read the account&apos;s tier and log-sharing setting in the vendor&apos;s own
          console and record them here. Our own model cannot be switched on until this is
          attested.
        </p>
        {query.error != null && <ProblemNotice error={query.error} onRetry={() => void query.refetch()} />}
        {query.error == null && !query.data && <Skeleton rows={2} label="Reading the in-call attestation" />}
        {query.data && (
          <ul className="divide-y divide-line border-y border-line">
            {query.data.providers.map((row) => (
              <li key={row.provider}>
                <InCallRow row={row} statement={query.data.statement} access={access} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}

function InCallRow({ row, statement, access }: { row: InCallDataUse; statement: string; access: Access }) {
  const [open, setOpen] = useState(false);
  const save = useAttestInCallDataUse();
  const attested = row.attested_at !== null;

  return (
    <div className="py-3.5 sm:px-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-body text-ink">{providerLabel(row.provider)}</p>
          <p className="mt-0.5 text-meta text-ink-muted">
            <MonoValue>{row.provider}</MonoValue>
          </p>
        </div>
        <span className={`inline-flex items-center gap-1 text-meta font-medium ${row.permits ? "text-brand" : "text-warn"}`}>
          {row.permits ? (
            <BadgeCheck aria-hidden className="h-3.5 w-3.5" />
          ) : (
            <TriangleAlert aria-hidden className="h-3.5 w-3.5" />
          )}
          {row.permits ? "Callers' speech may go here" : "Not attested for calls"}
        </span>
      </div>

      {attested && !row.permits && (
        <NoticeBox tone="warn" title="Attested, but not on terms that allow caller speech">
          <p className="mt-1">
            The latest attestation says the account is not on the paid tier, or opts content into
            the free-tier terms. Our own model stays off until a later attestation confirms both.
          </p>
        </NoticeBox>
      )}

      {attested ? (
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-meta">
          <dt className="text-ink-muted">Vendor project / account</dt>
          <dd className="text-ink">
            <MonoValue>{row.vendor_account_ref}</MonoValue>
          </dd>
          <dt className="text-ink-muted">On the vendor&apos;s paid tier</dt>
          <dd className="text-ink">{row.paid_tier_confirmed ? "Yes" : "No"}</dd>
          <dt className="text-ink-muted">Content not opted into free-tier terms</dt>
          <dd className="text-ink">{row.no_training_opt_in_confirmed ? "Yes" : "No"}</dd>
          <dt className="text-ink-muted">Attested</dt>
          <dd className="text-ink">
            {formatIST(row.attested_at)}
            {row.attested_by ? ` · ${row.attested_by}` : ""}
          </dd>
          {row.source_note && (
            <>
              <dt className="text-ink-muted">Source</dt>
              <dd className="text-ink">{row.source_note}</dd>
            </>
          )}
        </dl>
      ) : (
        <p className="mt-2 text-meta text-ink-muted">
          Nobody has attested this for calls yet. An attestation for the dashboard assistant does
          not count here: it is about a different kind of content.
        </p>
      )}

      {access.allowed ? (
        <div className="mt-3">
          {open ? (
            <AttestForm leg={row} statement={statement} onDone={() => setOpen(false)} save={save} />
          ) : (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen(true)}>
              <ShieldCheck aria-hidden className="h-3.5 w-3.5" />
              {attested ? "Update attestation" : "Record attestation"}
            </button>
          )}
        </div>
      ) : (
        <p className="mt-3 text-meta text-ink-muted">
          {access.reason ?? "Your admin account cannot change platform configuration."}
        </p>
      )}
    </div>
  );
}
