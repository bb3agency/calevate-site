"use client";

/**
 * NUMBER HEALTH: the answer rate of each number the account calls from, week by week, across
 * all its campaigns (`calls.from_e164`). A number whose last week fell sharply against its
 * own four weeks before, on enough calls in both, is flagged: carriers may be labelling it
 * as spam. Below the sample it says how many calls it is waiting for.
 */

import Link from "next/link";

import { Sparkline } from "@/components/arc/sparkline";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { formatCount, formatPhone } from "@/components/ui";
import type { NumberHealth } from "@/lib/api/accountImprove";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard, percent } from "../ImproveCard";
import { Quiet, WithAccountImprove, type AccountCardProps } from "./shared";

export const NUMBER_HEALTH_TITLE = "Number health";

export function NumberHealthCard({ slug }: AccountCardProps) {
  const { href } = useClientRealm();
  return (
    <ImproveCard
      headingLevel={2}
      title={NUMBER_HEALTH_TITLE}
      hint="How often people pick up each of your numbers."
      info="A sharp drop against a number's own weeks before often means carriers show it as possible spam."
    >
      <WithAccountImprove label="Reading how often your numbers are answered">
        {({ numbers }) => {
          if (numbers.numbers.length === 0) {
            return <Quiet>No calls placed from your numbers yet.</Quiet>;
          }
          const judged = numbers.numbers.filter((n) => n.recent_rate !== null);
          const flagged = numbers.numbers.filter((n) => n.dropped);
          return (
            <>
              {flagged.length > 0 ? (
                <p className="mb-3 text-body text-ink">
                  {flagged.length === 1
                    ? "One number is being answered far less than before."
                    : `${flagged.length} numbers are being answered far less than before.`}
                </p>
              ) : judged.length === 0 ? (
                <p className="mb-3 text-meta text-ink-muted">
                  Too few calls to judge yet: each number needs {formatCount(numbers.min_recent_placed)} calls in
                  a week.
                </p>
              ) : (
                <p className="mb-3 text-meta text-ink-muted">No number has dropped against its own weeks before.</p>
              )}
              <ul className="divide-y divide-line" aria-label="Your calling numbers">
                {numbers.numbers.map((n) => (
                  <NumberRow key={n.e164} number={n} />
                ))}
              </ul>
              {flagged.length > 0 && (
                <Link href={href(`/c/${slug}/phone-number`)} className={`${TEXT_ACTION_SM} -mx-2 mt-2`}>
                  Open your phone numbers
                </Link>
              )}
            </>
          );
        }}
      </WithAccountImprove>
    </ImproveCard>
  );
}

function NumberRow({ number: n }: { number: NumberHealth }) {
  const rates = n.weeks.map((w) => (w.placed > 0 ? w.answered / w.placed : 0));
  const phone = formatPhone(n.e164);
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 first:pt-0">
      <div className="min-w-0">
        <p className="text-body text-ink tabular-nums">{phone}</p>
        <p className="text-meta text-ink-muted tabular-nums">
          {n.recent_rate === null ? (
            `${formatCount(n.recent_placed)} calls last week`
          ) : (
            <>
              Last week {percent(n.recent_rate)}
              {n.baseline_rate !== null && <> · before {percent(n.baseline_rate)}</>}
            </>
          )}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Sparkline
          values={rates}
          label={`Answer rate of ${phone}, by week`}
          tone={n.dropped ? "neutral" : "brand"}
          className="w-24"
        />
        {n.dropped && <StatusPill tone="warn">May be labelled spam</StatusPill>}
      </div>
    </li>
  );
}
