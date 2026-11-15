"use client";

/**
 * A campaign's calls, newest first, each opening its call page, where the recording plays and
 * the transcript reads (the recording's access and audit rules live there, so they are not
 * repeated here). Filtered on every keystroke across the person, the headline, the outcome
 * and the agent (global rule 9).
 */

import Link from "next/link";
import { useMemo, useState } from "react";

import { SearchField } from "@/components/arc/search-field";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatDuration, formatIST } from "@/components/ui";
import { useCallsLog } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { matchesWords } from "./matchWords";

const OUTCOME: Record<string, string> = {
  call_back_booked: "Call back booked",
  needs_you: "Needs you",
  answered: "Answered",
  transferred: "Handed over",
  hung_up_early: "Hung up early",
  missed: "Not answered",
};

export function CampaignCalls({ slug, campaignId }: { slug: string; campaignId: string }) {
  const { session, href } = useClientRealm();
  const log = useCallsLog(session, { campaignId, pageSize: 25 });
  const [query, setQuery] = useState("");
  const rows = useMemo(() => {
    if (!log.data) return null;
    const seen = new Set<string>();
    return log.data.pages.flat().filter((c) => (seen.has(c.id) ? false : (seen.add(c.id), true)));
  }, [log.data]);

  if (log.isLoading) return <Skeleton rows={4} label="Loading this campaign's calls" />;
  if (log.error || !rows) {
    return (
      <ProblemNotice
        error={log.error ?? new Error("This campaign's calls did not load.")}
        onRetry={() => log.refetch()}
      />
    );
  }
  if (rows.length === 0) {
    return <p className="text-body text-ink-muted">No calls yet. They show here once it calls.</p>;
  }
  const shown = rows.filter((c) =>
    matchesWords(query, [c.lead_name, c.headline, c.summary, c.agent_name, OUTCOME[c.outcome_tag ?? ""] ?? c.status]),
  );
  return (
    <div className="space-y-4">
      <SearchField
        label="Search calls"
        hideLabel
        value={query}
        onValueChange={setQuery}
        placeholder="Search by person, what was said or outcome"
      />
      <ul className="divide-y divide-line border-y border-line">
        {shown.map((call) => (
          <li key={call.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3.5">
            <div className="min-w-0 flex-1">
              <p className="text-body font-medium text-ink">{call.lead_name || "Unknown caller"}</p>
              <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">
                {call.headline || call.summary || "No summary yet"}
              </p>
            </div>
            <span className="text-meta text-ink-muted">{OUTCOME[call.outcome_tag ?? ""] ?? call.status}</span>
            <span className="w-14 text-right text-meta text-ink-muted tabular-nums">{formatDuration(call.duration_s)}</span>
            <span className="text-meta text-ink-faint">{formatIST(call.started_at ?? call.created_at)}</span>
            <Link href={href(`/c/${slug}/calls/${call.id}`)} className={SECONDARY_BUTTON_SM}>
              Listen
            </Link>
          </li>
        ))}
        {shown.length === 0 && <li className="px-4 py-3 text-meta text-ink-muted">No call matches “{query}”.</li>}
      </ul>
      {log.hasNextPage && (
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={log.isFetchingNextPage} onClick={() => log.fetchNextPage()}>
          {log.isFetchingNextPage ? "Loading…" : "Show more calls"}
        </button>
      )}
    </div>
  );
}
