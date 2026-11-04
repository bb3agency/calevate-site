"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { problemToast, useActionFeedback } from "@/components/arc/feedback";
import { InlineEdit } from "@/components/arc/inline-edit";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Tabs } from "@/components/interior/tabs";
import { ProblemNotice, RestrictionNote, Skeleton, formatCount, formatPhone } from "@/components/ui";
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
import { CampaignHeaderActions } from "./CampaignHeaderActions";
import { CampaignResults, ResultFigures } from "./CampaignResults";
import { CampaignRun } from "./CampaignRun";
import { CampaignSettings } from "./CampaignSettings";
import { CampaignStateNotice } from "./CampaignStateNotice";
import { CampaignTimeline } from "./CampaignTimeline";
import { ContactResults } from "./ContactResults";
import { LaunchGate } from "./LaunchGate";
import { ScheduleCards } from "./ScheduleCards";
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
  // The launch checklist's "Add people" opens the panel in "Who will be called" and goes to it.
  const [addingPeople, setAddingPeople] = useState(false);
  const addPeople = () => {
    setAddingPeople(true);
    // After the panel has rendered, so the scroll lands on it rather than above it.
    window.setTimeout(() =>
      document.getElementById(peopleSectionId(campaignId))?.scrollIntoView?.({ block: "start", behavior: "smooth" }),
    );
  };
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
      editable={false}
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
          actions={
            <CampaignHeaderActions
              slug={slug}
              campaignId={campaignId}
              progress={data}
              setStatus={setStatus}
              setStatusFeedback={setStatusFeedback}
              canWrite={write.allowed}
              refusal={refusal}
              onGone={() => router.push(back.href)}
              onCopied={(id) => router.push(href(`/c/${slug}/campaigns/${id}`))}
            />
          }
        />
        <RestrictionNote reason={write.reason} />

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

      {/* THE STATUS BAND: the one block whose job changes with the campaign. Keyed on the
          phase so a launch swaps it in with a short settle rather than a jump. */}
      {launched ? (
        <div key="launched" className="settings-enter">
          <CampaignRun progress={data} campaignId={campaignId} />
        </div>
      ) : (
        <div
          key="before-launch"
          className="settings-enter space-y-6 rounded-card border border-line bg-surface p-4 shadow-card sm:p-6"
        >
          <ScheduleCards {...scheduleCardProps} className="border-b border-line pb-6" />
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
        </div>
      )}

      {/* A launched campaign can still repeat; its card sits under the live panel. */}
      {launched && <ScheduleCards {...scheduleCardProps} className="rounded-card border border-line p-4 sm:p-5" />}

      {!launched && check.data && (
        <Section title={status === "scheduled" ? "Make it weekly" : "Start later or repeat"}>
          <ArmingForms
            status={status}
            check={check}
            schedule={scheduleFeedback}
            repeat={repeatFeedback}
            scheduleForm={scheduleForm}
            canWrite={write.allowed}
            refusal={refusal}
          />
        </Section>
      )}

      {launched ? (
        <>
          <Section
            title="Results"
            action={
              <AskAssistant
                label={`Ask ${ASSISTANT_NAME} about this campaign`}
                prompt={`Tell me about the campaign "${data.name}": why calls did not connect, what callers asked about, and who I should follow up.`}
              />
            }
          >
            <ResultFigures results={results} />
          </Section>

          <Tabs
            label="About this campaign"
            defaultValue="people"
            items={[
              { value: "people", label: "People" },
              { value: "results", label: "What happened" },
              { value: "settings", label: "How it calls" },
            ]}
            panelClassName="pt-5"
            renderPanel={(tab) =>
              tab === "results" ? (
                <div className="space-y-10">
                  <CampaignResults slug={slug} campaignId={campaignId} results={results} />
                  <Section title="Day by day" headingLevel={3}>
                    <CampaignTimeline campaignId={campaignId} launchedAt={data.launched_at} />
                  </Section>
                </div>
              ) : tab === "settings" ? (
                <CampaignSettings slug={slug} campaignId={campaignId} progress={data} />
              ) : (
                people
              )
            }
          />
        </>
      ) : (
        // The people take the width and the settings sit beside them on a wide screen,
        // because the list is what changes before launch and the settings are checked once.
        <div className="grid grid-cols-1 items-start gap-10 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <DraftPeople
            slug={slug}
            campaignId={campaignId}
            maxAttempts={data.retry_policy.max_attempts}
            canWrite={write.allowed}
            refusal={refusal}
            adding={addingPeople}
            onAddingChange={setAddingPeople}
          />
          <CampaignSettings slug={slug} campaignId={campaignId} progress={data} layout="aside" />
        </div>
      )}
    </div>
  );
}
