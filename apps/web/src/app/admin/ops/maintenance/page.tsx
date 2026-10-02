"use client";

import { useState } from "react";
import { ShieldAlert, TriangleAlert } from "lucide-react";

import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { NoticeBox, PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import { useMaintenanceBoard, type MaintenanceBoard } from "@/lib/api/maintenance";

import { CurrentWindow } from "./CurrentWindow";
import { ScheduleWindowDrawer } from "./windowForms";
import { WindowHistory } from "./WindowHistory";
import { CurrentWindowHeading } from "./windowState";

/**
 * Planned maintenance: schedule one window, watch it drain, and end it.
 *
 * The page carries no `<h1>`: the shell prints the nav label.
 */
export default function MaintenancePage() {
  const board = useMaintenanceBoard();
  // A refetch that fails keeps the last `data`; the board is withheld then too, because a
  // stale "no window" invites a second booking over one the operator cannot see.
  const read: MaintenanceBoard | undefined = board.error === null ? board.data : undefined;

  return (
    <div className="space-y-8 pb-12">
      <PageHeader description="Drain live work, close the client portals for planned work, then reopen them." />

      {board.error !== null && (
        <ProblemNotice error={board.error} onRetry={() => void board.refetch()} />
      )}

      {board.isLoading ? (
        <Skeleton rows={4} label="Loading the maintenance board" />
      ) : read === undefined ? (
        // TanStack pauses a query while the browser is offline — no data, no error, not
        // loading — and that is no more "no window" than a failure is.
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="The maintenance board could not be read"
        >
          <p className="mt-1">
            So we cannot say whether a window is open. This is not an empty schedule — do not
            book one until this reads.
          </p>
        </NoticeBox>
      ) : read.current !== null ? (
        <CurrentWindow window={read.current} />
      ) : (
        <NoWindow leadHours={read.notice_lead_hours} />
      )}

      {read !== undefined && <WindowHistory history={read.history} />}

      <NoticeBox
        tone="neutral"
        icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
        title="What a window does not do"
      >
        <p className="mt-1">
          It never hangs up a live call and never cancels a queued job — the deadline bounds
          how long the PLATFORM waits, not how long other people&apos;s work takes. It deletes
          nothing. And it never locks operators out: this console, the health checks and the
          engine&apos;s webhooks are exempt from shedding in every mode.
        </p>
      </NoticeBox>
    </div>
  );
}

function NoWindow({ leadHours }: { leadHours: number }) {
  const [scheduling, setScheduling] = useState(false);
  return (
    <section aria-labelledby="maintenance-current" className="space-y-2">
      <CurrentWindowHeading />
      <EmptyState
        className="py-6"
        message={
          <>
            No window is open.
            <span className="mt-1 block text-[13px] text-ink-faint">
              The platform has one maintenance slot. Scheduling a second while one is open is
              refused.
            </span>
          </>
        }
        action={
          <button type="button" className={PRIMARY_BUTTON} onClick={() => setScheduling(true)}>
            Schedule a window
          </button>
        }
      />
      {scheduling && (
        <ScheduleWindowDrawer leadHours={leadHours} onClose={() => setScheduling(false)} />
      )}
    </section>
  );
}
