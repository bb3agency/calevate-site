"use client";

import type { ReactNode } from "react";

import { useChangeFlash } from "./valueFlash";

/**
 * The element `StatusPill` renders, in its own client module so `statusPill.tsx` stays
 * importable by server components (the marketing mockups) and its constants stay plain
 * values.
 *
 * A state that CHANGES while the screen is open — a call going from ringing to answered, a
 * campaign pausing — gets the console's one change mark (`value-flash`, a fading tint that
 * reduced motion turns off). The first state shown is never marked.
 */
export function StatusPillShell({
  tone,
  state,
  className,
  children,
}: {
  tone: string;
  /** What is compared between renders: the tone and, when it is plain text, the word. */
  state: string;
  className: string;
  children: ReactNode;
}) {
  const flashing = useChangeFlash(state);
  return (
    <span data-tone={tone} className={`${className} ${flashing ? "rounded-[4px] value-flash" : ""}`}>
      {children}
    </span>
  );
}
