"use client";

import { useState, type ReactNode } from "react";
import { CalendarClock, Hourglass, ShieldAlert, TriangleAlert } from "lucide-react";

import {
  Card,
  DANGER_BUTTON,
  EmptyState,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NOTICE_TONES,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  SectionHeading,
  Skeleton,
  StatTile,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import {
  useAmendMaintenance,
  useCancelMaintenance,
  useEndMaintenance,
  useMaintenanceBoard,
  useScheduleMaintenance,
  type MaintenanceInFlight,
  type MaintenanceWindow,
} from "@/lib/api/maintenance";

/**
 * Planned maintenance — schedule one, watch it drain, and end it.
 *
 * ══ WHY THIS SCREEN LOOKS THE WAY IT DOES ═══════════════════════════════════════════
 *
 * The founder's brief names the failure this page exists to prevent, in one sentence:
 * *"an operator staring at a spinner with no numbers will force it and break a live
 * call."* Everything below follows from that.
 *
 * 1. **The drain panel leads with the two numbers**, how old they are, and the deadline —
 *    before any button. A person deciding whether to wait needs the measurement first.
 * 2. **The straggler report survives the activation that produced it.** When a window
 *    forces, the counts it forced on stay on the screen; the alternative is an operator
 *    reading a live probe from ten minutes later and concluding the deadline was fine.
 * 3. **`announced` disables the start input rather than hiding the rule.** The server
 *    refuses to move an announced start (`amend_window`); the console says so BEFORE the
 *    operator types, with the reason, and offers the honest alternative (cancel and
 *    reschedule). A screen that let them type and then showed a 409 would teach them to
 *    treat this surface's refusals as noise.
 * 4. **Nothing here is computed from the browser's clock.** `state` is the worker's word,
 *    `measured_at` is the server's instant, `drain_deadline_at` is a column. A laptop four
 *    minutes fast must not be able to render "active" over a platform that is draining.
 *
 * The page carries no `<h1>`: the shell derives the title from the nav list
 * (`app/admin/layout.tsx`).
 */

/**
 * A state word in the shared four-tone palette.
 *
 * NOT `StatusBadge`, which is the LEAD/CALL status chip and looks its value up in a fixed
 * table of those vocabularies — a maintenance state passed to it would fall through to the
 * grey default, so five states would render identically and the badge would be decoration.
 * `NOTICE_TONES` is the same palette every verdict box in the console already uses (ux-audit
 * F-10), so this is one component reusing the token map rather than a sixth colour table.
 */
function TonePill({ tone, children }: { tone: NoticeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${NOTICE_TONES[tone]}`}
    >
      {children}
    </span>
  );
}

/** Where each state sits in the two-state model, in the operator's words. */
const STATE_COPY: Record<
  MaintenanceWindow["state"],
  { label: string; tone: NoticeTone; what: string }
> = {
  scheduled: {
    label: "Scheduled",
    tone: "neutral",
    what: "Nothing has changed yet. Clients see a banner; calls and campaigns run normally.",
  },
  draining: {
    label: "Draining",
    tone: "warn",
    what:
      "The platform has stopped starting new work and is waiting for what is already " +
      "running. Client portals are still OPEN. Inbound callers hear the maintenance " +
      "message; campaigns are paused.",
  },
  active: {
    label: "Active",
    tone: "stop",
    what:
      "Client portals are closed. Inbound calls are still answered, with the maintenance " +
      "message. Nothing has been deleted.",
  },
  completed: { label: "Finished", tone: "ok", what: "Everything is back." },
  cancelled: { label: "Called off", tone: "ok", what: "The window never opened." },
};

function InFlightPanel({
  inFlight,
  title,
  hint,
}: {
  inFlight: MaintenanceInFlight;
  title: string;
  hint: string;
}) {
  return (
    <div className="space-y-3">
      <SectionHeading icon={<Hourglass className="h-3.5 w-3.5" />}>{title}</SectionHeading>
      <div className="grid gap-3 sm:grid-cols-2">
        <StatTile label="Calls still up" value={String(inFlight.calls)} />
        <StatTile label="Jobs still queued" value={String(inFlight.jobs)} />
      </div>
      <p className="text-xs text-ink-faint">
        {hint} Measured {formatIST(inFlight.measured_at)}.
      </p>
      {/* A FLOOR IS NOT A TOTAL, and this is the one caveat that changes a decision: the
          probe walks every client one at a time under a time budget, and a walk that ran
          out has not asked everybody. The window will not activate on it, and neither
          should the operator. */}
      {!inFlight.complete && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert className="h-5 w-5" />}
          title="These numbers are a floor, not a total"
        >
          <p className="mt-1">
            The check could not reach {inFlight.tenants_unreached} client
            {inFlight.tenants_unreached === 1 ? "" : "s"} before its time budget ran out, so
            each of them may be holding a call this count does not include. The window will
            not activate on an incomplete check.
          </p>
        </NoticeBox>
      )}
    </div>
  );
}

function CurrentWindow({ window: current }: { window: MaintenanceWindow }) {
  const copy = STATE_COPY[current.state];
  const amend = useAmendMaintenance();
  const cancel = useCancelMaintenance();
  const end = useEndMaintenance();
  const [reason, setReason] = useState(current.reason);
  const [startsAt, setStartsAt] = useState(toLocalInput(current.starts_at));
  const [endsAt, setEndsAt] = useState(toLocalInput(current.ends_at));
  const [drain, setDrain] = useState(String(current.max_drain_minutes));
  // A window that has BEGUN is not rescheduled — its start is history and the API refuses
  // it by name. A `scheduled` one moves freely, announced or not: the commitment is kept
  // by re-announcing, not by freezing.
  const movable = current.state === "scheduled";

  return (
    <Card>
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <TonePill tone={copy.tone}>{copy.label}</TonePill>
          {current.forced && (
            <TonePill tone="stop">Activated on the deadline, not on a clean drain</TonePill>
          )}
        </div>
        <p className="text-sm text-ink-muted">{copy.what}</p>

        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile label="Opens" value={formatIST(current.starts_at)} />
          <StatTile label="Ends" value={formatIST(current.ends_at)} />
          <StatTile
            label="Drain deadline"
            value={
              current.drain_deadline_at === null
                ? `${current.max_drain_minutes} min once it opens`
                : formatIST(current.drain_deadline_at)
            }
          />
        </div>

        <div className="rounded-md border border-line bg-surface-subtle p-3">
          <p className="text-xs font-medium text-ink-muted">What clients are being told</p>
          <p className="mt-1 text-sm text-ink">{current.reason}</p>
        </div>

        {current.state === "draining" && current.in_flight !== null && (
          <InFlightPanel
            inFlight={current.in_flight}
            title="What the drain is waiting for"
            hint={
              "The window becomes active by itself when both reach zero, or on the deadline " +
              "above — whichever comes first. Nothing is cancelled either way: a call that is " +
              "up stays up and still produces its post-call record."
            }
          />
        )}

        {current.stragglers !== null && (
          <InFlightPanel
            inFlight={current.stragglers}
            title="What was still running when it activated"
            hint="These are the counts the activation decision was taken on."
          />
        )}

        {/* AMENDING. The start is deliberately absent from this form once a window is
            open — it is history by then — and `announced` is what removes it from the
            scheduling form too. */}
        <div className="space-y-3">
          <SectionHeading icon={<CalendarClock className="h-3.5 w-3.5" />}>Change it</SectionHeading>
          <label className="block">
            <span className={FIELD_LABEL}>What clients are told</span>
            <textarea
              value={reason}
              rows={2}
              onChange={(event) => setReason(event.target.value)}
              className={FIELD}
            />
            <span className={FIELD_HINT}>
              Shown verbatim in the email and on the page a locked-out client sees. Changing
              it re-notifies every client.
            </span>
          </label>
          {current.announced && (
            <NoticeBox
              tone="neutral"
              icon={<CalendarClock className="h-5 w-5" />}
              title="Clients have already been told about this window"
            >
              <p className="mt-1">
                Changing the time or the wording emails every client again with the window
                as it now is. That is the point — a client holding an old time is worse than
                a second email — but it is not a silent edit.
              </p>
            </NoticeBox>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            {movable && (
              <label className="block">
                <span className={FIELD_LABEL}>Opens at</span>
                <input
                  type="datetime-local"
                  value={startsAt}
                  onChange={(event) => setStartsAt(event.target.value)}
                  className={FIELD}
                />
                <span className={FIELD_HINT}>
                  Movable until the window opens. After that it is history — end it instead.
                </span>
              </label>
            )}
            <label className="block">
              <span className={FIELD_LABEL}>Ends at</span>
              <input
                type="datetime-local"
                value={endsAt}
                onChange={(event) => setEndsAt(event.target.value)}
                className={FIELD}
              />
              <span className={FIELD_HINT}>
                Every refused client request is told to come back at this time.
              </span>
            </label>
            <label className="block">
              <span className={FIELD_LABEL}>Drain bound (minutes)</span>
              <input
                type="number"
                min={1}
                max={240}
                value={drain}
                onChange={(event) => setDrain(event.target.value)}
                className={FIELD}
              />
              <span className={FIELD_HINT}>
                How long to wait for in-flight work before activating anyway. Editable while
                it drains.
              </span>
            </label>
          </div>
          {amend.error !== null && <ProblemNotice error={amend.error} />}
          <button
            type="button"
            className={SECONDARY_BUTTON}
            disabled={amend.isPending}
            onClick={() =>
              amend.mutate({
                windowId: current.id,
                // The start is sent only from a state that can take it, and only when it
                // moved — the API refuses a start change on a window that has begun, and a
                // form that sent one unchanged would turn every save into that refusal.
                startsAt:
                  !movable || startsAt === toLocalInput(current.starts_at)
                    ? undefined
                    : (fromLocalInput(startsAt) ?? undefined),
                // ONLY WHAT MOVED. Each field is compared in the representation the INPUT
                // holds, not against the ISO string on the row: the two differ by
                // formatting after one round trip through `datetime-local`, so comparing
                // against the row would mark an untouched field as changed on every save.
                // That is not cosmetic — a client-visible change re-notifies every client,
                // so a spurious `ends_at` would email the whole fleet because an operator
                // gave the drain five more minutes.
                reason: reason === current.reason ? undefined : reason,
                endsAt:
                  endsAt === toLocalInput(current.ends_at)
                    ? undefined
                    : (fromLocalInput(endsAt) ?? undefined),
                maxDrainMinutes:
                  Number(drain) === current.max_drain_minutes ? undefined : Number(drain),
              })
            }
          >
            {amend.isPending ? "Saving…" : "Save changes"}
          </button>
        </div>

        <div className="space-y-3 border-t border-line pt-4">
          <SectionHeading icon={<ShieldAlert className="h-3.5 w-3.5" />}>Stop it</SectionHeading>
          {cancel.error !== null && <ProblemNotice error={cancel.error} />}
          {end.error !== null && <ProblemNotice error={end.error} />}
          <div className="flex flex-wrap gap-3">
            {/* CANCEL vs END. Two verbs because the server treats them as two things,
                and each is rendered only where it is accepted rather than rendered to
                fail — a button that 409s teaches an operator to read this surface's
                refusals as noise. A window that has not BEGUN is called off (nothing has
                happened); one that is draining or active is ENDED, which is what puts the
                campaigns and the agents back. */}
            {current.state === "scheduled" ? (
              <button
                type="button"
                className={SECONDARY_BUTTON}
                disabled={cancel.isPending}
                onClick={() => cancel.mutate(current.id)}
              >
                {cancel.isPending ? "Calling it off…" : "Call it off"}
              </button>
            ) : (
              <button
                type="button"
                className={DANGER_BUTTON}
                disabled={end.isPending}
                onClick={() => end.mutate(current.id)}
              >
                {end.isPending
                  ? "Ending…"
                  : current.state === "active"
                    ? "End now and reopen the portals"
                    : "Stop now and put everything back"}
              </button>
            )}
          </div>
          <p className="text-xs text-ink-faint">
            Ending restores the portals first, then resumes every campaign this window
            paused and puts every agent back to its own script. That last part is a round
            trip per agent — watch for <code>maintenance_voice_incomplete</code>.
          </p>
        </div>
      </div>
    </Card>
  );
}

function ScheduleForm({ leadHours }: { leadHours: number }) {
  const schedule = useScheduleMaintenance();
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [reason, setReason] = useState("");
  const [drain, setDrain] = useState("15");
  const start = fromLocalInput(startsAt);
  const finish = fromLocalInput(endsAt);
  const ready = start !== null && finish !== null && reason.trim().length >= 10;

  return (
    <Card>
      <div className="space-y-4">
        <SectionHeading icon={<CalendarClock className="h-3.5 w-3.5" />}>Schedule a window</SectionHeading>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className={FIELD_LABEL}>Opens at</span>
            <input
              type="datetime-local"
              value={startsAt}
              onChange={(event) => setStartsAt(event.target.value)}
              className={FIELD}
            />
            <span className={FIELD_HINT}>
              {/* THE CONFIGURED LEAD, FROM THE SERVER. This said "24 hours" and "once that
                  has gone out this time is fixed" — the first is now a dial an operator
                  sets and the second is no longer true, so both halves were a screen
                  stating a rule the platform does not follow. */}
              Clients are emailed {leadHours} {leadHours === 1 ? "hour" : "hours"} ahead
              (set in Platform configuration). Scheduling closer than that is allowed — they
              simply get less notice, and it is recorded.
            </span>
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Ends at</span>
            <input
              type="datetime-local"
              value={endsAt}
              onChange={(event) => setEndsAt(event.target.value)}
              className={FIELD}
            />
            <span className={FIELD_HINT}>Over-run it and clients retry into a closed door.</span>
          </label>
        </div>
        <label className="block">
          <span className={FIELD_LABEL}>What clients are told</span>
          <textarea
            value={reason}
            rows={2}
            placeholder="We are upgrading the telephony stack. Nothing is deleted."
            onChange={(event) => setReason(event.target.value)}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            Written for a clinic owner, not an engineer. It is the email and the lockout page.
          </span>
        </label>
        <label className="block max-w-xs">
          <span className={FIELD_LABEL}>Drain bound (minutes)</span>
          <input
            type="number"
            min={1}
            max={240}
            value={drain}
            onChange={(event) => setDrain(event.target.value)}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            How long to wait for live calls and queued work before activating anyway.
          </span>
        </label>
        {schedule.error !== null && <ProblemNotice error={schedule.error} />}
        <button
          type="button"
          className={PRIMARY_BUTTON}
          disabled={!ready || schedule.isPending}
          onClick={() => {
            if (start === null || finish === null) return;
            schedule.mutate({
              startsAt: start,
              endsAt: finish,
              reason: reason.trim(),
              maxDrainMinutes: Number(drain),
            });
          }}
        >
          {schedule.isPending ? "Scheduling…" : "Schedule it"}
        </button>
      </div>
    </Card>
  );
}

export default function MaintenancePage() {
  const board = useMaintenanceBoard();
  const current = board.data?.current ?? null;
  const history = board.data?.history ?? [];

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        A planned window closes the client portals and answers inbound callers with a
        message instead of doing business. It opens by DRAINING — no new calls, no new
        campaign dials — and only becomes active once nothing is left in flight.
      </p>

      {board.error !== null && (
        <ProblemNotice error={board.error} onRetry={() => void board.refetch()} />
      )}

      {board.isLoading ? (
        <Card>
          <Skeleton rows={4} />
        </Card>
      ) : board.error !== null || board.data === undefined ? (
        // A FAILED OR PAUSED READ IS NOT "NO WINDOW". TanStack pauses a query while the
        // browser is offline — `isLoading` false, `error` null, `data` undefined — and the
        // schedule form below would otherwise invite an operator to book a second window
        // over one they simply could not see.
        <Card>
          <NoticeBox
            tone="warn"
            icon={<TriangleAlert className="h-5 w-5" />}
            title="The maintenance board could not be read"
          >
            <p className="mt-1">
              So we cannot say whether a window is open. This is not an empty schedule — do
              not book one until this reads.
            </p>
          </NoticeBox>
        </Card>
      ) : current !== null ? (
        <CurrentWindow window={current} />
      ) : (
        <>
          <NoticeBox
            tone="neutral"
            icon={<CalendarClock className="h-5 w-5" />}
            title="No window is open"
          >
            <p className="mt-1">
              The platform has one maintenance slot. Scheduling a second while one is open
              is refused.
            </p>
          </NoticeBox>
          <ScheduleForm leadHours={board.data.notice_lead_hours} />
        </>
      )}

      <Card bodyClassName="p-0">
        <div className="p-4">
          <SectionHeading icon={<CalendarClock className="h-3.5 w-3.5" />}>Recent windows</SectionHeading>
        </div>
        {history.length === 0 ? (
          <EmptyState
            title="No windows yet"
            hint="Scheduled maintenance is recorded here — including the ones that were called off."
          />
        ) : (
          <ul className="divide-y divide-line">
            {history.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                <TonePill tone={STATE_COPY[row.state].tone}>
                  {STATE_COPY[row.state].label}
                </TonePill>
                <span className="text-ink">{formatIST(row.starts_at)}</span>
                <span className="text-ink-faint">→ {formatIST(row.ends_at)}</span>
                {row.forced && (
                  <span className="inline-flex items-center gap-1 text-xs text-ink-muted">
                    <Hourglass className="h-3.5 w-3.5" />
                    forced on the deadline
                  </span>
                )}
                <span className="min-w-0 flex-1 truncate text-ink-muted">{row.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <NoticeBox
        tone="neutral"
        icon={<ShieldAlert className="h-5 w-5" />}
        title="What a window does not do"
      >
        <p className="mt-1">
          It never hangs up a live call and never cancels a queued job — the deadline bounds
          how long the PLATFORM waits, not how long other people&apos;s work takes. It
          deletes nothing. And it never locks operators out: this console, the health checks
          and the engine&apos;s webhooks are exempt from shedding in every mode.
        </p>
      </NoticeBox>
    </div>
  );
}

/**
 * An ISO instant as a `datetime-local` input value, in the VIEWER's zone.
 *
 * The input has no timezone of its own — it is wall-clock text — so a value written into
 * it is interpreted in the browser's zone when it is read back, and these two helpers are
 * the matched pair that makes the round trip lossless. They are the ONLY place in this
 * screen where a browser clock is consulted, and it is for the operator's own typing
 * rather than for any state decision (see the file header).
 */
function toLocalInput(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const offset = at.getTimezoneOffset() * 60_000;
  return new Date(at.getTime() - offset).toISOString().slice(0, 16);
}

/** The inverse: a `datetime-local` value as an ISO instant, or `null` if it is empty. */
function fromLocalInput(value: string): string | null {
  if (value.trim() === "") return null;
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}
