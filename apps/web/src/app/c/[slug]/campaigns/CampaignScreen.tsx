"use client";

import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Disclosure, ProblemNotice, RestrictionNote, Skeleton, formatCount, formatPhone } from "@/components/ui";
import {
  useCampaignProgress,
  useCampaignResults,
  useLaunchCampaign,
  useLaunchCheck,
  usePauseCampaign,
  useScheduleCampaign,
  useSetRecurrence,
  useUnscheduleCampaign,
} from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { useClientRealm } from "@/lib/api/session";

import { DraftPeople } from "./DraftPeople";
import { ArmingForms } from "./ArmingForms";
import { CampaignHeaderActions } from "./CampaignHeaderActions";
import { CampaignResults } from "./CampaignResults";
import { CampaignRun } from "./CampaignRun";
import { CampaignSettings } from "./CampaignSettings";
import { CampaignStateNotice } from "./CampaignStateNotice";
import { ContactResults } from "./ContactResults";
import { LaunchGate } from "./LaunchGate";
import { ScheduleCards } from "./ScheduleCards";
import { useScheduleForm } from "./campaignForm";
import { CampaignStatusPill } from "./campaignStatus";

/**
 * `/c/{slug}/campaigns/{id}`: ONE CAMPAIGN, at its own address (D-773).
 *
 * The screen's job changes with the campaign's state, and so does its first block:
 *
 * - a draft or a scheduled campaign: **get it ready and launch it** — the launch checklist,
 *   then who will be called, then starting later;
 * - a launched one: **how far it has got** — the live progress (`CampaignRun`), then what
 *   it achieved, then every person with what happened to them.
 *
 * Why it is not calling, when it is not, sits above both: a pause or a refusal is the
 * first thing the owner must act on. The settings it dials under are rows at the end,
 * not a run-on line under the name: they are read when checking, not every visit.
 *
 * Every figure is the server's or is not shown: while progress loads there is a skeleton,
 * and a failed read is a notice, never a zero.
 */
export function CampaignScreen({ slug, campaignId }: { slug: string; campaignId: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const progress = useCampaignProgress(session, campaignId);
  const check = useLaunchCheck(session, campaignId);
  const launch = useLaunchCampaign(session, campaignId);
  const setStatus = usePauseCampaign(session, campaignId);
  const schedule = useScheduleCampaign(session, campaignId);
  const unschedule = useUnscheduleCampaign(session, campaignId);
  const repeat = useSetRecurrence(session, campaignId);
  const scheduleForm = useScheduleForm();
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");
  const refusal = write.allowed ? undefined : (write.reason ?? undefined);

  const data = progress.data;
  const status = data?.status ?? null;
  const launched = status !== null && !["draft", "scheduled"].includes(status);
  const live = status === "running" || status === "paused";
  const results = useCampaignResults(session, campaignId, live, launched);
  const back = { href: href(`/c/${slug}/campaigns`), label: "All campaigns" };

  /*
   * THIS CAMPAIGN, DECLARED TO THE ASSISTANT: facts only, no person. "Ask Pip about this
   * campaign" reads its results through the `campaign_detail` tool by this id.
   */
  useCopilotSurface(
    data
      ? {
          route: `/c/${slug}/campaigns/${campaignId}`,
          title: data.name,
          realm: "client",
          fields: [],
          facts: [
            { key: "campaign_id", label: "This campaign's id", value: campaignId },
            { key: "status", label: "Status", value: data.status },
            { key: "pause_reason", label: "Why it is paused", value: data.pause_reason ?? "not paused" },
            {
              key: "not_calling",
              label: "Why it is calling nobody",
              value: data.not_calling.map((b) => b.rule).join(", ") || "nothing stops it",
            },
            { key: "people", label: "People on the list", value: String(data.total) },
          ],
          apply: () => undefined,
        }
      : null,
  );

  if (progress.isLoading) {
    return (
      <div className="max-w-5xl space-y-5 pb-12">
        <PageHeader back={back} title="Campaign" />
        <Skeleton rows={4} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="max-w-5xl space-y-5 pb-12">
        <PageHeader back={back} title="Campaign" />
        <ProblemNotice
          error={progress.error ?? new Error("This campaign did not load.")}
          onRetry={() => progress.refetch()}
        />
      </div>
    );
  }

  const armedScheduleWouldRefuse =
    status === "scheduled" &&
    check.data !== undefined &&
    !check.data.ready &&
    (data.schedule_blocked_rules?.length ?? 0) === 0;

  return (
    <div className="max-w-5xl space-y-10 pb-12">
      <div className="space-y-5">
        <PageHeader
          back={back}
          title={data.name}
          status={
            <CampaignStatusPill
              status={data.status}
              pauseReason={data.pause_reason}
              notCalling={data.not_calling.length > 0}
            />
          }
          description={
            <>
              {data.agent_name} calls from{" "}
              {data.number_e164 ? formatPhone(data.number_e164) : "the agent's own number"}
            </>
          }
          actions={
            <CampaignHeaderActions
              slug={slug}
              campaignId={campaignId}
              progress={data}
              setStatus={setStatus}
              canWrite={write.allowed}
              refusal={refusal}
              onGone={() => router.push(back.href)}
              onCopied={(id) => router.push(href(`/c/${slug}/campaigns/${id}`))}
            />
          }
        />
        <RestrictionNote reason={write.reason} />
        {setStatus.error && <ProblemNotice error={setStatus.error} />}
        {launch.error && <ProblemNotice error={launch.error} />}
        {schedule.error && <ProblemNotice error={schedule.error} />}
        {unschedule.error && <ProblemNotice error={unschedule.error} />}
        {repeat.error && <ProblemNotice error={repeat.error} />}

        <CampaignStateNotice
          slug={slug}
          campaignId={campaignId}
          progress={data}
          canWrite={write.allowed}
          refusal={refusal}
        />

        {launch.data && (
          <p role="status" className="text-body text-ink-muted">
            Calling {formatCount(launch.data.dialable)} {launch.data.dialable === 1 ? "person" : "people"}.
            {launch.data.dnc_scrubbed > 0 &&
              ` ${formatCount(launch.data.dnc_scrubbed)} were on the do-not-call list and won't be called.`}
          </p>
        )}
      </div>

      {launched && <CampaignRun progress={data} />}

      <ScheduleCards
        status={status}
        progress={progress}
        unschedule={unschedule}
        armedScheduleWouldRefuse={armedScheduleWouldRefuse}
        canWrite={write.allowed}
        refusal={refusal}
      />

      {!launched && (
        <>
          <LaunchGate
            slug={slug}
            campaignId={campaignId}
            status={status}
            check={check}
            progress={progress}
            launch={launch}
            canWrite={write.allowed}
            writeReason={write.reason}
            refusal={refusal}
          />
          {check.data && (
            <Disclosure
              title="Start later or repeat"
              subtitle="Set a start time or a weekly repeat. The same checks run again when it starts."
            >
              <ArmingForms
                status={status}
                check={check}
                schedule={schedule}
                repeat={repeat}
                scheduleForm={scheduleForm}
                canWrite={write.allowed}
                refusal={refusal}
              />
            </Disclosure>
          )}
        </>
      )}

      {launched && (
        <Section
          title="Results"
          action={
            <AskAssistant
              label={`Ask ${ASSISTANT_NAME} about this campaign`}
              prompt={`Tell me about the campaign "${data.name}": why calls did not connect, what callers asked about, and who I should follow up.`}
            />
          }
        >
          <CampaignResults slug={slug} campaignId={campaignId} results={results} />
        </Section>
      )}

      {launched ? (
        <Section title="People">
          <ContactResults
            slug={slug}
            campaignId={campaignId}
            maxAttempts={data.retry_policy.max_attempts}
            live={live}
            editable={false}
            canWrite={write.allowed}
            refusal={refusal}
          />
        </Section>
      ) : (
        <DraftPeople
          slug={slug}
          campaignId={campaignId}
          maxAttempts={data.retry_policy.max_attempts}
          canWrite={write.allowed}
          refusal={refusal}
        />
      )}

      <CampaignSettings slug={slug} campaignId={campaignId} progress={data} />
    </div>
  );
}
