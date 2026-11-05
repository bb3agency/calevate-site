# Lane 6: hardcoded vs dynamic (phase 1, 5 Nov 2026)

Scope: the whole repo (apps/web/src, apps/api, apps/workers, packages/shared, prompts, JSON
data, and seed scripts that reach production). I looked for business-specific content, per-trade
tables, trade-biased prompt examples, hand-written Telugu or Hindi, English-only heuristics,
fixed money, time and limit values, and provider names on client screens.

Method: I read the code at HEAD `6c0e887a9` and used `rg` sweeps (patterns are listed at the end).
I also ran one read-only query on the local dev DB. Line numbers are as read on 5 Nov 2026.

What I could not check:
- I did not drive the browser. Every finding below is visible in code. The screens that show
  them are named in each row, but I took no screenshots.
- I could not see the production `business_copies` rows. So I could not count how many live
  accounts have a judged capability profile.

## 0. Where the earlier map stands (`docs/evidence/hardcoded-business-content-2026-11.md`)

Four commits on 5 Nov act on that map:
- `6114cd7ef`: the capability profile `GeneratedCopy.capabilities`, plus `objections`,
  `caller_noun` and `pip_questions`.
- `2dc3dc105`: client screens and Pip.
- `b253824e1`: outcomes, moments, follow-ups, notices, profile, questions, topics, routing and
  WhatsApp.
- `7fa6eaf5a`: starters, playbooks, practice callers and spoken examples.

`3ea6c3d40` and `6c0e887a9` fixed "Main crops grown".

| Map item | State now | Evidence |
|---|---|---|
| A1 "may do" switches all on | Fitted when judged. `ScriptContextOut.policies_applicable` was added. | `7fa6eaf5a` |
| A2 starters "arrange {booking}", Receptionist / Lead follow-up, front desk | **Partly.** Fitted only when `fit.books is False`. The names and the "front desk" tone are unchanged for everyone else. | `agents/starters.py:538,562,274-275,382` |
| A3 fixed "Offer {booking}" step | Replaced by "Agree the next step" when the business is judged to take no bookings | `7fa6eaf5a` |
| A4 TRADES table, incl. custom "a booking / prices" | **Still live**, and it is the fallback for every unjudged business | `starters.py:171-283` |
| A5 objections assume a sale | **Still live** while unjudged: "How much does it cost?", "Can you just tell me the price?" | `trade_playbooks.py:150,413` |
| A6 "Unsure about buying" | Done ("Hesitant to go ahead") | `7fa6eaf5a` |
| A7 `_BOOKS` from step words | Reads `takes_bookings` first | `capability_manifest.py` |
| B1/B2 outcomes buy/book | Done. The starting outcomes are neutral. | `business_outcomes.py` |
| B3 "buying" moments | Withheld when the business is judged not to sell. `InsightsCard.tsx:21` still says "Promised to pay". | |
| B4/B5 follow-up starters | Done | `follow_ups/starters.py` |
| B6 hot-lead words | **Server done** (`tenancy/caller_words.py`). **Web not done** (see G6). | |
| C1 "price on request" | Done when judged `quotes_prices=False`. Still printed when unjudged. | `business_profile.py:271-274` |
| C2 address blocks go-live | Gated on `has_premises` | `b253824e1` |
| C3 first-run questions | Gated. `TRADE_CHOICES` is still per trade. | `first_run/questions.py:~100-157` |
| C4 price nags | Gated server-side through `missing_facts` | `TestSummary.tsx:145` reads it |
| C5 topic keywords | Gated by capability. **Still English plus romanised only** (G5). | `insights/detection.py:170-206` |
| C6 lead fields | AI-drafted for every business. The type's template is still written first and captured until the owner reviews the draft. | `agents/lead_fields.py:1-20` |
| C7 practice callers | Fitted. **The neutral set is English only** (G5-1). | `test_conversations.py:376-384` |
| C8 spoken examples | Shop turns were removed from `prompt_examples`. Per-type `examples` stay in the data file. | `spoken_style.json` |
| C9 brief pre-fill | Done | `2dc3dc105` |
| D1/D2 | Done | `6114cd7ef` |
| D3 script_assist shop identity | **Still present** | `workers/script_assist.py:146,151` |
| D4 Telugu-first defaults | **Partly.** The business's language is read first. Four separate `te-IN` fallbacks remain (G7). | |
| D5 routing | Health words are gated. The table is still English and romanised (G5). | `retrieval/routing.py:80-243` |
| E (screens/Pip) | Mostly done. Leftovers are listed in G6. | |
| Low: `lead_fields.py` "two kilos of green chilli", `extraction.py` "chilli in stock" example | **Both still present, and both reach every call's extraction prompt** (G3-1, G3-2) | |

**The structural gap the fixes left.** Every consumer follows "THE UNKNOWN RULE": a capability
of `None` means the consumer does what it did before (`tenancy/business_copy.py:16-18,265-268`,
`agents/business_fit.py:9-11`). So the old shop and booking defaults are still the platform's
default. They are only switched off for an account whose copy run has succeeded under prompt
version 4.

Local evidence: the seeded account `sunrise-homes` (`real_estate`) has **no `business_copies`
row**. In the local DB `calevate`, 0 of 7,748 organizations have one. The query was
`select count(*), count(bc.tenant_id) from organizations o left join business_copies bc ...`.
That DB is also behind the migration head: it is at `c4e7a2f9d1b8`, and the
`business_copies.prompt_version` column is missing.

## 1. Map: the mechanisms that put fixed content in front of a business

| # | Mechanism | Where | Who sees it |
|---|---|---|---|
| M1 | Capability profile and its unknown fallback | `tenancy/business_copy.py:234-336,615-625`, `agents/business_fit.py`, `tenancy/caller_words.py`, `web/lib/businessCapabilities.ts` | every consumer below |
| M2 | Eight-business-type tables | `scripts/seed.py:135 VERTICAL_TEMPLATES, :437 BUSINESS_TYPE_LABELS`, `agents/starters.py:171 TRADES`, `agents/trade_playbooks.py TRADE_WORDS`, `first_run/questions.py TRADE_CHOICES`, `web/lib/verticalExamples.ts`, `web/lib/businessTypes.ts`, `spoken_style.json languages.*.examples.<type>`, `agents/specimen_scenarios.py` | owners (placeholders, starters, questions), callers (starter scripts), the extraction model (lead fields) |
| M3 | Example sentences inside model prompts | `calevate_shared/extraction.py:757-758`, `calevate_shared/lead_fields.py:54`, `agents/call_rules.py:107,122`, `workers/script_assist.py:146,151`, `copilot/campaign_actions.py:85`, worker prompts naming "receptionist" or "shop owner" | the models, so every call's data and every draft |
| M4 | Hand-written Telugu, Hindi and staged-language strings in code | `agents/handoff.py:187-198`, `compliance/disclosure.py:178-203`, `compliance/privacy_notice.py:67-76`, `whatsapp/templates.py:98-140`, `agents/specimen_scenarios.py`, `agents/test_conversations.py:~300-375`, `web .../script/ScriptSections.tsx:320,331,423` | callers (handover line, notices, WhatsApp), owners (placeholders, practice runs) |
| M5 | Language word-list detectors | `agents/turn_checks.py` (~228 Indic lines), `compliance/optout.py:300-356`, `compliance/call_purpose.py:180-214`, `insights/detection.py:150-206`, `retrieval/routing.py:80-243`, `teach/questions.py:76-84`, `agents/script_lint.py:147-172`, `calevate_shared/opening_notices.py:27-31`, `calevate_shared/spoken_guard.py:158-166`, `copilot/agent_setup_actions.py:1027-1033`, `workers/call_language.py:104-110` | DNC (law), promo lint (launch gate), practice verdicts, gap topics, owner nudges |
| M6 | Sales words on client screens | `web .../attention/rows.tsx`, `_ui/copy.ts`, `NextSteps.tsx`, `leads/LeadTable.tsx`, `settings/alerts/AlertsScreen.tsx`, `campaigns/CampaignResults.tsx`, `knowledge/TeachBox.tsx`, `calls/CallAgain.tsx`, `lib/firstAgent.ts`, `copilot/notes.py` | owners |
| M7 | Language defaults | `calevate_shared/engine.py:3002`, `agents/models.py:532`, `agents/starters.py:92`, `web/lib/businessCapabilities.ts:108`, `agents/handoff.py:178` | new agents, fallbacks |
| M8 | Fixed money and time values in code | `billing/ai_quota.py:372`, `billing/auto_recharge.py:108-110`, `web .../billing/WhatCallsCost.tsx:118` | owners (billing) |
| M9 | Regression guards | `tests/clinic_words_guard_test.py` (clinic words only), `apps/web/tests/genericCopyGuard.test.ts` | nobody: they decide what can come back |

## 2. Findings

Severity follows BRIEF.md. "Unjudged" means a business whose copy run has not produced
`capabilities` (no run yet, a run that failed, or a copy from before prompt v4).

### G1. Capability profile: the fallback and its granularity

| ID | Sev | Where | What happens (observed) | What should happen | Rule |
|---|---|---|---|---|---|
| G1-1 | **P1** | `tenancy/business_copy.py:615-625` (`capabilities_for` returns `Capabilities.unknown()`); `agents/business_fit.py:9-11`; `tenancy/caller_words.py:9-11`; `web/lib/businessCapabilities.ts:96-104` | An unjudged business gets every old default. A business without the generated copy gets all of these: "Take bookings and orders" on, "Tell callers prices" on, the TRADES row's booking and caution, "price on request" in `[T0 FACTS]`, "Hot lead from your AI agent", shop practice callers, and sales objections. This covers no AI key, a failed run, the first minutes after signup, and any account that has not been re-judged under prompt v4. Locally, `sunrise-homes` and all 7,748 orgs have no copy row. | Unknown should mean neutral, not "sell and book". Withdraw nothing that is dangerous, and assume nothing about selling: the switches off and the words neutral until judged. Show the owner and the admin "Still learning what your business does" with a Retry button. Treat a failed copy run as an alarm, not a silent fallback. | Rule 1, Rule 6 |
| G1-2 | **P1** | `agents/business_fit.py` (keyed on tenant only); `starters.py:538,562`; `test_conversations.py:388-397`; `script_routes.py` `policies_applicable` | The profile is per business, but an agent's job is per agent. A business that sells (a shop, or the app's paid tier) can also have a support or onboarding agent. That agent still gets sales starters, price and booking switches, price objections and shop practice callers. Rytu Khata's support agent is fitted only because the whole business was judged to sell nothing. `3ea6c3d40` already moved lead-detail suggestions to the agent's own job for this reason. | Read the agent's own job (its script goal, steps and direction, or a per-agent "what this agent does") before the business profile. Use the business profile only as the seed. | Rule 1 |
| G1-3 | P2 | `business_copy.py:249-256` (`CAPABILITY_KEYS`, six booleans) | Everything outside the six booleans still comes from the TRADES row keyed by `vertical_template`. That includes the booking noun ("a site visit"), the caution line, the agent names "Receptionist" and "Lead follow-up", the topics line, and the `capture` line (`starters.py:171-283`). A Rytu Khata filed as `custom` reads "what you offer, prices, timings or location" (`starters.py:276`) whenever it is not judged `books=False`. | Generate these as copy fields: an agent-name suggestion, a caution, a topics line and a capture line. Keep TRADES only as a few-shot seed for that run. | Rule 1 |

### G2. Per-trade tables still serving a business

| ID | Sev | Where | Who sees it / what is wrong for another trade | Dynamic source |
|---|---|---|---|---|
| G2-1 | P2 | `web/lib/verticalExamples.ts:118-270` `BY_VERTICAL`, merged by `withGeneratedCopy` (`:352-363`) | Owners see the type's example text until the copy lands, and forever if it never does: "Sunrise Clinic", "2 BHK units in Gachibowli start at ₹85 lakh", "green chilli for Saturday", "bridal makeup". A retail-filed app reads grocery placeholders. | Use `GeneratedCopy.placeholders`. Before it lands, use `NEUTRAL_UNTIL_GENERATED`-style neutral text for every key, not the type row. |
| G2-2 | P2 | `agents/starters.py:171-283` TRADES (booking, caution, `receptionist_name`, `caller_name`, topics); `:382` tone "like a helpful person at the front desk" | Callers hear starter scripts written for a front desk. For a support agent, an outbound agent or an app, "front desk" and "Receptionist" are wrong. | Generate the agent name, tone and caution per agent (G1-2, G1-3). |
| G2-3 | P2 | `agents/trade_playbooks.py:150` ("How much does it cost?"), `:405-417` NEUTRAL_TRADE ("Can you just tell me the price?"), TRADE_WORDS per type | Unjudged agents get a price objection whether or not the business quotes prices. | Use `GeneratedCopy.objections`, or none. |
| G2-4 | P2 | `scripts/seed.py:135-~430` VERTICAL_TEMPLATES (e.g. `:198-272` real-estate "crore", "BHK", "ఐదు బెడ్ రూమ్స్" rules); applied at account and agent creation (`agents/lead_fields.py:7-12`) | Every call is extracted against the type's template fields until the owner reviews the AI draft. A business filed under the wrong type captures the wrong fields. | Apply the AI draft automatically. Keep the template only as the draft's seed (as the docstring already says) and never write it to the agent. |
| G2-5 | P3 | `first_run/questions.py:~100-157` TRADE_CHOICES ("Groceries…", "New vehicles…") | Owners see first-run chip options from a fixed menu. A custom business gets none. | Use `GeneratedCopy.caller_details` or offer chips, or the model's question run. |
| G2-6 | P3 | `web/lib/businessTypes.ts:26-38` hints ("preferred doctor", "Budget, locality, size, site visit") | The signup and admin type picker. This is acceptable as a picker, but the hints restate per-type fields. | Keep the picker as a seed. Drop the field hints. |
| G2-7 | P2 | `spoken_style.json` `languages.te-IN.openings.test_call` = "…ఇది మీ కొత్త రిసెప్షనిస్ట్ టెస్ట్ కాల్…" (also `_introduced`) | Every owner's test call announces "your new receptionist", including outbound and support agents. Founder-owned data, so the founder must reword it. | Founder rewords it in the data file. Phase 2 must not hand-write it. |
| G2-8 | P2 | `agents/specimen_scenarios.py` per-type Telugu and Hindi lines (`:75-105` "ఒక కేజీ powder కావాలి", "రేపు doctor ని చూపించుకోవాలి"; `:257` "two of them, to Guntur"; `:387` "I already got it somewhere else") | Practice callers are drawn from a type table. Non-type businesses get shop lines while unjudged. | Use the copy's `example_questions` and `objections` in the call language, written by the model (as the AI-written callers already are). |
| G2-9 | P3 | `web .../lead-sources/AddSourceDrawer.tsx:41`, `sourceKinds.ts:12-39` ("99acres, MagicBricks, Housing.com") | Every owner sees property portals as the example. | List the portals the server supports. The hint should come from the business's type or copy, or stay neutral ("Your portal or CRM"). |

### G3. Fixed example sentences in model prompts (every tenant)

| ID | Sev | Where | What is wrong | Fix |
|---|---|---|---|---|
| G3-1 | **P1** | `packages/shared/src/calevate_shared/extraction.py:757-758`: `headline … e.g. "Asked if chilli is in stock; wants a call back today"` | Every call of every business is summarised under a grocery example. The headline is what owners scan in Calls, so a support call is nudged toward shop phrasing. The earlier map listed this as "Low". It is in the extraction prompt of every call. | A structural example with no trade ("Asked <what>; wants <next step>"), or the business's own `example_questions[0]`. |
| G3-2 | **P1** | `calevate_shared/lead_fields.py:49-55`: core field `need` reason "(for example 'two kilos of green chilli', …)". This becomes the JSON-schema `description` sent to the extraction model (`apps/workers/extraction.py:603-604`) and the prompt hint (`calevate_shared/extraction.py:744`). | The core field is composed into **every** agent's spec, so every business's "What they want" is extracted with a chilli example. | Remove the trade example, or fill it from the business's copy at spec build. |
| G3-3 | P2 | `agents/call_rules.py:107` ("two kg or two packets?"), `:122` ("one kg, or more?") | Judge text read on every practice run of every business. It biases the judge toward quantity and order shapes. | Use neutral wording ("an amount that was unclear"). |
| G3-4 | P2 | `workers/script_assist.py:146` (identity example "a shop: products, prices, orders and delivery"), `:151` (Telugu examples "ఆర్డర్, డెలివరీ, బుకింగ్") | The script writer's only worked example is a shop. | Use the business's own `agent_role` and `business_line` from the copy. Any example words should come from `spoken_style.json` `word_swaps`. |
| G3-5 | P3 | `copilot/campaign_actions.py:85` ("e.g. book a visit") | Pip's campaign tool description. | Use the copy's `call_goal`. |
| G3-6 | P3 | `workers/caller_memory_distil.py:209` ("AI receptionist"), `workers/teach_questions.py:50` ("a receptionist could say"), `workers/agent_test_ai.py:415` ("a busy shop owner"), `workers/caller_help.py:76` ("A receptionist…") | The framing assumes inbound reception and a shop. | Say "the business's AI agent" and "the owner". |

### G4. Hand-written Telugu, Hindi and other languages in code (founder rule 2)

| ID | Sev | Where | What is wrong | Dynamic source |
|---|---|---|---|---|
| G4-1 | **P1** | `agents/handoff.py:187-189`: `"te-IN": "Sare, nenu ippudu maa team lo okarini kaluputunnanu. Konchem wait cheyandi."`, and Hindi in Latin letters. This is sent as ThinnestAI `handOver.line` (`engine/thinnest.py:2615-2624`, via `spoken_line_for` `handoff.py:393-400`). | Every Telugu and Hindi caller who is transferred hears a romanised line. By D-745 and `disclosure.py:155-158`, "a Telugu or Hindi sentence in Latin letters is read by the voice as if it were English". The staged languages are in native script; the two live ones are not. It is also hand-written, not from the founder's data file. | Move the line to `spoken_style.json` (founder-owned, native script, marked for review). Read it per language. |
| G4-2 | P2 | `compliance/disclosure.py:178-203` (AI and recording sentences, founder-worded "as the founder wrote them"), `compliance/privacy_notice.py:67-76` ("machine-drafted"), `whatsapp/templates.py:98-140` (Telugu and Hindi template bodies) | The founder-owned wording lives in Python. The privacy notice and WhatsApp bodies were machine-drafted by an agent. An edit needs a code release, and nothing records who approved each line. | One founder-owned language data file (like `spoken_style.json`), with `review` / `reviewed_by` per string. Code reads it. |
| G4-3 | P2 | `agents/test_conversations.py` standard callers (e.g. `:365` "మీ దగ్గర ఏం ఏం ఉన్నాయి?"), `agents/specimen_scenarios.py:75-105` | Telugu and Hindi practice caller lines were hand-written in code. | Write them with the model for the business (as `agent_test_ai` does), or put them in the founder data file. |
| G4-4 | P2 | `web .../agents/[agentId]/script/ScriptSections.tsx:320` "Namaskaram andi, cheppandi, em kavali?", `:331` "Namaskaram andi, mee enquiry gurinchi.", `:423` "andi and garu" | Every owner sees romanised Telugu placeholders whatever the agent's language. They are Latin letters, the shape D-745 forbids for spoken lines. The outbound one assumes an enquiry, which is the claim the founder removed from Rytu Khata (`agents/retired_lines.py:5-8`). | Use the copy's `starter_lines` or `outbound_purpose` in the agent's language. Otherwise use `spoken_style.json` `openings[lang]`. |
| G4-5 | P2 | `agents/turn_checks.py` (≈228 Indic lines: `_LABEL`, `_QUANTITY`, `_ORDER_ENDING`, `_FILLER`, `_TE_WH_*`, `_HI_WH`, `_TE_NUMBER`, `_HI_NUMBER`, `_NATIVE_PRICE`, `_DANGLING`…); retail units "kg, packets, bags, bottles, కిలో, కేజీ, ప్యాకెట్" (`:220-224`, `:418-420`) | The language rules were hand-written in code, with shop units baked into the "caller's part" and "unit supplied" checks. A Telugu sentence about acres, tickets or EMIs is judged by kilo and packet rules. | Language data in a founder-owned file (`spoken_style.json` `language_pack` already exists per language). Units should come from the business's own offers. |
| G4-6 | P3 | `agents/script_lint.py:147-172`, `calevate_shared/opening_notices.py:27-31`, `calevate_shared/spoken_guard.py:158-166`, `teach/questions.py:76-84`, `copilot/agent_setup_actions.py:1027-1033`, `workers/call_language.py:104-110` | These are small detection word lists for te and hi. They are acceptable as detectors, but they are hand-typed and scattered across six modules. | Consolidate them in one language-pack data file, read by each detector. |
| (kept) | — | `agents/retired_lines.py` (118 lines) | Detection-only and never spoken (`:22-23`). This is not a finding. | — |

### G5. English-, Telugu- or Hindi-only heuristics that silently fail

| ID | Sev | Where | What happens | Should |
|---|---|---|---|---|
| G5-1 | **P1** | `agents/test_conversations.py:376-384` (`_NEUTRAL_ASK`, `_NEUTRAL_VAGUE`, `_NEUTRAL_PRICE` are English only; `_in` falls back to English) | A business that takes no orders or quotes no prices, which is Rytu Khata's shape, gets **English** standard practice callers for its Telugu agent. The practice run then tests a language the agent does not use, and a pass means nothing. | Write the neutral callers in the agent's language with the model, or get them from the founder file. Never fall back to English silently. If a language has no lines, say "not tested in Telugu". |
| G5-2 | **P1 (latent)** | `compliance/optout.py:300-356` (patterns for en, romanised te/hi, and a small native te/hi set only); `agents/languages.py:123-150` `StagedLanguageReadiness.missing()` | Enabling ta, kn, ml or mr needs only sentence review, a test call and the vendor's word. Opt-out detection for that language is not required. A Tamil caller's "don't call me" would never reach the DNC ledger. | Add "opt-out phrases recorded for this language" to the readiness gate. Source the phrases from the founder data file. |
| G5-3 | P2 | `compliance/call_purpose.py:52` `Language = Literal["en","hi","te"]`, lists `:180-214` | The promo lint reports `clear` for a Tamil or Kannada script full of "தள்ளுபடி". That is a truthful-UI problem on a launch gate. | Report "not checked in <language>" (a `check` verdict) for an unsupported language. Lists come from the data file. |
| G5-4 | P2 | `insights/detection.py:150-206` topic keywords (English plus romanised: "unda", "ekkada", "kahan"…); `retrieval/routing.py:80-243` | Telugu- or Devanagari-script transcripts never match a topic or route. The gap falls to the phrase fallback and the fixed topic menu ("Availability & stock", "Offers & discounts") is never filled. Which script ThinnestAI's STT writes is UNVERIFIED here. `optout.py:339-341` says code-mixed native script occurs. | Classify topics with the model inside the existing post-call pass, or add native-script lists from the data file. Generate topic labels per business from `example_questions`. |
| G5-5 | P2 | `agents/turn_checks.py` `_SCRIPT_OF` covers six scripts, but the word rules cover te/hi only | Staged languages get the symbol rules only. Practice verdicts are silently weaker. | Report which checks ran for the language. |
| G5-6 | P3 | `teach/questions.py:76-84` hours and address regex (partial te/hi) | Answered topics are missed in other scripts, so owners are re-asked. | Same as G5-4. |
| G5-7 | P3 | `workers/extraction.py:1149-1290` `OfflineExtractor` (romanised Telugu negation and name lists); `:1193` English-only `_NEGATIVE` sentiment | Local and CI only (`get_extractor`, `:1493-1517`). This is not production. | No action needed. Noted for completeness. |

### G6. Sales words on client screens that ignore `caller_words`

The server has `tenancy/caller_words.py` and the web has `callersWord`. These strings use neither.

| ID | Sev | Where | Text | Should read |
|---|---|---|---|---|
| G6-1 | P2 | `web .../c/[slug]/_ui/copy.ts:20` → `NextSteps.tsx:352` | "N hot leads to call back" | The caller noun when `sells === false` ("2 interested users"). |
| G6-2 | P2 | `web .../attention/rows.tsx:23` | "Hot lead" | same |
| G6-3 | P2 | `web .../leads/LeadTable.tsx:116` | "new hot leads arrived" | same |
| G6-4 | P2 | `web .../settings/alerts/AlertsScreen.tsx:63,74,116,121,122`; `TeamList.tsx:4` | "Who hears about hot leads", "once per hot lead" | same |
| G6-5 | P3 | `web .../campaigns/CampaignResults.tsx:216` | "hot leads first" | same |
| G6-6 | P2 | `apps/api/copilot/notes.py:464` | Pip note "hot leads have waited" | `caller_words_for` |
| G6-7 | P2 | `web .../knowledge/TeachBox.tsx:48` STARTERS "Our prices: ", `:157` placeholder "Prices, timings, where you deliver…" | A business that quotes no prices and delivers nothing is invited to teach prices and delivery. | Gate on `quotesPrices`, `takesOrders` and `hasPremises`. Otherwise use the copy's `teach_note` sentences, which already exist (`exampleSentences`). |
| G6-8 | P3 | `web .../calls/[callId]/InsightsCard.tsx:21` "Promised to pay", `:29-57` "Price", "Delivery", "Visit" | Labels for moment kinds that the server already withholds when the business is judged not to sell. A stale call still shows them. | Map through `interest_moments_label`. |
| G6-9 | P3 | `web .../calls/CallAgain.tsx:43` hint "an enquiry or a booking"; `lib/firstAgent.ts:100,103` "customers ring"; `agents/first/HearItStep.tsx:594` "like a customer would" | Assumes customers and bookings. | `callersWord(...)`. |

### G7. Language defaults: one problem solved five ways

| ID | Sev | Where | What | Should |
|---|---|---|---|---|
| G7-1 | P3 | `calevate_shared/engine.py:3002` `DEFAULT_PRIMARY_LANGUAGE="te-IN"`; `agents/models.py:532` `server_default="te-IN"`; `agents/starters.py:92` `STARTER_LANGUAGE`; `web/lib/businessCapabilities.ts:108` `FALLBACK_LANGUAGE`; but `agents/handoff.py:178` falls back to **English** | Five constants for "what language when we do not know". The handover line disagrees with the rest. A Hindi-first or English-first business gets Telugu wherever its profile language is not threaded. | One accessor, "the business's first language (`profile.languages[0]`) else the platform default". The platform default becomes a console setting. Hard rule: one way per problem. |

### G8. Fixed money and time values in code

| ID | Sev | Where | What | Should |
|---|---|---|---|---|
| G8-1 | P2 | `billing/ai_quota.py:372` `AI_OVERAGE_BLOCK_INR = 500`. The comment at `:365-371` says "the size of the block … is a PRICE, and a price is the founder's". | A client-facing price is set in code. | A console setting (Ops → pricing), like `platform_fee_inr`. |
| G8-2 | P3 | `billing/auto_recharge.py:108-110` defaults ₹500 / ₹2,000 / ₹6,000 ("the founder's examples") | Prefilled defaults for every client. | A console setting, or derive them from the client's 14-day usage (`_USAGE_WINDOW_DAYS` already exists there). |
| G8-3 | P3 | `web .../billing/WhatCallsCost.tsx:118` "30-second steps · missed calls free" | Restates the server's `PULSE_SECONDS` (`billing/engine_minutes.py:103`) as literal copy. If the pulse changes, the screen is wrong. | Read the pulse from the packs card the panel already loads. |
| (kept) | — | `billing/ai_quota.py:385` `PLATFORM_AI_BRAKE_INR` | Deliberately a code constant (`:377-384`: no button by design). This is not a finding. | — |

### G9. No guard keeps other trades' words or hand-written Indic text out

| ID | Sev | Where | What | Should |
|---|---|---|---|---|
| G9-1 | P2 | `tests/clinic_words_guard_test.py:1-30` guards clinic words only. Nothing guards retail, real-estate or other trade words, or Indic script in `.py` and `.tsx`. | This is why G3-1 and G3-2 (chilli), G2-9 (property portals) and G4-1 and G4-4 (romanised Telugu) survived three cleanup lanes. | Generalise it into a trade-words guard over string literals that reach a person or a model, with a per-file allowlist and a reason. Add an Indic-literal guard that allows only data files and named detector modules. |

### G10. Provider names on client screens

I found none in `apps/web/src/app/c/**` string literals. The search was for ThinnestAI, Thinnest,
Gemini, Sarvam, Cartesia, Azure, OpenAI, Exotel, Plivo, Twilio, Deepgram, ElevenLabs and
Razorpay. Razorpay appears only as the client's **own** connected account
(`agents/actions/KindFields.tsx:488`, `integrations/ConnectedAccounts.tsx:82-83`) and as checkout,
which is acceptable. I did not check server-sent problem `detail` strings at runtime. They are
covered by `tests/vendor_error_message_test.py`, which I did not run.

## 3. Research notes

- Structured output: the capability judgement already cites its sources in the `6114cd7ef`
  commit body (Gemini structured-output docs, read 5 Nov 2026, and arXiv:2610.12056). I did not
  re-read them this session, and nothing here depends on them.
- The standard pattern for multi-tenant SaaS copy is to keep tenant-specific strings out of code
  and serve them from tenant data, with a neutral platform default. The finding that matters here
  is G1-1: Calevate's default is not neutral, it is "a selling business that books". I did not
  run a web search for this lane. The finding rests on the code, not on an external standard.

## 4. Proposed fixes (phase-2 groups that do not share files)

1. **Neutral unknown and per-agent job** (G1-1, G1-2, G1-3). Files: `tenancy/business_copy.py`
   (`Capabilities.unknown` semantics), `agents/business_fit.py` (add the agent's job),
   `tenancy/caller_words.py`, `web/lib/businessCapabilities.ts`, `workers/business_copy.py`
   (new fields: agent name, caution, topics, capture). Add a "still learning" state on the admin
   and client screens. This group goes first, because every other group reads it.
2. **Prompt examples** (G3-1 to G3-6). Files: `calevate_shared/extraction.py`,
   `calevate_shared/lead_fields.py`, `agents/call_rules.py`, `workers/script_assist.py`,
   `copilot/campaign_actions.py`, `workers/caller_memory_distil.py`,
   `workers/teach_questions.py`, `workers/agent_test_ai.py`, `workers/caller_help.py`. This is
   small and can ship first. Bump `PROMPT_VERSION` wherever a version exists.
3. **Founder language data file** (G4-1, G4-2, G4-3, G4-5, G4-6, G5-2, G5-3, G5-5). Create one
   file next to `spoken_style.json` (or extend its `language_pack`) holding the handover lines,
   notices, WhatsApp bodies, practice lines, opt-out phrases, promo words and turn-check word
   sets, each with `review` and `reviewed_by`. Files: `agents/handoff.py`,
   `compliance/disclosure.py`, `compliance/privacy_notice.py`, `whatsapp/templates.py`,
   `compliance/optout.py`, `compliance/call_purpose.py`, `agents/turn_checks.py`,
   `agents/script_lint.py`, `agents/languages.py` (readiness gate),
   `calevate_shared/spoken_style.py`. The founder supplies the native-script handover line for
   G4-1. Phase 2 must not write it.
4. **Practice callers** (G2-8, G4-3, G5-1). Files: `agents/test_conversations.py`,
   `agents/specimen_scenarios.py`, `workers/agent_test_ai.py`.
5. **Type tables become seeds only** (G2-1 to G2-6, G2-9). Files: `web/lib/verticalExamples.ts`,
   `agents/starters.py`, `agents/trade_playbooks.py`, `scripts/seed.py` plus
   `agents/lead_fields.py` (apply the draft automatically), `first_run/questions.py`,
   `web/lib/businessTypes.ts`, `web .../lead-sources/AddSourceDrawer.tsx`.
6. **Topic and routing language** (G5-4, G5-6). Files: `insights/detection.py`,
   `retrieval/routing.py`, `teach/questions.py`, and the extraction pass if topics move to the
   model.
7. **Client words** (G6-*, G4-4). Files: `web .../_ui/copy.ts`, `NextSteps.tsx`,
   `attention/rows.tsx`, `leads/LeadTable.tsx`, `settings/alerts/*`,
   `campaigns/CampaignResults.tsx`, `knowledge/TeachBox.tsx`, `calls/[callId]/InsightsCard.tsx`,
   `calls/CallAgain.tsx`, `lib/firstAgent.ts`, `agents/first/HearItStep.tsx`,
   `agents/[agentId]/script/ScriptSections.tsx`, `apps/api/copilot/notes.py`.
8. **Language default and money** (G7-1, G8-*). Files: `calevate_shared/engine.py`,
   `agents/models.py` (a migration only if the server default changes), `agents/starters.py`,
   `agents/handoff.py`, `web/lib/businessCapabilities.ts`, `billing/ai_quota.py`,
   `billing/auto_recharge.py`, `core/platform_config` plus `ops/config_catalog.py`,
   `web .../billing/WhatCallsCost.tsx`.
9. **Guards** (G9-1). Files: `tests/clinic_words_guard_test.py` (generalise it) and a new Indic
   literal guard. Land this last, so it locks in groups 2 to 7.

## Appendix: sweeps run

- Indic script: `grep -rlP "[\x{0C00}-\x{0C7F}]|[\x{0900}-\x{097F}]"` over apps, packages and
  scripts (with `LC_ALL=C.UTF-8`). That gave 60 source files, which I classified file by file
  above.
- Trade words in web literals: clinic, doctor, patient, BHK, site visit, chilli, crop, farmer,
  salon, kirana, MagicBricks, Guntur, appointment, and similar.
- Trade words in backend: chilli, kilo, kg, packet, stock, BHK, bedroom, lakh, crore, haircut,
  salon, farmer, crop, vehicle.
- Prompt examples: `(for example|e.g.|such as|like) … <trade word>` over workers, copilot,
  agents, teach, first_run, kb and shared.
- Romanised Telugu and Hindi: `andi|kavali|ledu|undi|unda|cheppandi|vaddu|haan|nahi|theek|…`.
- Provider names over `apps/web/src/app/c`.
- `Final` numeric constants named MAX, LIMIT, DAYS, INR or RATE over the business modules.
- `₹` and "N days" literals in client web code.
- The earlier map's quoted phrases, each re-checked by `rg`.

Note: "patient caller" (`agents/patient_caller.py`, `components/patientCallerRow.tsx`) is the
"Give callers time" preset for slow callers, not a medical term. It is not a finding.
