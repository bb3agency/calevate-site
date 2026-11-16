/**
 * The window every dial is held to (the dispatcher's 9am–9pm IST bound). A requested
 * window may only narrow it.
 */
export const PLATFORM_WINDOW = { start: "09:00", end: "21:00" } as const;

export function windowRefusal(start: string, end: string): string | null {
  if (start >= end) return "The hours must start before they end.";
  if (start < PLATFORM_WINDOW.start || end > PLATFORM_WINDOW.end) {
    return "Pick hours between 9am and 9pm IST.";
  }
  return null;
}
