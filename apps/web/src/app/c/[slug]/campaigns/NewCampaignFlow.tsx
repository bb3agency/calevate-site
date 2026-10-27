"use client";

/**
 * NEW CAMPAIGN, AS FOUR SHORT STEPS: the basics, who to call, when to call, then a review
 * of the whole campaign with Change beside every part and one "Create campaign".
 *
 * It was one 2,000-pixel form: three sets of choice cards, a file drop, a consent
 * question and four settings rows in one column, read on a phone. Steps let an owner
 * finish one question at a time, and each step is checked before Next, so a missing
 * answer is named on the step that asks it rather than at the bottom of the page. The
 * review keeps what the one-page form was for: the whole campaign is seen before it is
 * created, and nothing hides behind a Next that has not been shown again.
 *
 * Calling hours and calls at once are pre-set and shown as rows with Change; retries are
 * the client's choice (D-773); do-not-call skipping is the platform's and is stated. The
 * compliance check before LAUNCH is unchanged: creating makes a draft, and the draft's
 * own checklist (`LaunchGate`) still decides whether it can dial.
 */

import { useRef, useState, type ReactNode } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { WizardSteps } from "@/components/interior/wizard-steps";
import { ProblemNotice, formatCount, formatPhone } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate } from "@/lib/api/campaigns";
import { lookup } from "@/lib/lookup";

import { ConsentProvenanceFields } from "./ConsentProvenance";
import { LeadPicker } from "./LeadPicker";
import { ContactEditor } from "./ContactEditor";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";
import { CLASSIFICATIONS, CONSENT_SOURCES } from "./choices";
import {
  BasicsStep,
  PaceRows,
  StartChoice,
  campaignNumbers,
  describeRetry,
  type ListQuery,
} from "./NewCampaignSteps";
import { describeRepeat } from "./scheduleCopy";

/**
 * The window every dial is held to (the dispatcher's 9am–9pm IST bound). A requested
 * window may only narrow it.
 */
export const PLATFORM_WINDOW = { start: "09:00", end: "21:00" } as const;

export function windowRefusal(start: string, end: string): string | null {
  if (start >= end) return "The calling window has to start before it ends.";
  if (start < PLATFORM_WINDOW.start || end > PLATFORM_WINDOW.end) {
    return "Calls can only go out between 9am and 9pm IST. Choose a window inside those hours.";
  }
  return null;
}

const STEP_NAMES = ["The basics", "Who to call", "When to call", "Review"] as const;

export function NewCampaignFlow({
  form,
  schedule,
  agents,
  agentOptions,
  selectedAgentId,
  selectedAgent,
  hasNoAgents,
  numbers,
  templates,
  creating,
  createError,
  canWrite,
  onSubmit,
  onCancel,
  leadsMatching,
}: {
  form: CampaignFormState;
  schedule: ScheduleFormState;
  agents: { data: Agent[] | undefined };
  agentOptions: Agent[];
  selectedAgentId: string;
  selectedAgent: Agent | undefined;
  hasNoAgents: boolean;
  numbers: ListQuery<CampaignNumber>;
  templates: ListQuery<DltTemplate>;
  /** The draft is being created, or what it carries is being sent. */
  creating: boolean;
  /** Why creating the draft was refused, shown on the review step. */
  createError: unknown;
  canWrite: boolean;
  onSubmit: () => void;
  onCancel: () => void;
  /** How many leads the picker's filters match; undefined while they are counted. */
  leadsMatching: number | undefined;
}) {
  const { counts, refusal } = form.checked;
  const [step, setStep] = useState(0);
  // Which steps the person has tried to leave. A step's problem shows only after that,
  // and is worked out on every render, so it goes away the moment it is fixed.
  const [tried, setTried] = useState<ReadonlySet<number>>(() => new Set());
  const formRef = useRef<HTMLDivElement>(null);
  const markTried = (index: number) => setTried((seen) => new Set(seen).add(index));

  /** The first thing stopping step `index` being finished, in the order it asks. */
  function problemAt(index: number): string | null {
    if (index === 0) {
      if (form.name.trim().length < 2) return "Give this campaign a name.";
      if (!selectedAgentId) return "Choose the agent that makes these calls.";
      return null;
    }
    if (index === 1) {
      if (counts.ready === 0 && !form.fromLeads) {
        return "Add at least one number we can call, or choose people from your leads.";
      }
      if (form.fromLeads && leadsMatching === undefined) return "Wait a moment while your leads are counted.";
      if (form.fromLeads && leadsMatching === 0 && counts.ready === 0) {
        return "No leads match these filters. Change them, or add numbers above.";
      }
      if (refusal) return refusal;
      if (!form.provenanceAnswered) {
        return "Answer both questions about your list — a campaign without them can't be launched.";
      }
      return null;
    }
    if (index === 2) {
      if (form.concurrency < 1 || form.concurrency > 10) return "Choose between 1 and 10 calls at the same time.";
      if (form.restrictHours && (!form.windowStart || !form.windowEnd)) return "Choose both a start and an end time.";
      if (form.restrictHours) {
        const window = windowRefusal(form.windowStart, form.windowEnd);
        if (window) return window;
      }
      if (schedule.startMode === "later" && !schedule.startIso) return "Choose the date and time it should start.";
      if (schedule.startMode === "weekly" && schedule.repeatDays.length === 0) {
        return "Choose at least one day for this campaign to repeat on.";
      }
    }
    return null;
  }

  /** A new step starts at its top: on a phone Next sits a long way below it. */
  const goTo = (index: number) => {
    setStep(index);
    const top = formRef.current?.getBoundingClientRect().top;
    if (top !== undefined && top < 0) formRef.current?.scrollIntoView({ block: "start" });
  };

  /** Next checks this step; Create checks every step and opens the first one short. */
  const canAdvance = (index: number) => {
    if (index < STEP_NAMES.length - 1) {
      markTried(index);
      return problemAt(index) === null;
    }
    for (let i = 0; i < STEP_NAMES.length - 1; i += 1) {
      if (problemAt(i)) {
        markTried(i);
        goTo(i);
        return false;
      }
    }
    return true;
  };

  const problem = tried.has(step) ? problemAt(step) : null;
  const usableNumber = campaignNumbers(numbers.data, selectedAgentId).find((n) => n.id === form.numberId);

  const steps = [
    {
      id: "basics",
      label: STEP_NAMES[0],
      content: (
        <Section title="The basics" description="Name it, choose who calls, and what kind of call it is.">
          <BasicsStep
            form={form}
            agents={agents}
            agentOptions={agentOptions}
            selectedAgentId={selectedAgentId}
            selectedAgent={selectedAgent}
            hasNoAgents={hasNoAgents}
            numbers={numbers}
            templates={templates}
          />
        </Section>
      ),
    },
    {
      id: "people",
      label: STEP_NAMES[1],
      content: (
        <Section
          title="Who should we call?"
          description="Paste, import or add your contacts, then tell us where the list came from."
        >
          <div className="space-y-6">
            <ContactEditor
              entries={form.contacts}
              onChange={form.setContacts}
              agentLanguage={selectedAgent?.language_primary}
            />
            <LeadsChoice form={form} />
            <ConsentProvenanceFields
              idPrefix="new"
              source={form.consentSource}
              collectedAt={form.consentDate}
              onSource={form.setConsentSource}
              onCollectedAt={form.setConsentDate}
            />
          </div>
        </Section>
      ),
    },
    {
      id: "when",
      label: STEP_NAMES[2],
      content: (
        <Section title="When should we call?">
          <div className="space-y-6">
            <StartChoice schedule={schedule} />
            <PaceRows form={form} />
          </div>
        </Section>
      ),
    },
    {
      id: "review",
      label: STEP_NAMES[3],
      content: (
        <Section
          title="Check it, then create it"
          description="It is created as a draft. Nothing is called until you launch it from its checklist."
        >
          <SettingRows className="border-y border-line">
            <ReviewRow label="Name" value={form.name.trim() || "Not named yet"} onChange={() => goTo(0)} />
            <ReviewRow label="Agent" value={selectedAgent?.name ?? "Not chosen"} onChange={() => goTo(0)} />
            <ReviewRow
              label="Kind of call"
              value={CLASSIFICATIONS.find((c) => c.value === form.classification)?.label ?? form.classification}
              onChange={() => goTo(0)}
            />
            <ReviewRow
              label="Calling from"
              value={usableNumber ? formatPhone(usableNumber.e164) : "The agent's own number"}
              onChange={() => goTo(0)}
            />
            <ReviewRow
              label="People"
              value={
                <>
                  {formatCount(counts.ready)} {counts.ready === 1 ? "number" : "numbers"} ready
                  {form.fromLeads && leadsMatching !== undefined
                    ? `, plus ${formatCount(leadsMatching)} ${leadsMatching === 1 ? "lead" : "leads"}`
                    : ""}
                </>
              }
              onChange={() => goTo(1)}
            />
            <ReviewRow
              label="Where the list came from"
              value={lookup(Object.fromEntries(CONSENT_SOURCES.map((c) => [c.value, c.label])), form.consentSource) ?? "Not answered"}
              onChange={() => goTo(1)}
            />
            <ReviewRow label="Starts" value={startWords(schedule)} onChange={() => goTo(2)} />
            <ReviewRow
              label="Calling hours"
              value={form.restrictHours ? `${form.windowStart || "…"} – ${form.windowEnd || "…"} IST` : "9am – 9pm IST"}
              onChange={() => goTo(2)}
            />
            <ReviewRow label="Calls at the same time" value={String(form.concurrency)} onChange={() => goTo(2)} />
            <ReviewRow label="No answer, busy or voicemail" value={describeRetry(form.retry)} onChange={() => goTo(2)} />
          </SettingRows>
        </Section>
      ),
    },
  ];

  return (
    // A `div role="form"` rather than a `<form>`: the leads picker carries the Leads
    // screen's own small forms (a detail filter, naming a saved view), and a form may not
    // sit inside another. Nothing here submits; WizardSteps' buttons drive every step.
    <div ref={formRef} role="form" aria-label="New campaign" className="max-w-2xl">
      <WizardSteps
        steps={steps.map((s, index) =>
          index === step
            ? {
                ...s,
                content: (
                  <div className="space-y-6">
                    {s.content}
                    {problem ? (
                      <p role="alert" className="text-body text-danger">
                        {problem}
                      </p>
                    ) : null}
                    {index === STEP_NAMES.length - 1 && createError != null ? <ProblemNotice error={createError} /> : null}
                  </div>
                ),
              }
            : s,
        )}
        index={step}
        onIndexChange={goTo}
        canAdvance={canAdvance}
        onComplete={() => {
          if (canWrite) onSubmit();
        }}
        height="auto"
        framed={false}
        showCurrentLabel={false}
        label="New campaign steps"
        nextLabel="Next"
        finishLabel="Create campaign"
        finishing={creating}
        finishingLabel="Creating…"
        advanceDisabled={step === STEP_NAMES.length - 1 && !canWrite}
        extraActions={
          <button type="button" className={TEXT_ACTION} onClick={onCancel}>
            Cancel
          </button>
        }
      />
    </div>
  );
}

function startWords(schedule: ScheduleFormState): string {
  if (schedule.startMode === "later") {
    return schedule.startDate ? `Once, ${schedule.startDate} at ${schedule.startTime} IST` : "Once, at a time not chosen yet";
  }
  if (schedule.startMode === "weekly") return describeRepeat({ days: schedule.repeatDays, at: schedule.repeatTime });
  return "When you launch it";
}

function ReviewRow({ label, value, onChange }: { label: string; value: ReactNode; onChange: () => void }) {
  return (
    <SettingRow
      label={label}
      value={value}
      action={
        <button type="button" className={TEXT_ACTION} onClick={onChange} aria-label={`Change ${label.toLowerCase()}`}>
          Change
        </button>
      }
    />
  );
}

/**
 * "From your leads" on the create page. The lens is kept on the form and sent with the
 * count shown here once the draft exists (`POST …/contacts/from-leads`), beside any pasted
 * list.
 */
function LeadsChoice({ form }: { form: CampaignFormState }) {
  return (
    <div className="space-y-3 border-t border-line pt-4">
      <label className="flex items-center gap-2 touch:min-h-11">
        <input
          type="checkbox"
          checked={form.fromLeads}
          onChange={(e) => form.setFromLeads(e.target.checked)}
          className="h-4 w-4 rounded border-line accent-brand"
        />
        <span className="text-body text-ink">Also call people from your leads</span>
      </label>
      {form.fromLeads && <LeadPicker f={form.leads} />}
    </div>
  );
}
