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

import { formatINR } from "@/components/ui";
import type { ActionTool, ActionToolInput } from "@/lib/api/actions";
import { lookup } from "@/lib/lookup";
import type { VerticalExamples } from "@/lib/verticalExamples";

import type { DraftParam, Kind, Provider } from "./params";

/** A job is what the owner wants done. `booking` is two calendar tools behind one job. */
export type JobId = "booking" | Exclude<Kind, "calendar">;

export interface Job {
  id: JobId;
  kind: Kind;
  title: string;
  line: string;
}

/**
 * In the order the catalogue offers them. Booking is one job among peers, not the headline:
 * knowing the caller comes first because every other job reads better once it has run.
 */
export const JOBS: readonly Job[] = [
  {
    id: "caller_lookup",
    kind: "caller_lookup",
    title: "Know who is calling",
    line: "Your agent looks the caller up in your CRM or a sheet and greets them by name.",
  },
  {
    id: "booking",
    kind: "calendar",
    title: "Take bookings",
    line: "Your agent can check your Google Calendar and book callers in.",
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

/**
 * A job's name for THIS business. Only the booking job varies: a clinic books
 * appointments, everyone else takes bookings (`verticalExamples.bookingJobTitle`), so the
 * chooser never describes a property office or a school as a clinic.
 */
export function jobTitle(job: Job, eg: Pick<VerticalExamples, "bookingJobTitle">): string {
  return job.id === "booking" ? eg.bookingJobTitle : job.title;
}

/** A job's one line for THIS business (only the booking job varies). */
export function jobLine(job: Job, eg: Pick<VerticalExamples, "bookingJobLine">): string {
  return job.id === "booking" ? eg.bookingJobLine : job.line;
}

export function jobFor(kind: string): Job | undefined {
  return JOBS.find((j) => j.kind === kind);
}

export const BOOKING_JOB: Job = JOBS.find((j) => j.id === "booking")!;

/**
 * The service whose logo stands for a job in the catalogue, or null for a generic icon.
 * Only where the job always uses that one service: a CRM job could be Zoho or HubSpot, so
 * it waits until the owner picks.
 */
export function jobLogo(job: Job): string | null {
  switch (job.id) {
    case "booking":
      return "google_calendar";
    case "whatsapp":
      return "whatsapp";
    case "payment_link":
      return "razorpay";
    case "sheets":
      return "google_sheets";
    default:
      return null;
  }
}

/** The service whose logo stands for one set-up action, from the provider it was saved with. */
export function toolLogo(tool: Pick<ActionTool, "kind" | "provider">): string | null {
  switch (tool.kind) {
    case "calendar":
      return "google_calendar";
    case "whatsapp":
      return "whatsapp";
    case "sheets":
      return "google_sheets";
    case "payment_link":
      return tool.provider === null || tool.provider === "razorpay" ? "razorpay" : null;
    case "crm":
    case "caller_lookup":
      return tool.provider === "hubspot"
        ? "hubspot"
        : tool.provider === "zoho"
          ? "zoho_crm"
          : tool.provider === "sheet"
            ? "google_sheets"
            : null;
    default:
      return null;
  }
}

const PROVIDER_WORD: Record<string, string> = {
  aisensy: "AiSensy",
  meta_cloud: "WhatsApp Cloud API",
  interakt: "Interakt",
  zoho: "Zoho CRM",
  hubspot: "HubSpot",
  sheet: "Google Sheet",
  api: "Your own API",
  razorpay: "Razorpay",
};

function str(config: Record<string, unknown>, key: string): string {
  const value = config[key];
  return typeof value === "string" ? value.trim() : "";
}

function nested(config: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = config[key];
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

/** One plain line saying how an action is set up, for its row: "AiSensy · Template: price_list · en". */
export function toolSummary(tool: ActionTool): string {
  const c = tool.config;
  const provider = tool.provider ? (lookup(PROVIDER_WORD, tool.provider) ?? null) : null;
  const parts: (string | null)[] = [];
  switch (tool.kind) {
    case "whatsapp": {
      const template = str(c, "template");
      parts.push(provider, template ? `Template: ${template}` : null, str(c, "language") || null);
      break;
    }
    case "payment_link": {
      const fixed = str(c, "fixed_amount_inr");
      parts.push("Razorpay", fixed ? `${formatINR(fixed)} each time` : "Amount agreed on the call");
      const template = str(nested(c, "message"), "template");
      parts.push(template ? `Template: ${template}` : null);
      break;
    }
    case "crm":
      parts.push(provider, tool.provider === "hubspot" ? "Contacts" : str(c, "module") || null);
      break;
    case "sheets":
      parts.push(
        str(c, "spreadsheet_name") || "Google Sheet",
        str(c, "worksheet") || null,
        c.operation === "lookup" ? "Looks callers up" : "Adds a row per call",
      );
      break;
    case "caller_lookup":
      parts.push(provider ?? "Your records", str(c, "spreadsheet_name") || null);
      break;
    case "custom_api": {
      const url = str(c, "url");
      let host = "";
      try {
        host = url ? new URL(url).host : "";
      } catch {
        host = "";
      }
      parts.push(str(c, "method") || "POST", host || "No address yet");
      break;
    }
    default:
      parts.push(provider);
  }
  parts.push(tool.trigger === "after_call" ? "After the call" : null);
  return parts.filter((p): p is string => Boolean(p)).join(" · ");
}

/**
 * What is wrong with an action, in two or three words, or null when nothing is. A row shows
 * this as its only chip, so a healthy list carries no badges at all. `accounts` is the
 * business's connected accounts once loaded; a saved account that has since been removed
 * reads as not connected.
 */
export function toolProblem(
  tool: ActionTool,
  accounts: readonly { id: string }[] | undefined,
): string | null {
  const known = (id: string | null | undefined) =>
    Boolean(id) && (accounts === undefined || accounts.some((a) => a.id === id));
  const needsAccount = tool.kind !== "custom_api";
  if (needsAccount && !known(tool.credential_id)) return "Not connected";
  if (tool.kind === "whatsapp" && !str(tool.config, "template")) return "Needs a template";
  if (tool.kind === "payment_link") {
    const msg = nested(tool.config, "message");
    if (!known(typeof msg.credential_id === "string" ? msg.credential_id : null)) return "WhatsApp not connected";
    if (!str(msg, "template")) return "Needs a template";
  }
  if (tool.kind === "custom_api" && !str(tool.config, "url")) return "Needs an address";
  return null;
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
 * The hours and days are RULES the server keeps: both tools carry `opens`, `closes` and
 * `open_days`, so the executor offers only free times inside them and refuses a booking
 * outside them (`outside_hours`), whatever the agent is talked into. The same sentence is
 * also written into what the agent is told, so it says the hours to a caller rather than
 * finding them out from a refusal.
 */
export interface BookingDraft {
  credentialId: string;
  durationMin: number;
  /** Hours of the day, 0–23, in India time. */
  from: number;
  to: number;
  /** ISO weekdays, 1 = Monday … 7 = Sunday, sorted. */
  days: number[];
  calendarId: string;
}

export const BOOKING_DEFAULTS: Omit<BookingDraft, "credentialId"> = {
  durationMin: 60,
  from: 9,
  to: 18,
  days: [1, 2, 3, 4, 5, 6],
  calendarId: "primary",
};

export const LENGTH_CHOICES: readonly number[] = [15, 30, 45, 60, 90, 120];
export const HOUR_CHOICES: readonly number[] = Array.from({ length: 18 }, (_, i) => i + 6);
export const WEEKDAYS: readonly { day: number; short: string; long: string }[] = [
  { day: 1, short: "Mon", long: "Monday" },
  { day: 2, short: "Tue", long: "Tuesday" },
  { day: 3, short: "Wed", long: "Wednesday" },
  { day: 4, short: "Thu", long: "Thursday" },
  { day: 5, short: "Fri", long: "Friday" },
  { day: 6, short: "Sat", long: "Saturday" },
  { day: 7, short: "Sun", long: "Sunday" },
];

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

/** `[1..7]` → "Every day", `[1..6]` → "Mon – Sat", `[1, 3, 5]` → "Mon, Wed, Fri". */
export function daysLabel(days: readonly number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  if (sorted.length === 7) return "Every day";
  if (sorted.length === 0) return "No days";
  const name = (d: number) => WEEKDAYS.find((w) => w.day === d)?.short ?? String(d);
  const run = sorted.every((d, i) => i === 0 || d === (sorted[i - 1] ?? 0) + 1);
  if (run && sorted.length >= 3) return `${name(sorted[0] ?? 1)} – ${name(sorted[sorted.length - 1] ?? 7)}`;
  return sorted.map(name).join(", ");
}

const pad = (h: number) => `${String(h).padStart(2, "0")}:00`;
const hourOf = (hhmm: unknown): number | null => {
  if (typeof hhmm !== "string") return null;
  const m = /^(\d{2}):(\d{2})$/.exec(hhmm);
  return m ? Number(m[1]) : null;
};

function hoursSentence(d: BookingDraft): string {
  const days = d.days.length === 7 ? "" : ` on ${daysLabel(d.days).replace(" – ", " to ")}`;
  return `Only offer and book times between ${hourLabel(d.from)} and ${hourLabel(d.to)} India time${days}.`;
}
const HOURS_PATTERN = /between (\d{1,2}) (am|pm) and (\d{1,2}) (am|pm) India time/;

function to24(h: string, half: string): number {
  const n = Number(h) % 12;
  return half === "pm" ? n + 12 : n;
}

/** The booking hours written into a tool's instructions (actions made before the rule). */
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
  const hours = hoursSentence(d);
  const days = [...new Set(d.days)].sort((a, b) => a - b);
  const rules = {
    calendar_id: d.calendarId || "primary",
    duration_min: d.durationMin,
    opens: pad(d.from),
    closes: pad(d.to),
    open_days: days.length === 7 ? null : days,
  };
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
      config: { operation: "check", start_param: "start", end_param: "end", summary_param: null, ...rules },
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
      config: { operation: "book", start_param: "start", end_param: null, summary_param: "summary", ...rules },
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

/**
 * A booking job's settings, read back from its tools (for the summary and for Change):
 * the config's rules first, then — for an action made before the server kept hours — the
 * sentence in its instructions.
 */
export function readBooking(check: ActionTool | undefined, book: ActionTool | undefined): BookingDraft {
  const source = book ?? check;
  const config = source?.config ?? {};
  const duration = Number(config.duration_min);
  const calendarId = config.calendar_id;
  const opens = hourOf(config.opens);
  const closes = hourOf(config.closes);
  const written = readHours(source?.description ?? "");
  const days = Array.isArray(config.open_days)
    ? config.open_days.filter((d): d is number => typeof d === "number" && d >= 1 && d <= 7)
    : null;
  return {
    credentialId: source?.credential_id ?? "",
    durationMin: Number.isFinite(duration) && duration > 0 ? duration : BOOKING_DEFAULTS.durationMin,
    from: opens ?? written?.from ?? BOOKING_DEFAULTS.from,
    to: closes ?? written?.to ?? BOOKING_DEFAULTS.to,
    days: days && days.length > 0 ? [...days].sort((a, b) => a - b) : [1, 2, 3, 4, 5, 6, 7],
    calendarId: typeof calendarId === "string" && calendarId ? calendarId : "primary",
  };
}

/** The booking hours the server keeps for this job, or null when it takes bookings any time. */
export function keptHours(check: ActionTool | undefined, book: ActionTool | undefined): { from: number; to: number } | null {
  const config = (book ?? check)?.config ?? {};
  const from = hourOf(config.opens);
  const to = hourOf(config.closes);
  return from !== null && to !== null ? { from, to } : null;
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

/**
 * A set-up action's name on its row: the job's title while it carries the name the flow
 * derived for it (`send_whatsapp`, `send_whatsapp_2`), or the owner's own name when they
 * gave it one ("Look up an order"), so two of their own APIs never read the same.
 */
export function toolTitle(tool: Pick<ActionTool, "kind" | "name">): string {
  const job = jobFor(tool.kind);
  if (job && job.id !== "booking") {
    const base = NAME_BASE[job.id];
    if (tool.name === base || new RegExp(`^${base}_\d+$`).test(tool.name)) return job.title;
  }
  return humanName(tool.name);
}

/** Jobs that stay in the catalogue once set up: each instance is a different system. */
export const REPEATABLE_JOBS: readonly JobId[] = ["custom_api"];
