/**
 * The three answers, as the person on the phone would put them — and the two that are a
 * "no", which is the narrowing the record form and the assistant declaration share.
 */

import { type ConsentStatus } from "@/lib/api/messagingConsent";

export const STATUS_COPY: Record<ConsentStatus, { label: string; hint: string }> = {
  granted: {
    label: "Yes — they agreed to be messaged",
    hint: "An opt-in. It has to record what it rests on, and it stops being current after a year.",
  },
  declined: {
    label: "No — they were asked and said no",
    hint: "Recorded so nobody asks again, and so an audit can show they were asked.",
  },
  withdrawn: {
    label: "Stop — they asked us not to message them",
    hint: "Takes effect from now. The earlier record is kept; this one supersedes it.",
  },
};

export const NO_STATUSES: ConsentStatus[] = ["declined", "withdrawn"];
