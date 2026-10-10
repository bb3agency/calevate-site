"use client";

import { FIELD } from "@/components/ui";
import {
  DAY_LABELS,
  profileFieldId,
  type DayDraft,
  type ProfileDraft,
  type Weekday,
} from "@/lib/api/businessProfile";

import { Field } from "./fields";

/**
 * The week as a fixed grid. A day left blank is NOT ANSWERED; ticking Closed is an answer.
 * The agent says "we are closed on Sunday" for the second and nothing for the first.
 */
export function HoursEditor({
  draft,
  onChange,
  disabled,
  errorAt,
}: {
  draft: ProfileDraft;
  onChange: (next: ProfileDraft) => void;
  disabled: boolean;
  errorAt: (path: string) => string | undefined;
}) {
  const setDay = (day: Weekday, change: Partial<DayDraft>) =>
    onChange({
      ...draft,
      business_hours: draft.business_hours.map((row) => (row.day === day ? { ...row, ...change } : row)),
    });

  const copyMonday = () => {
    const monday = draft.business_hours.find((row) => row.day === "mon");
    if (!monday) return;
    onChange({
      ...draft,
      business_hours: draft.business_hours.map((row) =>
        row.day === "sat" || row.day === "sun" || row.day === "mon"
          ? row
          : { ...row, opens: monday.opens, closes: monday.closes, closed: monday.closed },
      ),
    });
  };

  return (
    <div className="space-y-2">
      <ul className="divide-y divide-line">
        {draft.business_hours.map((row) => {
          const answered = row.closed || (row.opens !== "" && row.closes !== "");
          return (
            <li key={row.day} className="grid grid-cols-2 items-end gap-2 py-2.5 sm:grid-cols-[8rem_1fr_1fr_auto]">
              <p className="col-span-2 flex items-center gap-2 text-body font-medium text-ink sm:col-span-1 sm:pb-2">
                {DAY_LABELS[row.day]}
                {!answered && <span className="text-meta font-normal text-ink-faint">Not set</span>}
              </p>
              <Field id={profileFieldId(`business_hours.${row.day}.opens`)} label="Opens" error={errorAt(row.day)}>
                {(props) => (
                  <input
                    {...props}
                    type="time"
                    value={row.opens}
                    disabled={row.closed || disabled}
                    onChange={(e) => setDay(row.day, { opens: e.target.value })}
                    className={FIELD}
                  />
                )}
              </Field>
              <Field id={profileFieldId(`business_hours.${row.day}.closes`)} label="Closes">
                {(props) => (
                  <input
                    {...props}
                    type="time"
                    value={row.closes}
                    disabled={row.closed || disabled}
                    onChange={(e) => setDay(row.day, { closes: e.target.value })}
                    className={FIELD}
                  />
                )}
              </Field>
              <label className="col-span-2 flex items-center gap-2 text-body text-ink-muted sm:col-span-1 sm:pb-2 touch:min-h-11">
                <input
                  id={profileFieldId(`business_hours.${row.day}.closed`)}
                  type="checkbox"
                  checked={row.closed}
                  disabled={disabled}
                  onChange={(e) => setDay(row.day, { closed: e.target.checked })}
                />
                Closed
              </label>
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        onClick={copyMonday}
        disabled={disabled}
        className="press rounded-sm text-meta font-medium text-brand-strong hover:underline disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        Copy Monday to Tuesday–Friday
      </button>
    </div>
  );
}

/** A day that is neither closed nor has both times, by day — the reason a save would be
 *  refused, said before it is sent. */
export function hoursProblems(draft: ProfileDraft): Partial<Record<Weekday, string>> {
  const out: Partial<Record<Weekday, string>> = {};
  for (const row of draft.business_hours) {
    if (row.closed) continue;
    if ((row.opens === "") !== (row.closes === "")) {
      out[row.day] = "Give both times, or tick Closed.";
    }
  }
  return out;
}
