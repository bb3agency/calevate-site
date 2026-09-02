"use client";

/**
 * THE TWO PANELS THE BUILD FORM IS MADE OF — the call cap, and the compliance floor.
 *
 * Split out of `new/page.tsx` (UX-DOCTRINE §6: a route module may export only `default`,
 * so it cannot be split by extraction and the answer is to keep almost nothing in it).
 * Neither of these is about creating an agent; one is a bounded server-driven field and the
 * other is a statement of what every agent is born with.
 */

import { ShieldCheck } from "lucide-react";

import { FIELD, FIELD_HINT, FIELD_LABEL, NOTICE_TONES, Skeleton, formatCallCap } from "@/components/ui";
import type { FormValidation } from "@/components/formValidation";
import type { useLanes } from "@/lib/api/publishing";

/**
 * The cost-runaway guard (SURFACES §2b), asked at creation in minutes.
 *
 * Every bound is the server's. The field does not render until `GET /v1/agents/lanes`
 * answers, because a minimum and a maximum this build invented are two numbers a client
 * would be refused on with no way to know why — and a blank input over a failed read would
 * silently create the agent on the platform default while looking like a choice.
 */
export function CallCapField({
  lanes,
  value,
  onChange,
  validation,
}: {
  lanes: ReturnType<typeof useLanes>;
  value: string;
  onChange: (next: string) => void;
  /**
   * The form's validation, passed in rather than started here: a hook of its own would
   * give this field a second `onSubmit` that the form never calls, so a number outside
   * the lane's range would be refused by nobody.
   */
  validation: FormValidation;
}) {
  if (lanes.isLoading) return <Skeleton rows={2} />;
  // The refusal is rendered by the caller, above; there is nothing honest to put here.
  if (!lanes.data) return null;
  const { call_cap_default_s, call_cap_min_s, call_cap_max_s } = lanes.data;
  return (
    <div className="max-w-sm">
      <label className="block">
        <span className={FIELD_LABEL}>Longest one call may run (optional)</span>
        <input
          {...validation.field("callCap", "Enter how long one call may run, or leave it blank.")}
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
      {validation.error("callCap")}
    </div>
  );
}

/**
 * What every agent is born with, said before it is built rather than discovered after.
 *
 * Each sentence here is enforced server-side and can be pointed at: both notice lines are
 * written by `create_agent` from the language templates and are NOT NULL with non-empty
 * CHECK constraints (hard rule 5); both toggles start TRUE at the INSERT; and the truthful
 * answer is appended to every prompt by `compose_engine_prompt` and re-verified against
 * the engine on every publish and every drift sweep, so no column, config row or script
 * can withdraw it. Nothing on this panel is a claim this screen made up.
 */
export function ComplianceFloor() {
  return (
    <div className={`rounded-card border p-4 ${NOTICE_TONES.neutral}`}>
      <p className="flex items-center gap-2 text-sm font-semibold">
        <ShieldCheck aria-hidden className="h-4 w-4 shrink-0" />
        What it will say about itself
      </p>
      <ul className="mt-2 space-y-1.5 text-sm">
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
    </div>
  );
}
