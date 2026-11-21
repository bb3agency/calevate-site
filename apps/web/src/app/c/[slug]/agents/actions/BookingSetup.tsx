"use client";

/**
 * BOOK APPOINTMENTS — the guided setup, in the shape the founder approved (REDESIGN-2):
 *
 *   Take bookings          (a clinic reads "Book appointments", verticalExamples)
 *   Your agent can check your Google Calendar and book callers in.
 *    Calendar   Google · sri@…   Change
 *    Length     1 hour
 *    Hours      9 am – 6 pm
 *                          [ Turn on booking ]
 *
 * A new job starts from the business profile's opening hours when it has them
 * (`jobs.bookingDefaults`); days with different hours are kept exactly until the owner sets
 * one time for every day. A closing hour at or before the opening one runs past midnight.
 *
 * Behind the button it creates (or updates) the two calendar tools `jobs.bookingTools`
 * derives, and switches this agent's actions on if they were off — the button's label is
 * the consequence (doctrine §4), so "Turn on booking" has to leave booking on.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ActionButton, useActionFeedback, useAsyncAction } from "@/components/arc/feedback";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { Disclosure, FIELD, FIELD_HINT, FIELD_LABEL, FilterChip, ProblemNotice } from "@/components/ui";
import {
  useCreateAction,
  useSetMasterSwitch,
  useUpdateAction,
  type ActionTool,
} from "@/lib/api/actions";
import { useBusinessProfile } from "@/lib/api/businessProfile";
import type { Session } from "@/lib/api/client";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { AccountRow } from "./AccountRow";
import { useSwitchOnWithheld } from "./viewAsWithheld";
import {
  CLOSE_HOUR_CHOICES,
  HOUR_CHOICES,
  LENGTH_CHOICES,
  WEEKDAYS,
  bookingDefaults,
  bookingTools,
  hourLabel,
  hoursLabel,
  lengthLabel,
  readBooking,
  uniqueName,
  type BookingDraft,
} from "./jobs";

const SELECT = `${FIELD} mt-0 w-auto`;

export function BookingSetup({
  agentId,
  session,
  tools,
  masterOn,
  check,
  book,
  onDone,
}: {
  agentId: string;
  session: Session;
  /** Every action on this agent, so derived names never collide. */
  tools: readonly ActionTool[];
  masterOn: boolean;
  /** The job's existing halves when changing it; absent when setting it up. */
  check?: ActionTool;
  book?: ActionTool;
  onDone: () => void;
}) {
  const editing = check !== undefined || book !== undefined;
  // Only a new job starts from the profile; a saved one keeps its own hours.
  const profileHours = useBusinessProfile(session, { enabled: !editing }).data?.hours;
  const [draft, setDraftState] = useState<BookingDraft>(() =>
    editing ? readBooking(check, book) : { credentialId: "", ...bookingDefaults(profileHours) },
  );
  // A new job follows the profile's hours until the owner changes a setting; the profile can
  // arrive after the form opens.
  const touched = useRef(editing);
  const setDraft: typeof setDraftState = useCallback((next) => {
    touched.current = true;
    setDraftState(next);
  }, []);
  useEffect(() => {
    if (!touched.current && profileHours) {
      setDraftState((d) => ({ ...d, ...bookingDefaults(profileHours) }));
    }
  }, [profileHours]);
  const create = useCreateAction(session, agentId);
  const update = useUpdateAction(session, agentId);
  const setMaster = useSetMasterSwitch(session, agentId);
  // Under view-as the two halves are created off (`agent_tools.add_action`) and switching
  // actions on is the owner's, so the operator sets booking up and leaves it off.
  const onWithheld = useSwitchOnWithheld(session);
  // The three writes run as one action (below), which owns the button's state; each
  // refusal is the ProblemNotice under the form, so none of them toasts.
  useActionFeedback(create, { errorDisplay: "inline" });
  useActionFeedback(update, { errorDisplay: "inline" });
  useActionFeedback(setMaster, { errorDisplay: "inline" });
  const failure = create.error ?? update.error ?? setMaster.error;
  const setCredential = useCallback(
    (credentialId: string) => setDraftState((d) => ({ ...d, credentialId })),
    [],
  );

  // The form, declared so the assistant can read and fill it ("make bookings 30 minutes,
  // 10 to 5"). Nothing is saved until the owner presses the button.
  const hourOptions = HOUR_CHOICES.map((h) => ({ value: String(h), label: hourLabel(h) }));
  const closeOptions = CLOSE_HOUR_CHOICES.map((h) => ({ value: String(h), label: hourLabel(h) }));
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: editing ? "Change booking" : "Set up booking",
    realm: "client",
    fields: [
      {
        id: "booking-length",
        label: "Length of each booking",
        type: "select",
        value: String(draft.durationMin),
        options: LENGTH_CHOICES.map((m) => ({ value: String(m), label: lengthLabel(m) })),
      },
      { id: "booking-from", label: "Bookings from (India time)", type: "select", value: String(draft.from), options: hourOptions },
      { id: "booking-to", label: "Bookings until (India time)", type: "select", value: String(draft.to), options: closeOptions },
      { id: "booking-calendar-id", label: "Which calendar", type: "text", value: draft.calendarId },
    ],
    facts: [
      { key: "calendar_connected", label: "A Google Calendar is chosen", value: draft.credentialId ? "yes" : "no" },
      { key: "booking_days", label: "Days it takes bookings", value: WEEKDAYS.filter((w) => draft.days.includes(w.day)).map((w) => w.long).join(", ") || "none" },
      { key: "booking_hours", label: "Booking hours", value: hoursLabel(draft) },
    ],
    apply: (items) => {
      for (const item of items) {
        const raw = asText(item.value);
        const n = Number(raw);
        if (item.field_id === "booking-length" && LENGTH_CHOICES.includes(n)) setDraft((d) => ({ ...d, durationMin: n }));
        if (item.field_id === "booking-from" && HOUR_CHOICES.includes(n)) setDraft((d) => ({ ...d, from: n, perDay: null }));
        if (item.field_id === "booking-to" && CLOSE_HOUR_CHOICES.includes(n)) setDraft((d) => ({ ...d, to: n, perDay: null }));
        if (item.field_id === "booking-calendar-id" && raw.trim()) setDraft((d) => ({ ...d, calendarId: raw.trim() }));
      }
    },
  });

  const blocked = !draft.credentialId
    ? "Connect a Google Calendar first."
    : draft.days.length === 0
      ? "Pick at least one day."
      : null;
  const hoursHint =
    draft.to % 24 === draft.from
      ? "India time. Any time of the day."
      : draft.to < draft.from
        ? "India time. Runs past midnight into the next day."
        : "India time. Times outside these are never offered or booked.";
  const toggleDay = (day: number) =>
    setDraft((d) => ({
      ...d,
      perDay: null,
      days: d.days.includes(day) ? d.days.filter((x) => x !== day) : [...d.days, day].sort((a, b) => a - b),
    }));

  const submit = useAsyncAction(
    async () => {
      const taken = tools.map((t) => t.name);
      const names = {
        check: check?.name ?? uniqueName("find_free_times", taken),
        book: book?.name ?? uniqueName("book_the_time", taken),
      };
      const bodies = bookingTools(draft, names);
      if (check) await update.mutateAsync({ toolId: check.id, body: bodies.check });
      else await create.mutateAsync(bodies.check);
      if (book) await update.mutateAsync({ toolId: book.id, body: bodies.book });
      else await create.mutateAsync(bodies.book);
      if (!masterOn && onWithheld === null) await setMaster.mutateAsync(true);
      onDone();
    },
    { errorDisplay: "inline" },
  );
  const busy = submit.status === "pending";

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (!blocked && !busy) submit.run();
      }}
    >
      <Section headingLevel={3} title={editing ? "Change the settings" : "Set it up"}>
        <SettingRows className="border-y border-line">
          <AccountRow
            label="Calendar"
            kind="google_calendar"
            value={draft.credentialId}
            onChange={setCredential}
            session={session}
          />
          <SettingRow
            label="Length"
            control={
              <select
                aria-label="Length of each booking"
                className={SELECT}
                value={draft.durationMin}
                onChange={(e) => setDraft({ ...draft, durationMin: Number(e.target.value) })}
              >
                {LENGTH_CHOICES.map((m) => (
                  <option key={m} value={m}>
                    {lengthLabel(m)}
                  </option>
                ))}
              </select>
            }
          />
          {draft.perDay ? (
            <SettingRow
              label="Hours"
              hint="Your business hours, India time. Each day keeps its own."
              value={hoursLabel(draft)}
              action={
                <button type="button" className={TEXT_ACTION} onClick={() => setDraft({ ...draft, perDay: null })}>
                  Use one time every day
                </button>
              }
            />
          ) : (
            <>
              <SettingRow
                label="Hours"
                hint={hoursHint}
                control={
                  <span className="flex items-center gap-2">
                    <select
                      aria-label="Bookings from"
                      className={SELECT}
                      value={draft.from}
                      onChange={(e) => setDraft({ ...draft, from: Number(e.target.value), perDay: null })}
                    >
                      {HOUR_CHOICES.map((h) => (
                        <option key={h} value={h}>
                          {hourLabel(h)}
                        </option>
                      ))}
                    </select>
                    <span aria-hidden className="text-ink-muted">
                      –
                    </span>
                    <select
                      aria-label="Bookings until"
                      className={SELECT}
                      value={draft.to}
                      onChange={(e) => setDraft({ ...draft, to: Number(e.target.value), perDay: null })}
                    >
                      {CLOSE_HOUR_CHOICES.map((h) => (
                        <option key={h} value={h}>
                          {hourLabel(h)}
                        </option>
                      ))}
                    </select>
                  </span>
                }
              />
              <SettingRow
                label="Days"
                control={
                  <span role="group" aria-label="Days it takes bookings" className="flex flex-wrap gap-1.5">
                    {WEEKDAYS.map((w) => (
                      <FilterChip
                        key={w.day}
                        label={w.short}
                        active={draft.days.includes(w.day)}
                        onClick={() => toggleDay(w.day)}
                      />
                    ))}
                  </span>
                }
              />
            </>
          )}
        </SettingRows>

        <Disclosure variant="inline" headingLevel={4} title="Advanced" className="mt-2">
          <label className="block max-w-sm">
            <span className={FIELD_LABEL}>Which calendar</span>
            <input
              className={FIELD}
              value={draft.calendarId}
              onChange={(e) => setDraft({ ...draft, calendarId: e.target.value })}
            />
          </label>
          <span className={FIELD_HINT}>
            &ldquo;primary&rdquo; is the main calendar of the account above.
          </span>
        </Disclosure>

        {failure ? (
          <div className="mt-4">
            <ProblemNotice error={failure} />
          </div>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center justify-end gap-x-5 gap-y-3">
          {blocked ? <p className="mr-auto text-meta text-ink-muted">{blocked}</p> : null}
          <button type="button" className={TEXT_ACTION} onClick={onDone}>
            Cancel
          </button>
          <ActionButton
            type="submit"
            status={submit.status}
            disabled={blocked !== null}
            successLabel={editing ? "Saved" : onWithheld ? "Set up" : "Turned on"}
          >
            {editing ? "Save changes" : onWithheld ? "Set up booking" : "Turn on booking"}
          </ActionButton>
        </div>
      </Section>
    </form>
  );
}
