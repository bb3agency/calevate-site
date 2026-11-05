"use client";

import { Pencil } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { formatCount } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber } from "@/lib/api/campaigns";
import { lookup } from "@/lib/lookup";

import { briefValue } from "./BriefFields";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";
import { CONSENT_SOURCES } from "./choices";
import { placementWords, rulesWords } from "./NewCampaignSteps";
import { describeRepeat } from "./scheduleCopy";

/**
 * THE CAMPAIGN AS IT STANDS, worked out once from the form: the review before Create reads
 * it, and its sentences are the ones the steps show beside "Change", so the review can never
 * disagree with what will be created.
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
  const purpose = briefValue(form.purpose);
  const goal = briefValue(form.goal);
  const source = lookup(Object.fromEntries(CONSENT_SOURCES.map((c) => [c.value, c.label])), form.consentSource);
  return [
    {
      step: 0,
      title: "What it's for",
      rows: [
        { label: "Who calls", value: agent?.name ?? "Not chosen", set: Boolean(agent) },
        { label: "Why you are calling", value: purpose ?? "Not said", set: purpose !== null },
        { label: "A good call ends with", value: goal ?? "Not said", set: goal !== null },
        { label: "How the calls go out", value: placementWords(form, numbers), set: true },
      ],
    },
    {
      step: 1,
      title: "Who to call",
      rows: [
        peopleWords(input),
        { label: "Where the list came from", value: source ?? "Not answered", set: source !== undefined },
      ],
    },
    {
      step: 2,
      title: "When",
      rows: [
        { label: "Starts", value: startWords(schedule), set: true },
        { label: "Calling rules", value: rulesWords(form, concurrency), set: true },
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

/** One group of the summary as a definition list; `onEdit` adds the jump back to its step. */
export function SummaryList({ group, onEdit }: { group: SummaryGroup; onEdit?: () => void }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-body font-semibold text-ink">{group.title}</h4>
        {onEdit ? (
          <button
            type="button"
            onClick={onEdit}
            aria-label={`Change ${group.title.toLowerCase()}`}
            className={`${TEXT_ACTION} inline-flex items-center gap-1 touch:min-h-11`}
          >
            <Pencil aria-hidden className="h-3 w-3" />
            Change
          </button>
        ) : null}
      </div>
      <dl className="mt-2 space-y-2.5 sm:space-y-1.5">
        {group.rows.map((row) => (
          <div key={row.label} className="grid grid-cols-1 gap-x-4 sm:grid-cols-[11rem_minmax(0,1fr)]">
            <dt className="text-meta text-ink-muted sm:pt-px">{row.label}</dt>
            <dd className={`min-w-0 break-words text-body ${row.set ? "text-ink" : "text-ink-faint"}`}>{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
