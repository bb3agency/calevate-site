/**
 * HOW A LEAD IS NAMED ON SCREEN — the words for its source, its stage's provenance and its
 * call count, and which name to show. React-free, so the leads table, the phone list and
 * the lead's own page read a lead the same way and a test drives it without a render.
 */

import { formatIST, formatPhone } from "@/components/ui";
import type { Lead } from "@/lib/api/leads";
import { lookup } from "@/lib/lookup";

/** Where a lead came from, in the owner's words (first-call review, F-7). */
const SOURCE_LABELS: Record<Lead["source"], string> = {
  inbound_call: "Incoming call",
  outbound_call: "Outgoing call",
  test_call: "Test call",
  campaign: "Campaign",
  webhook: "Website form",
  manual: "Import",
};

/** An unknown source is shown as it came rather than dropped (`lookup`). */
export function sourceLabel(source: string): string {
  return lookup(SOURCE_LABELS, source) ?? source.replace(/_/g, " ");
}

/** The name a lead goes by: its name, or its number when nobody has given one. */
export function leadTitle(lead: Pick<Lead, "name" | "phone_e164">): string {
  return lead.name?.trim() || formatPhone(lead.phone_e164);
}

/** "Called 3 times" for a lead that has called more than once; nothing otherwise. */
export function calledTimes(callCount: number): string | null {
  return callCount > 1 ? `Called ${callCount.toLocaleString("en-IN")} times` : null;
}

/**
 * Who put the lead in its stage. The rules after a call never move a stage backwards and
 * never over a person's choice, so an owner needs to see which of the two they are
 * looking at before they trust it.
 */
export function stageSetBy(setBy: Lead["status_set_by"]): string {
  return setBy === "person" ? "Set by your team" : "Set after a call";
}

/**
 * What happens next for a lead: the soonest live call back when there is one, otherwise
 * the next step its last call suggested.
 */
export function leadNextStep(lead: Pick<Lead, "next_callback_at" | "next_step">): string | null {
  if (lead.next_callback_at) return `Call back ${formatIST(lead.next_callback_at)}`;
  return lead.next_step?.trim() || null;
}

/**
 * The columns a lead list shows before anyone chooses: who, what they want, what is next,
 * what the last call came to, and the stage. Business fields and the rest wait in the
 * column chooser. `need` is the core field `calevate_shared.lead_fields.NEED_KEY` names
 * (served as `LeadFieldsOut.need_key`).
 */
export const DEFAULT_LEAD_COLUMNS: readonly string[] = ["name", "need", "next_step", "last_call", "status"];

/** A captured value as words, or `null` when the caller did not say it ("Not said"). */
export function capturedValue(field: { value?: unknown }): string | null {
  const { value } = field;
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : null;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
