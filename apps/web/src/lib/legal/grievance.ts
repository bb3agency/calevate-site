import type { LegalDocument } from "./types";

/**
 * Grievance redressal — one page, three regimes, and the timetables are different.
 *
 * The reason this is a document rather than a paragraph at the bottom of the privacy
 * notice: three separate instruments each require a published contact and each sets its
 * own clock, and they do not agree. Rule 5(9) of the SPDI Rules 2011 says one month and is
 * the operative privacy rule TODAY. Rule 4 of the Consumer Protection (E-Commerce)
 * Rules 2020 says acknowledge in 48 hours, redress in one month — but only of an
 * "e-commerce entity", and nobody has analysed whether B2B AI-voice SaaS is one, so §2
 * prints those two limits with an "if" and says why (27 Aug 2026). The sub-rule NUMBER
 * is deliberately not published either: three secondary readings reachable from this
 * environment number it 4(4), 4(5) and 4(6), the primary text is egress-blocked here, and
 * a citation nobody has opened is exactly the class of claim hard rule 11 forbids
 * restating. Rule 14(3) of the DPDP
 * Rules 2025 says publish your timeline and in no case exceed ninety days; its
 * substantive commencement is EIGHTEEN MONTHS after the DPDP Rules were published in the
 * gazette — mid-May 2027, and the exact day is not printed because this repository's own
 * sources give the publication date as 13 or 14 November 2025 and nobody has reached the
 * gazette (docs/LEGAL-SURFACE.md §9, item 9).
 *
 * Publishing the LONGEST of the three would be lawful and would be a worse product. So the
 * page states one commitment — the shortest — and shows the statutory outer limits beside
 * it, so a reader can see both what we promise and what we could get away with.
 *
 * ## Rewritten 26 August 2026: there is no company behind this page
 *
 * The founder confirmed it, and `docs/legal/LEGAL-OPS-PLAYBOOK.md` settles the shape:
 * `:16` — Calevate is a "product / trade name, not a separate company"; `:82` — "You and
 * the business are the same legal person". This page had been written as though a
 * complainant were writing to an organisation with desks in it. Three consequences, and
 * each is a sentence a complainant can act on rather than an internal detail:
 *
 * 1. **The three published contacts are not three desks.** Three instruments each demand
 *    a published contact, so three rows stay — but a page implying three desks would send
 *    a complainant hunting for the right one, and there is no wrong one to pick. The
 *    prose says that much and stops there: how many people read those mailboxes is the
 *    business's own composition, it is owed to nobody, and a complainant's next move does
 *    not change with the answer (26 Aug 2026 — the founder's instruction that these
 *    documents stop narrating our staffing and scale).
 * 2. **There is nothing above the person named.** No board, no head office, no second
 *    tier. That is worth SAYING, because the ordinary next move when a company's
 *    grievance officer does not answer is to escalate internally, and here that move does
 *    not exist — section 5 is the real one and it is external.
 * 3. **`{{GRIEVANCE_OFFICER_DESIGNATION}}` cannot be "Director".** Nobody holds that
 *    office. `placeholders.ts` records "Proprietor" as the designation for this shape.
 *
 * ## Being a sole proprietorship is not an exemption, and the page says why
 *
 * The obvious reading of "we are a sole proprietor" is that the corporate data-security
 * duties do not apply. They do. Section 43A of the Information Technology Act 2000 — the
 * section the SPDI Rules 2011 are made under, and the operative privacy law until 13 May
 * 2027 — carries its own Explanation defining "body corporate" as "any company and
 * includes a firm, sole proprietorship or other association of individuals engaged in
 * commercial or professional activities". ⚠ EVIDENCE CLASS: the bare-act text was read on
 * 26 Aug 2026 through a web search that returned the Explanation verbatim from bare-act
 * sources; `indiacode.nic.in`, `indiankanoon.org` and `meity.gov.in` are ALL egress-blocked
 * from this environment, so the section could not be opened directly and this is a
 * REPORTED reading rather than a page a session opened. It is stated in the prose because
 * a reader who concludes the opposite concludes it in our favour, which is the direction
 * this document set is written against — but re-verify it against the instrument before
 * relying on it commercially, per hard rule 11.
 *
 * ## What the redressal process actually is, said out loud (DP-8)
 *
 * `docs/LEGAL-SURFACE.md` DP-8: "There is no grievance intake surface, no ticket record
 * and no clock in the product — it is an email address. What closes it: either a mailbox +
 * a written procedure (sufficient at this size), or a `grievances` table. Say which; do
 * not leave it implied." Section 2's second callout says which, in the half that is the
 * reader's business: there is no complaint form, no ticket queue and nothing to sign in
 * to and watch, so a reader cannot infer a tracking system from a published timetable.
 * What it no longer narrates is the machinery behind the mailbox — who monitors it and
 * which steps are done by hand is our composition, not the complainant's remedy, and the
 * commitments in the middle column stand whatever it is (26 Aug 2026).
 *
 * ## There is no postal channel, and the address is still published
 *
 * Section 1 offered "By post — {{LEGAL_ENTITY_NAME}}, {{REGISTERED_ADDRESS}}" as a way to
 * complain. No postal correspondence is serviced, so that was a channel we would not have
 * answered on a page whose whole subject is answering. The channel is gone and the
 * ADDRESS is not: it is still printed, as the identification item the Consumer Protection
 * (E-Commerce) Rules 2020 want displayed and the address a legal notice is served at, and
 * `placeholders.ts` carries the same distinction so the next editor does not put the
 * postal line back.
 *
 * ## The name is still a blank, and that is an unmet obligation rather than a formatting gap
 *
 * `docs/LEGAL-SURFACE.md` S-2 puts it exactly: "A placeholder is not a designation — this
 * is UNMET until a person is appointed", and F-9 records it as EXTERNAL and the cheapest
 * unmet obligation on the page. Nothing here may invent one (`placeholders.ts:1-14`). The
 * appointment must be recorded in writing before the pending-review banner comes off.
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
            "Three published contacts, because three different instruments each require " +
            "one. They are not three desks, and Calevate is a product operated by " +
            "{{LEGAL_ENTITY_NAME}}, {{ENTITY_FORM}}. Pick whichever fits and do not " +
            "spend a minute choosing — there is no wrong one, and no complaint is turned " +
            "away for arriving at the wrong address.",
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
                "Procedures and Sensitive Personal Data or Information) Rules 2011 — " +
                "which does require this of us. Rule 4 of the Consumer Protection " +
                "(E-Commerce) Rules 2020 requires the same of an \"e-commerce entity\"; " +
                "whether that description reaches a business like ours is not settled, " +
                "and section 2 says so rather than assuming it either way.",
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
            "By telephone: {{CONTACT_PHONE}}. We do not operate a postal complaints " +
            "channel — the mailboxes above and that number are how a complaint reaches " +
            "us, and we would rather say so than offer a channel we do not service. " +
            "The supplier's principal place of business is {{REGISTERED_ADDRESS}}; " +
            "it identifies who you are dealing with and is where a legal notice is " +
            "served, not a place to send a complaint to.",
        },
        {
          kind: "callout",
          tone: "note",
          title: "There is no internal escalation above the person named here",
          text:
            "Worth knowing before you plan your next move. The usual escalation when a " +
            "company's grievance officer does not answer is to write to someone more " +
            "senior. There is no such tier here: the supplier is a sole proprietorship, " +
            "so the person named above is the business rather than a first level of it. " +
            "If we do not put your complaint right, the next step is not further up this " +
            "page; it is section 5, and section 5 is outside Calevate altogether.",
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
              "48 hours, under rule 4 of the Consumer Protection (E-Commerce) Rules " +
                "2020, if those Rules reach us — see the note below.",
            ],
            [
              "Substantive reply",
              "Within 15 business days for most complaints.",
              "One month (SPDI Rules 2011, rule 5(9) — this one does bind us), and the " +
                "same month under rule 4 of the Consumer Protection (E-Commerce) Rules " +
                "2020 if those Rules reach us.",
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
            "The Digital Personal Data Protection Rules 2025 commence in phases, and " +
            "rule 1 of those Rules sets the phases by counting from the day they were " +
            "published in the Official Gazette rather than by naming dates — the Data " +
            "Protection Board framework on publication, the Consent Manager provisions " +
            "twelve months later, and the substantive obligations including grievance " +
            "redressal eighteen months later. Eighteen months from a November 2025 " +
            "publication lands in the middle of May 2027. We do not print the exact day, " +
            "because we have not read the gazette copy ourselves and the sources we have " +
            "read disagree by one day about when it was published; the derived date " +
            "moves with it and nothing on this page turns on which. Until then the 2011 " +
            "rules under the Information Technology Act 2000 are the operative privacy " +
            "law and their one-month clock is the binding one. We are not waiting for " +
            "2027 to honour any of it, and the commitments in the middle column apply " +
            "now.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "One of those outer limits may not actually apply to us, and we have not settled it",
          text:
            "The E-Commerce Rules limits above are printed with an \"if\", and the " +
            "honest reason is that nobody has done the analysis. Those Rules bind an " +
            "\"e-commerce entity\" and were written for platforms through which " +
            "consumers buy goods and services. Calevate sells a subscription to " +
            "businesses over the internet; whether that makes it an e-commerce entity " +
            "for the purpose of those Rules is a real question and not one we are going " +
            "to answer in our own favour, in either direction, in a document about how " +
            "we handle your complaint. It is on the list for the advocate whose review " +
            "these documents are waiting on. Nothing about the middle column depends on " +
            "the answer: the commitments there are ours, they are shorter than every " +
            "limit in the right-hand column, and rule 5(9) of the 2011 rules — which " +
            "does bind us — already sets a one-month clock on its own.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "Complaints come to a mailbox — there is no form and no ticket queue",
          text:
            "A published timetable can read like a support portal, so: a complaint is " +
            "made by writing to one of the addresses in section 1. There is no complaint " +
            "form in the product, no ticket queue, and nothing you can sign in to and " +
            "watch. What you get instead is the reference number in your " +
            "acknowledgement, quoted in every message about your complaint after that, " +
            "which is what makes the commitments above checkable by you rather than by " +
            "us. If a reply is late, chase it — and section 5 does not require you to " +
            "wait for us either way.",
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
                "rather tell you the timing than let you find it out at the Board's " +
                "door: that right sits in the part of the Act that commences eighteen " +
                "months after the DPDP Rules 2025 were published, which is the middle of " +
                "May 2027 (section 2 explains why we give it as a period), though the " +
                "Board itself has existed since November 2025. Until then a complaint " +
                "about personal data is made under the Information Technology Act 2000 " +
                "and the 2011 rules made under it, which is exactly why the Grievance " +
                "Officer named above is the first step and why we publish their name " +
                "rather than a role title. One thing that changes nothing, stated " +
                "because it looks as though it should: the 2011 rules bind a \"body " +
                "corporate\", and section 43A of that Act — the section they are made " +
                "under — defines the term in its own Explanation as \"any company and " +
                "includes a firm, sole proprietorship or other association of " +
                "individuals engaged in commercial or professional activities\". " +
                "Calevate being a sole proprietorship rather than a company is therefore " +
                "not an exemption from anything on this page, and we would rather you " +
                "read that from us than have to look it up. Section 43A itself is not " +
                "where this page's commitments come from and we are not going to imply " +
                "that it is: all it does on its own is make a body corporate liable to " +
                "compensate someone where it was negligent in maintaining reasonable " +
                "security practices for SENSITIVE personal data and that negligence " +
                "caused a wrongful loss or a wrongful gain. It is a remedy for one kind " +
                "of failure, not the source of a duty to answer you.",
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
            "A complaint is recorded with its outcome, so that we can see patterns " +
            "rather than treating each one as an isolated event. The personal data in " +
            "your complaint is used to investigate and answer it and for nothing else, " +
            "and it is retained for as long as we need it to demonstrate that we dealt " +
            "with it " +
            "properly. The Privacy Policy governs it.",
        },
      ],
    },
  ],
};
