"use client";

import { ListPlus, PhoneOff, ShieldAlert, ShieldCheck } from "lucide-react";

import {
  Card,
  FIELD_INLINE,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  StatTile,
  formatCount,
} from "@/components/ui";
import {
  MAX_NUMBERS_PER_ADD,
  useAddDncNumbers,
  type DncSource,
} from "@/lib/api/dnc";
import { type Session } from "@/lib/api/client";

import { SOURCE_OPTIONS } from "./sources";

/**
 * Putting numbers on the suppression list.
 *
 * **Adding answers with counts, never numbers.** There is no per-number result to render,
 * by design — a list of who asked us to stop calling them is itself personal data. The
 * card says so rather than leaving the client hunting for a list that will never come.
 */
export function AddNumbers({
  session,
  paste,
  onPasteChange,
  source,
  onSourceChange,
  parsed,
}: {
  session: Session;
  paste: string;
  onPasteChange: (next: string) => void;
  source: DncSource;
  onSourceChange: (next: DncSource) => void;
  parsed: string[];
}) {
  const add = useAddDncNumbers(session);
  const tooMany = parsed.length > MAX_NUMBERS_PER_ADD;

  return (
    <Card title="Add numbers">
      <p className="text-sm text-ink-muted">
        Paste as many as you like — one per line, or separated by commas. Numbers
        can be ten digits or the full +91 form; we work out the rest.
      </p>
      <form
        className="mt-3 space-y-3"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate({ numbers: parsed, source }, { onSuccess: () => onPasteChange("") });
        }}
      >
        <textarea
          value={paste}
          onChange={(e) => onPasteChange(e.target.value)}
          rows={6}
          spellCheck={false}
          aria-label="Numbers to suppress"
          placeholder={"9876543210\n+919876543211\n9876543212"}
          className={`${FIELD_INLINE} w-full font-mono`}
        />

        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="dnc-source" className="text-sm text-ink-muted">
            Reason
          </label>
          <select
            id="dnc-source"
            value={source}
            onChange={(e) => onSourceChange(e.target.value as DncSource)}
            // The note changes the MEANING of this control (three of the four
            // reasons are permanent), so it must be programmatically associated —
            // a span merely sitting beside a select is one a screen reader never
            // reads with it (WCAG 3.3.2 — ux-audit DNC-2).
            aria-describedby="dnc-source-note"
            className={FIELD_INLINE}
          >
            {SOURCE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <span id="dnc-source-note" className="text-xs text-ink-faint">
            {SOURCE_OPTIONS.find((o) => o.value === source)?.note}
          </span>
        </div>

        {/* Stopped here rather than at the API's 422: 2000 is the server's cap and
            a client who pasted 5,000 rows deserves to be told before they wait. */}
        {tooMany && (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            That is {formatCount(parsed.length)} numbers. Add up to{" "}
            {formatCount(MAX_NUMBERS_PER_ADD)} at a time.
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={add.isPending || parsed.length === 0 || tooMany}
            className={PRIMARY_BUTTON_SM}
          >
            <ListPlus className="h-4 w-4" />
            {add.isPending
              ? "Adding…"
              : parsed.length === 1
                ? "Add 1 number"
                : `Add ${formatCount(parsed.length)} numbers`}
          </button>
          {parsed.length > 0 && !tooMany && (
            <span className="text-xs text-ink-faint">
              {formatCount(parsed.length)} distinct{" "}
              {parsed.length === 1 ? "entry" : "entries"} found in what you pasted.
            </span>
          )}
        </div>
      </form>

      {add.error != null && (
        <div className="mt-3">
          <ProblemNotice error={add.error} />
        </div>
      )}

      {/* Counts, and only counts — the API never echoes the numbers back and this
          screen must not imply that it could. */}
      {add.data && (
        <div className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <StatTile
              label="Added"
              value={formatCount(add.data.added)}
              icon={<PhoneOff className="h-5 w-5" />}
              tone="strong"
              hint="Suppressed from now on."
            />
            <StatTile
              label="Already on the list"
              value={formatCount(add.data.already_suppressed)}
              icon={<ShieldCheck className="h-5 w-5" />}
              hint="Nothing to do — they were suppressed already."
            />
            <StatTile
              label="Not a usable number"
              value={formatCount(add.data.malformed)}
              icon={<ShieldAlert className="h-5 w-5" />}
              hint="Skipped rather than guessed at."
            />
          </div>
          <p className="text-xs text-ink-faint">
            We report totals, not which number went where: a list of who asked us to
            stop calling them is itself personal data. Use the check above if you
            need to confirm one number.
          </p>
        </div>
      )}
    </Card>
  );
}
