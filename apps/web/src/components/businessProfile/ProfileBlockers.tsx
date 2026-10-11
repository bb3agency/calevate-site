"use client";

import { ChecklistRows } from "@/components/console/checklist";
import { setupHref, stepCopy, type StepId } from "@/lib/api/businessProfile";

export interface ProfileBlocker {
  code: string;
  step: StepId;
  message: string;
}

/**
 * "Finish your business profile": what still stops an agent taking calls, each with a link
 * to the setup step that fixes it. Rendered wherever going live can be refused for it, so
 * the refusal is never a silent failure.
 */
export function ProfileBlockers({
  blockers,
  href,
  title = "Finish your business profile",
  lead = "Your agents need these before they can take calls.",
}: {
  blockers: readonly ProfileBlocker[];
  href: (path: string) => string;
  title?: string;
  lead?: string;
}) {
  if (blockers.length === 0) return null;
  return (
    <ChecklistRows
      heading={title}
      tone="warn"
      summary={lead}
      rows={blockers.map((blocker) => ({
        id: blocker.code,
        label: stepCopy(blocker.step).short,
        status: "not_started",
        statusText: "To do",
        info: blocker.message,
        link: { href: setupHref(href, blocker.step), label: "Open" },
      }))}
    />
  );
}

/** The blockers carried by a refused go-live (`business_profile_incomplete`), read off the
 *  problem's fields, or an empty list for any other refusal. */
export function blockersFromProblem(
  code: string | undefined,
  fields: readonly { field: string; rule: string; message: string }[] | undefined,
): ProfileBlocker[] {
  if (code !== "business_profile_incomplete" || !fields) return [];
  return fields
    .filter((f) => f.field.startsWith("setup."))
    .map((f) => ({ code: f.rule, step: f.field.slice("setup.".length) as StepId, message: f.message }));
}
