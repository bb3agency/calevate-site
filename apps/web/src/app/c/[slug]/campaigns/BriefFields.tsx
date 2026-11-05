"use client";

/**
 * WHAT THE CAMPAIGN IS FOR: why it calls and what a good call ends with.
 *
 * Both ride every call as the call's reason, and every answered call is judged against the
 * goal (`apps/api/campaigns/brief.py`). The limits are the server's and are set by the call:
 * the two together must fit the one value the voice platform carries per call.
 *
 * The goal can be picked from the agent's own outcomes that move a lead up (interested or
 * hot). Those are drafted for this business from its details and the agent's job, so the
 * suggestions fit the trade without this screen naming any.
 */

import { useId } from "react";

import { FIELD, FilterChip } from "@/components/ui";
import { useCallOutcomes } from "@/lib/api/callOutcomes";
import { useClientRealm } from "@/lib/api/session";

import { RoomCounter, spokenLength } from "../agents/panels/openingLineFix";

import type { CampaignFormState } from "./campaignForm";

export const PURPOSE_MAX = 90;
export const GOAL_MAX = 50;
const LINE_MIN = 3;
const MAX_SUGGESTIONS = 4;
/** What the server refuses in a spoken line: markdown marks, bullets and braces. */
const FORMATTING = /[*#`_~|[\]<>{}]|^\s*(?:[-•]|\d+[.)])\s/;

function lineProblem(value: string, what: string, max: number): string | null {
  const length = spokenLength(value);
  if (length === 0) return `Say ${what}.`;
  if (length < LINE_MIN) return `Write a few more words for ${what}.`;
  if (length > max) return `Keep ${what} to ${max} characters.`;
  if (FORMATTING.test(value)) return `Write ${what} as plain words, without symbols.`;
  return null;
}

/** The first thing wrong with the two lines, in the order they are asked; null when both read. */
export function briefProblem(form: Pick<CampaignFormState, "purpose" | "goal">): string | null {
  return (
    lineProblem(form.purpose, "why you are calling", PURPOSE_MAX) ??
    lineProblem(form.goal, "the goal", GOAL_MAX)
  );
}

/** A line as the API takes it: trimmed, and null when blank. */
export function briefValue(value: string): string | null {
  const line = value.trim().replace(/\s+/g, " ");
  return line === "" ? null : line;
}

/** The agent's outcomes that move a lead up, as short goal suggestions. */
function useGoalSuggestions(agentId: string): string[] {
  const { session } = useClientRealm();
  const outcomes = useCallOutcomes(session);
  const agent = outcomes.data?.agents.find((a) => a.id === agentId);
  return (agent?.outcomes ?? [])
    .filter((o) => o.lead_status !== "contacted" && spokenLength(o.label) <= GOAL_MAX)
    .map((o) => o.label)
    .slice(0, MAX_SUGGESTIONS);
}

/**
 * The room left shows once there is a line to count: under an empty box "90 characters
 * left" reads as an instruction to fill ninety characters.
 */
function Room({ id, text, room }: { id: string; text: string; room: number }) {
  return text.trim() === "" ? null : <RoomCounter id={id} text={text} room={room} />;
}

export function BriefFields({ form, agentId }: { form: CampaignFormState; agentId: string }) {
  const purposeId = useId();
  const goalId = useId();
  const suggestions = useGoalSuggestions(agentId);
  return (
    <div className="space-y-6">
      <div>
        <label htmlFor={purposeId} className="block text-body font-medium text-ink">
          Why are you calling them?
        </label>
        <span id={`${purposeId}-hint`} className="mt-0.5 block text-meta text-ink-muted">
          The agent says this to each person. Use your own words.
        </span>
        <input
          id={purposeId}
          value={form.purpose}
          onChange={(e) => form.setPurpose(e.target.value)}
          maxLength={PURPOSE_MAX + 20}
          aria-describedby={`${purposeId}-hint ${purposeId}-room`}
          className={`${FIELD} mt-2`}
        />
        <Room id={`${purposeId}-room`} text={form.purpose} room={PURPOSE_MAX} />
      </div>

      <div>
        <label htmlFor={goalId} className="block text-body font-medium text-ink">
          What should a good call end with?
        </label>
        <span id={`${goalId}-hint`} className="mt-0.5 block text-meta text-ink-muted">
          The agent aims for this. We count the calls that do.
        </span>
        <input
          id={goalId}
          value={form.goal}
          onChange={(e) => form.setGoal(e.target.value)}
          maxLength={GOAL_MAX + 20}
          aria-describedby={`${goalId}-hint ${goalId}-room`}
          className={`${FIELD} mt-2`}
        />
        <Room id={`${goalId}-room`} text={form.goal} room={GOAL_MAX} />
        {/* Under the box, not above it: picked, a suggestion fills the box, so the box is
            the answer and these are shortcuts to it. */}
        {suggestions.length > 0 && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <span aria-hidden className="text-meta text-ink-muted">
              Or pick one:
            </span>
            <div role="group" aria-label="Goal suggestions" className="flex flex-wrap gap-2">
              {suggestions.map((label) => (
                <FilterChip
                  key={label}
                  label={label}
                  active={form.goal.trim() === label}
                  onClick={() => form.setGoal(label)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
