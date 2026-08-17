import type { LegalDocument } from "./types";

/**
 * The named sub-processor register, and the one place the list exists.
 *
 * The DPA's Annex C does not restate it — it links here. Two copies of a sub-processor
 * list is exactly the drift that makes the DPA's change-notification clause unkeepable.
 *
 * ## The `Status` column is load-bearing and is not decoration
 *
 * Nothing in this system is deployed to production yet. A register that listed fourteen
 * vendors with no standing would tell a reader that fourteen companies hold their
 * callers' data today, which is false; one that listed only the live ones would be an
 * empty page, which is useless to a client evaluating the product. So each row says which
 * of four states it is in — the vendor is in the running path, it is configured but the
 * feature is off, it is selected only if the client themselves turns it on, or it is a
 * contingency nobody has selected. Every state traces to a config field or an adapter in
 * the tree, cited in `docs/LEGAL-SURFACE.md`.
 */
export const SUBPROCESSORS: LegalDocument = {
  slug: "subprocessors",
  title: "Sub-processors",
  shortTitle: "Sub-processors",
  summary:
    "Every third party that processes personal data on our behalf, what reaches them, " +
    "and where they process it.",
  appliesTo:
    "Clients assessing Calevate, and anyone reading the Privacy Policy or the Data " +
    "Processing Addendum — both of which incorporate this page.",
  sections: [
    {
      id: "how-to-read",
      heading: "1. How to read this page",
      blocks: [
        {
          kind: "para",
          text:
            "A sub-processor is a company we engage to process personal data as part of " +
            "delivering the service. Under clause 6 of the Data Processing Addendum, this " +
            "page is the authorised list, and it is the list we notify changes against.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "Calevate is not yet running in production",
          text:
            "No client account is live and no production deployment exists. This register " +
            "describes the system as built and configured, which is the honest thing a " +
            "buyer needs before they sign, not a description of data flowing today. The " +
            "Status column tells you which is which, and every entry marked otherwise " +
            "than Core is one that only starts processing when a specific decision is " +
            "taken — by us or by you.",
        },
        {
          kind: "definitions",
          items: [
            {
              term: "Core",
              detail:
                "In the path for every client. Data reaches this vendor as soon as the " +
                "service runs at all.",
            },
            {
              term: "Client-enabled",
              detail:
                "Only processes data if you switch the corresponding feature on in your " +
                "own account. If you never connect it, it never sees anything of yours.",
            },
            {
              term: "Configured, not enabled",
              detail:
                "The integration exists in the product and is switched off. It refuses " +
                "to send rather than silently working, and turning it on is a deliberate " +
                "act.",
            },
            {
              term: "Contingency",
              detail:
                "An alternative kept ready in case the primary choice fails. Nothing has " +
                "been sent to it and no account exists. If one is ever adopted, that is a " +
                "change to this page and is notified under clause 6 of the DPA.",
            },
          ],
        },
      ],
    },
    {
      id: "register",
      heading: "2. The register",
      blocks: [
        {
          kind: "table",
          caption: "Sub-processors, the data each receives, and where it is processed",
          columns: ["Vendor", "What it does for us", "Personal data it receives", "Location", "Status"],
          rows: [
            [
              "Bolna",
              "Voice platform: runs the live call, connects the speech and language models, " +
                "and returns the transcript and call record.",
              "Caller phone number, live call audio, full transcript, call metadata, and the " +
                "agent configuration we send it.",
              "India for the platform. Their own copies of call recordings have been " +
                "observed on Amazon S3 in us-east-1 — see the note below.",
              "Core (primary engine). The verification pilot has not yet been run, and the " +
                "shipped default engine is a local stub.",
            ],
            [
              "Sarvam AI",
              "Speech recognition, the language model that runs the conversation, voice " +
                "synthesis, and the first pass that extracts fields from the transcript.",
              "Call audio and the raw, unredacted transcript. This is the one path that " +
                "must see raw text: a callback-number field needs the actual digits.",
              "India.",
              "Core.",
            ],
            [
              "Google Cloud — Vertex AI",
              "The dashboard assistant a client triggers from their own screen.",
              "The redacted transcript and the client's own configuration. Never raw " +
                "personal data.",
              "India — Mumbai (asia-south1) only. The region is a frozen constant in the " +
                "code and a build check fails the release if any model endpoint names a " +
                "global or non-Indian host.",
              "Core, on a client-triggered surface. A deployment with no Google credential " +
                "simply has no dashboard assistant.",
            ],
            [
              "Exotel · Vobiz · Plivo",
              "Telephone numbers and the carrier connection the calls run over.",
              "Caller and called numbers, and call detail records.",
              "India.",
              "Core once numbers are procured. None is procured yet, because that depends " +
                "on the DLT registrations.",
            ],
            [
              "Clerk",
              "Sign-in for the two dashboards. Two separate Clerk applications — one for " +
                "clients, one for our operators.",
              "Client users' names, email addresses, authentication factors and session " +
                "state. No caller data ever reaches it.",
              "United States.",
              "Core.",
            ],
            [
              "Cloudflare",
              "Two distinct things: the edge in front of the site (TLS, caching, protection " +
                "against attack), and R2 object storage.",
              "At the edge: every HTTP request, including IP addresses. In R2: call " +
                "recordings, exports, the archived raw call documents, the bodies delivered " +
                "to client CRMs, and database backup segments.",
              "Global. R2 selects a storage location automatically and offers no India-only " +
                "jurisdiction, so this data may be stored outside India.",
              "Core.",
            ],
            [
              "The hosting provider for the application server",
              "Runs the application, the background workers and the PostgreSQL database.",
              "Everything held in the database: phone numbers, transcripts, summaries, lead " +
                "records, account data.",
              "{{PRIMARY_HOSTING_LOCATION}}. The blueprint does not require India " +
                "co-location for this tier and nothing has been provisioned, so the " +
                "location is a decision that must be taken and stated before launch.",
              "Core.",
            ],
            [
              "Resend",
              "Transactional email: the hot-lead notification to a client, and operator " +
                "alerts.",
              "The recipient's email address; in a hot-lead notification, the lead's name " +
                "and the call summary. The phone number is masked before the email is " +
                "composed. Operator alerts carry identifiers only.",
              "United States.",
              "Core. An SMTP server of your own choosing is the alternative and is " +
                "selectable.",
            ],
            [
              "Sentry",
              "Error and performance monitoring for our own services.",
              "Error reports and traces. Personal data is stripped before it leaves the " +
                "process: the redaction pair backs the log formatter, the Sentry event " +
                "hook and breadcrumbs, and traces are redacted at the exporter rather " +
                "than at each call site.",
              "Operated from outside India.",
              "Configured, not enabled — it activates only when a DSN is set.",
            ],
            [
              "Razorpay",
              "Card, UPI and netbanking payments for self-serve top-ups.",
              "Payer contact details and payment metadata. Card numbers never reach us.",
              "India.",
              "Configured, not enabled. No merchant account has been confirmed.",
            ],
            [
              "Google — Sheets API",
              "Writes each new lead into a Google Sheet you own.",
              "The lead's fields, including name and — depending on the option you choose " +
                "— the phone number in raw or masked form.",
              "Google, global.",
              "Client-enabled. Access is granted by you sharing your own document with our " +
                "service account, and revoked by un-sharing it.",
            ],
            [
              "Meta — WhatsApp Business",
              "Sends a follow-up WhatsApp message to a lead using an approved template.",
              "The recipient's phone number and the template parameters.",
              "Meta, global.",
              "Configured, not enabled. No messaging provider has been chosen, and the " +
                "code refuses to send until one is. A separate, recorded messaging opt-in " +
                "is required for every recipient — consent to be called never satisfies it.",
            ],
            [
              "Meta — Lead Ads",
              "Retrieves the answers a person submitted on your Facebook or Instagram lead " +
                "form, so the agent can call them back.",
              "The lead form answers, including name and phone number.",
              "Meta, global.",
              "Client-enabled, and per lead source: it works only where you have supplied " +
                "the access token for your own Page.",
            ],
            [
              "Cartesia",
              "An alternative voice platform, built so that switching engines is a " +
                "configuration change rather than a rewrite.",
              "The same categories as the primary voice platform, if it were ever selected.",
              "United States.",
              "Contingency. No account exists and no request has ever been made to it from " +
                "this system.",
            ],
            [
              "Cohere",
              "Text embeddings, needed only if the retrieval service we adopt does not " +
                "bundle its own.",
              "Chunks of the knowledge content a client uploads for their agent to answer " +
                "from.",
              "Outside India.",
              "Contingency. Not selected.",
            ],
          ],
        },
      ],
    },
    {
      id: "cautions",
      heading: "3. Two things a careful reader should know",
      subsections: [
        {
          id: "bolna-residency",
          heading: "3.1 The voice platform's own recording storage",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "Observed in us-east-1",
              text:
                "Our voice platform's call recordings have been observed on Amazon S3 in " +
                "us-east-1. Their enterprise tier offers full India data residency for " +
                "audio, transcripts, logs and inference; we have not yet pinned that in a " +
                "signed contract. Until we have, a client should assume that a second " +
                "copy of their call recordings exists outside India for as long as the " +
                "platform retains it. Our own copy — the system of record, the one the " +
                "product reads and the one our retention periods govern — is in the " +
                "storage described in the register above.",
            },
          ],
        },
        {
          id: "byok",
          heading: "3.2 Model credentials, and what happens if you change them",
          blocks: [
            {
              kind: "para",
              text:
                "The speech and language models run under credentials the platform holds, " +
                "against endpoints the platform pins. Changing which model an agent uses " +
                "is a data-residency change and not a settings tweak, and it is treated as " +
                "one: the destination can no longer be a global endpoint, because a build " +
                "check refuses to compile a release in which one appears.",
            },
          ],
        },
      ],
    },
    {
      id: "changes",
      heading: "4. Changes to this list",
      blocks: [
        {
          kind: "para",
          text:
            "We will give clients at least 30 days' notice by email before a new " +
            "sub-processor starts processing their data, or before an existing one moves " +
            "to a materially different location. A client who reasonably objects on data " +
            "protection grounds may raise it with us under clause 6 of the Data " +
            "Processing Addendum, and if we cannot find a workaround they may terminate " +
            "the affected part of the service without penalty for the remainder of the " +
            "term.",
        },
        {
          kind: "para",
          text:
            "Replacing an existing sub-processor with one performing the same function in " +
            "an emergency — a vendor outage or a security incident — may happen without " +
            "notice. We will tell affected clients as soon as we reasonably can, and in " +
            "any event within 72 hours.",
        },
      ],
    },
  ],
};
