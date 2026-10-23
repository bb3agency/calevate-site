"use client";

/**
 * A hover/focus label for an ICON-ONLY control on a pointer device, on
 * `@radix-ui/react-tooltip` (adapted from uiarc's `tooltip`, MIT, see ./LICENSE).
 *
 * A tooltip repeats the control's accessible name for sighted mouse users; it never holds
 * information found nowhere else, because a phone cannot hover. Help text a reader needs
 * goes in an `InfoTip` (a tap-to-open toggletip) or on the screen.
 *
 * Grouped delay comes from `TooltipProvider` (mounted once in `app/providers.tsx`): the
 * first tip waits 400ms, and moving to a neighbour within 300ms opens it at once, which is
 * what makes a toolbar of icons feel quick without tips flashing as the pointer crosses it.
 */

import { createContext, useContext, type ReactElement, type ReactNode } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const Provided = createContext(false);

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={400} skipDelayDuration={300}>
      <Provided.Provider value>{children}</Provided.Provider>
    </TooltipPrimitive.Provider>
  );
}

export function Tooltip({
  content,
  children,
  side = "top",
}: {
  /** Short: the control's name, or its name and shortcut. */
  content: ReactNode;
  /** One focusable element, usually an icon `<button>` with its own `aria-label`. */
  children: ReactElement;
  side?: "top" | "bottom" | "left" | "right";
}) {
  const provided = useContext(Provided);
  const tip = (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          collisionPadding={8}
          className="popover-enter z-popover max-w-64 rounded-md bg-ink px-2 py-1 text-[12px] font-medium leading-4 text-surface shadow-raised"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
  // A screen rendered outside the app providers (a unit test) still gets a working tip.
  return provided ? tip : <TooltipProvider>{tip}</TooltipProvider>;
}
