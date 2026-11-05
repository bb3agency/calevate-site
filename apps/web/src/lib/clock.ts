/**
 * A wall-clock "HH:MM" as an owner says it: "09:00" → "9am", "13:30" → "1:30pm". The calling
 * window reads "9am to 9pm" on every screen (L3-23); a 24-hour "09:00–21:00" beside it was a
 * second style for one fact. Returns the input unchanged when it is not a time.
 */
export function clockWords(value: string): string {
  const match = /^(\d{1,2}):(\d{2})/.exec(value.trim());
  if (!match) return value;
  const hour = Number(match[1]);
  const minute = match[2];
  if (hour > 23) return value;
  const suffix = hour < 12 ? "am" : "pm";
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return minute === "00" ? `${twelve}${suffix}` : `${twelve}:${minute}${suffix}`;
}

/** "9am to 9pm" from two "HH:MM" values. */
export function clockRange(start: string, end: string): string {
  return `${clockWords(start)} to ${clockWords(end)}`;
}
