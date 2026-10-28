"use client";

/**
 * THE TWO PIECES THE BUILD FLOW IS MADE OF besides its questions — the call cap, and the
 * compliance floor. Neither is about creating an agent: one is a bounded server-driven
 * field, the other a statement of what every agent is born with.
 */

import { ShieldCheck } from "lucide-react";

import { NumberField } from "@/components/arc/number-field";
import { Disclosure, Skeleton, formatCallCap } from "@/components/ui";
import type { useLanes } from "@/lib/api/publishing";

import { NEW_AGENT } from "../../setup/_ui/copy";
import { Why } from "@/components/why";

/**
 * The cost-runaway guard, asked at creation in minutes, closed by default with the
 * standard limit named in its closed state.
 *
 * Every bound is the server's: the field does not render until `GET /v1/agents/lanes`
 * answers, because a minimum and maximum this build invented are numbers a client would be
 * refused on with no way to know why. The step's `validate` checks the range.
 */
export function CallCapField({
  lanes,
  value,
  onChange,
}: {
  lanes: ReturnType<typeof useLanes>;
  value: string;
  onChange: (next: string) => void;
}) {
  if (lanes.isLoading) return <Skeleton rows={1} />;
  if (!lanes.data) return null;
  const { call_cap_default_s, call_cap_min_s, call_cap_max_s } = lanes.data;
  return (
    <Disclosure
      title="Longest one call may run"
      subtitle={
        value.trim() === ""
          ? NEW_AGENT.capSubtitleDefault(formatCallCap(call_cap_default_s))
          : `${value.trim()} minutes`
      }
    >
      <NumberField
        className="max-w-sm"
        label="Minutes (optional)"
        hint={NEW_AGENT.capHint(formatCallCap(call_cap_min_s), formatCallCap(call_cap_max_s))}
        unit="minutes"
        optional
        min={Math.ceil(call_cap_min_s / 60)}
        max={Math.floor(call_cap_max_s / 60)}
        // The flow keeps the typed minutes as a string ("" = the standard limit), which the
        // review step and the assistant's fill both read; the field speaks numbers.
        value={value.trim() === "" || !Number.isFinite(Number(value)) ? null : Number(value)}
        onChange={(next) => onChange(next === null ? "" : String(next))}
      />
      <Why className="mt-2">
        Blank means the standard {formatCallCap(call_cap_default_s)}. It cannot be removed: it stops one stuck
        call running up a bill.
      </Why>
    </Disclosure>
  );
}

/** The range check for the step, in the field's own terms; `null` when it is fine. */
export function callCapProblem(lanes: ReturnType<typeof useLanes>, value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === "" || !lanes.data) return null;
  const minutes = Number(trimmed);
  const min = Math.ceil(lanes.data.call_cap_min_s / 60);
  const max = Math.floor(lanes.data.call_cap_max_s / 60);
  if (!Number.isInteger(minutes) || minutes < min || minutes > max) {
    return NEW_AGENT.capProblem(min, max);
  }
  return null;
}

/**
 * What every agent is born saying about itself: its greeting only, with both announcements
 * off (D-669) and the truthful answer always on. Shown before the agent exists so nobody
 * discovers it on a recording.
 */
export function ComplianceFloor() {
  return (
    <section aria-labelledby="compliance-floor-heading" className="border-t border-line pt-4">
      <p id="compliance-floor-heading" className="flex items-center gap-2 text-sm font-semibold text-ink">
        <ShieldCheck aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
        {NEW_AGENT.floorTitle}
      </p>
      {/* Hard rule 5's floor stays on screen, one short line each; only the detail waits
          behind the tap. */}
      <ul className="mt-2 space-y-1.5 text-sm text-ink-muted">
        {NEW_AGENT.floor.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <Why className="mt-1" label="How this works">
        <p>
          With an announcement on, it says it is an AI assistant, or that the call is being recorded,
          just before the greeting. You can switch either announcement on later, on the agent&apos;s own
          screen. Both sentences are already written in your language.
        </p>
        <p>The honest answer cannot be switched off by you, by us, or by its script.</p>
      </Why>
    </section>
  );
}
