/**
 * Isometric brand illustrations for the marketing homepage.
 *
 * ## The technique, in one place
 *
 * Each figure is built from rounded rectangles pushed through the classic 2:1 isometric
 * TOP-FACE transform — `matrix(0.866025 0.5 -0.866025 0.5 tx ty)` — so a square becomes a
 * diamond whose local x-axis runs down-right and local y-axis down-left (30°, cos30 =
 * 0.866025). A slab's THICKNESS is faked the way the reference art does it: draw the same
 * rounded rect twice, the lower copy shifted straight down in screen space, and the sliver
 * that peeks out below reads as the edge. Cubes add two explicit side-wall parallelograms.
 * `topMatrix` and `P` are the only geometry helpers; everything else is composition.
 *
 * ## Colour is theme-safe by construction
 *
 * Colours are set as `var(--token)` attributes — the same idiom `successRipple.tsx` uses,
 * which is how this repo already proves CSS custom properties resolve inside SVG
 * presentation attributes. The BRAND tokens (`--brand*`) are theme-invariant (globals.css
 * redefines only `--surface`/`--app`/`--line`/`--ink*` under `.dark`), so every stroke,
 * accent face, gradient and glow here uses a brand token and stays correct in both themes;
 * neutral "paper" faces use `--surface`, which is meant to follow the theme so the figure's
 * cards track the real cards beside them. The palette is tuned for the LIGHT editorial page
 * these sit on: thin `--brand-strong` strokes on light faces, low-opacity brand glass for
 * the accent faces.
 *
 * ## Motion
 *
 * No JS and no motion library — these are pure, SSR-safe SVG. The gentle idle loops are the
 * `mk-iso-*` classes defined once in globals.css under `[data-marketing-root]`, so (a) they
 * only ever animate on the marketing page, and (b) the marketing-scoped
 * `prefers-reduced-motion` reset already freezes them at their resting frame — every idle
 * keyframe here is written so 0%/100% IS the clean static state, so a reduced-motion reader
 * (and the test suite, which reports `reduce`) sees a settled, correct figure.
 *
 * Every export is decorative: `aria-hidden`, `focusable={false}`, sized by the caller's
 * `className` against a `viewBox` so it scales fluidly. They add no text nodes and no
 * `<img>`, so `publicLanding.test.tsx`'s negative assertions are untouched.
 */

import type { SVGProps } from "react";

/** cos(30°): the isometric foreshortening, matched to the reference matrix literal. */
const K = 0.866025;

/** The top-face transform placing a rect's local origin at screen (ox, oy). */
const topMatrix = (ox: number, oy: number) => `matrix(${K} 0.5 ${-K} 0.5 ${ox} ${oy})`;

/** Screen "x y" of local point (x, y) on a top-face plane rooted at (ox, oy). */
const P = (ox: number, oy: number, x: number, y: number) =>
  `${+(ox + K * x - K * y).toFixed(2)} ${+(oy + 0.5 * x + 0.5 * y).toFixed(2)}`;

type SlabProps = {
  /** Screen position of the slab's top (back) vertex. */
  ox: number;
  oy: number;
  /** Local side length (the slab is square in-plane). */
  s: number;
  rx: number;
  /** Thickness, in screen pixels straight down. */
  t: number;
  top: string;
  side: string;
  topOpacity?: number;
  sideOpacity?: number;
  stroke?: string;
  strokeOp?: number;
  sw?: number;
};

/**
 * One flat slab: a lower "thickness" copy plus the top face over it. The whole depth
 * illusion is the offset between the two, so callers stack these by decreasing `oy`.
 */
function Slab({
  ox,
  oy,
  s,
  rx,
  t,
  top,
  side,
  topOpacity = 1,
  sideOpacity = 1,
  stroke = "var(--brand-strong)",
  strokeOp = 0.6,
  sw = 1.2,
}: SlabProps) {
  return (
    <>
      <rect
        width={s}
        height={s}
        rx={rx}
        transform={topMatrix(ox, oy + t)}
        fill={side}
        fillOpacity={sideOpacity}
        stroke={stroke}
        strokeWidth={sw}
        strokeOpacity={strokeOp * 0.55}
      />
      <rect
        width={s}
        height={s}
        rx={rx}
        transform={topMatrix(ox, oy)}
        fill={top}
        fillOpacity={topOpacity}
        stroke={stroke}
        strokeWidth={sw}
        strokeOpacity={strokeOp}
      />
    </>
  );
}

/**
 * A lifted cube with an in-plane equaliser and a pinging signal — the "it answers, live"
 * motif for the hero. The cube floats above a soft green contact halo.
 */
export function IsoHandset({ className, ...props }: SVGProps<SVGSVGElement>) {
  // Local equaliser bars on the top face (centred on the 62-unit face), varied heights.
  const bars = [
    { x: 14, h: 18 },
    { x: 23, h: 32 },
    { x: 32, h: 24 },
    { x: 41, h: 34 },
    { x: 50, h: 20 },
  ];

  return (
    <svg
      viewBox="0 0 200 172"
      fill="none"
      aria-hidden
      focusable="false"
      className={className}
      {...props}
    >
      <defs>
        <linearGradient id="isoHandsetGlass" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--brand-bright)" stopOpacity={0.9} />
          <stop offset="100%" stopColor="var(--brand)" stopOpacity={0.95} />
        </linearGradient>
      </defs>

      {/* Soft green halo standing in for a ground shadow — brand token, so it reads on
          both themes rather than inverting the way an ink shadow would. */}
      <ellipse cx={100} cy={150} rx={46} ry={11} fill="var(--brand)" fillOpacity={0.1} />

      <g className="mk-iso-float-a">
        {/* Front-left and front-right walls (the shaded sides of the cube). */}
        <path
          d={`M ${P(100, 30, 0, 62)} L ${P(100, 30, 62, 62)} L ${P(100, 72, 62, 62)} L ${P(100, 72, 0, 62)} Z`}
          fill="var(--brand-strong)"
          fillOpacity={0.9}
          stroke="var(--brand-strong)"
          strokeWidth={1.1}
          strokeLinejoin="round"
        />
        <path
          d={`M ${P(100, 30, 62, 62)} L ${P(100, 30, 62, 0)} L ${P(100, 72, 62, 0)} L ${P(100, 72, 62, 62)} Z`}
          fill="var(--brand)"
          fillOpacity={0.92}
          stroke="var(--brand-strong)"
          strokeWidth={1.1}
          strokeLinejoin="round"
        />
        {/* Top face: green glass. */}
        <rect
          width={62}
          height={62}
          rx={12}
          transform={topMatrix(100, 30)}
          fill="url(#isoHandsetGlass)"
          stroke="var(--brand-strong)"
          strokeWidth={1.25}
          strokeOpacity={0.7}
        />
        {/* Equaliser lying in the top-face plane. */}
        {bars.map((b) => (
          <rect
            key={b.x}
            x={b.x - 2.25}
            y={31 - b.h / 2}
            width={4.5}
            height={b.h}
            rx={2}
            transform={topMatrix(100, 30)}
            fill="var(--surface)"
            fillOpacity={0.92}
          />
        ))}
        {/* Incoming-signal dot with an expanding ping ring. */}
        <circle cx={150} cy={32} r={5.5} fill="var(--brand-strong)" />
        <circle
          cx={150}
          cy={32}
          r={5.5}
          className="mk-iso-ping"
          fill="none"
          stroke="var(--brand-bright)"
          strokeWidth={1.6}
        />
      </g>
    </svg>
  );
}

/**
 * A small stack of rounded cards with the top one lifting off, carrying three extracted
 * "rows" — a call becoming a CRM record.
 */
export function IsoCallStack({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 210 176"
      fill="none"
      aria-hidden
      focusable="false"
      className={className}
      {...props}
    >
      <defs>
        <linearGradient id="isoStackGlass" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--brand-bright)" stopOpacity={0.9} />
          <stop offset="100%" stopColor="var(--brand-strong)" stopOpacity={0.92} />
        </linearGradient>
      </defs>

      {/* The two resting cards. */}
      <Slab ox={105} oy={78} s={84} rx={16} t={12} top="var(--surface)" side="var(--brand)" sideOpacity={0.16} />
      <Slab ox={105} oy={62} s={84} rx={16} t={12} top="var(--surface)" side="var(--brand)" sideOpacity={0.22} />

      {/* The contact shadow the lifted card leaves on the stack — a green tint, so it holds
          up in both themes and stays put while the card above it bobs. */}
      <rect
        width={84}
        height={84}
        rx={16}
        transform={topMatrix(105, 50)}
        fill="var(--brand-strong)"
        fillOpacity={0.12}
      />

      {/* The lifted record. */}
      <g className="mk-iso-lift">
        <rect
          width={84}
          height={84}
          rx={16}
          transform={topMatrix(105, 46)}
          fill="var(--brand)"
          fillOpacity={0.28}
          stroke="var(--brand-strong)"
          strokeWidth={1.2}
          strokeOpacity={0.4}
        />
        <rect
          width={84}
          height={84}
          rx={16}
          transform={topMatrix(105, 34)}
          fill="url(#isoStackGlass)"
          stroke="var(--brand-strong)"
          strokeWidth={1.25}
          strokeOpacity={0.7}
        />
        {/* Extracted fields, in the top-face plane; the middle one highlighted. */}
        <rect x={16} y={22} width={52} height={7} rx={3.5} transform={topMatrix(105, 34)} fill="var(--surface)" fillOpacity={0.92} />
        <rect x={16} y={40} width={34} height={7} rx={3.5} transform={topMatrix(105, 34)} fill="var(--brand-bright)" />
        <rect x={16} y={58} width={46} height={7} rx={3.5} transform={topMatrix(105, 34)} fill="var(--surface)" fillOpacity={0.92} />
      </g>
    </svg>
  );
}

/**
 * A five-tier isometric stack: white slabs with a green "spine" that deepens toward the
 * base, gently floating as one.
 *
 * Ornament, not a diagram. TRD §6 names five retrieval tiers and the product ships ONE of
 * them — T0, facts compiled into the prompt at publish time (`docs/TRD.md:948`) — so the
 * slabs are unlabelled and the whole thing is `aria-hidden`. Do not annotate them: a
 * labelled tier stack on a marketing page is a claim about a system we do not run.
 */
export function IsoKnowledge({ className, ...props }: SVGProps<SVGSVGElement>) {
  // i = 0 is the base tier (drawn first, lowest on screen); i = 4 is the apex.
  const tiers = [0, 1, 2, 3, 4];
  const sides = [
    "var(--brand-deep)",
    "var(--brand-strong)",
    "var(--brand)",
    "var(--brand-bright)",
    "var(--brand-bright)",
  ];

  return (
    <svg
      viewBox="0 0 210 208"
      fill="none"
      aria-hidden
      focusable="false"
      className={className}
      {...props}
    >
      <g className="mk-iso-float-b">
        {tiers.map((i) => (
          <Slab
            key={i}
            ox={105}
            oy={18 + (4 - i) * 20}
            s={78}
            rx={14}
            t={13}
            top={i === 4 ? "var(--brand-soft)" : "var(--surface)"}
            side={sides[i]}
            sideOpacity={0.9}
            strokeOp={0.55}
          />
        ))}
      </g>
    </svg>
  );
}

/**
 * Three isometric stages stepping down-right with pulsing "leads" travelling the dashed
 * path between them — the campaign pipeline, the last stage brightened as the converted one.
 */
export function IsoPipeline({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 232 168"
      fill="none"
      aria-hidden
      focusable="false"
      className={className}
      {...props}
    >
      {/* Stages, back (upper-left) to front (lower-right). */}
      <Slab ox={52} oy={26} s={58} rx={12} t={10} top="var(--surface)" side="var(--brand)" sideOpacity={0.16} />
      <Slab ox={112} oy={54} s={58} rx={12} t={10} top="var(--surface)" side="var(--brand)" sideOpacity={0.24} />
      <Slab ox={172} oy={82} s={58} rx={12} t={10} top="var(--brand-soft)" side="var(--brand)" sideOpacity={0.32} />

      {/* Flow path across the stage centroids (each at oy + s/2). */}
      <path
        d="M52 55 L112 83 L172 111"
        fill="none"
        stroke="var(--brand-strong)"
        strokeWidth={1.6}
        strokeOpacity={0.4}
        strokeDasharray="1 6"
        strokeLinecap="round"
      />

      {/* The leads: staggered pulses, the final one converted (bright, larger). */}
      <circle cx={52} cy={55} r={6.5} fill="var(--brand-strong)" className="mk-iso-flow" />
      <circle cx={112} cy={83} r={6.5} fill="var(--brand-strong)" className="mk-iso-flow" style={{ animationDelay: "0.5s" }} />
      <circle cx={172} cy={111} r={7.5} fill="var(--brand-bright)" className="mk-iso-flow" style={{ animationDelay: "1s" }} />
    </svg>
  );
}

/**
 * A frosted-glass cube carrying a shield-and-check emblem — the compliance motif, tuned for
 * the dark brand band it sits on. The cube's linework is `currentColor` (white on that band)
 * with a brand-bright emblem, and it floats above a faint brand glow rather than a shadow.
 */
export function IsoShield({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 188 172"
      fill="none"
      aria-hidden
      focusable="false"
      className={className}
      {...props}
    >
      <defs>
        <linearGradient id="isoShieldGlass" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity={0.14} />
          <stop offset="100%" stopColor="var(--brand-bright)" stopOpacity={0.12} />
        </linearGradient>
      </defs>

      {/* Lift glow instead of a shadow — a shadow darker than the dark-green band would need
          black; a brand-bright glow reads correctly on it. */}
      <ellipse cx={94} cy={150} rx={44} ry={11} fill="var(--brand-bright)" fillOpacity={0.12} />

      <g className="mk-iso-float-a">
        {/* Frosted side walls. */}
        <path
          d={`M ${P(94, 30, 0, 60)} L ${P(94, 30, 60, 60)} L ${P(94, 74, 60, 60)} L ${P(94, 74, 0, 60)} Z`}
          fill="currentColor"
          fillOpacity={0.06}
          stroke="currentColor"
          strokeWidth={1.1}
          strokeOpacity={0.22}
          strokeLinejoin="round"
        />
        <path
          d={`M ${P(94, 30, 60, 60)} L ${P(94, 30, 60, 0)} L ${P(94, 74, 60, 0)} L ${P(94, 74, 60, 60)} Z`}
          fill="currentColor"
          fillOpacity={0.03}
          stroke="currentColor"
          strokeWidth={1.1}
          strokeOpacity={0.22}
          strokeLinejoin="round"
        />
        {/* Top face. */}
        <rect
          width={60}
          height={60}
          rx={12}
          transform={topMatrix(94, 30)}
          fill="url(#isoShieldGlass)"
          stroke="currentColor"
          strokeWidth={1.2}
          strokeOpacity={0.3}
        />
        {/* Shield emblem, upright in screen space so it reads as a badge on the cube. */}
        <path
          d="M94 62 L118 71 L118 95 C118 114 94 125 94 125 C94 125 70 114 70 95 L70 71 Z"
          fill="var(--brand-bright)"
          fillOpacity={0.92}
          stroke="currentColor"
          strokeWidth={1}
          strokeOpacity={0.25}
          strokeLinejoin="round"
        />
        <path
          d="M83 93 L91 102 L106 84"
          fill="none"
          stroke="currentColor"
          strokeWidth={3.6}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    </svg>
  );
}
