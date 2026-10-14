"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { ProblemNotice, RestrictionNote } from "@/components/ui";
import { isAssignable } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import {
  recurrenceUntil,
  useCampaignNumbers,
  useCreateCampaign,
  useDltTemplates,
} from "@/lib/api/campaigns";
import { apiRequest } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useClientRealm } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { TrialLockNotice } from "../TrialLockNotice";
import { NewCampaignFlow } from "./NewCampaignFlow";
import { campaignNumbers } from "./NewCampaignSteps";
import { useCampaignForm, useScheduleForm } from "./campaignForm";
import { useCampaignsCopilotSurface } from "./campaignsCopilotSurface";

/**
 * `/c/{slug}/campaigns/new`: the create page (FLOWS §5).
 *
 * Creating makes a DRAFT. The list, the leads filter and a chosen start are sent once the
 * draft exists, and the page then moves to the campaign's own address, where the launch
 * checklist decides whether it can dial. A step that fails after the draft exists is
 * reported on the campaign's page by its own section (contacts, schedule), and the draft
 * is never lost: it is already in the list.
 */
export function NewCampaignScreen({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const queryClient = useQueryClient();
  const agents = useAgents(session);
  const numbers = useCampaignNumbers(session);
  const templates = useDltTemplates(session);
  const create = useCreateCampaign(session);
  const form = useCampaignForm();
  const scheduleForm = useScheduleForm();
  const [followUp, setFollowUp] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");
  const agentOptions = (agents.data ?? []).filter(isAssignable);
  const selectedAgentId = form.agentId || agentOptions[0]?.id || "";
  const selectedAgent = agentOptions.find((option) => option.id === selectedAgentId);
  const hasNoAgents = Boolean(agents.data) && agentOptions.length === 0;

  useCampaignsCopilotSurface({ form, scheduleForm, agentOptions, selectedAgentId, numbers, templates });
  useUnsavedGuard(
    !saving && (form.contacts.length > 0 || form.name.trim() !== "" || form.agentId !== ""),
  );

  const detail = (id: string) => href(`/c/${slug}/campaigns/${id}`);

  /**
   * The draft first, then what it carries. Each follow-up is a separate request against
   * the new id; one that is refused stops here with its reason, and the page links to the
   * draft rather than leaving the client guessing whether it exists.
   */
  const submit = () => {
    if (!selectedAgentId) return;
    const usable = campaignNumbers(numbers.data, selectedAgentId).some((n) => n.id === form.numberId);
    create.mutate(
      {
        agent_id: selectedAgentId,
        name: form.name,
        classification: form.classification,
        concurrency: form.concurrency,
        number_id: usable ? form.numberId : null,
        dlt_template_id: form.templateId || null,
        calling_hours: form.restrictHours ? { start: form.windowStart, end: form.windowEnd } : null,
        consent_provenance:
          form.consentSource && form.consentIso
            ? { source: form.consentSource, collected_at: form.consentIso }
            : null,
        retry_policy: form.retry,
      },
      {
        onSuccess: async ({ id }) => {
          setSaving(true);
          try {
            const base = `/v1/campaigns/${id}`;
            if (form.checked.ready.length > 0) {
              await apiRequest(session, `${base}/contacts`, {
                method: "POST",
                body: { contacts: form.checked.ready },
              });
            }
            if (form.fromLeads) {
              await apiRequest(session, `${base}/contacts/from-leads`, {
                method: "POST",
                body: { filter: form.fromLeads },
              });
            }
            if (scheduleForm.startMode === "later" && scheduleForm.startIso) {
              await apiRequest(session, `${base}/schedule`, {
                method: "POST",
                body: { start_at: scheduleForm.startIso },
              });
            }
            if (scheduleForm.startMode === "weekly") {
              await apiRequest(session, `${base}/recurrence`, {
                method: "POST",
                body: {
                  days: scheduleForm.repeatDays,
                  at: scheduleForm.repeatTime,
                  until: recurrenceUntil(scheduleForm.repeatEnds),
                },
              });
            }
            void queryClient.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
            form.reset();
            router.push(detail(id));
          } catch (error) {
            setSaving(false);
            setFollowUp({ error, id });
          }
        },
      },
    );
  };

  const failed = followUp as { error: unknown; id: string } | null;

  return (
    <div className="max-w-4xl space-y-5 pb-12">
      <PageHeader
        back={{ href: href(`/c/${slug}/campaigns`), label: "All campaigns" }}
        title="New campaign"
        actions={
          <AskAssistant
            label={`Build a campaign with ${ASSISTANT_NAME}`}
            prompt="Fill in this campaign for me: who to call, which agent and when. For example: call this week's hot leads tomorrow at 11."
          />
        }
        description="Your agent calls the people you add, inside the hours you allow."
      />
      <TrialLockNotice lock="campaigns" />
      <RestrictionNote reason={write.reason} />
      {agents.error && <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />}
      {numbers.error && <ProblemNotice error={numbers.error} onRetry={() => numbers.refetch()} />}
      {templates.error && <ProblemNotice error={templates.error} onRetry={() => templates.refetch()} />}
      {failed && (
        <div className="space-y-2">
          <ProblemNotice error={failed.error} />
          <p className="text-body text-ink-muted">
            The draft was created.{" "}
            <a href={detail(failed.id)} className="font-medium text-ink underline underline-offset-2">
              Open it
            </a>{" "}
            to finish adding people or setting its start.
          </p>
        </div>
      )}
      <NewCampaignFlow
        form={form}
        schedule={scheduleForm}
        agents={agents}
        agentOptions={agentOptions}
        selectedAgentId={selectedAgentId}
        selectedAgent={selectedAgent}
        hasNoAgents={hasNoAgents}
        numbers={numbers}
        templates={templates}
        create={create}
        canWrite={write.allowed && !saving}
        onSubmit={submit}
        onCancel={() => router.push(href(`/c/${slug}/campaigns`))}
      />
    </div>
  );
}
