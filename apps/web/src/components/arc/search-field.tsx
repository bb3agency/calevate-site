"use client";

/**
 * THE search box: a labelled `type="search"` input with a leading magnifier and a clear
 * button, for filtering a list. Adapted from uiarc's `search-field` (MIT, see ./LICENSE),
 * on `FIELD_INLINE_ICON`'s look, with what the catalogue asked for: an optional visually
 * hidden label, a 44px clear target on touch, Escape clears, every string a prop, and no
 * blur on the clear button.
 *
 * Calevate's list searches go to the API, so the component reports text two ways:
 * `onValueChange` on every keystroke (to keep the box controlled) and `onSearch` after the
 * typing settles (`debounceMs`), which is what a screen sends to the server. Enter calls
 * `onSearch` at once, so nobody waits out the debounce after pressing it.
 *
 * `ExpandingSearch` is the same field behind an icon button below `sm`, for a phone
 * toolbar that has no room for an always-open box; from `sm` up it is the plain field.
 */

import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState, type InputHTMLAttributes } from "react";
import { Search, X } from "lucide-react";
import clsx from "clsx";

import { FIELD_INLINE_ICON, FIELD_LABEL } from "@/components/ui";

export type SearchFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "onChange"> & {
  label: string;
  /** Keep the label for screen readers only, when the screen already says what is searched. */
  hideLabel?: boolean;
  value: string;
  onValueChange: (value: string) => void;
  /** The settled query, after `debounceMs` without typing, on Enter, and on clear. */
  onSearch?: (query: string) => void;
  debounceMs?: number;
  clearLabel?: string;
  /** Pressing "/" anywhere outside a field focuses this box. One per screen. */
  slashToFocus?: boolean;
  /** Extra classes for the wrapper (its width). */
  className?: string;
};

export const SearchField = forwardRef<HTMLInputElement, SearchFieldProps>(function SearchField(
  {
    label,
    hideLabel = false,
    value,
    onValueChange,
    onSearch,
    debounceMs = 300,
    clearLabel = "Clear search",
    slashToFocus = false,
    className,
    id,
    maxLength = 100,
    onKeyDown,
    ...rest
  },
  ref,
) {
  const generatedId = useId();
  const input = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => input.current as HTMLInputElement);
  const searchRef = useRef(onSearch);
  searchRef.current = onSearch;
  const lastSent = useRef(value);

  // Debounced report of the settled query. A value equal to the last one sent (Enter
  // already sent it, or a parent reset) is not sent twice.
  useEffect(() => {
    if (!searchRef.current || value === lastSent.current) return undefined;
    const timer = window.setTimeout(() => {
      if (value === lastSent.current) return;
      lastSent.current = value;
      searchRef.current?.(value);
    }, debounceMs);
    return () => window.clearTimeout(timer);
  }, [value, debounceMs]);

  useEffect(() => {
    if (!slashToFocus) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      event.preventDefault();
      input.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [slashToFocus]);

  const send = (query: string) => {
    lastSent.current = query;
    searchRef.current?.(query);
  };
  const clear = () => {
    onValueChange("");
    send("");
    input.current?.focus();
  };

  const inputId = id ?? generatedId;
  return (
    <div className={clsx("min-w-0", className)}>
      <label htmlFor={inputId} className={hideLabel ? "sr-only" : clsx(FIELD_LABEL, "mb-1")}>
        {label}
      </label>
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
        <input
          {...rest}
          ref={input}
          id={inputId}
          type="search"
          value={value}
          maxLength={maxLength}
          enterKeyHint="search"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            onKeyDown?.(event);
            if (event.defaultPrevented) return;
            if (event.key === "Escape" && value !== "") {
              // Escape empties the box first; a second Escape is left to the page.
              event.preventDefault();
              event.stopPropagation();
              clear();
            } else if (event.key === "Enter") {
              event.preventDefault();
              send(value);
            }
          }}
          className={clsx(
            FIELD_INLINE_ICON,
            "w-full pr-9 touch:pr-12 [&::-webkit-search-cancel-button]:appearance-none",
          )}
        />
        {value !== "" ? (
          <button
            type="button"
            onClick={clear}
            aria-label={clearLabel}
            className="absolute inset-y-0 right-0.5 my-auto grid h-7 w-7 place-items-center rounded text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <X aria-hidden className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
    </div>
  );
});

export type ExpandingSearchProps = SearchFieldProps & {
  /** The icon button's accessible name on a phone. Default: the field's label. */
  openLabel?: string;
};

/**
 * A search field that is an icon button on a phone and opens to full width when pressed.
 * It closes again on Escape or when it loses focus while empty, and gives focus back to
 * the button. From `sm` up it is always open.
 */
export function ExpandingSearch({ openLabel, className, ...field }: ExpandingSearchProps) {
  const [expanded, setExpanded] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const open = expanded || field.value !== "";

  const refocusButton = useRef(false);
  useEffect(() => {
    if (expanded) input.current?.focus();
    else if (refocusButton.current) {
      refocusButton.current = false;
      button.current?.focus();
    }
  }, [expanded]);

  return (
    <div className={clsx("min-w-0", open ? "flex-1" : "", className)}>
      <button
        ref={button}
        type="button"
        aria-label={openLabel ?? field.label}
        aria-expanded={open}
        onClick={() => setExpanded(true)}
        className={clsx(
          "press h-9 w-9 place-items-center rounded-md border border-line bg-surface text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11 sm:hidden",
          open ? "hidden" : "grid",
        )}
      >
        <Search aria-hidden className="h-4 w-4" />
      </button>
      <div className={clsx(open ? "block" : "hidden sm:block")}>
        <SearchField
          {...field}
          ref={input}
          hideLabel={field.hideLabel ?? true}
          onKeyDown={(event) => {
            field.onKeyDown?.(event);
            if (event.key === "Escape" && field.value === "" && expanded) {
              refocusButton.current = true;
              setExpanded(false);
            }
          }}
          onBlur={(event) => {
            field.onBlur?.(event);
            if (field.value === "") setExpanded(false);
          }}
        />
      </div>
    </div>
  );
}
