"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { PRIMARY_BUTTON, ProblemNotice, RestrictionNote } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useAddContacts,
  useCampaignNumbers,
  useCampaignProgress,
  useCampaigns,
  useCreateCampaign,
  useDltTemplates,
  useLaunchCampaign,
  useLaunchCheck,
  usePauseCampaign,
  useScheduleCampaign,
  useSetRecurrence,
  useUnscheduleCampaign,
} from "@/lib/api/campaigns";
import { useClientSession } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { isAssignable } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";

import { CampaignDetail } from "./CampaignDetail";
import { CampaignList } from "./CampaignList";
import { NewCampaignFlow } from "./NewCampaignFlow";
import { useCampaignForm, useScheduleForm } from "./campaignForm";
import { useCampaignsCopilotSurface } from "./campaignsCopilotSurface";

/**
 * Outbound campaigns (FLOWS §5, SURFACES §2b) — the screen, kept thin.
 *
 * PRIMARY JOB (UX-DOCTRINE §10): *get one list of people called, lawfully.* Everything
 * below is either the wiring for that or a refusal explaining why it cannot happen yet.
 *
 * The screen is built around one rule, and `LaunchGate.tsx` is where it is spelled:
 * **the launch button is disabled with its reasons on screen, not after a click.** The
 * API's `/launch-check` returns named blockers precisely so this page can list them as a
 * to-do; a generic "launch failed" toast would send the client to support instead of to
 * the fix. The client never sees a bypass, because there isn't one: `POST /launch`
 * re-runs the identical gate server-side (hard rule 5).
 *
 * ## What this module keeps, and why the rest left
 *
 * At 2,505 lines this was one file holding six subjects, which UX-DOCTRINE §6 names as a
 * hierarchy nobody can see. What stayed here is what genuinely belongs to the SCREEN and
 * cannot be pushed down:
 *
 * - the MUTATIONS. A `useMutation` is state, not a cache entry, so a second call to
 *   `useLaunchCampaign` would be a second, empty error channel — the `ProblemNotice`
 *   below would then never see the failure the button caused. They are declared once and
 *   handed to the component that fires them.
 * - the COPILOT SURFACE. `lib/copilot/registry.ts` makes the innermost registration the
 *   live one, so a screen gets exactly one, and this one names controls from both forms.
 * - the FORM STATE the surface reads (`campaignForm.ts`).
 * - the reads every child shares (`agents`, `numbers`, `templates`) and the §52 refusals
 *   they earn.
 *
 * The subjects that left, each to its own file: `blockerCopy.tsx`, `choices.tsx`,
 * `scheduleCopy.tsx`, `ConsentProvenance.tsx`, `CampaignList.tsx`, `NewCampaignFlow.tsx`,
 * `CampaignDetail.tsx`, `LaunchGate.tsx`.
 *
 * The screen renders no `<h1>`: the shell prints the page title from the nav list
 * (layout.tsx), and a second "Campaigns" beside it is a visible duplicate.
 */
export function CampaignsScreen() {
  const session = useClientSession();
  const agents = useAgents(session);

  const numbers = useCampaignNumbers(session);
  const templates = useDltTemplates(session);
  const campaigns = useCampaigns(session);

  /** Which view: the list, the new-campaign flow, or one campaign. */
  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  /** The parsed list waiting for its campaign to exist — see the effect below. */
  const [pendingContacts, setPendingContacts] = useState<
    { phone: string; name?: string }[] | null
  >(null);
  const [rowError, setRowError] = useState<unknown>(null);
  const form = useCampaignForm();
  const scheduleForm = useScheduleForm();
  const { name, numberId, csv } = form;

  /**
   * Every mutating step here is `leads:dispatch` (campaigns/routes.py), which `staff` does
   * not hold and a view-as operator does (D-587: dispatching a client's campaign is one of
   * an operator's support duties). The note is rendered once at the top; the server still
   * refuses, and every ProblemNotice below stays.
   */
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");
  /** The refusal as a control attribute, so a dead button explains itself on hover. */
  const refusal = write.allowed ? undefined : (write.reason ?? undefined);

  const create = useCreateCampaign(session);
  const addContacts = useAddContacts(session, campaignId);
  const check = useLaunchCheck(session, campaignId);
  const launch = useLaunchCampaign(session, campaignId);
  const progress = useCampaignProgress(session, campaignId);
  const setStatus = usePauseCampaign(session, campaignId);
  const schedule = useScheduleCampaign(session, campaignId);
  const unschedule = useUnscheduleCampaign(session, campaignId);
  const repeat = useSetRecurrence(session, campaignId);

  /**
   * Which agent dials decides the script, the voice and the disclosure line, so the
   * choice is always asked, even with one agent. Archived agents are not offered: the
   * server refuses binding one (`lifecycle.ASSIGNABLE_STATUSES`), and no wait makes such a
   * campaign launchable. A draft agent IS offered; the launch check refuses it by name
   * until it is published, which is a wait the client can plan for.
   */
  const agentOptions = (agents.data ?? []).filter(isAssignable);
  const selectedAgentId = form.agentId || agentOptions[0]?.id || "";
  const selectedAgent = agentOptions.find((option) => option.id === selectedAgentId);
  /**
   * "No agent" as a FACT FROM THE SERVER: `agentOptions` is also empty while the read is
   * in flight and after it failed, and the sentence this gates sends an owner to their
   * account manager for an agent they may already have.
   */
  const hasNoAgents = Boolean(agents.data) && agentOptions.length === 0;

  useCampaignsCopilotSurface({
    form,
    scheduleForm,
    agentOptions,
    selectedAgentId,
    numbers,
    templates,
  });

  /*
   * What a reload would lose: the pasted list until it is uploaded, and before the
   * campaign exists, the typed name, agent and number. Schedule fields carry defaults
   * nobody typed, so they are not counted.
   */
  useUnsavedGuard(
    csv.trim() !== "" ||
      (campaignId === null &&
        (name.trim() !== "" || form.agentId !== "" || numberId !== "")),
  );

  /**
   * THE SECOND HALF OF "CREATE CAMPAIGN". The contacts endpoint is per campaign, so the
   * list can only be sent once the create has answered with an id, and `useAddContacts`
   * is bound to the id this screen holds. Setting the id re-renders with the hook bound to
   * the new campaign; this effect then sends the list through it. On failure the screen
   * is already on the new draft, the error renders on its contacts panel, and the list
   * is still in the textarea (it is cleared only on success), so "Add contacts" retries.
   */
  useEffect(() => {
    if (!campaignId || !pendingContacts) return;
    setPendingContacts(null);
    addContacts.mutate(pendingContacts, { onSuccess: () => form.setCsv("") });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fires once per create
  }, [campaignId, pendingContacts]);

  const submitNew = () => {
    if (!selectedAgentId) return;
    const contacts = form.parsed;
    create.mutate(
      {
        agent_id: selectedAgentId,
        name,
        classification: form.classification,
        concurrency: form.concurrency,
        number_id: numberId || null,
        dlt_template_id: form.templateId || null,
        calling_hours: form.restrictHours
          ? { start: form.windowStart, end: form.windowEnd }
          : null,
        consent_provenance:
          form.consentSource && form.consentIso
            ? { source: form.consentSource, collected_at: form.consentIso }
            : null,
      },
      {
        onSuccess: (data) => {
          setCreating(false);
          setPendingContacts(contacts);
          setCampaignId(data.id);
        },
      },
    );
  };

  /**
   * Back to the list, with the AUDITED answers cleared: a second campaign's form must not
   * open with the last list's consent declaration pre-selected (`campaignForm.reset`).
   */
  const backToList = () => {
    setCampaignId(null);
    setCreating(false);
    create.reset();
    addContacts.reset();
    form.reset();
  };

  const startNew = () => {
    form.reset();
    create.reset();
    setCreating(true);
  };

  return (
    <div className="space-y-5 pb-12">
      {!campaignId && !creating && (
        <PageHeader
          description="Call a list of people with one of your agents."
          actions={
            <button
              type="button"
              onClick={startNew}
              disabled={!write.allowed}
              title={refusal}
              className={PRIMARY_BUTTON}
            >
              New campaign
            </button>
          }
        />
      )}

      <RestrictionNote reason={write.reason} />

      {campaigns.error && (
        <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} />
      )}
      {/* The three lists the create flow is BUILT from: a failure of any of them is a dead
          picker, and a dead picker needs its reason on the page, not "you have none". */}
      {agents.error && <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />}
      {numbers.error && <ProblemNotice error={numbers.error} onRetry={() => numbers.refetch()} />}
      {templates.error && (
        <ProblemNotice error={templates.error} onRetry={() => templates.refetch()} />
      )}
      {progress.error && <ProblemNotice error={progress.error} onRetry={() => progress.refetch()} />}
      {launch.error && <ProblemNotice error={launch.error} />}
      {setStatus.error && <ProblemNotice error={setStatus.error} />}
      {rowError != null && !campaignId && <ProblemNotice error={rowError} />}
      {/* A refused schedule or repeat names its reason (a start in the past, a time outside
          calling hours, no day chosen); none of them is guessable from a form that simply
          does nothing. */}
      {schedule.error && <ProblemNotice error={schedule.error} />}
      {unschedule.error && <ProblemNotice error={unschedule.error} />}
      {repeat.error && <ProblemNotice error={repeat.error} />}

      {campaignId ? (
        <CampaignDetail
          campaignId={campaignId}
          campaign={campaigns.data?.find((row) => row.id === campaignId)}
          form={form}
          scheduleForm={scheduleForm}
          progress={progress}
          check={check}
          addContacts={addContacts}
          launch={launch}
          setStatus={setStatus}
          schedule={schedule}
          unschedule={unschedule}
          repeat={repeat}
          canWrite={write.allowed}
          writeReason={write.reason}
          refusal={refusal}
          onBack={backToList}
        />
      ) : creating ? (
        <NewCampaignFlow
          form={form}
          agents={agents}
          agentOptions={agentOptions}
          selectedAgentId={selectedAgentId}
          selectedAgent={selectedAgent}
          hasNoAgents={hasNoAgents}
          numbers={numbers}
          templates={templates}
          create={create}
          canWrite={write.allowed}
          onSubmit={submitNew}
          onCancel={backToList}
        />
      ) : (
        <CampaignList
          campaigns={campaigns}
          onOpen={(id) => {
            setRowError(null);
            setCampaignId(id);
          }}
          canWrite={write.allowed}
          refusal={refusal}
          onRowError={setRowError}
        />
      )}
    </div>
  );
}
