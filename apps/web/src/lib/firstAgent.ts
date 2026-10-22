/**
 * THE FIRST AGENT, PIECE BY PIECE (D-854) — what the "Build your first agent" screen counts.
 *
 * Every piece is RECOMPUTED from rows the server already holds: the agent itself, the
 * business's pinned facts and the agent's calls. There is no stored "game state", so a person
 * who leaves half way, builds a piece by hand on another screen, or asks Pip from the dock
 * comes back to a card that says where they really are.
 *
 * "Account created" is always done: the meter starts above zero on purpose (endowed
 * progress), because the account is real work the owner has already finished.
 */

import type { Agent } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";

/** The greeting the card counts as done: short, and ending on a question that hands the turn
 *  to the caller. Pinned to `apps/api/copilot/screen_guides.FIRST_GREETING_MAX_CHARS`. */
export const GREETING_MAX_CHARS = 120;

/** How many questions callers ask most the card asks for. */
export const QUESTIONS_WANTED = 3;

export type PieceId =
  | "account"
  | "job"
  | "name"
  | "voice"
  | "greeting"
  | "questions"
  | "notes"
  | "ready"
  | "call";

export interface Piece {
  id: PieceId;
  label: string;
  done: boolean;
}

export interface PinnedAnswer {
  question: string;
  answer: string;
}

export interface FirstAgentState {
  agent: Agent | null;
  /** The business's pinned facts that answer a caller's question, in order. */
  answers: readonly PinnedAnswer[];
  /** This agent's calls, newest first, or undefined while unread. */
  calls: readonly CallSummary[] | undefined;
}

/** Characters as a person counts them: Telugu and emoji are not two units each. */
export function charCount(text: string): number {
  return Array.from(text).length;
}

export function greetingFits(line: string | null | undefined): boolean {
  const trimmed = (line ?? "").trim();
  return trimmed !== "" && charCount(trimmed) <= GREETING_MAX_CHARS && /[?？]$/.test(trimmed);
}

/**
 * THE agent this screen is building: the one named in the address, else the newest one on
 * the working roster. Ids are uuid v7, so the newest sorts last as text.
 */
export function firstAgentOf(agents: readonly Agent[] | undefined, named: string | null): Agent | null {
  const working = (agents ?? []).filter((agent) => agent.status !== "archived");
  if (named !== null) {
    const found = working.find((agent) => agent.id === named);
    if (found) return found;
  }
  return working.reduce<Agent | null>((newest, agent) => (newest === null || agent.id > newest.id ? agent : newest), null);
}

/** The pieces, in the order Pip asks for them. */
export function piecesOf({ agent, answers, calls }: FirstAgentState): Piece[] {
  const has = agent !== null;
  return [
    { id: "account", label: "Account created", done: true },
    { id: "job", label: "Its job", done: has },
    { id: "name", label: "Its name", done: has && agent.name.trim() !== "" },
    { id: "voice", label: "Its voice", done: has && Boolean(agent.engine_voice_id) },
    { id: "greeting", label: "How it greets callers", done: has && greetingFits(agent.script_opening_line) },
    { id: "questions", label: "What callers ask most", done: answers.length >= QUESTIONS_WANTED },
    { id: "notes", label: "What it notes down", done: has && agent.extraction_fields.length > 0 },
    { id: "ready", label: "Ready to try", done: has && agent.published },
    { id: "call", label: "Its first call", done: has && (calls?.length ?? 0) > 0 },
  ];
}

/** The first piece still to do, or null when every piece is done. */
export function nextPiece(pieces: readonly Piece[]): Piece | null {
  return pieces.find((piece) => !piece.done) ?? null;
}

/** The job, in the owner's words, from the agent's direction. */
export function jobOf(agent: Agent): string {
  if (agent.direction === "inbound") return "Answers your calls";
  if (agent.direction === "outbound") return "Calls your leads";
  return "Answers your calls and calls your leads";
}

/**
 * The one-tap answers for the piece Pip is on. They are the person's words, sent as their
 * message: nothing here decides anything on its own.
 */
export function quickRepliesFor(next: PieceId | null): readonly string[] {
  switch (next) {
    case "job":
      return ["Answer my calls", "Call my leads", "Both"];
    case "name":
      return ["Suggest a name"];
    case "voice":
      return ["Show me the voices", "Pick one for me"];
    case "greeting":
      return ["Keep this greeting", "Make it shorter", "Make it warmer"];
    case "questions":
      return ["Help me think of them"];
    case "notes":
      return ["That's everything", "Add one more"];
    case "ready":
    case "call":
      return ["How do I hear it?"];
    default:
      return [];
  }
}

/**
 * Pip's first line in an empty chat. On a fresh start it asks the first question itself, so
 * the first tap costs no model call; on a return it says what is next.
 */
export function introFor(next: Piece | null, agentName: string | null): string {
  if (next === null) return `${agentName ?? "Your agent"} is built. Ask me to change anything about it.`;
  if (next.id === "job") {
    return "Let's build your first agent together. First, what should it do: answer your calls, call your leads, or both?";
  }
  if (next.id === "ready" || next.id === "call") {
    return `${agentName ?? "Your agent"} is ready to hear. Type your number on the card and press Call me.`;
  }
  return `Welcome back. Next for ${agentName ?? "your agent"}: ${next.label.toLowerCase()}. Tap an answer below, or tell me.`;
}

/** Pip's one-line hint under the meter, for the piece it is on. */
export function hintFor(next: PieceId | null): string {
  switch (next) {
    case "job":
      return "Pick what it does first. Everything else follows from that.";
    case "name":
      return "Callers never hear its name. It is how you find it later.";
    case "voice":
      return "Press Hear it on the card to listen before you choose.";
    case "greeting":
      return `Short greetings work best: under ${GREETING_MAX_CHARS} characters, ending with a question.`;
    case "questions":
      return "Answer in your own words. Your agent says them the same way every time.";
    case "notes":
      return "These become the columns of your leads list.";
    case "ready":
    case "call":
      return "Type your number on the card and it rings you.";
    default:
      return "Your agent is built. Change anything on its own page.";
  }
}
