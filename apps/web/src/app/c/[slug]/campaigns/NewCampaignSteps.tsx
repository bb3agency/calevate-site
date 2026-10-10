"use client";

import { CheckCircle2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { FIELD, FIELD_HINT, FIELD_LABEL, formatPhone } from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate } from "@/lib/api/campaigns";
import { Term } from "@/lib/glossary";

import type { CampaignFormState, ScheduleFormState, StartMode } from "./campaignForm";
import { CLASSIFICATIONS, WEEKDAYS } from "./choices";
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
 * and what it dials from. The number sits here, beside the call type. A DLT template is
 * optional since D-692 (outbound needs verified KYC and the no-cold-calls pledge); it is
 * still offered for a client who registered one.
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
          No agent is set up yet — create one in Agents before campaigns can run.
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
            <span className={FIELD_HINT}>No numbers yet — buy one on the Numbers page.</span>
          )}
        </label>
        <label className="block min-w-0">
          <span className={FIELD_LABEL}>
            <Term id="dlt" /> template (optional)
          </span>
          <select value={form.templateId} onChange={(e) => form.setTemplateId(e.target.value)} className={FIELD}>
            <option value="">No template</option>
            {(templates.data ?? []).map((option) => (
              <option key={option.id} value={option.id}>
                {option.classification} — {option.status}
              </option>
            ))}
          </select>
          {templates.data?.length === 0 && (
            <span className={FIELD_HINT}>None registered. You do not need one to make calls.</span>
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
 * WHEN IT STARTS: launched by hand, once at a set time, or every week.
 *
 * Every option is one the API takes: the start on `POST …/schedule` and the weekly repeat
 * on `POST …/recurrence`, both sent after the draft exists. Neither runs the launch gate
 * when it is armed; the gate runs when the start fires, which is why the hint says so.
 */
export function StartChoice({ schedule }: { schedule: ScheduleFormState }) {
  return (
    <div className="space-y-4">
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
                  <span aria-hidden className="text-body text-ink">{day.short}</span>
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
          <p className={FIELD_HINT}>{describeRepeat({ days: schedule.repeatDays, at: schedule.repeatTime })}</p>
        </div>
      )}
      {schedule.startMode !== "review" && (
        <p className={FIELD_HINT}>
          We check every launch requirement again at the moment it starts — a campaign that stops being allowed to
          dial between now and then will not start.
        </p>
      )}
    </div>
  );
}

/**
 * THE PRE-SET RULES, as rows with Change (founder, REDESIGN-2): the hours it may call in
 * and how many calls run at once are the create fields (`calling_hours`, `concurrency`);
 * retrying unanswered calls and skipping the do-not-call list are the platform's own and
 * are stated, not offered.
 */
export function PaceRows({ form }: { form: CampaignFormState }) {
  const [editing, setEditing] = useState<"hours" | "pace" | null>(null);
  const change = (what: "hours" | "pace") => (
    <button type="button" className={TEXT_ACTION} onClick={() => setEditing(editing === what ? null : what)} aria-expanded={editing === what}>
      {editing === what ? "Done" : "Change"}
    </button>
  );
  return (
    <SettingRows className="border-y border-line">
      <SettingRow
        label="Calling hours"
        hint="Calls never go out before 9am or after 9pm. You can narrow that."
        value={form.restrictHours ? `${form.windowStart || "…"} – ${form.windowEnd || "…"} IST` : "9am – 9pm IST"}
        action={change("hours")}
      />
      {editing === "hours" && (
        <div className="settings-enter space-y-3 pb-4">
          <label className="flex items-center gap-2 touch:min-h-11">
            <input
              type="checkbox"
              checked={form.restrictHours}
              onChange={(e) => form.setRestrictHours(e.target.checked)}
              className="h-4 w-4 rounded border-line accent-brand"
            />
            <span className="text-body text-ink">Only call during specific hours</span>
          </label>
          {form.restrictHours && (
            <div className="grid max-w-xs grid-cols-2 gap-3">
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
        </div>
      )}
      <SettingRow
        label="Calls at the same time"
        hint="Lines are always kept free for people calling you."
        value={String(form.concurrency)}
        action={change("pace")}
      />
      {editing === "pace" && (
        <div className="settings-enter pb-4">
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
            <span className={FIELD_HINT}>Between 1 and 10. Lower is slower.</span>
          </label>
        </div>
      )}
      <SettingRow label="No answer" value="Tried again later" />
      <SettingRow label="Do-not-call list" value="Numbers on it are always skipped" />
    </SettingRows>
  );
}
