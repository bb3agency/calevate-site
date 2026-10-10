"use client";

/**
 * NEW CAMPAIGN, ON ONE PAGE (founder, REDESIGN-2): the basics, who to call and when, top
 * to bottom, with one "Create campaign" at the end. It used to be a four-step flow; the
 * same fields and the same refusals are here, in the same order, so a person sees the
 * whole campaign before creating it and nothing hides behind a Next.
 *
 * Calling hours and how many calls run at once are pre-set and shown as rows with Change;
 * no-answer retries and do-not-call skipping are the platform's and shown as facts. The
 * compliance check before LAUNCH is unchanged: creating makes a draft, and the draft's own
 * checklist (`LaunchGate`) still decides whether it can dial.
 */

import { useState } from "react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { useFormValidation } from "@/components/formValidation";
import { PRIMARY_BUTTON, ProblemNotice } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate, useCreateCampaign } from "@/lib/api/campaigns";

import { ConsentProvenanceFields } from "./ConsentProvenance";
import { ContactEditor } from "./ContactEditor";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";
import { BasicsStep, PaceRows, StartChoice, type ListQuery } from "./NewCampaignSteps";

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
  create,
  canWrite,
  onSubmit,
  onCancel,
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
  create: ReturnType<typeof useCreateCampaign>;
  canWrite: boolean;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const valid = useFormValidation();
  const { counts, refusal } = form.checked;
  const [problem, setProblem] = useState<string | null>(null);

  /** The first thing stopping this campaign being created, in page order. */
  function firstProblem(): string | null {
    if (form.name.trim().length < 2) return "Give this campaign a name.";
    if (!selectedAgentId) return "Choose the agent that makes these calls.";
    if (counts.ready === 0) return "Add at least one number we can call.";
    if (refusal) return refusal;
    if (!form.provenanceAnswered) {
      return "Answer both questions about your list — a campaign without them can't be launched.";
    }
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
    return null;
  }

  return (
    <form
      noValidate
      aria-label="New campaign"
      className="max-w-2xl space-y-10"
      onSubmit={(event) => {
        event.preventDefault();
        const next = firstProblem();
        setProblem(next);
        if (next === null && canWrite) onSubmit();
      }}
    >
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

      <Section
        title="Who should we call?"
        description="Paste, import or add your contacts, then tell us where the list came from."
      >
        <div className="space-y-6">
          <ContactEditor entries={form.contacts} onChange={form.setContacts} />
          <ConsentProvenanceFields
            validation={valid}
            idPrefix="new"
            source={form.consentSource}
            collectedAt={form.consentDate}
            onSource={form.setConsentSource}
            onCollectedAt={form.setConsentDate}
          />
        </div>
      </Section>

      <Section title="When should we call?">
        <div className="space-y-6">
          <StartChoice schedule={schedule} />
          <PaceRows form={form} />
        </div>
      </Section>

      <div className="space-y-3 border-t border-line pt-6">
        {problem ? (
          <p role="alert" className="text-body text-danger">
            {problem}
          </p>
        ) : null}
        {create.error ? <ProblemNotice error={create.error} /> : null}
        <div className="flex flex-wrap items-center justify-end gap-x-5 gap-y-3">
          <button type="button" className={TEXT_ACTION} onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className={PRIMARY_BUTTON} disabled={create.isPending || !canWrite}>
            {create.isPending ? "Creating…" : "Create campaign"}
          </button>
        </div>
        {schedule.startMode === "review" ? (
          <p className="text-meta text-ink-muted">
            It is created as a draft. Nothing is called until you launch it from its checklist.
          </p>
        ) : null}
      </div>
    </form>
  );
}
