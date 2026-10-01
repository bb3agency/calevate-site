"use client";

// Adapted from interior.dev (github.com/ddoemonn/interior @3148000), MIT License,
// Copyright (c) 2026 ozzy. Full notice: ./LICENSE.
//
// Changes from upstream: rendered through a portal into `document.body`, so a scrolling
// table or a `ScrollRegion` cannot clip it (upstream rendered inline, which the
// catalogue's ADAPT note names); the trigger is any element the caller renders through
// `renderTrigger`, so an icon button can be the anchor; closing by an outside press
// returns focus to the trigger as Escape already did; Escape no longer stops propagation
// for content that handles its own keys; colours are repo tokens.
//
// Positioning is the `position: fixed` + `getBoundingClientRect()` approach rather than
// the native Popover API with CSS anchor positioning. Anchor positioning is not yet in
// every browser our clients use, and the fallback the platform guidance recommends for it
// is exactly this one (modern-web-guidance "position-aware-tooltips", read 1 Oct 2026),
// so we ship the fallback everywhere instead of two code paths.

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";

const EASE = [0.23, 1, 0.32, 1] as const;
const RADIUS = 10;
const MIN_W = 160;
const MIN_H = 64;

const useIsoLayoutEffect = typeof document === "undefined" ? useEffect : useLayoutEffect;

export type PopoverSide = "top" | "bottom";
export type PopoverAlign = "start" | "center" | "end";

const FLIP: Record<PopoverSide, PopoverSide> = { top: "bottom", bottom: "top" };

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function usePlacement({
  open,
  anchorRef,
  side,
  align,
  offset,
  padding,
}: {
  open: boolean;
  anchorRef: RefObject<HTMLElement | null>;
  side: PopoverSide;
  align: PopoverAlign;
  offset: number;
  padding: number;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [resolved, setResolved] = useState<PopoverSide>(side);

  const update = useCallback(() => {
    const anchor = anchorRef.current;
    const wrap = wrapRef.current;
    const panel = panelRef.current;
    if (!anchor || !wrap || !panel) return;
    const content = contentRef.current;

    const a = anchor.getBoundingClientRect();
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const right = vw - padding;
    const bottom = vh - padding;
    panel.style.maxWidth = `${Math.max(MIN_W, right - padding)}px`;

    const room: Record<PopoverSide, number> = {
      top: a.top - padding - offset,
      bottom: bottom - a.bottom - offset,
    };
    let next = side;
    if (room[next] < panel.offsetHeight && room[FLIP[next]] > room[next]) next = FLIP[next];
    if (content) {
      const chrome = panel.offsetHeight - content.offsetHeight;
      content.style.maxHeight = `${Math.max(MIN_H, room[next] - chrome)}px`;
    }

    const w = panel.offsetWidth;
    const h = panel.offsetHeight;
    const y = clamp(next === "top" ? a.top - offset - h : a.bottom + offset, padding, bottom - h);
    const x = clamp(
      align === "start" ? a.left : align === "end" ? a.right - w : a.left + (a.width - w) / 2,
      padding,
      right - w,
    );
    wrap.style.left = `${Math.round(x)}px`;
    wrap.style.top = `${Math.round(y)}px`;

    // Scale from the trigger, not from the panel's centre.
    const point = clamp(a.left + a.width / 2 - x, RADIUS, w - RADIUS);
    panel.style.transformOrigin = `${Math.round(point)}px ${next === "top" ? h : 0}px`;
    setResolved((prev) => (prev === next ? prev : next));
  }, [anchorRef, side, align, offset, padding]);

  useIsoLayoutEffect(() => {
    if (open) update();
  }, [open, update]);

  useEffect(() => {
    if (!open) return;
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        update();
      });
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    if (anchorRef.current) observer?.observe(anchorRef.current);
    if (contentRef.current) observer?.observe(contentRef.current);
    window.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
    };
  }, [open, update, anchorRef]);

  return { wrapRef, panelRef, contentRef, side: resolved };
}

export type PopoverTriggerProps = {
  ref: (node: HTMLElement | null) => void;
  "aria-expanded": boolean;
  "aria-controls": string | undefined;
  "aria-haspopup": "dialog";
  onClick: () => void;
};

export type PopoverProps = {
  /** Render the trigger and spread `props` onto it; it must be a focusable control. */
  renderTrigger: (props: PopoverTriggerProps, open: boolean) => ReactNode;
  children: ReactNode;
  /** The panel's accessible name. */
  label: string;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  side?: PopoverSide;
  align?: PopoverAlign;
  offset?: number;
  padding?: number;
  className?: string;
};

export function Popover({
  renderTrigger,
  children,
  label,
  open: controlled,
  defaultOpen = false,
  onOpenChange,
  side = "bottom",
  align = "center",
  offset = 8,
  padding = 8,
  className = "",
}: PopoverProps) {
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const open = controlled ?? uncontrolled;
  const id = useId();
  const reduced = useReducedMotion();
  const anchorRef = useRef<HTMLElement | null>(null);
  const notify = useRef(onOpenChange);
  notify.current = onOpenChange;
  // The portal target exists only in the browser; rendering it after mount keeps the
  // server and first client render identical.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const { wrapRef, panelRef, contentRef, side: at } = usePlacement({
    open,
    anchorRef,
    side,
    align,
    offset,
    padding,
  });

  const setOpen = useCallback(
    (next: boolean) => {
      if (controlled === undefined) setUncontrolled(next);
      notify.current?.(next);
    },
    [controlled],
  );

  // Focus moves INTO the panel on open so a screen reader reads it and Tab continues
  // from it; every way of closing puts focus back on the trigger.
  useEffect(() => {
    if (open) panelRef.current?.focus({ preventScroll: true });
  }, [open, panelRef]);

  useEffect(() => {
    if (!open) return;
    const close = () => {
      setOpen(false);
      anchorRef.current?.focus({ preventScroll: true });
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (panelRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      // Not refocused: the press already chose where focus goes next.
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) close();
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, setOpen, panelRef]);

  const trigger = renderTrigger(
    {
      ref: (node) => {
        anchorRef.current = node;
      },
      "aria-expanded": open,
      "aria-controls": open ? id : undefined,
      "aria-haspopup": "dialog",
      onClick: () => setOpen(!open),
    },
    open,
  );

  const panel = (
    <AnimatePresence>
      {open ? (
        <div
          key="popover"
          ref={wrapRef}
          className="fixed left-0 top-0 z-50"
          onBlurCapture={(event) => {
            const next = event.relatedTarget as Node | null;
            if (!next) return;
            if (panelRef.current?.contains(next) || anchorRef.current?.contains(next)) return;
            setOpen(false);
          }}
        >
          <motion.div
            ref={panelRef}
            id={id}
            role="dialog"
            aria-label={label}
            tabIndex={-1}
            initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: at === "top" ? 4 : -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={
              reduced
                ? { opacity: 0, transition: { duration: 0.1 } }
                : { opacity: 0, scale: 0.98, transition: { duration: 0.12, ease: EASE } }
            }
            transition={reduced ? { duration: 0 } : { duration: 0.16, ease: EASE }}
            className={`relative rounded-[10px] border border-line bg-surface p-3 text-[13px] leading-relaxed text-ink shadow-raised focus-visible:outline-none ${className}`}
          >
            <div ref={contentRef} className="overflow-y-auto overscroll-contain">
              {children}
            </div>
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );

  return (
    <>
      {trigger}
      {mounted ? createPortal(panel, document.body) : null}
    </>
  );
}
