"use client";

/**
 * COMPARE YOUR CAMPAIGNS: every campaign and line with calls in the window, side by side on
 * the figures their own Improve tabs use, the best one named once two or more have enough
 * answered calls, and what is measurably different about it (its opening's length, its step
 * count, its calling hours), each computed from the scripts and settings, never guessed.
 * "Use what works" asks Pip for a draft of another campaign's or line's script with that
 * difference named; the draft waits there for the owner to keep or discard.
 */

import Link from "next/link";
import { useId, useState } from "react";

import { TEXT_ACTION_SM } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { FIELD, ScrollRegion, formatCount, formatINR } from "@/components/ui";
import {
  holderImproveHref,
  holderOf,
  type AccountImprove,
  type Difference,
  type HolderRow,
} from "@/lib/api/accountImprove";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { AskPipFix } from "../AskPipFix";
import { ImproveCard, percent } from "../ImproveCard";
import { Quiet, WithAccountImprove, type AccountCardProps } from "./shared";

export const COMPARE_TITLE = "Compare your campaigns";

const DIFFERENCE_WORDS: Record<Difference["kind"], string> = {
  opening_length: "Opening line",
  step_count: "Steps in the script",
  calling_hours: "Calling hours",
};

export function CompareCard({ slug }: AccountCardProps) {
  return (
    <ImproveCard
      headingLevel={2}
      title={COMPARE_TITLE}
      hint="Your campaigns and lines side by side, and what the best one does differently."
      info="Each figure needs enough calls first. A dash means too few to say."
    >
      <WithAccountImprove label="Comparing your campaigns">
        {(data) => <CompareBody slug={slug} data={data} />}
      </WithAccountImprove>
    </ImproveCard>
  );
}

function rate(value: number | null): string {
  return value === null ? "—" : percent(value);
}

function CompareBody({ slug, data }: { slug: string; data: AccountImprove }) {
  const { href } = useClientRealm();
  const { compare, window_days } = data;
  if (compare.holders.length === 0) {
    return <Quiet>No campaign or line has calls in the last {window_days} days.</Quiet>;
  }
  const best = compare.holders.find((h) => h.id === compare.best_id) ?? null;
  return (
    <>
      {best ? (
        <p className="mb-3 text-body text-ink">
          Best: <span className="font-medium">{best.name}</span>, reaching its goal on {rate(best.goal_rate)} of
          answered calls.
        </p>
      ) : (
        <p className="mb-3 text-meta text-ink-muted">
          Too few calls to name a best one yet: two or more need {formatCount(compare.min_answered)} answered
          calls each.
        </p>
      )}
      <ScrollRegion label="Your campaigns and lines compared">
        <table className="w-full min-w-[36rem] text-left text-meta">
          <caption className="sr-only">
            Your campaigns and lines, last {window_days} days, most answered calls first
          </caption>
          <thead className="text-ink-muted">
            <tr className="border-b border-line">
              <th scope="col" className="py-2 pr-3 font-medium">Campaign or line</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Answered</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Stop early</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Goal reached</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Hang up in {compare.early_seconds}s</th>
              <th scope="col" className="py-2 text-right font-medium">Per goal</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line tabular-nums">
            {compare.holders.map((h) => (
              <tr key={h.id} className={h.id === compare.best_id ? "bg-brand-soft" : undefined}>
                <th scope="row" className="py-2 pr-3 font-normal">
                  <Link
                    href={href(holderImproveHref(slug, holderOf(h)))}
                    className="text-ink underline-offset-2 hover:underline [overflow-wrap:anywhere]"
                  >
                    {h.name}
                  </Link>
                  {h.id === compare.best_id && (
                    <StatusPill tone="ok" className="ml-2">
                      Best
                    </StatusPill>
                  )}
                </th>
                <td className="py-2 pr-3 text-right text-ink">{h.kind === "campaign" ? rate(h.answer_rate) : "—"}</td>
                <td className="py-2 pr-3 text-right text-ink">{rate(h.drop_off_share)}</td>
                <td className="py-2 pr-3 text-right text-ink">{rate(h.goal_rate)}</td>
                <td className="py-2 pr-3 text-right text-ink">{rate(h.early_rate)}</td>
                <td className="py-2 text-right text-ink">
                  {h.cost_per_goal_inr === null ? "—" : formatINR(h.cost_per_goal_inr)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      {best && compare.differences.length > 0 && (
        <UseWhatWorks slug={slug} best={best} holders={compare.holders} differences={compare.differences} />
      )}
      {best && compare.differences.length === 0 && (
        <p className="mt-3 text-meta text-ink-muted">
          Its opening, steps and hours are like the others&apos;, so the difference is in what it says.
        </p>
      )}
    </>
  );
}

function UseWhatWorks({
  slug,
  best,
  holders,
  differences,
}: {
  slug: string;
  best: HolderRow;
  holders: HolderRow[];
  differences: Difference[];
}) {
  const { session, href } = useClientRealm();
  const write = useWriteAccess(session, "leads:dispatch", "ask Pip to rewrite a script");
  const others = holders.filter((h) => h.id !== best.id);
  const [targetId, setTargetId] = useState(others[0]?.id ?? "");
  const selectId = useId();
  const target = others.find((h) => h.id === targetId) ?? null;
  return (
    <div className="mt-4 border-t border-line pt-3">
      <h3 className="text-body font-medium text-ink">What {best.name} does differently</h3>
      <ul className="mt-2 space-y-1.5" aria-label={`What ${best.name} does differently`}>
        {differences.map((d) => (
          <li key={d.kind} className="text-meta text-ink">
            <span className="text-ink-muted">{DIFFERENCE_WORDS[d.kind]}:</span> {d.best}; the others {d.others}.
          </li>
        ))}
      </ul>
      {target && (
        <div className="mt-3 space-y-3">
          <label htmlFor={selectId} className="block text-meta font-medium text-ink">
            Use what works on
          </label>
          <select
            id={selectId}
            className={`${FIELD} max-w-sm`}
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
          >
            {others.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
          {differences.map((d) =>
            d.instruction ? (
              <div key={d.kind}>
                <p className="mb-1.5 text-meta text-ink-muted">
                  {ASSISTANT_NAME} drafts it; you keep or discard the draft.
                </p>
                <AskPipFix
                  key={`${d.kind}-${target.id}`}
                  holder={holderOf(target)}
                  instruction={d.instruction}
                  label={`Use what works: ${DIFFERENCE_WORDS[d.kind].toLowerCase()}`}
                  canWrite={write.allowed}
                  refusal={write.reason ?? undefined}
                />
              </div>
            ) : target.kind === "campaign" ? (
              <Link
                key={d.kind}
                href={href(`/c/${slug}/campaigns/${encodeURIComponent(target.id)}`)}
                className={`${TEXT_ACTION_SM} -mx-2`}
              >
                Change the calling hours on {target.name}
              </Link>
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}
