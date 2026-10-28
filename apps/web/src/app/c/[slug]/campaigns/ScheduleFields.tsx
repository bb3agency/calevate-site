"use client";

import { useId } from "react";

import { DatePicker } from "@/components/arc/calendar";
import { Field } from "@/components/arc/field";
import { todayIST } from "@/components/arc/ist-dates";
import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { FieldMessage } from "@/components/formValidation";
import { FIELD, FIELD_HINT, FIELD_LABEL } from "@/components/ui";

import { WEEKDAYS } from "./choices";
import type { ScheduleFormState } from "./campaignForm";

/**
 * The two schedule forms' fields, shared by the create flow (`StartChoice`) and an existing
 * draft's "Start later or repeat" card (`ArmingForms`), so a start or a repeat is asked
 * the same way wherever it is set.
 *
 * Dates are IST days from the kit `DatePicker` (no past days offered); times stay native
 * `type="time"` boxes, which a phone renders as its own wheel. Both are kept as the strings
 * `scheduleStartAt` / `recurrenceUntil` turn into instants with the +05:30 written in.
 */
export function StartAtFields({
  schedule,
  dateError,
  timeError,
}: {
  schedule: Pick<ScheduleFormState, "startDate" | "setStartDate" | "startTime" | "setStartTime">;
  dateError?: string | null;
  timeError?: string | null;
}) {
  return (
    <div className="grid max-w-md grid-cols-1 gap-3 sm:grid-cols-2">
      <DatePicker
        label="Start date"
        value={schedule.startDate || null}
        onChange={(day) => schedule.setStartDate(day ?? "")}
        min={todayIST()}
        error={dateError}
      />
      <Field label="Start time (IST)" error={timeError}>
        {(control) => (
          <input
            {...control}
            type="time"
            value={schedule.startTime}
            onChange={(e) => schedule.setStartTime(e.target.value)}
            className={`${FIELD} max-w-40`}
          />
        )}
      </Field>
    </div>
  );
}

export function RepeatFields({
  schedule,
  daysError,
}: {
  schedule: Pick<
    ScheduleFormState,
    "repeatDays" | "toggleRepeatDay" | "repeatTime" | "setRepeatTime" | "repeatEnds" | "setRepeatEnds"
  >;
  daysError?: string | null;
}) {
  const errorId = `${useId()}-days-error`;
  return (
    <div className="space-y-3">
      <fieldset aria-describedby={daysError ? errorId : undefined}>
        <legend className={FIELD_LABEL}>Which days</legend>
        <div className="mt-1 flex flex-wrap gap-2">
          {WEEKDAYS.map((day) => {
            const on = schedule.repeatDays.includes(day.value);
            return (
              <label
                key={day.value}
                className={`${CHOICE_CARD} px-3 py-1.5 touch:min-h-11 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand ${on ? CHOICE_ON : CHOICE_OFF}`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={on}
                  onChange={() => schedule.toggleRepeatDay(day.value)}
                />
                {/* The short name on screen, the full one spoken: seven "Wednesday"s wrap
                    onto three lines on a phone. */}
                <span aria-hidden className="text-body text-ink">
                  {day.short}
                </span>
                <span className="sr-only">{day.label}</span>
              </label>
            );
          })}
        </div>
        {daysError ? <FieldMessage id={errorId}>{daysError}</FieldMessage> : null}
      </fieldset>
      <div className="grid max-w-md grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Time (IST)">
          {(control) => (
            <input
              {...control}
              type="time"
              value={schedule.repeatTime}
              onChange={(e) => schedule.setRepeatTime(e.target.value)}
              className={`${FIELD} max-w-40`}
            />
          )}
        </Field>
        <DatePicker
          label="Stop repeating after"
          hint="Optional"
          value={schedule.repeatEnds || null}
          onChange={(day) => schedule.setRepeatEnds(day ?? "")}
          min={todayIST()}
          clearable
          placeholder="Keeps repeating"
        />
      </div>
      <p className={FIELD_HINT}>Pick a time between 9am and 9pm.</p>
    </div>
  );
}
