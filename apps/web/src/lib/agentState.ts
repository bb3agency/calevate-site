/**
 * WHAT AN AGENT'S STATE IS, decided once for the whole console section.
 *
 * The roster, the detail screen, the campaign picker and the Leads table's dial button all
 * have to answer the same question — "is this thing answering calls right now?" — and four
 * answers to one question is exactly the drift CLAUDE.md's one-way-per-problem rule is
 * about. It was already computed twice before this file existed: `liveState()` on the
 * agents screen and a byte-identical `canDial()` on the Leads table, agreeing only because
 * somebody kept them in step. Both callers moved here in the same change.
 *
 * The test is the SERVER's, in the same order the server applies it
 * (`agents/prompts.py::_is_live`): `published` first, because nothing else matters until
 * it is true — an agent that does not exist on the calling system cannot ring, whatever
 * its status column says.
 *
 * ## `status` is a bare `string` on the wire and this module treats it as one
 *
 * `AgentOut.status` carries no enum in the OpenAPI document, so every value reaching the
 * tables below is a wire string and is read through `lookup` (src/lib/lookup.ts). The
 * fail direction is deliberate and is NOT uniform:
 *
 * - An unrecognised status lands in `inactive`, never in `active`. "This agent is
 *   answering your calls right now" is the one claim on this screen that must never be
 *   made from a guess.
 * - Its own word is still printed, so a status this build has never seen shows up as
 *   itself rather than vanishing — an owner can quote it to their account manager.
 */

import type { Agent, AgentLanguage, LifecycleMove } from "@/lib/api/agents";
import { lookup } from "@/lib/lookup";

/**
 * The status a retired agent carries.
 *
 * Named once because three screens ask about it and because the column is a bare string:
 * if the API's word for "retired" is ever something else, this constant is the single
 * edit. `AGENT_STATUSES` on the server is `("draft", "live", "paused", "archived")` and
 * `archived` is a state agents really reach (migration e4b90d27c1f6), so the archive
 * section renders whenever the server sends one — and only then, because a client with
 * nothing retired should not be reading a permanently empty heading.
 */
export const ARCHIVED_STATUS = "archived";

/** The three buckets the roster groups by, in the order an owner cares about them. */
export type AgentGroupKey = "active" | "inactive" | "archived";

/**
 * Which bucket an agent belongs in — the ONE derivation.
 *
 * Note what "active" does not mean: it is not `status === "live"`. An agent switched to
 * live that has never been built on the calling system is a different wait from one built
 * and left switched off, and neither is answering a phone.
 */
export function agentGroup(agent: Agent): AgentGroupKey {
  if (agent.status === ARCHIVED_STATUS) return "archived";
  return agent.published && agent.status === "live" ? "active" : "inactive";
}

/** Is this agent picking up or dialling RIGHT NOW? The at-a-glance question. */
export function isAnsweringNow(agent: Agent): boolean {
  return agentGroup(agent) === "active";
}

/**
 * Can this agent be put on an outbound campaign?
 *
 * Live-and-published AND pointed outward. An inbound-only receptionist is a perfectly
 * healthy agent that cannot dial, and offering it as a campaign's caller produces an
 * `agent_not_live`-shaped refusal at launch instead of at the point of choosing.
 */
export function canDialOut(agent: Agent): boolean {
  return isAnsweringNow(agent) && agent.direction !== "inbound";
}

/**
 * Direction in the owner's terms. "Inbound" and "outbound" are OUR nouns; a clinic owner
 * thinks "does it pick up, or does it ring people?".
 */
export const DIRECTION_COPY: Record<string, { label: string; hint: string }> = {
  inbound: {
    label: "Answers calls",
    hint: "Picks up when someone rings your number.",
  },
  outbound: {
    label: "Makes calls",
    hint: "Dials your customers for campaigns and follow-ups.",
  },
  both: {
    label: "Answers and makes calls",
    hint: "Picks up incoming calls and dials out for campaigns.",
  },
};

/**
 * The three languages that ship, in the words a client reads.
 *
 * `Record<AgentLanguage, string>` over the GENERATED union, not `Record<string, string>`:
 * a fourth language on the server is then a type error here rather than an unnamed option
 * in a picker. An agent whose stored `language_primary` is not one of these — a value
 * retired since it was written — still falls back to its own code at every call site,
 * because `AgentOut.language_primary` remains a bare string on the wire.
 */
export const LANGUAGE_NAMES: Record<AgentLanguage, string> = {
  "te-IN": "Telugu",
  "hi-IN": "Hindi",
  "en-IN": "English (India)",
};

export const STATUS_COPY: Record<string, { label: string; hint: string }> = {
  draft: { label: "Draft", hint: "Still being put together by your account manager." },
  live: { label: "Switched on", hint: "Cleared to take calls." },
  paused: { label: "Paused", hint: "Switched off for now, on purpose." },
  [ARCHIVED_STATUS]: {
    label: "Archived",
    hint: "Retired. It takes no calls and makes none, and its call history is kept.",
  },
};

/** A wire enum as a readable phrase, for the fallback arm every table above needs. */
export function humanise(value: string): string {
  return value.replace(/_/g, " ");
}

/**
 * WHICH LIFECYCLE MOVES ARE OFFERED from a given status.
 *
 * A MIRROR of `apps/api/agents/lifecycle.py::AGENT_MOVERS`, and it says so rather
 * than pretending to be the authority. The server is the authority: it holds the table, it
 * takes the row lock, and it refuses an illegal move with a problem+json the screen
 * renders. What this decides is only which BUTTONS are worth showing — offering "Switch
 * on" beside an archived agent is a click that can only be refused, which this repo treats
 * as worse than no button at all.
 *
 * A second copy of a rule is a real cost and is accepted here for a reason worth writing
 * down: the alternative is a round trip per agent to be told what may be pressed, and the
 * table is four lines that change roughly never. If the API ever returns the allowed moves
 * on `AgentOut`, delete this and read that — it is strictly better, because then there is
 * one copy again.
 *
 * WHAT MAKES THE COPY SAFE IS NOT THIS COMMENT. `tests/agentTransitionsMirror.test.ts`
 * reads `apps/api/agents/lifecycle.py::AGENT_MOVERS` and fails when this table stops
 * matching it, in either direction — a move the server accepts and this omits is a control
 * the client cannot reach with nothing on screen to explain it, and a move this offers and
 * the server has dropped is a button that can only ever be refused. It compares against
 * the MOVER table rather than `AGENT_TRANSITIONS` because `deactivate` and `restore` both
 * end at `paused`, so the target state alone cannot say which button owns an edge.
 *
 * It FAILS CLOSED: a status this build has never seen offers no moves at all, rather than
 * guessing that an unknown state can be switched on.
 */
/*
 * The four moves are `LifecycleMove` in `lib/api/agents.ts`, where the request is made,
 * and are NOT re-declared here. A second union of the same four strings is the same defect
 * this file exists to remove one level up: both were correct, and the second one is where
 * the drift starts. Anything a screen needs is imported from the one that names the paths.
 */
const MOVES_BY_STATUS: Record<string, readonly LifecycleMove[]> = {
  draft: ["activate", "archive"],
  /* NO `archive` ON A LIVE AGENT, and the omission is the server's (D-527): deleting is
     refused with `agent_is_live` until the agent is switched off, because the console puts
     Delete on every row of the roster and one click there may not end a working phone
     line. The roster still SHOWS the control on a live agent — pressing it explains the
     one thing to do first and offers Switch off — which is not the same as offering a
     move that would 409. */
  live: ["deactivate"],
  paused: ["activate", "archive"],
  [ARCHIVED_STATUS]: ["restore"],
};

export function movesFor(status: string): readonly LifecycleMove[] {
  return lookup(MOVES_BY_STATUS, status) ?? [];
}

/**
 * May a campaign name this agent?
 *
 * EVERY state except archived, and that asymmetry is the server's rather than a guess:
 * `lifecycle.ASSIGNABLE_STATUSES` is `AGENT_TRANSITIONS` minus `archived`. A client
 * assembles a campaign draft — list, template, number, calling window — while the agent it
 * will use is still being written, and `campaigns/service.launch_blockers` refuses the
 * LAUNCH with `agent_not_live` until it is published. Archived is different in kind: there
 * is no state of the world in which that campaign becomes launchable, so binding one is a
 * dead end the client cannot diagnose.
 *
 * So a picker offers a draft agent (with a note that it cannot dial YET) and never offers
 * an archived one.
 */
export function isAssignable(agent: Agent): boolean {
  return agent.status !== ARCHIVED_STATUS;
}
