import type { LegalDocument } from "./types";

/**
 * The Acceptable Use Policy, and the telecom half is the document.
 *
 * A generic AUP — no spam, no malware, no illegal content — would be true and useless
 * here. The obligations that will actually get a Calevate client disconnected are Indian
 * telecom obligations that attach to THEM as the registered Principal Entity, and half of
 * them are enforced by gates in this product that refuse a campaign by name. So each rule
 * below names the blocker string the product returns when it stops you, which means a
 * client reading this page, a support agent reading a refusal, and the test suite are all
 * using the same vocabulary.
 */
export const ACCEPTABLE_USE: LegalDocument = {
  slug: "acceptable-use",
  title: "Acceptable Use Policy",
  shortTitle: "Acceptable Use",
  summary:
    "What you must have in place before Calevate places a call for you, and what you " +
    "may not use it for.",
  appliesTo:
    "Every Calevate client and everyone they give access to. It forms part of the Terms " +
    "of Service.",
  sections: [
    {
      id: "scope",
      heading: "1. Scope, and the one thing to take away",
      blocks: [
        {
          kind: "para",
          text:
            "This policy applies to everything you do with Calevate. Breaching it is a " +
            "breach of the Terms of Service, and clause 5 of this policy sets out what " +
            "we do about it.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "The registrations are yours, and the liability follows them",
          text:
            "Under India's commercial-communications framework, the business on whose " +
            "behalf a call is made is the Principal Entity (PE) and is registered as " +
            "such. Calevate is the registered Telemarketer (TM) linked to your " +
            "registration. That is not an administrative detail: the calls go out under " +
            "your identity, on templates registered in your name, and enforcement — " +
            "warnings, usage caps, suspension of your telecom resources, blacklisting — " +
            "lands on you. We build the gates and refuse the launch when a gate is not " +
            "green. We cannot take the obligation off you and we will not pretend to.",
        },
        {
          kind: "para",
          text:
            "Calevate is an India-only service. It is for businesses established in " +
            "India, calling recipients in India. We do not offer outbound calling to " +
            "numbers outside India, and the product refuses to dial a destination that is " +
            "not an Indian (+91) number — a non-Indian destination is not a setting you " +
            "can turn on. This is a deliberate scope limit, not a temporary gap.",
        },
      ],
    },
    {
      id: "telecom",
      heading: "2. Before we will dial for you",
      subsections: [
        {
          id: "registrations",
          heading: "2.1 Registrations — three of them, and none implies another",
          blocks: [
            {
              kind: "para",
              text:
                "The instrument behind everything in this section 2 is the Telecom " +
                "Commercial Communications Customer Preference Regulations, 2018 (as " +
                "amended), made by the Telecom Regulatory Authority of India. It is " +
                "what creates the Principal Entity and Telemarketer roles, the " +
                "registration of headers and templates, the number series in section " +
                "2.2, the preference registers in section 2.3 and the calling window in " +
                "section 2.4. We name it once, here, so that your adviser can read our " +
                "obligations against the regulation rather than against our summary of " +
                "it; the rest of this policy calls it the commercial-communications " +
                "framework.",
            },
            {
              kind: "para",
              text:
                "The Telecommunications Act 2023 sits behind that framework and is worth " +
                "knowing about even though it does not address you or us directly. Its " +
                "section 28 places the duties about unsolicited \"specified messages\" — " +
                "prior consent, and the do-not-disturb registers — on the licensed " +
                "access provider, which is your telephone operator, rather than on a " +
                "Principal Entity or a Telemarketer. They reach the two of us through " +
                "the 2018 regulations above and through the terms of the connection you " +
                "hold in your own name, which is also why the identity checks in section " +
                "2.8 attach to a telecom connection rather than to your Calevate account.",
            },
            {
              kind: "para",
              text:
                "A campaign will not launch until all of these exist and are active. The " +
                "product checks each one separately and tells you which is missing.",
            },
            {
              kind: "list",
              ordered: true,
              items: [
                "Our Telemarketer registration ({{DLT_TELEMARKETER_ID}}). Ours to obtain; " +
                  "the blocker is `tm_registration_missing`, it is false for every client " +
                  "at once, and until it clears nobody on the platform dials out.",
                "Your Principal Entity registration, and the active link between it and " +
                  "our Telemarketer registration. Yours to obtain; we run the process for " +
                  "you as part of onboarding. The blockers are " +
                  "`pe_registration_missing`, `pe_registration_not_active` and " +
                  "`tm_link_not_active`, in that order — an authorisation cannot be active " +
                  "for a registration that does not exist.",
                "The number you are calling from, and the header registered against it " +
                  "(`number_not_registered`). The connection must be one you hold in " +
                  "your own name with an Indian operator — you are the subscriber of " +
                  "record for it, not us, and we neither sell nor rent telephone " +
                  "numbers. A header registered to somebody else, or registered for one " +
                  "class of message and used for another, is the same category of breach " +
                  "as the number-series misuse in section 2.2. You also need an approved " +
                  "voice template for the kind of campaign you are running " +
                  "(`dlt_template_missing`, `dlt_template_not_approved`, " +
                  "`dlt_template_mismatch`).",
              ],
            },
            {
              kind: "para",
              text:
                "Answering your incoming calls is never gated on any of this. These rules " +
                "are about calls that go out.",
            },
          ],
        },
        {
          id: "series",
          heading: "2.2 The number series must match what the call actually is",
          blocks: [
            {
              kind: "para",
              text:
                "Promotional calls go out on a 140-series number. Transactional and " +
                "service calls go out on the 160 series or a standard number. You " +
                "classify each campaign and the product refuses a mismatch " +
                "(`number_series_mismatch`, `number_missing`).",
            },
            {
              kind: "callout",
              tone: "warning",
              title: "Misclassification is the most common way to lose a registration",
              text:
                "Labelling a promotional campaign as transactional to reach people who " +
                "have opted out of promotions is not a shortcut, it is the specific abuse " +
                "the number series exists to prevent, and it is the failure mode " +
                "registrations are revoked for. Do not do it. If you do it, we will stop " +
                "your account.",
            },
            {
              kind: "para",
              text:
                "Service calls may not carry a sales message. An agent on a service or " +
                "160-series line is topic-fenced and the regression suite asserts that it " +
                "refuses promotional turns. Do not configure around that.",
            },
          ],
        },
        {
          id: "dnd",
          heading: "2.3 Do-not-disturb and do-not-call",
          blocks: [
            {
              kind: "para",
              text: "Three separate suppression checks run, and they are not the same thing.",
            },
            {
              kind: "definitions",
              items: [
                {
                  term: "The national customer preference register",
                  detail:
                    "Held on the access providers' DLT platform, not by us — the " +
                    "preference database itself is not made available to telemarketers. " +
                    "The platform scrubs a list you submit and returns a reference, a " +
                    "count and a verdict valid until 23:59:59 that day. A promotional " +
                    "campaign will not launch, and will not keep dialling, without a " +
                    "current scrub: `national_dnd_scrub_missing`, " +
                    "`national_dnd_scrub_expired` (the run aged past its IST day) or " +
                    "`national_dnd_scrub_incomplete` (contacts were added after it ran). " +
                    "The check runs again on every dispatch tick, because the validity " +
                    "window ends at midnight while a campaign keeps going.",
                },
                {
                  term: "Your own do-not-call list",
                  detail:
                    "Every contact on it is marked blocked before a campaign starts " +
                    "running, and the launch stamps the time the scrub happened. If " +
                    "nothing survives the scrub the campaign is refused as " +
                    "`all_contacts_dnc`.",
                },
                {
                  term: "A platform-wide suppression",
                  detail:
                    "A number a regulator, an access provider or we ourselves have " +
                    "permanently blocked. It applies to every client and you cannot add " +
                    "to it or remove from it.",
                },
              ],
            },
            {
              kind: "para",
              text:
                'When somebody says "do not call me again" during a call, the agent adds ' +
                "them to your do-not-call list there and then, and a second pass over the " +
                "transcript after the call catches anything the first layer missed. The " +
                "regulations allow up to twenty-four hours for that to take effect; we " +
                "hold ourselves to before the next dispatch tick, which is thirty seconds. " +
                "You may not remove somebody from your do-not-call list because they have " +
                "since become a lead again.",
            },
          ],
        },
        {
          id: "hours",
          heading: "2.4 Calling hours",
          blocks: [
            {
              kind: "para",
              text:
                "Outbound calls are placed between 09:00 and 21:00 India Standard Time. " +
                "The gate refuses a dial outside that window and the contact is retried in " +
                "the next one. A campaign may narrow the window further; it may not widen " +
                "it. Do not ask us to.",
            },
          ],
        },
        {
          id: "consent",
          heading: "2.5 Where your list came from",
          blocks: [
            {
              kind: "para",
              text:
                "Every campaign must record where the contacts came from and when consent " +
                "was obtained. A campaign whose source has not been declared is refused as " +
                "`consent_provenance_missing`.",
            },
            {
              kind: "callout",
              tone: "warning",
              title: "Purchased lists are refused, in writing, as policy",
              text:
                'The source options deliberately include "purchased list". That is not ' +
                "an oversight and it is not an invitation: the option exists so that the " +
                "answer can be given honestly and then refused (`consent_source_refused`). " +
                "A list of options containing only acceptable answers does not stop " +
                "purchased lists, it hides them behind whichever option sounds nearest. " +
                "If your list was bought, scraped, harvested from a directory, or obtained " +
                "from a third party without the people on it agreeing to be contacted by " +
                "you, do not upload it to Calevate.",
            },
            {
              kind: "para",
              text:
                "You must be able to produce, for any number on any list you upload, when " +
                "and how that person agreed to be contacted by you, and by what means. You " +
                "warrant that you can. We may ask.",
            },
          ],
        },
        {
          id: "disclosure",
          heading: "2.6 Telling people they are speaking to an AI, and that the call is recorded",
          blocks: [
            {
              kind: "para",
              text:
                "Each agent has two settings: whether it announces that it is an AI " +
                "assistant at the start of a call, and whether it announces that the call " +
                "is being recorded. Both apply on incoming and outgoing calls and both are " +
                "yours to set.",
            },
            {
              kind: "callout",
              tone: "note",
              title: "What the setting does not do",
              // Deliberately the SAME sentence as the Privacy Policy's §5 callout. This
              // is an operative commitment stated in two documents, and a client's
              // adviser comparing them must not have to wonder whether a difference in
              // wording is a difference in meaning.
              text:
                "It does not change what the agent says when it is asked. If a caller " +
                "asks whether they are speaking to a machine, an AI, a bot or a " +
                "recording, the agent answers truthfully. If a caller asks whether the " +
                "call is being recorded, the agent answers truthfully. That behaviour is " +
                "enforced above your prompt, on our side of the system, and cannot be " +
                "overridden by anything you write into your agent's instructions. " +
                "Attempting to write around it is a breach of this policy.",
            },
            {
              kind: "para",
              text:
                "The decision about whether your calls need to announce either thing is " +
                "yours, because the obligation is yours. You are the Data Fiduciary for " +
                "the conversation and the registered Principal Entity for the call. Indian " +
                "courts have treated recording a call without the other party's knowledge " +
                "as an interference with the right to privacy, a draft TRAI amendment on " +
                "commercial communications is under consultation, and if you call anyone " +
                "in the EU the AI Act's transparency duty for AI systems that interact " +
                "with people has applied since 2 August 2026. Take your own advice. Our " +
                "default recommendation is to leave both announcements on.",
            },
            {
              kind: "para",
              text:
                "Whether the disclosure line was actually spoken is measured against each " +
                "call's transcript and shown on the call record, so you have evidence " +
                "either way. What you do NOT have, and this paragraph claimed until " +
                "22 August 2026: a caller declining recording does not stop the " +
                "recording. Nothing in the product can stop one mid-call, and the voice " +
                "platform reports no per-call recording decision, so a decline is " +
                "something your agent hears and you act on — not a control the platform " +
                "operates for you. Every call an agent handles is recorded, the agent " +
                "says so when asked, and a caller who wants the audio gone is an erasure " +
                "request you can run from your own screen.",
            },
            {
              kind: "callout",
              tone: "warning",
              title: "An open question about recordings that your adviser should see",
              text:
                "Raised here because it belongs to the decision you are making in this " +
                "section, not because we have an answer. The 2011 " +
                "sensitive-personal-data rules define biometric information to include " +
                "voice patterns, and sensitive personal data carries a stricter transfer " +
                "test than ordinary personal data. Whether the recording of an ordinary " +
                "business call is biometric information for that purpose has never been " +
                "decided by an Indian court or by a regulator. If it is, the stricter " +
                "test reaches every call your agents handle — and it reaches the live " +
                "conversation, not only the stored file. We are not resolving it for " +
                "you and we are not resolving it for us: it is with the advocate whose " +
                "review these documents are waiting on, and clause 9 of the Data " +
                "Processing Addendum sets it out in full, with the privacy notice's " +
                "section 8 saying the same thing to a caller.",
            },
          ],
        },
        {
          id: "messaging",
          heading: "2.7 WhatsApp and other messaging is a separate permission",
          blocks: [
            {
              kind: "para",
              text:
                "A business-initiated WhatsApp message needs its own opt-in, recorded with " +
                "its source and its date. Consent to be called never satisfies it, a " +
                "campaign's consent provenance never satisfies it, and nothing backfills " +
                "it. A stale opt-in stops authorising messages when its validity window " +
                "closes. The messaging gate is in addition to the do-not-call check, never " +
                "instead of it.",
            },
          ],
        },
        {
          id: "identity",
          heading: "2.8 Identity verification",
          blocks: [
            {
              kind: "para",
              text:
                "Self-serve and trial accounts must pass identity verification against a " +
                "public-registry document before they dial out (`kyc_missing`, " +
                "`kyc_not_verified`), and every account must pass it before buying a " +
                "phone number, because the obligation attaches to the telecom connection. " +
                "The first campaign on a self-serve or trial account is reviewed by a " +
                "person before it runs (`first_campaign_review_pending`). Do not open a " +
                "second account to get around a hold: the hold is on the account and a " +
                "new one is a breach of the Terms.",
            },
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "3. What you may not use Calevate for",
      blocks: [
        {
          kind: "list",
          items: [
            "Anything unlawful, or anything that would make a call unlawful — including " +
              "impersonating another business, a government body, a bank or a person.",
            "Deceiving people about who is calling or why. The agent must identify the " +
              "business it is calling for.",
            "Debt collection conducted by intimidation, harassment or repeated calling; " +
              "any threat; any abuse.",
            "Fraud, phishing, or eliciting one-time passwords, card numbers, Aadhaar " +
              "numbers, PAN numbers, bank credentials or passwords. Agents are configured " +
              "not to ask for these and you may not reconfigure them to.",
            "Medical, legal or financial advice presented as coming from a qualified " +
              "human, or any claim that the agent is a person.",
            "Political messaging, religious solicitation or opinion polling dressed as a " +
              "service call.",
            "Content that is obscene, defamatory, or that incites hatred or violence.",
            "Anything targeting children, or any service where you know the caller is " +
              "likely to be a child, without taking your own advice on parental consent " +
              "first.",
            "Uploading anyone else's personal data into your agent's knowledge base, or " +
              "into a prompt, without a basis for doing so — that content is answered from " +
              "on live calls and is not searched by an erasure request.",
            "Reselling access, or operating the service on behalf of a third party, " +
              "without our written agreement — the registrations are per Principal Entity " +
              "and a call placed for somebody else's business under your registration is " +
              "a breach of the telecom rules as well as of this policy.",
            "Placing calls to numbers outside India, or using the service for a business " +
              "not established in India. Calevate is India-only (section 1); the product " +
              "refuses a non-Indian destination number.",
          ],
        },
      ],
    },
    {
      id: "technical",
      heading: "4. Technical conduct",
      blocks: [
        {
          kind: "list",
          items: [
            "Do not attempt to reach another client's data, or to test whether you can.",
            "Do not probe, scan or attack the service, or attempt to bypass a rate limit, " +
              "a spend ceiling, a compliance gate or an authentication control. If you " +
              "find a way to, tell us at {{SECURITY_CONTACT_EMAIL}} — we will not pursue " +
              "anyone who reports a genuine finding in good faith and gives us a " +
              "reasonable chance to fix it.",
            "Do not write agent instructions designed to make the agent break a rule this " +
              "policy states, including instructions that tell it to deny being an AI.",
            "Do not share credentials or API keys, and do not leave a webhook signing " +
              "secret in client-side code.",
            "Do not use automated means to extract data from the product beyond the " +
              "exports and the API we provide.",
          ],
        },
      ],
    },
    {
      id: "enforcement",
      heading: "5. How this is enforced",
      blocks: [
        {
          kind: "para",
          text:
            "Most of section 2 is enforced automatically, before a call is placed rather " +
            "than after a complaint arrives. A campaign that fails any gate does not " +
            "launch, and the gates are re-checked on every dispatch tick so a campaign " +
            "that was compliant at launch stops if it stops being compliant.",
        },
        {
          kind: "para",
          text: "Where we act by hand, in escalating order:",
        },
        {
          kind: "list",
          ordered: true,
          items: [
            "We contact you and ask you to fix it.",
            "We hold your account's campaigns, which refuses every campaign until a " +
              "person releases the hold.",
            "We suspend outbound dialling for your account. Your incoming calls keep being " +
              "answered — dropping those would punish your customers for something you did.",
            "We halt all outbound dialling across the platform, if the problem is ours or " +
              "is systemic.",
            "We terminate, under the Terms of Service.",
          ],
        },
        {
          kind: "para",
          text:
            "We will act without notice where a regulator or an access provider instructs " +
            "us to, where there is a live risk to people being called, or where waiting " +
            "would expose us or another client to enforcement. Otherwise we will tell you " +
            "first.",
        },
      ],
    },
    {
      id: "reporting",
      heading: "6. Reporting a problem",
      blocks: [
        {
          kind: "para",
          text:
            "If you received a call you should not have, tell us at {{SUPPORT_EMAIL}} " +
            "with the number that called you, the number it reached and the approximate " +
            "time. We can identify the client and act. You may also complain to your own " +
            "telephone operator, who has a statutory complaint channel for unsolicited " +
            "commercial communications, and to TRAI. Nothing here asks you to come to us " +
            "first, and complaining to us does not affect any other remedy.",
        },
        {
          kind: "para",
          text: "Security reports go to {{SECURITY_CONTACT_EMAIL}}.",
        },
      ],
    },
  ],
};
