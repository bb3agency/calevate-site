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

/** What one unfilled fact is, and where its value comes from. */
export interface Placeholder {
  /** What the value is, in the founder's words. */
  readonly describes: string;
  /** Where the real value comes from — a registrar, a portal, a decision. */
  readonly source: string;
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
      "The registered name of the legal person that supplies Calevate, exactly as it " +
      "appears on the incorporation certificate — including the suffix (Private " +
      "Limited, LLP, or the proprietor's name for a proprietorship).",
    source: "Certificate of incorporation / registration. ROADMAP Milestone-0 'entity decision'.",
  },
  ENTITY_REGISTRATION_NUMBER: {
    describes:
      "The company identifier: CIN for a private limited company, LLPIN for an LLP, or " +
      "the Udyam / shop-and-establishment registration number for a proprietorship.",
    source: "MCA master data, or the registering authority for an unincorporated entity.",
  },
  GSTIN: {
    describes:
      "The 15-character GST identification number of the supplier. Until it exists, " +
      "invoices are issued as proforma documents and no tax may be collected " +
      "(CGST s.32) — the billing module already refuses to render a tax invoice " +
      "without it.",
    source: "GST registration certificate (Form REG-06).",
  },
  REGISTERED_ADDRESS: {
    describes:
      "The full registered office address, with state and PIN code. It is the address " +
      "on the GST invoice, the address a legal notice is served at, and one of the " +
      "items the Consumer Protection (E-Commerce) Rules 2020 require to be displayed.",
    source: "Certificate of incorporation / GST registration.",
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
    describes: "That person's designation in the company (for example, Director).",
    source: "The same appointment record.",
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
      "jurisdiction. Normally the city of the registered office.",
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
      "DLT registration with an access provider, which requires the legal entity to " +
      "exist first. ROADMAP Milestone-0.",
  },
  PRIMARY_HOSTING_LOCATION: {
    describes:
      "The country and city of the server that runs the application and holds the " +
      "database. This is UNRESOLVED in the blueprint — DEPLOYMENT.md §0 says a " +
      "general-purpose VPS with India co-location NOT required, and nothing has been " +
      "provisioned. It must be decided and stated before this notice is published, " +
      "because it decides whether the privacy notice describes a cross-border transfer " +
      "of every transcript and lead in the system.",
    source: "The hosting decision (ROADMAP D-25), and then the provisioned host itself.",
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
