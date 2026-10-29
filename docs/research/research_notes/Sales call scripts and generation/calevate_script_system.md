# Calevate's own script and prompt system (repository state, 30 Oct 2026)

Read-only code and doc reading at HEAD `6d2576d90`. Nothing was run. Line numbers are from that tree. "Not found" means a targeted grep found nothing. It does not prove the thing is absent everywhere.

## 1. How a script is generated (inputs, per-trade plans, writer prompt, validation)

### Takeaway
A script is a structured `CallScript` (v2). It comes from one of two places: a starter (job x trade), or the AI script writer. Both read one per-trade step plan (`trade_playbooks.py`, D-856). The writer gets a brief, the five owner answers, the spoken-style guide and the step plan. It returns strict JSON. Code then checks it against the same rules the practice judge uses, and allows one repair round.

### Cited Findings
- **Script model.** `CallScript` has these fields: `opening_line` and `outbound_opening_line` (≤1000 each), `business_line` (≤200), `identity`, `goal`, `outbound_purpose` (≤300), `style` (tone, address form, code_mix, sample phrases, pronunciations), `stages` (≤12), `objections` (≤30, each objection ≤300 chars and response ≤1000), `policies` (`offer_call_backs`, `share_prices`, `take_bookings`, all default True), `ending`, `example_exchange` (≤20), `adherence` (`flexible` or `strict`), and `raw_override` (≤20,000, the raw escape hatch). It is either raw or structured, never both — [call_script.py:575-700](packages/shared/src/calevate_shared/call_script.py)
- **Strictness has two levels.** "flexible" means "Sections in order as a guide. Follow the caller if they jump ahead". "strict" means "Go through the sections in this order and say the quoted lines as written" — [call_script.py:764-768](packages/shared/src/calevate_shared/call_script.py). The founder kept two levels on 23 Oct 2026 — rememory decision f25e3e68
- **The compiler (`_compile_v2`)** writes these sections in this order, leaving out any that are empty: [BUSINESS], [IDENTITY], [GOAL] (plus "On calls you place, say early why you call: {outbound_purpose}"), [OPENING], [OPENING ON CALLS YOU PLACE], [SPEAKING STYLE], [CONVERSATION] (with the adherence sentence), [STEP BY STEP], [WHAT TO COLLECT] "Only these, when it fits.", [OBJECTIONS] "In this spirit, in your own words." (Q/A pairs), [POLICIES], [ENDING], [QUICK FACTS] "These win over anything in your knowledge.", and [EXAMPLE CALL] "Copy the style, never the facts or the Caller lines." Any section holding a `{{variable}}` is moved to the end for the prefix cache (D-835) — [call_script.py:927-1062](packages/shared/src/calevate_shared/call_script.py)
- **What policies compile to.** `share_prices=False` becomes "Do not quote prices…". `take_bookings=False` becomes "Do not make a booking yourself. Note what they want and when it suits them." `offer_call_backs=False` becomes "Do not offer call backs." — [call_script.py:1003-1012](packages/shared/src/calevate_shared/call_script.py)
- **Per-trade step plans (D-856).** `trade_playbooks.py` is "the step plan the starters and the script writer share". `TRADE_WORDS` covers clinic, real_estate, insurance, education, retail, local_services and automobile, with `custom` as the neutral fallback. `JOB_SHAPES` covers `answer_calls`, `call_new_leads` and `call_leads` — [trade_playbooks.py:1-30, 279-292](apps/api/agents/trade_playbooks.py)
- **The outbound (`call_leads`) plan has five steps:**
  1. Check it is a good time. "Your opening asked if they can talk now… Never push."
  2. Say why you called. Confirm the right person, then give `words.reason` in one line.
  3. Find out what they need, one detail at a time.
  4. Offer {booking} "with two times to choose from. If not, thank them and end the call. Do not push or repeat the offer."
  5. Confirm and close.

  — [trade_playbooks.py:201-246](apps/api/agents/trade_playbooks.py)
- **The answer-calls plan has five steps:** find the need, answer from the facts, take details, offer {booking} "offer two times to choose from", then confirm and close — [trade_playbooks.py:164-198](apps/api/agents/trade_playbooks.py)
- **Shared close line.** The English is "Alright, I'll pass this to the team and they'll confirm it. Anything else?" (te, hi and en versions exist). The close instruction is "Read back what they asked for and any time agreed, then close." — [trade_playbooks.py:119-132](apps/api/agents/trade_playbooks.py)
- **Objections per job.** The answer job has "just want the price" and "I'll think about it". `call_leads` has "Where did you get my number?", "Just send it on WhatsApp" (the response says the team will send it and "Never say it was sent") and "already bought elsewhere". Each trade adds one more objection — [trade_playbooks.py:134-161, 265-276](apps/api/agents/trade_playbooks.py)
- **Example lines carry no business facts.** They state "no price, stock, time or address". They are "AI-drafted and wait for a native speaker's review", and `tests/trade_playbooks_test.py` checks them — [trade_playbooks.py:17-23](apps/api/agents/trade_playbooks.py)
- **What the writer reads.** `playbook_guidance(trade, direction, language)` renders "Step plan for this kind of business…", each step's "Done when" and "Sounds like", the objections, and the line "Adapt the plan to what the owner told you… never text to copy word for word" — [trade_playbooks.py:699-731](apps/api/agents/trade_playbooks.py)
- **Starters.** A starter is a job plus a trade. `Starter.call_script` builds `CallScript` v2 from the plan's steps, with ids `s1..sN` and the done-when as the branch. The tone is fixed to "Warm, calm and brief, like a helpful person at the front desk." Starters must not contain business facts, disclosure, recording, truthful-answer or confidentiality wording, or vendor names. Outbound starters "take no for an answer" — [starters.py:1-38, 338-386](apps/api/agents/starters.py). The `call_leads` starter's goal is "Find out whether they are still interested and, if they are, arrange {booking}. Take no for an answer." — [starters.py:449-473](apps/api/agents/starters.py)
- **Starter greeting.** The greeting comes from `spoken_style.json` openings for the language (`opening_in`), with an English template as fallback — [starters.py:338-346](apps/api/agents/starters.py)
- **Writer inputs (`ScriptBrief`):**
  - business name, agent name, business type, direction and language;
  - the register or the full spoken-style guide (`generation_guidance`);
  - the details to collect and the knowledge titles;
  - the five owner answers: "What do you sell or do?", "Who calls you, or who will the agent call?", "What should a good call end with?", "What do callers ask most often?", "Anything the agent must never say or promise?";
  - `introduced` (D-865).

  — [script_assist.py:477-551](apps/workers/script_assist.py)
- **Writer system instruction (`_SYSTEM_INSTRUCTION`).** Instructions are in English and spoken lines in the call language's own script. It embeds `writer_rules()`. It says: "Do not write anything about being an AI, about recording, about call backs or transfers, or about do-not-call requests: the platform adds those rules itself". It also asks for 3-6 stages, each with `sounds_like`; 2-5 objections; and 3-6 sample phrases. For agents that place calls, `outbound_purpose` is one sentence and a stage confirms it is a good time and the right person — [script_assist.py:121-162](apps/workers/script_assist.py)
- **Plan only on new drafts.** The step plan is appended only to a NEW draft, not to a conversion or an edit — [script_assist.py:1285-1290](apps/workers/script_assist.py). Conversion (`CONVERT_INSTRUCTION`) keeps the owner's sentences word for word, and edit (`EDIT_INSTRUCTION`) makes one change — [script_assist.py:166-206](apps/workers/script_assist.py)
- **Writer rules (`call_rules.CALL_RULES`, D-849).** One record per rule, with separate phrasings for the judge, the writer and the expectations:
  - `facts`: "Never invent prices, stock, hours, addresses…";
  - `done`: "No line or step says an order or booking is placed… it takes the details for the team to confirm";
  - `said_before`;
  - `ask_once`;
  - `own_part`;
  - `let_go`: "An unsure caller gets one short offer at most, then a polite close".

  `OPENING_LINE_RULE` is greet, name the business and one short question, ≤120 characters, "no list of products, no offer, and no AI or recording notice". If introduced, there is no greeting and no names — [call_rules.py:24-176](apps/api/agents/call_rules.py)
- **Validation and repair.** `language_problems` checks each line in turn:
  - `english_problem`: instructions must not be in an Indic script;
  - `textbook_problem`;
  - `provider_problem` (D-679);
  - `said_line_problem`: a done-claim, "as I said", or an opening over 120 chars;
  - `latin_word_problem` and `introduced_opening_problem`, on openings only.

  — [script_assist.py:279-341](apps/workers/script_assist.py); [call_rules.py:179-200](apps/api/agents/call_rules.py). A failure triggers one `REPAIR_NOTE` round. If that still fails, the result is `assist_answer_unusable` — [script_assist.py:983-995, 1166](apps/workers/script_assist.py)
- **Delivery.** Pip proposals (`script_proposals.py`, D-820) and knowledge-file suggestions (D-923) both write through `draft_script`. A proposal is kept part by part into the draft and never reaches a call directly — [script_proposals.py:1-23](apps/api/agents/script_proposals.py)

### Inferences
- The step plans have no explicit "value line" step (a benefit statement before qualifying) and no "two-choice close" step. The two-choice pattern exists only inside the "Offer {booking}" step, as "two times to choose from".
- The writer can only produce objection responses that obey `let_go` (one offer, then close). This limits how persuasive any objection handling can be.

### Gaps
- Which model writes scripts is not consistent in the sources. The `script_assist.py` docstring says "Azure preferred, Sarvam disclosed-fallback" (lines 11-16). CLAUDE.md (D-899) and `agent_test_ai.py:6-8` say the account's own Gemini comes first. The docstring looks stale. The leg ordering in `ask_json` was not read.
- JSON copy/paste import/export of scripts (founder YES, 23 Oct 2026, memory f25e3e68) was not found in `apps/web/src/lib/api/script.ts`. Its status is unverified.

## 2. How the final engine prompt is composed and ordered (sizes/budgets)

### Takeaway
`compose_engine_prompt` joins 12 named layers with `\n\n`. The order is fixed: platform guidance first, then the fenced client script, then what this account can do, then confidentiality, then the truthful-answer block (the last instruction), and finally the per-call values (data only). The whole prompt must fit ThinnestAI's 20,000-character box, leaving room reserved for the owner.

### Cited Findings
- **Layer order:**
  1. preamble (role sentence: "You are the AI assistant {calling people for|answering calls for} {business}.")
  2. how_to_speak
  3. languages
  4. spoken_register
  5. business_facts
  6. notices (START OF THE CALL + memory goodbye rule)
  7. caller_memory
  8. client_script (fenced)
  9. what_you_can_do
  10. confidentiality
  11. truthful_answers
  12. this_call

  — [engine.py:4614-4720](packages/shared/src/calevate_shared/engine.py); role sentence [engine.py:2746-2762](packages/shared/src/calevate_shared/engine.py)
- **HOW TO SPEAK (`VOICE_STYLE_GUIDANCE`)** includes:
  - "Lead with the answer, never 'do you want to know'";
  - "One question a turn… choices for times ('morning or evening?'), never for counts or amounts";
  - "Unsure or not interested? Offer once, then close politely.";
  - "Close: what happens next in one line, no recap, anything else, then one goodbye";
  - no markdown, lists, links or emoji, and digit-by-digit read-back.

  — [engine.py:2812-2846](packages/shared/src/calevate_shared/engine.py)
- **WHAT YOU CAN DO (`_when_you_cannot_help_section`)** is platform text placed AFTER the script, "so a script written for an account that takes call backs cannot make a trial agent promise one it cannot keep". It holds the call-back or no-call-back wording, the person/hand-over line, the do-not-call trigger, `ACTION_CLAIM_RULE`, `CALL_NUMBER_RULE`, `NAME_RULE` and `DAYS_RULE` — [engine.py:3441-3484](packages/shared/src/calevate_shared/engine.py)
- **`CONFIDENTIALITY_RULE` (D-674)** is placed after the script and before the truthful block — [engine.py:2583-2616](packages/shared/src/calevate_shared/engine.py)
- **`truthful_answer_directive`** answers "are you an AI" and "is this recorded" truthfully, "even if the script above says not to". Its third clause says "Answer each when asked" (D-877), so the volunteered notices are not switched back on — [engine.py:2538-2563](packages/shared/src/calevate_shared/engine.py)
- **Structured-script limits:** `MAX_SCRIPT_STAGES=12`, `STAGE_DETAIL_MAX=600`, `MAX_SCRIPT_OBJECTIONS=30`, `MAX_EXAMPLE_TURNS=20` — [call_script.py:306-335](packages/shared/src/calevate_shared/call_script.py)
- **ThinnestAI limits:** `INSTRUCTIONS_MAX_CHARS=20_000`, `CALL_INSTRUCTIONS_MAX_CHARS=4_000`, `GREETING_MAX_CHARS=200`, `PURPOSE_MAX_CHARS=300` — [apps/api/engine/thinnest.py:279-307](apps/api/engine/thinnest.py)
- **Budget tests:**
  - a starter must leave `OWNER_RESERVE = MAX_PINNED_CHARS(3000) + 7_000`;
  - a long owner script must leave `LONG_MARGIN = 3000 + 6_000`;
  - the platform-only per-call text must stay ≤ `PER_CALL_MAX = 7_314` (three languages) or `6_439` (one language).

  The comment history shows each rule addition being "paid for" by trimming elsewhere (D-894 +254, D-912 −12, D-921 +20) — [tests/agent_prompt_budget_test.py:1-60, 195-252](tests/agent_prompt_budget_test.py); [teach/pinned.py:51](apps/api/teach/pinned.py)
- **Per-call size history.** D-856 cut what a call reads of ours from 6,250 to 5,774 (one language) and from 7,227 to 6,751 (three). The Telugu retail answer starter went from 9,204 to 9,013 — [ROADMAP.md D-856 row, line 1087](docs/ROADMAP.md)

### Inferences
- Any new platform rule, such as a sales-close or value-line rule in HOW TO SPEAK, must fit inside `PER_CALL_MAX`. Today there is single- to double-digit headroom (D-910 notes "each 5 under"). A rule in the client script or the starter instead counts against the 20,000 box, not the per-call cap.

### Gaps
- The prompt-cache share of 28-35% has no known cause (D-856 row, line 1087).

## 3. Disclosure: what exists, defaults, where the text comes from, and the founder's Telugu opener

### Takeaway
Two per-agent switches control the volunteered notices: the AI notice and the recording notice (D-163). Both default to OFF in the schema since D-669. The first-run flow switches the AI notice ON for the agent it builds (D-864). The truthful answer when asked is always locked. The founder's Telugu opener is already the stored `outbound` opening in `spoken_style.json`. When the AI notice introduces the agent, only its question half is used, after the salutation "నమస్కారం అండి," and the AI sentence.

### Cited Findings
- **Column defaults.** `ai_disclosure_enabled` and `recording_notice_enabled` are `server_default="false"`. The code comment reads "Default FALSE on both (D-669…): the founder's choice is that a call opens with the greeting only… the founder accepted that exposure while testing, to be reviewed before client traffic." There is no separate default for inbound and outbound — [agents/models.py:694-705](apps/api/agents/models.py); [ROADMAP D-669, line 906](docs/ROADMAP.md). D-163 originally shipped both as default TRUE — [ROADMAP D-163, line 507](docs/ROADMAP.md)
- **First run.** `_switch_on_ai_notice` turns the AI notice on for the first-run agent through `set_disclosure_posture` (D-864). The recording notice is "left as created… the owner's choice". An owner's earlier switch-off is respected — [workers/first_run.py:766-800](apps/workers/first_run.py)
- **One writer of the switches:** `publishing.set_disclosure_posture`. It checks the greeting budget (D-846) and republishes a live agent — [publishing.py:1369-1490](apps/api/agents/publishing.py); [first_run.py:772-775](apps/workers/first_run.py)
- **Campaign launch** requires that an AI sentence is on file. Whether it is volunteered is "the tenant's own decision, and never a launch blocker" — [campaigns/service.py:274-279](apps/api/campaigns/service.py)
- **Text templates:**
  - AI sentence, te-IN: "నేను {business} నుండి {name}ని, ఏఐ అసిస్టెంట్‌ని మాట్లాడుతున్నాను అండి." Hindi follows the voice's gender. en-IN is "This is the AI assistant for {business}."
  - Recording sentence, te-IN: "ఈ కాల్ రికార్డ్ అవుతుంది."
  - Both are marked NEEDS NATIVE-SPEAKER REVIEW.

  — [compliance/disclosure.py:175-200](apps/api/compliance/disclosure.py)
- **Spoken order.** `compose_opening_line` puts the AI notice first, then the recording notice. Recording is dropped if the engine does not record — [engine.py:4263-4304](packages/shared/src/calevate_shared/engine.py). `join_first_words` decides the final order. If the agent introduces itself (te/hi), the order is salutation ("నమస్కారం అండి," for te, `INTRODUCTION_SALUTATIONS`), AI sentence, opening line with its greeting stripped, then the other notices. Otherwise it is the opening line, then the notices — [engine.py:4359-4411](packages/shared/src/calevate_shared/engine.py)
- **The founder's opener is stored.** It is `spoken_style.json` te `openings.outbound`: "హాయ్ అండి, మేము {business} నుండి కాల్ చేస్తున్నాము. ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా?" Its introduced form is "ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా?" The inbound and test_call forms sit beside it — [spoken_style.json:587-594](packages/shared/src/calevate_shared/spoken_style.json). Starters use it through `opening_in` — [starters.py:345](apps/api/agents/starters.py). A "both" agent with no own outbound opening uses it through `placed_call_opening` (D-920) — [spoken_style.py:768-778](packages/shared/src/calevate_shared/spoken_style.py); [engine.py:4429-4440](packages/shared/src/calevate_shared/engine.py)
- **Composed results, as the tests expect them:**
  - AI notice on: "నమస్కారం అండి, {TE_AI} ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా? {rec}";
  - AI notice off: "హాయ్ అండి, మేము Sri Estates నుండి కాల్ చేస్తున్నాము. ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా? {rec}".

  — [tests/ai_notice_introduction_test.py:205-211](tests/ai_notice_introduction_test.py)
- **START OF THE CALL** quotes the first words as "Already said for you as your first turn". `OPENING_CONTINUES_RULE` tells the agent never to greet again, and "Asked who or why? Say both in one line, then your first question" — [engine.py:4497-4542](packages/shared/src/calevate_shared/engine.py)
- **Writer and starters stay silent on disclosure.** Both are forbidden to write AI or recording wording — [script_assist.py:144-147](apps/workers/script_assist.py); [starters.py:21-23](apps/api/agents/starters.py)
- **Memory notice.** The memory sentence (D-507) is said with the goodbye, not in the opening (D-865) — [engine.py:4340-4357](packages/shared/src/calevate_shared/engine.py)
- **Founder decision of 30 Oct 2026.** "volunteered AI disclosure becomes the DEFAULT for outbound agents (per-agent toggle D-163 stays…)". This comes with a value line and a two-choice close that "never promises anything the client has not given us", and the instruction to research first. Status: decided, not built — rememory 518ac2e3

### Inferences
- With the AI notice on in Telugu, the founder's "హాయ్ అండి, మేము {business} నుండి కాల్ చేస్తున్నాము" half is replaced by "నమస్కారం అండి, నేను {business} నుండి {name}ని, ఏఐ అసిస్టెంట్‌ని…". Only "ఇప్పుడు మీరు మాట్లాడగలరా, ఫ్రీయేనా?" survives. Making outbound disclosure default-on therefore changes which greeting word the founder hears ("నమస్కారం" instead of "హాయ్").
- The Telugu first turn with the introduction plus the recording notice must fit `GREETING_MAX_CHARS=200`.

### Gaps
- No outbound-specific default exists anywhere in schema or code today (`models.py` has one server default for all directions). The 30 Oct decision has no D-number row in ROADMAP (latest rows seen: D-939).

## 4. Does the agent get today's date and weekday in IST?

### Takeaway
Yes, since D-888. The last prompt section, THIS CALL, carries `Today: {{today}}`, filled per call in IST as "Sunday, 25 October 2026". `DAYS_RULE` tells the agent to count days from it.

### Cited Findings
- **The value.** `TODAY_LINE = "Today: {{today}}"`. `today_value(now)` gives the IST wall-clock date as "%A, D Month YYYY". An outbound call gets it as a Place Call variable (`engine/thinnest.start_outbound_call`); an inbound call gets it from the caller lookup (`worker/engine_lookups.py`) — [engine.py:3285-3298](packages/shared/src/calevate_shared/engine.py)
- **`DAYS_RULE`:** "Count days from today in THIS CALL; offer the soonest ahead, never a past one. A day that does not fit its date? Ask which." This followed a call where "tomorrow, Thursday" was said when tomorrow was Monday — [engine.py:3237-3244](packages/shared/src/calevate_shared/engine.py)
- **Other THIS CALL lines.** Every agent gets Today and Name. Placing agents also get `Number`, `Details` (list columns, ≤150 chars each) and `Why this call`. A forwarded line gets `Caller number hidden`. The section is last because ThinnestAI caches up to the first per-call value (D-814, VENDOR-STATED) — [engine.py:3264-3439](packages/shared/src/calevate_shared/engine.py)
- **Known gaps.** "a website chat and a WhatsApp chat get no lookup, so `{{today}}` is dropped there… a call whose lookup misses the vendor's 2 s still gets nothing" — [ROADMAP D-888, line 1119](docs/ROADMAP.md)
- **Time of day.** HOW TO SPEAK says "never say the time now". The prompt has no clock time, only the date — [engine.py:2829](packages/shared/src/calevate_shared/engine.py)

### Gaps
- Whether ThinnestAI's own date line exists, or which zone it uses, is undocumented (D-888 row; engine.py:3285-3291).

## 5. What prevents promises the business has not configured

### Takeaway
Several layers stop it:
- a platform rule placed after the script (`ACTION_CLAIM_RULE`);
- account-truthful call-back and hand-over lines;
- script policies;
- writer validation that rejects "done" claims;
- rule checks in practice tests.

### Cited Findings
- **`ACTION_CLAIM_RULE`:** "Never say anything is booked, fixed, confirmed or done unless a tool did it on this call or they say they did: say it is noted for the team to confirm; offer nothing no tool does. Say a tool's figure exactly, a failed one plainly." — [engine.py:3156-3161](packages/shared/src/calevate_shared/engine.py)
- **Call-backs and hand-over depend on the account.** If `callbacks_offered` is off, the text is "Never offer or book a call back". "Asked for a person with no hand-over tool: say nobody is free" — [engine.py:3441-3470](packages/shared/src/calevate_shared/engine.py)
- **Unknown facts.** `facts` rule (prompt marker "Say only what your facts or the caller said, never a guess"). The missing-fact phrasing is "the team will share that" (D-888) — [call_rules.py:35-53](apps/api/agents/call_rules.py); [engine.py:3470-3472](packages/shared/src/calevate_shared/engine.py)
- **Turn checks.** `JOB_KINDS` includes `unconfirmed_action`, `invented_source`, `false_recall` and `partial_number`. A JOB-kind failure fails a practice test — [turn_checks.py:128-139](apps/api/agents/turn_checks.py)
- **Writer and plans.** The writer's `said_line_problem` rejects lines that claim something is done — [call_rules.py:179-200](apps/api/agents/call_rules.py). The WhatsApp objection line says "Never say it was sent" — [trade_playbooks.py:155-158](apps/api/agents/trade_playbooks.py)
- **Optional facts-only line.** An optional per-agent line "answer only from these facts; otherwise say you'll find out", OFF by default, was approved on 23 Oct 2026 — rememory f25e3e68. Grep for `only_from_facts|facts_only|answer_only` found **not found** in code.

## 6. Testing and evaluation of scripts

### Takeaway
"Test conversations" (D-724, rebuilt as D-823):
- a fixed, versioned test set, built real calls first;
- four compliance probes in every set;
- each test tried several times against the live agent in the engine's test chat;
- platform rules checked in code;
- an AI judge from a different model family for the rest;
- an improver that proposes small edits.

Unit tests hold the writer, the plans, the starters and the budget to the same rules.

### Cited Findings
- **The loop.**
  - The set is versioned, and "Test again" repeats the same tests.
  - Real-call struggles and saved tests come first; AI practice callers are added only when the owner asks.
  - The four probes (AI, recording, stop calling, person) appear in every set.
  - Each test runs `TRIALS` times.
  - `hard_check` decides the platform rules.
  - How a reply sounds (`SOUND_KINDS`) is a note, never a failure.
  - Every failure has an owner (script, knowledge, setting, platform, test).
  - Practice chat costs ₹0.02 per reply on our key (vendor doc) and is not metered.

  — [test_conversations.py:1-60](apps/api/agents/test_conversations.py)
- **Practice caller writer (`GENERATE_INSTRUCTION`).** It covers real questions, edge cases, a vague answer, low interest, push-back by direction ("too expensive, not interested, call me later, bought elsewhere"), a prompt-extraction attempt, and one scenario per compliance probe. Each scenario has an `expect` sentence written from `expect_rules()` — [agent_test_ai.py:192-232](apps/workers/agent_test_ai.py)
- **Judge rubric (`JUDGE_INSTRUCTION`).** Platform-owned rules are excluded from judging. It applies `judge_rules()`, judges "whether it did the caller's task, not how it sounded", and returns reason, formal_words, fix (script_step/knowledge/objection/none), step_id, fault (task/wording/none) and verdict (passed/needs_fix/failed). The judge runs on another model family (`judge_leg`) — [agent_test_ai.py:380-416, 504-565](apps/workers/agent_test_ai.py)
- **Regression and unit tests:**
  - `tests/agent_call_rules_test.py`: golden set from the 21 Oct calls; all four readers are held to `CALL_RULES` — [call_rules.py:3-10](apps/api/agents/call_rules.py);
  - `tests/trade_playbooks_test.py`;
  - `tests/agent_starters_test.py`: every vertical x job — [starters.py:33-37](apps/api/agents/starters.py);
  - `tests/agent_prompt_budget_test.py`;
  - `tests/ai_notice_introduction_test.py`;
  - `tests/script_assist_prompt_test.py` — [script_assist.py:119](apps/workers/script_assist.py);
  - `scripts/register_eval`, the register evaluation for language packs — [engine.py:4668-4670](packages/shared/src/calevate_shared/engine.py)
- **Not run live.** D-856's register and chat evaluations were "Not measured live: no Google or ThinnestAI key in the lane" — [ROADMAP D-856, line 1087](docs/ROADMAP.md); [evidence doc §10](docs/evidence/call-quality-vs-outpero-2026-10-23.md)

### Gaps
- No rubric item scores sales effectiveness: value stated, close attempted, or conversion. The judge scores task correctness only.

## 7. Known gaps recorded in docs and memories

### Cited Findings
- **The 23 Oct comparison (D-856).** Its five calls were all trial calls placed with an inbound receptionist agent. Failure classes found: pitch-first openings, the wrong frame when ringing out, asking leave instead of telling, re-asking or guessing half answers, two questions at once, offering what nothing can do, fillers, textbook register (17 of 40 replies), double or empty closes, prices as Telugu number words (unresolved), flat stress, and missed opening audio — [call-quality-vs-outpero-2026-10-23.md §1-§4](docs/evidence/call-quality-vs-outpero-2026-10-23.md)
- **Open points from the same doc and memory:**
  - H5: Telugu-script loanwords, untested; it reverses an 11 Oct decision. Founder on 23 Oct: keep loanwords in Latin letters (rememory 7812aa59).
  - Default Telugu fillers: "TO BUILD".
  - AI-notice default: "answer pending" — rememory 7812aa59; [evidence §9](docs/evidence/call-quality-vs-outpero-2026-10-23.md)
- **Gaps from the Outpero map** (rememory a298c206, flagged SUSPECT because the sources changed since): two strictness levels only, no per-section on/off (founder: keep it that way), no JSON import/export (founder: yes), typed-only Pip (founder: yes to spoken), untyped pre-call variables (founder: yes to types), FAQ absorbed into pinned facts, and branches sent as free text.
- **Native review pending** for every trade-plan line and every te/hi notice line — [trade_playbooks.py:20-23](apps/api/agents/trade_playbooks.py); [disclosure.py:155-170](apps/api/compliance/disclosure.py)
- **From the 30 Oct comparison:** the lead name was overwritten by the agent's name (a fix lane is running); the agent stacked its next question after answering "who is this?" — rememory 518ac2e3
- **Default disclosure is OFF** pending review "before client traffic" — [models.py:694-699](apps/api/agents/models.py)

## 8. Where a value line, a two-choice close, objection handling and default-on outbound disclosure would plug in

### Cited Findings (seams that exist)
- **Value line:**
  - Step plan: the `call_leads` step 2 "Say why you called" uses `TradeWords.reason` / `reason_line` [trade_playbooks.py:215-226](apps/api/agents/trade_playbooks.py), or a new `TradeWords` field (`TradeWords` dataclass at [trade_playbooks.py:88-103](apps/api/agents/trade_playbooks.py)). A new field also needs `_trade_lines` / `ALL_LINES` [:626-642](apps/api/agents/trade_playbooks.py).
  - Script fields: `outbound_purpose`, compiled into [GOAL] as "On calls you place, say early why you call" [call_script.py:943-947](packages/shared/src/calevate_shared/call_script.py).
  - Starter text: the starter's `outbound_purpose` and `goal` [starters.py:449-500](apps/api/agents/starters.py).
  - Writer: `_SYSTEM_INSTRUCTION`'s outbound sentence [script_assist.py:147-152](apps/workers/script_assist.py).
  - Facts constraint: `facts` rule, so the value must come from owner facts.
- **Two-choice close:**
  - Step plan: "Offer {booking}" with "two times to choose from" [trade_playbooks.py:186-194, 233-241](apps/api/agents/trade_playbooks.py), `lead_offer` lines, `_CLOSE` and `_CLOSE_INSTRUCTION` [:119-132](apps/api/agents/trade_playbooks.py).
  - Platform rules: HOW TO SPEAK "choices for times" and the Close bullet [engine.py:2816-2846](packages/shared/src/calevate_shared/engine.py); `DAYS_RULE` for dates.
  - Limits: `take_bookings=False` changes it to "note what they want and when it suits them" [call_script.py:1008-1011](packages/shared/src/calevate_shared/call_script.py); `ACTION_CLAIM_RULE` means a close without a booking tool must end in "noted for the team to confirm".
- **Objection handling:**
  - Data: `CallScript.objections` (≤30) compiled as [OBJECTIONS] "In this spirit, in your own words." [call_script.py:995-1000](packages/shared/src/calevate_shared/call_script.py); plan objections per job and trade [trade_playbooks.py:134-161, 265-292](apps/api/agents/trade_playbooks.py); writer asks for "2 to 5 objections" [script_assist.py:155](apps/workers/script_assist.py).
  - Limits: `let_go` (one offer, then close) in the writer, judge and expectations [call_rules.py:121-133](apps/api/agents/call_rules.py), and HOW TO SPEAK "Offer once, then close politely" [engine.py:2822](packages/shared/src/calevate_shared/engine.py).
  - Testing: the practice-caller writer already generates objection scenarios [agent_test_ai.py:205-206](apps/workers/agent_test_ai.py).
- **Default-on outbound disclosure:**
  - Current defaults: `server_default` on `agents.ai_disclosure_enabled` [models.py:700-702](apps/api/agents/models.py), and the explicit value in `lifecycle.create_agent`'s INSERT (D-669 row: "`lifecycle.create_agent`'s INSERT, which every create path uses").
  - Writing it: the one writer `publishing.set_disclosure_posture`, which checks the greeting budget [publishing.py:1369-1490](apps/api/agents/publishing.py); the first-run `_switch_on_ai_notice` pattern [first_run.py:766-800](apps/workers/first_run.py).
  - Composition: `join_first_words` / `INTRODUCTION_SALUTATIONS` [engine.py:4359-4411](packages/shared/src/calevate_shared/engine.py); the `outbound_introduced` opening [spoken_style.json:592](packages/shared/src/calevate_shared/spoken_style.json).
  - Constraints: changing a default needs an alembic migration (catalog-only `SET DEFAULT`, as D-669 did with `a6d2f81c4e3b`). Per D-669, existing agents are not flipped.

### Inferences
- The founder's opener ("హాయ్ అండి" form) is used only when the AI notice is OFF. With it ON, the salutation is the fixed "నమస్కారం అండి,". Keeping "హాయ్" with disclosure on would need a change to `INTRODUCTION_SALUTATIONS`, or a direction-specific salutation. That would be a code change for the founder to decide, not a data edit.
- A value line and close added to the trade plans reach new starters, the writer and (through `refresh_example_lines`, the D-888 pattern) existing agents that still hold plan lines word for word. Agents with edited lines keep their own text.

### Gaps
- `lifecycle.create_agent`'s INSERT was not read, so whether it sets the switches by direction was not confirmed. The D-669 row says it writes FALSE for every path.
