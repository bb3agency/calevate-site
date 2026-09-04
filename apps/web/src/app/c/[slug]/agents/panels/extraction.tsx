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
import { useFormValidation } from "@/components/formValidation";
import { useToast } from "@/components/interior/toaster";
import { isDeleted } from "@/lib/agentState";
import { useWriteAccess } from "@/lib/api/hooks";
import { useSetExtractionSchema, type Agent } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText, noFill } from "@/lib/copilot/types";

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
import { useVerticalExamples } from "@/lib/useVerticalExamples";

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
  if (isDeleted(agent)) {
    return <ArchivedExtractionList agent={agent} leadsHref={leadsHref} />;
  }
  return <ExtractionEditor agent={agent} leadsHref={leadsHref} />;
}

/** The editable form: add, rename, retype, reorder, delete, then save the whole list. */
function ExtractionEditor({ agent, leadsHref }: { agent: Agent; leadsHref: ReactNode }) {
  const session = useClientSession();
  // This tenant's trade, not a clinic's — see `lib/verticalExamples.ts`.
  const eg = useVerticalExamples();
  const save = useSetExtractionSchema(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change what this agent captures");
  const { toast } = useToast();

  const [rows, setRows] = useState<DraftRow[]>(() => agent.extraction_fields.map(toDraft));

  const savedCanonical = useMemo(() => canonical(agent.extraction_fields), [agent.extraction_fields]);
  const wireFields = toWireFields(rows);
  const dirty = canonical(wireFields) !== savedCanonical;
  const clientError = clientValidationError(rows);
  /* A nameless variable is answered AT its row (see `FieldEditorRow`); the two rules
     `clientValidationError` still holds are about the list as a whole. */
  const valid = useFormValidation();

  /*
   * THE CAPTURE COLUMNS, DECLARED TO THE SCREEN ASSISTANT.
   *
   * `DraftRow[]` in one `useState`, so the fill is one `setRows` — never the DOM.
   *
   * ROWS ARE ADDRESSED BY `uid`, NOT BY INDEX, and that is the point of this
   * registration rather than a detail of it: this list can be REORDERED while the panel
   * is open (`move` swaps two rows), so `rows.2.label` names a different variable after a
   * click that the assistant never saw. `uid` is minted per row and survives the swap.
   *
   * `key` is offered only on a NEW row. An existing variable's key is its storage id and
   * older leads' values are filed under it, so changing it orphans a column's history —
   * the editor shows it read-only for exactly that reason, and an assistant that could
   * write it would go round the one guard.
   */
  useCopilotSurface({
    route: "/c/{slug}/agents/{id} — what it writes down",
    title: "What the agent writes down",
    realm: "client",
    fields: rows.flatMap((row, index) => {
      const at = `variable ${index + 1}`;
      const fields = [
        { id: `extraction-${row.uid}-label`, label: `${at} name`, type: "text" as const, value: row.label },
        {
          id: `extraction-${row.uid}-type`,
          label: `${at} type`,
          type: "select" as const,
          value: row.type,
          options: Object.entries(FIELD_TYPE_COPY).map(([value, label]) => ({ value, label })),
        },
        {
          id: `extraction-${row.uid}-required`,
          label: `${at} required`,
          type: "bool" as const,
          value: row.required ? "true" : "false",
        },
        {
          id: `extraction-${row.uid}-reason`,
          label: `${at} — why the agent asks`,
          type: "textarea" as const,
          value: row.reason,
        },
      ];
      if (row.type === "enum") {
        fields.push({
          id: `extraction-${row.uid}-enumText`,
          label: `${at} choices`,
          type: "textarea" as const,
          value: row.enumText,
          // The editor takes one choice per line; a comma-separated answer would become
          // a single choice containing commas.
          help: "One choice per line.",
        } as (typeof fields)[number]);
      }
      if (row.isNew) {
        fields.push({
          id: `extraction-${row.uid}-key`,
          label: `${at} storage key`,
          type: "text" as const,
          value: row.key,
          help: "Lower-case, underscores. Left alone it is derived from the name.",
        } as (typeof fields)[number]);
      }
      return fields;
    }),
    /*
     * THE AGENT THIS PANEL BELONGS TO, and the reason it is declared HERE rather than on
     * the workspace around it.
     *
     * `registry.ts` keeps a STACK and the innermost registration wins — and child effects
     * commit before their parent's, so a surface declared by `AgentWorkspace` would push
     * on top of this one and take the capture columns away from the assistant on the one
     * screen they can be edited from. The agent's own state is small, so it travels with
     * the panel instead of displacing it.
     *
     * Every value here is the agent's configuration, which is the client's own writing —
     * no caller, no lead and no transcript is reachable from this component at all.
     */
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      { key: "agent_name", label: "Agent name", value: agent.name },
      { key: "agent_status", label: "Status", value: agent.status },
      { key: "agent_direction", label: "Direction", value: agent.direction },
      { key: "agent_language", label: "Primary language", value: agent.language_primary },
      {
        key: "agent_published",
        label: "Is what callers hear the same as what is saved here?",
        value: agent.published ? "yes — it is published" : "no — there are unpublished changes",
      },
      {
        key: "agent_inbound_numbers",
        label: "Numbers this agent answers",
        value: String(agent.inbound_number_count),
      },
      {
        key: "agent_llm_model",
        label: "AI model it runs on",
        value: `${agent.llm_model_effective} (chosen at the ${agent.llm_model_source} level)`,
      },
      {
        key: "agent_announcements",
        label: "What it volunteers at the start of a call",
        value: `AI disclosure: ${agent.ai_disclosure_enabled ? "on" : "off"}, recording notice: ${agent.recording_notice_enabled ? "on" : "off"}`,
      },
      {
        key: "capture_unsaved",
        label: "Are there unsaved changes to the capture list?",
        value: dirty ? "yes" : "no",
      },
      {
        key: "capture_may_save",
        label: "May this session save the capture list?",
        value: write.allowed ? "yes" : "no",
      },
    ],
    apply: (items) => {
      setRows((current) =>
        current.map((row) => {
          const patch: Partial<DraftRow> = {};
          for (const item of items) {
            const prefix = `extraction-${row.uid}-`;
            if (!item.field_id.startsWith(prefix)) continue;
            const member = item.field_id.slice(prefix.length);
            const text = asText(item.value);
            if (member === "label") patch.label = text;
            else if (member === "reason") patch.reason = text;
            else if (member === "enumText") patch.enumText = text;
            // Both shapes, for `intakeSurface`'s reason: the server sends a real boolean
            // for a `bool` field, and a model answering a text field with "true" should
            // still tick the box rather than write the word into it.
            else if (member === "required") patch.required = item.value === true || text === "true";
            // `keyTouched` rides along, exactly as the key input's own `onChange` does:
            // without it the typed key is thrown away the next time the label changes.
            else if (member === "key" && row.isNew) {
              patch.key = text;
              patch.keyTouched = true;
            } else if (member === "type" && lookup(FIELD_TYPE_COPY, text) !== undefined) {
              patch.type = item.value as DraftRow["type"];
            }
          }
          return Object.keys(patch).length === 0 ? row : { ...row, ...patch };
        }),
      );
    },
  });

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
        noValidate
        onSubmit={valid.onSubmit(() => {
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
        })}
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
                eg={eg}
                key={row.uid}
                row={row}
                index={index}
                total={rows.length}
                disabled={!write.allowed || save.isPending}
                validation={valid}
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

/** A deleted agent's columns, as the record they are — no editor, and a sentence saying why. */
function ArchivedExtractionList({
  agent,
  leadsHref,
}: {
  agent: Agent;
  leadsHref: ReactNode;
}) {
  /*
   * THE ARCHIVED AGENT'S SCREEN, DECLARED — because otherwise it is the one agent screen
   * with no launcher on it.
   *
   * `ExtractionEditor` carries the declaration for a working agent; a retired one renders
   * this component instead, and a screen whose whole subject is "what did this agent used
   * to do" is exactly where somebody asks. No field: the columns are a record of what the
   * agent did and editing them would rewrite that record, which is why this list is
   * read-only in the first place.
   */
  useCopilotSurface({
    route: "/c/{slug}/agents/{id} — a retired agent",
    title: "A retired agent",
    realm: "client",
    fields: [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      { key: "agent_name", label: "Agent name", value: agent.name },
      { key: "agent_status", label: "Status", value: agent.status },
      { key: "agent_archived_at", label: "Retired (UTC)", value: agent.archived_at ?? "not recorded" },
      { key: "agent_direction", label: "What it used to do", value: agent.direction },
      { key: "agent_language", label: "What it spoke", value: agent.language_primary },
      {
        key: "capture_fields",
        label: "Details it used to write down (the field names, never a value)",
        value: agent.extraction_fields.map((field) => field.label).join(", ") || "none",
      },
    ],
    apply: noFill,
  });

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
        This agent is deleted, so its columns in your {leadsHref} table are kept exactly as
        they were — part of the record of what it did. Bring it back first to change them.
      </p>
    </section>
  );
}
