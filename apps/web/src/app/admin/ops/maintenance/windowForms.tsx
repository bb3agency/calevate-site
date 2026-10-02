"use client";

import { useState } from "react";
import { CalendarClock } from "lucide-react";

import { Drawer } from "@/components/console/drawer";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  istInputToInstant,
} from "@/components/ui";
import {
  useAmendMaintenance,
  useScheduleMaintenance,
  type MaintenanceWindow,
} from "@/lib/api/maintenance";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { amendmentOf, draftOf, hasChanges, type WindowDraft } from "./windowDraft";

function TimeField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  hint: string;
}) {
  return (
    <label className="block">
      <span className={FIELD_LABEL}>{label}</span>
      <input
        type="datetime-local"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={FIELD}
      />
      <span className={FIELD_HINT}>{hint}</span>
    </label>
  );
}

function DrainField({ value, onChange, hint }: { value: string; onChange: (next: string) => void; hint: string }) {
  return (
    <label className="block max-w-xs">
      <span className={FIELD_LABEL}>Drain bound (minutes)</span>
      <input
        type="number"
        min={1}
        max={240}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={FIELD}
      />
      <span className={FIELD_HINT}>{hint}</span>
    </label>
  );
}

/**
 * Amend the open window. The start is absent once the window has begun (it is history
 * and the API refuses it by name); a `scheduled` window moves freely, announced or not,
 * because the commitment is kept by re-announcing rather than by freezing.
 */
export function AmendWindowDrawer({
  window: current,
  onClose,
}: {
  window: MaintenanceWindow;
  onClose: () => void;
}) {
  const amend = useAmendMaintenance();
  const [draft, setDraft] = useState<WindowDraft>(() => draftOf(current));
  const set = (patch: Partial<WindowDraft>) => setDraft((held) => ({ ...held, ...patch }));
  const amendment = amendmentOf(current, draft);
  const dirty = hasChanges(amendment);
  const movable = current.state === "scheduled";
  useUnsavedGuard(dirty);

  return (
    <Drawer
      open
      onClose={onClose}
      title="Change window"
      description="Only the fields you change are sent."
      footer={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={amend.isPending}>
            Cancel
          </button>
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={!dirty || amend.isPending}
            onClick={() =>
              amend.mutate({ windowId: current.id, ...amendment }, { onSuccess: onClose })
            }
          >
            {amend.isPending ? "Saving…" : "Save changes"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <label className="block">
          <span className={FIELD_LABEL}>What clients are told</span>
          <textarea
            value={draft.reason}
            rows={3}
            onChange={(event) => set({ reason: event.target.value })}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            Shown verbatim in the email and on the page a locked-out client sees. Changing it
            re-notifies every client.
          </span>
        </label>
        {movable && (
          <TimeField
            label="Opens at (IST)"
            value={draft.startsAt}
            onChange={(startsAt) => set({ startsAt })}
            hint="Movable until the window opens. After that it is history — end it instead."
          />
        )}
        <TimeField
          label="Ends at (IST)"
          value={draft.endsAt}
          onChange={(endsAt) => set({ endsAt })}
          hint="Every refused client request is told to come back at this time."
        />
        <DrainField
          value={draft.drain}
          onChange={(drain) => set({ drain })}
          hint="How long to wait for in-flight work before activating anyway. Editable while it drains."
        />
        {current.announced && (
          <NoticeBox
            tone="neutral"
            icon={<CalendarClock aria-hidden className="h-5 w-5" />}
            title="Clients have already been told about this window"
          >
            <p className="mt-1">
              Changing the time or the wording emails every client again with the window as it
              now is. That is the point — a client holding an old time is worse than a second
              email — but it is not a silent edit.
            </p>
          </NoticeBox>
        )}
        {amend.error !== null && <ProblemNotice error={amend.error} />}
      </div>
    </Drawer>
  );
}

const DEFAULT_DRAIN = "15";

export function ScheduleWindowDrawer({
  leadHours,
  onClose,
}: {
  leadHours: number;
  onClose: () => void;
}) {
  const schedule = useScheduleMaintenance();
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [reason, setReason] = useState("");
  const [drain, setDrain] = useState(DEFAULT_DRAIN);
  const start = istInputToInstant(startsAt);
  const finish = istInputToInstant(endsAt);
  const ready = start !== null && finish !== null && reason.trim().length >= 10;
  useUnsavedGuard(startsAt !== "" || endsAt !== "" || reason !== "" || drain !== DEFAULT_DRAIN);

  return (
    <Drawer
      open
      onClose={onClose}
      title="Schedule a window"
      description="It drains first, then closes the client portals until it ends."
      footer={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={schedule.isPending}>
            Cancel
          </button>
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={!ready || schedule.isPending}
            onClick={() => {
              if (start === null || finish === null) return;
              schedule.mutate(
                { startsAt: start, endsAt: finish, reason: reason.trim(), maxDrainMinutes: Number(drain) },
                { onSuccess: onClose },
              );
            }}
          >
            {schedule.isPending ? "Scheduling…" : "Schedule it"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {/* The lead comes from the server: it is a dial an operator sets, not a constant. */}
        <TimeField
          label="Opens at (IST)"
          value={startsAt}
          onChange={setStartsAt}
          hint={
            `Clients are emailed ${leadHours} ${leadHours === 1 ? "hour" : "hours"} ahead ` +
            "(set in Platform configuration). Scheduling closer than that is allowed — they " +
            "simply get less notice, and it is recorded."
          }
        />
        <TimeField
          label="Ends at (IST)"
          value={endsAt}
          onChange={setEndsAt}
          hint="Over-run it and clients retry into a closed door."
        />
        <label className="block">
          <span className={FIELD_LABEL}>What clients are told</span>
          <textarea
            value={reason}
            rows={3}
            placeholder="We are upgrading the telephony stack. Nothing is deleted."
            onChange={(event) => setReason(event.target.value)}
            className={FIELD}
          />
          <span className={FIELD_HINT}>
            Written for a clinic owner, not an engineer. It is the email and the lockout page.
          </span>
        </label>
        <DrainField
          value={drain}
          onChange={setDrain}
          hint="How long to wait for live calls and queued work before activating anyway."
        />
        {schedule.error !== null && <ProblemNotice error={schedule.error} />}
      </div>
    </Drawer>
  );
}
