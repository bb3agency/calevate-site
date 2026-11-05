# Fixed business assumptions in Calevate — map and fix plan (5 Nov 2026)

Founder, 5 Nov 2026: "we still have so much hardcoded shit all across Calevate … map all the
hardcoded shit and make everything that matters dynamic." Trigger: every agent's "What it may do"
shows "Offer a call back / Tell callers prices / Take bookings and orders", including Rytu Khata —
an app whose callers are registered users being helped, not customers being sold to.

Three read-only audits (backend; client app; Pip, practice callers, emails, admin setup) agree.
Line numbers are as read on 5 Nov 2026 and will drift; search by the quoted text.

## Root cause

There is no per-business record of what the business does with callers — whether it takes
bookings, takes orders, quotes prices, has a place callers visit, sells anything, is a health
business, what its callers are called, which objections they raise. So every layer falls back on
the eight fixed business types (`scripts/seed.py` BUSINESS_TYPE_LABELS / VERTICAL_TEMPLATES,
`apps/api/agents/starters.py` TRADES, `trade_playbooks.py` TRADE_WORDS, `first_run/questions.py`
TRADE_CHOICES, `spoken_style.json` per-type examples, `apps/web/src/lib/businessTypes.ts`,
`lib/verticalExamples.ts`) or on a "selling business" default — and the "custom" type is not
neutral: it still says "a booking", "prices", "delivery".

What is already per business and should be reused (verified by the audits):
- Business copy, D-827 (`apps/api/tenancy/business_copy.py` GeneratedCopy, `apps/workers/business_copy.py`,
  prompt-versioned, refreshed every 15 days) — placeholders, steps, caller_details,
  example_questions, starter_lines, screen_guide (the yes/no + reason pattern to copy).
- Profile wording (`apps/api/tenancy/profile_wording.py`): offer_label, booking_title, booking_hint,
  and `price_label = None` already meaning "quotes no prices" (display-only today).
- Business profile (services/prices, FAQs, booking_rules, languages, staff) → `[T0 FACTS]`.
- Starter plans (per-business step titles), business outcomes D-836, lead fields D-715/D-889,
  campaign brief/goal, capability manifest (live tools), per-agent switches, console config.

## The map

### A. What the agent may do, and the call plans (HIGH — changes calls)
- A1 `packages/shared/.../call_script.py` ScriptPolicies `offer_call_backs/share_prices/take_bookings`
  all default True; compiled "Do not quote prices…/Do not make a booking yourself…". Web:
  `agents/[agentId]/script/ScriptSections.tsx` "What it may do" switches; `ScriptParts.tsx`
  "tells prices / takes bookings" summary. `ScriptContextOut` says nothing about which apply.
- A2 `apps/api/agents/starters.py` every starter goal "arrange {trade.booking}"; agent name
  suggestions "Receptionist / Lead follow-up"; fixed tone "front desk"; English opening templates.
- A3 `apps/api/agents/trade_playbooks.py` a fixed "Offer {booking}" step in every plan (two exact
  times, weekday/date/time/place read-back), locked by JOB_STEP_COUNTS / starter_steps
  ("keep the plan's own word for a booking") and business-copy starter_lines count.
- A4 `starters.py` TRADES table incl. the custom row ("a booking", "prices, timings or location",
  "Never promise a price, a delivery date"); real-estate caution contradicts share_prices=True.
- A5 Objections assume a sale: `trade_playbooks.py` "How much does it cost?", "I already bought it
  or booked somewhere else", TRADE_WORDS per-type objections (custom: "Can you just tell me the price?").
- A6 `engine.py` VOICE_STYLE_GUIDANCE "Unsure about buying or not interested? Offer once, then close".
- A7 `capability_manifest.py` `_BOOKS` decides "this agent books" from step-title words + TRADES nouns
  → readiness "Connect a calendar", Pip.

### B. Outcomes, moments, follow-ups, lead words (HIGH)
- B1 `business_outcomes.py` STARTING_OUTCOMES "Wants to buy or book" first; web fallback
  `verticalExamples.ts` outcomeMeaning "wants to buy or book".
- B2 `apps/workers/business_outcomes_draft.py` forces a buy/order/book outcome in every draft.
- B3 `extraction.py` moment group "buying" (booking_agreed, price_quoted, asked_delivery_or_payment,
  will_buy_or_visit); web `lib/callMoments.ts` "Buying signal"; `calls/[callId]/InsightsCard.tsx`
  sales vocabulary ("Promised to pay", "Pass to sales", "Delivery", "Product").
- B4 `follow_ups/starters.py` "Qualify new leads" branches on fixed keys interested/not_interested;
  B5 "Visit reminder"/"Payment reminder" read fields nobody has (visit_date, due_date).
- B6 Lead status ladder shown as sales words: "Hot lead from your AI agent" email
  (`apps/workers/notifications.py`), daily summary "new lead / hot / Cost per lead"
  (`notifications/daily_summary.py`), dashboard `CostPerLead.tsx`, `followUpActions.tsx` "Won —
  They bought or booked", alerts panel "Hot lead, always". Keep the enum (D-21); show per-business words.

### C. Profile, go-live, knowledge, practice (HIGH)
- C1 `tenancy/business_profile.py` items without a price compile to "price on request" in [T0 FACTS].
- C2 `business_profile.py` go-live blocked on "Add your address" even with no premises.
- C3 `first_run/questions.py` fallback questions "How does someone book a booking?", "Where are
  you?"; web `agents/first/QuestionsStep.tsx` "e.g. Site visit", "What you offer / Price", "Shop number…".
- C4 Price nags: `test_conversations.py` missing_facts → "prices"; `teach/questions.py` "What do your
  products cost?"; web `TestSummary.tsx` "Add your prices first".
- C5 `insights/detection.py` fixed topic keywords (pricing, timings "open", location "where",
  stock "unda", booking…) reused by teach questions, setup nudges, kb proposals, hot facts.
- C6 `agents/lead_fields.py` only "custom" gets AI-drafted lead fields; known types get fixed templates.
- C7 Practice callers: `test_conversations.py` chilli-shop standard callers; `specimen_scenarios.py`
  shopper fallback lines ("two of them, to Guntur", "I already got it somewhere else").
- C8 `spoken_style.json` prompt_examples in every live prompt are shop/delivery turns; `_default`
  exchanges "do you have this in stock?"; `spoken_style.py` falls through to other trades' examples.
- C9 First-agent flow `agents/first/BriefStep.tsx` pre-fills the trade's example brief as a real
  value (saved on Continue) and offers other trades' briefs as chips.

### D. Copy generation and guards (MEDIUM)
- D1 `workers/business_copy.py` requires a booking job and a price in teach_note.
- D2 `business_copy.py` CLINIC_WORDS guard keyed on vertical == clinic (wrong both ways).
- D3 `workers/script_assist.py` example identity "the shop: products, prices, orders and delivery";
  `workers/agent_test_ai.py` price push-back callers; `starter_steps.py` booking word lock.
- D4 Telugu-first defaults: `starters.py` STARTER_LANGUAGE, `engine.py` DEFAULT_PRIMARY_LANGUAGE,
  `agents/models.py` server_default, web `StartFromJob.tsx` / `BuildAgent.tsx` — should be the
  business's own first language.
- D5 `retrieval/routing.py` fixed keyword routing table (doctor/dentist/open/slot…).

### E. Client screens and Pip (MEDIUM/LOW)
- Pip suggestions `lib/copilot/suggestions.ts` ("How do I let it take bookings?", "add my price
  list", "hot leads"); `NewCampaignScreen.tsx` / `campaignsCopilotSurface.ts` "book a visit";
  `script/scriptSurface.ts` "the shop and take orders"; `PipAsk.tsx` "price is too high";
  `copilot/console_actions.py`, `agent_actions.py`, `campaign_actions.py`, `charts.py` examples;
  `components/copilot/workspace/Routines.tsx` "missed leads / who is hot".
- Booking job screens `agents/actions/BookingSetup.tsx`, `BookingJob.tsx`, `jobs.ts` (offered to every
  business; "booking" everywhere though the card title is already dynamic).
- WhatsApp `integrations/whatsapp/Templates.tsx`, `lib/api/whatsapp.ts`, `whatsapp/templates.py`
  "Booking confirmed", "order or booking"; `phone-number/ExistingNumber.tsx` "after a booking".
- Script placeholders in Telugu regardless of the business language (`ScriptSections.tsx`,
  `SectionEditor.tsx`); `ScriptSections.tsx` "It is too expensive"; `SmallSteps.tsx` "reference number";
  `tour/tourModel.ts` "Prices, hours, bookings"; `QualityReport.tsx` "real bookings";
  `extraction.tsx` ignores renamed core labels; `OutcomeSplit.tsx` and `CallsScreen.tsx` show only
  platform outcomes, not the business's own.
- Low: `turn_checks.py` retail keyword lists (kg, packets, MagicBricks…), `lead_fields.py` "two kilos
  of green chilli", `extraction.py` "chilli in stock" example, "receptionist / shop owner" in worker
  prompts, `verticalExamples.ts` fallbacks ("Our main service is ₹500", "Festival offer reminder").

Kept fixed on purpose (not findings): hard rule 5 truthful answers, DNC, TRAI/DPDP categories and
consent sources, money constants, generic UI verbs.

## Fix plan

1. Foundation — a per-business capability profile in the business copy (one AI judgement per
   business, each with a reason, refreshed with the copy): takes_bookings, takes_orders,
   quotes_prices, has_premises, sells, health_business; plus objections (2–3 the business really
   meets), caller_noun (what its callers are called: customer, user, patient…), pip_questions;
   booking job title/line optional. Exposed to the API and a single backend accessor; until it
   lands an account keeps today's behaviour.
2. Consumers, in file groups that don't overlap: policies + starters + playbooks + objections +
   manifest (A); outcomes + moments + follow-ups + lead words (B); profile, go-live, first-run,
   practice callers, spoken examples, topics, lead-field drafts (C); copy prompts, guards,
   language defaults, routing (D); client screens + Pip suggestions (E).
3. Every consumer reads the profile; nothing new is keyed on the eight business types, which stay
   only as seeds for a first draft.
