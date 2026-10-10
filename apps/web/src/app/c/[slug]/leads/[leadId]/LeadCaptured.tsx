"use client";

import { ProblemNotice, Skeleton } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useLeadCaptured } from "@/lib/api/leadFields";
import { capturedValue } from "@/lib/leadLabels";

/**
 * What the agents captured about this person, under the labels the business uses — the
 * core every business gets first, then this business's own fields, then any older field
 * the agent no longer asks for (`GET /v1/leads/{id}/captured`). Empty reads "Not said".
 *
 * Its own read, so a failure here says so in place and leaves the rest of the lead alone.
 */
export function LeadCaptured({ session, leadId }: { session: Session; leadId: string }) {
  const captured = useLeadCaptured(session, leadId);
  if (captured.isLoading) return <Skeleton rows={2} label="Loading what was captured" />;
  if (captured.error != null) {
    return <ProblemNotice error={captured.error} onRetry={() => void captured.refetch()} />;
  }
  const fields = captured.data?.fields;
  if (!fields?.length) return null;
  return (
    <dl className="grid gap-x-8 border-t border-line pt-1 sm:grid-cols-2">
      {fields.map((field) => {
        const shown = capturedValue(field);
        return (
          <div key={field.key} className="flex min-w-0 items-baseline justify-between gap-4 border-b border-line py-2.5">
            <dt className="text-body text-ink-muted">
              {field.label}
              {!field.current && <span className="block text-meta text-ink-faint">No longer asked</span>}
            </dt>
            <dd className={`min-w-0 break-words text-right text-body ${shown === null ? "text-ink-faint" : "font-medium text-ink"}`}>
              {shown ?? "Not said"}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
