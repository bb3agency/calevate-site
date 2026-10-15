/**
 * Pip's mark: the in-product assistant (D-772), on every surface where Pip speaks.
 *
 * ## The idea
 *
 * A pip is a small dot, and Pip is one lifting off: a round dot rising up and to the
 * right, with a dotted trail behind it, for a product called Calevate. It is deliberately
 * not a face (an earlier face read as unsettling at icon size), and not a sparkle, robot
 * head, brain or gradient orb: those are every AI product's mark, and this product
 * already uses `Bot` for voice agents.
 *
 * ## Hand-drawn, in the house language
 *
 * Same family as `disconnectedCall.tsx`: token colours as presentation attributes, round
 * caps and joins, a brand-strong outline over a soft fill. The hand comes from the dot's
 * outline, which is uneven and runs a little past where it started, the way a pen closes
 * a loop.
 *
 * ## Two drawings, chosen by size
 *
 * Below 20 px the highlight and the overshoot are smaller than a device pixel and blur into
 * the outline, so the small drawing drops both, spaces the trail wider and thickens every
 * stroke.
 *
 * ## Colour
 *
 * `--brand-soft` dot, `--brand-strong` ink, `--brand` trail. None of the three is
 * redefined by `.dark`, so the mark is the same on a white card, a dark card and the admin
 * realm's slate launcher tile, and the outline holds 3:1 against both grounds (WCAG 1.4.11).
 *
 * ## Labelled or decorative
 *
 * Decorative by default (`aria-hidden`): beside the words "Ask Pip" or a panel titled Pip,
 * the mark repeats the name. Pass `label` only where the mark stands alone.
 */

import type { SVGProps } from "react";

/** At or above this rendered size the full drawing is legible; below it, the small one. */
const DETAIL_FROM_PX = 20;

/** Where the trail's three dots sit when Pip is at work: on the resting trail's curve. */
const TRAIL_DOTS: ReadonlyArray<readonly [number, number]> = [
  [4.1, 20.6],
  [6.9, 19.3],
  [9.1, 16.6],
];

export function PipMark({
  size = 24,
  label,
  thinking = false,
  className,
  ...props
}: {
  /** Rendered width and height in CSS pixels. Ignored when `className` sets a size. */
  size?: number;
  /** An accessible name, for a mark shown with no name beside it. Omit for decorative use. */
  label?: string;
  /**
   * Pip is working on an answer: the trail's dots light in turn and the pip lifts, unless
   * the reader asked for less motion.
   */
  thinking?: boolean;
} & Omit<SVGProps<SVGSVGElement>, "children">) {
  const small = size < DETAIL_FROM_PX;
  const outline = small ? 2 : 1.6;
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      focusable="false"
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
      className={className}
      data-pip={small ? "small" : "full"}
      {...props}
    >
      {label ? <title>{label}</title> : null}
      {thinking ? (
        // At work: three separate dots that light in turn (`pip-dot` in globals.css).
        <g fill="var(--brand)">
          {TRAIL_DOTS.map(([cx, cy], i) => (
            <circle
              key={i}
              cx={cx}
              cy={cy}
              r={small ? 1.15 : 0.95}
              className="pip-dot"
              style={{ animationDelay: `${i * 0.18}s` }}
            />
          ))}
        </g>
      ) : (
        // The trail: dots, drawn as near-zero dashes with round caps.
        <path
          d={small ? "M3.6 20.6C6 20.1 8 18.3 9.6 15.6" : "M3.2 20.8C5.8 20.3 7.9 18.4 9.6 15.4"}
          stroke="var(--brand)"
          strokeWidth={small ? 2.2 : 1.8}
          strokeLinecap="round"
          strokeDasharray={small ? "0.1 3.6" : "0.1 3"}
        />
      )}
      {/* The pip. The full drawing's outline runs on past its start. */}
      <g className={thinking ? "pip-lift" : undefined}>
        {small ? (
          <circle cx={14.6} cy={9.5} r={5.2} fill="var(--brand-soft)" stroke="var(--brand-strong)" strokeWidth={outline} />
        ) : (
          <>
            <path
              d="M14.6 4C17.8 3.9 20.3 6.4 20.1 9.6 19.9 12.7 17.3 15 14.3 14.9 11.2 14.8 9 12.3 9.2 9.2 9.4 6.2 11.8 4.1 14.9 4.1"
              fill="var(--brand-soft)"
              stroke="var(--brand-strong)"
              strokeWidth={outline}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d="M12.5 7.6C13.2 6.9 14.2 6.6 15.2 6.8" stroke="var(--brand)" strokeWidth={1.3} strokeLinecap="round" />
          </>
        )}
      </g>
    </svg>
  );
}

/** Pip's mark at icon size, for the navigation tables, whose icons take only a class. */
export function PipIcon({ className }: { className?: string }) {
  return <PipMark size={16} className={className} />;
}
