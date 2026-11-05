"use client";

import Link from "next/link";
import { CalendarClock, CalendarDays, Hand, ShieldCheck } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { NumberField } from "@/components/arc/number-field";
import { ChoiceCards } from "@/components/console/choiceCards";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, FIELD_HINT, FIELD_LABEL, SECONDARY_BUTTON_SM, Skeleton, formatPhone } from "@/components/ui";
import { LANGUAGE_NAMES, canDialOut } from "@/lib/agentState";
import { lookup } from "@/lib/lookup";
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

/**
 * SETTINGS THAT ALREADY HAVE AN ANSWER, said as one sentence with "Change" beside it. The
 * owner reads what will happen and moves on; the controls open only for someone who wants
 * a different answer. Nothing that changes the outcome is hidden: the sentence states every
 * value the controls hold.
 */
export function SettledSettings({
  title,
  summary,
  children,
  defaultOpen = false,
}: {
  title: string;
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  return (
    <section aria-label={title} className="rounded-card bg-surface-muted px-4 py-3.5 sm:px-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h4 className="text-body font-semibold text-ink">{title}</h4>
          <p aria-live="polite" className="mt-0.5 text-meta text-ink-muted">
            {summary}
          </p>
        </div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          aria-label={open ? `Close ${title.toLowerCase()}` : `Change ${title.toLowerCase()}`}
          onClick={() => setOpen(!open)}
          className={`${TEXT_ACTION} shrink-0 touch:min-h-11`}
        >
          {open ? "Done" : "Change"}
        </button>
      </div>
      {open && (
        <div id={panelId} className="settings-enter mt-4 space-y-5 border-t border-line pt-4">
          {children}
        </div>
      )}
    </section>
  );
}

/** Whether the agent can place these calls, in the owner's words. */
function agentReadiness(agent: Agent): string {
  if (canDialOut(agent)) return "Ready to call";
  if (agent.direction === "inbound") return "Answers calls only";
  return "Not calling yet";
}

/**
 * WHO MAKES THE CALLS, as the agents themselves rather than a dropdown: an owner knows
 * their agent by name, and a card can say whether it is ready without the "not able to
 * call out yet" suffix a select option had to carry.
 */
function AgentChoice({
  form,
  agentOptions,
  selectedAgentId,
  selectedAgent,
}: {
  form: CampaignFormState;
  agentOptions: Agent[];
  selectedAgentId: string;
  selectedAgent: Agent | undefined;
}) {
  const { session, href } = useClientRealm();
  const options = agentOptions.map((agent) => ({
    value: agent.id,
    label: agent.name,
    hint: (
      <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
        <span>{lookup(LANGUAGE_NAMES, agent.language_primary) ?? agent.language_primary}</span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${canDialOut(agent) ? "bg-success" : "bg-warn"}`} />
          {agentReadiness(agent)}
        </span>
      </span>
    ),
  }));
  return (
    <div className="space-y-2.5">
      <ChoiceCards
        legend="Which agent makes these calls"
        legendClassName="block text-body font-medium text-ink"
        name="campaign-agent"
        value={selectedAgentId}
        options={options}
        onChange={form.setAgentId}
        columns="sm:grid-cols-2"
      />
      {selectedAgent && !canDialOut(selectedAgent) ? (
        <p className="text-meta text-ink-muted">
          Build it now. It calls once this agent can call out.{" "}
          <Link href={href(`/c/${session.orgSlug}/agents/${selectedAgent.id}`)} className={TEXT_ACTION}>
            Open {selectedAgent.name}
          </Link>
        </p>
      ) : null}
    </div>
  );
}

/**
 * THE NAME, last on the step because it is made from the goal: an owner who picks "Booked
 * a visit" gets "Booked a visit, 5 Nov" and may keep it. Before there is a goal the
 * business's own example (D-827, written in the account's language) is offered as one tap,
 * not as greyed placeholder text that reads like an answer already given.
 */
function NameField({ form }: { form: CampaignFormState }) {
  const id = useId();
  const eg = useVerticalExamples();
  const example = eg.campaignName.trim();
  const offer = form.name.trim() === "" && example !== "" ? example : null;
  return (
    <div>
      <label htmlFor={id} className="block text-body font-medium text-ink">
        Name
      </label>
      <span id={`${id}-hint`} className="mt-0.5 block text-meta text-ink-muted">
        {form.nameFollowsGoal && form.name.trim() !== ""
          ? "Made from the goal. Type to change it."
          : "Only you see it, in your list of campaigns."}
      </span>
      <input
        id={id}
        value={form.name}
        onChange={(e) => form.setName(e.target.value)}
        maxLength={120}
        aria-describedby={`${id}-hint`}
        className={`${FIELD} mt-2`}
      />
      {offer && (
        <div className="mt-2.5 flex min-w-0 items-center gap-2">
          <span aria-hidden className="shrink-0 text-meta text-ink-muted">
            Or use:
          </span>
          <button
            type="button"
            onClick={() => form.setName(offer)}
            aria-label={`Use the name ${offer}`}
            className="press min-w-0 truncate rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-muted hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:min-h-11"
          >
            {offer}
          </button>
        </div>
      )}
    </div>
  );
}

/** "Service calls, from the agent's own number.": the placement as one sentence. */
export function placementWords(
  form: Pick<CampaignFormState, "classification" | "numberId" | "templateId">,
  numbers: CampaignNumber[] | undefined,
): string {
  const kind = form.classification === "promotional" ? "Promotional calls" : "Service calls";
  const number = campaignNumbers(numbers).find((n) => n.id === form.numberId);
  const from = number ? `from ${formatPhone(number.e164)}` : "from the agent's own number";
  return `${kind}, ${from}${form.templateId ? ", with your registered template" : ""}.`;
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
 * STEP 1, WHAT THE CALLS ARE FOR, in the order an owner thinks it: who calls, why, what a
 * good call ends with, then a name made from that. How the calls go out (the kind of call,
 * the number, a registered DLT template) has the right answer already for almost everyone,
 * so it is one sentence with Change beside it. A template is optional since D-692 (outbound
 * needs verified KYC and the no-cold-calls pledge); it is still offered for a client who
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
  placementOpen = false,
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
  /** Open on the edit page, where the owner came to change something. */
  placementOpen?: boolean;
}) {
  const usable = campaignNumbers(numbers.data);
  const { session, href } = useClientRealm();
  const registration = usePeRegistration(session);
  const classifications = offeredClassifications(
    registration.data?.calevate_tm_active === true,
    form.classification,
  );
  return (
    <div className="space-y-8">
      {hasNoAgents && (
        <div className="space-y-3 rounded-card border border-dashed border-line p-4">
          <p className="text-body text-ink">No agent is set up yet.</p>
          <Link href={href(`/c/${session.orgSlug}/agents`)} className={SECONDARY_BUTTON_SM}>
            Create an agent
          </Link>
        </div>
      )}
      {/* Only from a list the server sent: an empty picker over a read in flight or failed
          would read as "you have no agent". */}
      {Boolean(agents.data) && agentOptions.length > 0 && (
        <AgentChoice
          form={form}
          agentOptions={agentOptions}
          selectedAgentId={selectedAgentId}
          selectedAgent={selectedAgent}
        />
      )}
      {!agents.data && !hasNoAgents && <Skeleton rows={2} label="Loading your agents" />}

      <BriefFields form={form} agentId={selectedAgentId} />

      <NameField form={form} />

      <SettledSettings
        title="How the calls go out"
        summary={placementWords(form, numbers.data)}
        defaultOpen={placementOpen}
      >
        {/* The category decides which number series may dial (DATA-MODEL §6). */}
        <ShortChoice
          label="What kind of calls are these?"
          value={form.classification}
          options={classifications}
          onChange={form.setClassification}
        />
        <label className="block max-w-md">
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
          <label className="block max-w-md">
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
              <span className={FIELD_HINT}>None registered. You don&rsquo;t need one to call.</span>
            )}
          </label>
        )}
      </SettledSettings>
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
  showDnc = true,
}: {
  form: CampaignFormState;
  cap: number | undefined;
  capUnknown: boolean;
  /** Off where the note already sits beside the summary of these rules. */
  showDnc?: boolean;
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

      {showDnc && <DncNote />}
    </div>
  );
}

/** Do-not-call skipping is the platform's on every dial, so it is stated, never offered. */
function DncNote() {
  return (
    <p className="flex items-start gap-2 text-meta text-ink-muted">
      <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-success" />
      <span>Numbers on your do-not-call list are always skipped.</span>
    </p>
  );
}

/** "Between 9am and 9pm IST, up to 2 at a time. 3 tries, 30 min then 2 hours apart." */
export function rulesWords(
  form: Pick<CampaignFormState, "restrictHours" | "windowStart" | "windowEnd" | "retry">,
  concurrency: number,
): string {
  const hours = form.restrictHours
    ? `Between ${form.windowStart || "…"} and ${form.windowEnd || "…"} IST`
    : "Between 9am and 9pm IST";
  return `${hours}, up to ${concurrency} at a time. ${describeRetry(form.retry)}.`;
}

/**
 * THE CALLING RULES on the create page: already answered (the platform's hours, the
 * account's lines, three tries), so they read as one sentence with Change, and open to the
 * same controls the edit page shows.
 */
export function CallingRules({
  form,
  cap,
  capUnknown,
  concurrency,
}: {
  form: CampaignFormState;
  cap: number | undefined;
  capUnknown: boolean;
  /** The pace that will be sent, already held to the account's lines. */
  concurrency: number;
}) {
  return (
    <div className="space-y-3">
      <SettledSettings title="Calling rules" summary={rulesWords(form, concurrency)}>
        <PaceFields form={form} cap={cap} capUnknown={capUnknown} showDnc={false} />
      </SettledSettings>
      <DncNote />
    </div>
  );
}
