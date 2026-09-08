"use client";

/**
 * "Is this thing live?" as a sentence and as a badge — written once for the whole
 * section.
 *
 * The BUCKET an agent is in lives in `@/lib/agentState.ts`, which is pure derivation and
 * is also read by the campaign picker. What lives HERE is the console's words and colours for it,
 * because the roster and the detail screen must not describe one agent two ways: the
 * roster's badge and the detail screen's headline are the same call.
 *
 * It is a `.tsx` sibling rather than an export from `page.tsx` because a Next route module
 * may export only `default` and route-segment fields — a named export there fails the
 * production build with a message that names no line (D-196, tests/routeModuleExports).
 */

import { NOTICE_TONES } from "@/components/ui";
import { humanise, isDeleted } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";

export interface LiveState {
  /** The badge word. */
  label: string;
  /** Border/background/text classes — design tokens, never a fresh colour. */
  tone: string;
  /** The same fact as a sentence, for the screen that has room for one. */
  detail: string;
}

/**
 * The state, in the order the SERVER decides it (`agents/prompts.py::_is_live`).
 *
 * `published` is checked before `status` because nothing else matters until it is true:
 * an agent that does not exist on the calling system cannot ring, whatever its status
 * column says. An agent switched on but not yet built is a different wait from one built
 * and left switched off, and only we can tell them apart — so they get different words.
 *
 * Tones are the design tokens: brand-soft for live (the console's one "this is working"
 * colour) and the neutral surface for the waits. Paused borrows `NOTICE_TONES.warn`
 * rather than re-picking an amber — it is the one state a client may want to act on,
 * which is exactly what that tone already means everywhere else in this app.
 */
export function liveState(agent: Agent): LiveState {
  if (isDeleted(agent)) {
    return {
      // "Deleted", the console's word for this state since D-527 — the badge, the section
      // heading and the button that produced it have to be one word or an owner cannot
      // connect them. The detail keeps the sentence that makes the word honest.
      label: "Deleted",
      tone: "border-line bg-app text-ink-muted",
      detail:
        "It takes no calls and makes none. The calls it already handled are still in your call log.",
    };
  }
  if (!agent.published) {
    return {
      label: "Being set up",
      tone: "border-line bg-app text-ink-muted",
      detail:
        "Not on the calling system yet, so it cannot take or make calls. Your account manager finishes this before your first call.",
    };
  }
  if (agent.status === "paused") {
    return {
      label: "Paused",
      tone: NOTICE_TONES.warn,
      detail:
        "Switched off for now. No calls are being answered or made by this agent.",
    };
  }
  if (agent.status === "live") {
    return {
      label: "Live",
      tone: "border-brand-soft bg-brand-soft text-brand-strong",
      detail: "On the calling system and working right now.",
    };
  }
  /* Fails VISIBLE and claims nothing: a status this build has never seen keeps its own
     word rather than being described as working, and `agentGroup` has already kept it out
     of the roster's "Working right now" section for the same reason. */
  return {
    label: humanise(agent.status),
    tone: "border-line bg-app text-ink-muted",
    detail:
      "We cannot tell you from here whether this agent is taking calls. Your account manager can.",
  };
}

/**
 * WHICH VOICE QUALITY THIS AGENT SPEAKS IN — "Clear", "Studio" — or null.
 *
 * "Which of my agents is on Studio?" was unanswerable from this console: the roster row
 * carried no voice at all, and the only surface that names a tier is the detail screen, one
 * agent at a time. A tier is a PRICE (D-547: two tiers, two per-minute rates on every credit
 * lot), so it belongs where an owner scans.
 *
 * **THE NAME IS THE SERVER'S OR THERE IS NO BADGE.** It is read from the agent row and never
 * derived here — mapping a `provider` to "Studio" in TypeScript would be the second copy of
 * `billing/rates.VOICE_TIER_LABELS` that the marketing-provenance rule exists to prevent, and
 * the fallback available to such a copy is the vendor's own name, which is the one name a
 * client-facing surface may not print (founder, 7 Sep 2026).
 *
 * It is read DEFENSIVELY because `AgentOut` does not carry the field on every build: an API
 * that does not send it renders no badge, which is the honest answer, rather than a guess.
 * The same shape `AgentStats` is handled with two files over — a fact this screen does not
 * have is a fact it does not state.
 */
export function voiceTierLabel(agent: Agent): string | null {
  const label = (agent as { voice_tier_label?: unknown }).voice_tier_label;
  return typeof label === "string" && label.trim() !== "" ? label : null;
}

/** The voice-quality badge, beside the live one. Renders nothing when the API sent none. */
export function VoiceTierBadge({ agent }: { agent: Agent }) {
  const label = voiceTierLabel(agent);
  if (label === null) return null;
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-full border border-line bg-app px-3 py-1 text-xs font-semibold text-ink-muted"
      /* The visible word is a quality name on its own ("Studio"), which reads as a state
         next to "Live" unless it says what it is a name FOR. The accessible name carries
         the noun; the badge stays short enough to scan. */
      aria-label={`${label} voice`}
    >
      {label}
    </span>
  );
}

/** The badge, wherever an agent is named. */
export function LiveBadge({ agent }: { agent: Agent }) {
  const live = liveState(agent);
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-3 py-1 text-xs font-semibold ${live.tone}`}
    >
      {live.label}
    </span>
  );
}
