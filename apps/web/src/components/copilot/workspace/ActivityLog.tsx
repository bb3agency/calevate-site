"use client";

import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Undo2 } from "lucide-react";

import { EmptySketch } from "@/components/console/emptySketch";
import { StatusPill } from "@/components/console/statusPill";
import { EmptyState } from "@/components/console/emptyState";
import { NewItemsPill, useNewItems } from "@/components/interior/new-items-pill";
import { useEnterClass } from "@/components/live/arrivals";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import {
  ProblemNotice,
  SECONDARY_BUTTON,
  Skeleton,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useUndoAction } from "@/lib/api/copilot";
import { lookup } from "@/lib/lookup";
import {
  fetchOlderActivity,
  useCopilotActivity,
  type CopilotActionOut,
  type Realm,
} from "@/lib/copilot/workspace";

const STATUS: Record<CopilotActionOut["status"], { words: string; tone: NoticeTone }> = {
  done: { words: "Done", tone: "ok" },
  undone: { words: "Undone", tone: "neutral" },
  refused: { words: "Not allowed", tone: "warn" },
  pending_approval: { words: "Waiting for you", tone: "warn" },
  rejected: { words: "Declined", tone: "neutral" },
  expired: { words: "Expired", tone: "neutral" },
};

/**
 * EVERYTHING THE ASSISTANT DID, newest first, each with its Undo while the server still
 * offers one (D-694). Refused attempts are rows too: "never hide irreversibility" includes
 * never hiding what it tried and was not allowed to do.
 *
 * The list polls; when new rows arrive while the person has scrolled down to read older
 * ones, their place is kept and a pill offers the way back to the top.
 */
export function ActivityLog({ session, realm }: { session: Session; realm: Realm }) {
  const activity = useCopilotActivity(session, realm);
  const [older, setOlder] = useState<CopilotActionOut[]>([]);
  const [olderDone, setOlderDone] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderError, setOlderError] = useState<unknown>(null);

  const rows = useMemo(() => {
    const fresh = activity.data?.actions ?? [];
    const seen = new Set(fresh.map((row) => row.id));
    return [...fresh, ...older.filter((row) => !seen.has(row.id))];
  }, [activity.data, older]);
  const scroller = useNewItems<HTMLDivElement>({
    itemCount: rows.length,
    label: `What ${ASSISTANT_NAME} did`,
  });
  // An action taken while the log is open enters softly (D-774); the log on load does not.
  const enter = useEnterClass(activity.data ? rows.map((row) => row.id) : null);

  if (activity.error != null) {
    return <ProblemNotice error={activity.error} onRetry={() => void activity.refetch()} />;
  }
  if (activity.data === undefined) return <Skeleton rows={5} label="Loading the activity log…" />;
  if (rows.length === 0) {
    return (
      <EmptyState
        illustration={<EmptySketch kind="chat" />}
        message={`${ASSISTANT_NAME} hasn't done anything yet.`}
        hint="Every change it makes appears here, with an Undo while one is possible."
      />
    );
  }

  const hasMore = !olderDone && (older.length > 0 || activity.data.has_more);
  const loadOlder = async () => {
    const last = rows[rows.length - 1];
    if (last === undefined) return;
    setLoadingOlder(true);
    setOlderError(null);
    try {
      const page = await fetchOlderActivity(session, realm, last.created_at);
      setOlder((current) => [...current, ...page.actions]);
      if (!page.has_more) setOlderDone(true);
    } catch (error) {
      setOlderError(error);
    } finally {
      setLoadingOlder(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="relative">
        <NewItemsPill
          count={scroller.unread}
          onJump={scroller.jump}
          label={(count, over) => `${count}${over ? "+" : ""} new ${count === 1 && !over ? "entry" : "entries"}`}
        />
        <div
          {...scroller.scrollProps}
          className="max-h-[min(40rem,70dvh)] overflow-y-auto overscroll-contain border-y border-line focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          <ul className="divide-y divide-line">
            {rows.map((row) => (
              <ActivityRow key={row.id} row={row} session={session} realm={realm} enterClass={enter(row.id)} />
            ))}
          </ul>
        </div>
      </div>
      {olderError != null && <ProblemNotice error={olderError} onRetry={() => void loadOlder()} />}
      {hasMore && (
        <button
          type="button"
          onClick={() => void loadOlder()}
          disabled={loadingOlder}
          className={SECONDARY_BUTTON}
        >
          {loadingOlder ? "Loading…" : "Show older"}
        </button>
      )}
    </div>
  );
}

function ActivityRow({
  enterClass,
  row,
  session,
  realm,
}: {
  enterClass: string;
  row: CopilotActionOut;
  session: Session;
  realm: Realm;
}) {
  const undo = useUndoAction(session, realm);
  // The row's pill turns to "Undone" with the server's sentence; a refusal is drawn in
  // the row.
  const undoFeedback = useActionFeedback(undo, { errorDisplay: "inline" });
  const client = useQueryClient();
  const status = lookup(STATUS, row.status) ?? STATUS.done;
  const undone = undo.data !== undefined;
  return (
    <li className={`flex min-w-0 flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start ${enterClass}`}>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <StatusPill tone={undone ? STATUS.undone.tone : status.tone}>
            {undone ? STATUS.undone.words : status.words}
          </StatusPill>
          <span className="text-xs text-ink-faint">
            {formatIST(row.created_at)}
            {row.source === "job" ? " · background task" : ""}
          </span>
        </p>
        <p className="mt-1 break-words text-sm text-ink [overflow-wrap:anywhere]">
          {undo.data?.detail ?? row.summary ?? row.refusal_reason ?? `A change by ${ASSISTANT_NAME}`}
        </p>
        {row.status === "refused" && row.refusal_reason && row.summary && (
          <p className="mt-0.5 text-xs text-ink-muted">{row.refusal_reason}</p>
        )}
        {undo.error != null && (
          <div className="mt-2">
            <ProblemNotice error={undo.error} />
          </div>
        )}
      </div>
      {row.can_undo && !undone && (
        <ActionButton
          variant="secondary-sm"
          status={undoFeedback.status}
          onClick={() =>
            undo.mutate(row.id, {
              onSuccess: () => {
                void client.invalidateQueries({ queryKey: ["copilot-actions"] });
              },
            })
          }
          aria-label={`Undo: ${row.summary ?? "this change"}`}
          successLabel="Undone"
          className="shrink-0 self-start"
        >
          <Undo2 aria-hidden className="h-3.5 w-3.5" />
          Undo
        </ActionButton>
      )}
    </li>
  );
}
