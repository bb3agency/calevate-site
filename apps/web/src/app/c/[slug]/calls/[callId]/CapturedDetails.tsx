"use client";

import { Section } from "@/components/console/section";
import type { CallDetail } from "@/lib/api/client";
import { UNLISTED_NOTE, capturedValue, unlistedWords } from "@/lib/leadLabels";

/**
 * WHAT THE CALLER GAVE, as label–value rows under the labels the business uses.
 *
 * Only the details the caller actually said are rows (founder, 11 Oct 2026): a column of
 * "Not said" read as a form the caller refused to fill. The fields nobody mentioned fold
 * into one quiet line, so the owner still sees what the agent was listening for. A value
 * flagged for checking carries the server's note, which names the field and never repeats
 * the value.
 */
export function CapturedDetails({ detail }: { detail: CallDetail }) {
  const fields = detail.captured;
  // A choice the caller answered outside the list is something they said (D-889).
  const said = (field: (typeof fields)[number]) => capturedValue(field) ?? unlistedWords(field);
  const given = fields.filter((field) => said(field) !== null);
  // A call with no conversation has nothing to capture, and an empty list there would
  // read as things the caller refused to say.
  if (!fields.length || (detail.status !== "completed" && !given.length)) return null;
  if (detail.summary_state === "pending" && !given.length) {
    return (
      <Section title="Captured details">
        <p className="text-body text-ink-muted">These are filled in once the call has been read.</p>
      </Section>
    );
  }
  // Fields the agent no longer asks for appear only when this call carried a value for them.
  const unmentioned = fields.filter((field) => field.current && said(field) === null);
  return (
    <Section title="Captured details">
      {given.length === 0 ? (
        <p className="text-body text-ink-muted">The caller did not give any details on this call.</p>
      ) : (
        // dt/dd are direct children of one wrapper div each: a <dl> accepts a div that groups
        // a dt/dd pair and nothing deeper (axe definition-list / dlitem).
        <dl className="divide-y divide-line border-y border-line">
          {given.map((field) => {
            const review = detail.extraction_needs_review?.[field.key];
            return (
              <div key={field.key} className="grid grid-cols-1 gap-x-4 gap-y-0.5 py-3 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
                <dt className="text-body text-ink-muted">
                  {field.label}
                  {!field.current && <span className="block text-meta text-ink-faint">No longer asked</span>}
                </dt>
                <dd className="min-w-0 break-words text-body font-medium text-ink">
                  {said(field)}
                  {unlistedWords(field) && (
                    <span className="block text-meta font-normal text-ink-faint">{UNLISTED_NOTE}</span>
                  )}
                </dd>
                {review && <dd className="text-meta text-warn sm:col-start-2">{review}</dd>}
              </div>
            );
          })}
        </dl>
      )}
      {given.length > 0 && unmentioned.length > 0 && (
        <p className="mt-3 text-meta text-ink-faint [text-wrap:pretty]">
          Not mentioned: {unmentioned.map((field) => field.label).join(", ")}
        </p>
      )}
      {!detail.extraction_valid && (
        <p className="mt-3 text-meta text-warn">Some details could not be captured cleanly from this call.</p>
      )}
    </Section>
  );
}
