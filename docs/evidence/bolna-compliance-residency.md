# Bolna: compliance flags, data residency, and what we tell clients

> ⚠ **SUPERSEDED IN PART — 22 August 2026, D-449. THE VENDOR QUOTES ARE UNTOUCHED; ONE
> CONCLUSION IS WITHDRAWN.** §5's fork and every quotation in this document stand exactly as
> recorded. What does NOT stand is the consolation this document reaches more than once —
> that the MODEL legs remain Indian, so "the inference does not leave the country" while
> only the orchestration does (see §5 and §9). D-449 moved the language model to Azure
> OpenAI `eastus2`. **Only the SPEECH legs are Indian now**, and the caller's transcript
> crosses the border on every turn as it is spoken. The fork itself gets sharper rather than
> softer: buying Bolna's Enterprise India routing would put the ORCHESTRATION in India while
> the model stayed in the US — the mirror image of the position described here, and still
> not "the call happens in India". Nothing below was re-read or re-measured.


**Read 20 Aug 2026 against `bolna-findings/mirror/pages/` — the vendor's own documentation,
mirrored locally.** Every claim below quotes the page it comes from. Nothing here is
inferred from an index description, a URL shape or a support thread; where the pages are
SILENT this document says so by name rather than filling the gap, because this is the lane
where a guess is not recoverable (D-31, D-32, D-350 are each a case of vendor prose being
read as a specification).

Pages read end to end for this document: `api-reference/violations/{overview,list,submit}`,
`compliance-application/{introduction,how-to-submit-guide}`, all eight of `enterprise/*`,
`concepts/security.md`, `guides/inbound/obtaining-regulated-phone-numbers.md`, plus
`supported-telephony-providers.md`, `guides/outbound/calling-guardrails.md`,
`api-reference/limits.md`, `build-with-ai/{mcp,mcp-tool-list,mcp-prompts,skills-reference}.md`
and the 2026 changelogs, each of which settles something the assigned pages left open.

---

## 1. The Violations API — a compliance obligation nothing here was watching

### 1.1 What it is

`api-reference/violations/overview.md`:

> Manage and track call violations using the Bolna Violations APIs. List violations with
> filtering and pagination, and submit violation evidence.
>
> ```
> GET /violations/list
> POST /violations/submit
> ```

`api-reference/violations/list.md` (the OpenAPI block): `status` filters on
`pending | accepted | rejected | submitted`; a `Violation` carries `id`,
`from_phone_number`, `to_phone_number`, `date_of_call`, `status`, `created_at`,
`updated_at`, `user_id`, `agent_id`, `execution_id`, `image_url`
("Path to the violation evidence image, if available") and `email`.

`api-reference/violations/submit.md`:

> Submit a violation along with an evidence file (e.g., a screenshot or document). This
> endpoint updates the violation status and attaches the uploaded file.

with `multipart/form-data` requiring `violation_id` and `violation_file`, answering
`{"message": "success", "state": "submitted"}`.

Two further pages say what fills the list. `build-with-ai/mcp-tool-list.md`:

> `list_violations` — Flagged call violations — **content policy, regulatory, or fraud** —
> optionally filtered by status

and `build-with-ai/skills-reference.md` describes the pair as:

> `manage-violations` — List compliance flags and submit evidence files for review

### 1.2 What the documentation does NOT say, and these are the four that matter

| Question | Documented? |
|---|---|
| What raises a violation | **No.** "Content policy, regulatory, or fraud" is a taxonomy of causes, not a trigger. Complaint, carrier report, automated transcript scan and manual review are all consistent with every page. |
| Is there a deadline to submit evidence | **No.** No page names a window, a due date or a countdown. `created_at`/`updated_at` are on the record, which is what a deadline would be measured from. |
| What happens if we ignore one | **No.** Nothing states a consequence, and nothing states whether calling can be suspended. |
| What `accepted` / `rejected` mean | **No.** The words are undefined. `accepted` could mean the flag was upheld against us or that our evidence was accepted — opposite meanings for the same string. |

**The nearest published fact about enforcement** is in `frequently-asked-questions.md`,
about a neighbouring surface:

> If you see a message such as **"Agent is restricted due to disallowed content. Please
> review and update it."**, it means your agent's configuration or prompt may have
> triggered a violation of Bolna's content safety policies.

That is proof this vendor does restrict accounts over compliance findings. It is NOT proof
that an unanswered violation does so, and this document does not treat it as such.

### 1.3 The verdict: yes, we needed a poller, and it is built

Three properties make this an obligation rather than a feature request:

1. **It is raised by the vendor against OUR account** — the single account through which
   every client's regulated Indian calling runs.
2. **Nothing pushes it.** There is no violation webhook, and Bolna signs no webhook at all
   (`concepts/security.md`: *"There is no HMAC signature on webhook payloads in the current
   version"*). The entire notification channel is a list endpoint someone has to read.
3. **The first symptom of ignoring it would be enforcement.** With no deadline published,
   the only safe posture is to notice a flag the hour it appears.

So the sweep is built and wired, and it is a READ. What it deliberately does not do is
submit: `POST /violations/submit` requires an evidence FILE, and a machine cannot produce
evidence. An automated submitter would file something against a compliance finding to make
a queue go green, which is the precise failure the sweep exists to catch. Section 9 lists
the code.

**The hard-rule-6 trap in their payload, which is the reason our record is shaped the way
it is.** Their documented example evidence path is

```
73b9ed7c-c255-486b-b2eb-6c21e41a8ca1/violations/ce23f363-131a-47fc-8a33-258141a575b0/9845866566.png
```

beside `to_phone_number: '+919845866566'` on the same example record. **The filename IS the
recipient's phone number.** Storing or logging `image_url` would put a phone number into
every log line, alert body and support ticket that quoted it, disguised as an opaque path
that no reviewer would flag. `EngineViolation` therefore carries `has_evidence: bool` and
never the URL, and carries no phone number and no email at all — dropped at the adapter
edge, where a downstream caller cannot leak what it was never given.

### 1.4 The vendor questions this raises — for a human, not for code

These belong in the pilot's commercial thread (OPERATIONS §2 gate 11 is the thread; the
questions below are proposed as a new gate **9v**, text in §6.2):

1. What raises a violation, and is any part of it automated over transcripts? *(If they
   scan transcripts, that is a processing purpose our DPA does not currently describe.)*
2. Is there a deadline for submitting evidence, and what is it measured from?
3. What happens if a violation stays `pending` — can it suspend the account's calling,
   throttle it, or affect an agent only?
4. What do `accepted` and `rejected` mean, precisely?
5. On a reseller account, is a violation raised against the ACCOUNT or against the
   sub-account/agent? *(This decides whether one client's flag can stop every client's
   calling — see §8.3.)*

---

## 2. Residency, split four ways as instructed. Do not merge these.

### 2.1 In-call processing (media, orchestration, model calls)

**Default: the United States.** `enterprise/data-residency.md`:

> By default, all Bolna AI services operate in United States (US)-hosted infrastructure,
> but customers on enterprise plans can choose to have their data processed exclusively in
> India.

`concepts/security.md`:

> By default, Bolna processes calls on infrastructure in the US (AWS us-east-1).

**With India residency purchased and configured**, `enterprise/data-residency.md`:

> **Processing**: All inference, transcription, and response generation happens within
> Indian borders.

and `concepts/security.md` adds the region and one hedge worth noticing:

> * Call processing runs on servers in `ap-south-1` (Mumbai)
> * Recordings and transcripts are stored in India
> * LLM inference is routed to India-region endpoints **(where available)**

The parenthesis is theirs. Under BYOK it does not bind us either way — our LLM endpoint is
our own Azure resource — but it is the kind of qualifier that matters if we ever moved to
their integrations.

### 2.2 Transcripts

With India residency, `enterprise/data-residency.md`:

> **Storage**: All customer audio, transcripts, logs, and configurations are stored on
> secure infrastructure physically located in India.

Without it, the default sentence in §2.1 governs: US-hosted infrastructure. The data-at-rest
table in `concepts/security.md` lists "Transcripts — Full conversation text — Stored in
execution record" and names no location, so the default is the only statement available.

### 2.3 Recordings — and here the old evidence has expired

Our tree has said since D-31 that "Bolna call recordings were observed on S3 `us-east-1`".
That observation is real and still visible in eight API-reference pages, e.g.
`api-reference/executions/get_execution.md`:

> `https://bolna-call-recordings.s3.us-east-1.amazonaws.com/ACXXX…/REb1c182ccde4ddf7969a511a267d3c669`

**But two things have changed and both must be stated.**

First, an India bucket demonstrably exists. `changelog/may-2026.md` names the *previous*
recording URL format as:

> `https://bolna-recordings-india.s3.amazonaws.com/{vendor}/{file}.mp3`

Second, the region is no longer readable from a URL at all. The same changelog entry
(11 May 2026, "Action required by June 1"):

> Direct Amazon S3 recording URLs will stop working after **June 1, 2026**. … Starting
> June 1, call recording URLs will be served through a stable Bolna-hosted endpoint …
> `https://api.bolna.ai/recordings/call/{execution-id}` … The **resolved pre-signed link it
> returns expires after 24 hours** — do not store or cache it.

That date has passed. **So "observed in us-east-1" is now a DATED observation we cannot
re-verify by inspection, and it must not be presented as a current measurement.** What we
can say is what §2.1's default sentence says: US infrastructure unless residency is bought.
The client-facing copy was rewritten on exactly this basis (§9).

*A second, unrelated consequence of that changelog entry, flagged for whichever lane owns
the recording-copy path: a pre-signed link that expires in 24 hours and must never be
cached is a constraint on `recording_copy_failed`'s recovery window. Not this lane's to fix
and not verified against our code here.*

**Retention of their copy is undocumented.** `concepts/security.md`'s data-at-rest table
says of call recordings: "Available in execution record; **contact support for retention
policy**". Our privacy notice already reports engine-side deletion as
`unconfirmed_pending_vendor_api`; that remains correct and is now corroborated.

### 2.4 Metadata, logs and configuration

`enterprise/data-residency.md` puts "logs, and configurations" in the same India-storage
sentence as audio and transcripts, so the same default/purchase split applies.
`concepts/security.md` adds, on the credentials specifically:

> Agent configuration | Prompts, tool configs, provider keys | Encrypted at rest
>
> API keys | Hashed — Bolna cannot recover a plaintext key | N/A

and separately:

> When you configure third-party providers (OpenAI, ElevenLabs, Twilio, etc.) in Bolna,
> your provider API keys are stored encrypted in Bolna's infrastructure. They are used at
> call time to authenticate requests on your behalf. Bolna does not log or expose provider
> credentials in API responses.

Note the asymmetry, which is correct and worth reading twice: **their own API keys are
hashed; OUR provider keys are encrypted**, because they must be recoverable to be used.
That is unavoidable for BYOK and is not a criticism — but it means our Sarvam and Azure
credentials sit, recoverable, in US infrastructure by default. `Settings` classifies
`bolna_llm_credential_name` as `applies: live` for a wrong-field-name reason; this is a
separate reason to keep those credentials rotatable.

### 2.5 The compliance-application documents (CIN, GST)

`compliance-application/introduction.md`:

> * **Encrypted Storage**: All uploaded documents are encrypted at rest and in transit
> * **Limited Access**: Only authorized compliance team members can access your documents
> * **Regulatory Compliance**: We comply with data protection regulations including GDPR
> * **Secure Deletion**: Documents are securely deleted after the regulatory retention period

> We never share your compliance documents with third parties except as required by law or
> regulatory authorities.

**GDPR is named. The DPDP Act is not — anywhere on any page in this mirror.** For a vendor
whose India business is the subject of these very pages, that is a question for counsel and
for the contract (§10), not a defect we can code around.

---

## 3. The finding that outranks everything else: BYOK forecloses their India routing

`enterprise/indian-server-configuration.md` states requirements that must ALL hold:

> To route calls through Indian servers, your agent configuration must meet **all** of the
> following requirements:
>
> ### 1. Telephony Provider — Use **Plivo** as your telephony provider.
> *(Note: Twilio is not supported for Indian server routing. If you use Twilio, calls will
> be processed on US servers.)*
>
> ### 2. Transcriber — Deepgram, Azure, Sarvam, ElevenLabs, Smallest
>
> ### 3. Synthesizer — ElevenLabs, Sarvam, Azure TTS, Cartesia
>
> ### 4. LLM — Azure OpenAI
>
> ### 5. Provider API Keys — Use Bolna's default provider integrations. **Do not connect
> your own API keys for the transcriber, synthesizer, or LLM providers.**

and the consequence, in their own warning box:

> If you connect your own API keys for any provider (transcriber, synthesizer, or LLM),
> calls will automatically route through US servers **regardless of other configuration
> settings**.

The troubleshooting section repeats it as a checklist item: *"Check that you haven't
connected your own API keys for any provider in the Providers section."*

**Requirements 2, 3 and 4 we already satisfy exactly** — Sarvam STT, Sarvam TTS, Azure
OpenAI — which is a genuinely striking alignment and makes the fifth requirement the whole
of the problem.

**Requirement 5 is the opposite of what this product is.** BYOK on all three legs is D-31
and D-36; `apps/api/engine/bolna.py::_agent_body` sends our own model strings on every leg,
`BOLNA_CAPABILITIES` declares BYOK on all three, and `set_llm_credential` posts our Azure
key to `POST /providers` — which is precisely "the Providers section" their troubleshooting
step tells us to check is empty.

**So the residency option is not merely something we have not bought. It is something our
current architecture forecloses.** Buying it would move no call.

---

## 4. The telephony half, which splits the same way and was not obvious

`guides/inbound/obtaining-regulated-phone-numbers.md`:

> | **140-series** | Telemarketing and promotional calls | **Vobiz** |
> | **160-series** | Transactional and service calls (banking, insurance, etc.) | **Plivo** |

> Bolna uses **Vobiz** as the telephony provider for Indian calling, and Vobiz recommends
> registering on the **TATA Teleservices DLT portal**.

But Indian-server routing requires **Plivo** and names no other provider. Exotel and Vobiz
— both listed as India providers in `supported-telephony-providers.md` — appear nowhere in
the Indian-server requirements. Their status there is **undocumented, which is not the same
as supported**, and this document will not upgrade it.

**Read together, the promotional path is the one that cannot be in India even in
principle**: a 140-series promotional campaign runs on Vobiz, and Indian-server routing
requires Plivo. Outbound campaigns are the promotional product. This is a second,
independent reason §3's conclusion holds for the campaign half of the business, and it does
not depend on BYOK at all.

*(A question, not a claim: whether "route calls through Indian servers" is about the MEDIA
path only or about storage as well. `enterprise/data-residency.md` describes an
account-level residency selection covering storage AND processing;
`enterprise/indian-server-configuration.md` describes per-agent routing conditions. The two
pages never say how they compose. Added to the gate-9 question list in §6.2.)*

---

## 5. The fork, stated so a decision can be taken rather than drifted into

Neither arm is free and neither is ours alone to choose.

**Arm A — keep BYOK, accept US orchestration (the status quo, now documented).**
The model legs stay Indian: Sarvam is sovereign by vendor, Azure OpenAI is region-pinned to
South India, so the inference does not leave the country. The orchestration, the media path
and the platform's copies of recording and transcript are in the US. We keep BYOK's cost
control, the named-model transparency, and D-410's whole Azure pinning argument. **The DPA
must say so, and now does.** Cost: the residency story is materially weaker than the
sentence this repo has been carrying, and any client with a sector localisation mandate is
disqualified — which `/legal/dpa` §9 already invites them to tell us about before signing.

**Arm B — move to Bolna's own provider integrations and buy Enterprise residency.**
Calls process in `ap-south-1`; recordings, transcripts, logs and configs store in India.
Cost, and it is not small: we lose BYOK on all three legs, which means (i) `_llm_routing`,
`set_llm_credential` and D-410's entire Azure argument stop applying to the in-call leg —
their LLM would be *their* Azure OpenAI, not our South India resource, and "LLM inference is
routed to India-region endpoints (where available)" is a weaker guarantee than a resource we
attested; (ii) Sarvam's Bulbul v3 / Saaras selection becomes theirs to make, and D-36's
Telugu quality argument is re-opened; (iii) the ₹/min model changes completely — the BYOK
platform fee is replaced by their bundled rate (gate 12); (iv) telephony must be Plivo, so
the 140-series promotional path via Vobiz is affected (§4); (v) Enterprise plan pricing,
which nobody has quoted.

**Arm C — a second engine for residency-sensitive clients.** The adapter architecture makes
this cheap in code and expensive in operations. Recorded as available, not recommended.

**What this document does NOT do is pick.** It is D-31's ground being re-litigated, the
commercial half sits behind gate 12, and the engineering half is a rewrite of the in-call
model configuration. What it does do is stop the client-facing documents from describing
Arm B while we are running Arm A.

---

## 6. OPERATIONS §2 — the exact replacement text

*Applied 20 Aug 2026: gate 9 replaced, gate 9v added, and the two decision rows in §11 landed
as **D-415** and **D-416**.*

### 6.1 Gate 9, rewritten

The current row's last sentence — *"This is the one axis where LiveKit beats Bolna on
verified evidence today"* — is **no longer supportable as written, and it does not simply
flip either.** Bolna's India residency is real, documented and better specified than we
believed; it is also Enterprise-gated and excluded by our own architecture. Both halves have
to survive into the replacement, so here is the whole row:

> | 9 H | Compute region + residency [NEW, D-32; **verdict replaced 20 Aug 2026 from the vendor's own docs**] | **THE OLD VERDICT IS WITHDRAWN AND THE NEW ONE IS WORSE, NOT BETTER.** This row used to end "this is the one axis where LiveKit beats Bolna on verified evidence today", on the strength of recordings seen at `s3.us-east-1`. Bolna's documentation, read at last (`bolna-findings/mirror/pages/`), says three things that together retire that sentence and replace it with a harder problem. **(a) The default is the United States for EVERYTHING, not just storage** — *"By default, all Bolna AI services operate in United States (US)-hosted infrastructure"* (`enterprise/data-residency.md`), *"By default, Bolna processes calls on infrastructure in the US (AWS us-east-1)"* (`concepts/security.md`). **(b) India residency exists and is well specified** — audio, transcripts, logs and configurations stored in India, and *"All inference, transcription, and response generation happens within Indian borders"*, on `ap-south-1`. It is an **Enterprise-plan purchase** (`"Data residency is an Enterprise feature"`), so it is also gate 12's subject and gate 10's. **(c) AND OUR ARCHITECTURE EXCLUDES IT.** Their Indian-server requirements are Plivo telephony, a listed transcriber and synthesizer, Azure OpenAI — all of which we already match — plus *"Use Bolna's default provider integrations. Do not connect your own API keys for the transcriber, synthesizer, or LLM providers"*, with the consequence stated outright: *"If you connect your own API keys for any provider (transcriber, synthesizer, or LLM), calls will automatically route through US servers regardless of other configuration settings"* (`enterprise/indian-server-configuration.md`). **BYOK on all three legs is what this product IS** (D-31/D-36/D-410), so buying residency would move no call. A second, independent exclusion applies to the promotional half of the business: Indian-server routing names Plivo only, while 140-series telemarketing numbers come through **Vobiz** (`guides/inbound/obtaining-regulated-phone-numbers.md`). **What this gate now tests is therefore a DECISION, not a measurement** (`docs/evidence/bolna-compliance-residency.md` §5): keep BYOK and accept US orchestration with the DPA saying so — which is what `/legal/{subprocessors,privacy,dpa}` were corrected to say on 20 Aug 2026 — or move to their provider integrations and buy Enterprise residency, losing BYOK's cost control, D-410's Azure South India pinning on the in-call leg, and D-36's control of the Telugu speech stack. **Still to establish with the vendor, and each is a sentence in a contract rather than an experiment**: (i) whether "Indian server routing" covers STORAGE or only the media path — the two pages never compose; (ii) Enterprise pricing for residency, and whether it can be had without the rest of the Enterprise bundle; (iii) whether a sub-account can be residency-pinned independently of the parent (gate 10 interaction); (iv) the retention and deletion policy for their copies, which `concepts/security.md` answers only as "contact support for retention policy". **What survives unchanged, and is worth saying out loud:** the MODEL legs remain Indian in Arm A — Sarvam sovereign by vendor, Azure OpenAI region-pinned to South India by gates 20/20b/20c — so the inference does not leave the country even while the orchestration does. |

### 6.2 Gate 9v, new — the Violations API

> | 9v H | **The vendor's compliance-flag channel, and what it can do to us** [NEW, 20 Aug 2026] | Bolna raises VIOLATIONS against the account — *"Flagged call violations — content policy, regulatory, or fraud"* (`build-with-ai/mcp-tool-list.md`) — publishes them on `GET /violations/list`, pushes nothing, and documents no trigger, no deadline and no consequence. **Our half is done and does not wait on this gate**: `apps/workers/engine_violations.py` polls hourly, attributes each flag to a tenant through `engine_agent_routes`, and pages on `engine_violation_open` (`runbooks/engine-violations.md`). **The gate is the five answers only they can give**, and each changes something: (a) what raises one — if any part of it is an automated scan over transcripts, that is a processing purpose our DPA does not describe and must; (b) the deadline for submitting evidence, and what it runs from — this decides whether an hourly poll is generous or already too slow; (c) what an unanswered flag costs, specifically whether it can suspend the account's calling or only an agent; (d) what `accepted` and `rejected` mean, since the words are undefined and could describe the flag being upheld or our evidence being accepted; (e) on a reseller/sub-account structure, whether a flag attaches to the ACCOUNT or the SUB-ACCOUNT — because if one client's flagged call can stop the parent account's calling, that is a multi-tenant blast radius and it belongs in gate 10's answer as well as this one. **Pass criteria**: all five in writing, plus one observed round trip on a live account (list → submit → list) proving the status transition and confirming the evidence upload path. **Refuse to infer any of the five from the four status strings.** |

---

## 7. The compliance application and the DLT machinery, against our PE/TM model

### 7.1 Their account-level compliance application

`compliance-application/introduction.md`: *"Before purchasing phone numbers on Bolna, all
users must submit a compliance application… The compliance application is a one-time
requirement."* Required: full name, company name, **CIN certificate** (PDF ≤ 10 MB), **GST
number**, **GST certificate** (PDF ≤ 10 MB). Review is *"within 12-24 business hours"*,
*"Complex cases … may take up to 2 business days"*, and *"Once submitted, you cannot
directly edit your application."*

**This is CALEVATE's application, not the client's** — it gates *our* account's ability to
buy numbers. It needs our CIN and GST, which are two of the external blockers already
tracked (`{{ENTITY_REGISTRATION_NUMBER}}`, `{{GSTIN}}` in `placeholders.ts`, and
LEGAL-SURFACE F-9). Nothing to build; it is one more thing that cannot happen before the
entity exists.

### 7.2 The 140-series path, and how well our model already matches

`guides/inbound/obtaining-regulated-phone-numbers.md` — register as **Principal Entity** on
the TATA Teleservices DLT portal, with digital KYC over: Certificate of Incorporation, GST
Certificate, Company PAN, Director List & MOA, and a **Letter of Authorization signed by a
director named in the MOA**. Then:

> Once your Digital KYC is verified, a payment link for **₹5,900** will be generated

**Our model matches this exactly, including the fee.** `apps/api/compliance/kyc.py`'s
research note already records "we executed their ₹5,900 PE registration (which an access
provider granted only after checking PAN/GST/CIN and the authorised signatory's ID)", and
`dlt_registrations` holds `pe_id`, `entity_name`, `status`, `tm_link_status`,
`registered_at`, `verified_at`, with the client-facing refusals `pe_registration_missing`
and `pe_registration_not_active`. That is independent corroboration of a model derived from
regulator and aggregator sources, which is the strongest kind.

**One operational fact worth carrying into onboarding copy** (a warning box on their page,
and the sort of thing that costs a client a re-registration):

> The mobile number and email ID in the LOA become your permanent registered contact for
> all DLT communications. These cannot be easily changed after submission — choose
> carefully.

### 7.3 The 160-series path — and a product constraint we should say out loud

Their 160-series provisioning needs, in order: PE registration (yielding **PE-ID and
TM-ID**), COI + GST to Bolna for Plivo KYC, PE-ID/TM-ID/compliance-application-name shared
with Bolna, Plivo allocates the number **inactive**, then Header registration on DLT
submitting an **RBI / SEBI Certificate** *"as proof of regulatory compliance"*, then a
**URN** and approval screenshot back to Bolna, then Template registration, then the numbers
go active.

**The RBI/SEBI certificate is the constraint.** On their process, a 160-series number
requires proof of financial-sector regulation. A salon, a clinic or a real-estate office —
the client #1 profile — has none. If that holds in practice, then **our SMB clients are
140-series only**, and every campaign they run is `promotional`: preference-scrubbed
against the NCPR, inside the 09:00–21:00 window, on a promotional template.

Our code is *already built that way* — `PREFERENCE_SCRUBBED_CLASSIFICATIONS` is
`promotional` only, `number_series_mismatch` and `dlt_template_mismatch` refuse a
misclassified campaign, and `NUMBER_SERIES = ("140", "160", "standard")` keeps 160 available
— so **nothing needs to change**. What needs to change is what we tell a prospect: a
`service` campaign on a 160-series number is not something a non-BFSI SMB can have on this
vendor's path. That is a sales-copy and onboarding fact, and it is the honest version of a
feature our own docs describe as available.

*Scope note: this is a reading of Bolna's procurement page, not of TRAI's rules. Whether
TRAI itself restricts 160-series to RBI/SEBI-regulated entities, or whether that is a
requirement of the header-registration step as Vobiz/Plivo run it, is a question for
counsel (§10) — the distinction decides whether this is a vendor limit or a legal one.*

### 7.4 What our flow does not collect and probably should

Nothing here is a blocker today, because number provisioning is out-of-band and gated on
KYC. Named so it is a decision rather than an omission: the **URN** from header
registration, and the fact that a 160-series number is allocated-but-inactive until
template approval. `numbers.dlt_status` (`pending`/`registered`/`blocked`) can express
"allocated, not yet active" only as `pending`, which is also what "nothing has happened"
means. If a 160-series client ever appears, that is one enum value, not a redesign — and
until one does, adding it would be a column nobody reads.

---

## 8. Everything else the assigned pages settle

### 8.1 `concepts/security.md` corroborates our webhook doctrine, and corrected our allowlist

> There is no HMAC signature on webhook payloads in the current version. Source IP
> verification is the primary trust mechanism.

First-party confirmation of what TRD §5 had inferred from their OSS delivery code. And:

> Bolna sends webhooks from a fixed set of source IPs: **`13.203.39.153`**,
> **`13.126.9.249`**, **`13.202.133.53`** … Whitelist all three IPs

`DEFAULT_BOLNA_SOURCE_IPS` held only the first, so two of three senders were being refused
by a control that fails safe. **This was found and fixed independently by another lane as
D-414 while this document was being written** — verified present in
`packages/shared/src/calevate_shared/config.py`. Recorded here because this lane reached the
same finding from `concepts/security.md`, which is the page that says "whitelist all three",
and because `docs/SECURITY-COMPLIANCE.md` §5 still described a single address until this
change (§9).

### 8.2 Their "Responsible AI" claim is wider than the page it cites

`concepts/security.md`:

> Bolna agents are subject to the [Calling Guardrails] system, which lets you configure:
> * Time-of-day restrictions for when calls can be placed
> * **Do-not-call list integration**
> * Maximum call duration limits

`guides/outbound/calling-guardrails.md`, the page it links to, documents **time-of-day
only** — `call_start_hour`, `call_end_hour`, and auto-rescheduling. There is no DNC feature
and no max-duration feature on it. **So do not rely on a vendor DNC.** Ours is the control
(hard rule 5, `compliance/dnc.py`, propagation before the next dispatch tick) and it stays
the control; this is a note against ever "configuring the engine built-in instead".

**A related item for whichever lane owns the outbound path — not fixed here, flagged.**
That page documents `bypass_call_guardrails: true` on `POST /call`, which *"skips time
validation for a specific call"*. Our tree never sends it (`grep` returns only a comment in
`engine/bolna.py`), and it must stay that way: sending it would be a bypass of the
09:00–21:00 TCCCPR window, which hard rule 5 forbids adding "for testing". A guard test
asserting the flag never appears in an outbound body would be cheap; it is not written here
because the outbound call path is another lane's this session, and two lanes adding the
same guard is the "one way per problem" defect.

### 8.3 Sub-accounts, and the question they raise for §1

`enterprise/sub-accounts.md` describes exactly our agency model — *"Complete Data
Isolation"*, *"isolation at the **agents and call logs** level"*, an auto-provisioned API
key per sub-account, consolidated billing, and *"Shared resources such as **phone numbers
and providers** remain available at the organization level"*. It is **Enterprise-only**
("Sub-accounts is an Enterprise feature"), which is gate 10's live question.

Two things it says that bear on this lane. **(a) Providers are shared at the organization
level**, so a BYOK credential is an ORG-level object — meaning §3's US-routing consequence
would apply to every sub-account at once, not per client. **(b) Violations carry a
`user_id`**, and nothing states whether a flag attaches to a sub-account or to the parent.
If it attaches to the parent, one client's flagged call is a platform-wide exposure. That
is gate 9v(e) and it is the question this lane most wants answered.

### 8.4 On-premise, recorded and not recommended

`enterprise/on-premise-deployments.md` offers full containerised self-hosting: *"All audio,
requests, logs and transcripts remain within your environment. Nothing is sent to Bolna's
servers."* It would solve residency completely. It also requires running their stack —
`api_server`, `ws_server`, `telephone_server`, `q_manager`, `q_worker`, `arq_worker`, plus
**RabbitMQ** — which is a message broker CLAUDE.md's "Do NOT" list forbids adding, an
operational burden nobody here can carry, and a direct contradiction of D-31's "rented
engine" premise. Recorded so the option is known to have been considered and declined, not
overlooked.

---

## 9. What changed in our tree, and what did not

**Built (§1's poller):**

- `apps/api/engine/violations.py` — the boundary. `EngineViolation` (no phone number, no
  email, no evidence URL — `has_evidence` is a bool), `walk_violations` with the same
  completeness rules as `list_executions`, and `SupportsViolations`, a structural Protocol
  rather than an `EngineCapabilities` flag (a capability boolean would advertise a Protocol
  method that does not exist).
- `apps/api/engine/bolna.py` — `BolnaEngine.list_violations`, twelve lines, the seam only.
- `apps/workers/engine_violations.py` — `sweep_engine_violations`, hourly at :50, idempotent
  and read-only, attributing flags to tenants through `engine_agent_routes`, with the
  `Retry`-then-`alert` ladder every cron here uses.
- `apps/workers/settings.py` — the cron registration. `check_job_wiring` passes.
- `runbooks/engine-violations.md` and three rows in `runbooks/alarm-index.md`:
  `engine_violation_open` (WORKER_STALL), `engine_violation_sweep_incomplete`
  (WORKER_DELIVERY), `engine_violation_sweep_abandoned` (WORKER_TERMINAL).
- `tests/engine_violations_test.py` — 22 tests, including the field-by-field PII assertion
  over the vendor's own documented example row.

**Deliberately NOT built:** any client of `POST /violations/submit`; any new table or
migration (the flags live at the vendor, we re-read them at will, and hard rule 2 keeps raw
vendor payloads out of typed columns); any interpretation of `accepted`/`rejected`.

**Client-facing text corrected (§2, §3):**

- `apps/web/src/lib/legal/subprocessors.ts` — the voice platform's Location cell now reads
  United States; §3.1 is rewritten to state the default, the Enterprise gate, the BYOK
  exclusion, what still survives (Indian model legs), and that the old `us-east-1`
  observation can no longer be re-verified from a URL.
- `apps/web/src/lib/legal/privacy.ts` §8 — widened from "their copies of recordings" to the
  live audio, the transcript and their copy.
- `apps/web/src/lib/legal/dpa.ts` §9 — the same, in the operative clause.
- `apps/web/tests/legal.test.tsx` — a new assertion on the register ROW, not the prose.
- `docs/SECURITY-COMPLIANCE.md` §4 cross-border — quotes added, the false sentence
  *"Everything the caller says is processed in India"* removed; §5 webhook line corrected
  from one source IP to three.
- `docs/LEGAL-SURFACE.md` — finding **F-12**, appended (not inserted, per that document's
  own rule) so every F-1…F-11 citation still resolves; §6's "does not claim" list and §9's
  sources updated.

**Not changed, deliberately:** `check_model_residency.py` and everything about the Azure
legs. §4 of SECURITY-COMPLIANCE's model-residency paragraph is unaffected — the inference
still happens in South India. What moved is the description of the ORCHESTRATION.

---

## 10. For counsel, not for code

1. **Is a DPA that names the United States as the voice platform's processing location
   sufficient under DPDP §16 as it stands?** Our reading is yes (no country is notified as
   restricted), and `/legal/dpa` §9 says so. It is a bigger claim now than when the transfer
   was one vendor's recording copy.
2. **Does a sector-regulated client (BFSI, healthcare) have a localisation mandate we now
   fail?** `/legal/dpa` §9 already asks them to tell us before signing. That invitation is
   now doing real work and should be in the sales script, not only in the contract.
3. **Bolna's compliance page names GDPR and never the DPDP Act.** Should the sub-processor
   agreement require DPDP-equivalent obligations explicitly (LEGAL-SURFACE DP-11's downward
   leg, F-10)? No vendor contract is signed, so this is free to fix now.
4. **Does TRAI restrict 160-series to RBI/SEBI-regulated entities, or is that Bolna's /
   Plivo's / TATA's procurement requirement?** (§7.3.) The answer decides whether "service
   campaigns" are a product we may sell to an SMB at all.
5. **If Bolna raises a "violation" that alleges a regulatory breach on a call placed for a
   client, who answers it?** We hold the account; the client is the Principal Entity. The
   client contract should say who bears the consequence and who supplies the evidence.
6. **Recording retention at the vendor is "contact support for retention policy".** The
   erasure certificate already reports engine-side deletion as unconfirmed. A written
   retention and deletion commitment belongs in the contract (gate 12(f)).

---

## 11. Proposed decision-log entries (`docs/ROADMAP.md` §6 is not this lane's to edit)

**D-415 — Bolna's India residency exists, is well specified, and is foreclosed by our own
BYOK posture.** *(applied centrally 20 Aug 2026 as D-415.)* Their documentation puts every service on US infrastructure by default,
offers India residency as an Enterprise purchase covering storage and processing in
`ap-south-1`, and states that connecting customer provider keys routes calls through US
servers regardless of other configuration. BYOK on all three legs is D-31/D-36/D-410. So
gate 9's verdict is replaced (§6.1), the fork is recorded (§5), and — the part that does not
wait for the fork — the client-facing documents were corrected to describe Arm A, which is
what we actually run. Evidence class: **VERIFIED-VENDOR-DOCS**, quoted in
`docs/evidence/bolna-compliance-residency.md`.

**D-416 — The engine publishes compliance flags against our account, and we now read them.** *(applied centrally 20 Aug 2026 as D-416.)*
`GET /violations/list` is polled hourly by `sweep_engine_violations`; flags are attributed to
tenants through `engine_agent_routes` and page as `engine_violation_open`. No evidence is
submitted by machine, because `POST /violations/submit` takes a file and evidence is a human
artefact. The trigger, the deadline, the consequence and the meaning of two of the four
statuses are undocumented and are gate 9v (§6.2) — carried as open questions, never as
inferred values. The vendor payload's `image_url` ends in the recipient's phone number, so
the adapter reduces it to a boolean at the boundary; `tests/engine_violations_test.py`
asserts that field by field.
