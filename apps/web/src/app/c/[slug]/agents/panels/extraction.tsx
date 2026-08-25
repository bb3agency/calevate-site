"use client";

/**
 * WHAT THE AGENT WRITES DOWN — the capture columns, and the form that changes them.
 *
 * Split out of `agents/panels.tsx` (UX-DOCTRINE §6). The pure half — key derivation, the
 * dirty comparison, the pre-flight validation — lives in `./extractionDraft.ts`; this file
 * is only the rendering.
 */

import { useMemo, useState, type ReactNode } from "react";
import { ListChecks, Plus, Save } from "lucide-react";

import {
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SectionHeading,
} from "@/components/ui";
import { useToast } from "@/components/interior/toaster";
import { ARCHIVED_STATUS } from "@/lib/agentState";
import { useWriteAccess } from "@/lib/api/hooks";
import { useSetExtractionSchema, type Agent } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import {
  FIELD_TYPE_COPY,
  blankRow,
  canonical,
  clientValidationError,
  toDraft,
  toWireFields,
  type DraftRow,
} from "./extractionDraft";
import { FieldEditorRow } from "./extractionRow";

/**
 * What the agent writes down — and, for the owner, the form that changes it (D-21 is
 * superseded here; the capture columns are the client's to edit self-serve).
 *
 * `leadsHref` is passed rather than derived so this component knows nothing about routing
 * or about the view-as marker; the screen that has the slug builds the link. An ARCHIVED
 * agent keeps its columns as a record of what it did — editing them would rewrite that
 * record — so it gets the read-only list, mirroring `AgentIdentity` and `AgentModel`.
 */
export function ExtractionList({ agent, leadsHref }: { agent: Agent; leadsHref: ReactNode }) {
  if (agent.status === ARCHIVED_STATUS) {
    return <ArchivedExtractionList agent={agent} leadsHref={leadsHref} />;
  }
  return <ExtractionEditor agent={agent} leadsHref={leadsHref} />;
}

/** The editable form: add, rename, retype, reorder, delete, then save the whole list. */
function ExtractionEditor({ agent, leadsHref }: { agent: Agent; leadsHref: ReactNode }) {
  const session = useClientSession();
  const save = useSetExtractionSchema(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change what this agent captures");
  const { toast } = useToast();

  const [rows, setRows] = useState<DraftRow[]>(() => agent.extraction_fields.map(toDraft));

  const savedCanonical = useMemo(() => canonical(agent.extraction_fields), [agent.extraction_fields]);
  const wireFields = toWireFields(rows);
  const dirty = canonical(wireFields) !== savedCanonical;
  const clientError = clientValidationError(rows);

  function patchRow(uid: string, patch: Partial<DraftRow>) {
    setRows((current) => current.map((row) => (row.uid === uid ? { ...row, ...patch } : row)));
  }

  function move(index: number, delta: number) {
    setRows((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  return (
    <section>
      <SectionHeading icon={<ListChecks className="h-3.5 w-3.5" />}>
        What it writes down
      </SectionHeading>

      <p className="mt-2 text-sm text-ink-muted">
        These are the columns in your {leadsHref} table. The agent fills them in from the
        conversation — it never reads a form aloud, so a caller who answers early is not
        asked twice.
      </p>

      <RestrictionNote reason={write.reason} />
      {save.error && (
        <div className="mt-3">
          <ProblemNotice error={save.error} />
        </div>
      )}

      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!write.allowed || !dirty || clientError || save.isPending) return;
          save.mutate(
            { fields: toWireFields(rows) },
            {
              onSuccess: (result) => {
                // Repaint from the server's stored answer, not the draft — the validator
                // may have trimmed or reordered, and the screen must show what is on file.
                setRows(result.fields.map(toDraft));
                toast({ tone: "success", title: "Variables saved" });
              },
            },
          );
        }}
      >
        {rows.length === 0 ? (
          <p className="rounded-lg border border-line bg-app px-3 py-3 text-sm text-ink-muted">
            No variables yet. Calls still turn into leads with the caller name, number and a
            summary — add a variable to capture a business-specific detail on top of that.
          </p>
        ) : (
          <ul className="space-y-3">
            {rows.map((row, index) => (
              <FieldEditorRow
                key={row.uid}
                row={row}
                index={index}
                total={rows.length}
                disabled={!write.allowed || save.isPending}
                onChange={(patch) => patchRow(row.uid, patch)}
                onDelete={() => setRows((current) => current.filter((r) => r.uid !== row.uid))}
                onMoveUp={() => move(index, -1)}
                onMoveDown={() => move(index, 1)}
              />
            ))}
          </ul>
        )}

        <button
          type="button"
          onClick={() => setRows((current) => [...current, blankRow()])}
          disabled={!write.allowed || save.isPending}
          title={write.reason ?? undefined}
          className={SECONDARY_BUTTON}
        >
          <Plus aria-hidden className="h-4 w-4" />
          Add variable
        </button>

        <p className="text-xs text-ink-muted">
          {/* What `required` does, without promising an interrogation the product does not
              do: it marks the field REQUIRED in the extraction instruction, and a call that
              ends without it still becomes a lead with that column left empty
              (packages/shared/.../extraction.py). */}
          A variable marked <span className="font-medium text-ink">Required</span> is what
          the agent is told to capture on every call; a call that ends without one still
          becomes a lead, with that column left empty. The optional{" "}
          <span className="font-medium text-ink">reason</span> is fed to the AI so it fills
          the column more accurately — leave it blank to use just the name.
        </p>

        <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
          <button
            type="submit"
            disabled={!write.allowed || !dirty || Boolean(clientError) || save.isPending}
            title={write.reason ?? undefined}
            className={PRIMARY_BUTTON}
          >
            <Save aria-hidden className="h-4 w-4" />
            {save.isPending ? "Saving…" : "Save variables"}
          </button>
          {clientError ? (
            <span className="text-xs text-amber-700 dark:text-amber-400">{clientError}</span>
          ) : dirty ? (
            <span className="text-xs text-ink-muted">You have unsaved changes.</span>
          ) : (
            <span className="text-xs text-ink-muted">Nothing has been changed yet.</span>
          )}
        </div>

        <p className="text-xs text-ink-muted">
          Changes are saved here and take effect on the next call — there is no test run and
          no waiting. Renaming or removing a variable stops it showing as a column on leads
          captured before the change — their saved values are kept, just no longer shown
          under that name. That is why an existing variable&apos;s id cannot be changed here.
        </p>
      </form>
    </section>
  );
}

/** An archived agent's columns, as the record they are — no editor, and a sentence saying why. */
function ArchivedExtractionList({
  agent,
  leadsHref,
}: {
  agent: Agent;
  leadsHref: ReactNode;
}) {
  return (
    <section>
      <SectionHeading icon={<ListChecks className="h-3.5 w-3.5" />}>
        What it writes down
      </SectionHeading>
      {agent.extraction_fields.length > 0 ? (
        <ul className="mt-2 divide-y divide-line">
          {agent.extraction_fields.map((field) => (
            <li key={field.key} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 py-2.5">
              <span className="text-sm font-medium text-ink">{field.label}</span>
              <span className="rounded bg-app px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
                {lookup(FIELD_TYPE_COPY, field.type) ?? field.type}
              </span>
              {field.required && (
                <span className="rounded bg-brand-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-strong">
                  Required
                </span>
              )}
              {field.reason && (
                <span className="w-full text-xs text-ink-muted">{field.reason}</span>
              )}
              {field.enum_values?.length ? (
                <span className="w-full text-xs text-ink-muted">
                  One of: {field.enum_values.join(" · ")}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-ink-muted">This agent captured no extra columns.</p>
      )}
      <p className="mt-2 text-xs text-ink-muted">
        This agent is archived, so its columns in your {leadsHref} table are kept exactly as
        they were — part of the record of what it did. Bring it back first to change them.
      </p>
    </section>
  );
}
