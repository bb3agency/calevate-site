"use client";

// Adapted from interior.dev (github.com/ddoemonn/interior @3148000), MIT License,
// Copyright (c) 2026 ozzy. Full notice: ./LICENSE.
//
// Changes from upstream: the visible label is the button's own text (upstream drew it in
// an aria-hidden layer and gave the button sr-only text, so find-in-page and translation
// hit the wrong layer); a light thumb on a muted track replaces the dark masked thumb, so
// no second label layer is needed; an optional `count` per option; a value that matches no
// option checks nothing instead of option 0; disabled options say so to a pointer too;
// arrow-key changes jump the thumb instead of sliding it (keyboard actions do not
// animate); many options scroll inside a `ScrollRegion` at phone width rather than
// overflowing; repo tokens and touch sizing.

import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";

import { ScrollRegion } from "@/components/ui";

const CELL = { type: "spring", stiffness: 520, damping: 40, mass: 0.45 } as const;

export type SegmentedOption = {
  value: string;
  label: string;
  /** A figure shown after the label, e.g. how many rows this option holds. */
  count?: string;
  disabled?: boolean;
};

export type SegmentedControlProps = {
  options: SegmentedOption[];
  /** The radiogroup's accessible name. */
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  className?: string;
};

export function SegmentedControl({
  options,
  label,
  value,
  onValueChange,
  className = "",
}: SegmentedControlProps) {
  const count = Math.max(1, options.length);
  const index = options.findIndex((o) => o.value === value);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const reduced = useReducedMotion();
  const fromKeyboard = useRef(false);
  const pos = useMotionValue(Math.max(0, index));
  const thumbX = useTransform(pos, (v) => `${v * 100}%`);

  useEffect(() => {
    if (index < 0) return;
    if (reduced || fromKeyboard.current) {
      fromKeyboard.current = false;
      pos.jump(index);
      return;
    }
    const controls = animate(pos, index, CELL);
    return () => controls.stop();
  }, [index, reduced, pos]);

  const seek = (from: number, dir: number) => {
    let i = from;
    for (let k = 0; k < count; k++) {
      i = (i + dir + count) % count;
      if (!options[i]?.disabled) return i;
    }
    return from;
  };

  const go = (i: number) => {
    const option = options[i];
    if (!option || option.disabled) return;
    fromKeyboard.current = true;
    buttons.current[i]?.focus();
    if (option.value !== value) onValueChange(option.value);
  };

  const onKeyDown = (e: KeyboardEvent, i: number) => {
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      go(seek(i, 1));
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      go(seek(i, -1));
    } else if (e.key === "Home") {
      e.preventDefault();
      go(seek(count - 1, 1));
    } else if (e.key === "End") {
      e.preventDefault();
      go(seek(0, -1));
    }
  };

  // The roving stop: the checked option, or the first enabled one when nothing matches.
  const tabStop = index >= 0 ? index : Math.max(0, options.findIndex((o) => !o.disabled));

  return (
    <ScrollRegion label={label} className={`max-w-full [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${className}`}>
      <div
        role="radiogroup"
        aria-label={label}
        className="relative inline-grid w-max select-none rounded-[10px] bg-ink/[0.05] p-[3px] shadow-[inset_0_0_0_1px_var(--line)]"
        style={{ gridTemplateColumns: `repeat(${count}, 1fr)`, touchAction: "manipulation" }}
      >
        <motion.div
          aria-hidden
          className="pointer-events-none absolute bottom-[3px] left-[3px] top-[3px] rounded-[7px] bg-surface shadow-card ring-1 ring-ink/[0.06]"
          style={{
            width: `calc((100% - 6px) / ${count})`,
            x: thumbX,
            opacity: index < 0 ? 0 : 1,
          }}
        />
        {options.map((option, i) => {
          const checked = i === index;
          return (
            <button
              key={option.value}
              ref={(node) => {
                buttons.current[i] = node;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              aria-disabled={option.disabled || undefined}
              tabIndex={i === tabStop ? 0 : -1}
              onClick={() => {
                if (option.disabled || option.value === value) return;
                onValueChange(option.value);
              }}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={`relative z-[1] flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[7px] px-3 py-1.5 text-[13px] leading-[18px] transition-colors duration-(--duration-fast) ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand touch:min-h-11 ${
                option.disabled
                  ? "cursor-not-allowed text-ink-faint/60"
                  : checked
                    ? "font-medium text-ink"
                    : "font-medium text-ink-muted hover:text-ink"
              }`}
            >
              {option.label}
              {option.count !== undefined && (
                <span
                  className={`tabular-nums text-[12px] ${checked ? "text-ink-muted" : "text-ink-faint"}`}
                >
                  {option.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </ScrollRegion>
  );
}
