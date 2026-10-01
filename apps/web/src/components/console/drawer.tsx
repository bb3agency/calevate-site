"use client";

// Adapted from interior.dev's drawer (github.com/ddoemonn/interior @3148000, MIT License,
// Copyright (c) 2026 ozzy; notice in components/interior/LICENSE), per the catalogue's
// ADAPT notes: the focus contract is the repo's `useFocusTrap` (the one `ConfirmDialog`
// and `NavDrawer` use) instead of a second trap; it UNMOUNTS when closed, so heavy content
// (a player, a transcript) does not keep running; it does not make the rest of the page
// inert, so a toast raised from inside it is still announced; it is a bottom sheet on a
// phone; and it uses the repo's CSS entry convention (`scrim-enter` + an `@starting-style`
// panel) rather than a spring, like every other modal here.

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { useFocusTrap, type InitialFocus } from "@/lib/focusTrap";

const WIDTHS = {
  sm: "sm:w-[min(24rem,calc(100vw-2rem))]",
  md: "sm:w-[min(32rem,calc(100vw-2rem))]",
  lg: "sm:w-[min(44rem,calc(100vw-2rem))]",
} as const;

/**
 * A SIDE SHEET: a record's detail or a short create form opened OVER the list it belongs
 * to, so the list keeps its place. A panel from the right on a tablet or desktop; a sheet
 * that rises from the bottom and fills the screen on a phone.
 *
 * Modal, with the same contract as `ConfirmDialog`: focus moves inside on open (to the
 * first control, or to the panel with `initialFocus="container"` when it opens on text to
 * read), Tab cycles within, Escape and the scrim close it, and focus returns to what opened
 * it. It is rendered only while `open`, so its contents mount fresh each time.
 *
 * Use a page or a `StepFlow` instead when the thing has its own URL-worthy state or more
 * than a short form; a drawer is for a look or a quick edit.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = "md",
  initialFocus = "first-tabbable",
  closeLabel = "Close",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  /** One line under the title. */
  description?: ReactNode;
  children: ReactNode;
  /** The drawer's actions, pinned to its bottom edge: the primary one last. */
  footer?: ReactNode;
  width?: keyof typeof WIDTHS;
  initialFocus?: InitialFocus;
  closeLabel?: string;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted || !open) return null;
  return createPortal(
    <DrawerPanel
      onClose={onClose}
      title={title}
      description={description}
      footer={footer}
      width={width}
      initialFocus={initialFocus}
      closeLabel={closeLabel}
    >
      {children}
    </DrawerPanel>,
    document.body,
  );
}

function DrawerPanel({
  onClose,
  title,
  description,
  children,
  footer,
  width,
  initialFocus,
  closeLabel,
}: {
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width: keyof typeof WIDTHS;
  initialFocus: InitialFocus;
  closeLabel: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useFocusTrap(panel, true, onClose, initialFocus);

  return (
    <div className="fixed inset-0 z-50">
      {/* The scrim closes the drawer, as `NavDrawer`'s does — a button, so it is a real
          control rather than a clickable div. It sits outside the panel, so Tab never
          cycles onto it. */}
      <button
        type="button"
        aria-label={closeLabel}
        tabIndex={-1}
        onClick={onClose}
        className="scrim-enter absolute inset-0 bg-ink/40"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={`sheet-enter absolute inset-x-0 bottom-0 top-3 flex flex-col overflow-hidden rounded-t-2xl bg-surface shadow-overlay outline-none sm:inset-y-0 sm:left-auto sm:right-0 sm:top-0 sm:rounded-none sm:border-l sm:border-line ${WIDTHS[width]}`}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3.5 sm:px-5">
          <div className="min-w-0">
            <h2 id={titleId} className="text-[16px] font-semibold text-ink">
              {title}
            </h2>
            {description && (
              <p id={descriptionId} className="mt-0.5 text-[13px] text-ink-muted">
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            className="press -mr-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">{children}</div>
        {footer && (
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] sm:px-5 sm:pb-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
