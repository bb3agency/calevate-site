"use client";

/**
 * HOW A CALL CAN END FOR THIS BUSINESS — each agent's own call outcomes (D-836).
 *
 * Beside the outcomes every business shares (Missed, Hung up early, Call back booked,
 * Transferred, Needs you), which the platform decides from what happened, each agent has up
 * to eight of its own: a short name, what it means, and how far a call like that moves the
 * lead. The AI drafts them once from the business details and the agent's job; the owner
 * edits them here. A call keeps the name it was given, so an edit never rewrites a past call.
 */

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, PenLine, Plus, Save, Trash2 } from "lucide-react";
import type { UseMutationResult } from "@tanstack/react-query";

import { Section } from "@/components/console/section";
import { SavedTick } from "@/components/console/savedTick";
import { useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  FIELD_LABEL,
  FilterChip,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import type {
  CallOutcomeIn,
  CallOutcomes,
  CallOutcomesAgent,
  LeadMove,
} from "@/lib/api/callOutcomes";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { examplesFor, type VerticalExamples } from "@/lib/verticalExamples";

type OutcomeExamples = Pick<VerticalExamples, "outcomeLabel" | "outcomeMeaning">;

/** How far a call moves the lead, in the owner's words. Never Won or Lost: those are a person's. */
export const LEAD_MOVE_WORDS: Readonly<Record<LeadMove, string>> = {
  contacted: "Contacted",
  interested: "Interested",
  hot: "Hot",
};

/** One row being edited. `key` is the stored key, or null for a new outcome. */
export interface OutcomeRow {
  uid: string;
  key: string | null;
  label: string;
  meaning: string;
  lead_status: LeadMove;
}

let nextUid = 0;
const uid = () => `outcome-${(nextUid += 1)}`;

export function toRows(agent: Pick<CallOutcomesAgent, "outcomes">): OutcomeRow[] {
  return agent.outcomes.map((o) => ({ uid: uid(), key: o.key, label: o.label, meaning: o.meaning, lead_status: o.lead_status }));
}

export function toWire(rows: readonly OutcomeRow[]): CallOutcomeIn[] {
  return rows.map((row) => ({
    key: row.key,
    label: row.label.trim(),
    meaning: row.meaning.trim(),
    lead_status: row.lead_status,
  }));
}

/** Why the list cannot be saved yet, said about the list; null when it can. */
export function outcomesProblem(rows: readonly OutcomeRow[], max: number): string | null {
  if (rows.length > max) return `An agent can have at most ${max} outcomes.`;
  const names = rows.map((row) => row.label.trim().toLowerCase());
  if (names.some((name) => name === "")) return "Give every outcome a name.";
  if (new Set(names).size !== names.length) return "Two outcomes have the same name.";
  return null;
}

/** Where the agent's list came from, in one sentence. */
export function originLine(agent: Pick<CallOutcomesAgent, "starting" | "draft">): string {
  if (agent.draft === "queued" || agent.draft === "running") {
    return "Outcomes for this agent are being written from your business details. Until then calls are read with the general ones below.";
  }
  if (agent.starting && agent.draft === "skipped") {
    return "These are general outcomes: ones for your business were not written because AI help was paused or this month's allowance was used up. Edit them to fit.";
  }
  if (agent.starting && agent.draft === "failed") {
    return "These are general outcomes: ones for your business could not be written. Ask again, or edit them to fit.";
  }
  if (agent.starting) {
    return "These are general outcomes. Ones for your business are written when the agent is published, or after its next call.";
  }
  return "Written for your business. Edit them freely; changes apply from the next call.";
}

/** The mutation behind "Write them for me". */
export type DraftOutcomes = UseMutationResult<CallOutcomesAgent, Error, { agentId: string }>;

/**
 * "Write them for me" is offered while the agent still reads the general outcomes and its own
 * were never written: the draft never ran, could not be written, or was skipped. The server
 * refuses it otherwise, so the screen does not offer what would be refused.
 */
export function canAskForDraft(agent: Pick<CallOutcomesAgent, "starting" | "draft">): boolean {
  return agent.starting && (agent.draft === null || agent.draft === "failed" || agent.draft === "skipped");
}

export function CallOutcomesView({
  data,
  canWrite,
  save,
  draft,
  examples = examplesFor(null),
}: {
  data: CallOutcomes;
  canWrite: boolean;
  save: UseMutationResult<CallOutcomesAgent, Error, { agentId: string; outcomes: CallOutcomeIn[] }>;
  draft: DraftOutcomes;
  /** The account's own examples (`useVerticalExamples`, D-827); trade-neutral without them. */
  examples?: OutcomeExamples;
}) {
  const [selected, setSelected] = useState<string>(data.agents[0]?.id ?? "");
  const agent = data.agents.find((each) => each.id === selected) ?? data.agents[0];
  return (
    <Section
      title="How calls end"
      description="Besides Missed, Hung up early, Call back booked, Transferred and Needs you, which are decided from what happened on the call, each agent sorts its calls into outcomes of your business. Each one moves the lead up to the stage you choose; it never marks a lead won or lost."
    >
      {!agent ? (
        <p className="text-sm text-ink-muted">No agents yet. Outcomes appear here once you create one.</p>
      ) : (
        <div className="space-y-4">
          {data.agents.length > 1 && (
            <div role="group" aria-label="Agent" className="flex flex-wrap gap-2">
              {data.agents.map((each) => (
                <FilterChip key={each.id} label={each.name} active={each.id === agent.id} onClick={() => setSelected(each.id)} />
              ))}
            </div>
          )}
          <OutcomesEditor
            key={`${agent.id}:${agent.outcomes.map((o) => `${o.key}=${o.label}=${o.meaning}=${o.lead_status}`).join("|")}`}
            agent={agent}
            max={data.max_outcomes}
            canWrite={canWrite}
            save={save}
            draft={draft}
            examples={examples}
          />
        </div>
      )}
    </Section>
  );
}

function OutcomesEditor({
  agent,
  max,
  canWrite,
  save,
  draft,
  examples,
}: {
  agent: CallOutcomesAgent;
  max: number;
  canWrite: boolean;
  save: UseMutationResult<CallOutcomesAgent, Error, { agentId: string; outcomes: CallOutcomeIn[] }>;
  draft: DraftOutcomes;
  examples: OutcomeExamples;
}) {
  const [rows, setRows] = useState<OutcomeRow[]>(() => toRows(agent));
  const validation = useFormValidation();
  const saved = useMemo(() => JSON.stringify(toWire(toRows(agent))), [agent]);
  const dirty = JSON.stringify(toWire(rows)) !== saved;
  useUnsavedGuard(dirty);
  const problem = outcomesProblem(rows, max);
  const disabled = !canWrite || save.isPending;

  function patch(id: string, change: Partial<OutcomeRow>) {
    setRows((current) => current.map((row) => (row.uid === id ? { ...row, ...change } : row)));
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
        if (disabled || !dirty || problem) return;
        save.mutate({ agentId: agent.id, outcomes: toWire(rows) });
      })}
    >
      <p className="max-w-prose text-xs text-ink-muted [text-wrap:pretty]">{originLine(agent)}</p>
      {canWrite && canAskForDraft(agent) && (
        <div className="space-y-2">
          <button
            type="button"
            className={SECONDARY_BUTTON}
            disabled={draft.isPending || dirty}
            onClick={() => draft.mutate({ agentId: agent.id })}
          >
            <PenLine aria-hidden className="h-4 w-4" />
            {draft.isPending ? "Asking…" : "Write them for me"}
          </button>
          {dirty && <p className="text-xs text-ink-muted">Save or undo your changes first.</p>}
          {draft.error && <ProblemNotice error={draft.error} />}
        </div>
      )}
      {rows.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No outcomes of your own. Calls are still sorted by what happened on them.
        </p>
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {rows.map((row, index) => {
            const named = row.label.trim() || "this outcome";
            return (
              <li key={row.uid} className="py-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-ink-muted">Outcome {index + 1}</span>
                  <div className="flex shrink-0 items-center gap-1">
                    <button type="button" onClick={() => move(index, -1)} disabled={disabled || index === 0} aria-label={`Move ${named} up`} className={SECONDARY_BUTTON_SM}>
                      <ChevronUp aria-hidden className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={() => move(index, 1)} disabled={disabled || index === rows.length - 1} aria-label={`Move ${named} down`} className={SECONDARY_BUTTON_SM}>
                      <ChevronDown aria-hidden className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={() => setRows((current) => current.filter((r) => r.uid !== row.uid))} disabled={disabled} aria-label={`Delete ${named}`} className={SECONDARY_BUTTON_SM}>
                      <Trash2 aria-hidden className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                <div className="mt-2 grid gap-3 sm:grid-cols-[minmax(0,1fr)_11rem]">
                  <div>
                    <label className="block">
                      <span className={FIELD_LABEL}>Outcome name</span>
                      <input
                        {...validation.field(`label-${row.uid}`, "Give this outcome a name.")}
                        required
                        maxLength={40}
                        value={row.label}
                        disabled={disabled}
                        onChange={(event) => patch(row.uid, { label: event.target.value })}
                        placeholder={`e.g. ${examples.outcomeLabel}`}
                        className={FIELD}
                      />
                    </label>
                    {validation.error(`label-${row.uid}`)}
                  </div>
                  <label className="block">
                    <span className={FIELD_LABEL}>Moves the lead to</span>
                    <select
                      value={row.lead_status}
                      disabled={disabled}
                      onChange={(event) => patch(row.uid, { lead_status: event.target.value as LeadMove })}
                      className={FIELD}
                    >
                      {(Object.keys(LEAD_MOVE_WORDS) as LeadMove[]).map((value) => (
                        <option key={value} value={value}>
                          {LEAD_MOVE_WORDS[value]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label className="mt-3 block">
                  <span className={FIELD_LABEL}>What it means</span>
                  <input
                    maxLength={200}
                    value={row.meaning}
                    disabled={disabled}
                    onChange={(event) => patch(row.uid, { meaning: event.target.value })}
                    placeholder={`e.g. ${examples.outcomeMeaning}`}
                    className={FIELD}
                  />
                </label>
              </li>
            );
          })}
        </ul>
      )}

      <button
        type="button"
        className={SECONDARY_BUTTON}
        disabled={disabled || rows.length >= max}
        onClick={() =>
          setRows((current) => [...current, { uid: uid(), key: null, label: "", meaning: "", lead_status: "contacted" }])
        }
      >
        <Plus aria-hidden className="h-4 w-4" />
        {rows.length >= max ? `At most ${max} outcomes` : "Add an outcome"}
      </button>

      {save.error && <ProblemNotice error={save.error} />}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <button type="submit" className={PRIMARY_BUTTON} disabled={disabled || !dirty || Boolean(problem)}>
          <Save aria-hidden className="h-4 w-4" />
          {save.isPending ? "Saving…" : "Save outcomes"}
        </button>
        <SavedTick at={save.isSuccess ? save.submittedAt : 0} />
        <span className="text-xs text-ink-muted">
          {problem ?? (dirty ? "You have unsaved changes." : "Calls already sorted keep their outcome.")}
        </span>
      </div>
    </form>
  );
}
