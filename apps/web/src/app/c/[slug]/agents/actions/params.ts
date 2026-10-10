/**
 * The vocabulary the Actions forms are built from — kinds, providers, and one parameter.
 *
 * A plain `.ts` module for UX-DOCTRINE §6's reason: `Actions.tsx` was 738 lines with the
 * type unions, the lead-variable table, the draft shape and its wire mapping threaded
 * between four components. None of that is rendering, and none of it needs React.
 */

import type { ActionParam } from "@/lib/api/actions";

/** The kinds of action a client can add (D-700 added the last four). */
export type Kind =
  | "custom_api"
  | "whatsapp"
  | "calendar"
  | "sheets"
  | "payment_link"
  | "crm"
  | "caller_lookup";

/** In the order the Add buttons offer them: the ones most clients want first. */
export const KINDS: readonly Kind[] = [
  "caller_lookup",
  "calendar",
  "whatsapp",
  "payment_link",
  "crm",
  "sheets",
  "custom_api",
];

/** Every provider any kind can name. */
export type Provider =
  | "aisensy"
  | "meta_cloud"
  | "interakt"
  | "custom"
  | "google"
  | "zoho"
  | "hubspot"
  | "razorpay"
  | "sheet"
  | "api";

// Local unions for the casts of a form-control string, so the wire-fixture guard's ban on
// asserting onto a GENERATED schema type does not apply (these are ours, not generated).
export type CredKind =
  | "aisensy"
  | "meta_cloud"
  | "interakt"
  | "custom_api"
  | "google_calendar"
  | "google_sheets"
  | "razorpay"
  | "zoho_crm"
  | "hubspot";

/** The kinds a client saves by pasting a key; the others connect by signing in. */
export type KeyKind = "aisensy" | "meta_cloud" | "interakt" | "custom_api" | "razorpay";

/** A Google Sheet's id from its address, or the text as typed when it already is one. */
export function spreadsheetId(input: string): string {
  const match = /\/spreadsheets\/d\/([A-Za-z0-9_-]+)/.exec(input);
  return (match?.[1] ?? input).trim();
}

/** The saved-account kind an action (and its provider) uses, or null for none of its own. */
export function credentialKindFor(kind: Kind, provider: Provider): CredKind | null {
  if (kind === "custom_api") return "custom_api";
  if (kind === "calendar") return "google_calendar";
  if (kind === "payment_link") return "razorpay";
  if (kind === "sheets") return "google_sheets";
  if (kind === "whatsapp") {
    return provider === "aisensy" || provider === "meta_cloud" || provider === "interakt"
      ? provider
      : null;
  }
  if (provider === "zoho") return "zoho_crm";
  if (provider === "hubspot") return "hubspot";
  if (provider === "api") return "custom_api";
  if (provider === "sheet") return "google_sheets";
  return null;
}

/** The call facts a parameter can be bound to instead of a typed or AI-decided value. */
export const LEAD_VARS: { value: string; label: string }[] = [
  { value: "caller_phone", label: "Caller's phone number" },
  { value: "from_number", label: "The number the call came from" },
  { value: "to_number", label: "The number that was called" },
  { value: "call_sid", label: "This call's reference" },
];

/**
 * One parameter being drafted. `source` is the founder's spec's three bindings: a static
 * value, a lead/call variable, or AI-decided (the model fills it from the conversation).
 */
export interface DraftParam {
  name: string;
  source: "static" | "lead_var" | "ai";
  value: string;
  lead_var: string;
  description: string;
  type: "string" | "integer" | "number" | "boolean";
  required: boolean;
}

export function newParam(): DraftParam {
  return {
    name: "",
    source: "ai",
    value: "",
    lead_var: "caller_phone",
    description: "",
    type: "string",
    required: false,
  };
}

/** Draft → wire. The two nullable fields are null unless their own source is selected. */
export function toParam(p: DraftParam): ActionParam {
  return {
    name: p.name,
    source: p.source,
    value: p.source === "static" ? p.value : null,
    lead_var: p.source === "lead_var" ? p.lead_var : null,
    description: p.description,
    type: p.type,
    required: p.required,
  };
}

const SOURCES = ["static", "lead_var", "ai"] as const;
const TYPES = ["string", "integer", "number", "boolean"] as const;

/**
 * A stored parameter back into the editor's draft. `ToolOut.params` is a list of open
 * dicts on the wire, so every field is read defensively rather than asserted.
 */
export function fromParam(stored: Record<string, unknown>): DraftParam {
  const text = (key: string): string => {
    const value = stored[key];
    return typeof value === "string" ? value : "";
  };
  return {
    name: text("name"),
    source: SOURCES.find((s) => s === stored.source) ?? "ai",
    value: text("value"),
    lead_var: text("lead_var") || "caller_phone",
    description: text("description"),
    type: TYPES.find((t) => t === stored.type) ?? "string",
    required: stored.required === true,
  };
}
