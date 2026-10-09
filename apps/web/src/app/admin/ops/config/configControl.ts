import { timingCopy } from "@/app/admin/ops/opsLanguage";
import {
  formatCount,
  formatCallCap,
  formatIST,
  formatINR,
  formatPhone,
  type NoticeTone,
} from "@/components/ui";
import { providerLabel } from "@/lib/api/llmModels";
import type { ConfigControl, ConfigField, ConfigOption, ConfigValue } from "@/lib/api/opsConfig";

/**
 * How one platform setting is SHOWN and EDITED, from the `control` the server derives for it
 * (`apps/api/ops/config_controls.py`). Pure functions: the row, the change form and the
 * tests all read these, so a value never reads one way on the row and another in the form.
 *
 * The control guides input and nothing more. The server validates every write against the
 * `Settings` field itself, so `validateDraft` exists to say "not yet" while the operator
 * types — never to decide what the platform accepts.
 */

/** Every control this console can draw; anything else the server sends is `unknown`. */
export type ControlKind =
  | "switch"
  | "segmented"
  | "select"
  | "multi_select"
  | "entity_picker"
  | "number"
  | "money_inr"
  | "duration"
  | "percent"
  | "phone_in"
  | "phone"
  | "url"
  | "email"
  | "text";

const KINDS: ReadonlySet<string> = new Set<ControlKind>([
  "switch",
  "segmented",
  "select",
  "multi_select",
  "entity_picker",
  "number",
  "money_inr",
  "duration",
  "percent",
  "phone_in",
  "phone",
  "url",
  "email",
  "text",
]);

/**
 * The kind to draw. A kind a newer server sends that this build does not know is drawn as
 * a text box, and the form says so — the server still validates whatever is typed.
 */
export function controlKind(field: ConfigField): ControlKind | "unknown" {
  return KINDS.has(field.control.kind) ? (field.control.kind as ControlKind) : "unknown";
}

const NUMERIC: ReadonlySet<string> = new Set(["number", "duration", "money_inr", "percent"]);
const INDIA = "+91";

/** The draft the form holds, from a value the server sent. `""` is "not set". */
export function draftOf(field: ConfigField, value: ConfigValue): string {
  if (value === null) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  const kind = controlKind(field);
  if (kind === "percent" && typeof value === "number") return trimNumber(value * 100);
  if (kind === "phone_in" && typeof value === "string" && value.startsWith(INDIA)) {
    return value.slice(INDIA.length);
  }
  return String(value);
}

/** `30.000000000000004` → `"30"`: a percentage is shown to two places at most. */
function trimNumber(value: number): string {
  return String(Math.round(value * 100) / 100);
}

/** The values a multi-choice draft holds, in order, without blanks or repeats. */
export function listOf(draft: string): string[] {
  const seen: string[] = [];
  for (const part of draft.split(",")) {
    const value = part.trim();
    if (value && !seen.includes(value)) seen.push(value);
  }
  return seen;
}

/**
 * The value to send, from the draft.
 *
 * Money goes as the STRING typed, never through a JS number (hard rule 7). A blank is
 * `null` for a setting that accepts "not set", and the empty string for one whose "nothing"
 * is an empty list (`healer_paused_playbooks`), which the server stores as such.
 */
export function valueOf(field: ConfigField, draft: string): ConfigValue {
  const kind = controlKind(field);
  const trimmed = draft.trim();
  if (kind === "switch") return trimmed === "true";
  if (field.control.multiple) {
    const joined = listOf(trimmed).join(",");
    return joined === "" && field.nullable ? null : joined;
  }
  if (trimmed === "") return field.nullable ? null : NUMERIC.has(kind) ? null : "";
  if (kind === "number" || kind === "duration") {
    const parsed = Number(trimmed);
    return Number.isInteger(parsed) ? parsed : trimmed;
  }
  if (kind === "percent") {
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? Math.round(parsed * 100) / 10000 : trimmed;
  }
  if (kind === "phone_in") return `${INDIA}${trimmed.replace(/\D/g, "")}`;
  if (kind === "phone") return trimmed.replace(/[\s-]/g, "");
  return trimmed;
}

/** The option the server sent for `value`, if any. */
export function optionFor(field: ConfigField, value: string): ConfigOption | undefined {
  return field.options.find((option) => option.value === value);
}

/** One option as a person reads it: its label, its provider, and "default". */
export function optionText(field: ConfigField, option: ConfigOption): string {
  const notes: string[] = [];
  if (option.provider) notes.push(providerLabel(option.provider));
  if (field.has_default && option.value === field.default) notes.push("default");
  if (option.unavailable_reason) notes.push("not available to clients yet");
  return notes.length > 0 ? `${option.label} · ${notes.join(" · ")}` : option.label;
}

function withUnit(text: string, unit: string | null): string {
  return unit ? `${text} ${unit}` : text;
}

function durationText(control: ConfigControl, amount: number): string {
  if (control.unit === "milliseconds") {
    return amount % 1000 === 0
      ? formatCallCap(amount / 1000)
      : `${formatCount(amount)} milliseconds`;
  }
  return formatCallCap(amount);
}

/**
 * A value as a person reads it: On/Off, the option's label, ₹ with its unit, minutes, a
 * percentage, a grouped phone number. `null` is "Not set", never a blank.
 */
export function displayValue(field: ConfigField, value: ConfigValue): string {
  if (value === null) return "Not set";
  const kind = controlKind(field);
  const control = field.control;
  if (typeof value === "boolean") return value ? "On" : "Off";
  if (field.control.multiple && typeof value === "string") {
    const values = listOf(value);
    if (values.length === 0) return "None";
    if (kind === "entity_picker") {
      return values.length === 1 ? "1 selected" : `${values.length} selected`;
    }
    return values.map((v) => optionFor(field, v)?.label ?? v).join(", ");
  }
  if (typeof value === "string" && (kind === "select" || kind === "segmented")) {
    return optionFor(field, value)?.label ?? value;
  }
  if (kind === "money_inr") return withUnit(formatINR(String(value)), control.unit);
  if (kind === "percent" && typeof value === "number") return `${trimNumber(value * 100)}%`;
  if (kind === "duration" && typeof value === "number") return durationText(control, value);
  if (kind === "number" && typeof value === "number") {
    return withUnit(formatCount(value), control.unit);
  }
  if ((kind === "phone_in" || kind === "phone" || kind === "entity_picker") && typeof value === "string") {
    return value.startsWith("+") ? formatPhone(value) : value;
  }
  if (value === "") return "Empty";
  return String(value);
}

/** The draft as a person reads it, for the before → after preview. */
export function displayDraft(field: ConfigField, draft: string): string {
  return displayValue(field, valueOf(field, draft));
}

// --- checking a draft as it is typed -------------------------------------------------

/** `a` < `b` → negative; exact, for decimal strings that must never become floats. */
export function compareDecimal(a: string, b: string): number {
  const split = (value: string) => {
    const negative = value.startsWith("-");
    const [whole = "0", fraction = ""] = value.replace(/^[-+]/, "").split(".");
    return { negative, whole: whole.replace(/^0+(?=\d)/, ""), fraction };
  };
  const x = split(a);
  const y = split(b);
  const width = Math.max(x.fraction.length, y.fraction.length);
  const scaled = (part: ReturnType<typeof split>) =>
    BigInt(`${part.negative ? "-" : ""}${part.whole}${part.fraction.padEnd(width, "0")}` || "0");
  const diff = scaled(x) - scaled(y);
  return diff === BigInt(0) ? 0 : diff < BigInt(0) ? -1 : 1;
}

function boundsError(field: ConfigField, typed: string, shown: (bound: string) => string): string | null {
  const { minimum, maximum, minimum_exclusive: exclusive } = field.control;
  if (minimum !== null) {
    const order = compareDecimal(typed, minimum);
    if (order < 0 || (exclusive && order === 0)) {
      return exclusive ? `Must be more than ${shown(minimum)}.` : `Must be at least ${shown(minimum)}.`;
    }
  }
  if (maximum !== null && compareDecimal(typed, maximum) > 0) {
    return `Must be at most ${shown(maximum)}.`;
  }
  return null;
}

function patternMatches(pattern: string | null, value: string): boolean {
  if (pattern === null) return true;
  try {
    return new RegExp(pattern).test(value);
  } catch {
    // A Python-only construct this browser cannot compile: the server still checks it.
    return true;
  }
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Why this draft would be refused, in a sentence, or `null` when it looks right. A guide
 * while typing: the server's answer on Save is the one that counts.
 */
export function validateDraft(field: ConfigField, draft: string): string | null {
  const kind = controlKind(field);
  const control = field.control;
  const trimmed = draft.trim();
  if (kind === "switch" || field.control.multiple) return null;
  if (trimmed === "") {
    if (field.nullable) return null;
    return NUMERIC.has(kind) || kind === "select" || kind === "segmented"
      ? "Choose a value; this setting cannot be left empty."
      : null;
  }
  if (kind === "number" || kind === "duration") {
    if (!/^-?\d+$/.test(trimmed)) return "Use a whole number.";
    return boundsError(field, trimmed, (bound) => withUnit(formatCount(Number(bound)), control.unit));
  }
  if (kind === "money_inr") {
    if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return "Use an amount in rupees, like 4.50.";
    return boundsError(field, trimmed, (bound) => formatINR(bound));
  }
  if (kind === "percent") {
    if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return "Use a percentage, like 30.";
    return compareDecimal(trimmed, "100") > 0 ? "Must be at most 100%." : null;
  }
  if (kind === "phone_in") {
    return /^\d{10}$/.test(trimmed.replace(/\D/g, ""))
      ? null
      : "Use the ten-digit Indian mobile number, without +91.";
  }
  if (kind === "phone") {
    return /^\+[1-9]\d{7,14}$/.test(trimmed.replace(/[\s-]/g, ""))
      ? null
      : "Use the full number with its country code, like +91 98765 43210.";
  }
  if (control.max_length !== null && trimmed.length > control.max_length) {
    return `Keep it to ${control.max_length} characters or fewer.`;
  }
  if (control.min_length !== null && trimmed.length < control.min_length) {
    return `Use at least ${control.min_length} characters.`;
  }
  if (kind === "email" && !EMAIL.test(trimmed)) return "Use an email address, like ops@calevate.tech.";
  if (kind === "url" && !/^[a-z][a-z0-9+.-]*:\/\/\S+$/i.test(trimmed)) {
    return `Use a full address, starting ${control.placeholder ?? "https://"}`;
  }
  if (!patternMatches(control.pattern, trimmed)) {
    return control.help ? `Not in the right format: ${control.help}` : "Not in the right format.";
  }
  return null;
}

/**
 * The server's refusal of this setting's value, made readable: the model's own message
 * names a validator rule ("String should match pattern …"), which is the server's
 * vocabulary, so the common rules are said in words and the rest are passed through.
 */
export function serverFieldMessage(
  field: ConfigField,
  error: { fields?: { field: string; rule: string; message: string }[] } | null,
): string | null {
  const mine = error?.fields?.find((entry) => entry.field === field.key);
  if (!mine) return null;
  if (mine.rule === "string_pattern_mismatch") {
    return field.control.help ? `Not in the right format: ${field.control.help}` : "Not in the right format.";
  }
  if (mine.rule === "literal_error") return "That is not one of the choices.";
  return mine.message.replace(/^Value error,\s*/i, "").replace(/^Input should be/i, "Should be");
}

// --- confirming --------------------------------------------------------------------------

/**
 * What a `high`-risk change asks the operator to type: the value being put in force, as
 * they read it ("Off", "ThinnestAI", "7.25"). It changes with every change, so it cannot
 * become muscle memory, and typing it is a second look at exactly what is about to apply.
 * A long value (an address) asks for the setting's name instead.
 */
export function confirmPhrase(field: ConfigField, value: ConfigValue): string {
  const kind = controlKind(field);
  if (value === null) return "Not set";
  if (kind === "money_inr" || kind === "number" || kind === "duration") return String(value);
  if (kind === "percent" && typeof value === "number") return trimNumber(value * 100);
  const shown = displayValue(field, value);
  return shown.length <= 24 ? shown : field.label;
}

// --- what state a setting is in --------------------------------------------------------

export type StateTone = "neutral" | "changed" | "locked";

export interface SettingState {
  tone: StateTone;
  label: string;
}

/** Default, changed by whom and when, or locked by the server — one chip on the row. */
export function settingState(field: ConfigField): SettingState {
  if (field.source === "env") return { tone: "locked", label: "Locked by the server" };
  if (field.source === "db") {
    const who = field.updated_by ?? "an operator";
    const when = field.updated_at ? ` on ${formatIST(field.updated_at)}` : "";
    return { tone: "changed", label: `Changed by ${who}${when}` };
  }
  if (!field.editable) return { tone: "locked", label: "Locked by the server" };
  return { tone: "neutral", label: field.has_default ? "Default" : "Set on the server" };
}

export interface AppliesCopy {
  /** The server's word, for `TimingBadge`. */
  applies: string;
  /** The short line on the row, from the ops console's one timing vocabulary. */
  label: string;
  tone: NoticeTone;
  /** What the operator still has to do, in full; the server's own caveat follows. */
  sentence: string;
}

function sentenceCase(text: string): string {
  const trimmed = text.trim().replace(/\.$/, "");
  return trimmed ? `${trimmed[0].toUpperCase()}${trimmed.slice(1)}.` : "";
}

/**
 * When a change applies, in the operator's words: the label and tone are `timingCopy`'s
 * (one vocabulary across the ops console), and the sentence adds this setting's own caveat,
 * which is the part an operator acts on ("agents keep the old address until republished").
 * An `applies` word this build does not know reads "Timing not known", never "immediately".
 */
export function appliesCopy(field: ConfigField): AppliesCopy {
  const timing = timingCopy(field.applies);
  const caveat = field.caveat ? sentenceCase(field.caveat) : "";
  return {
    applies: field.applies,
    label: timing.label,
    tone: timing.tone,
    sentence: caveat ? `${timing.help} ${caveat}` : timing.help,
  };
}

/** Why this setting cannot be changed here, in one sentence. */
export function lockedReason(field: ConfigField): string {
  if (field.source === "env") {
    return "It is set in the server's environment. The environment always wins over the console, so it can only be changed there.";
  }
  return appliesCopy(field).sentence;
}

/** The reasons offered with one tap; the operator can always write their own. */
export const REASON_PRESETS: readonly string[] = [
  "Correcting a mistake",
  "New details from the vendor",
  "Planned change",
  "Responding to an incident",
];
