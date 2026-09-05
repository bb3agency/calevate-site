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
import { ARCHIVED_STATUS, humanise } from "@/lib/agentState";
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
  if (agent.status === ARCHIVED_STATUS) {
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
