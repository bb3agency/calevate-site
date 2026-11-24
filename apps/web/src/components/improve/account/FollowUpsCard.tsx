"use client";

/**
 * PEOPLE WAITING ON YOU: how many people reached the goal and how many call-backs agents
 * promised, as counts that open the Leads and Call-backs pages. The people themselves are
 * listed there, never here.
 */

import Link from "next/link";

import { formatCount } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { useLeadNouns } from "@/lib/businessCapabilities";

import { ImproveCard } from "../ImproveCard";
import { Quiet, WithAccountImprove, type AccountCardProps } from "./shared";

export const FOLLOW_UPS_TITLE = "People waiting on you";

export function FollowUpsCard({ slug }: AccountCardProps) {
  const { href } = useClientRealm();
  const nouns = useLeadNouns();
  return (
    <ImproveCard headingLevel={2} title={FOLLOW_UPS_TITLE} hint="Reach them while it still matters.">
      <WithAccountImprove label="Counting who is waiting">
        {({ follow_ups: f }) =>
          f.hot_leads === 0 && f.callbacks_due === 0 ? (
            <Quiet>No one is waiting on a follow-up or a call-back.</Quiet>
          ) : (
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2" aria-label={FOLLOW_UPS_TITLE}>
              <Count
                value={f.hot_leads}
                words="reached the goal"
                href={href(`/c/${slug}/leads?status=hot`)}
                action={`Open these ${nouns.leads}`}
              />
              <Count
                value={f.callbacks_due}
                words={f.callbacks_due === 1 ? "call-back promised" : "call-backs promised"}
                href={href(`/c/${slug}/callbacks`)}
                action="Open Call-backs"
              />
            </ul>
          )
        }
      </WithAccountImprove>
    </ImproveCard>
  );
}

function Count({ value, words, href, action }: { value: number; words: string; href: string; action: string }) {
  return (
    <li>
      <Link
        href={href}
        className="block rounded-card border border-line px-3 py-2 hover:bg-surface-muted focus-visible:outline-2"
      >
        <span className="block text-title font-semibold text-ink tabular-nums">{formatCount(value)}</span>
        <span className="block text-meta text-ink-muted">{words}</span>
        <span className="mt-0.5 block text-meta font-medium text-brand-strong">{action}</span>
      </Link>
    </li>
  );
}
