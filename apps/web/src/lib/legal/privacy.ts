import type { LegalDocument } from "./types";

/**
 * The privacy notice. Every factual claim below traces to code, schema or a blueprint
 * document, and `docs/LEGAL-SURFACE.md` carries the trace for each one.
 *
 * Three rules were applied while writing it, and they are what make it different from a
 * template:
 *
 * 1. **Nothing is claimed that the code does not do.** The retention periods are the
 *    numbers `scripts/seed.DEFAULT_RETENTION_POLICIES` actually installs and
 *    `apps/workers/retention.py` actually enforces — NOT the numbers
 *    SECURITY-COMPLIANCE §4 quotes, which differ. Where the two disagree the notice
 *    states the enforced number and the disagreement is a finding, not a rounding.
 * 2. **The residency claim is the narrow one that is enforced, and as of D-449 it is no
 *    longer an India claim at all.** "Everything stays in India" was never available:
 *    object storage is Cloudflare R2 with no India-only jurisdiction, and the voice
 *    platform's own documentation puts the whole call on US infrastructure. On 22 August
 *    2026 the language model moved from Azure OpenAI in South India to Azure OpenAI in
 *    East US 2, so the one India claim this notice still made about model inference is
 *    WITHDRAWN rather than narrowed a fourth time. What is still enforced — every model
 *    endpoint is pinned to the single region the source declares, and
 *    `scripts/check_model_residency.py` fails the build otherwise — is stated as exactly
 *    that and no wider. Speech, the first reading of the transcript and the application
 *    host (D-180, an Indian VPS) are the legs that remain Indian.
 * 3. **The AI-disclosure paragraph describes the toggle, not an always-on greeting.**
 *    Whether the agent announces itself at the start of a call is the client's setting;
 *    that it answers truthfully when asked is enforced server-side and cannot be
 *    overridden by a client's script. The obligation to disclose sits with the client as
 *    Data Fiduciary and Principal Entity, and the notice says so in those words.
 */
export const PRIVACY_POLICY: LegalDocument = {
  slug: "privacy",
  title: "Privacy Policy",
  shortTitle: "Privacy Policy",
  summary:
    "What personal data Calevate handles, why, where it goes, how long it is kept, and " +
    "who to contact about it.",
  appliesTo:
    "Visitors to calevate.tech, people who use a Calevate client account, and people " +
    "whose call is handled by an agent a Calevate client operates.",
  sections: [
    {
      id: "who-we-are",
      heading: "1. Who we are, and what this notice covers",
      blocks: [
        {
          kind: "para",
          text:
            "Calevate is a product of {{LEGAL_ENTITY_NAME}} (registration number " +
            "{{ENTITY_REGISTRATION_NUMBER}}), registered at {{REGISTERED_ADDRESS}}. In " +
            'this notice "we", "us" and "Calevate" mean that company; "you" means ' +
            "whichever of the three groups below you fall into.",
        },
        {
          kind: "para",
          text:
            "Calevate supplies AI telephone agents to businesses in India. A business " +
            "that buys Calevate — we call them the client — configures an agent that " +
            "answers their incoming calls and, if they have the registrations to do it, " +
            "calls a list they upload. This notice covers three different relationships, " +
            "and the answer to almost every question depends on which one you are in.",
        },
        {
          kind: "definitions",
          items: [
            {
              term: "You are visiting calevate.tech",
              detail:
                "Section 3.1 is your section. The public pages set no cookies, load no " +
                "analytics and send nothing to a third party beyond the ordinary " +
                "request logging described there.",
            },
            {
              term: "You use a Calevate client account",
              detail:
                "You signed in to a dashboard at app.calevate.tech, or somebody invited " +
                "you to one. For your own account data we are the Data Fiduciary and " +
                "this notice is our notice to you. Sections 3.2, 5, 10 and 12 apply.",
            },
            {
              term: "You spoke to an agent on the phone",
              detail:
                "The business you were calling — or that called you — is the Data " +
                "Fiduciary for that conversation. We hold and process it for them, as " +
                "their Data Processor. Section 2 explains what that means for you and " +
                "section 12.3 tells you where to send a request.",
            },
          ],
        },
      ],
    },
    {
      id: "roles",
      heading: "2. The two roles, and why the difference matters to you",
      blocks: [
        {
          kind: "para",
          text:
            "The Digital Personal Data Protection Act 2023 splits responsibility between " +
            'a "Data Fiduciary", who decides why and how personal data is processed, and ' +
            'a "Data Processor", who processes it on the Fiduciary\'s behalf and on its ' +
            "instructions. Calevate sits on both sides of that line depending on whose " +
            "data is in question.",
        },
        {
          kind: "table",
          caption: "Who is responsible for which data",
          columns: ["Data", "Data Fiduciary", "Our role"],
          rows: [
            [
              "Your Calevate account: your name, work email, phone, role, the settings " +
                "you change, your billing and tax details.",
              "Calevate",
              "We decide why we hold it, and this notice is our notice to you.",
            ],
            [
              "A caller's conversation with a client's agent: the phone number, the " +
                "recording, the transcript, and whatever the client's agent was " +
                "configured to write down.",
              "The client business whose agent handled the call",
              "Data Processor. We act on that client's instructions and on nobody " +
                "else's, and we do not use their callers' data for our own purposes.",
            ],
            [
              "A list of contacts a client uploads for an outbound campaign.",
              "The client business that uploaded it",
              "Data Processor. The client is also responsible for having a lawful basis " +
                "for every number on it.",
            ],
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "If you spoke to one of these agents and want something done",
          text:
            "Ask the business you were dealing with. They are the Data Fiduciary, the " +
            "law makes them responsible for what is done on their behalf, and the " +
            "product gives them a screen that files an access request or an erasure " +
            "request against their own records and returns a certificate. If you cannot " +
            "identify the business or they do not respond, section 12.3 is our backstop.",
        },
      ],
    },
    {
      id: "what-we-collect",
      heading: "3. What personal data is involved",
      subsections: [
        {
          id: "visitors",
          heading: "3.1 If you only visit calevate.tech",
          blocks: [
            {
              kind: "para",
              text:
                "The public pages — the home page and these legal pages — set no cookies " +
                "of any kind, carry no analytics or advertising tags, embed no third-party " +
                "fonts or scripts, and have no contact form. There is nothing to consent to " +
                "and no profile is built.",
            },
            {
              kind: "para",
              text:
                "What is unavoidably recorded is the ordinary web request: your IP " +
                "address, the page requested, the time, the referring page and your " +
                "browser's user-agent string, in the logs of our web server and of " +
                "Cloudflare, which sits in front of the site and provides TLS and " +
                "protection against attack. Those logs exist to keep the site up and to " +
                "investigate abuse. They are not used to profile you and they are not " +
                "combined with anything else.",
            },
            { kind: "para", text: "The cookie notice sets this out in full." },
          ],
        },
        {
          id: "client-users",
          heading: "3.2 If you use a Calevate client account",
          blocks: [
            {
              kind: "para",
              text: "We hold, as Data Fiduciary, the following about you and your business:",
            },
            {
              kind: "definitions",
              items: [
                {
                  term: "Identity and sign-in",
                  detail:
                    "Your name, work email address and (if you give one) your phone " +
                    "number, together with your role in the account. Sign-in is ours " +
                    "end to end — there is no third-party sign-in provider, so your " +
                    "account identity is not shared with one. We store your password " +
                    "only as an Argon2id hash and never in a form anyone here can read.",
                },
                {
                  term: "Your business's own details",
                  detail:
                    "The organisation name, the URL slug, the billing email, the GSTIN " +
                    "you give us for invoicing, the state you are registered in, and the " +
                    "commercial terms agreed with you.",
                },
                {
                  term: "The answers you give during onboarding",
                  detail:
                    "Opening hours, branches, prices, services and the names and " +
                    "escalation numbers of staff the agent may need to transfer to. " +
                    "These are the facts that get compiled into what your agent knows. " +
                    "Some of them are personal data about your staff, and you are " +
                    "responsible for having told them.",
                },
                {
                  term: "Identity verification (KYC)",
                  detail:
                    "For self-serve and trial accounts, and for any account buying a " +
                    "phone number: your entity type, the kind of public-registry " +
                    "document you produced (CIN, LLPIN, GSTIN, Udyam, shop-and- " +
                    "establishment or trade licence), its reference number, the " +
                    "signatory's name, and a reference to where the verification pack is " +
                    "filed. The schema deliberately refuses a twelve-digit bare number, " +
                    "so an Aadhaar number cannot be stored in that field even by mistake.",
                },
                {
                  term: "Regulatory registrations",
                  detail:
                    "Your DLT Principal Entity identifier, its status, and the status of " +
                    "the link between your registration and ours as your Telemarketer.",
                },
                {
                  term: "What you did in the product",
                  detail:
                    "An audit record of significant actions — who did what, to which " +
                    "record, when, and from which IP address. Some of these entries are " +
                    "required evidence: reading an unredacted transcript, for instance, " +
                    "always writes one.",
                },
                {
                  term: "Billing and usage",
                  detail:
                    "Minutes used, charges, credits, top-ups and invoices. Payments are " +
                    "taken by a payment gateway; card numbers never reach us.",
                },
              ],
            },
          ],
        },
        {
          id: "callers",
          heading: "3.3 If a client's agent handled your call",
          blocks: [
            {
              kind: "para",
              text:
                "We process the following on behalf of the client whose agent you spoke " +
                "to. This list is itemised rather than summarised, because the client's " +
                "own notice to you has to be able to reproduce it accurately.",
            },
            {
              kind: "definitions",
              items: [
                {
                  term: "Your phone number",
                  detail:
                    "In international format, on the call record, on any lead record " +
                    "created from the call, on any consent-ledger entry, and — if the " +
                    "client uploaded you to a campaign list — on the campaign contact row.",
                },
                {
                  term: "Call metadata",
                  detail:
                    "Direction, start and end time, duration, how the call ended, the " +
                    "outcome the agent recorded, an automatic sentiment label, and which " +
                    "agent and campaign it belonged to.",
                },
                {
                  term: "The audio recording",
                  detail:
                    "If recording was on for that call. See section 4.",
                },
                {
                  term: "The transcript",
                  detail:
                    "Stored twice: the raw text of what was said, and a redacted copy in " +
                    "which identifier patterns have been masked. The redacted copy is " +
                    "what the product shows by default, everywhere. See section 4.",
                },
                {
                  term: "A written summary of the call",
                  detail: "Generated from the transcript.",
                },
                {
                  term: "Whatever the client's agent was configured to find out",
                  detail:
                    "Each client defines their own list of fields — a name, an area, a " +
                    "budget, a symptom, a preferred appointment slot, a callback number " +
                    "— and those become the columns of their CRM. We cannot list them " +
                    "here because the client chooses them; the client's own notice must.",
                },
                {
                  term: "Timestamped key moments",
                  detail:
                    "Short labels marking where in the recording something notable " +
                    'happened, including quotations of what you said (for example, "the ' +
                    'caller asked not to be called again").',
                },
                {
                  term: "Consent and suppression records",
                  detail:
                    "Whether recording consent was granted or declined, any opt-out you " +
                    "gave, any messaging opt-in, and whether your number is on the " +
                    "client's do-not-call list. These are kept on an append-only ledger " +
                    "and are deliberately NOT erased on request — see section 12.4.",
                },
                {
                  term: "Copies that leave our database",
                  detail:
                    "If the client has connected their own CRM or a Google Sheet, we " +
                    "keep the exact body we sent them, so that a dispute about what was " +
                    "delivered can be answered with evidence rather than a " +
                    "reconstruction. We also archive the raw document the voice platform " +
                    "returns for each call; it carries your number and the transcript.",
                },
                {
                  term: "Anything else you volunteer",
                  detail:
                    "A conversation is open-ended. If you say something about your " +
                    "health, your finances or another person, it is in the recording and " +
                    "the transcript. Agents are configured not to ask for identifiers " +
                    "such as Aadhaar, PAN or card numbers, and the redaction pass masks " +
                    "them from the default view if they are spoken anyway — but the raw " +
                    "transcript retains what was said until it is aged out.",
                },
              ],
            },
            {
              kind: "callout",
              tone: "note",
              title: "What we do not do with it",
              text:
                "A client's caller data is used to run that client's service and for " +
                "nothing else. It is not used to train models, it is not pooled across " +
                "clients, it is not sold, and it is not used to market to callers. The " +
                "database enforces the separation on every single query, not the " +
                "application code: each client's rows are isolated by row-level security " +
                "in PostgreSQL, and the application connects with a database role that " +
                "cannot bypass it.",
            },
          ],
        },
      ],
    },
    {
      id: "recordings",
      heading: "4. Recordings, transcripts and who can hear or read them",
      subsections: [
        {
          id: "recording-default",
          heading: "4.1 Recording",
          blocks: [
            {
              kind: "para",
              text:
                "Calls handled by a client's agent are recorded when that client has " +
                "recording switched on. If a caller declines recording during the call, " +
                "recording stops, the call continues, and the refusal is written to an " +
                "immutable consent ledger with the part of the transcript that evidences " +
                "it.",
            },
            {
              kind: "para",
              text:
                "The audio is stored in our own object storage, not the voice platform's, " +
                "and that copy is the system of record. Access is by short-lived signed " +
                "links only — five minutes — the storage bucket blocks public access at " +
                "the account level, and objects are encrypted at rest.",
            },
          ],
        },
        {
          id: "redaction",
          heading: "4.2 The redacted transcript is the default, everywhere",
          blocks: [
            {
              kind: "para",
              text:
                "After a call, an automated pass masks identifier patterns in the " +
                "transcript: Aadhaar numbers (checked against the Verhoeff checksum), " +
                "PAN numbers, card numbers (Luhn), and one-time-password patterns, plus " +
                "a language-model pass for numbers that were spoken out digit by digit. " +
                "The result is a second copy of the transcript, and it is the copy every " +
                "screen, export and notification shows.",
            },
            {
              kind: "para",
              text:
                "Reading the unredacted text is a separate, higher permission that only " +
                "an account owner holds — staff members do not — and every single read " +
                "writes an audit entry naming who read it and when. The same rule covers " +
                "the exact body delivered to a client's own CRM.",
            },
          ],
        },
        {
          id: "who-can-access",
          heading: "4.3 Who inside Calevate can reach it",
          blocks: [
            {
              kind: "para",
              text:
                "Our operators can view a client's account read-only, to support them and " +
                "to answer questions after they leave. That access is not a shortcut: it " +
                "requires an operator sign-in that has passed multi-factor authentication " +
                "(enforced by the server, not by the screen), plus a short-lived signed " +
                "grant issued for that one operator and that one client. It cannot make " +
                "changes. Two audit entries are written — one when the authority is " +
                "issued, one when data is actually read — so the record distinguishes " +
                '"permission was granted" from "data was looked at".',
            },
          ],
        },
      ],
    },
    {
      id: "ai-disclosure",
      heading: "5. The agent is an AI, and what gets said about that on the call",
      blocks: [
        {
          kind: "para",
          text:
            "Every Calevate agent is an artificial voice running a language model. It is " +
            "not a person, and it is not a recording of a person.",
        },
        {
          kind: "para",
          text:
            "Whether the agent announces that at the start of a call — and whether it " +
            "announces that the call is being recorded — is a setting on each agent that " +
            "the client controls, on both incoming and outgoing calls. A client may turn " +
            "either announcement off.",
        },
        {
          kind: "callout",
          tone: "note",
          title: "What a client cannot switch off",
          text:
            "If a caller asks whether they are speaking to a machine, an AI, a bot or a " +
            "recording, the agent answers truthfully. If a caller asks whether the call " +
            "is being recorded, the agent answers truthfully. This is enforced on our " +
            "side of the system, above the client's own script, so a client cannot " +
            "instruct their agent to deny it or to deflect the question. There is no " +
            "setting that turns it off and no plan to add one.",
        },
        {
          kind: "para",
          text:
            "The legal duty to disclose, where one applies, is the client's. They are the " +
            "Data Fiduciary for the conversation and the registered Principal Entity " +
            "under the telecom regulations; the obligation to give notice, to have a " +
            "lawful basis, and to comply with any rule requiring an automated call to " +
            "identify itself attaches to them, not to us. Our Acceptable Use Policy says " +
            "so in terms, and our terms require the client to comply with it. We provide " +
            "the mechanism and the evidence — whether the disclosure line was actually " +
            "spoken is measured against each call's transcript and shown on the call " +
            "record — and we do not, and cannot, decide whether a particular client's " +
            "calls need it.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "This is an area of live regulatory change",
          text:
            "As at the date of this notice no notified Indian regulation requires a " +
            "commercial voice call to announce that it is AI-generated, but TRAI has a " +
            "draft third amendment to the commercial-communications regulations out for " +
            "consultation, and the EU AI Act's transparency duty for AI systems that " +
            "interact with people applies from 2 August 2026 to systems in scope there. " +
            "If a rule changes what the product must say, the product changes.",
        },
      ],
    },
    {
      id: "why",
      heading: "6. Why we process it",
      blocks: [
        {
          kind: "table",
          caption: "Purposes, and the basis on which each is done",
          columns: ["Purpose", "Whose data", "Basis"],
          rows: [
            [
              "Providing the service a client bought: answering their calls, running " +
                "their campaigns, extracting their leads.",
              "Client users and their callers",
              "For client users, performance of our contract with them. For callers, the " +
                "client's own basis — we act on their documented instructions and do not " +
                "hold a basis of our own.",
            ],
            [
              "Keeping evidence that a call was lawful: the consent ledger, the " +
                "suppression lists, the audit record.",
              "Callers",
              "Compliance with a legal obligation and the client's instruction. This is " +
                "why the consent ledger survives an erasure.",
            ],
            [
              "Billing, invoicing, tax and credit control.",
              "Client users",
              "Contract, and compliance with tax law.",
            ],
            [
              "Security, abuse prevention, incident investigation and keeping the service " +
                "up.",
              "All groups",
              "Our legitimate operational need as the operator of the system, and our " +
                "obligation as a Processor to protect what we hold.",
            ],
            [
              "Quality review: a sample of calls is reviewed each week against a " +
                "compliance checklist.",
              "Callers",
              "The client's instruction and our contract with them. Reviewers see the " +
                "redacted transcript unless they hold the higher permission, and the read " +
                "is audited.",
            ],
            [
              "Answering support questions from a client, including after they have left.",
              "Client users and their callers",
              "Contract, and the client's instruction.",
            ],
          ],
        },
        {
          kind: "para",
          text:
            "We do not sell personal data, we do not share it for anyone else's " +
            "marketing, and we do not use client or caller data to train or fine-tune any " +
            "model — ours or a vendor's.",
        },
      ],
    },
    {
      id: "sharing",
      heading: "7. Who else handles it",
      blocks: [
        {
          kind: "para",
          text:
            "We use a small number of specialist suppliers to run the service. Each of " +
            "them is a sub-processor, each is named, and each is listed with what data " +
            "reaches it and where it processes it, on the sub-processor page. That page " +
            "is part of this notice.",
        },
        {
          kind: "para",
          text:
            "Beyond those suppliers we disclose personal data only: to the client whose " +
            "data it is; to a destination the client themselves configured, such as their " +
            "own CRM endpoint or their own Google Sheet; to our professional advisers " +
            "under confidentiality; and where we are compelled by law, in which case we " +
            "will tell the affected client unless we are prohibited from doing so.",
        },
      ],
    },
    {
      id: "where",
      heading: "8. Where it is processed",
      blocks: [
        {
          kind: "para",
          text:
            "This section is written narrowly on purpose, and so is what it says about " +
            "the law. Section 16 of the DPDP Act permits transfer outside India except " +
            "to countries the Central Government notifies as restricted, and no such " +
            "list has been notified — but that section does not commence until 13 May " +
            "2027, so it is the absence of a restriction rather than a permission you " +
            "can point at today. Until then the Information Technology Act 2000 and the " +
            "2011 sensitive-personal-data rules govern, and they do carry a transfer " +
            "test: comparable protection at the destination, plus either consent or " +
            "necessity for a contract. The Data Processing Addendum sets out how we meet " +
            "it, and the one question under those rules that nobody has answered — " +
            "whether a call recording counts as biometric information, because the 2011 " +
            "definition of that term includes voice patterns — is stated there rather " +
            "than resolved by us. What follows is where the data actually goes, which is " +
            "the part you should not have to discover for yourself.",
        },
        {
          kind: "definitions",
          items: [
            {
              term: "Speech is processed in India; the language model is processed in the United States",
              detail:
                "Speech recognition and voice synthesis run on an Indian provider, on " +
                "both call legs, and so does the first pass that reads your transcript " +
                "and pulls the fields out of it. The language model on both AI legs — " +
                "the model that holds the conversation during a call, and the dashboard " +
                "assistant that works on redacted data — runs on Microsoft's Azure " +
                "OpenAI service configured for the East US 2 region, in the United " +
                "States. Until 22 August 2026 that service was configured for the South " +
                "India region and this notice said so; the claim that the language model " +
                "runs in India is withdrawn, not reworded. What the build enforces, " +
                "unchanged by the move: there is one function in the whole codebase that " +
                "may construct a model endpoint, it can produce only the single region " +
                "the source declares, the region appears exactly once and is not a " +
                "setting anyone can edit, and the release fails if any of that stops " +
                "being true — so no setting, console control or environment variable can " +
                "move the model to a third country, only a reviewed code change can. " +
                "What it cannot enforce, stated plainly because the distinction is real: " +
                "the provider's endpoint address does not name its own region, so that " +
                "the account and its model deployment are genuinely in East US 2 is " +
                "confirmed by a person against the provider's console and filed as dated " +
                "evidence, not proved by a build check. See the sub-processor page, " +
                "section 3.2.",
            },
            {
              term: "The application and the database",
              detail:
                "Run on a single virtual server at {{PRIMARY_HOSTING_LOCATION}}, with " +
                "PostgreSQL on the same host. This is the store that holds phone numbers, " +
                "transcripts, summaries and lead records. The location is a decision that " +
                "has been taken; the machine has not been provisioned, because no client " +
                "data is in production yet.",
            },
            {
              term: "Recordings, exports and archived call documents",
              detail:
                "Stored in Cloudflare R2. We ask Cloudflare to place the bucket in its " +
                "Asia-Pacific region — that is a placement preference Cloudflare " +
                "applies where it can, not a residency commitment, and R2 does not " +
                "offer an India-only jurisdiction. So this data is stored outside " +
                "India, and asking for Asia-Pacific does not change that. Cloudflare " +
                "publishes no datacentre for that region, so we do not name a country " +
                "for it either.",
            },
            {
              term: "The voice platform",
              detail:
                "The company that runs the call itself documents that its services run on " +
                "United States infrastructure by default, and that processing calls inside " +
                "India is an enterprise option a customer buys and configures. We have not " +
                "bought it. So the live audio, the transcript that platform produces and " +
                "its own copy of the recording should be treated as processed and stored " +
                "outside India — not only the recording, which is all an earlier version " +
                "of this notice said. Our own copies are the system of record and are held " +
                "as described above. The sub-processor page carries the detail, including " +
                "why buying that option would not by itself move our calls to India.",
            },
            {
              term: "Transactional email and error monitoring",
              detail:
                "Resend and Sentry are operated from outside India. They receive email " +
                "addresses and — for Sentry — error reports that pass through a " +
                "redaction hook before they leave the process. Sign-in is no longer on " +
                "this list: it used to be operated by an overseas provider and is now " +
                "ours, running on the same server as the rest of the application.",
            },
          ],
        },
        {
          kind: "callout",
          tone: "warning",
          title: "One claim you may have seen elsewhere",
          text:
            "If any Calevate page, deck or proposal tells you that all data stays in " +
            "India, it is stating an intention rather than the enforced position, and " +
            "this section overrides it. That now includes anything of ours written " +
            "before 22 August 2026 which said the language model runs in an Indian " +
            "region: it did, it does not any more, and the sentence is withdrawn rather " +
            "than qualified. What is enforced today is the model-endpoint pinning " +
            "described above — one declared region, moved only by a reviewed code " +
            "change — and that region is in the United States.",
        },
      ],
    },
    {
      id: "retention",
      heading: "9. How long it is kept",
      blocks: [
        {
          kind: "para",
          text:
            "Retention is set per client and per category of data, and a nightly job " +
            "enforces it. The periods below are the defaults a new client account " +
            "receives; a client can lengthen them, and the product refuses to shorten the " +
            "recording period below the floor described underneath.",
        },
        {
          kind: "table",
          caption: "Default retention periods and what happens at the end of them",
          columns: ["Category", "Default period", "What happens"],
          rows: [
            [
              "Call recordings (the audio)",
              "90 days",
              "The audio file is deleted from storage and then the link to it is " +
                "cleared, in that order.",
            ],
            [
              "Transcripts, and the summary derived from them",
              "365 days",
              "Every word is replaced with a marker; the shape of the conversation (turn " +
                "count, speakers, timings) is kept so call statistics stay countable. The " +
                "summary is deleted outright.",
            ],
            [
              "Leads, extracted fields, key moments, and the bodies delivered to a " +
                "client's own CRM",
              "1095 days (three years)",
              "The number is replaced, the name is removed, the extracted fields and key " +
                "moments are emptied, and the stored delivery bodies are deleted from " +
                "object storage.",
            ],
            [
              "The raw document the voice platform returns for each call",
              "90 days",
              "The archived object is deleted from storage and the link to it is " +
                "cleared. It carries the caller's number and the transcript, which is " +
                "why it has a clock of its own rather than riding on the transcript's.",
            ],
            [
              "Superseded versions of knowledge content a client uploads",
              "365 days",
              "Deleted. The version currently in use is never expired by this — a " +
                "client's live answer material is theirs and stays until they change " +
                "it — so the clock runs only on versions no screen shows.",
            ],
            [
              "Consent, opt-out and audit records",
              "Retained",
              "These are append-only ledgers. Nothing expires them on a timer, because " +
                "they are the evidence that the calls were lawful and that the system was " +
                "used properly.",
            ],
          ],
        },
        {
          kind: "para",
          text:
            "Call recordings carry a minimum of 90 days on top of whatever a client " +
            "chooses. The database refuses to store a shorter recording period, and the " +
            "retention job refuses to act on one if it somehow existed. Clients in " +
            "regulated sectors — banking, insurance, securities — may be subject to " +
            "longer minimums set by their own regulator, and are responsible for " +
            "configuring accordingly.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "What an erasure does to knowledge content, and what it deliberately does not",
          text:
            "This callout used to say that the two stores above reached no retention " +
            "period at all and that an erasure never looked at knowledge content. Both " +
            "have been built since, and a public document that is wrong about our own " +
            "controls is a defect even when the error runs in your favour, so it is " +
            "corrected rather than quietly dropped. What is true now: both stores are on " +
            "the same nightly job as everything else, with the periods in the table " +
            "above. An erasure request SEARCHES a client's knowledge content for the " +
            "person's number and reports how many documents mention it — and does not " +
            "edit or delete any of it. That is a deliberate limit, not a gap: the " +
            "material is the client's own writing, and a processor silently rewriting a " +
            "client's documents would be the larger wrong. The count is on the erasure " +
            "certificate so the client can act on it.",
        },
        {
          kind: "para",
          text:
            "Backups are kept for 35 days. For up to 35 days after data is erased, a copy " +
            "may still exist in a backup; that copy is not accessible to the product, is " +
            "not used for any purpose, and ages out on its own. If a backup ever has to " +
            "be restored, replaying any erasures that completed after the restore point " +
            "is a mandatory step of the restore procedure.",
        },
        {
          kind: "para",
          text:
            "Client account data — your identity, your organisation record, your " +
            "invoices — is kept for as long as the account exists and afterwards for as " +
            "long as tax and limitation law requires the underlying records.",
        },
      ],
    },
    {
      id: "security",
      heading: "10. How it is protected",
      subsections: [
        {
          id: "controls",
          heading: "10.1 What is actually in place",
          blocks: [
            {
              kind: "list",
              items: [
                "Each client's data is isolated at the database level by forced row-level " +
                  "security. The application connects with a role that cannot bypass it, " +
                  "and a cross-client read returns zero rows. Tests assert this for every " +
                  "table that holds client data.",
                "Two entirely separate sign-in realms — one for clients, one for our " +
                  "operators — with separate applications, separate cookies and no shared " +
                  "session logic.",
                "Multi-factor authentication is mandatory for operator accounts and is " +
                  "enforced by the server on every request, including reads. A token that " +
                  "does not evidence a second factor is refused; a token that says nothing " +
                  "about one is also refused.",
                "Role-based permissions, with the map from every endpoint to its required " +
                  "permission asserted when the service starts, so a route cannot ship " +
                  "without a declared lock behind it.",
                "Operator access to a client account is read-only, requires a short-lived " +
                  "signed grant naming that operator and that client, and is audited twice.",
                "The audit record and the consent, billing and usage ledgers are " +
                  "insert-only, enforced by database triggers rather than by convention. " +
                  "Corrections are compensating entries; nothing is rewritten. Audit " +
                  "entries are chained with a keyed hash so a removal or an edit is " +
                  "detectable.",
                "Transcripts are redacted before they leave the system, and the redaction " +
                  "pair also backs the log formatter, the error-reporting hook and every " +
                  "operator alert. Traces are redacted at the exporter rather than at each " +
                  "call site.",
                "Phone numbers, transcript text and extracted fields are never written to " +
                  "application logs. Identifiers only.",
                "Credentials are encrypted at rest with a per-secret key wrapped by a " +
                  "master key that exists only in the process environment and never in the " +
                  "database.",
                "TLS everywhere with HSTS; object storage buckets block public access at " +
                  "the account level; recordings are reached only through signed links " +
                  "that expire in five minutes.",
                "Incoming voice-platform webhooks are authenticated by a strict source-IP " +
                  "allowlist plus execution-id de-duplication, and are treated as hints: " +
                  "the authenticated poll back to the platform is the record of truth. " +
                  "Outgoing webhooks to a client's own systems are signed.",
                "Per-client spend and rate ceilings, and a global switch that halts all " +
                  "outbound dialling at once.",
              ],
            },
          ],
        },
        {
          id: "no-certification",
          heading: "10.2 What we do not claim",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "No certification, and no pretence of one",
              text:
                "Calevate holds no ISO 27001 certificate, no SOC 2 report and no other " +
                "third-party security certification, and has not been independently " +
                "penetration-tested. The backup and restore mechanism is built but the " +
                "restore drill has not yet been run successfully. If a certification " +
                "matters to your procurement, ask us — do not assume one from the " +
                "controls listed above.",
            },
          ],
        },
        {
          id: "breach",
          heading: "10.3 If something goes wrong",
          blocks: [
            {
              kind: "para",
              text:
                "We run a documented incident procedure: classify, contain, investigate " +
                "using the audit and delivery records, and notify. Where a breach affects " +
                "a client's caller data, we notify that client without undue delay so that " +
                "they, as the Data Fiduciary, can meet their own notification duties to " +
                "the Data Protection Board and to affected people. Where it affects a " +
                "client's own account data, we notify the client and the Board as " +
                "required. The Data Processing Addendum states the operative commitment.",
            },
          ],
        },
      ],
    },
    {
      id: "children",
      heading: "11. Children",
      blocks: [
        {
          kind: "para",
          text:
            "Calevate is a business tool. It is not directed at children, we do not " +
            "knowingly create accounts for anyone under 18, and no part of the product is " +
            "designed to be used by a child.",
        },
        {
          kind: "para",
          text:
            "A child may nonetheless telephone a business and reach an agent. India's law " +
            "puts additional obligations on the Data Fiduciary where a child's personal " +
            "data is processed, including verifiable parental consent and a prohibition " +
            "on tracking or behavioural advertising directed at children. Those duties sit " +
            "with the client, who knows their own customer base; a client whose service " +
            "is aimed at or commonly reaches children should say so and take advice before " +
            "recording calls. We do not build profiles of callers and we do not carry out " +
            "behavioural advertising for anyone.",
        },
      ],
    },
    {
      id: "rights",
      heading: "12. Your rights, and how to use them",
      subsections: [
        {
          id: "rights-list",
          heading: "12.1 What the rights are",
          blocks: [
            {
              kind: "para",
              text:
                "Under the Digital Personal Data Protection Act 2023 a data principal has " +
                "the right to a summary of the personal data being processed and of the " +
                "processing activities, the right to correction, completion, updating and " +
                "erasure, the right to nominate someone to exercise the rights on their " +
                "behalf, and the right to grievance redressal. Those rights are exercised " +
                "against the Data Fiduciary.",
            },
            {
              kind: "callout",
              tone: "note",
              title: "The phased commencement, stated plainly",
              text:
                "The DPDP Rules 2025 were notified on 14 November 2025 with a phased " +
                "commencement: the Data Protection Board framework from November 2025, " +
                "the Consent Manager provisions from November 2026, and the substantive " +
                "obligations — notice, consent, data principal rights and grievance " +
                "redressal — from 13 May 2027. Until then, the Information Technology Act " +
                "2000 and the 2011 sensitive-personal-data rules remain the operative law. " +
                "We are not waiting for 2027: the rights below are already implemented and " +
                "already honoured. We describe the timetable so that you can tell what is " +
                "a legal entitlement today from what is a commitment we have chosen to " +
                "make early.",
            },
          ],
        },
        {
          id: "rights-client",
          heading: "12.2 If you are a client user, about your own account data",
          blocks: [
            {
              kind: "para",
              text:
                "Write to {{DATA_PROTECTION_CONTACT_EMAIL}}. We will verify that you are " +
                "who you say you are before acting — an unverified request is itself a " +
                "route to a breach — and respond within 30 days, and in any event within " +
                "the 90-day outer limit the DPDP Rules set for grievance redressal. Most " +
                "of your account data you can also see and correct yourself in the " +
                "dashboard.",
            },
          ],
        },
        {
          id: "rights-caller",
          heading: "12.3 If you were a caller",
          blocks: [
            {
              kind: "para",
              text:
                "Ask the business whose agent handled your call. They are the Data " +
                "Fiduciary and it is their record. The product gives them two things they " +
                "can use immediately:",
            },
            {
              kind: "list",
              items: [
                "A subject access export, keyed to your phone number, containing the call " +
                  "records, the redacted transcripts, the lead record and the consent " +
                  "entries held about you. Recordings are reported as present or absent " +
                  "rather than as a link, because a link in an emailed document is a " +
                  "working key to the audio. Other people's numbers appearing inside a " +
                  "summary are masked: honouring your right must not disclose somebody " +
                  "else's data.",
                "An erasure request, which locates you across calls, transcripts, " +
                  "extractions, leads, campaign lists, stored delivery bodies and archived " +
                  "call documents, carries out the erasure, and produces a certificate " +
                  "recording what was done, when, and with per-record hashes as evidence. " +
                  "The certificate states its own limits rather than overclaiming.",
              ],
            },
            {
              kind: "para",
              text:
                "If you do not know which business it was, or they will not act, contact " +
                "{{DATA_PROTECTION_CONTACT_EMAIL}}. We will identify the client from the " +
                "number and the date, pass the request on, and tell you we have done so. " +
                "We cannot erase a client's records on your instruction alone — as their " +
                "Processor we act on their instructions — but we can and will make sure " +
                "the request reaches somebody who can.",
            },
          ],
        },
        {
          id: "rights-limits",
          heading: "12.4 What an erasure does not remove, and why",
          blocks: [
            {
              kind: "para",
              text:
                "Every certificate we issue states these limits. They are listed here so " +
                "that nobody has to file a request to find out.",
            },
            {
              kind: "list",
              items: [
                "Consent-ledger entries are kept, and they carry the number. They are the " +
                  "append-only proof that the calls were lawful; destroying them would " +
                  "destroy the evidence that consent existed.",
                "Billing records are kept. They carry no personal data and deleting them " +
                  "would rewrite a closed billing period.",
                "Call rows survive with their personal fields cleared, rather than being " +
                  "deleted, so the minutes that were billed stay countable.",
                "A recording younger than the 90-day telecom retention floor is not " +
                  "destroyed early. It is scheduled: the link to it is cleared " +
                  "immediately so nothing in the product can reach, play or export it, a " +
                  "destruction date is fixed at the moment the request runs, and the audio " +
                  "is destroyed automatically on that date without a second request. The " +
                  "certificate states the date.",
                "Copies held by the voice platform are reported as unconfirmed. Their " +
                  "deletion interface is undocumented, and we will not certify a deletion " +
                  "we cannot show.",
                "Knowledge content a client uploaded is not searched. If your details are " +
                  "in a document a client uploaded for their agent to answer from, " +
                  "removing them is manual work on the client's side.",
                "Backups age out on their own 35-day cycle.",
              ],
            },
          ],
        },
      ],
    },
    {
      id: "changes",
      heading: "13. Changes to this notice",
      blocks: [
        {
          kind: "para",
          text:
            "We will update this notice when what the product does changes. Material " +
            "changes affecting clients are notified by email to the account owner before " +
            "they take effect. The version in force is always the one published here, and " +
            "the date it took effect is shown at the top.",
        },
      ],
    },
    {
      id: "contact",
      heading: "14. Contact, and how to complain",
      blocks: [
        {
          kind: "definitions",
          items: [
            {
              term: "Questions about how your personal data is processed",
              detail:
                "{{DATA_PROTECTION_CONTACT_NAME}}, {{DATA_PROTECTION_CONTACT_EMAIL}}. " +
                "This is the contact rule 9 of the DPDP Rules 2025 requires us to " +
                "publish, and we repeat it in every reply to a rights request.",
            },
            {
              term: "Complaints",
              detail:
                "{{GRIEVANCE_OFFICER_NAME}}, {{GRIEVANCE_OFFICER_DESIGNATION}}, " +
                "{{GRIEVANCE_OFFICER_EMAIL}}. The grievance redressal page sets out the " +
                "timetable and what to include.",
            },
            {
              term: "Suspected security problems",
              detail: "{{SECURITY_CONTACT_EMAIL}}.",
            },
            {
              term: "By post",
              detail: "{{LEGAL_ENTITY_NAME}}, {{REGISTERED_ADDRESS}}. Telephone {{CONTACT_PHONE}}.",
            },
          ],
        },
        {
          kind: "para",
          text:
            "If we do not resolve your complaint you may take it to the Data Protection " +
            "Board of India. You do not need our permission and you do not lose any other " +
            "remedy by complaining to us first.",
        },
      ],
    },
  ],
};
