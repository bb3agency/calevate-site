"use client";

/**
 * LEAD DETAILS WE CAPTURE — the screen, for the client and for an operator.
 *
 * Founder decision 15 (10 Oct 2026): every lead carries a fixed core whatever the business,
 * plus details about THIS business — its type's standard set, or for a business that fits
 * no type, a set drafted once from its own business details. The core is shown as
 * always-on and cannot be edited; the business details are the owner's to add, rename,
 * retype, mark required, reorder and remove, per agent.
 *
 * The data and the four writes are passed in, so the client screen and the operator's
 * screen render one component and differ only in which endpoints they call
 * (`lib/api/leadFields.ts`).
 */

import { useMemo, useState } from "react";
import { Lock, Plus, Save } from "lucide-react";
import type { UseMutationResult } from "@tanstack/react-query";

import { FieldEditorRow } from "@/app/c/[slug]/agents/panels/extractionRow";
import {
  blankRow,
  canonical,
  clientValidationError,
  toDraft,
  toWireFields,
  type DraftRow,
} from "@/app/c/[slug]/agents/panels/extractionDraft";
import { ConfirmDialog } from "@/components/confirmDialog";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SavedTick } from "@/components/console/savedTick";
import { useFormValidation } from "@/components/formValidation";
import {
  FilterChip,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
  formatISTStamp,
} from "@/components/ui";
import type {
  DraftRequestOut,
  DraftReviewOut,
  ExtractionSchemaOut,
  LeadField,
  LeadFields,
  LeadFieldsAgent,
  LeadFieldsDraft,
  ReplaceOut,
  SaveAgentLeadFieldsIn,
} from "@/lib/api/leadFields";
import { ApiProblem } from "@/lib/api/client";
import type { LeadSuggestionsApi } from "@/lib/api/leadSuggestions";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { lookup } from "@/lib/lookup";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import type { VerticalExamples } from "@/lib/verticalExamples";

import { LeadSuggestions } from "./LeadSuggestions";

/** The core, in the owner's words. The server's labels head each row; these explain them. */
const CORE_MEANING: Readonly<Record<string, string>> = {
  name: "Who called",
  need: "What they want, or why they called",
  preferred_time: "When they'd like it, or a time to call back",
  other_number: "Another number they asked to be reached on",
  language: "The language they spoke",
  notes: "Anything else worth knowing before you call back",
};

export interface LeadDetailsWrites {
  save: UseMutationResult<ExtractionSchemaOut, Error, SaveAgentLeadFieldsIn>;
  /** The operator's button. On the client's screen the draft is asked of Pip (D-821). */
  draft?: UseMutationResult<DraftRequestOut, Error, void>;
  /** The owner's review of a finished draft: keep these keys. Client only. */
  review?: UseMutationResult<DraftReviewOut, Error, string[]>;
  replace: UseMutationResult<ReplaceOut, Error, { agent_ids?: string[] | null }>;
  /** One agent's suggested changes (D-889), read and answered in this realm. A hook. */
  useSuggestions: (agentId: string) => LeadSuggestionsApi;
}

export function LeadDetailsView({
  data,
  audience,
  canWrite,
  writeReason,
  writes,
  eg,
}: {
  data: LeadFields;
  /** "client" speaks to the owner ("your business"); "operator" names the client. */
  audience: "client" | "operator";
  canWrite: boolean;
  writeReason: string | null;
  writes: LeadDetailsWrites;
  eg: VerticalExamples;
}) {
  const your = audience === "client" ? "your" : "this client's";
  return (
    <div className="max-w-3xl space-y-10">
      <p className="max-w-prose text-body text-ink-muted [text-wrap:pretty]">
        Every call becomes a lead, with these details as its columns in Leads.
      </p>
      {writeReason && <RestrictionNote reason={writeReason} />}

      <CoreFields fields={data.core_fields} />

      <Section
        title={audience === "client" ? "Details about your business" : "Details about this business"}
        description={<Origin data={data} your={your} />}
      >
        <BusinessFields data={data} canWrite={canWrite} writes={writes} eg={eg} audience={audience} />
      </Section>
    </div>
  );
}

function CoreFields({ fields }: { fields: LeadField[] }) {
  return (
    <Section
      title="Always captured"
      description="On every call, with the caller's phone number. These can't be changed or removed."
    >
      <ul className="grid grid-cols-2 gap-x-4 gap-y-3 sm:gap-x-8">
        {fields.map((field) => (
          <li key={field.key} className="flex min-w-0 items-start gap-2">
            <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-faint" />
            <span className="min-w-0">
              <span className="block text-sm font-medium text-ink">{field.label}</span>
              <span className="block text-xs text-ink-muted">
                {lookup(CORE_MEANING, field.key) ?? field.label}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Origin({ data, your }: { data: LeadFields; your: string }) {
  if (data.has_standard_set) {
    return (
      <>
        Started from the standard details for {data.business_type_label.toLowerCase()}{" "}
        businesses. Change them any time.
      </>
    );
  }
  if (data.draft?.status === "done" && !data.draft.reviewed) {
    return <>Drafted once from {your} business details. Keep the ones that fit; no agent has them yet.</>;
  }
  if (data.draft?.status === "done") {
    const when = data.draft.completed_at ? ` on ${formatISTStamp(data.draft.completed_at)}` : "";
    return (
      <>
        Drafted once from {your} business details{when}.{" "}
        {your === "your" ? "They're yours" : "They're the client's"} to change: add, rename,
        reorder or remove any of them. They won&apos;t be drafted again.
      </>
    );
  }
  return <>What {your} business needs to know about each caller, on top of the details above.</>;
}

function BusinessFields({
  data,
  canWrite,
  writes,
  eg,
  audience,
}: {
  data: LeadFields;
  canWrite: boolean;
  writes: LeadDetailsWrites;
  eg: VerticalExamples;
  audience: "client" | "operator";
}) {
  const status = data.draft?.status;
  if (status === "queued" || status === "running") return <Drafting />;

  const agents = data.agents;
  const noFieldsAnywhere = agents.every((agent) => agent.business_fields.length === 0);
  return (
    <div className="space-y-6">
      {data.can_draft && noFieldsAnywhere && (
        <DraftOffer data={data} canWrite={canWrite} draft={writes.draft} audience={audience} />
      )}
      {data.draft?.status === "done" && !data.draft.reviewed && (
        <DraftReview draft={data.draft} canWrite={canWrite} review={writes.review} audience={audience} />
      )}
      {agents.length === 0 ? (
        <p className="text-sm text-ink-muted">
          {audience === "client" ? "You have" : "This client has"} no agents yet. The details
          set here are given to each agent as it is created.
        </p>
      ) : (
        <AgentFields data={data} canWrite={canWrite} writes={writes} eg={eg} audience={audience} />
      )}
    </div>
  );
}

function Drafting() {
  return (
    <div className="space-y-3">
      <p role="status" aria-live="polite" className="text-sm text-ink-muted">
        Drafting from the business details. This usually takes under a minute; the page
        updates on its own.
      </p>
      <Skeleton rows={4} label="Drafting the business details" />
    </div>
  );
}

/** What the client asks Pip; the operator's screen keeps its own button. */
export const DRAFT_REQUEST = "Draft the lead details for my business from its business details.";

function DraftOffer({
  data,
  canWrite,
  draft,
  audience,
}: {
  data: LeadFields;
  canWrite: boolean;
  draft: LeadDetailsWrites["draft"];
  audience: "client" | "operator";
}) {
  const failed = data.draft?.status === "failed";
  return (
    <div className="rounded-md border border-line px-4 py-4">
      <p className="text-sm font-medium text-ink">
        {failed ? "The details could not be drafted last time." : "Nothing here yet."}
      </p>
      <p className="mt-1 max-w-prose text-sm text-ink-muted [text-wrap:pretty]">
        {audience === "client" ? ASSISTANT_NAME : "Calevate"} can draft these once from the
        business details — what {audience === "client" ? "you sell" : "it sells"}, the questions
        callers ask and what your agents already know. You keep the ones that fit before any agent gets
        them, and they are not drafted again. For the best draft, fill in the business profile
        first.
      </p>
      {draft?.error && (
        <div className="mt-3">
          <ProblemNotice error={draft.error} />
        </div>
      )}
      {draft ? (
        <button
          type="button"
          className={`${PRIMARY_BUTTON} mt-3`}
          disabled={!canWrite || draft.isPending}
          onClick={() => draft.mutate()}
        >
          {draft.isPending ? "Starting…" : failed ? "Try again" : "Draft from the business details"}
        </button>
      ) : (
        <AskAssistant
          label={`Let ${ASSISTANT_NAME} draft them`}
          prompt={DRAFT_REQUEST}
          size="md"
          disabled={!canWrite}
          className="mt-3"
        />
      )}
    </div>
  );
}

/**
 * THE DRAFT, KEPT FIELD BY FIELD (D-821). Every field starts ticked; what is kept goes onto
 * every agent that has no details of its own yet and is what a new agent starts with. Once
 * reviewed, it is never offered again. An operator sees it and waits for the owner.
 */
function DraftReview({
  draft,
  canWrite,
  review,
  audience,
}: {
  draft: LeadFieldsDraft;
  canWrite: boolean;
  review: LeadDetailsWrites["review"];
  audience: "client" | "operator";
}) {
  const [kept, setKept] = useState<Set<string>>(() => new Set(draft.fields.map((f) => f.key)));
  const count = kept.size;
  const owner = audience === "client" && review !== undefined;
  return (
    <section aria-labelledby="draft-review-heading" className="space-y-3 rounded-md border border-line px-4 py-4">
      <div>
        <h3 id="draft-review-heading" className="text-sm font-medium text-ink">
          {draft.fields.length === 1 ? "1 drafted detail" : `${draft.fields.length} drafted details`}
        </h3>
        <p className="mt-1 text-sm text-ink-muted">
          {owner
            ? "Untick what you do not want. What you keep goes to every agent without details of its own."
            : "Waiting for the account owner to keep the ones that fit."}
        </p>
      </div>
      <ul className="divide-y divide-line border-y border-line">
        {draft.fields.map((field) => {
          const on = kept.has(field.key);
          return (
            <li key={field.key}>
              <label className={`flex items-start gap-3 py-2.5 ${owner ? "cursor-pointer" : ""} ${on ? "" : "opacity-55"}`}>
                {owner && (
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 shrink-0 accent-[var(--brand-strong)]"
                    checked={on}
                    disabled={!canWrite}
                    onChange={(e) =>
                      setKept((current) => {
                        const next = new Set(current);
                        if (e.target.checked) next.add(field.key);
                        else next.delete(field.key);
                        return next;
                      })
                    }
                  />
                )}
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-ink">{field.label}</span>
                  {field.reason && <span className="block text-xs text-ink-muted">{field.reason}</span>}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      {owner && review && (
        <>
          {review.error && <ProblemNotice error={review.error} />}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={PRIMARY_BUTTON}
              disabled={!canWrite || count === 0 || review.isPending}
              onClick={() => review.mutate([...kept])}
            >
              {count === draft.fields.length
                ? count === 1
                  ? "Add it to my agents"
                  : `Add all ${count} to my agents`
                : `Add ${count} of ${draft.fields.length} to my agents`}
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={!canWrite || review.isPending}
              onClick={() => review.mutate([])}
            >
              Keep none
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function AgentFields({
  data,
  canWrite,
  writes,
  eg,
  audience,
}: {
  data: LeadFields;
  canWrite: boolean;
  writes: LeadDetailsWrites;
  eg: VerticalExamples;
  audience: "client" | "operator";
}) {
  const [selected, setSelected] = useState<string>(data.agents[0]?.id ?? "");
  const agent = data.agents.find((each) => each.id === selected) ?? data.agents[0];
  if (!agent) return null;
  return (
    <div className="space-y-4">
      {data.agents.length > 1 && (
        <div role="group" aria-label="Agent" className="flex flex-wrap gap-2">
          {data.agents.map((each) => (
            <FilterChip
              key={each.id}
              label={each.name}
              active={each.id === agent.id}
              onClick={() => setSelected(each.id)}
            />
          ))}
        </div>
      )}
      {/* Keyed by agent AND version, so a save or a replace re-seeds the draft from what is
          now on file rather than keeping a stale list. */}
      <AgentEditor
        key={`${agent.id}:${agent.version}`}
        agent={agent}
        data={data}
        canWrite={canWrite}
        writes={writes}
        eg={eg}
        many={data.agents.length > 1}
        audience={audience}
      />
    </div>
  );
}

function AgentEditor({
  agent,
  data,
  canWrite,
  writes,
  eg,
  many,
  audience,
}: {
  agent: LeadFieldsAgent;
  data: LeadFields;
  canWrite: boolean;
  writes: LeadDetailsWrites;
  eg: VerticalExamples;
  many: boolean;
  audience: "client" | "operator";
}) {
  const [rows, setRows] = useState<DraftRow[]>(() => agent.business_fields.map(toDraft));
  const [confirming, setConfirming] = useState(false);
  const validation = useFormValidation();
  const saved = useMemo(() => canonical(agent.business_fields), [agent.business_fields]);
  const dirty = canonical(toWireFields(rows)) !== saved;
  // The version the rows were loaded from, sent as `expected_version`. A newer list (a kept
  // suggestion, Pip, the agent's own screen) is adopted while the rows are untouched; with
  // edits in progress the save is refused instead of dropping the newer fields.
  const [base, setBase] = useState(() => ({ version: agent.version, canonical: saved }));
  const adoptCurrent = () => {
    setBase({ version: agent.version, canonical: saved });
    setRows(agent.business_fields.map(toDraft));
  };
  if (agent.version !== base.version && canonical(toWireFields(rows)) === base.canonical) {
    adoptCurrent();
  }
  useUnsavedGuard(dirty);
  const clientError = clientValidationError(rows);
  const { save, replace, useSuggestions } = writes;
  const suggestions = useSuggestions(agent.id);
  const busy = save.isPending || replace.isPending;
  const disabled = !canWrite || busy;

  const fresh = data.has_standard_set ? data.standard_fields : (data.draft?.status === "done" ? data.draft.fields : []);
  const freshLabel = data.has_standard_set
    ? `the standard details for ${data.business_type_label.toLowerCase()} businesses`
    : "the drafted details";

  function patch(uid: string, change: Partial<DraftRow>) {
    setRows((current) => current.map((row) => (row.uid === uid ? { ...row, ...change } : row)));
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
    <form
      noValidate
      className="space-y-4"
      onSubmit={validation.onSubmit(() => {
        if (disabled || !dirty || clientError) return;
        save.mutate(
          { agentId: agent.id, fields: toWireFields(rows), expected_version: base.version },
          {
            onSuccess: (result) =>
              setBase({ version: result.version, canonical: canonical(result.fields) }),
          },
        );
      })}
    >
      {many && (
        <p className="text-xs text-ink-muted">
          Each agent keeps its own list. These are the details {agent.name} writes down.
        </p>
      )}
      <LeadSuggestions api={suggestions} canWrite={canWrite} dirty={dirty} audience={audience} />
      {rows.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No business details yet. Calls still become leads with everything under Always
          captured.
        </p>
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {rows.map((row, index) => (
            <FieldEditorRow
              key={row.uid}
              row={row}
              index={index}
              total={rows.length}
              disabled={disabled}
              eg={eg}
              validation={validation}
              noun="detail"
              showKey={false}
              onChange={(change) => patch(row.uid, change)}
              onDelete={() => setRows((current) => current.filter((r) => r.uid !== row.uid))}
              onMoveUp={() => move(index, -1)}
              onMoveDown={() => move(index, 1)}
            />
          ))}
        </ul>
      )}

      <button
        type="button"
        className={SECONDARY_BUTTON}
        disabled={disabled}
        onClick={() => setRows((current) => [...current, blankRow()])}
      >
        <Plus aria-hidden className="h-4 w-4" />
        Add a detail
      </button>

      {save.error && <ProblemNotice error={save.error} />}
      {save.error instanceof ApiProblem && save.error.code === "extraction_schema_changed_elsewhere" && (
        <button
          type="button"
          className={SECONDARY_BUTTON}
          onClick={() => {
            adoptCurrent();
            save.reset();
          }}
        >
          Load the current list
        </button>
      )}
      {replace.error && !confirming && <ProblemNotice error={replace.error} />}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <button
          type="submit"
          className={PRIMARY_BUTTON}
          disabled={disabled || !dirty || Boolean(clientError)}
        >
          <Save aria-hidden className="h-4 w-4" />
          {save.isPending ? "Saving…" : "Save details"}
        </button>
        <SavedTick at={save.isSuccess ? save.submittedAt : 0} />
        <span className="text-xs text-ink-muted">
          {clientError ?? (dirty ? "You have unsaved changes." : "Changes apply from the next call.")}
        </span>
      </div>

      <p className="max-w-prose text-xs text-ink-muted [text-wrap:pretty]">
        Renaming or removing a detail deletes nothing: older leads and calls keep their
        answers under the old name.
        {fresh.length > 0 && canWrite && (
          <>
            {" "}
            <button type="button" className={TEXT_ACTION} onClick={() => setConfirming(true)} disabled={busy}>
              Start again from {freshLabel}
            </button>
          </>
        )}
      </p>

      {confirming && (
        <ConfirmDialog
          title={`Replace ${agent.name}'s details?`}
          confirmLabel="Replace details"
          pendingLabel="Replacing…"
          pending={replace.isPending}
          error={replace.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() =>
            replace.mutate(
              { agent_ids: [agent.id] },
              { onSuccess: () => setConfirming(false) },
            )
          }
        >
          <p>
            {agent.name} will write down {freshLabel} from the next call:{" "}
            {fresh.map((field) => field.label).join(", ")}.
          </p>
          <p>Answers already captured stay on their leads and calls, under their old names.</p>
        </ConfirmDialog>
      )}
    </form>
  );
}
