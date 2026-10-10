"use client";

import { Section } from "@/components/console/section";
import type { CallDetail } from "@/lib/api/client";
import { capturedValue } from "@/lib/leadLabels";

/**
 * WHAT THE AGENT WROTE DOWN, as label–value rows under the labels the business uses.
 *
 * The rows are the server's `captured` list: the core every business captures first,
 * then this business's own fields, then any older field the agent no longer asks for
 * whose value is still on this call. Empty is "Not said" rather than a dash, because the
 * honest reading of an empty field is that the caller never said it. A value flagged for
 * checking carries the server's note, which names the field and never repeats the value.
 */
export function CapturedDetails({ detail }: { detail: CallDetail }) {
  const fields = detail.captured;
  const nothing = fields.every((f) => capturedValue(f) === null);
  // A call with no conversation has nothing to capture; a column of "Not said" there
  // would read as six things the caller refused to say.
  if (!fields.length || (detail.status !== "completed" && nothing)) return null;
  const reading = detail.summary_state === "pending" && nothing;
  return (
    <Section title="Captured details">
      {reading ? (
        <p className="text-body text-ink-muted">These are filled in once the call has been read.</p>
      ) : (
        <>
          {/* dt/dd are direct children of one wrapper div each: a <dl> accepts a div that
              groups a dt/dd pair and nothing deeper (axe definition-list / dlitem). */}
          <dl className="divide-y divide-line border-y border-line">
            {fields.map((field) => {
              const shown = capturedValue(field);
              const review = detail.extraction_needs_review?.[field.key];
              return (
                <div key={field.key} className="grid gap-x-4 gap-y-0.5 py-3 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
                  <dt className="text-body text-ink-muted">
                    {field.label}
                    {!field.current && <span className="block text-meta text-ink-faint">No longer asked</span>}
                  </dt>
                  <dd className={`min-w-0 break-words text-body ${shown === null ? "text-ink-faint" : "font-medium text-ink"}`}>
                    {shown ?? "Not said"}
                  </dd>
                  {review && <dd className="text-meta text-warn sm:col-start-2">{review}</dd>}
                </div>
              );
            })}
          </dl>
          {!detail.extraction_valid && (
            <p className="mt-3 text-meta text-warn">Some details could not be captured cleanly from this call.</p>
          )}
        </>
      )}
    </Section>
  );
}
