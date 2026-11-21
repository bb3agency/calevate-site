# Ways out in Pip-written scripts: research for branch coverage (21 Nov 2026)

What happened. On the Rytu Khata calls of 20 and 21 Nov 2026 (agent Varsha, te-IN, placed
calls to registered farmers about setting up the app), the person said they did not remember
registering, and on another call said there was nothing for now and they would do it later.
The script had no step or way out for either. The agent carried on with its steps, and both
calls ended badly.

Evidence classes used here: VVD = the vendor's own documentation, read at the URL; VENDOR-DATA
= a vendor's figures about its own calls, with no published method; ACADEMIC = a paper (only
the abstract was read, as noted). Every page was read on 21 Nov 2026.

## 1. Practices

| # | Practice | Source | Class | What it means for our writer |
| - | - | - | - | - |
| 1 | Write explicit rules for the edge cases a call meets: "Wrong person or wrong number — apologise and end the call". A request for more information gets a brief answer, then the call returns to the question flow. Busy and call-back requests are left to the platform's call-back feature, with no prompt rules for them. | help.close.com/feature-guide/chloe/voice-agent-setup/chloe-prompt-training | VVD | Wrong person: a way out to `end`. Busy or later: route to the platform's call-back (`call_back` target), never describe a call back in the script's words. An off-topic question needs no branch: it is answered from the knowledge base and the same step goes on. |
| 2 | Write out the branching for each path. A guardrail gets a direct condition and action, for example "politely decline or end the call". Off-topic: redirect the first time, offer to wrap up the second, end warmly the third. Unclear input: ask again, then after two failures offer a person. | docs.vapi.ai/prompting-guide | VVD | A way out is a plain-English condition plus a target. The in-call prompt already holds the counted repair: two unclear replies then the account's follow-up (`engine._when_you_cannot_help_section`). So the writer does not restate it. |
| 3 | Repair escalates and stops: rephrase first, then give options or examples, and end after two failed attempts. Give the person a way out. Avoid vague promises, and don't suggest a retry later or on another device when that will not fix it. | developers.google.com/assistant/conversation-design/errors | VVD | "Stuck on a step" needs at most one other way to do it, then a way out (`call_back` or `hand_over`). Never loop the person through the same action. |
| 4 | "Don't ask the user a question if you're not prepared to handle their answer." Plan for the likely answers before asking. | developers.google.com/assistant/conversation-design/questions | VVD | Each step that asks something gets a way out for each likely answer that does not go on: no, not now, already done, a different phone. The opening asks whether they can talk, so the first step must handle "not now". |
| 5 | Say who you are and why at once. Gong reports that stating the reason for the call makes booking 2.1 times more likely. A timing objection is acknowledged ("I totally understand"), then met with "When is a better time for you?" | gong.io/blog/cold-call-objections | VENDOR-DATA (method not published) | "Who is this / I don't remember" is answered with who is calling and why, in one line, and then the step's question is asked again. "Not now" is acknowledged and handed to the call-back, never argued with. The 2.1x figure is reported, not used as a number anywhere. |
| 6 | Each kind of refusal has its own response. A question about the call is answered honestly, then the purpose is restated, then the agent asks to go on. A soft refusal gets a person now or a call back from one. Do not redial with the same agent by default after a refusal. | retellai.com/blog/ai-caller-refusal-human-handoff | VVD (vendor blog) | Refusals are separate branches with separate targets: not now goes to `call_back`, not interested goes to `end` after one short answer. Asking for a person and asking never to be called again are the platform's: the hand-over and do-not-call tools, whose rules are composed after every script. |
| 7 | An LLM planner writes a decision-tree task plan, and the dialogue paths are derived from that tree, which makes the task logic more diverse. | arxiv.org/abs/2410.14853 (DFlow, Du et al., 2024; abstract only) | ACADEMIC | A generator covers more paths when it is asked to plan the branches explicitly, not left to improvise them. So the writer gets a short checklist chosen by the kind of call, rather than "handle objections". |

## 2. What the platform already does, so a script must not write it

Read from the code on 21 Nov 2026:

- **Call back.** `engine.CALL_BACK_TIME_RULE` asks what day and time, says it back and books it. It is composed only when the account keeps call backs. A `call_back` branch target compiles to "Offer a call back", or to "Say the business will get back to them" where call backs are off (`call_script._target_action`).
- **Not interested.** `engine.VOICE_STYLE_GUIDANCE`: "Offer once, then close politely." In the writer rules this is `call_rules` `let_go`.
- **Asking for a person.** `engine.OWN_RULES_HANDOVER_RULE` and `_when_you_cannot_help_section`: hand over only on request, or say nobody is free.
- **Do-not-call.** The do-not-call tool rule in `_when_you_cannot_help_section`, used only when they ask never to be called again.
- **AI and recording questions.** `TRUTHFUL_ANSWER_DIRECTIVE`, hard rule 5.
- **Unanswerable or unclear.** Two tries, then the account's follow-up (`_when_you_cannot_help_section`).

These rules come after the script, and they say how to respond. They do not stop the script's
own step list (ThinnestAI `steps`) from going on to its next step. On the 20 and 21 Nov calls,
the step with no exit is what pushed on. So a way out to `call_back` or `end` adds the route
on the step itself. That route is what the writer must supply. It must not re-describe the
behaviour at the end of the route.

## 3. Decisions for the writer

- The checklist follows the kind of call (`campaign_script_ask.CALL_KINDS`), never one template for every business. Every placed call covers four situations: busy or later, wrong person, "who is this / I don't remember", and not interested. A guiding call adds three: already done, a different phone, and stuck. Booking, reminder and collection calls each add "no time suits / cannot now", routed to a new time or to `call_back`.
- Asking for a person, do-not-call, AI and recording questions, and off-topic questions get no branch. The platform's rules handle them at any point in the call.
- A writer check refuses a whole script for placed calls that has no way out to `call_back` (not now) or no early way out to `end` (not interested or wrong person). No platform rule removes the need, for the reason given in §2. In an edit, only a way out the model removed is flagged: a script the owner already had without one stays as the owner made it.
