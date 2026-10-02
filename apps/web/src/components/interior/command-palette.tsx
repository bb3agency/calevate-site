"use client";

// Adapted from interior.dev (github.com/ddoemonn/interior @3148000), MIT License,
// Copyright (c) 2026 ozzy. Full notice: ./LICENSE.
//
// Changes from upstream: the fuzzy ranker and the combobox/listbox keyboard model are
// kept; results are GROUPED (each group a `role="group"` inside the listbox) and the
// caller owns the query, so a group can come from a server search; the layer is a modal
// dialog on `lib/focusTrap` (focus moves in, Tab stays in, Escape closes, focus returns to
// whatever opened it); there is NO open, close or highlight animation, because a palette is
// opened by keyboard many times a day and a motion there reads as lag (Emil Kowalski's
// frequency rule); repo tokens replace the stone palette; touch rows are 44px.

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Search } from "lucide-react";

import { useFocusTrap } from "@/lib/focusTrap";

const BOUNDARY = /[\s\-_/.:]/;

export type CommandItem = {
  id: string;
  label: string;
  /** The group heading this item is listed under. */
  group: string;
  /** A short fact on the right of the row: a slug, a section. */
  hint?: string;
  /** Extra text the query may match (a slug, a synonym). */
  keywords?: string;
};

function scoreOne(text: string, query: string): number {
  const t = text.toLowerCase();
  let cursor = 0;
  let total = 0;
  let streak = 0;
  for (let i = 0; i < query.length; i++) {
    const at = t.indexOf(query[i], cursor);
    if (at < 0) return -1;
    streak = at === cursor && i > 0 ? streak + 1 : 0;
    total += 2 + streak * 4;
    if (at === 0) total += 12;
    else if (BOUNDARY.test(t[at - 1])) total += 8;
    cursor = at + 1;
  }
  return total;
}

/** Fuzzy rank by label (and, slightly lower, keywords); list order breaks ties. */
export function rankCommands(items: readonly CommandItem[], query: string): CommandItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...items];
  const scored: { item: CommandItem; score: number; order: number }[] = [];
  items.forEach((item, order) => {
    const direct = scoreOne(item.label, q);
    const aliased = item.keywords ? scoreOne(item.keywords, q) - 3 : -1;
    const best = Math.max(direct, aliased);
    if (best < 0) return;
    scored.push({ item, score: best - item.label.length * 0.05, order });
  });
  scored.sort((a, b) => b.score - a.score || a.order - b.order);
  return scored.map((s) => s.item);
}

export type CommandPaletteProps = {
  /** Mounted while open; unmounting closes it and returns focus. */
  onClose: () => void;
  items: readonly CommandItem[];
  /** Group headings, in display order. A group with no matching item is omitted. */
  groups: readonly string[];
  query: string;
  onQueryChange: (next: string) => void;
  onSelect: (item: CommandItem) => void;
  /** Names the dialog and the search box. */
  label: string;
  placeholder?: string;
  emptyLabel?: string;
  /** A line under the results, e.g. a client search still in flight or refused. */
  footer?: ReactNode;
};

export function CommandPalette({
  onClose,
  items,
  groups,
  query,
  onQueryChange,
  onSelect,
  label,
  placeholder = "Search",
  emptyLabel = "Nothing matches",
  footer,
}: CommandPaletteProps) {
  const uid = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const pointer = useRef({ x: -1, y: -1 });
  const [pinned, setPinned] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useFocusTrap(panelRef, true, onClose);

  // Ranked, then regrouped in the caller's order, so arrow keys walk the list as drawn.
  const sections = useMemo(() => {
    const ranked = rankCommands(items, query);
    return groups
      .map((group) => ({ group, items: ranked.filter((item) => item.group === group) }))
      .filter((section) => section.items.length > 0);
  }, [items, groups, query]);
  const flat = useMemo(() => sections.flatMap((section) => section.items), [sections]);

  const activeId = flat.some((item) => item.id === pinned) ? pinned : (flat[0]?.id ?? null);
  const activeIndex = flat.findIndex((item) => item.id === activeId);
  const optionId = (id: string) => `${uid}-opt-${id}`;

  useEffect(() => {
    const timer = setTimeout(() => {
      setAnnouncement(
        flat.length === 0 ? emptyLabel : `${flat.length} ${flat.length === 1 ? "result" : "results"}`,
      );
    }, 400);
    return () => clearTimeout(timer);
  }, [flat.length, emptyLabel]);

  const reveal = (id: string) => {
    document.getElementById(optionId(id))?.scrollIntoView?.({ block: "nearest" });
  };

  const jump = (index: number) => {
    if (flat.length === 0) return;
    const next = flat[(index + flat.length) % flat.length];
    setPinned(next.id);
    reveal(next.id);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      jump((activeIndex < 0 ? -1 : activeIndex) + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      jump((activeIndex < 0 ? 0 : activeIndex) - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const target = flat[activeIndex];
      if (target) onSelect(target);
    }
    // Escape is the focus trap's: it closes from anywhere inside the dialog.
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center px-3 pt-[10vh] sm:px-4">
      {/* The scrim closes on click; it is not a control a keyboard needs (Escape is). */}
      <div aria-hidden onClick={onClose} className="absolute inset-0 bg-ink/40 dark:bg-black/65" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        className="relative flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(28,25,23,0.07),0_28px_56px_-24px_rgba(24,22,20,0.5)] focus-visible:outline-none"
      >
        <div className="flex h-12 shrink-0 items-center gap-2.5 border-b border-line px-4 touch:h-14">
          <Search aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
          <input
            type="text"
            role="combobox"
            aria-label={label}
            aria-expanded="true"
            aria-controls={`${uid}-list`}
            aria-autocomplete="list"
            aria-activedescendant={activeId ? optionId(activeId) : undefined}
            autoComplete="off"
            spellCheck={false}
            value={query}
            placeholder={placeholder}
            onChange={(event) => {
              onQueryChange(event.target.value);
              setPinned(null);
              if (listRef.current) listRef.current.scrollTop = 0;
            }}
            onKeyDown={onKeyDown}
            className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-faint"
          />
          <kbd className="hidden shrink-0 rounded border border-line px-1.5 font-mono text-[11px] text-ink-faint sm:inline">
            Esc
          </kbd>
        </div>
        {/* The aria-activedescendant combobox pattern: focus stays in the input, which owns
            the keyboard, so the listbox and its options are deliberately not focusable. */}
        {/* eslint-disable-next-line jsx-a11y/interactive-supports-focus */}
        <div
          ref={listRef}
          id={`${uid}-list`}
          role="listbox"
          aria-label={label}
          // Keeps focus in the search box when a row is clicked.
          onMouseDown={(event) => event.preventDefault()}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1.5"
        >
          {sections.map((section, s) => (
            <div key={section.group} role="group" aria-labelledby={`${uid}-g-${s}`} className="py-1">
              <div
                id={`${uid}-g-${s}`}
                role="presentation"
                className="px-2.5 pb-1 pt-1.5 text-[12px] font-medium text-ink-faint"
              >
                {section.group}
              </div>
              {section.items.map((item) => {
                const active = item.id === activeId;
                return (
                  // Keyboard selection is the combobox's (Up, Down, Enter); see the listbox.
                  // eslint-disable-next-line jsx-a11y/interactive-supports-focus, jsx-a11y/click-events-have-key-events
                  <div
                    key={item.id}
                    id={optionId(item.id)}
                    role="option"
                    aria-selected={active}
                    onPointerMove={(event) => {
                      const { x, y } = pointer.current;
                      if (event.clientX === x && event.clientY === y) return;
                      pointer.current = { x: event.clientX, y: event.clientY };
                      if (!active) setPinned(item.id);
                    }}
                    onClick={() => onSelect(item)}
                    className={`flex min-h-9 cursor-default items-center gap-3 rounded-lg px-2.5 py-1.5 touch:min-h-11 ${
                      active ? "bg-ink/[0.06] dark:bg-white/10" : ""
                    }`}
                  >
                    <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-ink">
                      {item.label}
                    </span>
                    {item.hint && (
                      <span className="max-w-[45%] shrink-0 truncate text-[12px] text-ink-faint">
                        {item.hint}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
          {flat.length === 0 && (
            <p className="px-3 py-8 text-center text-[13px] text-ink-muted">{emptyLabel}</p>
          )}
        </div>
        {footer && (
          <div className="shrink-0 border-t border-line px-4 py-2 text-[12px] text-ink-muted">{footer}</div>
        )}
        <span role="status" aria-live="polite" className="sr-only">
          {announcement}
        </span>
      </div>
    </div>,
    document.body,
  );
}
