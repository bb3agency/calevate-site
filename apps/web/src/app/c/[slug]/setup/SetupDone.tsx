"use client";

import Link from "next/link";
import { ArrowRight, CircleCheck } from "lucide-react";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";
import { STEPS, stepStates, type BusinessProfile, type StepId } from "@/lib/api/businessProfile";

/**
 * The last screen of the wizard: what is answered, what was skipped, and whether anything
 * still stops an agent going live — each with a way straight back to its step.
 */
export function SetupDone({
  profile,
  href,
  onOpen,
}: {
  profile: BusinessProfile;
  href: (path: string) => string;
  onOpen: (step: StepId) => void;
}) {
  const states = stepStates(profile);
  const items: ChecklistItem[] = STEPS.map((step) => ({
    id: step.id,
    label: step.short,
    state: states[step.id] === "todo" ? "todo" : "done",
    detail: states[step.id] === "skipped" ? "Skipped" : undefined,
    action:
      states[step.id] === "done" ? undefined : (
        <button
          type="button"
          onClick={() => onOpen(step.id)}
          className="inline-flex items-center gap-1 rounded-sm text-[13px] font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          {states[step.id] === "skipped" ? "Answer now" : "Open"}
          <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </button>
      ),
  }));
  const ready = profile.blockers.length === 0;
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <CircleCheck aria-hidden className={`mt-0.5 h-5 w-5 shrink-0 ${ready ? "text-brand-strong" : "text-ink-faint"}`} />
        <div>
          <h2 className="text-[18px] font-semibold tracking-tight text-ink">
            {ready ? "Your agents have what they need" : "Almost there"}
          </h2>
          <p className="mt-1 text-sm text-ink-muted">
            {ready
              ? "Every agent now answers with these facts. Change them any time."
              : `Before an agent can take calls: ${profile.blockers.map((b) => b.message.replace(/\.$/, "").toLowerCase()).join(", ")}.`}
          </p>
        </div>
      </div>
      <Checklist label="Business setup" items={items} />
      <div className="flex flex-wrap gap-2">
        <Link href={href("")} className={PRIMARY_BUTTON}>
          Go to dashboard
        </Link>
        <Link href={href("/settings/business")} className={SECONDARY_BUTTON}>
          Review business profile
        </Link>
      </div>
    </div>
  );
}
