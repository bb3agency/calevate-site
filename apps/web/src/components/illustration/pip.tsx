/**
 * Pip's face: the in-product assistant's mark (D-772), on every surface where Pip speaks.
 *
 * ## The idea
 *
 * A pip is the short tone on a phone line, so Pip is a small round character with ONE signal
 * tone beside it: a single short arc off its upper right, the way a sound leaves a speaker in
 * a hand sketch. One arc and not three, because three nested arcs is the Wi-Fi glyph and
 * says "connectivity". There is deliberately no sparkle, robot head, brain or gradient orb:
 * those are every AI product's mark, and this product already uses `Bot` for voice agents.
 *
 * ## Hand-drawn, in the house language
 *
 * Same family as `disconnectedCall.tsx`: token colours as presentation attributes, round
 * caps and joins, a brand-strong outline over a soft fill. The hand comes from the outline,
 * which is four uneven quarter curves rather than a `<circle>`, and which runs a little past
 * where it started, the way a pen closes a loop.
 *
 * ## Two drawings, chosen by size
 *
 * Below 20 px the overshoot and the mouth are smaller than a device pixel and blur into the
 * outline, so the small drawing drops both and thickens every stroke: at 16 px a 1.6 unit
 * stroke is about one pixel and an eye is about two.
 *
 * ## Colour
 *
 * `--brand-soft` body, `--brand-strong` ink, `--brand` tone. None of the three is redefined
 * by `.dark`, so the face is the same on a white card, a dark card and the admin realm's
 * slate launcher tile, and the outline and tone hold 3:1 against both grounds (WCAG 1.4.11).
 *
 * ## Labelled or decorative
 *
 * Decorative by default (`aria-hidden`): beside the words "Ask Pip" or a panel titled Pip,
 * the face repeats the name. Pass `label` only where the face stands alone.
 */

import type { SVGProps } from "react";

/** At or above this rendered size the full drawing is legible; below it, the small one. */
const DETAIL_FROM_PX = 20;

export function PipMark({
  size = 24,
  label,
  thinking = false,
  className,
  ...props
}: {
  /** Rendered width and height in CSS pixels. Ignored when `className` sets a size. */
  size?: number;
  /** An accessible name, for a face shown with no name beside it. Omit for decorative use. */
  label?: string;
  /** Pip is working on an answer: the tone pulses, unless the reader asked for less motion. */
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
      {/* The body: four uneven quarters. The full drawing runs on past its start. */}
      <path
        d={
          small
            ? "M10.6 6.2C14.7 6.1 18 9.3 17.9 13.4 17.8 17.6 14.5 20.9 10.4 20.9 6.3 20.9 3.1 17.7 3.2 13.6 3.3 9.4 6.5 6.3 10.6 6.2Z"
            : "M10.6 6C14.8 5.9 18.2 9.2 18.1 13.3 18 17.6 14.6 21.1 10.4 21.1 6.2 21.1 2.9 17.8 3 13.7 3.1 9.5 6.3 6.15 10.2 6.05 11.4 6 12.4 6.2 13.2 6.55"
        }
        fill="var(--brand-soft)"
        stroke="var(--brand-strong)"
        strokeWidth={outline}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Eyes, a touch uneven so it reads as drawn rather than set. */}
      <ellipse cx={8.1} cy={12.7} rx={small ? 1.35 : 1.05} ry={small ? 1.45 : 1.2} fill="var(--brand-strong)" />
      <ellipse cx={12.7} cy={12.5} rx={small ? 1.35 : 1.05} ry={small ? 1.45 : 1.2} fill="var(--brand-strong)" />
      {!small && (
        <path
          d="M8.6 16.1C9.6 17 11.4 17.1 12.4 16"
          stroke="var(--brand-strong)"
          strokeWidth={1.3}
          strokeLinecap="round"
        />
      )}
      {/* The one tone. */}
      <path
        d={small ? "M18.4 3.9C20.4 4.9 21.5 6.9 21.3 9.2" : "M18.7 3.5C20.7 4.4 21.8 6.5 21.6 8.9"}
        stroke="var(--brand)"
        strokeWidth={small ? 2.1 : 1.8}
        strokeLinecap="round"
        className={thinking ? "motion-safe:animate-pulse" : undefined}
      />
    </svg>
  );
}

/** Pip's face at icon size, for the navigation tables, whose icons take only a class. */
export function PipIcon({ className }: { className?: string }) {
  return <PipMark size={16} className={className} />;
}
