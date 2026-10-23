"use client";

/**
 * A SHORT LIST OF FREE-TEXT VALUES: the choices of an "enum" lead field, keywords. Type and
 * press Enter (or a comma) to add; Backspace in the empty box removes the last; each tag has
 * its own remove button. Suggestions, when given, filter as you type and are picked with the
 * arrows and Enter. Adapted from uiarc's `tag-input` (MIT, see ./LICENSE): the layout
 * animation is dropped and every string is a prop.
 *
 * Tags are compared without case, so "Follow-up" and "follow-up" cannot both be added;
 * the refusal is said under the field rather than silently ignored.
 */

import { useMemo, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import clsx from "clsx";

import { formatCount } from "@/components/ui";

import { Field } from "./field";

export type TagInputProps = {
  label: string;
  hint?: string;
  /** A refusal from the form (server or submit check); the component's own refusals show too. */
  error?: string | null;
  value: string[];
  onChange: (value: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
  maxTags?: number;
  maxLength?: number;
  /** Return a sentence to refuse a tag, or null to accept it. */
  validate?: (tag: string) => string | null;
  duplicateMessage?: (tag: string) => string;
  limitMessage?: (max: number) => string;
  removeLabel?: (tag: string) => string;
  disabled?: boolean;
  className?: string;
};

export function TagInput({
  label,
  hint,
  error,
  value,
  onChange,
  suggestions = [],
  placeholder = "Type and press Enter",
  maxTags = 30,
  maxLength = 40,
  validate,
  duplicateMessage = (tag) => `“${tag}” is already in the list.`,
  limitMessage = (max) => `Up to ${formatCount(max)} entries.`,
  removeLabel = (tag) => `Remove ${tag}`,
  disabled = false,
  className,
}: TagInputProps) {
  const [draft, setDraft] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);
  const [active, setActive] = useState(-1);
  const taken = useMemo(() => new Set(value.map((t) => t.toLocaleLowerCase())), [value]);
  const matches = useMemo(() => {
    const needle = draft.trim().toLocaleLowerCase();
    if (!needle) return [];
    return suggestions
      .filter((s) => !taken.has(s.toLocaleLowerCase()) && s.toLocaleLowerCase().includes(needle))
      .slice(0, 8);
  }, [draft, suggestions, taken]);

  const add = (raw: string) => {
    const tag = raw.trim().replace(/\s+/g, " ");
    if (!tag) return;
    if (taken.has(tag.toLocaleLowerCase())) return setRefusal(duplicateMessage(tag));
    if (value.length >= maxTags) return setRefusal(limitMessage(maxTags));
    const problem = validate?.(tag) ?? null;
    if (problem) return setRefusal(problem);
    onChange([...value, tag]);
    setDraft("");
    setRefusal(null);
    setActive(-1);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add(active >= 0 && matches[active] ? matches[active] : draft);
    } else if (event.key === "Backspace" && draft === "" && value.length > 0) {
      onChange(value.slice(0, -1));
    } else if ((event.key === "ArrowDown" || event.key === "ArrowUp") && matches.length > 0) {
      event.preventDefault();
      // -1 is the typed text itself; the arrows cycle through it and the suggestions.
      setActive((current) =>
        event.key === "ArrowDown"
          ? current + 1 >= matches.length ? -1 : current + 1
          : current - 1 < -1 ? matches.length - 1 : current - 1,
      );
    } else if (event.key === "Escape" && draft !== "") {
      event.preventDefault();
      event.stopPropagation();
      setDraft("");
      setActive(-1);
    }
  };

  const shownError = refusal ?? error ?? null;
  return (
    <Field label={label} hint={hint} error={shownError} className={className}>
      {(control) => {
        const listId = `${control.id}-suggestions`;
        return (
          <div className="relative mt-1">
            <div
              className={clsx(
                "flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border bg-surface px-1.5 py-1 transition-[border-color] duration-(--duration-fast) focus-within:border-brand has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand/25 touch:min-h-11",
                shownError ? "border-danger" : "border-line",
                disabled && "bg-surface-muted",
              )}
            >
              <ul className="contents" aria-label={label}>
                {value.map((tag) => (
                  <li key={tag} className="inline-flex max-w-full items-center gap-0.5 rounded-full bg-ink/[0.06] py-0.5 pl-2.5 pr-0.5 text-meta text-ink">
                    <span className="min-w-0 truncate">{tag}</span>
                    <button
                      type="button"
                      disabled={disabled}
                      aria-label={removeLabel(tag)}
                      onClick={() => onChange(value.filter((t) => t !== tag))}
                      className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-ink-muted hover:bg-ink/[0.08] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-9 touch:w-9"
                    >
                      <X aria-hidden className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
              <input
                {...control}
                role="combobox"
                aria-expanded={matches.length > 0}
                aria-controls={listId}
                aria-autocomplete="list"
                aria-activedescendant={active >= 0 && matches[active] ? `${listId}-${active}` : undefined}
                value={draft}
                disabled={disabled}
                maxLength={maxLength}
                enterKeyHint="enter"
                placeholder={value.length === 0 ? placeholder : undefined}
                onChange={(event) => {
                  setDraft(event.target.value);
                  setRefusal(null);
                  setActive(-1);
                }}
                onKeyDown={onKeyDown}
                onBlur={() => window.setTimeout(() => setActive(-1), 120)}
                className="min-w-24 flex-1 border-0 bg-transparent px-1 py-0.5 text-sm text-ink outline-none placeholder:text-ink-faint focus:outline-none"
              />
            </div>
            <ul
              id={listId}
              role="listbox"
              aria-label={label}
              hidden={matches.length === 0}
              className="absolute z-dropdown mt-1 max-h-60 w-full overflow-y-auto rounded-md border border-line bg-surface py-1 shadow-raised"
            >
              {matches.map((match, index) => (
                <li
                  key={match}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    add(match);
                  }}
                  className={clsx("cursor-pointer px-3 py-2 text-sm text-ink touch:min-h-11", index === active && "bg-ink/[0.05]")}
                >
                  {match}
                </li>
              ))}
            </ul>
          </div>
        );
      }}
    </Field>
  );
}
