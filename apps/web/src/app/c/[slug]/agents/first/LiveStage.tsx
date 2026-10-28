"use client";

import type { ReactNode } from "react";
import { Check, Clock, Hourglass, PhoneOff, Smartphone, type LucideIcon } from "lucide-react";

import { formatDuration } from "@/components/ui";

/**
 * THE LIVE PANEL (founder, 23 Oct 2026): where the brief is read and where the agent calls
 * you. The build is a list of its real steps (`BuildStep`), not a picture (D-918).
 *
 * Part of the page: the soft grey well the console uses for a read-only area, a hairline
 * border, the brand green as the accent, and the illustration drawn in white on it as the
 * focus. It was a dark panel first; the founder rejected that as a dark hero card that read
 * as Outpero's.
 *
 * Every frame is a state the server reported: the call moves when the call's own row says
 * queued, ringing, in progress or ended. Nothing waits on a timer of its own, so the panel
 * can never show progress that did not happen.
 *
 * Inline SVG and HTML with the `stage-*` motion utilities in `globals.css`: transform and
 * opacity only, no library. Under reduced motion each state paints its finished frame and the
 * words carry it.
 */
export function Stage({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section aria-label={label} className="rounded-card border border-line bg-surface-muted p-4 sm:p-5">
      {children}
    </section>
  );
}

export type OrbState = "idle" | "working" | "ready" | "live" | "trouble";

/**
 * THE AGENT'S MARK on the call: its initial in a soft green disc, inside a ring that says what
 * it is doing. Working: an arc goes round. Ready or live: the ring is green. Trouble: amber.
 */
export function AgentOrb({ initial, state, size = 56 }: { initial: string | null; state: OrbState; size?: number }) {
  const ring = state === "trouble" ? "var(--warn)" : "var(--brand)";
  return (
    <span aria-hidden className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg viewBox="0 0 64 64" className="absolute inset-0 h-full w-full" fill="none">
        <circle cx="32" cy="32" r="30" stroke="var(--line)" strokeWidth="2" />
        {state === "working" ? (
          <circle
            cx="32"
            cy="32"
            r="30"
            stroke={ring}
            strokeWidth="2.5"
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray="0.22 0.78"
            className="stage-spin"
          />
        ) : state !== "idle" ? (
          <circle key={state} cx="32" cy="32" r="30" stroke={ring} strokeWidth="2.5" className="stage-in" />
        ) : null}
      </svg>
      <span
        className="grid place-items-center rounded-full bg-brand-soft font-semibold text-brand-strong"
        style={{ width: size - 16, height: size - 16, fontSize: Math.round(size * 0.36) }}
      >
        {initial ?? ""}
      </span>
    </span>
  );
}

/* ------------------------------------------------------------------------------------- */
/* Reading the brief                                                                     */
/* ------------------------------------------------------------------------------------- */

/** How much of the brief the reading panel shows: enough to recognise as yours. */
const READ_PREVIEW_CHARS = 220;

/**
 * While a worker reads the description and writes the follow-up questions: the owner's own
 * words, with a band passing over them, beside an agent mark that is working. It says what is
 * happening ("reading what you wrote") without inventing what the worker is looking for.
 */
export function ReadingStage({ brief, lang }: { brief: string; lang: string }) {
  const chars = Array.from(brief.trim());
  const shown =
    chars.length > READ_PREVIEW_CHARS ? `${chars.slice(0, READ_PREVIEW_CHARS).join("").trimEnd()}…` : chars.join("");
  return (
    <Stage label="Reading what you wrote">
      <div className="flex items-center gap-4">
        <AgentOrb initial={null} state="working" size={44} />
        <div className="min-w-0">
          <p className="text-heading text-ink">Reading what you wrote</p>
          <p role="status" className="text-meta text-ink-muted">
            Working out what a caller would still ask
          </p>
        </div>
      </div>
      {shown ? (
        <p lang={lang} className="mt-4 break-words border-l-2 border-brand/40 pl-4 text-[15px] leading-relaxed text-ink-muted">
          <span className="text-shimmer">{shown}</span>
        </p>
      ) : null}
    </Stage>
  );
}

/* ------------------------------------------------------------------------------------- */
/* The test call                                                                         */
/* ------------------------------------------------------------------------------------- */

export type CallPhase = "preparing" | "dialling" | "ringing" | "talking" | "ended" | "missed" | "limit" | "error";

const PHASE_WORDS: Readonly<Record<CallPhase, string>> = {
  preparing: "Getting it ready",
  dialling: "Dialling your phone",
  ringing: "Ringing your phone",
  talking: "On the call",
  ended: "Call ended",
  missed: "The call didn't reach you",
  limit: "No test call right now",
  error: "The call didn't start",
};

/**
 * The call as the call: the agent on the left, your phone on the right, and the line between
 * them doing what the line is doing. Dashes travel while it dials; the phone buzzes with rings
 * spreading while it rings; level bars move while you talk, with the clock; the line turns
 * green and the phone takes a tick when it ends. A call that did not connect, a limit and a
 * failure each have their own still frame, words and way on.
 */
export function CallStage({
  phase,
  name,
  seconds = 0,
  title,
  detail,
  actions,
  icon,
}: {
  phase: CallPhase;
  name: string;
  /** Seconds since the call was answered, while talking or once ended. */
  seconds?: number;
  /** Overrides the phase's own words (the server's reason for a limit, say). */
  title?: string;
  detail?: ReactNode;
  actions?: ReactNode;
  /** The phone end's icon when the phase's own does not say it (a clock for the day's limit). */
  icon?: LucideIcon;
}) {
  const initial = Array.from(name.trim())[0]?.toUpperCase() ?? null;
  const trouble = phase === "missed" || phase === "limit" || phase === "error";
  const orb: OrbState = phase === "preparing" ? "working" : trouble ? "trouble" : phase === "dialling" ? "idle" : "live";
  return (
    <Stage label={`Test call: ${PHASE_WORDS[phase]}`}>
      <div className="mx-auto flex max-w-md items-center gap-3">
        <div className="flex flex-col items-center gap-1.5">
          <AgentOrb initial={initial} state={orb} size={56} />
          <span className="max-w-20 truncate text-[12px] text-ink-muted">{name}</span>
        </div>
        <Line phase={phase} />
        <div className="flex flex-col items-center gap-1.5">
          <PhoneMark phase={phase} icon={icon} />
          <span className="text-[12px] text-ink-muted">You</span>
        </div>
      </div>

      <div className="mt-4 text-center" role="status" aria-live="polite">
        <p className="text-heading text-ink">{title ?? PHASE_WORDS[phase]}</p>
        {phase === "talking" || (phase === "ended" && seconds > 0) ? (
          <p className="mt-1 font-mono text-[28px] font-medium tabular-nums leading-none tracking-tight text-ink">
            {formatDuration(seconds)}
          </p>
        ) : null}
        {detail ? <div className="mx-auto mt-1.5 max-w-sm text-meta text-ink-muted">{detail}</div> : null}
      </div>
      {actions ? (
        <div className="mt-4 flex flex-col items-stretch gap-2 sm:flex-row sm:justify-center">{actions}</div>
      ) : null}
    </Stage>
  );
}

/** Level bars' timings: each bar its own, so they never move in step. */
const LEVELS = [
  { d: 620, delay: 0, h: 0.55 },
  { d: 480, delay: 120, h: 0.85 },
  { d: 700, delay: 60, h: 0.4 },
  { d: 540, delay: 200, h: 1 },
  { d: 660, delay: 30, h: 0.6 },
  { d: 500, delay: 160, h: 0.9 },
  { d: 720, delay: 90, h: 0.45 },
] as const;

function Line({ phase }: { phase: CallPhase }) {
  if (phase === "talking") {
    return (
      <span aria-hidden className="flex h-10 min-w-0 flex-1 items-center justify-center gap-1.5">
        {LEVELS.map((bar, index) => (
          <span
            key={index}
            className="stage-level h-8 w-1.5 rounded-full bg-brand"
            style={{
              animationDuration: `${bar.d}ms`,
              animationDelay: `${bar.delay}ms`,
              transform: `scaleY(${bar.h})`,
            }}
          />
        ))}
      </span>
    );
  }
  const solid = phase === "ringing" || phase === "ended";
  return (
    <span aria-hidden className="relative h-0.5 min-w-0 flex-1 overflow-hidden rounded-full bg-line">
      {phase === "dialling" ? <span className="stage-dash absolute inset-y-0 -left-3 right-0" /> : null}
      {solid ? <span className={`stage-in absolute inset-0 ${phase === "ended" ? "bg-brand" : "bg-brand/50"}`} /> : null}
    </span>
  );
}

function PhoneMark({ phase, icon }: { phase: CallPhase; icon?: LucideIcon }) {
  const trouble = phase === "missed" || phase === "error" || phase === "limit";
  const Icon = icon ?? (phase === "limit" ? Hourglass : trouble ? PhoneOff : Smartphone);
  const tone = trouble
    ? "border-warn-line bg-warn-soft text-warn"
    : phase === "dialling" || phase === "preparing"
      ? "border-line bg-surface text-ink-faint"
      : "border-brand/50 bg-surface text-brand-strong";
  return (
    <span aria-hidden className="relative grid h-14 w-14 place-items-center">
      {phase === "ringing" ? (
        <>
          <span className="stage-ripple absolute inset-0 rounded-full border border-brand" />
          <span className="stage-ripple absolute inset-0 rounded-full border border-brand [animation-delay:800ms]" />
        </>
      ) : null}
      <span className={`relative grid h-12 w-12 place-items-center rounded-full border ${tone}`}>
        <Icon className={`h-5 w-5 ${phase === "ringing" ? "stage-buzz" : ""}`} />
        {phase === "ended" ? (
          <span className="absolute -bottom-0.5 -right-0.5 grid h-5 w-5 place-items-center rounded-full bg-brand-strong text-white">
            <Check className="h-3 w-3" strokeWidth={3} />
          </span>
        ) : null}
      </span>
    </span>
  );
}

/** The icon a limit is drawn with on its own: the day's calls (a clock) or the minutes. */
export function limitIcon(rule: string | null | undefined): LucideIcon {
  return rule && rule.includes("daily") ? Clock : Hourglass;
}
