"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { TEXT_ACTION } from "@/components/console/section";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  MonoValue,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatIST,
  formatPhone,
} from "@/components/ui";
import { useCallbacks, useCancelCallback, type ScheduledCallback } from "@/lib/api/callbacks";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

/**
 * THE CALL-BACKS YOUR AGENTS PROMISED (D-514).
 *
 * PRIMARY JOB: see which promised call-backs are coming, and stop one before it goes out.
 *
 * - Every row says WHY in the API's own `explanation` (the compliance gate's client-facing
 *   sentence for a refusal). This screen prints it and never composes one.
 * - Cancelling is a confirmation that states the consequence, and it closes only on
 *   success: a failed cancel leaves the promise live.
 * - Loading, failure and empty are three states. "No call-backs" is said only from rows
 *   the server sent, never under a failed request.
 * - The sentence naming the checks a call-back passes (do-not-call, calling hours, credit)
 *   qualifies a compliance control, so it stays visible, word for word.
 */

/** The heading a row sits under. Our status words never reach the screen; these do. */
const HEADINGS: Record<string, string> = {
  scheduled: "Waiting",
  dialing: "Calling now",
  completed: "Called",
  cancelled: "Called off",
  refused: "Not allowed",
  missed: "Ran out of time",
  failed: "Could not be placed",
};

const TONE: Record<string, string> = {
  scheduled: "bg-ink/[0.06] text-ink",
  dialing: "bg-brand-soft text-brand-strong",
  completed: "bg-ink/[0.06] text-ink-muted",
  refused: "border border-danger-line bg-danger-soft text-danger",
  missed: "border border-warn-line bg-warn-soft text-warn",
  failed: "border border-warn-line bg-warn-soft text-warn",
};

/** Peer views of one list (D-655): the live promises, or every one. */
const VIEWS = [
  { value: "open", label: "Upcoming" },
  { value: "all", label: "All" },
];

export function CallbacksScreen() {
  const session = useClientSession();
  const [view, setView] = useState("all");
  const openOnly = view === "open";
  const callbacks = useCallbacks(session, openOnly);
  const cancel = useCancelCallback(session);
  const write = useWriteAccess(session, "leads:dispatch", "call off a call-back");
  const [stopping, setStopping] = useState<ScheduledCallback | null>(null);
  const rows = callbacks.data;

  /*
   * Declared to the assistant: the Upcoming/All switch is the one control, and the facts
   * are counts by status. No row is declared, because every row is a caller's number
   * (hard rule 6).
   */
  const byStatus = new Map<string, number>();
  if (rows) for (const row of rows) byStatus.set(row.status, (byStatus.get(row.status) ?? 0) + 1);
  useCopilotSurface({
    route: "/c/{slug}/callbacks",
    title: "Call-backs",
    realm: "client",
    fields: [
      {
        id: "callbacks-view",
        label: "Which call-backs to show",
        type: "select",
        value: view,
        options: VIEWS,
        help: "Upcoming shows only the ones still waiting to be placed.",
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: rows
          ? "the call-backs below have loaded"
          : callbacks.error
            ? "the call-backs failed to load, so none is listed"
            : "still loading",
      },
      ...(rows
        ? [
            { key: "rows", label: "Call-backs listed", value: String(rows.length) },
            {
              key: "by_status",
              label: "How many are in each state",
              value:
                [...byStatus.entries()]
                  .map(([status, count]) => `${lookup(HEADINGS, status) ?? status}: ${count}`)
                  .join(", ") || "none",
            },
          ]
        : []),
      { key: "can_cancel", label: "Can this person call one off?", value: write.allowed ? "yes" : "no" },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "callbacks-view") continue;
        const wanted = asText(item.value);
        if (VIEWS.some((option) => option.value === wanted)) setView(wanted);
      }
    },
  });

  const columns: DataColumn<ScheduledCallback>[] = [
    {
      id: "who",
      header: "Number",
      cell: (row) => (
        <div className="min-w-0">
          <MonoValue className="whitespace-nowrap tabular-nums text-ink">
            {formatPhone(row.phone_e164)}
          </MonoValue>
          {/* Below `sm` the time column is dropped, so it rides under the number. */}
          <p className="text-meta text-ink-muted sm:hidden">{formatIST(row.requested_at)}</p>
        </div>
      ),
    },
    {
      id: "when",
      header: "Asked for",
      sort: { value: (row) => row.requested_at, kind: "time" },
      hideBelow: "sm",
      cell: (row) => <span className="whitespace-nowrap text-ink">{formatIST(row.requested_at)}</span>,
    },
    {
      id: "status",
      header: "Status",
      flash: (row) => row.status,
      cell: (row) => (
        <div className="max-w-md space-y-1">
          <span
            className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
              lookup(TONE, row.status) ?? TONE.completed
            }`}
          >
            {lookup(HEADINGS, row.status) ?? row.status}
          </span>
          {row.explanation && <p className="text-meta text-ink-muted">{row.explanation}</p>}
          {row.note && <p className="text-meta text-ink-muted">They said: {row.note}</p>}
        </div>
      ),
    },
    {
      id: "action",
      header: "Action",
      align: "right",
      cell: (row) =>
        // `dialing` is not stoppable: that phone may be ringing as this renders.
        row.status === "scheduled" && write.allowed ? (
          <button
            type="button"
            disabled={cancel.isPending && cancel.variables === row.id}
            onClick={() => setStopping(row)}
            className={TEXT_ACTION}
          >
            {cancel.isPending && cancel.variables === row.id ? "Calling it off…" : "Call it off"}
          </button>
        ) : row.status === "dialing" ? (
          <span className="text-meta text-ink-faint">Too late to stop</span>
        ) : row.settled_at ? (
          <span className="whitespace-nowrap text-meta text-ink-faint">{formatIST(row.settled_at)}</span>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6 pb-12">
      <PageHeader description="Calls your agents promised, placed at the time the caller asked." />
      {/* Qualifies the compliance gate every call-back passes: visible and word for word. */}
      <p className="max-w-prose text-meta text-ink-muted">
        It goes through the same checks as every other call — the do-not-call list,
        permitted calling hours, and your account&apos;s credit — so a promise that cannot
        lawfully be kept is stopped and says why.
      </p>

      <RestrictionNote reason={write.reason} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl label="Which call-backs" options={VIEWS} value={view} onValueChange={setView} />
        {rows && (
          <p className="text-meta text-ink-muted">
            <span className="font-semibold tabular-nums text-ink">{formatCount(rows.length)}</span>{" "}
            {openOnly ? "still to come" : rows.length === 1 ? "call-back" : "call-backs"}
          </p>
        )}
      </div>

      {callbacks.error && (
        <ProblemNotice error={callbacks.error} onRetry={() => callbacks.refetch()} />
      )}
      <div className="border-y border-line">
        {callbacks.isLoading ? (
          <div className="py-4">
            <Skeleton rows={5} label="Loading your call-backs" />
          </div>
        ) : !rows ? null : rows.length ? (
          <DataTable
            label={openOnly ? "Call-backs still to come" : "Every call-back"}
            rows={rows}
            columns={columns}
            getRowId={(row) => row.id}
          />
        ) : (
          <EmptyState
            illustration={<EmptySketch kind="callbacks" />}
            message={openOnly ? "Nobody is waiting for a call right now." : "No call-backs yet."}
            hint={
              openOnly
                ? undefined
                : "Agents book one when a caller asks to be rung back — switch it on under the agent's Remembering callers."
            }
          />
        )}
      </div>

      {stopping && (
        <ConfirmDialog
          title="Call this off?"
          confirmLabel="Do not ring them"
          pendingLabel="Calling it off…"
          cancelLabel="Keep it"
          pending={cancel.isPending}
          error={cancel.error}
          onCancel={() => {
            cancel.reset();
            setStopping(null);
          }}
          onConfirm={() => cancel.mutate(stopping.id, { onSuccess: () => setStopping(null) })}
        >
          <p>
            <MonoValue className="tabular-nums text-ink">{formatPhone(stopping.phone_e164)}</MonoValue>{" "}
            asked to be rung back on{" "}
            <strong className="font-semibold text-ink">{formatIST(stopping.requested_at)}</strong>.
          </p>
          <p>
            They will not be called.{" "}
            <strong className="font-semibold text-ink">Nobody tells them the call is off</strong>{" "}
            — if it matters, ring them yourself.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
