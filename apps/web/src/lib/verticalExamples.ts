import type { components } from "@/lib/api/schema";
import type { BusinessTypeOption } from "@/lib/businessTypes";

/**
 * The example text every client-setup form shows.
 *
 * Every placeholder across onboarding once described a dental clinic, so an operator
 * onboarding a property office or a coaching centre read examples that were wrong about the
 * business in front of them. A placeholder is the fastest instruction on a form, and forty
 * fields of clinic vocabulary teach an operator to describe a real-estate office as if it had
 * patients.
 *
 * Two sources, neither of them a list of trades kept here:
 *
 * - The admin console's new-account form, where the business type is all there is, shows
 *   that type's examples as the server sends them (`GET /v1/public/business-types`, from
 *   `calevate_shared/verticals.json`). A type the file gives none shows the neutral set.
 * - A client's own screens show the account's AI-written examples (`withGeneratedCopy`) over
 *   the neutral set.
 *
 * The neutral set (`CUSTOM`) is the fallback everywhere, never a trade's: an unknown or absent
 * type must not silently describe a dental practice, and its examples read as instructions
 * rather than as a business, so a fallback is visibly a fallback.
 */


export interface VerticalExamples {
  /** The business itself — the wizard's first two fields. */
  readonly orgName: string;
  readonly orgSlug: string;
  /** A knowledge note's title — the thing a client types, not a file they send. */
  readonly knowledgeTitle: string;
  /** A gap answer, in this trade's vocabulary. */
  readonly knowledgeAnswer: string;
  /** Why one extracted field matters — the "so we can …" half. */
  readonly extractionReason: string;
  /** What a founder types to have the script drafted for them. */
  readonly scriptBrief: string;
  /** A detail the agent collects on every call: an extracted field's name. */
  readonly extractionLabel: string;
  /** Choices for a pick-one field, comma-separated. */
  readonly extractionOptions: string;
  /** Two end-of-call rules, one per line. */
  readonly endCallRules: string;
  /** What a caller asked for, as typed into the lead search. */
  readonly leadSearch: string;
  /** The booking job's name in an agent's Actions (REDESIGN-2): only a clinic books appointments. */
  readonly bookingJobTitle: string;
  /** The booking job's one line, in this trade's words. */
  readonly bookingJobLine: string;
  /** What an owner types into the teach box: a price, where they serve, a never-promise. */
  readonly teachNote: string;
  /** The script's "your business in one line". */
  readonly businessLine: string;
  /** The script's role for the agent, in the second person. */
  readonly agentRole: string;
  /** What a good call achieves. */
  readonly callGoal: string;
  /** Why an outbound call is being made, as the agent says it. */
  readonly outboundPurpose: string;
  /** How the agent ends a call. */
  readonly callEnding: string;
  /** A name callers say and how to say it, for the script's pronunciation list. */
  readonly pronounceWord: string;
  readonly pronounceSayAs: string;
  /** A change an owner asks Pip for in the script, and a shorter one for a chip. */
  readonly scriptChange: string;
  readonly scriptChangeIdea: string;
  /** A quick fact: a caller's question and its one-line answer, kept as a pair. */
  readonly factQuestion: string;
  readonly factAnswer: string;
  /** What the agent should have done on a call that went wrong. */
  readonly testExpectation: string;
  /** An outbound campaign's name. */
  readonly campaignName: string;
  /** A WhatsApp message's purpose, and its body with a numbered blank for the customer's name. */
  readonly messageTitle: string;
  readonly messageBody: string;
  /** A call outcome's name and what it means. */
  readonly outcomeLabel: string;
  readonly outcomeMeaning: string;
}

/**
 * The examples that arrived with the account's own AI-written copy (D-827 prompt version 2),
 * the same for every trade until that copy lands. They are trade-free on purpose: before
 * this they were one grocery shop's ("Red chilli powder is ₹120 …") on every account, and a
 * neutral sentence reads as an instruction where another trade's reads as a mistake. None of
 * them assumes a sale, a price or a booking: a business that sells nothing reads them too.
 */
const NEUTRAL_UNTIL_GENERATED = {
  teachNote: "We are open Monday to Saturday, 9 to 6. Never promise a time without checking.",
  businessLine: "a family-run business in the city centre",
  agentRole: "You answer the phone for the business. You help callers with what they need and take their details.",
  callGoal: "Answer their question and, if they want to go ahead, take their name and a good time to call back.",
  // Never "you enquired with us": false for anyone on a list (`agents/retired_lines.py`).
  outboundPurpose: "I am calling to see if there is anything we can help you with.",
  callEnding: "Repeat what was agreed, thank them by name and say goodbye.",
  pronounceWord: "Your business name",
  pronounceSayAs: "How to say it out loud",
  scriptChange: "When someone asks for a discount, say the team will call them back about it",
  scriptChangeIdea: "Ask for a good time to call back",
  factQuestion: "Are you open on Sundays?",
  factAnswer: "No, we are open Monday to Saturday, 9 to 6.",
  testExpectation: "Give the answer from what we taught it.",
  campaignName: "Follow-up calls",
  messageTitle: "Request received",
  messageBody: "Thank you, {{1}}. We have your request and will call you back today.",
  outcomeLabel: "Wants to go ahead",
  outcomeMeaning: "The caller wants to take the next step with us.",
} as const satisfies Partial<VerticalExamples>;

/**
 * The neutral set: `custom`'s examples and every fallback. An operator who chose custom told
 * us the business does not fit a template; showing them a clinic would be the original bug
 * with an extra step.
 */
const CUSTOM: VerticalExamples = {
  orgName: "Sri Traders",
  orgSlug: "sri-traders",
  knowledgeTitle: "Common questions",
  knowledgeAnswer: "The answer a caller should have been given.",
  extractionReason: "so we can call back the enquiries that matter most first",
  scriptBrief:
    "What the business does, where it is, what callers usually want, and what the agent should do about it.",
  extractionLabel: "What they need",
  extractionOptions: "New enquiry, Repeat caller, Complaint",
  endCallRules:
    "Never promise anything you have not checked.\nAlways offer a callback if unsure.",
  leadSearch: "a call back on Saturday",
  bookingJobTitle: "Take bookings",
  bookingJobLine: "Your agent can check your Google Calendar and book callers in.",
  ...NEUTRAL_UNTIL_GENERATED,
};

/** A type's examples as the server sends them. */
export type ServedExamples = components["schemas"]["BusinessTypeExamplesOut"];

/** Each served key, in the table's spelling. */
const FROM_SERVED: Readonly<Record<keyof ServedExamples, keyof VerticalExamples>> = {
  org_name: "orgName",
  org_slug: "orgSlug",
  knowledge_title: "knowledgeTitle",
  knowledge_answer: "knowledgeAnswer",
  extraction_reason: "extractionReason",
  script_brief: "scriptBrief",
  extraction_label: "extractionLabel",
  extraction_options: "extractionOptions",
  end_call_rules: "endCallRules",
  lead_search: "leadSearch",
  booking_job_title: "bookingJobTitle",
  booking_job_line: "bookingJobLine",
};

/**
 * The examples for one business type: the server's for that type laid over the neutral set,
 * or the neutral set alone for a type with none, an unknown type, or before the list loads.
 */
export function examplesFor(option: BusinessTypeOption | null | undefined): VerticalExamples {
  const served = option?.examples;
  if (!served) return CUSTOM;
  const merged: { -readonly [K in keyof VerticalExamples]: string } = { ...CUSTOM };
  for (const from of Object.keys(FROM_SERVED) as (keyof ServedExamples)[]) {
    const value = served[from];
    if (typeof value === "string" && value.trim()) merged[FROM_SERVED[from]] = value;
  }
  return merged;
}

/** The account's AI-written placeholders (D-827), as the server sends them. */
export type GeneratedPlaceholders = components["schemas"]["Placeholders"];

/** The business profile's examples a copy written before `profile_wording` still carries
 * (`business_copy.RETIRED_PLACEHOLDERS`): the profile reads its own (`ProfileWording`). */
type RetiredPlaceholder =
  | "branch_label"
  | "service_name"
  | "service_price"
  | "service_note"
  | "ask_on_arrival"
  | "faq_question"
  | "staff_name"
  | "staff_spoken"
  | "staff_role"
  | "staff_why_it_matters"
  | "booking_rules"
  | "contact_name";

/** Each generated key, in the table's spelling. `orgName` and `orgSlug` are not generated:
 * they are shown only while an operator creates an account. */
const FROM_GENERATED: Readonly<
  Record<Exclude<keyof GeneratedPlaceholders, RetiredPlaceholder>, keyof VerticalExamples>
> = {
  knowledge_title: "knowledgeTitle",
  knowledge_answer: "knowledgeAnswer",
  extraction_reason: "extractionReason",
  script_brief: "scriptBrief",
  extraction_label: "extractionLabel",
  extraction_options: "extractionOptions",
  end_call_rules: "endCallRules",
  lead_search: "leadSearch",
  booking_job_title: "bookingJobTitle",
  booking_job_line: "bookingJobLine",
  teach_note: "teachNote",
  business_line: "businessLine",
  agent_role: "agentRole",
  call_goal: "callGoal",
  outbound_purpose: "outboundPurpose",
  call_ending: "callEnding",
  pronounce_word: "pronounceWord",
  pronounce_say_as: "pronounceSayAs",
  script_change: "scriptChange",
  script_change_idea: "scriptChangeIdea",
  fact_question: "factQuestion",
  fact_answer: "factAnswer",
  test_expectation: "testExpectation",
  campaign_name: "campaignName",
  message_title: "messageTitle",
  message_body: "messageBody",
  outcome_label: "outcomeLabel",
  outcome_meaning: "outcomeMeaning",
};

/**
 * The per-trade examples with the account's own generated ones laid over them, key by key.
 *
 * The table stays the fallback for every key the generated set does not fill (none, once a
 * copy lands; all of them before the first one does), so a screen never shows an empty
 * placeholder while the account's copy is on its way.
 */
export function withGeneratedCopy(
  base: VerticalExamples,
  generated: GeneratedPlaceholders | null | undefined,
): VerticalExamples {
  if (!generated) return base;
  const merged: { -readonly [K in keyof VerticalExamples]: string } = { ...base };
  for (const from of Object.keys(FROM_GENERATED) as (keyof typeof FROM_GENERATED)[]) {
    const value = generated[from];
    if (typeof value === "string" && value.trim()) merged[FROM_GENERATED[from]] = value;
  }
  return merged;
}
