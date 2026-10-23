"use client";

/**
 * SEVERAL CHOICES FROM A LIST: a button that summarises what is picked and opens a
 * checkbox list in a popover. Adapted from uiarc's `multi-select` (MIT, see ./LICENSE).
 *
 * Native checkboxes in a `fieldset` rather than a hand-rolled `listbox` with
 * `aria-multiselectable`: Tab and Space already work, a screen reader announces "checked"
 * without help, and nothing has to manage an active descendant. A filter box appears once
 * the list is long enough to need one (`filterFrom`).
 *
 * For up to about five options that fit on screen, show checkboxes or a `ChipGroup`
 * directly instead; a popover hides choices a person could have seen at a glance.
 */

import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import clsx from "clsx";

import { formatCount } from "@/components/ui";

import { Field, FIELD_FLUSH } from "./field";
import { Popover } from "./popover";

export type MultiSelectOption = { value: string; label: string; hint?: string; disabled?: boolean };

export type MultiSelectProps = {
  label: string;
  hideLabel?: boolean;
  hint?: string;
  error?: string | null;
  options: MultiSelectOption[];
  value: string[];
  onChange: (value: string[]) => void;
  /** What the button says with nothing picked ("Any status"). */
  emptyLabel?: string;
  /** "3 chosen". */
  countLabel?: (count: number) => string;
  /** Show a filter box once there are this many options. */
  filterFrom?: number;
  filterLabel?: string;
  selectAllLabel?: string;
  clearLabel?: string;
  disabled?: boolean;
  className?: string;
};

export function MultiSelect({
  label,
  hideLabel,
  hint,
  error,
  options,
  value,
  onChange,
  emptyLabel = "Any",
  countLabel = (count) => `${formatCount(count)} chosen`,
  filterFrom = 9,
  filterLabel = "Filter the list",
  selectAllLabel = "Choose all",
  clearLabel = "Clear",
  disabled = false,
  className,
}: MultiSelectProps) {
  const [filter, setFilter] = useState("");
  const chosen = useMemo(() => new Set(value), [value]);
  const shown = useMemo(() => {
    const needle = filter.trim().toLocaleLowerCase();
    return needle ? options.filter((o) => o.label.toLocaleLowerCase().includes(needle)) : options;
  }, [options, filter]);

  const picked = options.filter((o) => chosen.has(o.value));
  const summary =
    picked.length === 0
      ? emptyLabel
      : picked.length <= 2
        ? picked.map((o) => o.label).join(", ")
        : countLabel(picked.length);

  // Keep the caller's option order whatever order things were ticked in.
  const toggle = (option: MultiSelectOption, on: boolean) => {
    const next = new Set(chosen);
    if (on) next.add(option.value);
    else next.delete(option.value);
    onChange(options.filter((o) => next.has(o.value)).map((o) => o.value));
  };

  return (
    <Field label={label} hideLabel={hideLabel} hint={hint} error={error} className={className}>
      {(control) => (
        <div className="mt-1">
          <Popover
            label={label}
            align="start"
            className="w-[min(20rem,calc(100vw-1rem))] p-2"
            onOpenChange={(open) => {
              if (!open) setFilter("");
            }}
            trigger={
              <button
                type="button"
                {...control}
                disabled={disabled}
                className={clsx(
                  FIELD_FLUSH,
                  "flex items-center gap-2 text-left disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-ink-faint",
                )}
              >
                <span className={clsx("min-w-0 flex-1 truncate", picked.length === 0 && "text-ink-muted")}>{summary}</span>
                <ChevronDown aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
              </button>
            }
          >
            {options.length >= filterFrom ? (
              <input
                type="search"
                aria-label={filterLabel}
                placeholder={filterLabel}
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                className={clsx(FIELD_FLUSH, "mb-2")}
              />
            ) : null}
            <fieldset>
              <legend className="sr-only">{label}</legend>
              <div className="max-h-64 space-y-0.5 overflow-y-auto overscroll-contain">
                {shown.map((option) => (
                  <label
                    key={option.value}
                    className={clsx(
                      "flex min-h-9 cursor-pointer items-center gap-2.5 rounded-md px-2 text-sm text-ink hover:bg-ink/[0.04] touch:min-h-11",
                      option.disabled && "cursor-not-allowed text-ink-faint",
                    )}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 shrink-0 accent-(--brand-strong)"
                      checked={chosen.has(option.value)}
                      disabled={option.disabled}
                      onChange={(event) => toggle(option, event.target.checked)}
                    />
                    <span className="min-w-0 flex-1 truncate">{option.label}</span>
                    {option.hint ? <span className="shrink-0 text-xs text-ink-faint">{option.hint}</span> : null}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="mt-2 flex justify-between gap-2 border-t border-line pt-2">
              <button
                type="button"
                onClick={() => onChange(options.filter((o) => !o.disabled || chosen.has(o.value)).map((o) => o.value))}
                className="press rounded-md px-2 py-1 text-meta font-medium text-ink hover:bg-ink/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
              >
                {selectAllLabel}
              </button>
              <button
                type="button"
                onClick={() => onChange([])}
                disabled={value.length === 0}
                className="press rounded-md px-2 py-1 text-meta font-medium text-ink hover:bg-ink/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:text-ink-faint touch:min-h-11"
              >
                {clearLabel}
              </button>
            </div>
          </Popover>
        </div>
      )}
    </Field>
  );
}
