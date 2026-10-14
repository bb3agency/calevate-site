"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ListPlus, Pause, Play } from "lucide-react";

import { PageHeader } from "@/components/console/pageHeader";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Section } from "@/components/console/section";
import {
  DANGER_BUTTON,
  Disclosure,
  NOTICE_BAR,
  NOTICE_BASE,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
  formatCount,
  formatPhone,
} from "@/components/ui";
import {
  useAddContacts,
  useAddLeads,
  useCampaignProgress,
  useCampaignResults,
  useDeleteCampaign,
  useDuplicateCampaign,
  useLaunchCampaign,
  useLaunchCheck,
  useLeadPool,
  usePauseCampaign,
  useScheduleCampaign,
  useSetRecurrence,
  useStopCampaign,
  useUnscheduleCampaign,
  type CampaignProgress,
  type LeadFilter,
} from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { useClientRealm } from "@/lib/api/session";

import { ArmingForms } from "./ArmingForms";
import { CampaignResults } from "./CampaignResults";
import { CampaignStateNotice } from "./CampaignStateNotice";
import { ContactEditor } from "./ContactEditor";
import { ContactResults } from "./ContactResults";
import { LaunchGate } from "./LaunchGate";
import { LeadPicker, leadPoolFits } from "./LeadPicker";
import { describeRetry } from "./NewCampaignSteps";
import { ScheduleCards } from "./ScheduleCards";
import { useCampaignForm, useScheduleForm } from "./campaignForm";
import { CampaignStatusPill } from "./campaignStatus";


/**
 * `/c/{slug}/campaigns/{id}`: ONE CAMPAIGN, at its own address (D-773).
 *
 * Header: its name, its state (a paused campaign says why, a running one that will ring
 * nobody says "Not calling"), the facts it dials under, and the controls its state allows.
 * Then the one thing its state asks for: a draft's people and launch checklist, or a
 * launched campaign's results and the people with what happened to each.
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
    <div className="max-w-5xl space-y-8 pb-12">
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
        description={<Facts progress={data} />}
        actions={
          <HeaderActions
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
          <AddPeople campaignId={campaignId} canWrite={write.allowed} refusal={refusal} />
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

      <Section title={launched ? "People" : "Who will be called"}>
        <ContactResults
          slug={slug}
          campaignId={campaignId}
          maxAttempts={data.retry_policy.max_attempts}
          live={live}
          editable={!launched}
          canWrite={write.allowed}
          refusal={refusal}
        />
      </Section>
    </div>
  );
}

/** What the campaign dials under, in one line: kind, agent, number, hours, pace, retries. */
function Facts({ progress }: { progress: CampaignProgress }) {
  const hours = progress.calling_hours;
  const pace =
    progress.effective_concurrency < progress.concurrency
      ? `up to ${progress.effective_concurrency} at once (set to ${progress.concurrency}; your plan and the lines kept free allow ${progress.effective_concurrency})`
      : `up to ${progress.concurrency} at once`;
  return (
    <span>
      {[
        progress.classification === "promotional" ? "Promotional" : progress.classification === "service" ? "Service" : progress.classification,
        `${progress.agent_name} calls`,
        progress.number_e164 ? `from ${formatPhone(progress.number_e164)}` : "from the agent's own number",
        hours ? `${hours.start}–${hours.end} IST` : "9am–9pm IST",
        pace,
        describeRetry(progress.retry_policy),
      ].join(" · ")}
    </span>
  );
}

type Confirming = "stop" | "delete" | null;

/**
 * The controls this state allows, and nothing the server would refuse: Edit and Delete on
 * a draft; Pause on a running campaign; Resume on a paused one unless a complaint review is
 * still owed; Stop on anything still able to call; Duplicate always; Call again (the people
 * never reached) on a finished or stopped campaign. Stop and Delete restate what they do
 * before they act.
 */
function HeaderActions({
  slug,
  campaignId,
  progress,
  setStatus,
  canWrite,
  refusal,
  onGone,
  onCopied,
}: {
  slug: string;
  campaignId: string;
  progress: CampaignProgress;
  setStatus: ReturnType<typeof usePauseCampaign>;
  canWrite: boolean;
  refusal: string | undefined;
  onGone: () => void;
  onCopied: (id: string) => void;
}) {
  const { session, href } = useClientRealm();
  const stop = useStopCampaign(session, campaignId);
  const remove = useDeleteCampaign(session, campaignId);
  const duplicate = useDuplicateCampaign(session, campaignId);
  const [confirming, setConfirming] = useState<Confirming>(null);
  const status = progress.status;
  const finished = status === "completed" || status === "cancelled";
  const reviewOwed = progress.complaint_review_required;
  const remaining =
    (progress.contacts.pending ?? 0) + (progress.contacts.dialing ?? 0);

  return (
    <div className="flex flex-col items-end gap-3">
      <div className="flex flex-wrap justify-end gap-2">
        {status === "draft" && (
          <Link href={href(`/c/${slug}/campaigns/${campaignId}/edit`)} className={SECONDARY_BUTTON}>
            Edit
          </Link>
        )}
        {status === "running" && (
          <button type="button" title={refusal} disabled={!canWrite || setStatus.isPending} onClick={() => setStatus.mutate("pause")} className={SECONDARY_BUTTON}>
            <Pause aria-hidden className="h-3.5 w-3.5" />
            Pause
          </button>
        )}
        {status === "paused" && (
          <button
            type="button"
            title={reviewOwed ? "Confirm you have reviewed the opt-outs first." : refusal}
            disabled={!canWrite || setStatus.isPending || reviewOwed}
            onClick={() => setStatus.mutate("resume")}
            className={SECONDARY_BUTTON}
          >
            <Play aria-hidden className="h-3.5 w-3.5" />
            Resume
          </button>
        )}
        <button
          type="button"
          title={refusal}
          disabled={!canWrite || duplicate.isPending}
          onClick={() => duplicate.mutate({ with_unreached: false }, { onSuccess: (copy) => onCopied(copy.id) })}
          className={SECONDARY_BUTTON}
        >
          Duplicate
        </button>
        {finished && (
          <button
            type="button"
            title={refusal}
            disabled={!canWrite || duplicate.isPending}
            onClick={() => duplicate.mutate({ with_unreached: true }, { onSuccess: (copy) => onCopied(copy.id) })}
            className={SECONDARY_BUTTON}
          >
            Call the unreached again
          </button>
        )}
        {(status === "running" || status === "paused" || status === "scheduled") && (
          <button type="button" title={refusal} disabled={!canWrite} onClick={() => setConfirming("stop")} className={SECONDARY_BUTTON}>
            Stop for good…
          </button>
        )}
        {status === "draft" && (
          <button type="button" title={refusal} disabled={!canWrite} onClick={() => setConfirming("delete")} className={SECONDARY_BUTTON}>
            Delete…
          </button>
        )}
      </div>
      {duplicate.error ? <ProblemNotice error={duplicate.error} /> : null}
      {confirming && (
        <div className={`${NOTICE_BASE} ${NOTICE_BAR.warn} max-w-md text-left`}>
          <p className="font-semibold">
            {confirming === "stop" ? "Stop this campaign for good?" : "Delete this draft?"}
          </p>
          <p className="text-ink-muted">
            {confirming === "stop"
              ? `Nobody else on the list is called${remaining ? ` (${formatCount(remaining)} still waiting)` : ""}. A call already ringing finishes. It can't be restarted; Duplicate makes a new draft from it.`
              : "The draft and its list are removed. If calls or records already name it, it is kept as stopped instead."}
          </p>
          {(stop.error || remove.error) && <ProblemNotice error={stop.error ?? remove.error} />}
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              disabled={stop.isPending || remove.isPending}
              onClick={() =>
                confirming === "stop"
                  ? stop.mutate(undefined, { onSuccess: () => setConfirming(null) })
                  : remove.mutate(undefined, { onSuccess: onGone })
              }
              className={DANGER_BUTTON}
            >
              {confirming === "stop" ? "Stop for good" : "Delete draft"}
            </button>
            <button type="button" onClick={() => setConfirming(null)} className={SECONDARY_BUTTON}>
              Keep it
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Add people to a draft: pasted, uploaded or typed (`ContactEditor`), or from the CRM
 * (`LeadPicker`). Both go to the server, which dedupes, keeps India numbers only, and
 * refuses once the campaign has started.
 */
function AddPeople({
  campaignId,
  canWrite,
  refusal,
}: {
  campaignId: string;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const { session } = useClientRealm();
  const form = useCampaignForm();
  const addContacts = useAddContacts(session, campaignId);
  const addLeads = useAddLeads(session, campaignId);
  const [filter, setFilter] = useState<LeadFilter>({ statuses: [], sources: [] });
  const pool = useLeadPool(session, filter, true);
  const { checked } = form;
  const result = addContacts.data ?? addLeads.data;
  return (
    <Disclosure title="Add people" subtitle="Paste or upload a list, or pick people from your leads, any time before it starts.">
      <div className="space-y-8">
        <div className="space-y-3">
          {addContacts.error && <ProblemNotice error={addContacts.error} />}
          <ContactEditor entries={form.contacts} onChange={form.setContacts} label="People to add" />
          <button
            type="button"
            title={refusal}
            disabled={!canWrite || addContacts.isPending || checked.ready.length === 0 || checked.refusal !== null}
            onClick={() => addContacts.mutate(checked.ready, { onSuccess: () => form.setContacts([]) })}
            className={SECONDARY_BUTTON}
          >
            <ListPlus aria-hidden className="h-4 w-4" />
            {addContacts.isPending ? "Adding…" : "Add these people"}
          </button>
        </div>
        <div className="space-y-3 border-t border-line pt-6">
          <h3 className="text-body font-semibold text-ink">From your leads</h3>
          {addLeads.error && <ProblemNotice error={addLeads.error} />}
          <LeadPicker value={filter} onChange={setFilter} />
          <button
            type="button"
            title={refusal}
            disabled={!canWrite || addLeads.isPending || !leadPoolFits(pool.data?.matching, pool.data?.limit)}
            onClick={() => addLeads.mutate({ filter })}
            className={SECONDARY_BUTTON}
          >
            {addLeads.isPending
              ? "Adding…"
              : pool.data
                ? `Add ${formatCount(pool.data.matching)} ${pool.data.matching === 1 ? "lead" : "leads"}`
                : "Add leads"}
          </button>
        </div>
        {result && (
          <p role="status" className="text-meta text-ink-muted">
            Added {formatCount(result.added)}.
            {result.duplicate > 0 && ` ${formatCount(result.duplicate)} were already on the list.`}
            {result.malformed > 0 && ` ${formatCount(result.malformed)} numbers couldn't be read and were skipped.`}
            {(result.foreign ?? 0) > 0 && ` ${formatCount(result.foreign ?? 0)} numbers outside India were skipped.`}
          </p>
        )}
      </div>
    </Disclosure>
  );
}
