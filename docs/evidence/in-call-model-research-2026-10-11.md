# In-call model research: natural Telugu on ThinnestAI, 11 Oct 2026

The question (founder, 11 Oct 2026): how do we make the agents perform at their best, and are
Gemini models the best for Telugu? This answers it against what we saw on real calls
(`in-call-model-trials-2026-10-11.md`, `specimen-call-raghava-2026-10-11.md`) and what
ThinnestAI allows.

Evidence classes: **VP** vendor-published, **IB** independent benchmark, **PAPER**, **ANEC**
anecdotal, **UNVERIFIED**, **INFERENCE** (ours). Sources were read on 11 Oct 2026. ThinnestAI's
live docs (docs.thinnest.ai) were reachable and newer than our 8 Oct mirror; a claim marked
"live" has no hash-pinned copy yet.

## 1. Is Gemini the best for Telugu?

**Partly supported, not proven.** No current, independent comparison of *spoken, colloquial*
Telugu across models exists. What exists measures written knowledge:

| Source | Class | Finding |
|---|---|---|
| MILU, AI4Bharat, arXiv 2411.02538 v1 | PAPER | Telugu: GPT-4o 70.5, Gemini 1.5 Pro 63.8, Llama 3.1 405B 58.4, Gemini 1.5 Flash 56.8, GPT-4o-mini 52.0. In the small tier Gemini Flash leads by about 5 points. 2024 models. |
| IndicParam, arXiv 2512.00333 v2 | PAPER | Gemini 2.5 Flash first in every language tested, ahead of GPT-5 and GPT-OSS 120B. Telugu and Hindi are not among them. |
| "Evaluating Telugu proficiency: ChatGPT vs Gemini", arXiv 2404.19369 | PAPER | Gemini better on grammar, idiom and cultural nuance. 20 questions, written, 2024. |
| OpenAI IndQA | VP | Includes Telugu; OpenAI says it is not a language leaderboard. Per-language scores UNVERIFIED. |
| Sarvam 105B (`sarvam-105b-conversations`) | VP | Tuned for colloquial Indic speech; reasoning can be switched off. No independent numbers; not offered by ThinnestAI. |

**INFERENCE.** The signal leans towards Gemini over OpenAI's small models for Indian languages,
which agrees with the founder. Our own calls are stronger evidence for this use: GPT-5 Nano
produced broken Telugu, GPT-4.1 Nano was natural, GPT-OSS 120B sounded best.

## 2. Can a model stop "thinking"?

A model that reasons first is slower to its first word, and on a platform that does not filter
its output the reasoning can be spoken. That is call A's "We should end? Caller may ask more."

| Model | Thinking fully off? | Source |
|---|---|---|
| Gemini 2.5 Flash | yes, `thinkingBudget: 0` | VP, ai.google.dev thinking page, updated 9 Oct 2026 |
| Gemini 2.5 Flash-Lite | yes, off by default | same |
| Gemini 3.x Flash / Flash-Lite | **no**: "do not support fully turning thinking off"; `minimal` errors on 3.8 Flash | same |
| GPT-4.1 family, GPT-4o-mini | never reason | VP |
| GPT-5 Nano / Mini | **no**: lowest is `minimal`, which still reasons | VP, openai.com |
| GPT-OSS 120B | **no**: effort is low, medium or high only | VP, OpenAI harmony cookbook |
| Prana, Prana [Voice] | UNKNOWN | ThinnestAI publishes nothing (vendor question 23) |

GPT-OSS writes its thinking to a separate `analysis` channel that OpenAI says must never be
shown to users and that the host must strip (VP, developers.openai.com cookbook
"openai-harmony"). ThinnestAI documents nothing about reasoning, effort or hiding it (live and
mirror). So whether a GPT-OSS call leaks depends on ThinnestAI's serving, which we cannot see
or control.

Time to first token (IB, Artificial Analysis medians, non-reasoning modes): Gemini 2.5
Flash-Lite 0.32 s, Gemini 2.5 Flash 0.51 s, GPT-4.1 Nano 0.73 s. GPT-OSS 120B's first
*answer* token comes after its reasoning: 1.6 s on the fastest host, 4-7 s on others.
ThinnestAI's console shows its own figures (GPT-OSS 120B ~221 ms, GPT-4.1 Nano ~578 ms) and
the API publishes none.

## 3. What ThinnestAI allows

- **ThinnestAI does not host Gemini.** It is absent from `GET /models` (mirror
  `api-reference/models/list-models.md:352-393`, and live).
- **Gemini runs only on our own Google key, under BYOK scope `all`.** There are two scopes,
  `voice` and `all`; there is no "our model, their speech recognition" mix
  (`api-reference/bring-your-own-keys.md:15-17`). Under `all` we must bring our own STT as well
  (Sarvam is a listed provider, `:110-111`). ThinnestAI then charges ₹1.00/min instead of ₹1.50
  (`:19-22`); Google, the STT vendor and Cartesia bill us separately. Any model the key reaches
  is allowed (`:30-32`). If a key fails the reply fails: there is no fallback (`:124-127`).
  Scope is per workspace, so one client's workspace can be moved alone (`:131-133`).
- **While the agent speaks our own Cartesia voice (scope `voice`), calls run only on** Prana,
  Prana [Voice], GPT-OSS 120B, GPT-5 Nano and GPT-4.1 Nano (`:44-58`).
- **Per-agent controls we do not send today** (`update-agent.md:549-559`): `temperature` (0-2)
  and `maxReplyTokens` (100-800). Unset, the vendor's "Balanced" answer style applies.
- **Turn-taking** (live): `turnSilenceSeconds` 0.2-3 s (null = 0.25 s); an end-of-turn mode
  (Smart / Timer / Ear) that is console-only; spoken fillers while the agent works
  (`thinking`, `thinkingLines`, `thinkingDelayMs` default 900 ms).
- **Knowledge search adds a pause on calls**: the agent "has to find the answer before it can
  start speaking" (`channels/voice.md:301-313`). Search on calls can be switched off when the
  instructions already cover what callers ask.
- **Voicemail checking delays the greeting** "up to four seconds" (`channels/voice.md:611-637`).
  `callStartUrl` is not asked on calls the agent places, so it does not delay an outbound
  greeting (live).
- **The built-in do-not-call cannot be switched off** ("works on every voice agent",
  `channels/voice.md:392-394`); it triggers on "don't call me", "remove my number" or similar in
  any language, not on "not now" (`:366-372`). Call B shows a weak model also fires it on
  "cut the call".
- **Own-key voice speed, volume and emotion are not in the API** (live and mirror). The Sonic
  version is per workspace (`credentials.model`, kind `tts`).

## 4. The voice (Cartesia, VP, docs.cartesia.ai, read 11 Oct 2026)

- Sonic 3.6 is current and supports Telugu.
- `generation_config.volume` 0.5-2.0 and `speed` 0.6-1.5; speed does not apply to Professional
  Voice Clones. **Emotion is English-only**, so it cannot help a Telugu agent.
- A clone takes the mood of its sample, is built from one language, and on Sonic 3.6 learns from
  up to 60 s (older models from the first 10 s). A quiet, flat or English sample gives a quiet,
  flat Telugu voice.

## 5. Conclusion

**The model and the platform around it are two separate problems, and most of today's bad
experience was the second.** The 2-3 s opening was voicemail checking, half a second of every
reply was the pause setting, the opt-out was ThinnestAI's built-in behaviour, the missing order
details were the script, and the quiet voice is the clone sample and console volume.

**Model ranking for natural spoken Telugu on a phone call (INFERENCE from §§1-3):**

1. **Gemini 2.5 Flash, thinking off.** Best-supported Indic signal, about 0.5 s to first token,
   thinking provably off, no announced shutdown. Available only under BYOK `all` with our own
   Google and STT keys.
2. **Gemini 2.5 Flash-Lite.** Faster (0.3 s) and cheaper; instruction-following on an order flow
   UNVERIFIED.
3. **GPT-4.1 Nano.** The best of the five our own-voice setup allows: it never reasons, so it
   cannot leak thinking, and its Telugu was natural on call B. Weak at following a multi-step
   flow without explicit steps.
4. **Prana / Prana [Voice].** ThinnestAI's own, fastest by their figures, Telugu and reasoning
   UNKNOWN; worth one test call.
5. **Not for calls:** GPT-OSS 120B (thinking cannot be switched off and leaked on call A), GPT-5
   Nano or Mini (still reasons; broken Telugu on call C), Gemini 3.x Flash (cannot switch
   thinking off).

GPT-OSS 120B sounded best to the founder, and its Telugu is genuinely good. The risk is not its
language but its reasoning reaching the caller, which only ThinnestAI can stop.

**Getting the best from whichever model runs (ours to build):**

1. Send `temperature` low (about 0.3) and a reply-length cap through the API instead of the
   vendor default. Telugu takes many tokens per word, so the cap must be tested on real turns
   before it is fixed.
2. Give every order or booking script explicit steps that collect each detail (product, quantity,
   price confirmation, name, address) one per turn, and read them back.
3. Put the facts callers ask most (products, prices, delivery areas) in the instructions so the
   agent answers without a knowledge search; keep search for the long tail. The instructions box
   is at 7,798 of 8,000 characters on Raghava's agent, so this needs room made first.
4. Separate "end this call" from "never call me again" in the prompt (being built), and keep
   the client's Restore for when the vendor's built-in do-not-call still misfires.
5. Keep voicemail checking off by default for outbound and say what it costs where it is offered.
6. Re-record the clone: 30-60 s of lively, level Telugu, cloned on Sonic 3.6, then raise volume
   in ThinnestAI's console and check it over a real phone line.
7. Settle the model with a blind ear test by native speakers (runbooks/in-call-model-ear-test.md,
   `scripts/compare_in_call_models`), with the same scripted caller lines on each model.

## 6. Decisions for the founder

- **Try Gemini?** It means BYOK `all` on one workspace: our own Google key and an STT key
  (Sarvam), ThinnestAI at ₹1.00/min plus Google, STT and Cartesia charges, no fallback if a key
  fails. It reverses D-750 ("free ThinnestAI models only") for that workspace. A trial on a
  test workspace answers it before any client moves.
- **Which model until then?** GPT-4.1 Nano is the safe choice under our own voice; GPT-OSS 120B
  sounds better but can speak its thinking.

**Founder's answers (11 Oct 2026):**

- Gemini: ask ThinnestAI first (question 26) before any BYOK `all` trial. D-750 stands.
- Raghava's agent stays on GPT-OSS 120B for now, accepting the risk of spoken reasoning at
  the end of a call.
- The seven improvements in §5 are documented, not built. They wait for ThinnestAI's answers
  to questions 23, 24, 26, 28, 29 and 33, which decide the model and which knobs exist; then
  they are built together. The do-not-call restore and the "end this call is not an opt-out"
  prompt line (item 4) were already in progress and continue.

## 6a. What Gemini would add per call minute (ESTIMATE)

Prices read 11 Oct 2026: Gemini paid tier per 1M tokens, 2.5 Flash $0.30 input / $2.50 output
(thinking included) / $0.03 cached input, 2.5 Flash-Lite $0.10 / $0.40 / $0.01 (VP,
ai.google.dev/gemini-api/docs/pricing); Sarvam speech-to-text ₹30 per hour streaming (VP,
sarvam.ai/api-pricing); ThinnestAI ₹1.00/min under scope `all` against ₹1.50 under `voice`
(VP, `bring-your-own-keys.md:19-22`). Rate used: ₹96.5 per USD (REPORTED, undated converter
page; the result moves little with it). Cartesia is ours under both scopes, so it is unchanged.

Token use per call minute is an ESTIMATE, not a measurement: the 7,800-character
instructions (about 2,500 tokens) are re-sent on every reply, plus tools and the growing
conversation, at about four replies a minute: about 14,000 input tokens a minute, 20,000 with
knowledge searches (each search is another model pass), and about 300 output tokens.

| Per call minute | 2.5 Flash-Lite | 2.5 Flash |
|---|---|---|
| ThinnestAI | −₹0.50 | −₹0.50 |
| Our speech recognition (Sarvam) | +₹0.50 | +₹0.50 |
| Gemini, 14k-20k input tokens | +₹0.15 to ₹0.20 | +₹0.48 to ₹0.65 |
| **Net change** | **about +₹0.15 to ₹0.20** | **about +₹0.50 to ₹0.65** |

Before GST and foreign-exchange charges. If ThinnestAI's calls hit Gemini's prompt caching
(UNKNOWN), the repeated instructions bill at a tenth and the Gemini line for Flash falls to
roughly ₹0.20 to ₹0.30.
A trial call's real token count, from the Google console, replaces the estimate.

## 7. Questions only ThinnestAI can answer

Added to `docs/vendor/thinnest-api-requests-2026-10-10.md` as questions 26-33.
