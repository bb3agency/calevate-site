"use client";

import { Skeleton } from "@/components/ui";
import { useLeadSources } from "@/lib/api/leadSources";

import { sourceLabel } from "./sourceKinds";
import { FIELD } from "./styles";

export type SourcesQuery = ReturnType<typeof useLeadSources>;

/**
 * Pick one of the client's own lead sources.
 *
 * §52 applies to a form control as much as to a panel: while the list is loading this
 * is a skeleton, when the read FAILED it is a disabled control saying so, and only a
 * successful empty list may say there is nothing to pick. The three used to be one
 * text box that accepted anything, which is how "I pasted the ID from the email and it
 * says not found" became a support thread.
 */
export function SourcePicker({
  label,
  value,
  onChange,
  query,
  only,
  emptyHint = "Add a lead source above first.",
}: {
  label: string;
  value: string;
  onChange: (id: string) => void;
  query: SourcesQuery;
  only?: string;
  emptyHint?: string;
}) {
  if (query.isLoading) {
    return (
      <div className="w-full max-w-md">
        <Skeleton rows={1} />
      </div>
    );
  }
  const items = query.data?.items;
  if (!items) {
    // The read failed. The card's own ProblemNotice carries the reason and the retry;
    // what this must not do is render an empty picker, which reads as "you have none".
    return (
      <select
        disabled
        aria-label={label}
        className={`${FIELD} w-full max-w-md`}
        value=""
        onChange={() => undefined}
      >
        <option value="">We could not load your lead sources</option>
      </select>
    );
  }
  const choices = only ? items.filter((item) => item.source === only) : items;
  return (
    <select
      required
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={choices.length === 0}
      className={`${FIELD} w-full max-w-md`}
    >
      <option value="">{choices.length === 0 ? emptyHint : "Choose a lead source…"}</option>
      {choices.map((item) => (
        <option key={item.id} value={item.id}>
          {sourceLabel(item.source)} · {item.id.slice(0, 8)}
          {item.active ? "" : " (off)"}
        </option>
      ))}
    </select>
  );
}
