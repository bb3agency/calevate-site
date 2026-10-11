"use client";

import { useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { MODAL_ACTIONS, MODAL_PANEL, MODAL_SCRIM } from "./ui";
import { useFocusTrap, type InitialFocus } from "@/lib/focusTrap";

/**
 * THE modal dialog: a scrim, a panel labelled by its title and described by its body,
 * the APG focus contract (`useFocusTrap`: focus moves in, Tab cycles inside, Escape
 * closes, focus returns to the opener), and a portal into `document.body`.
 *
 * The portal is the point. Rendered in place, a `fixed` modal is still painted inside
 * whatever stacking context its ancestors create (a sticky bar, a transformed card, the
 * assistant panel), so a page container could draw over it. From `document.body` it sits
 * in the root context and its layer (`z-modal`) means what the scale says.
 *
 * Mounting is opening: callers render it inside `{open && …}`, and unmounting hands focus
 * back. It renders only in the browser — every caller opens it from an interaction, so
 * there is no server render to match.
 */
export function ModalDialog({
  title,
  description,
  children,
  actions,
  onClose,
  initialFocus = "container",
}: {
  /** Becomes the dialog's accessible name. */
  title: string;
  /** The body a screen reader reads with the title (`aria-describedby`). */
  description: ReactNode;
  /** Anything after the description that is not part of it: a refusal, a field. */
  children?: ReactNode;
  /** The buttons. On a phone they stack full width, the last one on top. */
  actions?: ReactNode;
  /** Escape, and whatever the caller's own cancel button does. */
  onClose: () => void;
  initialFocus?: InitialFocus;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const bodyId = useId();
  useFocusTrap(panel, true, onClose, initialFocus);

  if (typeof document === "undefined") return null;
  return createPortal(
    <div className={MODAL_SCRIM}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        className={MODAL_PANEL}
      >
        <h2 id={titleId} className="text-[17px] font-semibold text-ink">
          {title}
        </h2>
        <div id={bodyId} className="mt-3 space-y-3 text-sm text-ink-muted">
          {description}
        </div>
        {children}
        {actions ? <div className={MODAL_ACTIONS}>{actions}</div> : null}
      </div>
    </div>,
    document.body,
  );
}
