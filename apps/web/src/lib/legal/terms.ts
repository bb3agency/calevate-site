import type { LegalDocument } from "./types";

/**
 * The Terms of Service.
 *
 * Written from an Indian supplier's position — Indian governing law, an Indian seat, the
 * tax position this supplier is actually in, the telecom obligations allocated to the
 * client who actually holds the registration — rather than adapted from a US SaaS
 * template with the state name swapped.
 *
 * ## Clause 1 IDENTIFIES the supplier and says nothing about its legal form
 *
 * This document used to open with a "registration number" that a reader would take for a
 * CIN and a "registered office" that only a company has — false, and corrected in August
 * 2026 by drafting the opposite: a parties clause that named the form and two callouts
 * that explained it ("why it is not a company", "the cap is a contractual limit, not a
 * corporate shield"). Both are gone as of 2 September 2026, on the founder's decision.
 *
 * The reason is register, not law. Clause 1 now carries the three items a supplier is
 * actually required to display — name, registration number, principal place of business
 * (Consumer Protection (E-Commerce) Rules 2020, rule 4) — and stops. It asserts no legal
 * form in either direction, which is what most commercial contracts do; a contract that
 * narrates its own author's constitution reads as a draft, and the narration was doing no
 * work for the client that the clauses do not already do. Clause 14.1 still says what the
 * cap IS and what it does not cover, which is the operative part. What must never appear
 * here is the opposite claim — an incorporation, a CIN, a "registered office", a director
 * — because that would be a false statement in a contract rather than an omitted one.
 *
 * No insurance position is asserted anywhere either: `docs/legal/LEGAL-OPS-PLAYBOOK.md`
 * `:492` records that cyber/PI cover is optional at this size and is not held, and an
 * insurance sentence in a contract is a promise a counterparty relies on.
 *
 * ## Clause 6.2 is the GST position, and it is a statement rather than a blank
 *
 * It used to print `{{GSTIN}}` — a blank where a number goes, which asserts "we have one
 * and have not typed it in". We are not registered and are not required to be
 * (playbook §4, `:105` and `:115`), so the clause states the position and describes the
 * document the code actually issues: `apps/api/billing/invoice.py` emits
 * `document_type: "proforma"` — a bill of supply in substance — with `gst_inr` zero,
 * `tax_components` empty and `BILL_OF_SUPPLY_TAX_NOTE` in words on its face (CGST s.32,
 * CGST Rule 49). The clause describes THAT document, including the `estimated_*` figures
 * the same function emits, which are marked as an estimate and are never due.
 *
 * Two clauses are deliberately narrower than a template's would be, because the honest
 * version is narrower: clause 12 promises no availability target (nothing in this product
 * measures one, and the marketing page declines to state one for the same reason), and
 * clause 13 disclaims the accuracy of what a language model extracts rather than warranting
 * it. Overpromising in a contract is the one drafting error a client can actually enforce.
 * (That second reference read "clause 15", which is General; nothing checks a clause
 * number, so `tests/legal.test.tsx` now resolves every one in the published set.)
 *
 * ## Model B is the phone-number model, and the Terms carry its points
 *
 * `docs/legal/LEGAL-OPS-PLAYBOOK.md:479-490` lists what the Terms must contain for the
 * model this product uses — the client buys and KYCs the number on their own operator
 * account. Each point is now somewhere a reader can find it: subscriber-of-record and PE
 * warranties in clause 5, purpose-limited consent in the same list, the header/template
 * and subscriber indemnity in clause 14.2, the cap and its uncapped counterpart in
 * clause 14.1, the IP split in clause 8, and number ownership on exit in clause 11.
 * Clause 3 says what we do NOT supply, which under Model B includes the telephone
 * connection itself.
 *
 * Clause 6.1 carries one callout that is not about a fee at all: the model picker
 * D-454 shipped prints a rupee-per-minute figure against each model, and that figure is
 * `billing/rates.py`'s LIST-PRICE COST MODEL — the language leg is BYOK, the engine
 * reports no tokens, and `rates.py` says in as many words that nothing is billing it.
 * A client is charged their plan's overage rate or `self_serve_inr_per_min`
 * (`rates.prepaid_billed_inr`), neither of which moves with the model. A control that
 * shows a price is a control a client reads as a price, so the contract says which one
 * it is rather than leaving the screen to imply it.
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
            "These terms are between {{LEGAL_ENTITY_NAME}} (Udyam registration " +
            "number {{ENTITY_REGISTRATION_NUMBER}}, principal place of business " +
            "{{REGISTERED_ADDRESS}}) — " +
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
        {
          kind: "callout",
          tone: "warning",
          title: "This service is offered in India only",
          text:
            "Calevate is offered to businesses established in India, for calls to " +
            "recipients in India. By using the service you confirm that you are " +
            "established in India and that you will not use it to place calls to numbers " +
            "outside India. We do not currently offer outbound calling to destinations " +
            "outside India and the product refuses to dial a non-Indian number. If your " +
            "needs are outside India, this is not the service for you — tell us and we " +
            "will not open the account.",
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
            "granted, or not, by the access provider. We do not supply the telephone " +
            "number or the telephone connection either, and we do not resell either one. " +
            "You take the connection with an Indian operator in your own name and on your " +
            "own account, you remain the subscriber of record for it, and we operate on " +
            "that account using credentials you issue to us and can withdraw.",
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
            "Your account has two kinds of user, an owner and staff, and what staff may " +
              "do is partly yours to decide. Staff never reach billing, organisation " +
              "settings, unredacted transcripts or unredacted exports. Two things they " +
              "can do are worth knowing about before you invite somebody: they may use " +
              "the in-app assistant, which spends the AI allowance on your account; and " +
              "they may curate the knowledge your agents answer from, but only if you as " +
              "owner switch that on. It is off until you turn it on, and neither staff " +
              "nor anyone at Calevate viewing your account can turn it on for you.",
            "The information you give us must be accurate — your legal name, your GST " +
              "registration details and place of supply if you have them, and the " +
              "documents you produce for identity verification. Today those GST details " +
              "decide only what your billing document says about you, because we charge " +
              "no tax on it; from the day we are registered, wrong details mean the tax " +
              "is charged under the wrong head and you cannot claim it. Clause 6.2 sets " +
              "out our own GST position.",
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
            "Being the subscriber of record for every telephone connection your agents " +
              "use, and the registered Principal Entity for every call placed on it. You " +
              "warrant both, for every number you give us, and you tell us at once if " +
              "either stops being true — a call placed on a connection registered to " +
              "somebody else is a breach of the telecom rules before it is a breach of " +
              "this agreement.",
            "Having a lawful basis for every number you upload and every call you ask us " +
              "to place, and being able to evidence it — including what the person agreed " +
              "to, when, and for what. Consent obtained for one purpose does not " +
              "authorise a campaign about another, consent to be called does not " +
              "authorise a message on another channel, and a number on a suppression list " +
              "is not re-enabled by a later enquiry.",
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
            "Reviewing what the in-app assistant proposes before anyone confirms it. It " +
              "can suggest changing a lead's status, adding a number to your suppression " +
              "list, pausing a campaign or adding an entry to your knowledge, and it " +
              "carries none of them out by itself — the person who accepts a suggestion " +
              "is making that change, on your account, with the same effect and the same " +
              "checks as if they had used the screen. It is a language model too, and " +
              "the same sentence above applies to it.",
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
            {
              kind: "callout",
              tone: "note",
              title: "Choosing an AI model changes what you pay only if your plan says so",
              text:
                "You can choose which of our AI models your agents use. Your plan may " +
                "quote a per-minute SURCHARGE for models above the standard one, and if " +
                "it does, that figure is on your order form and nowhere else — it is a " +
                "commercial term agreed with you under the paragraph above, and no model " +
                "list, setting or screen can introduce or raise it on its own. **If your " +
                "plan quotes no surcharge, switching models changes nothing you are " +
                "charged**: not your monthly fee, not your per-minute rate, not the rate " +
                "your credit balance is drawn down at. Where a surcharge does apply it " +
                "applies to every metered minute an agent runs on that model, it is " +
                "shown against the model before you choose it, it appears as its own " +
                "line on your invoice so you can see what caused a larger number, and it " +
                "is calculated from the model each call actually ran — so changing model " +
                "mid-month re-prices nothing already spoken. A model we choose for you " +
                "is never surcharged; only a model you or your staff selected is. " +
                "Separately, the product may show what a model costs US to run, marked " +
                "as such — that is published so a choice about quality is not made blind " +
                "to cost, and it is not a figure you are charged.",
            },
          ],
        },
        {
          id: "gst",
          heading: "6.2 GST and invoicing",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "We charge you no GST, and you cannot claim input credit from us",
              text:
                "{{LEGAL_ENTITY_NAME}} is {{GST_STATUS}}. So the price you agree is the " +
                "whole amount payable: nothing you are charged carries CGST, SGST, IGST " +
                "or any other tax, and no invoice from us will ever show a tax line " +
                "while that is true. Section 32 of the CGST Act forbids a person who is " +
                "not registered from collecting tax, and the product will not render a " +
                "tax invoice without a supplier GSTIN. The consequence for you is real " +
                "and we would rather state it than let your accounts department find " +
                "it: there is no tax on our document, so there is no input tax credit to " +
                "claim against it. If your procurement requires a GST tax invoice, say " +
                "so before you sign.",
            },
            {
              kind: "para",
              text:
                "What you receive for each billing month is a bill of supply — the " +
                "document rule 49 of the CGST Rules provides for a supplier who is not " +
                "registered. It carries our identity and address, your identity, a serial " +
                "number and date, what was supplied and its value, and a note in words " +
                "saying that no tax is charged and that no input tax credit is available. " +
                "Because we expect to register one day, that document may also show what " +
                "the tax and the total WOULD be at today's rate once we are: it is " +
                "labelled as an estimate, it is not part of what you owe, and no payment " +
                "we take includes it.",
            },
            {
              kind: "para",
              text:
                "If our turnover crosses the registration threshold, or another trigger " +
                "makes registration compulsory, we will register and start issuing tax " +
                "invoices. From that date GST is payable in addition to the prices quoted " +
                "to you, at the rate in force for this class of supply, and the invoice " +
                "will carry the particulars rule 46 of the CGST Rules requires: our GSTIN " +
                "and yours, the serial number and date, the SAC for the supply, the " +
                "taxable value, the rate, the tax charged under the correct head, and the " +
                "place of supply. Whether that head is IGST or CGST plus SGST depends on " +
                "the place of supply, which for a registered recipient is your location — " +
                "so give us your correct GSTIN and state, because you cannot claim tax " +
                "charged under the wrong one. We will tell you before the first such " +
                "invoice, and we will not add tax to a month already billed.",
            },
            {
              kind: "para",
              text:
                "A correction to an issued tax invoice is made by a credit or debit note " +
                "under section 34 of the CGST Act referencing the original. While we are " +
                "unregistered there is no tax to credit, so a correction is a corrected " +
                "bill of supply and a compensating entry in the ledger. Either way the " +
                "document you were given is never silently re-rendered — the Refund and " +
                "Cancellation Policy explains why.",
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
            "callers' data for our own purposes or to train any model OF OURS, what a " +
            "vendor's own terms permit that vendor to do is stated rather than promised " +
            "away (clause 2 of that Addendum, which was narrowed on 27 August 2026 for " +
            "exactly that reason), and the sub-processors we use are named.",
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
              "develop, including the improvements we make to the product while running " +
              "it. You get a non-exclusive, non-transferable right to use it for your " +
              "own business while this agreement lasts.",
            "You own your Client Data and your Caller Data — your recordings, your " +
              "transcripts, the lead records and CRM fields your extraction schema " +
              "produces, and the agents, prompts and knowledge content you created. You " +
              "grant us only the licence we need to run the service for you, and it ends " +
              "when the agreement does, subject to clause 14.",
            "Improving the product never means learning from your callers. We do not use " +
              "your Client Data or your Caller Data to train, fine-tune or evaluate any " +
              "model. That is our own undertaking; what a vendor's terms permit that " +
              "vendor to do with what we send it is a separate question, and clause 2 of " +
              "the Data Processing Addendum states it rather than promising on every " +
              "vendor's behalf — that clause is the operative text and nothing here cuts " +
              "it back or widens it. What we own " +
              "is the generic product: the code, the prompts we wrote, the schemas we " +
              "ship. Not anything derived from your conversations.",
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
        {
          kind: "callout",
          tone: "note",
          title: "Your telephone number is yours, and ending this does not touch it",
          text:
            "The connection was taken in your name on your own operator account and it " +
            "stays there: there is nothing for us to hand back, port or release, because " +
            "we never held it. What ends on our side is the access: we stop using the " +
            "operator credentials you issued us and delete our copy of them, and we " +
            "revoke the API keys and webhook signing secrets issued for your account. " +
            "The link between your Principal Entity registration and our Telemarketer " +
            "registration lives on the access provider's platform and is yours to " +
            "remove — ask and we will run that step for you, as we do at onboarding. " +
            "Until it is removed, nothing can be dialled under it through us anyway, " +
            "because your account is closed.",
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
                "liability under clause 14.2, which is uncapped. A penalty, a claim or a " +
                "regulatory cost arising from your list, your consent, your registration " +
                "or your header is yours in full: the cap exists to keep a supplier's " +
                "exposure proportionate to a risk it chose and can see, and that risk is " +
                "not one of them.",
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
                "Principal Entity; use of a telephone connection you were not the " +
                "subscriber of record for; use of a header or a template registered to " +
                "somebody else, or registered for one class of message and used for " +
                "another; and any claim that your content infringes a third party's " +
                "rights.",
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
              "except that either may assign to a successor of its business on notice. " +
              "A transfer of that kind changes who your counterparty is and nothing " +
              "else in these terms, and your rights under them are unaffected.",
            "No partnership: nothing here makes either party the other's agent, partner " +
              "or employee, except that we act as your registered Telemarketer, which is " +
              "the specific relationship the telecom framework defines.",
            "Notices: to you at the email on your account; to us by email to " +
              "{{SUPPORT_EMAIL}}. A notice terminating this agreement is given the same " +
              "way, and no notice under these terms has to be posted — we do not " +
              "operate a postal correspondence channel, so a notice you post is a " +
              "notice we may not receive. Send it by email.",
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
            {
              term: "Who you are contracting with",
              detail:
                "{{LEGAL_ENTITY_NAME}}, Udyam registration number " +
                "{{ENTITY_REGISTRATION_NUMBER}}, principal place of business " +
                "{{REGISTERED_ADDRESS}} (clause 1). That address identifies the " +
                "supplier; it is not a correspondence channel, and we do not service " +
                "post.",
            },
          ],
        },
      ],
    },
  ],
};
