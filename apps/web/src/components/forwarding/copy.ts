/**
 * The words the forwarding screens use (D-746). Plain, from the client's side, no vendor
 * named, and not clinic-specific: "callers", "your business".
 *
 * What is NOT stated as fact here, because no carrier page confirms it for Indian networks:
 * that a switched-off or flight-mode phone forwards at once, that Wi-Fi calling keeps a
 * phone reachable, that pressing decline forwards a call, and that each network honours the
 * ring time. Those are in `SELF_CHECKS`: things to try during the test, not promises.
 */

import type { Carrier, ForwardingMode, ForwardedLine, ForwardingTest, LineKind } from "@/lib/api/forwarding";
import type { NoticeTone } from "@/components/ui";

export const CARRIER_LABEL: Record<Carrier, string> = {
  airtel: "Airtel",
  jio: "Jio",
  vi: "Vi",
  bsnl: "BSNL",
  other: "Another provider",
};

export const LINE_KIND_LABEL: Record<LineKind, string> = {
  mobile: "Mobile (SIM)",
  landline: "Landline",
  office_system: "Office phone system",
};

export const MODE_COPY: Record<ForwardingMode, { title: string; line: string }> = {
  conditional: {
    title: "Your phone rings first",
    line: "Your agent answers calls you miss, calls while you are busy, and calls when your phone is off.",
  },
  all_calls: {
    title: "Your agent answers every call",
    line: "Your phone does not ring for calls to this number.",
  },
};

/** "Rings 20 seconds first" or "Straight to your agent". */
export function modeSummary(mode: ForwardingMode, seconds: number): string {
  return mode === "all_calls" || seconds === 0
    ? "Every call goes straight to your agent"
    : `Rings ${seconds} seconds first, then your agent answers`;
}

export const CONDITION_LABEL: Record<string, string> = {
  no_answer: "When you don't answer",
  busy: "When you are busy or press decline",
  unreachable: "When your phone is off or has no signal",
  all_calls: "Every call",
  all_conditional: "Switch off the three above",
  everything: "Switch off all forwarding",
  disputed: "Sites disagree on what this does",
};

export const STATUS_COPY: Record<ForwardedLine["status"], { text: string; tone: NoticeTone }> = {
  untested: { text: "Not tested", tone: "warn" },
  testing: { text: "Testing", tone: "neutral" },
  working: { text: "Working", tone: "ok" },
  not_working: { text: "Not working", tone: "stop" },
};

export const CALLER_ID_COPY: Record<NonNullable<ForwardedLine["caller_id_finding"]>, string> = {
  caller_shown: "Your agent sees the caller's own number.",
  business_number_shown:
    "Your network shows your number instead of the caller's, so your agent asks callers for a number to call back on.",
  other_number_shown:
    "A call reached your agent from a different number. If nobody else rang you just then, your network shows another number.",
};

export const CONCURRENCY_COPY: Record<NonNullable<ForwardedLine["concurrency_finding"]>, string> = {
  both_arrived: "Two calls at the same time both reached your agent.",
  one_arrived: "Only one of two calls at the same time reached your agent. Your line may take one call at a time.",
  not_tested: "Two calls at the same time were not tested.",
};

export const OUTCOME_COPY: Record<NonNullable<ForwardingTest["outcome"]>, { text: string; tone: NoticeTone }> = {
  arrived: { text: "The test call reached your agent.", tone: "ok" },
  not_arrived: { text: "The test call did not reach your agent. Check the forward is switched on.", tone: "stop" },
  answered_on_phone: {
    text: "The test call was answered on your phone, so it was not forwarded. Let it ring next time.",
    tone: "warn",
  },
  not_placed: { text: "We could not place the test call. Try again in a few minutes.", tone: "stop" },
};

/** What to try during a test, because no carrier confirms these for India. */
export const SELF_CHECKS: string[] = [
  "Let the test call ring without answering. It should reach your agent after the ring time.",
  "Run it again and press decline when it rings. It should reach your agent at once.",
  "Switch the phone off and run it again. If your phone still takes the call, turn Wi-Fi calling off on it.",
];

export const RING_TIME_INFO =
  "Phone networks take 5 to 30 seconds. 0 means your phone does not ring: calls go straight to your agent, so you get the all-calls code. Some networks use their own ring time; the test shows what yours does.";
