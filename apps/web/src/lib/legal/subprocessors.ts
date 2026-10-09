import type { LegalDocument } from "./types";

/**
 * One published category of sub-processor, defined once so the rendered table, the names
 * the page may print, and the coverage guard all read the same rows.
 *
 * `key` is the identifier `docs/legal/SUBPROCESSOR-REGISTER.md` files each named vendor
 * under, and `scripts/check_subprocessor_coverage.py` holds the two together: every vendor
 * the code can reach must be in that register, its category must be a `key` here, and every
 * key here must have at least one vendor behind it. `named` is the short list of companies
 * this page MAY print, and only those; the register marks the same rows "Named publicly".
 */
interface CategoryRow {
  readonly key: string;
  readonly category: string;
  readonly named: readonly string[];
  readonly does: string;
  readonly receives: string;
  readonly location: string;
  readonly status: string;
}

/**
 * The categories, and the one place the public vendor picture exists.
 *
 * ## Why categories and not names (D-679)
 *
 * Calevate resells a voice platform under a white-label programme and does not name its
 * telephony or voice providers publicly. The founder chose the model a competitor already
 * publishes (app.outpero.com/security, read 6 Oct 2026): a table of CATEGORIES, and a named
 * list on request. The named list lives in `docs/legal/SUBPROCESSOR-REGISTER.md`, which is
 * never rendered; the per-vendor evidence classes this header used to carry moved there with
 * it.
 *
 * ## What moving to categories must NOT do
 *
 * Remove a fact. Every disclosure the named rows made is still here, reworded about the
 * category: that call audio and transcripts may leave India; that the speech provider's own
 * terms permit training on what it receives unless consent is declined; its retention
 * figures; that the "no vendor trains on your data" promise is narrowed to our own conduct;
 * the carrier's recording and our 90-day copy; the language model's United States region;
 * and every NOT VERIFIED location. Where one category holds companies in different states,
 * the cell says which state each is in without naming it. A category that merges two
 * companies' positions must never borrow the better one for both.
 *
 * Names are printed only where naming is unavoidable and harmless to the white label:
 * the payment gateway a client pays through, and services a client connects to its own
 * account itself (so the client necessarily knows the counterparty).
 *
 * ## The `status` column is load-bearing
 *
 * Production runs `ENGINE=thinnest` since 7 Oct 2026. Each row says which of four states
 * its companies are in — in the running path, configured but off, selected only if the
 * client turns it on, or a contingency nobody has selected.
 */
export const SUBPROCESSOR_CATEGORIES: readonly CategoryRow[] = [
  {
    key: "telephony",
    category: "Telephony",
    named: [],
    does:
      "Call carriage and numbers: the calling numbers and the connection the calls run " +
      "over. Today the hosted voice platform described in the next row rents the numbers " +
      "and carries every call, so its row covers this category for live calls. The rest " +
      "of this row describes the carriers our own call program uses instead, if the " +
      "service is switched back to that program: a carrier on our own account with it, " +
      "which CARRIES THE AUDIO — the call's media connection terminates at the carrier, " +
      "and it streams the sound of the call, in both directions, to and from the program " +
      "of ours that holds the conversation — and a second, fallback carrier with which we " +
      "hold no account.",
    receives:
      "From the hosted voice platform: as its row describes. From a carrier of our own, " +
      "if one is switched on: caller and called numbers, call detail records, the live " +
      "audio of the call in both directions, and a recording of the call, which we copy " +
      "and keep for 90 days, and which is deleted from the carrier one day after our copy " +
      "is saved.",
    location:
      "Not stated by the carrier in use when calls run on our own program. Nothing it " +
      "publishes that we have read says where it processes or stores call data, so we " +
      "name no country for it. The hosted voice platform's own published location is in " +
      "the next row.",
    status:
      "Core: the hosted voice platform carries every call. The carrier on our own account " +
      "and the fallback carrier are configured, not enabled: nothing reaches either " +
      "unless the service is switched back to our own call program.",
  },
  {
    key: "voice-platform",
    category: "Voice platform",
    named: [],
    does:
      "RUNS THE CALL. Two kinds of platform, and the service uses one of them at a time. " +
      "Since 7 October 2026 it uses a hosted voice platform that runs the whole call " +
      "itself: it holds the agent we configure, answers and places the calls on numbers " +
      "it rents to us, recognises what the caller says, runs the language model that " +
      "answers, and speaks. The cheaper of our two voice qualities is its own voices, " +
      "including voices our own staff create on it from a consenting speaker's recording; " +
      "the dearer quality is spoken by the voice-synthesis company in the text-to-speech " +
      "row, on our own account with it, which this platform calls on our behalf. So for " +
      "live calls the speech-recognition and in-call language-model work described below " +
      "is done by this platform and the companies it uses. The other kind, not in use, is " +
      "a hosting platform on which the conversation is a program of ours — our script, " +
      "our choice of models, our knowledge lookup — running in a container. A third " +
      "platform is kept as a contingency. Until 2 October 2026 this register also listed " +
      "a third-party voice platform that was to run the call; it is no longer used and " +
      "has been removed from the product.",
    receives:
      "The most sensitive combination anything in this table receives: the caller's live " +
      "audio in both directions, the transcript as it is produced, the agent's " +
      "instructions, the knowledge the agent answers from, and — where the account has " +
      "switched caller continuity on — the short note of what a returning caller told the " +
      "agent before. The hosted voice platform also receives the caller and called " +
      "numbers and a recording of the call, which we copy into our own storage and keep " +
      "for 90 days. The hosted voice platform also holds the voices our own staff create " +
      "on it: a recording of the person whose voice it is — one of our staff or someone " +
      "we engage, never one of your callers — kept with that person's recorded consent. " +
      "A hosting platform does not read any of those things; it runs the container they " +
      "pass through, which is a distinction about purpose and not about access.",
    location:
      "Different for each. The hosted voice platform's published privacy policy, read on " +
      "6 October 2026, says it stores data with a cloud provider in India, and that its " +
      "language-model step may be processed outside India by the model providers it uses; " +
      "it told us in writing on 7 October 2026 that it processes and stores in India, " +
      "which we report as its statement and not as a commitment we hold. The hosting " +
      "platform names the region we would run in only by its own region label: that is " +
      "not a residency commitment we have obtained, NOBODY HERE HAS ESTABLISHED WHICH " +
      "COUNTRY OR CITY IT IS IN, and its own pages cannot be read from our build " +
      "environment. Do not read India into it. The contingency platform's location is not " +
      "verified.",
    status:
      "Core: the hosted voice platform runs every call. Its published policy names its own " +
      "sub-processors — speech, language-model, cloud-hosting, payment and messaging " +
      "companies — and states a default retention of 180 days. It told us in writing on " +
      "7 October 2026 that it will sign a data processing agreement, and that it never " +
      "trains on recordings or transcripts on its two higher paid plans (on its " +
      "pay-as-you-go plan it may, unless switched off on request); until an agreement is " +
      "signed those are its statements, not terms we hold (section 3.7). The hosting " +
      "platform is configured, not enabled, and further from enabled than any other row " +
      "here: there is no account with it, nothing has been deployed to it and no call has " +
      "ever run on it. The contingency platform has been sent nothing and no decision to " +
      "adopt it has been taken.",
  },
  {
    key: "speech-to-text",
    category: "Speech-to-text",
    named: [],
    does:
      "Speech recognition during the call — turning what your caller says into text — " +
      "when calls run on our own call program. Today they run on the hosted voice " +
      "platform, which does this itself, so this company hears no live call at present; " +
      "it still receives every transcript as the post-call extraction row below. It is " +
      "one company, the same as that row and the standby in the language-model row. " +
      "Since 18 September 2026 it no longer produces the voice your caller hears.",
    receives:
      "Call audio and the raw, unredacted transcript. This is the one path that must see " +
      "raw text: a callback-number field needs the actual digits.",
    location:
      "An Indian company, and NOT India for the data. Its published privacy policy " +
      "states that personal data may be transferred to and processed in countries " +
      "outside India, and names United States cloud infrastructure and analytics " +
      "providers, European Union model and security vendors, and other jurisdictions as " +
      "necessary to provide the service — with EU Standard Contractual Clauses, adequacy " +
      "decisions and data-processing agreements as the safeguards. Its India-storage " +
      "commitments cover voice biometric data in its content-studio product and payment " +
      "data, not the ordinary speech traffic our calls generate. So the call audio and " +
      "the transcript may be processed outside India on this leg too.",
    status:
      "Configured, not enabled for live speech recognition while calls run on the hosted " +
      "voice platform; Core again if the service is switched back to our own call " +
      "program. The same company is Core for post-call extraction. Section 3.4 sets out " +
      "what its own terms permit it to do with what it receives, including model training.",
  },
  {
    key: "post-call-extraction",
    category: "Post-call extraction",
    named: [],
    does:
      "The first pass that reads the transcript after a call and pulls the client's " +
      "fields out of it. The same company as the speech-to-text row.",
    receives: "The raw, unredacted transcript.",
    location: "As the speech-to-text row: an Indian company that may process outside India.",
    status: "Core. Section 3.4 applies to it in full.",
  },
  {
    key: "text-to-speech",
    category: "Text-to-speech",
    named: [],
    does:
      "Turns what an agent says into speech during the call, for the dearer of the two " +
      "voice qualities. Today the cheaper quality is spoken by the hosted voice platform " +
      "itself (the voice-platform row), and the dearer one by a separate voice-synthesis " +
      "company on our own account with it: the hosted voice platform sends that company " +
      "the agent's words on our behalf. A second voice-synthesis company is used only " +
      "for the cheaper quality on our own call program, which is not in use, so nothing " +
      "reaches it today. Until 18 September 2026 the cheaper quality was spoken by the " +
      "speech-to-text company; it no longer synthesises anything.",
    receives:
      "The words the agent is about to speak, sent as text a turn at a time — which can " +
      "include a detail the caller has just given, where the agent repeats it back to " +
      "confirm it. Not the caller's own audio, not the transcript of what the caller said, " +
      "not the recording, and nothing from your dashboard.",
    location:
      "NOT VERIFIED for either, and we would rather say so than name a country. Neither " +
      "company's own pages can be read from our build environment. For the dearer " +
      "quality's company, what we hold is a reading of them relayed to us, which records " +
      "no data-residency commitment and no region we could ask for, and records that its " +
      "published privacy policy says its services “are designed for users in the " +
      "United States only and are not intended for users located outside the United " +
      "States” — a statement about who the service is for rather than where data is " +
      "processed. Of the second company we have read only its price list and its " +
      "published software package, which names an address and no region. Assume " +
      "processing outside India.",
    status:
      "Configured, not enabled, for both, and nothing has ever been sent to either. The " +
      "dearer quality's company starts receiving the words of agents on that quality once " +
      "we install our key with the hosted voice platform and a client chooses one of its " +
      "voices. The second company is not used while calls run on the hosted voice " +
      "platform. Section 3.6 is what a client should read before choosing the dearer " +
      "quality.",
  },
  {
    key: "language-models",
    category: "Language models",
    named: [],
    does:
      "On live calls today the model that holds the conversation is run by the hosted " +
      "voice platform, with model providers of its own (the voice-platform row). The " +
      "providers in this row serve the in-app assistant a client's own people open from " +
      "their dashboard, and also hold the conversation during a call when calls run on " +
      "our own call program, which is not in use. Three providers, and a client's " +
      "choice of model is also a choice of provider and place (section 3.3). The default " +
      "is a hyperscale cloud provider's service, which serves both legs, is the " +
      "assistant's fallback for a client whose own model cannot serve it, and runs the " +
      "hourly job that distils durable business facts out of past assistant " +
      "conversations. A second provider is an alternative for the IN-CALL leg only and " +
      "does NOT serve the in-app assistant: nobody here has read that provider's " +
      "published position on what it may do with what an API sends it, and an unread " +
      "position is not a permission. A third serves the call leg, and the assistant only " +
      "while we hold a recorded confirmation that our own account with it is on a plan " +
      "under which it does not train on what is submitted. The speech-to-text company is " +
      "the assistant's standby if no other provider can answer; there it answers in prose " +
      "only, is given none of the assistant's look-up tools, cannot read a client's " +
      "leads, calls or campaigns, and cannot fill in a form or propose a change.",
    receives:
      "On the call leg, on our own call program only, the conversation as it happens — " +
      "everything the caller says, " +
      "turn by turn, as it is said. On the assistant leg, the redacted transcript of a " +
      "call a client asks us to re-read, what a client's user types, and what the " +
      "assistant looks up in that client's own account to answer them: lead names and " +
      "statuses, recent calls with their already-redacted summaries, campaign and agent " +
      "names, counts, and the client's own knowledge content. Phone numbers reach it as " +
      "markers, and no raw transcript and no extraction payload is sent on this leg at " +
      "all. The second provider receives the call leg only. Nothing from the in-app " +
      "assistant reaches it. None of them receives the recording.",
    location:
      "Outside India for all three. The default provider: United States — its East US 2 " +
      "region, by configuration. This has moved twice: until 19 August 2026 the language " +
      "model ran in an Indian cloud region; from 19 August 2026 in a different Indian " +
      "region, in South India; since 22 August 2026 in East US 2. Its endpoint does not name its own " +
      "region, so this is a setting we make and check by hand rather than one a build can " +
      "prove (section 3.2). The second provider: United States, with no Indian region to " +
      "request. The third: global — its developer service names no region we can " +
      "request, so we cannot pin where it processes and do not claim to.",
    status:
      "Core for the default provider, on the assistant leg. The second provider receives " +
      "nothing while calls run on the hosted voice platform. The third serves the " +
      "assistant only under the condition above, and the call leg only on our own call " +
      "program.",
  },
  {
    key: "hosting",
    category: "Cloud hosting and database",
    named: [],
    does: "Runs the application, the background workers and the PostgreSQL database.",
    receives:
      "Everything held in the database: phone numbers, transcripts, summaries, lead " +
      "records, account data.",
    location:
      "{{PRIMARY_HOSTING_LOCATION}} — decided, and nothing has been provisioned yet, " +
      "because no client data is in production. This tier runs outside the live call " +
      "path, so India is not required for it; it was chosen anyway.",
    status: "Core.",
  },
  {
    key: "object-storage",
    category: "Object storage and backups",
    named: [],
    does: "Stores files outside the database, including the database's own backups.",
    receives:
      "Call recordings, exports, the archived raw call documents, the bodies delivered " +
      "to client CRMs, and database backup segments.",
    location:
      "Outside India. We ask the provider to place the bucket in its Asia-Pacific region. " +
      "That is a preference it honours where it can and not a residency commitment — it " +
      "guarantees a jurisdiction only for the European Union, the United States, and " +
      "United States government workloads, and offers no India-only jurisdiction — so " +
      "this data is stored outside India and may be stored outside Asia. We do not name a " +
      "city: the provider documents this region only as Asia-Pacific and does not publish " +
      "which datacentre serves it.",
    status: "Core.",
  },
  {
    key: "edge-network",
    category: "Website edge network",
    named: [],
    does: "Sits in front of the site: TLS, caching and protection against attack.",
    receives: "Every HTTP request, including IP addresses.",
    location: "Global.",
    status: "Core.",
  },
  {
    key: "email",
    category: "Email delivery",
    named: [],
    does: "Transactional email: the hot-lead notification to a client, and operator alerts.",
    receives:
      "The recipient's email address; in a hot-lead notification, the lead's name and " +
      "the call summary. The phone number is masked before the email is composed. " +
      "Operator alerts carry identifiers only.",
    location: "United States.",
    status: "Core. An SMTP server of your own choosing is the alternative and is selectable.",
  },
  {
    key: "monitoring",
    category: "Error monitoring and tracing",
    named: [],
    does:
      "Error and performance monitoring for our own services, and performance traces — " +
      "which request went where and how long each step took — when a deployment is set " +
      "to send them to a tracing collector. No company is chosen for the collector: its " +
      "address is a setting, and it can be a service of ours on our own host or a " +
      "monitoring vendor's.",
    receives:
      "Error reports, timing spans and identifiers. Personal data is stripped before " +
      "anything leaves the process: the redaction pair backs the log formatter, the " +
      "error-reporting hook and breadcrumbs, and traces are redacted at the exporter " +
      "rather than at each call site.",
    location:
      "The error-monitoring provider is operated from outside India. The tracing " +
      "collector is wherever it is configured to run, and nothing is configured.",
    status:
      "Configured, not enabled. Error monitoring activates only when its address is set; " +
      "with no collector address there is no tracing at all. If a monitoring vendor is " +
      "ever chosen for tracing, that is a change notified under clause 5 of the Data " +
      "Processing Addendum.",
  },
  {
    key: "payments",
    category: "Payments — Razorpay",
    named: ["Razorpay"],
    does: "Card, UPI and netbanking payments for self-serve top-ups.",
    receives: "Payer contact details and payment metadata. Card numbers never reach us.",
    location: "India.",
    status: "Configured, not enabled. No merchant account has been confirmed.",
  },
  {
    key: "identity-verification",
    category: "Identity verification",
    named: [],
    does:
      "Verifies a client business owner's Aadhaar or PAN through DigiLocker, when the " +
      "client chooses that route instead of a manual review.",
    receives:
      "The owner's DigiLocker sign-in happens on the provider's page. We receive the " +
      "record the owner chose and the provider's reference. The record can include the " +
      "date of birth, gender, address and contact details, a photo link and, for a PAN, " +
      "the full number; we read it in memory and keep only the name on it, a masked " +
      "Aadhaar or PAN and the reference. We store no document or image from this route.",
    location: "An Indian company; where it processes is not yet confirmed in writing.",
    status:
      "Configured, not enabled. It activates only when the provider's credentials are " +
      "set; until then a client verifies by manual review.",
  },
  {
    key: "knowledge-search",
    category: "Knowledge search",
    named: [],
    does:
      "Stores and searches the knowledge content a client publishes for their agents, for " +
      "the parts of the product that are NOT on a call: the in-app assistant and the " +
      "search over your own records in the dashboard. Nothing on the live call path uses " +
      "it — an agent answers a caller out of a sealed copy of the knowledge held in the " +
      "program running the call. A second company is a contingency for text embeddings, " +
      "needed only if the store adopted does not bundle its own.",
    receives:
      "Every passage of the knowledge a client has published — the text of the FAQs, " +
      "price lists, staff names and contact numbers they uploaded — and the questions " +
      "asked of it: what a client's user types into the in-app assistant, and what they " +
      "search their own records for. Never the call audio, never a transcript, and never " +
      "a recording.",
    location:
      "NOT VERIFIED for the store. It is software we intend to run on our OWN server, in " +
      "which case nothing reaches the company that writes it; its address is a setting, " +
      "so an operator could point it at a service that company runs instead. Nobody here " +
      "has read that company's own terms or retention position: its site cannot be " +
      "reached from our build environment. Either way, the store buys the embedding for " +
      "each question from a model vendor on our account, described in the " +
      "language-model row. The contingency embedding company is outside India.",
    status:
      "Configured, NOT SELECTED: the product ships set to a different store and nothing " +
      "of anybody's has reached this one. Two cautions belong with it: switching it on is " +
      "an operator setting that takes effect on the next request with no release, so this " +
      "row can become live without a code change; and when an account is closed, removing " +
      "its knowledge from this store rests on our own reading of how that software " +
      "deletes, which nobody has been able to check against the company's documentation. " +
      "Our own record of exactly what was sent drives the removal, and the erasure is " +
      "refused outright rather than reported as done if the store will not accept it. The " +
      "embedding company is a contingency and is not selected.",
  },
  {
    key: "messaging",
    category: "WhatsApp messaging — Meta, AiSensy, Interakt",
    named: ["Meta", "AiSensy", "Interakt"],
    does:
      "Sends a WhatsApp message to a lead using an approved template — as a post-call " +
      "follow-up, or as an action the agent triggers during the call. Meta's WhatsApp " +
      "Business service directly, or AiSensy or Interakt as alternative WhatsApp Business " +
      "Solution Providers carrying the in-call action on your behalf.",
    receives:
      "The recipient's phone number and the template's variables — whatever your action " +
      "was configured to fill them with. Never the recording or the transcript.",
    location:
      "Meta: global. AiSensy and Interakt: NOT VERIFIED, and we would rather say so than " +
      "name a country — neither company's documentation could be read from our build " +
      "environment. If you are choosing one of them, ask them directly, and ask us to " +
      "fill this in.",
    status:
      "Configured, not enabled for the post-call follow-up: no messaging provider has " +
      "been chosen for it and the code refuses to send until one is. The in-call action " +
      "is client-enabled — it runs on a credential you supply for your own account with " +
      "the provider you choose. Either way a separate, recorded messaging opt-in is " +
      "required for every recipient, and consent to be called never satisfies it.",
  },
  {
    key: "client-integrations",
    category: "Integrations you connect — Google, Meta",
    named: ["Google", "Meta"],
    does:
      "Three services you connect to your own account: Google Sheets (writes each new " +
      "lead into a sheet you own), Google Calendar (reads free time on a calendar you own " +
      "and books an appointment on it, when your agent has a calendar action), and Meta " +
      "Lead Ads (retrieves the answers a person submitted on your Facebook or Instagram " +
      "lead form, so the agent can call them back). None of them is a model request.",
    receives:
      "Sheets: the lead's fields, including name and — depending on the option you choose " +
      "— the phone number in raw or masked form. Calendar: the appointment's start and " +
      "end time and the event title, which is whichever field you mapped to it, commonly " +
      "the caller's name; the phone number only if you put it in that title yourself. " +
      "Lead Ads: the lead form answers, including name and phone number. Never the " +
      "recording or the transcript.",
    location: "Global.",
    status:
      "Client-enabled. Sheets access is granted by sharing your own document with our " +
      "service account and revoked by un-sharing it. Lead Ads works per lead source, only " +
      "where you have supplied the access token for your own Page. Calendar is " +
      "configured, not enabled: this deployment holds no sign-in client for it yet, and " +
      "every calendar route refuses cleanly until it does; after that it reaches only a " +
      "calendar you connect yourself, and disconnecting it revokes the access.",
  },
];

/**
 * The company names this page may print, derived from `SUBPROCESSOR_CATEGORIES`. Every
 * other sub-processor is unnamed here and listed in the internal register.
 */
export const PUBLICLY_NAMED_SUBPROCESSORS: readonly string[] = [
  ...new Set(SUBPROCESSOR_CATEGORIES.flatMap((row) => row.named)),
];

export const SUBPROCESSORS: LegalDocument = {
  slug: "subprocessors",
  title: "Sub-processors",
  shortTitle: "Sub-processors",
  summary:
    "Every category of third party that processes personal data on our behalf, what " +
    "reaches it, and where it is processed. A named list is available on request.",
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
            "A sub-processor is a third party — a company or an individual — that we " +
            "engage to process personal data as part of delivering the service. Under " +
            "clause 5 of the Data Processing Addendum, this page and the named list " +
            "described in section 4 are the authorised list, and they are what we notify " +
            "changes against.",
        },
        {
          kind: "para",
          text:
            "Sub-processors are listed here by CATEGORY. Each row describes every company " +
            "we use in that category: what it does, what reaches it, where it processes, " +
            "and its status. Where the companies in one category differ — one live and " +
            "one switched off, or one whose location we know and one whose location we " +
            "do not — the row says so rather than giving the better answer for both. We " +
            "name a company only where you pay it or connect it to your own account " +
            "yourself. The names of the rest are available on request (section 4).",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "What is running, and what is only configured",
          text:
            "Since 7 October 2026 the service runs its calls on the hosted voice platform " +
            "described in section 2. This page describes the system as built and " +
            "configured, including parts that are not in use, because a buyer needs the " +
            "whole picture before they sign. The Status column tells you which is which, " +
            "and every entry marked otherwise than Core is one that only starts " +
            "processing when a specific decision is taken — by us or by you.",
        },
        {
          kind: "definitions",
          items: [
            {
              term: "Core",
              detail:
                "In the path for every client. Data reaches this category as soon as the " +
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
                "change notified under clause 5 of the Data Processing Addendum.",
            },
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "Some Location cells say NOT VERIFIED, and that is the honest answer",
          text:
            "The Location column says where the companies in a category process the data " +
            "they receive. Where we have read a company's own published position, it says " +
            "so; where a person confirms it by hand against a console rather than a build " +
            "check, the row says that too, and section 3.2 explains which. Some cells say " +
            "NOT VERIFIED. That is not an oversight we forgot to fill in: those are " +
            "companies nobody here has been able to confirm, on a page whose only job is " +
            "telling you where data goes, and inventing a plausible country would be " +
            "worse than the gap. Every one of them is switched off or one you would have " +
            "to switch on yourself, so nothing reaches it unless somebody decides it does " +
            "— and for the two voice-synthesis companies, section 3.6 says what we do " +
            "know about them and what we still do not.",
        },
      ],
    },
    {
      id: "register",
      heading: "2. The categories",
      blocks: [
        {
          kind: "table",
          caption: "Sub-processor categories, the data each receives, and where it is processed",
          columns: [
            "Category",
            "What it does for us",
            "Personal data it receives",
            "Location",
            "Status",
          ],
          rows: SUBPROCESSOR_CATEGORIES.map((row) => [
            row.category,
            row.does,
            row.receives,
            row.location,
            row.status,
          ]),
        },
      ],
    },
    {
      id: "cautions",
      heading: "3. Seven things a careful reader should know",
      subsections: [
        {
          id: "call-residency",
          heading: "3.1 Where the call is handled, and why that is not India",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "Assume the call itself may be handled outside India",
              text:
                "The hosted voice platform carries the whole call: it answers, hears the " +
                "caller, runs the language model, speaks and records. Its published " +
                "policy places its storage in India and says its language-model step may " +
                "be processed outside India by the model providers it uses; it has told " +
                "us in writing that it processes and stores in India, and we report that " +
                "as its statement. On the dearer voice quality, the agent's words also go " +
                "to a voice-synthesis company whose location we have not verified " +
                "(section 3.6). We copy the recording into our own storage. So a client " +
                "should not assume that the live audio of their calls, or the transcript " +
                "produced from it, stays in India while the call is happening. If the " +
                "service is switched back to our own call program, the conversation runs " +
                "in a container on a hosting platform whose region nobody here has " +
                "placed in a country (section 3.7), and the sound of the call reaches it " +
                "through our telephone carrier, which does not state where it processes " +
                "or stores call data.",
            },
            {
              kind: "para",
              text:
                "What this does NOT change: the first-extraction work after every call " +
                "stays with an Indian company, and so does live speech recognition when " +
                "calls run on our own call program. It does NOT follow that it stays in " +
                "India, and until 27 August 2026 this paragraph let you read it that way. " +
                "That company's own published privacy policy permits it to " +
                "transfer personal data to and process it in countries outside India, " +
                "including on United States cloud infrastructure and with European Union " +
                "model and security vendors; section 3.4 sets that out with what its " +
                "terms allow it to do with the data. What none of it sits alongside any " +
                "more is a language model in India. Until 22 August 2026 this paragraph " +
                "said the model inference itself did not leave the country; since that " +
                "date the language model we run ourselves is in the United States. " +
                "Section 3.2 says what " +
                "moved and what we still promise about it. Our own copy of the recording " +
                "and transcript — the system of record, the one the product reads " +
                "and the one our retention periods govern — is in the storage " +
                "described in the table above.",
            },
            {
              kind: "para",
              text:
                "Until 2 October 2026 this section was about a third-party voice platform " +
                "which documented that it ran calls on United States infrastructure by " +
                "default. That platform is no longer used and has left this list; the " +
                "call is now handled by the platforms described above.",
            },
          ],
        },
        {
          id: "llm-residency",
          heading: "3.2 The language model is no longer in India or with one vendor, and what we still promise",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "Two claims we have withdrawn, not narrowed",
              text:
                "Until 22 August 2026 this page told you that the language model ran in " +
                "an Indian region, and that every model we offered ran with one vendor " +
                "from one account resource. Neither is true any more and we are not " +
                "going to keep the sentences alive with qualifiers: on that date the " +
                "default model's region moved to East US 2, in the United States, " +
                "withdrawing the claim that model inference happens in India; and the " +
                "product now offers models from three providers, so a client's choice of " +
                "model is also a choice of provider and place. What replaced both claims " +
                "is set out below, and it is a promise about our code rather than about a " +
                "country or a single vendor.",
            },
            {
              kind: "para",
              text:
                "Until 19 August 2026 the language model ran on an endpoint whose own " +
                "address contained the region it served, so a check in our build could " +
                "read the region out of the code and fail the release if it were ever " +
                "anything else. The provider we run by default now uses an address that " +
                "contains no region at all: the region is a property of the account " +
                "resource the address points at, not of the address. That is a " +
                "genuinely weaker guarantee than the one we could make in July, and it " +
                "was weaker before the region moved — the two changes are separate and " +
                "we would rather you read both here than infer either later.",
            },
            {
              kind: "para",
              text:
                "What the build still proves, in a shape that survived the move to more " +
                "than one provider: the set of providers our code may reach for the " +
                "language leg is fixed in the source, written down once, and no " +
                "configuration field is allowed to carry a region, an endpoint or a " +
                "provider it does not name. So no change to our software can send the " +
                "language leg to a provider or a place the source does not declare; " +
                "only a reviewed change to that declaration can, and the build refuses " +
                "that change until every other file in the tree agrees with it. What " +
                "moved on 22 August 2026 is which region the default provider names, and " +
                "what changed since is that there is now more than one provider to " +
                "choose between — not whether the set of them is pinned in code.",
            },
            {
              kind: "para",
              text:
                "One thing that sentence does not cover, and we would rather write it " +
                "than let you assume it away. For the leg served from the hyperscale " +
                "provider, the address our code builds names an account resource, and " +
                "which resource it names is an operational setting of ours, not a line " +
                "of code — so an operator pointing the service at a resource created in " +
                "another region would move that leg's processing without any check " +
                "above failing. Nothing else about that region is machine-readable " +
                "either, which is why the reading below is done by a person against that " +
                "specific resource. We treat a move like that as a change of processing " +
                "location, notified under clause 5 of the Data Processing Addendum " +
                "before it takes effect, and not as a settings change that happens to " +
                "have a consequence.",
            },
            {
              kind: "callout",
              tone: "warning",
              title: "Facts a person confirms, not the build",
              text:
                "For the leg served from the hyperscale provider: first, that the " +
                "provider account itself was created in the East US 2 region — the same " +
                "attestation as before, aimed at the current region. Second, that the " +
                "model deployment inside it is the regional kind rather than the " +
                "provider's global default, which would process requests wherever there " +
                "is capacity in the world; that one is unchanged by the move and still " +
                "matters, because a global deployment would put your callers' words in a " +
                "country neither of us has named. Both are read from the provider's " +
                "console by a person, dated and filed as evidence, and neither can be " +
                "seen from the endpoint, from the response, or from any check we could " +
                "write. The other providers a client can choose place their processing " +
                "on their own terms, stated in the language-model row above — one of " +
                "them names no region we could pin at all. We say all of this because a " +
                "document that called it machine-enforced would be overstating it.",
            },
          ],
        },
        {
          id: "byok",
          heading: "3.3 You can choose the model, across providers, and what that means",
          blocks: [
            {
              kind: "para",
              text:
                "While calls run on the hosted voice platform, the model that answers a " +
                "caller is one of that platform's, run with its own providers, and a " +
                "client chooses it by quality level rather than by provider. What follows " +
                "describes the models we run ourselves: the in-app assistant always, and " +
                "the call when calls run on our own call program. Those run under our own " +
                "accounts with each provider, against endpoints our code pins, and the " +
                "program of ours that runs the call holds those credentials.",
            },
            {
              kind: "para",
              text:
                "You can choose which of the models we run your agents use, for your " +
                "whole account or for a single agent, and the product shows a figure " +
                "against each one. This section used to say that choosing a model moved " +
                "which model answered and moved nothing about who processed your " +
                "callers' data or where — that every model on the list was served by " +
                "the same vendor, from the same account resource, in the region named " +
                "on this page. That was written when only one provider was on the " +
                "list, and it is no longer true. The models on offer now run with three " +
                "providers in more than one place, so your choice is a choice of which " +
                "provider handles the language leg and where. The single-vendor, " +
                "single-region promise this section used to make is WITHDRAWN, not " +
                "narrowed. What has NOT changed: the set of providers our code may reach " +
                "at all is fixed in code and moves only by a reviewed change to it, " +
                "never by a control on a screen — ours or yours — and the one operator " +
                "setting that can still reach where a given provider processes is the " +
                "account resource named in section 3.2.",
            },
            {
              kind: "para",
              text:
                "The figure beside each model on THIS page is OUR cost of running that " +
                "model, at the provider's published price, over a minute of a " +
                "five-minute call. We publish it so a choice about quality is not made " +
                "blind to what it costs us. It is not the figure a client sees on their " +
                "own screen, and it is not by itself a charge: what a client pays, and " +
                "whether choosing a model changes it, is clause 6.1 of the Terms of " +
                "Service.",
            },
          ],
        },
        {
          id: "speech-vendor-terms",
          heading: "3.4 What the speech provider's own terms allow, including model training",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "Your call audio may be processed outside India, and the provider's terms permit it to train on what it receives",
              text:
                "We chose an Indian company for the speech leg and that is still true of " +
                "the company. Two things in its own published documents are not what an " +
                "Indian company implies, and this page stated both wrongly until " +
                "27 August 2026. First, its privacy policy says personal data may be " +
                "transferred to and processed in countries outside India, and names " +
                "United States cloud infrastructure and analytics providers, European " +
                "Union model and security vendors, and other jurisdictions as necessary " +
                "to provide the service; the safeguards it names are EU Standard " +
                "Contractual Clauses, adequacy decisions and data-processing agreements. " +
                "Its India-storage commitments cover voice biometric data in its " +
                "content-studio product and payment data, not the ordinary speech traffic " +
                "a call generates. Second, its terms of service (version 2.0, effective " +
                "29 July 2026) permit it, at their paragraph 17.5, to use inputs, outputs " +
                "and usage data to train its machine-learning models — in accordance with " +
                "its privacy policy and applicable law, and where required subject to a " +
                "consent that may be declined or withdrawn, with access to certain of its " +
                "offerings possibly restricted if it is declined. That clause does not " +
                "vary by plan: free credits, pay-as-you-go and paid accounts are treated " +
                "alike.",
            },
            {
              kind: "para",
              text:
                "We have not signed an order form or enterprise agreement with that " +
                "company. Paragraph 6.2 of its terms gives a signed order form precedence " +
                "over the terms, which is the only route by which we could promise you " +
                "something stronger than the paragraph above — so until we have one we " +
                "will not write the stronger sentence. Clause 2 of the Data Processing " +
                "Addendum states what we do and do not promise about training as a " +
                "result, and if a no-training commitment on this leg is a condition of " +
                "your signing, tell us before you sign rather than after.",
            },
            {
              kind: "para",
              text:
                "What that company says about keeping what it receives, so this page is " +
                "complete rather than only corrected. Content submitted through its " +
                "APIs — inputs and outputs — is retained by default for 30 days after " +
                "last access, on a setting it describes as user-configurable; account " +
                "and profile data for the life of the account plus 90 days unless " +
                "earlier deletion is requested in writing; voice samples and models " +
                "until consent is withdrawn plus 30 days; and security incident logs " +
                "for seven years. On a deletion request it says it deletes within " +
                "30 days of verifying the request, except where retention is required " +
                "by law, where the data is needed for ongoing legal proceedings, or " +
                "where technical limitations prevent deletion — in which case it " +
                "anonymises instead. One gap we will not paper over: we have not been " +
                "able to find where in that company's console the 30-day content " +
                "retention is actually changed, so we do not claim to have changed it " +
                "and we do not describe a control we have not found.",
            },
          ],
        },
        {
          id: "in-app-assistant",
          heading: "3.5 What the in-app assistant sends out, and what it keeps",
          blocks: [
            {
              kind: "para",
              text:
                "Section 3 was headed “four things” until 1 September 2026 and " +
                "this is the fifth, added because the assistant inside a client's " +
                "dashboard changed shape and no page a client reads said so. It used to " +
                "do two things: answer questions about the screen in front of it, and " +
                "fill in that screen's fields. It now also looks things up in the " +
                "client's own account — their leads, their recent calls, their " +
                "campaigns, their agents, counts describing how the business is doing, " +
                "and their own knowledge content — and it can propose a small set of " +
                "changes for a person to confirm.",
            },
            {
              kind: "para",
              text:
                "What that means for this page is a change to what the language-model " +
                "provider on the assistant leg receives, and the language-model row " +
                "above says it: what a person types, plus names, statuses, counts and " +
                "already-redacted call summaries from the account. A phone number " +
                "reaches that provider as a marker rather than as digits, and no raw " +
                "transcript and no extracted-field payload is sent on this leg at all — " +
                "those are properties of the code rather than instructions in a prompt, " +
                "which matters because a prompt is not an access control. Which " +
                "providers may serve this leg is narrower than which may run a call: a " +
                "provider serves it only where somebody here has read that provider's " +
                "own published position on training with what it receives, and, where " +
                "the answer depends on which plan our account is on, recorded that " +
                "answer against the account. One offered provider fails that test today " +
                "and the language-model row says so.",
            },
            {
              kind: "para",
              text:
                "The assistant also now keeps something, and the product's own code and " +
                "its own on-screen wording both said it kept nothing until this was " +
                "corrected. It stores what a client's user asked and what it answered, " +
                "per person, and an hourly job reads a run of those back to a language " +
                "model to distil short durable facts about the business. Identifiers are " +
                "stripped before anything is written; that pass catches numbers, not " +
                "names. Those records are deleted after 180 days and entirely when an " +
                "account closes. Section 3.2 of the Privacy Policy describes them, " +
                "section 9 carries the period, and section 12.4 states the one thing an " +
                "erasure request does not do with them.",
            },
          ],
        },
        {
          id: "voice-vendor-terms",
          heading: "3.6 What the voice-synthesis companies' own terms allow, and what we have not established",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "One of them permits training on what it receives and sells its no-retention option only on a plan we cannot buy; of the other we have read nothing but a price list",
              text:
                "Section 3 was headed “five things” until 7 September 2026, and " +
                "this is the sixth: the product gained a second voice quality, spoken by " +
                "a second company, and a client choosing it should read what that " +
                "company's own published documents say before they do. Since " +
                "7 October 2026 calls run on the hosted voice platform, which speaks the " +
                "cheaper quality in its own voices and passes the agent's words for the " +
                "dearer quality to that company, on our own account with it. A third " +
                "company speaks the cheaper quality only on our own call program, which " +
                "is not in use; its own sites cannot be reached from the environment we " +
                "build in, so nobody here has read its position on training, on " +
                "retention, on residency or on anything else it does with what it " +
                "receives, and we state that as the gap it is rather than assuming its " +
                "answers match the company described next. The three things below are " +
                "the dearer quality's company's, all quoted from its documents rather " +
                "than inferred from them. Its privacy policy says it may use information it " +
                "receives to generate output and to train and enhance the models behind " +
                "its services, and offers an opt-out form whose effect is forward-only — " +
                "it stops future use for training and does not reach anything used " +
                "before the day it is submitted. Its zero-retention option, under which " +
                "submitted text and generated audio are not kept at all, is available " +
                "only on its enterprise plan; on the plans we could buy, what it keeps is " +
                "governed by its published data-processing agreement instead, and that " +
                "agreement is where the question is answered rather than by the " +
                "zero-retention option. And its privacy policy states that its services " +
                "“are designed for users in the United States only and are not " +
                "intended for users located outside the United States” — which we " +
                "quote in full because it is an unusual thing for an Indian business's " +
                "supplier to say, and paraphrasing it would soften it.",
            },
            {
              kind: "para",
              text:
                "What we have NOT established, listed rather than left for you to " +
                "assume. We have not established where this vendor processes the text " +
                "we would send it: its published documents, as read to us, name no " +
                "region and make no residency commitment, so the Location cell says so " +
                "instead of naming a country. We have not established the retention " +
                "periods that apply on a plan we could actually buy — only that they " +
                "come from the data-processing agreement and not from the zero-retention " +
                "option. We have not established whether that agreement can be entered " +
                "on a self-serve plan without a sales conversation, so we do not tell " +
                "you that one is in place. Each of those is a question with an answer " +
                "somebody can get, and none of them is a gap we would fill with a " +
                "plausible sentence. For the third company, which would speak the " +
                "cheaper quality on our own call program, the list is shorter and " +
                "worse: we have established none of those things, because its site " +
                "cannot be reached from the environment we build in and the one page of " +
                "its own anybody here has read — its published price list, read on " +
                "19 September 2026 — answers none of them. There is one more: what that " +
                "page gives is a list price and not a bill, so nobody has established " +
                "what one minute of it actually costs us, and no agent can be set to it " +
                "until somebody does. This paragraph " +
                "said until 20 September 2026 that the company publishes no price at " +
                "all, which was a page we had not found written down as a fact about the " +
                "company, and we would rather correct it here than quietly.",
            },
            {
              kind: "para",
              text:
                "Two limits on all of the above, both of which cut in your favour. " +
                "First, nothing has been sent to either of these companies from this " +
                "system: no voice of either company can be selected yet, and the " +
                "product refuses rather than silently working. The dearer quality's " +
                "company becomes selectable only once we install our key with the hosted " +
                "voice platform. Second, when one of them does become selectable it " +
                "receives only the words your agent speaks — never the caller's audio, " +
                "the transcript, the recording, or anything from your dashboard — so the " +
                "material above bears on what your agent says, which can include a " +
                "detail it repeats back to a caller, and not on the call as a whole. " +
                "This paragraph used to end by telling a client who would rather it did " +
                "not apply to them at all that they could keep every agent on the other " +
                "voice quality. That is withdrawn, not reworded: since 18 September 2026 " +
                "the other quality is spoken by the third company described above rather " +
                "than by the company whose terms section 3.4 sets out, so choosing " +
                "between the two voice qualities is no longer a way of keeping synthesis " +
                "with a company whose position anybody has read. While calls run on the " +
                "hosted voice platform, an agent on the cheaper quality sends nothing to " +
                "either company in this section: its voice is made by that platform and " +
                "the providers it uses, which it has not named to us voice by voice, so " +
                "that is not a refuge either — only a different recipient, described in " +
                "the voice-platform row. What is true of both companies here, and is the " +
                "limit that matters today, is the sentence this paragraph opens with: " +
                "nothing has been sent to either of them.",
            },
          ],
        },
        {
          id: "call-runtime",
          heading: "3.7 The platforms the call runs on, and what we have not established about them",
          blocks: [
            {
              kind: "callout",
              tone: "warning",
              title: "The call runs on a hosted voice platform, and its commitments are statements until a contract is signed",
              text:
                "Section 3 was headed “six things” until 15 September 2026, " +
                "and this is the seventh. The design of the call has changed twice. It " +
                "used to be that a voice platform took the call, ran the conversation " +
                "with models it chose on our behalf, and handed us a transcript " +
                "afterwards — a platform this list no longer includes, because it is no " +
                "longer used. The call was then moved to a program of OURS, running in a " +
                "container on a hosting platform, which is still built and kept as the " +
                "alternative. Since 7 October 2026 the call runs on a hosted voice " +
                "platform instead: it answers on numbers it rents to us, hears the " +
                "caller, runs the model, speaks and records, and we configure the agent " +
                "and receive the results. Either way a company other than us is on the " +
                "most sensitive path in the product, which is why this has a section " +
                "rather than a footnote.",
            },
            {
              kind: "para",
              text:
                "What we know about the hosted voice platform. Its published privacy " +
                "policy, read on 6 October 2026, says it stores data with a cloud " +
                "provider in India, that its language-model step may be processed " +
                "outside India by the model providers it uses, that it relies on " +
                "speech, language-model, cloud-hosting, payment and messaging companies " +
                "of its own, and that its default retention is 180 days. Its founder " +
                "told us in writing on 7 October 2026 that it will sign a data " +
                "processing agreement under Indian data-protection law; that recordings " +
                "and transcripts are never used for training on its two higher paid " +
                "plans, and on its pay-as-you-go plan may be unless it is switched off " +
                "on request; that recordings are kept for 30 to 75 days depending on the " +
                "plan and transcripts until deleted; and that it processes and stores in " +
                "India. Until a data processing agreement is signed, those are its " +
                "statements and not terms we hold, and we represent nothing beyond them.",
            },
            {
              kind: "para",
              text:
                "What we have NOT established about the hosting platform our own call " +
                "program would run on, stated plainly because a list that guesses is " +
                "worth less than one that names its gaps. Which legal entity operates " +
                "the platform, and in which country it is established: not established. " +
                "Where the region it labels for us physically is: not established — a " +
                "region label is not a residency commitment. What its terms permit it " +
                "to do with what passes through it, including whether anything may be " +
                "used to train a model: not established. How long anything is kept, and " +
                "whether any of it is kept at all once a call ends: not established. " +
                "Whether a data-processing agreement can be entered with it, and on what " +
                "plan: not established. Which other companies it relies on in turn: not " +
                "established. Every one of those is a question with an answer somebody " +
                "can obtain from the company's own documents, and not one of them is a " +
                "gap we will fill with a plausible sentence.",
            },
            {
              kind: "para",
              text:
                "Why we cannot simply look: that company's documentation host and its " +
                "own site both refuse a connection from the environment this software " +
                "is built in — measured again on 15 September 2026, with the same " +
                "result as every earlier attempt. That is the same reason the messaging " +
                "providers' and both voice-synthesis companies' locations say NOT " +
                "VERIFIED rather than naming a country. The answers are not secret; " +
                "they are simply not ours to assert until a person has read them, and " +
                "this page would rather be short of a fact than confident about one.",
            },
            {
              kind: "para",
              text:
                "One limit in your favour, and one that is not. In your favour: nothing " +
                "has reached the hosting platform from this system — no call has ever " +
                "run on it — and the record of every call that we keep afterwards is in " +
                "our own database and storage. Not in your favour, and stated rather " +
                "than left for you to work out: the hosted voice platform handles the " +
                "caller's AUDIO on every call, which is the one category on this page " +
                "that cannot be redacted, masked or summarised on its way past.",
            },
          ],
        },
      ],
    },
    {
      id: "named-list",
      heading: "4. The named list",
      blocks: [
        {
          kind: "para",
          text:
            "A named list of our current sub-processors — each company, the category it " +
            "is in, what it receives, where it processes and its status — is available " +
            "on request. Email {{DATA_PROTECTION_CONTACT_EMAIL}}. It carries the same " +
            "facts as the table above, company by company, and it is the list the " +
            "notices in section 5 are given against: a new company in a category already " +
            "on this page is notified exactly as a new category would be.",
        },
      ],
    },
    {
      id: "changes",
      heading: "5. Changes to this list",
      blocks: [
        {
          kind: "para",
          text:
            "We will give clients at least 30 days' notice by email before a new " +
            "sub-processor starts processing their data, or before an existing one moves " +
            "to a materially different location. A client who reasonably objects on data " +
            "protection grounds may raise it with us under clause 5 of the Data " +
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
            "and the only reason it cost nothing is that no client account was live, so " +
            "there was nobody owed 30 days' notice and nobody with a right to object. " +
            "We would rather write that than let the change look free. With a client " +
            "live, the same move would have to be notified by email 30 days " +
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
