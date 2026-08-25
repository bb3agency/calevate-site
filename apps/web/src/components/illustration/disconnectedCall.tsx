/**
 * "The number you have dialled does not exist" — the 404 figure, in the house language.
 *
 * ## Why this concept
 *
 * This product sells phone agents to Indian SMBs, and the recorded line every one of their
 * owners has heard a hundred times is the one about a number that could not be connected.
 * A 404 IS that recording: an address that does not answer. So the figure is a desk phone
 * OFF THE HOOK, with a keypad missing a key and a line that stops halfway — three readings
 * of the same idea, and none of them a generic broken robot or a magnifying glass.
 *
 * It is DECORATIVE and carries no meaning the page needs: `aria-hidden`, `focusable=false`,
 * no text nodes. The 404 copy stands alone with the SVG removed, which is the rule for any
 * illustration that is not itself the content.
 *
 * ## The technique, borrowed deliberately from `components/marketing/isometric.tsx`
 *
 * Same 2:1 isometric TOP-FACE transform — `matrix(0.866 0.5 -0.866 0.5 tx ty)` — so a rect
 * becomes a diamond; thickness is the same trick of drawing a face twice with the lower copy
 * pushed straight down in screen space; cubes get explicit side-wall parallelograms.
 *
 * The two geometry helpers are RE-DERIVED here rather than imported, and that is the one
 * duplication in this file that is deliberate: they are module-private in `isometric.tsx`,
 * and a 404 must not import from `components/marketing/` at all. That directory's figures
 * animate through the `mk-iso-*` classes, which globals.css scopes to `[data-marketing-root]`
 * — a marker this page does not and should not render. Importing one would have shipped a
 * figure whose motion silently depends on a page it is not on. This file is STATIC: no
 * animation, no JS, nothing to freeze for a `prefers-reduced-motion` reader, and nothing
 * that can rest on a wrong frame.
 *
 * ## Colour is theme-safe by construction
 *
 * Every colour is a `var(--token)` presentation attribute. `--brand*` is theme-INVARIANT
 * (globals.css redefines only `--surface`/`--app`/`--line`/`--ink*` under `.dark`), and the
 * neutral faces use `--surface`, which is meant to follow the theme so the figure tracks the
 * cards beside it. That matters more than usual here: this page ships in the same change as
 * the dark-mode switch, so it is rendered in both themes from day one.
 */

import type { SVGProps } from "react";

/** cos(30°): the isometric foreshortening. Matched to the reference matrix literal. */
const K = 0.866025;

/** The top-face transform placing a rect's local origin at screen (ox, oy). */
const topMatrix = (ox: number, oy: number): string =>
  `matrix(${K} 0.5 ${-K} 0.5 ${ox} ${oy})`;

/** Screen "x y" of local point (x, y) on a top-face plane rooted at (ox, oy). */
const P = (ox: number, oy: number, x: number, y: number): string =>
  `${+(ox + K * x - K * y).toFixed(2)} ${+(oy + 0.5 * x + 0.5 * y).toFixed(2)}`;

/** The base's top face lives on this plane; every keypad key is placed against it. */
const BASE_X = 104;
const BASE_Y = 66;
/** In-plane side of the base, and the wall depth in screen pixels. */
const BASE_S = 74;
const BASE_T = 20;

/**
 * The keypad, in local plane coordinates — three columns, four rows, the classic layout.
 *
 * The MISSING key is the middle of the second row, i.e. the "5": dead centre of the pad, so
 * the gap is the first thing the eye lands on, and far enough from the edge that it cannot
 * be mistaken for the pad simply being cropped.
 */
const KEY_COLS = [14, 32, 50];
const KEY_ROWS = [14, 30, 46, 62];
const MISSING_KEY = { x: KEY_COLS[1], y: KEY_ROWS[1] };

export function DisconnectedCall({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 240 180"
      fill="none"
      aria-hidden
      focusable="false"
      className={className}
      {...props}
    >
      {/* Ground contact, as a brand-tinted halo rather than an ink shadow: an ink shadow
          inverts between themes and a green one does not. */}
      <ellipse cx={120} cy={156} rx={72} ry={13} fill="var(--brand)" fillOpacity={0.1} />

      {/* ── The base, a cube: two shaded walls under a paper-white top face. ────────── */}
      <path
        d={`M ${P(BASE_X, BASE_Y, 0, BASE_S)} L ${P(BASE_X, BASE_Y, BASE_S, BASE_S)} L ${P(BASE_X, BASE_Y + BASE_T, BASE_S, BASE_S)} L ${P(BASE_X, BASE_Y + BASE_T, 0, BASE_S)} Z`}
        fill="var(--brand-strong)"
        fillOpacity={0.9}
        stroke="var(--brand-strong)"
        strokeWidth={1.1}
        strokeLinejoin="round"
      />
      <path
        d={`M ${P(BASE_X, BASE_Y, BASE_S, BASE_S)} L ${P(BASE_X, BASE_Y, BASE_S, 0)} L ${P(BASE_X, BASE_Y + BASE_T, BASE_S, 0)} L ${P(BASE_X, BASE_Y + BASE_T, BASE_S, BASE_S)} Z`}
        fill="var(--brand)"
        fillOpacity={0.92}
        stroke="var(--brand-strong)"
        strokeWidth={1.1}
        strokeLinejoin="round"
      />
      <rect
        width={BASE_S}
        height={BASE_S}
        rx={13}
        transform={topMatrix(BASE_X, BASE_Y)}
        fill="var(--surface)"
        stroke="var(--brand-strong)"
        strokeWidth={1.25}
        strokeOpacity={0.65}
      />

      {/* ── The keypad, lying in the top-face plane. One key is simply not there. ───── */}
      {KEY_ROWS.map((y) =>
        KEY_COLS.map((x) => {
          const missing = x === MISSING_KEY.x && y === MISSING_KEY.y;
          return (
            <rect
              key={`${x}-${y}`}
              x={x - 5.5}
              y={y - 5.5}
              width={11}
              height={11}
              rx={3}
              transform={topMatrix(BASE_X, BASE_Y)}
              // The hole shows the shadowed inside of the base rather than the page, so it
              // reads as a socket with nothing in it and not as a hole punched in the SVG.
              fill={missing ? "var(--brand-strong)" : "var(--brand)"}
              fillOpacity={missing ? 0.16 : 0.72}
              stroke="var(--brand-strong)"
              strokeWidth={missing ? 1.1 : 0}
              strokeOpacity={0.55}
              strokeDasharray={missing ? "3 2.5" : undefined}
            />
          );
        }),
      )}

      {/* ── The handset, lifted OFF the cradle and set down beside it. ──────────────── */}
      <g>
        {/* Its own small shadow, so it reads as resting on the desk rather than floating. */}
        <ellipse cx={62} cy={92} rx={34} ry={8} fill="var(--brand)" fillOpacity={0.12} />
        {/* Body: a long slab across the plane, drawn twice for thickness. */}
        <rect
          x={0}
          y={0}
          width={56}
          height={17}
          rx={8.5}
          transform={topMatrix(58, 66)}
          fill="var(--brand-strong)"
          fillOpacity={0.85}
        />
        <rect
          x={0}
          y={0}
          width={56}
          height={17}
          rx={8.5}
          transform={topMatrix(58, 58)}
          fill="var(--brand)"
          fillOpacity={0.95}
          stroke="var(--brand-strong)"
          strokeWidth={1.2}
          strokeOpacity={0.7}
        />
        {/* Earpiece and mouthpiece: the two raised caps that make it a handset and not a bar. */}
        {[2, 44].map((x) => (
          <rect
            key={x}
            x={x}
            y={-4}
            width={10}
            height={25}
            rx={5}
            transform={topMatrix(58, 54)}
            fill="var(--surface)"
            fillOpacity={0.94}
            stroke="var(--brand-strong)"
            strokeWidth={1}
            strokeOpacity={0.5}
          />
        ))}
      </g>

      {/* ── The line, and the point at which it stops. ──────────────────────────────── */}
      {/* Two segments with a real gap between them — the cord leaves the base, and never
          arrives. Capped at both broken ends so the break reads as a severed line rather
          than as a dashed stylistic flourish. */}
      <path
        d="M 148 96 C 168 104 176 116 172 128"
        stroke="var(--brand-strong)"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeOpacity={0.75}
        fill="none"
      />
      <path
        d="M 196 138 C 204 132 208 124 206 116"
        stroke="var(--brand-strong)"
        strokeWidth={2.4}
        strokeLinecap="round"
        strokeOpacity={0.45}
        fill="none"
      />
      {/* The break itself: two small terminals facing each other across the gap. */}
      <circle cx={172} cy={128} r={3.4} fill="var(--brand-strong)" fillOpacity={0.8} />
      <circle cx={196} cy={138} r={3.4} fill="var(--brand-strong)" fillOpacity={0.4} />
      {/* Two short strokes at the break, the universal shorthand for "no signal here". */}
      <path
        d="M 178 116 L 186 110 M 182 133 L 190 128"
        stroke="var(--brand-bright)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeOpacity={0.65}
      />
    </svg>
  );
}
