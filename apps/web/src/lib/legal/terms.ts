import type { LegalDocument } from "./types";

/**
 * The Terms of Service.
 *
 * Written from an Indian supplier's position — Indian governing law, an Indian seat, GST
 * on the invoice, the telecom obligations allocated to the client who actually holds the
 * registration — rather than adapted from a US SaaS template with the state name swapped.
 *
 * Two clauses are deliberately narrower than a template's would be, because the honest
 * version is narrower: clause 12 promises no availability target (nothing in this product
 * measures one, and the marketing page declines to state one for the same reason), and
 * clause 15 disclaims the accuracy of what a language model extracts rather than warranting
 * it. Overpromising in a contract is the one drafting error a client can actually enforce.
 */
export const TERMS_OF_SERVICE: LegalDocument = {
  slug: "terms",
  title: "Terms of Service",
  shortTitle: "Terms of Service",
  summary:
    "The agreement between Calevate and the business that uses it — what we supply, " +
    "what you are responsible for, what is owed, and what happens when it goes wrong.",
  appliesTo:
    "Every business with a Calevate account, and everyone who signs in to one. If you " +
    "are accepting on behalf of a business, you confirm you may bind it.",
  sections: [
    {
      id: "parties",
      heading: "1. Parties and acceptance",
      blocks: [
        {
          kind: "para",
          text:
            "These terms are between {{LEGAL_ENTITY_NAME}} (registration number " +
            "{{ENTITY_REGISTRATION_NUMBER}}, registered at {{REGISTERED_ADDRESS}}) — " +
            '"Calevate", "we", "us" — and the business that opens or uses an account — ' +
            '"you", "the Client". They apply from the moment you create an account, sign ' +
            "an order form, or use the service, whichever is earliest.",
        },
        {
          kind: "para",
          text:
            "These terms incorporate the Acceptable Use Policy, the Data Processing " +
            "Addendum, the sub-processor list, the Refund and Cancellation Policy and the " +
            "Privacy Policy. Where a signed order form conflicts with these terms, the " +
            "order form governs for the commercial matters it covers and these terms " +
            "govern everything else. Where the Data Processing Addendum conflicts with " +
            "these terms on the handling of personal data, the Addendum governs.",
        },
      ],
    },
    {
      id: "definitions",
      heading: "2. Definitions",
      blocks: [
        {
          kind: "definitions",
          items: [
            {
              term: "Agent",
              detail: "One configured AI telephone assistant belonging to your account.",
            },
            {
              term: "Caller Data",
              detail:
                "Personal data about the people your agents speak to: their number, the " +
                "recording, the transcript, and whatever your agent was configured to " +
                "extract. You are the Data Fiduciary for it; we are your Data Processor.",
            },
            {
              term: "Client Data",
              detail:
                "Everything you put into the account that is not Caller Data — your " +
                "business facts, prompts, knowledge content, uploaded lists and settings.",
            },
            {
              term: "PE and TM",
              detail:
                "Principal Entity and Telemarketer, as registered under India's " +
                "commercial-communications framework. You are the PE. We are the TM " +
                "linked to your registration.",
            },
            {
              term: "Engine",
              detail:
                "The third-party voice platform that runs the live call. Named on the " +
                "sub-processor list.",
            },
          ],
        },
      ],
    },
    {
      id: "service",
      heading: "3. What we supply",
      blocks: [
        {
          kind: "para",
          text:
            "A hosted service that answers your incoming telephone calls with an AI " +
            "agent, places outgoing calls on your instruction where your registrations " +
            "permit it, records and transcribes those calls, extracts the fields you " +
            "define into a lead record, and delivers them to your dashboard and, if you " +
            "connect one, to your own system.",
        },
        {
          kind: "para",
          text:
            "We may improve the service, and we may change how a feature works. We will " +
            "not remove a feature you rely on, or make a change that materially reduces " +
            "the service, without at least 30 days' notice by email to the account owner.",
        },
        {
          kind: "callout",
          tone: "note",
          title: "What we do not supply",
          text:
            "We are not a telecommunications licensee and we do not provide the " +
            "telecommunications service itself. We are not your legal, tax, medical or " +
            "financial adviser, and nothing an agent says on your behalf is advice from " +
            "us. We do not obtain your Principal Entity registration for you as a legal " +
            "guarantee — we run the process on your instructions and the registration is " +
            "granted, or not, by the access provider.",
        },
      ],
    },
    {
      id: "account",
      heading: "4. Your account",
      blocks: [
        {
          kind: "list",
          items: [
            "Calevate is for business use. You confirm you are a business, or a person " +
              "acting for the purposes of a business, and that you are 18 or over.",
            "You are responsible for everyone you give access to, and for keeping " +
              "credentials safe. Tell us at once if you think an account has been " +
              "compromised.",
            "The information you give us must be accurate — your legal name, your GSTIN " +
              "and place of supply for invoicing, and the documents you produce for " +
              "identity verification. Getting the GST details wrong means the tax on your " +
              "invoice is charged under the wrong head and you cannot claim it.",
            "You must complete identity verification where the Acceptable Use Policy " +
              "requires it, and keep your registrations current. A registration that " +
              "lapses stops your outbound calling until it is restored.",
          ],
        },
      ],
    },
    {
      id: "your-responsibilities",
      heading: "5. What you are responsible for",
      blocks: [
        {
          kind: "callout",
          tone: "warning",
          title: "The compliance obligations are yours, and this clause is why",
          text:
            "You are the Principal Entity for every call and the Data Fiduciary for every " +
            "conversation. You decide who is called, what the agent says, what is written " +
            "down and what happens to it afterwards. The law attaches the duty to the " +
            "party that makes those decisions, and this agreement does not move it.",
        },
        {
          kind: "list",
          items: [
            "Complying with the Acceptable Use Policy in full, including the calling " +
              "hours, the number series, the suppression checks and the consent provenance " +
              "rules.",
            "Having a lawful basis for every number you upload and every call you ask us " +
              "to place, and being able to evidence it.",
            "Giving the people you call whatever notice the law requires — including any " +
              "notice that the call is being recorded, and any notice that they are " +
              "speaking to an AI. Those announcements are settings on your agents and you " +
              "decide them. What your agents always do, whatever you set, is answer " +
              "truthfully when a caller asks; you may not configure around that.",
            "Publishing your own privacy notice to the people you call, telling them what " +
              "you collect and why, and handling their requests when they come to you.",
            "The content you put in: prompts, knowledge documents, extraction schemas and " +
              "uploaded lists. You warrant you have the rights to it, and you keep the " +
              "rights to it.",
            "Reviewing what your agent says. It is a language model. It will occasionally " +
              "be wrong, and it speaks in your name.",
          ],
        },
      ],
    },
    {
      id: "fees",
      heading: "6. Fees, tax and payment",
      subsections: [
        {
          id: "charges",
          heading: "6.1 What you pay",
          blocks: [
            {
              kind: "para",
              text:
                "Managed accounts pay what the signed order form says: a one-off setup " +
                "fee, a monthly fee including a stated number of minutes, and a per-minute " +
                "rate for minutes over that. Self-serve accounts pay in advance by topping " +
                "up a credit balance, which is drawn down as calls are metered. All prices " +
                "are in Indian Rupees.",
            },
            {
              kind: "para",
              text:
                "A change to your commercial terms takes effect from the date agreed and " +
                "does not re-price a month you have already been billed for. Your " +
                "historical invoices are re-derivable and are not rewritten.",
            },
          ],
        },
        {
          id: "gst",
          heading: "6.2 GST and invoicing",
          blocks: [
            {
              kind: "para",
              text:
                "Unless the order form says otherwise, prices are exclusive of GST and GST " +
                "is charged in addition at the applicable rate — currently 18% on this " +
                "class of supply. We issue an invoice for each billing month carrying the " +
                "particulars rule 46 of the CGST Rules requires: our identity and our " +
                "GSTIN {{GSTIN}}, your identity and GSTIN, the serial number and date, " +
                "the SAC for the supply, the taxable value, the rate, the tax charged, " +
                "and the place of supply.",
            },
            {
              kind: "para",
              text:
                "Whether you are charged IGST or CGST plus SGST depends on the place of " +
                "supply, which for a registered recipient is your location. Give us your " +
                "correct GSTIN and state: the document says which head it charged, because " +
                "you cannot claim tax charged under the wrong one.",
            },
            {
              kind: "callout",
              tone: "note",
              title: "Before registration",
              text:
                "Until {{LEGAL_ENTITY_NAME}} holds GST registration, no tax is collected " +
                "and the billing document is issued as a proforma rather than as a tax " +
                "invoice. Section 32 of the CGST Act prohibits an unregistered person from " +
                "collecting tax, and the product refuses to render a tax invoice without a " +
                "supplier GSTIN. A proforma is not a document you can claim input credit " +
                "against.",
            },
            {
              kind: "para",
              text:
                "A correction to an issued invoice is made by a credit or debit note under " +
                "section 34 of the CGST Act referencing the original, never by silently " +
                "re-rendering it.",
            },
          ],
        },
        {
          id: "payment",
          heading: "6.3 Payment, and what happens if you do not",
          blocks: [
            {
              kind: "list",
              items: [
                "Invoices are payable within the period stated on them. Card, UPI and " +
                  "netbanking payments are handled by a payment gateway; we never see your " +
                  "card number.",
                "Third-party charges we incur for you — telecom minutes, number rentals, " +
                  "registration fees — are passed through and are payable whether or not " +
                  "you are satisfied with the outcome of the calls.",
                "If an invoice is overdue we may suspend outbound dialling after telling " +
                  "you. We will keep answering your incoming calls where we reasonably can, " +
                  "because cutting those off punishes your customers.",
                "Your account has spending ceilings — one we set and one you can set for " +
                  "yourself. The lower of the two applies. Reaching a ceiling stops " +
                  "outbound dialling; it is a safety limit, not a billing dispute.",
              ],
            },
            {
              kind: "para",
              text: "Refunds and cancellation are dealt with in the Refund and Cancellation Policy.",
            },
          ],
        },
      ],
    },
    {
      id: "data",
      heading: "7. Data protection and confidentiality",
      blocks: [
        {
          kind: "para",
          text:
            "The Data Processing Addendum governs our handling of Caller Data and forms " +
            "part of this agreement. In summary: you are the Data Fiduciary, we are your " +
            "Data Processor, we act on your documented instructions, we do not use your " +
            "callers' data for our own purposes or to train any model, and the " +
            "sub-processors we use are named.",
        },
        {
          kind: "para",
          text:
            "Each of us will keep the other's confidential information confidential, use " +
            "it only for this agreement, and protect it at least as carefully as our own. " +
            "This does not apply to information that is public through no fault of the " +
            "recipient, was already known, is independently developed, or must be " +
            "disclosed by law — and where the law compels disclosure, the disclosing party " +
            "will tell the other unless prohibited.",
        },
      ],
    },
    {
      id: "ip",
      heading: "8. Intellectual property",
      blocks: [
        {
          kind: "list",
          items: [
            "We own the platform, the software, the documentation and everything we " +
              "develop. You get a non-exclusive, non-transferable right to use it for your " +
              "own business while this agreement lasts.",
            "You own your Client Data and your Caller Data. You grant us only the licence " +
              "we need to run the service for you, and it ends when the agreement does, " +
              "subject to clause 14.",
            "Neither of us may use the other's name or marks publicly without written " +
              "agreement. We will not name you as a customer without asking.",
            "If you send us feedback we may use it freely and without owing you anything. " +
              "Feedback is not Confidential Information, so do not put anything " +
              "confidential in it.",
          ],
        },
      ],
    },
    {
      id: "third-parties",
      heading: "9. Third parties in the path",
      blocks: [
        {
          kind: "para",
          text:
            "The service depends on a voice platform, speech and language model providers, " +
            "telecom operators, a payment gateway and infrastructure suppliers. They are " +
            "named on the sub-processor list. We choose them with care and we are " +
            "responsible to you for their acts in performing the service, but we do not " +
            "control their networks and an outage at one of them may interrupt the service. " +
            "Clause 12 says what we do and do not promise about that.",
        },
        {
          kind: "para",
          text:
            "Where you connect a service of your own — your CRM endpoint, your Google " +
            "Sheet, your Meta lead form — that connection is yours. What happens to data " +
            "once it reaches your system is your responsibility.",
        },
      ],
    },
    {
      id: "suspension",
      heading: "10. Suspension",
      blocks: [
        { kind: "para", text: "We may suspend all or part of the service where:" },
        {
          kind: "list",
          items: [
            "you are in breach of the Acceptable Use Policy;",
            "a regulator, an access provider or a court instructs us to;",
            "a registration you rely on lapses, is suspended or is revoked;",
            "there is a security risk, a live risk to the people being called, or a " +
              "runaway cost;",
            "an invoice is overdue and we have told you.",
          ],
        },
        {
          kind: "para",
          text:
            "We will limit a suspension to what is necessary, tell you why, and lift it as " +
            "soon as the cause is resolved. Suspension for your breach does not suspend " +
            "your obligation to pay. Where the emergency is ours or systemic we may halt " +
            "all outbound dialling across the platform at once; you will be told.",
        },
      ],
    },
    {
      id: "term",
      heading: "11. Term and termination",
      blocks: [
        {
          kind: "list",
          items: [
            "A managed engagement runs for the term on the order form and continues " +
              "monthly afterwards. Either party may end it on {{TERMINATION_NOTICE_DAYS}} " +
              "days' written notice, expiring at the end of a billing month.",
            "A self-serve account may be closed by you at any time from the dashboard or " +
              "by writing to {{SUPPORT_EMAIL}}. Unused credit is dealt with in the Refund " +
              "and Cancellation Policy.",
            "Either party may terminate immediately if the other commits a material breach " +
              "and does not remedy it within 30 days of written notice, or becomes " +
              "insolvent.",
            "We may terminate immediately, without a cure period, for a breach of the " +
              "Acceptable Use Policy that exposes people being called to harm or exposes " +
              "us or another client to regulatory enforcement.",
          ],
        },
        {
          kind: "para",
          text:
            "On termination your access ends, outbound dialling stops, and clause 14 " +
            "governs your data. Clauses 7, 8, 12, 13, 14, 15 and 17 survive.",
        },
      ],
    },
    {
      id: "availability",
      heading: "12. Availability — and what we do not promise",
      blocks: [
        {
          kind: "callout",
          tone: "warning",
          title: "There is no service level agreement",
          text:
            "We do not commit to an uptime percentage, a latency figure, an answer rate " +
            "or a transcription accuracy figure, and no such figure appears anywhere in " +
            "the product or on the website. Nothing in this system measures one, and a " +
            "number in a contract that nothing measures is a promise nobody can keep or " +
            "check. If your business needs a contractual service level, tell us before you " +
            "sign and we will negotiate one on the order form or tell you we cannot.",
        },
        {
          kind: "para",
          text:
            "What we do commit to: running the service with reasonable skill and care, " +
            "giving reasonable notice of planned maintenance where we can, and telling you " +
            "when something has gone wrong that affects you.",
        },
      ],
    },
    {
      id: "warranties",
      heading: "13. Warranties and disclaimers",
      blocks: [
        {
          kind: "para",
          text:
            "Each party warrants that it may enter into this agreement and will comply " +
            "with applicable law in performing it. We warrant that we will perform the " +
            "service with reasonable skill and care.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "About what the AI produces",
          text:
            "An agent's speech, its summaries, the fields it extracts, the sentiment it " +
            "labels and the moments it marks are generated by language models. They will " +
            "sometimes be wrong, incomplete or misleading, and quality in any particular " +
            "language or accent has not been independently measured. We do not warrant " +
            "their accuracy. Do not rely on them for a decision that matters without a " +
            "human checking — and never for a medical, legal, financial or safety " +
            "decision. You are responsible for what your agent says in your name.",
        },
        {
          kind: "para",
          text:
            "Beyond what is stated here, and to the extent the law allows, all other " +
            "warranties, conditions and terms implied by statute or common law are " +
            "excluded. Nothing in this agreement excludes or limits any liability that " +
            "cannot lawfully be excluded or limited, including for fraud, for fraudulent " +
            "misrepresentation, or for death or personal injury caused by negligence.",
        },
      ],
    },
    {
      id: "liability",
      heading: "14. Liability, indemnity, and your data on exit",
      subsections: [
        {
          id: "cap",
          heading: "14.1 Limitation of liability",
          blocks: [
            {
              kind: "para",
              text:
                "Subject to the sentence about non-excludable liability in clause 13, and " +
                "for each party: neither is liable to the other for loss of profit, loss " +
                "of revenue, loss of anticipated savings, loss of business or goodwill, or " +
                "for indirect or consequential loss, however arising.",
            },
            {
              kind: "para",
              text:
                "Each party's total aggregate liability arising out of or in connection " +
                "with this agreement in any twelve-month period is limited to the total " +
                "fees paid or payable by you to us in the twelve months before the event " +
                "giving rise to the claim.",
            },
            {
              kind: "para",
              text:
                "That cap does not apply to your obligation to pay fees, or to your " +
                "liability under clause 14.2.",
            },
            {
              kind: "callout",
              tone: "note",
              title: "Why the cap is drawn this way",
              text:
                "The consequences that could dwarf it — a telecom penalty, a " +
                "disconnection, a regulatory fine for calling somebody you had no basis to " +
                "call — arise from decisions only you can make: who is on the list, what " +
                "the agent says, whether the consent exists. Carrying an uncapped share of " +
                "a risk we cannot control is not something a supplier at this price can " +
                "do, and pretending otherwise in a contract would be worse than saying so.",
            },
          ],
        },
        {
          id: "indemnity",
          heading: "14.2 Indemnity",
          blocks: [
            {
              kind: "para",
              text:
                "You will indemnify us against claims, penalties, fines and reasonable " +
                "costs arising from: a breach by you of the Acceptable Use Policy; calls " +
                "placed to people for whom you had no lawful basis; content you supplied " +
                "for an agent to say or answer from; a failure by you to give a notice or " +
                "obtain a consent that the law required of you as Data Fiduciary or " +
                "Principal Entity; and any claim that your content infringes a third " +
                "party's rights.",
            },
            {
              kind: "para",
              text:
                "We will indemnify you against a third-party claim that the Calevate " +
                "platform itself, used as we intended, infringes that party's intellectual " +
                "property rights in India.",
            },
            {
              kind: "para",
              text:
                "The indemnified party must notify the other promptly, not admit " +
                "liability, and allow the indemnifying party to conduct the defence with " +
                "reasonable co-operation.",
            },
          ],
        },
        {
          id: "exit",
          heading: "14.3 Your data when the agreement ends",
          blocks: [
            {
              kind: "para",
              text:
                "For {{DATA_RETURN_WINDOW_DAYS}} days after termination you may export " +
                "your leads, calls and transcripts through the product. After that window " +
                "we will erase your data on your written instruction, and we will do it on " +
                "our own initiative if you give no instruction.",
            },
            {
              kind: "para",
              text:
                "Erasure at the end of an engagement is a defined process with its own " +
                "certificate, and the certificate enumerates what it does not remove " +
                "rather than leaving you to infer it: the append-only consent, billing and " +
                "audit ledgers, do-not-call suppressions, your own user accounts, copies " +
                "held by the voice platform, and knowledge content you uploaded. Those are " +
                "listed for the reasons the Privacy Policy gives, and are retained no " +
                "longer than the law requires.",
            },
          ],
        },
      ],
    },
    {
      id: "general",
      heading: "15. General",
      blocks: [
        {
          kind: "list",
          items: [
            "Force majeure: neither party is liable for a failure caused by something " +
              "beyond its reasonable control, including a telecom or cloud outage, a " +
              "regulatory direction, or a network-level block. A party affected must tell " +
              "the other and mitigate. This does not excuse paying money already owed.",
            "Assignment: neither party may assign without the other's written consent, " +
              "except that either may assign to a successor of its business on notice.",
            "No partnership: nothing here makes either party the other's agent, partner " +
              "or employee, except that we act as your registered Telemarketer, which is " +
              "the specific relationship the telecom framework defines.",
            "Notices: to you at the email on your account; to us at {{SUPPORT_EMAIL}} " +
              "with a copy by post to {{REGISTERED_ADDRESS}}. A notice terminating this " +
              "agreement must also be sent by post.",
            "Changes: we may amend these terms on 30 days' notice by email to the account " +
              "owner. If you do not accept a change you may terminate before it takes " +
              "effect, and we will refund any prepaid, unused fees for the period after " +
              "termination.",
            "Severability: if a clause is unenforceable, the rest stands.",
            "Waiver: not enforcing a right once does not waive it.",
            "Entire agreement: these terms and the documents they incorporate are the " +
              "whole agreement, and replace anything said before. Neither party relies on " +
              "any statement not written here — which does not limit liability for fraud.",
          ],
        },
      ],
    },
    {
      id: "law",
      heading: "16. Governing law and disputes",
      blocks: [
        {
          kind: "para",
          text:
            "This agreement, and any dispute arising out of or in connection with it " +
            "(including non-contractual disputes), is governed by the laws of India.",
        },
        {
          kind: "list",
          ordered: true,
          items: [
            "Talk first. Either party may raise a dispute by written notice, and both will " +
              "try in good faith to resolve it within 30 days. This step is not optional " +
              "but it does not prevent either party seeking urgent interim relief.",
            "If that fails, the dispute is referred to arbitration by a sole arbitrator " +
              "under the Arbitration and Conciliation Act 1996. The seat and venue is " +
              "{{JURISDICTION_CITY}}, India. The language is English. The award is final " +
              "and binding. Each party bears its own costs unless the arbitrator directs " +
              "otherwise.",
            "The courts at {{JURISDICTION_CITY}} have exclusive jurisdiction over anything " +
              "not within the arbitration clause, including interim relief and enforcement " +
              "of an award.",
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "If you are a consumer",
          text:
            "Calevate is sold for business use, and these terms are written for a " +
            "business counterparty. If you nonetheless have rights as a consumer under " +
            "the Consumer Protection Act 2019 — a sole proprietor buying to earn a " +
            "livelihood by self-employment may — nothing here takes them away, the " +
            "arbitration clause does not stop you approaching a consumer commission, and " +
            "the grievance page tells you who to contact and by when we must reply.",
        },
      ],
    },
    {
      id: "contact",
      heading: "17. Contact",
      blocks: [
        {
          kind: "definitions",
          items: [
            { term: "Account and billing", detail: "{{SUPPORT_EMAIL}}, {{CONTACT_PHONE}}" },
            {
              term: "Complaints",
              detail:
                "{{GRIEVANCE_OFFICER_NAME}}, {{GRIEVANCE_OFFICER_DESIGNATION}}, " +
                "{{GRIEVANCE_OFFICER_EMAIL}}",
            },
            { term: "Data protection", detail: "{{DATA_PROTECTION_CONTACT_EMAIL}}" },
            { term: "Security", detail: "{{SECURITY_CONTACT_EMAIL}}" },
            { term: "By post", detail: "{{LEGAL_ENTITY_NAME}}, {{REGISTERED_ADDRESS}}" },
          ],
        },
      ],
    },
  ],
};
