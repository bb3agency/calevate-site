/** The rights desk's own words (D-943), one short line each. */
export const DESK_COPY = {
  heading: "Requests from your customers",
  why:
    "A customer can ask to see, correct or erase their data. The law gives you 90 days to " +
    "answer. Log each request here so the clock is kept for you.",
  log: "Log a request",
  loading: "Loading requests",
  empty: "No customer has asked about their data yet.",
  counts: (open: number, soon: number, overdue: number) =>
    `${open} open · ${soon} due soon · ${overdue} overdue`,
  asked: (channel: string, day: string) => `${channel}, ${day}`,
  closed: (status: string) => (status === "refused" ? "Refused" : "Answered"),
  code: (ref: string) => `Code ${ref}`,
  codeWhy: "A one-way code of their number. We never list the number.",
  export: "Export their data",
  erase: "Erase their data",
  refuseIdentity: "Can't confirm who they are",
  kindField: "What they asked for",
  channelField: "How they asked",
  phoneField: "Their phone number",
  askedField: "When they asked",
  askedHint: "Leave empty for today. The 90 days start here.",
  logSubmit: "Log it",
  logging: "Logging…",
} as const;

export function daysLeftLine(days: number): string {
  if (days < 0) return `${-days} days overdue`;
  if (days === 0) return "Due today";
  return days === 1 ? "1 day left" : `${days} days left`;
}
