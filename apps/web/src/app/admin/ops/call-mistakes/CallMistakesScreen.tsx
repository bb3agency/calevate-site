"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { WriteFailure } from "@/app/admin/writeFailure";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Field } from "@/components/arc/field";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { ModalDialog } from "@/components/modalDialog";
import {
  FIELD,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import {
  FIX_NOTE_MAX,
  useMarkMistakeFixed,
  usePlatformMistakes,
  type MistakeState,
  type PlatformMistake,
} from "@/lib/api/callMistakes";
import { viewAsHref } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

const STATE_LABELS: Record<MistakeState, string> = {
  back: "Back after the fix",
  fixing: "Not fixed yet",
  fixed: "Fixed",
};

const STATE_TONES: Record<MistakeState, NoticeTone> = {
  back: "stop",
  fixing: "warn",
  fixed: "ok",
};

/**
 * Ops > Call mistakes (D-949): what agents got wrong on real calls across every account,
 * by kind. Each kind is a platform rule we fix, never the client; "Mark fixed" records that
 * the rule changed, with a note, and from then on a call showing the kind counts as it
 * coming back. The server orders the rows (back, not fixed, fixed) and works out the state.
 */
export function CallMistakesScreen() {
  const access = useAdminAccess("ops:manage", "read and mark the call mistakes");
  const board = usePlatformMistakes(!access.refused);
  const [fixing, setFixing] = useState<PlatformMistake | null>(null);
  const data = board.data;

  useCopilotSurface({
    route: "/admin/ops/call-mistakes",
    title: "Call mistakes",
    realm: "admin",
    fields: [],
    facts: access.refused
      ? [{ key: "board", label: "The board", value: "withheld — this admin account may not read it" }]
      : data
        ? [
            { key: "window_days", label: "Window (days)", value: String(data.window_days) },
            {
              key: "open",
              label: "Kinds not fixed or back after a fix",
              value:
                data.items
                  .filter((row) => row.state !== "fixed")
                  .map((row) => `${row.label} (${STATE_LABELS[row.state]}, ${row.calls_7d} calls in 7 days)`)
                  .join("; ") || "none",
            },
          ]
        : [{ key: "board", label: "The board", value: board.error ? "could not be read" : "still loading" }],
    apply: noFill,
  });

  const columns: DataColumn<PlatformMistake>[] = [
    {
      id: "label",
      header: "Mistake",
      cell: (row) => (
        <span className="[overflow-wrap:anywhere]">
          <span className="font-medium text-ink">{row.label}</span>
          <span className="block text-meta text-ink-muted">
            {row.rule ? `Fix in: ${row.rule}` : "No platform rule traced yet"}
          </span>
        </span>
      ),
      card: "block",
    },
    {
      id: "example",
      header: "Latest call",
      card: "block",
      cell: (row) =>
        row.last_call_id && row.last_client_slug ? (
          <a
            href={viewAsHref(row.last_client_slug, `/calls/${row.last_call_id}`)}
            className={TEXT_ACTION}
            aria-label={`Open the latest call: ${row.label}`}
          >
            Open the call
          </a>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    {
      id: "calls_7d",
      header: "Last 7 days",
      align: "right",
      cell: (row) => formatCount(row.calls_7d),
      sort: { value: (row) => row.calls_7d, kind: "number", first: "desc" },
    },
    {
      id: "calls_30d",
      header: "Last 30 days",
      align: "right",
      cell: (row) => formatCount(row.calls_30d),
      sort: { value: (row) => row.calls_30d, kind: "number", first: "desc" },
    },
    {
      id: "accounts_30d",
      header: "Accounts",
      align: "right",
      cell: (row) => formatCount(row.accounts_30d),
      sort: { value: (row) => row.accounts_30d, kind: "number", first: "desc" },
    },
    {
      id: "since_fix",
      header: "Since fix",
      align: "right",
      cell: (row) => (row.fixed_at ? formatCount(row.calls_since_fix) : "—"),
    },
    {
      id: "last_seen",
      header: "Last seen (IST)",
      cell: (row) => formatIST(row.last_seen_at),
      sort: { value: (row) => row.last_seen_at, kind: "time", first: "desc" },
    },
    {
      id: "state",
      header: "State",
      cell: (row) => <StatusPill tone={STATE_TONES[row.state]}>{STATE_LABELS[row.state]}</StatusPill>,
    },
    {
      id: "fix_note",
      header: "Fix note",
      card: "block",
      cell: (row) =>
        row.fix_note ? (
          <span className="[overflow-wrap:anywhere]">
            {row.fix_note}
            {row.fixed_at ? (
              <span className="block text-meta text-ink-muted">
                {formatIST(row.fixed_at)}
                {row.fixed_by ? ` · ${row.fixed_by}` : null}
              </span>
            ) : null}
          </span>
        ) : (
          <span className="text-ink-muted">—</span>
        ),
    },
    {
      id: "action",
      header: "Action",
      card: "block",
      cell: (row) => (
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          onClick={() => setFixing(row)}
          aria-label={`Mark fixed: ${row.label}`}
        >
          Mark fixed
        </button>
      ),
    },
  ];

  return (
    <div className="max-w-6xl space-y-8 pb-12">
      <PageHeader description="What agents got wrong on real calls, across every account." />
      {access.refused ? (
        <RestrictionNote reason={access.reason} />
      ) : board.error ? (
        <ProblemNotice error={board.error} onRetry={() => void board.refetch()} />
      ) : !data ? (
        <Skeleton rows={5} label="Loading the call mistakes" />
      ) : (
        <Section
          title={`Mistakes on real calls, last ${data.window_days} days`}
          info={
            <p>
              Each is a platform rule we fix. Open the latest call, change the rule named under
              the mistake, then mark it fixed; a call showing it again counts as it coming back.
            </p>
          }
        >
          <DataTable
            rows={data.items}
            columns={columns}
            getRowId={(row) => row.kind}
            label="Call mistakes by kind"
            empty="No mistakes found on real calls."
          />
        </Section>
      )}
      {fixing ? <MarkFixedDialog mistake={fixing} onClose={() => setFixing(null)} /> : null}
    </div>
  );
}

function MarkFixedDialog({ mistake, onClose }: { mistake: PlatformMistake; onClose: () => void }) {
  const mark = useMarkMistakeFixed();
  const feedback = useActionFeedback(mark, { errorDisplay: "inline", successToast: "Marked fixed" });
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  const blank = note.trim() === "";

  const submit = () => {
    setTried(true);
    // The form has no submit button inside it, so Enter submits it directly rather than
    // through the busy button below.
    if (blank || mark.isPending) return;
    mark.mutate({ kind: mistake.kind, note: note.trim() }, { onSuccess: onClose });
  };

  return (
    <ModalDialog
      title={`Mark fixed: ${mistake.label}`}
      description="Say what changed in the platform rule. From now on, a call showing this mistake counts as it coming back."
      onClose={onClose}
      initialFocus="first-tabbable"
      actions={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={mark.isPending}>
            Cancel
          </button>
          <ActionButton status={feedback.status} pendingLabel="Saving…" successLabel="Marked" onClick={submit}>
            Mark fixed
          </ActionButton>
        </>
      }
    >
      <form
        className="mt-4 space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field
          label="What changed"
          hint={`One line, up to ${FIX_NOTE_MAX} characters.`}
          error={tried && blank ? "Write what changed." : null}
        >
          {(control) => (
            <input
              {...control}
              required
              maxLength={FIX_NOTE_MAX}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className={FIELD}
            />
          )}
        </Field>
        {mark.error ? <WriteFailure error={mark.error} actionLabel="Mark fixed" /> : null}
      </form>
    </ModalDialog>
  );
}
