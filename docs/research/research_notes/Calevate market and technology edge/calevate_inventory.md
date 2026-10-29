# Calevate's own product capabilities (repo inventory, as of 30 Oct 2026)

Scope: facts read from the repository at `D:\Agency\calevate` (branch `claude/calevate-legal-ops-docs-rd2c4t`, head b2062cecc). Citations are repo paths (file:line) or decision-log rows in `docs/ROADMAP.md` §6 (D-xxx). Nothing was run; this is a read-only inventory. "Built" means the decision row or doc says built; live-production verification was not part of this pass.

## 1. Engine, voice and agent builder

### Takeaway
Every call runs on ThinnestAI (hosted telephony, STT, LLM, TTS and recording). Calevate sells two voice rungs, Clear and Studio. It has a deep agent builder: up to four reply languages that follow the caller, per-language "packs", voice tuning, scripts with guided steps, knowledge fan-out, readiness scoring and practice tests.

### Cited Findings
- Engine: ThinnestAI hosts the whole call, including numbers, telephony, STT, LLM, TTS and recording. `ENGINE` accepts only `thinnest` and `fake`, and the Pipecat engine was removed (D-678, D-763) — docs/README.md:150-153 ("One-line summary").
- Tenancy at the engine: one ThinnestAI customer workspace per client (D-693). Each customer workspace holds 2 agents until ThinnestAI raises the limit; the account holds 100 workspaces and 20 concurrent calls (VENDOR-STATED 23 Oct 2026) — docs/README.md:140-145.
- Clear = ThinnestAI's own stack on its Studio band (default, D-792) or Premium band. Studio = Cartesia on Calevate's key through ThinnestAI's voice-only BYOK, with ThinnestAI's STT, LLM and telephony — docs/THINNEST-INTEGRATION.md:316-321 (§4a table).
- Clients see only the names Clear and Studio; no client-facing text names a vendor (D-679) — docs/BRD.md:284-297.
- Voices: clients never clone voices. They pick and preview voices that the admin added and enabled. Clones are admin-only, with two consents recorded (10 clones on Pro, 20 on Scale per vendor docs; 25 on the PAYG account per §28) — docs/THINNEST-INTEGRATION.md:324-326; CLAUDE.md (root).
- Studio voice tuning by clients: speed 0.6-1.5, volume 0.5-2.0 and one of eight emotions, with a "Hear it" sample capped at 20 per account per IST day. The voice model and pronunciation dictionary are operator-only (D-767, D-843) — docs/THINNEST-INTEGRATION.md:329; docs/SURFACES.md:287-292. Speed also applies on Clear through `voice.speakingSpeed` (D-884).
- Languages: the code's language enum lists 23 Indian languages (telugu, hindi, english_india, bengali, gujarati, kannada, malayalam, marathi, odia, punjabi, tamil, assamese, bodo, dogri, kashmiri, konkani, maithili, manipuri, nepali, sanskrit, santali, sindhi, urdu) — packages/shared/src/calevate_shared/languages.py:152-176. Telugu-first positioning — CLAUDE.md (root). Note: that file's comment still says "STT is Sarvam throughout", which predates the ThinnestAI engine. Which of the 23 are actually usable on ThinnestAI's STT/TTS was not verified in this pass.
- Reply languages: each agent can have up to four languages (main language first). Every agent "follows the caller", sent as `language: "auto"` (D-815, D-830) — docs/THINNEST-INTEGRATION.md:304-305.
- Language packs: one platform prompt block per language covering words to say, words to avoid and 8 example exchanges, measured before it ships (D-830); changes to spoken register ship only on a measured offline-eval gain (D-829) — ROADMAP D-829, D-830.
- Turn-taking and call handling: interrupt threshold `thinnest_interrupt_words`, default 2 words (D-862); re-ask after 5 s (D-835); the opening can wait for the caller's "Hello" (D-871, D-901); per-language filler lines on slow turns (D-858); "Patient caller" preset (D-907). Call handling (pause, hang-up, quiet caller, filler, background sound) is set per agent or for all agents in one place (D-898) — docs/SURFACES.md:294-303. Turn detection "Ear" uses the pause (D-924).
- Script builder: the agent page has seven tabs (Overview, Script, Training, Actions, What it notes, Voice, Settings) (D-825). Guided script steps hold up to 15 small steps (D-908). Separate opening lines for answering and for placing calls (D-920). Screen-guided calls exist, where the caller follows along on a screen (D-906).
- First agent: the first agent is built by chatting with Pip or by hand (D-854). "Meet your agent" is the first-run flow: multi-select jobs, AI-written follow-up questions and file upload (D-855, D-863, D-918).
- Readiness score: 0-100 gauge on the agent Overview (D-870, D-873, D-916).
- Knowledge ("What your agents know"): facts, files and links. Word, Excel, CSV, text and photos reach every agent. PDFs and links are read into a searchable copy but do not reach agents yet, pending ThinnestAI (D-868; switch `kb_send_extracted_files`) — docs/SURFACES.md:332-340; docs/THINNEST-INTEGRATION.md:300. Knowledge belongs to the client and fans out to every agent (D-689) — docs/THINNEST-INTEGRATION.md:301. Agents keep their most-asked facts "by heart", chosen per agent (D-896). A new knowledge file proposes script edits (D-923).
- Caller memory: on ThinnestAI the engine's caller memory (`recap`/`fresh`) is used (D-690, D-814). It is gated behind the client accepting a caller-memory statement (D-900).
- In-call model: the platform default is `gemini-2.5-flash-lite` (`PLATFORM_DEFAULT_LLM_MODEL`). The "own model" switch puts calls on Calevate's Gemini key (default Gemini 3.1 Flash-Lite, D-817), but `thinnest_own_model` is currently OFF — docs/BRD.md:268-271; docs/THINNEST-INTEGRATION.md:332ff. What a client may pick is `agents/llm_models.offerable_models()` — CLAUDE.md (root). Client-side "AI model" settings page — apps/web/src/lib/clientNav.ts:173.
- Compliance in prompts: the agent always answers truthfully whether it is an AI and whether the call is recorded. It never reveals its instructions (D-674). AI-disclosure and recording-notice volunteering are per-agent toggles (D-163) — CLAUDE.md hard rule 5.
- Practice tests / QA of agents: versioned test sets with three tries per test and before/after comparison (D-828). An LLM judge (D-777), "Improve my agent" (D-823) and "Suggest a fix" (D-909).

### Inferences
- The depth on Telugu/Indic spoken register (language packs, measured prompt changes, production Telugu call fixes D-877/D-887/D-894/D-910/D-912) is a differentiator relative to a generic builder. Its quality is still not externally attested: gate T-6 (Telugu ear test) is not filed — docs/PRODUCTION-READINESS.md:44.

### Gaps
- Not verified which of the 23 enum languages ThinnestAI's STT/TTS actually supports end to end.
- Latency figures: per-call reply times are stored and reported (D-770, D-902), but no measured production p50/p90 figure was found in docs.

## 2. Inbound, outbound, campaigns, lead calling, call-backs, follow-ups

### Takeaway
Calevate has an inbound receptionist, outbound campaigns (scheduled, recurring, results by outcome), instant new-lead calling and call-backs. A per-lead "Follow-ups" journey engine is designed (D-940, 30 Oct 2026) but not yet in code.

### Cited Findings
- Campaigns: draft edit, delete, stop, duplicate (optionally with unreached contacts), contacts from leads, complaint review. Automatic pauses on complaint review, no credits or spend cap. One-time scheduled start and weekly recurrence — docs/SURFACES.md:657-673 (D-773).
- Campaign results count people, not calls (D-913), broken down by the agent's outcomes and choice fields (D-905). Pausing a campaign holds its call-backs and stopping it calls them off (D-914).
- Calling hours: outbound runs 09:00-21:00 IST, except a test call to the owner's own attested number (D-866). Calling hours are enforced per call by Calevate (D-872). Holidays, after-hours behaviour and the answering-machine switch are on "Leads & hours" — docs/FOLLOW-UPS.md:37; clientNav.ts:139.
- Instant new-lead call plan: agent, wait and retries (D-716), to be migrated into a "Call new leads" Follow-up — docs/FOLLOW-UPS.md:37, 210-225.
- Call-backs: a client nav entry exists (clientNav.ts:101). A call-back keeps the person, reason and campaign (D-905).
- Follow-ups (D-940): design only. Triggers are new lead, call ended, manual, and a date on the lead. Steps are call, decide-on-outcome, wait, WhatsApp template, assign, set status, tell team, after-call action and end. Pip builds a Follow-up from a sentence and there is no canvas in v1. Six starters: call_new_leads, qualify_new_leads, missed_call_callback, appointment_reminder, payment_reminder, win_back — docs/FOLLOW-UPS.md:27-37, 105-208. Calevate deliberately does not use ThinnestAI Workflows, because those calls would bypass its compliance gate — docs/FOLLOW-UPS.md:7-25. No `follow_ups` code exists under apps/api (grep, 30 Oct 2026), and no D-940 row is in ROADMAP.md yet.
- Live call log: calls appear from the moment of dial with a Live mark (D-886). Feeds update live across both consoles (D-774). The dashboard test-call card tracks the call (D-885).
- "Tell my team": a caller the agent cannot help is handed to the business's team by email or the client's WhatsApp, either after the call or in-call through the `tell_the_team` action (D-904).
- Phone numbers: ThinnestAI numbers are rented in the client's business name in its own workspace once KYC is verified (D-693) — docs/PRODUCTION-READINESS.md:51-53. A client can also bring a number (forward to a brought number, D-852; nav "Your phone number", clientNav.ts:105). A stopped client's number is held, not released (D-860). Conflicting note: docs/PRODUCTION-READINESS.md B1 still describes `PROVISIONING_IMPLEMENTED = False` / Model B carrier purchase (D-474). That predates D-693 and appears stale.

### Gaps
- D-867 (lending the shared trial number for inbound trial test calls) is "designed, not built".

## 3. CRM, lead extraction, outcomes

### Takeaway
Calevate has a schema-driven lead CRM with list and board views, per-agent AI-drafted business outcomes, post-call extraction and knowledge-gap detection.

### Cited Findings
- Leads list ⇄ board (one column per status); Performance and Needs-attention screens — docs/SURFACES.md:260-263.
- Extraction schema: a per-agent field list drives the CRM columns ("Lead details"), and AI suggests changes from the script (D-889). Choice answers that fall outside a list are kept verbatim (D-889). Lakh/crore spoken ranges are parsed (D-881).
- First post-call extraction runs on Sarvam (it reads the raw transcript), permanently — CLAUDE.md (root). The language/English pass runs as its own job after the lead is saved (D-931).
- Outcomes: each agent has its own business outcomes, drafted once by AI and edited by the owner. A buying outcome moves the lead to Interested (D-836). A hot outcome alerts the owner, and the client's CRM hears every lead and status move (D-841).
- Knowledge gaps: detected per call and aggregated by topic (apps/api/insights/service.py:1-12), answered through the teach/questions flow (D-893).
- Swipe actions on calls: resolved / needs_you (D-869).

### Gaps
- Extraction quality scoring is BLOCKED; Telugu extraction quality is recorded as UNMEASURED — docs/PRODUCTION-READINESS.md A3.

## 4. Channels (WhatsApp, email, SMS)

### Takeaway
Voice is the core. WhatsApp is built through Meta Embedded Signup (the client's own number, Calevate as Tech Provider). Email covers alerts, auth and team hand-offs. No SMS, by decision.

### Cited Findings
- WhatsApp: clients connect their own WhatsApp through Meta Embedded Signup, with Calevate as Meta Tech Provider. Four Calevate UTILITY templates exist in Telugu, Hindi and others. The agent asks before it sends, and the "yes" is recorded (D-784; `apps/api/whatsapp/` signup, accounts, templates, webhooks).
- Conflict: docs/PRODUCTION-READINESS.md A3 says "WhatsApp BSP decision + WABA BLOCKED" (`CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA = False`). Whether any live WABA is connected is not established.
- Owner WhatsApp hot-lead alerts require an opt-in — docs/SURFACES.md:319-323. Messaging-consent ledger — docs/SURFACES.md:639-647.
- SMS: "Its SMS needs DLT, and messaging is WhatsApp only (D-700)" — docs/FOLLOW-UPS.md:20-21.
- Email: designed HTML alarm and auth emails (D-790); an email redesign per purpose is STAGED until a rebrand name (D-933).
- Website chat or other text channels: not found.

## 5. Integrations

### Takeaway
One in-call action executor covers caller lookup, Google Calendar, WhatsApp, Razorpay payment links, Zoho CRM, HubSpot, Google Sheets and the client's own API. Signed outbound webhooks, a lead-ingest webhook with dry-run, and a native Meta Lead Ads receiver are also built.

### Cited Findings
- In-call actions (D-700): caller lookup, Google Calendar, WhatsApp, Razorpay payment links on the client's account, Zoho CRM, HubSpot, Google Sheets and the client's own API, all through one executor. Max 4 client actions per agent on ThinnestAI (`THINNEST_CLIENT_ACTIONS_MAX`) — docs/ROADMAP.md:937. Code: apps/api/actions/{calendar,crm,sheets,payment_links,whatsapp,oauth,pre_dial}.py.
- Outbound webhooks: HMAC-signed events, delivery rules, secret rotation and `call.recording_ready` with a signed recording link — docs/WEBHOOKS.md §1; docs/SURFACES.md:358-359. Google Sheets as a destination — docs/WEBHOOKS.md:180, 227.
- Lead ingest: endpoint, field mapping, consent field, dedupe, native Meta Lead Ads and a dry-run tester — docs/WEBHOOKS.md §2.1-2.7; the "Lead sources" screen has a no-call test — docs/SURFACES.md:310-313.
- Zapier/Make, Salesforce, IndiaMART, JustDial, 99acres/Housing.com or Outlook calendar connectors: not found.

## 6. Pip (in-app AI assistant)

### Takeaway
Pip is an agentic assistant in both consoles. It covers 26 client work areas with find/do tools, one-click plans for acting on many records, charts that can be pinned, proactive notes, a troubleshoot mode, file input and quality tracking.

### Cited Findings
- Pip, named with a hand-drawn face, is the single AI assistant (D-772, D-820, D-821). It is off until the account OWNER turns it on (D-788).
- Tools are grouped by area: calls, callbacks, leads, campaigns, agents, knowledge, numbers, team, settings, integrations, billing, reports, routines. One lens covers leads and calls, and a frozen one-click plan handles actions that reach callers or spend credit (D-893).
- Coverage matrix of every client and admin screen, with "how do I" answered from product docs (D-938) — docs/COPILOT-COVERAGE.md.
- Charts and tables of real account data that can be pinned to home as live cards (D-934). Proactive hourly notes, 08:00-21:00 IST (D-936). Troubleshoot mode giving ordered checks and one fix button (D-935). Thumbs up/down and success scores (D-937).
- Files: up to 5 per message, 20 MB per file (D-781). Cross-device live sync (D-782). Pip fixes auto-healer problems (D-776). Routines exist (COPILOT-COVERAGE §Routines).
- Model: Gemini first, then Azure OpenAI East US 2 only where configured, then the Sarvam standby (D-899). Background work uses the Gemini Flex tier (D-930).
- Missing, ranked: saved views, DNC check, consent lookup, raw transcript read, AI-quota read, test deletes, outcome redraft and more — docs/COPILOT-COVERAGE.md:463-483.

## 7. Analytics, reporting, QA, testing, insights

### Cited Findings
- Analytics API: heatmap, durations, timeline, campaigns and stats in IST days, plus announcements and a notification bell (D-869).
- Admin Voice response time: real per-call reply times from ThinnestAI, median and p90, by client, agent, rung and day (D-770, D-902) — docs/SURFACES.md:571-581.
- Weekly QA spot-check sampling of about 5% of calls per client, using a keyed-hash draw (apps/api/quality/sampling.py:1-12). Client "Quality" nav item — clientNav.ts:115.
- Client health exception board with 5 signals — docs/SURFACES.md:407-430.
- Experiments: script A/B arms, each carrying the knowledge (D-806).
- Practice tests and an LLM judge (D-777, D-828, D-844, D-845, D-917).

## 8. Compliance (consent, DNC, KYC, disclosure, DPDP)

### Cited Findings
- Outbound needs a verified KYC record (manual review or DigiLocker) and an accepted no-cold-calls pledge, not DLT. Inbound is never gated (D-692) — docs/README.md:134-135. Counsel's view (gate K-3) is BLOCKED — PRODUCTION-READINESS A3.
- Verify your business: one page (D-875) — docs/SURFACES.md:324-330. Reg 4 autodialer notice removed (D-762); sender attestation retired (D-775).
- DNC: tenant and global lists; DNC additions propagate before the next dispatch tick; the big red switch (global outbound halt) — docs/SURFACES.md:582-593, 528-535, 638.
- DPDP: subject export and erasure with a proof certificate — docs/SURFACES.md:648-655. Erasure also deletes data at ThinnestAI by code (D-922). Recording retention and re-copy to R2 (D-805, D-808).
- Transcripts default to redacted in API responses; raw text only behind a role check and audit — CLAUDE.md hard rule 5.
- Agreements, data rights, caller privacy notice and messaging consent nav items — clientNav.ts:127-141.
- Disclosed limits: no India data-residency claim; Sarvam may train on inputs (ToS s.17.5) — docs/README.md:160-170.

## 9. Billing and pricing

### Takeaway
Prepaid credit at ₹1 = 1 credit in six packs (₹2,000-₹50,000). Clear ₹4.50/min and Studio ₹6.00/min, flat on every pack, billed in 30-second steps. 7-day / 15-minute free trial. Online payment is not yet live.

### Cited Findings
- Rate card: Clear ₹4.50 and Studio ₹6.00 on packs starter ₹2,000, growth ₹5,000, scale ₹10,000, plus ₹15,000, pro ₹25,000 and max ₹50,000 (D-728) — docs/BRD.md:221-237. Verified in code: `Decimal("4.50")` / `Decimal("6.00")` per pack — apps/api/billing/credit_packs.py:211-237.
- Billed per minute in 30-second steps at the rate frozen on the credit lot, oldest lot first — docs/BRD.md:223-227. An optional monthly platform fee set in the ops console (D-707) — docs/BRD.md:214-218.
- Credit lapses 12 months after purchase, but only once the client has accepted Terms rev. 19 (D-897, D-900) — docs/BRD.md:247-252.
- Free trial: 7 days and 15 minutes (`self_serve_trial_days=7`, `self_serve_trial_free_minutes=15`); Studio test minutes are capped at 15 (`trial_studio_minutes`) — packages/shared/src/calevate_shared/config.py:635, 668-669; D-853.
- Unit cost (VENDOR-STATED): Clear ₹2.50/min (Studio band) or ₹2.00 (Premium). Margin is 43.1% or 54.5% at ₹4.50. Studio costs ₹1.50/min plus Cartesia ₹2.06-3.42, giving a 40%-17% margin — docs/BRD.md:259-266.
- Payments: Razorpay top-up code is built, but live keys are BLOCKED on the founder (gate 44). Until then a super admin grants credit (D-890) — docs/README.md:130-131; PRODUCTION-READINESS A3.
- GST: no GST at launch; documents are a bill of supply or proforma, with no tax invoice without a GSTIN — docs/legal/LEGAL-OPS-PLAYBOOK.md:115, 513. Statements, daily spend, number-rental line and printable statement — docs/SURFACES.md:351-357, 480-482.
- Client spend caps and AI-help allowance with explicit paid top-up — docs/SURFACES.md:341-350.

## 10. Onboarding, team, mobile, UI language, admin/ops, reliability

### Cited Findings
- Self-serve signup exists, but `self_serve_signup_enabled` defaults to OFF — docs/SURFACES.md:681-705. The operator wizard is an alternative. Go-live guide (apps/api/go_live).
- Team roles: `ROLE_PERMISSIONS` defines "staff" and "owner" for the client realm (apps/api/core/rbac.py:282-328). Team settings page, lead assignment to members — clientNav.ts:155; docs/SURFACES.md:461-473.
- Auth is first-party, with an 8-character minimum password (D-765) and two realms (D-165/D-177).
- Mobile/PWA: no web manifest or service worker found under apps/web/src/app or public; no native app found. Swipe actions exist (D-869).
- UI language: root layout `lang="en"` (apps/web/src/app/layout.tsx:199); no i18n library found in apps/web/package.json. The dashboard UI is English-only as far as the code shows.
- Admin: health board, hold queue, KYC, global DNC, platform config and secrets, outbound halt, load shed, outbox replay, view-as with an audited grant, credits, grants, trials, prompt history and rollback, voices, reply times — docs/SURFACES.md:370-635. Auto-healer (D-701, D-776); alarm index runbook (docs/README.md:118).
- Reliability: backups use one chain, wal-g to Cloudflare R2 (D-927), with RPO 30 min (D-928). However, docs/PRODUCTION-READINESS.md C says continuous backups have NEVER RUN on the VPS, and docs/README.md:128-129 agrees. A separate `workers-bulk` queue keeps the post-call pipeline unblocked (D-929). Deploys are run by hand and CD is disabled — docs/README.md:144-145.

## 11. Open founder decisions, external blockers, documented gaps

### Cited Findings
- External blockers before a paying client goes live: ThinnestAI's signed DPA (T-5), backups never run, Razorpay live keys (gate 44) and per-client outbound KYC — docs/README.md:122-138.
- Founder-blocked: Gemini paid tier (gate 41), which gates the own-model switch; Razorpay keys — docs/PRODUCTION-READINESS.md A2/A3. Counsel: K-3.
- Untested-live vendor premises: T-15, T-20, T-29 and T-35 (agents moving into the client workspace, built against the fake engine only) — docs/PRODUCTION-READINESS.md:43-46.
- Waiting on ThinnestAI: PDFs and links reaching agents (D-868). Designed but not built: shared trial number for inbound (D-867); Follow-ups (D-940, design dated 30 Oct 2026).
- Not claimed: India-resident data plane or language leg — docs/README.md:160-163.
- Admin-console LLM latency tracing is a named gap (D-49) — docs/README.md:155.
