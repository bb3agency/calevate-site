"use client";

import { Check, ChevronsUpDown, X } from "lucide-react";
import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { FIELD_LABEL } from "@/components/ui";

export interface SearchSelectOption {
  value: string;
  label: string;
  /** A short fact after the label, e.g. "2 of 3 to review". */
  hint?: string;
}

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
 * puts the chosen label back. `null` is the "every option" state, shown as `allLabel`.
 */
export function SearchSelect({
  label,
  options,
  value,
  onChange,
  allLabel,
  placeholder = "Type to search",
  className = "",
}: {
  label: string;
  options: SearchSelectOption[];
  value: string | null;
  onChange: (value: string | null) => void;
  allLabel: string;
  placeholder?: string;
  className?: string;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const input = useRef<HTMLInputElement>(null);
  const chosen = options.find((option) => option.value === value) ?? null;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const shown = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const matches = needle
      ? options.filter((option) => option.label.toLocaleLowerCase().includes(needle))
      : options;
    // The "every option" row leads only an unfiltered list: typing means looking for one.
    return needle ? matches : [{ value: "", label: allLabel }, ...matches];
  }, [options, query, allLabel]);

  const close = () => {
    setOpen(false);
    setQuery("");
  };
  const pick = (option: SearchSelectOption) => {
    onChange(option.value === "" ? null : option.value);
    close();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current) => (current + step + shown.length) % Math.max(shown.length, 1));
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      const option = shown[active];
      if (option) pick(option);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      close();
    }
  };

  const activeOption = open ? shown[active] : undefined;
  return (
    <div className={`relative ${className}`}>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <div className="relative mt-1">
        <input
          ref={input}
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeOption ? `${id}-opt-${active}` : undefined}
          autoComplete="off"
          spellCheck={false}
          className="w-full rounded-md border border-line bg-surface py-1.5 pl-3 pr-14 text-sm text-ink placeholder:text-ink-muted touch:min-h-11 transition-[border-color] duration-(--duration-fast) ease-out focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/25"
          placeholder={open ? placeholder : (chosen?.label ?? allLabel)}
          value={open ? query : (chosen?.label ?? "")}
          onChange={(event) => {
            setQuery(event.target.value);
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
        <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center gap-1 text-ink-faint">
          <ChevronsUpDown aria-hidden className="h-4 w-4" />
        </span>
        {chosen && !open && (
          <button
            type="button"
            onClick={() => onChange(null)}
            aria-label={`Clear ${label.toLowerCase()}: show ${allLabel.toLowerCase()}`}
            className="absolute inset-y-0 right-7 my-auto flex h-7 w-7 items-center justify-center rounded text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <X aria-hidden className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <ul
        id={listId}
        role="listbox"
        aria-label={label}
        hidden={!open}
        className="absolute z-dropdown mt-1 max-h-72 w-full overflow-y-auto overscroll-contain rounded-md border border-line bg-surface py-1 shadow-[0_8px_24px_-12px_rgb(0_0_0/0.25),0_2px_6px_-2px_rgb(0_0_0/0.08)]"
      >
        {shown.length === 0 ? (
          <li className="px-3 py-2 text-sm text-ink-muted">Nothing matches “{query.trim()}”</li>
        ) : (
          shown.map((option, index) => {
            const selected = (option.value || null) === value;
            return (
              <li
                key={option.value || "__all"}
                id={`${id}-opt-${index}`}
                role="option"
                aria-selected={selected}
                // `onMouseDown` + preventDefault keeps focus in the input, so blur does not
                // close the list before the click registers.
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(option);
                }}
                onMouseMove={() => setActive(index)}
                className={`flex cursor-pointer items-baseline gap-2 px-3 py-2 text-sm touch:min-h-11 ${
                  index === active ? "bg-ink/[0.05]" : ""
                }`}
              >
                <Check
                  aria-hidden
                  className={`h-3.5 w-3.5 shrink-0 self-center text-brand-strong ${selected ? "" : "invisible"}`}
                />
                <span className="min-w-0 flex-1 truncate text-ink">{option.label}</span>
                {option.hint && <span className="shrink-0 text-xs text-ink-muted">{option.hint}</span>}
              </li>
            );
          })
        )}
      </ul>
    </div>
  );
}
