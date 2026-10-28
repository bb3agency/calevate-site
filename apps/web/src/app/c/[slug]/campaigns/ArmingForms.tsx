"use client";

import { useState } from "react";
import { CalendarClock, Repeat } from "lucide-react";

import { ActionButton, type ActionFeedback } from "@/components/arc/feedback";
import { FIELD_HINT, FIELD_LABEL, ProblemNotice } from "@/components/ui";
import { recurrenceUntil, type NewRecurrence, type useLaunchCheck } from "@/lib/api/campaigns";

import { RepeatFields, StartAtFields } from "./ScheduleFields";
import { FireTimeRefusal } from "./scheduleCopy";
import { Why } from "@/components/why";
import type { ScheduleFormState } from "./campaignForm";

/** Said under the start date when the chosen moment cannot be armed; `null` when it can. */
export function startProblem(startIso: string | null, startDate: string, now = Date.now()): string | null {
  if (!startDate) return "Choose the day it should start.";
  if (!startIso) return "Choose the time it should start.";
  if (new Date(startIso).getTime() <= now) return "Choose a time that has not passed yet.";
  return null;
}

/**
 * START IT LATER, OR EVERY WEEK — the two arming forms, rendered OUTSIDE the launch
 * verdict on purpose.
 *
 * `POST /schedule` and `POST /recurrence` run no compliance gate (D-79,
 * `campaigns/scheduling.py` decision 3): the gate runs at FIRE time, on every occurrence,
 * through the same `launch_campaign` the Launch button calls. A client waiting on a
 * registration today can therefore arm next Tuesday's start today; hiding these forms
 * behind `ready` would invent a rule the server does not have. What the screen owes them
 * instead is the blocker list above and `FireTimeRefusal`, which says in advance what the
 * fire-time check will do. A form reachable with the blockers HIDDEN would be the
 * dangerous version of this.
 *
 * Guarded on `check.data` having answered, so nothing here states a consequence derived
 * from a verdict we do not have (§52).
 */
export function ArmingForms({
  status,
  check,
  schedule,
  repeat,
  scheduleForm,
  canWrite,
  refusal,
}: {
  status: string | null;
  check: ReturnType<typeof useLaunchCheck>;
  schedule: ActionFeedback<string>;
  repeat: ActionFeedback<NewRecurrence>;
  scheduleForm: ScheduleFormState;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  // Field messages appear once a submit was tried, never while the person is still typing.
  const [triedStart, setTriedStart] = useState(false);
  const [triedRepeat, setTriedRepeat] = useState(false);
  if (!check.data) return null;

  const { startIso, startDate, repeatDays, repeatTime, repeatEnds } = scheduleForm;
  const startError = triedStart ? startProblem(startIso, startDate) : null;
  const daysError = triedRepeat && repeatDays.length === 0 ? "Choose at least one day." : null;

  return (
    <div className="mt-3 space-y-3">
      {/* Keyed on `draft`: a campaign that is already `scheduled` shows its start, and the
          way out of it, in the "Scheduled" card above. */}
      {status === "draft" && (
        <form
          noValidate
          className="space-y-3 border-t border-line pt-3"
          onSubmit={(event) => {
            event.preventDefault();
            setTriedStart(true);
            if (startProblem(startIso, startDate) === null && startIso) schedule.run(startIso);
          }}
        >
          <p className={FIELD_LABEL}>Or start it later</p>
          {!check.data.ready && <FireTimeRefusal kind="start" when="arming" />}
          <StartAtFields
            schedule={scheduleForm}
            dateError={startError && startDate ? null : startError}
            timeError={startError && startDate ? startError : null}
          />
          {schedule.error != null && <ProblemNotice error={schedule.error} />}
          <ActionButton
            type="submit"
            variant="secondary"
            title={refusal}
            disabled={!canWrite}
            status={schedule.status}
            pendingLabel="Scheduling"
            successLabel="Scheduled"
          >
            <CalendarClock aria-hidden className="h-3.5 w-3.5" />
            Schedule start
          </ActionButton>
          <p className={FIELD_HINT}>We check everything again when it starts.</p>
        </form>
      )}

      {/* Both `draft` and `scheduled` can set a repeat: a client who picked Monday and then
          decided they want it weekly should not have to cancel first. */}
      <form
        noValidate
        className="space-y-3 border-t border-line pt-3"
        onSubmit={(event) => {
          event.preventDefault();
          setTriedRepeat(true);
          if (repeatDays.length === 0) return;
          repeat.run({ days: repeatDays, at: repeatTime, until: recurrenceUntil(repeatEnds) });
        }}
      >
        <p className={FIELD_LABEL}>Or repeat it every week</p>
        {!check.data.ready && <FireTimeRefusal kind="repeat" when="arming" />}
        <RepeatFields schedule={scheduleForm} daysError={daysError} />
        {repeat.error != null && <ProblemNotice error={repeat.error} />}
        <ActionButton
          type="submit"
          variant="secondary"
          title={refusal}
          disabled={!canWrite}
          status={repeat.status}
          pendingLabel="Setting"
          successLabel="Set"
        >
          <Repeat aria-hidden className="h-3.5 w-3.5" />
          Set repeat
        </ActionButton>
        <p className={FIELD_HINT}>
          A missed run is skipped, never called late.{" "}
          <Why inline>
            A run can be missed by a fault on our side, or because the last run is still going.
            We wait for the next one rather than call people at a different time of day.
          </Why>
        </p>
      </form>
    </div>
  );
}
