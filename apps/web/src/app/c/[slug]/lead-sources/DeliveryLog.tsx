"use client";

import { RotateCcw } from "lucide-react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { Section } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatCount, formatIST } from "@/components/ui";
import type { IngestActivityItem, useIngestActivity } from "@/lib/api/leadSources";
import { deliveryRowKeys } from "@/lib/leadSourceRows";
import { lookup } from "@/lib/lookup";

import { sourceLabel } from "./sourceKinds";

const OUTCOME_TONE: Record<string, string> = {
  accepted: "bg-brand-soft text-brand-strong",
  rejected: "border border-danger-line bg-danger-soft text-danger",
  processing: "border border-line bg-surface-muted text-ink-muted",
};

type Row = { item: IngestActivityItem; key: string };

/**
 * EVERY DELIVERY WE RECEIVED, accepted or not — the only evidence that a form or an ad
 * account is actually reaching us.
 *
 * Loading is a skeleton and failure is a refusal, never "No deliveries yet": on a screen
 * someone opened to find out whether their form is reaching us, that sentence sends them
 * to change a working integration. Keys come from `deliveryRowKeys`, because two
 * deliveries can share an event key.
 */
export function DeliveryLog({ activity }: { activity: ReturnType<typeof useIngestActivity> }) {
  const deliveries = activity.data?.items;

  const columns: DataColumn<Row>[] = [
    {
      id: "source",
      header: "Source",
      sort: { value: ({ item }) => item.source },
      cell: ({ item }) => (
        <div className="min-w-0">
          <p className="text-ink">{sourceLabel(item.source)}</p>
          {/* The sender's own id: a Meta `leadgen_id`, or our body digest for a form. It
              is what a client quotes when asking anyone about this lead. */}
          <code className="break-all font-mono text-meta text-ink-muted">{item.event_key}</code>
        </div>
      ),
    },
    {
      id: "outcome",
      header: "Outcome",
      sort: { value: ({ item }) => item.outcome },
      flash: ({ item }) => item.outcome,
      cell: ({ item }) => (
        <div className="max-w-xs space-y-1">
          <span
            className={`inline-flex rounded-full px-2 py-0.5 text-meta font-medium ${
              lookup(OUTCOME_TONE, item.outcome) ?? OUTCOME_TONE.processing
            }`}
          >
            {item.outcome}
          </span>
          {item.error && <p className="text-meta text-danger">{item.error}</p>}
          {/* SERVER-derived: only the server knows which reasons the re-drive acts on. */}
          {item.recoverable && (
            <p className="flex items-center gap-1 text-meta text-ink-muted">
              <RotateCcw className="h-3 w-3 shrink-0" aria-hidden />
              Recoverable — use “Recover unread leads” in this source&apos;s Meta setup.
            </p>
          )}
        </div>
      ),
    },
    {
      id: "retries",
      header: "Retries absorbed",
      align: "right",
      hideBelow: "sm",
      sort: { value: ({ item }) => item.deduplicated, kind: "number" },
      // A dash, not a zero: "zero retries" reads like a problem.
      cell: ({ item }) => (
        <span className="tabular-nums text-ink-muted">
          {item.deduplicated > 0 ? formatCount(item.deduplicated) : "—"}
        </span>
      ),
    },
    {
      id: "last",
      header: "Last seen",
      align: "right",
      sort: { value: ({ item }) => item.last_at, kind: "time", first: "desc" },
      cell: ({ item }) => (
        <span className="whitespace-nowrap text-meta text-ink-faint">{formatIST(item.last_at)}</span>
      ),
    },
  ];

  return (
    <Section
      title="Recent deliveries"
      action={
        deliveries ? (
          <span className="text-meta text-ink-faint">
            {formatCount(deliveries.length)} {deliveries.length === 1 ? "delivery" : "deliveries"}
          </span>
        ) : undefined
      }
    >
      {activity.isLoading ? (
        <Skeleton rows={3} />
      ) : !deliveries ? (
        <ProblemNotice
          error={activity.error ?? new Error("Your recent deliveries could not be loaded.")}
          onRetry={() => activity.refetch()}
        />
      ) : deliveries.length ? (
        <DataTable
          label="Ingest activity"
          rows={deliveryRowKeys(deliveries).map(([item, key]) => ({ item, key }))}
          columns={columns}
          getRowId={(row) => row.key}
        />
      ) : (
        <EmptyState illustration={<EmptySketch kind="deliveries" />} message="No deliveries yet. Each lead your form or ad account sends appears here, accepted or not." />
      )}
    </Section>
  );
}
