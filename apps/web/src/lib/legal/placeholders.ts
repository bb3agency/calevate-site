/**
 * Every fact about the business that this repository does not know, and must not invent.
 *
 * A legal document with a fabricated registered address, GSTIN or grievance officer is
 * worse than no document: it is a false statement published under the company's name, and
 * for the GST identity and the grievance contact it is a false statement a regulator reads
 * first. So each one is a `{{TOKEN}}` in the prose, rendered visibly, listed here with
 * what it is and where the founder gets it.
 *
 * `tests/legal.test.tsx` holds the two directions together: every token used in a document
 * is declared here, and every token declared here is used by at least one document. A
 * placeholder nobody renders is a fact somebody quietly hard-coded; a token nobody
 * declares is a fact nobody told the founder to fill in.
 */

import { lookup } from "@/lib/lookup";

/** What one unfilled fact is, and where its value comes from. */
export interface Placeholder {
  /** What the value is, in the founder's words. */
  readonly describes: string;
  /** Where the real value comes from — a registrar, a portal, a decision. */
  readonly source: string;
  /**
   * The decided value, once it exists. Present = the fact is KNOWN, and the renderer
   * substitutes it everywhere the token appears; absent = still a blank.
   *
   * This field is the fix for a defect that had been live on `/legal/dpa` clause 9 and
   * `/legal/privacy` §8: `{{PRIMARY_HOSTING_LOCATION}}` rendered as a raw token on two
   * client-facing pages for weeks AFTER the decision that answers it (D-180) was taken.
   * Nothing was wrong with the token machinery — nothing connected a taken decision to
   * the prose, so the only way to fill a blank was to edit every document that used it
   * and hope none was missed. One value here reaches all of them at once, the documents
   * keep the token so `textOf` can still audit both directions, and
   * `assertLegalSetPublishable` below makes the remaining blanks a publication blocker
   * rather than a thing a reader discovers.
   */
  readonly value?: string;
}

/**
 * The token syntax. Deliberately noisy: `{{…}}` survives copy-paste into a Word document
 * and into a lawyer's redline, where a subtle placeholder would be read as final text.
 */
export const PLACEHOLDER_PATTERN = /\{\{([A-Z0-9_ ]+)\}\}/g;

/**
 * Whether the set is still a draft. FALSE since 2 September 2026: the documents are
 * published and in force.
 *
 * Not a boolean flag with a default, and not a build-time environment read: publishing a
 * legal document is a one-way action, so the thing that gated it was a constant whose
 * flip shows up in a diff with a name on it. It was flipped on the founder's explicit
 * instruction, given after a lawyer's review of the set, and only once every fact in
 * `PLACEHOLDERS` below carried a value — `assertLegalSetPublishable` refuses the render
 * otherwise, so a blank cannot survive the flip even by accident.
 *
 * While it stood, every document carried the draft banner and every version string ended
 * `+pre-review`. Turning it off changed both: the banner component returns null, the
 * version label drops its qualifier, and every acceptance recorded against a
 * `+pre-review` version stopped being current, so the server asks every client to accept
 * again. Nothing special-cases that; it falls out of the version string.
 *
 * `apps/api/legal/catalogue.py` declares the same constant — there is no import from
 * TypeScript — and `scripts/check_docs_drift.py` fails CI if the two ever disagree.
 * `tests/legal.test.tsx` asserts the published state: no banner on any document, and no
 * unresolved token anywhere.
 */
export const PENDING_LEGAL_REVIEW = false;

/** The literal marker, so the banner text and the source grep for it agree. */
export const PENDING_LEGAL_REVIEW_MARKER = "{{PENDING LEGAL REVIEW}}";

/**
 * Tokens the page SHELL renders rather than any one document's prose.
 *
 * `{{EFFECTIVE_DATE}}` appears in the header of all eight pages and in none of their
 * section text, so the audit in `tests/legal.test.tsx` — which walks document content —
 * would report it as declared-but-unused and send somebody to delete a live token. It is
 * named here so the renderer and the audit read the same constant instead of both
 * spelling it, which is the drift `PENDING_LEGAL_REVIEW_MARKER` exists to avoid one line
 * up.
 */
export const CHROME_TOKENS: readonly string[] = ["{{EFFECTIVE_DATE}}"];

export const PLACEHOLDERS: Readonly<Record<string, Placeholder>> = {
  LEGAL_ENTITY_NAME: {
    describes:
      "The name the supplier contracts under, and the name every document identifies " +
      "it by. It is the enterprise name on the Udyam registration certificate, so the " +
      "documents and the register agree — which is the whole point of publishing a " +
      "name at all. The documents state the name, the registration number and the " +
      "principal place of business and stop there: they make no statement about the " +
      "supplier's legal form, and none is required of them (see " +
      "`ENTITY_REGISTRATION_NUMBER` for the display obligation that is real).",
    source:
      "PRIMARY SOURCE — the Udyam Registration Certificate, printed from " +
      "udyamregistration.gov.in on 25 Aug 2026 and read by the founder, which carries " +
      "the enterprise name CALEVATE. Rendered here in the case the prose uses.",
    value: "Calevate",
  },
  ENTITY_REGISTRATION_NUMBER: {
    describes:
      "The registration number the documents publish as an identifier — the Udyam " +
      "(MSME) number. It is one of the three neutral identification items the " +
      "documents carry (name, registration number, principal place of business), and " +
      "the display obligation behind it is rule 4 of the Consumer Protection " +
      "(E-Commerce) Rules 2020, which requires the legal name, the principal place of " +
      "business and contact details — and does NOT require the entity's legal form to " +
      "be stated. `docs/legal/LEGAL-OPS-PLAYBOOK.md:23` and §8 (`:227`) make Udyam the " +
      "first entity proof to obtain, and `:204` records why it matters beyond the " +
      "documents: RBI KYC for a current account in the trade name wants two proofs, " +
      "and Udyam is usually the first of them.",
    source:
      "PRIMARY SOURCE — the Udyam Registration Certificate, printed from " +
      "udyamregistration.gov.in on 25 Aug 2026 and read by the founder " +
      "(registration date 25/08/2026; enterprise type Micro; NIC 62013).",
    value: "UDYAM-AP-04-0146106",
  },
  GST_STATUS: {
    describes:
      "Whether the supplier is registered for GST, as a sentence a document can print. " +
      "THIS REPLACED `GSTIN`, and the change is not cosmetic: a blank GSTIN said \"we " +
      "have one and have not typed it in\", which was false. We are not registered, we " +
      "are not required to be, and that is a fact with a citation rather than a gap. " +
      "Restore a `GSTIN` token in the same change that registers — `apps/api/billing/" +
      "gst.py` already refuses to render a tax invoice without one, so the code and the " +
      "documents move together.",
    source:
      "`docs/legal/LEGAL-OPS-PLAYBOOK.md` §4: the CGST s.22 threshold for services in " +
      "Andhra Pradesh and Telangana is ₹20 lakh aggregate turnover (`:105`), and " +
      "Notification No. 10/2017–Integrated Tax (13 Oct 2017) exempts a person making " +
      "inter-state supplies of taxable SERVICES from the compulsory registration in " +
      "CGST s.24 while they are under it (`:115`). Both are the playbook's readings, " +
      "not this repository's — re-verify against the instruments before relying on " +
      "either commercially.",
    value:
      "not registered for GST, and not required to be at present turnover",
  },
  REGISTERED_ADDRESS: {
    describes:
      "WHERE the business is, at the CITY level — locality, state and country, and " +
      "deliberately no street lines. IT IS PUBLISHED AS AN IDENTIFICATION ITEM AND NOT " +
      "AS A CONTACT CHANNEL, and that distinction is the whole entry: it says which " +
      "business and which jurisdiction a reader is dealing with, and it offers no route " +
      "to send anything to. Half of what `docs/legal/LEGAL-OPS-PLAYBOOK.md:469` calls " +
      "the minimum credible bar (\"Contact (Indian phone + address + email)\") is met by " +
      "it together with `CONTACT_PHONE` and `SUPPORT_EMAIL`, and " +
      "`JURISDICTION_CITY` — the arbitral seat and the courts clause in the Terms — " +
      "names the same city, so the two agree by reading rather than by coincidence.\n\n" +
      "⚠ THE STREET LINES WERE REMOVED ON 4 SEPTEMBER 2026 AND MUST NOT COME BACK. " +
      "The value used to be the Udyam certificate's address in full — flat, building, " +
      "lane, colony, PIN. That is the FOUNDER'S HOME, and this repository was " +
      "publishing it on eight pages open to the internet, in a product whose own " +
      "privacy notice is about not over-collecting. The founder asked for it gone " +
      "(\"in our docs we still have my full address please fix that\"). Deleting the " +
      "token instead would have traded a privacy problem for a compliance one, which " +
      "is why the entry survives with less in it rather than not at all. The PIN code " +
      "went with the street lines on purpose: 522007 narrows to a sub-locality of " +
      "Guntur, so keeping it would have kept most of what was being removed.\n\n" +
      "WHAT THE REDUCED VALUE STILL SATISFIES, AND THE ONE DUTY IT MAY NOT. The " +
      "instruments that make us publish an identity at all are satisfied by name, " +
      "registration number, city, telephone and a monitored mailbox, and none of them " +
      "asks for a street: rule 5(9) of the SPDI Rules 2011 wants the Grievance " +
      "Officer's NAME and contact details; rule 9 of the DPDP Rules 2025 wants the " +
      "BUSINESS CONTACT INFORMATION of the person who answers a Data Principal's " +
      "questions; the telecom framework takes our address on DLT registration through " +
      "the access provider and publishes nothing. The one that is NOT clearly " +
      "satisfied is rule 4(2)(b) of the Consumer Protection (E-Commerce) Rules 2020, " +
      "which asks an e-commerce entity to display \"the principal geographic address " +
      "of its headquarters and all branches\" — a phrase that reads like a servable " +
      "address, not a city. Two things keep that from being a reason to republish a " +
      "home address, and NEITHER is a finding this file may state as fact: the Rules " +
      "hang off the Consumer Protection Act 2019, whose s.2(7) definition of " +
      "\"consumer\" excludes a person availing a service \"for any commercial " +
      "purpose\", and every client of this product is a business buying it for one; " +
      "and the duty is a WEBSITE display duty on the entity, not a clause any of these " +
      "eight documents owes. The real answer is a business address that is not " +
      "somebody's home, which is a thing to obtain and not a thing to draft — it is on " +
      "the founder (see D-532), and this value moves the day one exists.",
    source:
      "PRIMARY SOURCE for the value — the Udyam Registration Certificate, printed from " +
      "udyamregistration.gov.in on 25 Aug 2026 and read by the founder: the city, " +
      "state and country fields of its address, and nothing else from them. The " +
      "founder confirmed the reduction to city level, and that \"Guntur is fine\", on " +
      "4 Sep 2026.\n" +
      "EVIDENCE CLASS FOR THE STATUTORY READING ABOVE: WEB-SEARCH RELAY, NOT PRIMARY. " +
      "Every host carrying the instruments — indiacode.nic.in, consumeraffairs.nic.in, " +
      "trai.gov.in, wipo.int — is egress-blocked from this container, so the rule text " +
      "was read through search-engine extracts on 4 Sep 2026 and no page was fetched. " +
      "That is good enough to REDUCE what we publish, because nothing above claims a " +
      "duty is discharged that was not discharged before; it is NOT good enough to " +
      "close rule 4(2)(b), which is why D-532 routes that to a human with the " +
      "instrument in front of them rather than settling it here.",
    value: "Guntur, Andhra Pradesh, India",
  },
  CONTACT_PHONE: {
    describes:
      "A working telephone number that a customer can reach a human on. Indian payment " +
      "aggregators check for this during merchant onboarding, and it is a display item " +
      "under the Consumer Protection (E-Commerce) Rules 2020. Written the way a reader " +
      "dials it; E.164 (+918019857559) is what a machine field would take.",
    source:
      "PRIMARY SOURCE — the mobile number on the Udyam Registration Certificate, " +
      "printed from udyamregistration.gov.in on 25 Aug 2026 and read by the founder.",
    value: "+91 80198 57559",
  },
  SUPPORT_EMAIL: {
    describes: "The general support mailbox for client accounts and billing questions.",
    source:
      "PUBLISHED ADDRESS: currently a Gmail mailbox, by the founder's decision of " +
      "2 Sep 2026 — it is the mailbox that is actually read, and a published channel " +
      "nobody reads is worse than a plainer one that is. The intended upgrade is a " +
      "mailbox on the calevate.tech domain; when it exists the change is the `value` " +
      "here and nothing else, which is what this registry is for — four values in one " +
      "file rather than a hunt through eight documents. A REPLY REACHES IT (D-518): the " +
      "platform still SENDS from `notifications_from` (support@calevate.tech) because " +
      "the delivery provider refuses a send outright when the sender's domain is " +
      "unverified and no one can verify a public webmail domain — so pointing the " +
      "sender here would stop the mail, not redirect it. `notifications_reply_to` " +
      "carries this address instead, and a client pressing Reply lands in the mailbox " +
      "that is read. Change both together or a reply goes nowhere again.",
    value: "calevate.voice@gmail.com",
  },
  GRIEVANCE_OFFICER_NAME: {
    describes:
      "The named individual designated as Grievance Officer. A role title alone is not " +
      "enough: rule 5(9) of the SPDI Rules 2011 and rule 4(6) of the Consumer " +
      "Protection (E-Commerce) Rules 2020 both require the NAME to be published. ⚠ The " +
      "value is a first name only, which is what the founder gave. A full name is a " +
      "materially stronger compliance artefact than a first name, and this entry is " +
      "where the surname goes when it is supplied.",
    source: "The founder's decision (2 Sep 2026), and the appointment record.",
    value: "Umesh J",
  },
  GRIEVANCE_OFFICER_DESIGNATION: {
    describes:
      "That person's designation, which is the office they hold rather than a rank in " +
      "an organisation: \"Grievance Officer\". It is a separate entry from the name " +
      "because the designation does not discharge the duty on its own — rule 5(9) of " +
      "the SPDI Rules 2011 and rule 4(6) of the Consumer Protection (E-Commerce) Rules " +
      "2020 both require the NAME to be published, which is why " +
      "`GRIEVANCE_OFFICER_NAME` is a blank and stays one. " +
      "`docs/legal/LEGAL-OPS-PLAYBOOK.md:463` says the same in one line: " +
      "\"Grievance Redressal (named human = you)\".",
    source: "The founder's decision, and the appointment record.",
    value: "Grievance Officer",
  },
  GRIEVANCE_OFFICER_EMAIL: {
    describes: "A monitored mailbox that reaches the Grievance Officer directly.",
    source:
      "PUBLISHED ADDRESS: currently a Gmail mailbox, by the founder's decision of " +
      "2 Sep 2026 — it is the mailbox that is actually read, and a published channel " +
      "nobody reads is worse than a plainer one that is. The intended upgrade is a " +
      "mailbox on the calevate.tech domain; when it exists the change is the `value` " +
      "here and nothing else, which is what this registry is for — four values in one " +
      "file rather than a hunt through eight documents. A REPLY REACHES IT (D-518): the " +
      "platform still SENDS from `notifications_from` (support@calevate.tech) because " +
      "the delivery provider refuses a send outright when the sender's domain is " +
      "unverified and no one can verify a public webmail domain — so pointing the " +
      "sender here would stop the mail, not redirect it. `notifications_reply_to` " +
      "carries this address instead, and a client pressing Reply lands in the mailbox " +
      "that is read. Change both together or a reply goes nowhere again.",
    value: "calevate.voice@gmail.com",
  },
  DATA_PROTECTION_CONTACT_NAME: {
    describes:
      "The person who can answer a data principal's questions about how their personal " +
      "data is processed. Rule 9 of the DPDP Rules 2025 requires this contact to be " +
      "published prominently and repeated in every reply to a rights request. It may " +
      "be the same person as the Grievance Officer; it is a separate entry because the " +
      "two duties come from different instruments and may later sit with two people.",
    source:
      "The founder's decision (2 Sep 2026), and the appointment record. A statutory " +
      "Data Protection Officer is only required of a Significant Data Fiduciary, which " +
      "nobody has been notified as.",
    value: "Umesh J",
  },
  DATA_PROTECTION_CONTACT_EMAIL: {
    describes: "A monitored mailbox that reaches the data protection contact.",
    source:
      "PUBLISHED ADDRESS: currently a Gmail mailbox, by the founder's decision of " +
      "2 Sep 2026 — it is the mailbox that is actually read, and a published channel " +
      "nobody reads is worse than a plainer one that is. The intended upgrade is a " +
      "mailbox on the calevate.tech domain; when it exists the change is the `value` " +
      "here and nothing else, which is what this registry is for — four values in one " +
      "file rather than a hunt through eight documents. A REPLY REACHES IT (D-518): the " +
      "platform still SENDS from `notifications_from` (support@calevate.tech) because " +
      "the delivery provider refuses a send outright when the sender's domain is " +
      "unverified and no one can verify a public webmail domain — so pointing the " +
      "sender here would stop the mail, not redirect it. `notifications_reply_to` " +
      "carries this address instead, and a client pressing Reply lands in the mailbox " +
      "that is read. Change both together or a reply goes nowhere again.",
    value: "calevate.voice@gmail.com",
  },
  SECURITY_CONTACT_EMAIL: {
    describes:
      "Where a security researcher or a client reports a suspected vulnerability or " +
      "breach. Separate from support so a breach report is not queued behind billing " +
      "questions.",
    source:
      "PUBLISHED ADDRESS: currently a Gmail mailbox, by the founder's decision of " +
      "2 Sep 2026 — it is the mailbox that is actually read, and a published channel " +
      "nobody reads is worse than a plainer one that is. The intended upgrade is a " +
      "mailbox on the calevate.tech domain; when it exists the change is the `value` " +
      "here and nothing else, which is what this registry is for — four values in one " +
      "file rather than a hunt through eight documents. A REPLY REACHES IT (D-518): the " +
      "platform still SENDS from `notifications_from` (support@calevate.tech) because " +
      "the delivery provider refuses a send outright when the sender's domain is " +
      "unverified and no one can verify a public webmail domain — so pointing the " +
      "sender here would stop the mail, not redirect it. `notifications_reply_to` " +
      "carries this address instead, and a client pressing Reply lands in the mailbox " +
      "that is read. Change both together or a reply goes nowhere again.",
    value: "calevate.voice@gmail.com",
  },
  JURISDICTION_CITY: {
    describes:
      "The city that is the seat of arbitration and whose courts have exclusive " +
      "jurisdiction. Normally the city of the principal place of business, which is " +
      "what it is here — so the arbitration clause and the courts clause in the Terms " +
      "both point at Guntur, Andhra Pradesh.",
    source:
      "The founder's decision, confirmed explicitly on 2 Sep 2026, taking the default " +
      "this entry names: the city in the principal place of business on the Udyam " +
      "Registration Certificate (PRIMARY SOURCE, printed 25 Aug 2026 and read by the " +
      "founder).",
    value: "Guntur",
  },
  EFFECTIVE_DATE: {
    describes:
      "The date these documents are published and start binding. It renders under " +
      "\"In force from\" in the header of all eight pages, so it is written the way a " +
      "date is read rather than in the ISO spelling — `versions.ts` and " +
      "`apps/api/legal/catalogue.py` carry the machine form of the same day, and the " +
      "docs-drift guard holds those two equal.",
    source:
      "The publication decision: the founder's instruction of 2 Sep 2026, given after a " +
      "lawyer's review of the set, to take the documents out of draft.",
    value: "2 September 2026",
  },
  PRIMARY_HOSTING_LOCATION: {
    describes:
      "Where the server that runs the application and holds the database is. It decides " +
      "whether the privacy notice describes a cross-border transfer of every transcript " +
      "and lead in the system, which is why it was the one blank that mattered most. " +
      "D-180 answered it — a Hostinger VPS in India, superseding D-25's 'Hetzner-class, " +
      "co-location not required' as to provider and region — so it carries a value. What " +
      "the decision does NOT fix is the data centre, because nothing is provisioned yet " +
      "(`infra/README.md` §5); name the city here in the change that provisions it.",
    source: "The hosting decision (ROADMAP D-180), and then the provisioned host itself.",
    value: "a Hostinger data centre in India",
  },
  REFUND_PROCESSING_DAYS: {
    describes:
      "How many business days an approved refund takes to reach the original payment " +
      "instrument. Indian payment aggregators require a stated timeline on the " +
      "published refund policy.",
    source:
      "The founder's decision: the published commitment is 7 business days, which is " +
      "OUR undertaking rather than a figure any gateway has quoted us. It is the outer " +
      "edge of the window, so a settlement that lands sooner keeps the promise. If a " +
      "gateway's own timeline is later found to be longer, this number moves before " +
      "the promise is made to anyone.",
    value: "7",
  },
  TERMINATION_NOTICE_DAYS: {
    describes:
      "Notice period either party must give to end a managed engagement, in days, so " +
      "the prose can write \"{{TERMINATION_NOTICE_DAYS}} days' written notice\".",
    source:
      "The founder's decision. It must match what a signed order form says — an order " +
      "form with a different period wins for that client, and the Terms say so.",
    value: "30",
  },
  DATA_RETURN_WINDOW_DAYS: {
    describes:
      "How long after termination a client may still export their data before it is " +
      "erased. The erasure mechanism exists (`tenant_erasure_requests`); the window is " +
      "the commercial and legal commitment around it.",
    source:
      "The founder's decision, to be confirmed with counsel at review and recorded in " +
      "the decision log (ROADMAP §6).",
    value: "30",
  },
};

/** Every token used anywhere in `text`. */
export function placeholdersIn(text: string): string[] {
  return [...text.matchAll(PLACEHOLDER_PATTERN)].map((match) => match[1]);
}

/**
 * Substitute every token whose fact has been DECIDED, and leave the rest standing.
 *
 * Called by the renderer before anything is marked up, so a decided fact can never reach
 * a reader as `{{A_TOKEN}}` — which is what happened with the hosting location. An
 * undeclared token is left alone rather than dropped: `tests/legal.test.tsx` already
 * fails on one, and silently swallowing it here would turn a loud test failure into a
 * page with a hole in it.
 */
export function resolvePlaceholders(text: string): string {
  return text.replace(
    new RegExp(PLACEHOLDER_PATTERN.source, "g"),
    (token, name: string) => lookup(PLACEHOLDERS, name)?.value ?? token,
  );
}

/**
 * The facts still missing — every declared placeholder with no value yet, in declaration
 * order. This is the founder's remaining to-do list, computed rather than maintained.
 */
export function unresolvedPlaceholders(): string[] {
  return Object.entries(PLACEHOLDERS)
    .filter(([, entry]) => entry.value === undefined)
    .map(([token]) => token);
}

/**
 * Refuse to publish the legal set while any fact in it is still a blank.
 *
 * The renderer calls this on every document. While `PENDING_LEGAL_REVIEW` stands, blanks
 * are the POINT — they render as visible marks under a banner that tells the reader not
 * to rely on the page, and that is how the founder and their advocate see what is still
 * missing. The moment somebody deletes that banner they are publishing, and a published
 * legal document containing `{{GRIEVANCE_OFFICER_NAME}}` is not a cosmetic defect: it is a document that
 * announces its own drafting state to a regulator or a buyer's counsel.
 *
 * So the two constants are wired together rather than left as two independent decisions
 * a person has to remember to take in the right order. Turning the banner off with blanks
 * outstanding throws here, loudly, naming every one of them — it cannot be reached by a
 * reader, because it fails the build's own render first.
 *
 * `pendingReview` is a parameter so the refusal itself is testable; nothing but the test
 * should pass it.
 */
export function assertLegalSetPublishable(pendingReview: boolean = PENDING_LEGAL_REVIEW): void {
  if (pendingReview) return;
  const missing = unresolvedPlaceholders();
  if (missing.length === 0) return;
  throw new Error(
    `The pending-review banner has been removed while ${missing.length} fact(s) in the ` +
      `legal documents are still blank, so these tokens would publish as literal text: ` +
      `${missing.join(", ")}. Give each one a \`value\` in ` +
      `src/lib/legal/placeholders.ts, or put the banner back.`,
  );
}
