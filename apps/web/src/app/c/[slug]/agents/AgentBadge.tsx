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

import { StatusPill } from "@/components/console/statusPill";
import type { NoticeTone } from "@/components/ui";
import { humanise, isDeleted } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";
import { useTrialPanel } from "@/lib/api/trialCalls";

export interface LiveState {
  /** The badge word. */
  label: string;
  /** The shared tone, drawn by `StatusPill`. */
  tone: NoticeTone;
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
 * Tones: ok for live (the console's one "this is working" colour), neutral for the waits,
 * and warn for paused, the one state a client may want to act on.
 *
 * On a free trial a ready agent is as on as it can be: the trial's switch gets it ready
 * for test calls from the shared trial number (D-853), so it reads as on, not as waiting.
 */
export function liveState(agent: Agent, onTrial = false): LiveState {
  if (isDeleted(agent)) {
    return {
      // "Deleted", the console's word for this state since D-527 — the badge, the section
      // heading and the button that produced it have to be one word or an owner cannot
      // connect them. The detail keeps the sentence that makes the word honest.
      label: "Deleted",
      tone: "neutral",
      detail:
        "It takes no calls and makes none. The calls it already handled are still in your call log.",
    };
  }
  if (!agent.published) {
    return {
      label: "Being set up",
      tone: "neutral",
      detail:
        "Not on the calling system yet, so it cannot take or make calls, or be tried in the chat. Get it ready to try it, or switch it on.",
    };
  }
  /* Published and switched off: the server's "Ready, not taking calls" (D-838). Readied to
     try or switched off after working, it is one fact for the owner: it can be tried in the
     chat, and it answers no calls and makes none. */
  if (agent.status === "paused" && onTrial) {
    return {
      label: "On for test calls",
      tone: "ok",
      detail:
        "Ready for test calls from our shared trial number. It answers your own number and calls your leads once your account goes live.",
    };
  }
  if (agent.status === "paused") {
    return {
      label: "Ready, not taking calls",
      tone: "warn",
      detail: "You can try it in the chat. It answers no calls and makes none until you switch it on.",
    };
  }
  if (agent.status === "live") {
    return {
      label: "Live",
      tone: "ok",
      detail: "On the calling system and working right now.",
    };
  }
  /* Fails VISIBLE and claims nothing: a status this build has never seen keeps its own
     word rather than being described as working, and `agentGroup` has already kept it out
     of the roster's "Working right now" section for the same reason. */
  return {
    label: humanise(agent.status),
    tone: "neutral",
    detail:
      "We cannot tell you from here whether this agent is taking calls. Our team can.",
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

/** The voice quality, beside the live state. Renders nothing when the API sent none. */
export function VoiceTierBadge({ agent }: { agent: Agent }) {
  const label = voiceTierLabel(agent);
  if (label === null) return null;
  return (
    // A tag, not a state, so plain text; "voice" is written out because "Studio" alone
    // beside "Live" would read as another state.
    <span className="shrink-0 whitespace-nowrap text-meta text-ink-muted">{label} voice</span>
  );
}

/** The badge, wherever an agent is named. */
export function LiveBadge({ agent }: { agent: Agent }) {
  const session = useClientSession();
  // One cached read per account, asked only where the answer changes the words.
  const trial = useTrialPanel(session, agent.published && agent.status === "paused");
  const live = liveState(agent, trial.data?.on_trial === true);
  return <StatusPill tone={live.tone}>{live.label}</StatusPill>;
}
