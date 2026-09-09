"use client";

import { Bot, User } from "lucide-react";

/**
 * Who said it, and how the turn is dressed.
 *
 * `speaker` is a two-value union in the generated types, but it is a string the SERVER
 * chose at runtime and a union is a claim this build makes, not one the server is bound
 * by — so it is read with `lookup` and falls back VISIBLY: an unrecognised speaker keeps
 * its turn on screen with its own name printed, because a transcript line we cannot
 * attribute is the last thing that should silently vanish.
 */
export const SPEAKERS: Record<string, { label: string; icon: typeof Bot; medallion: string }> = {
  agent: { label: "Agent", icon: Bot, medallion: "bg-brand-soft text-brand-strong" },
  caller: { label: "Caller", icon: User, medallion: "bg-black/5 text-ink-muted dark:bg-white/10" },
};
