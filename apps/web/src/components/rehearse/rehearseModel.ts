import type { RehearsedAction, ReplyFlag } from "@/lib/api/rehearse";

/** One line of a rehearsal: what the owner typed, or what the agent answered and did. */
export type RehearsalTurn =
  | { from: "you"; text: string }
  | { from: "agent"; text: string; actions: RehearsedAction[]; flags: ReplyFlag[]; said: string };

/** The longest request the holder's Pip ask takes (`campaign_script_ask` instruction). */
export const FIX_MAX = 1000;

const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

/**
 * "Fix this in the script": the owner's request to Pip, in plain words, for the reply a
 * check flagged. Pip maps it to the step that says it and changes only that (W3.7).
 */
export function fixInstruction(flag: ReplyFlag, said: string, reply: string): string {
  const text =
    `On a practice chat the caller said "${clip(said.trim(), 200)}" and the agent answered ` +
    `"${clip(reply.trim(), 400)}". ${flag.reason} Change the part of the script that makes it ` +
    "answer like this, and nothing else.";
  return clip(text, FIX_MAX);
}
