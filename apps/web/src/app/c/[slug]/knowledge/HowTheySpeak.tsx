"use client";

/**
 * HOW THEY SPEAK (D-996): the one training every agent of the account is given (founder, 16 Nov
 * 2026), the way a company trains everyone it hires before assigning them work. A tab of What
 * your agents know: the other tabs hold the facts agents look up, this one how they behave.
 * Each campaign and inbound line keeps its own script on top of it.
 *
 * Built like a campaign's set-up (D-992), with the same coloured folds:
 *  1. About the business: the owner's own words, many lines.
 *  2. The training: Pip writes it by itself in the background (D-1034) from 1, the business
 *     profile and every source on this page, saves it live, and rewrites it when they change.
 *     The owner can still edit it (Pip keeps their edits in every rewrite) or press Rewrite
 *     now, which runs the same job; there is no second writer.
 *
 * It has no sources of its own: what Pip reads is added with the page's Add area, once.
 */

import Link from "next/link";
import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ExpandableText } from "@/components/arc/expandable-text";
import { STATE_DOT, StatusPill } from "@/components/console/statusPill";
import {
  FIELD,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { problemOf } from "@/lib/api/client";
import {
  useClearTrainingProposal,
  useCompanyTraining,
  useRequestTraining,
  useSaveOverview,
  useSaveTraining,
  type CompanyTraining,
  type MissingPart,
  type WriteReason,
} from "@/lib/api/companyTraining";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { FoldGroup, FoldSection } from "../campaigns/FoldSection";
import { PipAskRefused, PipFailed } from "../campaigns/PipScriptStatus";

export const TAB_LEAD = "Every agent learns this before any line or campaign script.";
export const OVERVIEW_HINT = "What is your business, and how should agents talk?";
export const OVERVIEW_PLACEHOLDER = "For example: we bake cakes to order in Kukatpally.";
export const TRAINING_HINT = "What every agent is given.";
/** The save refusal naming an Inbound line or campaign the training would push over the box. */
export const TOO_LONG_CODE = "company_training_too_long";

export function HowTheySpeak() {
  const { session } = useClientRealm();
  const training = useCompanyTraining(session);
  const write = useWriteAccess(session, "org:manage", "change the company training");
  const canWrite = write.allowed;
  const refusal = write.reason ?? undefined;

  return (
    <div className="space-y-6">
      <p className="text-body text-ink-muted">{TAB_LEAD}</p>
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
    <FoldSection id="training-overview" title="About the business" tone="task" hint={OVERVIEW_HINT}
      info="Write it in your own words, as much as you like: what you sell, who your customers are, how you talk to people. Pip rewrites the training from it, and from everything on this page, whenever it changes."
    >
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

/** Why Pip wrote, as the status line names it. Keys are the server's `reasons`. */
const REASON_WORDS: Record<WriteReason, string> = {
  first_agent: "your first agent",
  knowledge_changed: "knowledge changed",
  profile_changed: "business details changed",
  owner_words: "About the business changed",
  owner_asked: "you asked",
};

export function reasonWords(reasons: readonly WriteReason[]): string {
  return [...new Set(reasons.map((r) => REASON_WORDS[r]))].join(", ");
}

function Training({ data, canWrite, refusal }: Props) {
  const { session } = useClientRealm();
  const rewrite = useRequestTraining(session);
  const clear = useClearTrainingProposal(session);
  const save = useSaveTraining(session);
  const rewriteFeedback = useActionFeedback(rewrite, { errorDisplay: "inline" });
  const dismissFeedback = useActionFeedback(clear, { errorTitle: "Could not dismiss it" });
  useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved. Every agent gets it now." });
  const [draft, setDraft] = useState<string | null>(null);
  const [editedVersion, setEditedVersion] = useState(data.version);
  const proposal = data.proposal;
  const writing = proposal?.status === "drafting";
  const busy = writing || rewrite.isPending;

  return (
    <FoldSection
      id="training-text"
      title="Training"
      tone="script"
      hint={TRAINING_HINT}
      info="Each Inbound line and campaign keeps its own script on top of this. Where a script says something different, the script wins on its own calls. Pip writes this by itself from your business details and knowledge, rewrites it when they change, and keeps your own edits."
      aside={data.version > 0 ? `Version ${data.version}` : undefined}
    >
      {save.error != null && (
        <div className="mb-3 space-y-2">
          <ProblemNotice error={save.error} />
          <ScriptPlaces error={save.error} />
        </div>
      )}
      {rewrite.error != null && (
        <div className="mb-3">
          <PipAskRefused error={rewrite.error} onRetry={() => rewriteFeedback.run(undefined)} />
        </div>
      )}

      {proposal?.status === "failed" ? (
        <div className="mb-4">
          <PipFailed
            proposal={proposal}
            what="the training"
            canWrite={canWrite}
            retrying={rewrite.isPending}
            dismissing={clear.isPending}
            onRetry={() => rewriteFeedback.run(undefined)}
            onDismiss={() => dismissFeedback.run(proposal.id)}
          />
        </div>
      ) : (
        <WriteStatus data={data} />
      )}

      {draft !== null ? (
        <TrainingEditor
          value={draft}
          max={data.training_max}
          saving={save.isPending}
          canWrite={canWrite}
          refusal={refusal}
          onChange={setDraft}
          onSave={() =>
            save.mutate({ training: draft, version: editedVersion }, { onSuccess: () => setDraft(null) })
          }
          onCancel={() => {
            save.reset();
            setDraft(null);
          }}
        />
      ) : (
        <div>
          {data.training.trim() ? (
            <ExpandableText
              lines={8}
              moreLabel="Show all"
              lessLabel="Show less"
              className="text-body text-ink"
              textClassName="whitespace-pre-wrap [overflow-wrap:anywhere]"
            >
              {data.training}
            </ExpandableText>
          ) : (
            <p className="text-body text-ink-muted">{proposal ? "Pip is on it." : EMPTY_TRAINING}</p>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!canWrite}
              title={refusal}
              onClick={() => {
                save.reset();
                setEditedVersion(data.version);
                setDraft(data.training);
              }}
            >
              {data.training.trim() ? "Edit training" : "Write it myself"}
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!canWrite || busy}
              title={refusal}
              onClick={() => rewriteFeedback.run(undefined)}
            >
              {rewrite.isPending ? "Starting…" : "Rewrite now"}
            </button>
          </div>
        </div>
      )}
    </FoldSection>
  );
}

export const EMPTY_TRAINING = "Pip writes this once you add your first agent.";

/**
 * One line on Pip's write: writing now, about to, or when it last wrote and why. Chips say
 * what it kept; the facts newer knowledge replaced sit behind a tap.
 */
function WriteStatus({ data }: { data: CompanyTraining }) {
  const proposal = data.proposal;
  const last = data.last_write;
  if (proposal && proposal.status !== "failed") {
    return (
      <p role="status" className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1">
        <StatusPill tone="info" dot={`${STATE_DOT.waiting} animate-pulse motion-reduce:animate-none`}>
          {proposal.status === "drafting" ? "Pip is rewriting it" : "Pip rewrites it shortly"}
        </StatusPill>
        {proposal.reasons.length > 0 && (
          <span className="text-meta text-ink-muted">{reasonWords(proposal.reasons)}</span>
        )}
      </p>
    );
  }
  if (!last && !data.owner_edited) return null;
  return (
    <div className="mb-4 space-y-1">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {last && (
          <StatusPill tone="ok">
            Pip wrote it {formatIST(last.at)}
          </StatusPill>
        )}
        {last && last.reasons.length > 0 && (
          <span className="text-meta text-ink-muted">{reasonWords(last.reasons)}</span>
        )}
        {last && last.owner_edits_kept > 0 && (
          <span className="text-meta text-ink-muted">Your edits kept: {last.owner_edits_kept}</span>
        )}
        {last?.shortened && <span className="text-meta text-ink-muted">Shortened to fit</span>}
        {data.owner_edited && <StatusPill tone="neutral">Has your edits</StatusPill>}
      </p>
      {last?.disclosure && <p className="text-meta text-ink-muted">{last.disclosure}</p>}
      {last?.missing && last.missing.length > 0 && <MissingParts missing={last.missing} />}
      {last && last.superseded.length > 0 && (
        <details className="text-meta text-ink-muted">
          <summary className="cursor-pointer">Newer knowledge replaced {last.superseded.length}</summary>
          <ul className="mt-1 space-y-1">
            {last.superseded.map((fact) => (
              <li key={fact} className="[overflow-wrap:anywhere]">
                {fact}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

const MISSING_WORDS: Record<MissingPart, string> = {
  business: "what your business does",
  offer: "what you sell or provide",
  customers: "who your customers are",
};

/**
 * What Pip could not describe without guessing, and where to say it: Pip leaves such a part
 * out rather than writing it from a source about one piece of work (founder, 24 Nov 2026).
 */
function MissingParts({ missing }: { missing: readonly MissingPart[] }) {
  const said = missing.map((part) => MISSING_WORDS[part]);
  const list = said.length > 1 ? `${said.slice(0, -1).join(", ")} and ${said.at(-1)}` : said[0];
  return (
    <div role="note" className="mt-2 rounded-card border border-line bg-warn-soft p-3">
      <p className="text-meta font-medium text-ink">Pip needs more about your business</p>
      <p className="mt-1 text-meta text-ink-muted">Your knowledge does not say {list}.</p>
      <p className="text-meta text-ink-muted">
        Write it under About the business, or add a file that says it.
      </p>
      <a href="#training-overview" className={`${SECONDARY_BUTTON_SM} mt-2 inline-flex`}>
        Write about the business
      </a>
    </div>
  );
}

/**
 * The way out of a too-long refusal: a button straight to the Inbound line, campaign or
 * agent the server named, or both lists when it named none (a server older than the id).
 */
function ScriptPlaces({ error }: { error: unknown }) {
  const { session, href } = useClientRealm();
  const tooLong = problemOf<"CompanyTrainingTooLong">(error, TOO_LONG_CODE);
  if (!tooLong) return null;
  const base = `/c/${session.orgSlug}`;
  const id = (value: unknown) => (typeof value === "string" && value ? value : null);
  const lineId = id(tooLong.inbound_line_id);
  const campaignId = id(tooLong.campaign_id);
  const agentId = id(tooLong.agent_id);
  const named = lineId
    ? { to: `${base}/inbound/${lineId}`, label: "Open the Inbound line" }
    : campaignId
      ? { to: `${base}/campaigns/${campaignId}`, label: "Open the campaign" }
      : agentId
        ? { to: `${base}/agents/${agentId}`, label: "Open the agent" }
        : null;
  return (
    <div className="flex flex-wrap gap-2">
      {named ? (
        <Link href={href(named.to)} className={SECONDARY_BUTTON_SM}>
          {named.label}
        </Link>
      ) : (
        <>
          <Link href={href(`${base}/inbound`)} className={SECONDARY_BUTTON_SM}>
            Open Inbound lines
          </Link>
          <Link href={href(`${base}/campaigns`)} className={SECONDARY_BUTTON_SM}>
            Open Campaigns
          </Link>
        </>
      )}
    </div>
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
