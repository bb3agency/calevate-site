# Calevate gap report: what is still missing to sell and compete (9 Oct 2026)

Read-only review. No repo file was edited, nothing was run, and no tests were run.

**Sources**
- The repo at `D:\Agency\calevate`, working tree on 9 Oct 2026, including uncommitted lanes.
- rememory project `calevate`: the Outpero teardown parts 1-9 and the synthesis, ids cited inline.
- Public web pages fetched on 9 Oct 2026, URLs inline.

**Evidence labels (hard rule 11)**
- **REPO**: read in code or docs this session, with the file named.
- **WEB-9OCT**: read on the vendor's public page today.
- **TEARDOWN-AUG**: the authenticated Outpero teardown of 10-11 Aug 2026 (rememory). It is two months old, so anything not re-read today may have changed.
- **REPORTED**: in our docs or memory but not re-verified.
- **UNKNOWN**: not verified.

**Lanes already running.** These are listed as *in progress*, not as gaps:
- COPILOT: tools, routines, side panel, workspace and inline suggestions.
- TRIAL (D-697).
- PAYMENTS (D-698).
- Finished but uncommitted:
  - D-695 business profile and setup wizard;
  - D-696 PAN-only KYC, with the DigiLocker provider search still open;
  - the auth redesign;
  - the copy cleanup.

---

## 0. The five things to read if you read nothing else

1. **A client's own in-call actions do not run on the production engine.** These are WhatsApp, Google Calendar and Custom API.
   - `apps/api/engine/thinnest.py:311-331` declares `action_tools=False`.
   - `:969-970` refuses a publish that carries any action.
   - Outpero sells calendar booking and WhatsApp inside its ₹1,899 plan (WEB-9OCT, outpero.com/pricing).
   - ThinnestAI documents custom actions (`thinnest-findings/mirror/snapshots/2026-10-08/pages/agent/custom-api.md`), and we already use them for our own four platform tools. So this is buildable on our side.
2. **The repo does not record a live production call on ThinnestAI** (UNKNOWN). ROADMAP gate G0 (`docs/ROADMAP.md:44`) and `runbooks/thinnest-first-live-call.md` are still the checklist. Telugu quality on this engine is still an open T-gate.
3. **The ThinnestAI plan caps us at 3 customer workspaces on pay-as-you-go** (OPERATIONS T-8, REPO). Under D-693 one paying client is one workspace, so client #4 is blocked until the plan is upgraded.
   - Concurrency is 5 on pay-as-you-go (REPORTED, founder-relayed, memory 0036f3d9).
   - Outpero includes bulk campaigns of up to 20 concurrent calls (WEB-9OCT).
4. **The Clear rung's margin is thin.**
   - Clear sells at ₹4.00/min (D-681/D-601, REPO).
   - Its cost is about ₹3.27/min before the ThinnestAI Pro subscription and GST: an 18.3% gross margin (memory 5b189386, REPORTED, vendor-stated rates).
   - Outpero's Value tier is ₹3/min (WEB-9OCT).
   - This is a price-position decision for the founder, not an engineering task.
5. **No signed DPA with ThinnestAI** (OPERATIONS T-5, REPO). Our legal pages describe its India-storage and no-training position as "its statement, not a term we hold". Any client that asks for a DPA chain will find the gap.

---

## 1. Feature-parity matrix

**Columns**
- **Cal** = Calevate. Status is Have, Partial, In progress (with the lane) or Gap.
- **Outpero**: WEB-9OCT unless marked TEARDOWN-AUG.
- **Bolna** (bolna.ai and /pricing), **Retell** (retellai.com and /pricing), **Vapi** (vapi.ai/pricing), **Ringg** (ringg.ai/pricing) and **Gnani/Inya** (gnani.ai; inya.ai/pricing now 301-redirects to gnani.ai): all WEB-9OCT.
- "n/s" = not stated on the page read.

### Onboarding

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Self-serve signup | Have. `signup/page.tsx`, gated by `NEXT_PUBLIC_SELF_SERVE_SIGNUP_ENABLED`; production value UNKNOWN | Yes, 20 credits (pricing page) or 50 credits (homepage): its own pages disagree | Yes, $5 credit | Yes, $10 credit | Yes, $5 credit | Yes, free credits | Demo / API key |
| Guided setup | In progress: D-695 wizard (uncommitted) | "Swara HR" setup assistant | Templates, agent library | n/s | n/s | n/s | n/s |
| Free trial | In progress: TRIAL lane, D-697 (outbound test calls from a shared number) | Free trial credits | $5 credit | $10 credit | $5 credit | Credits | n/s |
| Free public demo line (call without signing up) | Gap | Yes, "call a live demo agent for free" | n/s | n/s | n/s | n/s | n/s |

### Agent builder

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Structured script | Partial. `calevate_shared/call_script.py` has opening, ordered steps, FAQ fence and end rules, with **no branching** | Branching 15-section graph with an adherence slider (TEARDOWN-AUG) | Playground and templates | Drag-and-drop flow canvas | n/s | No-code | "Application Studio" |
| AI edits the flow | In progress: COPILOT lane (agent actions) | Swara edits the flow by voice or text (TEARDOWN-AUG) | n/s | n/s | n/s | n/s | n/s |
| Test before live | Partial: phone test calls (trial panel, copilot `_plan_test_call`). No text sandbox, browser call or simulation | Text "Try it" sandbox, test call (TEARDOWN-AUG) | Playground | Simulation, and production calls turned into regression tests | "Testing and simulation" on every plan | n/s | n/s |
| A/B testing of agent versions | Gap | n/s | n/s | Yes | n/s | n/s | n/s |
| Versioning | Have: prompt and config versions, drift sweep | Last 3 versions (TEARDOWN-AUG) | n/s | Yes | n/s | n/s | n/s |

### Voices and languages

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Voice catalogue | Have: Clear and Studio rungs, admin-curated, previews, admin clones (D-687/688) | Value, Standard and Premium tiers, personas | Many TTS vendors | Many TTS vendors | Many | Own TTS | Own TTS |
| Languages sold | **3**: `OFFERED_LANGUAGE_IDS` = Telugu, Hindi, English-India (`languages.py:626`) | Lists Telugu, Hindi, English, Tamil, Kannada, Marathi and Malayalam; claims "10+" | "10+ vernacular" | Multilingual | Multilingual | n/s | 40+ |
| Ambient sound bed | Gap | Yes (TEARDOWN-AUG) | n/s | Denoising add-on | n/s | n/s | n/s |

### Knowledge

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Knowledge base | Have: per client, shared across its agents (D-689), with OCR and webpage | Per employee: docs, webpage, photo | Yes | Yes, +$0.005/min | n/s | n/s | n/s |
| Knowledge-gap detection from real calls | Have: `apps/api/insights/detection.py` | Yes (TEARDOWN-AUG) | n/s | Pattern detection | n/s | n/s | Analytics |

### In-call actions

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| WhatsApp during the call | **Gap on production.** Built in `apps/api/actions/whatsapp.py` for Pipecat, but `action_tools=False` on thinnest | Yes | n/s | SMS | n/s | WhatsApp agents | n/s |
| Calendar booking | **Gap on production** (`actions/calendar.py` exists, Pipecat only) | Google Calendar | n/s | Calendars | n/s | n/s | n/s |
| Custom API | **Gap on production** (`actions/execution.py`, Pipecat only) | Yes | Function calls | Functions | Tools | n/s | n/s |
| Live transfer | Have: in-call hand-over via `handOver` + `escalate_to_human` (D-690). Not warm, no briefing | Yes (memory 24cf6d76) | Yes | Warm transfer with briefing | Yes | n/s | Agent Assist |
| Opt-out, call-back | Have: platform custom actions (THINNEST-INTEGRATION §8) | DNC, callbacks | n/s | n/s | n/s | n/s | n/s |
| Voicemail / answering-machine detection | Gap. We send `detectMachines:false` (THINNEST-INTEGRATION §2) | Voicemail webhook trigger (TEARDOWN-AUG) | n/s | Yes | n/s | n/s | n/s |

### Campaigns

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Bulk campaigns | Have: CSV, compliance gate, recurrence (D-79), first-campaign review | Up to 20 concurrent calls in the plan; recurring | Batches | Batch, +$0.005/dial | n/s | n/s | n/s |
| Instant lead call-back | Have: `apps/api/ingest/service.py` (form-to-dial target under 60 s) | "Under 30 seconds" | n/s | n/s | n/s | n/s | n/s |
| Concurrency ceiling | **5** (ThinnestAI pay-as-you-go, REPORTED) | 20 | 25 on pilot | 20 free | 4-30 by plan | "as required" | n/s |

### CRM and lead handling

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Schema CRM | Have: typed extraction, leads table and board (`LeadBoard.tsx`), saved views, bulk actions, Needs-attention queue, call-backs | Untyped capture variables; table, grid and kanban (TEARDOWN-AUG) | Dispositions API | Post-call analysis | n/s | n/s | n/s |
| Native CRM connectors (HubSpot, Zoho, Salesforce, LeadSquared) | **Gap.** Generic signed webhooks and Google Sheets only (`integrations/routes.py`) | Logos shown for Salesforce, HubSpot and Zoho; depth UNKNOWN | n/s | HubSpot, GHL | n/s | n/s | n/s |

### Analytics and QA

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Analytics and QA | Have: Performance (funnel, busiest hours IST: `crm/performance.py`), Quality, 5% QA sampling, client QA reports (D-73) | Performance suite, "built-in call QA" | n/s | AI QA $0.10/min, A/B comparison | Monitoring | Advanced analytics ₹2/call | 100% call scoring |

### Integrations

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Lead sources | Have: signed generic webhook, **native Meta Lead Ads** (`ingest/meta.py`), Sheets | Meta/Instagram ads, forms, Zapier, Pabbly, webhooks | n8n, Make, Zapier | Make, n8n, GHL | n/s | n/s | n/s |
| Zapier, Make or Pabbly app listing | Gap. Inbound and outbound webhooks work with them generically, but there is no listed app | Zapier and Pabbly | Zapier, Make, n8n | Make, n8n | n/s | n/s | n/s |

### Billing and pricing

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Model | Prepaid credits; Clear ₹4.00 flat, Studio ₹7.00 falling to ₹5.50 by pack (BRD §6, REPORTED); 30-second steps (D-681). **In progress: PAYMENTS lane** (Razorpay live, auto-recharge, refunds, receipts) | ₹1,899 per employee per 30 days (launch price, struck from ₹2,499) + ₹3/5/7 per min; 30-second blocks | 6.00¢ falling to 4.51¢ per min, pilots | $0.07-0.31/min, itemised | $0.05/min hosting + providers | ₹6/min, number ₹499/month | Not published |
| Numbers | Have: client buys in its own name, ₹499/month by attestation (D-681, D-693) | Number included with the hire fee; homepage also says ₹649/month | Twilio, Plivo, Vobiz, SIP | $2/month, branded caller ID | Telephony, SIP | ₹499/month | n/s |

### Compliance

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Compliance posture | Have: truthful-answer floor, two-way DNC on every path, KYC + no-cold-calls pledge (D-692/696), redaction by default, consent ledger, published legal set (rev 15) | KYC'd numbers, "DLT-registered" line, AUP | India/US residency claim | SOC 2 Type II, HIPAA, ISO 27001 | HIPAA add-on, SOC n/s | n/s | SOC 2, ISO 27001, PCI-DSS (claims) |

### White-label and API

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Public API and keys | **Gap.** No client API-key model found in `apps/api` | Lead intake URL per employee only (TEARDOWN-AUG) | Full API, sub-accounts | Full API | Full API, multi-org | STT API | API |
| Agency / reseller white-label | Gap. We hide the vendor (D-679), but nobody can resell us | n/s | Sub-account APIs | n/s | Orgs | n/s | Partner programme (contents n/s) |

### Mobile

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Mobile | Gap: no PWA manifest or app found under `apps/web/src/app`. Responsive quality UNKNOWN | Responsive web with mobile bottom nav (TEARDOWN-AUG); no app | n/s | n/s | n/s | n/s | n/s |

### Support and docs

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Help docs | Gap. `/resources` is a sales explainer; there is no client help centre or API docs | docs.outpero.com, 27 topics (TEARDOWN-AUG) | Docs site | Docs | Docs | n/s | docs.gnani.ai |
| Assistant in the product | In progress: COPILOT lane | Swara | n/s | n/s | n/s | n/s | n/s |
| Status page | Gap | "All systems operational" footer badge (TEARDOWN-AUG) | Status page link | n/s | n/s | n/s | n/s |
| SLA | Terms say "There is no service level agreement" (`lib/legal/terms.ts:635`) | Marketing says 99.9%; their Terms disclaim it (TEARDOWN-AUG) | n/s | Enterprise 24/7 | 99% on Pro, 99.9% on Premier | n/s | n/s |

### Inbound receptionist

| Capability | Cal | Outpero | Bolna | Retell | Vapi | Ringg | Gnani |
|---|---|---|---|---|---|---|---|
| Inbound 24/7 | Have: inbound on a client-owned number, gated to paid accounts by the TRIAL lane | **"Coming soon"** (homepage WEB-9OCT) | Inbound API | Yes | Yes | Yes | Yes |

---

## 2. Ranked gaps

### P0: blocks selling to the first paying client

| # | Gap | Why it matters (evidence) | Size | Modules | Lane dependency |
|---|---|---|---|---|---|
| P0-1 | **Prove a live production call on `ENGINE=thinnest`**, inbound and outbound, plus a Telugu ear test | No record in repo of a placed call. ROADMAP:44 gate G0; `runbooks/thinnest-first-live-call.md`; OPERATIONS T-series (Telugu quality). Every competitor sells on demo calls. | S of engineering, founder time | engine/thinnest*, voice-runtime signed_intake, workers pipeline | TRIAL needs the shared number to work. Do this before the TRIAL lane goes live. |
| P0-2 | **Client in-call actions on thinnest**: WhatsApp confirmation, calendar booking, Custom API | `thinnest.py:311-331` (`action_tools=False`), `:969-970` refuses the publish. Outpero bundles calendar + WhatsApp in its plan (outpero.com/pricing, WEB-9OCT). Vendor custom actions exist (`agent/custom-api.md`), and our platform tools already use them (`reliability/engine_actions.py`). | M-L: render `ActionToolSpec` as vendor actions per workspace, secret per agent, drift check, conformance | engine/thinnest.py, engine/thinnest_actions.py, reliability/engine_actions.py, actions/*, agents/service.py:2615 | COPILOT TOOLS lane may already expose action authoring. **Interim:** make sure the client UI does not offer actions that then fail at publish (UNKNOWN whether it hides them today). |
| P0-3 | **ThinnestAI plan and concurrency.** 3 customer workspaces on pay-as-you-go; 5 concurrent calls | OPERATIONS T-8 (REPO); memory 0036f3d9 (concurrency, REPORTED). The 4th paid client cannot be provisioned. A campaign at 5 concurrent calls is weak against Outpero's 20. | S of engineering (`thinnest_max_concurrent_calls` is a setting), a commercial decision | engine/carrier_pacing.py, workers/engine_workspaces.py | TRIAL moves provisioning to first payment, so trials do not eat the cap. Keep it that way. |
| P0-4 | **Payments live** | Nobody can pay without it | In progress | billing/* | **PAYMENTS lane**. Not a gap. |
| P0-5 | **Self-serve signup switched on in production**, or a decision that sales is invite-only for now | `SIGNUP_OPEN` is a build-time env var (`lib/api/signup.ts:132`). The production value is UNKNOWN. | S | apps/web build env, compose.prod | TRIAL + ONBOARDING |
| P0-6 | **What the client is told about a hand-over request with no destination**, and about `lead.captured` / `conversation.escalated` | THINNEST-INTEGRATION §3 step 2: "no product surface consumes a notice yet"; §8: without a destination "the request is recorded, not bridged". A caller who asked for a human must reach somebody. | S-M: route to Needs-attention + hot-lead alert | ingest_engine_notice, crm/attention.py, workers/notifications.py | none |
| P0-7 | **ThinnestAI DPA and training statement in writing** | OPERATIONS T-5 (REPO). Our legal set marks it "not a term we hold". | External: vendor signature | docs/legal, lib/legal/subprocessors.ts | none |

### P1: needed to compete

| # | Gap | Evidence | Size | Modules | Lane dependency |
|---|---|---|---|---|---|
| P1-1 | **More languages on offer.** Tamil, Kannada, Marathi, Malayalam | We sell 3 (`languages.py:626`). Outpero lists 7, Bolna "10+", Gnani 40+ (WEB-9OCT). ThinnestAI answers in the caller's language (`channels/voice.md:193-196`), so the engine can carry more. Quality per language is UNKNOWN until an ear test is run. | S per language once tested (offer-seam rows + picker) | calevate_shared/languages.py, agents/engine_catalogue_offer.py | none |
| P1-2 | **Test without a phone.** Text sandbox or browser test call, plus a public demo line on the marketing site | Outpero "Try it" (TEARDOWN-AUG) and a free demo call (WEB-9OCT); Vapi and Retell simulation (WEB-9OCT). ThinnestAI has a website widget channel (`channels/website.md`); whether it can serve as a browser test of a voice agent is UNKNOWN. | M | agents, web agents/[agentId], marketing page.tsx | TRIAL (it owns test calls; coordinate) |
| P1-3 | **Branching in the call script** (go to section X when Y) and an adherence control | Outpero 15-section graph (TEARDOWN-AUG 84146937); Retell canvas (WEB-9OCT). Ours is linear (`call_script.py`). It compiles to a prompt, so branching is a compiler change, not an engine change. | L | calevate_shared/call_script.py, agents/prompts.py, web agents/[agentId]/script | COPILOT (flow-editing tools must learn the new shape) |
| P1-4 | **Answering-machine detection and voicemail outcome** | We send `detectMachines:false`. Outpero has a voicemail-only webhook trigger (TEARDOWN-AUG); Retell has voicemail handling (WEB-9OCT). Campaign connect rates and billing honesty both depend on it. | S-M | engine/thinnest.py, crm/performance.py (voicemail already excluded from "connected") | none |
| P1-5 | **Native CRM connectors.** Start with one: Zoho or LeadSquared (founder to pick; Indian SMB CRM share is UNKNOWN to me) | Outpero shows Salesforce, HubSpot and Zoho logos (WEB-9OCT; depth UNKNOWN); Retell has HubSpot. We have webhooks + Sheets only. | M each | integrations/*, workers/outbound_webhooks.py, google_oauth pattern | COPILOT TOOLS (assistant can drive it later) |
| P1-6 | **Zapier / Pabbly / Make listed app** | Outpero lists Zapier and Pabbly; Bolna lists Zapier, Make and n8n (WEB-9OCT). Our signed webhooks already work; a listed app is mostly packaging and a discovery channel. | M | integrations, ingest | none |
| P1-7 | **Client help centre and published webhook / API reference** | Outpero docs, 27 topics (TEARDOWN-AUG). We have none client-facing. The teardown already flagged "publish a versioned outbound webhook schema" as a cheap win (777dd436). | M | apps/web (new /help), OpenAPI subset | COPILOT can answer from it (search_docs-style) |
| P1-8 | **Mobile: PWA with installable shell and push for hot leads / Needs attention** | Outpero mobile bottom nav (TEARDOWN-AUG). SMB owners live on phones. | M | apps/web manifest, service worker, notifications | none |
| P1-9 | **WhatsApp follow-up to the caller after the call** (not only owner alerts) | Outpero "WhatsApp confirmations and follow-ups" in plan (WEB-9OCT). Our `workers/whatsapp.py` is owner hot-lead alerts via Meta Cloud and is "UNTESTED AGAINST A REAL WABA" (its own docstring). | M + a WABA (external) | workers/whatsapp*.py, compliance messaging-consent | none |
| P1-10 | **Client-configurable max call length** | Outpero: 10 s to 1 h in Settings (TEARDOWN-AUG). We send `maxCallSeconds` (`engine_settings.py:44`); whether a client can set it is UNKNOWN. | S | agents/engine_settings.py, web agent settings | none |
| P1-11 | **Ambient sound bed** | Outpero (TEARDOWN-AUG). Whether ThinnestAI supports it is UNKNOWN (not checked in mirror). | S if the vendor supports it | engine/thinnest.py | none |

### P2: differentiators

| # | Gap | Evidence | Size | Notes |
|---|---|---|---|---|
| P2-1 | **Omnichannel from one agent**: website chat widget, WhatsApp agent, SMS | ThinnestAI documents website, whatsapp, sms and telegram channels (`snapshots/2026-10-08/pages/channels/`). Ringg sells chat/WhatsApp agents (₹2 per session, WEB-9OCT). Outpero is voice only. | L | Same knowledge base and CRM; a real edge if done before Outpero |
| P2-2 | **Simulated-caller regression tests on every publish**, shown to the client | Retell turns production calls into regression tests; Vapi "testing and simulation" (WEB-9OCT). Our closed-loop QA (D-15, D-73) is the claimed edge; making it automatic per publish makes it visible. | M-L | Builds on quality/, scripts/qa_report |
| P2-3 | **A/B testing of agent versions** | Retell (WEB-9OCT) | M | config_versions already exist |
| P2-4 | **Agency / reseller sub-accounts** | Bolna sub-account APIs; Vapi orgs (WEB-9OCT). Indian digital agencies are a channel. | L | Needs a public API first (P2-5) |
| P2-5 | **Public REST API with client API keys** | Bolna, Retell and Vapi are API-first (WEB-9OCT) | M-L | RLS-scoped keys, rate limits, audit |
| P2-6 | **Warm transfer with a spoken brief to the human** | Retell (WEB-9OCT). Ours is a cold transfer. Vendor support on ThinnestAI is UNKNOWN. | M | Depends on the vendor |
| P2-7 | **Published proof**: first client case study and a public QA report | Outpero shows zero customer proof (TEARDOWN-AUG b285e97f; homepage WEB-9OCT still shows only integration and backer logos). Bolna names 9 customers (WEB-9OCT). | S after client #1 | The cheapest edge available |

---

## 3. Product and operations gaps beyond features

1. **First-call experience.** Time from signup to a call the owner hears.
   - TRIAL covers the mechanism.
   - What is missing is a measured target (for example under 5 minutes) and the empty states that drive it: a sample agent per vertical and a "call me now" button on the first screen.
   - Owned by TRIAL and ONBOARDING; check the two lanes join up.
2. **Lifecycle emails.** No welcome, nurture, weekly-digest or "your agent took N calls" email was found.
   - What exists: invites and OTP (`workers/auth_email.py`), hot-lead and wallet alerts, and trial notices.
   - Transport exists (Resend or SMTP, `core/transport.py`). Size S-M.
3. **Public status page.** None exists. Our terms honestly offer no SLA. A status page (even a hosted one) gives a trust signal without contract risk. Size S.
4. **Help centre and support channel.**
   - There is no help docs site, and no stated support hours or channel on the client side (UNKNOWN beyond the signup contact email).
   - Outpero states "within 1 business day" (TEARDOWN-AUG); Bolna offers WhatsApp priority support on pilots (WEB-9OCT).
5. **Client observability.**
   - Have: webhook delivery log + payload (`integrations/routes.py` /deliveries), alerts settings, a usage/spend page.
   - Gap: a per-call "why did this call fail" reason in plain words on the call detail page (UNKNOWN whether it exists), and the engine status shown to clients during a ThinnestAI incident.
6. **SLA.**
   - Keep "no SLA" in the terms (it is the honest edge against Outpero's contradiction).
   - Decide whether a paid tier gets a support-response SLA, which Vapi sells (WEB-9OCT) and which costs nothing in uptime risk.
7. **Legal.** The set is published (rev 15). Open items:
   - the ThinnestAI DPA (T-5);
   - the 30-day sub-processor notice for the engine switch, if any client was live before 7 Oct (memory 5b189386, REPORTED);
   - "hosting VPS not provisioned" wording on public pages flagged as stale (same memory; current state UNKNOWN).
8. **Vendor concentration.** ThinnestAI is the whole call path. Pipecat is kept as a fallback, but numbers are not portable between engines (THINNEST-INTEGRATION status). There is no runbook for "ThinnestAI is down for a day" from the client's point of view (UNKNOWN; not found in this pass).
9. **Margin monitoring.** Clear at about 18% gross margin before the Pro subscription (REPORTED). The `engine_charges` reconciliation exists; a per-client margin view exists in admin `spend`. Confirm it includes the Pro plan fee once bought.

---

## 4. Where Calevate honestly beats Outpero

| Edge | Evidence | Caveat |
|---|---|---|
| **Inbound receptionist ships.** | Outpero homepage still says inbound "coming soon" (WEB-9OCT); their docs said inbound callers hear a message even when setup looks complete (TEARDOWN-AUG b703d8dc). | Ours is proven only once P0-1 lands. |
| **The agent cannot be scripted into denying it is an AI or that the call is recorded.** | Hard rule 5, `compose_engine_prompt`, verified on every publish (REPO). Outpero's AUP makes disclosure the client's job (TEARDOWN-AUG 34fa4eaf). | Opening disclosure is a per-agent toggle for us too (D-163). Sell "cannot be made to deny it", not "always announces". |
| **Typed, validated extraction.** | Outpero wrote "Delhi" into a quantity field (TEARDOWN-AUG ab2fac83). | One observed bug, two months old. |
| **DNC on every dispatch path, two-way with the engine.** | D-691; Outpero docs said DNC is "not yet applied to instant" (TEARDOWN-AUG b703d8dc). | Re-verify the Outpero side before quoting it (Comet prompt 1). |
| **Redaction by default, role-gated raw transcripts.** | Hard rule 5 (REPO). Outpero UI showed raw PII (TEARDOWN-AUG). | |
| **Honest contract.** | Our terms state no SLA. Outpero markets 99.9% (WEB-9OCT, homepage and pricing) while its Terms §9 disclaims availability and §11 caps liability at 3 months (TEARDOWN-AUG). | Re-check their Terms are unchanged (Comet prompt 1). |
| **Signed, replayable integrations.** | HMAC-signed outbound webhooks, delivery log + payload view; native Meta Lead Ads (`ingest/meta.py`). Outpero used URL-token intake and Meta via Zapier (TEARDOWN-AUG 777dd436). | Outpero's homepage now says "Meta and Instagram ads"; whether that is now native is UNKNOWN. |
| **No monthly fee per agent on the wallet model**, number ₹499/month. | Outpero ₹1,899 per employee per 30 days; homepage number ₹649/month (WEB-9OCT). | BRD §6 also mentions "monthly per-agent activation fee"; whether it is charged today is UNKNOWN. Founder decision 2. Outpero's number is included in the hire fee, so compare totals, not lines. |
| **Knowledge shared across a client's agents; client-owned business profile.** | D-689, D-695 | Outpero is per employee (TEARDOWN-AUG). |
| **Per-client isolated voice workspace and KYC'd numbers in the client's own name.** | D-693 | |
| **An assistant that acts across the console, with undo and approvals.** | D-694, D-698 (in progress) | Outpero's Swara edits the call flow (TEARDOWN-AUG). This is parity-plus, not a moat. |
| **Mature, published legal set naming sub-processors.** | Rev 15 | Outpero withholds sub-processor names (TEARDOWN-AUG). |

---

## 5. Comet prompts (things that could not be verified here)

1. **Outpero docs refresh.** docs.outpero.com is a single-page app and returned only its title to a text fetch today.
   > Open https://docs.outpero.com and read these hash pages by screenshot: #inbound, #howitfits, #actions, #numbers, #credits, #reliability, #postcall. For each, record verbatim:
   > - whether inbound is live;
   > - whether DNC now applies to Instant calls;
   > - the in-call action list;
   > - the number price and KYC steps;
   > - the credit rate card;
   > - the max-concurrency figure;
   > - any new integrations (HubSpot, Zoho, Salesforce: native or via Zapier?).
   >
   > Then open https://outpero.com/terms and quote §9 (availability) and §11 (liability cap). Note the page dates.
2. **Outpero app changes since August.**
   > Log into app.outpero.com (Raghava Organics account). Screenshot the sidebar, the Actions tab of an employee, the Integrations or CRM section, the Voice tab language list, and Settings. Record:
   > - whether native CRM connectors exist;
   > - which languages are selectable;
   > - whether a text "Try it" sandbox and an ambient-sound control still exist.
3. **ThinnestAI capabilities we have not checked.**
   > In the ThinnestAI console and docs (docs.thinnest.ai), find:
   > - whether voice agents support an ambient/background sound setting;
   > - whether answering-machine detection (`detectMachines`) changes billing or outcome fields;
   > - whether the website widget can run a voice (not text) conversation in the browser;
   > - the current pay-as-you-go concurrency and customer-workspace limits, and the Pro plan monthly price in INR.
   >
   > Quote each with its page URL.
4. **Indian SMB CRM priority.**
   > Search for 2026 market data on CRM usage among Indian SMBs (Zoho CRM, LeadSquared, HubSpot, Bitrix24, Kylas, TeleCRM). Return sources with dates. Do not estimate.
5. **Exotel and Ozonetel AI agent pricing.** Neither publishes a per-minute AI price that I could find (web search 9 Oct 2026).
   > Open exotel.com and ozonetel.com AI voice agent pages. Record any published per-minute AI rates, concurrency, languages and integrations, with URLs and dates.
6. **Haptik voice.**
   > Open haptik.ai and record whether it sells an outbound/inbound AI voice agent to SMBs, its pricing and languages.

---

## 6. Founder decisions needed

1. **ThinnestAI plan.** When to move to Pro: needed before client #4 (T-8). Ask for a concurrency raise at the same time.
2. **Price position against Outpero's ₹3 Value tier.**
   - Hold Clear at ₹4.00 with about 18% margin (REPORTED), or reprice.
   - Decide whether a monthly per-agent fee exists for self-serve (BRD §6 says one does; Outpero charges ₹1,899).
3. **In-call actions on thinnest.** Build them now (P0-2) or hide them and sell without.
4. **Which languages to add**, and who runs the ear test per language.
5. **First native CRM**: Zoho, LeadSquared or HubSpot.
6. **Open self-serve signup in production**, or stay invite-only until client #1 is live.
7. **Support promise**: hours, channel (WhatsApp?) and a response target for paid accounts.
8. **WhatsApp**: get a WABA for caller-facing follow-ups (external, Meta Business verification).
