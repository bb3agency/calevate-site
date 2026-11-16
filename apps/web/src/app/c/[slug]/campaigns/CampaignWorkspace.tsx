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

import { useMemo, useRef, useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ExpandableText } from "@/components/arc/expandable-text";
import { SearchField } from "@/components/arc/search-field";
import { TEXT_ACTION_DANGER } from "@/components/console/section";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import {
  useAddMaterial,
  useArchiveMaterial,
  useCampaignWorkspace,
  useClearCampaignProposal,
  useRequestCampaignScript,
  useSaveCampaignScript,
  useSaveMainTask,
  useUploadMaterial,
  type CampaignWorkspace as Workspace,
} from "@/lib/api/campaignWorkspace";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";
import { useClientRealm } from "@/lib/api/session";

import { LeftOutNotice } from "../agents/[agentId]/script/PipProposal";
import { ProposalReview } from "../agents/[agentId]/script/ProposalReview";

import { KIND_LABEL, MATERIALS_HINT, MATERIALS_INFO, MaterialForm } from "./MaterialsDraft";
import { matchesWords } from "./matchWords";
import { PipGenerateBand } from "./PipGenerateBand";
import { PipFailed, PipWriting, retryable } from "./PipScriptStatus";
import { FoldSection } from "./FoldSection";
import { ScriptLanguagePick } from "./ScriptLanguages";

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
    <div className="space-y-10">
      <MainTask campaignId={campaignId} space={space.data} canWrite={canWrite} refusal={refusal} />
      <Materials campaignId={campaignId} space={space.data} canWrite={canWrite} refusal={refusal} />
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
  const [savingLanguage, setSavingLanguage] = useState(false);
  const hasTask = space.main_task.trim() !== "";
  const drafting = space.proposal?.status === "drafting";
  // A failed draft is replaced by the next request, so Generate is Try again, not a wait.
  const failed = space.proposal?.status === "failed";
  const reason = !hasTask
    ? "Save the main task first."
    : space.proposal?.status === "ready"
      ? "Review Pip's script below first."
      : failed
        ? "Pip's last try did not finish. See why below."
        : undefined;
  return (
    <div className="space-y-2">
      <PipGenerateBand
        onGenerate={() => askFeedback.run(undefined)}
        busy={ask.isPending || drafting}
        beside={
          <ScriptLanguagePick
            campaignId={campaignId}
            agentId={space.agent_id}
            canWrite={canWrite}
            refusal={refusal}
            onSaving={setSavingLanguage}
          />
        }
        disabled={!canWrite || savingLanguage || !hasTask || (space.proposal != null && !(failed && retryable(space.proposal.reason)))}
        reason={reason}
        refusal={refusal}
        label={failed ? "Try again" : "Generate"}
        inline
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
    <FoldSection id="campaign-main-task" title="Main task" tone="task" hint={MAIN_TASK_HINT} info={MAIN_TASK_INFO}>
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
    </FoldSection>
  );
}

function Materials({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const add = useAddMaterial(session, campaignId);
  const uploadFile = useUploadMaterial(session, campaignId);
  const archive = useArchiveMaterial(session, campaignId);
  useActionFeedback(add, { errorDisplay: "inline" });
  useActionFeedback(uploadFile, { errorDisplay: "inline" });
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
    <FoldSection id="campaign-materials" title="Materials" tone="materials" hint={MATERIALS_HINT} info={MATERIALS_INFO}>

      <MaterialForm
        canWrite={canWrite}
        refusal={refusal}
        onAdd={({ file, ...item }) => {
          add.reset();
          uploadFile.reset();
          return file ? uploadFile.mutateAsync({ file, title: item.title }) : add.mutateAsync(item);
        }}
        adding={add.isPending || uploadFile.isPending}
        addError={uploadFile.error ?? add.error}
      />

      {space.materials.length > 0 && (
        <div className="mt-4 space-y-3">
          {space.materials.length > 3 && (
            <SearchField label="Search materials" hideLabel value={query} onValueChange={setQuery} placeholder="Search materials" />
          )}
          <ul className="max-w-4xl divide-y divide-line border-y border-line">
            {shown.map((m) => (
              <li key={m.id} className="flex items-start gap-3 py-3.5">
                <span className="mt-0.5 w-12 shrink-0 text-meta text-ink-muted">
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
                    <a href={m.url} target="_blank" rel="noreferrer noopener" className="text-meta text-ink-muted underline decoration-line underline-offset-2 hover:text-ink [overflow-wrap:anywhere]">
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
                  className={TEXT_ACTION_DANGER}
                  disabled={!canWrite || archive.isPending}
                  title={refusal}
                  aria-label={`Remove ${m.title}`}
                  onClick={() => archiveFeedback.run(m.id)}
                >
                  Remove
                </button>
              </li>
            ))}
            {shown.length === 0 && <li className="py-3.5 text-meta text-ink-muted">Nothing matches “{query}”.</li>}
          </ul>
        </div>
      )}
    </FoldSection>
  );
}

function ScriptSection({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const clear = useClearCampaignProposal(session, campaignId);
  const save = useSaveCampaignScript(session, campaignId);
  const stopFeedback = useActionFeedback(clear, { errorTitle: "Could not stop Pip" });
  useActionFeedback(save, { errorDisplay: "inline" });
  const ask = useRequestCampaignScript(session, campaignId);
  const askFeedback = useActionFeedback(ask, { errorDisplay: "inline" });
  const [editing, setEditing] = useState(false);
  const proposal = space.proposal;
  const script = space.script;
  const hasTask = space.main_task.trim() !== "";

  // Closing the editor (Save changes, Close, or keeping Pip's script) swaps a long list for
  // the short read, which would leave the view far below the section. Bring the section
  // back into view and put the focus on Edit script, so the owner is where they were.
  const editButton = useRef<HTMLButtonElement>(null);
  const backToScript = () =>
    window.requestAnimationFrame(() => {
      const section = document.getElementById("campaign-script");
      if (section && section.getBoundingClientRect().top < 0) section.scrollIntoView({ block: "start" });
      editButton.current?.focus({ preventScroll: true });
    });
  const closeEditor = () => {
    setEditing(false);
    backToScript();
  };

  const keep = async (next: CallScript) => {
    try {
      await save.mutateAsync(next);
      if (proposal) await clear.mutateAsync(proposal.id);
      closeEditor();
    } catch {
      // A refused save is `save.error`, rendered above; a refused clear is toasted.
    }
  };

  return (
    <FoldSection id="campaign-script" title="Script" tone="script" hint={SCRIPT_HINT} info={SCRIPT_INFO}>
      {/* Generate sits in the Script section (founder, 15 Nov 2026): one place to get a script and read it. */}
      <div className="mb-4">
        <GenerateScript campaignId={campaignId} space={space} canWrite={canWrite} refusal={refusal} />
      </div>

      {save.error != null && (
        <div className="mb-3">
          <ProblemNotice error={save.error} />
        </div>
      )}

      {proposal?.status === "drafting" && (
        <PipWriting proposal={proposal} stopping={clear.isPending} onStop={() => stopFeedback.run(proposal.id)} />
      )}

      {proposal?.status === "failed" && (
        <>
          <PipFailed
            proposal={proposal}
            canWrite={canWrite}
            retrying={ask.isPending}
            dismissing={clear.isPending}
            onRetry={() => askFeedback.run(undefined)}
            onDismiss={() => stopFeedback.run(proposal.id)}
          />
          {ask.error != null && (
            <div className="mt-3">
              <ProblemNotice error={ask.error} />
            </div>
          )}
        </>
      )}

      {proposal?.status === "ready" && proposal.script && (
        <div className="border-y border-line py-4">
          <ProposalReview
            key={proposal.id}
            current={script ?? EMPTY_SCRIPT}
            base={proposal.base_script ?? EMPTY_SCRIPT}
            proposal={proposal.script}
            pending={save.isPending ? "apply" : clear.isPending ? "discard" : null}
            onApply={(next) => void keep(next)}
            onDiscard={() => stopFeedback.run(proposal.id)}
          >
            {proposal.disclosure && <p className="text-meta text-ink-muted">{proposal.disclosure}</p>}
            {proposal.left_out.length > 0 && <LeftOutNotice parts={proposal.left_out} />}
          </ProposalReview>
        </div>
      )}

      {!proposal && editing && (
        <div className="rounded-card border border-line bg-surface p-4">
          {/* Every part as saved, with Edit / Update / Cancel on each; nothing to add again. */}
          <ProposalReview
            editing
            current={EMPTY_SCRIPT}
            proposal={script ?? EMPTY_SCRIPT}
            pending={save.isPending ? "apply" : null}
            onApply={(next) => void keep(next)}
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
    </FoldSection>
  );
}

/**
 * A short read of the saved script, named exactly as Edit script names the same parts
 * (`scriptDiff.PARTS`), so the owner recognises each one when they open it to change it.
 */
function ScriptSummary({ script }: { script: CallScript }) {
  const outbound = script.outbound_opening_line !== "";
  const opening = script.outbound_opening_line || script.opening_line;
  const steps =
    script.stages.length > 0
      ? script.stages.map((s) => s.name)
      : script.steps.map((s) => (s.instruction.length > 80 ? `${s.instruction.slice(0, 80)}…` : s.instruction));
  return (
    <dl className="grid grid-cols-1 gap-3 text-body sm:grid-cols-[10rem_1fr]">
      {opening && (
        <>
          <dt className="text-meta font-medium text-ink-muted">
            {outbound ? "Opening line when it calls" : "Opening line"}
          </dt>
          <dd className="text-ink">“{opening}”</dd>
        </>
      )}
      {script.goal && (
        <>
          <dt className="text-meta font-medium text-ink-muted">The goal</dt>
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
      <dd className="text-ink">{script.faqs.length === 1 ? "1 fact" : `${script.faqs.length} facts`}</dd>
      <dt className="text-meta font-medium text-ink-muted">When callers push back</dt>
      <dd className="text-ink">
        {script.objections.length === 1 ? "1 answer" : `${script.objections.length} answers`}
      </dd>
    </dl>
  );
}
