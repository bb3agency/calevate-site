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
 *  3. Script — a green ground: Pip writes it from 1 and 2, the owner reviews it part by part
 *     with the same Review / Update / Edit the agent Script page uses, and edits it any time.
 */

import { useMemo, useState } from "react";

import { problemToast, useActionFeedback } from "@/components/arc/feedback";
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
  useUploadMaterial,
  type CampaignMaterial,
  type CampaignWorkspace as Workspace,
} from "@/lib/api/campaignWorkspace";
import { useAddLink } from "@/lib/api/kb";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";
import { useClientRealm } from "@/lib/api/session";

import { LeftOutNotice } from "../agents/[agentId]/script/PipProposal";
import { ProposalReview } from "../agents/[agentId]/script/ProposalReview";

import { FilePicker } from "./FilePicker";
import { matchesWords } from "./matchWords";
import { PipGenerateBand } from "./PipGenerateBand";

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
  const [error, setError] = useState<unknown>(null);
  const hasTask = space.main_task.trim() !== "";
  const drafting = space.proposal?.status === "drafting";
  const reason = !hasTask
    ? "Write and save the main task first, then Pip can write the script."
    : space.proposal?.status === "ready"
      ? "Pip's script is waiting for your review below. Keep or discard it, then generate again."
      : space.proposal?.status === "failed"
        ? "Pip's last try did not finish. Dismiss it below, then generate again."
        : refusal;
  return (
    <div className="space-y-2">
      <PipGenerateBand
        onGenerate={() => {
          setError(null);
          ask.mutate(undefined, { onError: setError });
        }}
        busy={ask.isPending || drafting}
        disabled={!canWrite || !hasTask || space.proposal != null}
        reason={reason}
      />
      <InlineError error={error} title="Pip could not start" />
    </div>
  );
}

function InlineError({ error, title }: { error: unknown; title: string }) {
  if (!error) return null;
  return (
    <p role="alert" className="mt-2 text-meta text-danger">
      {problemToast(error, title).description ?? title}
    </p>
  );
}

function SectionHead({ step, title, hint }: { step: number; title: string; hint: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-heading text-ink">
        <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-ink text-meta font-semibold text-surface">
          {step}
        </span>
        {title}
      </h2>
      <p className="mt-1 text-meta text-ink-muted">{hint}</p>
    </div>
  );
}

function MainTask({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const [editing, setEditing] = useState(space.main_task.trim() === "");
  const [text, setText] = useState(space.main_task);
  const [error, setError] = useState<unknown>(null);
  const save = useSaveMainTask(session, campaignId);
  const dirty = text.trim() !== space.main_task.trim();

  const startEdit = () => {
    setText(space.main_task);
    setError(null);
    setEditing(true);
  };
  const cancel = () => {
    setText(space.main_task);
    setError(null);
    setEditing(space.main_task.trim() === "");
  };
  const submit = async () => {
    setError(null);
    try {
      await save.mutateAsync(text);
      setEditing(false);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <section
      aria-labelledby="campaign-main-task"
      className="rounded-card border border-line border-l-4 border-l-brand bg-surface p-4 shadow-card sm:p-6"
    >
      <div id="campaign-main-task">
        <SectionHead
          step={1}
          title="Main task"
          hint="What should this campaign achieve? Write it in your own words, as much as you like."
        />
      </div>
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
            placeholder="For example: call farmers who registered on Rytu Khata but never opened the app, and help them add it to their home screen, step by step for Android or iPhone."
            onChange={(e) => setText(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              disabled={!canWrite || !text.trim() || !dirty || save.isPending}
              title={refusal}
              onClick={() => void submit()}
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {space.main_task.trim() !== "" && (
              <button type="button" className={SECONDARY_BUTTON_SM} disabled={save.isPending} onClick={cancel}>
                Cancel
              </button>
            )}
          </div>
          <InlineError error={error} title="The main task did not save" />
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

const KIND_LABEL: Record<CampaignMaterial["kind"], string> = { file: "File", link: "Link", note: "Note" };

function Materials({ campaignId, space, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const add = useAddMaterial(session, campaignId);
  const archive = useArchiveMaterial(session, campaignId);
  const uploadFile = useUploadMaterial(session, campaignId);
  const addLink = useAddLink(session);
  const archiveFeedback = useActionFeedback(archive, { errorTitle: "Could not remove it", successToast: "Removed" });
  const [mode, setMode] = useState<"file" | "link" | "note" | null>(null);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const busy = add.isPending || uploadFile.isPending || addLink.isPending;

  const shown = useMemo(
    () =>
      space.materials.filter((m) =>
        matchesWords(query, [m.title, m.url, m.note, KIND_LABEL[m.kind], m.source === "call" ? "learned from calls" : ""]),
      ),
    [space.materials, query],
  );

  const reset = () => {
    setMode(null);
    setTitle("");
    setUrl("");
    setNote("");
    setFile(null);
    setError(null);
  };

  const submit = async () => {
    setError(null);
    try {
      if (mode === "file") {
        if (!file) return setError("Choose a file.");
        await uploadFile.mutateAsync({ file, title: title.trim() || undefined });
      } else if (mode === "link") {
        if (!/^https?:\/\//i.test(url.trim())) return setError("Paste the full address, starting with https://");
        const up = await addLink.mutateAsync({ url: url.trim() });
        await add.mutateAsync({ kind: "link", title: title.trim() || url.trim(), url: url.trim(), kb_upload_id: up.id });
      } else if (mode === "note") {
        if (!note.trim()) return setError("Write the note.");
        await add.mutateAsync({ kind: "note", title: title.trim() || note.trim().slice(0, 60), note: note.trim() });
      }
      reset();
    } catch (e) {
      setError(problemToast(e, "That did not save. Try again.").description ?? "That did not save. Try again.");
    }
  };

  return (
    <section
      aria-labelledby="campaign-materials"
      className="rounded-card border border-info-line bg-info-soft p-4 sm:p-6 dark:bg-info/10"
    >
      <div id="campaign-materials">
        <SectionHead
          step={2}
          title="Materials"
          hint="Everything Pip and the agent should know: documents, price lists, website links, video links, call recordings, notes. Files and links also go into your knowledge, so the agent can look things up on a call."
        />
      </div>

      <div className="flex flex-wrap gap-2">
        {(["file", "link", "note"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            className={mode === kind ? PRIMARY_BUTTON_SM : SECONDARY_BUTTON_SM}
            disabled={!canWrite}
            title={refusal}
            aria-pressed={mode === kind}
            onClick={() => (mode === kind ? reset() : (reset(), setMode(kind)))}
          >
            {kind === "file" ? "Upload a file" : kind === "link" ? "Add a link" : "Write a note"}
          </button>
        ))}
      </div>

      {mode && (
        <div className="mt-4 space-y-3 rounded-card border border-info-line bg-surface p-4">
          <label className="block text-meta font-medium text-ink">
            Name <span className="font-normal text-ink-muted">(optional)</span>
            <input className={`${FIELD} mt-1 w-full`} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          </label>
          {mode === "file" && (
            <FilePicker
              file={file}
              onFile={setFile}
              hint="PDF, Word, Excel, CSV, text or a photo, up to 20 MB. For a video or a call recording, add its link."
            />
          )}
          {mode === "link" && (
            <label className="block text-meta font-medium text-ink">
              Address
              <input
                type="url"
                inputMode="url"
                className={`${FIELD} mt-1 w-full`}
                value={url}
                placeholder="https://"
                onChange={(e) => setUrl(e.target.value)}
              />
            </label>
          )}
          {mode === "note" && (
            <label className="block text-meta font-medium text-ink">
              Note
              <textarea
                className={`${FIELD} mt-1 min-h-28 w-full resize-y`}
                value={note}
                maxLength={4000}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
          )}
          {error && (
            <p role="alert" className="text-meta text-danger">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <button type="button" className={PRIMARY_BUTTON_SM} disabled={busy} onClick={() => void submit()}>
              {busy ? "Adding…" : "Add"}
            </button>
            <button type="button" className={SECONDARY_BUTTON_SM} disabled={busy} onClick={reset}>
              Cancel
            </button>
          </div>
        </div>
      )}

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
  const [saveError, setSaveError] = useState<unknown>(null);
  const [editing, setEditing] = useState(false);
  const proposal = space.proposal;
  const script = space.script;
  const hasTask = space.main_task.trim() !== "";

  const keep = async (next: CallScript) => {
    setSaveError(null);
    try {
      await save.mutateAsync(next);
      if (proposal) await clear.mutateAsync(proposal.id);
      setEditing(false);
    } catch (e) {
      setSaveError(e);
    }
  };

  return (
    <section
      aria-labelledby="campaign-script"
      className="rounded-card border border-brand/30 bg-brand-soft p-4 sm:p-6 dark:bg-brand-strong/15"
    >
      <div id="campaign-script" className="flex flex-wrap items-start justify-between gap-3">
        <SectionHead
          step={3}
          title="Script"
          hint="What the agent says and how it runs each call. Pip writes it from your main task and materials; change anything, any time. Start puts only this script on the agent."
        />
      </div>

      <InlineError error={saveError} title="The script did not save" />

      {proposal?.status === "drafting" && (
        <div role="status" className="flex flex-wrap items-center gap-3 rounded-card border border-line bg-surface p-4">
          <span className="h-3 w-3 animate-pulse rounded-full bg-brand" aria-hidden />
          <span className="text-body text-ink">
            Pip is writing the script from your main task and materials. This page checks every 5 seconds.
          </span>
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
          >
            {proposal.disclosure && <p className="text-meta text-ink-muted">{proposal.disclosure}</p>}
            {proposal.left_out.length > 0 && <LeftOutNotice parts={proposal.left_out} />}
          </ProposalReview>
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
              {hasTask
                ? "No script yet. Press Generate above and Pip writes it from your main task and materials."
                : "Write the main task first. Then Pip can write the script."}
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
    <dl className="grid gap-3 text-body sm:grid-cols-[10rem_1fr]">
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
