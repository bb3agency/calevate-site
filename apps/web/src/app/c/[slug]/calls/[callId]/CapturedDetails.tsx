"use client";

import { Section } from "@/components/console/section";
import type { CallDetail } from "@/lib/api/client";
import { UNLISTED_NOTE, capturedValue, unlistedWords } from "@/lib/leadLabels";
import { lookup } from "@/lib/lookup";

/**
 * WHAT THE CALLER GAVE, as label–value rows under the labels the business uses.
 *
 * Only the details the caller actually said are rows (founder, 11 Oct 2026): a column of
 * "Not said" read as a form the caller refused to fill. The fields nobody mentioned fold
 * into one quiet row of chips, so the owner still sees what the agent was listening for. A value
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
  // An unclear answer was said, so it is listed with its reason below rather than here.
  const unclear = new Set(detail.unclear_fields.map((field) => field.key));
  const unmentioned = fields.filter((field) => field.current && said(field) === null && !unclear.has(field.key));
  return (
    <Section title="Captured details">
      {given.length === 0 ? (
        <p className="text-body text-ink-muted">The caller did not give any details on this call.</p>
      ) : (
        // dt/dd are direct children of one wrapper div each: a <dl> accepts a div that groups
        // a dt/dd pair and nothing deeper (axe definition-list / dlitem).
        // Two up, small label over value: a phone shows twice as many details per screen.
        <dl className="grid grid-cols-2 gap-x-4 gap-y-4 border-y border-line py-3">
          {given.map((field) => {
            const review = detail.extraction_needs_review?.[field.key];
            const from = lookup(SOURCE_WORDS, field.source);
            return (
              <div key={field.key} className="min-w-0 space-y-0.5">
                <dt className="text-meta text-ink-muted [overflow-wrap:anywhere]">
                  {field.label}
                  {!field.current && (
                    <span className="block text-meta text-ink-faint">No longer asked</span>
                  )}
                </dt>
                <dd className="min-w-0 break-words text-body font-medium text-ink">
                  {said(field)}
                  {unlistedWords(field) && (
                    <span className="block text-meta font-normal text-ink-faint">{UNLISTED_NOTE}</span>
                  )}
                  {from && <span className="block text-meta font-normal text-ink-faint">{from}</span>}
                </dd>
                {review && <dd className="text-meta text-warn">{review}</dd>}
              </div>
            );
          })}
        </dl>
      )}
      {given.length > 0 && unmentioned.length > 0 && (
        <ul aria-label="Not mentioned" className="mt-3 flex flex-wrap items-center gap-1.5 text-meta">
          <li className="text-ink-faint">Not mentioned:</li>
          {unmentioned.map((field) => (
            <li key={field.key} className="rounded-md bg-surface-muted px-2 py-0.5 text-ink-muted">
              {field.label}
            </li>
          ))}
        </ul>
      )}
      <Unclear detail={detail} />
    </Section>
  );
}

/** Where a detail came from when the caller did not say it (only a name is ever filled). */
const SOURCE_WORDS: Record<string, string> = {
  list: "From your list",
  lead: "From your leads",
};

/**
 * The details the caller answered that could not be used, each named with our reason, so
 * the owner knows which to check rather than "some". With none named, the reading itself
 * failed, which is a different message: nothing below it can be trusted to be complete.
 */
function Unclear({ detail }: { detail: CallDetail }) {
  if (detail.extraction_valid) return null;
  if (!detail.unclear_fields.length) {
    return <p className="mt-3 text-meta text-warn">We couldn&apos;t read this call&apos;s details. Check the chat below.</p>;
  }
  return (
    <div className="mt-3">
      <p className="text-meta font-medium text-warn">Unclear, worth a check:</p>
      <ul className="mt-1 space-y-1 text-meta">
        {detail.unclear_fields.map((field) => (
          <li key={field.key}>
            <span className="font-medium text-ink">{field.label}</span>
            <span className="text-ink-muted">: {field.reason}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
