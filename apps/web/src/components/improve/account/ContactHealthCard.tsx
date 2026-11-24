"use client";

/**
 * CONTACT LIST HEALTH, across the account's campaign lists: people on a do-not-call list,
 * people every try failed to reach, and people rung by two or more campaigns within a few
 * days. Counts only. There is no setting yet that leaves people out of new campaigns for
 * having been called recently, so this links to the campaigns rather than offering a press
 * that would do nothing.
 */

import Link from "next/link";

import { TEXT_ACTION_SM } from "@/components/console/section";
import { formatCount } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard } from "../ImproveCard";
import { Quiet, WithAccountImprove, type AccountCardProps } from "./shared";

export const CONTACTS_TITLE = "Contact list health";

export function ContactHealthCard({ slug }: AccountCardProps) {
  const { href } = useClientRealm();
  return (
    <ImproveCard headingLevel={2} title={CONTACTS_TITLE} hint="Who on your lists should not be called, or not so often.">
      <WithAccountImprove label="Checking your contact lists">
        {({ contacts: c }) =>
          c.on_dnc === 0 && c.unreachable === 0 && c.called_too_often === 0 ? (
            <Quiet>Your contact lists look clean.</Quiet>
          ) : (
            <>
              <dl className="divide-y divide-line">
                <Row value={c.on_dnc} term="On a do-not-call list" note="Never called: the list keeps them out." />
                <Row value={c.unreachable} term="Could not be reached" note="Every try failed to connect." />
                <Row
                  value={c.called_too_often}
                  term="Called too often"
                  note={`Called by two or more campaigns in ${c.too_often_days} days.`}
                />
              </dl>
              {c.called_too_often > 0 && (
                <Link href={href(`/c/${slug}/campaigns`)} className={`${TEXT_ACTION_SM} -mx-2 mt-2`}>
                  Review your campaigns
                </Link>
              )}
            </>
          )
        }
      </WithAccountImprove>
    </ImproveCard>
  );
}

function Row({ value, term, note }: { value: number; term: string; note: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2 first:pt-0">
      <dt className="min-w-0">
        <span className="block text-body text-ink">{term}</span>
        <span className="block text-meta text-ink-muted">{note}</span>
      </dt>
      <dd className="shrink-0 text-body font-semibold text-ink tabular-nums">{formatCount(value)}</dd>
    </div>
  );
}
