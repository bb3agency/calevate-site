"use client";

/**
 * SUGGESTED CHANGES to one agent's lead details (D-889): choices to add or remove, or a new
 * detail to capture, read from the business's script, details, quick facts and what recent
 * callers asked for that no choice fitted. Each waits for the owner; nothing changes until
 * one is accepted, and one turned down is not offered again.
 *
 * Built to be scanned on a phone: each change is two short lines (what changes, with its
 * choices as chips; where it came from), and the model's one-sentence reason waits behind
 * "Why?". Accepting saves the agent's details, which re-seeds the editor below from the
 * server, so while the editor holds unsaved edits Accept waits rather than replace them.
 */

import { useState } from "react";
import { X } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, QUIET_ICON_BUTTON, SECONDARY_BUTTON_SM, formatISTStamp } from "@/components/ui";
import type { LeadSuggestion, LeadSuggestionsApi } from "@/lib/api/leadSuggestions";

const SOURCE: Readonly<Record<LeadSuggestion["source"], string>> = {
  script: "Script",
  business: "Business details",
  facts: "Quick facts",
  calls: "Recent calls",
};

function title(s: LeadSuggestion): string {
  if (s.kind === "add_choices") return `Add to ${s.field_label}`;
  if (s.kind === "remove_choices") return `Remove from ${s.field_label}`;
  return `New detail: ${s.field_label}`;
}

function evidence(s: LeadSuggestion): string {
  if (s.callers > 0) return `${s.callers} ${s.callers === 1 ? "caller" : "callers"} asked`;
  return SOURCE[s.source];
}

export function LeadSuggestions({
  api,
  canWrite,
  dirty,
  audience,
}: {
  api: LeadSuggestionsApi;
  canWrite: boolean;
  /** The editor below holds unsaved edits. */
  dirty: boolean;
  audience: "client" | "operator";
}) {
  const { query, accept, dismiss, check } = api;
  const data = query.data;
  if (!data) return null;
  const busy = accept.isPending || dismiss.isPending;
  const reading = data.state === "queued" || data.state === "running";
  const suggestions = data.suggestions;
  const count = suggestions.length;

  return (
    <section aria-labelledby="lead-suggestions-heading" className="rounded-md border border-line px-3 py-3 sm:px-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="lead-suggestions-heading" className="text-sm font-medium text-ink">
          {count ? `Suggested changes (${count})` : "Suggested changes"}
        </h3>
        {canWrite && !reading && (
          <button type="button" className={`${TEXT_ACTION} shrink-0 text-xs`} disabled={check.isPending} onClick={() => check.mutate()}>
            {check.isPending ? "Starting…" : data.state === "none" ? "Check now" : "Check again"}
          </button>
        )}
      </div>

      <p role="status" aria-live="polite" className="mt-0.5 text-xs text-ink-muted">
        {reading ? (
          <span className="text-shimmer">Checking the script and recent calls…</span>
        ) : count ? (
          audience === "client" ? "Nothing changes until you accept." : "Nothing changes until one is accepted."
        ) : (
          <Status state={data.state} checkedAt={data.checked_at} audience={audience} />
        )}
      </p>

      {count > 0 && (
        <ul className="mt-2 divide-y divide-line">
          {suggestions.map((s) => (
            <Row
              key={s.id}
              suggestion={s}
              canWrite={canWrite}
              acceptDisabled={busy || dirty}
              dismissDisabled={busy}
              accepting={accept.isPending && accept.variables === s.id}
              onAccept={() => accept.mutate(s.id)}
              onDismiss={() => dismiss.mutate(s.id)}
            />
          ))}
        </ul>
      )}

      {dirty && count > 0 && canWrite && (
        <p className="mt-2 text-xs text-ink-muted">Save or undo the changes below to accept one.</p>
      )}
      {accept.error && <div className="mt-2"><ProblemNotice error={accept.error} /></div>}
      {dismiss.error && <div className="mt-2"><ProblemNotice error={dismiss.error} /></div>}
      {check.error && <div className="mt-2"><ProblemNotice error={check.error} /></div>}
    </section>
  );
}

function Row({
  suggestion: s,
  canWrite,
  acceptDisabled,
  dismissDisabled,
  accepting,
  onAccept,
  onDismiss,
}: {
  suggestion: LeadSuggestion;
  canWrite: boolean;
  acceptDisabled: boolean;
  dismissDisabled: boolean;
  accepting: boolean;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  const [why, setWhy] = useState(false);
  const reasonId = `why-${s.id}`;
  return (
    <li className="py-2.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="break-words text-sm font-medium text-ink">{title(s)}</p>
          {s.values.length > 0 ? (
            <ul aria-label="Choices" className="mt-1 flex flex-wrap gap-1">
              {s.values.map((value) => (
                <li
                  key={value}
                  className={`rounded px-1.5 py-0.5 text-xs ${
                    s.kind === "remove_choices" ? "bg-ink/[0.04] text-ink-muted line-through" : "bg-ink/[0.06] text-ink"
                  }`}
                >
                  {value}
                </li>
              ))}
            </ul>
          ) : (
            s.kind === "new_field" && <p className="mt-0.5 text-xs text-ink-muted">In the caller&apos;s own words</p>
          )}
          <p className="mt-1 text-xs text-ink-faint">
            {evidence(s)}
            <span aria-hidden> · </span>
            <button
              type="button"
              className="text-ink-muted underline decoration-line underline-offset-2 hover:text-ink"
              aria-expanded={why}
              aria-controls={reasonId}
              onClick={() => setWhy((open) => !open)}
            >
              {why ? "Hide" : "Why?"}
            </button>
          </p>
          {why && (
            <p id={reasonId} className="mt-1 max-w-prose text-xs text-ink-muted [text-wrap:pretty]">
              {s.reason}
            </p>
          )}
        </div>
        {canWrite && (
          <div className="flex shrink-0 items-center gap-0.5">
            <button type="button" className={SECONDARY_BUTTON_SM} disabled={acceptDisabled} onClick={onAccept}>
              {accepting ? "Accepting…" : "Accept"}
            </button>
            <button
              type="button"
              className={QUIET_ICON_BUTTON}
              aria-label={`Not now: ${title(s)}`}
              title="Not now"
              disabled={dismissDisabled}
              onClick={onDismiss}
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

function Status({
  state,
  checkedAt,
  audience,
}: {
  state: string;
  checkedAt: string | null;
  audience: "client" | "operator";
}) {
  if (state === "none") return <>Not checked yet.</>;
  if (state === "failed") return <>The last check could not finish.</>;
  if (state === "skipped") {
    return <>Not checked: {audience === "client" ? "this month's" : "the client's"} AI allowance is used up.</>;
  }
  return <>Nothing to change{checkedAt ? `, checked ${formatISTStamp(checkedAt)}` : ""}.</>;
}
