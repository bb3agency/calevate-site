"use client";

import { StepFlow } from "@/components/console/stepFlow";
import { useFormValidation } from "@/components/formValidation";
import { ProblemNotice } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CampaignNumber, DltTemplate, useCreateCampaign } from "@/lib/api/campaigns";

import { ConsentProvenanceFields } from "./ConsentProvenance";
import { ContactEditor } from "./ContactEditor";
import type { CampaignFormState, ScheduleFormState } from "./campaignForm";
import { BasicsStep, ReviewSummary, WhenStep, type ListQuery } from "./NewCampaignSteps";

/**
 * NEW CAMPAIGN, one subject per step: the basics, who to call, when, then review.
 *
 * PRIMARY JOB: get a list of people into a draft campaign with its consent answer on record.
 *
 * - The provenance question sits in the SAME step as the list it describes ("Who should we
 *   call?"), because the client is holding that list at that moment, which is the one
 *   moment they can answer it cheaply. A draft without it cannot launch. Its wording is a
 *   compliance artefact (SEC-COMP §3) and is unchanged (`ConsentProvenance.tsx`).
 * - Submit is a chain through the hooks the campaign page uses (`CampaignsScreen`): create
 *   the draft, then add the contacts, and arm a start or a repeat if one was chosen. A
 *   failed upload lands on the draft with the error and the list still in place to retry.
 */
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

  return (
    <StepFlow
      label="New campaign"
      onCancel={onCancel}
      submitLabel="Create campaign"
      onSubmit={() => {
        if (canWrite) onSubmit();
      }}
      pending={create.isPending}
      error={create.error ? <ProblemNotice error={create.error} /> : undefined}
      steps={[
        {
          id: "basics",
          title: "The basics",
          hint: "Name it, choose who calls, and what kind of call it is.",
          validate: () =>
            form.name.trim().length < 2
              ? "Give this campaign a name."
              : !selectedAgentId
                ? "Choose the agent that makes these calls."
                : null,
          content: (
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
          ),
        },
        {
          id: "who",
          title: "Who should we call?",
          hint: "Import, paste or add your contacts, then tell us where the list came from.",
          validate: () =>
            counts.ready === 0
              ? "Add at least one number we can call."
              : refusal
                ? refusal
                : !form.provenanceAnswered
                  ? "Answer both questions about your list — a campaign without them can't be launched."
                  : null,
          content: (
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
          ),
        },
        {
          id: "when",
          title: "When should we call?",
          validate: () =>
            form.concurrency < 1 || form.concurrency > 10
              ? "Choose between 1 and 10 calls at the same time."
              : form.restrictHours && (!form.windowStart || !form.windowEnd)
                ? "Choose both a start and an end time."
                : schedule.startMode === "later" && !schedule.startIso
                  ? "Choose the date and time it should start."
                  : schedule.startMode === "weekly" && schedule.repeatDays.length === 0
                    ? "Choose at least one day for this campaign to repeat on."
                    : null,
          content: <WhenStep form={form} schedule={schedule} />,
        },
      ]}
      review={{
        title: "Check and create",
        content: (
          <ReviewSummary
            form={form}
            schedule={schedule}
            agentName={selectedAgent?.name}
            number={(numbers.data ?? []).find((option) => option.id === form.numberId)}
            template={(templates.data ?? []).find((option) => option.id === form.templateId)}
          />
        ),
      }}
    />
  );
}
