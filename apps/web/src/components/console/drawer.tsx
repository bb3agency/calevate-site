"use client";

// Adapted from interior.dev's drawer (github.com/ddoemonn/interior @3148000, MIT License,
// Copyright (c) 2026 ozzy; notice in components/interior/LICENSE), per the catalogue's
// ADAPT notes: the focus contract is the repo's `useFocusTrap` (the one `ConfirmDialog`
// and `NavDrawer` use) instead of a second trap; it UNMOUNTS when closed, so heavy content
// (a player, a transcript) does not keep running; it does not make the rest of the page
// inert, so a toast raised from inside it is still announced; it is a bottom sheet on a
// phone; and it uses the repo's CSS entry convention (`scrim-enter` + an `@starting-style`
// panel) rather than a spring, like every other modal here.

import {
  createContext,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { DANGER_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import { useFocusTrap, type InitialFocus } from "@/lib/focusTrap";
import { UnsavedRegistry, type UnsavedRegistryValue } from "@/lib/useUnsavedGuard";

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
 *
 * ## A form in the body, its submit button in the footer
 *
 * The footer is a sibling of the body, not inside it, so a `type="submit"` button there
 * submits nothing unless it names the form — and a forgotten `form=` attribute is a button
 * that looks right and silently does nothing. Pass the body form's id as `formId` and use
 * `DrawerSubmit` in the footer: it takes the id from the drawer, so the binding cannot be
 * left off.
 *
 * ## Closing over unsaved typing
 *
 * Escape, the scrim and ✕ are one keystroke or one stray tap from discarding a half-typed
 * form. While the drawer holds unsaved edits — `dirty`, or any `useUnsavedGuard` call
 * inside it — those three ask first, in the drawer's own footer, rather than closing. A
 * second modal would fight this one's focus trap for Escape. A Cancel button the caller
 * renders is an explicit choice and is not intercepted.
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
  formId,
  dirty = false,
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
  /** The id of the `<form>` in the body that the footer's `DrawerSubmit` submits. */
  formId?: string;
  /** Unsaved edits the caller tracks itself; Escape, the scrim and ✕ then ask first. */
  dirty?: boolean;
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
      formId={formId}
      dirty={dirty}
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
  formId,
  dirty,
}: {
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width: keyof typeof WIDTHS;
  initialFocus: InitialFocus;
  closeLabel: string;
  formId?: string;
  dirty: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const keepEditing = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [asking, setAsking] = useState(false);

  // Drafts reported by `useUnsavedGuard` inside the body. Forwarded to an enclosing
  // registry (a `SettingsLayout` section) too, so a draft in a drawer still stops a
  // section switch behind it.
  const parent = useContext(UnsavedRegistry);
  const drafts = useRef(new Set<string>());
  const registry = useMemo<UnsavedRegistryValue>(
    () => ({
      report: (id, isDirty) => {
        if (isDirty) drafts.current.add(id);
        else drafts.current.delete(id);
        parent?.report(id, isDirty);
      },
    }),
    [parent],
  );

  const requestClose = () => {
    if (asking) {
      setAsking(false);
      return;
    }
    if (dirty || drafts.current.size > 0) setAsking(true);
    else onClose();
  };
  useFocusTrap(panel, true, requestClose, initialFocus);

  useEffect(() => {
    if (asking) keepEditing.current?.focus();
  }, [asking]);

  return (
    <div className="fixed inset-0 z-50">
      {/* The scrim closes the drawer, as `NavDrawer`'s does — a button, so it is a real
          control rather than a clickable div. It sits outside the panel, so Tab never
          cycles onto it. */}
      <button
        type="button"
        aria-label={closeLabel}
        tabIndex={-1}
        onClick={requestClose}
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
            onClick={requestClose}
            aria-label={closeLabel}
            className="press -mr-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">
          <UnsavedRegistry.Provider value={registry}>{children}</UnsavedRegistry.Provider>
        </div>
        {asking ? (
          <div
            role="group"
            aria-label="Unsaved changes"
            className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] sm:px-5 sm:pb-3"
          >
            <p role="alert" className="mr-auto text-[13px] text-ink">
              Close without saving? What you typed here will be lost.
            </p>
            <button ref={keepEditing} type="button" onClick={() => setAsking(false)} className={SECONDARY_BUTTON}>
              Keep editing
            </button>
            <button type="button" onClick={onClose} className={DANGER_BUTTON}>
              Discard changes
            </button>
          </div>
        ) : (
          footer && (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] sm:px-5 sm:pb-3">
              <DrawerForm.Provider value={formId}>{footer}</DrawerForm.Provider>
            </div>
          )
        )}
      </div>
    </div>
  );
}

const DrawerForm = createContext<string | undefined>(undefined);

/**
 * The footer's submit button, bound to the drawer's `formId`. Rendered outside a drawer
 * that names its form it would submit nothing, so that is refused at render rather than
 * discovered by a person pressing a dead button.
 */
export function DrawerSubmit(props: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type" | "form">) {
  const form = useContext(DrawerForm);
  if (form === undefined) {
    throw new Error("DrawerSubmit must be in the footer of a Drawer given a formId.");
  }
  return <button {...props} type="submit" form={form} />;
}
