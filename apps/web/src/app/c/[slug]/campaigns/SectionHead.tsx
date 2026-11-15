"use client";

import type { ReactNode } from "react";

import { InfoTip } from "@/components/console/infoTip";

/**
 * The numbered head of a campaign's set-up sections (main task, materials, script, agent and
 * start), on the new-campaign page and the campaign page alike. `hint` is one short line;
 * anything longer goes in `info`, behind the ⓘ.
 */
export function SectionHead({
  step,
  title,
  hint,
  info,
  id,
}: {
  step: number;
  title: string;
  hint: ReactNode;
  info?: ReactNode;
  id?: string;
}) {
  return (
    <div className="mb-3">
      <h2 id={id} className="text-heading text-ink">
        <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full border border-line align-[1px] text-meta font-semibold tabular-nums text-ink-muted">
          {step}
        </span>
        {title}
      </h2>
      <p className="mt-1 flex items-center gap-1 text-meta text-ink-muted">
        <span className="block">{hint}</span>
        {info && (
          <InfoTip label={title.toLowerCase()} align="start">
            {info}
          </InfoTip>
        )}
      </p>
    </div>
  );
}
