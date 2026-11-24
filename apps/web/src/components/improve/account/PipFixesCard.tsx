"use client";

/**
 * PIP'S FIXES, IN ONE FEED: the changes made on their own across the account in the window:
 * script repairs, step outcomes written, notices woven into an opening (`script_versions`),
 * calling hours narrowed to the best block and an opening test's winner applied. Each opens
 * where it can be put back: a script change the campaign's or line's Versions, narrowed hours
 * the campaign's Improve tab (its Best hours Undo), because hours are a setting, not a version.
 */

import Link from "next/link";

import { TEXT_ACTION_SM } from "@/components/console/section";
import { formatIST } from "@/components/ui";
import { holderImproveHref, holderVersionsHref, type PipFix } from "@/lib/api/accountImprove";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { ImproveCard } from "../ImproveCard";
import { Quiet, WithAccountImprove, type AccountCardProps } from "./shared";

export const FIXES_TITLE = `${ASSISTANT_NAME}'s fixes`;

function fixWords(fix: PipFix): string {
  switch (fix.kind) {
    case "pip_repair":
      return "Repaired lines the script checks found";
    case "pip_outcomes":
      return "Wrote the outcome of steps that had none";
    case "pip_notices":
      return "Added the notices to the opening line";
    case "best_hours":
      return fix.detail ? `Set the calling hours to ${fix.detail.replace("-", " to ")}` : "Set the best calling hours";
    case "opening_winner":
      return "Made the winning opening the one every call uses";
  }
}

export function PipFixesCard({ slug }: AccountCardProps) {
  const { href } = useClientRealm();
  return (
    <ImproveCard
      headingLevel={2}
      title={FIXES_TITLE}
      hint={`What ${ASSISTANT_NAME} changed on its own. Each can be put back.`}
    >
      <WithAccountImprove label={`Reading ${ASSISTANT_NAME}'s fixes`}>
        {({ fixes, window_days }) =>
          fixes.length === 0 ? (
            <Quiet>No changes made on their own in the last {window_days} days.</Quiet>
          ) : (
            <ul className="divide-y divide-line" aria-label={FIXES_TITLE}>
              {fixes.map((fix) => (
                <li
                  key={`${fix.kind}-${fix.holder_id}-${fix.at}`}
                  className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 first:pt-0"
                >
                  <div className="min-w-0">
                    <p className="text-body text-ink">{fixWords(fix)}</p>
                    <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">
                      {fix.holder_name} · {formatIST(fix.at)}
                    </p>
                  </div>
                  {fix.kind === "best_hours" ? (
                    <Link
                      href={href(holderImproveHref(slug, { kind: fix.holder_kind, id: fix.holder_id }))}
                      className={`${TEXT_ACTION_SM} -mx-2`}
                      aria-label={`Open the calling hours of ${fix.holder_name}`}
                    >
                      Calling hours
                    </Link>
                  ) : (
                    <Link
                      href={href(holderVersionsHref(slug, { kind: fix.holder_kind, id: fix.holder_id }))}
                      className={`${TEXT_ACTION_SM} -mx-2`}
                      aria-label={`Open the versions of ${fix.holder_name}`}
                    >
                      Versions
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )
        }
      </WithAccountImprove>
    </ImproveCard>
  );
}
