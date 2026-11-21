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
    line: "Greets callers by name from your CRM or sheet.",
  },
  {
    id: "booking",
    kind: "calendar",
    title: "Take bookings",
    line: "Checks your Google Calendar and books callers in.",
  },
  {
    id: "whatsapp",
    kind: "whatsapp",
    title: "Send a WhatsApp message",
    line: "Sends your approved WhatsApp messages to callers.",
  },
  {
    id: "payment_link",
    kind: "payment_link",
    title: "Send a payment link",
    line: "Sends a payment link on WhatsApp. Paid to you.",
  },
  {
    id: "crm",
    kind: "crm",
    title: "Save callers to Zoho or HubSpot",
    line: "Saves the caller as a lead while on the call.",
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
    line: "For your developer: calls your own system mid-call.",
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
 * The hours are RULES the server keeps: both tools carry `hours`, per weekday in the business
 * profile's shape (`{"mon": {"opens", "closes"}}`), so the executor offers only free times
 * inside them and refuses a booking outside them (`outside_hours`), whatever the agent is
 * talked into. A window that closes at or before it opens runs past midnight, and
 * `00:00`–`00:00` is the whole day. The same hours are also written into what the agent is
 * told, so it says them to a caller rather than finding them out from a refusal. Actions
 * saved before per-day hours carry `opens`, `closes` and `open_days`, which still read back.
 */
export interface BookingDraft {
  credentialId: string;
  durationMin: number;
  /** Hours of the day in India time: `from` 0–23, `to` 1–24 (24 is midnight). A `to` at or
   *  before `from` runs past midnight. */
  from: number;
  to: number;
  /** ISO weekdays, 1 = Monday … 7 = Sunday, sorted. */
  days: number[];
  /** Exact windows per ISO weekday (from the business profile, or saved that way) while the
   *  owner has not set one time for every day; null when `from`/`to`/`days` say it all. */
  perDay: DayWindows | null;
  calendarId: string;
}

/** Booking hours per ISO weekday, `HH:MM` India time. */
export type DayWindows = Partial<Record<number, { opens: string; closes: string }>>;

export const BOOKING_DEFAULTS: Omit<BookingDraft, "credentialId"> = {
  durationMin: 60,
  from: 9,
  to: 18,
  days: [1, 2, 3, 4, 5, 6],
  perDay: null,
  calendarId: "primary",
};

export const LENGTH_CHOICES: readonly number[] = [15, 30, 45, 60, 90, 120];
/** Opening hours, midnight to 11 pm. */
export const HOUR_CHOICES: readonly number[] = Array.from({ length: 24 }, (_, i) => i);
/** Closing hours, 1 am to midnight (24). */
export const CLOSE_HOUR_CHOICES: readonly number[] = Array.from({ length: 24 }, (_, i) => i + 1);
export const WEEKDAYS: readonly { day: number; short: string; long: string; key: DayKey }[] = [
  { day: 1, short: "Mon", long: "Monday", key: "mon" },
  { day: 2, short: "Tue", long: "Tuesday", key: "tue" },
  { day: 3, short: "Wed", long: "Wednesday", key: "wed" },
  { day: 4, short: "Thu", long: "Thursday", key: "thu" },
  { day: 5, short: "Fri", long: "Friday", key: "fri" },
  { day: 6, short: "Sat", long: "Saturday", key: "sat" },
  { day: 7, short: "Sun", long: "Sunday", key: "sun" },
];
type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

/** `9` → "9 am", `12` → "12 pm", `18` → "6 pm", `0` and `24` → "12 am". */
export function hourLabel(hour: number): string {
  const h24 = hour % 24;
  const suffix = h24 < 12 ? "am" : "pm";
  const h = h24 % 12 === 0 ? 12 : h24 % 12;
  return `${h} ${suffix}`;
}

/** `"09:30"` → "9:30 am", `"18:00"` → "6 pm". */
function clockLabel(hhmm: string): string {
  const [h = 0, m = 0] = hhmm.split(":").map(Number);
  const label = hourLabel(h);
  return m === 0 ? label : label.replace(" ", `:${String(m).padStart(2, "0")} `);
}

/** "9 am – 6 pm", "Any time of day" for a whole day. */
function windowLabel(opens: string, closes: string): string {
  return opens === closes ? "Any time of day" : `${clockLabel(opens)} – ${clockLabel(closes)}`;
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

const pad = (h: number) => `${String(h % 24).padStart(2, "0")}:00`;
const hourOf = (hhmm: unknown): number | null => {
  if (typeof hhmm !== "string") return null;
  const m = /^(\d{2}):(\d{2})$/.exec(hhmm);
  return m ? Number(m[1]) : null;
};
const isClock = (value: unknown): value is string => typeof value === "string" && /^\d{2}:\d{2}$/.test(value);

/** The per-day windows a draft stands for. */
export function draftWindows(d: BookingDraft): DayWindows {
  if (d.perDay) return d.perDay;
  const windows: DayWindows = {};
  for (const day of d.days) windows[day] = { opens: pad(d.from), closes: pad(d.to) };
  return windows;
}

/**
 * The windows as one draft: `from`/`to`/`days` when every open day shares one whole-hour
 * window, else kept exactly in `perDay` (with the first open day's hours in the simple
 * controls, for when the owner sets one time for every day).
 */
function draftOfWindows(windows: DayWindows): Pick<BookingDraft, "from" | "to" | "days" | "perDay"> {
  const days = WEEKDAYS.map((w) => w.day).filter((day) => windows[day] !== undefined);
  const first = days.length > 0 ? windows[days[0] ?? 1] : undefined;
  if (!first) return { from: BOOKING_DEFAULTS.from, to: BOOKING_DEFAULTS.to, days: BOOKING_DEFAULTS.days, perDay: null };
  const from = hourOf(first.opens) ?? BOOKING_DEFAULTS.from;
  const closes = hourOf(first.closes) ?? BOOKING_DEFAULTS.to;
  const to = closes === 0 ? 24 : closes;
  const same = days.every((day) => windows[day]?.opens === first.opens && windows[day]?.closes === first.closes);
  const whole = first.opens.endsWith(":00") && first.closes.endsWith(":00");
  return { from, to, days, perDay: same && whole ? null : windows };
}

/**
 * Where a new booking job starts: the business profile's opening hours when it has any
 * (`BusinessProfile.hours`, one row per day; a closed or unanswered day takes no bookings),
 * else 9 am to 6 pm, Monday to Saturday.
 */
export function bookingDefaults(
  hours: readonly { day: string; opens?: string | null; closes?: string | null; closed?: boolean | null }[] | undefined,
): Omit<BookingDraft, "credentialId"> {
  const windows: DayWindows = {};
  for (const row of hours ?? []) {
    const day = WEEKDAYS.find((w) => w.key === row.day)?.day;
    if (day !== undefined && !row.closed && isClock(row.opens) && isClock(row.closes)) {
      windows[day] = { opens: row.opens, closes: row.closes };
    }
  }
  if (Object.keys(windows).length === 0) return { ...BOOKING_DEFAULTS };
  return { ...BOOKING_DEFAULTS, ...draftOfWindows(windows) };
}

/** The hours as one short line: "9 am – 6 pm", or per day when the days differ. */
export function hoursLabel(d: BookingDraft | null): string {
  if (d === null) return "Any time";
  if (!d.perDay) return windowLabel(pad(d.from), pad(d.to));
  const groups = new Map<string, number[]>();
  for (const w of WEEKDAYS) {
    const window = d.perDay[w.day];
    if (window) groups.set(`${window.opens}|${window.closes}`, [...(groups.get(`${window.opens}|${window.closes}`) ?? []), w.day]);
  }
  return [...groups.entries()]
    .map(([key, days]) => {
      const [opens = "", closes = ""] = key.split("|");
      return `${daysLabel(days)} ${windowLabel(opens, closes)}`;
    })
    .join(" · ");
}

function hoursSentence(d: BookingDraft): string {
  if (d.perDay) return `Only offer and book times in these hours, India time: ${hoursLabel(d)}.`;
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
  const windows = draftWindows(d);
  const rules = {
    calendar_id: d.calendarId || "primary",
    duration_min: d.durationMin,
    hours: Object.fromEntries(
      WEEKDAYS.filter((w) => windows[w.day] !== undefined).map((w) => [w.key, windows[w.day]]),
    ),
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
 * A booking job's settings, read back from its tools (for the summary and for Change): the
 * per-day `hours` first, then the one window an older action keeps (`opens`, `closes`,
 * `open_days`), then — for an action made before the server kept hours — the sentence in
 * its instructions.
 */
export function readBooking(check: ActionTool | undefined, book: ActionTool | undefined): BookingDraft {
  const source = book ?? check;
  const config = source?.config ?? {};
  const duration = Number(config.duration_min);
  const calendarId = config.calendar_id;
  const common = {
    credentialId: source?.credential_id ?? "",
    durationMin: Number.isFinite(duration) && duration > 0 ? duration : BOOKING_DEFAULTS.durationMin,
    calendarId: typeof calendarId === "string" && calendarId ? calendarId : "primary",
  };
  const stored = config.hours;
  if (stored !== null && typeof stored === "object") {
    const windows: DayWindows = {};
    for (const w of WEEKDAYS) {
      const window = (stored as Record<string, unknown>)[w.key] as { opens?: unknown; closes?: unknown } | null | undefined;
      if (window && isClock(window.opens) && isClock(window.closes)) {
        windows[w.day] = { opens: window.opens, closes: window.closes };
      }
    }
    return { ...common, ...draftOfWindows(windows) };
  }
  const opens = hourOf(config.opens);
  const closes = hourOf(config.closes);
  const written = readHours(source?.description ?? "");
  const days = Array.isArray(config.open_days)
    ? config.open_days.filter((d): d is number => typeof d === "number" && d >= 1 && d <= 7)
    : null;
  return {
    ...common,
    from: opens ?? written?.from ?? BOOKING_DEFAULTS.from,
    to: closes ?? written?.to ?? BOOKING_DEFAULTS.to,
    days: days && days.length > 0 ? [...days].sort((a, b) => a - b) : [1, 2, 3, 4, 5, 6, 7],
    perDay: null,
  };
}

/** The booking hours the server keeps for this job, or null when it takes bookings any time. */
export function keptHours(check: ActionTool | undefined, book: ActionTool | undefined): BookingDraft | null {
  const config = (book ?? check)?.config ?? {};
  const kept = config.hours !== null && typeof config.hours === "object";
  return kept || (hourOf(config.opens) !== null && hourOf(config.closes) !== null) ? readBooking(check, book) : null;
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

/**
 * Jobs no longer offered for a new action. Writing calls into a sheet is an Integrations
 * destination ("Send results to"); the server refuses a new one here
 * (`action_sheet_moved`). Kept in `JOBS` so a sheet action set up before still has its
 * name, icon and form.
 */
export const RETIRED_JOBS: readonly JobId[] = ["sheets"];

/**
 * Where an action that runs after the call now belongs, for its move-out notice: a sheet
 * row or a post to the client's own system is an Integrations destination, a CRM record
 * (Zoho, HubSpot: no Integrations destination) is saved during the call instead, and
 * anything else, a thank-you WhatsApp first, is a Follow-up step.
 */
export function afterCallHome(tool: Pick<ActionTool, "kind">): "integrations" | "during_call" | "follow_ups" {
  if (tool.kind === "sheets" || tool.kind === "custom_api") return "integrations";
  if (tool.kind === "crm") return "during_call";
  return "follow_ups";
}
