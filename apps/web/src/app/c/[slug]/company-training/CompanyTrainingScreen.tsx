"use client";

/**
 * THE COMPANY TRAINING (founder, 16 Nov 2026): the one training every agent of the account is
 * given, the way a company trains everyone it hires before assigning them work. Each agent,
 * campaign and inbound line keeps its own script on top of it.
 *
 * Built like a campaign's set-up (D-992), with the same coloured folds:
 *  1. About the business: the owner's own words, many lines.
 *  2. Materials: documents, links and notes; files and links also go into the knowledge.
 *  3. Training: Pip writes it from 1 and 2, the owner reads it, keeps it or edits it, and a
 *     save brings every agent onto it.
 */

import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ExpandableText } from "@/components/arc/expandable-text";
import { TEXT_ACTION_DANGER } from "@/components/console/section";
import { PageHeader } from "@/components/console/pageHeader";
import {
  FIELD,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import {
  useAddTrainingMaterial,
  useArchiveTrainingMaterial,
  useClearTrainingProposal,
  useCompanyTraining,
  useRequestTraining,
  useSaveOverview,
  useSaveTraining,
  useUploadTrainingMaterial,
  type CompanyTraining,
} from "@/lib/api/companyTraining";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { FoldGroup, FoldSection } from "../campaigns/FoldSection";
import { KIND_LABEL, MaterialForm } from "../campaigns/MaterialsDraft";
import { PipGenerateBand } from "../campaigns/PipGenerateBand";
import { PipFailed, PipWriting, retryable } from "../campaigns/PipScriptStatus";

export const PAGE_DESCRIPTION = "Every agent learns this before its own script.";
export const OVERVIEW_HINT = "What is your business, and how should your agents talk about it?";
export const OVERVIEW_INFO =
  "Write it in your own words, as much as you like: what you sell, who your customers are, prices, hours, how you talk to people. Pip writes the training from it.";
export const OVERVIEW_PLACEHOLDER =
  "For example: we are a family bakery in Kukatpally. We make cakes to order and deliver within 5 km. Call customers sir or madam.";
export const MATERIALS_HINT = "What Pip should read first.";
export const MATERIALS_INFO =
  "Price lists, brochures, your website, notes. Files and links also go into your knowledge, so agents can look things up on a call.";
export const TRAINING_HINT = "What every agent is given.";
export const TRAINING_INFO =
  "Each agent, campaign and phone line keeps its own script on top of this. Where a script says something different, the script wins on its own calls.";

export function CompanyTrainingScreen() {
  const { session } = useClientRealm();
  const training = useCompanyTraining(session);
  const write = useWriteAccess(session, "org:manage", "change the company training");
  const canWrite = write.allowed;
  const refusal = write.reason ?? undefined;

  return (
    <div className="max-w-6xl space-y-6 pb-12">
      <PageHeader description={PAGE_DESCRIPTION} />
      <RestrictionNote reason={write.reason} />
      {training.isLoading ? (
        <Skeleton rows={4} label="Loading the company training" />
      ) : !training.data ? (
        <ProblemNotice
          error={training.error ?? new Error("The company training did not load.")}
          onRetry={() => training.refetch()}
        />
      ) : (
        <FoldGroup className="space-y-8">
          <Overview data={training.data} canWrite={canWrite} refusal={refusal} />
          <Materials data={training.data} canWrite={canWrite} refusal={refusal} />
          <Training data={training.data} canWrite={canWrite} refusal={refusal} />
        </FoldGroup>
      )}
    </div>
  );
}

type Props = { data: CompanyTraining; canWrite: boolean; refusal?: string };

function Overview({ data, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const [editing, setEditing] = useState(data.overview.trim() === "");
  const [text, setText] = useState(data.overview);
  const save = useSaveOverview(session);
  useActionFeedback(save, { errorDisplay: "inline" });
  const dirty = text.trim() !== data.overview.trim();

  const cancel = () => {
    setText(data.overview);
    save.reset();
    setEditing(data.overview.trim() === "");
  };

  return (
    <FoldSection id="training-overview" title="About the business" tone="task" hint={OVERVIEW_HINT} info={OVERVIEW_INFO}>
      {editing ? (
        <>
          <label htmlFor="training-overview-text" className="sr-only">
            About the business
          </label>
          <textarea
            id="training-overview-text"
            className={`${FIELD} min-h-36 w-full resize-y`}
            value={text}
            maxLength={data.overview_max}
            disabled={!canWrite}
            title={refusal}
            placeholder={OVERVIEW_PLACEHOLDER}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              disabled={!canWrite || !text.trim() || !dirty || save.isPending}
              title={refusal}
              onClick={() => save.mutate(text, { onSuccess: () => setEditing(false) })}
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {data.overview.trim() !== "" && (
              <button type="button" className={SECONDARY_BUTTON_SM} disabled={save.isPending} onClick={cancel}>
                Cancel
              </button>
            )}
            <span className="ml-auto text-meta tabular-nums text-ink-muted">
              {text.length.toLocaleString("en-IN")} / {data.overview_max.toLocaleString("en-IN")}
            </span>
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
            {data.overview}
          </ExpandableText>
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} mt-3`}
            disabled={!canWrite}
            title={refusal}
            onClick={() => {
              setText(data.overview);
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

function Materials({ data, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const add = useAddTrainingMaterial(session);
  const upload = useUploadTrainingMaterial(session);
  const archive = useArchiveTrainingMaterial(session);
  useActionFeedback(add, { errorDisplay: "inline" });
  useActionFeedback(upload, { errorDisplay: "inline" });
  const archiveFeedback = useActionFeedback(archive, { errorTitle: "Could not remove it", successToast: "Removed" });

  return (
    <FoldSection id="training-materials" title="Materials" tone="materials" hint={MATERIALS_HINT} info={MATERIALS_INFO}>
      <MaterialForm
        canWrite={canWrite}
        refusal={refusal}
        onAdd={({ file, ...item }) => {
          add.reset();
          upload.reset();
          return file ? upload.mutateAsync({ file, title: item.title }) : add.mutateAsync(item);
        }}
        adding={add.isPending || upload.isPending}
        addError={upload.error ?? add.error}
      />
      {data.materials.length > 0 && (
        <ul className="mt-4 max-w-4xl divide-y divide-line border-y border-line">
          {data.materials.map((m) => (
            <li key={m.id} className="flex items-start gap-3 py-3.5">
              <span className="mt-0.5 w-12 shrink-0 text-meta text-ink-muted">{KIND_LABEL[m.kind]}</span>
              <div className="min-w-0 flex-1">
                <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">{m.title}</p>
                {m.url && (
                  <a
                    href={m.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-meta text-ink-muted underline decoration-line underline-offset-2 hover:text-ink [overflow-wrap:anywhere]"
                  >
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
        </ul>
      )}
    </FoldSection>
  );
}

function Training({ data, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const ask = useRequestTraining(session);
  const clear = useClearTrainingProposal(session);
  const save = useSaveTraining(session);
  const askFeedback = useActionFeedback(ask, { errorDisplay: "inline" });
  const stopFeedback = useActionFeedback(clear, { errorTitle: "Could not stop Pip" });
  useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved. Every agent gets it now." });
  // The text being edited, and the Pip draft it started from (kept with it on Save).
  const [draft, setDraft] = useState<{ text: string; proposalId?: string } | null>(null);
  const proposal = data.proposal;
  const hasOverview = data.overview.trim() !== "";
  const failed = proposal?.status === "failed";
  const reason = !hasOverview
    ? "Save About the business first."
    : proposal?.status === "ready"
      ? "Read Pip's training below first."
      : failed
        ? "Pip's last try did not finish. See why below."
        : undefined;

  const keep = (text: string, proposalId?: string) =>
    save.mutate({ training: text, proposal_id: proposalId }, { onSuccess: () => setDraft(null) });

  return (
    <FoldSection
      id="training-text"
      title="Training"
      tone="script"
      hint={TRAINING_HINT}
      info={TRAINING_INFO}
      aside={data.version > 0 ? `Version ${data.version}` : undefined}
    >
      <div className="mb-4">
        <PipGenerateBand
          heading="Let Pip, our AI agent, write the training"
          from="Pip writes it from About the business and your materials."
          onGenerate={() => askFeedback.run(undefined)}
          busy={ask.isPending || proposal?.status === "drafting"}
          disabled={!canWrite || !hasOverview || (proposal != null && !(failed && retryable(proposal.reason)))}
          reason={reason}
          refusal={refusal}
          label={failed ? "Try again" : "Generate"}
          inline
        />
        {ask.error != null && (
          <div className="mt-2">
            <ProblemNotice error={ask.error} />
          </div>
        )}
      </div>

      {save.error != null && (
        <div className="mb-3">
          <ProblemNotice error={save.error} />
        </div>
      )}

      {proposal?.status === "drafting" && (
        <PipWriting
          proposal={proposal}
          what="the training"
          stopping={clear.isPending}
          onStop={() => stopFeedback.run(proposal.id)}
        />
      )}

      {proposal?.status === "failed" && (
        <PipFailed
          proposal={proposal}
          what="the training"
          canWrite={canWrite}
          retrying={ask.isPending}
          dismissing={clear.isPending}
          onRetry={() => askFeedback.run(undefined)}
          onDismiss={() => stopFeedback.run(proposal.id)}
        />
      )}

      {draft ? (
        <TrainingEditor
          value={draft.text}
          max={data.training_max}
          saving={save.isPending}
          canWrite={canWrite}
          refusal={refusal}
          onChange={(text) => setDraft({ ...draft, text })}
          onSave={() => keep(draft.text, draft.proposalId)}
          onCancel={() => {
            save.reset();
            setDraft(null);
          }}
        />
      ) : proposal?.status === "ready" && proposal.training ? (
        <div className="space-y-3 border-y border-line py-4">
          <h3 className="text-body font-semibold text-ink">Pip&apos;s training</h3>
          {proposal.disclosure && <p className="text-meta text-ink-muted">{proposal.disclosure}</p>}
          <ExpandableText
            lines={12}
            moreLabel="Show all"
            lessLabel="Show less"
            className="text-body text-ink"
            textClassName="whitespace-pre-wrap [overflow-wrap:anywhere]"
          >
            {proposal.training}
          </ExpandableText>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              disabled={!canWrite || save.isPending || clear.isPending}
              title={refusal}
              onClick={() => keep(proposal.training ?? "", proposal.id)}
            >
              {save.isPending ? "Saving…" : "Keep it"}
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!canWrite || save.isPending || clear.isPending}
              title={refusal}
              onClick={() => setDraft({ text: proposal.training ?? "", proposalId: proposal.id })}
            >
              Edit first
            </button>
            <button
              type="button"
              className={TEXT_ACTION_DANGER}
              disabled={!canWrite || save.isPending || clear.isPending}
              title={refusal}
              onClick={() => stopFeedback.run(proposal.id)}
            >
              Discard
            </button>
          </div>
        </div>
      ) : data.training.trim() ? (
        <div>
          <ExpandableText
            lines={8}
            moreLabel="Show all"
            lessLabel="Show less"
            className="text-body text-ink"
            textClassName="whitespace-pre-wrap [overflow-wrap:anywhere]"
          >
            {data.training}
          </ExpandableText>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!canWrite || proposal != null}
              title={refusal}
              onClick={() => setDraft({ text: data.training })}
            >
              Edit training
            </button>
            {data.updated_at && (
              <span className="text-meta text-ink-muted">Saved {formatIST(data.updated_at)}</span>
            )}
          </div>
        </div>
      ) : (
        !proposal && (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-body text-ink-muted">
              {hasOverview ? "No training yet. Press Generate above." : "Write About the business first."}
            </p>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!canWrite}
              title={refusal}
              onClick={() => setDraft({ text: "" })}
            >
              Write it myself
            </button>
          </div>
        )
      )}
    </FoldSection>
  );
}

function TrainingEditor({
  value,
  max,
  saving,
  canWrite,
  refusal,
  onChange,
  onSave,
  onCancel,
}: {
  value: string;
  max: number;
  saving: boolean;
  canWrite: boolean;
  refusal?: string;
  onChange: (text: string) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div>
      <label htmlFor="training-editor" className="sr-only">
        Training
      </label>
      <textarea
        id="training-editor"
        className={`${FIELD} min-h-72 w-full resize-y`}
        value={value}
        maxLength={max}
        disabled={!canWrite}
        title={refusal}
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={PRIMARY_BUTTON_SM}
          disabled={!canWrite || saving}
          title={refusal}
          onClick={onSave}
        >
          {saving ? "Saving…" : "Save for every agent"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={saving} onClick={onCancel}>
          Cancel
        </button>
        <span className="ml-auto text-meta tabular-nums text-ink-muted">
          {value.length.toLocaleString("en-IN")} / {max.toLocaleString("en-IN")}
        </span>
      </div>
    </div>
  );
}
