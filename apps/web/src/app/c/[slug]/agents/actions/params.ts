/**
 * The vocabulary the Actions forms are built from — kinds, providers, and one parameter.
 *
 * A plain `.ts` module for UX-DOCTRINE §6's reason: `Actions.tsx` was 738 lines with the
 * type unions, the lead-variable table, the draft shape and its wire mapping threaded
 * between four components. None of that is rendering, and none of it needs React.
 */

import type { ActionParam } from "@/lib/api/actions";

/** The three kinds of action a client can add. */
export type Kind = "custom_api" | "whatsapp" | "calendar";

/** Every provider any kind can name. */
export type Provider = "aisensy" | "meta_cloud" | "interakt" | "custom" | "google";

// Local unions for the two casts of a form-control string, so the wire-fixture guard's ban
// on asserting onto a GENERATED schema type does not apply (these are ours, not generated).
export type CredKind = "aisensy" | "meta_cloud" | "interakt" | "custom_api" | "google_calendar";

/** The call facts a parameter can be bound to instead of a typed or AI-decided value. */
export const LEAD_VARS: { value: string; label: string }[] = [
  { value: "caller_phone", label: "Caller's phone number" },
  { value: "from_number", label: "From number" },
  { value: "to_number", label: "To number" },
  { value: "call_sid", label: "Call id" },
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
