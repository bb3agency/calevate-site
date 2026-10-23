"use client";

/**
 * ONE CHOICE FROM A LONG LIST, FOUND BY TYPING — the WAI-ARIA 1.2 "select-only combobox
 * with list autocomplete" (an `input[role=combobox]` owning a `listbox`).
 *
 * A native `<select>` is right up to a dozen options and wrong at a hundred clients: it
 * cannot be searched beyond first-letter jumps, and on a phone it opens a wheel of every
 * name. The command palette is the other searchable list in this tree, and it navigates;
 * this one sets a value and stays put.
 *
 * Typing filters; the arrows move the active option; Enter picks it; Escape closes and
 * puts the chosen label back. With `allLabel`, `null` is the "every option" state and the
 * value can be cleared; without it a choice is required and there is no clear button.
 *
 * Async: pass `onQueryChange` and the component stops filtering locally — the caller
 * fetches and hands back `options`, with `loading` while it does.
 *
 * The list opens inside the component (`z-dropdown`), not in a portal, so it scrolls with
 * the form it belongs to, including inside a drawer.
 */

import { Check, ChevronsUpDown, LoaderCircle, X } from "lucide-react";
import { useMemo, useState, type KeyboardEvent } from "react";
import clsx from "clsx";



import { FIELD_FLUSH, Field } from "./field";

export type ComboboxOption = {
  value: string;
  label: string;
  /** A short fact after the label, e.g. "2 of 3 to review". */
  hint?: string;
  disabled?: boolean;
};

export type ComboboxProps = {
  label: string;
  hideLabel?: boolean;
  hint?: string;
  error?: string | null;
  options: ComboboxOption[];
  value: string | null;
  onChange: (value: string | null) => void;
  /** Names the `null` choice ("All clients") and makes the value clearable. */
  allLabel?: string;
  placeholder?: string;
  /** Server-side search: called with the typed text; local filtering is switched off. */
  onQueryChange?: (query: string) => void;
  loading?: boolean;
  loadingText?: string;
  emptyText?: (query: string) => string;
  clearLabel?: string;
  disabled?: boolean;
  className?: string;
};

const ALL = "";

export function Combobox({
  label,
  hideLabel,
  hint,
  error,
  options,
  value,
  onChange,
  allLabel,
  placeholder = "Type to search",
  onQueryChange,
  loading = false,
  loadingText = "Looking…",
  emptyText = (query) => `Nothing matches “${query}”`,
  clearLabel,
  disabled = false,
  className,
}: ComboboxProps) {
  const chosen = options.find((option) => option.value === value) ?? null;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const shown = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const matches =
      needle && !onQueryChange
        ? options.filter((option) => option.label.toLocaleLowerCase().includes(needle))
        : options;
    // The "every option" row leads only an unfiltered list: typing means looking for one.
    return allLabel !== undefined && !needle ? [{ value: ALL, label: allLabel }, ...matches] : matches;
  }, [options, query, allLabel, onQueryChange]);

  const setTyped = (text: string) => {
    setQuery(text);
    onQueryChange?.(text);
  };
  const close = () => {
    setOpen(false);
    if (query !== "") setTyped("");
  };
  const pick = (option: ComboboxOption) => {
    if (option.disabled) return;
    onChange(option.value === ALL && allLabel !== undefined ? null : option.value);
    close();
  };
  const move = (step: number) => {
    if (shown.length === 0) return;
    let next = active;
    for (let tries = 0; tries < shown.length; tries += 1) {
      next = (next + step + shown.length) % shown.length;
      if (!shown[next]?.disabled) break;
    }
    setActive(next);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      move(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      const option = shown[active];
      if (option) pick(option);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  };

  const clearable = allLabel !== undefined && chosen !== null && !open && !disabled;
  return (
    <Field label={label} hideLabel={hideLabel} hint={hint} error={error} className={clsx("relative", className)}>
      {(control) => {
        const listId = `${control.id}-list`;
        const activeOption = open ? shown[active] : undefined;
        return (
          <>
            <div className="relative mt-1">
              <input
                {...control}
                role="combobox"
                aria-expanded={open}
                aria-controls={listId}
                aria-autocomplete="list"
                aria-activedescendant={activeOption ? `${control.id}-opt-${active}` : undefined}
                aria-busy={loading || undefined}
                autoComplete="off"
                spellCheck={false}
                disabled={disabled}
                className={clsx(FIELD_FLUSH, "pr-14 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-ink-faint")}
                placeholder={open ? placeholder : (chosen?.label ?? allLabel ?? placeholder)}
                value={open ? query : (chosen?.label ?? "")}
                onChange={(event) => {
                  setTyped(event.target.value);
                  setActive(0);
                  setOpen(true);
                }}
                onFocus={() => {
                  setOpen(true);
                  setActive(0);
                }}
                // Closing on blur waits a tick so a pointer press on an option lands first.
                onBlur={() => window.setTimeout(close, 120)}
                onKeyDown={onKeyDown}
              />
              <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-ink-faint">
                {loading ? (
                  <LoaderCircle aria-hidden className="h-4 w-4 motion-safe:animate-spin" />
                ) : (
                  <ChevronsUpDown aria-hidden className="h-4 w-4" />
                )}
              </span>
              {clearable ? (
                <button
                  type="button"
                  onClick={() => onChange(null)}
                  aria-label={clearLabel ?? `Clear ${label}: show ${allLabel}`}
                  className="absolute inset-y-0 right-7 my-auto flex h-7 w-7 items-center justify-center rounded text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
                >
                  <X aria-hidden className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
            <ul
              id={listId}
              role="listbox"
              aria-label={label}
              hidden={!open}
              className="absolute z-dropdown mt-1 max-h-72 w-full overflow-y-auto overscroll-contain rounded-md border border-line bg-surface py-1 shadow-raised"
            >
              {loading && shown.length === 0 ? (
                <li role="presentation" className="px-3 py-2 text-sm text-ink-muted">
                  {loadingText}
                </li>
              ) : shown.length === 0 ? (
                <li role="presentation" className="px-3 py-2 text-sm text-ink-muted">
                  {emptyText(query.trim())}
                </li>
              ) : (
                shown.map((option, index) => {
                  const selected = (option.value === ALL && allLabel !== undefined ? null : option.value) === value;
                  return (
                    <li
                      key={option.value || "__all"}
                      id={`${control.id}-opt-${index}`}
                      role="option"
                      aria-selected={selected}
                      aria-disabled={option.disabled || undefined}
                      // `onMouseDown` + preventDefault keeps focus in the input, so blur does not
                      // close the list before the click registers.
                      onMouseDown={(event) => {
                        event.preventDefault();
                        pick(option);
                      }}
                      onMouseMove={() => setActive(index)}
                      className={clsx(
                        "flex cursor-pointer items-baseline gap-2 px-3 py-2 text-sm touch:min-h-11",
                        index === active && "bg-ink/[0.05]",
                        option.disabled && "cursor-not-allowed opacity-60",
                      )}
                    >
                      <Check
                        aria-hidden
                        className={clsx("h-3.5 w-3.5 shrink-0 self-center text-brand-strong", !selected && "invisible")}
                      />
                      <span className="min-w-0 flex-1 truncate text-ink">{option.label}</span>
                      {option.hint && <span className="shrink-0 text-xs text-ink-muted">{option.hint}</span>}
                    </li>
                  );
                })
              )}
            </ul>
          </>
        );
      }}
    </Field>
  );
}
