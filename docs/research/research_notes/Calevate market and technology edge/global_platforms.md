# Global AI voice-agent platforms: feature catalogue (as of Oct 2026)

All sources were read on 30 Oct 2026. Evidence classes are used throughout:
- **PRIMARY**: the vendor's own page, docs, changelog or a regulator's page.
- **SECONDARY**: a third-party blog or comparison. Many of these are written by competitors (Retell, Cekura, Coval, Trillet, Synthflow blogs), which is flagged where it applies.

Every price and latency figure is a **vendor claim** or a third-party report, not a measurement. Where something could not be established, it is marked UNKNOWN.

This was a time-boxed pass of about 17 tool calls. The primary pages actually read were the Retell pricing and changelog pages, the Vapi changelog, the ElevenLabs API pricing page, and the FTC's Air AI pages (through search results). Everything else is SECONDARY and should be re-verified before it reaches a price, a wire value or a client-facing claim (hard rule 11).

## Q1. What do the leading platforms offer, grouped by area?

### Takeaway
The developer platforms (Retell, Vapi, ElevenLabs Agents, Bland, Synthflow) have converged on the same kit:
- a builder with flows or sub-agents;
- simulated-caller testing and evals;
- post-call analysis and AI QA;
- warm transfer with a briefing;
- voicemail handling and batch outbound;
- knowledge-base crawling;
- webhooks and CRM sync;
- PII redaction and retention controls.

They now compete on testing depth, observability and per-contact memory. Enterprise vendors (Sierra, PolyAI) compete on managed outcomes. SMB receptionist products (Goodcall, Smith.ai, Lindy) compete on flat or per-call pricing and on human backup.

### Cited Findings

**Builder / agent design**
- Retell lists these Build features: Call Transfer, Book Appointments, Knowledge Base and Navigate IVR. It also lists "Pre-built Agent Templates". PRIMARY. — [Retell pricing](https://www.retellai.com/pricing)
- Retell has "Agent Transfer and Subagents", which switches between agents mid-call with context carried over. Date UNKNOWN; the entry is undated on the page. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- Retell has "Agent Versioning 2.0" with drafts plus staging and production tags. It also has node-level knowledge bases, and a role-based user manager with Admin, Developer and Member roles. Dates UNKNOWN. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- On 31 Mar 2026, Retell deprecated single-agent phone-number fields in favour of **weighted agent lists** for inbound, outbound and SMS routing. This is effectively traffic-splitting across agents. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- Vapi Squads are multi-assistant orchestration:
  - The squad builder was refreshed on 12 Oct 2026.
  - Since 5 Oct 2026, chat squad handoffs extract variables from the conversation instead of overwriting them.
  - Since 22 Jun 2026, handoff webhooks carry the assistant's configured variables.
  - PRIMARY. — [Vapi changelog](https://docs.vapi.ai/changelog)
- Vapi "Composer" is an AI builder inside the console. Since 14 Sep 2026 it can create and run simulations, including scenarios, tester personalities and suites. PRIMARY. — [Vapi changelog](https://docs.vapi.ai/changelog)
- On 20 Jul 2026, Vapi added Model Presets with latency, cost and quality metrics for comparing model options. PRIMARY. — [Vapi changelog](https://docs.vapi.ai/changelog)
- ElevenLabs Agents changes reported in its changelog:
  - Workflows: conversations can start at a specific workflow node (20 Apr 2026).
  - "Create agent draft" compiles and validates structured procedures (reported 5 Oct 2026).
  - Batch calls gained timezone scheduling (12 Jan 2026), a concurrency limit (9 Mar 2026) and a CSV results export.
  - SECONDARY summary of PRIMARY changelog pages. The search tool itself flagged that some dates looked inconsistent.
  - — [ElevenLabs changelog 20 Apr 2026](https://elevenlabs.io/docs/changelog/2026/4/20), [12 Jan 2026](https://elevenlabs.io/docs/changelog/2026/1/12), [9 Mar 2026](https://elevenlabs.io/docs/changelog/2026/3/9)
- ElevenLabs is positioned as one platform for voice, chat and email agents. Reported channels are telephony, web, mobile, WhatsApp, SMS, email and chat, with no cap on agent count (only on concurrency and minutes). SECONDARY. — [getmacha](https://www.getmacha.com/blog/elevenlabs-agents-pricing-explained)
- PolyAI:
  - Agent Studio launched on 15 Apr 2025 as a "voice-first omnichannel" platform. It offers no-code, low-code and pro-code building, agent versioning, user provisioning, and tuning of lexicons and tone. PRIMARY press release. — [PR Newswire](https://www.prnewswire.com/news-releases/polyai-unveils-agent-studio-empowering-enterprises-with-generative-ai-for-customer-service-excellence-302428965.html)
  - A PolyAI blog title says "Dialog Studio (formerly Agent Studio)", so a rename is possible; the date is UNKNOWN. — [PolyAI blog](https://poly.ai/blog/introducing-agent-studio)
  - A "Wren" natural-language builder and an Agent Development Kit (22 Apr 2026, Git-based) are reported. SECONDARY, not verified. — [beri.net](https://www.beri.net/tools/polyai)
- Lindy is an agent builder for non-developers. Calls are an add-on to a general automation product. SECONDARY. — [cloudtalk](https://www.cloudtalk.io/blog/lindy-ai-review/)

**Testing and evaluation**
- Retell:
  - Simulation testing and batch simulation testing launched on 14 Apr 2025 for single- and multi-prompt agents. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
  - "Conductor" simulates proposed changes and failed-call test cases before anything ships, and every change needs approval. Date UNKNOWN. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- Vapi:
  - Simulation suites against assistants or squads with per-run results (10 Aug 2026).
  - Suite duplication (7 Sep 2026).
  - Searchable, shareable eval run history (28 Sep 2026).
  - **Latency thresholds that fail a simulation run** (5 Oct 2026).
  - PRIMARY. — [Vapi changelog](https://docs.vapi.ai/changelog)
  - Evals reportedly launched on 3 Dec 2025. They are JSON mock-conversation tests with three judge types (exact or regex, LLM-as-judge, tool-call verification) and can run in CI/CD through a CLI. SECONDARY, single source (Coval, a competitor). — [Coval Vapi review](https://www.coval.ai/blog/vapi-review-2026-is-this-voice-ai-platform-right-for-your-project/)
- ElevenLabs has agent simulation tests and test suites with `tool_mock_config` for mocked tool calls (9 Mar 2026). Test summaries show credits and USD price. SECONDARY summary of PRIMARY changelog. — [ElevenLabs changelog 9 Mar 2026](https://elevenlabs.io/docs/changelog/2026/3/9)
- Independent testing vendors:
  - Hamming has no published price. It tests latency percentiles, WER, barge-in, background noise, telephony conditions, load and red-teaming, and claims 50+ metrics and 1,000+ concurrent simulations. SECONDARY, competitor-authored. — [Cekura](https://www.cekura.ai/blogs/hamming-alternative)
  - Coval reportedly costs:
    - Starter: $100/mo for 100 simulation minutes and 1,000 monitored calls.
    - Growth: $500/mo for 1,000 simulation minutes and 10,000 monitored calls.
    - Enterprise: from $4,500/mo.
    - Overage: $0.40 or $0.25 per simulation minute.
    - SECONDARY. — [Cekura](https://www.cekura.ai/blogs/ai-voice-agent-testing-tools)
  - Other names in this category are Cekura, Bluejay, Roark, Future AGI and Speechmatics' list. — [Speechmatics](https://www.speechmatics.com/company/articles-and-news/de-risk-your-voice-agent-11-best-voice-agent-testing-platforms)

**Analytics / conversation intelligence**
- Retell (PRIMARY, all dates UNKNOWN) — [Retell changelog](https://www.retellai.com/changelog):
  - "Live Call Monitoring and Custom Dashboards": real-time transcripts, call scoring, **auto-actions on bad calls** and shareable team dashboards.
  - "AI QA Analyst and Alerting": automated call review, resolution tracking, and **alerts on shifts in cost, success rate or sentiment**.
  - "Analytics Dashboard 2.0": post-call metrics as column, bar, donut or line charts.
- Retell lists "Post Call Analysis" and "AI Quality Assurance". AI QA is free for the first 100 minutes, then $0.10/min. PRIMARY. — [Retell pricing](https://www.retellai.com/pricing)
- Vapi (PRIMARY) — [Vapi changelog](https://docs.vapi.ai/changelog):
  - **Traffic tab** showing the call split across published versions with filterable metrics (26 Oct 2026). This is effectively A/B analysis of agent versions.
  - "Server message failed" monitor alerting on webhook delivery failures (19 Oct 2026).
  - Per-phase latency breakdown and VAD transitions in call logs (13 Jul 2026).
  - Logs show which assistant in a squad handled each call (29 Jun 2026).

**Telephony**
- Retell (PRIMARY) — [Retell pricing](https://www.retellai.com/pricing):
  - Telephony is $0.015/min. SIP trunking and custom telephony are free.
  - Numbers are $2/mo. Branded Call ID is $0.10 per outbound call.
  - Verified Phone Number is $10, shown on the page both as a monthly and as a one-time fee (inconsistent on the page).
  - Batch Call is $0.005 per dial. SMS is $0.01 per message.
- On 30 Jun 2025, Retell added outbound disconnection reasons including `marked_as_spam` and `user_declined`. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- Retell warm transfer (PRIMARY, dates UNKNOWN) — [Retell changelog](https://www.retellai.com/changelog):
  - "Warm Transfer 2.0": human detection before bridging, whisper and three-way messages, hold music.
  - "Advanced Warm Transfer": an AI briefs the human before they accept, and can **reject transfers that don't meet criteria**.
  - Caller-ID choice on transfer.
- Vapi transfers (PRIMARY) — [Vapi changelog](https://docs.vapi.ai/changelog):
  - Warm SIP transfers play hold audio and a completion sound (27 Jul 2026).
  - Blind transfers gained a fallback plan, a dial timeout and logged outcomes (10 Aug 2026).
  - Transfer destinations can have friendly names (31 Aug 2026).
- Retell "Custom Voicemail Handling" lets each agent hang up, play a prerecorded message, or generate one on the fly. Date UNKNOWN. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- Bland bills transfers at $0.05 or $0.04/min, numbers at $15/mo, SMS at $0.02, and reportedly $0.015 per unanswered attempt. SECONDARY. — [ringly](https://www.ringly.io/blog/bland-ai-pricing), [cleanform](https://cleanform.io/blog/bland-ai-pricing/)
- Model vendors' telephony:
  - OpenAI Realtime supports WebRTC, WebSocket and SIP. SECONDARY. — [layer3labs](https://www.layer3labs.io/guides/openai-realtime-api-pricing)
  - Gemini Live API is reported to have no first-party SIP or PSTN, so you bring your own carrier. Google's own tutorial bridges through Twilio. — [DEV/googleai](https://dev.to/googleai/add-telephony-to-a-gemini-live-agent-with-twilio-1elc), [developersdigest](https://www.developersdigest.tech/voice-agents/gemini-live-api)

**Integrations / workflows**
- Retell "Built-in CRM" does two-way real-time sync with Salesforce and HubSpot, keyed on the caller's phone number. Date UNKNOWN. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- Retell "Knowledge Base Auto Add Future Pages": new pages under chosen URL paths are crawled and kept up to date. Date UNKNOWN. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- Retell lists "Webhooks and API Access" under Platform. PRIMARY. — [Retell pricing](https://www.retellai.com/pricing)

**Compliance / safety**
- Retell (PRIMARY):
  - Safety Guardrails add-on: +$0.005/min.
  - PII Removal: +$0.01/min.
  - Data retention with auto-delete after a set window.
  - Enterprise tier: SSO, RBAC and custom MSA/DPA.
  - — [Retell pricing](https://www.retellai.com/pricing), [Retell changelog](https://www.retellai.com/changelog)
- Vapi (PRIMARY):
  - HIPAA-enabled assistants. AssemblyAI is allowed on them from 26 Oct 2026; xAI was made HIPAA-compliant on 13 Jul 2026.
  - Zero Data Retention mode, with end-of-call reports reliably delivered under it from 20 Jul 2026.
  - — [Vapi changelog](https://docs.vapi.ai/changelog)
  - HIPAA is reportedly $2,000/mo and ZDR $1,000/mo as add-ons. SECONDARY, sources disagree. — [layer3labs](https://www.layer3labs.io/guides/vapi-pricing)
- Coval's enterprise tier reportedly has SAML SSO, SCIM, audit logs and data residency. SECONDARY. — [Cekura](https://www.cekura.ai/blogs/ai-voice-agent-testing-tools)

**Reliability / SLA**
- Retell Enterprise offers 24/7 omnichannel support, a "dedicated stable server" add-on and dedicated implementation support. Pay-as-you-go gets community and email support. PRIMARY. — [Retell pricing](https://www.retellai.com/pricing)
- Vapi Scale is reportedly an annual contract with a fixed platform fee, committed volume and an SLA. SECONDARY. — [layer3labs](https://www.layer3labs.io/guides/vapi-pricing)

**Onboarding / self-serve / agency**
- Retell gives $10 in free credits, 20 free concurrent calls, and full platform access on pay-as-you-go. PRIMARY. — [Retell pricing](https://www.retellai.com/pricing)
- Synthflow reportedly:
  - retired its published agency tiers;
  - sells enterprise contracts from about $30k/yr;
  - charges about $2,000/mo for a white-label and reseller toolkit;
  - removed in-product Stripe reselling in Sep 2026.
  - SECONDARY, from a competitor (Trillet). — [Trillet](https://trillet.ai/blogs/synthflow-vs-trillet-comparison)
- Smith.ai's differentiator is **human-receptionist backup** behind the AI. SECONDARY. — [dialzara](https://dialzara.com/compare/goodcall-vs-smith-ai)

### Inferences
- Most relevant to Calevate:
  1. Pre-publish simulation with a change-approval gate (Retell Conductor). This maps onto Calevate's QA and test calls.
  2. Latency-threshold assertions in tests (Vapi, 5 Oct 2026).
  3. Alerts on drift in success rate or sentiment (Retell AI QA Analyst).
  4. Per-contact running memory (Retell Conversation Memory). This maps onto follow-up journeys.
  5. Warm transfer with an AI briefing to the human.
  6. Version traffic-split analytics (Vapi Traffic tab, Retell weighted agent lists).
- Calevate already has, or is building, analogues of: knowledge-base crawl, CRM sync keyed on phone, voicemail handling and batch outbound.
- Branded or verified caller ID (Retell) addresses the spam-labelling problem. Its Indian equivalent would sit in the TRAI and 140/160-series regime, which is not researched here.

### Gaps
- Bland AI's current feature set (pathways, memory, citations) could not be confirmed. The search returned only pricing.
- Synthflow, Thoughtly, Goodcall, Aircall, Dialpad and Lindy feature claims were not read from primary pages.
- Sierra's product features beyond its pricing model were not covered.
- Google Customer Engagement Suite: no result covered it, so its feature set and telephony are UNKNOWN.
- Cartesia's own voice-agent API (Line) was not researched; UNKNOWN.

## Q2. What are the newest capabilities (2025-2026)?

### Takeaway
Most of what is genuinely new in 2025-2026 is about validating and operating agents, not about the conversation itself:
- simulation suites with tester personas;
- CI evals with latency gates;
- AI QA with alerting and auto-actions on bad calls;
- version traffic-splitting;
- per-contact memory briefs;
- AI-briefed warm transfer;
- KB auto-crawl;
- per-caller language matching.

On pricing, outcome pricing (Sierra) is the one structural change.

### Cited Findings
- **Simulated-caller testing:**
  - Retell: 14 Apr 2025, PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
  - Vapi: suites on 10 Aug 2026, Composer-generated personas and scenarios on 14 Sep 2026, latency limits on 5 Oct 2026. PRIMARY. — [Vapi changelog](https://docs.vapi.ai/changelog)
  - ElevenLabs: tests with tool mocks, 2026. SECONDARY summary. — [ElevenLabs changelog](https://elevenlabs.io/docs/changelog/2026/3/9)
- **Automatic QA scoring:**
  - Retell AI QA costs $0.10/min after 100 free minutes. PRIMARY. — [Retell pricing](https://www.retellai.com/pricing)
  - Retell has live call scoring with auto-actions on bad calls. PRIMARY, date UNKNOWN. — [Retell changelog](https://www.retellai.com/changelog)
- **A/B of prompts or versions:**
  - Retell weighted agent lists (31 Mar 2026).
  - Vapi Traffic tab across published versions (26 Oct 2026).
  - PRIMARY. — [Retell changelog](https://www.retellai.com/changelog), [Vapi changelog](https://docs.vapi.ai/changelog)
- **Warm transfer with summary:** Retell "Advanced Warm Transfer" has an AI brief the human and can reject transfers. PRIMARY, date UNKNOWN. — [Retell changelog](https://www.retellai.com/changelog)
- **Voicemail detection and drop:** Retell offers hang up, prerecorded or generated messages per agent. PRIMARY, date UNKNOWN. — [Retell changelog](https://www.retellai.com/changelog)
- **Multilingual switching:**
  - Retell "Granular Multilingual" matches language automatically per caller. PRIMARY, date UNKNOWN. — [Retell changelog](https://www.retellai.com/changelog)
  - ElevenLabs claims "90+ languages supported". PRIMARY claim. — [ElevenLabs API pricing](https://elevenlabs.io/pricing/api)
  - ElevenLabs language-detection changes are dated 10 Aug 2026; details not read. — [ElevenLabs changelog](https://elevenlabs.io/docs/changelog/2026/8/10)
- **Memory across calls:** Retell "Conversation Memory" keeps a running brief per contact, updated after calls and SMS, at $0.005 per save or backfill run. PRIMARY, date UNKNOWN. — [Retell changelog](https://www.retellai.com/changelog)
- **Knowledge auto-sync:** Retell "Auto Add Future Pages" crawling. PRIMARY. — [Retell changelog](https://www.retellai.com/changelog)
- **Agent-to-agent handoff with context:**
  - Retell "Agent Transfer and Subagents". — [Retell changelog](https://www.retellai.com/changelog)
  - Vapi Squads with variable extraction on handoff (5 Oct 2026). — [Vapi changelog](https://docs.vapi.ai/changelog)
- **Outcome-based pricing:** Sierra charges per resolved conversation, saved cancellation or upsell, and in most cases nothing for unresolved conversations. Routing and greeter calls are billed per conversation. Sierra reportedly said in Jul 2026 that this works only where the work is "highly autonomous and highly attributable". SECONDARY, no public rate card. — [cloudtalk](https://www.cloudtalk.io/blog/sierra-ai-pricing/), [featurebase](https://www.featurebase.app/blog/sierra-ai-pricing)
- **White-label / agency:** Synthflow's toolkit is reportedly about $2k/mo, with in-product Stripe reselling removed in Sep 2026. SECONDARY, competitor-authored. — [Trillet](https://trillet.ai/blogs/synthflow-vs-trillet-comparison)
- **AI builders inside the console:**
  - Vapi Composer. PRIMARY. — [Vapi changelog](https://docs.vapi.ai/changelog)
  - PolyAI "Wren". SECONDARY. — [beri.net](https://www.beri.net/tools/polyai)
  - These are the closest analogues to Calevate's Pip.
- **Webhook delivery monitoring:** Vapi, 19 Oct 2026. PRIMARY. — [Vapi changelog](https://docs.vapi.ai/changelog)

### Inferences
- The "AI that operates the console" pattern (Vapi Composer, PolyAI Wren) is now mainstream at the developer platforms. Calevate's Pip is therefore table stakes, not a differentiator, unless it adds simulation authoring and failed-call-to-test-case conversion as Vapi Composer and Retell Conductor do.
- Outcome pricing appears only at the enterprise end with high attribution. For Indian SMBs, a per-qualified-lead or per-booked-appointment price is plausible. It would need Calevate's extraction schema to define attributable outcomes. This is an inference only, with no Indian market evidence gathered here.

### Gaps
- Dates for most Retell features are UNKNOWN. The changelog page shows them undated, and characters 100,000-159,166 of the page were not read.
- Sentiment analysis per platform beyond Retell's alerting was not verified.
- No Indian-language (Telugu) support claims were verified for any global platform.

## Q3. Pricing models and latency claims

### Takeaway
The developer platforms charge a platform fee of about $0.05-0.08/min plus model, voice and telephony pass-through. Real totals cluster around $0.10-0.30/min (vendor claims and third-party estimates). SMB receptionist products use flat per-agent or per-call pricing. Enterprise vendors use contracts or outcome pricing. No primary latency figures were obtained in this pass.

### Cited Findings
- **Retell** (PRIMARY, read 30 Oct 2026) — [Retell pricing](https://www.retellai.com/pricing):
  - Headline: "$0.07-$0.31 / min".
  - Voice infra: $0.055/min.
  - TTS: $0.015/min for platform, Cartesia, OpenAI and similar voices; $0.04-0.10/min for ElevenLabs voices.
  - LLM examples: Gemini 3.0 Flash $0.016/min, Claude 4.5 Haiku $0.025/min, GPT 5.4 $0.08/min.
  - Speech-to-speech: GPT Realtime $0.345/min, GPT Realtime mini $0.07/min.
  - KB: +$0.005/min; first 10 knowledge bases free, then $8/KB/mo.
  - Concurrency: 20 free, then $8/concurrency/mo.
  - Enterprise custom concurrency from 50+.
- **Vapi**: $0.05/min hosting fee plus pass-through, or $0 for BYO keys. Reported tiers include a Core plan at about $29/mo with 10 concurrent calls. Totals are reportedly $0.10-0.30/min. SECONDARY, sources disagree on plan names. — [layer3labs](https://www.layer3labs.io/guides/vapi-pricing), [usagepricing](https://www.usagepricing.com/blueprint/vapi)
- **ElevenLabs Agents** (PRIMARY) — [ElevenLabs API pricing](https://elevenlabs.io/pricing/api):
  - $0.08/min, with burst pricing at $0.16/min above the concurrency limit.
  - Plans: Free, Starter $6, Creator $22, Pro $99, Scale $299, Business $990/mo.
  - Included minutes 15 / 75 / 275 / 1,238 / 3,738 / 12,375 with concurrency 4 / 6 / 10 / 20 / 30 / 40. The page does not label the row-to-plan mapping.
  - LLM is billed on top per SECONDARY sources, which disagree about telephony. — [getmacha](https://www.getmacha.com/blog/elevenlabs-agents-pricing-explained)
- **Bland**: plan-based since Dec 2025. Start is free at $0.14/min, Build $299/mo at $0.12/min, Scale $499/mo at $0.11/min. SECONDARY. — [ringly](https://www.ringly.io/blog/bland-ai-pricing), [superdupr](https://superdupr.com/blog/voice-ai-pricing)
- **Synthflow**: reportedly enterprise contracts from $30k/yr. An older self-serve Pro plan was $99/mo for 200 minutes. SECONDARY, conflicting. — [dograh](https://www.dograh.com/feeds/blog/synthflow-bland-ai)
- **Deepgram Voice Agent API**: about $0.075/min Standard and about $0.163/min Advanced. It is billed on WebSocket connection time, with telephony extra. One source reports a 13 Sep 2026 rise from $0.056 to $0.075. SECONDARY. — [cekura](https://www.cekura.ai/blogs/deepgram-pricing), [cartesia](https://www.cartesia.ai/learn/deepgram-pricing)
- **OpenAI Realtime**: gpt-realtime-2.1 audio costs $32 per 1M input tokens and $64 per 1M output; mini is $10/$20. SECONDARY, citing OpenAI's pricing page, which was not read directly. — [eesel](https://www.eesel.ai/blog/openai-api-pricing), [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- **Gemini Live**: audio input about $3 per 1M tokens. Output for 3.1 Flash Live Preview is reportedly $12 per 1M. SECONDARY. — [developersdigest](https://www.developersdigest.tech/voice-agents/gemini-live-api)
- **Sierra**: outcome-based with no public rate card. The $150k/yr starting price and $1-2.50 per resolution are third-party estimates that Sierra has not confirmed. — [cekura](https://www.cekura.ai/blogs/sierra-ai-pricing)
- **Goodcall**: flat $79 / $129 / $249 per agent per month with "unlimited minutes", plus $0.50 per unique customer over the cap. SECONDARY. — [conduit](https://www.conduit.ai/blog/goodcall-alternatives)
- **Smith.ai**: per-call pricing. Figures conflict, e.g. $97/mo for 50 AI calls versus $9.75 per call. SECONDARY, conflicting. — [getaira](https://www.getaira.io/blog/ai-receptionist-pricing-guide), [serviceagent](https://serviceagent.ai/blogs/smith-ai-alternatives/)
- **Aircall** AI Voice Agent: price not published, with a 3-licence minimum. **Dialpad**: not clearly published (credits or quote). SECONDARY. — [conduit](https://www.conduit.ai/blog/goodcall-alternatives)
- **Thoughtly**: reportedly Flex from $500/mo; older docs say from $0.05/min. **Lindy**: plans $29.99-199.99/mo, with voice reportedly $0.19/min, which is unconfirmed. SECONDARY. — [cloudtalk Thoughtly](https://www.cloudtalk.io/blog/thoughtly-ai-pricing/), [ainora Lindy](https://ainora.lt/blog/lindy-ai-review-alternatives-2026)
- **Latency**: Retell's own comparison claims Bland measures 700-1,500 ms. This is a competitor's claim, not neutral. — [Retell blog](https://www.retellai.com/blog/vapi-vs-bland)

### Inferences
- The three pricing models map onto three buyer types:
  - Developer platforms meter components per minute.
  - SMB receptionist products (Goodcall, Smith.ai) sell flat or per-call plans that a non-technical owner can budget.
  - Enterprise vendors sell outcomes.
- An Indian SMB product should probably follow the SMB pattern on the surface (flat or per-call) while metering per minute underneath.
- Retell's itemised add-ons show that individual features are priced separately: QA, PII redaction, guardrails, memory saves, branded caller ID and KB.

### Gaps
- No primary or independent latency benchmarks (ms) were obtained for any platform: UNKNOWN.
- The primary pages for Vapi pricing, Bland, Synthflow, Deepgram and OpenAI were not read in this pass.

## Q4. What users praise and complain about

### Takeaway
The review signal is thin and heavily contaminated by competitor-authored comparisons. The recurring themes are:
- latency variance and reliability under concurrency (Vapi);
- synthetic-sounding voices and a code-heavy setup (Bland, per a competitor);
- cost scaling for high-volume outbound and a dashboard that overwhelms new users (Retell);
- support delays.

A regulator case (Air AI) shows the "AI agent will grow your business" marketing risk in the SMB segment.

### Cited Findings
- Retell has about 1,670 G2 reviews at 4.8 stars:
  - Praise: low latency and ease of use.
  - Complaints: cost scaling for high-volume outbound and a dashboard that overwhelms new users.
  - Trustpilot reviewers describe moving from Vapi over support and stability.
  - SECONDARY summary of G2 and Trustpilot. — [G2 Retell](https://g2.com/products/retell-ai/reviews), [Trustpilot](https://ca.trustpilot.com/review/retellai.com)
- Vapi: a G2 reviewer reported inconsistent response times, and a Reddit user said quality degraded at higher concurrency. Basic agents are easy to build. SECONDARY. — [quiq](https://quiq.com/blog/vapi-ai-review/)
- Vapi: older tutorials describe a visual builder that is no longer usable, which creates confusion from docs drift. SECONDARY. — [lindy](https://www.lindy.ai/blog/vapi-ai)
- Bland's G2 page has only 3 reviews, which is too few for signal. — [G2 Bland](https://www.g2.com/sellers/bland-ai)
- Air AI:
  - The FTC sued on 25 Aug 2025 over false earnings claims and refund guarantees aimed at small businesses.
  - A Mar 2026 settlement bans the operators from marketing business opportunities, with an $18M judgment largely suspended and $50k in consumer relief.
  - PRIMARY (FTC). — [FTC Aug 2025](https://www.ftc.gov/news-events/news/press-releases/2025/08/ftc-sues-stop-air-ai-using-deceptive-claims-about-business-growth-earnings-potential-refund), [FTC Mar 2026](https://www.ftc.gov/news-events/news/press-releases/2026/03/air-ai-its-owners-will-be-banned-marketing-business-opportunities-settle-ftc-charges-company-misled)

### Inferences
- These SMB-relevant complaints are design inputs for Calevate:
  - predictable bills, which favour flat or capped plans;
  - a simple dashboard (consistent with the "buttons, not paragraphs" rule);
  - reliability under concurrency;
  - honest capability marketing (Air AI shows the regulatory exposure in overclaiming to small businesses).

### Gaps
- No direct Reddit (r/AI_Agents, r/VoiceAI) or Hacker News threads were read. The complaints above are second-hand.
- Hallucination complaints per platform: no sources found.
- No user reviews from Indian SMB buyers of these global platforms were found.
