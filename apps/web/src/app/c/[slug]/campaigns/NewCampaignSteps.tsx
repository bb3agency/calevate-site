"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { NumberField } from "@/components/arc/number-field";
import { TEXT_ACTION } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { FIELD, FIELD_HINT, FIELD_LABEL, SECONDARY_BUTTON_SM, formatPhone } from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import { usePeRegistration } from "@/lib/api/dltRegistration";
import { useClientRealm } from "@/lib/api/session";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import type { Agent } from "@/lib/api/agents";
import {
  RETRY_GAP_CHOICES,
  type CampaignNumber,
  type DltTemplate,
  type RetryPolicy,
} from "@/lib/api/campaigns";
import { Term } from "@/lib/glossary";

import type { CampaignFormState, ScheduleFormState, StartMode } from "./campaignForm";
import { offeredClassifications } from "./choices";
import { RepeatFields, StartAtFields } from "./ScheduleFields";
import { describeRepeat } from "./scheduleCopy";

/** A read a step is BUILT from: its failure is a dead picker, not an empty one. */
export interface ListQuery<T> {
  data: T[] | undefined;
  isLoading: boolean;
}

/**
 * The numbers a campaign of this agent can call from: the launch gate's own predicate
 * (`places_calls`) and the agent binding it also checks (`number_not_bound_to_agent`), so
 * the picker never offers a number the launch then refuses.
 */
export function campaignNumbers(
  numbers: CampaignNumber[] | undefined,
  agentId: string,
): CampaignNumber[] {
  return (numbers ?? []).filter((number) => number.places_calls && number.agent_id === agentId);
}

/** "30 min", "2 hours", "1 day": a gap between tries as a person says it. */
export function gapWords(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 1440) return `${minutes / 60} ${minutes === 60 ? "hour" : "hours"}`;
  return "1 day";
}

/** The retry policy in one line: "3 tries, 30 min then 2 hours apart". */
export function describeRetry(retry: { max_attempts: number; gaps_minutes?: number[] }): string {
  if (retry.max_attempts === 1) return "1 try, no retries";
  return `${retry.max_attempts} tries, ${(retry.gaps_minutes ?? []).map(gapWords).join(" then ")} apart`;
}

/**
 * HOW OFTEN TO TRY ONE PERSON (D-773): 1–5 tries, and a gap before each retry from the
 * server's fixed menu (`RETRY_GAP_CHOICES`). Changing the count keeps the gaps already
 * chosen and fills new ones with the last.
 */
export function RetryChoice({
  value,
  onChange,
}: {
  value: RetryPolicy;
  onChange: (value: RetryPolicy) => void;
}) {
  const gapList = value.gaps_minutes ?? [];
  const setAttempts = (attempts: number) => {
    const gaps = (value.gaps_minutes ?? []).slice(0, attempts - 1);
    while (gaps.length < attempts - 1) gaps.push(gaps[gaps.length - 1] ?? 30);
    onChange({ max_attempts: attempts, gaps_minutes: gaps });
  };
  return (
    <div className="space-y-3">
      <NumberField
        className="max-w-xs"
        label="Tries per person"
        hint="1 means no retries. Answered calls are never retried."
        value={value.max_attempts}
        onChange={(next) => setAttempts(next ?? 1)}
        min={1}
        max={5}
      />
      {gapList.length > 0 && (
        <div className="grid grid-cols-1 max-w-md gap-3 sm:grid-cols-2">
          {gapList.map((gap, index) => (
            <label key={index} className="block">
              <span className={FIELD_LABEL}>Wait before try {index + 2}</span>
              <select
                value={gap}
                onChange={(e) => {
                  const gaps = [...gapList];
                  gaps[index] = Number(e.target.value);
                  onChange({ ...value, gaps_minutes: gaps });
                }}
                className={FIELD}
              >
                {RETRY_GAP_CHOICES.map((choice) => (
                  <option key={choice} value={choice}>
                    {gapWords(choice)}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * A short choice: its question, a segmented control, and one line on the option picked.
 * Each option here is a word or three, so cards would only add height; the line under the
 * control carries what a card's second line used to.
 */
function ShortChoice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; hint: ReactNode }[];
  onChange: (value: T) => void;
}) {
  const picked = options.find((option) => option.value === value);
  return (
    <div>
      <p className={FIELD_LABEL} aria-hidden>
        {label}
      </p>
      <SegmentedControl
        label={label}
        className="mt-1.5"
        value={value}
        options={options.map((option) => ({ value: option.value, label: option.label }))}
        onValueChange={(next) => onChange(next as T)}
      />
      {picked && <p className={FIELD_HINT}>{picked.hint}</p>}
    </div>
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
  showTemplate = true,
}: {
  form: CampaignFormState;
  agents: { data: Agent[] | undefined };
  agentOptions: Agent[];
  selectedAgentId: string;
  selectedAgent: Agent | undefined;
  hasNoAgents: boolean;
  numbers: ListQuery<CampaignNumber>;
  templates: ListQuery<DltTemplate>;
  /** The edit page has no template field: `PATCH` does not change it. */
  showTemplate?: boolean;
}) {
  const usable = campaignNumbers(numbers.data, selectedAgentId);
  const { session, href } = useClientRealm();
  const registration = usePeRegistration(session);
  const eg = useVerticalExamples();
  const classifications = offeredClassifications(
    registration.data?.calevate_tm_active === true,
    form.classification,
  );
  return (
    <div className="space-y-5">
      <label className="block max-w-sm">
        <span className={FIELD_LABEL}>Name</span>
        <input
          value={form.name}
          onChange={(e) => form.setName(e.target.value)}
          placeholder={`e.g. ${eg.campaignName}`}
          className={FIELD}
        />
      </label>

      {hasNoAgents && (
        <div className="space-y-2">
          <p className="text-sm text-ink">No agent is set up yet.</p>
          <Link href={href(`/c/${session.orgSlug}/agents`)} className={SECONDARY_BUTTON_SM}>
            Create an agent
          </Link>
        </div>
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
          {selectedAgent && !canDialOut(selectedAgent) ? (
            <span className={FIELD_HINT}>It can&rsquo;t call out yet. You can still build this.</span>
          ) : null}
        </label>
      )}

      {/* The category decides which number series may dial (DATA-MODEL §6). */}
      <ShortChoice
        label="What kind of calls are these?"
        value={form.classification}
        options={classifications}
        onChange={form.setClassification}
      />

      <div className="grid max-w-sm gap-5">
        <label className="block min-w-0">
          <span className={FIELD_LABEL}>Calling from</span>
          <select value={form.numberId} onChange={(e) => form.setNumberId(e.target.value)} className={FIELD}>
            <option value="">The agent&rsquo;s own number</option>
            {usable.map((option) => (
              <option key={option.id} value={option.id}>
                {formatPhone(option.e164)} ({option.series} series)
              </option>
            ))}
          </select>
          {/* Only from a list the server sent; a failed read is refused at the top. */}
          {numbers.data && (
            <span className={FIELD_HINT}>
              {usable.length === 0
                ? "No number set up for this agent. Its own is used."
                : "Only numbers this agent can call from."}
            </span>
          )}
        </label>
        {showTemplate && (
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
            <span className={FIELD_HINT}>None registered. Not needed to call.</span>
          )}
        </label>
        )}
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
      <ShortChoice
        label="How should it start?"
        value={schedule.startMode}
        options={START_MODES}
        onChange={schedule.setStartMode}
      />
      {schedule.startMode === "later" && (
        <div className="settings-enter">
          <StartAtFields schedule={schedule} />
        </div>
      )}
      {schedule.startMode === "weekly" && (
        <div className="settings-enter space-y-3">
          <RepeatFields schedule={schedule} />
          <p className={FIELD_HINT}>{describeRepeat({ days: schedule.repeatDays, at: schedule.repeatTime })}</p>
        </div>
      )}
      {schedule.startMode !== "review" && (
        <p className={FIELD_HINT}>We check everything again when it starts.</p>
      )}
    </div>
  );
}

/**
 * THE PRE-SET RULES, as rows with Change (founder, REDESIGN-2):
 * the hours it may call in, how many calls run at once and how often an unanswered person
 * is tried again are this campaign's own (`calling_hours`, `concurrency`, `retry_policy`);
 * skipping the do-not-call list is the platform's and is stated, not offered.
 */
export function PaceRows({ form }: { form: CampaignFormState }) {
  const [editing, setEditing] = useState<"hours" | "pace" | "retry" | null>(null);
  const change = (what: "hours" | "pace" | "retry") => (
    <button type="button" className={TEXT_ACTION} onClick={() => setEditing(editing === what ? null : what)} aria-expanded={editing === what}>
      {editing === what ? "Done" : "Change"}
    </button>
  );
  return (
    <SettingRows className="border-y border-line">
      <SettingRow
        label="Calling hours"
        hint="Never before 9am or after 9pm. You can narrow it."
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
        <div className="settings-enter max-w-xs pb-4">
          <NumberField
            label="Calls at the same time"
            hint="1 to 10. Your plan may allow fewer."
            value={form.concurrency}
            onChange={(next) => form.setConcurrency(next ?? 1)}
            min={1}
            max={10}
            unit="calls"
          />
        </div>
      )}
      <SettingRow
        label="If nobody answers"
        hint="Tries per person, and the wait between."
        value={describeRetry(form.retry)}
        action={change("retry")}
      />
      {editing === "retry" && (
        <div className="settings-enter pb-4">
          <RetryChoice value={form.retry} onChange={form.setRetry} />
        </div>
      )}
      <SettingRow label="Do-not-call list" value="Numbers on it are always skipped" />
    </SettingRows>
  );
}
