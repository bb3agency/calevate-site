"use client";

/**
 * The languages the PRODUCT sells, once, for both wizard steps that ask about them.
 *
 * Step 1 picks the agent's PRIMARY language (`CreateOrgIn.language`) and step 3 asks
 * which languages the business works in (`IntakeFacts.languages`, which the API stores as
 * `languages_extra` — the OTHERS). Two questions, one set of answers, and a second copy
 * of the labels is where the two screens start disagreeing about what `hi-IN` is called.
 *
 * The values are `CreateOrgIn["language"]` — the GENERATED union — so a language the API
 * stops accepting fails this build rather than the operator's first request. That the
 * intake endpoint itself takes a bare `list[str]` is not a reason to offer free text: the
 * catalog behind the voice stack carries exactly these three (`apps/api/agents/voices.py`
 * argues why — the docs give a COUNT of Bulbul v3's languages and never a list, so
 * offering more would be enumerating something we would be inventing).
 *
 * It lives beside the wizard rather than in `lib/api/` because it is a PRODUCT choice
 * about what to offer, not a fact about the wire.
 */

import type { CreateOrgIn } from "@/lib/api/admin";

export type WizardLanguage = CreateOrgIn["language"];

export const WIZARD_LANGUAGES: { value: WizardLanguage; label: string; hint: string }[] = [
  { value: "te-IN", label: "Telugu", hint: "The default, and what the voice stack is tuned for" },
  { value: "hi-IN", label: "Hindi", hint: "" },
  { value: "en-IN", label: "English (India)", hint: "" },
];
