/**
 * A wall-clock time as an owner says it: "9am", "1:30pm", "12am". The calling window reads
 * "9am to 9pm" on every screen (L3-23); a 24-hour "09:00–21:00" or a "9:00 am" beside it was
 * a second style for one fact. Every wall-clock time on a screen is worded here. An INSTANT
 * (a moment, shown in IST) is `formatIST` in `components/ui`, a different question.
 */
function words(hour: number, minute: number): string {
  const suffix = hour < 12 ? "am" : "pm";
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return minute === 0 ? `${twelve}${suffix}` : `${twelve}:${String(minute).padStart(2, "0")}${suffix}`;
}

/** "09:00" → "9am", "13:30" → "1:30pm". Returns the input unchanged when it is not a time. */
export function clockWords(value: string): string {
  const match = /^(\d{1,2}):(\d{2})/.exec(value.trim());
  if (!match) return value;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) return value;
  return words(hour, minute);
}

/** An hour of the day, 0-23: `9` → "9am", `18` → "6pm". */
export function hourWords(hour: number): string {
  return words(hour, 0);
}

/** Minutes since midnight: `570` → "9:30am", `600` → "10am". */
export function minuteOfDayWords(minutes: number): string {
  return words(Math.floor(minutes / 60), minutes % 60);
}

/** "9am to 9pm" from two "HH:MM" values. */
export function clockRange(start: string, end: string): string {
  return `${clockWords(start)} to ${clockWords(end)}`;
}
