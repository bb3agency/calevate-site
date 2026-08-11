"use client";

import Link from "next/link";
import { use } from "react";

import { Card, EmptyState, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { useAttention, type AttentionKind } from "@/lib/api/attention";
import { useClientRealm } from "@/lib/api/session";

/**
 * Per-kind chip copy and colour. Plain words, not system nouns: the reader is a
 * business owner, so "Call blocked" beats "lead_blocked". Colours follow the same
 * temperature scale as the rest of the app — rose for things broken on their side,
 * amber for things the rules stopped, sky for things merely stuck, slate for review
 * outcomes.
 */
const KIND_COPY: Record<AttentionKind, { label: string; tone: string }> = {
  lead_blocked: {
    label: "Call blocked",
    tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  },
  delivery_failed: {
    label: "Delivery failed",
    tone: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  },
  campaign_stalled: {
    label: "Campaign stalled",
    tone: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  },
  kb_rejected: {
    label: "Knowledge not accepted",
    tone: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  },
};

/**
 * The "needs attention" queue (SURFACES §2b).
 *
 * The platform blocks calls, campaigns and knowledge on purpose — compliance gate,
 * DNC, review — and each block is correct behaviour that still leaves the owner with
 * something to decide. This screen is the promise that none of that happens silently:
 * if we stopped it, it is listed here with the reason and the fix.
 */
export default function AttentionPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const queue = useAttention(session);

  const counts = queue.data?.counts ?? {};
  const chips = (Object.keys(KIND_COPY) as AttentionKind[]).filter((kind) => (counts[kind] ?? 0) > 0);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Needs attention</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Everything the platform stopped, and why. When a call is blocked, a delivery
          fails or a campaign stalls, it never happens silently — it shows up here with
          what to do next.
        </p>
      </div>

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => queue.refetch()} />}

      {/* Summary chips: a fast read of WHERE the trouble is before scanning the list.
          Kinds with zero items are omitted — an all-zeros row would just be noise. */}
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {chips.map((kind) => (
            <span
              key={kind}
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${KIND_COPY[kind].tone}`}
            >
              {KIND_COPY[kind].label}
              <span className="tabular-nums font-semibold">{counts[kind]}</span>
            </span>
          ))}
        </div>
      )}

      <Card>
        {queue.isLoading ? (
          <Skeleton rows={5} />
        ) : queue.data && queue.data.total === 0 ? (
          <EmptyState
            title="Nothing needs you right now."
            hint="Blocked calls, failed deliveries and stalled campaigns will appear here."
          />
        ) : queue.data ? (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {queue.data.items.map((item) => (
              <li key={`${item.kind}-${item.id}-${item.occurred_at}`} className="py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                      KIND_COPY[item.kind]?.tone ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                    }`}
                  >
                    {KIND_COPY[item.kind]?.label ?? item.kind.replace(/_/g, " ")}
                  </span>
                  <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                    {item.title}
                  </span>
                  <span className="ml-auto text-xs text-slate-500">
                    {formatIST(item.occurred_at)}
                  </span>
                </div>
                {/* The detail line is the point of the screen: the title only names the
                    subject, but the detail is the remedy — what happened and what the
                    owner should do. It gets its own full-width line so it never gets
                    crushed between badge and timestamp. */}
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{item.detail}</p>
                {item.href && (
                  <Link
                    href={href(`/c/${slug}${item.href}`)}
                    className="mt-1.5 inline-block rounded-md border border-slate-200 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                  >
                    Open
                  </Link>
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </div>
  );
}
