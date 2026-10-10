"use client";

import { Lock, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_INLINE,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
  istDateToInstant,
} from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { LeadCalling, LeadCallingInput } from "@/lib/api/leadCalling";

type Plan = LeadCallingInput;
type Weekday = NonNullable<Plan["days"]>[number];
type AfterHours = NonNullable<Plan["after_hours"]>;

const DAYS: { key: Weekday; short: string; long: string }[] = [
  { key: "mon", short: "Mon", long: "Monday" },
  { key: "tue", short: "Tue", long: "Tuesday" },
  { key: "wed", short: "Wed", long: "Wednesday" },
  { key: "thu", short: "Thu", long: "Thursday" },
  { key: "fri", short: "Fri", long: "Friday" },
  { key: "sat", short: "Sat", long: "Saturday" },
  { key: "sun", short: "Sun", long: "Sunday" },
];

/** A holiday is a calendar day in India (D-709), read the same whatever zone the viewer's laptop is in. */
function holidayLabel(day: string): string {
  const instant = istDateToInstant(day);
  if (!instant) return day;
  return new Date(instant).toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

const WAITS: { seconds: number; label: string }[] = [
  { seconds: 0, label: "Straight away" },
  { seconds: 30, label: "After 30 seconds" },
  { seconds: 60, label: "After 1 minute" },
  { seconds: 120, label: "After 2 minutes" },
  { seconds: 300, label: "After 5 minutes" },
  { seconds: 900, label: "After 15 minutes" },
  { seconds: 1800, label: "After 30 minutes" },
  { seconds: 3600, label: "After 1 hour" },
];

const AFTER_HOURS: { key: AfterHours; label: string; hint: string }[] = [
  { key: "next_open", label: "Call when you open", hint: "The first minute of your next calling hours." },
  { key: "open_plus_3h", label: "Call 3 hours after you open", hint: "Leaves the morning for leads that arrive then." },
  { key: "next_day", label: "Call the next day", hint: "At opening on your next calling day, even if you open later today." },
  { key: "hold", label: "Hold them for me", hint: "They wait below until you choose to call or not." },
];

const INTERVALS: { minutes: number; label: string }[] = [
  { minutes: 10, label: "10 minutes" },
  { minutes: 30, label: "30 minutes" },
  { minutes: 60, label: "1 hour" },
  { minutes: 120, label: "2 hours" },
  { minutes: 180, label: "3 hours" },
  { minutes: 360, label: "6 hours" },
  { minutes: 1440, label: "1 day" },
];

/** `09:00:00` (the API) as `09:00` (the time input), and back. */
const hhmm = (value: string | undefined) => (value ?? "").slice(0, 5);

function toInput(plan: LeadCalling): Plan {
  return {
    calling_agent_id: plan.calling_agent_id,
    wait_seconds: plan.wait_seconds,
    hours_start: hhmm(plan.hours_start),
    hours_end: hhmm(plan.hours_end),
    days: plan.days,
    holidays: plan.holidays,
    after_hours: plan.after_hours,
    retry_attempts: plan.retry_attempts,
    retry_interval_minutes: plan.retry_interval_minutes,
    detect_machines: plan.detect_machines,
  };
}

function problemOf(plan: Plan, windowStart: string, windowEnd: string): string | null {
  const start = plan.hours_start ?? "";
  const end = plan.hours_end ?? "";
  if (!start || !end) return "Enter both times.";
  if (start < windowStart || end > windowEnd) {
    return `Calling hours must sit between ${windowStart} and ${windowEnd}.`;
  }
  if (start >= end) return "The end time must be after the start time.";
  return null;
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="border-t border-line pt-4 first:border-t-0 first:pt-0">
      <legend className="text-sm font-semibold text-ink">{title}</legend>
      {hint && <p className="mt-0.5 text-xs text-ink-muted">{hint}</p>}
      <div className="mt-3 space-y-3">{children}</div>
    </fieldset>
  );
}

/**
 * How new leads are called, for the whole business (founder decision 10, D-716).
 *
 * One form in five groups read top to bottom in the order a lead lives through them: who
 * calls, when, what happens after hours, what happens if nobody answers, and machines.
 * The rules nobody can switch off close the card in the server's own words.
 */
export function CallingPlan({
  plan,
  agents,
  canWrite,
  refusal,
  saving,
  saveError,
  savedAgents,
  onSave,
}: {
  plan: { data?: LeadCalling; isLoading: boolean; error: unknown };
  agents: Agent[] | undefined;
  canWrite: boolean;
  refusal: string | null;
  saving: boolean;
  saveError: unknown;
  savedAgents: number | null;
  onSave: (next: Plan) => void;
}) {
  const [draft, setDraft] = useState<Plan | null>(null);
  const [holiday, setHoliday] = useState("");

  useEffect(() => {
    if (plan.data) setDraft(toInput(plan.data));
  }, [plan.data]);

  const callers = useMemo(
    () =>
      (agents ?? []).filter(
        (agent) => agent.status !== "archived" && agent.direction !== "inbound",
      ),
    [agents],
  );

  if (plan.isLoading || (!draft && !plan.error)) {
    return (
      <Card title="How new leads are called">
        <Skeleton rows={6} />
      </Card>
    );
  }
  if (!plan.data || !draft) {
    return (
      <Card title="How new leads are called">
        <ProblemNotice error={plan.error} />
      </Card>
    );
  }

  const windowStart = hhmm(plan.data.window_start);
  const windowEnd = hhmm(plan.data.window_end);
  const problem = problemOf(draft, windowStart, windowEnd);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toInput(plan.data));
  const set = (patch: Partial<Plan>) => setDraft({ ...draft, ...patch });
  const days = draft.days ?? [];
  const holidays = draft.holidays ?? [];
  const retries = draft.retry_attempts ?? 0;

  const addHoliday = () => {
    if (!holiday || holidays.includes(holiday) || holidays.length >= 60) return;
    set({ holidays: [...holidays, holiday].sort() });
    setHoliday("");
  };

  return (
    <Card title="How new leads are called">
      <form
        className="space-y-5"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!problem && canWrite) onSave(draft);
        }}
      >
        {plan.data.trial_notice && (
          <NoticeBox tone="warn" title="Free trial: test calls only">
            {plan.data.trial_notice} You can set this up now; it starts calling once your
            account is live.
          </NoticeBox>
        )}

        <Group title="Who calls" hint="One agent calls every new lead, from every source.">
          <label className="block max-w-md">
            <span className={FIELD_LABEL}>Agent</span>
            <select
              className={FIELD}
              value={draft.calling_agent_id ?? ""}
              disabled={!canWrite}
              onChange={(event) => set({ calling_agent_id: event.target.value || null })}
            >
              <option value="">The agent each lead source was set up with</option>
              {callers.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                  {agent.status === "live" ? "" : " (not switched on)"}
                </option>
              ))}
            </select>
            <span className={FIELD_HINT}>Only agents that place calls are listed.</span>
          </label>
        </Group>

        <Group title="When to call">
          <label className="block max-w-md">
            <span className={FIELD_LABEL}>Wait before calling</span>
            <select
              className={FIELD}
              value={draft.wait_seconds ?? 0}
              disabled={!canWrite}
              onChange={(event) => set({ wait_seconds: Number(event.target.value) })}
            >
              {WAITS.map((wait) => (
                <option key={wait.seconds} value={wait.seconds}>
                  {wait.label}
                </option>
              ))}
            </select>
            <span className={FIELD_HINT}>
              A short wait lets someone finish the form before the phone rings. Waits are
              checked every 30 seconds.
            </span>
          </label>

          <div>
            <span className={FIELD_LABEL} id="calling-hours-label">
              Calling hours (Indian time)
            </span>
            <div className="mt-1 flex flex-wrap items-center gap-2" aria-labelledby="calling-hours-label">
              <input
                type="time"
                aria-label="Start calling at"
                className={FIELD_INLINE}
                min={windowStart}
                max={windowEnd}
                step={900}
                value={draft.hours_start ?? ""}
                disabled={!canWrite}
                aria-invalid={problem ? true : undefined}
                aria-describedby="calling-hours-hint"
                onChange={(event) => set({ hours_start: event.target.value })}
              />
              <span className="text-sm text-ink-muted">to</span>
              <input
                type="time"
                aria-label="Stop calling at"
                className={FIELD_INLINE}
                min={windowStart}
                max={windowEnd}
                step={900}
                value={draft.hours_end ?? ""}
                disabled={!canWrite}
                aria-invalid={problem ? true : undefined}
                aria-describedby="calling-hours-hint"
                onChange={(event) => set({ hours_end: event.target.value })}
              />
            </div>
            <span id="calling-hours-hint" className={problem ? "mt-1 block text-xs text-danger" : FIELD_HINT}>
              {problem ?? `Anywhere between ${windowStart} and ${windowEnd}; nobody is called outside that.`}
            </span>
          </div>

          <fieldset>
            <legend className={FIELD_LABEL}>Calling days</legend>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {DAYS.map((day) => {
                const on = days.includes(day.key);
                return (
                  <label
                    key={day.key}
                    className={`press flex cursor-pointer items-center rounded-md border px-2.5 py-1 text-sm touch:min-h-11 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app ${
                      on ? "border-brand bg-brand-soft text-brand-strong" : "border-line text-ink-muted"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={on}
                      disabled={!canWrite || (on && days.length === 1)}
                      aria-label={day.long}
                      onChange={() =>
                        set({
                          days: on
                            ? days.filter((d) => d !== day.key)
                            : DAYS.map((d) => d.key).filter((d) => d === day.key || days.includes(d)),
                        })
                      }
                    />
                    {day.short}
                  </label>
                );
              })}
            </div>
            <span className={FIELD_HINT}>At least one day stays on.</span>
          </fieldset>

          <div>
            <label className="block max-w-md">
              <span className={FIELD_LABEL}>Holidays (no calls)</span>
              <span className="mt-1 flex flex-wrap items-center gap-2">
                <input
                  type="date"
                  className={FIELD_INLINE}
                  value={holiday}
                  disabled={!canWrite}
                  onChange={(event) => setHoliday(event.target.value)}
                />
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={!canWrite || !holiday}
                  onClick={addHoliday}
                >
                  Add holiday
                </button>
              </span>
            </label>
            {holidays.length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Holidays">
                {holidays.map((day) => (
                  <li
                    key={day}
                    className="flex items-center gap-1 rounded-md border border-line px-2 py-0.5 text-xs text-ink"
                  >
                    {holidayLabel(day)}
                    <button
                      type="button"
                      aria-label={`Remove ${day}`}
                      disabled={!canWrite}
                      className="rounded p-0.5 text-ink-faint hover:text-ink touch:min-h-11 touch:min-w-11"
                      onClick={() => set({ holidays: holidays.filter((d) => d !== day) })}
                    >
                      <X aria-hidden className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <span className={FIELD_HINT}>None added.</span>
            )}
          </div>
        </Group>

        <Group title="Leads that arrive after hours">
          <div className="space-y-2" role="radiogroup" aria-label="Leads that arrive after hours">
            {AFTER_HOURS.map((choice) => (
              <label key={choice.key} className="flex cursor-pointer items-start gap-2.5">
                <input
                  type="radio"
                  name="after-hours"
                  className="mt-1 accent-brand"
                  checked={draft.after_hours === choice.key}
                  disabled={!canWrite}
                  onChange={() => set({ after_hours: choice.key })}
                />
                <span>
                  <span className="block text-sm text-ink">{choice.label}</span>
                  <span className="block text-xs text-ink-muted">{choice.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </Group>

        <Group title="If nobody answers">
          <div role="radiogroup" aria-label="Try again" className="flex flex-wrap gap-1.5">
            {[0, 1, 2, 3].map((count) => (
              <label
                key={count}
                className={`press flex cursor-pointer items-center rounded-md border px-2.5 py-1 text-sm touch:min-h-11 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app ${
                  retries === count ? "border-brand bg-brand-soft text-brand-strong" : "border-line text-ink-muted"
                }`}
              >
                <input
                  type="radio"
                  name="retries"
                  className="sr-only"
                  checked={retries === count}
                  disabled={!canWrite}
                  onChange={() => set({ retry_attempts: count })}
                />
                {count === 0 ? "Don't try again" : count === 1 ? "Try once more" : `Try ${count} more times`}
              </label>
            ))}
          </div>
          {retries > 0 && (
            <label className="block max-w-md">
              <span className={FIELD_LABEL}>Between tries, wait</span>
              <select
                className={FIELD}
                value={draft.retry_interval_minutes ?? 60}
                disabled={!canWrite}
                onChange={(event) => set({ retry_interval_minutes: Number(event.target.value) })}
              >
                {INTERVALS.map((interval) => (
                  <option key={interval.minutes} value={interval.minutes}>
                    {interval.label}
                  </option>
                ))}
              </select>
              <span className={FIELD_HINT}>
                A try that lands outside your hours moves to your next opening. Tries stop
                once they answer or call you back.
              </span>
            </label>
          )}
        </Group>

        <Group title="Answering machines">
          <ToggleSwitch
            label="Hang up if a machine answers"
            hint="Applies to every call your agents place. Off means the agent speaks to voicemail too."
            checked={Boolean(draft.detect_machines)}
            disabled={!canWrite}
            onChange={(next) => set({ detect_machines: next })}
          />
        </Group>

        <section aria-labelledby="always-applied" className="rounded-md bg-surface-muted px-4 py-3">
          <h3 id="always-applied" className="flex items-center gap-1.5 text-xs font-semibold text-ink">
            <Lock aria-hidden className="h-3.5 w-3.5" />
            Always applied, whatever you choose
          </h3>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs text-ink-muted">
            {plan.data.always_applied.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        </section>

        {saveError != null && <ProblemNotice error={saveError} />}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            className={PRIMARY_BUTTON}
            disabled={!canWrite || !dirty || saving || problem !== null}
            title={refusal ?? undefined}
          >
            {saving ? "Saving…" : "Save"}
          </button>
          {dirty && !saving ? (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setDraft(toInput(plan.data!))}>
              Undo changes
            </button>
          ) : null}
          <span role="status" className="text-xs text-ink-muted">
            {!dirty && savedAgents !== null
              ? savedAgents > 0
                ? `Saved. ${savedAgents} live agent${savedAgents === 1 ? "" : "s"} updated.`
                : "Saved."
              : ""}
          </span>
        </div>
      </form>
    </Card>
  );
}
