"use client";

/**
 * ONE editable capture variable — the row the extraction editor repeats.
 *
 * Its own module for UX-DOCTRINE §6's reason: `extraction.tsx` held the list, the form,
 * the row and the archived read-only view, and the row is half of it. Nothing here reads
 * the network or the session — it is given a draft row and hands back a patch, which is
 * what makes it the piece a reviewer can hold in their head.
 */

import { useState } from "react";
import { ChevronDown, ChevronUp, Pencil, Trash2 } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  SECONDARY_BUTTON_SM,
  ToggleSwitch,
} from "@/components/ui";
import type { FormValidation } from "@/components/formValidation";
import { hasKey } from "@/lib/lookup";

import { FIELD_TYPE_COPY, effectiveKey, type DraftRow, type FieldType } from "./extractionDraft";
import type { VerticalExamples } from "@/lib/verticalExamples";

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
  eg,
  validation,
  noun = "variable",
  showKey = true,
}: {
  row: DraftRow;
  index: number;
  total: number;
  disabled: boolean;
  /**
   * This tenant's example text. A PROP, not a hook, because this file's own docstring is
   * the reason: it "does not touch the network or the session — it is given a draft row
   * and hands back a patch". Reaching for `/v1/me` here to fill one placeholder would
   * trade that away, and the parent already holds the answer.
   */
  eg: VerticalExamples;
  onChange: (patch: Partial<DraftRow>) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  /**
   * The LIST's validation, so a nameless variable is answered at the row it is in rather
   * than by one sentence under the whole editor.
   *
   * Ids are still not invented here — the hook mints them from a `useId` held by the
   * panel, so two editors for two agents on one screen get two id spaces, which is the
   * collision this file's docstring refuses to risk. The key is the row's `uid` and not
   * its index, for the same reason the copilot registration uses `uid`: the list can be
   * reordered while it is open.
   */
  validation: FormValidation;
  /** What one row is called on this screen: "variable" on the agent, "detail" on Lead details. */
  noun?: string;
  /** Show the storage id. The client's Lead details screen keeps it out of the way. */
  showKey?: boolean;
}) {
  const named = row.label.trim() || `this ${noun}`;
  const Noun = noun.charAt(0).toUpperCase() + noun.slice(1);
  // A saved variable is a one-line row until somebody edits it; a new one opens ready to
  // fill. Five fully-open editors were most of this screen's length.
  const [open, setOpen] = useState(row.isNew);
  const typeLabel = hasKey(FIELD_TYPE_COPY, row.type) ? FIELD_TYPE_COPY[row.type] : row.type;
  const controls = (
    <div className="flex shrink-0 items-center gap-1">
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
  );

  if (!open) {
    return (
      <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">{named}</span>
          <span className="block text-xs text-ink-muted">
            {typeLabel}
            {row.required ? " · Required" : ""}
            {showKey && (
              <>
                {" · "}
                <span className="font-mono">{row.key}</span>
              </>
            )}
          </span>
        </span>
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label={`Edit ${named}`}
          className={SECONDARY_BUTTON_SM}
        >
          <Pencil aria-hidden className="h-3.5 w-3.5" />
          Edit
        </button>
        {controls}
      </li>
    );
  }

  return (
    <li className="settings-enter py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-ink-muted">
          {Noun} {index + 1}
        </span>
        <div className="flex items-center gap-1">
          {!row.isNew && (
            <button type="button" onClick={() => setOpen(false)} className={SECONDARY_BUTTON_SM}>
              Done
            </button>
          )}
          {controls}
        </div>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="block">
            <span className={FIELD_LABEL}>Name</span>
            <input
              {...validation.field(`label-${row.uid}`, `Give this ${noun} a name.`)}
              required
              maxLength={80}
              value={row.label}
              disabled={disabled}
              onChange={(event) => onChange({ label: event.target.value })}
              placeholder={`e.g. ${eg.extractionLabel}`}
              className={FIELD}
            />
          </label>
          {validation.error(`label-${row.uid}`)}
        </div>
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
            placeholder={`One per line, or separated by commas\ne.g. ${eg.extractionOptions}`}
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
          placeholder={`e.g. ${eg.extractionReason}`}
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

        {!showKey ? null : row.isNew ? (
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
