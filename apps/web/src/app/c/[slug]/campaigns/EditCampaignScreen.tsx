"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { isAssignable } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import {
  useCampaignNumbers,
  useCampaignProgress,
  useDltTemplates,
  useUpdateCampaign,
  type Classification,
} from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { windowRefusal } from "./NewCampaignFlow";
import { BasicsStep, PaceRows, campaignNumbers } from "./NewCampaignSteps";
import { useCampaignForm } from "./campaignForm";

/**
 * `/c/{slug}/campaigns/{id}/edit`: change a DRAFT's settings (D-773, `PATCH`).
 *
 * The same fields as the create page, read back from the campaign. Who to call is changed
 * on the campaign's own page (add or remove people), and where the list came from has its
 * own audited declaration there. A campaign that is no longer a draft is not editable,
 * and this page says so rather than offering a form the server refuses.
 */
export function EditCampaignScreen({ slug, campaignId }: { slug: string; campaignId: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const progress = useCampaignProgress(session, campaignId);
  const agents = useAgents(session);
  const numbers = useCampaignNumbers(session);
  const templates = useDltTemplates(session);
  const update = useUpdateCampaign(session, campaignId);
  // Success moves back to the campaign, so the save is said in a toast that survives it.
  const updateFeedback = useActionFeedback(update, { errorDisplay: "inline", successToast: "Changes saved" });
  const write = useWriteAccess(session, "leads:dispatch", "change campaigns");
  const form = useCampaignForm();
  const [loaded, setLoaded] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const detail = href(`/c/${slug}/campaigns/${campaignId}`);
  const data = progress.data;

  useEffect(() => {
    if (!data || loaded) return;
    form.setName(data.name);
    form.setAgentId(data.agent_id);
    if (data.classification === "promotional" || data.classification === "service") {
      form.setClassification(data.classification as Classification);
    }
    form.setNumberId(data.number_id ?? "");
    form.setConcurrency(data.concurrency);
    form.setRestrictHours(Boolean(data.calling_hours));
    if (data.calling_hours) {
      form.setWindowStart(data.calling_hours.start);
      form.setWindowEnd(data.calling_hours.end);
    }
    form.setRetry({ max_attempts: data.retry_policy.max_attempts, gaps_minutes: data.retry_policy.gaps_minutes });
    setLoaded(true);
  }, [data, loaded, form]);

  const agentOptions = (agents.data ?? []).filter(isAssignable);
  const selectedAgentId = form.agentId || agentOptions[0]?.id || "";
  const back = { href: detail, label: data?.name ?? "Campaign" };

  if (progress.isLoading || (data && !loaded)) {
    return (
      <div className="max-w-4xl space-y-5 pb-12">
        <PageHeader back={back} title="Edit campaign" />
        <Skeleton rows={4} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="max-w-4xl space-y-5 pb-12">
        <PageHeader back={back} title="Edit campaign" />
        <ProblemNotice error={progress.error ?? new Error("This campaign did not load.")} onRetry={() => progress.refetch()} />
      </div>
    );
  }
  if (data.status !== "draft") {
    return (
      <div className="max-w-4xl space-y-5 pb-12">
        <PageHeader back={back} title="Edit campaign" />
        <p className="text-body text-ink-muted">
          Only a draft can be changed. This campaign has started; duplicate it to make a new draft from it.
        </p>
      </div>
    );
  }

  const save = () => {
    const window = form.restrictHours ? windowRefusal(form.windowStart, form.windowEnd) : null;
    const next =
      form.name.trim().length < 2 ? "Give this campaign a name." : !selectedAgentId ? "Choose the agent that makes these calls." : window;
    setProblem(next);
    if (next) return;
    const usable = campaignNumbers(numbers.data, selectedAgentId).some((n) => n.id === form.numberId);
    update.mutate(
      {
        name: form.name.trim(),
        agent_id: selectedAgentId,
        classification: form.classification,
        number_id: usable ? form.numberId : null,
        concurrency: form.concurrency,
        calling_hours: form.restrictHours ? { start: form.windowStart, end: form.windowEnd } : null,
        retry_policy: form.retry,
      },
      { onSuccess: () => router.push(detail) },
    );
  };

  return (
    <div className="max-w-4xl space-y-5 pb-12">
      <PageHeader back={back} title="Edit campaign" />
      <RestrictionNote reason={write.reason} />
      <form
        noValidate
        aria-label="Edit campaign"
        className="max-w-2xl space-y-10"
        onSubmit={(event) => {
          event.preventDefault();
          if (write.allowed) save();
        }}
      >
        <Section title="The basics">
          <BasicsStep
            form={form}
            agents={agents}
            agentOptions={agentOptions}
            selectedAgentId={selectedAgentId}
            selectedAgent={agentOptions.find((a) => a.id === selectedAgentId)}
            hasNoAgents={Boolean(agents.data) && agentOptions.length === 0}
            numbers={numbers}
            templates={templates}
            showTemplate={false}
          />
        </Section>
        <Section title="How it calls">
          <PaceRows form={form} />
        </Section>
        <div className="space-y-3 border-t border-line pt-6">
          {problem && (
            <p role="alert" className="text-body text-danger">
              {problem}
            </p>
          )}
          {update.error ? <ProblemNotice error={update.error} /> : null}
          <div className="flex flex-wrap items-center justify-end gap-x-5 gap-y-3">
            <button type="button" className={TEXT_ACTION} onClick={() => router.push(detail)}>
              Cancel
            </button>
            <ActionButton
              type="submit"
              title={write.allowed ? undefined : (write.reason ?? undefined)}
              disabled={!write.allowed}
              status={updateFeedback.status}
              pendingLabel="Saving"
              successLabel="Saved"
            >
              Save changes
            </ActionButton>
          </div>
        </div>
      </form>
    </div>
  );
}
