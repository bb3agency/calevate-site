"use client";

// The keyboard model (arrows that skip disabled items and wrap, Home/End, type-ahead,
// Escape back to the trigger) is ported from interior.dev's dropdown
// (github.com/ddoemonn/interior @3148000, MIT License, Copyright (c) 2026 ozzy; notice in
// components/interior/LICENSE), with the catalogue's ADAPT fixes: it is an ACTION menu
// (role="menu", the APG menu-button pattern) rather than a select, it renders through a
// portal so a scrolling table cannot clip it, Escape does not also close an enclosing
// dialog, and Tab closes the menu without swallowing the keystroke.

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { MoreHorizontal } from "lucide-react";

import { usePopoverPlacement } from "@/components/interior/popover";

const EASE = [0.23, 1, 0.32, 1] as const;

export type RowMenuItem = {
  id: string;
  label: string;
  /** Runs on choose. Omit when `href` is given. */
  onSelect?: () => void;
  /** Navigates instead. In-realm callers pass the result of `href()` from the realm. */
  href?: string;
  /** A destructive action: red text. Still confirm it where it is irreversible. */
  tone?: "danger";
  disabled?: boolean;
  /**
   * Why it is disabled, or a short qualifier, shown on the right. It DESCRIBES the item
   * rather than naming it, so a screen reader hears "Release" and then why, instead of one
   * run-on name.
   */
  hint?: string;
  /**
   * The item's accessible name, when the visible label leans on what is around it — a
   * short "Remove" beside a person's name reads as "Remove" alone in the menu.
   */
  ariaLabel?: string;
  icon?: ReactNode;
};

/**
 * THE ROW'S "MORE" MENU — the secondary actions on one row of a list (archive, rename,
 * open the record), behind a ⋯ button so the row itself stays one target (UX-DOCTRINE §4).
 *
 * `label` names the row: the button reads "More actions for Reception", because a table
 * of buttons all called "More" cannot be told apart. Focus moves into the menu on open
 * and back to the button on close. Items that would be refused are shown disabled with
 * their reason as the hint rather than hidden.
 */
export function RowMenu({
  label,
  items,
  align = "end",
  className = "",
}: {
  /** The row's name: "Reception" → "More actions for Reception". */
  label: string;
  items: RowMenuItem[];
  align?: "start" | "end";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const menuId = useId();
  const reduced = useReducedMotion();
  const triggerRef = useRef<HTMLElement | null>(null);
  const itemRefs = useRef<(HTMLElement | null)[]>([]);
  const firstFocus = useRef<"first" | "last">("first");
  const buffer = useRef({ text: "", at: 0 });
  const { wrapRef, panelRef, contentRef } = usePopoverPlacement({
    open,
    anchorRef: triggerRef,
    side: "bottom",
    align,
    offset: 4,
    padding: 8,
  });

  useEffect(() => setMounted(true), []);

  const enabled = items.map((item, i) => (item.disabled ? -1 : i)).filter((i) => i >= 0);
  const focusItem = useCallback((i: number) => itemRefs.current[i]?.focus(), []);

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const target = firstFocus.current === "first" ? enabled[0] : enabled[enabled.length - 1];
    if (target !== undefined) focusItem(target);
    else panelRef.current?.focus();
    // Only on open: re-running on every render would pull focus back to the first item.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      const node = event.target as Node;
      if (panelRef.current?.contains(node) || triggerRef.current?.contains(node)) return;
      close(false);
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [open, close, panelRef]);

  const openWith = (where: "first" | "last") => {
    firstFocus.current = where;
    setOpen(true);
  };

  const choose = (item: RowMenuItem) => {
    if (item.disabled) return;
    close(!item.href);
    item.onSelect?.();
  };

  const onMenuKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const at = itemRefs.current.findIndex((node) => node === document.activeElement);
    const pos = enabled.indexOf(at);
    const move = (to: number) => {
      event.preventDefault();
      const target = enabled[(to + enabled.length) % enabled.length];
      if (target !== undefined) focusItem(target);
    };
    if (event.key === "ArrowDown") move(pos + 1);
    else if (event.key === "ArrowUp") move(pos < 0 ? -1 : pos - 1);
    else if (event.key === "Home") move(0);
    else if (event.key === "End") move(enabled.length - 1);
    else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === "Tab") {
      // Close and let the Tab continue from the trigger, rather than swallowing it.
      close(true);
    } else if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
      const now = Date.now();
      buffer.current = {
        text: (now - buffer.current.at < 600 ? buffer.current.text : "") + event.key.toLowerCase(),
        at: now,
      };
      const hit = enabled.find((i) => items[i].label.toLowerCase().startsWith(buffer.current.text));
      if (hit !== undefined) {
        event.preventDefault();
        focusItem(hit);
      }
    }
  };

  const itemClass = (item: RowMenuItem) =>
    `flex h-9 w-full cursor-default items-center gap-2.5 rounded-[7px] px-2.5 text-left text-[13px] outline-none touch:min-h-11 focus:bg-ink/[0.06] hover:bg-ink/[0.04] ${
      item.disabled ? "text-ink-faint" : item.tone === "danger" ? "text-danger" : "text-ink"
    }`;

  const menu = (
    <AnimatePresence>
      {open ? (
        <div key="menu" ref={wrapRef} className="fixed left-0 top-0 z-50">
          <motion.div
            ref={panelRef}
            id={menuId}
            role="menu"
            aria-label={`Actions for ${label}`}
            tabIndex={-1}
            onKeyDown={onMenuKey}
            initial={reduced ? { opacity: 1 } : { opacity: 0, scale: 0.96, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={reduced ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, scale: 0.98, transition: { duration: 0.1, ease: EASE } }}
            transition={reduced ? { duration: 0 } : { duration: 0.15, ease: EASE }}
            className="w-max min-w-48 max-w-[calc(100vw-1rem)] rounded-[10px] border border-line bg-surface p-1 shadow-raised focus-visible:outline-none"
          >
            <div ref={contentRef} className="overflow-y-auto">
              {items.map((item, i) => {
                const body = (
                  <>
                    {item.icon && <span aria-hidden className="shrink-0 text-ink-faint">{item.icon}</span>}
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.hint && (
                      <span id={`${menuId}-${item.id}-hint`} className="shrink-0 text-[12px] text-ink-faint">
                        {item.hint}
                      </span>
                    )}
                  </>
                );
                const common = {
                  role: "menuitem" as const,
                  tabIndex: -1,
                  "aria-disabled": item.disabled || undefined,
                  "aria-label": item.ariaLabel ?? (item.hint ? item.label : undefined),
                  "aria-describedby": item.hint ? `${menuId}-${item.id}-hint` : undefined,
                  className: itemClass(item),
                };
                return item.href && !item.disabled ? (
                  <Link
                    key={item.id}
                    href={item.href}
                    ref={(node) => {
                      itemRefs.current[i] = node;
                    }}
                    onClick={() => choose(item)}
                    {...common}
                  >
                    {body}
                  </Link>
                ) : (
                  <button
                    key={item.id}
                    type="button"
                    ref={(node) => {
                      itemRefs.current[i] = node;
                    }}
                    onClick={() => choose(item)}
                    {...common}
                  >
                    {body}
                  </button>
                );
              })}
            </div>
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );

  return (
    <>
      <button
        ref={(node) => {
          triggerRef.current = node;
        }}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`More actions for ${label}`}
        onClick={() => (open ? close(true) : openWith("first"))}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            openWith("first");
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            openWith("last");
          }
        }}
        className={`press relative z-[1] inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.06] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11 ${
          open ? "bg-ink/[0.06] text-ink" : ""
        } ${className}`}
      >
        <MoreHorizontal aria-hidden className="h-4 w-4" />
      </button>
      {mounted ? createPortal(menu, document.body) : null}
    </>
  );
}
