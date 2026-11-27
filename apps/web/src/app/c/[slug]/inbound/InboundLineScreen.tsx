"use client";

/**
 * `/c/{slug}/inbound/{id}`: ONE INBOUND LINE (D-997). The business and its work are the
 * centre; the agent is only the voice. The page follows the campaign page: a header with the
 * name (renamed in place) and the line's state, today's calls with the one button for whoever is
 * still waiting (`LineToday`), then coloured fold sections in the order an
 * owner sets a line up: Voice, Main task, Sources, Script, Actions, Outside hours, Numbers,
 * Test call, Calls taken, Improve, Archive.
 *
 * Saving the script puts it live, as does any edit to what a live line's callers hear. When
 * the platform step fails the edit is still saved (the refusal is titled "Saved, but not live
 * yet"), so the header offers Put it live, on a line that still reads as live too.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import { ActionButton, problemToast, useActionFeedback } from "@/components/arc/feedback";
import { ExpandableText } from "@/components/arc/expandable-text";
import { InlineEdit } from "@/components/arc/inline-edit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { PageHeader } from "@/components/console/pageHeader";
import { TEXT_ACTION, TEXT_ACTION_SM } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { DiagnoseCards } from "@/components/improve/DiagnoseCards";
import { GiveCallersTimeCard } from "@/components/improve/GiveCallersTimeCard";
import { SHORTER_ASK, ScriptDraftLive } from "@/components/scriptDraft/ScriptDraftLive";
import { TooLongDraft } from "@/components/scriptDraft/ScriptDraftView";
import { ScriptSizeMeter, scriptSizeOf } from "@/components/scriptDraft/ScriptSizeMeter";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
  formatDuration,
  formatIST,
  formatPhone,
} from "@/components/ui";
import { useAgentActions } from "@/lib/api/actions";
import { LINE_TEST_ANCHOR } from "@/lib/api/agentJobs";
import { useAgents } from "@/lib/api/agents";
import { DAYS, DAY_LABELS, useBusinessProfile } from "@/lib/api/businessProfile";
import { useCampaignNumbers } from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  isSavedNotLive,
  useArchiveInboundLine,
  useAssignLineNumber,
  useClearLineProposal,
  useInboundLine,
  useInboundLines,
  useLineAwaitsPutLive,
  useLineCalls,
  useLineTestCall,
  useLineTestCalls,
  useLineTestNumbers,
  usePublishInboundLine,
  useRequestLineScript,
  useRestoreLineScript,
  useSaveLineScript,
  useSetLineActions,
  useSetLineSources,
  useUpdateInboundLine,
  type InboundLine,
} from "@/lib/api/inboundLines";
import { todayOf, useInboundToday } from "@/lib/api/inboundToday";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";
import { useScriptVersions } from "@/lib/api/scriptVersions";
import { useClientRealm } from "@/lib/api/session";
import { endingLabel } from "@/lib/callReview";

import { LeftOutNotice, lineWarningsOf } from "../agents/[agentId]/script/PipProposal";
import type { PartKey } from "../agents/[agentId]/script/scriptDiff";
import { ChecksUnread, ScriptNeedsFix } from "@/components/scriptChecks/ScriptNeedsFix";
import {
  SHOW_FINDING_EVENT,
  findingWarnings,
  isPromptTooLong,
  isScriptNeedsFix,
  useScriptChecks,
} from "@/lib/api/scriptChecks";
import { TestCallForm } from "../campaigns/CampaignBoosters";
import { ScriptSummary } from "../campaigns/CampaignWorkspace";
import { JobNotes, lineNotesTakeEffect } from "../campaigns/CampaignNotes";
import { FoldGroup, FoldSection } from "../campaigns/FoldSection";
import { JobAlerts } from "../campaigns/JobAlerts";
import { TestCallRows } from "../campaigns/TestCallList";
import { SlotsFullProblem, isSlotsFull } from "../campaigns/SlotHolders";
import { GENERATE_LABEL, PipGenerateBand } from "../campaigns/PipGenerateBand";
import { jobBack } from "../campaigns/jobBack";
import { PipFailed, PipWriting, retryable } from "../campaigns/PipScriptStatus";
import { ScriptVersions, restoredToast } from "../campaigns/ScriptVersions";
import { SourcePicker, useChosenCount } from "../campaigns/SourcePicker";

import { CallBackButton, MissedCallBackSwitch, TodayCounts } from "./LineToday";
import { LineStatusPill, lineState } from "./lineStatus";
import { MAIN_TASK_MAX_CHARS } from "@/lib/textLimits";

// Drawn only while Pip's draft waits or the script is being edited: their own chunks.
const ProposalReview = dynamic(
  () => import("../agents/[agentId]/script/ProposalReview").then((m) => m.ProposalReview),
  { loading: () => <Skeleton rows={4} /> },
);
const ScriptPartsEditor = dynamic(
  () => import("../agents/[agentId]/script/ScriptPartsEditor").then((m) => m.ScriptPartsEditor),
  { loading: () => <Skeleton rows={4} /> },
);

// A line answers calls; it never places one, so the outbound parts are not offered. It has no
// call flow canvas, so its steps and opening line are edited in Edit script.
const OUTBOUND_PARTS: readonly PartKey[] = ["outbound_purpose", "outbound_opening_line"];

const NAME_MAX = 80;

export const VOICE_INFO = "The agent gives the line its voice. Changing it updates a live line at once.";
export const MAIN_TASK_INFO = "Write it in your own words, as much as you like. Pip writes the script from it.";
const MAIN_TASK_PLACEHOLDER = "For example: answer questions about our services and book a visit.";
export const SOURCES_INFO = "Pick from What your agents know. Pip reads them when it writes the script.";
export const SCRIPT_INFO = "Pip writes it from what this line is for and its files and notes. Saving puts it live on this line.";
const SCRIPT_LOCKED = "You can't change this line's script.";
export const ACTIONS_INFO = "Actions are set up on the agent. Switch off the ones this line should not use.";
export const NUMBERS_INFO = "A number answers with one line. Adding it here moves it from its old line.";
export const ARCHIVE_INFO = "A line that still answers a number cannot be archived. Move its numbers first.";
const ARCHIVE_BLOCKED = "Move its numbers to another line first.";
export const TEST_CALL_INFO = "It uses this line's saved script, so you hear what callers will. It works before the line has a number.";

type Props = { line: InboundLine; canWrite: boolean; refusal?: string };

export function InboundLineScreen({ slug, lineId }: { slug: string; lineId: string }) {
  const { session, href } = useClientRealm();
  const line = useInboundLine(session, lineId);
  const write = useWriteAccess(session, "org:manage", "change inbound lines");
  // A test call rings a phone, the campaign test call's permission.
  const canTest = useWriteAccess(session, "leads:dispatch", "place test calls");
  const refusal = write.allowed ? undefined : (write.reason ?? undefined);
  const rename = useUpdateInboundLine(session, lineId);
  const renameFeedback = useActionFeedback(rename, { errorDisplay: "inline" });
  const publish = usePublishInboundLine(session, lineId);
  const publishFeedback = useActionFeedback(publish, { errorTitle: "Not live yet", successToast: "The line is live" });
  const awaitsPutLive = useLineAwaitsPutLive(session, lineId);
  const from = useSearchParams().get("from");
  const list = { href: href(`/c/${slug}/inbound`), label: "All inbound lines" };
  const back = jobBack({
    from,
    agentId: line.data?.agent_id,
    agentName: line.data?.agent_name,
    list,
    agentHref: (id) => href(`/c/${slug}/agents/${id}`),
  });

  if (line.isLoading) {
    return (
      <div className="max-w-5xl space-y-5 pb-12">
        <PageHeader back={back} title="Inbound line" />
        <Skeleton rows={4} label="Loading the line" />
      </div>
    );
  }
  if (!line.data) {
    return (
      <div className="max-w-5xl space-y-5 pb-12">
        <PageHeader back={back} title="Inbound line" />
        <ProblemNotice error={line.error ?? new Error("This line did not load.")} onRetry={() => line.refetch()} />
      </div>
    );
  }
  const data = line.data;
  const props: Props = { line: data, canWrite: write.allowed, refusal };

  return (
    <div className="max-w-5xl space-y-6 pb-12">
      <PageHeader
        back={back}
        title={
          <InlineEdit
            value={data.name}
            label="Line name"
            textClassName="text-xl font-semibold tracking-tight"
            maxLength={NAME_MAX}
            wrap
            disabled={!write.allowed}
            status={renameFeedback.status}
            errorMessage={problemToast(rename.error, "That name did not save").description}
            validate={(next) => (next.trim() ? null : "Give the line a name.")}
            onSave={(name) => renameFeedback.run({ name })}
          />
        }
        status={<LineStatusPill line={data} />}
        actions={
          lineState(data) === "not_live" || awaitsPutLive ? (
            <ActionButton
              status={publishFeedback.status}
              pendingLabel="Putting it live…"
              successLabel="Live"
              disabled={!write.allowed}
              title={refusal}
              onClick={() => publishFeedback.run(undefined)}
            >
              Put it live
            </ActionButton>
          ) : undefined
        }
      />
      <LineTodayBar slug={slug} lineId={data.id} />
      <RestrictionNote reason={write.reason} />
      {/* No free calling setup: what holds each one, as links (the toast cannot). */}
      <SlotsFullProblem slug={slug} error={publish.error} />
      {isScriptNeedsFix(publish.error) && (
        <ScriptNeedsFix holder={{ kind: "line", id: data.id }} canWrite={write.allowed} refusal={refusal} />
      )}

      <FoldGroup className="space-y-8">
        <VoiceSection {...props} />
        <MainTaskSection {...props} />
        <SourcesSection {...props} />
        <ScriptSection {...props} />
        <JobNotes
          kind="line"
          jobId={data.id}
          canWrite={write.allowed}
          refusal={refusal}
          takeEffect={lineNotesTakeEffect}
        />
        <JobAlerts kind="line" jobId={data.id} />
        <ActionsSection {...props} slug={slug} />
        <OutsideHoursSection slug={slug} lineId={data.id} />
        <NumbersSection
          {...props}
          putLive={() => publishFeedback.run(undefined)}
          puttingLive={publish.isPending}
        />
        <TestCallSection line={data} slug={slug} canWrite={canTest.allowed} refusal={canTest.reason ?? undefined} />
        <CallsSection line={data} slug={slug} />
        <FoldSection id="line-improve" title="Improve" tone="results" hint="Where its calls lose people, and the fixes.">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <DiagnoseCards slug={slug} holder={{ kind: "inbound_line", id: data.id }} canWrite={write.allowed} refusal={refusal} />
            <GiveCallersTimeCard slug={slug} holder={{ kind: "inbound_line", id: data.id }} canWrite={write.allowed} refusal={refusal} />
          </div>
        </FoldSection>
        <ArchiveSection {...props} slug={slug} />
      </FoldGroup>
    </div>
  );
}

function VoiceSection({ line, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  const update = useUpdateInboundLine(session, line.id);
  const feedback = useActionFeedback(update, { errorDisplay: "inline", successToast: "Voice changed" });
  const awaitsPutLive = useLineAwaitsPutLive(session, line.id);
  const offered = (agents.data ?? []).filter((agent) => agent.status !== "archived" || agent.id === line.agent_id);
  return (
    <FoldSection id="line-voice" title="Voice" tone="agent" hint="Which agent answers on this line." info={VOICE_INFO}>
      {agents.isLoading ? (
        <Skeleton rows={1} label="Loading your agents" />
      ) : !agents.data ? (
        <ProblemNotice error={agents.error ?? new Error("Your agents did not load.")} onRetry={() => agents.refetch()} />
      ) : (
        <div className="space-y-2">
          <label className={FIELD_LABEL} htmlFor={`${line.id}-voice`}>
            Agent
          </label>
          <select
            id={`${line.id}-voice`}
            className={`${FIELD} w-full sm:w-80`}
            value={line.agent_id}
            disabled={!canWrite || update.isPending}
            title={refusal}
            onChange={(event) => feedback.run({ agent_id: event.target.value })}
          >
            {offered.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
          {update.error != null && (awaitsPutLive || !isSavedNotLive(update.error)) && (
            <ProblemNotice error={update.error} />
          )}
        </div>
      )}
    </FoldSection>
  );
}

function MainTaskSection({ line, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const [editing, setEditing] = useState(line.main_task.trim() === "");
  const [text, setText] = useState(line.main_task);
  const save = useUpdateInboundLine(session, line.id);
  useActionFeedback(save, { errorDisplay: "inline" });
  const dirty = text.trim() !== line.main_task.trim();
  const cancel = () => {
    setText(line.main_task);
    save.reset();
    setEditing(line.main_task.trim() === "");
  };
  return (
    <FoldSection id="line-main-task" title="What this line is for" tone="task" hint="What should this line do for callers?" info={MAIN_TASK_INFO}>
      {editing ? (
        <>
          <label htmlFor={`${line.id}-main-task`} className="sr-only">
            What this line is for
          </label>
          <textarea
            id={`${line.id}-main-task`}
            className={`${FIELD} min-h-36 w-full resize-y`}
            value={text}
            maxLength={MAIN_TASK_MAX_CHARS}
            disabled={!canWrite}
            title={refusal}
            placeholder={MAIN_TASK_PLACEHOLDER}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <ActionButton
              variant="primary-sm"
              status={save.isPending ? "pending" : "idle"}
              pendingLabel="Saving…"
              disabled={!canWrite || !text.trim() || !dirty}
              title={refusal}
              onClick={() => save.mutate({ main_task: text }, { onSuccess: () => setEditing(false) })}
            >
              Save
            </ActionButton>
            {line.main_task.trim() !== "" && (
              <ActionButton variant="secondary-sm" disabled={save.isPending} onClick={cancel}>
                Cancel
              </ActionButton>
            )}
          </div>
          {save.error != null && (
            <div className="mt-2">
              <ProblemNotice error={save.error} />
            </div>
          )}
        </>
      ) : (
        <>
          <ExpandableText
            lines={6}
            moreLabel="Show more"
            lessLabel="Show less"
            className="text-body text-ink"
            textClassName="whitespace-pre-wrap [overflow-wrap:anywhere]"
          >
            {line.main_task}
          </ExpandableText>
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} mt-3`}
            disabled={!canWrite}
            title={refusal}
            onClick={() => {
              setText(line.main_task);
              save.reset();
              setEditing(true);
            }}
          >
            Edit
          </button>
        </>
      )}
    </FoldSection>
  );
}

function SourcesSection({ line, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const save = useSetLineSources(session, line.id);
  useActionFeedback(save, { errorDisplay: "inline", successToast: "Files and notes saved" });
  const count = useChosenCount(line.source_ids);

  return (
    <FoldSection
      id="line-sources"
      title="Files and notes it can use"
      tone="materials"
      hint="What Pip reads to write this line's script."
      info={SOURCES_INFO}
      aside={count > 0 ? `${count} chosen` : undefined}
    >
      <SourcePicker
        saved={line.source_ids}
        legend="Files and notes for this line"
        canWrite={canWrite}
        refusal={refusal}
        save={save}
      />
    </FoldSection>
  );
}

function ScriptSection({ line, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const clear = useClearLineProposal(session, line.id);
  const save = useSaveLineScript(session, line.id);
  const ask = useRequestLineScript(session, line.id);
  const awaitsPutLive = useLineAwaitsPutLive(session, line.id);
  const stopFeedback = useActionFeedback(clear, { errorTitle: "Could not stop Pip" });
  const askFeedback = useActionFeedback(ask, { errorDisplay: "inline" });
  useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved and live" });
  const restore = useRestoreLineScript(session, line.id);
  const restoreFeedback = useActionFeedback(restore, { errorDisplay: "inline", successToast: restoredToast });
  const versions = useScriptVersions(session, { kind: "line", id: line.id }, line.script, line.script != null);
  const [editing, setEditing] = useState(false);
  //: The draft the owner chose to review part by part instead of in the live view.
  const [reviewing, setReviewing] = useState<string | null>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const proposal = line.proposal;
  const script = line.script;

  const hasTask = line.main_task.trim() !== "";
  const drafting = proposal?.status === "drafting";
  // The saved script's checks, each on its line in Edit script (`script_gate`).
  const checks = useScriptChecks(session, { kind: "line", id: line.id }, script);
  const size = scriptSizeOf(checks.data);
  const warnings = useMemo(
    () => (checks.isSuccess ? findingWarnings(checks.data.findings) : []),
    [checks.isSuccess, checks.data],
  );
  // "Show me" from a refusal: open Edit script on the flagged part, which scrolls to its line.
  const [showing, setShowing] = useState<{ stageId: string | null } | null>(null);
  useEffect(() => {
    const show = (event: Event) => {
      if (!script) return;
      setEditing(true);
      setShowing({ stageId: (event as CustomEvent<{ stageId: string | null }>).detail?.stageId ?? null });
    };
    window.addEventListener(SHOW_FINDING_EVENT, show);
    return () => window.removeEventListener(SHOW_FINDING_EVENT, show);
  }, [script]);
  const failed = proposal?.status === "failed";

  const closeEditor = () => {
    setEditing(false);
    setShowing(null);
    window.requestAnimationFrame(() => {
      const section = document.getElementById("line-script");
      if (section && section.getBoundingClientRect().top < 0) section.scrollIntoView({ block: "start" });
      editButton.current?.focus({ preventScroll: true });
    });
  };
  // The draft kept is settled by the same save (`proposal_id`), so nothing is cleared after.
  const keep = (next: CallScript, proposalId?: string) =>
    save.mutate({ script: next, proposalId }, { onSuccess: closeEditor });

  const reason = !hasTask
    ? "Save what this line is for first."
    : proposal?.status === "ready"
      ? "Review Pip's script below first."
      : failed
        ? "Pip's last try did not finish. See why below."
        : undefined;

  // Pip's written draft, part by part: what the live view falls back to, and what "Review
  // part by part" opens in its place.
  const readyReview =
    proposal?.status === "ready" && proposal.script ? (
      <div className="border-y border-line py-4">
        <ProposalReview
          key={proposal.id}
          current={script ?? EMPTY_SCRIPT}
          base={proposal.base_script ?? EMPTY_SCRIPT}
          proposal={proposal.script}
          notes={proposal.why}
          warnings={lineWarningsOf(proposal.left_out)}
          pending={save.isPending ? "apply" : clear.isPending ? "discard" : null}
          onApply={(next) => keep(next, proposal.id)}
          onDiscard={() => stopFeedback.run(proposal.id)}
        >
          {proposal.fixes && (
            <p className="text-sm text-ink [overflow-wrap:anywhere]">Written to fix a mistake on calls: {proposal.fixes}.</p>
          )}
          {proposal.disclosure && <p className="text-meta text-ink-muted">{proposal.disclosure}</p>}
          {proposal.left_out.length > 0 && <LeftOutNotice parts={proposal.left_out} />}
        </ProposalReview>
      </div>
    ) : null;
  const liveDraft =
    proposal != null && (proposal.status === "drafting" || readyReview !== null) && reviewing !== proposal.id;

  return (
    <FoldSection id="line-script" title="Script" tone="script" hint="What the agent says on this line." info={SCRIPT_INFO}>
      <div className="mb-4 space-y-2">
        <PipGenerateBand
          onGenerate={() => askFeedback.run(undefined)}
          busy={ask.isPending || drafting}
          disabled={!canWrite || !hasTask || (proposal != null && !(failed && retryable(proposal.reason)))}
          reason={reason}
          refusal={refusal}
          label={failed ? "Try again" : GENERATE_LABEL}
          inline
        />
        {ask.error != null && <ProblemNotice error={ask.error} />}
      </div>

      {/* The retry a "Saved, but not live yet" refusal names is the header's Put it live;
          once that went through, the refusal is no longer true. */}
      {save.error != null && (awaitsPutLive || !isSavedNotLive(save.error)) && (
        <div className="mb-3">
          {isSlotsFull(save.error) ? (
            <SlotsFullProblem slug={session.orgSlug} error={save.error} />
          ) : isScriptNeedsFix(save.error) ? (
            <ScriptNeedsFix holder={{ kind: "line", id: line.id }} canWrite={canWrite} refusal={refusal} />
          ) : proposal?.status === "ready" && isPromptTooLong(save.error) ? (
            <TooLongDraft
              detail={save.error.message}
              shorter={{
                status: askFeedback.status,
                retryable: askFeedback.retryable,
                run: () => {
                  save.reset();
                  askFeedback.run(SHORTER_ASK);
                },
              }}
              discard={{ status: stopFeedback.status, retryable: stopFeedback.retryable, run: () => stopFeedback.run(proposal.id) }}
            />
          ) : (
            <ProblemNotice error={save.error} />
          )}
        </div>
      )}

      {/* PIP WRITING, LIVE, then its changes with Keep or Discard: the same view as the Pip
          panel. Without the draft stream, the page keeps its own line and review. */}
      {proposal && liveDraft && (
        <div className="py-2">
          <ScriptDraftLive
            key={proposal.id}
            session={session}
            holder={{ kind: "inbound_line", id: line.id }}
            proposalId={proposal.id}
            toastOutcome
            refusal={canWrite ? null : (refusal ?? SCRIPT_LOCKED)}
            fallback={
              proposal.status === "drafting" ? (
                <PipWriting proposal={proposal} stopping={clear.isPending} onStop={() => stopFeedback.run(proposal.id)} />
              ) : (
                readyReview
              )
            }
            extra={
              readyReview ? (
                <button type="button" className={TEXT_ACTION} onClick={() => setReviewing(proposal.id)}>
                  Review part by part
                </button>
              ) : null
            }
          />
        </div>
      )}

      {proposal?.status === "failed" && (
        <PipFailed
          proposal={proposal}
          canWrite={canWrite}
          retrying={ask.isPending}
          dismissing={clear.isPending}
          onRetry={() => askFeedback.run(undefined)}
          onDismiss={() => stopFeedback.run(proposal.id)}
        />
      )}

      {proposal && !liveDraft && readyReview}

      {!proposal && editing && (
        <div className="rounded-card border border-line bg-surface p-4">
          {checks.isError && <ChecksUnread onRetry={() => void checks.refetch()} />}
          <ScriptPartsEditor
            script={script ?? EMPTY_SCRIPT}
            leaveOut={OUTBOUND_PARTS}
            warnings={warnings}
            show={showing}
            saving={save.isPending}
            onSave={(next) => keep(next)}
            onClose={closeEditor}
          />
        </div>
      )}

      {!proposal && !editing && (
        <div>
          {script ? (
            <>
              {/* A line may be answered by a "both" agent, whose placed-call line is real (D-920). */}
              <ScriptSummary script={script} direction="both" />
              {size && (
                <div className="mt-3">
                  <ScriptSizeMeter size={size} />
                </div>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button
                  ref={editButton}
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={!canWrite}
                  title={refusal}
                  onClick={() => setEditing(true)}
                >
                  Edit script
                </button>
                <ScriptVersions
                  versions={versions.data}
                  noun="script"
                  readOnly={!canWrite}
                  dirty={false}
                  restore={restoreFeedback}
                  onRestore={(input) => restore.mutateAsync(input)}
                />
                {line.published_at && (
                  <span className="text-meta text-ink-muted">Live since {formatIST(line.published_at)}</span>
                )}
              </div>
            </>
          ) : (
            <p className="text-body text-ink-muted">
              {hasTask ? `No script yet. Press ${GENERATE_LABEL} above.` : "Say what this line is for first."}
            </p>
          )}
        </div>
      )}
    </FoldSection>
  );
}

function ActionsSection({ line, canWrite, refusal, slug }: Props & { slug: string }) {
  const { session, href } = useClientRealm();
  const actions = useAgentActions(session, line.agent_id);
  const save = useSetLineActions(session, line.id);
  const feedback = useActionFeedback(save, { errorTitle: "Could not change the action" });
  const setUp = href(`/c/${slug}/agents/${line.agent_id}?section=actions`);
  const tools = (actions.data?.tools ?? []).filter((tool) => tool.enabled);
  const flip = (name: string, on: boolean) => {
    const off = on ? line.actions_off.filter((x) => x !== name) : [...line.actions_off, name];
    feedback.run(off);
  };
  return (
    <FoldSection id="line-actions" title="Actions" tone="generate" hint="What the agent may do on this line." info={ACTIONS_INFO}>
      {actions.isLoading ? (
        <Skeleton rows={2} label="Loading the agent's actions" />
      ) : !actions.data ? (
        <ProblemNotice error={actions.error ?? new Error("The agent's actions did not load.")} onRetry={() => actions.refetch()} />
      ) : tools.length === 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-body text-ink-muted">{line.agent_name} has no actions yet.</p>
          <Link href={setUp} className={SECONDARY_BUTTON_SM}>
            Set up actions
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          <ul className="max-w-3xl space-y-1">
            {tools.map((tool) => (
              <li key={tool.id}>
                <ToggleSwitch
                  label={tool.name}
                  hint={tool.description || undefined}
                  checked={!line.actions_off.includes(tool.name)}
                  disabled={!canWrite || save.isPending}
                  onChange={(on) => flip(tool.name, on)}
                />
              </li>
            ))}
          </ul>
          <Link href={setUp} className={TEXT_ACTION_SM} title={refusal}>
            Change {line.agent_name}&apos;s actions
          </Link>
        </div>
      )}
    </FoldSection>
  );
}

/** Today's calls and the one button for whoever is still waiting, above the set-up folds. */
function LineTodayBar({ slug, lineId }: { slug: string; lineId: string }) {
  const { session } = useClientRealm();
  const today = useInboundToday(session);
  const counts = todayOf(today.data, lineId);
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
      <TodayCounts slug={slug} lineId={lineId} day={today.data?.day} today={counts} failed={today.isError} />
      <CallBackButton slug={slug} lineId={lineId} waiting={counts?.waiting ?? 0} />
    </div>
  );
}

function OutsideHoursSection({ slug, lineId }: { slug: string; lineId: string }) {
  const { session, href } = useClientRealm();
  const profile = useBusinessProfile(session);
  const hours = profile.data?.hours ?? [];
  const byDay = new Map(hours.map((day) => [day.day, day]));
  return (
    <FoldSection id="line-hours" title="Outside hours" tone="settings" hint="Your opening hours, and calling back missed callers.">
      {profile.isLoading ? (
        <Skeleton rows={1} label="Loading your opening hours" />
      ) : !profile.data ? (
        <ProblemNotice error={profile.error ?? new Error("Your opening hours did not load.")} onRetry={() => profile.refetch()} />
      ) : (
        <div className="space-y-3">
          {hours.length === 0 ? (
            <p className="text-body text-ink-muted">No opening hours set yet.</p>
          ) : (
            <dl className="grid max-w-md grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-body">
              {DAYS.map((day) => {
                const entry = byDay.get(day);
                const text = !entry
                  ? "Not set"
                  : entry.closed
                    ? "Closed"
                    : `${entry.opens ?? "?"} to ${entry.closes ?? "?"}`;
                return (
                  <div key={day} className="contents">
                    <dt className="text-ink-muted">{DAY_LABELS[day]}</dt>
                    <dd className="tabular-nums text-ink">{text}</dd>
                  </div>
                );
              })}
            </dl>
          )}
          <Link href={href(`/c/${slug}/settings/business`)} className={SECONDARY_BUTTON_SM}>
            Change opening hours
          </Link>
        </div>
      )}
      <div className="mt-5 border-t border-line pt-4">
        <MissedCallBackSwitch slug={slug} lineId={lineId} />
      </div>
    </FoldSection>
  );
}

/**
 * A number on a line that is not live answers nobody (D-1019 D3): only a live line holds
 * what answers it, so each number says so and the section offers the one move that fixes
 * it. Putting the line live is the owner's press, never done for them. A live line in the
 * voice of an agent that is not taking calls answers nobody either, and says which agent.
 */
function NumbersSection({
  line,
  canWrite,
  refusal,
  putLive,
  puttingLive,
}: Props & { putLive: () => void; puttingLive: boolean }) {
  const { session, href } = useClientRealm();
  const numbers = useCampaignNumbers(session);
  const lines = useInboundLines(session);
  // A live line's numbers are answered only while its voice is taking calls
  // (`agents/service.route_line_numbers`): switched off, they ring nothing.
  const voice = useAgents(session).data?.find((agent) => agent.id === line.agent_id);
  const voiceOff = voice !== undefined && voice.status !== "live";
  const answering = line.live && !voiceOff;
  const assign = useAssignLineNumber(session, line.id);
  const feedback = useActionFeedback(assign, { errorDisplay: "inline", successToast: "Number added" });
  const [adding, setAdding] = useState(false);
  const [numberId, setNumberId] = useState("");

  const onThisLine = new Set(line.numbers.map((n) => n.id));
  // Which line each number answers with now, so the picker can say what a move takes from.
  const lineOf = new Map<string, string>();
  if (lines.data) {
    for (const other of lines.data) {
      for (const n of other.numbers) lineOf.set(n.id, other.name);
    }
  }
  const offered = (numbers.data ?? []).filter((n) => !onThisLine.has(n.id));
  const chosen = numberId || offered[0]?.id || "";
  const movesFrom = chosen ? lineOf.get(chosen) : undefined;

  return (
    <FoldSection
      id="line-numbers"
      title="Numbers"
      tone="people"
      hint="The numbers that answer with this line."
      info={NUMBERS_INFO}
      aside={line.numbers.length > 0 ? String(line.numbers.length) : undefined}
    >
      <div className="space-y-4">
        {line.numbers.length === 0 ? (
          <p className="text-body text-ink-muted">No number yet. Callers cannot reach this line.</p>
        ) : (
          <ul className="max-w-md divide-y divide-line border-y border-line">
            {line.numbers.map((n) => (
              <li key={n.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2.5 text-body text-ink">
                <span className="tabular-nums">{formatPhone(n.e164)}</span>
                {!answering && <StatusPill tone="warn">Not answering</StatusPill>}
              </li>
            ))}
          </ul>
        )}

        {line.live && voiceOff && line.numbers.length > 0 && (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-body text-ink-muted [overflow-wrap:anywhere]">
              {voice.name} is not taking calls, so callers hear nothing.
            </p>
            <Link href={href(`/c/${session.orgSlug}/agents/${voice.id}`)} className={SECONDARY_BUTTON_SM}>
              Open {voice.name}
            </Link>
          </div>
        )}

        {!line.live && line.numbers.length > 0 && (
          <div className="flex flex-wrap items-center gap-3">
            {line.script ? (
              <>
                <p className="text-body text-ink-muted">Callers hear nothing until this line is live.</p>
                <button
                  type="button"
                  className={PRIMARY_BUTTON_SM}
                  disabled={!canWrite || puttingLive}
                  title={refusal}
                  onClick={putLive}
                >
                  {puttingLive ? "Putting it live…" : "Put this line live"}
                </button>
              </>
            ) : (
              <>
                <p className="text-body text-ink-muted">Write the script, then put this line live.</p>
                <a href="#line-script" className={SECONDARY_BUTTON_SM}>
                  Write the script
                </a>
              </>
            )}
          </div>
        )}

        {!adding ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite}
            title={refusal}
            onClick={() => setAdding(true)}
          >
            Add a number
          </button>
        ) : numbers.isLoading || lines.isLoading ? (
          <Skeleton rows={1} label="Loading your numbers" />
        ) : !numbers.data ? (
          <ProblemNotice error={numbers.error ?? new Error("Your numbers did not load.")} onRetry={() => numbers.refetch()} />
        ) : lines.isError ? (
          // Without the lines we cannot say which line a number moves from.
          <ProblemNotice error={lines.error} onRetry={() => lines.refetch()} />
        ) : offered.length === 0 ? (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-body text-ink-muted">No other number to add.</p>
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setAdding(false)}>
              Close
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <label className={FIELD_LABEL} htmlFor={`${line.id}-add-number`}>
              Number
            </label>
            <select
              id={`${line.id}-add-number`}
              className={`${FIELD} w-full sm:w-80`}
              value={chosen}
              onChange={(event) => setNumberId(event.target.value)}
            >
              {offered.map((n) => (
                <option key={n.id} value={n.id}>
                  {formatPhone(n.e164)}
                  {lineOf.has(n.id) ? ` (now on ${lineOf.get(n.id)})` : ""}
                </option>
              ))}
            </select>
            {movesFrom && (
              <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">It moves from {movesFrom}.</p>
            )}
            <div className="flex flex-wrap gap-2">
              <ActionButton
                variant="primary-sm"
                status={assign.isPending ? "pending" : "idle"}
                pendingLabel="Adding…"
                disabled={!canWrite || !chosen}
                title={refusal}
                onClick={() =>
                  assign.mutate(chosen, {
                    onSuccess: () => {
                      setAdding(false);
                      setNumberId("");
                    },
                  })
                }
              >
                {movesFrom ? "Move it here" : "Add it"}
              </ActionButton>
              <ActionButton
                variant="secondary-sm"
                disabled={assign.isPending}
                onClick={() => {
                  assign.reset();
                  setAdding(false);
                }}
              >
                Cancel
              </ActionButton>
            </div>
            {feedback.error != null && <ProblemNotice error={feedback.error} />}
          </div>
        )}
      </div>
    </FoldSection>
  );
}

/** The line rings the owner's phone, as a caller would hear it; a draft line too. */
function TestCallSection({
  line,
  slug,
  canWrite,
  refusal,
}: {
  line: InboundLine;
  slug: string;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const call = useLineTestCall(session, line.id);
  useActionFeedback(call, { errorDisplay: "inline" });
  const saved = useLineTestNumbers(session, line.id);
  const calls = useLineTestCalls(session, line.id);
  return (
    <FoldSection id={LINE_TEST_ANCHOR} title="Test call" tone="test" hint="This line rings your phone." info={TEST_CALL_INFO}>
      {line.script ? (
        <TestCallForm
          slug={slug}
          call={call}
          saved={saved}
          canWrite={canWrite}
          refusal={refusal}
          ringsFrom={{ agentId: line.agent_id, lineId: line.id }}
        />
      ) : (
        <p className="text-body text-ink-muted">Write the script first, then hear it here.</p>
      )}
      <TestCallRows slug={slug} calls={calls} canWrite={canWrite} refusal={refusal} />
    </FoldSection>
  );
}

function CallsSection({ line, slug }: { line: InboundLine; slug: string }) {
  const { session, href } = useClientRealm();
  const calls = useLineCalls(session, line.id);
  return (
    <FoldSection id="line-calls" title="Calls taken" tone="progress" hint="The latest calls this line answered.">
      {calls.isLoading ? (
        <Skeleton rows={2} label="Loading this line's calls" />
      ) : !calls.data ? (
        <ProblemNotice error={calls.error ?? new Error("This line's calls did not load.")} onRetry={() => calls.refetch()} />
      ) : calls.data.length === 0 ? (
        <p className="text-body text-ink-muted">No calls yet.</p>
      ) : (
        <>
        <ul aria-label="Calls this line took" className="max-w-3xl divide-y divide-line border-y border-line">
          {calls.data.map((call) => (
            <li key={call.id} className="relative flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3">
              <Link
                href={href(`/c/${slug}/calls/${call.id}`)}
                className="text-body font-medium text-ink after:absolute after:inset-0 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                {call.started_at ? formatIST(call.started_at) : "Not started"}
              </Link>
              <span className="text-meta tabular-nums text-ink-muted">
                {endingLabel(call.outcome_tag ?? call.status)} · {formatDuration(call.duration_s)}
              </span>
            </li>
          ))}
        </ul>
        {/* This list stops at the latest 50; the call log holds every one (D-1006). */}
        <p className="mt-3">
          <Link href={href(`/c/${slug}/calls?inbound_line_id=${encodeURIComponent(line.id)}`)} className={TEXT_ACTION}>
            All its calls
          </Link>
        </p>
        </>
      )}
    </FoldSection>
  );
}

function ArchiveSection({ line, canWrite, refusal, slug }: Props & { slug: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const archive = useArchiveInboundLine(session, line.id);
  const feedback = useActionFeedback(archive, { errorDisplay: "inline", successToast: "Line archived" });
  const [confirming, setConfirming] = useState(false);
  // The api refuses to archive a line that still answers a number (`line_answers_numbers`).
  const answersNumbers = line.numbers.length > 0;
  return (
    <FoldSection
      id="line-archive"
      title="Archive"
      tone="details"
      hint="Stop using this line."
      info={ARCHIVE_INFO}
      defaultOpen={false}
    >
      {answersNumbers && <p className="mb-2 text-meta text-ink-muted">{ARCHIVE_BLOCKED}</p>}
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={!canWrite || answersNumbers}
        title={canWrite && answersNumbers ? ARCHIVE_BLOCKED : refusal}
        onClick={() => setConfirming(true)}
      >
        Archive this line
      </button>
      {confirming && (
        <ConfirmDialog
          title="Archive this line?"
          confirmLabel="Archive"
          pendingLabel="Archiving"
          cancelLabel="Keep it"
          status={feedback.status}
          error={feedback.error ?? null}
          onCancel={() => {
            feedback.reset();
            setConfirming(false);
          }}
          onConfirm={() => archive.mutate(undefined, { onSuccess: () => router.push(href(`/c/${slug}/inbound`)) })}
        >
          <span className="block">Its calls stay in your call logs.</span>
        </ConfirmDialog>
      )}
    </FoldSection>
  );
}
