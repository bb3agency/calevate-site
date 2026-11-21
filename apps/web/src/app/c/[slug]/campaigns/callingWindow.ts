/**
 * The window every dial is held to (the dispatcher's 9am–9pm IST bound, `calevate_shared.
 * calling_window.DEFAULT_WINDOW`). A requested window may only narrow it. Every sentence and
 * time input that states the window reads it from here.
 */
import { clockWords } from "@/lib/clock";

export const PLATFORM_WINDOW = { start: "09:00", end: "21:00" } as const;

/** The platform window as words: `"9am to 9pm"`, or `"9am and 9pm"`, `"9am–9pm"`. */
export function windowWords(joiner: " to " | " and " | "–" = " to "): string {
  return `${clockWords(PLATFORM_WINDOW.start)}${joiner}${clockWords(PLATFORM_WINDOW.end)}`;
}

/** Minutes since midnight, India time: `"09:00"` → 540. */
export function minutesOf(hhmm: string): number {
  const [h = 0, m = 0] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

export function windowRefusal(start: string, end: string): string | null {
  if (start >= end) return "The hours must start before they end.";
  if (start < PLATFORM_WINDOW.start || end > PLATFORM_WINDOW.end) {
    return `Pick hours between ${windowWords(" and ")} IST.`;
  }
  return null;
}
