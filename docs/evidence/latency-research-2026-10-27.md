# Live-call latency: industry practice, what ThinnestAI lets us control, and a ranked plan (27 Oct 2026)

Brief: founder, 27 Oct 2026, "latency reduced by a lot on our live calls ... better conversions".
This is research and a plan only. No repo code was changed.

It builds on, and does not redo:
- `docs/evidence/latency-research-2026-10-21.md` (21 Oct report);
- rememory 5a3acfa9, 688797e1, 0d9429bf, 3a6a2e08 (ThinnestAI §25), 4c8af4fc, 84048b66, c79138bf, 87e54215, 530cc6d6, 35a5ccdb.

Evidence classes:
- **VVD**: VERIFIED-VENDOR-DOCS, read this session.
- **VS**: VENDOR-STATED, by email.
- **VP**: VENDOR-PUBLISHED (blog or marketing).
- **REPORTED**: a third party.
- **MEASURED**: our own calls or curl.
- **ESTIMATE**: arithmetic on cited inputs.
- **UNKNOWN**.

All web pages below were read on 27 Oct 2026 unless another date is given.

---

## 0. Bottom line

1. **Where we are (MEASURED, 4c8af4fc).** The reply wait (`responseMs`, from the moment the caller stops speaking to the agent's first audio) has a median of:
   - **1.60-1.70 s on Timer** (3 calls);
   - **2.14-2.22 s on Ear** (2 calls).

   The model's own share (`firstTokenMs`) is 0.93-1.15 s. Interruptions fell from 1-3 per call to 0 on Ear. The samples are tiny.

2. **The model share is a ~1 s floor we cannot prompt our way out of.** The figures:
   - Gemini 3.1 and 3.5 Flash-Lite first byte from India is about 1.0 s at `minimal` thinking (MEASURED, 688797e1).
   - ThinnestAI measured 0.9 s at a 6k-token prompt and 1.2 s at 1k (VS §25).

   So **prompt size, caching and the choice of Flash-Lite generation do not move it**. Priority tier is not applied on our Google project (MEASURED, 0d9429bf). Google's page says Priority is Preview and "available across the Interactions API endpoints" ([ai.google.dev/gemini-api/docs/priority-inference](https://ai.google.dev/gemini-api/docs/priority-inference), VVD, updated 2026-10-13).

3. **The biggest lever no session has looked at yet is the knowledge-search round trip.**
   - On ThinnestAI our business facts are deliberately **not in the prompt**. `HostedAgentLimits.facts_in_knowledge=True`, a founder decision of 6 Oct made on cost grounds (`apps/api/engine/hosted_platform.py:104`, `apps/api/agents/engine_facts.py:1-12`).
   - The prompt orders the model to *"Search with the search_knowledge tool ... before answering about the business"* (`packages/shared/src/calevate_shared/engine.py:2901-2907`).
   - So every business question ("price?", "where are you?", "do you have X?") costs a tool step, which is a second Gemini pass plus the search. ThinnestAI says the agent "has to find the answer before it can start speaking, so the caller hears a short pause" (`thinnest-findings/mirror/snapshots/2026-10-19/pages/channels/voice.md:494-500`, VVD; the same text is on the live docs.thinnest.ai/channels/voice).
   - At ~1 s per Gemini pass, that is **roughly +1 s on every lookup turn** (ESTIMATE). It is the likeliest cause of our p90 of 2.2-2.7 s and the 8.0 s p90 call of 20 Oct.
   - Putting a small business's facts back in the prompt is the largest saving available inside our own code. It reverses the 6 Oct cost decision, so it needs the founder.

4. **Ear costs about 0.45 s at the median for zero interruptions.** That trade-off is the founder's (§3).

5. **A "real" sub-1 s reply needs a different architecture**, either a speech-to-speech model or a faster LLM host. ThinnestAI added **GPT-Live-1 speech-to-speech** on 22-23 Oct:
   - it has two voices for Telugu;
   - it is billed at a flat rate per minute;
   - it is Enterprise only and set up by ThinnestAI;
   - no latency figure is published (live docs.thinnest.ai/channels/voice and /whats-new, VVD).

   It is a founder and ThinnestAI conversation, not a code change.

6. **A measurement trap: the ~2.14 s Ear medians may be clipped by the filler.** The filler fires after `thinkingDelayMs` = 2000 ms (`apps/api/engine/thinnest.py:328`). Whether ThinnestAI counts a filler as the "agent's first audio" in `responseMs` is UNKNOWN. If it does, the Ear medians sitting just above 2.0 s are partly the filler, and the true answer arrives later. We must ask before we trust any before/after number (§5 question T1).

7. **Conversion evidence is thin.** No peer-reviewed or controlled study linking voice-agent latency to conversion or hang-ups was found (§1.6). We should run our own A/B with a business outcome as the primary metric.

---

## 1. Industry practice (research)

### 1.1 Budgets and targets

- **ElevenLabs' illustrative budget** is end-to-end ~680 ms p50 and ~1,560 ms p95: endpointing 120/280, STT final 60/150, network 60/160, **LLM TTFT 250/600**, TTS first audio 110/220, player buffer 80/150. It says *"the two largest latency line items are the LLM's time-to-first-token and the endpointing delay"*. On endpointing: *"If you wait for, say, 700 ms of silence ... you have added 700 ms to every turn"*. Source: [elevenlabs.io/blog/voice-agent-latency-optimization](https://elevenlabs.io/blog/voice-agent-latency-optimization), VP, updated 9 Oct 2026.
- **Retell** says it "achieves latency as low as 600ms", user stops → agent starts, best case ([docs.retellai.com/reliability/check-estimated-latency](https://docs.retellai.com/reliability/check-estimated-latency), VVD).
- **Pipecat/Daily** target 800 ms voice to voice (talk summary, REPORTED via search: [ai.engineer talk](https://www.ai.engineer/talks/IA4lZjh9sTs-pipecat-cloud-enterprise-voice-agents-built-on)).
- **Hamming's tiers** are p95 < 800 ms good and p95 > 1,500 ms poor ([hamming.ai](https://hamming.ai/resources/voice-agent-ab-testing-guide), REPORTED via search).
- **Our stack cannot reach those budgets.** Each assumes an LLM first token of 250 ms, and ours is ~1,000 ms. A realistic floor on today's stack is ~1.3-1.5 s at the median (ESTIMATE: ~1.0 model + 0.25 silence + ~0.2 TTS and network).

### 1.2 Turn detection and endpointing

- **LiveKit's defaults** are endpointing `min_delay` 0.5 s and `max_delay` 3.0 s. *"Preemptive generation ... start LLM generation as soon as a final transcript arrives, before the turn is confirmed"* is on by default. `preemptive_tts` is off by default because it "cuts more latency at the cost of wasted compute". The page warns that *"Preemptive generation in particular doesn't always reduce latency"* ([docs.livekit.io turns/tuning](https://docs.livekit.io/agents/logic/turns/tuning.md), VVD).
- **Vapi.** Its `waitSeconds` defaults to 0.4, and 0.0-0.2 is recommended for real-time use. Smart endpointing is **"Only available for English conversations"**. For other languages it uses text endpointing (defaults: 0.1 s on punctuation, 1.5 s without, 0.5 s on numbers). Source: [docs.vapi.ai voice-pipeline-configuration](https://docs.vapi.ai/customization/voice-pipeline-configuration), VVD.
- **Semantic end-of-turn models with Telugu: none found.**
  - Pipecat Smart Turn v3.2 covers 23 languages, Hindi and Marathi but **no Telugu**, with "under 100ms on most cloud instances" ([github.com/pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn), VVD).
  - Deepgram Flux Multilingual covers 10 languages, Hindi but no Telugu ([BusinessWire, 29 Apr 2026](https://www.businesswire.com/news/home/20260429043418/en/), VP via search).
  - So **ThinnestAI's Ear is the only semantic option we have for Telugu**. ThinnestAI says Ear runs "our own real-time recogniser for Indian languages", Telugu supported, "not measured on Telugu or Indian phone lines" (VS §25).

### 1.3 LLM time to first token

- **Thinking.** On Gemini 3.x thinking cannot be fully off; 3.5 Flash-Lite defaults to `minimal`. Google advises lowering `thinking_level` rather than `max_output_tokens` to cut "cost or latency" ([ai.google.dev/gemini-api/docs/thinking](https://ai.google.dev/gemini-api/docs/thinking), VVD, updated 2026-10-14). ThinnestAI already asks Gemini 2.5/3 to "think less" on calls ([docs.thinnest.ai/api-reference/bring-your-own-keys](https://docs.thinnest.ai/api-reference/bring-your-own-keys), VVD).
- **Caching.** Google's caching page claims cost savings only and says nothing about latency ([ai.google.dev/gemini-api/docs/caching](https://ai.google.dev/gemini-api/docs/caching), VVD, updated 2026-10-23). ThinnestAI's 6k vs 1k measurement (VS) shows no prompt-size penalty. **Not a latency lever for us.**
- **Faster hosts.** Artificial Analysis measures on a 10k-token input, median over 72 h, REPORTED:
  - gpt-oss-120b (low) first answer token: Cerebras 1.48 s, SambaNova 3.80 s, Groq 4.88 s ([artificialanalysis.ai gpt-oss-120b-low](https://artificialanalysis.ai/models/gpt-oss-120b-low/providers));
  - Gemini 3.1 Flash-Lite (AI Studio): 4.71 s ([artificialanalysis.ai gemini-3-1-flash-lite-preview](https://artificialanalysis.ai/models/gemini-3-1-flash-lite-preview/providers)).

  These include reasoning time on AA's default settings and do not match our `minimal` ~1.0 s. Read them as relative only.
- **Telugu quality on open models.** No Telugu benchmark for Groq/Cerebras-hosted models was found (UNKNOWN). ThinnestAI called GPT-OSS 120B "fast but dumb" (VS, 2d457b6e).
- **Speculative or early generation** is industry standard (LiveKit preemptive generation; ElevenLabs "speculative execution: feed stable partials into the LLM"). **ThinnestAI already does it**: `voice.earlyAnswers`, on by default, "the first words come sooner" ([docs.thinnest.ai/api-reference/agents/update-agent](https://docs.thinnest.ai/api-reference/agents/update-agent), VVD). We send it (`thinnest.py:2066`). Our console default is `true` (`calevate_shared/config.py:534`).

### 1.4 TTS first audio and streaming

- **Sentence-at-a-time synthesis.** ThinnestAI: *"Speech is produced one sentence at a time"* (mirror `channels/voice.md:190`, VVD). The first sentence must finish generating before any audio, so **a short first sentence is a lever in our prompt**.
- **Cartesia** recommends WebSocket reuse, a context per turn, and continuations. It notes "full sentences produce the best prosody but add latency" ([docs.cartesia.ai websocket/buffering](https://docs.cartesia.ai/use-the-api/tts-websocket/buffering), via search, REPORTED). The pipeline is ThinnestAI's, so we do not control it.
- **Sonic model.** Sonic 3.6 supports Telugu (`te`) and publishes no latency figure ([docs.cartesia.ai latest](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest), VVD). Sonic-turbo has no Telugu (21 Oct report).

### 1.5 Fillers, backchannels and acknowledgements (perceived latency)

- **The only primary study found** is arXiv 2507.22352, in VR with LLM agents. It found *"natural conversational fillers improve perceived response time, especially in high-delay conditions"* and that delays above ~4 s degrade experience ([arxiv.org/abs/2507.22352](https://arxiv.org/abs/2507.22352), REPORTED, read this session).
- **What ThinnestAI offers:**
  - `voice.thinking` filler after `thinkingDelayMs` (200-5000, default 900);
  - `thinkingAtTurnEnd` ("Okay." before every reply);
  - Ear-only `acknowledgements` / `acknowledgementWords`, and `backchannelDetection` / `backchannelWords`.

  All are from live update-agent, VVD.
- **Masking is not shortening.** These change perceived wait, not `responseMs`, and they cost Cartesia characters at ~₹4.84-4.86 per 1k characters (530cc6d6; founder-attested 12f1aa47).

### 1.6 Latency and conversion: the evidence

- **No controlled study isolates latency → conversion or hang-up.** A wide search found only:
  - vendor claims with no method (Parloa, Waboom, famulor);
  - a confounded before/after (Reveor, Medium: 4.5 s → 0.95 s alongside a 32% → 8% abandonment, with several changes shipped together) (REPORTED).
- **The human baseline.** Human turn gaps are short, and every language studied minimises them (Stivers et al. 2009, PNAS, cited in the 21 Oct report).
- **Hamming's A/B advice** is to treat fewer than 100 calls per variant as directional only, and to use latency as a guardrail beside the business metric (REPORTED).

**Conclusion:** the "better conversions" premise is plausible but unproven. Measure it ourselves (§4, question F7).

---

## 2. ThinnestAI: every latency-relevant control, and what we send

Sources:
- live docs.thinnest.ai `api-reference/agents/update-agent`, `channels/voice`, `whats-new`, `models/list-models`, `tools/update-built-in-tools`, `bring-your-own-keys` (VVD);
- the mirror `thinnest-findings/mirror/snapshots/2026-10-19`.

| Control | Vendor meaning | What we send | Where |
|---|---|---|---|
| `voice.turnDetection` `timer`/`smart`/`ear`/null | Timer is "faster but cuts off people who pause"; Smart waits (0.6 s ceiling); Ear recognises speech in real time, "waits through a pause mid-thought", "costs nothing extra" | Console `thinnest_turn_detection` (code default `timer`, `config.py:522`). **Production row = `ear` since 21 Oct 13:32 IST** (4c8af4fc) | `thinnest.py:2057` |
| `voice.turnSilenceSeconds` 0.2-3 | Timer: the silence that ends the turn. Ear: quiet before speech is declared over, then a second pause check (VS §25) | `agents.turn_silence_ms` / console, 0.25 s (D-849) | `thinnest.py:2052` |
| `voice.earlyAnswers` (default true) | Starts the reply on what it has heard so far; discarded runs bill our Google key and are not counted in `usage` | Console `thinnest_early_answers`, default true | `thinnest.py:2066` |
| `voice.acknowledgements` (Ear only, default true), `acknowledgementWords` (≤30 × 40 chars) | "haan ji" while the caller pauses; billed as Cartesia characters (VS §25) | `acknowledgements` sent under Ear (default true); **`acknowledgementWords` NOT sent** (founder: a potential feature, 87e54215) | `thinnest.py:2060` |
| `voice.backchannelDetection` (Ear, default true), `backchannelWords` | Tells "hmm" from a real interruption while the agent talks | **Not sent** (vendor default on) | — |
| `voice.thinking`, `thinkingDelayMs`, `thinkingRepeatMs`, `thinkingLines` (≤8 × 60) | Filler when a reply has not started | thinking on, **2000 ms**, repeat 2500, per-language lines | `thinnest.py:323-331`, `:2092-2093` |
| `voice.thinkingAtTurnEnd` | "Okay." before every reply | false | `thinnest.py:327` |
| `voice.interruptWords`, `holdShortSpeech`, `neverInterrupt`, `greetingUninterruptible`, `openingWaitsForCaller` | Interruption and opening behaviour (not reply latency) | console / platform values | `thinnest.py:2041`, `:2069`, `:323-326` |
| `maxReplyTokens` 100-800 | Reply ceiling; does not move the first word | console 300 | `thinnest.py:2153` |
| `model` / BYOK LLM | "A model is only offered if it can answer fast enough"; List Models publishes **no latency** ("Typical latency is not published") | own key `gemini-3.1-flash-lite` (`byok: llm_voice`) | `thinnest.py:2166`, `:2184` |
| BYOK LLM providers | OpenAI, Anthropic, Gemini, **Groq**, Mistral, Sarvam, DeepSeek, xAI, Together, Fireworks, **Cerebras**, OpenRouter, any OpenAI-compatible URL | Gemini only | — |
| `callTier` | Always `premium`; "never raises a call's price" (23 Oct whats-new) | — | — |
| Knowledge on calls | "Two switches, on the Actions page"; "Turn the calls one off if you want the quickest possible line"; **`search_knowledge` is not a switch over the API** | Cannot set it over the API. Our prompt orders a search before any business answer | `engine.py:2901-2907` |
| Speech-to-speech `openai-gpt-live-1` (22 Oct), `openai-gpt-realtime-mini` (23 Oct) | Telugu among 9 Indian languages (GPT-Live-1); flat per-minute rate including the line; Enterprise only, "set up by us"; fillers, speed, Ear, early answers greyed out | Not available to us | — |
| Region / greeting caching | Not documented anywhere in the live docs or mirror | — | UNKNOWN |
| Per-turn timing | Only call-level `responseMs` and `firstTokenMs` median/p90/max; the split is "in our per-turn timing logs" (VS §25), asked twice, **not answered** (§28 item 14) | — | — |

---

## 3. Ranked plan

Savings are per reply unless stated. "Lookup turn" means a turn on which the model calls `search_knowledge`.

| # | Lever | Expected saving | Evidence class | Cost (INR) | Telugu risk | Where | How we measure |
|---|---|---|---|---|---|---|---|
| 1 | **Business facts back in the prompt for agents whose facts fit**: per-agent `facts_in_knowledge` by size; the prompt says "answer from the facts here; search only for what is not here" | **~0.9-1.2 s on each lookup turn** (one Gemini pass removed: ~1.0 s floor MEASURED 688797e1, plus search time UNKNOWN). Median moves only by the share of lookup turns (UNKNOWN; measure). p90 should fall most | Pass time MEASURED + VS; total ESTIMATE | Adds the facts' tokens to every reply. Example: 1,500 tokens × ~5 replies/min at $0.25/M (VVD pricing, 22 Oct 2026) × ₹95 (D-768) ≈ ₹0.18/min uncached, ≈ ₹0.02/min if cached. Each avoided lookup saves a second pass of ~6-8k tokens ≈ ₹0.14-0.19 uncached. **Roughly neutral at ≥1 lookup per minute** (ESTIMATE) | Low (the same facts in a different place). Risk: facts drift if the 20k instructions cap is hit, so the size check must refuse rather than truncate | **Our code** (`engine/hosted_platform.py`, `agents/engine_facts.py`, `engine.py` `_knowledge_section`, `agents/service._script_for`). **Founder decision** (reverses 6 Oct). The console switch "knowledge on calls" needs ThinnestAI for the API, or the founder per agent | Count lookups before and after with Test Chat `mode:"call"` (shows `search_knowledge` steps), plus `firstTokenMs` p90 and `usage.inputTokens`/turns per call |
| 2 | **Ear vs Timer, decided on data** | Back to Timer ≈ **−0.45 s median** (2.14-2.22 → 1.60-1.70), at the cost of interruptions (0 → 1-3 per call) and half-sentence answers | MEASURED, n = 2 vs 3 calls | ≈ ₹0; Ear acknowledgements add TTS characters | Timer cuts off Telugu callers who pause (D-849, half sentences) | Console `thinnest_turn_detection` (exists). **Founder decision** | ≥10 calls per arm, same agent and script; `responseMs` p50/p90, `interruptions`, and a judged half-sentence count. Needs lever 6 to split the page by mode |
| 3 | **Short first sentence** ("a first sentence of a few words, ending in a full stop, then the rest") | ~50-200 ms (first sentence generated before synthesis; Flash-Lite ~360 tok/s output, AA REPORTED; Telugu is token-heavy) | VVD (one sentence at a time) + ESTIMATE | ≈ ₹0 | Medium: formulaic openers clash with "each turn begun differently" and natural Telugu; judge with `turn_checks` / practice callers | **Our code** (`VOICE_STYLE_GUIDANCE`, `engine.py:2846`) behind a console switch for A/B | `responseMs − firstTokenMs` gap before and after; reply judge |
| 4 | **Filler timing as perceived latency**: `thinkingDelayMs` 2000 → ~1300-1500 so the slow tail (lookups, p90 2.2-2.7 s) hears a filler sooner | 0 ms real, but less dead air on slow turns | VVD (field), REPORTED (fillers help perception, VR study) | ~15-char Telugu filler ≈ ₹0.07 each at ₹4.84/kchar; only on slow turns | Low (lines already per language) | Platform value in `thinnest.py:328`. **Founder decision** (he chose 2000 on 20 Oct, c79138bf) | Answer T1 first; then count fillers in transcripts/`ttsCharacters` per minute |
| 5 | **`turnSilenceSeconds` 0.25 → 0.2 under Ear** (the minimum) | ≤50 ms | VVD range + VS (Ear meaning) | 0 | Slightly more early "speech over" declarations; Ear's second check guards | Console | Same A/B |
| 6 | **Measurement plumbing** (prerequisite for 1-5): stamp each call with the voice settings it ran on (turn mode, silence, early answers, filler delay, facts inline/in knowledge, model) and split `/admin/ops/reply-times` by them. Set a reachable `reply_time_target_ms` (today 500, `config.py:548`) | 0 (makes every other number trustworthy) | — | 0 | — | **Our code** (`apps/api/ops/reply_times.py` has only tier/client/agent/day splits) | — |
| 7 | **A faster LLM host on BYOK** (Cerebras or Groq gpt-oss, or OpenAI via the OpenAI-compatible URL) | UNKNOWN. AA's 10k-input Cerebras gpt-oss-120b 1.48 s is not better than our ~1.0 s; Groq 4.88 s | REPORTED | UNKNOWN (no attested price) | **High**: no Telugu benchmark; ThinnestAI called GPT-OSS "fast but dumb" (VS) | Founder decision; bench first from the VPS with curl (as 688797e1) on a real 6k call prompt, 50 requests each | curl TTFB p50/p90 + Telugu test chats judged |
| 8 | **Speech-to-speech GPT-Live-1** on ThinnestAI | Potentially the largest (no STT→LLM→TTS cascade), but **no figure published**: "it starts answering as soon as the caller stops" | VVD (features), latency UNKNOWN | Flat per minute, price shown only in the picker: UNKNOWN | UNKNOWN Telugu quality. Loses our Cartesia/Studio voices and clones, fillers, Ear and our Gemini. Must re-verify hard rule 5 (truthful answers, CONFIDENTIALITY) on a model we do not prompt the same way | **Needs ThinnestAI** (Enterprise) + founder | A pilot agent; `responseMs` + judged Telugu calls |
| 9 | **Gemini priority tier** | Tail only; not applied on our project | MEASURED (0d9429bf) + VVD (Preview, Interactions API) | +75-100% LLM price (3.1 FL $0.45 in / $2.70 out vs $0.25 / $1.50, VVD pricing 22 Oct 2026) | None | Google enablement, then ThinnestAI opt-in | `usageMetadata.serviceTier` |
| 10 | **Cache hit fix (28-35%)** | ~0 latency (VS: no prompt-size effect) | VS | Cost only, ≤ ~₹0.6/min (530cc6d6) | None | ThinnestAI (asked §22 item 2, §28 item 14, unanswered) | `cachedInputTokens` share |

**Rejected again (evidence in the 21 Oct report §4, unchanged):**
- a model "silence" reply (VS §25: an empty reply gives an apology + `byok_failed`);
- `thinkingAtTurnEnd` (masks every turn; the founder dislikes it);
- sonic-turbo (no Telugu);
- a Mumbai Gemini region (the API key has no region);
- lowering `maxReplyTokens`;
- prompt trimming for speed (cost only);
- switching to 3.5 Flash-Lite for speed (MEASURED the same ~1.0 s; it also costs more at $0.30/$2.50, VVD).

### What the stack can realistically reach (ESTIMATE)

| Step | Median | p90 | Interruptions |
|---|---|---|---|
| Today (Ear) | ~2.15 s | ~2.7 s+ | 0 |
| Plus lever 1 (facts inline) | ~1.9-2.1 s | ~2.0-2.3 s | 0 |
| Plus lever 3 | another ~0.1 s off | — | — |
| With Timer instead of Ear | ~1.5-1.6 s | — | back to 1-3 per call |

The ~1.0 s Gemini floor stays in every row. Below ~1.3 s needs lever 7 or 8.

---

## 4. Grouped

**Do now in our code** (no founder decision; nothing changes for callers until a switch is flipped):
- **6. Measurement plumbing.** Settings stamp per call, the Reply times page split by setting, a lookup-count estimate. A Test Chat `mode:"call"` harness that replays a fixed set of 20 Telugu business questions per agent and counts `search_knowledge` steps and reply times.
- **1. Build "facts in prompt when they fit".** A per-agent size gate, a refusal not a truncation, and a console switch `thinnest_facts_in_prompt` defaulting off until the founder says yes. Keep the knowledge document for big catalogues. Update the D-678 / 6 Oct decision row only once the founder decides.
- **3. Short-first-sentence rule** behind a console switch, default off, plus a `turn_checks` check.
- **5.** Allow `turnSilenceSeconds` 0.2 under Ear in the console range. It already is (0.2-3); it is only a value.

**Needs a founder decision:**
- lever 1 on (reverses 6 Oct);
- lever 2 (Ear vs Timer);
- lever 4 (filler delay);
- the target numbers;
- levers 7 and 8 (model or architecture change);
- the A/B design;
- spend.

**Needs ThinnestAI** (questions T1-T7 for the next email):
- **T1.** Is a filler (`thinkingLines`) or an Ear acknowledgement counted as the "agent's first audio" in `responseMs`? If so, can `quality` report time to the first word of the actual answer?
- **T2.** The per-turn timing split for our calls (end-of-speech wait, Ear second check, recognition final, first sentence complete, voice first audio). Asked twice, not answered (§26 item 1, §28 item 14).
- **T3.** Expose the "knowledge on calls" switch over the API, or per agent in `PATCH /agents/{id}/tools`. Add a per-turn count of knowledge lookups to `quality`.
- **T4.** How long does Ear's second pause check take on average, and can it be tuned?
- **T5.** Does synthesis start at a comma or clause, or only at a full stop? (Asked 21 Oct as Q9; no answer found in §25-§35.)
- **T6.** Where do call media, the recogniser and the Cartesia and Gemini requests run (region)?
- **T7.** GPT-Live-1 for a pay-as-you-go account:
  - price per minute in INR;
  - median reply time on Indian lines;
  - Telugu quality;
  - whether our instructions (AI disclosure, recording answer, confidentiality) are honoured verbatim;
  - whether knowledge and custom actions work;
  - whether our Cartesia voice is possible (the docs suggest not).

---

## 5. Questions for the founder (recommended default in bold)

1. **Target.** Replace the 500 ms target (`reply_time_target_ms`, unreachable: the model alone is ~1.0 s) with a reachable one. **Default: p50 1.6 s / p90 2.2 s now; revisit after levers 1 and 8.**
2. **Facts in the prompt (lever 1).** Reverse the 6 Oct decision for agents whose facts fit, at ≈ ₹0-0.18/min extra tokens and probably neutral once lookups are counted. **Default: yes, up to ~6,000 characters of facts; bigger catalogues stay in knowledge.**
3. **Ear vs Timer (lever 2).** About 0.45 s faster at the median on Timer, against interruptions and half-sentence answers. **Default: keep Ear while we A/B, then decide on ≥10 calls each. Pick Timer only if conversions (Q7) do not drop.**
4. **Filler delay (lever 4).** **Default: keep 2000 ms until ThinnestAI answers T1. Then test 1,400 ms only if lookup turns stay slow after lever 1.**
5. **Filler and acknowledgement wording in the brand voice.** **Default: keep the per-language `thinkingLines` (D-858). Keep Ear `acknowledgementWords` unset (the vendor's "haan ji"/"okay"), as decided 23 Oct.** If he wants Telugu "సరే అండి" / "ఆ" as acknowledgements, he approves the exact words.
6. **Short first sentence (lever 3).** **Default: yes, A/B behind a switch, judged by practice callers for naturalness.**
7. **A/B and what "conversion" means.** **Default: one Raghava-style test agent per arm; ≥10 calls per arm for latency (directional), ≥100 per arm before claiming a conversion effect. Primary outcome: the call's outcome reaching "Interested/Wants to buy" or a booking. Guardrail: hang-up within 30 s.**
8. **Spend on speed.** Priority tier (+75-100% LLM, not available today) and a speech-to-speech pilot (price UNKNOWN). **Default: no priority tier; yes to asking ThinnestAI for GPT-Live-1 pricing and a Telugu pilot quote (T7), with no commitment.**
9. **A model or host switch (lever 7).** **Default: stay on gemini-3.1-flash-lite (shutdown announced for 7 May 2027, replacement 3.5 Flash-Lite, [deprecations page](https://ai.google.dev/gemini-api/docs/deprecations) VVD, updated 2026-10-22). Run a ₹-cheap curl bench of Cerebras/Groq gpt-oss and an OpenAI mini model only if he wants a sub-1.3 s option on record.**

---

## 6. Sources read this session (27 Oct 2026)

**ThinnestAI (live docs, VVD):**
- docs.thinnest.ai/api-reference/agents/update-agent
- /channels/voice
- /whats-new (22, 23, 24, 26 Oct entries)
- /api-reference/models/list-models
- /api-reference/tools/update-built-in-tools
- /api-reference/bring-your-own-keys
- /api-reference/calls/get-call.md
- /guides/how-your-agent-sounds.md
- the mirror `thinnest-findings/mirror/snapshots/2026-10-19/pages/channels/voice.md:190, 489-500, 946-976`

**Google (VVD):**
- ai.google.dev/gemini-api/docs/pricing (updated 2026-10-22)
- /deprecations (2026-10-22)
- /models (2026-10-22)
- /thinking (2026-10-14)
- /caching (2026-10-23)
- /priority-inference (2026-10-13)

**Industry:**
- LiveKit turns/tuning (VVD)
- Vapi voice-pipeline-configuration (VVD)
- Retell check-estimated-latency (VVD)
- ElevenLabs blog (VP)
- Pipecat smart-turn README (VVD)
- Cartesia latest models (VVD)
- Artificial Analysis provider pages (REPORTED)
- arXiv 2507.22352 (REPORTED)
- Deepgram Flux (VP via search)
- Hamming, Reveor and Parloa (REPORTED, vendor)

**Our code:**
- `apps/api/engine/thinnest.py:296-331, 1971-2193`
- `apps/api/engine/hosted_platform.py:40-60, 95-110`
- `apps/api/agents/engine_facts.py:1-30`
- `packages/shared/src/calevate_shared/engine.py:2846-2934`
- `packages/shared/src/calevate_shared/config.py:488-548`
- `apps/api/ops/reply_times.py`
- `apps/api/teach/pinned.py:51` (MAX_PINNED_CHARS 3000)
