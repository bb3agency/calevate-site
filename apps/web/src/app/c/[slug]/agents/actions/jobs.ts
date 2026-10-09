/**
 * THE GUIDED ACTIONS FLOW'S VOCABULARY: jobs a client picks, and the machine values the
 * flow derives behind them (REDESIGN-2).
 *
 * The API is unchanged. A client used to type a tool `name` against a regex, pick a
 * trigger and bind every parameter; the guided flow asks for the job and two or three
 * plain settings, and this module turns those into the same `ToolIn` bodies. The old
 * fields survive under "Advanced" for the custom-API case.
 *
 * Plain `.ts` for UX-DOCTRINE §6: none of this is rendering, and it is the half a test
 * can drive without a render.
 */

import type { ActionTool, ActionToolInput } from "@/lib/api/actions";

import type { DraftParam, Kind, Provider } from "./params";

/** A job is what the owner wants done. `booking` is two calendar tools behind one job. */
export type JobId = "booking" | Exclude<Kind, "calendar">;

export interface Job {
  id: JobId;
  kind: Kind;
  title: string;
  line: string;
}

/** In the order the chooser offers them: the ones most businesses want first. */
export const JOBS: readonly Job[] = [
  {
    id: "booking",
    kind: "calendar",
    title: "Book appointments",
    line: "Your agent can check your Google Calendar and book callers in.",
  },
  {
    id: "caller_lookup",
    kind: "caller_lookup",
    title: "Know who is calling",
    line: "Your agent looks the caller up in your CRM or a sheet and greets them by name.",
  },
  {
    id: "whatsapp",
    kind: "whatsapp",
    title: "Send a WhatsApp message",
    line: "Your agent sends one of your approved WhatsApp messages, such as your price list.",
  },
  {
    id: "payment_link",
    kind: "payment_link",
    title: "Send a payment link",
    line: "Your agent sends a payment link on WhatsApp. The money goes to your own account.",
  },
  {
    id: "crm",
    kind: "crm",
    title: "Save callers to your CRM",
    line: "Each caller is saved as a lead or a contact while the call carries on.",
  },
  {
    id: "sheets",
    kind: "sheets",
    title: "Write callers into a Google Sheet",
    line: "Each call adds a row with what the caller told your agent.",
  },
  {
    id: "custom_api",
    kind: "custom_api",
    title: "Use your own API",
    line: "For your developer: your agent calls an address on your own system during the call.",
  },
];

export function jobFor(kind: string): Job | undefined {
  return JOBS.find((j) => j.kind === kind);
}

/** The base of the derived `name` per job — the server's pattern is `^[a-zA-Z][a-zA-Z0-9_]*$`. */
export const NAME_BASE: Record<Exclude<JobId, "booking">, string> = {
  caller_lookup: "look_up_the_caller",
  whatsapp: "send_whatsapp",
  payment_link: "send_payment_link",
  crm: "save_to_crm",
  sheets: "save_to_sheet",
  custom_api: "call_your_system",
};

/** `base`, or `base_2`, `base_3`… — the first one no other action on this agent uses. */
export function uniqueName(base: string, taken: readonly string[], keep?: string): string {
  if (keep !== undefined && keep === base) return base;
  const used = new Set(taken.filter((n) => n !== keep));
  if (!used.has(base)) return base;
  for (let i = 2; ; i += 1) {
    const candidate = `${base}_${i}`;
    if (!used.has(candidate)) return candidate;
  }
}

/** A tool's machine name read as words: `find_free_times` → "Find free times". */
export function humanName(name: string): string {
  const words = name.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : name;
}

/** What the agent is told to do, per job, before the owner changes it. */
export const DEFAULT_INSTRUCTIONS: Record<Exclude<JobId, "booking">, string> = {
  caller_lookup: "Use this first, before greeting, to find out who is calling.",
  whatsapp: "Send this message once the caller asks for it on WhatsApp.",
  payment_link: "Send the payment link once the caller agrees to pay.",
  crm: "Save the caller once you know their name and what they want.",
  sheets: "Save the caller's answers as soon as they give their name and what they need.",
  custom_api: "Use this when the caller gives the details it needs.",
};

function aiParam(name: string, description: string, over: Partial<DraftParam> = {}): DraftParam {
  return {
    name,
    source: "ai",
    value: "",
    lead_var: "caller_phone",
    description,
    type: "string",
    required: false,
    ...over,
  };
}

/** The values a job's action collects, before the owner changes them under Advanced. */
export function defaultParams(kind: Kind, provider: Provider): DraftParam[] {
  if (kind === "whatsapp") {
    return [
      aiParam("recipient", "The caller's number.", { source: "lead_var", lead_var: "caller_phone" }),
    ];
  }
  if (kind === "payment_link") {
    return [aiParam("amount", "The amount in rupees the caller agreed to pay.", { type: "number", required: true })];
  }
  if (kind === "crm") {
    return provider === "hubspot"
      ? [aiParam("firstname", "The caller's name.", { required: true })]
      : [aiParam("Last_Name", "The caller's name.", { required: true })];
  }
  if (kind === "sheets") {
    return [
      aiParam("Name", "The caller's name."),
      aiParam("Need", "What the caller wants, in a few words."),
    ];
  }
  return [];
}

/* ------------------------------------------------------------------ booking ---- */

/**
 * BOOK APPOINTMENTS is two calendar tools, because the server's `CalendarConfig` does one
 * operation per tool: `check` (find free times in a window) and `book` (book one time).
 * The owner sees one job; the agent gets both.
 *
 * HOURS ARE AN INSTRUCTION, NOT A RULE THE SERVER ENFORCES. `CalendarConfig` has no
 * opening-hours field, so the hours are written into what the agent is told on both
 * tools. The agent follows them; the calendar API would still accept a booking outside
 * them if the agent were talked into one. Making the server refuse is an API change
 * (REDESIGN-2 report, founder decision).
 */
export interface BookingDraft {
  credentialId: string;
  durationMin: number;
  /** Hours of the day, 0–23, in India time. */
  from: number;
  to: number;
  calendarId: string;
}

export const BOOKING_DEFAULTS: Omit<BookingDraft, "credentialId"> = {
  durationMin: 60,
  from: 9,
  to: 18,
  calendarId: "primary",
};

export const LENGTH_CHOICES: readonly number[] = [15, 30, 45, 60, 90, 120];
export const HOUR_CHOICES: readonly number[] = Array.from({ length: 18 }, (_, i) => i + 6);

/** `9` → "9 am", `12` → "12 pm", `18` → "6 pm". */
export function hourLabel(hour: number): string {
  const suffix = hour < 12 ? "am" : "pm";
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h} ${suffix}`;
}

/** `60` → "1 hour", `90` → "1 hour 30 minutes", `30` → "30 minutes". */
export function lengthLabel(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const hours = h === 0 ? "" : h === 1 ? "1 hour" : `${h} hours`;
  const mins = m === 0 ? "" : `${m} minutes`;
  return [hours, mins].filter(Boolean).join(" ") || `${minutes} minutes`;
}

const HOURS_SENTENCE = (from: number, to: number) =>
  `Only offer and book times between ${hourLabel(from)} and ${hourLabel(to)} India time.`;
const HOURS_PATTERN = /between (\d{1,2}) (am|pm) and (\d{1,2}) (am|pm) India time/;

function to24(h: string, half: string): number {
  const n = Number(h) % 12;
  return half === "pm" ? n + 12 : n;
}

/** The booking hours written into a tool's instructions, if it was written by this flow. */
export function readHours(description: string): { from: number; to: number } | null {
  const m = HOURS_PATTERN.exec(description);
  if (!m) return null;
  return { from: to24(m[1] ?? "", m[2] ?? ""), to: to24(m[3] ?? "", m[4] ?? "") };
}

const TIME_FORMAT = "as YYYY-MM-DDTHH:MM in India time";

/** The two `ToolIn` bodies that make up the booking job. */
export function bookingTools(
  d: BookingDraft,
  names: { check: string; book: string },
): { check: ActionToolInput; book: ActionToolInput } {
  const length = `Each booking is ${lengthLabel(d.durationMin)}.`;
  const hours = HOURS_SENTENCE(d.from, d.to);
  const base = {
    kind: "calendar" as const,
    provider: "google",
    trigger: "during_call" as const,
    credential_id: d.credentialId || null,
  };
  return {
    check: {
      ...base,
      name: names.check,
      description: `Use this to find free times before offering any to the caller. ${length} ${hours}`,
      pre_call_message: "One moment, let me check the calendar.",
      params: [
        { name: "start", source: "ai", value: null, lead_var: null, type: "string", required: true, description: `Start of the time to check, ${TIME_FORMAT}.` },
        { name: "end", source: "ai", value: null, lead_var: null, type: "string", required: true, description: `End of the time to check, ${TIME_FORMAT}.` },
      ],
      config: {
        operation: "check",
        calendar_id: d.calendarId || "primary",
        start_param: "start",
        end_param: "end",
        duration_min: d.durationMin,
        summary_param: null,
      },
    },
    book: {
      ...base,
      name: names.book,
      description: `Use this to book once the caller agrees to a free time. ${length} ${hours}`,
      pre_call_message: "One moment while I book that.",
      params: [
        { name: "start", source: "ai", value: null, lead_var: null, type: "string", required: true, description: `The agreed start time, ${TIME_FORMAT}.` },
        { name: "summary", source: "ai", value: null, lead_var: null, type: "string", required: false, description: "The caller's name and what the booking is for." },
      ],
      config: {
        operation: "book",
        calendar_id: d.calendarId || "primary",
        start_param: "start",
        end_param: null,
        duration_min: d.durationMin,
        summary_param: "summary",
      },
    },
  };
}

/** The calendar tools on an agent, split into the booking job's two halves. */
export function bookingParts(tools: readonly ActionTool[]): {
  check: ActionTool | undefined;
  book: ActionTool | undefined;
} {
  const calendar = tools.filter((t) => t.kind === "calendar");
  return {
    check: calendar.find((t) => t.config.operation === "check"),
    book: calendar.find((t) => t.config.operation === "book"),
  };
}

/** A booking job's settings, read back from its tools (for the summary and for Change). */
export function readBooking(check: ActionTool | undefined, book: ActionTool | undefined): BookingDraft {
  const source = book ?? check;
  const duration = Number(source?.config.duration_min);
  const calendarId = source?.config.calendar_id;
  const hours = readHours(source?.description ?? "");
  return {
    credentialId: source?.credential_id ?? "",
    durationMin: Number.isFinite(duration) && duration > 0 ? duration : BOOKING_DEFAULTS.durationMin,
    from: hours?.from ?? BOOKING_DEFAULTS.from,
    to: hours?.to ?? BOOKING_DEFAULTS.to,
    calendarId: typeof calendarId === "string" && calendarId ? calendarId : "primary",
  };
}

/** True when the hours were not written by this flow (an action set up by hand). */
export function hoursUnknown(check: ActionTool | undefined, book: ActionTool | undefined): boolean {
  return readHours((book ?? check)?.description ?? "") === null;
}

/**
 * A `datetime-local` value plus minutes, as another `datetime-local` value — computed on
 * the wall-clock fields so the browser's own time zone never shifts India time.
 */
export function addMinutesLocal(value: string, minutes: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!m) return value;
  const at = new Date(Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]! + minutes));
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}T${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}`;
}
