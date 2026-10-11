import { sentenceCase } from "@/components/admin/kit";
import type { HostedVoice } from "@/lib/api/opsHostedVoices";

/**
 * Filtering the voice lists, in the browser. The platform list is one unpaged answer of a few
 * hundred rows (list-voices.md:346, list-byok-voices.md), already in memory for the screen,
 * so narrowing it here is instant and needs no second read.
 */

export type TierFilter = "all" | "clear" | "studio";
/** `active` (the default) is everything but archived: archiving is how a voice is put away. */
export type StateFilter = "active" | "any" | "offered" | "not_offered" | "archived";
export type PreviewFilter = "any" | "with" | "without";

export interface VoiceFilters {
  query: string;
  tier: TierFilter;
  /** An `accent_label` (or the raw tag), or "" for any. */
  accent: string;
  /** A provider gender word, or "" for any. */
  gender: string;
  state: StateFilter;
  preview: PreviewFilter;
}

export const NO_FILTERS: VoiceFilters = {
  query: "",
  tier: "all",
  accent: "",
  gender: "",
  state: "active",
  preview: "any",
};

export function accentOf(voice: HostedVoice): string | null {
  return voice.accent_label ?? voice.accent ?? null;
}

/** The distinct values a filter can offer, sorted, from the voices on screen. */
export function choices(voices: HostedVoice[], pick: (voice: HostedVoice) => string | null): string[] {
  const seen = new Set<string>();
  for (const voice of voices) {
    const value = pick(voice);
    if (value) seen.add(value);
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

function matchesQuery(voice: HostedVoice, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [voice.label, voice.vendor_label, voice.description ?? "", accentOf(voice) ?? ""].some(
    (text) => text.toLowerCase().includes(q),
  );
}

export function matches(voice: HostedVoice, f: VoiceFilters): boolean {
  if (!matchesQuery(voice, f.query)) return false;
  if (f.tier !== "all" && voice.rung !== f.tier) return false;
  if (f.accent && accentOf(voice) !== f.accent) return false;
  if (f.gender && voice.gender !== f.gender) return false;
  if (f.state === "active" && voice.state === "archived") return false;
  if (f.state === "offered" && !voice.offered) return false;
  if (f.state === "not_offered" && (voice.offered || voice.state === "archived")) return false;
  if (f.state === "archived" && voice.state !== "archived") return false;
  if (f.preview === "with" && !voice.preview_available) return false;
  if (f.preview === "without" && voice.preview_available) return false;
  return true;
}

export function applyFilters(voices: HostedVoice[], f: VoiceFilters): HostedVoice[] {
  return voices.filter((voice) => matches(voice, f));
}

export function isFiltered(f: VoiceFilters): boolean {
  return (Object.keys(NO_FILTERS) as (keyof VoiceFilters)[]).some((key) => f[key] !== NO_FILTERS[key]);
}

/**
 * Find one voice by the provider's id an operator pasted, or by our own `<source>:<id>`.
 * Only the list we hold is searched: a voice the platform did not list is not forced in.
 */
export function findByVoiceId(voices: HostedVoice[], pasted: string): HostedVoice | null {
  const id = pasted.trim();
  if (!id) return null;
  return voices.find((voice) => voice.vendor_id === id || voice.voice_id === id) ?? null;
}

/** "Indian English accent · Feminine" — the facts a row prints under the name. */
export function metaLine(voice: HostedVoice): string {
  const parts: string[] = [];
  const accent = accentOf(voice);
  if (accent) parts.push(voice.source === "engine" ? `${accent} accent` : accent);
  if (voice.gender) parts.push(sentenceCase(voice.gender));
  return parts.join(" · ");
}
