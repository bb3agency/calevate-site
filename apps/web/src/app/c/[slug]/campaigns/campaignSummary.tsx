"use client";

import { Pencil } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { formatCount, formatPhone } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber } from "@/lib/api/campaigns";
import { lookup } from "@/lib/lookup";

import { briefValue } from "./BriefFields";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";
import { CLASSIFICATIONS, CONSENT_SOURCES } from "./choices";
import { campaignNumbers, describeHours, describeRetry } from "./NewCampaignSteps";
import { describeRepeat } from "./scheduleCopy";

/**
 * THE CAMPAIGN AS IT STANDS, worked out once and read in two places: the summary beside
 * the steps, and the review before Create. One derivation, so the rail and the review can
 * never disagree about what will be created.
 */

export interface SummaryRow {
  label: string;
  value: string;
  /** False while the answer is still missing: drawn faint, never as if chosen. */
  set: boolean;
}

export interface SummaryGroup {
  /** The step that asks these, for the jump back to it. */
  step: number;
  title: string;
  rows: SummaryRow[];
}

export interface SummaryInput {
  form: CampaignFormState;
  schedule: ScheduleFormState;
  agent: Agent | undefined;
  numbers: CampaignNumber[] | undefined;
  /** How many leads the picker matches; undefined while counted or when not picking. */
  leadsMatching: number | undefined;
  /** The pace that will be sent, already held to the account's lines. */
  concurrency: number;
}

const plural = (n: number, one: string, many: string) => `${formatCount(n)} ${n === 1 ? one : many}`;

export function startWords(schedule: ScheduleFormState): string {
  if (schedule.startMode === "later") {
    return schedule.startDate ? `Once, ${schedule.startDate} at ${schedule.startTime} IST` : "Once, at a time not chosen yet";
  }
  if (schedule.startMode === "weekly") {
    return schedule.repeatDays.length > 0
      ? describeRepeat({ days: schedule.repeatDays, at: schedule.repeatTime })
      : "Every week, days not chosen yet";
  }
  return "When you launch it";
}

function peopleWords({ form, leadsMatching }: Pick<SummaryInput, "form" | "leadsMatching">): SummaryRow {
  const ready = form.checked.counts.ready;
  const leads = form.fromLeads ? leadsMatching : undefined;
  if (ready === 0 && !form.fromLeads) return { label: "People", value: "None added yet", set: false };
  const numbers = `${plural(ready, "number", "numbers")} ready`;
  if (!form.fromLeads) return { label: "People", value: numbers, set: true };
  if (leads === undefined) return { label: "People", value: `${numbers}, leads being counted`, set: ready > 0 };
  return { label: "People", value: `${numbers}, plus ${plural(leads, "lead", "leads")}`, set: ready + leads > 0 };
}

export function summarize(input: SummaryInput): SummaryGroup[] {
  const { form, schedule, agent, numbers, concurrency } = input;
  const number = campaignNumbers(numbers).find((n) => n.id === form.numberId);
  const purpose = briefValue(form.purpose);
  const goal = briefValue(form.goal);
  const source = lookup(Object.fromEntries(CONSENT_SOURCES.map((c) => [c.value, c.label])), form.consentSource);
  return [
    {
      step: 0,
      title: "Basics",
      rows: [
        { label: "Name", value: form.name.trim() || "Not named yet", set: form.name.trim() !== "" },
        { label: "Agent", value: agent?.name ?? "Not chosen", set: Boolean(agent) },
        { label: "Why you are calling", value: purpose ?? "Not said", set: purpose !== null },
        { label: "Goal", value: goal ?? "Not said", set: goal !== null },
        {
          label: "Kind of call",
          value: CLASSIFICATIONS.find((c) => c.value === form.classification)?.label ?? form.classification,
          set: true,
        },
        { label: "Calling from", value: number ? formatPhone(number.e164) : "The agent's own number", set: true },
      ],
    },
    {
      step: 1,
      title: "People",
      rows: [
        peopleWords(input),
        { label: "Where the list came from", value: source ?? "Not answered", set: source !== undefined },
      ],
    },
    {
      step: 2,
      title: "Timing",
      rows: [
        { label: "Starts", value: startWords(schedule), set: true },
        { label: "Calling hours", value: describeHours(form), set: true },
        { label: "Calls at the same time", value: `Up to ${concurrency}`, set: true },
        { label: "If nobody answers", value: describeRetry(form.retry), set: true },
      ],
    },
  ];
}

/**
 * The campaign in one sentence: "Front desk will call 12 people when you launch it." With
 * leads included it says "up to", because a lead already on the list is not added twice.
 */
export function headline({ form, schedule, agent, leadsMatching }: SummaryInput): string {
  const who = agent?.name ?? "Your agent";
  const ready = form.checked.counts.ready;
  const leads = form.fromLeads ? (leadsMatching ?? 0) : 0;
  const total = ready + leads;
  const people = total === 0 ? "nobody yet" : `${form.fromLeads ? "up to " : ""}${plural(total, "person", "people")}`;
  const when =
    schedule.startMode === "review"
      ? "when you launch it"
      : schedule.startMode === "later"
        ? schedule.startDate
          ? `on ${schedule.startDate} at ${schedule.startTime} IST`
          : "at a time you pick"
        : schedule.repeatDays.length > 0
          ? describeRepeat({ days: schedule.repeatDays, at: schedule.repeatTime })
          : "every week";
  return `${who} will call ${people} ${when}.`;
}

/**
 * One group of the summary as a definition list. `onEdit` adds the jump back to the step
 * that asks it; `compact` is the rail's narrower, label-over-value form.
 */
export function SummaryList({
  group,
  onEdit,
  compact = false,
}: {
  group: SummaryGroup;
  onEdit?: () => void;
  compact?: boolean;
}) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h4 className={compact ? "text-meta font-semibold text-ink-muted" : "text-body font-semibold text-ink"}>
          {group.title}
        </h4>
        {onEdit ? (
          <button
            type="button"
            onClick={onEdit}
            aria-label={`Change ${group.title.toLowerCase()}`}
            className={`${TEXT_ACTION} inline-flex items-center gap-1`}
          >
            <Pencil aria-hidden className="h-3 w-3" />
            Change
          </button>
        ) : null}
      </div>
      <dl className={compact ? "mt-2 space-y-2" : "mt-3 divide-y divide-line"}>
        {group.rows.map((row) => (
          <div
            key={row.label}
            className={compact ? "min-w-0" : "grid grid-cols-1 gap-x-4 gap-y-0.5 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)]"}
          >
            <dt className="text-meta text-ink-muted">{row.label}</dt>
            <dd className={`min-w-0 break-words text-body ${row.set ? "text-ink" : "text-ink-faint"}`}>{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
