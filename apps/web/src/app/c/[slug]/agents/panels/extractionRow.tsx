"use client";

/**
 * ONE editable capture variable — the row the extraction editor repeats.
 *
 * Its own module for UX-DOCTRINE §6's reason: `extraction.tsx` held the list, the form,
 * the row and the archived read-only view, and the row is half of it. Nothing here reads
 * the network or the session — it is given a draft row and hands back a patch, which is
 * what makes it the piece a reviewer can hold in their head.
 */

import { ChevronDown, ChevronUp, Trash2 } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  SECONDARY_BUTTON_SM,
  ToggleSwitch,
} from "@/components/ui";
import { hasKey } from "@/lib/lookup";

import { FIELD_TYPE_COPY, effectiveKey, type DraftRow, type FieldType } from "./extractionDraft";

/**
 * One editable variable, as a stacked card so it works on a phone with no sideways scroll.
 *
 * Every control is wrapped in its own `<label>` (implicit association) rather than carrying
 * an `id` — two editors of two agents on one screen would collide on any id scheme, and the
 * wrapping label is what keeps the axe sweep (`tests/a11y.test.tsx`) green without one.
 */
export function FieldEditorRow({
  row,
  index,
  total,
  disabled,
  onChange,
  onDelete,
  onMoveUp,
  onMoveDown,
}: {
  row: DraftRow;
  index: number;
  total: number;
  disabled: boolean;
  onChange: (patch: Partial<DraftRow>) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  const named = row.label.trim() || "this variable";
  return (
    <li className="rounded-card border border-line bg-app p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
          Variable {index + 1}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={disabled || index === 0}
            aria-label={`Move ${named} up`}
            className={SECONDARY_BUTTON_SM}
          >
            <ChevronUp aria-hidden className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={disabled || index === total - 1}
            aria-label={`Move ${named} down`}
            className={SECONDARY_BUTTON_SM}
          >
            <ChevronDown aria-hidden className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={disabled}
            aria-label={`Delete ${named}`}
            className={SECONDARY_BUTTON_SM}
          >
            <Trash2 aria-hidden className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className={FIELD_LABEL}>Name</span>
          <input
            required
            maxLength={80}
            value={row.label}
            disabled={disabled}
            onChange={(event) => onChange({ label: event.target.value })}
            placeholder="e.g. Reason for visit"
            className={FIELD}
          />
        </label>
        <label className="block">
          <span className={FIELD_LABEL}>Type</span>
          <select
            value={row.type}
            disabled={disabled}
            onChange={(event) => onChange({ type: event.target.value as FieldType })}
            className={FIELD}
          >
            {/* An unrecognised stored type (a value this build's union does not name) is
                offered as itself, so opening the editor never silently retypes a column. */}
            {!hasKey(FIELD_TYPE_COPY, row.type) && <option value={row.type}>{row.type}</option>}
            {Object.entries(FIELD_TYPE_COPY).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {row.type === "enum" && (
        <label className="mt-3 block">
          <span className={FIELD_LABEL}>Options</span>
          <textarea
            rows={3}
            value={row.enumText}
            disabled={disabled}
            onChange={(event) => onChange({ enumText: event.target.value })}
            placeholder={"One per line, or separated by commas\ne.g. New, Follow-up, Emergency"}
            className={`${FIELD} py-2`}
          />
          <span className={FIELD_HINT}>The agent must pick one of these for the column.</span>
        </label>
      )}

      <label className="mt-3 block">
        <span className={FIELD_LABEL}>Reason — why this is needed (optional)</span>
        <input
          maxLength={200}
          value={row.reason}
          disabled={disabled}
          onChange={(event) => onChange({ reason: event.target.value })}
          placeholder="e.g. so we can route urgent cases to a doctor first"
          className={FIELD}
        />
        <span className={FIELD_HINT}>
          The AI uses this to fill the field more accurately. Leave blank to use just the
          name.
        </span>
      </label>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <ToggleSwitch
          label="Required"
          checked={row.required}
          disabled={disabled}
          onChange={(next) => onChange({ required: next })}
        />

        {row.isNew ? (
          <label className="block min-w-0">
            <span className={FIELD_LABEL}>Column id</span>
            <input
              value={effectiveKey(row)}
              disabled={disabled}
              onChange={(event) => onChange({ key: event.target.value, keyTouched: true })}
              className={`${FIELD} font-mono`}
            />
          </label>
        ) : (
          <span className="text-xs text-ink-muted">
            Column id: <span className="font-mono text-ink">{row.key}</span>
          </span>
        )}
      </div>
    </li>
  );
}
