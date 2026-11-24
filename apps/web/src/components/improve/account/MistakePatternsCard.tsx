"use client";

/**
 * MISTAKES ACROSS CAMPAIGNS: a call-mistake kind found on two or more campaigns or lines in
 * the window (`call_mistakes`, D-949). One script cannot be the cause of a mistake many
 * scripts share, so it points at the agent's settings and Company training, where every
 * campaign's calls are fixed at once; each campaign's own Improve lists its own mistakes.
 */

import Link from "next/link";

import { TEXT_ACTION_SM } from "@/components/console/section";
import { formatCount } from "@/components/ui";
import { companyTrainingHref } from "@/lib/api/accountImprove";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard } from "../ImproveCard";
import { Quiet, WithAccountImprove, holdersWord, type AccountCardProps } from "./shared";

export const PATTERNS_TITLE = "Mistakes across campaigns";

export function MistakePatternsCard({ slug }: AccountCardProps) {
  const { href } = useClientRealm();
  return (
    <ImproveCard
      headingLevel={2}
      title={PATTERNS_TITLE}
      hint="Mistakes that show up on more than one campaign or line."
      info="When many scripts share a mistake, the fix is in the agent or the company training."
    >
      <WithAccountImprove label="Reading mistakes across your campaigns">
        {({ patterns, compare, window_days }) => {
          if (compare.holders.length < patterns.min_holders) {
            return <Quiet>This needs calls on two or more campaigns or lines.</Quiet>;
          }
          if (patterns.patterns.length === 0) {
            return <Quiet>No mistake shows on more than one campaign or line in the last {window_days} days.</Quiet>;
          }
          return (
            <ul className="divide-y divide-line" aria-label={PATTERNS_TITLE}>
              {patterns.patterns.map((p) => (
                <li key={p.kind} className="py-2.5 first:pt-0">
                  <p className="text-body text-ink [overflow-wrap:anywhere]">{p.label}</p>
                  <p className="text-meta text-ink-muted tabular-nums">
                    {formatCount(p.calls)} {p.calls === 1 ? "call" : "calls"} on {holdersWord(p.holders)}. Likely the
                    agent or company training, not one script.
                  </p>
                  <div className="mt-1 flex flex-wrap gap-x-1">
                    {p.agents.map((a) => (
                      <Link
                        key={a.id}
                        href={href(`/c/${slug}/agents/${encodeURIComponent(a.id)}`)}
                        className={`${TEXT_ACTION_SM} -mx-2`}
                        aria-label={`Open ${a.name}'s settings: ${p.label}`}
                      >
                        {a.name}&apos;s settings
                      </Link>
                    ))}
                    <Link
                      href={href(companyTrainingHref(slug))}
                      className={`${TEXT_ACTION_SM} -mx-2`}
                      aria-label={`Open Company training: ${p.label}`}
                    >
                      Company training
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          );
        }}
      </WithAccountImprove>
    </ImproveCard>
  );
}
