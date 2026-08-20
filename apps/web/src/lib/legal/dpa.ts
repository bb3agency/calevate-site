import type { LegalDocument } from "./types";

/**
 * The Data Processing Addendum — Calevate as Processor, the client as Fiduciary.
 *
 * Written against the DPDP Act's own vocabulary rather than the GDPR's, because the
 * instrument that binds here is section 8(1)-(2): the Fiduciary is responsible for
 * processing carried out on its behalf and may engage a Processor only under a valid
 * contract, and rule 6 of the DPDP Rules 2025 requires that contract to impose equivalent
 * security safeguards. Annex B is therefore not a marketing list — it is the clause that
 * makes rule 6(f) satisfiable, and every measure in it is one that exists in the code
 * today. Where a measure is aspirational it is absent, and where a limit is real it is in
 * clause 9 or clause 12.
 */
export const DPA: LegalDocument = {
  slug: "dpa",
  title: "Data Processing Addendum",
  shortTitle: "Data Processing Addendum",
  summary:
    "The contract term that governs how Calevate processes your callers' personal data " +
    "as your Data Processor.",
  appliesTo:
    "Every Calevate client. It forms part of the Terms of Service and applies " +
    "automatically — you do not need to sign a separate copy, though we will sign one if " +
    "your procurement requires it.",
  sections: [
    {
      id: "roles",
      heading: "1. Roles, scope and precedence",
      blocks: [
        {
          kind: "para",
          text:
            "This Addendum applies whenever we process personal data on your behalf. For " +
            "that data you are the Data Fiduciary and we are your Data Processor within " +
            "the meaning of the Digital Personal Data Protection Act 2023. Section 8(1) of " +
            "that Act makes you responsible for compliance in respect of processing carried " +
            "out on your behalf; this Addendum is the contract section 8(2) requires " +
            "before you may engage us at all.",
        },
        {
          kind: "para",
          text:
            "For your own account data — the identities of your users, your organisation " +
            "record, your billing and tax details — we are the Data Fiduciary, this " +
            "Addendum does not apply, and the Privacy Policy governs.",
        },
        {
          kind: "para",
          text:
            "Where this Addendum conflicts with the Terms of Service on the handling of " +
            "personal data, this Addendum governs.",
        },
      ],
    },
    {
      id: "instructions",
      heading: "2. Processing on your instructions",
      blocks: [
        {
          kind: "para",
          text:
            "We process your callers' personal data only on your documented instructions, " +
            "and for no other purpose. Your instructions are: these documents, the " +
            "configuration you set in the product (your agents, their prompts, your " +
            "extraction schema, your retention periods, your integrations), and any " +
            "further written instruction we accept.",
        },
        {
          kind: "list",
          items: [
            "We do not use your callers' personal data for our own purposes.",
            "We do not use it to train, fine-tune or evaluate any model, ours or a " +
              "vendor's, and our vendor arrangements are selected so that submitted content " +
              "is not used to improve the vendor's products. One consumer-tier model " +
              "interface was disqualified outright on this ground, and the code refuses the " +
              "credential that would reach it.",
            "We do not pool it across clients, sell it, or share it for anyone's marketing.",
            "If we believe an instruction of yours breaks the law, we will tell you and " +
              "may decline to act on it. Several such refusals are automatic — the " +
              "compliance gates described in the Acceptable Use Policy — and they are not " +
              "waivable, including for testing.",
          ],
        },
      ],
    },
    {
      id: "confidentiality",
      heading: "3. Confidentiality and personnel",
      blocks: [
        {
          kind: "list",
          items: [
            "Everyone we allow near your data is bound by confidentiality obligations that " +
              "survive their engagement.",
            "Access is on a need-to-know basis, granted by role, and the map from every " +
              "endpoint to the permission it requires is asserted when the service starts " +
              "rather than reviewed by eye.",
            "Our operators may view your account read-only, in order to support you. That " +
              "access requires multi-factor authentication enforced by the server, plus a " +
              "short-lived signed grant naming that one operator and your account, and it " +
              "cannot make changes. Two audit entries are written: one when the authority " +
              "is issued, one when data is actually read.",
            "Reading an unredacted transcript, or the exact body delivered to your own " +
              "system, is a higher permission and always writes an audit entry.",
          ],
        },
      ],
    },
    {
      id: "security",
      heading: "4. Security",
      blocks: [
        {
          kind: "para",
          text:
            "We implement and maintain the technical and organisational measures set out " +
            "in Annex B, which are designed to meet the standard rule 6 of the DPDP Rules " +
            "2025 describes: securing personal data by encryption, obfuscation or masking; " +
            "controlling access to the systems that hold it; keeping logs and monitoring so " +
            "that unauthorised access can be detected, investigated and prevented from " +
            "recurring; and being able to continue processing if confidentiality, integrity " +
            "or availability is compromised.",
        },
        {
          kind: "para",
          text:
            "We may change a measure, provided the overall level of protection is not " +
            "reduced.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "No certification is claimed",
          text:
            "Calevate holds no ISO 27001 certificate, no SOC 2 report and no equivalent " +
            "third-party attestation, and has not been independently penetration-tested. " +
            "The backup and restore mechanism exists and its restore drill has not yet " +
            "been passed. This clause is the commitment; Annex B is what stands behind it; " +
            "neither is a certificate and we will not describe them as one.",
        },
      ],
    },
    {
      id: "subprocessors",
      heading: "5. Sub-processors",
      blocks: [
        {
          kind: "para",
          text:
            "You authorise us to engage the sub-processors listed on the sub-processor " +
            "page, which is incorporated into this Addendum. Each one is engaged under a " +
            "written contract imposing data protection obligations equivalent to these, " +
            "and we remain responsible to you for their performance.",
        },
        {
          kind: "para",
          text:
            "We will give you at least 30 days' notice by email before a new sub-processor " +
            "begins processing your data, or before an existing one moves to a materially " +
            "different location. You may object on reasonable data protection grounds " +
            "within that period. If we cannot offer a workaround you may terminate the " +
            "affected part of the service without penalty for the remainder of the term, " +
            "and we will refund prepaid unused fees for it. A like-for-like replacement " +
            "made in an emergency may happen without notice, and we will tell you within " +
            "72 hours.",
        },
      ],
    },
    {
      id: "rights",
      heading: "6. Helping you answer your callers",
      blocks: [
        {
          kind: "para",
          text:
            "The rights of a data principal are exercised against you, not against us. We " +
            "will help you answer them, and the help is built into the product rather than " +
            "being a support ticket:",
        },
        {
          kind: "list",
          items: [
            "A subject access export, keyed to a phone number, containing the call " +
              "records, the redacted transcripts, the lead record and the consent entries " +
              "held about that person. Recordings are reported as present or absent rather " +
              "than as a link, and phone-shaped values belonging to other people are masked " +
              "so that honouring one person's right does not disclose another's data.",
            "An erasure request that locates the person across calls, transcript turns, " +
              "extractions, leads, campaign contact lists, the bodies delivered to your own " +
              "systems and the archived raw call documents, carries out the erasure, and " +
              "produces a certificate recording what was done, where, when, and with " +
              "per-record hashes as evidence. The certificate is yours to hand to the " +
              "person who asked.",
            "Correction: you can edit a lead record directly.",
          ],
        },
        {
          kind: "para",
          text:
            "If a data principal contacts us directly we will not act on their instruction " +
            "— we have no authority to — but we will pass it to you promptly and tell them " +
            "we have done so.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "What an erasure does not reach, stated here and on every certificate",
          text:
            "Append-only consent, billing and audit ledgers are retained, and the consent " +
            "ledger carries the number, because it is the evidence the calls were lawful. " +
            "Call rows survive with their personal fields cleared so billed minutes stay " +
            "countable. A recording younger than the 90-day retention floor is not " +
            "destroyed early: the link to it is cleared at once, a destruction date is " +
            "fixed when the request runs, and the audio is destroyed on that date without a " +
            "second request. Copies held by the voice platform are reported as unconfirmed, " +
            "because their deletion interface is undocumented and we will not certify a " +
            "deletion we cannot show. Knowledge content you uploaded is not searched. " +
            "Backups age out on their own 35-day cycle.",
        },
      ],
    },
    {
      id: "breach",
      heading: "7. Personal data breach",
      blocks: [
        {
          kind: "list",
          items: [
            "We will notify you without undue delay, and in any event within 48 hours of " +
              "becoming aware of a personal data breach affecting your data. The window is " +
              "shorter than your own 72-hour reporting obligation to the Data Protection " +
              "Board on purpose: you need time to act on what we tell you.",
            "The notification will describe what happened, when, which categories of data " +
              "and roughly how many data principals are affected, the likely consequences, " +
              "what we have done and what we propose to do, and a contact for further " +
              "questions. Where we do not yet know something we will say so and follow up " +
              "rather than delay the first notification.",
            "We will help you meet your own obligations to the Board and to affected data " +
              "principals, including with the forensic record: the audit chain, the " +
              "delivery log and the access records.",
            "We will not make a public statement identifying you without your agreement, " +
              "unless the law requires it.",
          ],
        },
      ],
    },
    {
      id: "retention",
      heading: "8. Retention, return and deletion",
      blocks: [
        {
          kind: "para",
          text:
            "We retain your callers' personal data for the periods configured on your " +
            "account, and a nightly job enforces them. The defaults and what happens at the " +
            "end of each period are set out in the Privacy Policy, section 9. A minimum of " +
            "90 days applies to call recordings; the database refuses a shorter period.",
        },
        {
          kind: "para",
          text:
            "On termination, and for {{DATA_RETURN_WINDOW_DAYS}} days afterwards, you may " +
            "export your data through the product. After that we erase it on your written " +
            "instruction, and on our own initiative if you give none. The end-of-engagement " +
            "erasure has its own certificate, which enumerates what it does not erase " +
            "rather than leaving it to inference.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "Two stores with no retention period yet",
          text:
            "The raw document the voice platform returns for each call is archived and no " +
            "retention category expires it; the only clock on it is a storage lifecycle " +
            "rule that has not been applied to a live bucket. Knowledge content you upload " +
            "is kept indefinitely, in every version. Both are reached by an end-of- " +
            "engagement erasure to the extent stated on the certificate, and both are open " +
            "items on our own register rather than solved problems.",
        },
      ],
    },
    {
      id: "transfers",
      heading: "9. Where processing happens",
      blocks: [
        {
          kind: "para",
          text:
            "Section 16 of the DPDP Act permits transfer of personal data outside India " +
            "except to a country the Central Government notifies as restricted; no such " +
            "notification has been made. Rule 15 of the DPDP Rules requires us to observe " +
            "any conditions the Government imposes, and we will.",
        },
        {
          kind: "para",
          text:
            "The sub-processor page states, for each vendor, where it processes. The " +
            "material facts, stated here so they are in the contract and not only in a " +
            "notice: speech recognition and voice synthesis run on an Indian provider; " +
            "the language model on both AI legs runs on a hyperscale provider's service " +
            "configured for an Indian region, named on the sub-processor page, which our " +
            "build constrains but cannot prove — see the paragraph below, which is part " +
            "of this clause; object storage selects its location automatically and " +
            "offers no India-only jurisdiction; the application host is at " +
            "{{PRIMARY_HOSTING_LOCATION}}; the voice platform runs the call itself, and " +
            "holds its own copy of the recording and transcript, outside India — its " +
            "documentation states that its services run on United States infrastructure " +
            "unless an enterprise residency option is purchased, and we have not purchased " +
            "one; and transactional email and error monitoring are operated from outside " +
            "India. Sign-in is ours and runs on the application host.",
        },
        {
          kind: "callout",
          tone: "warning",
          title: "What we warrant about the language model, and what we do not",
          text:
            "We warrant that our software cannot send a language-model request anywhere " +
            "but an Indian region without a change to our source code that fails our own " +
            "build: one function constructs every model endpoint, it cannot emit a " +
            "non-Indian region, the region is written once, and no configuration setting " +
            "may carry a region or an endpoint. We do NOT warrant this as machine-proved " +
            "at the provider, and we will not let a shorter sentence imply that we do. " +
            "Our provider's endpoint address contains no region — the region belongs to " +
            "the account resource — so that the resource is in South India, and that its " +
            "model deployment is the regional kind rather than the provider's worldwide " +
            "default, are confirmed by a named person against the provider's console, " +
            "dated and retained as evidence, and available to you under clause 10. " +
            "Before 19 August 2026 the language leg ran on a provider whose endpoint did " +
            "name its region; the change of provider is what narrowed this warranty, and " +
            "it is recorded rather than absorbed.",
        },
        {
          kind: "para",
          text:
            "If your own sector regulator requires data localisation beyond this, tell us " +
            "before you sign. We will tell you honestly whether we can meet it.",
        },
      ],
    },
    {
      id: "audit",
      heading: "10. Audit and information rights",
      blocks: [
        {
          kind: "list",
          items: [
            "We will make available the information you reasonably need to demonstrate " +
              "compliance with this Addendum — Annex B, the sub-processor list, our " +
              "retention configuration, and our answers to a reasonable security " +
              "questionnaire.",
            "You may audit our compliance once in any twelve-month period, on 30 days' " +
              "written notice, during business hours, without disrupting the service, and " +
              "subject to confidentiality. You may use an independent auditor who is not a " +
              "competitor of ours. You bear the cost unless the audit finds a material " +
              "breach of this Addendum, in which case we bear our own.",
            "Additional audits may be carried out where a regulator requires one, or " +
              "following a personal data breach affecting your data.",
            "An audit must not expose another client's data. Where a request would, we " +
              "will offer the equivalent evidence in a form that does not.",
          ],
        },
      ],
    },
    {
      id: "annex-a",
      heading: "Annex A — Details of the processing",
      blocks: [
        {
          kind: "table",
          caption: "Subject matter, duration, nature, purpose, data and data principals",
          columns: ["Item", "Detail"],
          rows: [
            [
              "Subject matter",
              "Providing the Calevate AI telephone agent service to the Client.",
            ],
            [
              "Duration",
              "For the term of the Terms of Service, plus the retention periods configured " +
                "on the account and the exit window in clause 8.",
            ],
            [
              "Nature of the processing",
              "Answering and placing telephone calls; recording; speech recognition; " +
                "generating conversational responses; transcription; redaction; extraction " +
                "of Client-defined fields; storage; retrieval; display; export and " +
                "delivery to Client-configured destinations; suppression-list management; " +
                "metering; erasure.",
            ],
            [
              "Purpose",
              "The Client's own purpose in operating a telephone line — handling enquiries, " +
                "capturing leads, following up contacts — as configured by the Client.",
            ],
            [
              "Categories of personal data",
              "Phone numbers; call metadata; call audio recordings; raw and redacted " +
                "transcripts; call summaries; timestamped key moments; the fields the " +
                "Client's extraction schema defines (which may include name, location, " +
                "budget, stated requirement, appointment preference, callback number and " +
                "anything else the Client chooses); lead records and their history; consent " +
                "and opt-out records; contact rows uploaded by the Client, including any " +
                "additional columns in the Client's file.",
            ],
            [
              "Special categories",
              "Not intentionally processed. Because a conversation is open-ended, a caller " +
                "may volunteer health, financial or other sensitive information, and it " +
                "will be present in the recording and the transcript. Agents are configured " +
                "not to ask for government identifiers, and the redaction pass masks " +
                "Aadhaar, PAN, card and one-time-password patterns from the default view.",
            ],
            [
              "Categories of data principals",
              "People who call the Client's number; people the Client asks us to call; " +
                "people whose details the Client uploads or forwards from a lead form. " +
                "Staff of the Client named in onboarding answers as transfer or escalation " +
                "contacts.",
            ],
            [
              "Sub-processors",
              "As listed on the sub-processor page, which forms part of this Annex.",
            ],
          ],
        },
      ],
    },
    {
      id: "annex-b",
      heading: "Annex B — Technical and organisational measures",
      subsections: [
        {
          id: "annex-b-separation",
          heading: "B.1 Separation between clients",
          blocks: [
            {
              kind: "list",
              items: [
                "Every table holding Client data carries the tenant identifier and forced " +
                  "row-level security in PostgreSQL. The application connects with a " +
                  "database role that cannot bypass those policies.",
                "The tenant context is set from the verified session, never from a request " +
                  "parameter, and fails closed.",
                "A cross-tenant read returning zero rows is asserted by test for every " +
                  "such table, and a build check refuses a new table that ships without " +
                  "its policy.",
              ],
            },
          ],
        },
        {
          id: "annex-b-access",
          heading: "B.2 Access control",
          blocks: [
            {
              kind: "list",
              items: [
                "Two separate authentication realms — client and operator — with separate " +
                  "session modules, separate cookies and no shared session logic. " +
                  "Authentication is first-party: no identity vendor holds an account " +
                  "identity or a credential for this system.",
                "Multi-factor authentication is mandatory for operator accounts and is " +
                  "enforced in the token verifier on every request, including reads. A " +
                  "token that does not evidence a second factor is refused; so is one that " +
                  "says nothing about one.",
                "Role-based permissions. Client roles are owner and staff; staff cannot " +
                  "reach billing, organisation settings, unredacted transcripts, or exports " +
                  "containing unredacted data. The endpoint-to-permission map is asserted " +
                  "at start-up in four directions, including that every declared permission " +
                  "is actually held by some role.",
                "Operator access to a client account is read-only, requires a short-lived " +
                  "signed grant bound to that operator and that client, is revoked " +
                  "instantly by sign-out or role change, and is audited twice.",
                "Invitations are single-use, expire in 72 hours, are stored hashed, and are " +
                  "burned on use.",
              ],
            },
          ],
        },
        {
          id: "annex-b-data",
          heading: "B.3 Protecting the data itself",
          blocks: [
            {
              kind: "list",
              items: [
                "Transcripts are stored with a redacted copy alongside the raw text, and " +
                  "the redacted copy is what every screen, export and notification uses. " +
                  "The redaction covers Aadhaar (Verhoeff-checked), PAN, card numbers " +
                  "(Luhn-checked) and one-time-password patterns, plus a model-assisted " +
                  "pass for numbers spoken digit by digit.",
                "Recordings are held in our own object storage, encrypted at rest, reached " +
                  "only by signed links valid for five minutes, in buckets where public " +
                  "access is blocked at the account level.",
                "Credentials are encrypted at rest with a per-secret key wrapped by a " +
                  "master key that lives only in the process environment and never in the " +
                  "database. Key rotation is supported with an overlap period.",
                "Consent, usage, billing and audit records are insert-only, enforced by " +
                  "database triggers. Corrections are compensating entries; nothing is " +
                  "rewritten. Audit entries are chained with a keyed hash so a removal or " +
                  "edit is detectable.",
                "Phone numbers, transcript text and extracted fields are never written to " +
                  "application logs. The same redaction pair backs the log formatter, the " +
                  "error-reporting event hook and breadcrumbs, and every operator alert " +
                  "body; traces are redacted at the exporter rather than at each call site.",
              ],
            },
          ],
        },
        {
          id: "annex-b-transport",
          heading: "B.4 Transport and integrations",
          blocks: [
            {
              kind: "list",
              items: [
                "TLS everywhere, with HSTS.",
                "Incoming voice-platform webhooks are authenticated per platform: a " +
                  "signature and replay window where the platform signs, and a strict " +
                  "source-IP allowlist plus execution-id de-duplication where it does not. " +
                  "Payloads are treated as hints; the authenticated poll back to the " +
                  "platform is the record of truth.",
                "Outgoing webhooks to your systems are signed with a per-endpoint secret, " +
                  "retried on transport failures and specific server errors only, and " +
                  "logged.",
                "Client-facing ingest endpoints have a per-endpoint secret, validate their " +
                  "payload against a schema, are rate limited, and treat payloads as " +
                  "untrusted data rather than as instructions.",
              ],
            },
          ],
        },
        {
          id: "annex-b-resilience",
          heading: "B.5 Resilience, monitoring and development",
          blocks: [
            {
              kind: "list",
              items: [
                "Background jobs are idempotent, keyed, retried a bounded number of times " +
                  "and then routed to a dead-letter queue rather than lost silently.",
                "Per-client rate and spend ceilings, plus a global switch that halts all " +
                  "outbound dialling at once.",
                "Continuous write-ahead-log archiving plus an encrypted offsite dump, both " +
                  "retained 35 days. The restore procedure is documented and includes " +
                  "replaying erasures that completed after the recovery point.",
                "Static analysis, type checking, dependency and secret scanning, and a test " +
                  "suite including cross-tenant isolation tests, run on every change. " +
                  "Authentication, billing and compliance modules require a second review.",
                "Staging and production are separated, with separate agents and separate " +
                  "numbers; promoting configuration to production is an explicit audited " +
                  "action.",
              ],
            },
            {
              kind: "callout",
              tone: "warning",
              title: "Stated honestly",
              text:
                "The backup mechanism exists and the restore drill has not yet been run " +
                "successfully. Until it has, treat backup and recovery as designed rather " +
                "than as proven. We will tell clients when the first drill passes.",
            },
          ],
        },
      ],
    },
    {
      id: "annex-c",
      heading: "Annex C — Sub-processors",
      blocks: [
        {
          kind: "para",
          text:
            "The authorised list is the sub-processor page, which is incorporated into " +
            "this Addendum and is maintained as a single register rather than restated " +
            "here. Clause 5 governs changes to it.",
        },
      ],
    },
    {
      id: "dpa-contact",
      heading: "Contact",
      blocks: [
        {
          kind: "para",
          text:
            "Notices under this Addendum, including breach notifications you send us and " +
            "audit requests, go to {{DATA_PROTECTION_CONTACT_NAME}} at " +
            "{{DATA_PROTECTION_CONTACT_EMAIL}}, with security matters copied to " +
            "{{SECURITY_CONTACT_EMAIL}}.",
        },
      ],
    },
  ],
};
