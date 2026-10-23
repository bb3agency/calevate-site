"use client";

/**
 * Drag-down-to-dismiss for the kit's bottom sheets: `ModalDialog` and `Drawer` are sheets
 * below `sm` (640px) and a centred dialog or a side drawer above it, and this adds the one
 * thing a phone sheet is expected to do that a button cannot — follow the thumb down and go.
 *
 * Adapted from uiarc's `bottom-sheet` (MIT, see ./LICENSE), keeping its gesture and none of
 * its Radix dialog: the sheets already own their focus contract (`lib/focusTrap`) and stay
 * non-inert so a toast raised from inside one is still announced.
 *
 * The gesture lives on a grab strip at the top of the sheet only, never on its scrolling
 * body, so a list inside the sheet scrolls rather than dragging the sheet. It tracks the
 * pointer 1:1 (pointer capture, the grab offset kept), resists upward pulls (rubber band),
 * and decides on release from distance OR velocity, so a short flick closes it as a long
 * drag does. It is off above `sm`, for a mouse, and under reduced motion; there the sheet
 * still closes by its close button, its scrim and Escape, so nothing depends on the drag.
 */

import { useCallback, useRef, type PointerEvent as ReactPointerEvent, type RefObject } from "react";

/** The sheet breakpoint: below Tailwind's `sm`, where `MODAL_PANEL` and `Drawer` are sheets. */
const SHEET_QUERY = "(max-width: 39.98rem)";
/** A release faster than this (px per ms, downwards) closes the sheet whatever the distance. */
const FLICK_VELOCITY = 0.5;
/** A release past this share of the sheet's height closes it. */
const CLOSE_SHARE = 0.3;
const SNAP_BACK = "transform 280ms var(--ease-drawer-curve)";
const SLIDE_OUT = "transform 180ms var(--ease-out-strong)";

/** Progressive resistance past a boundary: the further the pull, the less the sheet follows. */
export function rubberBand(overshoot: number, dimension: number, constant = 0.55): number {
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}

/** Whether a release closes the sheet: far enough down, or flicked down fast enough. */
export function releaseCloses(offset: number, velocity: number, height: number): boolean {
  if (offset <= 0) return false;
  return velocity > FLICK_VELOCITY || offset > height * CLOSE_SHARE;
}

type Drag = { pointerId: number; startY: number; samples: { t: number; y: number }[] };

function matches(query: string): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
}

export function useSheetDrag(
  panel: RefObject<HTMLElement | null>,
  {
    onDismiss,
    willDismiss = () => true,
  }: {
    /** Close the sheet (the same path as its close button). */
    onDismiss: () => void;
    /**
     * False when closing would first ask a question (unsaved edits): the sheet then springs
     * back and `onDismiss` is called so the question can be asked in place.
     */
    willDismiss?: () => boolean;
  },
) {
  const drag = useRef<Drag | null>(null);

  const settle = useCallback(
    (closing: boolean) => {
      const el = panel.current;
      if (!el) return;
      if (closing && willDismiss()) {
        el.style.transition = SLIDE_OUT;
        el.style.transform = "translateY(100%)";
        let done = false;
        const finish = () => {
          if (done) return;
          done = true;
          onDismiss();
        };
        el.addEventListener("transitionend", finish, { once: true });
        window.setTimeout(finish, 220);
        return;
      }
      el.style.transition = SNAP_BACK;
      el.style.transform = "";
      if (closing) onDismiss();
      el.addEventListener(
        "transitionend",
        () => {
          el.style.transition = "";
        },
        { once: true },
      );
    },
    [panel, onDismiss, willDismiss],
  );

  const onPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (event.pointerType === "mouse" || drag.current) return;
      if (!matches(SHEET_QUERY) || matches("(prefers-reduced-motion: reduce)")) return;
      const el = panel.current;
      if (!el) return;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      drag.current = {
        pointerId: event.pointerId,
        startY: event.clientY,
        samples: [{ t: event.timeStamp, y: event.clientY }],
      };
      el.style.transition = "none";
    },
    [panel],
  );

  const onPointerMove = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      const current = drag.current;
      const el = panel.current;
      if (!current || !el || event.pointerId !== current.pointerId) return;
      const dy = event.clientY - current.startY;
      const offset = dy >= 0 ? dy : -rubberBand(-dy, el.offsetHeight || 1);
      el.style.transform = `translateY(${offset}px)`;
      current.samples = [...current.samples.slice(-4), { t: event.timeStamp, y: event.clientY }];
    },
    [panel],
  );

  const onPointerEnd = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      const current = drag.current;
      const el = panel.current;
      if (!current || event.pointerId !== current.pointerId) return;
      drag.current = null;
      if (!el) return;
      const first = current.samples[0];
      const last = current.samples[current.samples.length - 1];
      const elapsed = Math.max(1, last.t - first.t);
      const velocity = (last.y - first.y) / elapsed;
      const offset = event.clientY - current.startY;
      settle(event.type !== "pointercancel" && releaseCloses(offset, velocity, el.offsetHeight || 1));
    },
    [panel, settle],
  );

  return { onPointerDown, onPointerMove, onPointerUp: onPointerEnd, onPointerCancel: onPointerEnd };
}

/**
 * The grab strip: a visible handle on a phone, nothing above `sm`. Decorative to assistive
 * tech (`aria-hidden`), because the sheet's close button is the accessible way out.
 */
export function SheetHandle(props: ReturnType<typeof useSheetDrag>) {
  return (
    <div
      aria-hidden
      data-sheet-handle=""
      {...props}
      className="-mt-2 mb-1 flex h-6 shrink-0 touch-none cursor-grab items-center justify-center sm:hidden"
    >
      <span className="h-1 w-10 rounded-full bg-ink/20" />
    </div>
  );
}
