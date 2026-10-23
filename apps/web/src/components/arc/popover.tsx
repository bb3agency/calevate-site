"use client";

/**
 * THE popover: a panel anchored to a trigger, on `@radix-ui/react-popover`.
 *
 * Radix rather than the hand-rolled `interior/popover` it replaces, because what it adds is
 * correctness the old one did not have: collision handling that flips and shifts the panel
 * to stay on screen (the old one only clamped), `aria-expanded`/`aria-controls` wiring,
 * focus moved in on open and back to the trigger on close, and dismissal on Escape or an
 * outside press that respects nested layers. It is non-modal, so a toast raised while it is
 * open is still announced.
 *
 * It portals into `<body>` on the `z-popover` layer, which sits above dialogs and drawers,
 * so an ⓘ inside a drawer is no longer painted underneath it.
 */

import type { ReactElement, ReactNode } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import clsx from "clsx";

export type PopoverSide = "top" | "bottom" | "left" | "right";
export type PopoverAlign = "start" | "center" | "end";

/** The floating surface every kit popover, menu and hover card shares. */
export const FLOATING_PANEL =
  "popover-enter z-popover rounded-[10px] border border-line bg-surface shadow-raised outline-none";

export type PopoverProps = {
  /** A single focusable element (usually a `<button>`); it becomes the trigger. */
  trigger: ReactElement;
  children: ReactNode;
  /** The panel's accessible name. */
  label: string;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  side?: PopoverSide;
  align?: PopoverAlign;
  /** Gap between trigger and panel, px. */
  offset?: number;
  className?: string;
};

export function Popover({
  trigger,
  children,
  label,
  open,
  defaultOpen,
  onOpenChange,
  side = "bottom",
  align = "center",
  offset = 6,
  className,
}: PopoverProps) {
  return (
    <PopoverPrimitive.Root open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          aria-label={label}
          side={side}
          align={align}
          sideOffset={offset}
          collisionPadding={8}
          className={clsx(
            FLOATING_PANEL,
            "max-h-(--radix-popover-content-available-height) max-w-[calc(100vw-1rem)] overflow-y-auto overscroll-contain p-3 text-[13px] leading-relaxed text-ink",
            className,
          )}
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

/** A close control inside a popover's body ("Done", "Cancel"). */
export const PopoverClose = PopoverPrimitive.Close;
