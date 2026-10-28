/**
 * The three answers, as the person on the phone would put them — and the two that are a
 * "no", which is the narrowing the record form and the assistant declaration share.
 */

import { type ConsentStatus } from "@/lib/api/messagingConsent";

export const STATUS_COPY: Record<ConsentStatus, { label: string; hint: string }> = {
  granted: {
    label: "Yes — they agreed to be messaged",
    hint: "Needs proof, and it stops being current after a year.",
  },
  declined: {
    label: "No — they were asked and said no",
    hint: "Saved so nobody asks again.",
  },
  withdrawn: {
    label: "Stop — they asked us not to message them",
    hint: "Starts now. The earlier record is kept.",
  },
};

export const NO_STATUSES: ConsentStatus[] = ["declined", "withdrawn"];
