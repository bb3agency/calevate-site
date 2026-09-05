import { Building2, GraduationCap, Stethoscope, Umbrella } from "lucide-react";

/**
 * The four verticals the product ships starting points for, and what each trade gets.
 *
 * ## Why this is a data module and not a constant inside the tabs component
 *
 * Two surfaces render it — the homepage's tab strip (`components/marketing/industryTabs.
 * tsx`) and `/industries`, which shows all four at full length. One copy, imported by both,
 * because two copies of a field list is exactly the drift the test below exists to catch,
 * one file further along. It is a plain `.ts` module rather than living beside the tabs so
 * that the server-rendered page does not pull a `"use client"` module in to read four
 * arrays.
 *
 * ## `fields` IS THE SEED, LABEL FOR LABEL
 *
 * Copied verbatim and in order from `VERTICAL_TEMPLATES` in `scripts/seed.py`, and
 * `publicLanding.test.tsx` reads them back out of the rendered DOM and diffs them against
 * that file. The value of this list to a buyer is that it is the actual first screen of
 * their agent; a prettier label here is a small lie that only shows up on the day they log
 * in.
 *
 * `suite` marks the two verticals the golden-transcript fixtures cover today — only `cl_*`
 * and `re_*` cases exist in `tests/fixtures/golden_transcripts.json`. Stated on every
 * vertical in both directions rather than implied by silence.
 *
 * ## What the other fields may and may not claim
 *
 * `asks`, `result` and `advantage` are an ILLUSTRATION of one lead, and every surface that
 * renders them says so. `typical` describes what a business in that trade would CONFIGURE
 * — questions, an opening line, a list to work — never a preset the product ships beyond
 * `fields`. All four verticals are written to the same depth on purpose (the founder's
 * decision, 5 Sep 2026): clinics leads the reading order because it leads `seed.py`, and
 * gets no richer example and no editorial promotion for it.
 */
export interface Industry {
  readonly id: string;
  readonly icon: typeof Stethoscope;
  readonly name: string;
  /** The `VERTICAL_TEMPLATES` labels, verbatim and in the seed's order. */
  readonly fields: readonly string[];
  /** Whether a golden-transcript suite exists for this vertical today. */
  readonly suite: boolean;
  /** The problem this trade actually has, in the owner's words. */
  readonly problem: string;
  /** What the caller is asked. */
  readonly asks: string;
  /** The row the owner opens — the structured result, as chips. */
  readonly result: readonly string[];
  /** Why that matters to the business, in one sentence. */
  readonly advantage: string;
  /** What a business in this trade typically sets the agent up to do. */
  readonly typical: readonly string[];
}

export const INDUSTRIES: readonly Industry[] = [
  {
    id: "clinics",
    icon: Stethoscope,
    name: "Clinics",
    fields: ["Symptom / reason", "Preferred doctor", "Urgency", "Preferred slot", "Insurance"],
    suite: true,
    problem:
      "The phone rings hardest at exactly the hour your front desk is busiest, and an " +
      "unanswered call from somebody in pain is a patient who rings the clinic down the road.",
    asks: "What is troubling you, how soon do you need to be seen, and who would you like to see?",
    result: ["Root canal", "Dr Rao", "This week", "Tuesday 6pm", "Cash"],
    advantage:
      "Your front desk opens the day on people who already said what they need and when they can come in.",
    typical: [
      "Answer every call, including the ones that arrive after the clinic closes.",
      "Ask what is wrong, how urgent it is, and which doctor they want.",
      "Offer a slot and book it, once the clinic's Google account is connected.",
      "Ring back the people who enquired online but never called.",
    ],
  },
  {
    id: "property",
    icon: Building2,
    name: "Property offices",
    fields: ["Budget (lakhs)", "Location", "BHK", "Timeline", "Site visit"],
    suite: true,
    problem:
      "Portal leads arrive in bulk and most of them are not buying this year. Your " +
      "salespeople find that out one call at a time, which is a day spent sorting rather " +
      "than selling.",
    asks: "What budget are you working with, which area, how many bedrooms, and when do you want to move?",
    result: ["80 lakh budget", "Gachibowli", "3BHK", "This month", "Site visit: Sat"],
    advantage:
      "Your salesperson rings a qualified buyer, not an unexplained phone number.",
    typical: [
      "Take the first call to every portal enquiry, in the order they arrived.",
      "Ask budget, area, configuration and timeline before anybody's time is spent.",
      "Book the site visit while the person is still interested.",
      "Hand the salesperson a shortlist, with everybody else still on the list and marked.",
    ],
  },
  {
    id: "insurance",
    icon: Umbrella,
    name: "Insurance",
    fields: ["Policy type", "Sum assured", "Renewal due", "Existing insurer"],
    suite: false,
    problem:
      "A renewal is won or lost in the weeks before it falls due, and the advisor who " +
      "rings first usually keeps it. Knowing which of your enquiries is close is the " +
      "whole job.",
    asks: "Which cover are you looking at, for how much, and when is your current policy due?",
    result: ["Health cover", "10 lakh sum assured", "Renewal in 3 weeks", "Existing: other insurer"],
    advantage:
      "You know which renewals are close before somebody else calls them first.",
    typical: [
      "Ask which cover, for how much, and when the current policy is due.",
      "Mark the ones falling due soonest so they surface first.",
      "Book a callback at a time the person actually chose.",
      "Send each one into the CRM the advisors already work from.",
    ],
  },
  {
    id: "coaching",
    icon: GraduationCap,
    name: "Coaching and colleges",
    fields: ["Course", "Class / year", "Fee concern", "Demo booked"],
    suite: false,
    problem:
      "Admission season is a month of calls in which the same four questions are asked " +
      "several hundred times, by counsellors who should be talking to the parents who " +
      "are close to deciding.",
    asks: "Which course, which year is the student in, and would you like to sit in on a class?",
    result: ["NEET repeater", "Class 12", "Asked about fees", "Demo: Friday"],
    advantage:
      "Your counsellor spends admission season on parents who have already asked for a demo.",
    typical: [
      "Answer the season's volume without a temporary phone room.",
      "Ask the course, the year, and whether fees are the sticking point.",
      "Book the demo class, and ring back the ones who did not answer.",
      "Give the counsellors a list sorted by who asked for a demo.",
    ],
  },
];
