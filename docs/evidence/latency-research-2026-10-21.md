# Reply latency and cost on ThinnestAI: where the 1.7 s goes and what can cut it (21 Oct 2026)

Evidence classes: VERIFIED-VENDOR-DOCS (VVD), VENDOR-STATED (VS, email), VENDOR-PUBLISHED (VP,
marketing or blog), REPORTED (third party), ESTIMATE (arithmetic from cited inputs), UNKNOWN.
Mirror = `thinnest-findings/mirror/snapshots/2026-10-19/pages/` unless stated.
Memory ids are rememory `calevate` ids.

## 0. Bottom line

- The 500 ms target (D-770, ab911090) cannot be reached on this stack. The model's own share
  (`firstTokenMs`) is a median of 928 to 949 ms on its own. No field we control brings that under
  500 ms. That is arithmetic, not a judgement.
- What is realistic is a cut of roughly 0.2 to 0.6 s at the median and a larger cut at p90. It
  comes from three places:
  1. turn detection (a new mode, `ear`, that we have not tried);
  2. the Gemini tail (priority tier, which ThinnestAI would have to send);
  3. less text read before the first word (`callInstructions` and `ownRules`, which also save money).
- The founder's "silence instead of a reply" idea for caller half-sentences is not supported by
  the docs. The docs say the agent never goes quiet when the model gives nothing, and on our own
  key the fallback is an apology. The vendor's own answer to half-sentences is `ear` mode (§5).

## 1. Where the ~1.7 s goes

Measured (two Studio Telugu calls, 21 Oct 2026, Get Call `quality`):

| Metric | Median | p90 |
|---|---|---|
| `responseMs` (caller stops speaking → agent's first audio) | 1690 / 1703 | 2179 / 2688 |
| `firstTokenMs` (the model's share) | 928 / 949 | 1452 / 1917 |

- `responseMs` is defined "from when they stopped speaking to the agent's first audio on the
  line" (`api-reference/calls/get-call.md:1084-1087`). That definition includes the turn-end
  silence window.
- `firstTokenMs` is "our side of it", the platform's description in the `call.analysed` /
  `quality` text in openapi.json.

Decomposition of the median (ESTIMATE; ThinnestAI publishes no per-stage split):

| Stage | ms | Basis |
|---|---|---|
| Turn-end silence (`timer`, `turnSilenceSeconds` 0.25) | ~250 | our setting; `update-agent.md:1440-1451` |
| Model first token (Gemini 3.1 Flash-Lite, own key, thinking `minimal`) | ~930 | measured; thinking level VS (f4ecc712, §18 item 8) |
| STT finalisation + Cartesia first audio + phone network and buffering | ~510 (remainder) | Cartesia Sonic 3 first audio is a median of 166 ms including network, measured by Vapi (REPORTED, [humannessindex.vapi.ai](https://humannessindex.vapi.ai/models/cartesia-sonic-3)); the rest is UNKNOWN |

Two caveats:
- ThinnestAI already starts the model when the caller's speech ends, while it is still
  confirming they have finished. It says this saves "a fifth of a second or so" per turn
  (`whats-new/index.md:180-187`, 14 Oct). So part of the silence window overlaps the model, and
  the rows do not simply add.
- The model share dominates: about 55% of the median and 67-71% of the p90.

What drives that ~930 ms (research):
- **Thinking.** It cannot be fully off on Gemini 3.x; `minimal` is the floor (e1f1737c, a22068da).
- **Input size.** About 6k tokens per reply, of which only ~2.3k are cached (84048b66). Google says
  caching lowers "cost and latency" but gives no TTFT figure
  ([Vertex context cache overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview),
  VVD, read 21 Oct 2026). How much 3.7k uncached tokens cost in prefill time on Flash-Lite is UNKNOWN.
- **Variance in the Gemini API.** One forum user on `gemini-3.1-flash-lite-preview` with
  `minimal` thinking saw 0.6-0.7 s normally and 15-20 s on about a quarter of six requests
  ([discuss.ai.google.dev, 6 May 2026](https://discuss.ai.google.dev/t/gemini-3-1-flash-lite-is-very-slow-and-inconsistent/143754),
  REPORTED, anecdotal). That is consistent with our wide p90/median gap, but not proof of it.
- **Network path.** UNKNOWN. ThinnestAI holds our key as `{apiKey, model}` (the Gemini API key,
  not Vertex), and the Gemini API has no region choice. On Vertex, 3.1 Flash-Lite is documented on
  the global endpoint only; no asia-south1 row was found
  ([Vertex locations](https://docs.cloud.google.com/vertex-ai/docs/generative-ai/learn/locations),
  REPORTED via search, 21 Oct 2026). Where ThinnestAI's media servers sit is not in the mirror
  (grep for Mumbai/region/data centre: nothing).
- **Artificial Analysis's 5-6 s "time to first answer token"** for 3.1 Flash-Lite
  ([artificialanalysis.ai](https://artificialanalysis.ai/models/gemini-3-1-flash-lite-preview/providers),
  REPORTED) uses a 10k-token input and includes thinking at the default level. It does not
  describe calls at `minimal`, so do not quote it as our expectation.

For scale:
- Human turn gaps are short. Across 10 languages, average gaps vary within a range of 250 ms of
  the cross-language mean, and every language minimises silence between turns (Stivers et al.
  2009, PNAS 106(26):10587, [MPI record](https://forms.mpi.nl/node/50939)). The commonly quoted
  "~200 ms" mode was NOT verified here.
- ElevenLabs' illustrative budget is ~680 ms at p50 and ~1560 ms at p95 end to end, with model
  first token at 250 / 600 ms
  ([elevenlabs.io blog, updated 9 Oct 2026](https://elevenlabs.io/blog/voice-agent-latency-optimization),
  VP, illustrative).

## 2. Levers, ranked by expected latency effect

| # | Lever | Owner | Expected effect | Cost effect | Evidence | How (field / file) | Risk |
|---|---|---|---|---|---|---|---|
| 1 | **Try `voice.turnDetection: "ear"`** (real-time recognition decides end of turn) instead of our forced `timer` | Us (field); Telugu availability is ThinnestAI's | Vendor: "knows sooner when the caller has finished, because the end of their speech is detected as it happens rather than after a timer". Also waits through mid-thought pauses rather than answering half a sentence. Size UNKNOWN; at best the 250 ms window plus fewer wasted replies | "Ear costs nothing extra" (`channels/voice.md:973-974`). Fewer cut-off replies means fewer TTS characters | VVD `channels/voice.md:931-960`, `update-agent.md:1418-1439`, `whats-new/index.md:158-166` | `apps/api/engine/thinnest.py:283-284` `TURN_DETECTION = "timer"` (sent at :1859, drift label :1210). Needs a console setting or per-agent value, then an A/B on the Raghava trial agent comparing `responseMs` and `interruptions` | (a) "the agent uses `timer` on a line where real-time recognition is not available" (`update-agent.md:1437-1438`); Telugu availability UNKNOWN. (b) `acknowledgements` (on by default) makes the agent say "haan ji" at longer pauses on phone calls (`voice.md:946-953`); whether that counts as Cartesia characters is UNKNOWN; it can be switched off (`update-agent.md:1548-1554`). (c) Supersedes D-767's reason for forcing timer (f8bef964), which compared timer only with smart |
| 2 | **Gemini priority inference** (`service_tier: "priority"`) | ThinnestAI sends the request; Google; founder pays | Targets the tail (p90 1.45-1.9 s model share). Google: priority traffic is "prioritized above standard", "designed for second response times", non-sheddable. No TTFT figure | +75-100% on token price ([ai.google.dev priority-inference](https://ai.google.dev/gemini-api/docs/priority-inference), VVD, updated 13 Oct 2026; Preview; 3.1 Flash-Lite listed). On the 20 Oct call the LLM was ₹0.76/min (530cc6d6), so +₹0.57-0.76/min (ESTIMATE) | VVD (Google) | No ThinnestAI field exists (mirror grep: none). Ask (Q5). Before asking, measure it ourselves from our own key with a 6k-token Telugu call prompt, standard vs priority, 50 requests each | Preview; separate rate limits (0.3x standard); overflow silently drops to standard (header `x-gemini-service-tier`) |
| 3 | **Less text before the first word**: replace the ~1,675-char default call rules via `voice.callInstructions`; send `ownRules: true` (D-847); trim our layers | Us (fields), once their text is in hand | Smaller prefill. Latency size UNKNOWN (no published prefill rate for 3.1 Flash-Lite); likely tens of ms (ESTIMATE). The cost effect is the certain part | ~1,675 chars ≈ 400-600 tokens per turn removed (ESTIMATE). At the ₹0.0238/ktok uncached rung (35a5ccdb), about ₹0.01 per reply | VS §21 item 8 (default call rules + speaking rules on every turn); `update-agent.md` `callInstructions` REPLACES built-in call rules (≤4,000 chars) | `voice.callInstructions`; text already requested in §22 item 3 | Their speaking rules stay (founder 99f4d113). `callInstructions` replaces only the call rules; check that the speaking rules survive in the read-back |
| 4 | **Fix the 34-35% cache hit** | ThinnestAI (cause UNKNOWN, 84048b66) | Latency effect unquantified by Google; cost effect certain | 100% caching would save about ₹0.6/min (530cc6d6) | §22 item 2 already asks | Nothing new to ask | — |
| 5 | **A short first clause in every reply** (e.g. "సరే అండి," then the answer) | Us (prompt) | ThinnestAI synthesises "one sentence at a time" (`channels/voice.md:190-191`), so first audio waits for the whole first sentence. At ~300 output tok/s ([AA](https://artificialanalysis.ai/models/gemini-3-1-flash-lite-preview/providers), REPORTED), a 20-token first sentence is ~65 ms (ESTIMATE). Small | +a few characters per reply if the clause is extra; ±0 if it replaces words | VVD + ESTIMATE | `calevate_shared/engine.py` VOICE_STYLE_GUIDANCE; check the vendor's speaking rules first (`docs/vendor/thinnest-speaking-rules-2026-10-18.md`) | Whether a comma starts synthesis is UNKNOWN (Q9). A formulaic opener collides with "vary openings" and the founder's natural-Telugu goal |
| 6 | **A faster model** (e.g. Gemini 3.5 Flash-Lite) | Founder decision | UNKNOWN. Google: "fastest 3.5-class", 350 output tok/s, "significantly outperforms 3.1 Flash-Lite" ([deepmind.google](https://deepmind.google/models/gemini/flash-lite/), VP); no TTFT published | $0.30 in / $2.50 out vs $0.25 / $1.50 (REPORTED, [vorplabs](https://vorplabs.com/models/releases/gemini-3-5-flash-lite); not checked on Google's pricing page) | VP / REPORTED | Measure TTFT and Telugu register with our own key first; offering it goes through D-817 (`own_model_call`) | Telugu quality unproven. The founder chose 3.1 Flash-Lite (a22068da). Do not switch on this evidence |
| 7 | **Knowledge search off on calls** for agents whose facts fit in the prompt | ThinnestAI (API), client | Removes the "short pause" while it looks something up (`channels/voice.md:489-500`). Per-turn size UNKNOWN | None | VVD | Console-only: `search_knowledge` "is not a switch" over the API (`api-reference/tools/update-built-in-tools.md:7`). Ask (Q7) | Wrong answers if the facts are not in the prompt |
| 8 | Lower `turnSilenceSeconds` 0.25 → 0.2 | Us | −50 ms per reply | ≈0 | VVD `update-agent.md:1440-1451` | `agents.turn_silence_ms` (D-751) | More cut-offs of Telugu speakers. Not recommended; `ear` is the better route |

## 3. What to do

**We can ship now (fields we control):**
1. A/B `turnDetection: "ear"` vs `"timer"` on the Raghava trial agent. Make `TURN_DETECTION`
   (`thinnest.py:284`) a console setting rather than a constant. Read back `turnDetection`. Compare
   `responseMs` median/p90, `interruptions` and `ttsCharacters` per minute over a few calls each.
   Turn `voice.acknowledgements` off in the first round so its effect is isolated.
2. Benchmark TTFT from our own Google key, on a 6k-token copy of a real call prompt, for:
   3.1 Flash-Lite standard; 3.1 Flash-Lite priority; and 3.5 Flash-Lite at `minimal` (if offered
   on our project). Fifty requests each, median and p90. This costs cents and tells us whether
   lever 2 or 6 is worth a vendor ask or a founder decision. It is not the ThinnestAI path (their
   region is unknown), so treat it as a relative result.
3. Do not change `thinkingDelayMs` (2000), `thinkingAtTurnEnd` (false) or `maxReplyTokens` for
   latency: none of them moves the first word (§4).

**Ask ThinnestAI** (not covered in §20 or §22):
- **Q1. Empty reply.** If our model returns an empty reply (no text, no tool call) for a caller
  turn, what does the agent do: stay silent and keep listening, treat it as a model failure
  (apology, `modelErrors`, `call.problem`), or something else? Is there a supported "no reply"
  marker the model can emit so that nothing is spoken and no characters are sent to the voice?
- **Q2. Ear mode on our calls.** Is real-time recognition available for Telugu (te-IN) on Indian
  phone lines for an agent on `llm_voice` (your recogniser)? Which recogniser runs in Ear mode?
  Does `turnSilenceSeconds` apply in Ear, and as what? What end-of-turn delay does Ear typically
  add or save against Timer 0.25 s?
- **Q3. Ear acknowledgements.** Are the "haan ji" acknowledgements synthesised on our Cartesia key
  and counted in `ttsCharacters`?
- **Q4. Early answers that get dropped.** When an early answer is dropped because the caller was
  not finished (14 Oct What's New), are those model tokens billed to our Google key and counted in
  `usage.inputTokens`? How often does it happen per call?
- **Q5. Gemini request path.** Which Google endpoint and region do you call with our key? Is it
  streaming? Could an agent opt in to `service_tier: "priority"` (Google's Priority inference,
  Preview, 3.1 Flash-Lite supported) on our key?
- **Q6. What `firstTokenMs` measures.** Does it run from the caller's speech end or from your
  request? Could `quality` add STT-final and voice-first-byte medians, so we can see where the
  rest of `responseMs` goes?
- **Q7. Knowledge search switch.** Could the "knowledge on calls" switch be exposed on the API (it
  is console-only)?
- **Q8. Hosting region.** Where do call media and the Cartesia request run (India or elsewhere)?
- **Q9. When speech starts.** Does speech for a sentence start at the first comma or clause, or
  only at a full stop?

**Founder decisions:**
- The 500 ms target versus the measured 928 ms model share. Either keep it as an aspiration or
  set a reachable p50/p90 (for example 1.2 s / 1.8 s). The admin screen judges calls against it.
- Whether to pay +75-100% on the LLM leg for priority, if the benchmark shows a tail gain.
- Whether Ear's spoken acknowledgements are acceptable in the brand voice.
- Any model change (3.5 Flash-Lite) only after the TTFT and Telugu evidence.

## 4. Attractive but not supported by evidence

- **The model returning silence for a half-sentence.** The docs say "The agent does not go dark…
  the reply falls through to another model rather than to silence" (`agent/behaviour.md:145-148`).
  On our own model key "the model never has one [a backup]: if your key fails, the caller hears
  our apology and the call is flagged" (`api-reference/bring-your-own-keys.md:176-178`).
  `modelErrors` counts turns where the agent "apologised to the caller instead"
  (`get-call.md:1154-1160`). The docs say nothing about an empty reply, so its behaviour is
  UNKNOWN (Q1). The risk is an apology instead of silence.
- **`thinkingAtTurnEnd` (acknowledge before every reply).** It masks the wait and does not shorten
  it. The vendor itself says "on a quick one it is a syllable in front of everything"
  (`update-agent.md:1411-1417`). It also adds TTS characters to every reply, and the founder
  disliked fillers (c79138bf, cd543854).
- **Cartesia `sonic-turbo` for speed.** Its language list in LiveKit's table has no Telugu
  ([docs.livekit.io Cartesia](https://docs.livekit.io/agents/models/tts/cartesia/), REPORTED). The
  ThinnestAI own-voice model field accepts only `sonic-3.6`, `sonic-3.6-2026-08-27`, `sonic-3.5`,
  `sonic-3` and `sonic-2` (`api-reference/bring-your-own-keys.md:401`). Cartesia calls sonic-3.6
  "our fastest" ([docs.cartesia.ai latest](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest),
  VVD, no figure). We are already on the fastest Telugu option.
- **A Mumbai Gemini region.** Not available to us. ThinnestAI uses a Gemini API key, and 3.1
  Flash-Lite on Vertex shows the global endpoint only (§1).
- **Explicit context caching for speed.** Google publishes no latency figure. It was rejected on
  cost at our volume (35a5ccdb).
- **Lowering `maxReplyTokens`.** It caps the end of a reply, not its first word (f7815b0c).
- **Vendor end-of-turn models for Telugu.** None of the well-known ones lists Telugu:
  - LiveKit's turn detector lists Hindi, not Telugu
    ([docs.livekit.io turn-detector](https://docs.livekit.io/agents/logic/turns/turn-detector), VVD);
  - Pipecat Smart Turn: 23 languages incl. Hindi and Marathi, no Telugu
    ([github.com/pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn), VVD via search);
  - Deepgram Flux Multilingual: 10 languages incl. Hindi, no Telugu
    ([deepgram.com press release](https://deepgram.com/learn/deepgram-launches-flux-multilingual-press-release), VP);
  - AssemblyAI Universal-3.5 Pro Streaming: Hindi among 18, Telugu not shown
    ([assemblyai.com/docs](https://www.assemblyai.com/docs/streaming/universal-streaming/turn-detection), REPORTED via search);
  - Sarvam realtime STT accepts te-IN but documents only VAD silence endpointing
    ([docs.sarvam.ai realtime streaming](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming), REPORTED via search);
  - only Soniox markets Telugu with "semantic" endpoint detection
    ([soniox.com Telugu](https://soniox.com/speech-to-text/use-cases/voice-agents/telugu), VP,
    API parameters unverified).

  Soniox is on ThinnestAI's own-key STT list (`api-reference/bring-your-own-keys.md:155`). But our
  sets keep ThinnestAI's recogniser, and an own STT that "cannot listen in real time" falls back to
  Timer (`channels/voice.md:974-976`). This is a possible later path, not a recommendation.

## 5. Caller half-sentences ("నాకొక", "మాకు", "కారం పొడి కావాలండి ఒక"): cost and latency per option

Inputs:
- Cartesia ₹4.84 per 1K characters, founder-attested (12f1aa47).
- ₹95/$ (D-768).
- Gemini uncached input at the ₹0.0238/ktok rung (35a5ccdb); about 6k input tokens per reply, 35%
  cached (84048b66).
- Output: 35 tokens at $1.50/M × 95 ≈ ₹0.005.
- Line time on `llm_voice`: ₹1.00/min (a84fd5cd).

All per-event figures are ESTIMATES. "LLM per reply" ≈ ₹0.09-0.14, depending on the cache.

| Option | Characters | TTS ₹ | LLM ₹ | Extra line time | Total ₹ per event | Latency effect | Status |
|---|---|---|---|---|---|---|---|
| Full reply to the fragment (~100 Telugu chars) | 100 | 0.48 | 0.09-0.14 | ~5 s of talk and repair ≈ 0.08 | **≈0.65-0.70** | The caller is cut off; the conversation repairs | Today's behaviour under `timer` 0.25 s |
| Short nudge ("చెప్పండి అండి", ~14 chars) | 14 | 0.07 | 0.09-0.14 | ~1 s ≈ 0.02 | **≈0.18-0.23** | Still a full model turn (~0.93 s) before it speaks | Prompt-only; possible today, but needs the model to classify a fragment reliably (untested) |
| Silence: model returns nothing | 0 | 0 | 0.09-0.14 (the model still ran) | 0 | **≈0.09-0.14, if silence is honoured** | None | **UNKNOWN / likely unsafe**: docs point to a fallback or an apology (§4). Q1 |
| `turnSilenceSeconds` 0.25 → 0.5 on every reply | 0 | 0 | 0 | +0.25 s × ~12 replies ≈ 3 s/call ≈ 0.05 per call | **≈0.05 per call**, plus +250 ms on every reply (≈15% of the 1.69 s median) | Slower on every turn | Possible today (D-751 "Relaxed" preset); catches pauses up to 0.5 s only |
| `ear` (or `smart`, ceiling 0.6 s) | 0 for the fragment; Ear acknowledgements may add a few characters (Q3) | 0 to ~0.03 | 0 when it waits, but dropped early answers may bill tokens (Q4) | ~0 | **≈0 to 0.03** | Ear: vendor says end of turn is detected sooner and it waits only when the thought is unfinished. Smart: "replies start later" (`update-agent.md:1428-1431`) | Ear needs Telugu real-time recognition (Q2). Recommended first test (lever 1) |

Reading:
- The nudge is about a third the cost of a full reply, but it does not remove the wait. Silence
  is cheapest only if the platform honours it, which the docs argue against.
- A blanket longer pause costs little money but adds latency to every reply.
- The option the vendor built for this exact case is `ear`, at no extra charge. Whether it
  works in Telugu is the one question that decides it.
