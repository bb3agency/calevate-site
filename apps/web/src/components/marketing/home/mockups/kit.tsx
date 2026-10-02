import type { ReactNode } from "react";

/**
 * THE PARTS EVERY HOMEPAGE MOCKUP IS DRAWN FROM.
 *
 * The mockups are the product's own screens, re-drawn at marketing scale and filled with
 * ILLUSTRATIVE sample data: the labels, statuses and colours are the console's real ones
 * (each mockup names the screen it is drawn from), and the people, places and counts are
 * made up for a dental clinic in Hyderabad and a property office in Vijayawada.
 *
 * Honesty rules the sample data follows, because every word here is text on a public page
 * (`publicLanding` scans `textContent`, which includes `aria-hidden` subtrees):
 * - no phone number that could be real — the mask `+91 98XXX XX123` cannot be dialled;
 * - no percentage, rate, price or score, and no count presented as a result we achieved;
 *   the section captions say these are illustrations;
 * - no snake_case wire values: where the console prints a raw enum we print the words.
 *
 * Nothing here is `<p>`/`<li>`/`<h*>`: a mockup's words are not the page's prose or its
 * heading outline.
 */

/** A skeleton line. Width is a Tailwind class so every bar stays on the spacing scale. */
export function Bar({
  w = "w-full",
  tone = "base",
  className = "",
}: {
  w?: string;
  tone?: "base" | "strong" | "brand" | "faint";
  className?: string;
}) {
  const fill = {
    base: "bg-ink/10",
    strong: "bg-ink/20",
    brand: "bg-brand/35",
    faint: "bg-ink/[0.06]",
  }[tone];
  return <span className={`block h-2 rounded-full ${fill} ${w} ${className}`} />;
}

/** A person's initials in a soft disc, as the console's own `Avatar` draws them. */
export function Avatar({
  name,
  className = "h-7 w-7",
  tone = "base",
}: {
  name?: string;
  className?: string;
  tone?: "base" | "brand";
}) {
  const initials = (name ?? "")
    .split(/\s+/)
    .map((part) => part[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <span
      className={`flex shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
        tone === "brand" ? "bg-brand-soft dark:bg-brand-strong/20 text-brand-strong dark:text-brand-bright" : "bg-slate-100 dark:bg-white/[0.06] text-slate-600 dark:text-slate-300"
      } ${className}`}
    >
      {initials}
    </span>
  );
}

/**
 * The six lead stages, in the console's own colours (`components/ui.tsx`
 * `LEAD_STATUS_STYLES`) and its own casing: the leads table prints the raw lowercase value.
 */
export type LeadStatus = "new" | "contacted" | "interested" | "hot" | "won" | "lost";

const STATUS_TONE: Record<LeadStatus, string> = {
  new: "bg-slate-100 dark:bg-white/[0.06] text-slate-700 dark:text-slate-300",
  contacted: "bg-sky-100 text-sky-800",
  interested: "bg-violet-100 text-violet-800",
  hot: "bg-amber-100 text-amber-900",
  won: "bg-emerald-100 text-emerald-800",
  lost: "bg-rose-100 text-rose-800",
};

export function StatusPill({ status, className = "" }: { status: LeadStatus; className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap ${STATUS_TONE[status]} ${className}`}
    >
      {status}
    </span>
  );
}

/** A call's status or outcome pill, same shape as the console's. */
export function Tag({
  children,
  tone = "slate",
  className = "",
}: {
  children: ReactNode;
  tone?: "slate" | "emerald" | "sky" | "amber" | "violet" | "brand";
  className?: string;
}) {
  const fill = {
    slate: "bg-slate-100 dark:bg-white/[0.06] text-slate-700 dark:text-slate-300",
    emerald: "bg-emerald-100 text-emerald-800",
    sky: "bg-sky-100 text-sky-800",
    amber: "bg-amber-100 text-amber-900",
    violet: "bg-violet-100 text-violet-800",
    brand: "bg-brand-soft dark:bg-brand-strong/20 text-brand-strong dark:text-brand-bright",
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap ${fill} ${className}`}
    >
      {children}
    </span>
  );
}

/** A masked caller number. The X's are deliberate: no sample number can be dialled. */
export function MaskedPhone({ tail = "123", className = "" }: { tail?: string; className?: string }) {
  return (
    <span className={`font-mono text-[11px] whitespace-nowrap text-ink-muted ${className}`}>
      +91 98XXX XX{tail}
    </span>
  );
}

/** A small label chip: a language, a field type, a filter. */
export function Chip({
  children,
  tone = "neutral",
  className = "",
}: {
  children: ReactNode;
  tone?: "neutral" | "brand";
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] leading-5 font-medium whitespace-nowrap ${
        tone === "brand"
          ? "bg-brand-soft dark:bg-brand-strong/20 text-brand-strong dark:text-brand-bright"
          : "bg-surface text-ink-muted ring-1 ring-line"
      } ${className}`}
    >
      {children}
    </span>
  );
}

/**
 * A panel of product UI: white, hairline, lifted. `overlay` is the floating layer that sits
 * on top of a window (a toast, a side sheet) and takes the strongest elevation token.
 */
export function Panel({
  children,
  className = "",
  elevation = "card",
}: {
  children: ReactNode;
  className?: string;
  elevation?: "card" | "raised" | "overlay";
}) {
  const shadow = { card: "shadow-card", raised: "shadow-raised", overlay: "shadow-overlay" }[
    elevation
  ];
  return (
    <div className={`rounded-xl border border-line bg-surface ${shadow} ${className}`}>
      {children}
    </div>
  );
}

/**
 * An app window: a title strip and a body. The strip names the SCREEN ("Leads",
 * "Campaign") because that is the one word that tells a stranger which part of the
 * product they are looking at; everything else in it is skeleton.
 */
export function Window({
  title,
  children,
  className = "",
  actions,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
}) {
  return (
    <div
      className={`overflow-hidden rounded-2xl border border-line bg-surface shadow-raised ${className}`}
    >
      <div className="flex h-10 items-center gap-3 border-b border-line bg-app/70 px-4">
        <span className="flex gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-ink/10" />
          <span className="h-2.5 w-2.5 rounded-full bg-ink/10" />
          <span className="h-2.5 w-2.5 rounded-full bg-ink/10" />
        </span>
        <span className="text-xs font-semibold text-ink-muted">{title}</span>
        {actions && <span className="ml-auto flex items-center gap-2">{actions}</span>}
      </div>
      {children}
    </div>
  );
}

/*
 * A voice level, drawn rather than sampled. The heights are a fixed shape (louder in the
 * middle of a phrase, quieter at its edges) so the server and the client draw the same
 * thing and nothing is random at render time.
 */
const LEVELS = [
  3, 5, 8, 6, 10, 14, 9, 12, 16, 11, 7, 13, 18, 12, 9, 15, 10, 6, 11, 8, 5, 9, 6, 4,
] as const;
const PHASES = ["", "mk-eq--b", "mk-eq--c", "mk-eq--d"] as const;

export function Waveform({
  bars = LEVELS.length,
  live = false,
  size = "lg",
  tone = "brand",
  className = "",
}: {
  bars?: number;
  /** Breathes while on screen. Off for a recording, which is a fixed shape. */
  live?: boolean;
  size?: "sm" | "lg";
  tone?: "brand" | "muted" | "inverse";
  className?: string;
}) {
  const colour = { brand: "bg-brand", muted: "bg-ink/20", inverse: "bg-white/80" }[tone];
  const steps = HEIGHT[size];
  return (
    <span className={`flex items-center gap-[3px] ${size === "lg" ? "h-10" : "h-5"} ${className}`}>
      {LEVELS.slice(0, bars).map((level, i) => (
        <span
          // Index keys are correct here: the list is a fixed literal that never reorders.
          key={i}
          className={`block w-[3px] shrink-0 rounded-full ${colour} ${
            steps[Math.min(4, Math.floor(level / 4))]
          } ${live ? `mk-eq ${PHASES[i % PHASES.length]}` : ""}`}
        />
      ))}
    </span>
  );
}

/** Five steps of bar height per size. A class per step keeps every bar on the scale. */
const HEIGHT = {
  sm: ["h-1", "h-2", "h-3", "h-4", "h-5"],
  lg: ["h-2", "h-4", "h-6", "h-8", "h-10"],
} as const;
