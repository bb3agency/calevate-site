# Voice-agent prompt, script and evaluation research (25 Nov 2026)

Scope: what to send the in-call model (Gemini Flash-Lite family on ThinnestAI), how Pip should
write guided outbound scripts, and how to score them. Every external claim was read on
2026-11-25 at the URL given (evidence class VERIFIED-VENDOR-DOCS or PRIMARY-PAPER unless marked).
`M` = `thinnest-findings/mirror/snapshots/2026-10-29/pages` (hash-pinned vendor mirror).
Failure evidence: founder test calls of 24 Nov 12:15 IST and 25 Nov 01:37 IST, and the Rytu Khata
script of 25 Nov (session scratchpad; evidence only, no Telugu copied here).

## What the two calls show (the defects this research must answer)

- One turn carried a check, a condition and two actions (25 Nov, turn 4).
- The agent asked a known customer's name in the middle of a step, because the script told it to
  collect the name, goal met, comfort level, interest and another number. All are now recorded as
  captured, and most are false.
- It asked "is it done?" before the caller could act (turns 8, 16, 27). It took a garbled
  "And." as done (turn 15) and moved on.
- It repeated one line word for word (turn 23). It opened 9 of 12 replies with the same
  acknowledgement (24 Nov).
- It spoke textbook register and said brand names twice, once in Telugu script and once bracketed
  in English.
- Branch conditions were step names, for example "Add Farms" leading to s3, instead of caller
  states. The actor was wrong ("I'll note them"). "Not registered" sits after Finalise.
- After-call fields were filled from things never said, and "Campaign Goal Met" read "Yes".

---

## A. Findings by topic

### A1. Prompt design for real-time voice agents

**Structure and order**
- **OpenAI.** Use labelled sections in this order:
  1. Role & Objective
  2. Personality & Tone
  3. Context
  4. Reference Pronunciations
  5. Tools
  6. Instructions/Rules
  7. Conversation Flow
  8. Safety & Escalation

  Drop the sections you do not need, and prefer short bullets over paragraphs. Source:
  OpenAI Realtime Prompting Guide, https://developers.openai.com/cookbook/examples/realtime_prompting_guide
  (notebook source read from github.com/openai/openai-cookbook `examples/Realtime_prompting_guide.ipynb`).
- **Google Live API.** Order the instructions "persona, then conversational rules, then
  guardrails". Use one system instruction per agent, and list the rules "in the order you expect
  the model to follow them". Source: https://aistudio.google.com/docs/live-api/best-practices.
- **Vapi.** Its order is:
  1. Identity & Personality
  2. Response Guidelines
  3. Guardrails, placed "prominently"
  4. Context
  5. Workflow
  6. Examples

  Source: https://docs.vapi.ai/prompting-guide.
- **ElevenLabs.** Its order is Personality, Environment, Tone, Goal, Guardrails, Tools, Error
  handling. It says models "pay extra attention" to a `# Guardrails` heading. Source:
  https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide.
- **LiveKit.** Its order is identity, output rules, conversational flow, tools, guardrails, plus a
  "User information" section filled from known data "to avoid asking redundant questions".
  Source: https://docs.livekit.io/agents/start/prompting.
- **Gemini 3.** Use one consistent delimiter style. Put role, constraints and output format in the
  system instruction. After long context, put the specific instructions at the very end. Source:
  https://aistudio.google.com/docs/prompting-strategies.
- **Anthropic.** Put long material at the top and the query at the end. This "can improve response
  quality by up to 30 percent". Source:
  https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices.

**Length**
- **OpenAI.** Its examples pin "2–3 sentences per turn" (same OpenAI guide).
- **LiveKit.** "Keep replies brief by default: one to three sentences. Ask one question at a
  time." (same LiveKit page)
- **ThinnestAI.** "Two sentences is plenty" (`M/guides/how-your-agent-sounds.md:59-66`).
- **Alexa.** Use the one-breath test: if you need a breath to say it, shorten it or split it
  (https://developer.amazon.com/blogs/alexa/post/531ffdd7-acf3-43ca-9831-9c375b08afe0/things-every-alexa-skill-should-do-pass-the-one-breath-test,
  18 Jun 2018).
- **Prompt length.**
  - ElevenLabs: past 2,000 tokens, latency and cost rise, so split the agent or move reference
    material to a knowledge base.
  - Vapi: "Every token costs latency".
  - Retell: "a longer prompt is not a better prompt". It cut a worked example from about 970
    words to about 300 without losing function (https://docs.retellai.com/build/prompt-engineering-guide).
  - No source gives an accuracy threshold for prompt length.

**Rules vs examples**
- **OpenAI.** The model "strongly closely follows sample phrases" and may overuse them. A Variety
  rule fixed a repeated "Got it" ("Do not repeat the same sentence twice. Vary your responses…").
  Tune it as "don't reuse the same opener more than once every N turns".
- **Google.** "We recommend to always include few-shot examples". Too many examples cause
  overfitting, and the format must be consistent (Gemini prompting strategies).
- **Anthropic.** Use 3–5 examples that are relevant, diverse and tagged. Give the reason for a
  rule; its example is "read aloud by a text-to-speech engine, so never use ellipses". Say what to
  do rather than what not to do.
- **Vapi.** Use at least three transcripts: happy path, edge case and error recovery. Avoid long
  ban lists, which "can prime the banned phrases".
- **Retell.**
  - Do not patch each failure with a prohibition; fix the unclear task statement.
  - State each instruction once.
  - Do not over-script acknowledgements.
  - Do not use AI-generated starter prompts, which are over-cautious.
- **Conflicting view.** LiveKit says rules may need reinforcing "across multiple sections", while
  Retell and ElevenLabs say state each rule once and repeat only the critical one or two. Neither
  side publishes measurements.

**Turn-taking, one question, waiting for an action**
- **Google conversation design.**
  - Signal the user's turn with a question.
  - "Don't keep speaking after you've asked a question."
  - Do not put all the options and questions in one turn.

  Source: https://developers.google.com/assistant/conversation-design/learn-about-conversation.
  The Conversational Actions product was deprecated on 13 Jun 2023, but the design guidance is
  still published.
- **Vapi.** "Ask only one question at a time." Collect, confirm, move on. If the caller goes quiet,
  wait 10–15 s, then check in once.
- **Google Live.** Mark recurring loops apart from one-time steps, for example "Let this step go
  on for as long as the client wants". This is the nearest published pattern for waiting while
  the user acts.
- **OpenAI.** Give each phase "Exit when" criteria that are "concrete and minimal". This "prevents
  the model from … skipping steps, or jumping ahead".
- **Not covered.** No source we read gives a pattern specifically for "do this on your phone and
  tell me when done".

**Unclear or garbled input**
- **OpenAI.**
  - "Only respond to clear audio or text."
  - If the audio is "ambiguous… /unintelligible" or not fully understood, ask for clarification
    in the preferred language.
  - Wording matters: changing "inaudible" to "unintelligible" improved handling of noisy input.
  - Alternatively, repeat the last question.
- **Google errors guide.**
  - First No Match: a rapid reprompt, "Do not repeat the original prompt verbatim".
  - Second No Match: add options or examples.
  - End after 2 No Match attempts. Never more than 3 errors in a row.
  - No Input: rephrase concisely, and do not say "I didn't hear you".

  Source: https://developers.google.com/assistant/conversation-design/errors.
- **Vapi.** Ask for a repeat, then escalate after two attempts. If the caller says only "hmm", ask
  one short question before assuming they are done. Spell back proper nouns.

**Repetition and filler**
- **LiveKit.** "Don't open consecutive turns with the same word or acknowledgment."
- **Google Live.** "Each response… should be a net new addition… not a recap."

**State and steps: prompt text vs a state machine**
- **OpenAI.**
  - Two patterns: a JSON state machine (id, description, instructions, examples, transitions with
    conditions) and dynamic `session.update`.
  - Warning: "too many rigid states can overload the model".
- **Pipecat Flows.** "monolithic prompts with many tools lead to hallucinations and lower
  accuracy". Each node "focuses the LLM on a single task". It works by rewriting the context at
  each transition. Source: https://docs.pipecat.ai/pipecat/flows/introduction. The claim comes
  with no benchmark.
- **Retell.** Start with a single prompt. "Having multiple steps does not, by itself, require
  conversation flow." Switch only when the prompt grows too large, after simplifying first
  (https://docs.retellai.com/build/choose-agent-type).
- **ThinnestAI's `steps`.** Up to 12 steps of `title` (80 chars), `detail` (600), `branches`
  (`when`/`action`) and `collect` (`M/api-reference/agents/create-agent.md:886-891, 1226-1258`).
  The mirror does **not** say whether the engine tracks the current step or just renders the steps
  into the prompt (see E).

**Persona and register**
- **OpenAI.** Pin the output language when it switches unexpectedly.
- **Google Live.** "RESPOND IN {OUTPUT_LANGUAGE}. YOU MUST RESPOND UNMISTAKABLY IN …"
- **Google conversation design.** Use plain, familiar words and avoid technical terms.
- **Vapi.** Match the caller's energy: give crisp callers "fewer fillers, shorter turns".

### A2. Small-model instruction following

- **Lost in the Middle.** Liu et al., *Lost in the Middle* (TACL; arXiv:2307.03172). Performance
  is highest when the relevant information is at the beginning or end of the input, and degrades
  when it sits in the middle, "even for explicitly long-context models".
- **IFScale.** Jaroslawicz et al., *How Many Instructions Can LLMs Follow at Once?*
  (arXiv:2507.11538, NeurIPS 2025), Appendix A. Accuracy at 10, 50, 100 and 500 instructions:

  | Model | 10 | 50 | 100 | 500 |
  |---|---|---|---|---|
  | gemini-2.5-flash-preview | 100% | 96.0% | 82.0% | 34.2% |
  | gpt-4.1-nano | 94% | 72.8% | 51.6% | 16.2% |
  | gpt-4o-mini | 94% | 65.6% | 41.8% | 10.4% |
  | claude-3.5-haiku | 98% | 78% | 43.4% | 8.5% |

  - Smaller models show "exponential decay" to floors of about 7–15%.
  - Models are biased toward earlier instructions. This primacy effect peaks at 150–200
    instructions.
  - Errors are mostly **omissions**: the instruction is dropped, not distorted.
  - **Limits:**
    - The instructions are keyword-inclusion constraints on a report, not conversational
      behaviours.
    - Flash-Lite was **not tested**.
- **Vendor notes on small models.** ElevenLabs: ultra-low-latency models show "lower performance
  on complex tool-calling" and "may require more explicit prompting". OpenAI: conflicting or
  ambiguous instructions degrade performance.

### A3. Script and flow design for guided outbound calls

- **Opening.**
  - ThinnestAI: keep the opening short, because a caller who hears a paragraph talks over it
    (`M/channels/voice.md:361-369`). Name the business and invite the caller to speak
    (`M/guides/how-your-agent-sounds.md:107-114`).
  - Google Live: the model waits by default, so add the greeting to the prompt, and include user
    details to personalise it.
- **Ordered steps.**
  - ThinnestAI survey guide: ask "in this order, one at a time, and wait for each answer". Put the
    countable questions first, because people hang up partway through. "Do not let it improvise
    the options." (`M/guides/survey-agent.md:65-91`)
  - OpenAI: one targeted question per phase, and capture "minimal details".
- **Never ask what is known.**
  - Google: users offer more than asked, so "Don't force repeat answers".
  - LiveKit: load known user data.
  - Retell: "skip information already given". Use corrected details and do not re-ask.
  - Rasa 3.x forms ask "the next empty slot" and stop when all required slots are filled
    (https://legacy-docs-oss.rasa.com/docs/rasa/forms).
- **Confirmation.**
  - Google: implicit confirmation is the norm. Use explicit confirmation "only when the cost of
    misunderstanding… is high". Do not confirm simple input recognised with high confidence
    (https://developers.google.com/assistant/conversation-design/confirmations).
  - Vapi: batch read-backs for transactional flows only.
  - OpenAI: read digits back one at a time and re-confirm after a correction.
- **Exits.**
  - Google: end gracefully after 2 failed collection attempts and offer another route.
  - Vapi: offer a transfer after 2 failed attempts.
  - **Not found:** a primary published source on outbound call openings for permission, purpose,
    "not now", wrong person or objection handling (see E).
- **Things the caller cannot see.** ThinnestAI's guide says no lists, links or "click here"
  (`M/guides/how-your-agent-sounds.md:80-88`). That guide is about things the caller cannot see.
  In an app-setup call the caller is looking at their own phone, so naming one on-screen label is
  the task itself. Even so, a URL should be sent by message rather than read aloud (same lines).

### A4. Indic and Telugu voice specifics

- **Code-mixing is normal.** Madhumani et al. (arXiv:2006.05257, Table 1) measured the
  Code-Mixing Index of code-switched sets. Telugu–English was 23.85 (train+dev) and 21.62 (test),
  against 22.08/17.07 for Tamil and 18.91/16.32 for Gujarati: "The CMI of Telugu-English is the
  highest" (https://ar5iv.labs.arxiv.org/html/2006.05257). CoSTA (arXiv:2406.10993) calls
  code-switching "widely prevalent" in India and releases a Telugu–English benchmark.
- **ASR accuracy on Telugu is modest.**
  - SraVaani 1.0 (arXiv:2608.08235v2, Table 3) gives Telugu WER averaged over 6 datasets
    (17.77 h): Gemini 3 Flash 28.9%, Sarvam Saaras v3 28.7%, IndicConformer 26.4%,
    SraVaani 25.1%.
  - On code-switched speech that model writes "the entire transcription in the script of the
    predicted primary language", and its language ID "is not always reliable".
  - IndicVoices (arXiv:2403.01926) is 74% extempore and 17% conversational speech: 7,348 h,
    22 languages.
- **ThinnestAI language handling.**
  - A fixed language makes the recogniser listen for that language. "Match the customer" decides
    the language per sentence, "so a short or mixed reply can be heard as the wrong one"
    (`M/channels/voice.md:557-570`).
  - Custom `vocabulary` is passed to the recogniser (`M/api-reference/agents/create-agent.md:1833-1845`).
    Our adapter deliberately sends none after a looping call (D-948, `apps/api/engine/thinnest.py:385-397`).
- **Not found:** published, Telugu-specific error taxonomies, for example short replies or
  English UI words.

### A5. Evaluating generated scripts and dialogue

- **MT-Bench.** Zheng et al., *Judging LLM-as-a-Judge* (NeurIPS 2023 D&B, arXiv:2306.05685).
  It names "position, verbosity, and self-enhancement biases, as well as limited reasoning".
  Strong judges reach "over 80% agreement", the same level as human–human agreement.
- **Position bias.** Wang et al. (arXiv:2305.17926) found that swapping the order of two answers
  can flip a GPT-4 verdict. Fixes:
  - generate evidence before scoring;
  - average over both orders;
  - send the hard cases to humans.
- **G-Eval.** G-Eval (arXiv:2303.16634) uses chain-of-thought plus form-filling and reaches
  Spearman 0.514 with humans on summarisation. It found "preliminary evidence" that LLM judges
  favour LLM-written text.
- **Test across many calls.** Vapi: "Probabilistic regressions don't show up in one-off testing."
  Check prompt changes across many calls.

---

## B. Checklist: our in-call prompt

**Order** (A1 and A2: primacy, lost in the middle, Gemini's "instructions last after long
context"):
1. **Role & objective.** 2 lines: who is speaking, for which business, and what "done" means for
   this call.
2. **Known facts about this contact.** Name, what they already did, and the language. Each one
   carries "do not ask for this".
3. **Speaking rules.** At most about 8 bullets, positive, each with its reason (see the list
   below).
4. **Unclear input.** 3 bullets (see below).
5. **Hard compliance lines.** The truthful AI and recording answers and the confidentiality rule
   (hard rule 5, D-674). Unchanged in content. Give them their own `Guardrails` heading
   (ElevenLabs).
6. **Current task / steps.** Last, nearest the conversation. If ThinnestAI renders `steps` after
   `instructions`, the current task is already at the end. UNKNOWN; see E.

**Length.** No source supports a hard accuracy cap.
- What is supported: ElevenLabs flags latency and cost past 2,000 tokens. Retell cut 970 words to
  300 without losing function.
- IFScale shows a Flash-class model dropping from 96% to 82% between 50 and 100 instructions,
  mostly by omission.
- Recommendation (ours, grounded in those sources):
  - Count imperative sentences, not characters, and keep the platform rules to 25 or fewer.
  - Merge overlapping rules.
  - Move everything ThinnestAI can do as a setting out of prose.
- We send about 9k characters on top of the vendor's own text, which our code estimates at about
  4,700 characters plus about 1,675 of default call rules (VENDOR-STATED,
  `apps/api/engine/thinnest.py:300-309`).

**Speaking rules, as phrased**
- "Say one thing, then stop: one instruction or one question per turn, then wait." (Google, Vapi,
  LiveKit)
- "Keep each turn to one or two short sentences, because the caller hears it once and cannot
  skim." (ThinnestAI, OpenAI, Alexa)
- "Do not start two turns in a row with the same word or acknowledgement. Vary or drop the
  acknowledgement." (LiveKit, OpenAI Variety rule) This answers the acknowledgement that opened
  9 of 12 replies.
- "Never say the same sentence twice in a call. If you must ask again, ask it shorter and in
  different words." (OpenAI, Google No Match)
- "Speak everyday spoken Telugu, as people mix it: common English words such as app, phone,
  install and login stay in English. Say each name once." (CMI evidence; Google "plain, familiar
  words"). Do not add a ban list of textbook words: Vapi warns that lists prime the banned
  phrases.
- "Use what you already know about this person. Never ask for a detail listed under Known facts."
  (LiveKit, Google quantity maxim, Retell)

**Unclear-input rules**
- "If what the caller said is unclear, cut off, or does not answer your question, do not guess
  and do not move on. Ask once, briefly, in different words." (OpenAI "unintelligible" wording;
  Google rapid reprompt)
- "Treat a step as done only when the caller clearly says it is done or describes what they now
  see. 'Okay' or a fragment is not done." (OpenAI concrete exit criteria) This answers turns 15
  and 16 of 25 Nov.
- "After two unclear answers on the same point, offer a simpler route or a call back." (Google:
  2 attempts; Vapi: escalate after 2)

**Move into engine settings or native fields instead of prose**

| Behaviour | ThinnestAI field (mirror) | Note |
|---|---|---|
| Ordered steps, branches, required data | `steps[].title/detail/branches/collect`, 12 at most (`create-agent.md:886-891, 1226-1258`) | Steps do not count toward `instructions` (`agent/behaviour.md:42-47`) |
| Speaking rules | `voice.callInstructions`, 4,000 chars or fewer, REPLACES the built-in call rules, placed after `instructions` (`create-agent.md:1915-1927`; `channels/voice.md:330-357`) | Keep the vendor's two load-bearing lines: titles written in full, no brackets (`voice.md:341-352`) |
| Re-asking an unanswered question | `voice.reaskAfterSeconds`: 0 or 1.5–10 s, default 2.5 s (`create-agent.md:1561-1569`; `voice.md:811, 829-839`) | 2.5 s is shorter than any phone action takes; see E |
| "Are you still there?" | `nudgeAfterSeconds`, `nudges`, `nudgePhrase` (`create-agent.md:1854-1881`) | Vapi: 10–15 s, once |
| Fillers | `thinking`, `thinkingLines`, `thinkingDelayMs`, `thinkingRepeatMs`, `thinkingAtTurnEnd` (`create-agent.md:1467-1520`) | `thinkingAtTurnEnd` adds "a syllable in front of everything" (`:1514-1520`), so keep it off |
| Pause and end of turn | `turnDetection`: smart / timer / timer_v2 / ear (`create-agent.md:1521-1548`; `voice.md:1115-1150`) | `timer_v2` waits through mid-sentence pauses and digit groups |
| Listener words | `interruptWords`, `holdShortSpeech`; Ear-only `backchannelWords` and `acknowledgements` (`create-agent.md:1570-1580, 1723-1729, 1797-1832`) | |
| Opening timing | `openingWaitsForCaller`, `greetingUninterruptible` (`create-agent.md:1730-1746`) | 24 Nov: caller said "Hello" first |
| Recogniser hints | `vocabulary` (`create-agent.md:1833-1845`) | Held empty on purpose, D-948 |
| Language | Agent language fixed to te-IN rather than auto (`voice.md:557-570`) | |

---

## C. Checklist: our script writer (Pip)

**Call start**
- [ ] Opening: name the business, greet the known contact by name, and ask permission once
  ("is now a good time?"). The purpose sentence follows only after a yes, and never repeats the
  permission question. The 24 Nov call asked it twice.
- [ ] State the purpose once, in one sentence, with the time it takes.
- [ ] The first step's first line is a single question about the caller's current state, for
  example "is the app on your home screen?". It is not an instruction bundle.

**Step design**
- [ ] One step is one caller action or one question. Split any step whose line contains two
  verbs for the caller, or a condition plus an action. Turn 4 of 25 Nov broke this.
- [ ] Each step states its **done signal** as an observable caller statement: "caller says they
  see X" or "caller says Y opened". This follows OpenAI's "Exit when", concrete and minimal.
- [ ] For actions on the phone, the line ends with "tell me when it's done" and then waits. It
  must not ask "is it done?" in the same turn.
- [ ] The actor is right: the caller does things in their app. The agent never "notes" data the
  caller types into the app.
- [ ] Each step is a short directive with 0–2 sample phrases that are clearly marked as examples.
  OpenAI: models copy sample phrases closely.

**Branches**
- [ ] `when` describes a **caller state** ("already installed", "cannot find the button",
  "busy now"). It is never another step's name. Lint: refuse a `when` that equals a step title.
- [ ] Every step has a stuck path: one rephrase, then a simpler route or a call back (Google:
  2 attempts).
- [ ] Exits that belong to the opening ("not registered", "wrong person", "not now", "not
  interested") branch from step 1 or the opening. They never sit after Finalise.
- [ ] "Already done" skips forward.

**Field collection**
- [ ] `collect` lists only what this campaign must capture, at the step where it arises naturally.
- [ ] Never collect anything already on the contact record. Name and number are known on an
  outbound list (LiveKit, Google, Retell, Rasa).
- [ ] Do not collect opinion fields the conversation will not cover, such as comfort level,
  interest or another number. They invite fabricated values after the call.
- [ ] Outcome fields ("goal met") come from step completion, not from the model's impression.

**Language and register**
- [ ] Spoken Telugu with the everyday English loanwords kept as people say them. Each name or
  button label is said once, in one script, with no bracketed duplicate.
- [ ] One to two sentences per line, passing the one-breath test.
- [ ] No URLs read aloud: offer to send them by message (ThinnestAI guide).

---

## D. Checklist: evaluation scorecards

**Deterministic checks first** (no judge needed):
- turns containing more than one question or caller action;
- consecutive turns that open with the same acknowledgement;
- exact repeats of an agent sentence;
- a known field asked for;
- a step marked done with no caller utterance matching its done signal;
- a branch `when` that equals a step title;
- a bracketed duplicate name.

Every flag cites a turn index.

**Grounding check for after-call fields.** Every captured value must cite the caller turn that
supports it. With no supporting turn, the field reads "not discussed", never a guess. This answers
"Technical Comfort Level" and the false "expense recorded" on 25 Nov.

**LLM judge** (only for register, naturalness and script quality):
- one rubric criterion per score, form-filled, with evidence quoted before the score (G-Eval;
  Wang et al. multiple-evidence calibration);
- for A/B comparisons, run both orders and average (Wang et al.);
- penalise length explicitly rather than rewarding it (Zheng et al.: verbosity bias);
- use a judge model from a different family from the writer where possible (G-Eval: LLM judges
  favour LLM text; Zheng et al.: self-enhancement);
- calibrate against founder-labelled calls, and report agreement before trusting scores
  (Zheng et al.: 80% or more is the human–human level).

**Regression set.** A fixed set of scripted caller simulations: happy path, garbled reply,
"not now", wrong person, already done, stuck on a step. Rerun on every prompt or writer change,
because single calls do not show probabilistic regressions (Vapi).

---

## E. UNKNOWNs and open questions

1. **How ThinnestAI renders `steps`.** UNKNOWN whether it is a state machine with step tracking
   or prompt text, and where in the prompt it sits relative to `instructions` and
   `callInstructions`. The mirror describes only the schema (`create-agent.md:1226-1258`). Ask
   the vendor. This decides whether "current step last" is achievable.
2. **Whether the re-ask timer caused the early "is it done?".** Unverified hypothesis that it
   caused the early "is it done?" and the word-for-word repeat on 25 Nov (turns 16, 23). The docs
   say the re-ask is "in its own words" (`voice.md:833`), which contradicts a verbatim repeat.
   Check the agent's published `reaskAfterSeconds` (`apps/api/engine/publish_view.py:214`) and the
   call timeline before changing anything.
3. **Flash-Lite instruction capacity.** UNKNOWN. IFScale tested only gemini-2.5-flash-preview,
   and on keyword constraints, not dialogue behaviour. Our own count of imperative sentences per
   turn is unmeasured.
4. **Which recogniser hears Telugu on our calls.** UNKNOWN for each `turnDetection` mode, as is
   its Telugu WER. Our code records Sarvam saaras:v4 under Ear as VENDOR-STATED (`thinnest.py:386`).
5. **Outbound call openings.** No primary source found on permission, purpose, "not now", wrong
   person or objection handling. The script rules in C come from conversation-design sources,
   not call-centre outcome studies.
6. **Telugu-specific ASR error patterns** (short replies, English UI words): no primary source
   found.
7. **Whether the 25 Nov call ended at a test-call cap.** UNKNOWN; it ended at 3:08.
8. **One rule or several copies.** LiveKit says reinforce rules across sections; Retell and
   ElevenLabs say state them once. Unresolved; test it on the regression set.
9. **Google's conversation-design pages.** They are from a product deprecated on 13 Jun 2023. The
   guidance is generic and still published, but Google no longer maintains it.
