"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Order two decimal STRINGS ("10159.00", "-3.5") without turning either into a float.
 * Money arrives as strings (hard rule 7) and `Number("10159.00")` is how a rupee figure
 * becomes 10158.999…; scaling both to the same number of fraction digits and comparing
 * as BigInt is exact for any length. Returns null when either is not a plain decimal.
 */
export function compareDecimal(a: string, b: string): number | null {
  const parse = (v: string) => /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(v.trim());
  const x = parse(a);
  const y = parse(b);
  if (!x || !y) return null;
  const scale = Math.max(x[3]?.length ?? 0, y[3]?.length ?? 0);
  const big = (m: RegExpExecArray) =>
    BigInt(`${m[1] === "-" ? "-" : ""}${m[2]}${(m[3] ?? "").padEnd(scale, "0")}`);
  const d = big(x) - big(y);
  return d === BigInt(0) ? 0 : d > BigInt(0) ? 1 : -1;
}

/** How long a changed value stays marked. Long enough to be seen, short enough to stop. */
export const FLASH_MS = 1200;

/**
 * True for a moment after `value` CHANGES — never on the first value, and never because
 * a poll returned the same answer again. Compared as strings, so money is never parsed.
 */
export function useChangeFlash(value: string | null | undefined): boolean {
  const previous = useRef<string | null | undefined>(undefined);
  const [flashing, setFlashing] = useState(false);
  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (before === undefined || before === null || value === null || value === undefined) return;
    if (before === value) return;
    setFlashing(true);
    const id = setTimeout(() => setFlashing(false), FLASH_MS);
    return () => clearTimeout(id);
  }, [value]);
  return flashing;
}

/**
 * A polled figure that marks itself when it changes. The mark is a fading tint
 * (`value-flash` in globals.css), which reduced motion turns off; nothing is announced,
 * because a dashboard of polled numbers announcing every refresh would talk over the
 * reader.
 */
export function FlashValue({
  value,
  children,
  className = "",
}: {
  /** The string compared between polls — the raw wire value, not the formatted one. */
  value: string | null | undefined;
  children: ReactNode;
  className?: string;
}) {
  const flashing = useChangeFlash(value);
  return (
    <span className={`rounded-[4px] ${flashing ? "value-flash" : ""} ${className}`}>{children}</span>
  );
}
