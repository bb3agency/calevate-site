# Speech and language technology for real-time Indian-language phone voice agents (Telugu first), state as of October 2026

Read date for every source below: 30 Oct 2026 unless stated. Evidence labels:
- **[VENDOR]**: the vendor's own page, read directly.
- **[VENDOR via search]**: a vendor figure quoted in a search-result summary. The vendor page itself was not opened.
- **[3P]**: a third-party blog or aggregator. Not independent measurement unless it says it measured.
- **[INDEP]**: independent measurement, either peer-reviewed or an academic preprint.

Pages fetched directly this session: Sarvam pricing, Cartesia model docs, Google Gemini API pricing, and arXiv 2608.08235 (SraVaani). OpenAI's pricing page returned 403, and so did the MarkTechPost Saaras V4 article. Every other figure comes from search-result summaries and must be re-verified before it reaches money or a client-facing claim (hard rule 11).

FX: INR↔USD conversions in the Inferences sections use **₹95/USD**, which is Calevate's internal planning rate (D-768, repo-internal). It is not a market rate.

## 1. STT for Telugu / Indian languages and code-mixing

### Takeaway
The only independent multi-system Telugu comparison found is IISc's SraVaani paper (Aug 2026). It puts IndicConformer-600M, Sarvam Saaras v3 and Gemini 3 Flash within about 4 WER points of each other on Telugu, at 25–29% average WER across 6 datasets. That is far worse than vendor headline figures. Price-wise, Sarvam (₹0.49/min) and Deepgram/Smallest (about $0.004–0.009/min) sit in the same band. Nobody publishes independent Telugu streaming accuracy on 8 kHz phone audio, so a bake-off on our own call audio is the only way to rank them.

### Cited Findings
- **Independent Telugu WER, averaged over 6 datasets [INDEP]:**
  - SraVaani-1.0: 25.1
  - IndicConformer-600M: 26.4
  - Sarvam Saaras v3: 28.7
  - Gemini 3 Flash: 28.9
  - Paper: arXiv 2608.08235, submitted 8 Aug 2026 by IISc SPIRE Lab / ARTPARK.
- **Same paper, other languages [INDEP]:**
  - Hindi: IndicConformer 13.8, SraVaani 14.0, Saaras v3 14.5, Gemini 3 Flash 14.5.
  - Tamil: SraVaani 26.2, IndicConformer 30.1, Saaras v3 32.1.
  - Kannada: SraVaani 27.4, IndicConformer 28.4, Saaras v3 31.2, Gemini 3 Flash 32.9.
  - Datasets include Kathbath and FLEURS; IndicVoices and Vistaar were not evaluated.
  - Gemini 3 Flash scored 8.7 on FLEURS-Hindi and 8.5 on Kathbath-Hindi.
  - Source: [arXiv 2608.08235](https://arxiv.org/html/2608.08235v1)
- **Agricultural-domain Telugu benchmark [INDEP, as summarised by search; not opened]:**
  - Google Speech-to-Text: 33.2% WER, ranked first.
  - Gemini 2.5 Pro: 37.9%.
  - Sarvam: 46.5%, ranked sixth.
  - The paper's table lists Chirp 3 without Telugu support.
  - Source: [arXiv 2602.03868](https://arxiv.org/html/2602.03868v1)
  - Contrast: in SraVaani, Saaras v3 is near the leaders. These are different domains and different Sarvam versions.
- **Other Indic ASR benchmarks that exist but whose Telugu figures were not retrieved:**
  - Vimarsha, which evaluates IndicConformer and Saaras v3: [arXiv 2609.24199](https://arxiv.org/pdf/2609.24199)
  - Josh Talks "Voice of India" national ASR benchmark, with a Telugu leaderboard: [voiceofindiablogs.ai.joshtalks.com](https://voiceofindiablogs.ai.joshtalks.com/)
  - Indic DiarBench: [arXiv 2607.23808](https://arxiv.org/pdf/2607.23808)
- **Sarvam STT price [VENDOR]:**
  - ₹0.49/min real-time or batch on PAYG.
  - Plan rates: Pro ₹0.45, Growth ₹0.41, Business ₹0.38.
  - Diarization: ₹0.59/min PAYG.
  - The pricing page names no model versions (Saarika/Saaras) and gives no latency figures.
  - Source: [sarvam.ai/api-pricing](https://www.sarvam.ai/api-pricing)
- **Sarvam Saaras V4:**
  - Released around 26 Sep 2026.
  - Covers all 22 scheduled Indian languages plus English.
  - Claims time-to-first-token under 150 ms over WebSocket [VENDOR via search].
  - Sources: [MarkTechPost](https://www.marktechpost.com/2026/09/26/sarvam-ai-releases-saaras-v4-a-speech-to-text-model-for-all-22-indian-languages-and-global-english/) (403 on fetch); [mindcat.ai](https://mindcat.ai/blog/sarvam-saaras-v4-speech-to-text) [3P]
  - Saaras V4 has no independent Telugu WER yet.
- **Sarvam streaming finalisation latency [INDEP-ish community benchmark, Bangla, not Telugu]:**
  - Sarvam: 0.9 s median from end of speech to final transcript.
  - OpenAI: 4.2 s.
  - Gemini Live: more than 10 s.
  - Source: [riverborn/bangla-stt-benchmark-results](https://huggingface.co/datasets/riverborn/bangla-stt-benchmark-results)
- **Deepgram Nova-3:**
  - Telugu is in monolingual mode.
  - A May 2026 update claims improved Telugu, Tamil, Bengali and Marathi accuracy, without numbers [VENDOR via search].
  - Source: [futureagi](https://futureagi.com/blog/speech-to-text-apis-in-2026-benchmarks-pricing-developer-s-decision-guide/)
- **Deepgram streaming prices [3P aggregators; conflicting; confirm on deepgram.com]:**
  - Nova-3 monolingual: $0.0077/min list, about $0.0048 promo.
  - Nova-3 multilingual: $0.0092/min list, about $0.0058 promo.
  - Flux Multilingual (built-in turn detection): $0.0078/min PAYG.
  - Sources: [diyai.io](https://diyai.io/ai-tools/speech-to-text/deepgram-pricing-2026/); [pricingsaas 2026Q2 diff](https://pricingsaas.com/companies/deepgram/diffs/2026Q2)
- **ElevenLabs Scribe v2:**
  - Scribe v2 Realtime: $0.39/hour; batch Scribe v2: $0.22/hour [VENDOR via search].
  - Claims under 150 ms latency across 90+ languages.
  - Sources: [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api); [cxodigitalpulse](https://www.cxodigitalpulse.com/elevenlabs-launches-scribe-v2-realtime-for-sub-150-ms-live-transcription-across-90-languages/)
  - Telugu WER: Soniox (a competitor) claims 1.25% for Soniox against 3.16% for ElevenLabs. This is a competitor's own benchmark, not independent: [soniox.com](https://soniox.com/compare-stt/soniox-vs-elevenlabs/telugu)
- **Smallest.ai Pulse STT [VENDOR via search]:**
  - $0.004/min realtime, $0.003/min batch.
  - Claims 64 ms model latency.
  - South Indian languages (ta, te, kn, ml, multi-south-indic) are streaming-only, India-region-only, and **Beta**.
  - Source: [docs.smallest.ai Pulse](https://docs.smallest.ai/model-cards/speech-to-text/pulse)
- **Gnani:** no official pricing was found. One third-party source cites about 300 ms STT latency with enterprise pricing [3P]: [autointerviewai](https://www.autointerviewai.com/blog/gnani-ringg-smallest-new-indian-voice-ai-models-2026)
- **Google streaming transcription (gemini-3.5-transcribe-live) [VENDOR]:** $0.005/min audio in plus $0.004/min text out. Source: [ai.google.dev pricing](https://ai.google.dev/gemini-api/docs/pricing)

### Inferences
- On independent data, open IndicConformer-600M (AI4Bharat, MIT-licensed) is at least as accurate on Telugu as Saaras v3 and Gemini 3 Flash. Self-hosting it is therefore viable on quality. Hosting cost and streaming latency were not measured here.
- Telugu WER of 25–29% on read and conversational benchmarks means 8 kHz phone audio will plausibly be worse. Phone-band Telugu WER for every system is UNKNOWN.
- At ₹95/$, Sarvam's ₹0.49/min is about $0.0052/min. That is roughly price parity with Deepgram multilingual promo and Smallest Pulse. STT is under ₹1/min everywhere and is not the cost driver.

### Gaps
- No independent Telugu WER for Saaras V4, Deepgram Nova-3, Scribe v2, gpt-4o-transcribe, Chirp 3 or Gnani.
- No independent Telugu code-mix (Tenglish) benchmark found.
- No 8 kHz/μ-law telephony Telugu evaluation found.
- OpenAI transcribe pricing not read (403).
- ThinnestAI's own STT model and accuracy are UNKNOWN from public sources.

## 2. TTS: Telugu naturalness, latency, price, cloning

### Takeaway
Cartesia Sonic 3.6 officially supports Telugu, Tamil and Kannada. Sarvam's new Bulbul V4 Flash is ₹1.00 per 1K characters, a third of Bulbul V3's price. No independent Telugu naturalness (MOS) ranking across vendors was found.

### Cited Findings
- **Cartesia Sonic 3.6 [VENDOR]:**
  - Current model is `sonic-3.6` (snapshot `sonic-3.6-2026-08-27`).
  - Covers 44 languages, including Telugu (`te`), Tamil (`ta`), Kannada (`kn`), Malayalam, Marathi, Bengali, Gujarati, Punjabi, Odia and Urdu.
  - The docs give no latency figure and no pricing.
  - Source: [docs.cartesia.ai](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest)
- **Cartesia latency [3P]:**
  - Vendor claims under 90 ms.
  - One third-party measurement found about 166 ms median including network, and advises planning for 166–190 ms.
  - Source: [invideo.io](https://invideo.io/blog/cartesia-sonic-ai-voice/)
- **Cartesia pricing [3P]:**
  - Credits at 1 per character.
  - Plans: Startup $49/mo for 1.25M credits; Scale $299/mo for 8M credits.
  - Together AI resells Sonic-3 at $65 per 1M characters.
  - Sources: [cloudtalk](https://www.cloudtalk.io/blog/cartesia-pricing/); [together.ai](https://www.together.ai/models/cartesia-sonic-3)
- **Sarvam TTS prices, per 1K characters [VENDOR]:**
  - Bulbul V4 Flash: ₹1.00 PAYG; Pro ₹0.925, Growth ₹0.85, Business ₹0.80.
  - Bulbul V3: ₹3.00 PAYG; Business ₹2.60.
  - Voice cloning: ₹2.00 per 1K characters.
  - Source: [sarvam.ai/api-pricing](https://www.sarvam.ai/api-pricing)
- **Sarvam Telugu streaming latency [VENDOR via search]:**
  - Claims under 250 ms to first byte over WebSocket.
  - Cap: 2,500 characters per request.
  - Source: [sarvam.ai Telugu TTS](https://www.sarvam.ai/apis/text-to-speech/telugu)
- **ElevenLabs Flash v2.5 [VENDOR via search]:**
  - $0.04 per 1K characters, 32 languages.
  - Telugu support **not confirmed**.
  - Source: [elevenlabs.io/pricing/api](https://elevenlabs.io/pricing/api)
- **Smallest Lightning v3.1:**
  - Vapi Humanness Index measured 420 ms latency including network, at about $14.50 per 1M characters [3P measured]: [humannessindex.vapi.ai](https://humannessindex.vapi.ai/models/smallestai-lightning-v31)
  - Vendor claims about 200 ms TTFB.
- **Google Gemini TTS, per 1M tokens, with 25 audio tokens per second [VENDOR]:**
  - gemini-3.8-flash-tts: $0.50 in / $9.00 audio out through 31 Dec 2026, doubling to $1.00 / $18.00 from 1 Jan 2027.
  - gemini-3.8-flash-lite-tts: $0.50 in / $6.00 out in 2026, doubling to $12.00 in 2027.
  - Source: [ai.google.dev pricing](https://ai.google.dev/gemini-api/docs/pricing)
- **Indic TTS accent benchmark exists (PSP, per-dimension accent):** [arXiv 2604.25476](https://arxiv.org/pdf/2604.25476). Its vendor results were not retrieved.

### Inferences
Per-minute TTS cost assumes 600 characters of agent speech per call-minute. That figure is an assumption, not a measurement.

| Option | Cost per call-minute |
|---|---|
| Bulbul V4 Flash | about ₹0.60 |
| Bulbul V3 | about ₹1.80 |
| Cartesia at the $65/1M reseller rate | about $0.039 ≈ ₹3.7 |
| Gemini 3.8 flash-lite TTS, 30 s of audio (750 tokens × $6/1M) | about $0.0045 ≈ ₹0.43 (2026 price) |

- Cartesia is the most expensive leg in the Studio stack.
- Bulbul V4 Flash and Gemini TTS are cheaper by an order of magnitude. Their Telugu quality against Cartesia is UNKNOWN.

### Gaps
- No independent Telugu MOS or naturalness comparison found.
- Cartesia's official per-character or per-minute price was not read on cartesia.ai.
- No independent Telugu TTFA measurements found.
- Azure, Chirp 3 HD and Gnani Telugu TTS pricing were not retrieved.

## 3. LLMs for live calls

### Takeaway
gemini-2.5-flash-lite is still Google's cheapest listed text model, at $0.10 input / $0.40 output per 1M tokens, with cached input $0.01. Newer Flash-Lite generations cost 2.5–6× more on output. Sarvam's own 105B model is very cheap in INR.

### Cited Findings
- **Google Gemini API, per 1M tokens, paid Standard tier [VENDOR]:**

  | Model | Input | Output | Cached input |
  |---|---|---|---|
  | gemini-2.5-flash-lite | $0.10 text, $0.30 audio | $0.40 | $0.01 |
  | gemini-2.5-flash | $0.30 | $2.50 | |
  | gemini-3.1-flash-lite | $0.25 | $1.50 | |
  | gemini-3.5-flash-lite | $0.30 | $2.50 | |
  | gemini-3-flash-preview (labelled legacy) | $0.50 | $3.00 | |
  | gemini-3.6-flash / 3.8-flash | $0.75 | $3.75 | |

  - The 3.6/3.8 Flash prices double from 1 Jan 2027.
  - Cache storage costs $1.00/hr; batch is half price.
  - Source: [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)
- **Sarvam-hosted LLMs, per 1M tokens, input / cached input / output [VENDOR]:**
  - Sarvam 105B: ₹15 / ₹5 / ₹60.
  - GLM 5.3 Flash: ₹13.50 / ₹2.50 / ₹45.
  - DeepSeek V4.1 Flash: ₹25 / ₹0.50 / ₹105.
  - Gemma 4: ₹35 / ₹10 / ₹90.
  - Sarvam-M is no longer listed.
  - Source: [sarvam.ai/api-pricing](https://www.sarvam.ai/api-pricing)
- **Gemini in India-region hosting:**
  - Google's data-residency page lists Mumbai (asia-south1) for Gemini 2.5 Flash and Pro ML processing.
  - A flash-lite row was not confirmed.
  - Live models are excluded from the global endpoint.
  - Sources: [Vertex data residency](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/data-residency); [Firebase locations](https://firebase.google.com/docs/ai-logic/locations?api=vertex)

### Inferences
- **Illustrative per-minute LLM cost (assumption):** 5 turns per minute, about 3K input tokens per turn, 60 output tokens per turn.
  - gemini-2.5-flash-lite: 15K × $0.10/1M + 300 × $0.40/1M ≈ $0.0016/min ≈ ₹0.15.
  - With caching of the static prompt: lower still.
  - gemini-3.5-flash-lite: about $0.0053/min ≈ ₹0.50.
  - The LLM is not the cost driver at Flash-Lite tier.
- Gemini 3 Flash's price is now marked "legacy". That supports staying on 2.5-flash-lite for cost. Whether the newer 3.x Flash-Lite models support thinking fully off is UNKNOWN from this read.

### Gaps
- No independent time-to-first-token figures (e.g. Artificial Analysis) were retrieved for any model from India.
- No independent Telugu conversational-quality benchmark comparing Gemini, GPT-5 mini/nano, Claude Haiku and Sarvam 105B was found.
- OpenAI and Anthropic prices were not read: OpenAI's page returned 403 and Anthropic's was not fetched.

## 4. Speech-to-speech / native-audio models

### Takeaway
Gemini Live models are priced per minute and are cheap: about $0.005/min audio in and $0.018/min audio out. However, the only Telugu evidence is vendor-adjacent blogs. One community benchmark found Gemini Live's transcript finalisation very slow, at more than 10 s on Bangla. There is no independent Telugu phone-call readiness evidence.

### Cited Findings
- **Gemini Live pricing [VENDOR]:**
  - Models: gemini-3.8-live and gemini-3.1-flash-live-preview.
  - Input: $3.00/1M audio tokens ≈ $0.005/min.
  - Output: $12.00/1M ≈ $0.018/min.
  - Text: $0.75 in / $4.50 out.
  - gemini-2.5-flash-native-audio-preview-12-2025: $3 audio in, $12 audio out.
  - Source: [ai.google.dev pricing](https://ai.google.dev/gemini-api/docs/pricing)
- **Latency claims [3P, conflicting]:**
  - Gemini 3.1 Flash Live: about 200 ms to first audio; GPT Realtime 1.5: about 300 ms ([flowtivity](https://flowtivity.ai/blog/gemini-3-1-flash-live-vs-gpt-realtime-1-5-voice-agent-comparison-2026/)).
  - Gemini Live on Vertex: about 377 ms, against about 1,578 ms through AI Studio ([edesy](https://edesy.in/ai-voice-assistant/blog/gemini-live-vs-openai-realtime)).
  - A Mumbai SIP server connected directly to asia-south1 avoided transatlantic routing (same source).
- **Telugu support:** listed among Gemini Live's native languages by third-party blogs. Not verified on Google's docs.
- **OpenAI GPT Realtime 2 / 1.5:** named in third-party comparisons ([mindstudio](https://www.mindstudio.ai/blog/openai-gpt-realtime-2-vs-google-gemini-tts)). Pricing was not read (403).

### Inferences
At about $0.0115/min for 50/50 talk (≈ ₹1.1), Gemini Live is cheaper than the cascaded stack with Cartesia. Adopting it would mean bypassing ThinnestAI's STT/TTS cascade, which conflicts with the current engine architecture (D-678..). Telugu voice quality and function-calling reliability are UNKNOWN.

### Gaps
- No independent Telugu S2S evaluation.
- Ultravox, Moshi-class and Sarvam S2S offerings were not researched within this budget.

## 5. Turn detection, interruption, noise, IVR, codecs

### Takeaway
Semantic turn detectors officially cover Hindi only among Indic languages. Telugu still relies on VAD plus a tuned silence delay, or on Deepgram Flux Multilingual's built-in end-of-turn detection.

### Cited Findings
- **LiveKit turn detectors:**
  - The multilingual model supports 14 languages; Hindi is the only Indic one.
  - Needs about 400 MB RAM and about 25 ms per inference.
  - An audio-based turn detector also exists, with Hindi as its only Indic language.
  - Sources: [LiveKit docs](https://docs.livekit.io/agents/logic/turns/turn-detector); [LiveKit blog](https://livekit.com/blog/improved-end-of-turn-model-cuts-voice-ai-interruptions-39)
- **Sarvam's LiveKit production guide [VENDOR via search]:** recommends Sarvam VAD with a tuned `min_delay` over the semantic detector for Indic languages. Source: [docs.sarvam.ai](https://docs.sarvam.ai/api/integration/livekit-production-best-practices)
- **Community models:**
  - A Tamil smart-turn model: [HF santhosh-005/smart-turn-tamil](https://huggingface.co/santhosh-005/smart-turn-tamil)
  - VideoSDK Namo, claiming 93.1% Hindi accuracy, not verified: [VideoSDK blog](https://blogs.videosdk.live/namo-turn-detection-v1-semantic-turn-detection-for-ai-voice-agents)
- **Deepgram Flux Multilingual:** STT with integrated turn detection, $0.0078/min [3P]. Source: [diyai.io](https://diyai.io/ai-tools/speech-to-text/deepgram-pricing-2026/)

### Gaps
- No Telugu semantic turn detector found.
- Krisp, backchannel, voicemail/IVR detection and 8 kHz codec effects were not researched within this budget.
- ThinnestAI's own turn-taking implementation is UNKNOWN from public sources.

## 6. End-to-end latency budget and Indian regions; cost floor

### Takeaway
Component vendor claims sum to about 500–800 ms. No independent mouth-to-ear Telugu PSTN measurement was found. A cascaded stack built from Indian vendors can cost about ₹1–1.5/min before telephony, against ₹4.50 and ₹6.00 retail.

### Cited Findings
- **Component latencies:** STT TTFT under 150 ms (Sarvam V4) [VENDOR via search]; TTS 166–190 ms (Cartesia, 3P measured) or under 250 ms (Bulbul) [VENDOR]. See §1 and §2 for sources.
- **Indian GPU and model regions:**
  - Gemini 2.5 Flash and Pro processing is listed in asia-south1 ([Vertex data residency](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/data-residency)).
  - Smallest's South Indic STT runs India-region only ([docs.smallest.ai](https://docs.smallest.ai/model-cards/speech-to-text/pulse)).
- **Agent full-stack roundup [3P]:** $0.05–0.21 per minute. Source: [autointerviewai](https://www.autointerviewai.com/blog/gnani-ringg-smallest-new-indian-voice-ai-models-2026)

### Inferences
Illustrative floor using the assumptions above:

| Leg | Option | Cost per minute |
|---|---|---|
| STT | Sarvam | ₹0.49 |
| LLM | gemini-2.5-flash-lite | ₹0.15 |
| TTS | Bulbul V4 Flash | ₹0.60 |
| **Total (excluding telephony and engine fees)** | | **≈ ₹1.24** |

- Swapping Cartesia in for Bulbul V4 Flash adds about ₹3.1/min.
- Calevate's ThinnestAI band rates (₹1.00–2.50/min, repo-internal, VENDOR-PUBLISHED per CLAUDE.md) bundle telephony. They are not directly comparable.

### Gaps
- No independent India PSTN mouth-to-ear measurement.
- No Indian telephony per-minute rates gathered in this lane.
- Whether gemini-2.5-flash-lite and the Live models are served from asia-south1 is unconfirmed.
