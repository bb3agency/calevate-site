"use client";

import { useEffect, useState } from "react";

import { IstDateTimeField } from "@/components/admin/istDateTimeField";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NumberField } from "@/components/arc/number-field";
import { todayIST } from "@/components/arc/ist-dates";
import { Drawer } from "@/components/console/drawer";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
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

/** The drain bound the API accepts, in minutes. */
const DRAIN_MIN = 1;
const DRAIN_MAX = 240;

/** The draft keeps the drain as text (what `windowDraft` compares); the field works in numbers. */
function DrainField({ value, onChange, hint }: { value: string; onChange: (next: string) => void; hint: string }) {
  return (
    <NumberField
      label="Drain bound"
      unit="minutes"
      min={DRAIN_MIN}
      max={DRAIN_MAX}
      step={1}
      largeStep={15}
      value={value === "" ? null : Number(value)}
      onChange={(next) => onChange(next === null ? "" : String(next))}
      hint={hint}
      className="max-w-xs"
    />
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
  const amendFeedback = useActionFeedback(amend, {
    errorDisplay: "inline",
    successToast: "Window changed",
  });
  const [draft, setDraft] = useState<WindowDraft>(() => draftOf(current));
  const set = (patch: Partial<WindowDraft>) => setDraft((held) => ({ ...held, ...patch }));
  const amendment = amendmentOf(current, draft);
  const dirty = hasChanges(amendment);
  const movable = current.state === "scheduled";
  useUnsavedGuard(dirty);
  // Closed from an effect, after the feedback hook has raised its toast, rather than from
  // `onSuccess`, which would unmount the drawer before the hook saw the success.
  useEffect(() => {
    if (amendFeedback.status === "success") onClose();
  }, [amendFeedback.status, onClose]);

  return (
    <Drawer
      open
      dirty={dirty}
      onClose={onClose}
      title="Change window"
      description="Only the fields you change are sent."
      footer={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={amend.isPending}>
            Cancel
          </button>
          <ActionButton
            status={amendFeedback.status}
            disabled={!dirty}
            pendingLabel="Saving…"
            onClick={() => amendFeedback.run({ windowId: current.id, ...amendment })}
          >
            Save changes
          </ActionButton>
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
          <IstDateTimeField
            label="Opens at"
            value={draft.startsAt}
            onChange={(startsAt) => set({ startsAt })}
            hint="Movable until the window opens. After that it is history — end it instead."
          />
        )}
        <IstDateTimeField
          label="Ends at"
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
            title="Clients have already been told about this window"
          >
            <p className="mt-1">
              Changing the time or the wording emails every client again with the window as it
              now is. That is the point. A client holding an old time is worse than a second
              email, but it is not a silent edit.
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
  const scheduleFeedback = useActionFeedback(schedule, {
    errorDisplay: "inline",
    successToast: "Window scheduled",
  });
  useEffect(() => {
    if (scheduleFeedback.status === "success") onClose();
  }, [scheduleFeedback.status, onClose]);
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [reason, setReason] = useState("");
  const [drain, setDrain] = useState(DEFAULT_DRAIN);
  const start = istInputToInstant(startsAt);
  const finish = istInputToInstant(endsAt);
  const ready = start !== null && finish !== null && reason.trim().length >= 10;
  const dirty = startsAt !== "" || endsAt !== "" || reason !== "" || drain !== DEFAULT_DRAIN;
  useUnsavedGuard(dirty);

  return (
    <Drawer
      open
      dirty={dirty}
      onClose={onClose}
      title="Schedule a window"
      description="It drains first, then closes the client portals until it ends."
      footer={
        <>
          <button type="button" className={SECONDARY_BUTTON} onClick={onClose} disabled={schedule.isPending}>
            Cancel
          </button>
          <ActionButton
            status={scheduleFeedback.status}
            disabled={!ready}
            pendingLabel="Scheduling…"
            successLabel="Scheduled"
            onClick={() => {
              if (start === null || finish === null) return;
              scheduleFeedback.run({
                startsAt: start,
                endsAt: finish,
                reason: reason.trim(),
                maxDrainMinutes: Number(drain),
              });
            }}
          >
            Schedule it
          </ActionButton>
        </>
      }
    >
      <div className="space-y-4">
        {/* The lead comes from the server: it is a dial an operator sets, not a constant. */}
        <IstDateTimeField
          label="Opens at"
          min={todayIST()}
          value={startsAt}
          onChange={setStartsAt}
          hint={
            `Clients are emailed ${leadHours} ${leadHours === 1 ? "hour" : "hours"} ahead ` +
            "(set in Platform configuration). Scheduling closer than that is allowed — they " +
            "simply get less notice."
          }
        />
        <IstDateTimeField
          label="Ends at"
          min={startsAt.split("T")[0] || todayIST()}
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
            Written for a business owner, not an engineer. It is the email and the lockout page.
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
