# Live call quality: our calls against Outpero's call — 23 October 2026 (D-856)

**What this is.** Five of our real calls (Raghava Organics, Telugu, 20-22 Oct 2026) set beside one
Outpero call the founder judged excellent (22 Oct 2026), turn by turn, scored with our own checks.
It lists the failure classes in our calls, the root cause of each in our prompt, script or writer,
and what D-856 changed. Related: `script-vs-outpero-2026-10-23.md` (script structure, H1-H4),
`outpero-onboarding-2026-10-22.md` §4, `latency-research-2026-10-21.md`,
`telugu-register-2026-10-21.md`, `docs/PROMPT-GUIDE.md`.

**Evidence classes.** Every transcript is FOUNDER-RELAYED (pasted from ThinnestAI's dashboard, our
call page and Outpero's call page). Whether Outpero's agent lines are its model's text or a
transcription of its voice is UNKNOWN; ours are the model's text as ThinnestAI stores it. Outpero's
in-call model, prompt and latency are UNKNOWN (the founder reports Gemini 2.5 Flash / Flash-Lite and
replies "well under 500-600 ms", neither measured here). One competitor call is an example, not a
measurement.

## 1. The calls

| Call | When (IST) | Agent | How it was placed | Founder's verdict |
|---|---|---|---|---|
| A | 20 Oct 19:25 | Raghava receptionist (answer calls), Studio, gemini-3.1-flash-lite | trial test call (we rang the founder) | "way better", filler before every turn, greeting not heard, no outcome, textbook words left |
| B | 21 Oct 09:58 | same | trial test call | given for the cost and interruption questions |
| C | 21 Oct 10:00 | same | trial test call | "slight interruptions" |
| D | 22 Oct, call 1 | same, new opening line | trial test call | 8/10, "almost exactly how I wanted"; flat, robotic stress |
| E | 22 Oct, call 2 | same | trial test call | 5/10; opening not heard, no reason given for the call |
| O | 22 Oct | Outpero test agent (introduced itself as Sanjana), Madhav Real Estate, bulk follow-up | Outpero rang the founder | "as if a real human"; replies felt under 500-600 ms; barge-in handled well |

Every one of our five calls was an **outbound test call placed with an inbound receptionist agent**
(`agents/trial_calls.py`: a trial test call may use any ready agent and opens with its usual
greeting, D-853). That shape caused failure class 2 below.

## 2. Our checks on both sides

`agents/turn_checks.turn_problems` and `calevate_shared.spoken_guard.textbook_words` (te-IN), run in
the lane container on every agent reply, with the caller line before it. Script:
`scratchpad/ci/d856_score.py`; the calls as data: `scratchpad/ci/d856_calls.json` (founder test
lines only, no number).

| Call | Replies | With a textbook word | …without ధర | Median chars | too_long | several_questions | asks_to_tell (new) |
|---|---|---|---|---|---|---|---|
| A | 10 | 4 (40%) | 2 | 75 | 3 | 0 | 1 |
| B | 7 | 2 (29%) | 1 | 97 | 2 | 1 | 1 |
| C | 9 | 3 (33%) | 3 | 100 | 3 | 0 | 0 |
| D | 7 | 5 (71%) | 3 | 146 | 4 | 0 | 1 |
| E | 7 | 3 (43%) | 3 | 134 | 5 | 0 | 0 |
| **Ours** | **40** | **17 (43%)** | **12 (30%)** | | | | |
| O | 10 | 2 (20%: సుమారు, ప్రస్తుతం) | 2 | 124 | 7 | 6 before D-856, 3 after | 0 |

Words in ours (replies holding each): మరియు 7, ధర 6, వివరాలు 3, అమ్ముతాము 3, సహజంగా 1, నాణ్యత, పరిమాణం, అవసరం,
సమాచారం, క్షమించండి 1 each.

**What the numbers say.** Outpero's replies are not shorter than ours: its median is 124 characters
and our own length check fails 7 of its 10 replies. Length is not where we lose. What differs is
what a turn does (§3). Our "one question a turn" check also failed 6 of its 10 replies, most of them
one question said twice ("which area? any particular area in mind?") or one question with its
options; D-856 stops counting a restatement opened by అంటే / లేక / or as a second question.

## 3. Turn by turn

**Opening and permission.** O opens with a six-word identity check by name and, only after "go on",
gives business, AI identity and the reason in one breath ("you enquired earlier about property in
Hyderabad, so what are you looking for now?"), with options. Ours opens with a 140-173 character
product pitch ("we sell chemical-free dried chilli and chilli powder… what do you need?"). On A and E
the founder's pickup "Hello" ran into it and he never heard it; the greeting is already
uninterruptible (`engine/thinnest.PLATFORM_VOICE_VALUES`, D-835), so what he missed was the start of
the audio, an engine and telephony matter. The pitch-first greeting is the agent's own opening line,
which D-849's writer rule already caps at 120 characters with one question (`call_rules.
OPENING_LINE_RULE`); the Telugu starter openings in `spoken_style.json` are already short and the
outbound one asks permission ("ఇప్పుడు రెండు నిమిషాలు మాట్లాడొచ్చా?").

**Disclosure placement.** O says "AI" once, inside its self-introduction. E answered "who is
speaking?" with the AI notice and a recording notice nobody asked for, in textbook passive
("రికార్డ్ చేయబడుతోంది"), then a product question.

**One question per turn, reacting to answers.** O: "ఓకే అండి, ల్యాండ్ కోసం చూస్తున్నారా! మంచిది."
then the next question, every turn; it reacts to the content ("Neopolis has good land options")
before asking. Ours asked "do you want to know the price?" on A, B and D (and C closed "do you need
any more details") instead of saying the price, and on A asked it after the caller had said "any
price is fine, send it". Our prompt told it: the engine's default call rule, sent as ours since
D-850, said "Never reply with only an acknowledgement and a question"
(`CALL_INSTRUCTIONS`, HEAD `engine.py:2951`), and HOW TO SPEAK said "Lead with the answer, then
wait" with nothing about reacting (HEAD `engine.py:2783`).

**Half answers.** O, on the caller's bare "ఒక." (one…) for budget, offered its reading with an out:
"అంటే ఒక కోటి రూపాయల వరకు బడ్జెట్ అనుకుంటున్నారా అండి? లేక ఇంకేమైనా ఐడియా ఉందా?" The caller
corrected it in one turn ("1 to 1.5"). Ours: on "మాకు" (A, C) it repeated its question word for
word; on "నాకొక" (B) it guessed "one kg" and asked about delivery in the same turn; on "కారం పొడి
కావాలండి ఒక" (C) it stated "so, one kg" and moved on, and the caller had to correct it to half a kg,
after which it asked the delivery question again (B and C both asked it twice). D-849's rule was a
bare "go on" (HEAD `engine.py:2785`), which the model did not follow on a number; guessing and moving
on is implicit confirmation, which saves a turn but makes a wrong guess hard to undo (§7, R5).

**Barge-in.** O handled the founder talking over it ("book it") with a one-word "షూర్" and then the
next question. Ours on A repeated "can you talk now?" seven seconds later (the engine's re-ask after
silence, `reaskAfterSeconds`) and was cut off; on D the caller added a second question while it was
speaking and the agent answered both. What a caller heard before cutting in is not visible to the
model; that part is the engine's.

**Register.** §2. O also writes English loanwords in Telugu script (ఓకే, ఏరియా, బడ్జెట్,
ఆప్షన్స్, డీటెయిల్స్, సాటర్డే); ours is told to keep them in English letters (founder, 11 Oct
2026, for Cartesia). Whether that difference drives its lower textbook share is a hypothesis (H5,
§8), not a finding.

**Fillers.** A had "ఒక్క సెకండ్ / ఒక్క నిమిషం అండి" before nearly every turn; it was the engine's
filler at 900 ms against a 937 ms model first word, fixed by D-835 (filler after 2,000 ms). The
model also wrote one itself ("ఒక్క సెకండ్ అండి, ధర ఎంతో చూసి చెప్తాను", A), which the default call
rule asked for: "If you need a moment to look something up, say so rather than going quiet" (HEAD
`engine.py:2954`). The founder also heard an English "Hmm… I see" on A, which is in neither
transcript: the engine's own filler or acknowledgement, picked in English after the caller's
"Hello" (UNKNOWN which; `filler_lines` empty means the vendor's own lines).

**False "done" and offers.** D asked "shall I confirm the order?" with nothing able to confirm one,
then answered the caller's "do it and WhatsApp me the details" with "noted" and a website to visit
("raghavaorganics.com ను సందర్శించవచ్చు"). O said "site visit ఫిక్స్ చేశాను" and "I'll send the
details on WhatsApp"; whether it had a tool that did either is UNKNOWN, and our checker did not
treat "fix చేశాను" as a booking claim until D-856.

**Closing.** O: confirms what was agreed, "any doubts?", then a warm goodbye naming the day. Ours: a
fixed "మీకు కావాల్సిన వస్తువులను నోట్ చేసుకున్నాను, thanks అండి" on A-D, twice in one turn on A
and B, with no word on what happens next, and no name or address taken (A).

**Latency** (production `calls.engine_quality`, rememory cffb1b4b). A: reply median 1,604 ms, model
first word 937 ms; B and C: 1,690 and 1,703 ms; two 21 Oct evening calls after Ear and the lean
switches: 2,139 and 2,215 ms. D and E: not read here. O: the founder's impression only.

## 4. Failure classes in our calls

| # | Class | Evidence (call, turn) | Root cause in our code | D-856 fix | Ours or the engine's |
|---|---|---|---|---|---|
| 1 | Pitch-first opening, missed at pickup | A t0, E t0: 140-173 chars of products | Raghava's own opening line (owner-written before D-849's 120-char rule); engine audio start | Writer and starter openings stay short and ask one question (`call_rules.OPENING_LINE_RULE`, `spoken_style.json` openings); the who-is-calling rule recovers | Line: ours. Missed audio start: engine/telephony |
| 2 | Wrong frame when the receptionist rings out | E t2-t6: "what do you need?", then "why didn't you say who is calling first?" | Role sentence says "answering calls for" (`engine.role_sentence`); nothing tells the model who placed a call | `WHO_IS_CALLING_RULE` in START OF THE CALL for agents that answer calls: asked who or why, say who and why in one line, then ask if now is a good time (`engine.py:3871`) | Ours. A per-call "you placed this call" value was built and rejected: it must sit after the truthful-answer block or end the cached prefix early (§6) |
| 3 | Asking leave to tell instead of telling | A t15, B t10, D t8: "ధర గురించి తెలుసుకోవాలనుకుంటున్నారా?" | "Never reply with only an acknowledgement and a question" (HEAD `engine.py:2951`); no reaction rule | HOW TO SPEAK: "Asked something? Lead with the answer, never 'do you want to know'. Told something? React in a few words, then ask the next thing." New check `asks_to_tell` | Ours |
| 4 | Half answer re-asked or guessed | A t11 / C t8 repeat; B t4, C t10 guess and move on | Bare "go on" rule (HEAD `engine.py:2785`); checker allowed only ≤4-word replies (`NUDGE_MAX_WORDS`) | "Half an answer? Offer your reading as a question with a way out ('one kg, or more?'); never finish it for them." Checker accepts one short question that offers the cut number (`turn_checks._offers_reading`) and still fails a guess stated as said; judge rule `own_part` says the same | Ours. The 0.25 s turn timer that cuts them stays (founder, 21 Oct 2026) |
| 5 | Two questions, or the same question again after a correction | B t4 (two), B t6 / C t12 (delivery asked twice) | No one-question rule in the chat (it lived only in call rules) | "One question a turn… choices help; never re-ask what they said" now in HOW TO SPEAK, read in calls and practice chat | Ours |
| 6 | Offering what nothing can do; website instead of WhatsApp | D t10 "confirm the order?", D t12 website | Offer not covered by `ACTION_CLAIM_RULE`; "never mention links" only in call rules | `ACTION_CLAIM_RULE`: "…or offer what no tool of yours does"; judge `done` rule; "links" in HOW TO SPEAK; standing caller `specimen_just_whatsapp` | Ours |
| 7 | Self-made filler | A t17 "ఒక్క సెకండ్ అండి, ధర ఎంతో చూసి చెప్తాను" | "say so rather than going quiet" (HEAD `engine.py:2954`) | Removed; "Never announce a search or a wait, or narrate one." The engine's own filler covers a wait over 2 s | Ours; the engine filler timing was D-835 |
| 8 | Textbook register | 17 of 40 replies (§2) | Model leans formal; instruction route measured at its limit (`telugu-register-2026-10-21.md`) | Per-step spoken example lines in every starter and the writer's plan (Google: always include few-shot examples) | Partly ours; H5 untested |
| 9 | Fixed, double or empty close | A t17, B t12 double goodbye; A-D "noted, thanks" with no next step | Starter close "Read back their name, the number to reach them on…" (HEAD `starters.py:342`, against `CALL_NUMBER_RULE`); no close rule | HOW TO SPEAK: "Close with what happens next and anything else, then say goodbye once"; every plan's last step | Ours |
| 10 | Unasked notices and pitch on "who is speaking?" | E t4, E t6 | No rule for the question | Class 2's rule; `specimen_who_is_calling` | Ours |
| 11 | Long answers to a side question | D t4, t6 (three sentences, ~190 chars) | Turn length only in call rules, not chat | "One or two short sentences, then wait" in HOW TO SPEAK | Ours |
| 12 | Price as Telugu number words | A t17, C t14, D t10, E t10 | Model ignores "prices in English words" | None new; measured 21% (`register_eval`) | Ours, unresolved |
| 13 | Flat or wrong stress | D (founder) | Cartesia prosody | None (punctuation rules unchanged) | Voice engine |
| 14 | Opening audio not heard | A, E | Pickup timing | None from the prompt | Engine/telephony |

## 5. What changed in the prompt (D-856)

- **One place for turn shape.** Every sentence of `CALL_INSTRUCTIONS` but the call frame moved into
  HOW TO SPEAK, BUSINESS FACTS and WHAT YOU CAN DO, which the engine reads on calls and in the
  practice chat. `CALL_INSTRUCTIONS` is now 149 characters (was 1,112) and must stay non-blank
  (blank restores the engine's 1,675). `tests/call_instructions_test.py` maps every default sentence
  to its new place; two are turned round on purpose (classes 3 and 7).
- HOW TO SPEAK: react then ask; answer, never "do you want to know"; one question, choices allowed;
  offer a reading of a half answer; carry on in fewer words after a barge-in; no lists or links;
  never announce a search; close with what happens next and one goodbye.
- BUSINESS FACTS adds address, duration and "how such businesses usually work"; WHAT YOU CAN DO adds
  "or offer what no tool of yours does", a tool's figure exactly, a failed one plainly.
- START OF THE CALL adds `WHO_IS_CALLING_RULE` for agents that answer calls.
- Locked layers untouched: the truthful-answer block (still last), `CONFIDENTIALITY_RULE`, the
  client-script fence, the spoken-output and digits rules. Composition digests re-pinned
  (`tests/thinnest_facts_in_knowledge_test.py`).

## 6. Prompt size and the cache

**Measured** (`scratchpad/ci/d856_measure.py`, `engine_prompt_layers` plus the native steps payload
and `CALL_INSTRUCTIONS`; starters as `agents/starters` builds them, business "Raghava Organics", AI
notice on, facts in knowledge, own rules on).

Per layer, Telugu retail starter that answers calls, characters, before → after:

| Layer | Before | After |
|---|---|---|
| preamble | 293 | 293 |
| HOW TO SPEAK | 1,172 | 1,496 |
| SPOKEN REGISTER | 900 | 900 |
| BUSINESS FACTS | 435 | 510 |
| START OF THE CALL | 159 | 257 |
| client script | 1,473 | 1,590 |
| WHAT YOU CAN DO | 757 | 845 |
| CONFIDENTIALITY (locked) | 855 | 855 |
| truthful answers (locked) | 820 | 820 |
| instructions total | 6,880 | 7,582 |
| native steps (now with a spoken line per step) | 1,212 | 1,282 |
| `CALL_INSTRUCTIONS` | 1,112 | 149 |
| **what a call reads of ours** | **9,204** | **9,013 (-2.1%)** |

Platform layers only (no script), what a call reads of ours: one language 6,250 → 5,774 (-476,
-7.6%), three languages 7,227 → 6,751 (`tests/agent_prompt_budget_test.PER_CALL_MAX`, the new
enforced target). Starters, Telugu, before → after: clinic answer 9,243 → 9,104, real estate leads
9,441 → 9,459, retail leads 9,516 → 9,490, custom answer 9,074 → 8,879; three-language retail
10,181 → 9,990. Every starter now also carries a spoken example line on each step.

**Tokens** are ESTIMATES: Gemini's own guide puts a token at about four characters of English; a
Telugu character costs more and its ratio was not measured here (no Google key in this lane). On
that ratio the platform cut is about 120 tokens a turn.

**Why `thinnest_call_instructions` and `thinnest_own_rules` did not visibly cut input tokens**
(production 5.9-8.4k a turn before and after, rememory cffb1b4b). Arithmetic, not a measurement:
callInstructions replaced 1,675 characters with our 1,112 (563 fewer), and ownRules drops the
vendor's hand-over (279-480) and lead (88 or 652) sentences while we add our 120-character hand-over
line. Together about 0.3-1.1k characters, roughly 100-300 tokens, against 6-8k a turn that also
carries the growing history, the tool schemas and every knowledge-search step ("usage.inputTokens is
the sum over all turns of what the model provider reported, tool steps included", §18.0 of
`docs/vendor/thinnest-replies-2026-10-12.md`). A 2-5% change is inside the spread between calls of
different length. D-856's further 476 characters (~120 tokens) will not be visible on that meter
either; it is a cost and focus gain, not a latency lever. ThinnestAI states the model's first byte is
~0.9 s at 6k tokens and 1.2 s at 1k (§25, rememory 3a6a2e08, VENDOR-STATED), so prompt length is not
what sets our reply time.

**The cache: what we control and what we do not.**
- VENDOR-STATED (§18.0): the system prompt is built once per call and is identical on every turn;
  across calls it is identical up to our first `{{variable}}`; the time of day rides on the caller's
  line; `cachedInputTokens` is Google's own count. §23.0: ThinnestAI gets 90%+ cache hits on OpenAI
  models with the same settings.
- VERIFIED-VENDOR-DOCS (ai.google.dev/gemini-api/docs/caching, read 23 Oct 2026): implicit caching
  is on for Gemini 2.5 and newer; listed minimums are 2,048 tokens (2.5 Flash, 2.5 Pro) and 4,096
  (the Gemini 3.x models listed); **gemini-3.1-flash-lite is not in the table**, and its model page
  says only "Caching: Supported". Advice: large common content first; similar prefixes within a
  short time.
- Ours, already in place: every per-call value is last (`THIS CALL`, D-814); a script section with a
  `{{variable}}` is compiled after the fixed ones (`call_script.per_call_sections_last`, D-835); the
  composition has no clock or counter (`tests/agent_call_rules_test.py`). The vendor's fixed rules,
  the agent's name and its business line come before our text, so prefixes are never shared across
  agents whatever we order.
- A lead, not a finding: per turn, the cached count on the calls in rememory cffb1b4b is about
  2.0-2.8k tokens whatever the call's length (assuming turn one caches nothing). A constant cached
  prefix well short of the whole system prompt would point at something after it differing between
  turns, or at Gemini caching only part of a prefix. **The cause is UNKNOWN**; it can only be read in
  ThinnestAI's request log (§22 item 2, not answered beyond the OpenAI comparison).
- Rejected for D-856: a per-call "you placed this call" value for class 2. It would either follow the
  truthful-answer block, which must stay the last rule (`tests/prompt_fence_test.py`), or sit before
  the script and end the shared prefix there.

## 7. Web research (read 23 Oct 2026)

| # | Source | What it says | Class |
|---|---|---|---|
| R1 | ai.google.dev/gemini-api/docs/caching | §6 above | VERIFIED-VENDOR-DOCS |
| R2 | ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite | "Caching: Supported"; no minimum given | VERIFIED-VENDOR-DOCS |
| R3 | ai.google.dev/gemini-api/docs/gemini-3 (marked deprecated in favour of a newer page) | "Be concise in your input prompts"; `minimal` thinking "does not guarantee that thinking is off"; keep temperature at 1.0 | VERIFIED-VENDOR-DOCS |
| R4 | ai.google.dev/gemini-api/docs/prompting-strategies | Always include few-shot examples; too many make the model overfit them; put critical constraints and the persona in the system instruction; be precise and direct | VERIFIED-VENDOR-DOCS |
| R5 | isi.edu/results/publications/17917 (2002 study of user behaviour under error conditions) and cs.brandeis.edu/~cs115/CS115_slides/HandlingErrorsInDialogue.pdf | Implicit confirmation (embedding a guess in the next question) is efficient, but users who meet an error through it recover worse and slower than after an explicit check | SECONDARY (abstract and course slides via search) |
| R6 | developers.openai.com/cookbook/examples/realtime_prompting_guide (archived) | Short labelled sections, bullets over paragraphs; the model follows sample phrases closely; add a variety rule against robotic repetition | VENDOR-PUBLISHED |
| R7 | elevenlabs.io/docs/agents-platform/best-practices/prompting-guide | Concise action-based rules; a dedicated guardrails section; "prompts over 2000 tokens increase latency and cost" | VENDOR-PUBLISHED, unmeasured claim |
| R8 | arxiv.org/abs/2507.11538 (IFScale, NeurIPS 2025) | Instruction following degrades as instructions multiply; models favour earlier instructions | PAPER (abstract read) |
| R9 | doi 10.1073/pnas.0903616106 (Stivers et al. 2009) | Across ten languages people avoid overlap and minimise silence between turns; language means differ within about 250 ms | PAPER (abstract via secondary listings) |

How they shaped D-856: R4 and R6 for an example line per step and sample phrases; R5 for offering a
reading as a question rather than acting on it; R3, R7 and R8 for fewer rules said once (the 23
default call sentences now live in one place); R1-R2 for what the cache section can and cannot say.
Code-mixed register sources are those of `telugu-register-2026-10-21.md` §2, not re-read here.

## 8. Per-trade step plans

`apps/api/agents/trade_playbooks.py`: for every trade in `agents/starters.TRADES` (clinic, real
estate, insurance, education, retail, local services, automobile, custom) and each job (answer
calls, call leads), five steps with a done-when branch, the trade's questions (one thing a turn,
with choices), its usual objections (two or three per job plus one per trade) and a spoken example line per
step in Telugu, Hindi and English. Starters build their steps, example lines and objections from it;
the AI script writer reads it with every new draft (`apps/workers/script_assist.draft_script`). A
business-specific line from the business copy (D-827) replaces a plan line; a person's line is never
replaced. All 51 lines per language (three shared, six per trade) pass `turn_problems`, the textbook list and the
writer's rules (`tests/trade_playbooks_test.py`). They are AI-drafted and wait for a native
speaker's review like the rest of `spoken_style.json`. A third job ("call my list" beside "call new leads", in progress) is one key in
`JOB_SHAPES`; the coverage test then demands it for every trade.

## 9. Hypotheses and founder questions

- **H5 (new).** Outpero writes English loanwords in Telugu script; we require English letters. If
  the Latin-letter rule pushes the model to the native word (మరియు, వివరాలు) rather than a script
  switch, a variant that allows Telugu-script loanwords would cut textbook words. Testable with
  `register_eval` once a variant is added; Cartesia's reading of Telugu-script loanwords would need
  the founder's ear test. Not built: it reverses a founder decision of 11 Oct 2026.
- **Q1.** Should a test call of an agent that only answers calls open with the outbound greeting
  ("calling from {business}, can we talk for two minutes?") instead of its inbound one? That is a
  change to the dial path and the greeting check, not the prompt.
- **Q2.** Should the platform set Telugu filler lines by default (class 13's English "Hmm… I see")?

## 10. Pending live evaluations (need the Google and ThinnestAI keys; not run here)

On the VPS, from `/var/www/calevate`, after D-856 is deployed:

```
sudo -u calevate bash -lc 'cd /var/www/calevate && docker compose -p calevate -f compose.prod.yml exec -T workers python -m scripts.register_eval --spend --max-inr 50 --language te-IN --no-cross --variants current'
sudo -u calevate bash -lc 'cd /var/www/calevate && docker compose -p calevate -f compose.prod.yml exec -T workers python -m scripts.register_chat_eval --agent <raghava agent uuid> --dry-run'
```

The first measures the textbook-word share of the new composition against the 36% baseline; the
second prints the new layer sizes on the real agent. Then a practice-test run on the Raghava agent
from its Tests tab (the four new standing callers rotate in), two trial test calls with the
receptionist and two with a call-leads starter, each read with Get Call `quality` and
`python -m scripts.prompt_size --agent <uuid>`.
