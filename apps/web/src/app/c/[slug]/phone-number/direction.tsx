"use client";

/**
 * WHAT A NUMBER IS FOR — the three legs, worded once for the two screens that ask: the
 * purchase, which records an intent, and the assignment, which puts the number on an
 * agent. The choice records an intent and authorises nothing. Who may call out is the
 * campaign launch gate's question (verified business and the no-cold-calls pledge, D-692);
 * no confirmation per number is asked since D-775.
 */

import type { CallDirection } from "@/lib/api/numberProvisioning";

/** The three legs, in the order a client meets them — answering first. */
export const DIRECTIONS: { value: CallDirection; label: string; hint: string }[] = [
  {
    value: "inbound",
    label: "Answer calls to this number",
    hint: "Anyone who rings it reaches your agent.",
  },
  {
    value: "outbound",
    label: "Call out from this number",
    hint: "Your agent dials from it: reminders, follow-ups and call-backs.",
  },
  {
    value: "both",
    label: "Both",
    hint: "It answers callers, and your agent dials out from it.",
  },
];

