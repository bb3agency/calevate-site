/**
 * Who said it, in one word.
 *
 * `speaker` is a two-value union in the generated types, but it is a string the SERVER
 * chose at runtime, so it is read with `lookup` and falls back VISIBLY: an unrecognised
 * speaker keeps its turn on screen with its own name printed, because a transcript line we
 * cannot attribute is the last thing that should silently vanish.
 */
export const SPEAKERS: Record<string, { label: string }> = {
  agent: { label: "Agent" },
  caller: { label: "Caller" },
};
