"use client";

import type { CSSProperties, ReactNode } from "react";
import { Check, Clock, Hourglass, PhoneOff, Smartphone, type LucideIcon } from "lucide-react";

import { formatDuration } from "@/components/ui";
import type { FirstRunBuildStep } from "@/lib/api/firstRun";

/**
 * THE LIVE PANEL (founder, 23 Oct 2026): where the agent is built and where it calls you.
 *
 * Part of the page: the soft grey well the console uses for a read-only area, a hairline
 * border, the brand green as the accent, and the illustration drawn in white on it as the
 * focus. It was a dark panel first; the founder rejected that as a dark hero card that read
 * as Outpero's.
 *
 * Every frame is a state the server reported. The build's parts move when `GET /v1/first-run`
 * says a step is being worked on or is done; the call moves when the call's own row says
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
  { h: 14, settle: 0.5 },
  { h: 22, settle: 0.45 },
  { h: 16, settle: 0.55 },
  { h: 24, settle: 0.4 },
  { h: 18, settle: 0.5 },
  { h: 22, settle: 0.45 },
  { h: 12, settle: 0.6 },
] as const;

/** The script's lines inside its page, by width. */
const SCRIPT_LINES = [104, 86, 112, 66] as const;

/**
 * THE AGENT'S CARD, PUT TOGETHER (founder, 23 Oct 2026: a picture, ours, on a light page).
 *
 * The picture is the card the agent ends up with: its face and name at the top, its voice
 * under its name, its script and its greeting side by side below, and the AI notice as a seal
 * on the card's corner. Each piece is a slot drawn as a light grey outline until the server
 * says that step is done; then it fills with the soft green and settles into place. The slot
 * being made is outlined in green and breathes. When all four are in, the card's own border
 * turns green: the agent is whole.
 *
 * One composed object rather than a list of steps, so it reads as the agent and not as a
 * checklist; it is also the same anatomy as the "Your agent" card beside the steps, so the
 * picture and the card agree. One caption says the same in words, and a hidden list gives a
 * screen reader every step. Transform and opacity only, in one `viewBox`, so it scales to the
 * panel at any width.
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
      <svg
        viewBox="0 0 360 214"
        className="mx-auto block h-auto w-full max-w-[480px]"
        role="img"
        aria-label={
          built ? "Your agent's card, with its voice, script, greeting and AI notice" : "Your agent's card being put together"
        }
      >
        <rect
          x="8"
          y="14"
          width="344"
          height="192"
          rx="16"
          fill="var(--surface)"
          stroke={built ? "var(--brand)" : "var(--line)"}
          strokeWidth="1.5"
          className="transition-[stroke] duration-500"
        />
        <Face initial={initial} name={name} built={built} failed={failed} />
        <VoiceSlot state={stateOf("voice")} tag={voice?.state === "done" ? voice.tag : undefined} />
        <line x1="24" y1="108" x2="336" y2="108" stroke="var(--line)" strokeWidth="1" />
        <ScriptSlot state={stateOf("script")} />
        <GreetingSlot state={stateOf("greeting")} />
        <NoticeSeal state={stateOf("notice")} />
      </svg>

      {stateOf("greeting") === "done" && greeting ? (
        <figure className="stage-in mx-auto mt-3 max-w-md rounded-md border border-line bg-surface px-4 py-3">
          <figcaption className="text-meta text-ink-muted">It opens every call with</figcaption>
          <blockquote lang={greetingLang} className="mt-1 line-clamp-3 break-words text-[15px] leading-relaxed text-ink">
            “{greeting}”
          </blockquote>
        </figure>
      ) : null}
      <p aria-live="polite" className="mt-3 text-center text-meta text-ink-muted">
        {working && !failed ? <span className="text-shimmer">{caption}</span> : caption}
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
      {footer ? <div className="mt-4 flex justify-center">{footer}</div> : null}
    </Stage>
  );
}

/** A slot's look: a light grey outline before it is reached, green and breathing while it is
 *  made, soft green when done, amber when it needs the owner, red where the build stopped. */
function slotTone(state: RowState): { stroke: string; fill: string; ink: string; dash?: string; className: string } {
  switch (state) {
    case "done":
      return { stroke: "var(--brand)", fill: "var(--brand-soft)", ink: "var(--brand-strong)", className: "" };
    case "warn":
      return { stroke: "var(--warn)", fill: "var(--warn-soft)", ink: "var(--warn)", className: "" };
    case "failed":
      return { stroke: "var(--danger)", fill: "var(--surface)", ink: "var(--danger)", dash: "4 4", className: "" };
    case "working":
      return { stroke: "var(--brand)", fill: "var(--surface)", ink: "var(--brand)", dash: "5 4", className: "stage-breathe" };
    default:
      return { stroke: "var(--chart-neutral)", fill: "var(--surface)", ink: "var(--chart-neutral)", className: "" };
  }
}

/** The pieces of a slot that arrive with it: they rise a few pixels and fade in, once. */
function Arrival({ state, children }: { state: RowState; children: ReactNode }) {
  return <g className={state === "done" || state === "warn" ? "stage-arrive" : ""}>{children}</g>;
}

const LABEL = { fontSize: 11.5, fontWeight: 500 } as const;

function Face({
  initial,
  name,
  built,
  failed,
}: {
  initial: string | null;
  name: string | null;
  built: boolean;
  failed: boolean;
}) {
  return (
    <g aria-hidden>
      <circle cx="52" cy="60" r="28" fill="none" stroke="var(--line)" strokeWidth="2" />
      {built || failed ? (
        <circle
          key={String(built)}
          cx="52"
          cy="60"
          r="28"
          fill="none"
          stroke={failed ? "var(--warn)" : "var(--brand)"}
          strokeWidth="2.5"
          className="stage-in"
        />
      ) : (
        <circle
          cx="52"
          cy="60"
          r="28"
          fill="none"
          stroke="var(--brand)"
          strokeWidth="2.5"
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray="0.22 0.78"
          className="stage-spin"
        />
      )}
      <circle cx="52" cy="60" r="22" fill={initial ? "var(--brand-soft)" : "var(--surface-muted)"} />
      {initial ? (
        <text
          x="52"
          y="60"
          textAnchor="middle"
          dominantBaseline="central"
          fill="var(--brand-strong)"
          fontSize="20"
          fontWeight="600"
          className="stage-in"
        >
          {initial}
        </text>
      ) : (
        <g fill="var(--chart-neutral)">
          <circle cx="52" cy="54" r="7" />
          <path d="M39 74c2-7 7-10 13-10s11 3 13 10z" />
        </g>
      )}
      {name ? (
        <text x="92" y="50" fill="var(--text)" fontSize="17" fontWeight="600" className="stage-in">
          {name.length > 18 ? `${name.slice(0, 17)}…` : name}
        </text>
      ) : (
        <rect x="92" y="38" width="96" height="12" rx="6" fill="var(--surface-muted)" />
      )}
    </g>
  );
}

/** The voice, under the name: bars that rise as if speaking, then settle low, with its name. */
function VoiceSlot({ state, tag }: { state: RowState; tag?: string }) {
  const tone = slotTone(state);
  const arrived = state === "done";
  return (
    <g aria-hidden>
      <rect
        x="88"
        y="62"
        width="200"
        height="30"
        rx="15"
        fill={tone.fill}
        stroke={tone.stroke}
        strokeWidth="1.5"
        strokeDasharray={tone.dash}
        className={tone.className}
      />
      {VOICE_BARS.map((bar, index) => (
        <rect
          key={index}
          x={102 + index * 7}
          y={77 - bar.h / 2}
          width="3.5"
          height={bar.h}
          rx="1.75"
          fill={arrived ? "var(--brand)" : tone.ink}
          className={arrived ? "stage-settle" : ""}
          style={
            {
              "--settle": bar.settle,
              transform: `scaleY(${arrived ? bar.settle : 0.3})`,
              transformBox: "fill-box",
              transformOrigin: "center",
              animationDelay: `${index * 40}ms`,
            } as CSSProperties
          }
        />
      ))}
      <Arrival state={state}>
        <text x="158" y="81" fill={arrived ? "var(--brand-strong)" : "var(--text-faint)"} {...LABEL}>
          {arrived && tag ? (tag.length > 20 ? `${tag.slice(0, 19)}…` : tag) : "Voice"}
        </text>
      </Arrival>
    </g>
  );
}

/** The script: a page whose lines fill in, one after another. */
function ScriptSlot({ state }: { state: RowState }) {
  const tone = slotTone(state);
  const arrived = state === "done";
  return (
    <g aria-hidden>
      <rect
        x="24"
        y="120"
        width="150"
        height="74"
        rx="10"
        fill={tone.fill}
        stroke={tone.stroke}
        strokeWidth="1.5"
        strokeDasharray={tone.dash}
        className={tone.className}
      />
      <text x="36" y="138" fill={arrived ? "var(--brand-strong)" : "var(--text-faint)"} {...LABEL}>
        Script
      </text>
      {SCRIPT_LINES.map((width, index) => (
        <rect
          key={index}
          x="36"
          y={148 + index * 10}
          width={width}
          height="4"
          rx="2"
          fill={arrived ? "var(--brand)" : "var(--line)"}
          opacity={arrived ? 0.55 : 1}
          className={arrived ? "stage-line-in" : ""}
          style={{ transformBox: "fill-box", transformOrigin: "left center", animationDelay: `${index * 90}ms` }}
        />
      ))}
    </g>
  );
}

/** The greeting: a speech bubble beside the script that pops out once it is written. */
function GreetingSlot({ state }: { state: RowState }) {
  const tone = slotTone(state);
  const arrived = state === "done";
  return (
    <g
      aria-hidden
      className={arrived ? "stage-pop" : tone.className}
      style={{ transformBox: "fill-box", transformOrigin: "10% 100%" }}
    >
      <path
        d="M196 120h128a12 12 0 0 1 12 12v38a12 12 0 0 1-12 12H216l-14 12 2-12h-8a12 12 0 0 1-12-12v-38a12 12 0 0 1 12-12z"
        fill={tone.fill}
        stroke={tone.stroke}
        strokeWidth="1.5"
        strokeDasharray={tone.dash}
      />
      <text x="198" y="138" fill={arrived ? "var(--brand-strong)" : "var(--text-faint)"} {...LABEL}>
        Greeting
      </text>
      {[0, 1].map((index) => (
        <rect
          key={index}
          x="198"
          y={150 + index * 11}
          width={index === 0 ? 118 : 80}
          height="4"
          rx="2"
          fill={arrived ? "var(--brand)" : "var(--line)"}
          opacity={arrived ? 0.55 : 1}
        />
      ))}
    </g>
  );
}

/** The AI notice: a seal stamped on the card's corner. */
function NoticeSeal({ state }: { state: RowState }) {
  const tone = slotTone(state);
  const arrived = state === "done";
  return (
    <g aria-hidden>
      <g
        className={arrived ? "stage-stamp" : tone.className}
        style={{ transformBox: "fill-box", transformOrigin: "center" }}
      >
        <circle
          cx="316"
          cy="48"
          r="20"
          fill={arrived ? "var(--brand-strong)" : "var(--surface)"}
          stroke={arrived ? "var(--brand-strong)" : tone.stroke}
          strokeWidth="1.5"
          strokeDasharray={arrived ? undefined : tone.dash}
        />
        {arrived ? (
          <path
            d="M316 36l8 3v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10v-6z"
            fill="none"
            stroke="white"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
        ) : null}
        <text
          x="316"
          y={arrived ? 47 : 52}
          textAnchor="middle"
          fill={arrived ? "white" : "var(--text-faint)"}
          fontSize={arrived ? 7.5 : 11}
          fontWeight="700"
        >
          AI
        </text>
      </g>
    </g>
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
