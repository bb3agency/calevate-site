import { formatClock } from "@/components/callAudioPlayer";
import type { CallDetail } from "@/lib/api/client";

/**
 * Key moments, shared by the call page (list, player markers, transcript bubbles) and the
 * lead page. One place decides how a moment's time is written and where a click lands.
 */
export type CallMoment = CallDetail["moments"][number];
export type MomentCategory = CallMoment["category"];

/**
 * How far before an approximate moment a click starts playing. The voice platform's turn
 * time is when the line was written down, not where it sits in the audio (founder,
 * 11 Oct 2026: show it as approximate and start a little early so the moment is heard).
 */
export const MOMENT_LEAD_IN_MS = 2_000;

export const CATEGORY_LABEL: Record<MomentCategory, string> = {
  details: "Details",
  attention: "Needs attention",
  buying: "Buying signal",
};

/**
 * The category's dot. Only "needs attention" carries a warning colour; buying signals use
 * the brand colour and plain details stay neutral, so the panel is not a rainbow.
 */
export const CATEGORY_DOT: Record<MomentCategory, string> = {
  details: "bg-ink-faint",
  attention: "bg-warn",
  buying: "bg-brand-strong dark:bg-brand-bright",
};

/** `0:21`, or `~0:21` when the time is the platform's rough position. */
export function turnClock(startMs: number, approximate: boolean): string {
  const clock = formatClock(startMs / 1000);
  return approximate ? `~${clock}` : clock;
}

/** The time as a screen reader should say it: "about 0:21" rather than "tilde 0:21". */
export function spokenClock(startMs: number, approximate: boolean): string {
  const clock = formatClock(startMs / 1000);
  return approximate ? `about ${clock}` : clock;
}

export function momentClock(moment: Pick<CallMoment, "at_ms" | "precision">): string {
  return turnClock(moment.at_ms, moment.precision === "approximate");
}

/** Where playback should start for a moment: a little early when its time is approximate. */
export function momentSeekMs(moment: Pick<CallMoment, "at_ms" | "precision">): number {
  return moment.precision === "approximate"
    ? Math.max(0, moment.at_ms - MOMENT_LEAD_IN_MS)
    : moment.at_ms;
}

/** Whole seconds for a `?t=` link into the call page. */
export function momentLinkSeconds(moment: Pick<CallMoment, "at_ms" | "precision">): number {
  return Math.floor(momentSeekMs(moment) / 1000);
}

/** The moments on each transcript turn, for the marker under that turn's bubble. */
export function momentsByTurn(moments: readonly CallMoment[]): Map<number, CallMoment[]> {
  const byTurn = new Map<number, CallMoment[]>();
  for (const moment of moments) {
    if (moment.turn_idx == null) continue;
    const list = byTurn.get(moment.turn_idx);
    if (list) list.push(moment);
    else byTurn.set(moment.turn_idx, [moment]);
  }
  return byTurn;
}

/**
 * A `?t=` value from the URL, or null. Non-numbers and negatives are ignored rather than
 * clamped: a malformed link should open the call at the start, not at a guessed time.
 */
export function parseStartAt(raw: string | null | undefined): number | null {
  if (raw == null || raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
}
