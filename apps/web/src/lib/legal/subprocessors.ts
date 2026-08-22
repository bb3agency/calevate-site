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
              "United States. Their documentation states that all of their services run on " +
                "US infrastructure unless an enterprise data-residency option is purchased, " +
                "which we have not purchased. Read the note below before relying on this " +
                "row either way — it is the most important caution on this page.",
              "Core (primary engine). The verification pilot has not yet been run, and the " +
                "shipped default engine is a local stub.",
            ],
            [
              "Sarvam AI",
              "Speech recognition and voice synthesis during the call, the first pass " +
                "that extracts fields from the transcript, and the standby for the " +
                "dashboard assistant if the primary model is unavailable.",
              "Call audio and the raw, unredacted transcript. This is the one path that " +
                "must see raw text: a callback-number field needs the actual digits.",
              "India.",
              "Core. It no longer supplies the language model that holds the " +
                "conversation — that is the next row.",
            ],
            [
              "Microsoft — Azure OpenAI",
              "Both language-model legs: the model that holds the conversation during a " +
                "call, and the dashboard assistant a client triggers from their own " +
                "screen.",
              "On the call leg, the conversation as it happens — everything the caller " +
                "says, turn by turn, as it is said. On the dashboard leg, the redacted " +
                "transcript and the client's own configuration, never raw personal data. " +
                "The two legs see very different things and are listed separately for " +
                "that reason.",
              "United States — East US 2, by configuration. This cell has moved twice " +
                "and both steps are kept rather than overwritten: until 19 August 2026 " +
                "the language model ran on Google Cloud's Vertex AI in the asia-south1 " +
                "region (Mumbai, India); from 19 August 2026 on this vendor's South " +
                "India region; and since 22 August 2026 on this vendor's East US 2 " +
                "region, in the United States. Read the caution below before relying " +
                "on this: the endpoint does not name its own region, so this is a " +
                "setting we make and check by hand rather than one a build can prove.",
              "Core. Until 19 August 2026 this row named Google Cloud's Vertex AI for the " +
                "dashboard leg only; both legs moved to Microsoft on that date, and the " +
                "in-call leg — which hears the caller — is new to this vendor. On " +
                "22 August 2026 the region moved out of India; the vendor did not " +
                "change, and neither did the speech provider or the first reading of " +
                "your transcript, which are Indian and stay Indian.",
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
              "Cloudflare",
              "Two distinct things: the edge in front of the site (TLS, caching, protection " +
                "against attack), and R2 object storage.",
              "At the edge: every HTTP request, including IP addresses. In R2: call " +
                "recordings, exports, the archived raw call documents, the bodies delivered " +
                "to client CRMs, and database backup segments.",
              "Global. We ask R2 to place the bucket in its Asia-Pacific region. That " +
                "is a preference Cloudflare honours where it can and not a residency " +
                "commitment — R2 guarantees a jurisdiction only for the European Union, " +
                "the United States, and United States government workloads, and offers " +
                "no India-only jurisdiction — so this data is stored outside India and " +
                "may be stored outside Asia. We do not name a city: Cloudflare " +
                "documents this region only as Asia-Pacific and does not publish which " +
                "datacentre serves it.",
              "Core.",
            ],
            [
              "The hosting provider for the application server",
              "Runs the application, the background workers and the PostgreSQL database.",
              "Everything held in the database: phone numbers, transcripts, summaries, lead " +
                "records, account data.",
              "India — {{PRIMARY_HOSTING_LOCATION}}. The blueprint does not require " +
                "India co-location for this tier, which runs outside the live call path; " +
                "it was chosen anyway. Nothing has been provisioned yet, because no " +
                "client data is in production.",
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
              "Writes each new lead into a Google Sheet you own. Since 19 August 2026 " +
                "this is the ONLY thing any Google service does for us: no call audio, " +
                "no transcript and no model request reaches Google any more.",
              "The lead's fields, including name and — depending on the option you choose " +
                "— the phone number in raw or masked form. Never the recording or the " +
                "transcript.",
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
      heading: "3. Three things a careful reader should know",
      subsections: [
        {
          id: "bolna-residency",
          heading: "3.1 Where the voice platform runs the call, and why that is not India",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "Assume the call itself is handled outside India",
              text:
                "The company that runs our voice platform documents that its services run " +
                "on United States infrastructure by default, and that processing calls " +
                "inside India is an enterprise option a customer buys and configures. We " +
                "have not bought it, and no contract pins it. So a client should assume " +
                "that the live audio of their calls, the transcript the platform produces, " +
                "and the platform's own copy of the recording are handled outside India " +
                "for as long as the platform keeps them.",
            },
            {
              kind: "para",
              text:
                "There is a second reason, and it is a design consequence rather than a " +
                "purchasing one, so we state it plainly. The platform's published " +
                "conditions for running a call on Indian servers require that the speech " +
                "and language models be the platform's own integrations — and this product " +
                "is built the other way round, on our own accounts with each model " +
                "provider, which is what lets us tell you exactly which model hears your " +
                "caller. Their documentation says that connecting your own provider keys " +
                "sends the call through their US servers whatever else is configured. " +
                "Buying the residency option would therefore not by itself move our calls " +
                "to India: it is a choice between two things we have said elsewhere on " +
                "this page that we value, and we would rather you saw the trade-off than " +
                "read a sentence that hides it.",
            },
            {
              kind: "para",
              text:
                "What this does NOT change: the speech provider is Indian, on both call " +
                "legs, and so is the first pass that reads your transcript and extracts " +
                "the fields. What it no longer sits alongside is a language model in " +
                "India. Until 22 August 2026 this paragraph said the model inference " +
                "itself did not leave the country; since that date the language model " +
                "runs in the United States, so both the platform that orchestrates the " +
                "call and the model that answers on it are outside India. Section 3.2 " +
                "says what moved and what we still promise about it. Our own copy of the " +
                "recording and transcript — the system of record, the one the product " +
                "reads and the one our retention periods govern — is in the storage " +
                "described in the register above.",
            },
            {
              kind: "para",
              text:
                "An earlier version of this page said the platform was in India and " +
                "described only its recording storage as being in the United States. That " +
                "was based on recording links we had seen, which pointed at Amazon S3 in " +
                "the us-east-1 region; the platform has since moved those links behind its " +
                "own address, so the storage region can no longer be read off them. The " +
                "correction above comes from the platform's own published documentation " +
                "rather than from an observation, and it is broader than what the old " +
                "sentence said.",
            },
          ],
        },
        {
          id: "llm-residency",
          heading: "3.2 The language model is no longer in India, and what we still promise about it",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "A claim we have withdrawn, not narrowed",
              text:
                "Until 22 August 2026 this page told you that the language model ran in " +
                "an Indian region. That is no longer true and we are not going to keep " +
                "the sentence alive with qualifiers: on that date the model region moved " +
                "to East US 2, in the United States, and the claim that model inference " +
                "happens in India is withdrawn. The vendor did not change and neither " +
                "did anything else on this page. What replaced the claim is set out " +
                "below, and it is a promise about our code rather than about a country.",
            },
            {
              kind: "para",
              text:
                "Until 19 August 2026 the language model ran on an endpoint whose own " +
                "address contained the region it served, so a check in our build could " +
                "read the region out of the code and fail the release if it were ever " +
                "anything else. Our current provider's address contains no region at " +
                "all: the region is a property of the account resource the address " +
                "points at, not of the address. That is a genuinely weaker guarantee " +
                "than the one we could make in July, and it was weaker before the region " +
                "moved — the two changes are separate and we would rather you read both " +
                "here than infer either later.",
            },
            {
              kind: "para",
              text:
                "What the build still proves, and it is the same shape as before: there " +
                "is exactly one place in our code that can construct a model endpoint, " +
                "it can produce only the single region our source declares, that region " +
                "is written once and is not a setting anyone can edit, and no " +
                "configuration field is allowed to carry a region or an endpoint at all. " +
                "So no change to our software or our settings can move the language leg " +
                "to a third country; only a reviewed change to the declared region can, " +
                "and the build refuses that change until every other file in the tree " +
                "agrees with it. What moved on 22 August 2026 is which region is named, " +
                "not whether one is.",
            },
            {
              kind: "callout",
              tone: "warning",
              title: "Two facts a person confirms, not the build",
              text:
                "First, that the provider account itself was created in the East US 2 " +
                "region — the same attestation as before, aimed at the new region. " +
                "Second, that the model deployment inside it is the regional kind rather " +
                "than the provider's global default, which would process requests " +
                "wherever there is capacity in the world; that one is unchanged by the " +
                "move and still matters, because a global deployment would put your " +
                "callers' words in a country neither of us has named. Both are read from " +
                "the provider's console by a person, dated and filed as evidence, and " +
                "neither can be seen from the endpoint, from the response, or from any " +
                "check we could write. We say so because a document that called this " +
                "machine-enforced would be overstating it.",
            },
          ],
        },
        {
          id: "byok",
          heading: "3.3 Model credentials, and what happens if you change them",
          blocks: [
            {
              kind: "para",
              text:
                "The speech and language models run under credentials the platform holds, " +
                "against endpoints the platform pins. Changing which model an agent uses " +
                "is a data-residency change and not a settings tweak, and it is treated as " +
                "one: no model endpoint can be built anywhere in our code except through " +
                "the single function described above, and the build refuses a release in " +
                "which one is.",
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
            "The move of the language model from South India to East US 2 on 22 August " +
            "2026 is exactly the event that sentence describes: an existing " +
            "sub-processor moving to a materially different location. It cost nothing, " +
            "and the only reason it cost nothing is that no client account is live, so " +
            "there was nobody owed 30 days' notice and nobody with a right to object. " +
            "We would rather write that than let the change look free. Once the first " +
            "client is live, the same move would have to be notified by email 30 days " +
            "before it took effect, a client could object on data-protection grounds, " +
            "and if we could not offer them a workaround they could terminate the " +
            "affected part of the service without penalty — which is the cost this " +
            "clause is for, and the reason a region is not a thing we change casually.",
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
