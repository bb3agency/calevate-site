/**
 * A working label that shimmers while something runs ("Reading the voice platform…"),
 * through the `text-shimmer` utility in globals.css (no motion under reduced motion or
 * forced colours; the words stay).
 *
 * The component exists for one thing the bare class cannot do: a STANDALONE progress line
 * (not inside a button) is a polite status, so a screen reader hears that work started.
 * Inside an `ActionButton` use the button's own pending face instead; inside any other
 * button, the bare `text-shimmer` class is enough, since the button already has focus.
 */

import type { ReactNode } from "react";
import clsx from "clsx";

export function TextShimmer({
  children,
  announce = true,
  className,
}: {
  children: ReactNode;
  /** A polite live status. Off for a label inside a control that already has focus. */
  announce?: boolean;
  className?: string;
}) {
  return (
    <span role={announce ? "status" : undefined} className={clsx("text-shimmer", className)}>
      {children}
    </span>
  );
}
