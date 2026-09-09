"use client";

import { RotateCcw } from "lucide-react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  ScrollRegion,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { deliveryRowKeys } from "@/lib/leadSourceRows";
import { lookup } from "@/lib/lookup";
import type { useIngestActivity } from "@/lib/api/leadSources";

import { sourceLabel } from "./sourceKinds";

/**
 * ACCOUNT FOR EVERY DELIVERY, INCLUDING THE RETRIES.
 *
 * Form vendors retry; the "retries absorbed" column shows the dedupe doing its job, which
 * is the answer to the classic support thread "your system got fifteen requests, why did
 * my customer only get one call?".
 */

/**
 * Outcome chips: accepted = the lead landed, rejected = it did not and the error column
 * says why, processing = still in flight (deliberately muted — it resolves).
 *
 * The two coloured tones follow `StatusBadge`'s palette rather than the design tokens
 * because there is no token for a success tint; the neutral one uses tokens, which is
 * why it needs no `dark:` pair.
 */
const OUTCOME_TONE: Record<string, string> = {
  accepted: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  rejected: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  processing: "border border-line bg-app text-ink-muted",
};

export function DeliveryLog({ activity }: { activity: ReturnType<typeof useIngestActivity> }) {
  /* `activity.data`, never `?? []`: "the server said nothing arrived" and "we could not
     ask" are different facts, and only the first one may print an empty state. */
  const deliveries = activity.data?.items;

  return (
    <Card
      title="Recent deliveries"
      action={
        deliveries ? (
          <span className="text-xs text-ink-faint">
            {formatCount(deliveries.length)}{" "}
            {deliveries.length === 1 ? "source" : "sources"} with activity
          </span>
        ) : undefined
      }
      bodyClassName="p-2"
    >
      {activity.error != null && (
        <div className="mb-3 px-4 pt-2">
          <ProblemNotice error={activity.error} onRetry={() => activity.refetch()} />
        </div>
      )}
      {/* Loading is a skeleton and failure is the notice above — never "No deliveries
          yet", which on a screen someone opened to find out whether their form is
          reaching us at all is the one sentence that sends them to change a working
          integration. */}
      {activity.isLoading ? (
        <div className="p-4">
          <Skeleton rows={3} />
        </div>
      ) : !deliveries ? null : deliveries.length ? (
        <ScrollRegion label="Ingest activity">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                <th className="px-3 py-2.5 font-semibold">Source</th>
                <th className="px-3 py-2.5 font-semibold">Reference</th>
                <th className="px-3 py-2.5 font-semibold">Outcome</th>
                <th className="px-3 py-2.5 font-semibold">Retries absorbed</th>
                <th className="px-3 py-2.5 text-right font-semibold">Last seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {deliveryRowKeys(deliveries).map(([item, rowKey]) => (
                <tr key={rowKey}>
                  <td className="px-3 py-2.5 text-ink">{sourceLabel(item.source)}</td>
                  {/* The sender's own id for this delivery. For a Meta source it is the
                      `leadgen_id` — the string Meta's Ads Manager and Meta support both
                      speak, and the one thing that survives a lead we could not read, so
                      it is what a client quotes when asking anybody about it. For a form
                      vendor it is our body digest, which is the honest answer there. */}
                  <td className="px-3 py-2.5">
                    <code className="break-all font-mono text-xs text-ink-muted">
                      {item.event_key}
                    </code>
                  </td>
                  <td className="px-3 py-2.5">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        // `lookup`, not `OUTCOME_TONE[item.outcome]`: a bare index
                        // reaches Object.prototype (src/lib/lookup.ts).
                        lookup(OUTCOME_TONE, item.outcome) ?? OUTCOME_TONE.processing
                      }`}
                    >
                      {item.outcome}
                    </span>
                    {item.error && (
                      <p className="mt-1 text-xs text-rose-700 dark:text-rose-400">
                        {item.error}
                      </p>
                    )}
                    {/* SERVER-DERIVED, never inferred here by comparing `error` against a
                        list this file would then hold a stale copy of. A row is
                        recoverable when the re-drive route would actually act on it, and
                        only the server knows which reasons those are — a badge that
                        guessed would promise a recovery the route declines to make. */}
                    {item.recoverable && (
                      <p className="mt-1 flex items-center gap-1 text-xs text-ink-muted">
                        <RotateCcw className="h-3 w-3 shrink-0" aria-hidden />
                        Recoverable — use “Recover unread leads” above.
                      </p>
                    )}
                  </td>
                  <td className="px-3 py-2.5 tabular-nums text-ink-muted">
                    {/* 0 renders as "—": "zero retries" reads like a problem,
                        a dash reads like nothing needed absorbing. */}
                    {item.deduplicated > 0 ? formatCount(item.deduplicated) : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs text-ink-faint">
                    {formatIST(item.last_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      ) : (
        <EmptyState
          title="No deliveries yet"
          hint="When your website form or ad account sends a lead, it appears here — accepted or not."
        />
      )}
    </Card>
  );
}
