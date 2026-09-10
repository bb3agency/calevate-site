"use client";

import { CalendarClock, Repeat } from "lucide-react";

import { FIELD, FIELD_HINT, FIELD_LABEL, SECONDARY_BUTTON } from "@/components/ui";
import {
  recurrenceUntil,
  type useLaunchCheck,
  type useScheduleCampaign,
  type useSetRecurrence,
} from "@/lib/api/campaigns";

import { WEEKDAYS } from "./choices";
import { FireTimeRefusal } from "./scheduleCopy";
import type { ScheduleFormState } from "./campaignForm";

/**
 * START IT LATER, OR EVERY WEEK — the two arming forms, and why they sit OUTSIDE the
 * verdict.
 *
 * Extracted from `LaunchGate.tsx` (UX-DOCTRINE §6), which still renders them inside the
 * same card and still renders the blocker list above them. That placement is the fix, not
 * a layout preference, and the full argument travels with the markup below.
 *
 * Guarded by the caller on `check.data` having ANSWERED: nothing here ever states a
 * consequence derived from a verdict we do not have (§52).
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
  schedule: ReturnType<typeof useScheduleCampaign>;
  repeat: ReturnType<typeof useSetRecurrence>;
  scheduleForm: ScheduleFormState;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const {
    startDate, setStartDate,
    startTime, setStartTime,
    startIso,
    repeatDays, toggleRepeatDay,
    repeatTime, setRepeatTime,
    repeatEnds, setRepeatEnds,
  } = scheduleForm;
  if (!check.data) return null;
  return (
    <>
              {/* THE ARMING CONTROLS, OUTSIDE THE VERDICT — and that placement is the
                  fix, not a layout preference.

                  Both forms used to render only inside the `ready` branch, so a campaign
                  with an outstanding blocker could not arm a start or a repeat at all. That
                  was the SCREEN inventing a rule the server does not have: `POST /schedule`
                  and `POST /recurrence` run no compliance gate (campaigns/routes.py says so
                  in both docstrings, `campaigns/scheduling.py` decision 3 says why, D-79
                  records it). The gate runs at FIRE time, on every occurrence, through the
                  same `launch_campaign` the Launch button calls — which is exactly what
                  makes a DLT registration that lapses in week three refuse week three. A
                  client waiting on the registrar today can therefore set next Tuesday's
                  start today, and refusing them was refusing today for a condition Tuesday
                  will have fixed.

                  What the screen owes them instead of a hidden form is the other half of
                  that truth, and it is directly above and beside these controls: the
                  blocker list is still rendered in full by the branch above, and
                  `FireTimeRefusal` says in advance what the fire-time check will do. A
                  form reachable with the blockers HIDDEN would be the dangerous version of
                  this fix rather than the fix.

                  Guarded on `check.data` rather than rendered unconditionally: a loading or
                  failed launch check reaches the skeleton or the refusal above and never
                  gets here, so nothing below ever states a consequence derived from a
                  verdict we do not have (§52). */}
                <div className="mt-3 space-y-3">
                  {/* Schedule, in the SAME card as Launch, because it is the same
                      action with a delay on it — and the gate that guards Launch runs
                      again when this fires. The green tick above is about right now;
                      the hint below says plainly that it is not a promise about the
                      start, and `FireTimeRefusal` says what happens when it is not
                      even true about right now.

                      Still keyed on `draft`: a campaign that is already `scheduled`
                      shows its start (and the way out of it) in the "Scheduled" card
                      above, which is where changing one's mind about a date belongs. */}
                  {status === "draft" && (
                    <div className="space-y-2 border-t border-line pt-3">
                      <p className={FIELD_LABEL}>Or start it later</p>
                      {!check.data.ready && (
                        <FireTimeRefusal kind="start" when="arming" />
                      )}
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          type="date"
                          aria-label="Start date"
                          value={startDate}
                          onChange={(e) => setStartDate(e.target.value)}
                          className={FIELD}
                        />
                        <input
                          type="time"
                          aria-label="Start time (IST)"
                          value={startTime}
                          onChange={(e) => setStartTime(e.target.value)}
                          className={FIELD}
                        />
                        <button
                          type="button"
                          title={refusal}
                          disabled={
                            !canWrite || !startIso || schedule.isPending
                          }
                          onClick={() => startIso && schedule.mutate(startIso)}
                          className={SECONDARY_BUTTON}
                        >
                          <CalendarClock aria-hidden className="h-3.5 w-3.5" />
                          {schedule.isPending
                            ? "Scheduling…"
                            : "Schedule start"}
                        </button>
                      </div>
                      <p className={FIELD_HINT}>
                        Times are IST. We check every one of these requirements
                        again at the moment it starts — a campaign that stops
                        being allowed to dial between now and then will not
                        start.
                      </p>
                    </div>
                  )}

                  {/* REPEAT, in the same card and for the same reason as the schedule
                      form above: it is the Launch button with a calendar on it, and the
                      gate that guards Launch runs again on every single occurrence. Both
                      `draft` and `scheduled` can set one — a client who picked Monday and
                      then decided they want it weekly should not have to cancel first —
                      which is the whole of the card's own guard, so it carries no second
                      copy of it here. */}
                  <div className="space-y-2 border-t border-line pt-3">
                    <p className={FIELD_LABEL}>Or repeat it every week</p>
                    {!check.data.ready && (
                      <FireTimeRefusal kind="repeat" when="arming" />
                    )}
                    <fieldset>
                      <legend className={FIELD_HINT}>Which days</legend>
                      <div className="mt-1 flex flex-wrap gap-3">
                        {WEEKDAYS.map((day) => (
                          <label
                            key={day.value}
                            className="flex items-center gap-1.5 text-sm text-ink"
                          >
                            <input
                              type="checkbox"
                              checked={repeatDays.includes(day.value)}
                              onChange={() => toggleRepeatDay(day.value)}
                              className="h-4 w-4 rounded border-line accent-brand"
                            />
                            {/* The full day name for a screen reader, the short one on
                                screen: seven visible "Wednesday"s wrap onto three lines
                                on a phone, and an icon-only toggle would be a control
                                with no label at all. */}
                            <span aria-hidden>{day.short}</span>
                            <span className="sr-only">{day.label}</span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    <div className="flex flex-wrap items-end gap-2">
                      <label className="block">
                        <span className={FIELD_LABEL}>Time (IST)</span>
                        <input
                          type="time"
                          value={repeatTime}
                          onChange={(e) => setRepeatTime(e.target.value)}
                          className={FIELD}
                        />
                      </label>
                      <label className="block">
                        <span className={FIELD_LABEL}>
                          Stop repeating after (optional)
                        </span>
                        <input
                          type="date"
                          value={repeatEnds}
                          onChange={(e) => setRepeatEnds(e.target.value)}
                          className={FIELD}
                        />
                      </label>
                      <button
                        type="button"
                        title={refusal}
                        disabled={
                          !canWrite ||
                          repeatDays.length === 0 ||
                          repeat.isPending
                        }
                        onClick={() =>
                          repeat.mutate({
                            days: repeatDays,
                            at: repeatTime,
                            until: recurrenceUntil(repeatEnds),
                          })
                        }
                        className={SECONDARY_BUTTON}
                      >
                        <Repeat aria-hidden className="h-3.5 w-3.5" />
                        {repeat.isPending ? "Setting…" : "Set repeat"}
                      </button>
                    </div>
                    {/* A dead button needs its reason beside it, like the create
                        form's provenance note — and this one is dead by default,
                        because no day is pre-ticked. */}
                    {repeatDays.length === 0 && (
                      <p className="text-xs text-ink-faint">
                        Choose at least one day for this campaign to repeat on.
                      </p>
                    )}
                    <p className={FIELD_HINT}>
                      Calls go out between 9am and 9pm, so a repeat has to sit
                      inside those hours. If a run is missed — a fault our side,
                      or a previous run still going — we skip it and wait for
                      the next one rather than calling people at a different
                      time of day.
                    </p>
                  </div>
                </div>
    </>
  );
}
