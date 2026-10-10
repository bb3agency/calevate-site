"use client";

import { useId, useState } from "react";
import { Plus } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import { RowMenu } from "@/components/console/rowMenu";
import { StepFlow } from "@/components/console/stepFlow";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  Skeleton,
  ToggleSwitch,
  formatIST,
} from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";
import {
  WEEKDAYS,
  scheduleWords,
  useCreateRoutine,
  useDeleteRoutine,
  useRoutineRuns,
  useRoutines,
  useRunRoutine,
  useUpdateRoutine,
  type CopilotRoutineOut,
  type CopilotRoutineRunOut,
  type Weekday,
} from "@/lib/copilot/workspace";

/** Starting points a person can pick and edit — the founder's own two examples first. */
const EXAMPLES: readonly { name: string; instruction: string; days: Weekday[]; time: string }[] = [
  {
    name: "Morning call-backs",
    instruction: "Call back yesterday's missed leads.",
    days: ["mon", "tue", "wed", "thu", "fri", "sat"],
    time: "09:30",
  },
  {
    name: "Friday lead summary",
    instruction: "Summarise this week's leads: how many came in, who is hot, and who to call next.",
    days: ["fri"],
    time: "17:00",
  },
];

const NAME_MAX = 80;
const INSTRUCTION_MAX = 2000;

/**
 * ROUTINES: things the assistant does on a schedule, as the person who set them up (D-694).
 *
 * Each run is a background task, so it meets every check a typed request meets. The rule
 * this screen states once, where the routine is made: anything that would call someone,
 * spend money or cannot be undone waits in Approvals — a routine never does it alone.
 */
export function Routines({ session }: { session: Session }) {
  const routines = useRoutines(session);
  const [editing, setEditing] = useState<CopilotRoutineOut | "new" | null>(null);
  const [history, setHistory] = useState<CopilotRoutineOut | null>(null);
  const [deleting, setDeleting] = useState<CopilotRoutineOut | null>(null);
  const update = useUpdateRoutine(session);
  const run = useRunRoutine(session);
  const remove = useDeleteRoutine(session);
  const [notice, setNotice] = useState<string | null>(null);

  const rows = routines.data?.routines ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-prose text-sm text-ink-muted">
          Calls, spending and anything that can&apos;t be undone wait for your approval.
        </p>
        <button type="button" onClick={() => setEditing("new")} className={PRIMARY_BUTTON}>
          <Plus aria-hidden className="h-4 w-4" />
          New routine
        </button>
      </div>

      {notice ? (
        <p role="status" className="text-body text-ink">
          {notice}
        </p>
      ) : null}
      {routines.error != null && (
        <ProblemNotice error={routines.error} onRetry={() => void routines.refetch()} />
      )}
      {routines.data === undefined && routines.error == null && (
        <Skeleton rows={3} label="Loading routines…" />
      )}
      {routines.data !== undefined && rows.length === 0 && (
        <EmptyState
          message="No routines yet."
          hint="For example: every weekday at 9:30 am, call back yesterday's missed leads."
        />
      )}
      {update.error != null && <ProblemNotice error={update.error} />}
      {run.error != null && <ProblemNotice error={run.error} />}

      {rows.length > 0 && (
        <ul className="divide-y divide-line border-y border-line" aria-label="Your routines">
          {rows.map((routine) => (
            <li
              key={routine.id}
              className="flex min-w-0 flex-col gap-3 py-3.5 sm:flex-row sm:items-start"
            >
              <div className="min-w-0 flex-1">
                <p className="break-words text-sm font-medium text-ink [overflow-wrap:anywhere]">
                  {routine.name}
                </p>
                <p className="mt-0.5 line-clamp-2 break-words text-sm text-ink-muted [overflow-wrap:anywhere]">
                  {routine.instruction}
                </p>
                <p className="mt-1 text-xs text-ink-faint">
                  {scheduleWords(routine.schedule)}
                  {routine.enabled && routine.next_run_at
                    ? ` · next ${formatIST(routine.next_run_at)}`
                    : " · off"}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <ToggleSwitch
                  label={<span className="sr-only">Run {routine.name} on its schedule</span>}
                  checked={routine.enabled}
                  disabled={update.isPending}
                  onChange={(enabled) => update.mutate({ id: routine.id, patch: { enabled } })}
                />
                <RowMenu
                  label={routine.name}
                  items={[
                    {
                      id: "run",
                      label: "Run now",
                      onSelect: () =>
                        run.mutate(routine.id, {
                          onSuccess: () => setNotice("Started. It's running as a background task."),
                        }),
                    },
                    { id: "edit", label: "Edit", onSelect: () => setEditing(routine) },
                    { id: "history", label: "History", onSelect: () => setHistory(routine) },
                    {
                      id: "delete",
                      label: "Delete",
                      tone: "danger",
                      onSelect: () => setDeleting(routine),
                    },
                  ]}
                />
              </div>
            </li>
          ))}
        </ul>
      )}

      <Drawer
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "New routine" : "Edit routine"}
        width="md"
      >
        {editing !== null && (
          <RoutineEditor
            session={session}
            routine={editing === "new" ? null : editing}
            onDone={() => setEditing(null)}
            onSaved={setNotice}
          />
        )}
      </Drawer>

      <Drawer
        open={history !== null}
        onClose={() => setHistory(null)}
        title={history?.name ?? "History"}
        description="When it ran, and what became of each run."
        width="lg"
      >
        {history !== null && <RunHistory session={session} routineId={history.id} />}
      </Drawer>

      {deleting !== null && (
        <ConfirmDialog
          title={`Delete ${deleting.name}?`}
          confirmLabel="Delete routine"
          pendingLabel="Deleting…"
          pending={remove.isPending}
          error={remove.error}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        >
          It stops running. Tasks it already started finish, and what they did stays in the
          activity log.
        </ConfirmDialog>
      )}
    </div>
  );
}

function RoutineEditor({
  session,
  routine,
  onDone,
  onSaved,
}: {
  session: Session;
  routine: CopilotRoutineOut | null;
  onDone: () => void;
  onSaved: (sentence: string) => void;
}) {
  const [name, setName] = useState(routine?.name ?? "");
  const [instruction, setInstruction] = useState(routine?.instruction ?? "");
  const [days, setDays] = useState<Weekday[]>(
    routine?.schedule.days ?? ["mon", "tue", "wed", "thu", "fri"],
  );
  const [time, setTime] = useState(routine?.schedule.time ?? "09:00");
  const create = useCreateRoutine(session);
  const update = useUpdateRoutine(session);
  const ids = { name: useId(), instruction: useId(), time: useId(), days: useId() };
  const pending = create.isPending || update.isPending;
  const error = create.error ?? update.error;
  const ordered = WEEKDAYS.map((day) => day.value).filter((day) => days.includes(day));
  const schedule = { days: ordered, time };

  const save = () => {
    const body = { name: name.trim(), instruction: instruction.trim(), schedule };
    const done = () => {
      onSaved(routine === null ? "Routine added." : "Routine saved.");
      onDone();
    };
    if (routine === null) create.mutate({ ...body, enabled: true }, { onSuccess: done });
    else update.mutate({ id: routine.id, patch: body }, { onSuccess: done });
  };

  return (
    <StepFlow
      label={routine === null ? "New routine" : "Edit routine"}
      submitLabel={routine === null ? "Add routine" : "Save routine"}
      onSubmit={save}
      pending={pending}
      error={error != null ? <ProblemNotice error={error} /> : undefined}
      steps={[
        {
          id: "what",
          title: "What should the assistant do?",
          hint: "Write it the way you'd ask it. It replies in the language you write in.",
          validate: () =>
            name.trim() === ""
              ? "Give the routine a name."
              : instruction.trim() === ""
                ? "Say what the assistant should do each time."
                : null,
          content: (
            <div className="space-y-4">
              {routine === null && (
                <div className="flex flex-wrap gap-2" role="group" aria-label="Start from an example">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example.name}
                      type="button"
                      onClick={() => {
                        setName(example.name);
                        setInstruction(example.instruction);
                        setDays(example.days);
                        setTime(example.time);
                      }}
                      className="press rounded-full border border-line px-3 py-1 text-xs text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
                    >
                      {example.name}
                    </button>
                  ))}
                </div>
              )}
              <div>
                <label htmlFor={ids.name} className={FIELD_LABEL}>
                  Name
                </label>
                <input
                  id={ids.name}
                  value={name}
                  maxLength={NAME_MAX}
                  onChange={(event) => setName(event.target.value)}
                  className={FIELD}
                />
              </div>
              <div>
                <label htmlFor={ids.instruction} className={FIELD_LABEL}>
                  What to do
                </label>
                <textarea
                  id={ids.instruction}
                  value={instruction}
                  rows={4}
                  maxLength={INSTRUCTION_MAX}
                  onChange={(event) => setInstruction(event.target.value)}
                  className={FIELD}
                />
                <span className={FIELD_HINT}>
                  Phone numbers you type here are hidden before it is saved.
                </span>
              </div>
            </div>
          ),
        },
        {
          id: "when",
          title: "When should it run?",
          hint: "India time.",
          validate: () => (days.length === 0 ? "Pick at least one day." : null),
          content: (
            <div className="space-y-4">
              <fieldset>
                <legend id={ids.days} className={FIELD_LABEL}>
                  Days
                </legend>
                <div className="mt-1 flex flex-wrap gap-2">
                  {WEEKDAYS.map((day) => {
                    const on = days.includes(day.value);
                    return (
                      <button
                        key={day.value}
                        type="button"
                        aria-pressed={on}
                        aria-label={day.long}
                        onClick={() =>
                          setDays((current) =>
                            on ? current.filter((value) => value !== day.value) : [...current, day.value],
                          )
                        }
                        className={`press h-9 min-w-11 rounded-md border px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 ${
                          on
                            ? "border-brand bg-brand-soft font-medium text-brand-strong"
                            : "border-line text-ink-muted hover:bg-ink/[0.04]"
                        }`}
                      >
                        {day.short}
                      </button>
                    );
                  })}
                </div>
              </fieldset>
              <div className="max-w-[10rem]">
                <label htmlFor={ids.time} className={FIELD_LABEL}>
                  Time
                </label>
                <input
                  id={ids.time}
                  type="time"
                  step={300}
                  value={time}
                  onChange={(event) => setTime(event.target.value.slice(0, 5) || "09:00")}
                  className={FIELD}
                />
              </div>
            </div>
          ),
        },
      ]}
      review={{
        title: "Check and save",
        content: (
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-ink-faint">Name</dt>
              <dd className="break-words text-ink [overflow-wrap:anywhere]">{name}</dd>
            </div>
            <div>
              <dt className="text-ink-faint">What it does</dt>
              <dd className="whitespace-pre-wrap break-words text-ink [overflow-wrap:anywhere]">
                {instruction}
              </dd>
            </div>
            <div>
              <dt className="text-ink-faint">When</dt>
              <dd className="text-ink">
                {days.length > 0 ? scheduleWords(schedule) : "No days picked"}
              </dd>
            </div>
            <div>
              <dt className="text-ink-faint">What waits for you</dt>
              <dd className="text-ink">
                Calling anyone, spending money and anything that can&apos;t be undone wait in
                Approvals. Small changes happen straight away, each with an Undo.
              </dd>
            </div>
          </dl>
        ),
      }}
    />
  );
}

const RUN_WORDS: Record<string, string> = {
  queued: "Started",
  running: "Running",
  done: "Finished",
  failed: "Stopped",
  cancelled: "Cancelled",
};

function RunHistory({ session, routineId }: { session: Session; routineId: string }) {
  const runs = useRoutineRuns(session, routineId);
  if (runs.error != null) {
    return <ProblemNotice error={runs.error} onRetry={() => void runs.refetch()} />;
  }
  if (runs.data === undefined) return <Skeleton rows={4} label="Loading history…" />;
  if (runs.data.runs.length === 0) {
    return <EmptyState message="It hasn't run yet." />;
  }
  const columns: DataColumn<CopilotRoutineRunOut>[] = [
    {
      id: "when",
      header: "When",
      sort: { value: (row) => row.created_at, kind: "time", first: "desc" },
      cell: (row) => <span className="whitespace-nowrap text-ink">{formatIST(row.created_at)}</span>,
    },
    {
      id: "how",
      header: "How",
      hideBelow: "sm",
      cell: (row) => (
        <span className="text-ink-muted">{row.trigger === "manual" ? "Run now" : "On schedule"}</span>
      ),
    },
    {
      id: "outcome",
      header: "Outcome",
      flash: (row) => row.job_status ?? row.status,
      cell: (row) =>
        row.status === "skipped" ? (
          <span className="block max-w-md text-ink-muted">Skipped. {row.reason}</span>
        ) : (
          <span className="text-ink">
            {lookup(RUN_WORDS, row.job_status ?? "queued") ?? "Started"}
          </span>
        ),
    },
  ];
  return (
    <DataTable
      rows={runs.data.runs}
      columns={columns}
      getRowId={(row) => row.id}
      label="Runs of this routine"
    />
  );
}
