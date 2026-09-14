"use client";

/**
 * The languages the PRODUCT sells, once, for both wizard steps that ask about them.
 *
 * Step 1 picks the agent's PRIMARY language (`CreateOrgIn.language`) and step 3 asks
 * which languages the business works in (`IntakeFacts.languages`, which the API stores as
 * `languages_extra` — the OTHERS). Two questions, one set of answers, and a second copy
 * of the labels is where the two screens start disagreeing about what `hi-IN` is called.
 *
 * ⚠ **THE LABELS ARE NO LONGER TYPED HERE, AND THE ARGUMENT AGAINST A SECOND COPY WAS
 * ALREADY IN THIS DOCSTRING.** It made the case and then retyped the names anyway, which
 * is how one product came to have three tables of them — this one, `lib/api/signup.ts`
 * and `lib/agentState.LANGUAGE_NAMES` — agreeing only because nobody had edited one. The
 * copilot's card, which had a fourth, did not agree: it called `en-IN` "Indian English"
 * while every screen it refers to called it "English (India)". `LANGUAGE_NAMES` is now
 * the console's only table of those names (`Record<AgentLanguage, string>` over the
 * GENERATED union), and the server's labels come from `calevate_shared.languages`, so the
 * name a client reads and the name an operator reads are one string.
 *
 * The values are `CreateOrgIn["language"]` — the GENERATED union — so a language the API
 * stops accepting fails this build rather than the operator's first request. Indexing
 * `LANGUAGE_NAMES` by it is deliberate and is the second half of that guard: the org's
 * language union and the agent's language union are the same three tags on the server, and
 * if they ever diverge this line stops compiling instead of rendering an option the other
 * screen cannot show. That the intake endpoint itself takes a bare `list[str]` is not a
 * reason to offer free text.
 *
 * It lives beside the wizard rather than in `lib/api/` because the HINTS are a PRODUCT
 * choice about how to present the offer, not a fact about the wire.
 */

import { LANGUAGE_CHOICES } from "@/lib/agentState";
import type { CreateOrgIn } from "@/lib/api/admin";

export type WizardLanguage = CreateOrgIn["language"];

/** What an operator is told about a language beyond its name. Only Telugu has anything
 *  to say; the empty string is the honest spelling of "nothing to add", and the wizard
 *  renders it as nothing. */
const HINTS: Record<WizardLanguage, string> = {
  "te-IN": "The default, and what the voice stack is tuned for",
  "hi-IN": "",
  "en-IN": "",
};

export const WIZARD_LANGUAGES: { value: WizardLanguage; label: string; hint: string }[] =
  LANGUAGE_CHOICES.map(({ value, label }) => ({ value, label, hint: HINTS[value] }));
