"use client";

import { useBusinessCopy, type StepSuggestion } from "@/lib/api/businessCopy";
import { useMe } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { examplesFor, withGeneratedCopy, type VerticalExamples } from "@/lib/verticalExamples";

/**
 * This tenant's example text, for a screen inside `/c/<slug>`.
 *
 * The account's own AI-written examples (D-827, `GET /v1/business-copy`) are laid over the
 * per-trade table key by key; until the first copy lands, and for any key it leaves empty,
 * the table answers. While either read is in flight `examplesFor(undefined)` returns the
 * trade-neutral set, which reads as an instruction rather than as a different business —
 * so the placeholder never flickers from one trade's example to another's.
 *
 * `vertical` is for a screen that already holds the account's business type from its own
 * read (the business profile editor); it wins over `/v1/me`'s.
 */
export function useVerticalExamples(vertical?: string | null): VerticalExamples {
  const session = useClientSession();
  const me = useMe(session);
  const copy = useBusinessCopy(session);
  const base = examplesFor(vertical === undefined ? me.data?.organization?.vertical_template : vertical);
  return withGeneratedCopy(base, copy.data?.placeholders);
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
