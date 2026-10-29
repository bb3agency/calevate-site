# Prompt/script architecture, generation pipelines and evaluation for LLM phone voice agents (Indic, code-mixed) — as of Oct 2026

Read date for every source below: 30 Oct 2026. Evidence classes: VENDOR-DOCS (a vendor's own documentation, describing its own product or recommending practice), VENDOR-BLOG (vendor marketing/opinion), ACADEMIC (arXiv/ACL; peer review status noted where known), PRACTITIONER (third-party opinion), INFERENCE (mine, not sourced). Several pages were read through a summarising fetch tool, so short quoted phrases are as that tool returned them. Re-open the page before any of them goes into code or client-facing copy (hard rule 11).

## 1. What vendor voice-agent prompt guides recommend (structure, length, phrasing, flows vs single prompt, tool-grounded commitments)

### Takeaway
The vendors agree to a striking degree. Use a sectioned prompt (identity/persona → style → guardrails → context → workflow → examples/tools). Keep turns to one or two sentences and ask one question per turn. Keep the prompt short: ElevenLabs flags anything over 2,000 tokens, and Retell's thresholds are about 1,000 words or five functions. Start with one prompt and move to a flow or state machine only when the call really branches. Commitments should be grounded by tools: what is said happens only after a tool returns. That is done by describing the whole task ("done" includes saving and confirming) and by enforcing sensitive values server-side, not by long "do not" lists.

### Cited Findings
**Structure**
- ElevenLabs Agents (VENDOR-DOCS):
  - Markdown sections `# Personality`, `# Environment`, `# Tone`, `# Goal`, `# Guardrails`, `# Tools`, one instruction per line, tone defined once.
  - Models give the `# Guardrails` heading extra attention.
  - Mark critical steps "This step is important" and repeat only the one or two most important rules.
  - Source: [ElevenLabs prompting guide](https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide).
- Vapi (VENDOR-DOCS) recommends six sections:
  1. Identity & Personality, including an "identity lock" against persona changes
  2. Response Guidelines
  3. Guardrails, which override everything else and include prompt-extraction protection
  4. Context, runtime data injected via variables: current date/time, caller info, company info
  5. Workflow / Use Cases, with an intent router and per-scenario playbooks with explicit branches
  6. Examples: few-shot transcripts covering a happy path, an edge case and error recovery, including branches for tool results with zero, one or many results

  Source: [Vapi prompting guide](https://docs.vapi.ai/prompting-guide).
- OpenAI Realtime prompting guide (VENDOR-DOCS) uses these sections:
  - Role & Objective
  - Personality & Tone
  - Context
  - Reference Pronunciations
  - Tools
  - Instructions/Rules
  - Conversation Flow (states, goals, transitions)
  - Safety & Escalation

  It says to add domain sections such as Compliance and to drop unneeded ones. Source: [OpenAI Realtime prompting guide](https://developers.openai.com/cookbook/examples/realtime_prompting_guide).
- Sarvam Voice Agents (VENDOR-DOCS) uses five sections: Persona, Objective (what "done" looks like), Context (often from variables), Guardrails (must / must not), and Steps/workflow, including when to call tools. Source: [Sarvam system prompt](https://docs.sarvam.ai/voice-agents/build/system-prompt.md).

**Length**
- ElevenLabs: prompts over 2,000 tokens increase latency and cost. Split the agent into specialists or move reference material into a knowledge base. Source: [ElevenLabs](https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide).
- Retell's worked example cuts a prompt from about 970 words to about 300 by removing repeated rules and over-detailed step scripts. Start with the happy path and add failure handling only when there is evidence it is needed. Keep one brevity instruction, in the Speaking style section. Source: [Retell prompt engineering guide](https://docs.retellai.com/build/prompt-engineering-guide).
- Retell says single-prompt agents suit 1–3 functions and linear calls. Consider a Conversation Flow when the prompt exceeds about 1,000 words or uses more than 5 functions. Multi-prompt agents are deprecated and will be converted to flows after 02/01/2027. Sources: [Retell choose agent type](https://docs.retellai.com/build/choose-agent-type); [Retell deprecation notice](https://docs.retellai.com/deprecation-notice/2026/12-15_multi_prompt_agents). These are search-snippet level; the full pages were not opened.
- Sarvam: keep the first prompt short and refine it with the prompt checker ("AI review") and the test agent before adding complexity. Source: [Sarvam single-state agents](https://docs.sarvam.ai/voice-agents/build/single-state-agents.md).

**Turn-level phrasing**
- Vapi:
  - Answer in one or two sentences and offer at most two or three options.
  - Ask one question at a time: collect one field, confirm it, move on.
  - After answering, end the turn with a clarifying question so it does not stall.
  - Avoid "Long monologues instead of two options followed by a question", which the guide lists as an anti-pattern. This directly supports a two-choice close.
  - Read phone numbers digit by digit, spell out dates and money, and say times conversationally.
  - Use no visual formatting. Em-dashes and SSML behave inconsistently across TTS providers.
  - Use a fixed fallback line rather than guessing.

  Source: [Vapi](https://docs.vapi.ai/prompting-guide).
- OpenAI Realtime:
  - Prefer short bullets to paragraphs.
  - The model "closely follows sample phrases", so examples steer it strongly.
  - Add a variety rule to reduce robotic repetition.
  - Pin the output language if the model switches languages.
  - Write logic in words, not pseudo-code.
  - Capitalise key rules.
  - Small wording changes matter: swapping "inaudible" for "unintelligible" improved handling of noisy input.

  Source: [OpenAI](https://developers.openai.com/cookbook/examples/realtime_prompting_guide).
- ElevenLabs: TTS mispronounces digits and symbols. You can either have the LLM spell them out (the default, which "may occasionally fail") or use a platform normaliser, which is more reliable at a small latency cost. For tool inputs, give the format with an example, such as digits only for phone numbers. Source: [ElevenLabs](https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide).

**Declarative vs scripted; single prompt vs flow**
- Sarvam:
  - Describe the outcome and the rules rather than a line-by-line script, "since scripts break when the conversation leaves the expected path".
  - Declarative prompts still need specifics about what to collect and confirm.
  - Give one agent one goal.
  - Front-load the goal, guardrails and "done" condition.
  - Define unhappy paths: refusal, silence, wrong number, missing data.
  - Use a multi-state design only when the call genuinely branches into distinct phases.

  Source: [Sarvam single-state agents](https://docs.sarvam.ai/voice-agents/build/single-state-agents.md).
- Retell flows: start simple, give each job its own node (for example name and phone collection), and put transition logic in node conditions rather than in the prompt. Source: [Retell agent types](https://docs.retellai.com/build/choose-agent-type) (snippet level).
- A Retell community thread (PRACTITIONER, user-sourced) mentions "Flex Mode", which compiles a flow into one structured prompt at runtime. Unverified. Source: [Retell community](https://community.retellai.com/t/single-prompt-agent-vs-conversational-agent-which-do-you-prefer/3129).

**Tool-grounded commitments (stopping unconfigured promises)**
- Retell does not address hallucinated actions directly. It advises against patching with "do not" rules and says to state the full task, including what completion requires: for example, a date change means choosing the date, saving it and confirming it. In its example the agent speaks about success or failure only after the booking tool returns. Source: [Retell](https://docs.retellai.com/build/prompt-engineering-guide).
- Vapi:
  - Long negative banlists "can prime the banned phrases".
  - Do not treat the prompt as a security boundary; enforce sensitive values server-side.
  - Use atomic tools (`get_slots` and `book_slot` rather than one tool with a mode parameter).
  - Describe when to call a tool and when not to.
  - Give Transfer and Hang Up tools explicit descriptions; blank ones make the model avoid them.
  - Keep tool responses short.
  - When tool calls are unreliable, "the fix is usually the tool's description, not the prompt".
  - Use a configured `request-start` message for slow tools; it is more reliable than prompting the LLM to acknowledge.
  - Never name tool resource IDs in prose, because they leak into speech.
  - For CRM capture, call the tool as each field arrives.

  Source: [Vapi](https://docs.vapi.ai/prompting-guide).
- ElevenLabs: describe every tool parameter. When a tool fails, acknowledge it, retry, then escalate: "Do not guess or make up information." Source: [ElevenLabs](https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide).
- Sarvam government-services guidance: when the agent does not know, say so plainly and redirect to a human helpline rather than guessing. Source: [Sarvam docs index](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/use-cases/government-services/llms.txt) (snippet level).

### Inferences
- INFERENCE: Calevate's composition is already generator content plus server-enforced blocks (truthful answers, confidentiality, no markdown, digit-by-digit numbers). That matches the vendor consensus that hard rules belong in a dedicated guardrails block and in server-side enforcement, not only in the prompt.
- INFERENCE: The budget is the real risk. ThinnestAI's speaking rules are about 4,700 characters, roughly 1,200 tokens if English-like at about 4 characters per token. That figure is from the brief and was not re-measured here. The generator therefore has very little room before ElevenLabs' 2,000-token warning or Retell's 1,000-word threshold. The generator should target a hard token cap and drop repetition, since Retell cut 970 words to 300 by deleting repeats.
- INFERENCE: Prefer "describe what done means, plus tool-gated confirmation" over banlists for promise-safety. An example would be "a booking exists only after the booking action returns success; before that you may only say you will note the request". Pair it with a deterministic post-generation lint (section 3).
- INFERENCE: The per-trade step plans should be declarative goals with collect/confirm lists, as Sarvam advises, not verbatim lines. The opening line is the one place where a fixed script is defensible.

### Gaps
- Bland Pathways, Synthflow, Vapi Composer, Google Gemini Live and LiveKit/Pipecat prompt guidance were not read this session: UNKNOWN.
- The detailed body of the OpenAI Realtime guide (exact per-turn sentence limits, the JSON format for conversation-flow states, tool preambles) did not come through the fetch, because the page is about 2M characters of embedded audio: UNKNOWN beyond the section list above.
- The full Retell single-prompt and conversation-flow best-practice pages were not opened.

## 2. Indian-language specifics (prompt language, script of examples, code-mixing, numbers/dates, honorifics)

### Takeaway
No vendor guide read here says whether Indic voice-agent prompts should be in English or native script, and no paper read here tests that question for a voice agent. The academic evidence on input and instructions leans towards English (or translate-test, or code-mixed) instructions over native-language Telugu prompting. Romanized code-mixed instructions degrade LLM performance as code-mixing density rises. For speech output, a native-script step before TTS sharply cut errors on code-mixed Telugu in one TTS paper. That supports a pattern of English instructions plus Telugu-script example phrases, but it is an inference to be tested, not a finding.

### Cited Findings
**Prompt language**
- "Better To Ask in English?" (ACADEMIC, arXiv 2504.20022): English consistently outperforms all Indic languages on factual accuracy. Telugu falls in the low-performing group and Hindi in the moderate one. Source: [arXiv 2504.20022](https://arxiv.org/abs/2504.20022) (abstract/snippet level).
- Education-task study (ACADEMIC, arXiv 2504.17720): English prompts beat translated prompts on most tasks, with tutoring as the exception. Telugu scored lowest, at 49.7% against 70.9% for English, partly because one model does not officially support Telugu. Source: [arXiv 2504.17720](https://arxiv.org/pdf/2504.17720) (snippet level).
- arXiv 2603.18898 (ACADEMIC, 2026): longer tokenization of native-script input correlates with lower accuracy. Translation-based and code-mixed strategies narrow the gap to English. Source: [arXiv 2603.18898](https://arxiv.org/pdf/2603.18898) (snippet level; title not confirmed).
- HinTel-AlignBench (ACADEMIC, arXiv 2511.15183): average scores on a vision-language subset were Hindi 61.51, Telugu 62.53 and English 68.6. Source: [arXiv 2511.15183](https://arxiv.org/pdf/2511.15183) (snippet level).

**Code-mixed and romanized input**
- Indi-RomCoM (ACADEMIC, arXiv 2606.30790, 29 Jun 2026): LLMs consistently underperform on romanized code-mixed instructions, and performance falls as code-mixing density rises. The benchmark covers four unnamed Indic languages; Telugu is not confirmed. It does not directly compare native script with romanized text. Source: [arXiv 2606.30790](https://arxiv.org/abs/2606.30790).
- IndicTalk (ACADEMIC, arXiv 2607.23242): a 9-language persona-based multi-turn corpus with native-script and romanized code-mixed variants, evaluated with LLM-as-judge plus humans. It is a candidate source of test dialogues. Source: [arXiv 2607.23242](https://arxiv.org/pdf/2607.23242) (snippet level).

**Speech output**
- Praxy Voice (ACADEMIC, arXiv 2604.25441, TTS): on code-mixed Telugu, transliterating Latin-script input to native script before TTS cut LLM-WER from 0.80 to 0.14 in pilot results. The gain was smaller for Hindi. Source: [arXiv 2604.25441](https://arxiv.org/pdf/2604.25441) (snippet level).

**Vendor guidance**
- Sarvam (VENDOR-DOCS) says the prompt should state how to handle numbers, dates and code-mixing, but gives no rules, no script recommendation and nothing on honorifics. Source: [Sarvam system prompt](https://docs.sarvam.ai/voice-agents/build/system-prompt.md).
- Sarvam says its models understand code-mixing such as Hinglish and Tanglish. It suggests Saaras v3 STT with `language="unknown"` for auto-detection. Source: [Sarvam LiveKit guide](https://docs.sarvam.ai/api-reference-docs/integration/build-voice-agent-with-live-kit) (snippet level).
- A community guide (PRACTITIONER, edesy.in) has a prompt instruction to speak numbers in Indian format (lakhs/crores) for Hindi. Source: [edesy.in Hindi](https://edesy.in/docs/voice-agent/languages/hindi).
- OpenAI: pin the output language if the model drifts. Source: [OpenAI Realtime guide](https://developers.openai.com/cookbook/examples/realtime_prompting_guide).

### Inferences
- INFERENCE: Write the rules and structure in English, which is shorter in tokens and stronger on instruction-following per the papers above. Give a handful of sample phrasings in Telugu script, written the way callers actually code-mix (English nouns kept as English words). Pin the output language and script explicitly.
- INFERENCE: Avoid romanized Telugu in examples. Indi-RomCoM shows instruction-following degrades on romanized code-mix, and Praxy shows TTS errors drop with native script.
- INFERENCE: Because "the model closely follows sample phrases" (OpenAI), every Telugu example becomes near-verbatim output. Example phrasings must therefore be founder- or customer-approved, which matches the project memory that the founder writes the Telugu wording. Keep three or fewer per agent with a variety rule.
- INFERENCE: Honorific choice (for example the plural/respect form and "garu") should be a language-pack constant, not left to the generator.

### Gaps
- No primary evidence was found on Gemini Flash-Lite-class models specifically for Telugu output quality, or for Telugu-script vs transliterated few-shot examples in a prompt: UNKNOWN. This needs an in-house A/B (section 4).
- No source gave Telugu-specific number, date or currency read-out conventions: UNKNOWN.
- Honorific guidance: no source found.

## 3. Script-generation pipelines (from business info, vertical templates, self-critique, linting, caching layout)

### Takeaway
No public end-to-end "website → voice script → self-critique → ship" product with published results was found. The components are standard: summarise source content into voice-sized facts, use a strong model as prompt engineer to critique against failing transcripts, and use eval-driven optimisers. Two further practices are well supported. Lay the prompt out with static content first and per-call variables last, for Gemini implicit caching. Use deterministic checks rather than only LLM judgement.

### Cited Findings
- AWS prescriptive guidance (VENDOR-DOCS) describes a meta-prompt loop: a capable model acts as prompt engineer, reviews the prompt against failed examples, and proposes fixes. Source: [AWS prompt optimization](https://docs.aws.amazon.com/prescriptive-guidance/latest/gen-ai-lifecycle-operational-excellence/dev-experimenting-prompt-optimization.md) (snippet level).
- Tekmatix (VENDOR-BLOG) sells a prompt optimiser that tests a cloned agent against simulated chats so the production prompt is untouched. Source: [Tekmatix](https://tekmatix.com/blog/b/how-to-optimize-conversations-ai-prompts-tekmatix) (snippet level).
- Cekura (VENDOR-BLOG, May 2026) has a post on self-improving voice agents that diagnose failing evals and apply prompt fixes. Source: [Cekura prompt-engineering tag](https://www.cekura.ai/blogs/tags/prompt-engineering) (snippet level).
- A voice vendor (VENDOR-BLOG) warns against pasting scraped website content directly and recommends condensing it into voice-sized chunks. Source: [growwstacks](https://growwstacks.com/blog/how-to-build-voice-ai-prompts/) (snippet level).
- Sarvam ships a "prompt checker / AI review", a vendor example of an automated prompt lint. Source: [Sarvam](https://docs.sarvam.ai/voice-agents/build/single-state-agents.md).
- Gemini prompting strategies (VENDOR-DOCS):
  - Put essential behavioural constraints and output-format requirements in the system instruction.
  - Use one delimiter style consistently.
  - With long context, place specific instructions at the end.
  - Always include few-shot examples with identical formatting, but not too many, to avoid overfitting.
  - Gemini 3 should be "direct and precise", not persuasive, and defaults to concise answers.
  - For Gemini 3 Flash, add "Remember it is 2026 this year" to search-using prompts.

  Source: [Gemini prompting strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies).
- Gemini implicit caching (VENDOR-DOCS):
  - On by default for Gemini 2.5 and newer.
  - Minimum input is 2,048 tokens for 2.5 Flash and 2.5 Pro, and 4,096 for 3.x Flash/Pro and 4 Argon.
  - "Try putting large and common contents at the beginning of your prompt" and send similar-prefix requests close together.
  - Cache hits show in `usage.total_cached_tokens`.
  - No discount percentage is stated on the page.

  Source: [Gemini caching](https://ai.google.dev/gemini-api/docs/caching).
- Vapi: inject runtime data (date/time, caller and company info) as variables into a Context section. Long banlists prime the banned phrases. Source: [Vapi](https://docs.vapi.ai/prompting-guide).

### Inferences
- INFERENCE: The in-call prompt is assembled by ThinnestAI, with its rules plus ours, so whether the call LLM gets a prefix-cache hit depends on ThinnestAI's request layout and on whether the prompt reaches the model's minimum token count. Whether Flash-Lite is listed was not checked (see Gaps). In our own composition, keep the compliance blocks and language pack byte-stable and first, the generated business section next, and per-call variables (today's date and weekday in IST, caller name) last.
- INFERENCE: A defensible generator pipeline:
  1. Extract structured business facts (services, hours, prices only if the client stated them) into a typed schema.
  2. Fill a per-trade template: goal, collect/confirm list, value line, two-choice close, objection handlers.
  3. Run a deterministic lint:
     - token cap;
     - no unconfigured action verbs ("I have booked", "you will receive an SMS") unless the matching tool is enabled;
     - no prices or offers absent from the facts;
     - no stacked questions in example turns;
     - persona name equals the configured agent name;
     - no markdown;
     - none of the server-owned compliance text duplicated.
  4. Run an LLM rubric critique with one revision pass.
  5. Run the scripted-simulation regression (section 4) before publish.

  Steps 3 and 5 are blocking. Step 4 is advisory, because judges miss cross-turn issues (section 4).

### Gaps
- No published success rates for website-to-voice-script generators: UNKNOWN.
- Whether Gemini Flash-Lite variants are covered by implicit caching, and their minimum token count, was not on the parts of the page read: UNKNOWN.
- Whether ThinnestAI's request layout preserves a stable prefix: UNKNOWN. This is a vendor question.

## 4. Evaluation (simulated callers, judge rubrics, regression, A/B, metrics tied to booking)

### Takeaway
The established practice:
- Run simulated callers (persona plus goal plus decision tree) at volume.
- Score each run with a mix of deterministic end-state checks and LLM judges.
- Run a fixed regression set before every prompt or model change, blocking deploys against a last-known-good baseline.
- Turn every production failure into a test.

LLM judges are measurably unreliable on cross-turn errors and should be treated as a floor. No source read publishes a metric validated against booking or conversion rate.

### Cited Findings
**Change discipline**
- ElevenLabs:
  - Track task completion rate and escalation rate.
  - Find the failing prompt section or tool definition.
  - Change one thing at a time and re-test on the same cases, warning against "multiple prompt changes simultaneously".
  - Run regression simulations before deploying.
  - Benchmark two or three candidate models on your actual prompt.

  Source: [ElevenLabs](https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide).
- Vapi: single calls do not reveal probabilistic regressions, so run many scenarios per change. Measure the end-to-end success rate, and listen to calls, because TTS and turn-taking matter as much as words. Source: [Vapi](https://docs.vapi.ai/prompting-guide).

**Hamming (VENDOR-BLOG)**
- Test-suite mix: 40% happy path, 30% edge cases, 15% error handling, 10% adversarial, 5% acoustic.
- Size: at least 50 scenarios, 200+ for production.
- Regression set: at least 20 critical paths, 50 recommended.
- Every production failure becomes a test case.
- About 100+ observations are needed to detect a 5% change at 95% confidence.
- Regression tolerances: task completion ±3% and latency ±10%; block the deploy on regression.
- Targets: scheduling task success >90%, reprompt rate <10%, tool-call success >99% for booking.
- Failure-mode list includes "Agent talks over user repeatedly" and "Agent asks same question 3+ times".
- It makes no claim that any metric correlates with bookings or conversion.
- Source: [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents).

**Cekura (VENDOR-BLOG)**
- Auto-generates hundreds of scenarios from the agent description and knowledge base, with 6–7 assertions per test. The manual alternative is a library of 30–50 intents mined from real transcripts.
- Metrics: late-turn instruction following, barge-in handling, P95/P99 latency (voice-to-voice <1,500 ms), hallucination against the knowledge base.
- Judges are "strong on turn-local errors and weak on cross-turn state". It cites a June 2026 study in which a deployed agent's built-in judge caught 2 of 9 systematic problem patterns, and flagged 0 of 100 rounds where humans confirmed 23 defects. It recommends treating the judge as "a regression floor".
- That study's primary source was not located: REPORTED.
- Source: [Cekura](https://www.cekura.ai/blogs/voice-ai-evals).

**ServiceNow EVA (ACADEMIC/industry, HF blog, 24 Mar 2026)**
- Two scores:
  - Accuracy: deterministic task completion against the expected database state, faithfulness (LLM judge, grounded in instructions, policies, user input and tool results), and speech fidelity for codes and amounts.
  - Experience: conciseness, conversation progression without repetition or stalling, and turn-taking.
- Simulated users get a goal with an exact decision tree, a persona and TTS audio. Invalid simulations are regenerated.
- Across 20 systems no configuration led on both accuracy and experience.
- A large pass@3 vs pass^3 gap means agents that can succeed often do not succeed reliably.
- Source: [EVA](https://huggingface.co/blog/ServiceNow-AI/eva).

**Evaluating the evaluators**
- "Testing the Testers" (ACADEMIC, arXiv 2511.04133, v2 14 Jan 2026) collected 21,600 human judgments across 45 simulations to rate three commercial voice-testing platforms. A third party reports 86.7%, 75.7% and 62.7% evaluation accuracy. Those figures were not confirmed in the paper, and one author is affiliated with Evalion, a possible conflict. Sources: [arXiv 2511.04133](https://arxiv.org/abs/2511.04133v1); [ContextQA review](https://contextqa.com/blog/ai-voice-agent-testing-tools/) (PRACTITIONER).
- A Coval page cites the same paper with Coval 48.9 and Cekura 43.0. These numbers conflict with the third-party figures above and come from an interested vendor: unverified. Source: [Coval vs Cekura](https://www.coval.ai/blog/coval-vs-cekura/) (VENDOR-BLOG, snippet level).

### Inferences
- INFERENCE: A sales-call rubric for Calevate should split into two parts.
  - Deterministic (blocking):
    - disclosure sentences spoken when toggled;
    - no action claimed without a matching successful tool event in the trace;
    - extraction fields filled;
    - persona name consistent;
    - resolved dates equal the expected date computed in IST;
    - at most one question mark per agent turn;
    - no re-ask of a field already captured.
  - LLM-judged (advisory):
    - opener quality;
    - value line delivered;
    - qualification coverage;
    - two-choice close attempted;
    - objection handled without new promises;
    - conciseness.
- INFERENCE: Use pass^k (all k runs pass), not pass@k, for promise-safety scenarios, per EVA's consistency finding.
- INFERENCE: Telugu simulations need Telugu-speaking persona simulators and Telugu TTS for the caller. A text-only simulation will not exercise STT on code-mixed speech, the dominant error source per Praxy and Hamming's slot-error priority. A text-level suite is still the cheap first gate.
- INFERENCE: Correlation with booking must be measured in-house. Compare rubric scores with the CRM booking outcome per call, then A/B prompt variants on live traffic with at least ~100 calls per arm for coarse differences (Hamming's rule of thumb; a power calculation should replace it).

### Gaps
- No public study ties any voice-agent eval metric to booking or conversion rate: UNKNOWN.
- Retell, Vapi, Coval and Hamming product test-suite docs (exact features, Indic language support) were not opened: UNKNOWN.
- No Indic-language voice-agent eval benchmark was found. IndicTalk is a text corpus.

## 5. Failure modes and the prompt/tool patterns that fix them

### Takeaway
Each common failure has a documented mitigation:
- **Over-talking:** a one-or-two-sentence turn limit with two options followed by a question.
- **Stacked questions:** one field per turn.
- **Re-asking:** incremental capture plus a known-fields context, and loop detection in tests.
- **Hallucinated commitments:** a completion definition that requires a tool's success, plus server-side enforcement.
- **Wrong relative dates:** inject the current date and weekday, and better, a deterministic date-resolution tool. Benchmarks show in-context temporal arithmetic is unreliable and tool-augmented computation fixes most of it.
- **Persona mismatch:** an identity lock with a single source for the name.

### Cited Findings
- Over-talking and monologues: one or two sentences per turn and at most two or three options; long monologues are an anti-pattern. Source: [Vapi](https://docs.vapi.ai/prompting-guide). EVA scores conciseness separately and gives an overwhelming list of spoken options as a failure example. Source: [EVA](https://huggingface.co/blog/ServiceNow-AI/eva).
- Stacked questions: "Collect one field, confirm it, then move on." Source: [Vapi](https://docs.vapi.ai/prompting-guide).
- Re-asking and loops: Hamming defines a loop as the agent asking "same question 3+ times" and tests it with multi-turn memory tests. Vapi recommends using caller ID when available, calling the CRM tool as each field is collected, batch-confirming at the end, and correcting only the wrong field. Sources: [Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents); [Vapi](https://docs.vapi.ai/prompting-guide).
- Hallucinated commitments: state the full task including completion (save and confirm), speak about outcomes only after the tool result, and do not patch with "do not" rules. Source: [Retell](https://docs.retellai.com/build/prompt-engineering-guide). Enforce server-side; the prompt is not a security boundary. Source: [Vapi](https://docs.vapi.ai/prompting-guide). "Do not guess or make up information" on tool failure. Source: [ElevenLabs](https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide).
- Wrong dates:
  - Vapi puts the current date and time in a Context section. Source: [Vapi](https://docs.vapi.ai/prompting-guide).
  - Gemini docs advise stating the current year and knowledge cutoff for Gemini 3 Flash. Source: [Gemini prompting strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies).
  - SPAN (ACADEMIC, AAAI-26, arXiv 2511.09993): average LLM accuracy of 34.5% on cross-calendar temporal reasoning, with none above 80% and "Future-Date Degradation". A tool-augmented code-generation "Time Agent" reaches 95.31%. Source: [arXiv 2511.09993](https://arxiv.org/html/2511.09993v1) (snippet level). It is cross-calendar, not weekday resolution, so it is indirect evidence.
  - Kyriba (PRACTITIONER/VENDOR dev article): relative dates are especially hard for LLMs, and "on Monday" is ambiguous. Its fix is a deterministic date-computation tool. Source: [Kyriba](https://developer.kyriba.com/site/articles/temporal-logic-enhancement) (snippet level).
  - A practitioner note suggests attaching relative labels to candidate dates, for example listing "today = Thu 30 Oct, tomorrow = Fri 31 Oct, this Sunday = 2 Nov" in context, to reduce hallucinated day names. Source: [neura.market](https://neura.market/answers/llm-accurate-relative-days-of-week) (PRACTITIONER, unverified).
- Persona and identity drift: use an "identity lock" in the Identity section. Source: [Vapi](https://docs.vapi.ai/prompting-guide).
- Language drift: pin the output language. Source: [OpenAI Realtime guide](https://developers.openai.com/cookbook/examples/realtime_prompting_guide).
- Named-entity errors: a single misheard character, as in a confirmation code, can end the conversation. Use spell-back read-backs for exact data only, not for soft data like intent or interest. Sources: [EVA](https://huggingface.co/blog/ServiceNow-AI/eva); [Vapi](https://docs.vapi.ai/prompting-guide).

### Inferences
- INFERENCE: For Calevate, inject a per-call IST date table: today's date and weekday, plus resolved "tomorrow", "this <weekday>" and "next <weekday>" for the next 7–14 days, computed in `Asia/Kolkata` by our code. Place it at the end of the prompt (per-call variable, after the cacheable prefix). Where the engine supports a custom function, expose a `resolve_date` action, with the agent required to read back the absolute date and weekday before confirming. The two are complementary. Whether ThinnestAI supports per-call variable injection or custom functions needs checking against its docs snapshot in `snapshots/`. That was not checked here.
- INFERENCE: Name the persona once, from one configured field, in the identity section. The generator must never emit a name in example lines; the lint rejects any capitalised name not equal to the configured one.

### Gaps
- No primary source measured "two questions in one turn" frequency or a fix's effect size: UNKNOWN.
- No benchmark specifically on weekday-relative resolution ("this Sunday" vs "next Sunday") was found. Evidence is indirect (SPAN) or practitioner-level.
- Whether Gemini Flash-Lite in particular mis-resolves relative weekdays when given the date was not measured by any source: UNKNOWN. It should be added to the in-house suite.
