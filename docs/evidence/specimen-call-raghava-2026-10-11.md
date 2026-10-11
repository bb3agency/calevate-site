# Specimen call: Raghava Organics, 11 Oct 2026 (D-749)

An outbound Telugu call on `ENGINE=thinnest` at 15:33 IST. The founder made it a **specimen**
for the whole system (11 Oct 2026). Each failure is named as a class that can happen to any
business, in Telugu, Hindi or English. Each class is fixed at the platform layer, so it reaches
every agent.

**The agent ran the OLD instructions.** Its live apply failed with `agreements_not_accepted`,
so it never received the D-739, D-744 or D-745 text. Every failure below was first checked
against the CURRENT platform text, and a rule was added only where that text did not already
cover the class.

The caller's partial number appears only as "944…". The regression fixture uses a made-up
prefix (`tests/specimen_call_test.py`).

**Owner** says whose problem it is:
- **ours**: our prompt or adapter
- **vendor**: ThinnestAI's pipeline
- **model**: the in-call model, which no prompt fully controls

## Classes

| Turns | Class | Owner | Cause | Fix | Caught by |
|---|---|---|---|---|---|
| 17, 21 | **False action claim**: "order recorded", "details saved", with no action able to do either | ours | No rule tied "done" to an action. Nothing filters model output on ThinnestAI. | `ACTION_CLAIM_RULE`, after the client script: never say done unless a tool confirmed it on this call; otherwise say what happens next. Connected actions still confirm. | `unconfirmed_action` (test loop). `claimed_not_done` key moment on the call page, from `action_invocations` and `scheduled_callbacks`. |
| 17, 19 | **Re-asking for known data**: the phone number on a call to that number | ours | The number is already on the lead (`leads.phone_e164` comes from the call). No rule said so. Scripts list "phone" to collect. | `CALL_NUMBER_RULE`, after the script: never ask for it, at most "this same number?". Hidden-number calls keep `FORWARDED_LINE_RULE` (D-746). The voice block also says never to ask for what they already said. | `asked_known_number` |
| 20-21, 34-35 | **Partial data accepted as complete**: 3 digits taken as a phone number | ours | "One digit at a time" covered reading a number out, not taking one down. | Voice block: numbers a few digits at a time, read back one digit at a time; a mobile has ten, never fewer. | `partial_number` (digits add up across turns, so small groups pass) |
| 7, 9 | **Product name translated, and a wrong fact made up**: powder "from green chilli", and "organic chilli" turned into పచ్చి మిర్చి | ours + model | Facts guarded price, stock and time, but not "what a product is or how it is made". Nothing said not to translate names. | Business facts: never guess or add to a fact, including what a product is or how it is made; say names as the facts give them, never translated. Script builder: "Names and how to say them" (compiled as "Say these names exactly like this"). | Judge (`specimen_fact_not_in_knowledge`). A rule cannot know the right fact. |
| 7 | **Foreign-script token**: a Korean syllable mid-Telugu | model | Each language's register already says "in Telugu script". | No new prompt text. | `foreign_script` |
| 13, 15, 23, 33, 35 | **Actions and notes written as text**: "(Waiting for user response)", "[awaiting response]", "[hang_up]", "[call hang_up]" | vendor + model | The old text forbade "bracketed text". Some notes may be the vendor's own (queued question 6). | Voice block: "Never write actions, notes or anything in brackets". The line is now released by `voice.endCallOnFinish: true`. | `brackets` (existing) |
| 9, 15 | **Turn repeated or re-generated** after an interruption: three copies of a question glued together, plus "[cut off before finishing]" | vendor (to confirm) | Looks like a re-run with the partial reply appended (queued question 7). Not invented here. | Nothing on our side beyond one or two sentences a turn. Sentences glued without a space now split for the checks. | `repeated_question`, `too_long` |
| 25, 27, 35 | **Goodbye while the caller is talking** | ours + model | "End only after a goodbye" did not say "not while they are still asking". | Voice block: never while they talk or ask something. | `goodbye_while_asking` |
| 3, 15 | **Several questions in one turn, and over-answering** | ours (old text) | Covered by D-739: one or two sentences, one question. | No new text. | `several_questions`, `too_long` (existing) |
| 3, 11, 15, 17 | **Textbook register**: కొనుగోలు, మరియు, సుమారు, సహజంగా, ఆహారాలు, నిర్ధారించాలనుకుంటున్నారా, నమోదు, తద్వారా, స్వయంగా, ప్రాంతం | ours (old text) | D-744 swaps covered five of these. | Added to `spoken_style.json` (te-IN, `needs_native_review`): సహజంగా, నిర్ధారించాలనుకుంటున్నారా, తద్వారా, స్వయంగా, ప్రాంతం, ఉదాహరణకు, ఉత్పత్తి. | `formal_words` |
| 15 | **Digits and native number words in speech**: "1 కిలో", "ఆరు నూరు రూపాయలు". The ₹600 price itself is correct. | ours | The old rule said "in words", and Telugu words satisfied it. | Voice block: "in English words" ("six hundred rupees"). | `spoken_number` (Telugu and Hindi number words before rupees; digits before an Indian-script unit) |
| 3-5 | **Repeating a whole turn when asked to repeat** | ours | No rule. | Voice block: asked to repeat, say it shorter. | `repeated_turn` |
| 37 | **Context lost after interruptions** | model + vendor | Probably the vendor's context handling after interruptions (questions 6 and 7). | Voice block: if they talk over you, stop, answer, then carry on where you were. Never ask for what they already said. | Judge (`specimen_side_question`) |

**End-of-turn silence.** Digits were cut off after 0.25 s of quiet, which is the vendor default.
This was item 2 of the 10 Oct email. The live `update-agent` reference (read 11 Oct 2026) now
lists `voice.turnSilenceSeconds`: a number or null, 0.2 to 3, defaulting to 0.25 s on most
lines. Raising it for dictation is a founder decision. It is not changed here.

## Regression

- **Standing test callers.** `apps/api/agents/specimen_scenarios.py` has seven classes. Each
  has business-type variants (retail, local services, clinic, default) in te-IN, hi-IN and
  en-IN. Every test run carries two of them, rotating, ahead of the AI-written callers.
- **Scripted replay.** `tests/specimen_call_test.py` replays this call through the hard checks.
  Every class must be caught, and the good replies must pass.
