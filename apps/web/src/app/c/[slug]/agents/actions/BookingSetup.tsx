"use client";

/**
 * BOOK APPOINTMENTS — the guided setup, in the shape the founder approved (REDESIGN-2):
 *
 *   Book appointments
 *   Your agent can check your Google Calendar and book callers in.
 *    Calendar   Google · sri@…   Change
 *    Length     1 hour
 *    Hours      9 am – 6 pm
 *                          [ Turn on booking ]
 *
 * Behind the button it creates (or updates) the two calendar tools `jobs.bookingTools`
 * derives, and switches this agent's actions on if they were off — the button's label is
 * the consequence (doctrine §4), so "Turn on booking" has to leave booking on.
 */

import { useCallback, useState } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { Disclosure, FIELD, FIELD_HINT, FIELD_LABEL, PRIMARY_BUTTON, ProblemNotice } from "@/components/ui";
import {
  useCreateAction,
  useSetMasterSwitch,
  useUpdateAction,
  type ActionTool,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { AccountRow } from "./AccountRow";
import {
  BOOKING_DEFAULTS,
  HOUR_CHOICES,
  JOBS,
  LENGTH_CHOICES,
  bookingTools,
  hourLabel,
  lengthLabel,
  readBooking,
  uniqueName,
  type BookingDraft,
} from "./jobs";

const BOOKING = JOBS[0]!;
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
  const [draft, setDraft] = useState<BookingDraft>(() =>
    editing ? readBooking(check, book) : { credentialId: "", ...BOOKING_DEFAULTS },
  );
  const create = useCreateAction(session, agentId);
  const update = useUpdateAction(session, agentId);
  const setMaster = useSetMasterSwitch(session, agentId);
  const [busy, setBusy] = useState(false);
  const failure = create.error ?? update.error ?? setMaster.error;
  const setCredential = useCallback(
    (credentialId: string) => setDraft((d) => ({ ...d, credentialId })),
    [],
  );

  const hoursValid = draft.to > draft.from;
  const blocked = !draft.credentialId
    ? "Connect a Google Calendar first."
    : !hoursValid
      ? "The closing hour has to be after the opening hour."
      : null;

  async function submit() {
    setBusy(true);
    try {
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
      if (!masterOn) await setMaster.mutateAsync(true);
      onDone();
    } catch {
      // The refusal is on the mutation that failed, rendered below.
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (!blocked && !busy) void submit();
      }}
    >
      <Section headingLevel={3} title={BOOKING.title} description={BOOKING.line}>
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
          <SettingRow
            label="Hours"
            hint="India time. Your agent offers and books only inside these hours."
            control={
              <span className="flex items-center gap-2">
                <select
                  aria-label="Bookings from"
                  className={SELECT}
                  value={draft.from}
                  onChange={(e) => setDraft({ ...draft, from: Number(e.target.value) })}
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
                  onChange={(e) => setDraft({ ...draft, to: Number(e.target.value) })}
                >
                  {HOUR_CHOICES.map((h) => (
                    <option key={h} value={h}>
                      {hourLabel(h)}
                    </option>
                  ))}
                </select>
              </span>
            }
          />
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
          <button type="submit" className={PRIMARY_BUTTON} disabled={busy || blocked !== null}>
            {busy ? "Saving…" : editing ? "Save changes" : "Turn on booking"}
          </button>
        </div>
      </Section>
    </form>
  );
}
