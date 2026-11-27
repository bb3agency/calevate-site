# Outpero public site, docs and API: state on 28 Nov 2026

Read on 28 Nov 2026 from public pages only, without logging in or submitting a form. Each fact names its URL.

Evidence class: VENDOR-PUBLISHED (Outpero's own pages). Summaries are paraphrase, and quotes are kept to 15 words or fewer.

Method:
- Marketing pages were read through a text fetcher.
- docs.outpero.com is a JavaScript single-page app, so it was rendered in a real browser.
  - Each hash route was opened and its body text read after a 2.5 s settle.
  - With a shorter settle (0.7 s), several routes showed the previous route's body. This is the same stale-body effect seen in August; it is a render lag, not stale content.
  - Every route listed below was re-read with the longer settle and showed its own body.
- The OpenAPI spec was downloaded raw and saved beside this file as `outpero-openapi-2026-11-28.json` (181,263 bytes, OpenAPI 3.1.0, `info.version` 1.0.0).

Baseline compared against: the August 2026 teardown (rememory memories 694cc713, 84146937, 219acb9b, 987bafb4, ab2fac83, 34fa4eaf, b285e97f, b703d8dc, 777dd436) and the 22 Oct 2026 onboarding (ce5860a2).

---

## 1. Page and route index

### outpero.com (marketing)

| URL | Purpose | Status 28 Nov |
|---|---|---|
| https://outpero.com/ | Home, "AI telecalling software" | Live, redesigned |
| https://outpero.com/pricing | Pricing | Live |
| https://outpero.com/voices | Voice samples | Live, NEW since Aug |
| https://outpero.com/product/instant-leads | Instant leads product | Live, NEW |
| https://outpero.com/product/campaigns | Bulk campaigns product | Live, NEW |
| https://outpero.com/product/inbound | Inbound receptionist | Live, NEW (presented as available) |
| https://outpero.com/partners/apply | Agency partner application | Live, NEW |
| https://outpero.com/agency | Done-for-you agency services | Live (the old /about content moved here) |
| https://outpero.com/about | Agency "About OUTPERO" | Live (sitemap lastmod 2026-03-27; not linked from the new nav) |
| https://outpero.com/ai-employee | Old product page | Live, but now serves the new home-page content; the 99.9% SLA is gone |
| https://outpero.com/deploy | AP/Telangana landing page, "Hire Andhra & Telangana's Fastest AI Employee" | Live, older copy (sitemap lastmod 2026-03-27) |
| https://outpero.com/contact | Contact form | Live |
| https://outpero.com/compare | Index: 35 vendor and 23 alternative comparisons | Live, NEW |
| https://outpero.com/blog | 118 posts (30 Jul to 22 Oct 2026) | Live, greatly expanded |
| https://outpero.com/glossary | 103 terms | Live, NEW |
| https://outpero.com/free-ai-voice-agent | 50-free-credits explainer | Live, NEW |
| https://outpero.com/telugu-ai-voice-agents | Telugu landing page | Live |
| https://outpero.com/terms-and-conditions | Terms (marketing-site copy) | Live, updated 14 Oct 2026 |
| https://outpero.com/privacy-policy | Privacy | Live, updated 14 Oct 2026 |
| https://outpero.com/refund-policy | Refund | Live, updated 14 Oct 2026 |
| https://outpero.com/security, /acceptable-use, /privacy, /cookie-policy, /careers | – | HTTP 404 (the policies now live on app.outpero.com; there is no careers page) |
| https://outpero.com/sitemap.xml | Sitemap | Lastmod range 2026-03-27 to 2026-10-22 |

The sitemap also shows a programmatic-SEO estate:

| Group | Pages | Example path |
|---|---|---|
| City and state "fastest employee" pages | 171 (36 states/UTs, 135 cities) | `/fastest-employee/*` |
| Industry pages | 55 | `/ai-voice-agents/for/*` |
| Industry × city pages | 180, across 10 cities | `/ai-voice-agents/for/{industry}/{city}` |
| Use-case pages | about 55 | `/ai-voice-agents/use-case/*` |
| Language pages | 18 (including Bengali, Gujarati, Punjabi, Odia, Urdu and Assamese, which the free-credits page says are not live) | `/ai-voice-agents/language/*` |
| Native-language pages | 6 | `/ai-voice-agents/native/*` |
| Feature pages | 11 | `/ai-voice-agents/features/*` |
| Q&A pages | 444 | `/questions/*` |
| Comparison pages | 58 | `/compare/*` |
| "Alternatives to X" pages | 14 | `/alternatives/*` |
| Single-keyword landing pages | about 60 (for example /ai-telecaller, /ai-dialer, /white-label-ai-voice-agent, /ai-ivr) | `/{keyword}` |

### docs.outpero.com Help centre (27 topics; "Last updated: 18 October 2026" on every topic)

| Section | Route | Topic |
|---|---|---|
| Start here | #overview | What Outpero does |
| | #first-employee | Creating your first employee (NEW route) |
| | #going-live | Going live: what it costs (NEW route) |
| Your AI employees | #lifecycle | The employee lifecycle |
| | #script | Call script & flow |
| | #voice | Voice & sound |
| | #actions | Actions & integrations |
| | #postcall | Post-call data & webhooks |
| | #publishing | Publishing changes |
| | #versions | Versions & starting over |
| Calling channels | #instant | Instant Lead Calling |
| | #bulk | Bulk Campaigns |
| | #inbound | Inbound Calling (REWRITTEN: now shipped) |
| | #calling-rules | Calling rules & your responsibilities (was #rules) |
| Calls & reporting | #calllog | Call log & call details |
| | #leads | Leads |
| | #conversations | All Conversations |
| | #performance | Performance analytics |
| Setup | #numbers | Phone numbers |
| | #training | Training & knowledge |
| Billing | #credits | How credits work |
| | #topup | Adding credits (was #addcredits) |
| | #statements | Statements & transactions |
| Account | #notifications | Notifications |
| | #settings | Settings & account |
| Reference | #reliability | Reliability & call limits |
| | #howitfits | How it all fits together |

Policy links in the docs sidebar point to app.outpero.com: /terms, /privacy, /refund, /cookies, /acceptable-use, /security and /contact.

### docs.outpero.com API documentation (all NEW since Aug; API v1 dated 16 Oct 2026)

| Section | Routes |
|---|---|
| Get started | #api, #api/quickstart, #api/authentication, #api/test-mode |
| Concepts | #api/concepts/calling-rules, /call-lifecycle, /errors, /rate-limits, /idempotency, /pagination, /formats, /versioning |
| Reference | #api/reference/inbound-calls, /me, /employees, /phone-numbers, /balance, /calls, /leads, /campaigns, /do-not-call, /webhooks, /events |
| Webhooks | #api/webhooks, #api/webhooks/events, /signatures, /retries |
| Guides | #api/guides/n8n, /make, /zapier, /pabbly |
| Resources | #api/downloads, #api/changelog |
| Downloads | https://docs.outpero.com/developers/openapi.json and https://docs.outpero.com/developers/outpero-v1.postman_collection.json (24,153 bytes, 37 requests in 11 folders) |
| Dashboard link | https://app.outpero.com/#developers (API keys, webhooks) |

---

## 2. Per-page notes: marketing site

### Home (https://outpero.com/)
- **Positioning:** the headline is now "AI telecalling software", with the claim of India's most natural-sounding voice agents.
- **Languages:** 7 (Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi, English). Telugu is no longer the lead language on the home page.
- **Sections, in order:**
  - a "What should your AI telecaller do?" prompt box with templates and voice input;
  - "Trusted by 5,000+ businesses", with no names or logos;
  - a demo call in which the agent books a site visit and sends a WhatsApp location, with CRM and Sheet sync;
  - 8 sample calls, labelled as AI on both sides;
  - "Agentic, not just talking": calendar, WhatsApp, CRM lookup, custom API (EMI fetch), transfer to staff, caller memory;
  - built-ins: numbers in 5 minutes with digital KYC and an "IVRS-ready" number, auto-retries, "DLT-registered numbers and consent checks", mid-call recovery, duplicate-call avoidance, auto-pause on carrier refusals, and a spend floor;
  - a "For developers" section with lead intake (202 Accepted) and outcome webhooks;
  - pricing.
- **Customer proof:** none beyond the 5,000+ count. The only logos are Sarvam and Cartesia, shown as startup-programme backers.
- **New nav items:** Voices, Partners, Docs, API.

### Pricing (https://outpero.com/pricing)
Pricing is no longer per employee. The full figures are in section 5.
- There is a worked example of a month's cost (see section 5).
- The page defines a channel as one concurrent call; extra channels cost ₹649/month each.
- It lists no top-up packs, bonuses, competitor price table or billing rounding. The August page benchmarked Bolna, Vapi and others by price; that table is gone from /pricing.

### Voices (https://outpero.com/voices, NEW)
- Claims 600+ voices auditioned, 7 languages native-reviewed, and thousands of tuning calls.
- Offers 8 samples with named voices: Sneha, Neha, Ankit, Pooja, Rahul, Kavya, Riya, Vishal (IDs P01–P09).
- Lists behaviours: ambient sound, apologising, graceful exits, back-channel acknowledgements, barge-in, and following the caller's language.
- "Enhance" rewrites a script to local conventions ("ji"/"aap", lakh/crore).
- Shows only "Voices from ₹5/min" and no per-tier count. The 22 Oct in-app count was 32 Premium and 23 Standard (ce5860a2).

### Instant leads (https://outpero.com/product/instant-leads, NEW)
- Calls each new lead in under 30 seconds; the demo shows the phone ringing at 18 seconds.
- **Named sources:**
  - Facebook and Instagram Lead Ads;
  - IndiaMART and JustDial;
  - Zoho CRM, LeadSquared and Sell.Do;
  - Zapier, Make, n8n and Pabbly;
  - WordPress, Wix, any web form, Google Sheets;
  - the Lead API.
- Out-of-hours leads are called when the window opens. Callback times are honoured. Repeat enquirers resume the earlier conversation. Calendar booking and in-call WhatsApp are available.
- **Developer claims:** a POST that returns 202, with duplicate leads within a few minutes ignored. A `call.ended` webhook is signed with HMAC-SHA256.
  - The API docs instead name the events `call.completed` and `call.not_connected`, so the marketing event name differs from the docs.
- No customer proof.

### Bulk campaigns (https://outpero.com/product/campaigns, NEW)
- The demo runs a 1,240-row CSV across 3 lines, 10:00–19:00 Mon–Sat, "DND respected". Results come back as Interested / Call back / Not interested / No answer.
- **Features:** column-to-variable mapping, skipping recently called contacts, holiday skipping, a retry schedule (30 min, then 2 h, then next day), and pause/edit/extend while live.
- **Throughput for 1,000 contacts:** about 18.1 h on 1 channel, about 6 h on 3, about 1.8 h on 10.
- Channels cost ₹649/month each.
- The only compliance claim is DND respected; the page does not mention DLT or consent.

### Inbound (https://outpero.com/product/inbound, NEW)
- Presented as available, with no "coming soon" label. The August docs said inbound was not shipped.
- Answers 24/7, switches language mid-call, transfers hot or unhandled callers to a person, books appointments, sends WhatsApp, and records each call with a summary and captured details.
- Explicitly "no IVR menu". Claims 0 seconds on hold and about 5 minutes to set up a number.
- No prices beyond per-minute billing. No customer proof.

### Partners (https://outpero.com/partners/apply, NEW)
- An application form for agencies reselling AI voice agents.
- The form asks for:
  - name, agency, email, phone, website and location;
  - services and active-client range (0–5 up to 50+);
  - AI familiarity, acquisition plan and awareness plan.
- There is a "Sign in to the partner portal" link.
- No commission, margin, tier or white-label terms are published. The sitemap does have /white-label-ai-voice-agent.

### Agency (https://outpero.com/agency) and About (https://outpero.com/about)
Done-for-you packages, matching August's /about:

| Package | Price | Covers |
|---|---|---|
| Revenue Capture | from ₹60,000 | AI voice agent, WhatsApp/SMS bot, CRM sync |
| Ops Efficiency (flagship) | from ₹1,00,000 | 3–5 automations, n8n/Make |
| Web Capture | from ₹50,000 | landing pages and lead capture |
| 19 individual solutions | from ₹14,999 | – |

- Process: a 30-minute call, a fixed-price scope, go-live within 2 weeks, and "results within 30 days".
- No client names. The stats block shows placeholder zeros ("0 sec", "0 hrs", "0x").
- /about still names only the founder's first name, through vatsal@outpero.com.

### Contact (https://outpero.com/contact)
- Lists email only (support@outpero.com; the visible text reads "ussupport@outpero.com", which is a typo).
- No phone, address or GSTIN on the page.
- Form fields: name, business, work email, phone, business type, size, calls per month, and what the AI employee should do.

### Compare (https://outpero.com/compare, NEW)
- Covers 35 named vendors at /compare/vs/*: Indian voice AI, telephony, enterprise, global and developer platforms. Bolna, Vapi, Retell, Bland, OmniDimension, Edesy, Vomyra, SquadStack, Exotel and Ozonetel are among them.
- Also covers 23 alternatives such as "vs human telecaller" and "vs IVR".
- Competitor prices it quotes:
  - Edesy ₹1,499 Pro with 300 free minutes;
  - Vomyra from ₹19,999/month;
  - SquadStack ₹2–5/min;
  - TeleCRM ₹799–1,099 per user per month;
  - HighLevel $97/month;
  - ElevenLabs $0.08/min;
  - Twilio ConversationRelay $0.07/min.
- **/compare/vs/bolna:** Bolna details are dated "checked 30 July 2026". The page concedes Bolna suits teams with engineers who want to pick each layer. It says Bolna leaves DLT and DNC to the developer. The August "Bolna ₹8-10/min robotic Telugu" jab is not on this page.

### Blog (https://outpero.com/blog)
- 118 posts: 1 on 30 Jul, 87 on 14 Oct, 28 on 19 Oct, 2 on 22 Oct 2026.
- Themes:
  - language "best/cheapest/top companies" posts for Tamil, Malayalam, Kannada, Telugu, Hindi and Marathi;
  - city guides, including Hyderabad, Vizag, Vijayawada, Telangana and Andhra Pradesh;
  - industry buyer's guides;
  - cost comparisons against human telecallers;
  - vendor roundups;
  - compliance (for example /blog/are-ai-calling-agents-legal-in-india).
- The latest post is "Free Telugu AI Voice Agent (2026)" (22 Oct).

### Glossary (https://outpero.com/glossary, NEW)
- 103 terms at /glossary/{slug}.
- Categories: Voice AI 39, Metrics 18, Telephony 19, Language 4 (including Tenglish), Compliance 11 (DLT, TCCCP 2018, DPDP 2023, UCC), Sales 12.

### Free AI voice agent (https://outpero.com/free-ai-voice-agent, NEW)
- 50 credits (₹50): about 10 minutes on Standard or about 7 on Premium.
- Billed on connected time only. No going-live bonus is mentioned.
- Tells users to test only on their own or consenting colleagues' phones, citing TCCCP 2018.
- Live languages: Hindi, Telugu, Tamil, Marathi, Kannada, Malayalam, Indian English. Bengali, Gujarati, Punjabi and Odia are stated as not live.

### Telugu (https://outpero.com/telugu-ai-voice-agents)
- **Claims:** "Tenglish", neutral spoken Telugu for both Telangana and Andhra, a mid-sentence switch to English, and 0.8–1.3 s average latency.
- **Comparison:** a ₹18,000/month human telecaller.
- **Features listed:** caller memory, WhatsApp, Google Calendar, custom API, post-call webhooks, knowledge base.
- **FAQ:** advises testing on Rayalaseema, coastal Andhra and Telangana leads.
- There is a deploy form (not submitted). No customers are named.
- Prices match /pricing.

### Deploy (https://outpero.com/deploy, older AP/TS landing page)
- Pricing copy: "₹0/mo base salary" and "From ₹5/min", with Value, Standard and Premium tiers named but no per-tier prices.
- **Claims:**
  - under 800 ms latency "using Cartesia and Sarvam";
  - 100+ concurrent calls;
  - DLT-compliant +91 numbers;
  - live in about 10 minutes.
- An unsourced "400%" lead-decay stat. Contact is by WhatsApp. No proof.

### Legal (marketing-site copies, all "Last updated 14 October 2026")
- **Terms** (https://outpero.com/terms-and-conditions):
  - Entity: OpenDG Private Limited, Hyderabad. No GSTIN.
  - §09: they aim for 99.9% uptime with no guarantee unless agreed in writing.
  - §13 liability cap: fees paid in the 3 months before the event, per 12-month period.
  - §05: TRAI TCCCPR/DLT/NCPR duties sit on the customer.
  - §05/§07: AI and recording disclosures are the customer's duty "where required".
  - §17: exclusive jurisdiction in Hyderabad.
- **Privacy** (https://outpero.com/privacy-policy):
  - Sub-processors are listed by category only.
  - Some providers process data outside India.
  - Call data is kept while the customer keeps it.
  - The policy is silent on model training.
  - The grievance contact is support@outpero.com, with no officer named. DPDP 2023 is cited.
- **Refund** (https://outpero.com/refund-policy):
  - **Unused paid credits are refundable on account closure if requested within 180 days of the last top-up**, less gateway fees.
  - Wrong call charges can be disputed within 30 days.
  - Response in 3 business days; payout in 7–10 business days.
  - The current month's number and channel charges are not refunded.

### Legal (app.outpero.com Legal Centre, which the docs link to)
- **Terms** (https://app.outpero.com/terms), "Last updated: 3 November 2026":
  - §4: prepaid credits through Razorpay, "no joining fee and no per-employee charge".
  - Number rental and extra channels are recurring deductions from credits, never from a card.
  - The balance never goes negative.
  - §9: no guarantee the service will be uninterrupted.
  - §11: liability capped at fees paid in the 3 months before the claim.
  - §13: exclusive jurisdiction in Hyderabad.
- **Refund** (https://app.outpero.com/refund), "Last updated: 3 November 2026":
  - **Purchased credits are non-refundable and non-transferable**.
  - A number month or channel period already paid is non-refundable.
  - Signup bonus credits may be changed at any time.
  - Refunds only for duplicate charges, credits not delivered, or a verified bug, within 5–7 business days.
  - **This contradicts the marketing-site refund policy** (180-day closure refund).
- **Acceptable Use** (https://app.outpero.com/acceptable-use), "Last updated: 1 August 2026":
  - Unchanged in substance since August.
  - The customer must be able to produce the lawful basis, their privacy policy and the recording within 24 hours of a complaint.
  - The customer is responsible for AI and recording disclosure.
- **Security & Sub-processors** (https://app.outpero.com/security), "Last updated: 25 July 2026":
  - Unchanged since July, and still mentions "hire-fee checkout".
  - Named providers: Supabase (auth), Razorpay, PostHog EU (setup flow only).
  - Other categories unnamed, with a list "on request".
  - Cross-provider failover mid-call across STT, LLM and TTS.
  - A 72-hour target for incident notification.

---

## 3. Per-route notes: docs.outpero.com Help centre

The overview header claims 3 channels, 27 topics, "3–7 c per minute" and "₹649 per phone number / month".

- **#overview**
  - An employee has one main job (Instant, Bulk or Inbound).
  - Every employee also answers its own leads when they ring back (Settings → Incoming calls).
  - Flow: describe → draft → free test → go live with a ₹649/month number → watch.
- **#first-employee:** built in "Employee Store".
  - Step 1: pick a channel and a language (7, plus an optional second Indian language; English always on).
  - Step 2: describe the job by typing or voice note.
  - Step 3: a free test call to your own phone, which "don't touch your credit balance". The 22 Oct first-hand test call was charged ₹13.60 (ce5860a2), so the docs and the observed behaviour disagree.
  - Step 4: start training.
- **#going-live:** no joining fee, licence or per-employee monthly charge.
  - Exactly two costs: talk time at ₹3–7/min and a ₹649/month number per live employee.
  - A one-time PAN/Aadhaar check.
  - The number auto-renews from credits. If it goes unpaid, they email and retry, then release the number to the carrier.
  - Nothing else is deleted when a number lapses.
- **#lifecycle:** four states, Draft → In training → Live → Paused.
  - Real calls need all three: a number, "Taking calls" on, and published at least once.
  - The August "hired" gate is gone.
- **#script**
  - Default sections: identity → greeting → qualify → objections → call to action → closing.
  - Free-text call-end rules.
  - A permanent FAQs section.
  - Strictness on a 1–5 dial.
  - Pre-call `{{variables}}` versus captured variables.
- **#voice:** voice engine branded "Swara".
  - Standard ₹5/min and **Premium ₹7/min**. The site says ₹6.8.
  - The worked example still mentions a "Value" voice.
  - Ambient options: Office, Call Center, Restaurant, Quiet Room, Retail Store.
  - Voice changes go live immediately.
- **#actions:** still only four opt-in actions: Calendar booking, Sheets read/write, Custom API, WhatsApp.
  - Call transfer, which the marketing site advertises, is not listed here.
- **#postcall:** captured-variable edits apply immediately.
  - Webhook triggers: every connected call / completed only / voicemail only.
  - Test-send is available.
- **#publishing:** script, flow, actions and webhooks need "Apply to live calls". Voice, captured variables and training apply immediately. Unchanged.
- **#versions:** keeps the last 3 published versions.
  - Switch channel (Instant ↔ Bulk) clears call history.
  - Start from scratch wipes script, training and history but keeps the number, balance and billing.
- **#instant:** a private intake URL per employee.
  - **Now protected by an `X-Outpero-Lead-Secret` header.** In August the token sat in the path and the secret header was optional.
  - Endpoint: `POST https://api.outpero.com/lead-intake/<connection-id>`. Only `phone` is required.
  - **Unknown fields are now accepted and ignored**, and only fields matching defined pre-call variables reach the script. August was schemaless.
  - Sources: generic webhook, Google Sheets, Meta Lead Ads via Zapier (still not native), Zapier/Make.
  - Test webhook and a webhook activity log (accepted / deduplicated / rejected).
  - Calling policy: delay, window, out-of-window handling (next open / +3h / +6h / next day / hold), and a retry ladder capped at 9 steps (10 attempts).
  - "Needs attention" queue and "Call now".
- **#bulk**
  - Contact sources: manual, paste or CSV. Unmatched columns must be mapped, created or ignored, never guessed.
  - Saved reusable lists.
  - Calling window, days and holidays.
  - **Concurrency 1–20.**
  - Retries 1–9, same run or next day.
  - Schedule or recur daily/weekly.
  - Cross-campaign recent-contact skip.
  - **Per-campaign suppression list (NEW).**
  - Live panel; CSV export.
  - **Limit: 10 live campaigns per account (was 3 in Aug)**, and 1 per number, with queueing (oldest first).
  - DNC is checked on add and again before each call, but **"not yet applied to Instant lead calls"**, which is unchanged from August in the Help centre.
- **#inbound:** fully rewritten and now shipped.
  - Hire with "Receptionist & Support".
  - Train on timings, services and FAQs. It takes a message instead of guessing.
  - Buy and attach a number. A setup checklist ticks when the first call arrives.
  - **Every caller first hears that the call is recorded, then the greeting.**
  - Messages and callback requests trigger an email plus a notification and land in "Messages from callers". There is a daily summary email.
  - Opening hours: 24/7 by default, or closed-with-message.
  - "Missed callers" shows reasons. The missed-caller callback (once, inside hours, never DNC) is on by default.
  - Concurrency equals the number's channels (1 by default, shared with outbound).
  - No separate fee; per-minute only. A call the balance can't cover isn't answered.
  - `GET /v1/inbound-calls`.
- **#calling-rules**
  - The business is the caller and bears responsibility.
  - No bought or scraped lists.
  - Consent confirmation is recorded as a durable record.
  - **Hours are enforced:** Bulk 9 AM–9 PM, Instant 6 AM–10 PM.
  - DNC requests are added automatically.
  - The DND/DLT and data-protection obligations sit with the business.
- **#calllog:** each call shows recording, summary, sentiment, talk ratio, next step, transcript ("no transcript available" if none), extracted data, notes, share, and call back.
  - **Retention: recordings, transcripts and summaries kept while the account is active, with no limit.**
- **#leads:** one row per phone number, with table, card and kanban views, and "Call now".
- **#conversations:** filters remembered; CSV export.
- **#performance:** account-wide funnel, channel split, busiest hours, and an employee leaderboard. Instant and Bulk each have their own dashboards.
- **#numbers:** browse and buy, paying "the setup fee and first month" from credits.
  - KYC on the first purchase only (PAN, then Aadhaar via DigiLocker).
  - Auto-activates; assign to an employee.
- **#training:** teach by text, voice or photo, which is sorted into facts and rules for review.
  - Documents are retrieved only when needed.
  - Suggestions come from struggles on real calls.
  - The sandbox costs 0.05 credits per message.
  - Precedence: script > rules > voice.
- **#credits:** 1 credit = ₹1.
  - **Signup bonus 100 credits** here; the site says 50.
  - Standard ₹5, Premium ₹7, script generation 0.2 credits per use.
  - Chat test "₹0.20/message" on this page, versus 0.05 credits on #training: an internal contradiction.
  - Building, training and tests free; number ₹649/month.
  - Billed in 30-second blocks, rounded up. Ring/busy/unanswered free.
  - A graceful goodbye at zero balance.
  - A low-credit email at about ₹50, at most daily.
- **#topup:** presets ₹500 / ₹1,000 / ₹2,500 / ₹5,000 or custom, by card or UPI, credited 1:1.
  - **No bonus packs any more.** August had ₹999 to ₹50,000 packs with bonus credits.
- **#statements:** monthly statement with CSV, transactions with running balance, per-employee usage.
- **#notifications:** campaign finished, caller opted out, announcements.
- **#settings**
  - Caller memory (off by default).
  - **Auto-reschedule ("call me at 5pm") off by default.**
  - DNC list.
  - Password and sign-out.
  - Data export of leads to CSV.
- **#reliability:** maximum call length 10 minutes by default (10 s to 1 h).
  - Inaudible failover.
  - A Premium voice under strain falls back to a Value voice billed at the lower rate, never upward.
  - No healthy path → no call. Failure mid-call → a spoken apology and a clean end.
- **#howitfits:** a shared line (first come takes it). One Bulk campaign per number. **10 live campaigns.** The precedence rule, the publish speeds, DNC "not yet applied to Instant", and the three-part gate.

---

## 4. Public API v1 (NEW; docs.outpero.com/#api, openapi.json)

- **Base URL and auth**
  - Base: `https://api.outpero.com/v1`.
  - Auth: `Authorization: Bearer op_live_…`. Keys are created at Developers → API keys (https://app.outpero.com/#developers).
  - Keys are shown once, with only a fingerprint stored, and end in a checksum so secret scanners can spot them.
  - Up to 10 keys, each Full access or Read only.
  - Creating a full-access key records the customer's consent confirmation.
  - Browser-origin requests are refused (403 `browser_requests_not_allowed`).
  - Source: #api/authentication.
- **Endpoints (37 operations in openapi.json):**

  | Resource | Operations |
  |---|---|
  | `/me`, `/balance` | GET |
  | `/employees` | list, get. Fields include `mode` instant/bulk/inbound, `call_variables`, `capture_fields`, `calling_hours`, `incoming_calls`, `voice_tier`, `max_call_duration_seconds`, `is_published` |
  | `/phone-numbers` | list, get. Includes `channels` |
  | `/calls` | list, POST, get, cancel. POST body: `employee_id`, `phone`, `name`, `variables`, `external_id`, `metadata` (≤20 keys), `scheduled_at` (≤7 days), `dry_run`. Instant-mode employees only |
  | `/leads` | list, get. Filters: outcome, direction, campaign, employee |
  | `/campaigns` | list, create, get, contacts list, add contacts (≤1,000 per request, 50,000 per campaign), launch, pause, resume, cancel. Window kept within 09:00–21:00 |
  | `/dnc` | list, add, delete |
  | `/webhook-endpoints` | CRUD, deliveries, resend, rotate-secret, test |
  | `/events` | list, get, kept 30 days |
  | `/inbound-calls` | list, get. Status answered / missed / called_back |

  - Campaign retry fields: `retry_mode` next_day / same_run / after_days; `max_attempts` 1–10 (default 3); `retry_gap_minutes` 5–1440; `retry_gap_days` 1–30.
- **Call status enum:** queued, scheduled, on_hold, in_progress, completed, not_connected, failed, canceled, blocked. A call waiting more than 24 hours is cancelled. Poll no faster than every 15 seconds (#api/concepts/call-lifecycle).
- **Result object:** outcome, summary, sentiment, captured, transcript lines (agent/customer), `recording_url` valid for 1 hour, `credits_charged`, duration, `ended_by`, `callback_at`.
- **Calling rules through the API** (#api/concepts/calling-rules):
  - The employee's own number is required (409).
  - Hours always inside 6:00–22:00 IST; campaigns 9:00–21:00.
  - **DNC is checked at creation and again before dialling; a matched call is created as `blocked`.**
  - 402 when out of credits. No API surcharge.
  - A duplicate (same person and employee within a window of 5 minutes or more) returns the existing call with HTTP 200.
  - **Contradiction:** the API docs apply DNC to API-placed instant calls, while Help centre #bulk and #howitfits still say DNC is not applied to Instant.
- **dry_run** works on every write. The response lists each check; nothing is written or charged. The sample number +919876543210 is refused (#api/test-mode).
- **Idempotency** (#api/concepts/idempotency):
  - `Idempotency-Key` header, up to 255 characters, held 24 hours.
  - A replay returns `Idempotent-Replayed: true`.
  - A different body gives 422 `idempotency_key_reused`; a request still in flight gives 409.
- **Rate limits** (#api/concepts/rate-limits):

  | Limit | Value |
  |---|---|
  | Reads | 120 per minute per key |
  | Writes | 60 per minute per key |
  | Per account | 300 per minute |
  | API calls placed | 1,000 per 24 h per account (100 in the first week or before the first payment) |
  | Calls to the same person | 3 per 24 h across all sources |
  | Request body | 1 MB |
  | Endpoints | 10 |

  Headers: `X-RateLimit-*`; 429 with `Retry-After`.
- **Errors** (#api/concepts/errors):
  - Shape: `{error:{type, code, message, param, request_id}}`, with `X-Request-Id`.
  - Codes include `invalid_phone`, `missing_required_variable`, `employee_not_instant`/`employee_not_bulk`, `insufficient_credits`, `api_writes_disabled` (incident kill switch), `employee_not_published`/`no_phone_number`, `daily_call_limit_reached`, `too_many_calls_to_number`.
- **Versioning** (#api/concepts/versioning): additive-only within v1. Breaking changes go to /v2 with 12 months' notice. Events carry `api_version` (currently "2026-10-16").
- **Webhooks** (#api/webhooks, /signatures, /retries, /events):
  - https URLs only, with private addresses refused.
  - Headers: `X-Outpero-Event`, `-Event-Id`, `-Delivery-Id`, `-Timestamp`, `-Signature`.
  - **Signature:** `sha256=hex(HMAC_SHA256(secret, timestamp + "." + raw_body))`. Reject anything older than 5 minutes. For 24 hours after a rotation, `X-Outpero-Signature-Previous` is also sent.
  - Reply 2xx within 10 s; redirects count as failures.
  - **8 attempts:** immediately, 1 min, 5 min, 30 min, 2 h, 6 h, 12 h, 24 h.
  - An endpoint that fails every delivery for 3 days is disabled, with a notice.
  - Delivery log and resend. Delivery is at-least-once and unordered; dedupe on the event id.
  - The older per-employee Outcomes-tab webhook still works with the same signature scheme.
  - **Events:** `call.completed`, `call.not_connected`, `lead.created`, `call.inbound_answered`, `call.inbound_missed`, `campaign.status_changed`, or `*` for all.
- **Guides:** n8n, Make, Zapier, Pabbly. The n8n guide (#api/guides/n8n) offers:
  - a Header Auth credential;
  - an idempotency key built from `$execution.id`-`$itemIndex`;
  - a "Copy as n8n node" button on every endpoint;
  - 4 importable workflows (Sheet row → call → write-back; lead form → call; results → Slack; Sheet → campaign);
  - batching advice: loop in batches of 50 with a 30 s wait.
- **Downloads:** Postman collection, OpenAPI 3.1, n8n workflows (#api/downloads).
- **Changelog** (#api/changelog):
  - **16 Oct 2026:** v1 launch (keys, employees, numbers, balance, calls, leads, campaigns, DNC, signed webhooks).
  - **18 Oct 2026:** incoming calls (`/inbound-calls`, `incoming_calls` on employees, `caller_request`/`message` on leads, the `call.inbound_answered` event).

---

## 5. Pricing as of 28 Nov 2026

All prices exclude GST. Source: https://outpero.com/pricing unless another URL is given.

| Item | Figure | Source |
|---|---|---|
| Standard voice | ₹5 / connected minute ("Most chosen") | /pricing |
| Premium voice | ₹6.8 / min | /pricing. Docs say ₹7 (#voice, #credits) |
| Custom / volume | from ₹3.5 / min, by quote | /pricing |
| Value voice | not on the site. Docs still mention a ₹3 rate (#credits text, #reliability fallback) | docs |
| Setup fee / monthly subscription / per-employee fee | none | /pricing, app Terms §4 (3 Nov) |
| Business number | ₹649 / month, includes 1 channel, deducted from credits | /pricing |
| Extra channel | ₹649 / month each, renews every 30 days | /pricing, app Terms §4 |
| Number setup fee | a fee is mentioned but no figure is given | docs #numbers |
| Free credits at signup | 50 (no card) | /pricing, /free-ai-voice-agent. Docs #credits say 100 |
| Going-live bonus | not published (22 Oct in-app showed +300; ce5860a2) | – |
| Top-up | presets ₹500 / ₹1,000 / ₹2,500 / ₹5,000 or custom, 1:1, no bonus packs | docs #topup |
| Billing unit | 30-second blocks, rounded up; unanswered calls free | docs #credits |
| AI script generation | 0.2 credits per use | docs #credits |
| Chat sandbox | 0.05 credits per message (#training) or ₹0.20 per message (#credits); the two pages contradict each other | docs |
| GST | 18%, not included | /pricing |
| Worked example | 2,000 connected calls × 1.5 min on Standard = ₹15,000 + ₹649 number = ₹15,649/month + GST, about ₹8 per call | /pricing |
| 1,000-contact list | about 6 h on 3 channels; number plus 2 extra channels = ₹1,947/month | /pricing |
| Done-for-you agency | from ₹14,999 (solution), ₹50k / ₹60k / ₹1,00,000 (systems) | /agency |

---

## 6. Changed since August and October 2026

1. **The hire fee is gone.**
   - August: ₹1,899 per employee per month, including ₹500 of credits and a number.
   - Now: talk time plus ₹649 per number per month (pricing, docs #going-live, app Terms 3 Nov).
   - The Premium rate fell from ₹7 to ₹6.8 on the site, though the docs still say ₹7.
   - The Value ₹3 tier is gone from the site. A Custom tier from ₹3.5 is new.
2. **Concurrency is now sold as channels**, at ₹649/month each. Campaigns run at 1–20 concurrent calls, and inbound concurrency equals the channel count. August had "one number = one line".
3. **Top-up bonus packs were dropped** (August: ₹999 to ₹50,000 with up to +6,000 bonus). Plain 1:1 presets replace them.
4. **Inbound has shipped.**
   - August docs: "coming soon", with inbound numbers only playing a message.
   - Now: a receptionist with messages, call-backs, opening hours, missed-caller call-back, and a recording notice before the greeting.
   - There is also an inbound API and events.
5. **A public REST API v1 launched on 16 Oct 2026**, with inbound endpoints added on 18 Oct. It covers keys with scopes, dry_run, idempotency, rate limits, an error catalogue, versioning, HMAC-signed timestamped webhooks with secret rotation, 8 retries, a delivery log and resend, and OpenAPI, Postman and n8n assets.
   - This closes most of the integration gaps we listed in August (memory 777dd436): unsigned outbound, fire-once delivery, no published outbound schema.
6. **The lead intake contract changed.**
   - From the path token `/leads/in/<token>` with an optional secret
   - to `/lead-intake/<connection-id>` with an `X-Outpero-Lead-Secret` header.
   - Unknown fields are now ignored rather than turned into variables.
7. **The live-campaign limit rose from 3 to 10 per account.** A per-campaign suppression list was added.
8. **The 99.9% uptime SLA claim was removed** from the marketing pages (home, /ai-employee).
   - The marketing Terms §09 now says they "aim for" 99.9% with no guarantee.
   - The app Terms §9 still guarantee nothing.
   - The liability cap is unchanged at 3 months of fees.
9. **There are two divergent policy sets.** outpero.com has Terms, Privacy and Refund dated 14 Oct; app.outpero.com has Terms and Refund dated 3 Nov.
   - The marketing refund policy allows refunds of unused paid credits within 180 days of closure.
   - The app refund policy says purchased credits are non-refundable.
   - outpero.com/security, /acceptable-use and /cookie now return 404; the app copies are the only ones.
   - Security (25 Jul) and AUP (1 Aug) are unchanged.
10. **A massive programmatic-SEO build went up between 4 and 22 Oct.**
    - About 1,500+ URLs: 118 blog posts, 444 Q&A pages, 103 glossary terms, 58 comparisons, 14 alternatives, 171 city/state pages, 235 industry and industry×city pages, use-case and language pages.
    - It is Telugu/AP-TS heavy but now pan-India across 7 languages.
11. **Positioning moved** from "AI employee", Telugu-first, to "AI telecalling software" with 7 equal languages.
    - New pages: Voices, product pages, Partners (agency reseller program), Compare.
    - The home page now claims "DLT-registered numbers and consent checks".
12. **Lifecycle and gates:** "hired" was replaced by Draft / In training / Live / Paused. A live call needs a number, "Taking calls" on, and publication.
13. **Recordings and transcripts are now kept with no limit while the account is active** (#calllog). Deletion is on request.
14. **New Settings items:** auto-reschedule for callbacks, and a lead CSV export. Every outbound employee now also answers callbacks from its own leads.
15. **Things that did not change:**
    - DNC is still "not yet applied to Instant" in the Help centre, though the API docs apply it.
    - Still only 4 actions in the docs (no transfer listed).
    - 3 versions kept, with no diff.
    - Meta Lead Ads still only through Zapier in the docs (the product page lists Facebook/Instagram Lead Ads directly).
    - Still no named customer anywhere; "5,000+ businesses" is unsupported.
    - Sarvam and Cartesia are still shown as backers; /deploy names them as the speech models.
    - Sub-processors are still unnamed beyond Supabase, Razorpay and PostHog.
16. **Internal inconsistencies to cite carefully:**
    - signup credits 50 (site) versus 100 (docs);
    - Premium ₹6.8 versus ₹7;
    - sandbox 0.05 credits versus ₹0.20;
    - "test calls free" (docs) versus the charged test call observed on 22 Oct;
    - `call.ended` (marketing) versus `call.completed` (API);
    - DNC on Instant (API yes, Help centre no);
    - 18 language pages versus 7 live languages.

---

## 7. Not readable or not found

- **Status page:** status.outpero.com does not resolve (DNS ENOTFOUND). No public status page was found.
- **App-store presence, YouTube demo videos, LinkedIn/social:** no listing or channel was found by web search, and the site footer, /about and /questions/what-is-outpero link to none. UNKNOWN whether any exist.
- **/agency FAQ:** the answers were not in the text extraction.
- **/partners/apply:** no commercial terms are published.
- **Sitemap pages not fetched individually:** the 444 /questions, 171 /fastest-employee, 235 industry pages, use-case pages and 57 of the 58 /compare pages. Their titles and counts are from https://outpero.com/sitemap.xml only.
- **API sub-pages read in summary only:** the full field lists of /employees, /leads, /campaigns and /webhooks were read from openapi.json and the rendered pages but not transcribed. The raw spec beside this file is the reference.
- **Guide pages:** #api/guides/make, /zapier and /pabbly were rendered (1.5–1.8k characters each) but not summarised beyond their existence.
- **Docs render lag:** the stale-body effect from August reproduces at a 0.7 s settle. At a 2.5 s settle every route above returned its own distinct body, and none was left unread.
