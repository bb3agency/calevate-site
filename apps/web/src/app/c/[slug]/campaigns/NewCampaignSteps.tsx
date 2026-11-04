"use client";

import Link from "next/link";
import { CalendarClock, CalendarDays, Hand, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { NumberField } from "@/components/arc/number-field";
import { ChoiceCards } from "@/components/console/choiceCards";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { FIELD, FIELD_HINT, FIELD_LABEL, SECONDARY_BUTTON_SM, Skeleton, formatPhone } from "@/components/ui";
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

import { BriefFields } from "./BriefFields";
import {
  CONCURRENCY_MAX,
  clampConcurrency,
  type CampaignFormState,
  type ScheduleFormState,
  type StartMode,
} from "./campaignForm";
import { offeredClassifications } from "./choices";
import { RepeatFields, StartAtFields } from "./ScheduleFields";
import { describeRepeat } from "./scheduleCopy";

/** A read a step is BUILT from: its failure is a dead picker, not an empty one. */
export interface ListQuery<T> {
  data: T[] | undefined;
  isLoading: boolean;
}

/**
 * The numbers a campaign can call from: the launch gate's own predicate (`places_calls`),
 * so the picker never offers a number the launch then refuses. Any of the account's numbers
 * serves any of its agents; the call lends it to the campaign's agent.
 */
export function campaignNumbers(numbers: CampaignNumber[] | undefined): CampaignNumber[] {
  return (numbers ?? []).filter((number) => number.places_calls);
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

/** Calling hours in one line, the platform window when none is set. */
export function describeHours(form: Pick<CampaignFormState, "restrictHours" | "windowStart" | "windowEnd">): string {
  return form.restrictHours ? `${form.windowStart || "…"} – ${form.windowEnd || "…"} IST` : "9am – 9pm IST";
}

/**
 * A group of related fields inside a step, titled by what it decides. Proximity does the
 * grouping; the rule between groups is the only container, so a step reads as one form
 * rather than a stack of cards.
 */
export function FieldGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-4 border-t border-line pt-6 first:border-t-0 first:pt-0">
      <h4 className="text-body font-semibold text-ink">{title}</h4>
      {children}
    </div>
  );
}

const TRIES = ["1", "2", "3", "4", "5"] as const;

/**
 * HOW OFTEN TO TRY ONE PERSON (D-773): 1–5 tries, and a gap before each retry from the
 * server's fixed menu (`RETRY_GAP_CHOICES`). Changing the count keeps the gaps already
 * chosen and fills new ones with the last. Five values, so a segmented control: every
 * answer is visible and one tap away, where a stepper hid four of them.
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
      <div>
        <p className={FIELD_LABEL} aria-hidden>
          Tries per person
        </p>
        <SegmentedControl
          label="Tries per person"
          className="mt-1.5"
          value={String(value.max_attempts)}
          options={TRIES.map((n) => ({ value: n, label: n }))}
          onValueChange={(next) => setAttempts(Number(next))}
        />
        <p className={FIELD_HINT}>1 means no retries. Answered calls are never retried.</p>
      </div>
      {gapList.length > 0 && (
        <div className="settings-enter grid max-w-md grid-cols-1 gap-3 sm:grid-cols-2">
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
 * STEP 1, THE BASICS, in three groups: who is calling (name and agent), what the calls are
 * for (why, and what a good call ends with), and how they are sent (kind of call, the
 * number, an optional DLT template). A template is optional since D-692 (outbound needs
 * verified KYC and the no-cold-calls pledge); it is still offered for a client who
 * registered one.
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
  const usable = campaignNumbers(numbers.data);
  const { session, href } = useClientRealm();
  const registration = usePeRegistration(session);
  const eg = useVerticalExamples();
  const classifications = offeredClassifications(
    registration.data?.calevate_tm_active === true,
    form.classification,
  );
  return (
    <div className="space-y-6">
      <FieldGroup title="Who is calling">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="block min-w-0">
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
          {/* Only from a list the server sent: an empty picker over a read in flight or
              failed would read as "you have no agent". */}
          {Boolean(agents.data) && agentOptions.length > 0 && (
            <label className="block min-w-0">
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
          {!agents.data && !hasNoAgents && <Skeleton rows={1} label="Loading your agents" />}
        </div>
      </FieldGroup>

      <FieldGroup title="What the calls are for">
        <BriefFields form={form} agentId={selectedAgentId} />
      </FieldGroup>

      <FieldGroup title="How they are placed">
        {/* The category decides which number series may dial (DATA-MODEL §6). */}
        <ShortChoice
          label="What kind of calls are these?"
          value={form.classification}
          options={classifications}
          onChange={form.setClassification}
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
                  ? "No number can make calls yet. The agent's own line is used."
                  : "Any of your numbers. Every agent can call from them."}
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
      </FieldGroup>
    </div>
  );
}

const ICON = "h-4 w-4 text-brand-strong";

const START_MODES: { value: StartMode; label: string; hint: string; icon: ReactNode }[] = [
  {
    value: "review",
    label: "I'll launch it",
    hint: "From its checklist, once everything is ready.",
    icon: <Hand aria-hidden className={ICON} />,
  },
  {
    value: "later",
    label: "At a set time",
    hint: "Starts once, at the date and time you pick.",
    icon: <CalendarClock aria-hidden className={ICON} />,
  },
  {
    value: "weekly",
    label: "Every week",
    hint: "Runs on the days and at the time you pick.",
    icon: <CalendarDays aria-hidden className={ICON} />,
  },
];

/** "I'll launch it", "At a set time", "Every week": the start as a person names it. */
export const START_MODE_LABEL: Record<StartMode, string> = {
  review: START_MODES[0].label,
  later: START_MODES[1].label,
  weekly: START_MODES[2].label,
};

/**
 * WHEN IT STARTS: launched by hand, once at a set time, or every week — three cards, since
 * each answer changes what the step asks next and deserves its sentence on show.
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
        legendClassName="sr-only"
        name="campaign-start-mode"
        value={schedule.startMode}
        options={START_MODES}
        onChange={schedule.setStartMode}
        columns="sm:grid-cols-3"
      />
      {schedule.startMode === "later" && (
        <div className="settings-enter">
          <StartAtFields schedule={schedule} />
        </div>
      )}
      {schedule.startMode === "weekly" && (
        <div className="settings-enter space-y-3">
          <RepeatFields schedule={schedule} />
          <p className="text-body text-ink">Runs {describeRepeat({ days: schedule.repeatDays, at: schedule.repeatTime })}.</p>
        </div>
      )}
      {schedule.startMode !== "review" && (
        <p className={FIELD_HINT}>We check everything again when it starts.</p>
      )}
    </div>
  );
}

const HOURS = [
  { value: "any", label: "9am to 9pm" },
  { value: "set", label: "Set hours" },
] as const;

/**
 * HOW MANY AT ONCE: the account's call lines are the ceiling (`GET /v1/call-lines`), the
 * same lines the campaign page reports, so the step never offers a pace the account cannot
 * dial. A small ceiling is a row of buttons; a larger one a stepper.
 */
function PaceChoice({
  form,
  cap,
  capUnknown,
}: {
  form: CampaignFormState;
  /** The most the account can place at once; undefined while unknown. */
  cap: number | undefined;
  /** The lines could not be read: offer the campaign's own bound and say so. */
  capUnknown: boolean;
}) {
  const label = "Calls at the same time";
  const value = clampConcurrency(form.concurrency, cap);
  if (cap === undefined && !capUnknown) return <Skeleton rows={1} label="Checking how many calls your account can make at once" />;
  const limit = cap ?? CONCURRENCY_MAX;
  const hint =
    cap === undefined
      ? "We couldn't check your account's limit. It still applies."
      : `Up to ${cap} at once on your account. Need more? Ask us.`;
  if (limit <= 6) {
    return (
      <div>
        <p className={FIELD_LABEL} aria-hidden>
          {label}
        </p>
        <SegmentedControl
          label={label}
          className="mt-1.5"
          value={String(value)}
          options={Array.from({ length: limit }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))}
          onValueChange={(next) => form.setConcurrency(Number(next))}
        />
        <p className={FIELD_HINT}>{hint}</p>
      </div>
    );
  }
  return (
    <NumberField
      className="max-w-xs"
      label={label}
      hint={hint}
      value={value}
      onChange={(next) => form.setConcurrency(next ?? 1)}
      min={1}
      max={limit}
      unit="calls"
    />
  );
}

/**
 * THE CALLING RULES, all on show: the hours it may call in, how many calls run at once and
 * how often an unanswered person is tried again are this campaign's own (`calling_hours`,
 * `concurrency`, `retry_policy`); skipping the do-not-call list is the platform's and is
 * stated, not offered. Each was a row behind "Change"; a choice that is two or five taps
 * wide is quicker to make than to open.
 */
export function PaceFields({
  form,
  cap,
  capUnknown,
}: {
  form: CampaignFormState;
  cap: number | undefined;
  capUnknown: boolean;
}) {
  return (
    <div className="space-y-6">
      <FieldGroup title="Calling hours">
        <div>
          <p className={FIELD_LABEL} aria-hidden>
            When it may call
          </p>
          <SegmentedControl
            label="When it may call"
            className="mt-1.5"
            value={form.restrictHours ? "set" : "any"}
            options={HOURS.map((h) => ({ ...h }))}
            onValueChange={(next) => form.setRestrictHours(next === "set")}
          />
          <p className={FIELD_HINT}>Never before 9am or after 9pm IST. You can narrow it.</p>
        </div>
        {form.restrictHours && (
          <div className="settings-enter grid max-w-xs grid-cols-2 gap-3">
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
      </FieldGroup>

      <FieldGroup title="Pace">
        <PaceChoice form={form} cap={cap} capUnknown={capUnknown} />
        <p className="text-meta text-ink-muted">Lines are always kept free for people calling you.</p>
      </FieldGroup>

      <FieldGroup title="If nobody answers">
        <RetryChoice value={form.retry} onChange={form.setRetry} />
        <p className="text-body text-ink">{describeRetry(form.retry)}.</p>
      </FieldGroup>

      <p className="flex items-start gap-2 rounded-card bg-surface-muted px-3 py-2.5 text-meta text-ink">
        <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-success" />
        <span>Numbers on your do-not-call list are always skipped.</span>
      </p>
    </div>
  );
}
