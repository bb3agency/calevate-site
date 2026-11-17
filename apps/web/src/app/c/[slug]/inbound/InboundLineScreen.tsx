"use client";

/**
 * `/c/{slug}/inbound/{id}`: ONE INBOUND LINE (D-997). The business and its work are the
 * centre; the agent is only the voice. The page follows the campaign page: a header with the
 * name (renamed in place) and the line's state, then coloured fold sections in the order an
 * owner sets a line up: Voice, Main task, Sources, Script, Actions, Outside hours, Numbers,
 * Test call, Calls taken, Archive.
 *
 * Saving the script puts it live. When the platform step fails the script is still saved
 * (the refusal is titled "Saved, but not live yet"), so the header offers Put it live.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ExpandableText } from "@/components/arc/expandable-text";
import { InlineEdit } from "@/components/arc/inline-edit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { PageHeader } from "@/components/console/pageHeader";
import { TEXT_ACTION, TEXT_ACTION_SM } from "@/components/console/section";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
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
  useArchiveInboundLine,
  useAssignLineNumber,
  useClearLineProposal,
  useInboundLine,
  useInboundLines,
  useLineCalls,
  useLineTestCall,
  useLineTestCalls,
  useLineTestNumbers,
  usePublishInboundLine,
  useRequestLineScript,
  useSaveLineScript,
  useSetLineActions,
  useSetLineSources,
  useUpdateInboundLine,
  type InboundLine,
} from "@/lib/api/inboundLines";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";
import { useClientRealm } from "@/lib/api/session";
import { endingLabel } from "@/lib/callReview";

import { LeftOutNotice } from "../agents/[agentId]/script/PipProposal";
import { ProposalReview } from "../agents/[agentId]/script/ProposalReview";
import { TestCallForm } from "../campaigns/CampaignBoosters";
import { ScriptSummary } from "../campaigns/CampaignWorkspace";
import { FoldGroup, FoldSection } from "../campaigns/FoldSection";
import { TestCallRows } from "../campaigns/TestCallList";
import { SlotsFullProblem, isSlotsFull } from "../campaigns/SlotHolders";
import { PipGenerateBand } from "../campaigns/PipGenerateBand";
import { PipFailed, PipWriting, retryable } from "../campaigns/PipScriptStatus";
import { SourcePicker } from "../campaigns/SourcePicker";

import { LineStatusPill, lineState } from "./lineStatus";

const NAME_MAX = 80;
const MAIN_TASK_MAX = 4000;

export const VOICE_INFO = "The agent gives the line its voice. Changing it updates a live line at once.";
export const MAIN_TASK_INFO = "Write it in your own words, as much as you like. Pip writes the script from it.";
const MAIN_TASK_PLACEHOLDER = "For example: answer questions about our services and book a visit.";
export const SOURCES_INFO = "Pick from What your agents know. Pip reads them when it writes the script.";
export const SCRIPT_INFO = "Pip writes it from your main task and sources. Saving puts it live on this line.";
export const ACTIONS_INFO = "Actions are set up on the agent. Switch off the ones this line should not use.";
export const NUMBERS_INFO = "A number answers with one line. Adding it here moves it from its old line.";
export const ARCHIVE_INFO = "A line that still answers a number cannot be archived. Move its numbers first.";
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
  const back = { href: href(`/c/${slug}/inbound`), label: "All inbound lines" };

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
            validate={(next) => (next.trim() ? null : "Give the line a name.")}
            onSave={(name) => renameFeedback.run({ name })}
          />
        }
        status={<LineStatusPill line={data} />}
        actions={
          lineState(data) === "not_live" ? (
            <button
              type="button"
              className={PRIMARY_BUTTON}
              disabled={!write.allowed || publish.isPending}
              title={refusal}
              onClick={() => publishFeedback.run(undefined)}
            >
              {publish.isPending ? "Putting it live…" : "Put it live"}
            </button>
          ) : undefined
        }
      />
      <RestrictionNote reason={write.reason} />
      {/* No free calling setup: what holds each one, as links (the toast cannot). */}
      <SlotsFullProblem slug={slug} error={publish.error} />

      <FoldGroup className="space-y-8">
        <VoiceSection {...props} />
        <MainTaskSection {...props} />
        <SourcesSection {...props} />
        <ScriptSection {...props} />
        <ActionsSection {...props} slug={slug} />
        <OutsideHoursSection slug={slug} />
        <NumbersSection {...props} />
        <TestCallSection line={data} slug={slug} canWrite={canTest.allowed} refusal={canTest.reason ?? undefined} />
        <CallsSection line={data} slug={slug} />
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
          {update.error != null && <ProblemNotice error={update.error} />}
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
    <FoldSection id="line-main-task" title="Main task" tone="task" hint="What should this line do for callers?" info={MAIN_TASK_INFO}>
      {editing ? (
        <>
          <label htmlFor={`${line.id}-main-task`} className="sr-only">
            Main task
          </label>
          <textarea
            id={`${line.id}-main-task`}
            className={`${FIELD} min-h-36 w-full resize-y`}
            value={text}
            maxLength={MAIN_TASK_MAX}
            disabled={!canWrite}
            title={refusal}
            placeholder={MAIN_TASK_PLACEHOLDER}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              disabled={!canWrite || !text.trim() || !dirty || save.isPending}
              title={refusal}
              onClick={() => save.mutate({ main_task: text }, { onSuccess: () => setEditing(false) })}
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {line.main_task.trim() !== "" && (
              <button type="button" className={SECONDARY_BUTTON_SM} disabled={save.isPending} onClick={cancel}>
                Cancel
              </button>
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
  useActionFeedback(save, { errorDisplay: "inline", successToast: "Sources saved" });
  const count = line.source_ids.length;

  return (
    <FoldSection
      id="line-sources"
      title="Sources"
      tone="materials"
      hint="What Pip reads to write this line's script."
      info={SOURCES_INFO}
      aside={count > 0 ? `${count} chosen` : undefined}
    >
      <SourcePicker
        saved={line.source_ids}
        legend="Sources for this line"
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
  const publish = usePublishInboundLine(session, line.id);
  useActionFeedback(publish, { errorDisplay: "inline", successToast: "The line is live" });
  const stopFeedback = useActionFeedback(clear, { errorTitle: "Could not stop Pip" });
  const askFeedback = useActionFeedback(ask, { errorDisplay: "inline" });
  useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved and live" });
  const [editing, setEditing] = useState(false);
  const editButton = useRef<HTMLButtonElement>(null);
  const proposal = line.proposal;
  const script = line.script;
  const hasTask = line.main_task.trim() !== "";
  const drafting = proposal?.status === "drafting";
  const failed = proposal?.status === "failed";

  const closeEditor = () => {
    setEditing(false);
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
    ? "Save the main task first."
    : proposal?.status === "ready"
      ? "Review Pip's script below first."
      : failed
        ? "Pip's last try did not finish. See why below."
        : undefined;

  return (
    <FoldSection id="line-script" title="Script" tone="script" hint="What the agent says on this line." info={SCRIPT_INFO}>
      <div className="mb-4 space-y-2">
        <PipGenerateBand
          onGenerate={() => askFeedback.run(undefined)}
          busy={ask.isPending || drafting}
          disabled={!canWrite || !hasTask || (proposal != null && !(failed && retryable(proposal.reason)))}
          reason={reason}
          refusal={refusal}
          label={failed ? "Try again" : "Generate"}
          inline
        />
        {ask.error != null && <ProblemNotice error={ask.error} />}
      </div>

      {save.error != null && (
        <div className="mb-3 space-y-2">
          {isSlotsFull(save.error) ? (
            <SlotsFullProblem slug={session.orgSlug} error={save.error} />
          ) : (
            <ProblemNotice error={save.error} />
          )}
          {/* A live line keeps its old "Live" state when only the platform step failed, so
              the header offers no Put it live; the retry the refusal names is here. */}
          {line.script && (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!canWrite || publish.isPending}
              title={refusal}
              onClick={() => publish.mutate(undefined, { onSuccess: () => save.reset() })}
            >
              {publish.isPending ? "Putting it live…" : "Put it live"}
            </button>
          )}
          {publish.error != null &&
            (isSlotsFull(publish.error) ? (
              <SlotsFullProblem slug={session.orgSlug} error={publish.error} />
            ) : (
              <ProblemNotice error={publish.error} />
            ))}
        </div>
      )}

      {proposal?.status === "drafting" && (
        <PipWriting proposal={proposal} stopping={clear.isPending} onStop={() => stopFeedback.run(proposal.id)} />
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

      {proposal?.status === "ready" && proposal.script && (
        <div className="border-y border-line py-4">
          <ProposalReview
            key={proposal.id}
            current={script ?? EMPTY_SCRIPT}
            base={proposal.base_script ?? EMPTY_SCRIPT}
            proposal={proposal.script}
            notes={proposal.why}
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
      )}

      {!proposal && editing && (
        <div className="rounded-card border border-line bg-surface p-4">
          <ProposalReview
            editing
            current={EMPTY_SCRIPT}
            proposal={script ?? EMPTY_SCRIPT}
            pending={save.isPending ? "apply" : null}
            onApply={(next) => keep(next)}
            onDiscard={closeEditor}
          />
        </div>
      )}

      {!proposal && !editing && (
        <div>
          {script ? (
            <>
              <ScriptSummary script={script} />
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
                {line.published_at && (
                  <span className="text-meta text-ink-muted">Live since {formatIST(line.published_at)}</span>
                )}
              </div>
            </>
          ) : (
            <p className="text-body text-ink-muted">
              {hasTask ? "No script yet. Press Generate above." : "Write the main task first."}
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

function OutsideHoursSection({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const profile = useBusinessProfile(session);
  const hours = profile.data?.hours ?? [];
  const byDay = new Map(hours.map((day) => [day.day, day]));
  return (
    <FoldSection id="line-hours" title="Outside hours" tone="settings" hint="Your opening hours, set once for the business.">
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
    </FoldSection>
  );
}

function NumbersSection({ line, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const numbers = useCampaignNumbers(session);
  const lines = useInboundLines(session);
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
              <li key={n.id} className="py-2.5 text-body tabular-nums text-ink">
                {formatPhone(n.e164)}
              </li>
            ))}
          </ul>
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
              <button
                type="button"
                className={PRIMARY_BUTTON_SM}
                disabled={!canWrite || !chosen || assign.isPending}
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
                {assign.isPending ? "Adding…" : movesFrom ? "Move it here" : "Add it"}
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={assign.isPending}
                onClick={() => {
                  assign.reset();
                  setAdding(false);
                }}
              >
                Cancel
              </button>
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
          fromTestLine={!line.live}
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
  return (
    <FoldSection
      id="line-archive"
      title="Archive"
      tone="details"
      hint="Stop using this line."
      info={ARCHIVE_INFO}
      defaultOpen={false}
    >
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={!canWrite}
        title={refusal}
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
