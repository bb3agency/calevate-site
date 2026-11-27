"use client";

/**
 * A CAMPAIGN'S OWN WORK (D-992): what it should achieve, what it works from, and the script
 * its calls follow. The campaign owns what is said; the agent is the voice, and Start puts
 * this script on the campaign's own calling agent, never on the agent itself (D-1003).
 *
 * Three sections, each with its own colour so the eye keeps them apart:
 *  1. Main task — a green rule: the owner's words, many lines.
 *  2. Sources — a blue ground: what the campaign picked from What your agents know, plus
 *     "Add a file or note", which adds to What your agents know and picks it (founder,
 *     16 Nov 2026: one place holds them). An answer on the Questions tab is added the same way.
 *  3. Script — a dark green rule: Pip writes it from 1 and 2, the owner reviews it part by
 *     part with the same Review / Update / Edit the agent Script page uses, and edits it any
 *     time. A rule rather than a green ground: a tinted card reads as a notice
 *     (`tests/noticeStyle.test.tsx`).
 */

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ExpandableText } from "@/components/arc/expandable-text";
import { TEXT_ACTION } from "@/components/console/section";
import { SHORTER_ASK, ScriptDraftLive } from "@/components/scriptDraft/ScriptDraftLive";
import { TooLongDraft } from "@/components/scriptDraft/ScriptDraftView";
import { ScriptSizeMeter, scriptSizeOf } from "@/components/scriptDraft/ScriptSizeMeter";
import { FIELD, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import {
  useAddCampaignSource,
  useCampaignSettings,
  useCampaignWorkspace,
  useClearCampaignProposal,
  useRequestCampaignScript,
  useRestoreCampaignScript,
  useRewriteStepOutcomes,
  useSaveCampaignScript,
  useSaveMainTask,
  useSetCampaignSources,
  type CampaignWorkspace as Workspace,
  type ScriptAsk,
} from "@/lib/api/campaignWorkspace";
import type { AgentDirection } from "@/lib/api/agents";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";
import { useScriptVersions } from "@/lib/api/scriptVersions";
import { useClientRealm } from "@/lib/api/session";

import { LeftOutNotice, lineWarningsOf } from "../agents/[agentId]/script/PipProposal";
import type { PartKey } from "../agents/[agentId]/script/scriptDiff";
import { ScriptNeedsFix } from "@/components/scriptChecks/ScriptNeedsFix";
import {
  SHOW_FINDING_EVENT,
  findingWarnings,
  isOpeningFinding,
  isPromptTooLong,
  isScriptNeedsFix,
  showRequestOf,
  useScriptChecks,
} from "@/lib/api/scriptChecks";

import { AddSourceForm, SOURCES_HINT, SOURCES_INFO } from "./AddSource";
import { GENERATE_LABEL, PipGenerateBand } from "./PipGenerateBand";
import { MAIN_TASK_SECTION, MATERIALS_SECTION, SCRIPT_SECTION } from "./campaignSections";
import { NoSourcesHint, PipNote, TonePick, type Tone } from "./PipScriptAsk";
import { PipAskRefused, PipFailed, PipWriting, retryable } from "./PipScriptStatus";
import { FoldSection } from "./FoldSection";
import { SourcePicker, useChosenCount } from "./SourcePicker";
import { CampaignFlow, FLOW_PART } from "./CampaignFlow";
import { restoredToast } from "./ScriptVersions";
import { openingOf } from "./scenarioModel";
import { ScriptLanguagePick, languageName } from "./ScriptLanguages";
import { MAIN_TASK_PLACEHOLDER } from "./NewCampaignSteps";
import { MAIN_TASK_MAX_CHARS } from "@/lib/textLimits";

// The review is drawn only while Pip's draft waits or the script is being edited, so it is
// its own chunk rather than part of every campaign page's first load.
const ProposalReview = dynamic(
  () => import("../agents/[agentId]/script/ProposalReview").then((m) => m.ProposalReview),
  { loading: () => <Skeleton rows={4} /> },
);
const ScriptPartsEditor = dynamic(
  () => import("../agents/[agentId]/script/ScriptPartsEditor").then((m) => m.ScriptPartsEditor),
  { loading: () => <Skeleton rows={4} /> },
);

// The call flow canvas edits the steps and both opening lines, so Edit script leaves them out.
const CANVAS_PARTS: readonly PartKey[] = ["opening_line", "outbound_opening_line"];

export const MAIN_TASK_HINT = "What should this campaign achieve?";
export const MAIN_TASK_INFO = "Write it in your own words, as much as you like. Pip writes the script from it.";
export const SCRIPT_HINT = "What the agent says on each call.";
const SCRIPT_LOCKED = "You can't change this campaign's script.";
export const SCRIPT_INFO =
  "Pip writes it from what this campaign is for and its files and notes; change anything, any time. Only this campaign's calls say it; your agent's own script stays as it is.";
/** The first section's name, in the owner's words (redesign plan §6). */
export const PURPOSE_TITLE = "What this campaign is for";
export const MATERIALS_TITLE = "Files and notes it can use";

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
      <Sources campaignId={campaignId} space={space.data} canWrite={canWrite} refusal={refusal} />
      <ScriptSection campaignId={campaignId} space={space.data} canWrite={canWrite} refusal={refusal} />
    </div>
  );
}

type Props = { campaignId: string; space: Workspace; canWrite: boolean; refusal?: string };

/** What the owner chose for the next draft: a tone and a note (D-1004). */
type Asking = { tone: Tone | ""; note: string };

/** The request body for a whole-script draft with the owner's choices, or none. */
export function scriptAsk(asking: Asking): ScriptAsk | undefined {
  const body: ScriptAsk = {};
  if (asking.tone) body.tone = asking.tone;
  if (asking.note.trim()) body.instruction = asking.note.trim();
  return Object.keys(body).length > 0 ? body : undefined;
}

type ScriptRequest = ReturnType<typeof useRequestCampaignScript>;

/** Generate: Pip writes (or rewrites) the script from the main task and sources. */
function GenerateScript({
  campaignId,
  space,
  canWrite,
  refusal,
  asking,
  onAsking,
  ask,
  onAsk,
}: Props & {
  asking: Asking;
  onAsking: (next: Asking) => void;
  /** The section's one request to Pip, so Generate waits on a part rewrite and the reverse. */
  ask: ScriptRequest;
  onAsk: (asked: ScriptAsk | undefined) => void;
}) {
  const [savingLanguage, setSavingLanguage] = useState(false);
  const hasTask = space.main_task.trim() !== "";
  const drafting = space.proposal?.status === "drafting";
  // A failed draft is replaced by the next request, so Generate is Try again, not a wait.
  const failed = space.proposal?.status === "failed";
  const reason = !hasTask
    ? "Save what this campaign is for first."
    : space.proposal?.status === "ready"
      ? "Review Pip's script below first."
      : failed
        ? "Pip's last try did not finish. See why below."
        : undefined;
  const held = !canWrite || drafting || ask.isPending;
  return (
    <div className="space-y-2">
      <PipGenerateBand
        onGenerate={() => onAsk(scriptAsk(asking))}
        busy={ask.isPending || drafting}
        beside={
          <>
            <ScriptLanguagePick
              campaignId={campaignId}
              agentId={space.agent_id}
              canWrite={canWrite}
              refusal={refusal}
              onSaving={setSavingLanguage}
            />
            <TonePick
              value={asking.tone}
              disabled={held}
              title={refusal}
              onChange={(tone) => onAsking({ ...asking, tone })}
            />
          </>
        }
        disabled={!canWrite || savingLanguage || !hasTask || (space.proposal != null && !(failed && retryable(space.proposal.reason)))}
        reason={reason}
        refusal={refusal}
        label={failed ? "Try again" : GENERATE_LABEL}
        inline
      />
      {hasTask && <PipNote value={asking.note} disabled={held} onChange={(note) => onAsking({ ...asking, note })} />}
      {hasTask && space.source_ids.length === 0 && <NoSourcesHint />}
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
    <FoldSection id={MAIN_TASK_SECTION} title={PURPOSE_TITLE} tone="task" hint={MAIN_TASK_HINT} info={MAIN_TASK_INFO}>
      {editing ? (
        <>
          <label htmlFor={`${campaignId}-main-task`} className="sr-only">
            {PURPOSE_TITLE}
          </label>
          <textarea
            id={`${campaignId}-main-task`}
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
              onClick={submit}
            >
              Save
            </ActionButton>
            {space.main_task.trim() !== "" && (
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

function Sources({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const save = useSetCampaignSources(session, campaignId);
  const add = useAddCampaignSource(session, campaignId);
  useActionFeedback(save, { errorDisplay: "inline", successToast: "Files and notes saved" });
  useActionFeedback(add, { errorDisplay: "inline", successToast: "Added and picked" });
  const count = useChosenCount(space.source_ids);

  return (
    <FoldSection
      id={MATERIALS_SECTION}
      title={MATERIALS_TITLE}
      tone="materials"
      hint={SOURCES_HINT}
      info={SOURCES_INFO}
      aside={count > 0 ? `${count} chosen` : undefined}
    >
      <div className="space-y-4">
        {/* Keyed on what is saved, so an item added below shows ticked rather than being
            dropped by ticks still waiting to be saved. */}
        <SourcePicker
          key={space.source_ids.join()}
          saved={space.source_ids}
          legend="Files and notes for this campaign"
          canWrite={canWrite}
          refusal={refusal}
          save={save}
          emptyAction={false}
        />
        <AddSourceForm
          canWrite={canWrite}
          refusal={refusal}
          onAdd={(item) => {
            add.reset();
            return add.mutateAsync(item);
          }}
          adding={add.isPending}
          addError={add.error}
        />
      </div>
    </FoldSection>
  );
}

function ScriptSection({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const clear = useClearCampaignProposal(session, campaignId);
  const save = useSaveCampaignScript(session, campaignId);
  const restore = useRestoreCampaignScript(session, campaignId);
  const restoreFeedback = useActionFeedback(restore, { errorDisplay: "inline", successToast: restoredToast });
  const versions = useScriptVersions(session, { kind: "campaign", id: campaignId }, space.script, space.script != null);
  const rewrite = useRewriteStepOutcomes(session, campaignId);
  const rewriteFeedback = useActionFeedback(rewrite, { errorDisplay: "inline", successToast: "Pip is rewriting every “Done when…”" });
  const stopFeedback = useActionFeedback(clear, { errorTitle: "Could not stop Pip" });
  useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const ask = useRequestCampaignScript(session, campaignId);
  const askFeedback = useActionFeedback(ask, { errorDisplay: "inline" });
  const [editing, setEditing] = useState(false);
  const [asking, setAsking] = useState<Asking>({ tone: "", note: "" });
  //: The draft the owner chose to review part by part instead of in the live view.
  const [reviewing, setReviewing] = useState<string | null>(null);
  const proposal = space.proposal;
  const script = space.script;
  const checks = useScriptChecks(session, { kind: "campaign", id: campaignId }, script);
  const size = scriptSizeOf(checks.data);
  const warnings = useMemo(
    () => (checks.isSuccess ? findingWarnings(checks.data.findings) : []),
    [checks.isSuccess, checks.data],
  );
  // "Show me" from the compliance checks or a refusal: the section opens wherever the line
  // is. A step or the opening is the flow's to show (`CampaignFlow`); any other part opens
  // Edit script on it.
  const [reveal, setReveal] = useState(0);
  const [showing, setShowing] = useState<{ stageId: string | null } | null>(null);
  useEffect(() => {
    const show = (event: Event) => {
      const request = showRequestOf(event);
      setReveal((n) => n + 1);
      if (!script || request.stageId || isOpeningFinding(request)) return;
      setEditing(true);
      setShowing({ stageId: null });
    };
    window.addEventListener(SHOW_FINDING_EVENT, show);
    return () => window.removeEventListener(SHOW_FINDING_EVENT, show);
  }, [script]);
  const hasTask = space.main_task.trim() !== "";
  // Pip rewrites one part in a chosen language; the draft then comes back for review here.
  const settings = useCampaignSettings(session, campaignId, space.agent_id).data;
  const main = settings ? (settings.overrides.language_primary ?? settings.defaults.language_primary) : null;
  const flowLanguages = [
    ...new Set(
      [main, ...(settings?.overrides.languages_extra ?? settings?.defaults.languages_extra ?? [])].filter(
        (t): t is string => Boolean(t),
      ),
    ),
  ];
  const reviewLanguages = flowLanguages.map((tag) => ({ tag, name: languageName(tag) }));
  const generatePart = settings
    ? {
        languages: settings.offered_languages.map((tag) => ({ tag, name: languageName(tag) })),
        initial: main ?? settings.offered_languages[0] ?? "",
        reason: !canWrite ? refusal : ask.isPending ? "Pip is writing." : undefined,
        onGenerate: (part: string, language: string, instruction?: string) => {
          setEditing(false);
          askFeedback.run({
            part,
            language,
            ...(asking.tone ? { tone: asking.tone } : {}),
            ...(instruction ? { instruction } : {}),
          });
        },
      }
    : undefined;

  // Closing the editor (Save changes, Close, or keeping Pip's script) swaps a long list for
  // the short read, which would leave the view far below the section. Bring the section
  // back into view and put the focus on Edit script, so the owner is where they were.
  const editButton = useRef<HTMLButtonElement>(null);
  const backToScript = () =>
    window.requestAnimationFrame(() => {
      const section = document.getElementById(SCRIPT_SECTION);
      if (section && section.getBoundingClientRect().top < 0) section.scrollIntoView({ block: "start" });
      editButton.current?.focus({ preventScroll: true });
    });
  const closeEditor = () => {
    setEditing(false);
    setShowing(null);
    backToScript();
  };

  const keep = async (next: CallScript) => {
    try {
      // The draft is settled by the save itself, so a save whose put-live is refused does not
      // leave it standing over the script it kept.
      await save.mutateAsync(proposal ? { script: next, proposalId: proposal.id } : { script: next });
      closeEditor();
    } catch {
      // A refused save is `save.error`, rendered above.
    }
  };

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
          languages={reviewLanguages}
          warnings={lineWarningsOf(proposal.left_out)}
          pending={save.isPending ? "apply" : clear.isPending ? "discard" : null}
          onApply={(next) => void keep(next)}
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
    <FoldSection id={SCRIPT_SECTION} title="Script" tone="script" hint={SCRIPT_HINT} info={SCRIPT_INFO} reveal={reveal}>
      {/* Generate sits in the Script section (founder, 15 Nov 2026): one place to get a script and read it. */}
      <div className="mb-4">
        <GenerateScript
          campaignId={campaignId}
          space={space}
          canWrite={canWrite}
          refusal={refusal}
          asking={asking}
          onAsking={setAsking}
          ask={ask}
          onAsk={(asked) => askFeedback.run(asked)}
        />
      </div>

      {/* Every request to Pip — Generate, Try again, a part's rewrite, mapping the call flow —
          is refused here, whichever button sent it; it is inline, so nowhere else says it. */}
      {ask.error != null && (
        <div className="mb-3">
          <PipAskRefused error={ask.error} onRetry={() => askFeedback.run(ask.variables)} />
        </div>
      )}

      {save.error != null && (
        <div className="mb-3">
          {isScriptNeedsFix(save.error) ? (
            <ScriptNeedsFix holder={{ kind: "campaign", id: campaignId }} canWrite={canWrite} refusal={refusal} />
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

      {/* PIP WRITING, LIVE, and then its changes with Keep or Discard: the same view the Pip
          panel shows, so Rewrite now here looks the same as asking Pip. Without the draft
          stream, the page keeps its own writing line and part-by-part review. */}
      {proposal && liveDraft && (
        <div className="py-2">
          <ScriptDraftLive
            key={proposal.id}
            session={session}
            holder={{ kind: "campaign", id: campaignId }}
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
          onRetry={() => askFeedback.run(scriptAsk(asking))}
          onDismiss={() => stopFeedback.run(proposal.id)}
        />
      )}

      {proposal && !liveDraft && readyReview}

      {!proposal && editing && (
        <div className="rounded-card border border-line bg-surface p-4">
          <ScriptPartsEditor
            script={script ?? EMPTY_SCRIPT}
            leaveOut={CANVAS_PARTS}
            steps={false}
            generatePart={generatePart}
            languages={reviewLanguages}
            saving={save.isPending}
            onSave={(next) => void keep(next)}
            onClose={closeEditor}
            warnings={warnings}
            show={showing}
          />
        </div>
      )}

      {!proposal && !editing && (
        <div>
          {script ? (
            <>
              {/* A campaign only places calls, and they open on `opening_line` (`openingOf`). */}
              <ScriptSummary script={script} direction="outbound" />
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
              </div>
              <CampaignFlow
                campaignId={campaignId}
                agentId={space.agent_id}
                languages={flowLanguages}
                script={script}
                canWrite={canWrite}
                refusal={refusal}
                saving={save.isPending}
                saveError={save.error}
                onSave={async (next) => {
                  await save.mutateAsync({ script: next });
                }}
                mapping={ask.isPending}
                versions={versions.data}
                outcomesPending={space.step_outcomes_pending}
                restore={restoreFeedback}
                onRestore={(input) => restore.mutateAsync(input)}
                outcomesByOwner={space.step_outcomes_by_owner}
                rewriteOutcomes={rewriteFeedback}
                onRewriteOutcomes={() => rewrite.mutateAsync()}
                onMapScenarios={
                  main ? () => askFeedback.run({ part: FLOW_PART, language: main }) : undefined
                }
                onWriteExamples={(part, language, instruction) =>
                  askFeedback.run({ part, language, instruction, ...(asking.tone ? { tone: asking.tone } : {}) })
                }
              />
            </>
          ) : (
            <p className="text-body text-ink-muted">
              {hasTask
                ? `No script yet. Press ${GENERATE_LABEL} above.`
                : "Say what this campaign is for first. Then Pip can write the script."}
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
export function ScriptSummary({ script, direction }: { script: CallScript; direction: AgentDirection }) {
  const { line: opening, placed: outbound } = openingOf(script, direction);
  const steps =
    script.stages.length > 0
      ? script.stages.map((s) => s.name)
      : script.steps.map((s) => (s.instruction.length > 80 ? `${s.instruction.slice(0, 80)}…` : s.instruction));
  return (
    <dl className="grid grid-cols-1 gap-3 text-body sm:grid-cols-[10rem_1fr]">
      {opening && (
        <>
          <dt className="text-meta font-medium text-ink-muted">
            {outbound ? "First thing it says when it calls" : "First thing it says"}
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
      <dt className="text-meta font-medium text-ink-muted">If they say no or not now</dt>
      <dd className="text-ink">
        {script.objections.length === 1 ? "1 answer" : `${script.objections.length} answers`}
      </dd>
    </dl>
  );
}
