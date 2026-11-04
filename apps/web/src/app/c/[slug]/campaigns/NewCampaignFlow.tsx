"use client";

/**
 * NEW CAMPAIGN, AS FOUR SHORT STEPS beside a summary of the campaign as it stands: the
 * basics, who to call, when to call, then a review with Change beside every group and one
 * "Create campaign".
 *
 * Steps let an owner finish one question at a time, and each step is checked before Next,
 * so a missing answer is named on the step that asks it rather than at the bottom of the
 * page. The summary beside them answers "what have I set so far?" without stepping back;
 * the review shows the same summary full width, so the whole campaign is seen before it
 * is created. Both read `campaignSummary.summarize`, so they cannot disagree.
 *
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
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate } from "@/lib/api/campaigns";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { briefProblem } from "./BriefFields";
import { ConsentProvenanceFields } from "./ConsentProvenance";
import { LeadPicker } from "./LeadPicker";
import { ContactEditor } from "./ContactEditor";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";
import { BasicsStep, PaceFields, StartChoice, type ListQuery } from "./NewCampaignSteps";
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
  { id: "basics", label: "The basics", heading: "The basics", lede: "Name it, pick the agent, and say what the calls are for." },
  { id: "people", label: "Who to call", heading: "Who should we call?", lede: "Add a list, pick from your leads, or both." },
  { id: "when", label: "When to call", heading: "When should we call?", lede: "Choose when it starts. The calling rules are already set." },
  { id: "review", label: "Review", heading: "Check it, then create it", lede: "Saved as a draft. Nothing is called yet." },
] as const;

const REVIEW = STEPS.length - 1;

/** The step's own top: its question, and one line on what it decides. */
function StepHeader({ index }: { index: number }) {
  const step = STEPS[index]!;
  return (
    <div className="space-y-1">
      <h3 className="text-title text-ink">{step.heading}</h3>
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
  /** The way to have the assistant fill the steps in, shown at the top of the summary. */
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
  const [furthest, setFurthest] = useState(0);
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
      return briefProblem(form);
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
    setFurthest((far) => Math.max(far, index));
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
  const groups = summarize(summaryInput);
  const sentence = headline(summaryInput);

  const content: ReactNode[] = [
    <BasicsStep
      key="basics"
      form={form}
      agents={agents}
      agentOptions={agentOptions}
      selectedAgentId={selectedAgentId}
      selectedAgent={selectedAgent}
      hasNoAgents={hasNoAgents}
      numbers={numbers}
      templates={templates}
    />,
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
      <PaceFields form={form} cap={concurrencyCap} capUnknown={capUnknown} />
    </div>,
    <div key="review" className="space-y-6">
      <p className="rounded-card bg-brand-soft px-4 py-3.5 text-heading text-ink dark:bg-brand-strong/20">{sentence}</p>
      <div className="space-y-6">
        {groups.map((group) => (
          <div key={group.step} className="border-t border-line pt-5">
            <SummaryList group={group} onEdit={() => goTo(group.step)} />
          </div>
        ))}
      </div>
    </div>,
  ];

  const nextLabel = step < REVIEW ? `Next: ${STEPS[step + 1]!.label.toLowerCase()}` : "Next";

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start xl:grid-cols-[minmax(0,1fr)_20rem] xl:gap-10">
      {/* A `div role="form"` rather than a `<form>`: the leads picker carries the Leads
          screen's own small forms (a detail filter, naming a saved view), and a form may
          not sit inside another. Nothing here submits; WizardSteps' buttons drive every
          step. */}
      <div ref={formRef} role="form" aria-label="New campaign" className="min-w-0 scroll-mt-6">
        <WizardSteps
          steps={STEPS.map((s, index) => ({
            id: s.id,
            label: s.label,
            content:
              index === step ? (
                <div className="space-y-6 rounded-card border border-line bg-surface p-4 shadow-card sm:p-6">
                  <StepHeader index={index} />
                  {content[index]}
                  {problem ? (
                    <p role="alert" className="text-meta text-danger">
                      {problem}
                    </p>
                  ) : null}
                  {index === REVIEW && createError != null ? <ProblemNotice error={createError} /> : null}
                </div>
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

      <aside aria-label="Campaign summary" className="min-w-0 space-y-4 lg:sticky lg:top-6">
        {/* The review step IS the summary, full width; beside it the card would repeat it. */}
        {step < REVIEW && (
          <section className="hidden overflow-hidden rounded-card border border-line bg-surface shadow-card lg:block">
            <div className="border-b border-line bg-surface-muted px-4 py-4">
              <h3 className={`break-words text-heading ${form.name.trim() ? "text-ink" : "text-ink-faint"}`}>
                {form.name.trim() || "Untitled campaign"}
              </h3>
              <p aria-live="polite" className="mt-1 text-meta text-ink-muted">
                {sentence}
              </p>
            </div>
            <div className="space-y-5 px-4 py-4">
              {groups.map((group) => (
                <SummaryList
                  key={group.step}
                  compact
                  group={group}
                  onEdit={group.step <= furthest && group.step !== step ? () => goTo(group.step) : undefined}
                />
              ))}
            </div>
            <p className="border-t border-line px-4 py-3 text-meta text-ink-muted">
              Saved as a draft. Nothing is called until you launch.
            </p>
          </section>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-dashed border-line px-4 py-3 lg:block lg:space-y-3">
          <p className="min-w-0 text-meta text-ink-muted">
            <span className="block">Rather say it in a sentence?</span>
            <span className="block">{ASSISTANT_NAME} fills in the steps. You check them.</span>
          </p>
          {assistant}
        </div>
      </aside>
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
