"use client";

import type { CSSProperties, ReactNode } from "react";
import { Check, Clock, Hourglass, PhoneOff, Smartphone, type LucideIcon } from "lucide-react";

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

export interface BuildRow {
  step: FirstRunBuildStep["step"];
  title: string;
  /** While worked on: what it is doing ("Choosing a voice for Telugu"). */
  doing: string;
  /** Once done: what really happened ("Lakshmi · Studio. …"), read to a screen reader. */
  result?: string;
  /** Once done, the few words the picture can carry (the voice's name and band). */
  tag?: string;
  state: RowState;
}

const ROW_WORDS: Readonly<Record<RowState, string>> = {
  waiting: "Waiting",
  working: "Working on it",
  done: "Done",
  warn: "Needs you",
  failed: "Stopped",
};

/** The voice's bars: their height while speaking and the share of it they settle to. */
const VOICE_BARS = [
  { h: 18, settle: 0.45 },
  { h: 32, settle: 0.4 },
  { h: 24, settle: 0.5 },
  { h: 40, settle: 0.35 },
  { h: 28, settle: 0.45 },
  { h: 36, settle: 0.4 },
  { h: 20, settle: 0.5 },
] as const;

/** The script page's lines, by width. */
const SCRIPT_LINES = [40, 34, 40, 26, 36] as const;

/**
 * THE AGENT BEING PUT TOGETHER (founder, 23 Oct 2026: a picture, not a checklist). The agent
 * sits in the middle; each of its four parts comes to it when the server says that step is
 * done: the voice as bars that speak and settle, the script as a page whose lines fill, the
 * greeting as a bubble, the AI notice as a badge stamped on. The part being made breathes
 * in outline; parts not reached are faint outlines. One caption says the same in words, and a
 * hidden list gives a screen reader every step.
 *
 * Transform and opacity only, in one `viewBox`, so it scales to the panel at any width.
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
  const stateOf = (step: BuildRow["step"]): RowState => rows.find((row) => row.step === step)?.state ?? "waiting";
  const voice = rows.find((row) => row.step === "voice");
  const initial = name ? (Array.from(name.trim())[0]?.toUpperCase() ?? null) : null;
  const caption = failed
    ? `Stopped before it finished${working ? ` · ${working.title}` : ""}`
    : built
      ? "Ready to ring you"
      : `${done} of ${rows.length}${working ? ` · ${working.doing}` : ""}`;

  return (
    <Stage label={built ? `${name ?? "Your agent"} is built` : "Your agent being built"}>
      {/* The step's own heading says "Building your agent"; the stage names the agent once it
          has a name, which arrives with its voice. */}
      {name ? <p className="truncate text-heading text-stage-ink">{built ? name : `Building ${name}`}</p> : null}

      <svg
        viewBox="0 0 360 190"
        className="mx-auto mt-2 block h-auto w-full max-w-[460px]"
        role="img"
        aria-label={built ? "Your agent, with its voice, script, greeting and AI notice" : "Your agent being put together"}
      >
        <SceneLinks stateOf={stateOf} />
        <VoicePart state={stateOf("voice")} tag={voice?.state === "done" ? voice.tag : undefined} />
        <ScriptPart state={stateOf("script")} />
        <GreetingPart state={stateOf("greeting")} />
        <Avatar initial={initial} built={built} failed={failed} />
        <NoticePart state={stateOf("notice")} />
      </svg>

      {stateOf("greeting") === "done" && greeting ? (
        <figure className="stage-in relative mx-auto mt-2 max-w-md rounded-xl border border-stage-line bg-stage-raised px-4 py-3">
          <span
            aria-hidden
            className="absolute -top-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 border-l border-t border-stage-line bg-stage-raised"
          />
          <figcaption className="text-meta text-stage-faint">It opens every call with</figcaption>
          <blockquote lang={greetingLang} className="mt-1 line-clamp-3 break-words text-[15px] leading-relaxed text-stage-ink">
            “{greeting}”
          </blockquote>
        </figure>
      ) : null}
      <p aria-live="polite" className="mt-3 text-center text-meta text-stage-muted">
        {working && !failed ? <span className="stage-shimmer">{caption}</span> : caption}
      </p>
      <ol className="sr-only">
        {rows.map((row) => (
          <li key={row.step}>
            {row.title}: {ROW_WORDS[row.state]}
            {row.state === "working" ? `, ${row.doing}` : ""}
            {row.result && (row.state === "done" || row.state === "warn") ? `. ${row.result}` : ""}
          </li>
        ))}
      </ol>

      {footer ? <div className="mt-5">{footer}</div> : null}
    </Stage>
  );
}

/** A part's tone: lit when done, amber when it needs the owner, red when the build stopped
 *  on it, breathing while it is made, faint before. */
function toneOf(state: RowState): { stroke: string; fill: string; className: string } {
  switch (state) {
    case "done":
      return { stroke: "var(--stage-live)", fill: "rgb(74 222 128 / 0.12)", className: "stage-in" };
    case "warn":
      return { stroke: "var(--stage-warn)", fill: "rgb(251 191 36 / 0.1)", className: "stage-in" };
    case "failed":
      return { stroke: "var(--stage-danger)", fill: "transparent", className: "" };
    case "working":
      return { stroke: "var(--stage-live)", fill: "transparent", className: "stage-breathe" };
    default:
      return { stroke: "var(--stage-line)", fill: "transparent", className: "" };
  }
}

/** The faint lines that join each part to the agent, lit as the part arrives. */
function SceneLinks({ stateOf }: { stateOf: (step: BuildRow["step"]) => RowState }) {
  const lit = (step: BuildRow["step"]) => (stateOf(step) === "done" ? "var(--stage-live)" : "var(--stage-line)");
  const line = (step: BuildRow["step"], d: string) => (
    <path
      d={d}
      fill="none"
      stroke={lit(step)}
      strokeWidth="1.5"
      strokeDasharray="2 4"
      strokeLinecap="round"
      className="transition-[stroke] duration-500"
    />
  );
  return (
    <g aria-hidden>
      {line("voice", "M118 92 H140")}
      {line("script", "M220 92 H244")}
      {line("greeting", "M152 52 L164 62")}
    </g>
  );
}

function Avatar({ initial, built, failed }: { initial: string | null; built: boolean; failed: boolean }) {
  const ring = failed ? "var(--stage-warn)" : "var(--stage-live)";
  return (
    <g aria-hidden>
      <circle cx="180" cy="92" r="44" fill="none" stroke="var(--stage-line)" strokeWidth="2" />
      {built || failed ? (
        <circle key={String(built)} cx="180" cy="92" r="44" fill="none" stroke={ring} strokeWidth="2.5" className="stage-in" />
      ) : (
        <circle
          cx="180"
          cy="92"
          r="44"
          fill="none"
          stroke={ring}
          strokeWidth="2.5"
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray="0.2 0.8"
          className="stage-spin"
        />
      )}
      <circle cx="180" cy="92" r="34" fill="var(--stage-raised)" />
      {initial ? (
        <text
          x="180"
          y="92"
          textAnchor="middle"
          dominantBaseline="central"
          fill="var(--stage-ink)"
          fontSize="28"
          fontWeight="600"
          className="stage-in"
        >
          {initial}
        </text>
      ) : (
        <g fill="var(--stage-faint)">
          <circle cx="180" cy="84" r="9" />
          <path d="M163 108c3-9 10-13 17-13s14 4 17 13z" />
        </g>
      )}
    </g>
  );
}

/** The voice: bars that rise as if speaking, then settle to a low line, with its name. */
function VoicePart({ state, tag }: { state: RowState; tag?: string }) {
  const tone = toneOf(state);
  const arrived = state === "done";
  return (
    <g aria-hidden>
      <rect x="44" y="64" width="72" height="56" rx="12" fill={tone.fill} stroke={tone.stroke} strokeWidth="1.5" className={tone.className} />
      {VOICE_BARS.map((bar, index) => (
        <rect
          key={index}
          x={53 + index * 8.5}
          y={92 - bar.h / 2}
          width="5"
          height={bar.h}
          rx="2.5"
          fill={arrived ? "var(--stage-live)" : "var(--stage-line)"}
          className={arrived ? "stage-settle" : ""}
          style={
            {
              "--settle": bar.settle,
              transform: `scaleY(${arrived ? bar.settle : 0.25})`,
              transformBox: "fill-box",
              transformOrigin: "center",
              animationDelay: `${index * 40}ms`,
            } as CSSProperties
          }
        />
      ))}
      {arrived && tag ? (
        <text x="80" y="140" textAnchor="middle" fill="var(--stage-muted)" fontSize="12.5" className="stage-in">
          {tag.length > 22 ? `${tag.slice(0, 21)}…` : tag}
        </text>
      ) : (
        <text x="80" y="140" textAnchor="middle" fill="var(--stage-faint)" fontSize="12.5">
          Voice
        </text>
      )}
    </g>
  );
}

/** The script: a page whose lines fill in, one after another. */
function ScriptPart({ state }: { state: RowState }) {
  const tone = toneOf(state);
  const arrived = state === "done";
  return (
    <g aria-hidden>
      <path
        d="M244 58h44l14 14v58a6 6 0 0 1-6 6h-52a6 6 0 0 1-6-6V64a6 6 0 0 1 6-6z"
        fill={arrived ? "var(--stage-raised)" : tone.fill}
        stroke={tone.stroke}
        strokeWidth="1.5"
        className={tone.className}
      />
      <path d="M288 58v14h14" fill="none" stroke={tone.stroke} strokeWidth="1.5" />
      {SCRIPT_LINES.map((width, index) => (
        <rect
          key={index}
          x="248"
          y={80 + index * 10}
          width={width}
          height="3.5"
          rx="1.75"
          fill={arrived ? "var(--stage-muted)" : "var(--stage-line)"}
          className={arrived ? "stage-line-in" : ""}
          style={{ transformBox: "fill-box", transformOrigin: "left center", animationDelay: `${index * 90}ms` }}
        />
      ))}
      <text x="272" y="152" textAnchor="middle" fill={arrived ? "var(--stage-muted)" : "var(--stage-faint)"} fontSize="12.5">
        Script
      </text>
    </g>
  );
}

/** The greeting: a speech bubble that pops out of the agent. */
function GreetingPart({ state }: { state: RowState }) {
  const tone = toneOf(state);
  const arrived = state === "done";
  return (
    <g aria-hidden className={arrived ? "stage-pop" : tone.className} style={{ transformBox: "fill-box", transformOrigin: "80% 100%" }}>
      <path
        d="M104 14h52a10 10 0 0 1 10 10v16a10 10 0 0 1-10 10h-4l-6 10-4-10h-38a10 10 0 0 1-10-10V24a10 10 0 0 1 10-10z"
        fill={arrived ? "rgb(74 222 128 / 0.14)" : tone.fill}
        stroke={tone.stroke}
        strokeWidth="1.5"
      />
      {[118, 130, 142].map((cx) => (
        <circle key={cx} cx={cx} cy="32" r="3" fill={arrived ? "var(--stage-live)" : "var(--stage-line)"} />
      ))}
      <text x="78" y="36" textAnchor="end" fill={arrived ? "var(--stage-muted)" : "var(--stage-faint)"} fontSize="12.5">
        Greeting
      </text>
    </g>
  );
}

/** The AI notice: a shield stamped onto the agent. */
function NoticePart({ state }: { state: RowState }) {
  const tone = toneOf(state);
  const arrived = state === "done";
  return (
    <g aria-hidden>
      <g className={arrived ? "stage-stamp" : tone.className} style={{ transformBox: "fill-box", transformOrigin: "center" }}>
        <path
          d="M212 104l13 5v9c0 8-6 13-13 16-7-3-13-8-13-16v-9z"
          fill={arrived ? "var(--stage-live)" : "var(--stage)"}
          stroke={arrived ? "var(--stage-live)" : tone.stroke}
          strokeWidth="1.5"
        />
        {arrived ? (
          <path d="M206.5 118.5l4 4 7-8" fill="none" stroke="var(--stage)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        ) : (
          <text x="212" y="122" textAnchor="middle" fill="var(--stage-faint)" fontSize="8" fontWeight="600">
            AI
          </text>
        )}
      </g>
      <text x="212" y="152" textAnchor="middle" fill={arrived ? "var(--stage-muted)" : "var(--stage-faint)"} fontSize="12.5">
        AI notice
      </text>
    </g>
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
