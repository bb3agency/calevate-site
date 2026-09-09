/**
 * Why a number is on the suppression list, in the client's words — the one table the
 * Add form, the list rows and the assistant declaration all read.
 *
 * The values are the API's. Keeping the words here rather than in three components is
 * what stops the Add form offering a reason the list cannot name back.
 */

import { type DncSource } from "@/lib/api/dnc";

/** Read through `lookup()`: `DncEntryOut.source` is `string | null` on the wire. */
export const SOURCE_COPY: Record<string, { label: string; hint: string }> = {
  manual: { label: "Added by your team", hint: "Someone here typed or pasted it in." },
  customer_request: {
    label: "They asked us to stop",
    hint: "A request from the person themselves.",
  },
  call_optout: {
    label: "Opted out on a call",
    hint: "They told the agent not to call again.",
  },
  regulator: { label: "Regulator list", hint: "Suppressed by a regulator's list." },
};

/**
 * The four reasons, ordered by how often they are used. Only `manual` is reversible —
 * that is `REMOVABLE_SOURCES` on the server, and the form says it out loud, because
 * picking the wrong reason here is a decision that cannot be taken back from this screen.
 */
export const SOURCE_OPTIONS: { value: DncSource; label: string; note: string }[] = [
  {
    value: "manual",
    label: "Added by your team",
    note: "You can remove these again from the list below.",
  },
  {
    value: "customer_request",
    label: "They asked us to stop",
    note: "Permanent — a person's request cannot be undone from here.",
  },
  {
    value: "call_optout",
    label: "They opted out on a call",
    note: "Permanent — a person's request cannot be undone from here.",
  },
  {
    value: "regulator",
    label: "From a regulator's list",
    note: "Permanent — remove it through support if it is wrong.",
  },
];
