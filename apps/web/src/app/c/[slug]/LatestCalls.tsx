"use client";

import Link from "next/link";
import { useMemo } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { DataTable } from "@/components/console/dataTable";
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
    <Section
      title="Latest calls"
      action={
        <Link
          href={allHref}
          className={TEXT_ACTION}
        >
          View all
        </Link>
      }
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
          illustration={<EmptySketch kind="calls" />}
          message="No calls yet."
          hint="They appear here a couple of minutes after a call ends."
        />
      ) : (
        <DataTable
          rows={recent.data}
          columns={columns}
          getRowId={(call) => call.id}
          label="Latest calls"
        />
      )}
    </Section>
  );
}
