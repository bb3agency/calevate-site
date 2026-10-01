"use client";

import Link from "next/link";
import { useMemo } from "react";

import { EmptyState, ProblemNotice, Skeleton } from "@/components/ui";
import { DataTable } from "@/components/console/dataTable";
import { Panel } from "@/components/console/panel";
import type { useCalls } from "@/lib/api/hooks";

import { callColumns } from "./calls/callColumns";

/**
 * The six most recent calls — the fastest route from "somebody rang" to ringing them
 * back, which is why the number is printed in full (D-436). Same row as the call log,
 * so a call reads the same on both screens; a call that comes in on a poll is marked.
 */
export function LatestCalls({
  recent,
  allHref,
  callHref,
}: {
  recent: ReturnType<typeof useCalls>;
  allHref: string;
  callHref: (id: string) => string;
}) {
  const columns = useMemo(() => callColumns({ callHref, compact: true }), [callHref]);
  return (
    <Panel
      title="Latest calls"
      action={
        <Link
          href={allHref}
          className="rounded-sm text-[13px] font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 touch:inline-flex touch:items-center"
        >
          View all
        </Link>
      }
      bodyClassName="px-1 pb-1 sm:px-2 sm:pb-2"
    >
      {recent.isLoading ? (
        <div className="p-3">
          <Skeleton rows={5} />
        </div>
      ) : recent.error || !recent.data ? (
        /* Both non-answers — a refusal and a paused (offline) query — are this arm, so
           "No calls yet" is only ever printed over a list the server sent (§52). */
        <div className="p-3">
          <ProblemNotice
            error={recent.error ?? new Error("The latest calls did not load.")}
            onRetry={() => void recent.refetch()}
          />
        </div>
      ) : !recent.data.length ? (
        <EmptyState
          title="No calls yet"
          hint="They appear here within a couple of minutes of the call ending."
        />
      ) : (
        <DataTable
          rows={recent.data}
          columns={columns}
          getRowId={(call) => call.id}
          label="Latest calls"
        />
      )}
    </Panel>
  );
}
