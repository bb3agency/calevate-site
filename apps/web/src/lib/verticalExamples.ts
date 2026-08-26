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
  /** Addresses and branches. */
  readonly branchLabel: string;
  /** Services and prices: what is sold, what it costs, the caveat beside it. */
  readonly serviceName: string;
  readonly servicePrice: string;
  readonly serviceNote: string;
  /** The phrase for "we will not quote a price on the phone" in this trade. */
  readonly askOnArrival: string;
  /** A question the price list does not answer. */
  readonly faqQuestion: string;
  /** Staff: a name worth spelling phonetically, and what that person does. */
  readonly staffName: string;
  readonly staffSpoken: string;
  readonly staffRole: string;
  /** What a mispronounced name costs YOU, in this trade's words. */
  readonly staffWhyItMatters: string;
  /** Booking rules, as free prose. */
  readonly bookingRules: string;
  /** Who a caller is put through to. */
  readonly contactName: string;
  /** A knowledge-base document title. */
  readonly knowledgeTitle: string;
  /** A gap answer, in this trade's vocabulary. */
  readonly knowledgeAnswer: string;
  /** Why one extracted field matters — the "so we can …" half. */
  readonly extractionReason: string;
  /** What a founder types to have the script drafted for them. */
  readonly scriptBrief: string;
}

const CLINIC: VerticalExamples = {
  orgName: "Sunrise Clinic",
  orgSlug: "sunrise-clinic",
  branchLabel: "Main branch",
  serviceName: "Consultation",
  servicePrice: "500",
  serviceNote: "Mornings only",
  askOnArrival: "ask at reception",
  faqQuestion: "Do you take walk-ins?",
  staffName: "Dr Lakshmi Prasad",
  staffSpoken: "LUCK-shmee pra-SAAD",
  staffRole: "Dentist",
  staffWhyItMatters: "a mispronounced doctor's name is the first thing a caller notices",
  bookingRules:
    "Slots every 20 minutes, up to two weeks ahead. Never promise a specific doctor without checking.",
  contactName: "Front desk",
  knowledgeTitle: "Clinic hours",
  knowledgeAnswer:
    "Our consultation fee is ₹500, adjusted against any treatment on the same day.",
  extractionReason: "so we can route urgent cases to a doctor first",
  scriptBrief:
    "We are a dental clinic in Hyderabad. Callers usually want to book a check-up or ask about teeth cleaning prices. Book appointments and take a callback number.",
};

const REAL_ESTATE: VerticalExamples = {
  orgName: "Skyline Properties",
  orgSlug: "skyline-properties",
  branchLabel: "Head office",
  serviceName: "2 BHK, Gachibowli",
  servicePrice: "8500000",
  serviceNote: "Ready to move",
  askOnArrival: "discussed at the site visit",
  faqQuestion: "Is the property loan-approved?",
  staffName: "Venkat Ramana",
  staffSpoken: "VENK-at ra-MAA-na",
  staffRole: "Sales manager",
  staffWhyItMatters:
    "a mispronounced agent's name is the first thing a caller notices, and they ask for that person by name",
  bookingRules:
    "Site visits Saturday and Sunday, two slots a day, up to three weeks ahead. Never quote a final price on the phone.",
  contactName: "Sales desk",
  knowledgeTitle: "Site visit timings",
  knowledgeAnswer:
    "The 2 BHK units in Gachibowli start at ₹85 lakh, and the price on the phone is indicative until a site visit.",
  extractionReason: "so we can call back the buyers whose budget matches an available unit",
  scriptBrief:
    "We are a property office in Hyderabad. Callers usually ask about available flats, price and location. Book site visits and take a budget and a callback number.",
};

const INSURANCE: VerticalExamples = {
  orgName: "Sujatha Insurance Services",
  orgSlug: "sujatha-insurance",
  branchLabel: "Main office",
  serviceName: "Term life cover",
  servicePrice: "12000",
  serviceNote: "Annual premium, age 30",
  askOnArrival: "quoted after we take your details",
  faqQuestion: "What documents do I need to renew?",
  staffName: "Sujatha Rani",
  staffSpoken: "su-JAA-tha RAA-ni",
  staffRole: "Advisor",
  staffWhyItMatters:
    "a mispronounced advisor's name is the first thing a caller notices, and policyholders ask for their own advisor",
  bookingRules:
    "Advisor callbacks weekdays, within one working day. Never confirm a premium on the phone without the policy number.",
  contactName: "Front office",
  knowledgeTitle: "Renewal documents",
  knowledgeAnswer:
    "A term life renewal needs the policy number and a current address proof; the premium is confirmed once we pull up the policy.",
  extractionReason: "so we can call back the policies that are closest to lapsing first",
  scriptBrief:
    "We are an insurance agency in Vijayawada. Callers usually ask about renewals, premiums and claims. Take the policy number and book an advisor callback.",
};

const EDUCATION: VerticalExamples = {
  orgName: "Vidya Coaching Centre",
  orgSlug: "vidya-coaching",
  branchLabel: "Main centre",
  serviceName: "NEET crash course",
  servicePrice: "45000",
  serviceNote: "Weekend batch",
  askOnArrival: "discussed at the counselling session",
  faqQuestion: "When does the next batch start?",
  staffName: "Padmavathi Reddy",
  staffSpoken: "pad-maa-VA-thi REDD-y",
  staffRole: "Physics faculty",
  staffWhyItMatters:
    "a mispronounced teacher's name is the first thing a parent notices, and they ask for that faculty by name",
  bookingRules:
    "Counselling sessions after 4pm on weekdays, up to a week ahead. Never promise a seat in a batch that is full.",
  contactName: "Admissions desk",
  knowledgeTitle: "Batch timings",
  knowledgeAnswer:
    "The NEET crash course is ₹45,000 for the weekend batch, and the fee can be paid in two instalments.",
  extractionReason: "so we can call back the parents whose child is closest to an exam date",
  scriptBrief:
    "We are a coaching centre in Guntur. Callers usually ask about courses, batch timings and fees. Book counselling sessions and take the student's class and a callback number.",
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
  branchLabel: "Main branch",
  serviceName: "The main thing you sell",
  servicePrice: "500",
  serviceNote: "Mornings only",
  askOnArrival: "ask when you visit",
  faqQuestion: "What the price list does not answer",
  staffName: "The name a caller asks for",
  staffSpoken: "How to say it out loud",
  staffRole: "What they do",
  staffWhyItMatters: "a mispronounced name is the first thing a caller notices",
  bookingRules:
    "How appointments are taken, how far ahead, and what the agent must never promise without checking.",
  contactName: "Front desk",
  knowledgeTitle: "Opening hours",
  knowledgeAnswer: "The answer a caller should have been given.",
  extractionReason: "so we can call back the enquiries that matter most first",
  scriptBrief:
    "What the business does, where it is, what callers usually want, and what the agent should do about it.",
};

const BY_VERTICAL: Readonly<Record<Vertical, VerticalExamples>> = {
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
  // `lookup`, not `key in table` — the house rule, and it is right about this one: `in`
  // walks the prototype chain, so a wire value of `constructor` would report as present
  // and hand this form the `Object` function to read placeholders off. The vertical
  // arrives from an API response, which is exactly the untrusted-key case.
  return lookup(BY_VERTICAL, vertical) ?? CUSTOM;
}
