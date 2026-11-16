"use client";

/**
 * WHAT THIS CAMPAIGN'S CALLS NOTE (D-1003). Empty follows the agent's own list, so a campaign
 * notes what its agent notes until the owner gives it a list of its own. The rows are edited
 * with the agent's own editor row (`agents/panels/extractionRow`) and its draft arithmetic
 * (`agents/panels/extractionDraft`), so the two lists are written the same way and held to the
 * same rules. A save over a list changed elsewhere is refused (`campaign_notes_changed_elsewhere`)
 * and offers the current list.
 */

import { useMemo, useState } from "react";
import { Plus, Save } from "lucide-react";
import Link from "next/link";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { useFormValidation } from "@/components/formValidation";
import { ProblemNotice, SECONDARY_BUTTON, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import { useCampaignNotes, useSaveCampaignNotes, type CampaignNotes as Notes } from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

import {
  blankRow,
  canonical,
  clientValidationError,
  toDraft,
  toWireFields,
  type DraftRow,
} from "../agents/panels/extractionDraft";
import { FieldEditorRow } from "../agents/panels/extractionRow";
import { TEAM_ALERTS_ANCHOR } from "../agents/panels/teamAlerts";
import { FoldSection } from "./FoldSection";

type Props = { slug: string; campaignId: string; agentId: string; canWrite: boolean; refusal?: string };

const NOTES_INFO =
  "The agent asks for these on this campaign's calls and writes them on the lead. Empty means it notes what the agent notes everywhere else.";

export function CampaignNotes(props: Props) {
  const { session } = useClientRealm();
  const notes = useCampaignNotes(session, props.campaignId, props.agentId);
  return (
    <FoldSection
      id={`campaign-notes-${props.campaignId}`}
      title="What it notes"
      tone="details"
      hint="The details its calls write down."
      info={NOTES_INFO}
    >
      {notes.error != null && <ProblemNotice error={notes.error} onRetry={() => notes.refetch()} />}
      {!notes.data && notes.error == null && <Skeleton rows={2} label="Loading what it notes" />}
      {notes.data && (
        <NotesEditor key={notes.data.digest} data={notes.data} onReload={() => void notes.refetch()} {...props} />
      )}
    </FoldSection>
  );
}

function NotesEditor({
  data,
  onReload,
  slug,
  campaignId,
  canWrite,
  refusal,
}: Props & { data: Notes; onReload: () => void }) {
  const { session } = useClientRealm();
  const eg = useVerticalExamples();
  const save = useSaveCampaignNotes(session, campaignId);
  const feedback = useActionFeedback(save, { errorDisplay: "inline" });
  const valid = useFormValidation();
  const [rows, setRows] = useState<DraftRow[]>(() => data.fields.map(toDraft));
  const [own, setOwn] = useState(data.fields.length > 0);

  const saved = useMemo(() => canonical(data.fields), [data.fields]);
  const wire = own ? toWireFields(rows) : [];
  const dirty = canonical(wire) !== saved;
  useUnsavedGuard(dirty);
  const clientError = own ? clientValidationError(rows) : null;
  const conflict = save.error instanceof ApiProblem && save.error.code === "campaign_notes_changed_elsewhere";
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

  if (!own) {
    return (
      <div className="space-y-3">
        <p className="text-meta text-ink-muted">Same as {data.agent_name}.</p>
        {data.agent_fields.length > 0 ? (
          <ul className="divide-y divide-line border-y border-line">
            {data.agent_fields.map((field) => (
              <li key={field.key} className="py-2 text-meta text-ink">
                {field.label}
                {field.required && <span className="ml-2 text-ink-muted">Required</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-meta text-ink-muted">Name, number and a summary only.</p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={disabled}
            title={refusal}
            onClick={() => {
              setRows(data.agent_fields.length > 0 ? data.agent_fields.map(toDraft) : [blankRow()]);
              setOwn(true);
            }}
          >
            Give it its own list
          </button>
          {dirty && (
            <ActionButton
              type="button"
              status={feedback.status}
              successLabel="Saved"
              disabled={disabled}
              onClick={() => save.mutate({ fields: [], expected_digest: data.digest })}
            >
              <Save aria-hidden className="h-4 w-4" />
              Save
            </ActionButton>
          )}
        </div>
        <p className="text-xs text-ink-muted">
          Change the agent&apos;s list on its <Link className="underline" href={`/c/${slug}/agents/${data.agent_id}`}>page</Link>.
        </p>
      </div>
    );
  }

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (disabled || !dirty || clientError) return;
        save.mutate({ fields: wire, expected_digest: data.digest });
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
      {rows.length === 0 ? (
        <p className="text-meta text-ink-muted">No details yet. Calls still note name, number and a summary.</p>
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
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={disabled} onClick={() => setOwn(false)}>
          Use {data.agent_name}&apos;s list
        </button>
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
      <p className="text-xs text-ink-muted">
        {data.applied_now ? "From its next call." : "From its first call."} Old leads keep their values.
      </p>
      {data.fields.length > 0 && (
        <p className="text-xs text-ink-muted">
          Want your team told about an answer?{" "}
          <Link
            className="underline"
            href={`/c/${slug}/agents/${data.agent_id}?section=settings#${TEAM_ALERTS_ANCHOR}`}
          >
            Set alerts
          </Link>
        </p>
      )}
    </form>
  );
}
