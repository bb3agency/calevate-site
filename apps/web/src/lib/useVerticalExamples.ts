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
