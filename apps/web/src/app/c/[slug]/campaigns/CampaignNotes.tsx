"use client";

/**
 * WHAT IT NOTES (D-1028): the details a campaign's or an inbound line's calls write down. The
 * list belongs to the job, never to the agent, so the campaign page, the line page and every
 * card on Lead details (D-1029) show this one editor. Rows are the shared field row
 * (`agents/panels/extractionRow`) and draft arithmetic (`agents/panels/extractionDraft`). A
 * save over a list changed elsewhere is refused (`<kind>_notes_changed_elsewhere`) and offers
 * the current list. "Import" loads another job's list, or the business's starting set, into
 * the editor as an unsaved change; Save keeps it. The job's suggested changes (D-889) sit at
 * the top of the card; an accept whose put-live was refused still saved, so the editor shows
 * the saved list and the card offers Save again.
 *
 * Where the reads and writes go is a `JobNotesSource`: the client realm's endpoints by
 * default, the operator's twins when the admin Lead details screen provides its own.
 */

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, Download, Plus, Save } from "lucide-react";
import Link from "next/link";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Menu, type MenuItem } from "@/components/arc/menu";
import { EmptyState } from "@/components/console/emptyState";
import { useFormValidation } from "@/components/formValidation";
import { LeadSuggestions } from "@/components/leadFields/LeadSuggestions";
import { ProblemNotice, SECONDARY_BUTTON, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import { useCampaigns } from "@/lib/api/campaigns";
import {
  useFetchJobNotes,
  useJobNotes,
  useSaveJobNotes,
  type JobKind,
  type JobNotes as Notes,
  type JobNotesInput,
} from "@/lib/api/campaignWorkspace";
import { useInboundLines } from "@/lib/api/inboundLines";
import type { LeadField } from "@/lib/api/leadFields";
import { useLeadSuggestions, type LeadSuggestionsApi } from "@/lib/api/leadSuggestions";
import { useClientRealm } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import type { VerticalExamples } from "@/lib/verticalExamples";

import { blankRow, canonical, clientValidationError, toDraft, toWireFields, type DraftRow } from "../agents/panels/extractionDraft";
import { FieldEditorRow } from "../agents/panels/extractionRow";
import { jobAlertsPath } from "../agents/panels/teamAlerts";
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

type OtherJobs = { items: { id: string; label: string; hint?: string }[]; loading: boolean; failed: boolean };

/** Where one realm reads and writes job lists. Each member is a hook, called on every render. */
export interface JobNotesSource {
  audience: "client" | "operator";
  useNotes: (kind: JobKind, jobId: string) => UseQueryResult<Notes>;
  useSave: (kind: JobKind, jobId: string) => UseMutationResult<Notes, Error, JobNotesInput>;
  useFetch: (kind: JobKind) => (jobId: string) => Promise<Notes>;
  /** The account's other open jobs of a kind, read once `wanted` (the import menu opened). */
  useOthers: (kind: JobKind, jobId: string, wanted: boolean) => OtherJobs;
  useSuggestions: (kind: JobKind, jobId: string) => LeadSuggestionsApi;
  /** Where this job's alerts are set, or null where this realm has no such page. */
  useAlertsHref: (kind: JobKind, jobId: string) => string | null;
  /** The example text the field rows show. */
  useExamples: () => VerticalExamples;
}

function useClientOthers(kind: JobKind, jobId: string, wanted: boolean): OtherJobs {
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

// Named so the feedback guard reads it as a hook definition; its caller (`NotesEditor`'s
// `save`) is the use that gets `useActionFeedback`.
const useClientSaveJobNotes: JobNotesSource["useSave"] = (kind, jobId) =>
  useSaveJobNotes(useClientRealm().session, kind, jobId);

/** The client realm's endpoints: the default, so the campaign and line pages provide nothing. */
export const CLIENT_JOB_NOTES: JobNotesSource = {
  audience: "client",
  useNotes: (kind, jobId) => useJobNotes(useClientRealm().session, kind, jobId),
  useSave: useClientSaveJobNotes,
  useFetch: (kind) => useFetchJobNotes(useClientRealm().session, kind),
  useOthers: useClientOthers,
  useSuggestions: (kind, jobId) => useLeadSuggestions(useClientRealm().session, kind, jobId),
  useExamples: useVerticalExamples,
  useAlertsHref: (kind, jobId) => {
    const { href, session } = useClientRealm();
    return href(jobAlertsPath(session.orgSlug, kind, jobId));
  },
};

const JobNotesSourceContext = createContext<JobNotesSource | null>(null);

export function JobNotesSourceProvider({ source, children }: { source: JobNotesSource; children: ReactNode }) {
  return <JobNotesSourceContext.Provider value={source}>{children}</JobNotesSourceContext.Provider>;
}

function useSource(): JobNotesSource {
  return useContext(JobNotesSourceContext) ?? CLIENT_JOB_NOTES;
}

/** A set the platform offers to load into the editor: the business's starting set. */
export type OfferedSet = { label: string; fields: LeadField[] };

type JobProps = {
  kind: JobKind;
  jobId: string;
  canWrite: boolean;
  refusal?: string;
  /** When a saved list reaches the calls, from the server's `applied_now`. */
  takeEffect: (appliedNow: boolean) => string;
  /** The card's name; the job's own page says "What it notes". */
  title?: string;
  /** A state beside the name, such as the job's status pill. */
  aside?: ReactNode;
  /** The line under the name; a link to the job's page on Lead details. */
  hint?: ReactNode;
  /** Offered in the import menu beside the other jobs. */
  offered?: OfferedSet | null;
};

export function JobNotes(props: JobProps) {
  const source = useSource();
  const notes = source.useNotes(props.kind, props.jobId);
  // Here rather than in the editor: an accept changes the list's digest, which remounts the
  // editor, and the accept's outcome (a kept change whose put-live was refused) must outlive it.
  const suggestions = source.useSuggestions(props.kind, props.jobId);
  const noun = NOUN[props.kind];
  return (
    <FoldSection
      id={`${props.kind}-notes-${props.jobId}`}
      title={props.title ?? "What it notes"}
      tone="details"
      aside={props.aside}
      hint={props.hint ?? "The details its calls write down."}
      info={`The agent asks for these on this ${noun}'s calls and writes them on the lead.`}
    >
      {notes.error != null && <ProblemNotice error={notes.error} onRetry={() => notes.refetch()} />}
      {!notes.data && notes.error == null && <Skeleton rows={2} label="Loading what it notes" />}
      {notes.data && (
        <NotesEditor
          key={notes.data.digest}
          data={notes.data}
          source={source}
          suggestions={suggestions}
          onReload={() => void notes.refetch()}
          {...props}
        />
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

export function CampaignNotes({ campaignId, status, canWrite, refusal }: CampaignProps) {
  return (
    <JobNotes
      kind="campaign"
      jobId={campaignId}
      canWrite={canWrite}
      refusal={refusal}
      takeEffect={(now) => notesTakeEffect(now, status)}
    />
  );
}

function ImportMenu({
  kind,
  jobId,
  disabled,
  title,
  offered,
  source,
  onImport,
}: {
  kind: JobKind;
  jobId: string;
  disabled: boolean;
  title?: string;
  offered?: OfferedSet | null;
  source: JobNotesSource;
  onImport: (choice: { id: string; name: string } | OfferedSet) => void;
}) {
  const noun = NOUN[kind];
  const [wanted, setWanted] = useState(false);
  const others = source.useOthers(kind, jobId, wanted);
  const want = () => setWanted(true);
  const fromSet: MenuItem[] =
    offered && offered.fields.length > 0
      ? [{ id: "offered-set", label: offered.label, hint: "Standard", onSelect: () => onImport(offered) }]
      : [];
  const fromJobs: MenuItem[] = others.items.length
    ? others.items.map((job) => ({
        id: job.id,
        label: job.label,
        hint: job.hint,
        onSelect: () => onImport({ id: job.id, name: job.label }),
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
      items={[...fromSet, ...fromJobs]}
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
          {offered && offered.fields.length > 0 ? "Import" : `Import from another ${noun}`}
          <ChevronDown aria-hidden className="h-4 w-4" />
        </button>
      }
    />
  );
}

function NotesEditor({
  data,
  source,
  suggestions,
  onReload,
  kind,
  jobId,
  canWrite,
  refusal,
  takeEffect,
  offered,
}: JobProps & { data: Notes; source: JobNotesSource; suggestions: LeadSuggestionsApi; onReload: () => void }) {
  const eg = source.useExamples();
  const save = source.useSave(kind, jobId);
  const fetchNotes = source.useFetch(kind);
  const alertsHref = source.useAlertsHref(kind, jobId);
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
  const importFrom = async (choice: { id: string; name: string } | OfferedSet) => {
    setImportError(null);
    save.reset();
    if ("fields" in choice) {
      setRows(choice.fields.map(toDraft));
      setImported(choice.label);
      return;
    }
    setImporting(true);
    try {
      const other = await fetchNotes(choice.id);
      setRows(other.fields.map(toDraft));
      setImported(choice.name);
    } catch (error) {
      setImportError(error);
    } finally {
      setImporting(false);
    }
  };

  // An accepted suggestion kept its change but did not reach the calls: Save over the same list
  // is the retry the refusal names, so it is offered with nothing changed.
  const kept = suggestions.kept != null;
  const submit = () => {
    if (disabled || (!dirty && !kept) || clientError) return;
    // From here the save answers for itself, a refused put-live included.
    suggestions.clearKept();
    save.mutate(
      { fields: wire, expected_digest: data.digest },
      { onSuccess: () => setImported(null) },
    );
  };

  return (
    <form className="space-y-4" noValidate onSubmit={valid.onSubmit(submit)}>
      <LeadSuggestions
        api={suggestions}
        canWrite={canWrite}
        dirty={dirty}
        audience={source.audience}
        onSaveAgain={submit}
        savingAgain={save.isPending}
      />
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
          offered={offered}
          source={source}
          onImport={(choice) => void importFrom(choice)}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <ActionButton
          type="submit"
          status={feedback.status}
          successLabel="Saved"
          disabled={!canWrite || (feedback.status === "idle" && ((!dirty && !kept) || Boolean(clientError)))}
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
      {data.fields.length > 0 && alertsHref && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <p className="text-xs text-ink-muted">Want your team told about an answer?</p>
          <Link className={SECONDARY_BUTTON_SM} href={alertsHref}>
            Set alerts
          </Link>
        </div>
      )}
    </form>
  );
}
