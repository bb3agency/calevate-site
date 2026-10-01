import { type ReactNode } from "react";

import { Term } from "@/lib/glossary";
import { type Classification, type ConsentSource } from "@/lib/api/campaigns";

/**
 * THE FIXED VOCABULARIES this screen offers a client, and the styling of the cards that
 * offer them.
 *
 * Extracted from `page.tsx` (UX-DOCTRINE §6: extract by SUBJECT). One subject: the closed
 * sets — call category, consent source, weekday. The choice-card classes they are
 * rendered with are shared (`components/console/choiceCard.ts`). None of the wording changed in the move; `CONSENT_SOURCES` in
 * particular is a compliance artefact whose neutrality is the point, and its argument is
 * kept with it below.
 */

/**
 * The five answers, in the client's language.
 *
 * `purchased_list` sits in this list at the same size, in the same order it appears in
 * the API's enum, with the same plain description as the other four and NO warning
 * attached. That is deliberate, and it is the whole reason the option exists: the
 * policy is that a purchased list is refused IN WRITING, and a refusal can only be
 * written against an answer somebody actually gave. Labelling it "not allowed" here,
 * greying it out, or hiding it behind a disclosure would not stop anyone dialling a
 * bought list — it would only teach them to pick the nearest acceptable-sounding
 * neighbour ("existing customers"), which loses the refusal AND corrupts the record we
 * would need if a complaint ever landed. So the form asks a neutral question, and the
 * consequence arrives from the server, by name, rendered as its own blocker above.
 */
export const CONSENT_SOURCES: { value: ConsentSource; label: string; hint: string }[] =
  [
    {
      value: "existing_customer",
      label: "Our existing customers",
      hint: "People who have bought from us or hold an account with us.",
    },
    {
      value: "inbound_enquiry",
      label: "People who contacted us",
      hint: "Enquiries by phone, message or walk-in that we're following up.",
    },
    {
      value: "web_form_optin",
      label: "Signed up on our website",
      hint: "Filled in a form online and agreed to be contacted.",
    },
    {
      value: "offline_form_optin",
      label: "Signed up on paper",
      hint: "A form, register or slip filled in at our shop, office or an event.",
    },
    {
      value: "purchased_list",
      label: "Bought or rented list",
      hint: "Contacts supplied by a data vendor, broker or another business.",
    },
  ];

/**
 * The days of the week, in the server's own numbering (ISO: 1 = Monday).
 *
 * Not `Date.getDay()`'s numbering, which starts at Sunday = 0. One vocabulary from the
 * checkbox to the stored rule to the dispatch tick; a second one is an off-by-one that
 * dials on the wrong day, which on this product means calling strangers on a Sunday.
 */
export const WEEKDAYS: { value: number; label: string; short: string }[] = [
  { value: 1, label: "Monday", short: "Mon" },
  { value: 2, label: "Tuesday", short: "Tue" },
  { value: 3, label: "Wednesday", short: "Wed" },
  { value: 4, label: "Thursday", short: "Thu" },
  { value: 5, label: "Friday", short: "Fri" },
  { value: 6, label: "Saturday", short: "Sat" },
  { value: 7, label: "Sunday", short: "Sun" },
];


export const CLASSIFICATIONS: {
  value: Classification;
  label: string;
  hint: ReactNode;
}[] = [
  {
    value: "promotional",
    label: "Promotional",
    hint: (
      <>
        Offers and marketing — dials from a{" "}
        <Term id="series140" /> number
      </>
    ),
  },
  {
    value: "service",
    label: "Service",
    hint: (
      <>
        Updates to existing customers —{" "}
        <Term id="series160" /> or standard
      </>
    ),
  },
  {
    value: "transactional",
    label: "Transactional",
    hint: (
      <>
        Order and appointment updates —{" "}
        <Term id="series160" /> or standard
      </>
    ),
  },
];

