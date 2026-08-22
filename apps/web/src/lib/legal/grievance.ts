import type { LegalDocument } from "./types";

/**
 * Grievance redressal — one page, three regimes, and the timetables are different.
 *
 * The reason this is a document rather than a paragraph at the bottom of the privacy
 * notice: three separate instruments each require a published contact and each sets its
 * own clock, and they do not agree. Rule 5(9) of the SPDI Rules 2011 says one month and is
 * the operative privacy rule TODAY. Rule 4(6) of the Consumer Protection (E-Commerce)
 * Rules 2020 says acknowledge in 48 hours, redress in one month. Rule 14(3) of the DPDP
 * Rules 2025 says publish your timeline and in no case exceed ninety days, and its
 * substantive commencement is 13 May 2027.
 *
 * Publishing the LONGEST of the three would be lawful and would be a worse product. So the
 * page states one commitment — the shortest — and shows the statutory outer limits beside
 * it, so a reader can see both what we promise and what we could get away with.
 */
export const GRIEVANCE: LegalDocument = {
  slug: "grievance",
  title: "Grievance Redressal",
  shortTitle: "Grievance Redressal",
  summary:
    "Who to contact with a complaint, what we commit to, by when, and where to escalate " +
    "if we do not deliver.",
  appliesTo:
    "Anyone with a complaint about Calevate: a client, a person who works for a client, " +
    "or a member of the public who received a call.",
  sections: [
    {
      id: "who",
      heading: "1. Who to contact",
      blocks: [
        {
          kind: "para",
          text:
            "Three named contacts, because three different instruments require one and " +
            "the right desk depends on what went wrong. If you are not sure, use the " +
            "Grievance Officer; internal routing is our problem, not yours.",
        },
        {
          kind: "table",
          caption: "Contacts, and what each one is for",
          columns: ["If your complaint is about", "Contact", "Required by"],
          rows: [
            [
              "Anything at all — service, billing, conduct, a call you received. This is " +
                "the general channel and it never turns anyone away.",
              "{{GRIEVANCE_OFFICER_NAME}}, {{GRIEVANCE_OFFICER_DESIGNATION}} — " +
                "{{GRIEVANCE_OFFICER_EMAIL}}",
              "Rule 5(9), Information Technology (Reasonable Security Practices and " +
                "Procedures and Sensitive Personal Data or Information) Rules 2011; and " +
                "rule 4(6), Consumer Protection (E-Commerce) Rules 2020.",
            ],
            [
              "How your personal data is processed, or exercising a right over it.",
              "{{DATA_PROTECTION_CONTACT_NAME}} — {{DATA_PROTECTION_CONTACT_EMAIL}}",
              "Rule 9, Digital Personal Data Protection Rules 2025 — the business contact " +
                "of the person who can answer a data principal's questions.",
            ],
            [
              "A suspected security vulnerability or a suspected breach.",
              "{{SECURITY_CONTACT_EMAIL}}",
              "Our own commitment. Reports made in good faith will not be pursued, and we " +
                "ask for a reasonable window to fix before disclosure.",
            ],
          ],
        },
        {
          kind: "para",
          text:
            "By post: {{LEGAL_ENTITY_NAME}}, {{REGISTERED_ADDRESS}}. By telephone: " +
            "{{CONTACT_PHONE}}.",
        },
      ],
    },
    {
      id: "timetable",
      heading: "2. What we commit to, and the statutory outer limits",
      blocks: [
        {
          kind: "table",
          caption: "Our commitment against the statutory limits",
          columns: ["Stage", "Our commitment", "The longest the law allows"],
          rows: [
            [
              "Acknowledgement",
              "Within 2 business days, with a reference number and the name of the person " +
                "handling it.",
              "48 hours (Consumer Protection (E-Commerce) Rules 2020, rule 4(6)).",
            ],
            [
              "Substantive reply",
              "Within 15 business days for most complaints.",
              "One month (SPDI Rules 2011, rule 5(9); Consumer Protection (E-Commerce) " +
                "Rules 2020, rule 4(6)).",
            ],
            [
              "A complaint needing investigation across call records, or one involving a " +
                "client's own records",
              "Within 30 days, with a progress update at day 15 if it will take that long.",
              "Ninety days (DPDP Rules 2025, rule 14(3), on its commencement).",
            ],
            [
              "A rights request over personal data — access, correction, erasure",
              "Within 30 days of verifying who you are.",
              "Ninety days (DPDP Rules 2025, rule 14(3), on its commencement).",
            ],
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "Why two sets of dates",
          text:
            "The Digital Personal Data Protection Rules 2025 were notified on 14 November " +
            "2025 with a phased commencement — the Data Protection Board framework from " +
            "November 2025, Consent Manager provisions from November 2026, and the " +
            "substantive obligations including grievance redressal from 13 May 2027. Until " +
            "then the 2011 rules under the Information Technology Act 2000 are the " +
            "operative privacy law and their one-month clock is the binding one. We are " +
            "not waiting for 2027 to honour any of it, and the commitments in the middle " +
            "column apply now.",
        },
      ],
    },
    {
      id: "what-to-include",
      heading: "3. What to send us",
      blocks: [
        {
          kind: "para",
          text:
            "You do not need a form or a particular wording. What speeds it up is enough " +
            "detail for us to find the record:",
        },
        {
          kind: "list",
          items: [
            "What happened, and what you would like done about it.",
            "For a complaint about a call: the number that called you, the number it " +
              "reached, and roughly when. That is enough for us to identify the client and " +
              "the call.",
            "For a billing complaint: the invoice number or payment reference.",
            "For a rights request: the phone number or email address the data is held " +
              "against.",
            "How to reach you back.",
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "We will verify who you are before acting on a rights request",
          text:
            "Handing someone else's call records to a stranger who asked confidently is " +
            "itself a breach, so an access or erasure request is verified before it is " +
            "acted on. Verification is proportionate — usually demonstrating control of " +
            "the number or the email in question. We will not ask you to send us a copy of " +
            "an identity document, and you should not send one.",
        },
      ],
    },
    {
      id: "callers",
      heading: "4. If an AI agent called you, or you called one",
      blocks: [
        {
          kind: "para",
          text:
            "Calevate supplies the technology; the business you were dealing with decides " +
            "who is called and what is recorded. In the language of the law they are the " +
            "Data Fiduciary and we are their Data Processor, which means your rights are " +
            "exercised against them and we cannot erase their records on your instruction " +
            "alone.",
        },
        {
          kind: "para",
          text: "That said, you are not required to work out which business it was:",
        },
        {
          kind: "list",
          ordered: true,
          items: [
            "Write to {{GRIEVANCE_OFFICER_EMAIL}} with the number that called you and " +
              "roughly when.",
            "We identify the client, pass your request to them, and tell you that we have " +
              "and who they are.",
            "If you asked not to be called again, that takes effect immediately regardless " +
              "of anything else — we add the number to the client's suppression list " +
              "ourselves, and it applies before the next dispatch cycle.",
            "If the client does not respond to you, tell us. We will chase them, and " +
              "persistent failure to honour data rights is a breach of our terms with " +
              "them that we can act on.",
          ],
        },
      ],
    },
    {
      id: "escalation",
      heading: "5. If we do not put it right",
      blocks: [
        {
          kind: "para",
          text:
            "Coming to us first is not a condition of any of these, and complaining to us " +
            "does not stop you doing any of them at the same time.",
        },
        {
          kind: "definitions",
          items: [
            {
              term: "Personal data",
              detail:
                "Complain to the Data Protection Board of India. The Digital Personal " +
                "Data Protection Act 2023 gives a data principal the right to complain to " +
                "the Board about a Data Fiduciary or a Consent Manager — and we would " +
                "rather tell you the timing than let you find it out at the Board's door: " +
                "that right sits in the part of the Act commencing on 13 May 2027, though " +
                "the Board itself has existed since November 2025. Until that date a " +
                "complaint about personal data is made under the Information Technology " +
                "Act 2000 and the 2011 rules made under it, which is exactly why the " +
                "Grievance Officer named above is the first step and why we publish their " +
                "name rather than a role title.",
            },
            {
              term: "Unsolicited or unlawful commercial calls",
              detail:
                "Complain to your own telephone operator, who runs a statutory complaint " +
                "channel for unsolicited commercial communications, and to the Telecom " +
                "Regulatory Authority of India. You can do this whether or not you know " +
                "which business called you — the operator can trace it.",
            },
            {
              term: "Consumer disputes",
              detail:
                "Approach the District, State or National Consumer Disputes Redressal " +
                "Commission according to the value of the claim, or the National Consumer " +
                "Helpline. The arbitration clause in our Terms does not take away a " +
                "consumer's statutory route.",
            },
            {
              term: "Contract disputes with a business client",
              detail:
                "Clause 16 of the Terms of Service applies — negotiation, then arbitration " +
                "seated at {{JURISDICTION_CITY}}.",
            },
          ],
        },
      ],
    },
    {
      id: "record",
      heading: "6. How we handle what you send us",
      blocks: [
        {
          kind: "para",
          text:
            "A complaint is recorded with its outcome so that we can see patterns rather " +
            "than treating each one as an isolated event. The personal data in your " +
            "complaint is used to investigate and answer it and for nothing else, and it " +
            "is retained for as long as we need it to demonstrate that we dealt with it " +
            "properly. The Privacy Policy governs it.",
        },
      ],
    },
  ],
};
