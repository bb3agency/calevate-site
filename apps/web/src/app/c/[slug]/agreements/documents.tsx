"use client";

import { ExternalLink } from "lucide-react";

import { NOTICE_TONES, formatIST, type NoticeTone } from "@/components/ui";
import type { DocumentState, LegalDocumentState } from "@/lib/api/agreements";

/** The five server-decided states, as the badge each one wears. */
const STATE_BADGE: Record<DocumentState, { label: string; tone: NoticeTone }> = {
  accepted: { label: "Accepted", tone: "ok" },
  never_accepted: { label: "Not accepted", tone: "stop" },
  reacceptance_required: { label: "Needs accepting again", tone: "stop" },
  changed: { label: "Updated", tone: "warn" },
  not_required: { label: "Reading only", tone: "neutral" },
};

/**
 * A small tone pill on the shared `NOTICE_TONES` palette, so "not accepted" here is the
 * colour of a refusal everywhere else. Not `StatusBadge`, which is keyed on the lead and
 * call vocabularies and has no document state in it.
 */
export function TonePill({ tone, label }: { tone: NoticeTone; label: string }) {
  return (
    <span className={`whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${NOTICE_TONES[tone]}`}>
      {label}
    </span>
  );
}

/** The documents as rows: name and state on one line, the version and who accepted under it. */
export function DocumentRows({ docs }: { docs: LegalDocumentState[] }) {
  return (
    <ul className="divide-y divide-line border-y border-line">
      {docs.map((doc) => (
        <DocumentRow key={doc.slug} doc={doc} />
      ))}
    </ul>
  );
}

function DocumentRow({ doc }: { doc: LegalDocumentState }) {
  const badge = STATE_BADGE[doc.state];
  return (
    <li className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5 py-3.5">
      <div className="min-w-0 flex-1 basis-56">
        <a
          href={doc.href}
          target="_blank"
          rel="noreferrer"
          aria-label={`Read ${doc.title} (opens in a new tab)`}
          className="inline-flex items-center gap-1.5 rounded-sm text-body font-medium text-ink underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          {doc.title}
          <ExternalLink className="h-3.5 w-3.5 text-ink-faint" aria-hidden />
        </a>
        {(doc.state === "changed" || doc.state === "reacceptance_required") && (
          <p className="mt-0.5 text-meta text-ink-muted">{doc.headline}</p>
        )}
        <dl className="mt-0.5 flex flex-wrap gap-x-4 gap-y-0.5 text-meta text-ink-faint">
          <div className="flex gap-1">
            <dt>Version</dt>
            <dd className="font-mono text-ink-muted">{doc.version}</dd>
          </div>
          {doc.accepted_version && (
            <div className="flex gap-1">
              <dt>You accepted</dt>
              <dd className="font-mono text-ink-muted">{doc.accepted_version}</dd>
            </div>
          )}
          {doc.accepted_at && (
            <div className="flex gap-1">
              <dt>On</dt>
              <dd className="text-ink-muted">
                {formatIST(doc.accepted_at)}
                {doc.accepted_by_name ? ` by ${doc.accepted_by_name}` : ""}
              </dd>
            </div>
          )}
          {/* An undated document says so rather than losing the row: a reader who sees no
              date cannot tell that from a screen that forgot to print it. */}
          <div className="flex gap-1">
            <dt>Effective from</dt>
            <dd className="text-ink-muted">{doc.effective_date ?? "not yet dated"}</dd>
          </div>
        </dl>
      </div>
      <TonePill tone={badge.tone} label={badge.label} />
    </li>
  );
}
