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
Flash-Lite 0.32 s, Gemini 2.5 Flash 0.51 s, GPT-4.1 Nano 0.73 s. Artificial Analysis
measures GPT-OSS 120B only at high reasoning effort on a 10,000-token prompt, which is not
comparable to how ThinnestAI runs it, so no figure is given for it here. ThinnestAI's console shows its own figures (GPT-OSS 120B ~221 ms, GPT-4.1 Nano ~578 ms) and
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

## 6a. What Gemini would cost per call minute, from public figures

The founder's two set-ups (11 Oct 2026), which need ThinnestAI to add a scope (question 26):

- **Clear + Gemini**: ThinnestAI's speech recognition and voice, Gemini on our Google key.
- **Studio + Gemini**: ThinnestAI's speech recognition, Gemini on our key, Cartesia on our key.

Speech recognition and the voice are the same as today in each, so Gemini changes only the
model's cost and the model's share of the reply time.

**Prices** (VP, ai.google.dev/gemini-api/docs/pricing, read 11 Oct 2026), USD per 1M tokens:
2.5 Flash $0.30 input, $2.50 output (thinking included), $0.03 cached input; 2.5 Flash-Lite
$0.10, $0.40, $0.01. Implicit caching is on by default for Gemini 2.5 models, from 2,048 input
tokens on 2.5 Flash; the page lists no minimum for Flash-Lite and promises no hit rate
(VP, ai.google.dev/gemini-api/docs/caching). Rate: ₹96 per USD (REPORTED: FBIL was 95.2 on
3 Jul 2026 and about 95.6-96.8 in May-June; no October figure found). The answer moves by
about 1% per rupee.

**Tokens.** A Gemini token is "about 4 characters" of English (VP, ai.google.dev/gemini-api/
docs/tokens). Gemini uses the Gemma 3 tokenizer (REPORTED, a port of Google's SDK), which a
community benchmark puts at 3.38 tokens per word across 22 Indian languages (REPORTED).

| Context the model reads on every reply | Tokens |
|---|---|
| Our instructions, 7,798 characters (about 6,000 English, 1,800 Telugu) | about 2,400 |
| Script steps, sent beside the instructions | about 500 |
| ThinnestAI's own call rules and tool definitions (unpublished; its replaceable rules box holds 4,000 characters) | up to about 1,500 |
| **System part, re-sent on every reply** | **about 4,400** |
| Conversation so far, from the three test calls | about 200-400 |

The three test calls ran about 4-5 agent replies a minute; a knowledge search or a tool call
(call B's do-not-call) is one more model pass. Taken as **5 passes a minute**: about 23,500
input tokens and 200-400 output tokens a minute (calls A and B averaged about 35 tokens a
reply, call C about 80).

| Gemini per call minute (before GST) | No cache hits | Cache hits on the system part |
|---|---|---|
| 2.5 Flash | ₹0.72-0.77 | ₹0.18-0.22 |
| 2.5 Flash-Lite | ₹0.23-0.24 | ₹0.05-0.06 (if Flash-Lite caches) |

**Prompt caching.** The system part is identical on every reply of every call of an agent, so
it is the ideal thing to cache. Google offers two kinds (VP, ai.google.dev/gemini-api/docs/
caching): implicit, on by default, charged at the cached rate when a request starts with a
recently seen prefix, with no hit rate promised; and explicit, where the fixed block is stored
once and every request points to it, so the cached rate is guaranteed, at $1.00 per 1M tokens
per hour of storage (about $0.0044, ₹0.42, an hour for one agent's 4,400 tokens). Neither is
ours to switch on: ThinnestAI builds the requests, so it decides (question 26).

What ThinnestAI would charge for either set-up is UNKNOWN until Ashutosh prices it. Today: ₹2.50
a minute for Clear on its own model (VENDOR-STATED), ₹1.50 for our voice with its model, ₹1.00
for all three keys ours (VP, `bring-your-own-keys.md:19-22`). Each set-up costs its new
ThinnestAI rate plus the Gemini line above, plus Cartesia for Studio as today.

**Reply time.** Only the model's share changes, by the same amount in both set-ups. Measured on
one basis (IB, Artificial Analysis medians, time to first token): Gemini 2.5 Flash-Lite 0.32 s,
2.5 Flash 0.51 s, GPT-4.1 Nano 0.73 s. Artificial Analysis measures GPT-OSS 120B only at
**high** reasoning effort on a 10,000-token prompt (1.61 s to the first answer token on its
fastest host), which is not how ThinnestAI runs it (its effort setting is unpublished), so that
figure is not comparable and is not used. ThinnestAI's console shows 221 ms for GPT-OSS 120B
and 578 ms for GPT-4.1 Nano, measured some other way. So Gemini is faster than GPT-4.1 Nano on
one basis; against GPT-OSS 120B as ThinnestAI runs it there is no like-for-like figure, and on
the calls the founder found GPT-OSS 120B quick. Not included: the round trip from
ThinnestAI's servers to Google (ThinnestAI's location is unpublished), and a few tens of
milliseconds to read our 4,400-token context.

## 6b. What Clear and Studio would cost us per minute with Gemini, by monthly volume

**Inputs, with their class:**

| Input | Figure | Class and source |
|---|---|---|
| ThinnestAI, Clear today (Premium band, its own model) | ₹2.50/min | VENDOR-STATED, console reading 6 Oct 2026 (memory 3c6810e9) |
| ThinnestAI, our voice with its model | ₹1.50/min | VP, `bring-your-own-keys.md:19-22` |
| ThinnestAI, all three keys ours | ₹1.00/min | same |
| ThinnestAI wallet top-up fee | 10% PAYG, 9% Pro | VENDOR-STATED (D-723) |
| ThinnestAI Pro plan | ₹2,499/month; PAYG holds at most 3 customer workspaces | console reading 6 Oct 2026; D-693 |
| Cartesia plans | Pro $5 / 100K chars, then $65 per 1M; Startup $49 / 1.25M, then $45; Scale $299 / 8M, then $38; 1 credit = 1 character | VP, cartesia.ai/pricing, read 11 Oct 2026 |
| Agent speech | 571 characters per call minute | measured over 3 production calls (D-728) |
| Gemini per minute | Flash-Lite ₹0.06 cached to ₹0.24 uncached; Flash ₹0.20 to ₹0.75 | §6a |
| Rate | ₹96 per USD | §6a |

**What ThinnestAI would charge for the two set-ups is unpublished.** It is bracketed, as an
INFERENCE from its own price steps: the step from all three keys ours (₹1.00) to our voice only
(₹1.50) is the value of its speech recognition and model together, ₹0.50. Taking only the model
away therefore leaves Studio + Gemini between ₹1.00 and ₹1.50, and Clear + Gemini between ₹2.00
and ₹2.50. **Conservative** = top of the bracket and no Gemini caching; **best** = bottom of the
bracket with caching.

Plan per row: up to 1,000 minutes on PAYG (3 clients or fewer); above that ThinnestAI Pro,
whose ₹2,499 is spread over the minutes; Cartesia on whichever plan is cheapest at that volume.
Not included: phone number rental, GST, and ThinnestAI's Scale plan (5% lower rates, 8% fee,
₹4,999), which would lower the 25,000 and 50,000 rows a little.

| Minutes a month | Cartesia per minute (plan) | Clear + Flash-Lite | Clear + Flash | Studio + Flash-Lite | Studio + Flash |
|---|---|---|---|---|---|
| 1,000 | ₹3.42 (Pro) | ₹2.26-2.99 | ₹2.40-3.50 | ₹4.58-5.31 | ₹4.72-5.82 |
| 5,000 | ₹2.33 (Startup) | ₹2.74-3.47 | ₹2.88-3.98 | ₹3.98-4.71 | ₹4.12-5.22 |
| 10,000 | ₹2.40 (Startup) | ₹2.49-3.22 | ₹2.63-3.73 | ₹3.80-4.53 | ₹3.94-5.04 |
| 25,000 | ₹2.06 (Scale) | ₹2.34-3.07 | ₹2.48-3.58 | ₹3.31-4.04 | ₹3.45-4.55 |
| 50,000 | ₹2.07 (Scale) | ₹2.29-3.02 | ₹2.43-3.53 | ₹3.27-4.00 | ₹3.41-4.51 |

Each cell is best-conservative. The 5,000 row is above the 1,000 row for Clear because Pro's
₹2,499 is spread over few minutes there.

For comparison, today at PAYG: Clear on ThinnestAI's own model ₹2.75 a minute; Studio ₹1.65
plus Cartesia. Rate card (D-728): Clear ₹4.50, Studio ₹6.00.

## 6c. The founder's two tiers, both on our own Gemini key (12 Oct 2026)

The founder's definition: **Clear** = ThinnestAI speech recognition + our Gemini + ThinnestAI
voice; **Studio** = ThinnestAI speech recognition + our Gemini + our Cartesia voice. Neither is
built by ThinnestAI yet (Ashutosh, 12 Oct 2026).

Inputs and their class:
- ThinnestAI, Studio set-up: ₹1.00/min on every plan (Ashutosh, 12 Oct 2026, VENDOR-STATED).
- ThinnestAI, Clear set-up: **not priced**. Ashutosh: "the cost wont differ much, cause LLM don't
  cost us much", negotiable with a monthly minimum. Taken as today's Premium-band ₹2.50
  (VENDOR-STATED, 6 Oct console); the studio band would be ₹3.00.
- Top-up fee 2.36% on every plan (VENDOR-STATED, 12 Oct 2026), on the ThinnestAI part only.
- Gemini per call minute, no caching (ThinnestAI says implicit caching did not hit for them):
  2.5 Flash-Lite ₹0.23-0.24, 3.1 Flash-Lite ₹0.59-0.62 (§6a token method; Google prices read
  11-12 Oct 2026; ₹96 per USD). 3.1 Flash-Lite's minimal thinking adds tokens not counted.
- Cartesia at 571 characters a call minute, cheapest plan for the volume: ₹3.42 (1,000 min),
  ₹2.33 (5,000), ₹2.40 (10,000), ₹2.06 (25,000), ₹2.07 (50,000) (cartesia.ai/pricing, 11 Oct 2026).
- Rate card (D-728): Clear ₹4.50, Studio ₹6.00. No GST charged (D-728).

Not in the per-minute figures: ThinnestAI Pro, ₹2,499 a month once there are more than three
clients; phone number rental; GST on vendor bills.

**Cost to us per minute and margin**

| Minutes a month | Clear + 2.5 FL | Clear + 3.1 FL | Studio + 2.5 FL | Studio + 3.1 FL |
|---|---|---|---|---|
| 1,000 | ₹2.79 (38%) | ₹3.16 (30%) | ₹4.68 (22%) | ₹5.05 (16%) |
| 5,000 | ₹2.79 (38%) | ₹3.16 (30%) | ₹3.59 (40%) | ₹3.96 (34%) |
| 10,000 | ₹2.79 (38%) | ₹3.16 (30%) | ₹3.66 (39%) | ₹4.03 (33%) |
| 25,000 | ₹2.79 (38%) | ₹3.16 (30%) | ₹3.32 (45%) | ₹3.69 (39%) |
| 50,000 | ₹2.79 (38%) | ₹3.16 (30%) | ₹3.33 (45%) | ₹3.70 (38%) |

Clear = 2.50 × 1.0236 + Gemini; Studio = 1.00 × 1.0236 + Gemini + Cartesia. Margin = (price −
cost) / price.

**Gross profit a month, before Pro's ₹2,499**

| Minutes a month | Clear + 2.5 FL | Clear + 3.1 FL | Studio + 2.5 FL | Studio + 3.1 FL |
|---|---|---|---|---|
| 1,000 | ₹1,706 | ₹1,336 | ₹1,321 | ₹951 |
| 5,000 | ₹8,530 | ₹6,680 | ₹12,057 | ₹10,207 |
| 10,000 | ₹17,060 | ₹13,360 | ₹23,414 | ₹19,714 |
| 25,000 | ₹42,650 | ₹33,400 | ₹67,035 | ₹57,785 |
| 50,000 | ₹85,300 | ₹66,800 | ₹133,570 | ₹115,070 |

What moves these:
- Every ₹0.25 ThinnestAI takes off the Clear minute adds ₹0.25 (about 5.5 points) to Clear.
- Clear on the studio band instead of Premium: +₹0.51 a minute.
- Pinned facts at the new 3,000-character ceiling add about 750-1,000 tokens to every reply's
  input, about 20% more Gemini cost (+₹0.05 on 2.5 Flash-Lite, +₹0.12 on 3.1 Flash-Lite).
- If caching does hit: Gemini drops to ₹0.05-0.06 (2.5 FL) or ₹0.13-0.17 (3.1 FL).
- Risks outside the money: if our Google key fails mid-call the caller hears silence
  (Ashutosh, 12 Oct 2026); ThinnestAI says Gemini 2.5 is deprecated on 15 Oct 2026 while Google's
  page shows no shutdown date for 2.5 Flash-Lite (recheck before choosing it).

## 7. Questions only ThinnestAI can answer

Added to `docs/vendor/thinnest-api-requests-2026-10-10.md` as questions 26-33.
