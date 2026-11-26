# 03 — External research for the call-script rebuild

All sources read on **26 Nov 2026**. Quotes are 15 words or fewer. For web pages, the quote comes
from the fetch tool's extraction of that page. The ThinnestAI mirror and the Bali (2009) PDF were
read directly. Evidence classes:
- **VENDOR-PUBLISHED**: a vendor's own documentation.
- **PAPER**: a paper's abstract, or for Bali (2009), its full text.
- **REPORTED**: seen only in a search snippet, not read.
- **UNKNOWN**: not found.

Only the abstracts of the arXiv papers were read, not the full papers. The figures below are the
abstracts' own figures.

---

## Part A. Findings

### 1. How voice-agent platforms structure prompts for multi-step guided calls

**ThinnestAI, our engine (mirror `thinnest-findings/mirror/snapshots/2026-11-26/pages/`, VENDOR-PUBLISHED)**

**A conversation script is a separate, structured field.**
- `agent/behaviour.md:45-47`: there are "up to 12 steps, each with an 80-character title and a 600-character detail". Steps do not count toward the instructions.
- The instructions can be up to 20,000 characters (`:44-45`). They are sent "to the model on every reply", so length costs money on every turn (`:43-44`).
- In the API (`api-reference/agents/create-agent.md:1225-1258`), each step has `title`, `detail`, `branches[{when, action}]` and `collect[]`. `collect` means "What must be in hand before the step is done".
- The mirror does **not** say how steps are presented to the model at runtime: whether the whole script goes in at once or only the current step, and how progress through the steps is tracked. That is UNKNOWN.

**Spoken-style rules** (`guides/how-your-agent-sounds.md`):
- Lead with the real answer (`:16-37`).
- Keep replies to one or two sentences (`:59-66`).
- Never describe things the caller cannot see. The guide's example is "no buttons… no 'click here'" (`:80-84`).
- Let people finish: "Silence is them thinking, not them finishing" (`:98-101`).
- A model that follows instructions loosely is a reason to change the model (`:166-169`).
- Test by deliberately interrupting, and by saying half a sentence and pausing (`:189-199`).

**Ordered questions:** the survey guide asks the questions "in this order, one at a time, and wait for each answer" (`guides/survey-agent.md:73`).

**Pre-release testing:**
- Test chat with `"mode": "call"` uses the agent's call prompt and the model its calls use. It "shows the words a caller will be given" (`agent/custom-api.md:132-138`).
- It does not test the voice, the hearing, or the in-call tools (same page).

**Mid-call or post-call decisions:** the AI decides block in Workflows offers "Review decisions" with a confidence bar that is calibrated from human marks. At least ten marked answers are needed before a bar is offered (`agent/workflows.md:319-330`).

**Retell AI (VENDOR-PUBLISHED)**
- Prompt engineering guide (docs.retellai.com/build/prompt-engineering-guide):
  - Its worked example rewrites a prompt of about 970 words down to about 300.
  - It asks for date, time and party size "one question at a time", with a wait marker after each.
  - "State each instruction once by default."
- Conversation-flow best practices (docs.retellai.com/build/conversation-flow/best-practices):
  - Split a task into nodes only to reduce context or to limit which tools are available.
  - "Keep the number of choices small" for transitions.
  - The global prompt holds the role. The node prompt holds only that node's task. Transition conditions say *when* to leave, not where to go.
  - Putting a later node's instructions in an earlier node makes the agent act on the wrong task.
- Subagent node (docs.retellai.com/build/conversation-flow/subagent-node): one node can hold a multi-turn conversation and use tools, so you do not need one node per question.

**Vapi (VENDOR-PUBLISHED, docs.vapi.ai/prompting-guide)**
- The prompt is split into sections, with step-by-step playbooks for each workflow.
- "Ask only one question at a time."
- On silence, wait about 10–15 s, check in once, then end the call.
- "Prefer a short positive principle over an exhaustive negative enumeration." The reason given is that long lists of banned phrases prime those phrases.
- "Never let a banned string appear elsewhere in the prompt as an example value."
- For unclear input: ask the caller to repeat. If it is still unclear after two attempts, offer a transfer.
- Few-shot transcripts: give at least three, covering the happy path, an edge case and an error recovery. "Without examples, the LLM interprets your instructions unpredictably."

**ElevenLabs Agents (VENDOR-PUBLISHED, elevenlabs.io/docs/agents-platform/best-practices/prompting-guide)**
- Use markdown sections, and put a Guardrails section at the top.
- Write multi-step tasks as numbered steps in the Goal section.
- The prompt "does not control conversation flow mechanics like turn-taking".
- Keep agents specialised: "Overly broad instructions or large context windows increase latency and reduce accuracy."
- Use an orchestrator that hands off to specialist agents.
- "If the user is frustrated, acknowledge their concerns before proceeding."
- Repeating the one or two critical instructions twice can help.
- The guide gives no guidance on how to write examples.

**Bland AI Pathways (VENDOR-PUBLISHED, docs.bland.ai/tutorials/pathways)**
- A call is a graph of nodes with labelled edges, plus a global prompt.
- Each node either has a prompt (generated text) or Static Text (the same wording every time).
- Loop conditions: "If the condition is not met, the agent will stay on the same node".
- There is a **Wait for Response** node type.
- Global nodes take precedence, and the call returns to the previous node afterwards.
- Testing includes per-node unit tests built from historical calls.

**Pipecat Flows (VENDOR-PUBLISHED, docs.pipecat.ai/guides/features/pipecat-flows)**
- A flow is "a graph of nodes"; each node focuses the LLM "on a single task with only the tools it needs".
- "monolithic prompts with many tools lead to hallucinations and lower accuracy".
- It is now part of core `pipecat.flows` (github.com/pipecat-ai/pipecat-flows README).
- The context strategies (reset / summary) were not read on these pages. They are UNKNOWN here.

**LiveKit Agents (VENDOR-PUBLISHED, docs.livekit.io/agents/build/workflows/)**
- Start with one agent. "Split workflows only when you encounter a concrete limitation." The limitations named are bloated instructions, multi-turn data collection, and users who need to backtrack.
- Tasks are short-lived and return a typed result.
- Task groups run an ordered sequence of tasks, let the user go back to earlier steps, and share context.

**OpenAI Realtime prompting guide (VENDOR-PUBLISHED, developers.openai.com/api/docs/guides/realtime-models-prompting; cookbook copy at developers.openai.com/cookbook/examples/realtime_prompting_guide)**
- Use labelled sections, including a Conversation Flow section of states.
- Each state has an exit condition. The guide's example is "Exit when: Intent and address … are known."
- The model copies sample phrases closely: "The model strongly closely follows sample phrases."
- The guide's prompt text: "DO NOT ALWAYS USE THESE EXAMPLES, VARY YOUR RESPONSES."
- The variety rule: "Do not repeat the same sentence twice."
- "Ask one question at a time." "Do not ask for multiple exact values in the same turn."
- Unclear audio: act "only … on audio it can understand with confidence", and "Don't repeat the same unclear-audio clarification twice."
- "Ambiguity or conflicting instructions = degraded performance".

**Google Gemini Live (VENDOR-PUBLISHED, docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/best-practices)**
- Structure the system instruction as persona, then conversational rules, then guardrails, with one agent per system instruction.
- State rules in the order the model should follow them.
- Separate one-time steps from loops the user can repeat.
- State the language explicitly in both the configuration and the system instruction.
- Instructions to speak faster or slower "don't reliably change the synthesized speaking rate".
- A search snippet adds that every turn bills the full context, including the system instruction (REPORTED; this was a snippet, not read on the page).

**Cross-vendor pattern (synthesis of the sources above)**
- **Structure.** Most vendors use either a graph of small task nodes (Retell, Bland, Pipecat, LiveKit tasks) or one prompt with an explicit ordered flow (OpenAI states, Vapi playbooks, ElevenLabs numbered goals).
- **One question per turn.** Retell, Vapi and OpenAI all say to ask one question at a time.
- **Stating when a step is done.** Each puts the condition in a different place: Bland loop conditions, OpenAI exit criteria, ThinnestAI `collect`.
- **Repetitive openers and fillers.** Only OpenAI writes explicit variety rules, and Google covers repeated acknowledgements (see §3).
- **Waiting ("tell me when it's done").** Bland has a Wait for Response node, Vapi checks in once after a silence, and ThinnestAI says silence is the caller thinking.
- **Confused callers.** Vapi says to repeat, then transfer after two attempts. OpenAI says not to repeat the same clarification. ElevenLabs says to acknowledge before proceeding.

### 2. Generating with an LLM: following many constraints, long contexts, decomposition, self-repair, judges and simulators

**Following many constraints at once**
- **IFScale** (Jaroslawicz et al., arXiv 2507.11538, Jul 2025): the benchmark scales up to 500 instructions. "even the best frontier models only achieve 68% accuracy" at the highest density. Models favour instructions that appear *earlier* in the prompt.
- **ComplexBench** (Wen et al., arXiv 2407.03978, NeurIPS 2024 D&B): when constraints are combined, "ComplexBench identifies significant deficiencies in existing LLMs."
- **FollowBench** (Jiang et al., arXiv 2310.20410, ACL 2024): adds one constraint per level, and performance weakens as constraints are added. Its constraint types include an "Example" type.
- **IFEval** (Zhou et al., arXiv 2311.07911, Nov 2023): built on about 500 prompts with 25 kinds of *verifiable* instruction that can be checked automatically. This is the template for programmatic checks.

**Long contexts**
- **Lost in the Middle** (Liu et al., arXiv 2307.03172, TACL): models do best when the relevant information is at the start or end of the input, and worst when it sits in the middle. "current language models do not robustly make use of information in long input contexts".
- **Same Task, More Tokens** (Levy, Jacoby, Goldberg, arXiv 2402.14848, ACL 2024): reasoning degrades "at much shorter input lengths" than the technical maximum.
- **LLMs Get Lost in Multi-Turn Conversation** (Laban et al., arXiv 2505.06120, May 2025):
  - Performance is about 39% lower on average in multi-turn conversations than in single-turn prompts.
  - Models make premature assumptions early and then rely on them: "they get lost and do not recover."

**Decomposed generation versus a single pass**
- **Re3** (Yang et al., arXiv 2210.06774, EMNLP 2022) runs plan → draft → rewrite → edit.
- Compared with a single pass on the same base model, human raters judged its stories coherent 14 points more often (absolute) and on-premise 20 points more often.
- Evidence that decomposition works for long structured documents comes from story generation. No study on generating call scripts was found (UNKNOWN).

**Self-refine and critique-repair loops**
- **Self-Refine** (Madaan et al., arXiv 2303.17651): generate → feedback → refine improved results by about 20% absolute on average across 7 tasks, including dialogue response generation.
- **LLMs Cannot Self-Correct Reasoning Yet** (Huang et al., arXiv 2310.01798, ICLR 2024): without external feedback, self-correction does not help on reasoning tasks and sometimes hurts. "LLMs struggle to self-correct their responses without external feedback".
- So repair loops need an *external* signal, such as a programmatic check, a separate judge, or a simulator outcome, rather than "check your own work".

**LLM-as-judge and simulated users**
- **MT-Bench / Chatbot Arena** (Zheng et al., arXiv 2306.05685, NeurIPS 2023): GPT-4-class judges agree with human preferences more than 80% of the time, about the level at which humans agree with each other. Judges show **position, verbosity and self-enhancement** biases.
- **τ-bench** (Yao et al., arXiv 2406.12045):
  - An LLM plays the user.
  - Success is judged on the end state of the database.
  - **pass^k** measures reliability as success on all k trials.
  - gpt-4o succeeds on fewer than half the tasks, and its pass^8 is below 25% in retail.
- **SimulatorArena** (Dou et al., arXiv 2510.05444, EMNLP 2025): simulators conditioned on a user profile reach a Spearman correlation of about 0.7 with human ratings.
- **Lost in Simulation** (Seshadri et al., arXiv 2601.17087, Jan 2026):
  - Success rates shift by up to 9 points depending on which LLM plays the user.
  - Results are systematically miscalibrated.
  - Simulators perform "worst for AAVE and Indian English speakers."

### 3. Conversation design for guidance over the phone

- **Chunk and check** (NHS Scotland Right Decisions, rightdecisions.scot.nhs.uk …/chunk-and-check, public-health guidance): give information in small pieces and check understanding after each piece. "don't ask "Do you understand?" because they may just nod or say yes!"
  - The AHRQ teach-back pages returned HTTP 403. Their content is REPORTED from search snippets only: ask open "explain it back" questions rather than yes/no.
- **Google conversation design: Confirmations** (developers.google.com/assistant/conversation-design/confirmations, VENDOR-PUBLISHED; this is the legacy Assistant guidance)
  - Use explicit confirmation rarely, for high-stakes or hard-to-undo steps.
  - Use implicit confirmation most of the time.
  - "Acknowledge that an action has been completed (unless it is self-evident)."
- **Google: Acknowledgements** (…/conversation-design/acknowledgements)
  - Starting every turn with "Okay" sounds robotic.
  - "Avoid overuse by adding randomization and by skipping some acknowledgements in dialogs."
  - A refusal gets a neutral acknowledgement, not "Sure" or "Got it".
- **Hindi discourse particles** (Kalika Bali, "F0 cues for the discourse functions of hā̃ in Hindi", Interspeech 2009, doi 10.21437/Interspeech.2009-742; PDF read directly)
  - In natural Hindi phone calls, *hā̃* ("yes") serves several discourse functions; one of them is agreement. Others are **backchannel**, literal yes, topic start, topic end and pivot.
  - The labels were annotated on 1,134 tokens from 12 mobile-phone conversations.
  - Implication: a caller's "yes" during an instruction is often a backchannel, *not* confirmation that the action is done.
- **Telugu backchannels and discourse markers:** no primary study was found in this pass. Telugu-specific data is UNKNOWN. A search surfaced an Indian-language disfluency paper covering Telugu (ACL Anthology 2024.wildre-1.1) and a Hindi backchannel-prediction dataset (arXiv 2101.01899). Both are REPORTED; neither was read.
- **Conversation analysis of human phone tech support** (Baker, Emmison & Firth 2005, seven phases including an instruction phase; Poole, Edwards & Jarvis, a CSCW study of HomeNet support calls): REPORTED only. The Georgia Tech PDF refused the connection and the book chapter was not reachable.

### 4. Evaluating voice scripts before release

**Retell** (docs.retellai.com/test/llm-simulation-testing, VENDOR-PUBLISHED)
- A test case has a user prompt (identity, goal, personality), success criteria graded pass or fail one at a time, dynamic variables, function mocks, and a choice of LLM for the simulated user.
- Limits: 10-minute timeout and 400 utterances. A run stops if the simulated user repeats itself or the agent goes silent.
- The simulated user and the agent are each billed per message.
- "Judge a scenario on its pass rate across runs, not one run."

**Vapi** (docs.vapi.ai/test/simulations-best-practices, VENDOR-PUBLISHED)
- A scenario is paired with a personality (tone, patience, interrupting, background sound).
- "Score the final result and important guardrails, not one exact route through the conversation."
- Use one iteration to set a test up, then at least five iterations before trusting a pass rate.
- Use chat mode to iterate and voice mode for final validation.
- "Synthetic callers do not fully represent real callers, devices, or environments."
- The overview mentions built-in confused and impatient personalities (REPORTED from a search snippet; the best-practices page does not name them).

**ElevenLabs** (elevenlabs.io/docs/eleven-agents/customization/agent-testing, VENDOR-PUBLISHED)
- Three test types: Simulation (multi-turn, 1–50 turns, default 5), Next Reply, and Tool Call.
- Runs from CI with `elevenlabs agents test <agent-id>`.
- `repeat_count` of 2–20 returns pass rates and groups the failures.
- Cost is not stated (UNKNOWN).

**ThinnestAI**
- Test chat in call mode gives text-level, single-turn-per-request testing of the call prompt (above).
- No native multi-turn simulator was found in the mirror (UNKNOWN beyond test chat).

**Cost and latency of these gates**
- Per-message billing is VENDOR-PUBLISHED for Retell only.
- No vendor publishes a per-test price or time on the pages read: UNKNOWN.
- Cost grows with turns × repeats × (agent + simulator + judge calls). That is arithmetic, not a published figure.

### 5. Examples ("few-shot") versus instructions, on the founder's direction

**Research**
- **Demonstrations mostly teach format and distribution, not correctness.** Min et al. (arXiv 2202.12837, EMNLP 2022): "randomly replacing labels in the demonstrations barely hurts performance". What the examples supply is the label space, the input distribution and the *format*. The model copies the surface form.
- **Copy bias.** Ali, Wolf & Titov (arXiv 2410.01288, Oct 2024): models "copy answers from provided examples instead of learning the underlying patterns."
- **Order and recency effects.**
  - Zhao et al. (arXiv 2102.09690, ICML 2021): the choice of examples and their order swing accuracy from near chance to near state of the art. Models are biased toward answers placed near the end of the prompt.
  - Lu et al. (arXiv 2104.08786, ACL 2022): "the order in which the samples are provided can make the difference". A good order for one model does not carry over to another.
- **Diversity helps.** Levy, Bogin & Berant (arXiv 2212.06800, ACL 2023): choosing examples that *together cover* the structures needed beats choosing only the most similar ones.
- **Retrieval helps.** Liu et al. (arXiv 2101.06804): examples retrieved for semantic similarity to the input beat random ones, by up to +41.9% on ToTTo and +45.5% on NQ.
  - Hu et al., IC-DST (arXiv 2203.08568, Findings EMNLP 2022): annotated *dialogues* retrieved as examples beat earlier few-shot dialogue-state-tracking methods.
- **Examples can override instructions and priors.**
  - Wei et al. (arXiv 2303.03846): large models follow contradictory in-context labels; "overriding semantic priors is an emergent ability of model scale".
  - Agarwal et al., Many-Shot ICL (arXiv 2404.11018, NeurIPS 2024): "many-shot learning is effective at overriding pretraining biases". Inference cost grows linearly with the number of examples.
- **The verbatim-repetition risk with a single example** is supported by the copy-bias and format findings above. No study measured specifically "one example leads to the same sentence on every call": that exact effect is UNKNOWN.

**Vendor prompting guides on examples**
- **OpenAI Realtime:** the model copies sample phrases closely. Its own sample-phrase block says not to always use them and to vary the responses. Its variety rule says not to repeat a sentence.
- **Vapi:** give at least three few-shot transcripts (happy path, edge case, error recovery). Never let a banned string appear as an example value. Long lists of banned phrases prime those phrases.
- **Anthropic** (platform.claude.com …/claude-prompting-best-practices, "Use examples effectively"):
  - Examples should be relevant and diverse, "vary enough that Claude doesn't pick up unintended patterns".
  - Wrap them in `<example>` tags so they are not read as instructions.
  - Use 3–5.
- **Google Gemini** (aistudio.google.com/docs/prompting-strategies):
  - "Use specific and varied examples".
  - Keep the format of examples identical.
  - With too many, the model "may start to overfit the response to the examples."
- **Retell:** examples are short and concrete, for example a spelled-out date to read aloud. The page has no guidance on copying.
- **ElevenLabs:** no guidance on examples in its prompting guide.
- **ThinnestAI mirror:**
  - No guidance on example dialogues was found.
  - Each step's `detail` is capped at 600 characters (`create-agent.md:1236`), so several example turns per step will not fit inside a step. They would have to live in the 20,000-character instructions.

**Learning examples from real calls**
- **Published practice:**
  - Bland builds per-node unit tests from historical calls.
  - Vapi recommends adding production recordings and manual calls to simulations.
  - IC-DST and Liu et al. show that *retrieving annotated* past dialogues as examples works.
- **No vendor page read describes automatically mining good turns from transcripts into live prompts.** That is UNKNOWN.
- **PII risk:** Duan et al., "Flocks of Stochastic Parrots" (arXiv 2305.15594): data placed in prompts can leak. Their membership-inference attack detects which records were used: "Our work first shows that these concerns are valid."
- **Reinforcing errors:**
  - Copy bias, plus the fact that intrinsic self-judgement is unreliable (Huang et al.), means a mined example nobody checked is reproduced faithfully, defects included. Selection needs an external check: human marks, or an outcome such as the step being confirmed done.
  - ThinnestAI's own calibrated Review-decisions bar (at least 10 human marks, conservative thresholds) is an in-house precedent for human-marked selection.
  - No primary source on drift from feeding generated calls back in was read (UNKNOWN).

---

## Part B. Implications for Calevate

These are recommendations, separate from the findings above. Each one cites the findings it
rests on.

1. **Generate the script step by step, not as one document.**
   - Plan the steps first, then generate each step's content against that plan, then run *external* checks and repair.
   - Rests on: Re3, §2; IFScale and ComplexBench, where more constraints in one pass means more misses; Huang, where self-checking alone does not help.

2. **Keep each in-call step small and state when it is done.**
   - Each step should hold one action, plus what the caller must report seeing before moving on (ThinnestAI `collect`).
   - Rests on: one question per turn (Retell, Vapi, OpenAI); exit criteria (OpenAI); loop until the condition is met (Bland); `collect` (ThinnestAI).

3. **Never treat "yes" or "haa" as "done".**
   - Confirm by what the caller sees on the screen, using an open question ("what is on the screen now?") rather than "did you do it?".
   - Rests on: Bali (2009), where *hā̃* is often a backchannel; NHS chunk-and-check, where people say yes without understanding; Google, use explicit confirmation only for steps that matter.
   - Telugu-specific evidence is UNKNOWN. A native-speaker review of Telugu backchannel words is an external input (the founder writes the Telugu wording).

4. **Treat waiting as its own behaviour.**
   - After "tell me when it's open", stay silent. Check in once after a pause. Do not re-instruct.
   - Rests on: Bland's Wait for Response node; Vapi's 10–15 s single check-in; ThinnestAI's "silence is them thinking".
   - Test it with the half-sentence-and-pause check (`how-your-agent-sounds.md:195-199`).

5. **Example-led prompting (founder direction), done the way the evidence supports.**
   - **(a) Several examples per step, never one.** Give at least 3 varied example turns. Vary the wording, the opener and the length, while the action stays the same. Rests on: copy bias; Min et al. (format is copied); Anthropic (3–5, diverse); Gemini (varied); Vapi (at least 3).
   - **(b) Mark them as examples and say to vary.** Wrap them in tags and add an explicit "these are examples; vary your words; never repeat a sentence" line. Rests on: OpenAI's sample-phrase and variety rules; Anthropic's `<example>` tags.
   - **(c) Show the right behaviour, not lists of forbidden phrases.** Use positive examples only. Never quote a forbidden opener or filler as a "don't say" example. Rests on: Vapi's warnings on banlist priming and banned strings as example values.
   - **(d) Include examples for difficult callers.** Cover confused, busy and stuck callers, as the edge-case and error-recovery examples. Rests on: Vapi (happy path, edge case, error recovery); OpenAI (do not repeat a clarification); ElevenLabs (acknowledge frustration).
   - **(e) Mind order and position.**
     - Keep the current step's examples next to its instruction.
     - Put the critical rules at the start or end, not the middle.
     - Rotate the order of examples between generated scripts rather than keeping one fixed order.
     - Rests on: Lost in the Middle; IFScale (models favour earlier instructions); Zhao and Lu (order and recency).
   - **(f) Budget the size.** Examples raise the cost of every turn, and long prompts degrade both reasoning and multi-turn reliability. Cap examples per step and measure.
     - The ThinnestAI step `detail` is 600 characters, so examples go in the instructions, inside the 20,000-character limit.
     - Rests on: ThinnestAI `behaviour.md:43-47`; Agarwal (cost grows linearly); Levy 2024; Laban 2025.
   - **(g) Examples will override rules, so they must themselves follow the rules.** Every example must pass the same checks as the script: spoken style, one action per turn, no screen words the caller cannot see, the notice rules. Rests on: Wei et al. and Agarwal (examples override priors); FollowBench (example constraints count as constraints).

6. **Mining examples from real calls is possible, but only with a human in the loop.**
   - Candidate turns come from transcripts, are taken only after **redaction** (hard rule 6 and the PII rules), and enter the prompt only after a **human mark** or an outcome signal such as the next step being confirmed.
   - Never include raw caller text.
   - Keep the mined set versioned so an example can be withdrawn.
   - Rests on: Duan et al. (data in prompts can leak); copy bias and Huang (unchecked examples are copied with their errors); IC-DST and Liu (retrieved examples work); ThinnestAI's Review-decisions precedent (at least 10 marks).
   - Fully automatic mining has no published vendor practice (UNKNOWN). Recommend against it until it has been measured.

7. **Gate release on simulated calls, read as pass rates.**
   - Run multiple personas: confused, busy, low-literacy, one who says half a sentence and pauses, one who interrupts.
   - Run each scenario at least 5 times and gate on the pass rate (pass^k-style), scoring outcomes and guardrails rather than one exact route.
   - Rests on: Vapi (at least 5 runs, outcomes not routes); Retell (pass rate across runs); ElevenLabs (`repeat_count`); τ-bench (pass^k).

8. **Do not trust the simulator alone for our callers.**
   - LLM simulators are least faithful for Indian English speakers, and Telugu was not studied.
   - Pair the simulation gate with real test calls (ThinnestAI test chat in call mode for wording, and real phone calls outdoors and with interruptions), and periodically calibrate the judge against human marks.
   - Rests on: Lost in Simulation; SimulatorArena (profile-conditioned simulators are better, about 0.7); Vapi ("Synthetic callers do not fully represent real callers"); ThinnestAI testing guidance.

9. **Use a separate judge with known biases, plus deterministic checks.**
   - Use rule checks (IFEval-style) for whatever can be verified mechanically: one action per turn, turn length, banned script elements, repeated openers across turns.
   - Use the LLM judge only for meaning. Randomise the order of what it compares, and do not use the generating model as its own judge.
   - Rests on: IFEval; MT-Bench (position, verbosity and self-enhancement biases).

10. **Price the gate before building it.**
    - No vendor publishes a per-test price or time. Our cost is turns × repeats × (agent + simulator + judge calls).
    - Measure it on one script before setting the persona count and repeat count. The current cost is UNKNOWN.
