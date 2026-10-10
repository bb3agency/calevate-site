"use client";

import { use, useState } from "react";

import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ProblemNotice, RestrictionNote, ScrollRegion, Skeleton, formatCount } from "@/components/ui";
import { useAttention, type AttentionKind } from "@/lib/api/attention";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { useAttentionCopilot } from "./copilot";
import { KIND_COPY, Row, byUrgency } from "./rows";

const ALL = "all";

/**
 * The "needs attention" queue (SURFACES §2b): everything the platform stopped on purpose
 * (compliance gate, DNC, review), listed with the reason and the fix, so none of it
 * happens silently.
 *
 * - The empty state requires the server to have SAID zero (`total === 0`). With no data
 *   there is no list, only the refusal: "nothing needs you" and "we could not read your
 *   queue" are opposite facts.
 * - The list is capped (50, newest first) and the counts are not, so the filter counts and
 *   the shortfall line come from `counts`/`total`, never from the rows.
 */
export default function AttentionPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const queue = useAttention(session);
  const me = useMe(session);
  const [filter, setFilter] = useState<string>(ALL);

  /**
   * `GET /v1/attention` requires `leads:read` — staff work this queue, so it is
   * deliberately NOT gated on an owner permission (crm/routes.py says so at the
   * decorator). Read off `/v1/me` all the same: a session that lacks it should be told,
   * once and quietly, rather than shown a red alert that reads like an outage.
   *
   * Nothing is refused while `/v1/me` is in flight, and nothing is refused if it failed —
   * we do not know, so the request goes out and the API's own answer renders.
   */
  const data = queue.data;
  const counts: Record<string, number> = data?.counts ?? {};
  const countOf = (kind: AttentionKind): number => lookup(counts, kind) ?? 0;
  const kinds = (Object.keys(KIND_COPY) as AttentionKind[]).filter((kind) => countOf(kind) > 0);
  useAttentionCopilot(queue, me, { value: filter, all: ALL, kinds, set: setFilter });

  const refused = me.data !== undefined && !me.data.permissions.includes("leads:read");
  if (refused) {
    return (
      <RestrictionNote reason="This queue needs permission to read leads, which this account does not have. Ask your account owner for access." />
    );
  }

  // Most urgent first (calls going unanswered before a number we safely did not ring);
  // the server sends newest first, and newest-first is kept within one kind.
  const shown = data ? byUrgency(filter === ALL ? data.items : data.items.filter((item) => item.kind === filter)) : [];

  return (
    <div className="max-w-4xl space-y-6 pb-12">
      <PageHeader description="What needs you, most urgent first, and what to do next." />

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => void queue.refetch()} />}

      {/* Counts come from the server's own tally (`counts`), never from the rows on screen:
          the list is capped, so counting rows would under-report exactly when it is busiest.
          A filter only when there is more than one kind to choose between (D-655). */}
      {kinds.length > 1 && (
        <div role="group" aria-label="Queue summary">
          <ScrollRegion label="Filter the queue" className="max-w-full">
            <SegmentedControl
              label="Show"
              value={filter}
              onValueChange={setFilter}
              options={[
                { value: ALL, label: "All", count: formatCount(data?.total ?? 0) },
                ...kinds.map((kind) => ({ value: kind, label: KIND_COPY[kind].label, count: formatCount(countOf(kind)) })),
              ]}
            />
          </ScrollRegion>
        </div>
      )}
      {kinds.length === 1 && (
        <p role="group" aria-label="Queue summary" className="text-meta text-ink-muted">
          {KIND_COPY[kinds[0]].label} <span className="font-semibold tabular-nums text-ink">{formatCount(countOf(kinds[0]))}</span>
        </p>
      )}

      {/* No data means no list: an empty panel under an error reads as "nothing needs you",
          the one sentence this screen must never say by accident. */}
      {!data ? (
        queue.isLoading ? <Skeleton rows={5} /> : null
      ) : data.total === 0 ? (
        <div className="border-y border-line">
          <EmptyState
            illustration={<EmptySketch kind="attention" />}
            message="Nothing needs you right now."
            hint="Blocked calls, failed deliveries and stalled campaigns will appear here."
          />
        </div>
      ) : (
        <div className="border-y border-line">
          <ul className="divide-y divide-line">
            {shown.map((item) => (
              <Row key={`${item.kind}-${item.id}-${item.occurred_at}`} item={item} to={item.href ? href(`/c/${slug}${item.href}`) : null} />
            ))}
          </ul>
          {/* The API sorts newest first before it slices, so the rows that fall off are the
              OLDEST; `total` is the server's count of the whole set, never `items.length`. */}
          {data.total > data.items.length && (
            <p className="border-t border-line py-3 text-meta text-ink-faint">
              Showing the {formatCount(data.items.length)} most recent of {formatCount(data.total)}. Older
              items are not listed.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
