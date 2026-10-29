"use client";

import { Lock, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { DatePicker } from "@/components/arc/calendar";
import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { todayIST } from "@/components/arc/ist-dates";
import { RadioGroup } from "@/components/arc/radio-group";
import {
  Card,
  Disclosure,
  FIELD_HINT,
  FIELD_INLINE,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
  istDateToInstant,
} from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { LeadCalling, LeadCallingInput } from "@/lib/api/leadCalling";
import { useClientRealm } from "@/lib/api/session";

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

const AFTER_HOURS: { value: AfterHours; label: string; hint: string }[] = [
  { value: "next_open", label: "Call when you open", hint: "The first minute of your next calling hours." },
  { value: "open_plus_3h", label: "Call 3 hours after you open", hint: "Mornings stay free for new leads." },
  { value: "next_day", label: "Call the next day", hint: "At opening on your next calling day." },
  { value: "hold", label: "Hold them for me", hint: "They wait for you to choose." },
];

/** `09:00:00` (the API) as `09:00` (the time input), and back. */
const hhmm = (value: string | undefined) => (value ?? "").slice(0, 5);

function toInput(plan: LeadCalling): Plan {
  return {
    hours_start: hhmm(plan.hours_start),
    hours_end: hhmm(plan.hours_end),
    days: plan.days,
    holidays: plan.holidays,
    after_hours: plan.after_hours,
    detect_machines: plan.detect_machines,
  };
}

function problemOf(plan: Plan, windowStart: string, windowEnd: string): string | null {
  const start = plan.hours_start ?? "";
  const end = plan.hours_end ?? "";
  if (!start || !end) return "Enter both times.";
  if (start < windowStart || end > windowEnd) {
    return `Use times between ${windowStart} and ${windowEnd}.`;
  }
  if (start >= end) return "The end time must be after the start time.";
  return null;
}

/**
 * One part of the plan as a folded row whose closed face says what it is set to
 * ("When to call · Straight away · 09:00–19:00"). Five open groups made this card the whole
 * phone screen, burying the lead sources under it (critique-information-density:
 * progressive disclosure). Native `<details>`, so every field stays mounted and a
 * half-made change survives folding.
 */
function Group({
  title,
  status,
  hint,
  open = false,
  children,
}: {
  title: string;
  status: ReactNode;
  hint?: string;
  open?: boolean;
  children: ReactNode;
}) {
  // Read once at mount: following `open` afterwards would fold the row shut under the
  // person's cursor the moment they fixed the problem that opened it.
  const [startOpen] = useState(open);
  return (
    <Disclosure variant="row" headingLevel={3} title={title} status={status} defaultOpen={startOpen}>
      <fieldset>
        <legend className="sr-only">{title}</legend>
        {hint && <p className="text-xs text-ink-muted">{hint}</p>}
        <div className="mt-3 space-y-3">{children}</div>
      </fieldset>
    </Disclosure>
  );
}

/**
 * The account's calling hours, for the whole business (founder decision 10, D-716).
 *
 * When to call, what happens after hours, and machines. Which agent calls a new lead, the
 * wait and the retries are the "Call new leads" Follow-up's (D-940). The rules nobody can
 * switch off close the card in the server's own words.
 */
export function CallingPlan({
  plan,
  canWrite,
  refusal,
  saveStatus,
  saveError,
  savedAgents,
  onSave,
}: {
  plan: { data?: LeadCalling; isLoading: boolean; error: unknown };
  agents: Agent[] | undefined;
  canWrite: boolean;
  refusal: string | null;
  /** The save's state from the screen's `useActionFeedback`. */
  saveStatus: FeedbackStatus;
  saveError: unknown;
  savedAgents: number | null;
  onSave: (next: Plan) => void;
}) {
  const { session, href } = useClientRealm();
  const [draft, setDraft] = useState<Plan | null>(null);
  const [holiday, setHoliday] = useState<string | null>(null);

  useEffect(() => {
    if (plan.data) setDraft(toInput(plan.data));
  }, [plan.data]);

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
  const afterHoursLabel = AFTER_HOURS.find((o) => o.value === draft.after_hours)?.label ?? "";
  const newLeads = plan.data.new_leads_follow_up;

  const addHoliday = () => {
    if (!holiday || holidays.includes(holiday) || holidays.length >= 60) return;
    set({ holidays: [...holidays, holiday].sort() });
    setHoliday(null);
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
            {plan.data.trial_notice} Calling starts when you go live.
          </NoticeBox>
        )}

        {newLeads && newLeads.status !== "live" && (
          <NoticeBox
            tone="warn"
            title={`${newLeads.name} is ${newLeads.status === "paused" ? "paused" : "off"}`}
            action={
              <Link href={href(`/c/${session.orgSlug}/follow-ups/${newLeads.id}`)} className={SECONDARY_BUTTON_SM}>
                Turn it back on
              </Link>
            }
          >
            New leads are saved but not called.
          </NoticeBox>
        )}

        <div className="-mx-1 divide-y divide-line rounded-card border border-line">
        <Group
          title="When to call"
          status={`${draft.hours_start ?? ""}–${draft.hours_end ?? ""}`}
          hint="Which agent calls, the wait and the tries are in Follow-ups."
          open={problem !== null}
        >
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
              {problem ?? `Between ${windowStart} and ${windowEnd} only.`}
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
            <div className="flex max-w-md flex-wrap items-end gap-2">
              <DatePicker
                label="Holidays (no calls)"
                value={holiday}
                onChange={setHoliday}
                min={todayIST()}
                isDisabled={(day) => holidays.includes(day)}
                disabled={!canWrite}
                className="min-w-0 flex-1"
              />
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={!canWrite || !holiday}
                onClick={addHoliday}
              >
                Add holiday
              </button>
            </div>
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

        <Group title="Leads that arrive after hours" status={afterHoursLabel}>
          <RadioGroup
            label={<span className="sr-only">Leads that arrive after hours</span>}
            name="after-hours"
            options={AFTER_HOURS}
            value={draft.after_hours ?? null}
            disabled={!canWrite}
            onChange={(next) => {
              const choice = AFTER_HOURS.find((option) => option.value === next);
              if (choice) set({ after_hours: choice.value });
            }}
          />
        </Group>

        <Group title="Answering machines" status={draft.detect_machines ? "Hang up" : "Keep talking"}>
          <ToggleSwitch
            label="Hang up if a machine answers"
            hint="For every call. Off: it talks to voicemail."
            checked={Boolean(draft.detect_machines)}
            disabled={!canWrite}
            onChange={(next) => set({ detect_machines: next })}
          />
        </Group>

        <Disclosure
          variant="row"
          headingLevel={3}
          title="Always applied"
          status={<Lock aria-label="Can't be changed" className="h-3.5 w-3.5" />}
        >
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-muted">
            {plan.data.always_applied.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        </Disclosure>
        </div>

        {saveError != null && <ProblemNotice error={saveError} />}
        <div className="flex flex-wrap items-center gap-3">
          <ActionButton
            type="submit"
            status={saveStatus}
            successLabel="Saved"
            disabled={!canWrite || (!dirty && saveStatus !== "success") || problem !== null}
            title={refusal ?? undefined}
          >
            Save
          </ActionButton>
          {dirty && saveStatus !== "pending" ? (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setDraft(toInput(plan.data!))}>
              Undo changes
            </button>
          ) : null}
          {problem ? <span className="text-xs text-danger">Check the calling hours</span> : null}
          <span role="status" className="text-xs text-ink-muted">
            {!dirty && savedAgents !== null
              ? savedAgents > 0
                ? `Saved. Updating ${savedAgents === 1 ? "1 live agent" : `${savedAgents} live agents`}.`
                : "Saved."
              : ""}
          </span>
        </div>
      </form>
    </Card>
  );
}
