"use client";

/**
 * THE TWO PIECES THE BUILD FLOW IS MADE OF besides its questions — the call cap, and the
 * compliance floor. Neither is about creating an agent: one is a bounded server-driven
 * field, the other a statement of what every agent is born with.
 */

import { ShieldCheck } from "lucide-react";

import { Disclosure, FIELD, FIELD_HINT, FIELD_LABEL, Skeleton, formatCallCap } from "@/components/ui";
import type { useLanes } from "@/lib/api/publishing";

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
          ? `${formatCallCap(call_cap_default_s)} (the standard limit)`
          : `${value.trim()} minutes`
      }
    >
      <label className="block max-w-sm">
        <span className={FIELD_LABEL}>Minutes (optional)</span>
        <input
          type="number"
          inputMode="numeric"
          min={Math.ceil(call_cap_min_s / 60)}
          max={Math.floor(call_cap_max_s / 60)}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={String(Math.round(call_cap_default_s / 60))}
          className={FIELD}
        />
        <span className={FIELD_HINT}>
          In minutes. Leave it blank for the standard {formatCallCap(call_cap_default_s)}. It
          can be anywhere between {formatCallCap(call_cap_min_s)} and{" "}
          {formatCallCap(call_cap_max_s)}, and there is no way to remove it — it is what stops
          one stuck call running up a bill.
        </span>
      </label>
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
    return `Enter a whole number of minutes between ${min} and ${max}, or leave it blank.`;
  }
  return null;
}

/**
 * What every agent is born saying. Three sentences, word for word, shown before the
 * agent exists so nobody discovers them on a recording.
 */
export function ComplianceFloor() {
  return (
    <section aria-labelledby="compliance-floor-heading" className="border-t border-line pt-4">
      <p id="compliance-floor-heading" className="flex items-center gap-2 text-sm font-semibold text-ink">
        <ShieldCheck aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
        What it will say about itself
      </p>
      <ul className="mt-2 space-y-1.5 text-sm text-ink-muted">
        <li>
          It starts every call by saying it is an AI assistant and that the call is being
          recorded. Both sentences are written for you in the language you chose.
        </li>
        <li>
          You can switch either announcement off later, per agent, on the agent&apos;s own
          screen — the two are separate obligations and are separately switchable.
        </li>
        <li>
          Whatever those switches say, it always answers honestly when a caller asks
          whether it is an AI or whether the call is recorded. That one cannot be switched
          off by you, by us, or by anything written in its script.
        </li>
      </ul>
    </section>
  );
}
