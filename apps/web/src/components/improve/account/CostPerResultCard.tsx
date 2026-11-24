"use client";

/**
 * COST PER RESULT: what each campaign's and line's calls cost against the goals they reached,
 * from the usage charges on your credit ledger, in rupees as the server rounded them (hard
 * rule 7: the figures arrive as decimal strings and are never added up here). A role that may
 * not see billing is told so instead of shown dashes.
 */

import { RestrictionNote, formatCount, formatINR } from "@/components/ui";
import type { HolderRow } from "@/lib/api/accountImprove";

import { ImproveCard } from "../ImproveCard";
import { Quiet, WithAccountImprove } from "./shared";

export const COST_TITLE = "Cost per result";

/** Cheapest goal first; holders that spent and reached none after, most spent first. */
function ranked(holders: HolderRow[]): HolderRow[] {
  const spent = holders.filter((h) => h.spend_inr !== null && Number(h.spend_inr) > 0);
  const withGoals = spent
    .filter((h) => h.cost_per_goal_inr !== null)
    .sort((a, b) => Number(a.cost_per_goal_inr) - Number(b.cost_per_goal_inr));
  const without = spent
    .filter((h) => h.cost_per_goal_inr === null)
    .sort((a, b) => Number(b.spend_inr) - Number(a.spend_inr));
  return [...withGoals, ...without];
}

export function CostPerResultCard() {
  return (
    <ImproveCard
      headingLevel={2}
      title={COST_TITLE}
      hint="What your calls cost for each goal reached."
      info="The charges for each campaign's and line's calls, divided by the goals they reached."
    >
      <WithAccountImprove label="Working out what each result cost">
        {({ compare, window_days }) => {
          if (compare.total_spend_inr === null) {
            return <RestrictionNote reason="Only people who can see billing see what results cost." />;
          }
          const rows = ranked(compare.holders);
          if (rows.length === 0) {
            return <Quiet>Nothing spent on calls in the last {window_days} days.</Quiet>;
          }
          return (
            <>
              <p className="mb-3 text-body text-ink">
                {compare.total_cost_per_goal_inr === null ? (
                  <>
                    {formatINR(compare.total_spend_inr)} spent, no goal reached yet, last {window_days} days.
                  </>
                ) : (
                  <>
                    <span className="font-semibold tabular-nums">{formatINR(compare.total_cost_per_goal_inr)}</span> per
                    goal reached, last {window_days} days.
                  </>
                )}
              </p>
              <ul className="divide-y divide-line" aria-label={COST_TITLE}>
                {rows.map((h) => (
                  <li key={h.id} className="flex items-baseline justify-between gap-4 py-2 first:pt-0">
                    <span className="min-w-0 text-body text-ink [overflow-wrap:anywhere]">{h.name}</span>
                    <span className="shrink-0 text-right text-meta text-ink-muted tabular-nums">
                      {h.cost_per_goal_inr === null ? (
                        <>{formatINR(h.spend_inr)} spent, no goal yet</>
                      ) : (
                        <>
                          <span className="font-semibold text-ink">{formatINR(h.cost_per_goal_inr)}</span> a goal ·{" "}
                          {formatCount(h.goals)} {h.goals === 1 ? "goal" : "goals"}
                        </>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          );
        }}
      </WithAccountImprove>
    </ImproveCard>
  );
}
