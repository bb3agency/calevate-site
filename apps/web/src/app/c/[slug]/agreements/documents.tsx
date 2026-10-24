"use client";

import { ExternalLink } from "lucide-react";

import { formatDateShort, isISODate } from "@/components/arc/ist-dates";
import { StatusPill } from "@/components/console/statusPill";
import { formatIST, type NoticeTone } from "@/components/ui";
import type { DocumentState, LegalDocumentState } from "@/lib/api/agreements";

/**
 * The server-decided states, as the status each one wears. `not_required` wears none: its
 * section's heading already says there is nothing to accept.
 */
const STATE_BADGE: Record<Exclude<DocumentState, "not_required">, { label: string; tone: NoticeTone }> = {
  accepted: { label: "Accepted", tone: "ok" },
  never_accepted: { label: "Not accepted", tone: "stop" },
  reacceptance_required: { label: "Needs accepting again", tone: "stop" },
  changed: { label: "Updated", tone: "warn" },
};

/** The documents as rows: the title (which opens it) and its state on one line, the facts under it. */
export function DocumentRows({ docs }: { docs: LegalDocumentState[] }) {
  return (
    <ul className="divide-y divide-line border-y border-line">
      {docs.map((doc) => (
        <DocumentRow key={doc.slug} doc={doc} />
      ))}
    </ul>
  );
}

/**
 * The effective date is a calendar day (`YYYY-MM-DD`), not an instant, so it goes through
 * the day formatter rather than `formatIST`; anything else is printed as sent rather than
 * guessed at. An undated document says so: a reader who sees no date cannot tell that from
 * a screen that forgot to print it.
 */
function effectiveLine(date: string | null): string {
  if (!date) return "No effective date yet";
  return `In force from ${isISODate(date) ? formatDateShort(date) : date}`;
}

function DocumentRow({ doc }: { doc: LegalDocumentState }) {
  const badge = doc.state === "not_required" ? null : STATE_BADGE[doc.state];
  const explains = doc.state === "changed" || doc.state === "reacceptance_required";
  return (
    // The whole row opens the document (the link's ::after covers it), so the tap target is
    // the row's full height rather than the title's line.
    <li className="relative py-3">
      <div className="flex items-start justify-between gap-3">
        <a
          href={doc.href}
          target="_blank"
          rel="noreferrer"
          aria-label={`Read ${doc.title} (opens in a new tab)`}
          className="group min-w-0 rounded-sm text-body font-medium text-ink [overflow-wrap:anywhere] after:absolute after:inset-0 after:rounded-sm focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-brand"
        >
          <span className="underline-offset-2 group-hover:underline">{doc.title}</span>
          <ExternalLink aria-hidden className="ml-1.5 inline h-3.5 w-3.5 -translate-y-px align-middle text-ink-faint" />
        </a>
        {badge && (
          <StatusPill tone={badge.tone} className="mt-0.5">
            {badge.label}
          </StatusPill>
        )}
      </div>
      {explains && <p className="mt-0.5 text-meta text-ink-muted">{doc.headline}</p>}
      <p className="mt-0.5 text-meta text-ink-faint">
        {doc.accepted_at && (
          <>
            <span className="text-ink-muted max-sm:block">
              Accepted <time dateTime={doc.accepted_at}>{formatIST(doc.accepted_at)}</time>
              {doc.accepted_by_name ? ` by ${doc.accepted_by_name}` : ""}
            </span>
            <span aria-hidden className="max-sm:hidden"> · </span>
          </>
        )}
        <span className="whitespace-nowrap">{effectiveLine(doc.effective_date)}</span>
      </p>
    </li>
  );
}
