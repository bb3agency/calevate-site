"use client";

import { useState } from "react";

import { ProblemNotice, RestrictionNote } from "@/components/ui";
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
import { NewCampaignForm } from "./NewCampaignForm";
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
 * `scheduleCopy.tsx`, `ConsentProvenance.tsx`, `CampaignList.tsx`, `NewCampaignForm.tsx`,
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

  const [campaignId, setCampaignId] = useState<string | null>(null);
  const form = useCampaignForm();
  const scheduleForm = useScheduleForm();
  const { name, numberId, csv } = form;

  /**
   * D-22 read-only, applied to the controls rather than discovered on click. All four
   * mutating steps on this screen — create, add contacts, launch, pause/resume — are
   * `leads:dispatch` (campaigns/routes.py), which is a MUTATING permission: `staff`
   * does not hold it, and an impersonating operator is refused it however senior they
   * are. The note is rendered once at the top rather than four times, because the
   * reason is the same one every time; the launch control is the single exception and
   * says why at its own call site. The server still refuses; every ProblemNotice below
   * stays.
   */
  const write = useWriteAccess(
    session,
    "leads:dispatch",
    "start or run campaigns",
  );
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
   * choice is ALWAYS on screen — not only when there is more than one. A campaign that
   * silently bound `agents[0]` was a campaign whose caller nobody chose, and with the
   * agents console able to mint a second agent in a minute, "there is only one" stopped
   * being a safe assumption the moment the form rendered.
   *
   * ARCHIVED AGENTS ARE NOT OFFERED, and that is the server's rule rather than taste:
   * `lifecycle.ASSIGNABLE_STATUSES` refuses one outright, because no amount of waiting
   * makes a campaign bound to a retired agent launchable. Every other state IS offered —
   * a draft agent is a legitimate choice while its script is being written, and
   * `launch_blockers` refuses the LAUNCH with `agent_not_live` until it is published,
   * which is a wait a client can act on rather than a dead end.
   */
  const agentOptions = (agents.data ?? []).filter(isAssignable);
  const selectedAgentId = form.agentId || agentOptions[0]?.id || "";
  const selectedAgent = agentOptions.find((option) => option.id === selectedAgentId);
  /**
   * This account has no agent — as a FACT FROM THE SERVER, not as "the list is empty
   * right now". `agentOptions` is also empty while `/v1/agents` is in flight and after
   * it has FAILED, and the sentence below it used to gate ("your account manager builds
   * one before campaigns can run") is a claim about this business's setup, on the screen
   * where an owner decides whether their campaigns can run at all. Rendered over a 503
   * it sends them to their account manager for an agent they already have.
   *
   * `!agents.isLoading` was not enough: a settled-and-failed query is not loading.
   * Same spelling as `hasNoAgents` two screens away in `/c/<slug>/knowledge` — the
   * repo already solved this and a fourth spelling is where the drift starts.
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
   * WHAT WOULD BE LOST IF THIS TAB RELOADED — see `lib/useUnsavedGuard.ts`.
   *
   * The contact list is the answer at every stage: it lives only in this textarea until
   * "Add contacts" succeeds, which is the one moment `csv` is cleared. Before the campaign
   * itself exists there is more — the name, the agent and the number are typed and unsent
   * — so both are asked. The schedule and repeat fields are deliberately NOT counted: they
   * carry defaults nobody typed, and a form that asked on the way out of an untouched
   * screen is the ask people learn to click through.
   */
  useUnsavedGuard(
    csv.trim() !== "" ||
      (campaignId === null &&
        (name.trim() !== "" || form.agentId !== "" || numberId !== "")),
  );

  const startAnother = () => {
    setCampaignId(null);
    form.reset();
  };

  return (
    <div className="space-y-5 pb-12">
      <p className="max-w-2xl text-sm text-ink-muted">
        Call a list of people. Calls go out between 9am and 9pm, numbers on the
        do-not-call list are never dialled, and anyone who doesn&apos;t answer
        is tried again later.
      </p>

      <RestrictionNote reason={write.reason} />

      {campaigns.error && (
        <ProblemNotice
          error={campaigns.error}
          onRetry={() => campaigns.refetch()}
        />
      )}
      {/* THE THREE READS THAT FAILED IN SILENCE.
          `campaigns`, `progress`, `check`, `create` all surfaced their refusals; the
          three lists the create form is BUILT FROM did not, so each failure degraded
          into something the screen stated as fact. Agents: the empty-state sentence
          above (see `hasNoAgents`). Numbers and templates: two `<select>`s holding
          nothing but "Choose a number…" / "Choose a template…", a client concluding
          their account has neither, and no refusal anywhere on the page to contradict
          it. A picker that cannot be filled is a dead form, and a dead form needs the
          reason next to it — the same argument `/c/<slug>/knowledge` makes for its own
          agents notice. Retryable, because all three are plain GETs. */}
      {agents.error && (
        <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />
      )}
      {numbers.error && (
        <ProblemNotice
          error={numbers.error}
          onRetry={() => numbers.refetch()}
        />
      )}
      {templates.error && (
        <ProblemNotice
          error={templates.error}
          onRetry={() => templates.refetch()}
        />
      )}
      {progress.error && (
        <ProblemNotice
          error={progress.error}
          onRetry={() => progress.refetch()}
        />
      )}
      {addContacts.error && <ProblemNotice error={addContacts.error} />}
      {launch.error && <ProblemNotice error={launch.error} />}
      {setStatus.error && <ProblemNotice error={setStatus.error} />}
      {/* A refused schedule is a refusal, never a silently unchanged form: the server
          names the reason (a start in the past, one beyond the horizon, a campaign that
          has already launched) and the client can only act on it if it is on screen. */}
      {schedule.error && <ProblemNotice error={schedule.error} />}
      {unschedule.error && <ProblemNotice error={unschedule.error} />}
      {/* A refused repeat is a refusal with something to do about it: a time outside
          calling hours, no day chosen, an end date before the first run. All three are
          named by the server and none of them is guessable from a form that simply does
          nothing. */}
      {repeat.error && <ProblemNotice error={repeat.error} />}

      {!campaignId && (
        <CampaignList campaigns={campaigns} onOpen={setCampaignId} />
      )}

      {!campaignId ? (
        <NewCampaignForm
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
          refusal={refusal}
          onCreated={setCampaignId}
        />
      ) : (
        <CampaignDetail
          campaignId={campaignId}
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
          onStartAnother={startAnother}
        />
      )}
    </div>
  );
}
