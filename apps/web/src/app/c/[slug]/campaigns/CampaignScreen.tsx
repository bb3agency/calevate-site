"use client";

import { useRouter } from "next/navigation";

import { problemToast, useActionFeedback } from "@/components/arc/feedback";
import { InlineEdit } from "@/components/arc/inline-edit";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Tabs } from "@/components/interior/tabs";
import { NoticeBox, ProblemNotice, RestrictionNote, Skeleton, formatCount, formatPhone } from "@/components/ui";
import {
  useCampaignProgress,
  useCampaignResults,
  useLaunchCampaign,
  useLaunchCheck,
  usePauseCampaign,
  useScheduleCampaign,
  useSetRecurrence,
  useUnscheduleCampaign,
  useUpdateCampaign,
} from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { useClientRealm } from "@/lib/api/session";

import { DraftPeople, peopleSectionId } from "./DraftPeople";
import { ArmingForms } from "./ArmingForms";
import { AgentSection, ImproveTab, TestCallSection } from "./CampaignBoosters";
import { CampaignNotes } from "./CampaignNotes";
import { CampaignCalls } from "./CampaignCalls";
import { campaignRun } from "./campaignProgress";
import { CampaignHeaderActions } from "./CampaignHeaderActions";
import { CampaignQuestions } from "./CampaignQuestions";
import { CampaignResults, ResultFigures } from "./CampaignResults";
import { CampaignRun } from "./CampaignRun";
import { CampaignSettings } from "./CampaignSettings";
import { CampaignStateNotice } from "./CampaignStateNotice";
import { CampaignTimeline } from "./CampaignTimeline";
import { CampaignWorkspace } from "./CampaignWorkspace";
import { FoldGroup, FoldSection } from "./FoldSection";
import { OtherCallSettings } from "./OtherCallSettings";
import { ContactResults } from "./ContactResults";
import { LaunchGate } from "./LaunchGate";
import { ScheduleCards } from "./ScheduleCards";
import { StartCampaign } from "./StartCampaign";
import { useScheduleForm } from "./campaignForm";
import { CampaignStatusPill } from "./campaignStatus";

/**
 * `/c/{slug}/campaigns/{id}`: ONE CAMPAIGN, at its own address (D-773).
 *
 * The screen's job changes with the campaign's state, and so does its first block, the
 * status band:
 *
 * - a draft or a scheduled campaign: **get it ready and launch it** — one panel holding
 *   any armed start, the launch checklist or the one Call button, and beside it what
 *   pressing it does (people, calls at once, hours, number, kind of call); then starting
 *   later or repeating as two option cards; then who will be called, with how it calls
 *   beside them on a wide screen;
 * - a launched one: **what it is doing and how far it has got** — the live panel
 *   (`CampaignRun`: who is on a call, calls at once against the limit, the next try), the
 *   headline results, then three tabs: People first, because each person and their call
 *   is what an owner comes back for; the result breakdowns; and the settings it dials
 *   under, which are read when checking, not every visit.
 *
 * Why it is not calling, when it is not, sits above both: a pause or a refusal is the
 * first thing the owner must act on. The name is renamed in place in any status: it is a
 * label for the owner's own list and changes nothing about who is called.
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
  const launchFeedback = useActionFeedback(launch, { errorTitle: "Could not launch this campaign" });
  const setStatusFeedback = useActionFeedback(setStatus, {
    errorTitle: "Could not change this campaign",
    successToast: (_out, action) => (action === "pause" ? "Campaign paused" : "Campaign resumed"),
    successDescription: (_out, action) =>
      action === "pause" ? "Calls not yet made wait until you resume." : undefined,
  });
  // The armed schedule shows in its own card further up the page, so its arrival is said.
  const scheduleFeedback = useActionFeedback(schedule, { errorDisplay: "inline", successToast: "Start scheduled" });
  const unscheduleFeedback = useActionFeedback(unschedule, {
    errorTitle: "Could not cancel the schedule",
    successToast: "Schedule cancelled",
    successDescription: "It will not start on its own any more.",
  });
  const repeatFeedback = useActionFeedback(repeat, { errorDisplay: "inline", successToast: "Repeat set" });
  const rename = useUpdateCampaign(session, campaignId);
  // Inline: the field stays open with the refusal under it (`InlineEdit`).
  const renameFeedback = useActionFeedback(rename, { errorDisplay: "inline" });
  const scheduleForm = useScheduleForm();
  // The launch checklist's "Add people" goes to the Add people section.
  const addPeople = () =>
    document.getElementById(peopleSectionId(campaignId))?.scrollIntoView?.({ block: "start", behavior: "smooth" });
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
      <div className="max-w-6xl space-y-5 pb-12">
        <PageHeader back={back} title="Campaign" />
        <Skeleton rows={4} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="max-w-6xl space-y-5 pb-12">
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

  const scheduleCardProps = {
    status,
    progress,
    unschedule: unscheduleFeedback,
    armedScheduleWouldRefuse,
    canWrite: write.allowed,
    refusal,
  };

  const people = (
    <ContactResults
      slug={slug}
      campaignId={campaignId}
      maxAttempts={data.retry_policy.max_attempts}
      live={live}
      canWrite={write.allowed}
      refusal={refusal}
    />
  );

  // People, the agent, hours and retries change in every state; a campaign can always be
  // started again (founder, 16 Nov 2026).
  const changeable = data.archived_at == null;
  const stopped = status === "cancelled" || status === "completed";

  // In the row beside Collapse all / Expand all, after Start (founder, 16 Nov 2026).
  const actionProps = {
    slug,
    campaignId,
    progress: data,
    setStatus,
    setStatusFeedback,
    canWrite: write.allowed,
    refusal,
    onGone: () => router.push(back.href),
    onCopied: (id: string) => router.push(href(`/c/${slug}/campaigns/${id}`)),
  };
  const campaignActions = <CampaignHeaderActions {...actionProps} />;
  // Start and Stop sit on Set up and Progress & results only (founder, 16 Nov 2026).
  const startButton = (
    <StartCampaign
      campaignId={campaignId}
      status={status}
      check={check}
      progress={progress}
      launch={launchFeedback}
      resume={setStatusFeedback}
      canWrite={write.allowed}
      refusal={refusal}
    />
  );

  return (
    <div className="max-w-6xl space-y-8 pb-12">
      <div className="space-y-5">
        <PageHeader
          back={back}
          title={
            <InlineEdit
              value={data.name}
              label="Campaign name"
              textClassName="text-xl font-semibold tracking-tight"
              maxLength={120}
              wrap
              validate={(next) => (next.length < 2 ? "Use at least 2 characters." : null)}
              status={renameFeedback.status}
              errorMessage={problemToast(rename.error, "That name did not save").description}
              disabled={!write.allowed}
              onSave={(name) => renameFeedback.run({ name })}
            />
          }
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
          meta={data.goal ? <span className="text-ink-muted">Goal: {data.goal}</span> : undefined}
          actions={<CampaignHeaderActions {...actionProps} show="duplicate" />}
        />
        <RestrictionNote reason={write.reason} />

        {data.archived_at != null && (
          // F-10: why this campaign calls nobody, and who put it away.
          <NoticeBox tone="neutral" title="Archived. It calls nobody.">
            {data.archived_by_realm === "admin"
              ? `Archived by our team. Why: ${data.archive_reason ?? "not given"}`
              : "Restore it to use it again."}
          </NoticeBox>
        )}

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
              ` ${formatCount(launch.data.dnc_scrubbed)} skipped: on do-not-call.`}
          </p>
        )}
      </div>

      {/* One layout whatever the status (founder, 15 Nov 2026): the set-up as entered comes
          first; how it is going sits in its own tab. */}
      <Tabs
        label="This campaign"
        defaultValue="setup"
        variant="pills"
        items={[
          { value: "setup", label: "Set up", accent: "bg-brand-strong text-white" },
          { value: "progress", label: "Progress & results", accent: "bg-series-2 text-white" },
          { value: "calls", label: "Calls & recordings", accent: "bg-series-3 text-white" },
          { value: "questions", label: "Questions to answer", accent: "bg-series-5 text-white" },
          { value: "improve", label: "Improve", accent: "bg-series-4 text-white" },
        ]}
        panelClassName="pt-5"
        renderPanel={(current) =>
          current === "calls" ? (
            // One Calls section (founder, 16 Nov 2026): the calls and their recordings, then who
            // was called and how; before the first call, only the line saying none yet.
            <FoldGroup>
              <FoldSection title="Calls" tone="people" id={peopleSectionId(campaignId)}>
                {status === "draft" || campaignRun(data).called === 0 ? (
                  <p className="text-body text-ink-muted">No calls yet. They show here once it calls.</p>
                ) : (
                  <div className="space-y-10">
                    <CampaignCalls slug={slug} campaignId={campaignId} />
                    <div>
                      <h3 className="mb-3 text-body font-semibold text-ink">By person</h3>
                      {people}
                    </div>
                  </div>
                )}
              </FoldSection>
            </FoldGroup>
          ) : current === "questions" ? (
            <CampaignQuestions slug={slug} campaignId={campaignId} canWrite={write.allowed} refusal={refusal} />
          ) : current === "improve" ? (
            <ImproveTab slug={slug} campaignId={campaignId} canWrite={write.allowed} refusal={refusal} />
          ) : current === "progress" ? (
            launched ? (
              <FoldGroup className="space-y-8" actions={<>{startButton}{campaignActions}</>}>
                <FoldSection title="Where it stands" tone="progress">
                  <CampaignRun progress={data} campaignId={campaignId} />
                </FoldSection>
                <FoldSection title="Results" tone="results">
                  <div className="mb-3 flex justify-end">
                    <AskAssistant
                      label={`Ask ${ASSISTANT_NAME} about this campaign`}
                      prompt={`Tell me about the campaign "${data.name}": why calls did not connect, what callers asked about, and who I should follow up.`}
                    />
                  </div>
                  <ResultFigures results={results} />
                  <div className="mt-8 space-y-10">
                    <CampaignResults slug={slug} campaignId={campaignId} results={results} />
                    <Section title="Day by day" headingLevel={3}>
                      <CampaignTimeline campaignId={campaignId} launchedAt={data.launched_at} />
                    </Section>
                  </div>
                </FoldSection>
                <FoldSection title="How it calls" tone="details">
                  <CampaignSettings slug={slug} campaignId={campaignId} progress={data} />
                </FoldSection>
              </FoldGroup>
            ) : (
              <p className="border-y border-line py-6 text-body text-ink-muted">
                Progress and results show here once the campaign starts.
              </p>
            )
          ) : (
            // Every section folds; Start campaign, Collapse all and Expand all sit above them all.
            <FoldGroup
              className="space-y-8"
              actions={
                <>
                  {startButton}
                  {campaignActions}
                </>
              }
            >
              <CampaignWorkspace campaignId={campaignId} canWrite={write.allowed} refusal={refusal} />
              <AgentSection
                campaignId={campaignId}
                agentId={data.agent_id}
                editable={changeable}
                canWrite={write.allowed}
                refusal={refusal}
              />
              <CampaignNotes
                slug={slug}
                campaignId={campaignId}
                agentId={data.agent_id}
                canWrite={write.allowed && changeable}
                refusal={refusal}
              />
              <TestCallSection slug={slug} campaignId={campaignId} canWrite={write.allowed} refusal={refusal} />
              {/* People to call: an Excel or CSV file, pasted rows, or one name and number at a
                  time, until it stops (founder, 16 Nov 2026: people may join mid-campaign). */}
              <DraftPeople
                stopped={stopped}
                slug={slug}
                campaignId={campaignId}
                maxAttempts={data.retry_policy.max_attempts}
                canWrite={write.allowed}
                refusal={refusal}
                total={data.total}
              />
              <ScheduleCards {...scheduleCardProps} />
              <LaunchGate
                slug={slug}
                campaignId={campaignId}
                status={status}
                check={check}
                progress={progress}
                launch={launchFeedback}
                canWrite={write.allowed}
                writeReason={write.reason}
                refusal={refusal}
                onAddPeople={addPeople}
              />
              <OtherCallSettings
                campaignId={campaignId}
                progress={data}
                numberEditable={status === "draft"}
                editable={changeable}
                callingHours={data.calling_hours}
                retryPolicy={data.retry_policy}
                canWrite={write.allowed}
                refusal={refusal}
                startLater={
                  check.data && status === "draft" ? (
                    <ArmingForms
                      status={status}
                      check={check}
                      schedule={scheduleFeedback}
                      repeat={repeatFeedback}
                      scheduleForm={scheduleForm}
                      canWrite={write.allowed}
                      refusal={refusal}
                      showRepeat={false}
                    />
                  ) : undefined
                }
              />
              <div className="flex justify-end">
                <StartCampaign
                  campaignId={campaignId}
                  status={status}
                  check={check}
                  progress={progress}
                  launch={launchFeedback}
                  resume={setStatusFeedback}
                  canWrite={write.allowed}
                  refusal={refusal}
                />
              </div>
            </FoldGroup>
          )
        }
      />
    </div>
  );
}
