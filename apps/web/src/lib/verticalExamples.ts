import type { components } from "@/lib/api/schema";
import { lookup } from "@/lib/lookup";

/**
 * The example text every client-setup form shows, PER VERTICAL.
 *
 * ## The defect this replaces
 *
 * Every placeholder across onboarding described a dental clinic: "Consultation", "₹500",
 * "Dr Lakshmi Prasad", "Dentist", "Do you take walk-ins?", "Slots every 20 minutes …
 * never promise a specific doctor without checking", and a helper sentence about "a
 * mispronounced doctor's name". Five verticals ship (`admin/new/page.tsx::VERTICALS`) and
 * four of them are not clinics, so an operator onboarding a property office or a coaching
 * centre read examples that were wrong about the business in front of them.
 *
 * They were only ever `placeholder=` — nothing was pre-filled and nothing could be
 * submitted unchanged, which is worth stating because that is the sharper version of the
 * bug and it is not the one that was here. What WAS here is worse than cosmetic: a
 * placeholder is the fastest instruction on a form, and forty fields of clinic vocabulary
 * teach an operator to describe a real-estate office as if it had patients.
 *
 * ## Why a table rather than a prop per field
 *
 * The alternative is threading twenty strings through two components. The vertical is ONE
 * fact and the examples are a function of it, so it is one lookup at the top of each form
 * and every field reads from the same row. Adding a vertical means adding a row here and
 * the type stops the build until every field in it is filled — which is the point: a
 * sixth vertical cannot ship with a clinic's examples by omission.
 */

/** The API's own enum, so a template it stops accepting fails the build. */
export type Vertical = components["schemas"]["CreateOrgIn"]["vertical_template"];

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
 * neutral sentence reads as an instruction where another trade's reads as a mistake.
 */
const NEUTRAL_UNTIL_GENERATED = {
  teachNote: "Our main service is ₹500. We are open Monday to Saturday, 9 to 6. Never promise a time without checking.",
  businessLine: "a family-run business in the city centre",
  agentRole: "You answer the phone for the business. You help callers with what they need and take their details.",
  callGoal: "Answer their question and, if they want to go ahead, take their name and a good time to call back.",
  outboundPurpose: "You enquired with us last week, so I am calling to help you with it.",
  callEnding: "Repeat what was agreed, thank them by name and say goodbye.",
  pronounceWord: "Your business name",
  pronounceSayAs: "How to say it out loud",
  scriptChange: "When someone asks for a discount, say the team will call them back about it",
  scriptChangeIdea: "Ask for a good time to call back",
  factQuestion: "Are you open on Sundays?",
  factAnswer: "No, we are open Monday to Saturday, 9 to 6.",
  testExpectation: "Give the price from what we taught it.",
  campaignName: "Festival offer reminder",
  messageTitle: "Request received",
  messageBody: "Thank you, {{1}}. We have your request and will call you back today.",
  outcomeLabel: "Wants to go ahead",
  outcomeMeaning: "The caller wants to buy or book what we offer.",
} as const satisfies Partial<VerticalExamples>;

const CLINIC: VerticalExamples = {
  orgName: "Sunrise Clinic",
  orgSlug: "sunrise-clinic",
  knowledgeTitle: "Clinic hours",
  knowledgeAnswer:
    "Our consultation fee is ₹500, adjusted against any treatment on the same day.",
  extractionReason: "so we can route urgent cases to a doctor first",
  scriptBrief:
    "We are a dental clinic in Hyderabad. Callers usually want to book a check-up or ask about teeth cleaning prices. Book appointments and take a callback number.",
  extractionLabel: "Reason for visit",
  extractionOptions: "New, Follow-up, Emergency",
  endCallRules: "Never promise a same-day appointment.\nAlways offer a callback if unsure.",
  leadSearch: "teeth cleaning on Saturday",
  bookingJobTitle: "Book appointments",
  bookingJobLine: "Your agent can check your Google Calendar and book callers in.",
  ...NEUTRAL_UNTIL_GENERATED,
};

const REAL_ESTATE: VerticalExamples = {
  orgName: "Skyline Properties",
  orgSlug: "skyline-properties",
  knowledgeTitle: "Site visit timings",
  knowledgeAnswer:
    "The 2 BHK units in Gachibowli start at ₹85 lakh, and the price on the phone is indicative until a site visit.",
  extractionReason: "so we can call back the buyers whose budget matches an available unit",
  scriptBrief:
    "We are a property office in Hyderabad. Callers usually ask about available flats, price and location. Book site visits and take a budget and a callback number.",
  extractionLabel: "Budget",
  extractionOptions: "Ready to move, Under construction, Plot",
  endCallRules: "Never quote a final price on the phone.\nAlways offer a site visit if unsure.",
  leadSearch: "3BHK in Gachibowli",
  bookingJobTitle: "Book site visits",
  bookingJobLine: "Your agent can check your Google Calendar and book site visits for callers.",
  ...NEUTRAL_UNTIL_GENERATED,
};

const INSURANCE: VerticalExamples = {
  orgName: "Sujatha Insurance Services",
  orgSlug: "sujatha-insurance",
  knowledgeTitle: "Renewal documents",
  knowledgeAnswer:
    "A term life renewal needs the policy number and a current address proof; the premium is confirmed once we pull up the policy.",
  extractionReason: "so we can call back the policies that are closest to lapsing first",
  scriptBrief:
    "We are an insurance agency in Vijayawada. Callers usually ask about renewals, premiums and claims. Take the policy number and book an advisor callback.",
  extractionLabel: "Policy type",
  extractionOptions: "New policy, Renewal, Claim",
  endCallRules:
    "Never confirm a premium without the policy number.\nAlways offer an advisor callback if unsure.",
  leadSearch: "renewal due this month",
  bookingJobTitle: "Book meetings",
  bookingJobLine: "Your agent can check your Google Calendar and book callers a meeting with you.",
  ...NEUTRAL_UNTIL_GENERATED,
};

const EDUCATION: VerticalExamples = {
  orgName: "Vidya Coaching Centre",
  orgSlug: "vidya-coaching",
  knowledgeTitle: "Batch timings",
  knowledgeAnswer:
    "The NEET crash course is ₹45,000 for the weekend batch, and the fee can be paid in two instalments.",
  extractionReason: "so we can call back the parents whose child is closest to an exam date",
  scriptBrief:
    "We are a coaching centre in Guntur. Callers usually ask about courses, batch timings and fees. Book counselling sessions and take the student's class and a callback number.",
  extractionLabel: "Course",
  extractionOptions: "Enquiry, Demo booked, Admitted",
  endCallRules: "Never promise a seat in a batch that is full.\nAlways offer a callback if unsure.",
  leadSearch: "NEET weekend batch",
  bookingJobTitle: "Book counselling sessions",
  bookingJobLine: "Your agent can check your Google Calendar and book counselling sessions for callers.",
  ...NEUTRAL_UNTIL_GENERATED,
};

const RETAIL: VerticalExamples = {
  orgName: "Green Basket Organics",
  orgSlug: "green-basket-organics",
  knowledgeTitle: "This week's price list",
  knowledgeAnswer: "Free home delivery on orders above ₹500 within 5 km.",
  extractionReason: "so we can pack the order before the customer arrives",
  scriptBrief:
    "We sell organic vegetables, fruits and groceries in Hyderabad. Callers ask what is in stock and the price, and place orders for pickup or delivery. Take the order and a call-back time.",
  extractionLabel: "Product",
  extractionOptions: "Pickup, Home delivery",
  endCallRules:
    "Never promise stock or a delivery time without checking.\nAlways offer a call-back if unsure.",
  leadSearch: "green chilli for Saturday",
  bookingJobTitle: "Take orders",
  bookingJobLine: "Your agent can check your Google Calendar and book pickup times for callers.",
  ...NEUTRAL_UNTIL_GENERATED,
};

const LOCAL_SERVICES: VerticalExamples = {
  orgName: "Glow Studio",
  orgSlug: "glow-studio",
  knowledgeTitle: "Service menu",
  knowledgeAnswer: "Bridal packages start at ₹8,000, including a trial session.",
  extractionReason: "so we can send the right stylist",
  scriptBrief:
    "We are a salon in Madhapur. Callers ask about prices and book haircuts, facials and bridal makeup, at the studio or at home. Book a slot and take a call-back time.",
  extractionLabel: "Service wanted",
  extractionOptions: "At the shop, At home",
  endCallRules: "Never promise a stylist or a slot without checking.\nAlways offer a call-back if unsure.",
  leadSearch: "bridal makeup in December",
  bookingJobTitle: "Book slots",
  bookingJobLine: "Your agent can check your Google Calendar and book callers into a free slot.",
  ...NEUTRAL_UNTIL_GENERATED,
};

const AUTOMOBILE: VerticalExamples = {
  orgName: "Sai Ram Motors",
  orgSlug: "sai-ram-motors",
  knowledgeTitle: "Service price list",
  knowledgeAnswer: "Pickup and drop is free within 5 km for a general service.",
  extractionReason: "so the workshop can plan the day's jobs",
  scriptBrief:
    "We are a two-wheeler and car service centre in Kukatpally. Callers book services, ask about repair costs and spare parts, and ask for pickup. Book a service slot and take the vehicle details.",
  extractionLabel: "Vehicle",
  extractionOptions: "Two-wheeler, Car, Auto or commercial",
  endCallRules:
    "Never quote a repair cost before inspection.\nAlways offer a call-back if unsure.",
  leadSearch: "Activa service on Monday",
  bookingJobTitle: "Book service slots",
  bookingJobLine: "Your agent can check your Google Calendar and book vehicles in.",
  ...NEUTRAL_UNTIL_GENERATED,
};

/**
 * `custom` is the "build the fields by hand" template, so its examples are deliberately
 * TRADE-NEUTRAL rather than borrowed from one of the four above. An operator who chose
 * custom told us the business does not fit a template; showing them a clinic would be the
 * original bug with an extra step.
 */
const CUSTOM: VerticalExamples = {
  orgName: "Sri Traders",
  orgSlug: "sri-traders",
  knowledgeTitle: "Your price list",
  knowledgeAnswer: "The answer a caller should have been given.",
  extractionReason: "so we can call back the enquiries that matter most first",
  scriptBrief:
    "What the business does, where it is, what callers usually want, and what the agent should do about it.",
  extractionLabel: "What they need",
  extractionOptions: "New enquiry, Repeat customer, Complaint",
  endCallRules:
    "Never promise a delivery date or a price without checking.\nAlways offer a callback if unsure.",
  leadSearch: "a booking for Saturday",
  bookingJobTitle: "Take bookings",
  bookingJobLine: "Your agent can check your Google Calendar and book callers in.",
  ...NEUTRAL_UNTIL_GENERATED,
};

const BY_VERTICAL: Readonly<Record<NonNullable<Vertical>, VerticalExamples>> = {
  retail: RETAIL,
  local_services: LOCAL_SERVICES,
  automobile: AUTOMOBILE,
  clinic: CLINIC,
  real_estate: REAL_ESTATE,
  insurance: INSURANCE,
  education: EDUCATION,
  custom: CUSTOM,
};

/**
 * The examples for one vertical, falling back to the trade-neutral set.
 *
 * The fallback is `custom` and NOT `clinic`, which is the whole point of this module: an
 * unknown or absent vertical must not silently describe a dental practice. `custom`'s
 * examples read as instructions ("The main thing you sell") rather than as a business, so
 * a fallback is visibly a fallback instead of quietly being wrong.
 */
export function examplesFor(vertical: string | null | undefined): VerticalExamples {
  return lookupExamples(vertical);
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

function lookupExamples(vertical: string | null | undefined): VerticalExamples {
  // `lookup`, not `key in table` — the house rule, and it is right about this one: `in`
  // walks the prototype chain, so a wire value of `constructor` would report as present
  // and hand this form the `Object` function to read placeholders off. The vertical
  // arrives from an API response, which is exactly the untrusted-key case.
  return lookup(BY_VERTICAL, vertical) ?? CUSTOM;
}
