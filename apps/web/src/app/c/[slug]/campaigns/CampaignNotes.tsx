"use client";

/**
 * WHAT IT NOTES (D-1028): the details a campaign's or an inbound line's calls write down. The
 * list belongs to the job, never to the agent, so the campaign page and the line page show
 * this one editor. Rows are the shared field row (`agents/panels/extractionRow`) and draft
 * arithmetic (`agents/panels/extractionDraft`). A save over a list changed elsewhere is
 * refused (`<kind>_notes_changed_elsewhere`) and offers the current list. "Import from
 * another ..." loads another job's list into the editor as an unsaved change; Save keeps it.
 */

import { useMemo, useState } from "react";
import { ChevronDown, Download, Plus, Save } from "lucide-react";
import Link from "next/link";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Menu, type MenuItem } from "@/components/arc/menu";
import { EmptyState } from "@/components/console/emptyState";
import { useFormValidation } from "@/components/formValidation";
import { ProblemNotice, SECONDARY_BUTTON, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import { useCampaigns } from "@/lib/api/campaigns";
import {
  useFetchJobNotes,
  useJobNotes,
  useSaveJobNotes,
  type JobKind,
  type JobNotes as Notes,
} from "@/lib/api/campaignWorkspace";
import { useInboundLines } from "@/lib/api/inboundLines";
import { useClientRealm } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

import { blankRow, canonical, clientValidationError, toDraft, toWireFields, type DraftRow } from "../agents/panels/extractionDraft";
import { FieldEditorRow } from "../agents/panels/extractionRow";
import { TEAM_ALERTS_ANCHOR } from "../agents/panels/teamAlerts";
import { campaignStatusWord } from "./campaignStatus";
import { FoldSection } from "./FoldSection";

/**
 * When a saved campaign list reaches the calls. `applied_now` is a held engine agent, put live
 * on save; a running or paused campaign without one gets one at its next dial; a stopped one at
 * its next Start; a draft or a scheduled one at its first call.
 */
export function notesTakeEffect(appliedNow: boolean, status: string | null | undefined): string {
  if (appliedNow || status === "running" || status === "paused") return "From its next call.";
  if (status === "completed" || status === "cancelled") return "From its next Start.";
  return "From its first call.";
}

/** When a saved line list reaches the calls: a live line is put live again on save. */
export function lineNotesTakeEffect(appliedNow: boolean): string {
  return appliedNow ? "From its next call." : "When you put it live.";
}

const NOUN: Record<JobKind, string> = { campaign: "campaign", line: "line" };

type JobProps = {
  kind: JobKind;
  jobId: string;
  slug: string;
  canWrite: boolean;
  refusal?: string;
  /** When a saved list reaches the calls, from the server's `applied_now`. */
  takeEffect: (appliedNow: boolean) => string;
};

export function JobNotes(props: JobProps) {
  const { session } = useClientRealm();
  const notes = useJobNotes(session, props.kind, props.jobId);
  const noun = NOUN[props.kind];
  return (
    <FoldSection
      id={`${props.kind}-notes-${props.jobId}`}
      title="What it notes"
      tone="details"
      hint="The details its calls write down."
      info={`The agent asks for these on this ${noun}'s calls and writes them on the lead.`}
    >
      {notes.error != null && <ProblemNotice error={notes.error} onRetry={() => notes.refetch()} />}
      {!notes.data && notes.error == null && <Skeleton rows={2} label="Loading what it notes" />}
      {notes.data && (
        <NotesEditor key={notes.data.digest} data={notes.data} onReload={() => void notes.refetch()} {...props} />
      )}
    </FoldSection>
  );
}

type CampaignProps = {
  slug: string;
  campaignId: string;
  /** The campaign's status, which says when a saved list reaches its calls. */
  status?: string | null;
  canWrite: boolean;
  refusal?: string;
};

export function CampaignNotes({ campaignId, status, ...rest }: CampaignProps) {
  return (
    <JobNotes kind="campaign" jobId={campaignId} takeEffect={(now) => notesTakeEffect(now, status)} {...rest} />
  );
}

/**
 * The account's other open campaigns or lines, as the import menu offers them. Read only once
 * the menu is asked for (`wanted`), so a page that never imports never lists them.
 */
function useOtherJobs(
  kind: JobKind,
  jobId: string,
  wanted: boolean,
): { items: { id: string; label: string; hint?: string }[]; loading: boolean; failed: boolean } {
  const { session } = useClientRealm();
  const campaigns = useCampaigns(session, wanted && kind === "campaign");
  const lines = useInboundLines(session, wanted && kind === "line");
  if (kind === "campaign") {
    if (campaigns.error || !campaigns.data) {
      return { items: [], loading: !campaigns.error, failed: campaigns.error != null };
    }
    const rows = campaigns.data.filter((c) => c.id !== jobId && !c.archived_at);
    return {
      loading: false,
      failed: false,
      items: rows.map((c) => ({ id: c.id, label: c.name, hint: campaignStatusWord(c.status) })),
    };
  }
  if (lines.error || !lines.data) {
    return { items: [], loading: !lines.error, failed: lines.error != null };
  }
  const rows = lines.data.filter((l) => l.id !== jobId);
  return {
    loading: false,
    failed: false,
    items: rows.map((l) => ({ id: l.id, label: l.name, hint: l.live ? "Live" : "Draft" })),
  };
}

function ImportMenu({
  kind,
  jobId,
  disabled,
  title,
  onImport,
}: {
  kind: JobKind;
  jobId: string;
  disabled: boolean;
  title?: string;
  onImport: (id: string, name: string) => void;
}) {
  const noun = NOUN[kind];
  const [wanted, setWanted] = useState(false);
  const others = useOtherJobs(kind, jobId, wanted);
  const want = () => setWanted(true);
  const items: MenuItem[] = others.items.length
    ? others.items.map((job) => ({
        id: job.id,
        label: job.label,
        hint: job.hint,
        onSelect: () => onImport(job.id, job.label),
      }))
    : [
        {
          id: "none",
          label: others.failed
            ? `Could not load your ${noun}s. Reload the page to try again.`
            : others.loading || !wanted
              ? `Loading ${noun}s…`
              : `No other active ${noun}s`,
          disabled: true,
        },
      ];
  return (
    <Menu
      label={`Import from another ${noun}`}
      align="start"
      items={items}
      trigger={
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={disabled}
          title={title}
          onPointerDown={want}
          onKeyDown={want}
          onFocus={want}
          onClick={want}
        >
          <Download aria-hidden className="h-4 w-4" />
          Import from another {noun}
          <ChevronDown aria-hidden className="h-4 w-4" />
        </button>
      }
    />
  );
}

function NotesEditor({
  data,
  onReload,
  kind,
  jobId,
  slug,
  canWrite,
  refusal,
  takeEffect,
}: JobProps & { data: Notes; onReload: () => void }) {
  const { session, href } = useClientRealm();
  const eg = useVerticalExamples();
  const save = useSaveJobNotes(session, kind, jobId);
  const fetchNotes = useFetchJobNotes(session, kind);
  const feedback = useActionFeedback(save, { errorDisplay: "inline" });
  const valid = useFormValidation();
  const [rows, setRows] = useState<DraftRow[]>(() => data.fields.map(toDraft));
  const [imported, setImported] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<unknown>(null);

  const saved = useMemo(() => canonical(data.fields), [data.fields]);
  const wire = toWireFields(rows);
  const dirty = canonical(wire) !== saved;
  useUnsavedGuard(dirty);
  const clientError = clientValidationError(rows);
  const conflict = save.error instanceof ApiProblem && save.error.code === `${kind}_notes_changed_elsewhere`;
  const disabled = !canWrite || save.isPending;

  const patchRow = (uid: string, patch: Partial<DraftRow>) =>
    setRows((current) => current.map((row) => (row.uid === uid ? { ...row, ...patch } : row)));
  const move = (index: number, delta: number) =>
    setRows((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  const importFrom = async (id: string, name: string) => {
    setImporting(true);
    setImportError(null);
    try {
      const other = await fetchNotes(id);
      setRows(other.fields.map(toDraft));
      setImported(name);
      save.reset();
    } catch (error) {
      setImportError(error);
    } finally {
      setImporting(false);
    }
  };

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (disabled || !dirty || clientError) return;
        save.mutate(
          { fields: wire, expected_digest: data.digest },
          { onSuccess: () => setImported(null) },
        );
      })}
    >
      {save.error != null && (
        <div>
          <ProblemNotice error={save.error} />
          {conflict && (
            <button
              type="button"
              className={`mt-2 ${SECONDARY_BUTTON}`}
              onClick={() => {
                save.reset();
                onReload();
              }}
            >
              Load the current list
            </button>
          )}
        </div>
      )}
      {importError != null && <ProblemNotice error={importError} />}
      {imported && dirty && (
        <p role="status" className="text-meta text-ink-muted">
          Loaded from {imported}. Save to keep it.
        </p>
      )}
      {rows.length === 0 ? (
        <EmptyState
          align="start"
          message="No details yet."
          hint="Calls still note name, number and a summary."
        />
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {rows.map((row, index) => (
            <FieldEditorRow
              eg={eg}
              key={row.uid}
              row={row}
              index={index}
              total={rows.length}
              disabled={disabled}
              validation={valid}
              noun="detail"
              showKey={false}
              onChange={(patch) => patchRow(row.uid, patch)}
              onDelete={() => setRows((current) => current.filter((r) => r.uid !== row.uid))}
              onMoveUp={() => move(index, -1)}
              onMoveDown={() => move(index, 1)}
            />
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={disabled}
          title={refusal}
          onClick={() => setRows((current) => [...current, blankRow()])}
        >
          <Plus aria-hidden className="h-4 w-4" />
          Add a detail
        </button>
        <ImportMenu
          kind={kind}
          jobId={jobId}
          disabled={disabled || importing}
          title={refusal}
          onImport={(id, name) => void importFrom(id, name)}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <ActionButton
          type="submit"
          status={feedback.status}
          successLabel="Saved"
          disabled={!canWrite || (feedback.status === "idle" && (!dirty || Boolean(clientError)))}
          title={refusal}
        >
          <Save aria-hidden className="h-4 w-4" />
          Save
        </ActionButton>
        {clientError ? (
          <span className="text-xs text-warn">{clientError}</span>
        ) : dirty ? (
          <span className="text-xs text-ink-muted">You have unsaved changes.</span>
        ) : null}
      </div>
      <p className="text-xs text-ink-muted">{takeEffect(data.applied_now)} Old leads keep their values.</p>
      {data.fields.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <p className="text-xs text-ink-muted">Want your team told about an answer?</p>
          <Link
            className={SECONDARY_BUTTON_SM}
            href={href(`/c/${slug}/agents/${data.agent_id}?section=settings#${TEAM_ALERTS_ANCHOR}`)}
          >
            Set alerts
          </Link>
        </div>
      )}
    </form>
  );
}
