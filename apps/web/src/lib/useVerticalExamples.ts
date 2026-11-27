"use client";

import { useBusinessCopy, type StepSuggestion } from "@/lib/api/businessCopy";
import { useClientSession } from "@/lib/api/session";
import { examplesFor, withGeneratedCopy, type VerticalExamples } from "@/lib/verticalExamples";

/**
 * This tenant's example text, for a screen inside `/c/<slug>`.
 *
 * The account's own AI-written examples (D-827, `GET /v1/business-copy`) laid over the
 * trade-neutral set key by key. Never another trade's row: a business filed under a type it
 * only resembles (an app filed as a shop) read that type's examples until its copy landed,
 * and for ever if it never did (audit of 5 Nov 2026, G2-1). The neutral set reads as an
 * instruction rather than as a different business, so it is right before the copy lands and
 * for any key the copy leaves empty. The per-trade rows serve only the operator's
 * new-account form, where the type is all there is.
 *
 * The business profile's own fields do not read this: they have their own wording, written
 * for the business (`BusinessProfile.wording`).
 */
export function useVerticalExamples(): VerticalExamples {
  const copy = useBusinessCopy(useClientSession());
  return withGeneratedCopy(examplesFor(undefined), copy.data?.placeholders);
}

/** A sentence the owner can tap into the first-run brief. */
export interface BriefExample {
  readonly id: string;
  readonly label: string;
  readonly text: string;
}

/** Which generated sentences read as something an owner would write about their business,
 *  in the order offered. Left out: `outbound_purpose` and `agent_role`, which are written as
 *  the agent speaking or being spoken to, and `business_line`, a fragment. */
const BRIEF_EXAMPLE_KEYS = [
  ["script_brief", "A brief written for you"],
  ["call_goal", "What a good call does"],
  ["teach_note", "Something callers ask"],
  ["call_ending", "How a call ends"],
] as const;

/**
 * The first card's examples: ONLY the account's own AI-written copy (D-827), never the
 * trade-neutral set. A neutral sentence is right as a placeholder, but tapped into the box
 * it is saved as the owner's own fact ("open Monday to Saturday, 9 to 6") and the agent
 * would say it on calls. Empty until the copy lands.
 */
export function useBriefExamples(): readonly BriefExample[] {
  const placeholders = useBusinessCopy(useClientSession()).data?.placeholders;
  if (!placeholders) return [];
  return BRIEF_EXAMPLE_KEYS.flatMap(([key, label]) => {
    const text = placeholders[key]?.trim();
    return text ? [{ id: key, label, text }] : [];
  });
}

/** The account's generated suggestions beyond the placeholders: empty until they land. */
export interface BusinessSuggestions {
  readonly steps: readonly StepSuggestion[];
  readonly callerDetails: readonly string[];
  readonly exampleQuestions: readonly string[];
  /** The language the steps' example lines are in (BCP-47), or null before any copy. */
  readonly language: string | null;
}

const NONE: BusinessSuggestions = { steps: [], callerDetails: [], exampleQuestions: [], language: null };

export function useBusinessSuggestions(): BusinessSuggestions {
  const copy = useBusinessCopy(useClientSession());
  if (!copy.data) return NONE;
  return {
    steps: copy.data.steps,
    callerDetails: copy.data.caller_details,
    exampleQuestions: copy.data.example_questions,
    language: copy.data.language ?? null,
  };
}

/** The same spoken language, whatever the region: `te-IN` and `te` are both Telugu. */
export function sameLanguage(a: string | null | undefined, b: string | null | undefined): boolean {
  const base = (code: string | null | undefined) => (code ?? "").toLowerCase().split(/[-_]/)[0];
  return Boolean(base(a)) && base(a) === base(b);
}
