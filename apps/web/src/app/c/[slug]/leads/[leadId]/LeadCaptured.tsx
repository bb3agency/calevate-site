"use client";

import { ProblemNotice, Skeleton } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useLeadCaptured } from "@/lib/api/leadFields";
import { UNLISTED_NOTE, capturedValue, unlistedWords } from "@/lib/leadLabels";

/**
 * What the agents captured about this person, under the labels the business uses
 * (`GET /v1/leads/{id}/captured`): the core every business gets first, then this
 * business's own fields, then any older field the agent no longer asks for.
 *
 * The call screen's rule (founder, 11 Oct 2026; L3-10): only the details the person
 * actually gave are rows, because a column of "Not said" reads as a form they refused to
 * fill. The details still asked for and never given fold into one quiet "Not mentioned"
 * line, and an older detail with no value is not listed at all. The lead's own name fills
 * an empty name field on the server (`crm/captured.with_known_name`).
 *
 * Its own read, so a failure here says so in place and leaves the rest of the lead alone.
 */
export function LeadCaptured({ session, leadId }: { session: Session; leadId: string }) {
  const captured = useLeadCaptured(session, leadId);
  if (captured.isLoading) return <Skeleton rows={2} label="Loading what was captured" />;
  if (captured.error != null) {
    return <ProblemNotice error={captured.error} onRetry={() => void captured.refetch()} />;
  }
  const fields = captured.data?.fields ?? [];
  if (!fields.length) return null;
  const shown = (field: (typeof fields)[number]) => capturedValue(field) ?? unlistedWords(field);
  const given = fields.filter((field) => shown(field) !== null);
  const unmentioned = fields.filter((field) => field.current && shown(field) === null);
  return (
    <div className="space-y-3">
      {given.length === 0 ? (
        <p className="text-body text-ink-muted">No details have been given yet.</p>
      ) : (
        <dl className="grid grid-cols-1 gap-x-8 border-t border-line pt-1 sm:grid-cols-2">
          {given.map((field) => (
            <div key={field.key} className="flex min-w-0 items-baseline justify-between gap-4 border-b border-line py-2.5">
              <dt className="text-body text-ink-muted">
                {field.label}
                {!field.current && <span className="block text-meta text-ink-faint">No longer asked</span>}
              </dt>
              <dd className="min-w-0 break-words text-right text-body font-medium text-ink">
                {shown(field)}
                {unlistedWords(field) && <span className="block text-meta font-normal text-ink-faint">{UNLISTED_NOTE}</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {unmentioned.length > 0 && (
        <ul aria-label="Not mentioned" className="flex flex-wrap items-center gap-1.5 text-meta">
          <li className="text-ink-faint">Not mentioned:</li>
          {unmentioned.map((field) => (
            <li key={field.key} className="rounded-md bg-surface-muted px-2 py-0.5 text-ink-muted">
              {field.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
