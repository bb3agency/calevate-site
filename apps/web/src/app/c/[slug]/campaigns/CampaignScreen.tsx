"use client";

import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { problemToast, useActionFeedback } from "@/components/arc/feedback";
import { InlineEdit } from "@/components/arc/inline-edit";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Tabs, type TabItem } from "@/components/interior/tabs";
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
import { useCampaignQuestions } from "@/lib/api/campaignWorkspace";
import { useWriteAccess } from "@/lib/api/hooks";
import { SHOW_FINDING_EVENT } from "@/lib/api/scriptChecks";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { usePhoneServiceDown } from "@/lib/api/phoneService";
import { useClientRealm } from "@/lib/api/session";

import { DraftPeople } from "./DraftPeople";
import { ArmingForms } from "./ArmingForms";
import { AgentSection, ImproveTab, TestCallSection } from "./CampaignBoosters";
import { CampaignNotes } from "./CampaignNotes";
import { campaignRun } from "./campaignProgress";
import { CampaignHeaderActions } from "./CampaignHeaderActions";
import { CampaignResults, ResultFigures } from "./CampaignResults";
import { CampaignSettings } from "./CampaignSettings";
import { CampaignStateNotice } from "./CampaignStateNotice";
import { CampaignWorkspace } from "./CampaignWorkspace";
import {
  CampaignSectionsProvider,
  DRAFT_TABS,
  LAUNCHED_TABS,
  SCRIPT_SECTION,
  campaignTabFor,
  linkedCampaignTab,
  markSections,
  peopleSectionId,
  type CampaignTab,
} from "./campaignSections";
import { FoldGroup, FoldSection } from "./FoldSection";
import { JobAlerts } from "./JobAlerts";
import { jobBack } from "./jobBack";
import { OtherCallSettings } from "./OtherCallSettings";
import { LaunchGate, useChecksLeft } from "./LaunchGate";
import { ScheduleCards } from "./ScheduleCards";
import { StartCampaign } from "./StartCampaign";
import { useScheduleForm } from "./campaignForm";
import { CampaignStatusPill } from "./campaignStatus";

/*
 * The set-up tabs (Script, People, Settings, Checks) stay mounted while hidden, so a jump to
 * one of their sections always finds its element and a half-filled form survives a look at
 * another tab. The panels only a launched campaign shows (the live run, the day-by-day
 * chart, the calls, Improve) are their own chunks, loaded when their tab opens.
 */
const panelLoading = () => <Skeleton rows={4} />;
const CampaignRun = dynamic(() => import("./CampaignRun").then((m) => m.CampaignRun), { loading: panelLoading });
const CampaignTimeline = dynamic(() => import("./CampaignTimeline").then((m) => m.CampaignTimeline), {
  loading: panelLoading,
});
const CampaignCalls = dynamic(() => import("./CampaignCalls").then((m) => m.CampaignCalls), { loading: panelLoading });
const CampaignQuestions = dynamic(() => import("./CampaignQuestions").then((m) => m.CampaignQuestions), {
  loading: panelLoading,
});

const SET_UP_TABS: readonly CampaignTab[] = ["script", "people", "settings", "checks"];

/**
 * The open tab's fill (`Tabs variant="pills"`): ink for every tab. Green means done or
 * success in this palette, so an open tab is never green; the sections inside keep their
 * own colours (`FoldSection`), which is where the eye finds its place.
 */
const TAB_ACCENT = "bg-ink text-surface";

function tabLabel(tab: CampaignTab, checksLeft: number | null, questions: number | null): string {
  switch (tab) {
    case "script":
      return "Script";
    case "people":
      return "People";
    case "settings":
      return "Settings";
    case "checks":
      return checksLeft ? `Checks (${formatCount(checksLeft)} left)` : "Checks";
    case "progress":
      return "Progress";
    case "calls":
      return "Calls";
    case "improve":
      return questions ? `Improve (${formatCount(questions)})` : "Improve";
  }
}

/**
 * `/c/{slug}/campaigns/{id}`: ONE CAMPAIGN, at its own address (D-773), in tabs by the
 * owner's question (redesign plan §3, 28 Nov 2026).
 *
 * - Not launched yet: **Script** (what it is for, what it says, who says it, a test call),
 *   **People**, **Settings** (when it calls, alerts, the rest), **Checks** (the compliance
 *   gate). Start campaign sits in the page header, so it is in reach on every tab.
 * - Launched: **Progress** first, because how it is going is what an owner comes back for,
 *   then **Calls**, the same set-up tabs, and **Improve** (questions to answer first).
 *
 * Why it is not calling, when it is not, sits above the tabs: a pause or a refusal is the
 * first thing the owner must act on. Every figure is the server's or is not shown.
 */
export function CampaignScreen({ slug, campaignId }: { slug: string; campaignId: string }) {
  const { session, href } = useClientRealm();
  const phoneServiceDown = usePhoneServiceDown(session);
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const progress = useCampaignProgress(session, campaignId);
  const check = useLaunchCheck(session, campaignId);
  const launch = useLaunchCampaign(session, campaignId);
  const setStatus = usePauseCampaign(session, campaignId);
  const schedule = useScheduleCampaign(session, campaignId);
  const unschedule = useUnscheduleCampaign(session, campaignId);
  const repeat = useSetRecurrence(session, campaignId);
  const launchFeedback = useActionFeedback(launch, { errorTitle: "Could not launch this campaign", errorDisplay: "inline" });
  const setStatusFeedback = useActionFeedback(setStatus, {
    errorTitle: "Could not change this campaign",
    successToast: (_out, action) => (action === "pause" ? "Campaign paused" : "Campaign resumed"),
    successDescription: (_out, action) =>
      action === "pause" ? "Calls not yet made wait until you resume." : undefined,
  });
  // The armed schedule shows in its own card, so its arrival is said.
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
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");
  const refusal = write.allowed ? undefined : (write.reason ?? undefined);
  const checksLeft = useChecksLeft(check);

  const data = progress.data;
  const status = data?.status ?? null;
  const launched = status !== null && !["draft", "scheduled"].includes(status);
  const live = status === "running" || status === "paused";
  const results = useCampaignResults(session, campaignId, live, launched);
  // The Improve tab counts them; a draft has no Improve tab, so it asks for none.
  const questions = useCampaignQuestions(session, campaignId, launched);
  const list = { href: href(`/c/${slug}/campaigns`), label: "All campaigns" };
  const back = jobBack({
    from: params.get("from"),
    agentId: data?.agent_id,
    agentName: data?.agent_name,
    list,
    agentHref: (id) => href(`/c/${slug}/agents/${id}`),
  });

  // The open tab: the owner's choice, else the one the link names (`?tab=`), else the first.
  const tabs = launched ? LAUNCHED_TABS : DRAFT_TABS;
  const linked = linkedCampaignTab(params.get("tab"), launched);
  const [chosen, setChosen] = useState<CampaignTab | null>(null);
  const current: CampaignTab =
    chosen && (tabs.includes(chosen) || chosen === linked) ? chosen : (linked ?? tabs[0]);
  const shownTabs = tabs.includes(current) ? tabs : [...tabs, current];

  // `?tab=` follows the open tab, so a reload or a shared link opens the same one. Through
  // the History API, which Next keeps in step, rather than a navigation that would refetch.
  const selectTab = useCallback(
    (tab: CampaignTab) => {
      setChosen(tab);
      const next = new URLSearchParams(window.location.search);
      next.set("tab", tab);
      window.history.replaceState(window.history.state, "", `${pathname}?${next.toString()}${window.location.hash}`);
    },
    [pathname],
  );

  // A link to a section (`#campaign-test` from the agent's Try it, `#campaign-alerts` from an
  // alert) opens the tab that holds it, then lands on it once the page has drawn.
  const ready = data != null;
  useEffect(() => {
    if (!ready) return;
    const section = window.location.hash.slice(1);
    const tab = section ? campaignTabFor(section, campaignId, launched) : null;
    if (!tab) return;
    setChosen(tab);
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => markSections([section], "focus")));
    // Once, when the campaign first loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  // "Show me" on a script line (from Checks, a refusal or a notice): the script sections
  // listen for it and land on the line, once their tab is the one showing.
  useEffect(() => {
    const show = () => selectTab("script");
    window.addEventListener(SHOW_FINDING_EVENT, show);
    return () => window.removeEventListener(SHOW_FINDING_EVENT, show);
  }, [selectTab]);

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
        <PageHeader back={list} title="Campaign" />
        <Skeleton rows={4} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="max-w-6xl space-y-5 pb-12">
        <PageHeader back={list} title="Campaign" />
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

  // People, the agent, hours and retries change in every state; a campaign can always be
  // started again (founder, 16 Nov 2026).
  const changeable = data.archived_at == null;
  const stopped = status === "cancelled" || status === "completed";

  const actionProps = {
    slug,
    campaignId,
    progress: data,
    setStatus,
    setStatusFeedback,
    canWrite: write.allowed,
    refusal,
    onGone: () => router.push(list.href),
    onCopied: (id: string) => router.push(href(`/c/${slug}/campaigns/${id}`)),
  };
  const launchGate = (
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
      onAddPeople={() => selectAndMark("people", peopleSectionId(campaignId))}
    />
  );
  const startButton = (showLeft: boolean) => (
    <StartCampaign
      slug={slug}
      campaignId={campaignId}
      status={status}
      check={check}
      progress={progress}
      launch={launchFeedback}
      resume={setStatusFeedback}
      canWrite={write.allowed}
      refusal={refusal}
      showLeft={showLeft}
    />
  );
  function selectAndMark(tab: CampaignTab, section: string) {
    selectTab(tab);
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => markSections([section], "focus")));
  }

  const panels: Record<CampaignTab, () => ReactNode> = {
    script: () => (
      <FoldGroup className="space-y-8">
        <CampaignWorkspace campaignId={campaignId} canWrite={write.allowed} refusal={refusal} />
        <AgentSection
          campaignId={campaignId}
          agentId={data.agent_id}
          status={status}
          editable={changeable}
          canWrite={write.allowed}
          refusal={refusal}
        />
        <CampaignNotes
          slug={slug}
          campaignId={campaignId}
          status={status}
          canWrite={write.allowed && changeable}
          refusal={refusal}
        />
        {/* Last, because hearing it is how the owner proves the script above. */}
        <TestCallSection
          slug={slug}
          campaignId={campaignId}
          canWrite={write.allowed}
          refusal={refusal}
          agentId={data.agent_id}
        />
      </FoldGroup>
    ),
    // People to call: an Excel or CSV file, pasted rows, or one name and number at a time,
    // until it stops (founder, 16 Nov 2026: people may join mid-campaign).
    people: () => (
      <FoldGroup className="space-y-8">
        <DraftPeople
          stopped={stopped}
          live={live}
          slug={slug}
          campaignId={campaignId}
          maxAttempts={data.retry_policy.max_attempts}
          canWrite={write.allowed}
          refusal={refusal}
          total={data.total}
        />
      </FoldGroup>
    ),
    settings: () => (
      <FoldGroup className="space-y-8">
        <ScheduleCards
          status={status}
          progress={progress}
          unschedule={unscheduleFeedback}
          armedScheduleWouldRefuse={armedScheduleWouldRefuse}
          canWrite={write.allowed}
          refusal={refusal}
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
        <JobAlerts kind="campaign" jobId={campaignId} />
        {/* Launched: the checks as they were answered, kept with the rest of its settings. */}
        {launched && launchGate}
      </FoldGroup>
    ),
    checks: () => (
      <FoldGroup className="space-y-8">
        {launchGate}
        <div className="flex justify-end">{startButton(false)}</div>
      </FoldGroup>
    ),
    progress: () => (
      <FoldGroup className="space-y-8">
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
    ),
    // The calls and their recordings; who was called, person by person, is on People.
    calls: () => (
      <FoldGroup>
        <FoldSection title="Calls" tone="people">
          {campaignRun(data).called === 0 ? (
            <p className="text-body text-ink-muted">No calls yet. They show here once it calls.</p>
          ) : (
            <CampaignCalls slug={slug} campaignId={campaignId} />
          )}
        </FoldSection>
      </FoldGroup>
    ),
    // What the agent could not answer comes first: answering it is the quickest win.
    improve: () => (
      <div className="space-y-10">
        <Section title="Questions to answer" headingLevel={2}>
          <CampaignQuestions
            slug={slug}
            campaignId={campaignId}
            canWrite={write.allowed}
            refusal={refusal}
            onAnswered={() => selectAndMark("script", SCRIPT_SECTION)}
          />
        </Section>
        <Section title="More ways to improve it" headingLevel={2}>
          <ImproveTab
            slug={slug}
            campaignId={campaignId}
            canWrite={write.allowed}
            refusal={refusal}
            agentId={data.agent_id}
            status={status}
          />
        </Section>
      </div>
    ),
  };

  const items: TabItem[] = shownTabs.map((tab) => ({
    value: tab,
    label: tabLabel(tab, launched ? null : checksLeft, questions.data?.length ?? null),
    accent: TAB_ACCENT,
  }));

  return (
    <CampaignSectionsProvider campaignId={campaignId} launched={launched} selectTab={selectTab}>
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
                phoneServiceDown={phoneServiceDown}
              />
            }
            description={
              <>
                {data.agent_name} calls from{" "}
                {data.number_e164 ? formatPhone(data.number_e164) : "the agent's own number"}
              </>
            }
            meta={data.goal ? <span className="text-ink-muted">Goal: {data.goal}</span> : undefined}
            // Start (the one filled button) and Stop are in reach on every tab.
            actions={
              <div className="flex flex-wrap items-center justify-end gap-2">
                {startButton(!launched)}
                <CampaignHeaderActions {...actionProps} />
                <CampaignHeaderActions {...actionProps} show="duplicate" />
              </div>
            }
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

        <Tabs
          label="This campaign"
          value={current}
          onValueChange={(next) => selectTab(next as CampaignTab)}
          variant="pills"
          items={items}
          keepMounted={SET_UP_TABS}
          panelClassName="pt-5"
          renderPanel={(tab) => panels[tab as CampaignTab]()}
        />
      </div>
    </CampaignSectionsProvider>
  );
}
