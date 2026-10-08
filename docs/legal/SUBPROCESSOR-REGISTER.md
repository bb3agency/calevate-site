# Sub-processor register — INTERNAL, NAMED

**Not published.** `/legal/subprocessors` lists sub-processors by CATEGORY only and says a
named list is available on request (D-679, founder decision 6 Oct 2026: Calevate resells a
voice platform under a white-label programme and does not name its telephony or voice
providers publicly; reference model app.outpero.com/security, read by the founder 6 Oct
2026). This file is that named list. It is what an "on request" answer is built from, and
it is what `scripts/check_subprocessor_coverage.py` reads.

## How this file is enforced

- Every vendor the CODE can reach (a credential-shaped `Settings` field, or a module in
  `apps/api/engine/` or `apps/api/retrieval/`) must have a row in the table below.
- Every category a row names must be a `key` of `SUBPROCESSOR_CATEGORIES` in
  `apps/web/src/lib/legal/subprocessors.ts`, and every published category must have at
  least one row here.
- "Named publicly" is `yes` only where the public page may print the company's name, and
  then the name must be in that category's `named` list on the page. Every alias of a `no`
  row is banned from every published legal document (`apps/web/tests/legalVendorNames.test.ts`).
- A vendor added to the code without a row here fails CI. Adding a COMPANY to an existing
  category is still a sub-processor change notified under DPA clause 5, even though the
  public page does not change.

When answering a request for the named list, send the table plus the per-vendor detail
below for the categories the requester's account uses, and keep the evidence-class notes
internal.

## Register

The table between the markers is machine-read. One row per company per role. Categories
are comma-separated keys; aliases are comma-separated words that would identify the row.

<!-- register:start -->
| Identity | Role | Categories | Named publicly | Aliases |
|---|---|---|---|---|
| Vobiz | Telephone carrier on the self-hosted engine (`ENGINE=pipecat`, Calevate's own account); carries nothing on the live deployment | telephony | no | Vobiz |
| Plivo | Fallback carrier the software can be switched to; no account held | telephony | no | Plivo |
| ThinnestAI | Hosted voice platform that runs the whole call and rents the numbers: the live deployment (`ENGINE=thinnest`, since 7 Oct 2026); speaks the Clear voice quality and holds our admin-cloned voices | telephony, voice-platform | no | ThinnestAI, Thinnest |
| Pipecat Cloud | Container platform our own call program runs on (`ENGINE=pipecat`; not the live deployment) | voice-platform | no | Pipecat |
| Cartesia | Alternative voice platform (contingency) | voice-platform | no | Cartesia |
| Sarvam | Speech recognition during the call on the self-hosted engine (`ENGINE=pipecat`); not on the live deployment | speech-to-text | no | Sarvam, Saaras, Bulbul |
| Sarvam | First post-call extraction pass over the raw transcript | post-call-extraction | no | Sarvam |
| Sarvam | Standby for the in-app assistant, prose only, no look-up tools | language-models | no | Sarvam |
| Cartesia | Voice synthesis for the Studio voice quality, on our own account: through the hosted voice platform's voice-only BYOK on the live deployment, directly on `ENGINE=pipecat` | text-to-speech | no | Cartesia, Sonic |
| Gnani | Voice synthesis for the Clear voice quality on the self-hosted engine (`ENGINE=pipecat`) only; not used on the live deployment | text-to-speech | no | Gnani, Timbre |
| Microsoft | Azure OpenAI, East US 2: the in-app assistant's default language model on every deployment, and the default in-call model on `ENGINE=pipecat` (on the live deployment the hosted voice platform runs the in-call model) | language-models | no | Microsoft, Azure |
| OpenAI | Alternative in-call language model on `ENGINE=pipecat`; does not serve the in-app assistant | language-models | no | OpenAI |
| Google | Gemini API: alternative language model, the in-call leg on `ENGINE=pipecat` and the assistant under conditions | language-models | no | Gemini, Vertex |
| Hostinger | Application server and PostgreSQL (D-180; the production VPS, deployed 7 Oct 2026) | hosting | no | Hostinger |
| Cloudflare | R2 object storage: recordings, exports, archived call documents, CRM bodies, backup segments | object-storage | no | Cloudflare, R2 |
| Cloudflare | Edge in front of the site: TLS, caching, attack protection | edge-network | no | Cloudflare |
| Resend | Transactional email | email | no | Resend |
| Sentry | Error and performance monitoring | monitoring | no | Sentry |
| Razorpay | Card, UPI and netbanking payments | payments | yes | Razorpay |
| Supermemory | Knowledge store and search outside the call (configured, not selected) | knowledge-search | no | Supermemory |
| Cohere | Text embeddings (contingency) | knowledge-search | no | Cohere |
| Meta | WhatsApp Business messages | messaging | yes | Meta |
| AiSensy | WhatsApp Business Solution Provider, client-enabled | messaging | yes | AiSensy |
| Interakt | WhatsApp Business Solution Provider, client-enabled | messaging | yes | Interakt |
| Google | Sheets API: writes leads to a client's own sheet | client-integrations | yes | Google |
| Google | Calendar API: reads free time and books on a client's own calendar | client-integrations | yes | Google |
| Meta | Lead Ads: retrieves a client's own lead-form answers | client-integrations | yes | Meta |
<!-- register:end -->

Why these five are named publicly: Razorpay is the payment gateway a client pays through
and sees on its own checkout, as Outpero names theirs. Google (Sheets, Calendar), Meta
(Lead Ads, WhatsApp) and the two WhatsApp providers are services a client connects to its
own account with its own consent or credential, so the client necessarily knows the
counterparty and naming it reveals nothing about our supply chain. Every telephony, voice,
speech, model, hosting, storage, email and monitoring vendor is unnamed.

The tracing collector has no row: no company is chosen and nothing is configured. It is
described in the public `monitoring` category; choosing a company for it adds a row here
and is a clause 5 notice.

## Per-vendor detail

Each section carries what the public page used to say in the vendor's own row. The public
category rows say the same facts without the names. Evidence classes follow hard rule 11.

### Vobiz (telephony), with Plivo as fallback

- Does: calling numbers and carrier connection; the call's media terminates at the carrier
  and it streams the call audio both ways to and from our call program. Vobiz in use on our
  own account; Plivo is a fallback our software can be switched to, with no account held.
- Receives: caller and called numbers, call detail records, live audio both ways, and a
  recording of the call, which we copy and keep 90 days; Vobiz's copy is deleted one day
  after ours is saved (D-668/D-670). Vobiz states it otherwise keeps a recording up to
  30 days.
- Location: not stated by the vendor. Nothing Vobiz publishes that we have read says where
  it processes or stores call data; no country is named (founder instruction 2 Oct 2026).
- Status: configured, not enabled on the live deployment, which runs `ENGINE=thinnest` and
  sends Vobiz nothing (founder, 7 Oct 2026). Core only if the deployment is switched back to
  `ENGINE=pipecat`, and then it carries the founder's test calls only until Vobiz consents in
  writing to client traffic (gate V-10).

### ThinnestAI (telephony, voice platform)

- Does: runs the whole call on the live deployment (`ENGINE=thinnest`, D-678; production
  since 7 Oct 2026) instead of Pipecat Cloud: holds the agent we configure, answers and
  places calls on numbers it rents to us, and does its own speech recognition, language
  model and voice. Vobiz carries nothing on this deployment. Calevate resells it under its
  white-label programme (founder, 6 Oct 2026). Voices (D-687, 8 Oct 2026): the Clear
  quality is spoken by its own studio-band voices, including voices our admin clones on it;
  the Studio quality is spoken by Cartesia on OUR key through its voice-only BYOK, so it
  passes the agent's words to Cartesia on our behalf.
- Receives: live audio both ways, the transcript, a recording (copied into our storage and
  kept 90 days), caller and called numbers, the agent's instructions and its knowledge.
  Also the voice samples our admin uploads to clone a voice: a recording of a real person
  (our staff or someone we engage, never a client's caller), held under the two consents
  ThinnestAI records with who agreed and when (`thinnest-findings/mirror/snapshots/
  2026-10-07b/pages/channels/voice-clone.md:33-44`). Deleting a clone deletes the
  recording, the preview and the voice (`:101-112`).
- Location: its published privacy policy, read 6 Oct 2026, says it stores data on Google
  Cloud in Mumbai, India, and that the language-model step may be processed outside India
  by the model providers it names (OpenAI, Anthropic, Google). VENDOR-PUBLISHED. Its
  founder's email of 7 Oct 2026 says it is processed and stored in India (Mumbai).
  VENDOR-STATED. The public page names no city (D-680).
- Status: Core on the live deployment. Its policy names Sarvam, OpenAI, Anthropic, Google,
  Google Cloud, Razorpay and Meta as its own sub-processors and states a default retention
  of 180 days. Its email of 7 Oct 2026 (VENDOR-STATED, `docs/evidence/thinnest-ai-evaluation.md`
  §10 item 11): it will sign a DPA under the DPDP Act; recordings and transcripts are never
  used for training on Pro or Scale (on pay-as-you-go they may be, unless switched off on
  request); recording retention 30/49/75 days by plan, transcripts until deleted. No DPA is
  recorded as signed in this repository (OPERATIONS gate T-5).

### Pipecat Cloud (voice platform)

- Does: runs our own call program in a container. Replaced Bolna (deleted D-639, 2 Oct
  2026), a third-party voice platform that documented running calls on US infrastructure by
  default.
- Receives: the most sensitive combination on the register: live audio both ways, the
  transcript as produced, the agent's instructions, its knowledge, and, where caller
  continuity is on, the note of what a returning caller said before. The platform runs the
  container they pass through; that is a distinction about purpose, not access.
- Location: the region the vendor calls "ap-south". A region name, not a residency
  commitment; which country or city it is in is NOT ESTABLISHED. Both documented hosts are
  egress-blocked from the build environment (re-measured 15 Sep 2026).
- Status: configured, not enabled. No account, the manifest has never been applied, no
  container started, no call run. Not established: operating legal entity and country; where
  "ap-south" is; what its terms permit including training; retention; whether a DPA can be
  entered; its own sub-processors.

### Cartesia (alternative voice platform)

- Contingency engine adapter (`engine/cartesia.py`), never adopted. Would receive the same
  categories as the call platform. Location not verified. Nothing sent.

### Sarvam (speech-to-text, post-call extraction, assistant standby)

- Does: speech recognition during the call on `ENGINE=pipecat` only (on the live deployment
  the hosted voice platform recognises speech); on every deployment, the first extraction
  pass over the transcript (`SARVAM_API_KEY` is required);
  standby for the in-app assistant if no other provider can answer, where it answers in
  prose only, is given no look-up tools, cannot read leads, calls or campaigns and cannot
  fill a form or propose a change. Since 18 Sep 2026 (D-629) it synthesises no voice.
- Receives: call audio and the raw, unredacted transcript (a callback-number field needs the
  digits).
- Location: India for the COMPANY; not India for the data. Its privacy policy ("Cross-Border
  Data Transfers") says personal data may be transferred to and processed outside India,
  naming US cloud infrastructure (AWS, GCP, Azure) and analytics providers, EU model and
  security vendors, and other jurisdictions as necessary, under EU SCCs, adequacy decisions
  and DPAs. Its India-storage commitments cover content-studio voice biometrics and payment
  data, not API speech traffic.
- Terms: ToS v2.0, effective 29 Jul 2026, s.17.5 permits training on inputs, outputs and
  usage data, per its privacy policy and applicable law and, where required, subject to a
  consent that may be declined or withdrawn (declining may restrict some offerings). Does
  not vary by plan. s.6.2: only a signed order form displaces it; we have none.
- Retention: content 30 days after last access by default, described as user-configurable
  (nobody has located where that setting is changed, so we do not say we changed it);
  account data account life + 90 days; voice samples until consent withdrawal + 30 days;
  security incident logs 7 years; deletion within 30 days of verifying a request, except
  legal retention, live proceedings or technical limits (then anonymised).
- EVIDENCE: VENDOR-PUBLISHED, read by the founder at www.sarvam.ai on 27 Aug 2026 and
  relayed. sarvam.ai is egress-blocked from the build container.
- Status: Core.

### Cartesia (text-to-speech, Studio)

- Receives the words the agent is about to speak, as text a turn at a time (can include a
  detail the caller just gave, repeated back). Not caller audio, not the transcript, not the
  recording, nothing from the dashboard.
- Its privacy policy says it may use information it receives to generate output and to
  train and enhance its models, with a forward-only opt-out form; zero-retention is
  enterprise-only, otherwise retention is governed by its published DPA (periods NOT
  ESTABLISHED; whether the DPA is self-serve signable NOT ESTABLISHED). Its policy says its
  services "are designed for users in the United States only and are not intended for users
  located outside the United States". Processing location NOT VERIFIED.
- EVIDENCE: VENDOR-PUBLISHED, RELAYED (`docs/evidence/cartesia-tts-verification-2026-09-06.md`
  §A5); cartesia.ai is egress-blocked here. Certification claims recorded there are
  marketing lines, not certificates, and are not repeated publicly.
- Path on the live deployment (D-687, 8 Oct 2026): the hosted voice platform sends the
  agent's words to Cartesia on OUR Cartesia key, installed in one shared ThinnestAI
  customer workspace with voice-only BYOK on (`thinnest-findings/mirror/snapshots/
  2026-10-07b/pages/api-reference/bring-your-own-keys.md:13-24`). Cartesia bills our
  account directly; ThinnestAI holds the key encrypted (`:77-78`). On `ENGINE=pipecat` our
  own call program calls Cartesia directly. Same receipt either way.
- Status: configured, not enabled. Nothing is sent until the Studio workspace exists with
  our key installed and a client publishes a Studio agent (OPERATIONS gate T-12).

### Gnani (text-to-speech, Clear)

- Same receipt as Cartesia's synthesis role. All three of its sites are egress-blocked
  (measured 15 Sep 2026). Only its price is read: Rs 27.00 per 10,000 characters,
  `app.gnani.ai/voice/pricing`, founder-relayed 19 Sep 2026, VENDOR-PUBLISHED. Nothing about
  training, retention, residency or a DPA is established. Its published SDK names the
  address its speech service answers on and no region.
- Status: configured, not enabled, and on `ENGINE=pipecat` only. Not used on the live
  deployment (`ENGINE=thinnest`), where the Clear quality is the hosted voice platform's own
  studio-band voices (D-687) and Gnani is not one of its voice providers. On `ENGINE=pipecat`:
  no credential, and the Clear rung is unsellable until an operator attests a billed price
  (hard rule 7). Nothing sent. The row stays because `gnani_api_key` is still a setting the
  Pipecat engine reads.

### Microsoft — Azure OpenAI (language models)

- The in-app assistant on every deployment (including the fallback for a client whose own
  model cannot serve the assistant, and the hourly memory distillation job), and the
  default in-call model on `ENGINE=pipecat`. On the live deployment (`ENGINE=thinnest`) the
  hosted voice platform runs the in-call model with its own providers, so Microsoft
  receives no call turns there.
- Receives: in call, the conversation turn by turn; on the dashboard leg, the redacted
  transcript a client asks to have re-read, what a user types, and look-up results (lead
  names and statuses, redacted call summaries, campaign and agent names, counts, knowledge).
  Phone numbers reach it as markers; no raw transcript or extraction payload.
- Location: United States, East US 2, by configuration. Vertex asia-south1 until 19 Aug
  2026; Azure South India 19-22 Aug 2026; East US 2 since 22 Aug 2026 (D-449). The endpoint
  names no region; gates 20/20c are human attestations.

### OpenAI (language models)

- Alternative for the IN-CALL leg on `ENGINE=pipecat` only (nothing on the live
  deployment, where the hosted voice platform runs the call's model); does not serve the in-app assistant because nobody
  here has read its data-use position (`DASHBOARD_TERMS_UNREAD`). Receives the conversation
  turn by turn; never the recording. United States; no Indian region to request.
  Client-selectable.

### Google — Gemini API (language models)

- Alternative for the in-call leg, and for the assistant only while a recorded confirmation
  holds that our Google account is on a no-training plan with nothing opted back in.
  Receives the same as Microsoft's legs; never a raw transcript, extraction payload, raw
  phone number or recording. Location: global; the developer API names no region.
  Client-selectable.

### Hostinger (hosting)

- Application, workers and PostgreSQL. Receives everything in the database. A Hostinger VPS
  (D-180), deployed to production on 7 Oct 2026. Which data centre, and so which country, the
  provisioned VPS is in is NOT RECORDED in this repository; D-180 chose India. Confirm it in
  the Hostinger panel before the public pages (which still say nothing is provisioned) are
  updated.

### Cloudflare (object storage, edge network)

- R2: recordings, exports, archived raw call documents, bodies delivered to client CRMs,
  database backup segments. We ask for the Asia-Pacific location hint; R2 guarantees a
  jurisdiction only for the EU, the US and US government workloads, with no India-only
  option, so the data is outside India and may be outside Asia. No city is published.
- Edge: every HTTP request including IP addresses. Global. Core.

### Resend (email)

- Hot-lead notifications (recipient address; lead name and call summary; phone masked) and
  operator alerts (identifiers only). United States. Core; a client-chosen SMTP server is
  selectable instead.

### Sentry (monitoring)

- Error reports and traces, redacted before leaving the process. Operated from outside
  India. Configured, not enabled (activates only when a DSN is set).

### Razorpay (payments)

- Payer contact details and payment metadata; card numbers never reach us. India.
  Configured, not enabled; no merchant account confirmed.

### Supermemory (knowledge search)

- Knowledge store and search outside the call (assistant and dashboard search); the live
  call answers from a sealed copy in the call program. Would receive every published
  knowledge passage and the questions asked of it. Intended to be self-hosted on our server,
  but its address is an operator setting that takes effect with no release. Its terms and
  delete surface are unread (supermemory.ai egress-blocked, 14 Sep 2026); erasure rests on
  our reading of the software and is refused rather than reported done if the store will
  not accept it. It buys query embeddings from a model vendor on our account. Configured,
  not selected.

### Cohere (knowledge search)

- Embeddings, only if the retrieval service adopted does not bundle its own. Outside India.
  Contingency; appears nowhere in the code.

### Meta, AiSensy, Interakt (messaging); Google, Meta (client integrations)

- WhatsApp via Meta: post-call follow-up is configured, not enabled (no provider chosen);
  the in-call action runs on a credential the client supplies. AiSensy and Interakt are
  alternative BSPs for the in-call action on the client's own credential; their locations
  are NOT VERIFIED (both hosts egress-blocked; `apps/api/actions/whatsapp.py` is REPORTED).
  A separate recorded messaging opt-in is required for every recipient.
- Google Sheets: lead fields (phone raw or masked by option), never recording or
  transcript; access by sharing a sheet with our service account. Google Calendar: start,
  end and the mapped title (commonly the caller's name); configured, not enabled (no OAuth
  client). Meta Lead Ads: lead-form answers including name and phone, per lead source on the
  client's own page token. All global.
