"use client";

/**
 * A CAMPAIGN'S OWN WORK (D-992): what it should achieve, what it works from, and the script
 * its calls follow. The campaign owns what is said; the agent is the voice, and Start puts
 * only this script live on it.
 *
 * Three sections, each with its own colour so the eye keeps them apart:
 *  1. Main task — a green rule: the owner's words, many lines.
 *  2. Materials — a blue ground: documents, links and notes, including notes learned from
 *     the campaign's own calls (the Questions tab adds them).
 *  3. Script — a dark green rule: Pip writes it from 1 and 2, the owner reviews it part by
 *     part with the same Review / Update / Edit the agent Script page uses, and edits it any
 *     time. A rule rather than a green ground: a tinted card reads as a notice
 *     (`tests/noticeStyle.test.tsx`).
 */

import { useMemo, useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ExpandableText } from "@/components/arc/expandable-text";
import { SearchField } from "@/components/arc/search-field";
import { FIELD, NoticeBox, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import {
  useAddMaterial,
  useArchiveMaterial,
  useCampaignWorkspace,
  useClearCampaignProposal,
  useRequestCampaignScript,
  useSaveCampaignScript,
  useSaveMainTask,
  type CampaignWorkspace as Workspace,
} from "@/lib/api/campaignWorkspace";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";
import { useClientRealm } from "@/lib/api/session";

import { ProposalReview } from "../agents/[agentId]/script/ProposalReview";

import { KIND_LABEL, MATERIALS_HINT, MATERIALS_INFO, MaterialForm } from "./MaterialsDraft";
import { matchesWords } from "./matchWords";
import { PipGenerateBand } from "./PipGenerateBand";
import { SectionHead } from "./SectionHead";

export const MAIN_TASK_HINT = "What should this campaign achieve?";
export const MAIN_TASK_INFO = "Write it in your own words, as much as you like. Pip writes the script from it.";
export const MAIN_TASK_PLACEHOLDER =
  "For example: call farmers who registered on Rytu Khata but never opened the app, and help them add it to their home screen, step by step for Android or iPhone.";
export const SCRIPT_HINT = "What the agent says on each call.";
export const SCRIPT_INFO =
  "Pip writes it from your main task and materials; change anything, any time. Start puts only this script on the agent.";

export function CampaignWorkspace({
  campaignId,
  canWrite,
  refusal,
}: {
  campaignId: string;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const space = useCampaignWorkspace(session, campaignId);
  if (space.isLoading) return <Skeleton rows={4} label="Loading the campaign's work" />;
  if (!space.data) {
    return (
      <ProblemNotice
        error={space.error ?? new Error("This campaign's work did not load.")}
        onRetry={() => space.refetch()}
      />
    );
  }
  return (
    <div className="space-y-6">
      <MainTask campaignId={campaignId} space={space.data} canWrite={canWrite} refusal={refusal} />
      <Materials campaignId={campaignId} space={space.data} canWrite={canWrite} refusal={refusal} />
      <GenerateScript campaignId={campaignId} space={space.data} canWrite={canWrite} refusal={refusal} />
      <ScriptSection campaignId={campaignId} space={space.data} canWrite={canWrite} refusal={refusal} />
    </div>
  );
}

type Props = { campaignId: string; space: Workspace; canWrite: boolean; refusal?: string };

/** Generate: Pip writes (or rewrites) the script from the main task and materials. */
function GenerateScript({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const ask = useRequestCampaignScript(session, campaignId);
  const askFeedback = useActionFeedback(ask, { errorDisplay: "inline" });
  const hasTask = space.main_task.trim() !== "";
  const drafting = space.proposal?.status === "drafting";
  const reason = !hasTask
    ? "Save the main task first."
    : space.proposal?.status === "ready"
      ? "Review Pip's script below first."
      : space.proposal?.status === "failed"
        ? "Dismiss Pip's last try below first."
        : undefined;
  return (
    <div className="space-y-2">
      <PipGenerateBand
        onGenerate={() => askFeedback.run(undefined)}
        busy={ask.isPending || drafting}
        disabled={!canWrite || !hasTask || space.proposal != null}
        reason={reason}
        refusal={refusal}
      />
      {ask.error != null && <ProblemNotice error={ask.error} />}
    </div>
  );
}

function MainTask({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const [editing, setEditing] = useState(space.main_task.trim() === "");
  const [text, setText] = useState(space.main_task);
  const save = useSaveMainTask(session, campaignId);
  useActionFeedback(save, { errorDisplay: "inline" });
  const dirty = text.trim() !== space.main_task.trim();

  const startEdit = () => {
    setText(space.main_task);
    save.reset();
    setEditing(true);
  };
  const cancel = () => {
    setText(space.main_task);
    save.reset();
    setEditing(space.main_task.trim() === "");
  };
  const submit = () => save.mutate(text, { onSuccess: () => setEditing(false) });

  return (
    <section
      aria-labelledby="campaign-main-task"
      className="rounded-card border border-line border-l-4 border-l-brand bg-surface p-4 shadow-card sm:p-6"
    >
      <SectionHead id="campaign-main-task" step={1} title="Main task" hint={MAIN_TASK_HINT} info={MAIN_TASK_INFO} />
      {editing ? (
        <>
          <label htmlFor={`${campaignId}-main-task`} className="sr-only">
            Main task
          </label>
          <textarea
            id={`${campaignId}-main-task`}
            className={`${FIELD} min-h-36 w-full resize-y`}
            value={text}
            maxLength={4000}
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
              onClick={submit}
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {space.main_task.trim() !== "" && (
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
          {/* Long tasks open folded to six lines, with Show more to read the rest. */}
          <ExpandableText
            lines={6}
            moreLabel="Show more"
            lessLabel="Show less"
            className="text-body text-ink"
            textClassName="whitespace-pre-wrap [overflow-wrap:anywhere]"
          >
            {space.main_task}
          </ExpandableText>
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} mt-3`}
            disabled={!canWrite}
            title={refusal}
            onClick={startEdit}
          >
            Edit
          </button>
        </>
      )}
    </section>
  );
}

function Materials({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const add = useAddMaterial(session, campaignId);
  const archive = useArchiveMaterial(session, campaignId);
  useActionFeedback(add, { errorDisplay: "inline" });
  const archiveFeedback = useActionFeedback(archive, { errorTitle: "Could not remove it", successToast: "Removed" });
  const [query, setQuery] = useState("");

  const shown = useMemo(
    () =>
      space.materials.filter((m) =>
        matchesWords(query, [m.title, m.url, m.note, KIND_LABEL[m.kind], m.source === "call" ? "learned from calls" : ""]),
      ),
    [space.materials, query],
  );

  return (
    <section
      aria-labelledby="campaign-materials"
      className="rounded-card border border-info-line bg-info-soft p-4 sm:p-6 dark:bg-info/10"
    >
      <SectionHead id="campaign-materials" step={2} title="Materials" hint={MATERIALS_HINT} info={MATERIALS_INFO} />

      <MaterialForm
        canWrite={canWrite}
        refusal={refusal}
        onAdd={(item) => add.mutateAsync(item)}
        adding={add.isPending}
        addError={add.error}
      />

      {space.materials.length > 0 && (
        <div className="mt-4 space-y-3">
          {space.materials.length > 3 && (
            <SearchField label="Search materials" hideLabel value={query} onValueChange={setQuery} placeholder="Search materials" />
          )}
          <ul className="divide-y divide-info-line overflow-hidden rounded-card border border-info-line bg-surface">
            {shown.map((m) => (
              <li key={m.id} className="flex items-start gap-3 px-4 py-3">
                <span className="mt-0.5 shrink-0 rounded-sm bg-info-soft px-1.5 py-0.5 text-meta font-medium text-info">
                  {KIND_LABEL[m.kind]}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">
                    {m.title}
                    {m.source === "call" && (
                      <span className="ml-2 text-meta font-normal text-brand-strong">Learned from calls</span>
                    )}
                  </p>
                  {m.url && (
                    <a href={m.url} target="_blank" rel="noreferrer noopener" className="text-meta text-info underline [overflow-wrap:anywhere]">
                      {m.url}
                    </a>
                  )}
                  {m.note && (
                    <ExpandableText
                      lines={3}
                      moreLabel="Show more"
                      lessLabel="Show less"
                      className="mt-0.5 text-meta text-ink-muted"
                      textClassName="whitespace-pre-wrap [overflow-wrap:anywhere]"
                    >
                      {m.note}
                    </ExpandableText>
                  )}
                </div>
                <button
                  type="button"
                  className="shrink-0 text-meta text-ink-muted underline hover:text-danger"
                  disabled={!canWrite || archive.isPending}
                  title={refusal}
                  aria-label={`Remove ${m.title}`}
                  onClick={() => archiveFeedback.run(m.id)}
                >
                  Remove
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="px-4 py-3 text-meta text-ink-muted">Nothing matches “{query}”.</li>}
          </ul>
        </div>
      )}
    </section>
  );
}

function ScriptSection({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const clear = useClearCampaignProposal(session, campaignId);
  const save = useSaveCampaignScript(session, campaignId);
  const stopFeedback = useActionFeedback(clear, { errorTitle: "Could not stop Pip" });
  useActionFeedback(save, { errorDisplay: "inline" });
  const [editing, setEditing] = useState(false);
  const proposal = space.proposal;
  const script = space.script;
  const hasTask = space.main_task.trim() !== "";

  const keep = async (next: CallScript) => {
    try {
      await save.mutateAsync(next);
      if (proposal) await clear.mutateAsync(proposal.id);
      setEditing(false);
    } catch {
      // A refused save is `save.error`, rendered above; a refused clear is toasted.
    }
  };

  return (
    <section
      aria-labelledby="campaign-script"
      className="rounded-card border border-line border-l-4 border-l-brand-strong bg-surface p-4 shadow-card sm:p-6"
    >
      <SectionHead id="campaign-script" step={3} title="Script" hint={SCRIPT_HINT} info={SCRIPT_INFO} />

      {save.error != null && (
        <div className="mb-3">
          <ProblemNotice error={save.error} />
        </div>
      )}

      {proposal?.status === "drafting" && (
        <div role="status" className="flex flex-wrap items-center gap-3 rounded-card border border-line bg-surface p-4">
          <span className="h-3 w-3 animate-pulse rounded-full bg-brand" aria-hidden />
          <span className="text-body text-ink">Pip is writing the script. It shows here when done.</span>
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} ml-auto`}
            disabled={clear.isPending}
            onClick={() => stopFeedback.run(proposal.id)}
          >
            {clear.isPending ? "Stopping…" : "Stop"}
          </button>
        </div>
      )}

      {proposal?.status === "failed" && (
        <NoticeBox tone="warn" title="Pip could not write it this time">
          <p>{proposal.note}</p>
          <button type="button" className={`${SECONDARY_BUTTON_SM} mt-2`} onClick={() => stopFeedback.run(proposal.id)}>
            Dismiss
          </button>
        </NoticeBox>
      )}

      {proposal?.status === "ready" && proposal.script && (
        <div className="rounded-card border border-line bg-surface p-4">
          <ProposalReview
            key={proposal.id}
            current={script ?? EMPTY_SCRIPT}
            base={proposal.base_script ?? EMPTY_SCRIPT}
            proposal={proposal.script}
            pending={save.isPending ? "apply" : clear.isPending ? "discard" : null}
            onApply={(next) => void keep(next)}
            onDiscard={() => stopFeedback.run(proposal.id)}
          />
        </div>
      )}

      {!proposal && editing && (
        <div className="rounded-card border border-line bg-surface p-4">
          {/* Every part shown as written, with Review / Update / Cancel on each. */}
          <ProposalReview
            current={EMPTY_SCRIPT}
            proposal={script ?? EMPTY_SCRIPT}
            pending={save.isPending ? "apply" : null}
            onApply={(next) => void keep(next)}
            onDiscard={() => setEditing(false)}
          />
        </div>
      )}

      {!proposal && !editing && (
        <div className="rounded-card border border-line bg-surface p-4">
          {script ? (
            <>
              <ScriptSummary script={script} />
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canWrite} title={refusal} onClick={() => setEditing(true)}>
                  Edit script
                </button>
                {space.script_live_version != null && (
                  <span className="text-meta text-ink-muted">On the agent since the last Start (version {space.script_live_version}).</span>
                )}
              </div>
            </>
          ) : (
            <p className="text-body text-ink-muted">
              {hasTask ? "No script yet. Press Generate above." : "Write the main task first. Then Pip can write the script."}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function ScriptSummary({ script }: { script: CallScript }) {
  const opening = script.outbound_opening_line || script.opening_line;
  const steps =
    script.stages.length > 0
      ? script.stages.map((s) => s.name)
      : script.steps.map((s) => (s.instruction.length > 80 ? `${s.instruction.slice(0, 80)}…` : s.instruction));
  return (
    <dl className="grid grid-cols-1 gap-3 text-body sm:grid-cols-[10rem_1fr]">
      {opening && (
        <>
          <dt className="text-meta font-medium text-ink-muted">Opens with</dt>
          <dd className="text-ink">“{opening}”</dd>
        </>
      )}
      {script.goal && (
        <>
          <dt className="text-meta font-medium text-ink-muted">Aims for</dt>
          <dd className="text-ink">{script.goal}</dd>
        </>
      )}
      {steps.length > 0 && (
        <>
          <dt className="text-meta font-medium text-ink-muted">Steps</dt>
          <dd>
            <ol className="list-decimal space-y-0.5 pl-5 text-ink">
              {steps.map((name, i) => (
                <li key={`${name}-${i}`}>{name}</li>
              ))}
            </ol>
          </dd>
        </>
      )}
      <dt className="text-meta font-medium text-ink-muted">Quick facts</dt>
      <dd className="text-ink">
        {script.faqs.length} · objections {script.objections.length}
      </dd>
    </dl>
  );
}
