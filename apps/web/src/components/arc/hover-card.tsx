"use client";

/**
 * A preview that appears while a pointer rests on (or keyboard focus sits on) a row's
 * link — a lead's last call and status, a call's outcome — so a desktop user can scan a
 * table without opening each record.
 *
 * Adapted from uiarc's `hover-card` (MIT, see ./LICENSE), on `@radix-ui/react-popover`
 * anchored to the trigger rather than Radix's own HoverCard package, which is not installed.
 *
 * Desktop only, and never the only route to anything: on a device that cannot hover
 * (`(hover: hover) and (pointer: fine)` false) it renders the trigger alone, and the link
 * still opens the record. The card does not take focus when it opens, so Tab moves on from
 * the link as if the card were not there; Escape closes it.
 */

import { useEffect, useRef, useState, type ReactElement, type ReactNode } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import clsx from "clsx";

import { useMediaQuery } from "@/lib/useMediaQuery";

import { FLOATING_PANEL } from "./popover";

export type HoverCardProps = {
  /** The row's link (one element). It keeps its own click and keyboard behaviour. */
  trigger: ReactElement;
  /** The preview. Read-only facts; actions belong on the row or the record. */
  children: ReactNode;
  /** The card's accessible name: "Preview of Priya Reddy". */
  label: string;
  openDelay?: number;
  closeDelay?: number;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  className?: string;
};

const CAN_HOVER = "(hover: hover) and (pointer: fine)";

export function HoverCard({
  trigger,
  children,
  label,
  openDelay = 500,
  closeDelay = 150,
  side = "bottom",
  align = "start",
  className,
}: HoverCardProps) {
  const canHover = useMediaQuery(CAN_HOVER);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  if (!canHover) return trigger;

  const schedule = (next: boolean, delay: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(next), delay);
  };
  const show = () => schedule(true, openDelay);
  const hide = () => schedule(false, closeDelay);

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Anchor asChild>
        <span
          className="inline-flex min-w-0"
          onPointerEnter={show}
          onPointerLeave={hide}
          onFocus={show}
          onBlur={hide}
        >
          {trigger}
        </span>
      </PopoverPrimitive.Anchor>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          aria-label={label}
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          onPointerEnter={() => window.clearTimeout(timer.current)}
          onPointerLeave={hide}
          className={clsx(FLOATING_PANEL, "w-72 max-w-[calc(100vw-1rem)] p-3 text-[13px] text-ink", className)}
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
