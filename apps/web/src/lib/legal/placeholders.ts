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
 * The banner every document carries until a human deliberately deletes it.
 *
 * Not a boolean flag with a default, and not a build-time environment read: publishing an
 * unreviewed legal document is a one-way action, so the thing that stops it is a constant
 * whose removal shows up in a diff with a name on it. `tests/legal.test.tsx` asserts the
 * banner renders on every document while this is `true`.
 */
export const PENDING_LEGAL_REVIEW = true;

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
      "The name the supplier contracts under. THERE IS NO COMPANY AND NO PARENT " +
      "ENTITY: `docs/legal/LEGAL-OPS-PLAYBOOK.md:16` and `:80-96` settle the shape — " +
      "Calevate is a product operated by a sole proprietor, and a sole proprietorship " +
      "has no legal identity separate from the individual who runs it. The founder's " +
      "decision (26 Aug 2026) is to contract under the TRADE NAME, which the playbook " +
      "permits at `:94` (\"[Your legal name / trade name]\").",
    source: "The founder's decision. Playbook §3.",
    value: "Calevate",
  },
  ENTITY_FORM: {
    describes:
      "What kind of legal person the supplier is, in one noun phrase, so no document " +
      "has to guess. It exists because every one of these documents used to imply an " +
      "incorporated company — a certificate of incorporation, a CIN, a Director — and " +
      "none of that is true. A sole proprietorship is the individual: `docs/legal/" +
      "LEGAL-OPS-PLAYBOOK.md:82` — \"You and the business are the same legal person\".",
    source: "Playbook §3, and the founder's decision not to incorporate at launch.",
    value: "a sole proprietorship established in India",
  },
  ENTITY_REGISTRATION_NUMBER: {
    describes:
      "The Udyam (MSME) registration number. NOT a CIN and not an LLPIN — there is no " +
      "company to have one. `docs/legal/LEGAL-OPS-PLAYBOOK.md:23` and §8 (`:227`) make " +
      "Udyam the first entity proof for this shape, and `:204` records why it matters " +
      "beyond the documents: RBI KYC for a proprietorship current account wants two " +
      "proofs in the trade name, and Udyam is usually the first of them.",
    source: "The Udyam registration certificate (udyamregistration.gov.in).",
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
      "The principal place of business, with state and PIN code. NOT a \"registered " +
      "office\" — a proprietorship has none to register. IT IS PUBLISHED AS AN " +
      "IDENTIFICATION ITEM AND NOT AS A CONTACT CHANNEL, and that distinction is the " +
      "whole entry: it is the address a legal notice is served at, one of the items " +
      "the Consumer Protection (E-Commerce) Rules 2020 require to be displayed, and " +
      "half of what `docs/legal/LEGAL-OPS-PLAYBOOK.md:469` calls the minimum credible " +
      "bar (\"Contact (Indian phone + address + email)\") — so the token stays and the " +
      "documents declare the address. What no document offers any more is a POSTAL " +
      "ROUTE: no postal correspondence is serviced, so every \"write to us at\" is an " +
      "email address and a termination notice is an email too (26 Aug 2026). Do not " +
      "re-add a \"By post\" line anywhere — a channel nobody services is worse than no " +
      "channel — and do not answer that by deleting the token, because the display " +
      "obligation is unchanged.",
    source: "The founder's decision, and whatever address the Udyam registration carries.",
  },
  CONTACT_PHONE: {
    describes:
      "A working telephone number that a customer can reach a human on. Indian payment " +
      "aggregators check for this during merchant onboarding, and it is a display item " +
      "under the Consumer Protection (E-Commerce) Rules 2020.",
    source: "A business line that is actually answered — not a personal mobile if avoidable.",
  },
  SUPPORT_EMAIL: {
    describes: "The general support mailbox for client accounts and billing questions.",
    source:
      "A monitored mailbox on the calevate.tech domain. The platform already defaults " +
      "its outbound sender to support@calevate.tech (`notifications_from`).",
  },
  GRIEVANCE_OFFICER_NAME: {
    describes:
      "The named individual designated as Grievance Officer. A role title alone is not " +
      "enough: rule 5(9) of the SPDI Rules 2011 and rule 4(6) of the Consumer " +
      "Protection (E-Commerce) Rules 2020 both require the NAME to be published.",
    source: "A founder or employee appointment, recorded in writing.",
  },
  GRIEVANCE_OFFICER_DESIGNATION: {
    describes:
      "That person's designation. \"Director\" is not available — there is no company " +
      "and there are no directors; for this shape it is normally \"Proprietor\". The " +
      "designation does not discharge the duty on its own: rule 5(9) of the SPDI Rules " +
      "2011 and rule 4(6) of the Consumer Protection (E-Commerce) Rules 2020 both " +
      "require the NAME, which is why `GRIEVANCE_OFFICER_NAME` is a separate blank and " +
      "stays one. `docs/legal/LEGAL-OPS-PLAYBOOK.md:463` says the same in one line: " +
      "\"Grievance Redressal (named human = you)\".",
    source: "The appointment record.",
  },
  GRIEVANCE_OFFICER_EMAIL: {
    describes: "A monitored mailbox that reaches the Grievance Officer directly.",
    source: "A mailbox on the calevate.tech domain, distinct from general support.",
  },
  DATA_PROTECTION_CONTACT_NAME: {
    describes:
      "The person who can answer a data principal's questions about how their personal " +
      "data is processed. Rule 9 of the DPDP Rules 2025 requires this contact to be " +
      "published prominently and repeated in every reply to a rights request. It may " +
      "be the same person as the Grievance Officer; it is a separate entry because the " +
      "two duties come from different instruments and may later sit with two people.",
    source:
      "A founder or employee appointment. A statutory Data Protection Officer is only " +
      "required if the company is notified as a Significant Data Fiduciary.",
  },
  DATA_PROTECTION_CONTACT_EMAIL: {
    describes: "A monitored mailbox that reaches the data protection contact.",
    source: "A mailbox on the calevate.tech domain.",
  },
  SECURITY_CONTACT_EMAIL: {
    describes:
      "Where a security researcher or a client reports a suspected vulnerability or " +
      "breach. Separate from support so a breach report is not queued behind billing " +
      "questions.",
    source: "A monitored mailbox on the calevate.tech domain.",
  },
  JURISDICTION_CITY: {
    describes:
      "The city that is the seat of arbitration and whose courts have exclusive " +
      "jurisdiction. Normally the city of the principal place of business.",
    source: "A commercial decision, taken with counsel.",
  },
  EFFECTIVE_DATE: {
    describes:
      "The date these documents are published and start binding. Fill it in the same " +
      "change that removes the pending-review banner, not before.",
    source: "The publication decision.",
  },
  DLT_TELEMARKETER_ID: {
    describes:
      "Calevate's registered Telemarketer (TM) identifier on an access provider's DLT " +
      "platform. Until it exists no outbound campaign can lawfully be dialled, and the " +
      "compliance gate already refuses every campaign with the blocker " +
      "`tm_registration_missing`.",
    source:
      "DLT registration with an access provider under the proprietor's PAN " +
      "(`docs/legal/LEGAL-OPS-PLAYBOOK.md:87`, §10). The entity is no longer the " +
      "blocker — the registration is.",
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
      "The payment gateway's own settlement timeline plus internal approval time. Ask " +
      "the gateway for their figure and add your own approval window.",
  },
  TERMINATION_NOTICE_DAYS: {
    describes: "Notice period either party must give to end a managed engagement.",
    source: "A commercial decision, and it must match what the signed order form says.",
  },
  DATA_RETURN_WINDOW_DAYS: {
    describes:
      "How long after termination a client may still export their data before it is " +
      "erased. The erasure mechanism exists (`tenant_erasure_requests`); the window is " +
      "a commercial and legal commitment nobody has taken.",
    source: "A decision taken with counsel, recorded in the decision log (ROADMAP §6).",
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
 * legal document containing `{{REGISTERED_ADDRESS}}` is not a cosmetic defect: it is a document that
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
