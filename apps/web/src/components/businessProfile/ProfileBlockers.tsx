"use client";

import Link from "next/link";
import { ArrowRight, ClipboardList } from "lucide-react";

import { NoticeBox } from "@/components/ui";
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
    <NoticeBox tone="warn" icon={<ClipboardList aria-hidden className="h-5 w-5" />} title={title}>
      <p className="mt-1">{lead}</p>
      <ul className="mt-2 space-y-1">
        {blockers.map((blocker) => (
          <li key={blocker.code}>
            <Link
              href={setupHref(href, blocker.step)}
              className="inline-flex items-center gap-1 rounded-sm font-medium underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
            >
              {stepCopy(blocker.step).short}
              <ArrowRight aria-hidden className="h-3.5 w-3.5" />
            </Link>
          </li>
        ))}
      </ul>
    </NoticeBox>
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
