"use client";

import type { ReactNode } from "react";
import {
  AlertTriangle,
  BookOpenText,
  Check,
  Clock,
  Hourglass,
  MessageSquareQuote,
  PhoneOff,
  ShieldCheck,
  Smartphone,
  AudioLines,
  X,
  type LucideIcon,
} from "lucide-react";

import { formatDuration } from "@/components/ui";
import type { FirstRunBuildStep } from "@/lib/api/firstRun";

/**
 * THE LIVE STAGE (founder, 23 Oct 2026): the one dark panel on the light first-run screen,
 * where the agent is built and where it calls you.
 *
 * Every frame is a state the server reported. The build's rows move when `GET /v1/first-run`
 * says a step is being worked on or is done; the call moves when the call's own row says
 * queued, ringing, in progress or ended. Nothing waits on a timer of its own, so the stage
 * can never show progress that did not happen.
 *
 * Hand-built from HTML, inline SVG and the `stage-*` utilities in `globals.css`: transform
 * and opacity only, no library, nothing loaded. Under reduced motion each state paints its
 * finished frame and the words carry it.
 */
export function Stage({
  label,
  children,
  className = "",
}: {
  /** The region's accessible name ("Your agent being built"). */
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={label}
      className={`relative isolate overflow-hidden rounded-[18px] bg-stage p-5 text-stage-ink shadow-raised sm:p-6 ${className}`}
    >
      {/* The agent's light: one soft green glow behind the mark, so the stage has a source. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -left-16 -top-20 z-below h-56 w-56 rounded-full bg-[radial-gradient(closest-side,rgb(74_222_128/0.16),transparent)]"
      />
      {children}
    </section>
  );
}

export type OrbState = "idle" | "working" | "ready" | "live" | "trouble";

/**
 * THE AGENT'S MARK on the stage: its initial in a disc, inside a ring that says what it is
 * doing. Working: an arc goes round. Ready: the ring draws closed. Live (on a call): the ring
 * is lit. Trouble: the ring turns amber.
 */
export function AgentOrb({ initial, state, size = 64 }: { initial: string | null; state: OrbState; size?: number }) {
  const ring = state === "trouble" ? "var(--stage-warn)" : state === "idle" ? "var(--stage-line)" : "var(--stage-live)";
  return (
    <span
      aria-hidden
      className="relative inline-grid shrink-0 place-items-center"
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 64 64" className="absolute inset-0 h-full w-full" fill="none">
        <circle cx="32" cy="32" r="30" stroke="var(--stage-line)" strokeWidth="2" />
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
          <circle
            key={state}
            cx="32"
            cy="32"
            r="30"
            stroke={ring}
            strokeWidth="2.5"
            pathLength={1}
            transform="rotate(-90 32 32)"
            className="stage-draw"
          />
        ) : null}
      </svg>
      <span
        className={`grid place-items-center rounded-full bg-stage-raised font-semibold text-stage-ink ${
          state === "live" ? "ring-1 ring-stage-live/40" : ""
        }`}
        style={{
          width: size - 16,
          height: size - 16,
          fontSize: Math.round(size * 0.36),
        }}
      >
        {initial ?? ""}
      </span>
    </span>
  );
}

/* ------------------------------------------------------------------------------------- */
/* The build                                                                             */
/* ------------------------------------------------------------------------------------- */

export type RowState = "waiting" | "working" | "done" | "warn" | "failed";

const STEP_ICON: Readonly<Record<FirstRunBuildStep["step"], LucideIcon>> = {
  voice: AudioLines,
  script: BookOpenText,
  greeting: MessageSquareQuote,
  notice: ShieldCheck,
};

export interface BuildRow {
  step: FirstRunBuildStep["step"];
  title: string;
  /** While worked on: what it is doing ("Choosing a voice for Telugu"). */
  doing: string;
  /** Once done: what really happened ("Lakshmi · Studio"). */
  result?: string;
  state: RowState;
}

/**
 * The build as it happens: four rows on a rail that fills as each lands. The row being worked
 * on names what it is doing with a moving band; a finished row draws its tick and says what
 * was chosen. The rail's fill is a `scaleY` of the share done, so it grows in step with the
 * rows, never ahead of them.
 */
export function BuildStage({
  rows,
  name,
  greeting,
  greetingLang,
  built,
  failed,
  footer,
}: {
  rows: readonly BuildRow[];
  name: string | null;
  greeting: string | null;
  greetingLang: string;
  built: boolean;
  failed: boolean;
  footer?: ReactNode;
}) {
  const done = rows.filter((row) => row.state === "done" || row.state === "warn").length;
  const working = rows.find((row) => row.state === "working");
  const initial = name ? (Array.from(name.trim())[0]?.toUpperCase() ?? null) : null;
  const fill = rows.length > 1 ? Math.min(1, Math.max(0, (done - (built ? 1 : 0.5)) / (rows.length - 1))) : 0;
  const greetingDone = rows.some((row) => row.step === "greeting" && row.state === "done");

  return (
    <Stage label={built ? `${name ?? "Your agent"} is built` : "Your agent being built"}>
      <div className="flex items-center gap-4">
        <AgentOrb initial={initial} state={failed ? "trouble" : built ? "ready" : "working"} />
        <div className="min-w-0">
          <p className="truncate text-heading text-stage-ink">
            {built && name ? name : name ? `Building ${name}` : "Choosing its voice"}
          </p>
          <p aria-live="polite" className="text-meta text-stage-muted">
            {failed
              ? "Stopped before it finished"
              : built
                ? "Ready to ring you"
                : `${done} of ${rows.length} done${working ? ` · ${working.title}` : ""}`}
          </p>
        </div>
      </div>

      <ol className="relative mt-4 space-y-3">
        <span aria-hidden className="absolute bottom-3.5 left-[13px] top-3.5 w-0.5 rounded-full bg-stage-line">
          <span
            className="block h-full w-full origin-top rounded-full bg-stage-live transition-transform duration-500 ease-out motion-reduce:transition-none"
            style={{ transform: `scaleY(${fill})` }}
          />
        </span>
        {rows.map((row) => (
          <li key={row.step} className="relative grid grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-x-3">
            <StepMark state={row.state} icon={STEP_ICON[row.step]} />
            <div className="min-w-0 pt-0.5">
              <p className={`text-body font-medium ${row.state === "waiting" ? "text-stage-faint" : "text-stage-ink"}`}>
                <span className="sr-only">{ROW_WORDS[row.state]}: </span>
                {row.title}
              </p>
              {row.state === "working" ? (
                <p className="text-meta text-stage-muted">
                  <span className="stage-shimmer">{row.doing}</span>
                </p>
              ) : row.result && (row.state === "done" || row.state === "warn") ? (
                <p
                  key={row.state}
                  className={`stage-in break-words text-meta ${row.state === "warn" ? "text-stage-warn" : "text-stage-muted"}`}
                >
                  {row.result}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ol>

      {greetingDone && greeting ? (
        <figure className="stage-in mt-5 rounded-xl border border-stage-line bg-stage-raised px-4 py-3">
          <figcaption className="text-meta text-stage-faint">It opens every call with</figcaption>
          <blockquote lang={greetingLang} className="mt-1 break-words text-[15px] leading-relaxed text-stage-ink">
            “{greeting}”
          </blockquote>
        </figure>
      ) : null}
      {footer ? <div className="mt-5">{footer}</div> : null}
    </Stage>
  );
}

const ROW_WORDS: Readonly<Record<RowState, string>> = {
  waiting: "Waiting",
  working: "Working on it",
  done: "Done",
  warn: "Needs you",
  failed: "Stopped",
};

/** A row's mark: a ring while waiting, an arc going round while worked on, a drawn tick when
 *  done, an amber or red mark when it needs the owner. */
function StepMark({ state, icon: Icon }: { state: RowState; icon: LucideIcon }) {
  const lit = state === "done";
  return (
    <span aria-hidden className="relative z-raised grid h-7 w-7 place-items-center rounded-full bg-stage">
      <svg viewBox="0 0 28 28" className="absolute inset-0 h-7 w-7" fill="none">
        <circle
          cx="14"
          cy="14"
          r="13"
          fill={lit ? "rgb(74 222 128 / 0.14)" : "var(--stage)"}
          stroke={
            state === "warn"
              ? "var(--stage-warn)"
              : state === "failed"
                ? "var(--stage-danger)"
                : lit
                  ? "var(--stage-live)"
                  : "var(--stage-line)"
          }
          strokeWidth="1.5"
        />
        {state === "working" ? (
          <circle
            cx="14"
            cy="14"
            r="13"
            stroke="var(--stage-live)"
            strokeWidth="2"
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray="0.3 0.7"
            className="stage-spin"
          />
        ) : null}
        {lit ? (
          <path
            d="M9 14.5l3.2 3.2L19 11"
            stroke="var(--stage-live)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            className="stage-draw"
          />
        ) : null}
      </svg>
      {lit ? null : state === "warn" ? (
        <AlertTriangle className="relative h-3.5 w-3.5 text-stage-warn" />
      ) : state === "failed" ? (
        <X className="relative h-3.5 w-3.5 text-stage-danger" />
      ) : (
        <Icon className={`relative h-3.5 w-3.5 ${state === "working" ? "text-stage-ink" : "text-stage-faint"}`} />
      )}
    </span>
  );
}

/* ------------------------------------------------------------------------------------- */
/* Reading the brief                                                                     */
/* ------------------------------------------------------------------------------------- */

/** How much of the brief the reading stage shows: enough to recognise as yours. */
const READ_PREVIEW_CHARS = 220;

/**
 * While a worker reads the description and writes the follow-up questions: the owner's own
 * words, with a band passing over them, under an agent mark that is working. It says what is
 * happening ("reading what you wrote") without inventing what the worker is looking for.
 */
export function ReadingStage({ brief, lang }: { brief: string; lang: string }) {
  const chars = Array.from(brief.trim());
  const shown =
    chars.length > READ_PREVIEW_CHARS ? `${chars.slice(0, READ_PREVIEW_CHARS).join("").trimEnd()}…` : chars.join("");
  return (
    <Stage label="Reading what you wrote">
      <div className="flex items-center gap-4">
        <AgentOrb initial={null} state="working" size={48} />
        <div className="min-w-0">
          <p className="text-heading text-stage-ink">Reading what you wrote</p>
          <p role="status" className="text-meta text-stage-muted">
            Working out what a caller would still ask
          </p>
        </div>
      </div>
      {shown ? (
        <p
          lang={lang}
          className="mt-5 break-words border-l-2 border-stage-live/50 pl-4 text-[15px] leading-relaxed text-stage-muted"
        >
          <span className="stage-shimmer">{shown}</span>
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
 * them doing what the line is doing. Dashes travel while it dials; the phone buzzes with
 * rings spreading while it rings; level bars move while you talk, with the clock; the line
 * lights and the phone takes a tick when it ends. A call that did not connect, a limit and a
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
  const orb: OrbState =
    phase === "preparing" ? "working" : trouble ? "trouble" : phase === "dialling" ? "idle" : "live";
  return (
    <Stage label={`Test call: ${PHASE_WORDS[phase]}`}>
      <div className="flex items-center gap-3">
        <div className="flex flex-col items-center gap-1.5">
          <AgentOrb initial={initial} state={orb} size={56} />
          <span className="max-w-20 truncate text-[12px] text-stage-faint">{name}</span>
        </div>
        <Line phase={phase} />
        <div className="flex flex-col items-center gap-1.5">
          <PhoneMark phase={phase} icon={icon} />
          <span className="text-[12px] text-stage-faint">You</span>
        </div>
      </div>

      <div className="mt-5 text-center" role="status" aria-live="polite">
        <p className="text-heading text-stage-ink">{title ?? PHASE_WORDS[phase]}</p>
        {phase === "talking" || (phase === "ended" && seconds > 0) ? (
          <p className="mt-1 font-mono text-[28px] font-medium tabular-nums leading-none tracking-tight text-stage-ink">
            {formatDuration(seconds)}
          </p>
        ) : null}
        {detail ? <div className="mx-auto mt-1.5 max-w-sm text-meta text-stage-muted">{detail}</div> : null}
      </div>
      {actions ? (
        <div className="mt-5 flex flex-col items-stretch gap-2 sm:flex-row sm:justify-center">{actions}</div>
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
            className="stage-level h-8 w-1.5 rounded-full bg-stage-live"
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
    <span aria-hidden className="relative h-0.5 min-w-0 flex-1 overflow-hidden rounded-full bg-stage-line">
      {phase === "dialling" ? <span className="stage-dash absolute inset-y-0 -left-3 right-0" /> : null}
      {solid ? (
        <span className={`stage-in absolute inset-0 ${phase === "ended" ? "bg-stage-live" : "bg-stage-live/50"}`} />
      ) : null}
    </span>
  );
}

function PhoneMark({ phase, icon }: { phase: CallPhase; icon?: LucideIcon }) {
  const trouble = phase === "missed" || phase === "error";
  const Icon = icon ?? (phase === "limit" ? Hourglass : trouble ? PhoneOff : Smartphone);
  const tone = trouble
    ? "border-stage-warn/60 text-stage-warn"
    : phase === "limit"
      ? "border-stage-warn/60 text-stage-warn"
      : phase === "dialling" || phase === "preparing"
        ? "border-stage-line text-stage-faint"
        : "border-stage-live/60 text-stage-live";
  return (
    <span aria-hidden className="relative grid h-14 w-14 place-items-center">
      {phase === "ringing" ? (
        <>
          <span className="stage-ripple absolute inset-0 rounded-full border border-stage-live" />
          <span className="stage-ripple absolute inset-0 rounded-full border border-stage-live [animation-delay:800ms]" />
        </>
      ) : null}
      <span className={`relative grid h-12 w-12 place-items-center rounded-full border bg-stage-raised ${tone}`}>
        <Icon className={`h-5 w-5 ${phase === "ringing" ? "stage-buzz" : ""}`} />
        {phase === "ended" ? (
          <span className="absolute -bottom-0.5 -right-0.5 grid h-5 w-5 place-items-center rounded-full bg-stage-live text-stage">
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

/** A button on the stage. Light on dark, so the stage's one action reads as the action. */
export const STAGE_BUTTON =
  "press inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-stage-ink px-4 text-sm font-semibold text-stage transition-colors duration-(--duration-fast) [&:not(:disabled)]:hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stage-live focus-visible:ring-offset-2 focus-visible:ring-offset-stage";
export const STAGE_BUTTON_QUIET =
  "press inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-stage-line px-4 text-sm font-medium text-stage-ink transition-colors duration-(--duration-fast) [&:not(:disabled)]:hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stage-live focus-visible:ring-offset-2 focus-visible:ring-offset-stage";
