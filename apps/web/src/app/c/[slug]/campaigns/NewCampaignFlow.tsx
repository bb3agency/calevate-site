"use client";

/**
 * NEW CAMPAIGN, AS FOUR SHORT STEPS in one column: what the calls are for, who to call,
 * when, then a review that reads like the campaign itself with one "Create campaign".
 *
 * One column, no running summary beside it. The summary rail used to repeat every field as
 * a label and "Not said" while the owner was still answering, which made the first screen
 * a wall of empty answers; the review step shows the whole campaign once there is one to
 * show. Settings that already have the right answer for almost everyone (the kind of call
 * and the number, the calling rules) are one sentence with Change beside them, so each step
 * asks only what the owner must decide. The same pattern as the broadcast builders Indian
 * owners already use (a template or goal first, then the audience, then send now or later).
 *
 * Each step is checked before Next, so a missing answer is named on the step that asks it.
 * Calls at once are offered only up to the account's call lines (D-773 pace, the lines
 * `GET /v1/call-lines` reports); retries are the client's choice; do-not-call skipping is
 * the platform's and is stated. The compliance check before LAUNCH is unchanged: creating
 * makes a draft, and the draft's own checklist (`LaunchGate`) still decides whether it can
 * dial.
 */

import { useId, useRef, useState, type ReactNode } from "react";

import { TEXT_ACTION } from "@/components/console/section";
import { WizardSteps } from "@/components/interior/wizard-steps";
import { ProblemNotice } from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate } from "@/lib/api/campaigns";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { briefProblem } from "./BriefFields";
import { ConsentProvenanceFields } from "./ConsentProvenance";
import { LeadPicker } from "./LeadPicker";
import { ContactEditor } from "./ContactEditor";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";
import { BasicsStep, CallingRules, StartChoice, type ListQuery } from "./NewCampaignSteps";
import { SummaryList, headline, summarize, type SummaryInput } from "./campaignSummary";

/**
 * The window every dial is held to (the dispatcher's 9am–9pm IST bound). A requested
 * window may only narrow it.
 */
export const PLATFORM_WINDOW = { start: "09:00", end: "21:00" } as const;

export function windowRefusal(start: string, end: string): string | null {
  if (start >= end) return "The hours must start before they end.";
  if (start < PLATFORM_WINDOW.start || end > PLATFORM_WINDOW.end) {
    return "Pick hours between 9am and 9pm IST.";
  }
  return null;
}

const STEPS = [
  {
    id: "purpose",
    label: "What it's for",
    heading: "What are these calls for?",
    lede: "Choose who calls, and what a good call should end with.",
  },
  { id: "people", label: "Who to call", heading: "Who should we call?", lede: "Add your list, pick from your leads, or both." },
  {
    id: "when",
    label: "When",
    heading: "When should we call?",
    lede: "Choose how it starts. The calling rules are already set.",
  },
  {
    id: "review",
    label: "Review",
    heading: "Check it, then create it",
    lede: "Saved as a draft. Nobody is called until you launch it.",
  },
] as const;

const REVIEW = STEPS.length - 1;

/** The step's own top: its question, and one line on what it decides. */
function StepHeader({ index, headingId }: { index: number; headingId: string }) {
  const step = STEPS[index]!;
  return (
    <div className="space-y-1">
      <h3 id={headingId} className="text-title text-ink">
        {step.heading}
      </h3>
      <p className="text-body text-ink-muted">{step.lede}</p>
    </div>
  );
}

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
  concurrency,
  concurrencyCap,
  capUnknown,
  assistant,
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
  /** The pace that will be sent: the request held to the account's lines. */
  concurrency: number;
  /** The most calls at once the account can place; undefined while unknown. */
  concurrencyCap: number | undefined;
  /** The account's lines could not be read. */
  capUnknown: boolean;
  /** The way to have the assistant fill the steps in, offered on the first step. */
  assistant: ReactNode;
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
  const headingId = useId();
  const markTried = (index: number) => setTried((seen) => new Set(seen).add(index));

  /** The first thing stopping step `index` being finished, in the order it asks. */
  function problemAt(index: number): string | null {
    if (index === 0) {
      if (!selectedAgentId) return "Choose the agent that makes these calls.";
      return briefProblem(form) ?? (form.name.trim().length < 2 ? "Give this campaign a name." : null);
    }
    if (index === 1) {
      if (counts.ready === 0 && !form.fromLeads) {
        return "Add at least one number, or pick from your leads.";
      }
      if (form.fromLeads && leadsMatching === undefined) return "One moment: counting your leads.";
      if (form.fromLeads && leadsMatching === 0 && counts.ready === 0) {
        return "No leads match. Change the filters.";
      }
      if (refusal) return refusal;
      if (!form.provenanceAnswered) {
        return "Answer both questions about your list.";
      }
      return null;
    }
    if (index === 2) {
      if (form.restrictHours && (!form.windowStart || !form.windowEnd)) return "Choose both a start and an end time.";
      if (form.restrictHours) {
        const window = windowRefusal(form.windowStart, form.windowEnd);
        if (window) return window;
      }
      if (schedule.startMode === "later" && !schedule.startIso) return "Choose the date and time it should start.";
      if (schedule.startMode === "weekly" && schedule.repeatDays.length === 0) {
        return "Choose at least one day to repeat on.";
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
    if (index < REVIEW) {
      markTried(index);
      return problemAt(index) === null;
    }
    for (let i = 0; i < REVIEW; i += 1) {
      if (problemAt(i)) {
        markTried(i);
        goTo(i);
        return false;
      }
    }
    return true;
  };

  const problem = tried.has(step) ? problemAt(step) : null;
  const summaryInput: SummaryInput = {
    form,
    schedule,
    agent: selectedAgent,
    numbers: numbers.data,
    leadsMatching,
    concurrency,
  };

  const content: ReactNode[] = [
    <div key="purpose" className="space-y-8">
      <AssistantOffer>{assistant}</AssistantOffer>
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
    </div>,
    <div key="people" className="space-y-8">
      <ContactEditor
        entries={form.contacts}
        onChange={form.setContacts}
        agentLanguage={selectedAgent?.language_primary}
      />
      <LeadsChoice form={form} />
      <ConsentPanel form={form} />
    </div>,
    <div key="when" className="space-y-8">
      <StartChoice schedule={schedule} />
      <CallingRules form={form} cap={concurrencyCap} capUnknown={capUnknown} concurrency={concurrency} />
    </div>,
    <ReviewCard key="review" input={summaryInput} onEdit={goTo} />,
  ];

  const nextLabel = step < REVIEW ? `Next: ${STEPS[step + 1]!.label.toLowerCase()}` : "Next";

  return (
    // A `div role="form"` rather than a `<form>`: the leads picker carries the Leads
    // screen's own small forms (a detail filter, naming a saved view), and a form may not
    // sit inside another. Nothing here submits; WizardSteps' buttons drive every step.
    <div ref={formRef} role="form" aria-label="New campaign" className="min-w-0 max-w-3xl scroll-mt-6">
      <WizardSteps
        steps={STEPS.map((s, index) => ({
          id: s.id,
          label: s.label,
          content:
            index === step ? (
              <section
                aria-labelledby={headingId}
                className="space-y-7 sm:rounded-card sm:border sm:border-line sm:bg-surface sm:p-7 sm:shadow-card"
              >
                <StepHeader index={index} headingId={headingId} />
                {content[index]}
                {problem ? (
                  <p role="alert" className="text-meta text-danger">
                    {problem}
                  </p>
                ) : null}
                {index === REVIEW && createError != null ? <ProblemNotice error={createError} /> : null}
              </section>
            ) : null,
        }))}
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
        nextLabel={nextLabel}
        finishLabel="Create campaign"
        finishing={creating}
        finishingLabel="Creating…"
        advanceDisabled={step === REVIEW && !canWrite}
        extraActions={
          <button type="button" className={TEXT_ACTION} onClick={onCancel}>
            Cancel
          </button>
        }
      />
    </div>
  );
}

/** The assistant as the other way in, one quiet line above the first question. */
function AssistantOffer({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 rounded-card border border-dashed border-line px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="min-w-0 text-meta text-ink-muted">
        Rather say it in a sentence? {ASSISTANT_NAME} can fill this in.
      </p>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

/**
 * THE REVIEW, shaped like the campaign it creates: its name, one sentence of what will
 * happen, then each part with Change. Its sentences are the ones the steps show
 * (`campaignSummary.summarize`), so the review cannot disagree with what is sent.
 */
function ReviewCard({ input, onEdit }: { input: SummaryInput; onEdit: (step: number) => void }) {
  const groups = summarize(input);
  return (
    <div className="space-y-5">
      <div className="rounded-card bg-brand-soft/60 px-4 py-4 sm:px-5">
        <p className="break-words text-heading text-ink">{input.form.name.trim()}</p>
        <p aria-live="polite" className="mt-1 text-body text-ink-muted">
          {headline(input)}
        </p>
        {input.agent && !canDialOut(input.agent) ? (
          <p className="mt-2 text-meta text-ink">
            This agent can&rsquo;t call out yet. Launch waits until it can.
          </p>
        ) : null}
      </div>
      {groups.map((group) => (
        <div key={group.step} className="border-t border-line pt-5">
          <SummaryList group={group} onEdit={() => onEdit(group.step)} />
        </div>
      ))}
    </div>
  );
}

/**
 * "From your leads" on the create page. The lens is kept on the form and sent with the
 * count shown here once the draft exists (`POST …/contacts/from-leads`), beside any pasted
 * list.
 */
function LeadsChoice({ form }: { form: CampaignFormState }) {
  const hintId = useId();
  return (
    <div
      className={`rounded-card border transition-colors duration-(--duration-fast) ${
        form.fromLeads ? "border-brand bg-brand/[0.03]" : "border-line"
      }`}
    >
      <label className="flex cursor-pointer items-start gap-3 px-4 py-3.5 touch:min-h-11">
        <input
          type="checkbox"
          checked={form.fromLeads}
          onChange={(e) => form.setFromLeads(e.target.checked)}
          aria-describedby={hintId}
          className="mt-0.5 h-4 w-4 shrink-0 rounded border-line accent-brand"
        />
        <span className="min-w-0">
          <span className="block text-body font-medium text-ink">Also call people from your leads</span>
          {/* Hidden from the name, read as the description: the checkbox keeps its short
              name and still says how the leads are chosen. */}
          <span id={hintId} aria-hidden className="block text-meta text-ink-muted">
            Filter them the way you do on your Leads page.
          </span>
        </span>
      </label>
      {form.fromLeads && (
        <div className="settings-enter border-t border-line px-4 pb-4 pt-4">
          <LeadPicker f={form.leads} />
        </div>
      )}
    </div>
  );
}

/**
 * Where the list came from: an audited statement, so it sits in its own panel after the
 * people it describes, apart from the list tools, and is never pre-answered.
 */
function ConsentPanel({ form }: { form: CampaignFormState }) {
  return (
    <div className="rounded-card bg-surface-muted p-4 sm:p-5">
      <ConsentProvenanceFields
        idPrefix="new"
        source={form.consentSource}
        collectedAt={form.consentDate}
        onSource={form.setConsentSource}
        onCollectedAt={form.setConsentDate}
      />
    </div>
  );
}
