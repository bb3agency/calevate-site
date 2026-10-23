"use client";

/**
 * Long text clamped to a few lines, with "Show more" only when it really overflows.
 * Adapted from uiarc's `expandable-text` (MIT, see ./LICENSE).
 *
 * For a transcript turn, a captured note, a before/after quote: text a reader usually
 * skims and sometimes needs in full. The whole text stays in the DOM (a screen reader and
 * find-in-page reach all of it); only the paint is clamped.
 *
 * Overflow is measured, not guessed from a character count: the toggle appears only when
 * the clamped box is shorter than its content, and is re-measured when the width changes
 * (a phone turned sideways). The server render has no toggle; the first measurement adds
 * it, which is cheaper than Arc's opposite default of showing a toggle on short text.
 *
 * No height animation: it is opened often and read at once, so it snaps (the catalogue's
 * "500-600ms is slow for a text toggle"). A link inside the hidden part opens the text when
 * it takes keyboard focus, so Tab never lands on something the reader cannot see.
 */

import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import clsx from "clsx";

export function ExpandableText({
  children,
  lines = 4,
  moreLabel = "Show more",
  lessLabel = "Show less",
  defaultExpanded = false,
  className,
  textClassName,
}: {
  children: ReactNode;
  /** Lines shown while collapsed. */
  lines?: number;
  moreLabel?: string;
  lessLabel?: string;
  defaultExpanded?: boolean;
  className?: string;
  /** Classes for the text block itself (size, colour, `whitespace-pre-wrap`). */
  textClassName?: string;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [overflowing, setOverflowing] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const id = useId();

  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return undefined;
    const measure = () => {
      // Measured only while clamped; once open there is nothing to compare against, and
      // the toggle must stay so the reader can close it again.
      if (node.dataset.clamped === "true") setOverflowing(node.scrollHeight > node.clientHeight + 1);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [lines, children]);

  const clamped = !expanded;
  return (
    <div
      className={className}
      onFocusCapture={(event) => {
        if (!clamped || !overflowing || event.target === box.current) return;
        const outer = box.current?.getBoundingClientRect();
        const target = event.target.getBoundingClientRect();
        if (outer && target.bottom > outer.bottom + 1) setExpanded(true);
      }}
    >
      <div
        ref={box}
        id={id}
        data-clamped={clamped ? "true" : "false"}
        className={clsx("break-words", textClassName)}
        style={
          clamped
            ? { display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: lines, overflow: "hidden" }
            : undefined
        }
      >
        {children}
      </div>
      {overflowing || expanded ? (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={id}
          onClick={() => setExpanded((open) => !open)}
          className="mt-1 inline-flex min-h-7 items-center rounded-sm text-meta font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          {expanded ? lessLabel : moreLabel}
        </button>
      ) : null}
    </div>
  );
}
