# Openings and call flow for Pip's script writer (21 Nov 2026)

The failure this answers (Varsha, Rytu Khata app-setup campaign for registered farmers, te-IN,
20-21 Nov 2026): the opening said only "Hello, I am from Rytu Khata, can you talk now?", with
no agent name and no reason. The first step then greeted again, asked again whether now
suits, and said "you gave your name in the app" before saying why it called. The person asked
"who are you, what name?" and hung up.

Evidence classes (CLAUDE.md hard rule 11): **VVD** is the vendor's or author's own published
guidance, read at the URL. **VENDOR-DATA** is a vendor's own figures, with no published
method. **3P** is a third party's practice guide. Every source was read on 21 Nov 2026.

## 1. What the sources say

| # | Practice | Source | Class |
| - | - | - | - |
| P1 | A placed call opens by saying who is calling, from which company and why, before anything else. In the outbound service script, the agent introduces themselves and the company, addresses the customer by name, then gives the reason for the call. Questions, scheduling and a recap close follow. | servicetitan.com/guides/contractor-playbook/outbound-call-scripts ("Recurring Services" script) | 3P |
| P2 | Stating the reason for the call gives a "2.1x higher success rate". A bare "did I catch you at a bad time?" scored 2.15%, the lowest opener tested, against 11.18% for a permission opener that says what the call is. | gong.io/blog/cold-call-stats (modified 4 Mar 2026); gong.io/blog/the-best-and-worst-cold-call-openers-backed-by-data-from-300m-calls | VENDOR-DATA |
| P3 | "Prompt the user with only a single question at a time"; "Don't ask the user a question if you're not prepared to handle their answer". | developers.google.com/assistant/conversation-design/questions (updated 2024-09-18) | VVD |
| P4 | Explicit confirmation "Requires a response from the user". Use it "sparingly, only when the cost of misunderstanding the user is high". Implicit confirmation, which restates and moves on, is the default. | developers.google.com/assistant/conversation-design/confirmations (updated 2024-09-18) | VVD |
| P5 | Error recovery: the first reprompt is short (an apology and a condensed question). The second adds help. Never repeat the original prompt word for word. Stop after a small number of failures. | developers.google.com/assistant/conversation-design/errors | VVD |
| P6 | Keep a turn short enough to be "read out by a human in one or two breaths", with breaths between ideas, not inside them. | developer.amazon.com/en-US/alexa/alexa-haus/design-principles/be-brief | VVD |
| P7 | Prompts: state the constraints, say what to do and what not to do, ask for the response format, and split complex work into one prompt per instruction. Use structured output for complex JSON. | aistudio.google.com/docs/prompting-strategies (formerly ai.google.dev/gemini-api/docs/prompting-strategies; Gemini is the writer's primary model, D-899) | VVD |
| P8 | A validator's exact error sent back to the model fixes the output more often than drawing a fresh sample. | Self-Refine, arxiv.org/abs/2303.17651; Instructor reask, python.useinstructor.com/concepts/retrying (both already cited in `apps/workers/opening_line.py`) | Academic / 3P |

None of these sources gives a character count for an opening. P6 is a breath test, not a
length. Gong's figures come from its own call corpus with no published method, so they back
the order of the opening (reason before the question), not a number.

## 2. What it means for the writer

1. **A placed-call opening has three parts, in this order: who, why, then the question**
   (P1, P2, P6). Who is the agent's name and the business, in one short sentence. Why is
   the call's one reason, taken from the campaign's main task or the agent's
   outbound_purpose, in the next short sentence, without the names again. Then one question:
   can they talk now. Each sentence ends with a full stop so the voice pauses between ideas
   (P6). The question comes last so the person knows it is their turn (`QUESTION_END_RULE`).
   When the engine's AI introduction already said who is calling (`introduced`, D-865), the
   opening is only the reason and the question.
2. **The writer was never told the agent's name.** `ScriptBrief.user_message` printed the
   business name but not the agent's, so no prompt could produce "I am Varsha". The brief
   now carries it.
3. **A check that does not depend on the language** (P8). We cannot tell from a Telugu line
   whether it carries the reason the English main task gives without a second model call. So
   the check tests the opening's structure. On a placed call, the agent's name must appear
   as written (the only spelling we can match). There must also be a sentence before the
   question that is neither a greeting, nor a notice, nor a sentence with a name in it: that
   is where the reason goes. The bare Varsha line fails both checks. A line that merges who
   and why into one sentence fails too, and is sent back to be split into short sentences,
   which is the shape we want anyway. What the check cannot see is whether that sentence is
   really the reason. The writer instruction and the opening writer ask for it explicitly.
   That gap is stated here rather than hidden.
4. **Length.** Who, why and a question do not fit the 120-character opening cap in Telugu.
   The reviewed starter line (`spoken_style.json`, te-IN `outbound`) is already 87
   characters with no agent name, no lead name and no reason. A placed-call opening
   therefore gets 160 characters. Its total with woven notices stays inside the 200 the
   answering opening already reaches (`opening_notices.WOVEN_*`). The engine's own ceilings
   are still measured at save and publish. This is a cost decision: about 40 more characters
   per placed call.
5. **The steps follow the purpose, starting from the person's yes** (P3, P4). After the
   opening come: the person's situation, asked rather than stated, branching on the answer
   (P3: ask only what you can handle); the steps one at a time; a check that it is done (an
   explicit confirmation, P4, because a half-finished setup is costly to miss); and a close
   on the one next step (`CLOSING_STEP`). No step greets again or asks again whether now
   suits. `call_rules.opening_redone_line_problems` (0.4.91) already checks that, and this
   work builds on it.
6. **Error recovery is not the writer's job.** P5 belongs to the in-call prompt (budget
   full, `calevate_shared/engine.py`) and to the situational-branches lane (busy, wrong
   person, does not remember). This work leaves it there.
7. **Keep the writer's instruction small** (P7): one sentence for the order of the steps,
   and the opening rule stated once (`call_rules.OPENING_LINE_RULE`), not again in every
   prompt.
