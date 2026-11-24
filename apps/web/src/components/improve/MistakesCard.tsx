"use client";

/**
 * MISTAKES ON THESE CALLS (founder, 24 Nov 2026): the call-mistake kinds most often found on
 * this campaign's or line's calls (`call_mistakes`, D-949), each with how many calls showed it,
 * where its fix stands in the call page's own words (`callMistakeFix`), and its latest call.
 * Nothing for the owner to press: each one is fixed by Pip or our team.
 */

import Link from "next/link";

import { StatusPill } from "@/components/console/statusPill";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { formatCount } from "@/components/ui";
import { callMistakeFix } from "@/lib/api/callMistakes";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard, WithDiagnosis, type ImproveCardProps } from "./ImproveCard";

export const MISTAKES_TITLE = "Mistakes on these calls";

export function MistakesCard({ slug, holder }: Pick<ImproveCardProps, "slug" | "holder">) {
  const { href } = useClientRealm();
  return (
    <ImproveCard
      title={MISTAKES_TITLE}
      hint="What the agent got wrong, and its fix."
      info="Pip fixes the script where a line of it causes the mistake. Our team fixes the rest."
    >
      <WithDiagnosis holder={holder} label="Reading the mistakes on these calls">
        {({ mistakes, window_days }) =>
          mistakes.length === 0 ? (
            <p className="text-meta text-ink-muted">No mistakes found in the last {window_days} days.</p>
          ) : (
            <ul className="divide-y divide-line" aria-label={MISTAKES_TITLE}>
              {mistakes.map((m) => {
                const fix = callMistakeFix(m.status);
                return (
                  <li key={m.kind} className="py-2.5 first:pt-0">
                    <p className="text-body text-ink [overflow-wrap:anywhere]">{m.label}</p>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="text-meta text-ink-muted tabular-nums">
                        {formatCount(m.calls)} {m.calls === 1 ? "call" : "calls"}
                      </span>
                      <StatusPill tone={fix.tone}>{fix.words}</StatusPill>
                      <Link
                        href={href(`/c/${slug}/calls/${m.last_call_id}`)}
                        className={`${TEXT_ACTION_SM} -mx-2`}
                        aria-label={`Open the latest call: ${m.label}`}
                      >
                        Latest call
                      </Link>
                    </div>
                  </li>
                );
              })}
            </ul>
          )
        }
      </WithDiagnosis>
    </ImproveCard>
  );
}
