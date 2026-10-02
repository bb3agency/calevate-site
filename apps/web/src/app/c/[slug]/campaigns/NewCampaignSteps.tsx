"use client";

import { CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { FIELD, FIELD_HINT, FIELD_LABEL, formatCount, formatPhone } from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate } from "@/lib/api/campaigns";
import { Term } from "@/lib/glossary";

import type { CampaignFormState, ScheduleFormState, StartMode } from "./campaignForm";
import { CLASSIFICATIONS, CONSENT_SOURCES, WEEKDAYS } from "./choices";
import { describeRepeat } from "./scheduleCopy";

/** A read a step is BUILT from: its failure is a dead picker, not an empty one. */
export interface ListQuery<T> {
  data: T[] | undefined;
  isLoading: boolean;
}

/** One choice-card radio group, the shape every choice on this flow uses. */
function ChoiceCards<T extends string>({
  legend,
  name,
  value,
  options,
  onChange,
  columns = "sm:grid-cols-3",
}: {
  legend: string;
  name: string;
  value: T;
  options: { value: T; label: string; hint: ReactNode }[];
  onChange: (value: T) => void;
  columns?: string;
}) {
  return (
    <fieldset>
      <legend className={FIELD_LABEL}>{legend}</legend>
      <div className={`mt-2 grid gap-2 ${columns}`}>
        {options.map((option) => (
          <label key={option.value} className={`${CHOICE_CARD} ${value === option.value ? CHOICE_ON : CHOICE_OFF}`}>
            <input
              type="radio"
              name={name}
              className="sr-only"
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            {value === option.value && (
              <CheckCircle2 aria-hidden className="absolute right-2 top-2 h-4 w-4 text-brand-strong" />
            )}
            <span className="block pr-6 text-sm font-semibold text-ink">{option.label}</span>
            <span className="mt-0.5 block text-xs text-ink-faint">{option.hint}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * STEP 1, THE BASICS: what the campaign is called, who makes the calls, what kind of call,
 * and what it dials from. The number and the DLT template sit here, beside the call type,
 * because both must MATCH it (a promotional call needs a 140-series number and a
 * promotional template) and a mismatch is easiest to avoid where the three are side by side.
 */
export function BasicsStep({
  form,
  agents,
  agentOptions,
  selectedAgentId,
  selectedAgent,
  hasNoAgents,
  numbers,
  templates,
}: {
  form: CampaignFormState;
  agents: { data: Agent[] | undefined };
  agentOptions: Agent[];
  selectedAgentId: string;
  selectedAgent: Agent | undefined;
  hasNoAgents: boolean;
  numbers: ListQuery<CampaignNumber>;
  templates: ListQuery<DltTemplate>;
}) {
  return (
    <div className="space-y-5">
      <label className="block max-w-sm">
        <span className={FIELD_LABEL}>Name</span>
        <input
          value={form.name}
          onChange={(e) => form.setName(e.target.value)}
          placeholder="e.g. Diwali service reminder"
          className={FIELD}
        />
      </label>

      {hasNoAgents && (
        <p className="text-sm text-ink-muted">
          No agent is set up yet — your account manager builds one before campaigns can run.
        </p>
      )}
      {/* Only from a list the server sent: an empty picker over a read in flight or failed
          would read as "you have no agent". */}
      {Boolean(agents.data) && agentOptions.length > 0 && (
        <label className="block max-w-sm">
          <span className={FIELD_LABEL}>Which agent makes these calls</span>
          <select value={selectedAgentId} onChange={(e) => form.setAgentId(e.target.value)} className={FIELD}>
            {agentOptions.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
                {canDialOut(agent) ? "" : " — not able to call out yet"}
              </option>
            ))}
          </select>
          <span className={FIELD_HINT}>
            {selectedAgent && !canDialOut(selectedAgent)
              ? "You can build the campaign now, but it will not launch until the agent is switched on and able to dial out."
              : "Its script and voice are what your customers will hear."}
          </span>
        </label>
      )}

      {/* The category decides which number series may dial (DATA-MODEL §6). */}
      <ChoiceCards
        legend="What kind of calls are these?"
        name="classification"
        value={form.classification}
        options={CLASSIFICATIONS}
        onChange={form.setClassification}
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block min-w-0">
          <span className={FIELD_LABEL}>Calling from</span>
          <select value={form.numberId} onChange={(e) => form.setNumberId(e.target.value)} className={FIELD}>
            <option value="">Choose a number…</option>
            {(numbers.data ?? []).map((option) => (
              <option key={option.id} value={option.id}>
                {formatPhone(option.e164)} ({option.series} series)
              </option>
            ))}
          </select>
          {/* "None" only from a list the server sent; a failed read is refused at the top. */}
          {numbers.data?.length === 0 && (
            <span className={FIELD_HINT}>No numbers yet — your account manager sets these up.</span>
          )}
        </label>
        <label className="block min-w-0">
          <span className={FIELD_LABEL}>
            <Term id="dlt" /> template
          </span>
          <select value={form.templateId} onChange={(e) => form.setTemplateId(e.target.value)} className={FIELD}>
            <option value="">Choose a template…</option>
            {(templates.data ?? []).map((option) => (
              <option key={option.id} value={option.id}>
                {option.classification} — {option.status}
              </option>
            ))}
          </select>
          {templates.data?.length === 0 && (
            <span className={FIELD_HINT}>None registered yet. Calls can&apos;t go out without one.</span>
          )}
        </label>
      </div>
    </div>
  );
}

const START_MODES: { value: StartMode; label: string; hint: string }[] = [
  { value: "review", label: "I'll launch it", hint: "From its checklist, once everything is ready." },
  { value: "later", label: "At a set time", hint: "Starts once, at the date and time you pick." },
  { value: "weekly", label: "Every week", hint: "Runs on the days and at the time you pick." },
];

/**
 * STEP 3, WHEN: how it starts, the hours it may call in, and its pace.
 *
 * Every option here is one the API takes: the window and the pace on create
 * (`CreateCampaignIn.calling_hours` / `concurrency`), the start on `POST …/schedule`, and the
 * weekly repeat on `POST …/recurrence`. The last two are sent after the draft exists, and
 * neither runs the launch gate when it is armed: the gate runs when the start fires, which
 * is why the hint under them says so. Retrying unanswered calls is the dispatcher's own
 * policy, not a create field, so it is stated rather than offered.
 */
export function WhenStep({ form, schedule }: { form: CampaignFormState; schedule: ScheduleFormState }) {
  return (
    <div className="space-y-5">
      <ChoiceCards
        legend="How should it start?"
        name="start-mode"
        value={schedule.startMode}
        options={START_MODES}
        onChange={schedule.setStartMode}
      />
      {schedule.startMode === "later" && (
        <div className="settings-enter grid max-w-sm grid-cols-2 gap-3">
          <label className="block">
            <span className={FIELD_LABEL}>Start date</span>
            <input type="date" value={schedule.startDate} onChange={(e) => schedule.setStartDate(e.target.value)} className={FIELD} />
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Start time (IST)</span>
            <input type="time" value={schedule.startTime} onChange={(e) => schedule.setStartTime(e.target.value)} className={FIELD} />
          </label>
        </div>
      )}
      {schedule.startMode === "weekly" && (
        <div className="settings-enter space-y-3">
          <fieldset>
            <legend className={FIELD_LABEL}>Which days</legend>
            <div className="mt-1 flex flex-wrap gap-2">
              {WEEKDAYS.map((day) => (
                <label
                  key={day.value}
                  className={`${CHOICE_CARD} px-3 py-1.5 ${schedule.repeatDays.includes(day.value) ? CHOICE_ON : CHOICE_OFF}`}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={schedule.repeatDays.includes(day.value)}
                    onChange={() => schedule.toggleRepeatDay(day.value)}
                  />
                  <span aria-hidden className="text-sm text-ink">{day.short}</span>
                  <span className="sr-only">{day.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="grid max-w-sm grid-cols-2 gap-3">
            <label className="block">
              <span className={FIELD_LABEL}>Time (IST)</span>
              <input type="time" value={schedule.repeatTime} onChange={(e) => schedule.setRepeatTime(e.target.value)} className={FIELD} />
            </label>
            <label className="block">
              <span className={FIELD_LABEL}>Stop after (optional)</span>
              <input type="date" value={schedule.repeatEnds} onChange={(e) => schedule.setRepeatEnds(e.target.value)} className={FIELD} />
            </label>
          </div>
        </div>
      )}
      {schedule.startMode !== "review" && (
        <p className={FIELD_HINT}>
          We check every launch requirement again at the moment it starts — a campaign that stops being allowed to
          dial between now and then will not start.
        </p>
      )}

      {/* The window NARROWS the 9am–9pm bound every dial already has; it never sets one. */}
      <fieldset>
        <label className="flex items-center gap-2 touch:min-h-11">
          <input
            type="checkbox"
            checked={form.restrictHours}
            onChange={(e) => form.setRestrictHours(e.target.checked)}
            className="h-4 w-4 rounded border-line accent-brand"
          />
          <span className="text-sm text-ink">Only call during specific hours</span>
        </label>
        <p className="mt-1 text-xs text-ink-faint">
          Calls never go out before 9am or after 9pm — this narrows that further.
        </p>
        {form.restrictHours && (
          <div className="settings-enter mt-3 grid max-w-xs grid-cols-2 gap-3">
            <label className="block">
              <span className={FIELD_LABEL}>From</span>
              <input type="time" value={form.windowStart} onChange={(e) => form.setWindowStart(e.target.value)} className={FIELD} />
            </label>
            <label className="block">
              <span className={FIELD_LABEL}>Until</span>
              <input type="time" value={form.windowEnd} onChange={(e) => form.setWindowEnd(e.target.value)} className={FIELD} />
            </label>
          </div>
        )}
      </fieldset>
      <label className="block max-w-xs">
        <span className={FIELD_LABEL}>Calls at the same time</span>
        <input
          type="number"
          min={1}
          max={10}
          value={form.concurrency}
          onChange={(e) => form.setConcurrency(Number(e.target.value))}
          className={FIELD}
        />
        <span className={FIELD_HINT}>Lower is slower. Lines are always kept free for people calling you.</span>
      </label>
      <p className="text-xs text-ink-faint">Anyone who doesn&apos;t answer is tried again later.</p>
    </div>
  );
}

/** The fourth step: what will be created, read back before the button that creates it. */
export function ReviewSummary({
  form,
  schedule,
  agentName,
  number,
  template,
}: {
  form: CampaignFormState;
  schedule: ScheduleFormState;
  agentName: string | undefined;
  number: CampaignNumber | undefined;
  template: DltTemplate | undefined;
}) {
  const source = CONSENT_SOURCES.find((option) => option.value === form.consentSource);
  const kind = CLASSIFICATIONS.find((option) => option.value === form.classification);
  const { counts } = form.checked;
  const start =
    schedule.startMode === "later"
      ? `${schedule.startDate} at ${schedule.startTime} IST`
      : schedule.startMode === "weekly"
        ? `Repeats ${describeRepeat({ days: schedule.repeatDays, at: schedule.repeatTime })} IST`
        : "You launch it from its checklist";
  return (
    <dl className="divide-y divide-line text-sm">
      <ReviewRow label="Name">{form.name}</ReviewRow>
      <ReviewRow label="Agent">{agentName ?? "None chosen"}</ReviewRow>
      <ReviewRow label="Kind of call">{kind?.label}</ReviewRow>
      <ReviewRow label="Calling from">{number ? formatPhone(number.e164) : "No number chosen"}</ReviewRow>
      <ReviewRow label="Template">
        {template ? `${template.classification} — ${template.status}` : "No template chosen"}
      </ReviewRow>
      <ReviewRow label="Contacts">
        {formatCount(counts.ready)} ready
        {counts.invalid + counts.duplicate > 0 &&
          ` · ${formatCount(counts.invalid + counts.duplicate)} left out`}
      </ReviewRow>
      <ReviewRow label="Where the list came from">
        {source?.label ?? "Not answered"}
        {form.consentDate ? ` · agreed ${form.consentDate}` : ""}
      </ReviewRow>
      <ReviewRow label="Start">{start}</ReviewRow>
      <ReviewRow label="Hours">
        {form.restrictHours ? `${form.windowStart}–${form.windowEnd} IST` : "9am–9pm IST"}
      </ReviewRow>
      <ReviewRow label="Calls at once">{form.concurrency}</ReviewRow>
    </dl>
  );
}

function ReviewRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 gap-y-0.5 py-2">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="min-w-0 font-medium text-ink">{children}</dd>
    </div>
  );
}
