"use client";

import Link from "next/link";
import { useState } from "react";
import { CalendarClock, PhoneOff, ShieldCheck } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { SelectionBar } from "@/components/arc/filter-toolbar";
import { useCallbackWhen } from "@/components/calls/followUpActions";
import { ConfirmDialog } from "@/components/confirmDialog";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { TEXT_ACTION } from "@/components/console/section";
import { HowItWorks } from "@/components/console/howItWorks";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ModalDialog } from "@/components/modalDialog";
import {
  MonoValue,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
  formatPhone,
} from "@/components/ui";
import {
  useCallbacks,
  useCancelCallback,
  useChangeCallbacks,
  useMoveCallback,
  type CallbacksBulkResult,
  type ScheduledCallback,
} from "@/lib/api/callbacks";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";
import { StatusPill } from "@/components/console/statusPill";
import type { NoticeTone } from "@/components/ui";

/**
 * THE CALL-BACKS PROMISED TO CALLERS AND LEADS (D-514, D-893).
 *
 * PRIMARY JOB: see which call-backs are coming, and move or stop one — or many — before
 * it goes out.
 *
 * - Every row says WHY in the API's own `explanation` (the compliance gate's client-facing
 *   sentence for a refusal). This screen prints it and never composes one.
 * - Moving offers only the times the server accepts (9am–9pm India time, `useCallbackWhen`,
 *   the same picker as "Call back later"). Calling off is a confirmation that states the
 *   consequence. Both close only on success: a failure leaves the dialog and the promise.
 * - Ticked rows change each on its own: one already being placed, ended or refused by a
 *   calling rule stays as it was, and the result says which and why, in the server's words.
 * - Loading, failure and empty are three states. "No call-backs" is said only from rows
 *   the server sent, never under a failed request.
 * - The checks a call-back passes (do-not-call, calling hours, credit) qualify a compliance
 *   control, so they stay visible as chips under the title rather than folding away.
 * - One short line per item (founder, Oct 2026: "buttons, not paragraphs"): the row actions
 *   are real buttons, and the detail sits behind How it works.
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

const TONE: Record<string, NoticeTone> = {
  scheduled: "neutral",
  dialing: "ok",
  completed: "neutral",
  refused: "stop",
  missed: "warn",
  failed: "warn",
};

/** Peer views of one list (D-655): the live promises, or every one. */
/** The checks every call-back passes before it rings: a compliance control, always shown. */
const CHECKS = ["Do-not-call list", "Calling hours", "Your credit"];

const VIEWS = [
  { value: "open", label: "Upcoming" },
  { value: "all", label: "All" },
];

/** What is being moved: one row from its own button, or the ticked ones. */
type Moving = { ids: string[]; one: ScheduledCallback | null };

function plural(n: number, one: string, many: string): string {
  return `${formatCount(n)} ${n === 1 ? one : many}`;
}

export function CallbacksScreen() {
  // `href` keeps the D-22 operator session on the link to the agents screen.
  const { session, href } = useClientRealm();
  const [view, setView] = useState("all");
  const openOnly = view === "open";
  const callbacks = useCallbacks(session, openOnly);
  const cancel = useCancelCallback(session);
  const move = useMoveCallback(session);
  const change = useChangeCallbacks(session);
  // The refusal is shown inside the dialog; the toast confirms once the dialog has closed.
  const cancelFeedback = useActionFeedback(cancel, {
    errorDisplay: "inline",
    successToast: "Call-back called off",
    successDescription: "Nobody will ring them for it.",
  });
  const moveFeedback = useActionFeedback(move, {
    errorDisplay: "inline",
    successToast: (row) => `Moved to ${formatIST(row.requested_at)}`,
  });
  const changeFeedback = useActionFeedback(change, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "leads:dispatch", "move or call off a call-back");
  const [stopping, setStopping] = useState<ScheduledCallback | null>(null);
  const [moving, setMoving] = useState<Moving | null>(null);
  const [stoppingMany, setStoppingMany] = useState<string[] | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [bulkResult, setBulkResult] = useState<CallbacksBulkResult | null>(null);
  const rows = callbacks.data;
  // Only rows still on screen count as ticked: a refetch can drop one that rang meanwhile.
  const ticked = rows ? rows.filter((row) => selected.has(row.id)).map((row) => row.id) : [];

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
    saves: "view",
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
            { key: "ticked", label: "Call-backs ticked", value: String(ticked.length) },
          ]
        : []),
      {
        key: "can_cancel",
        label: "Can this person move or call one off?",
        value: write.allowed ? "yes" : "no",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "callbacks-view") continue;
        const wanted = asText(item.value);
        if (VIEWS.some((option) => option.value === wanted)) setView(wanted);
      }
    },
  });

  const finishBulk = (result: CallbacksBulkResult) => {
    setBulkResult(result);
    // The selection is spent; leaving it ticked invites a second run.
    setSelected(new Set());
  };

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
      card: "block",
      flash: (row) => row.status,
      cell: (row) => (
        <div className="max-w-md space-y-1">
          <StatusPill tone={row.held ? "warn" : (lookup(TONE, row.status) ?? "neutral")} wrap>
            {row.held ? "On hold" : (lookup(HEADINGS, row.status) ?? row.status)}
          </StatusPill>
          {row.explanation && <p className="text-meta text-ink-muted">{row.explanation}</p>}
          {/* Not "They said": the note is the agent's summary, a team member's note, or ours
              ("A new enquiry who did not answer the last try"), never the caller's words. */}
          {row.note && <p className="text-meta text-ink-muted">Note: {row.note}</p>}
        </div>
      ),
    },
    {
      id: "action",
      header: "Action",
      align: "right",
      card: "block",
      cell: (row) =>
        // `dialing` is not stoppable: that phone may be ringing as this renders.
        row.status === "scheduled" && write.allowed ? (
          // Two equal buttons, side by side and full width on a phone (44px targets).
          <div className="grid grid-cols-2 gap-2 max-sm:pt-1 sm:flex sm:justify-end">
            <button
              type="button"
              onClick={() => {
                move.reset();
                setMoving({ ids: [row.id], one: row });
              }}
              className={`${SECONDARY_BUTTON_SM} justify-center whitespace-nowrap max-sm:min-h-11`}
            >
              <CalendarClock aria-hidden className="h-3.5 w-3.5" />
              Move
            </button>
            <button
              type="button"
              disabled={cancel.isPending && cancel.variables === row.id}
              onClick={() => setStopping(row)}
              className={`${SECONDARY_BUTTON_SM} justify-center whitespace-nowrap max-sm:min-h-11`}
            >
              <PhoneOff aria-hidden className="h-3.5 w-3.5" />
              {cancel.isPending && cancel.variables === row.id ? "Calling off…" : "Call off"}
            </button>
          </div>
        ) : row.status === "dialing" ? (
          <span className="text-meta text-ink-faint">Too late to stop</span>
        ) : row.settled_at ? (
          <span className="whitespace-nowrap text-meta text-ink-faint">{formatIST(row.settled_at)}</span>
        ) : null,
    },
  ];

  return (
    <div className="max-w-4xl space-y-6 pb-12">
      {/* The checks every call-back passes qualify a compliance control, so they stay on the
          page as chips under the title; the rest is behind How it works. */}
      <div>
        <PageHeader description="Calls your agents promised to make." />
        <ul aria-label="Checked before each call-back" className="mt-2 flex flex-wrap items-center gap-1.5 text-meta text-ink-muted">
          <li className="inline-flex items-center gap-1">
            <ShieldCheck aria-hidden className="h-3.5 w-3.5 text-brand-strong" />
            Checked first:
          </li>
          {CHECKS.map((check) => (
            <li key={check} className="rounded-md bg-surface-muted px-2 py-0.5 text-ink">
              {check}
            </li>
          ))}
        </ul>
        <HowItWorks
          headingLevel={3}
          items={[
            "It rings at the time the caller asked for.",
            "If a check stops it, the row says why.",
            "Move it to any time, 9am to 9pm.",
            "Calling off does not tell the caller.",
            "Ring them yourself if it matters.",
          ]}
        />
      </div>

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

      {bulkResult && <BulkResult result={bulkResult} onDismiss={() => setBulkResult(null)} />}

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
            selection={
              write.allowed
                ? {
                    selected,
                    onChange: setSelected,
                    rowLabel: (row) => `Select the call-back to ${formatPhone(row.phone_e164)}`,
                    allLabel: "Select every call-back listed",
                  }
                : undefined
            }
          />
        ) : (
          <EmptyState
            illustration={<EmptySketch kind="callbacks" />}
            message={openOnly ? "Nobody is waiting for a call." : "No call-backs yet."}
            hint={openOnly ? undefined : "Agents book one when a caller asks."}
            action={
              openOnly ? (
                <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setView("all")}>
                  Show all
                </button>
              ) : (
                // Call-backs are switched on per agent, under its Remembering callers.
                <Link href={href(`/c/${session.orgSlug}/agents`)} className={SECONDARY_BUTTON_SM}>
                  Turn on in Agents
                </Link>
              )
            }
          />
        )}
      </div>

      <SelectionBar count={ticked.length} noun="call-back" onClear={() => setSelected(new Set())}>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          onClick={() => {
            change.reset();
            setMoving({ ids: ticked, one: null });
          }}
        >
          Move
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          onClick={() => {
            change.reset();
            setStoppingMany(ticked);
          }}
        >
          Call off
        </button>
      </SelectionBar>

      {stopping && (
        <ConfirmDialog
          title="Call this off?"
          confirmLabel="Do not ring them"
          pendingLabel="Calling it off…"
          cancelLabel="Keep it"
          status={cancelFeedback.status}
          error={cancel.error}
          onCancel={() => {
            cancel.reset();
            setStopping(null);
          }}
          onConfirm={() => cancel.mutate(stopping.id, { onSuccess: () => setStopping(null) })}
        >
          <p>
            <MonoValue className="tabular-nums text-ink">{formatPhone(stopping.phone_e164)}</MonoValue>
            {" · due "}
            <strong className="font-semibold text-ink">{formatIST(stopping.requested_at)}</strong>
          </p>
          <p>
            <strong className="font-semibold text-ink">Nobody tells them.</strong> Ring them if it matters.
          </p>
        </ConfirmDialog>
      )}

      {stoppingMany && (
        <ConfirmDialog
          title={`Call off ${plural(stoppingMany.length, "call-back", "call-backs")}?`}
          confirmLabel="Do not ring them"
          pendingLabel="Calling them off…"
          cancelLabel="Keep them"
          status={changeFeedback.status}
          error={change.error}
          onCancel={() => {
            change.reset();
            setStoppingMany(null);
          }}
          onConfirm={() =>
            change.mutate(
              { action: "cancel", callback_ids: stoppingMany },
              {
                onSuccess: (result) => {
                  finishBulk(result);
                  setStoppingMany(null);
                },
              },
            )
          }
        >
          <p>
            <strong className="font-semibold text-ink">Nobody tells them.</strong> Ring them if it matters.
          </p>
          <p>Ones already ringing or done stay as they are.</p>
        </ConfirmDialog>
      )}

      {moving && (
        <MoveDialog
          moving={moving}
          status={moving.one ? moveFeedback.status : changeFeedback.status}
          error={moving.one ? move.error : change.error}
          onClose={() => {
            move.reset();
            change.reset();
            setMoving(null);
          }}
          onMove={(at) => {
            if (moving.one) {
              move.mutate({ callbackId: moving.one.id, at }, { onSuccess: () => setMoving(null) });
              return;
            }
            change.mutate(
              { action: "move", callback_ids: moving.ids, at },
              {
                onSuccess: (result) => {
                  finishBulk(result);
                  setMoving(null);
                },
              },
            );
          }}
        />
      )}
    </div>
  );
}

function MoveDialog({
  moving,
  status,
  error,
  onClose,
  onMove,
}: {
  moving: Moving;
  status: ReturnType<typeof useActionFeedback>["status"];
  error: unknown;
  onClose: () => void;
  onMove: (at: string) => void;
}) {
  const when = useCallbackWhen();
  const one = moving.one;
  const submit = () => {
    const at = when.check();
    if (at) onMove(at);
  };
  return (
    <ModalDialog
      title={one ? "Move this call-back" : `Move ${plural(moving.ids.length, "call-back", "call-backs")}`}
      description={
        one ? (
          <>
            <MonoValue className="block tabular-nums font-medium text-ink">
              {formatPhone(one.phone_e164)}
            </MonoValue>
            Now due {formatIST(one.requested_at)}. Pick a time, 9am to 9pm.
          </>
        ) : (
          "Pick a time, 9am to 9pm. Ones already ringing stay."
        )
      }
      onClose={onClose}
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={status === "pending"}>
            Cancel
          </button>
          <ActionButton status={status} successLabel="Moved" pendingLabel="Moving…" onClick={submit}>
            {one ? "Move it" : "Move them"}
          </ActionButton>
        </>
      }
    >
      <form
        className="mt-4 space-y-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {when.fields}
        <ProblemNotice error={error} />
      </form>
    </ModalDialog>
  );
}

/** What a change to the ticked rows did, in the server's words for each one left out. */
function BulkResult({ result, onDismiss }: { result: CallbacksBulkResult; onDismiss: () => void }) {
  const moved = result.results.filter((r) => r.status === "moved").length;
  const cancelled = result.results.filter((r) => r.status === "cancelled").length;
  const leftOut = result.results.filter((r) => r.status !== "moved" && r.status !== "cancelled");
  const reasons = new Map<string, number>();
  for (const r of leftOut) {
    const reason = r.reason ?? "It could not be found any more.";
    reasons.set(reason, (reasons.get(reason) ?? 0) + 1);
  }
  const done = [
    moved ? `Moved ${plural(moved, "call-back", "call-backs")}.` : null,
    cancelled ? `Called off ${plural(cancelled, "call-back", "call-backs")}.` : null,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <NoticeBox
      tone={leftOut.length ? "warn" : "ok"}
      role="status"
      title={done || "Nothing was changed."}
      action={
        <button type="button" className={TEXT_ACTION} onClick={onDismiss}>
          Dismiss
        </button>
      }
    >
      {leftOut.length > 0 && (
        <ul className="space-y-0.5 text-meta text-ink-muted [overflow-wrap:anywhere]">
          {[...reasons.entries()].map(([reason, count]) => (
            <li key={reason}>
              {plural(count, "left as it was", "left as they were")}: {reason}
            </li>
          ))}
        </ul>
      )}
    </NoticeBox>
  );
}
