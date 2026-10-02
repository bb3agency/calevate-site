> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is Voice Transcription (ASR)? How Telephony Affects Accuracy (2026)

> Voice transcription (ASR) turns speech into text. How it works, streaming vs batch, Word Error Rate, key features, and why telephony audio quality decides accuracy.

*July 3, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

Voice transcription is the process of converting spoken audio into written text, and the technology that does it is called **ASR (automatic speech recognition)**. It is the layer that lets a voice AI agent understand what a caller just said, lets a contact centre search a million recorded calls, and lets a meeting tool produce a readable summary. If you are building anything that listens to a phone call, ASR is the part that turns sound into something software can act on.

This guide goes well past the dictionary definition: how an ASR system works from raw audio to words, the difference between streaming and batch transcription, how accuracy is measured with Word Error Rate (WER), the features that separate a usable transcript from a wall of text, and the one factor most articles skip: why the **quality of the underlying telephony audio limits how accurate ASR can be**. Preserving the best source audio available matters more than relabelling or upsampling narrowband audio after capture.

<Note>
  **Key takeaways**

  * **Voice transcription (ASR)** is the conversion of speech audio into text by an automatic speech recognition model; it is the "ears" of any [voice AI](/docs/blogs/what-is-a-voice-api) system.
  * A modern ASR pipeline is **audio → feature extraction → acoustic + language modelling (or one end-to-end transformer) → decoding → text**.
  * **Streaming** transcription returns words within a few hundred milliseconds for live voice AI; **batch** transcription processes a whole recording afterward for analytics.
  * Accuracy is measured by **Word Error Rate (WER)** - the percentage of words inserted, deleted, or substituted versus a reference.
  * The biggest accuracy lever is the **audio itself**: narrowband 8 kHz telephony, noise, and packet loss raise WER long before the model is the bottleneck. Legacy real-world telephony WER often runs **40–50%**.
  * Vobiz is the **transport and recording layer** that sends inbound L16 audio at 8 or 16 kHz, or μ-law at 8 kHz, to your ASR pipeline. It powers the speech-to-text stack; it does not replace it.
</Note>

## What is voice transcription (ASR)?

**Voice transcription** is the conversion of spoken language into written text. **Automatic speech recognition (ASR)** is the machine-learning technology that performs that conversion without a human typist. [Speech recognition is an interdisciplinary subfield of computer science and computational linguistics that develops methods enabling the recognition and translation of spoken language into text by computers](https://en.wikipedia.org/wiki/Speech_recognition).

The one distinction that matters: ASR is **not** the same as voice *identification*. ASR answers "what was said"; speaker recognition (or voice biometrics) answers "who said it." A transcription system produces the words; a separate step called diarization labels which speaker produced which words. Conflating the two is the most common mistake in this space.

It also helps to be precise about where ASR sits. A full voice AI turn is a chain: **ASR (speech to text) → an LLM that decides what to say → TTS (text to speech) that speaks the reply**. Vobiz is the telephony infrastructure carrying audio in and out of that chain - it moves the media and records it cleanly. The ASR model itself is provided by engines like Deepgram, OpenAI Whisper, or Sarvam, and the agent logic by platforms like Vapi or Retell. Understanding ASR means understanding that one link in the chain.

## How ASR works

A modern ASR system turns a stream of audio samples into a sequence of words in roughly four stages. Older systems split the job across separate models; newer ones fold most of it into a single neural network, but the conceptual stages are the same.

### 1. Audio capture and feature extraction

Sound enters as a waveform - thousands of amplitude samples per second. Raw samples are noisy and high-dimensional, so the system first extracts **features**: compact numerical representations of the audio that emphasise the parts of the signal that carry speech. The classic representation is a set of **Mel-frequency cepstral coefficients (MFCCs)** or a mel spectrogram, computed over short overlapping windows (typically 10–25 ms each). This is the step where audio quality bites: if the signal arriving here is band-limited or noisy, the features are degraded, and no downstream model can recover information that was never captured.

### 2. Acoustic modelling

The **acoustic model** maps those audio features to the smallest units of sound, called **phonemes** (a language like English has roughly 40). [Acoustic models statistically represent the relationship between an audio signal and the phonemes that make up speech](https://en.wikipedia.org/wiki/Speech_recognition). Historically this was done with **Hidden Markov Models (HMMs)** combined with Gaussian mixtures; [HMMs model speech as a sequence of states with probabilistic transitions](https://en.wikipedia.org/wiki/Hidden_Markov_model), and they dominated ASR for decades. Today the acoustic model is almost always a deep neural network.

### 3. Language modelling

Acoustics alone are ambiguous: "recognize speech" and "wreck a nice beach" sound nearly identical. The **language model** resolves that ambiguity by scoring how likely a given word sequence is in the target language and domain. It is the difference between a phonetically plausible transcript and a grammatically sensible one, and it is why a model tuned on medical dictation transcribes drug names that a general model mangles.

### 4. Decoding (and the end-to-end shift)

The **decoder** searches the combined acoustic and language scores for the most probable word sequence, emitting the final text. In classic pipelines these three models are trained and tuned separately.

The big change since the mid-2010s is **end-to-end** ASR, where a single neural network learns the whole mapping from audio to text. Two architectures dominate: models trained with [Connectionist Temporal Classification (CTC), which aligns input audio frames to output characters without requiring a pre-segmented transcript](https://en.wikipedia.org/wiki/Connectionist_temporal_classification), and **transformer / sequence-to-sequence** models. OpenAI's Whisper is a well-known example: [an encoder-decoder transformer trained on 680,000 hours of multilingual, multitask supervised data collected from the web](https://cdn.openai.com/papers/whisper.pdf), which made robust multilingual transcription broadly available. End-to-end models fold the acoustic and language modelling into one network, which is why most production ASR engines today are a single model rather than a three-stage stack.

## Streaming vs batch transcription

There are two fundamentally different ways to run ASR, and choosing the wrong one breaks the use case. The split is about *when* you get the text.

**Streaming (real-time) transcription** processes audio continuously as it arrives and emits words within a few hundred milliseconds, often as "partial" hypotheses that get refined as more context arrives. This is non-negotiable for [voice AI agents](/docs/blogs/what-is-a-voice-api): the agent cannot answer a question it has not finished hearing, and a one-second transcription delay added to LLM and TTS latency makes the conversation feel broken. Streaming ASR is fed over a live [bidirectional audio stream](/docs/audio-streams) - for telephony that means a [WebSocket media stream](/docs/concepts/streaming-websockets) carrying the call audio to the ASR engine as it happens.

**Batch (offline) transcription** processes a complete recording after the fact. Because it can see the entire file, it can use more context and heavier models, so it is typically more accurate per word and is the right tool for [post-call analytics](/docs/solutions/post-call-analytics), compliance archives, and search over recorded calls. Batch ASR runs against the audio file produced by [call recording](/docs/solutions/call-recording).

| Dimension | Streaming transcription | Batch transcription |
| - | - | - |
| **When text appears** | While the person is speaking | After the call/recording ends |
| **Latency** | Hundreds of milliseconds | Seconds to minutes |
| **Context window** | Limited (must commit early) | Full recording |
| **Typical accuracy** | Slightly lower (less context) | Slightly higher |
| **Audio source** | Live [WebSocket stream](/docs/xml/stream) | Stored [recording](/docs/platform/voice/recordings) |
| **Best for** | Live voice agents, agent assist, captions | Analytics, QA, compliance, search |
| **Interruptible (barge-in)** | Yes | N/A |

A real stack often uses both: streaming ASR to drive the live agent, then batch ASR over the [recording](/docs/platform/voice/recordings) afterward for a more accurate transcript and analytics.

## Measuring accuracy: Word Error Rate (WER)

The standard metric for ASR accuracy is **Word Error Rate (WER)**. It compares the machine transcript against a human reference transcript and counts the edits needed to fix it. [WER is derived from the Levenshtein distance at the word level and is computed as the sum of substitutions, deletions, and insertions divided by the number of words in the reference](https://en.wikipedia.org/wiki/Word_error_rate):

```
WER = (S + D + I) / N

S = substitutions   D = deletions   I = insertions   N = words in the reference
```

A WER of **10%** means one word in ten is wrong; **lower is better**, and a perfect transcript is 0%. WER is widely used precisely because it is simple and comparable, but it has known limitations: it weights every word equally, so a missed "not" (which flips meaning) counts the same as a missed "the," and it penalises harmless paraphrases. It is a proxy for usefulness, not usefulness itself - but it is the proxy everyone reports.

### What drives WER up

Most of the things that wreck transcription accuracy are *not* the model. They are the input:

* **Narrowband telephony audio.** Traditional phone calls are sampled at **8 kHz**, capturing only frequencies up to \~3.4 kHz. That throws away the high-frequency energy that distinguishes consonants like *s*, *f*, and *th* - exactly the sounds ASR confuses most. Wideband audio at **16 kHz or 24 kHz** keeps that information.
* **Background noise and reverberation.** Street noise, cross-talk, and echo bury the speech signal and inflate WER sharply.
* **Accents, dialects, and code-switching.** Models trained mostly on one accent degrade on others; mixed-language speech (common in India) is harder still.
* **Packet loss and jitter.** On a poor [VoIP](/docs/blogs/what-is-voip) path, dropped or late audio packets create gaps the model fills with garbage.
* **Domain vocabulary.** Names, drug names, SKUs, and jargon absent from training data get substituted with common words.

This is why **legacy telephony ASR routinely sees real-world WER of 40–50%** even when the same model scores in the single digits on clean studio audio. The model did not get worse - the audio did.

## ASR features that matter

Raw transcribed words are rarely enough. The features below turn a transcript into something a human or an LLM can actually use.

| Feature | What it does | Why it matters |
| - | - | - |
| **Speaker diarization** | Labels *who* spoke each segment ("Speaker 1 / Speaker 2") | Separates agent from caller; [partitions an audio stream into segments by speaker identity](https://en.wikipedia.org/wiki/Speaker_diarisation) |
| **Punctuation & casing** | Adds full stops, commas, capitalisation | Makes transcripts readable and parseable by downstream LLMs |
| **Word-level timestamps** | Marks the start/end time of each word | Enables search, captions, and jumping to a moment in a [recording](/docs/platform/voice/recordings) |
| **Custom vocabulary / boosting** | Biases the model toward your terms | Recovers names, products, and jargon the base model misses |
| **Confidence scores** | Per-word probability the transcript is right | Lets you flag low-confidence spans for review |
| **Number & entity formatting** | "two thirty pm" → "2:30 PM" | Cleaner data for analytics and automation |
| **Profanity / PII redaction** | Masks sensitive content | Compliance for recorded and stored transcripts |
| **Language identification** | Detects and switches language mid-call | Handles multilingual and code-switched calls |

For voice agents, the input side of this lives in [Gather speech input detection](/docs/xml/gather/detecting-speech-inputs), where the platform collects caller speech and hands it to recognition.

## How telephony affects ASR accuracy

Here is the part most "what is ASR" articles miss, and it is the whole game for phone-based transcription: **the ceiling on ASR accuracy is set by the audio, not the model.** You can wire up the best speech-to-text engine in the world, and if you feed it a narrowband, compressed, packet-dropping phone stream, it will still produce a bad transcript. Garbage in, garbage out - literally, frame by frame.

It is worth being precise about *why* a phone call is such hostile input for a speech model, because each stage of the telephony path removes or distorts information that ASR depends on, and the losses compound. Below are the six telephony factors that move WER the most, roughly in order of impact.

### 1. Narrowband sampling discards the consonant band

The legacy phone network is built around **8 kHz sampling**. By the [Nyquist–Shannon sampling theorem](https://en.wikipedia.org/wiki/Nyquist%E2%80%93Shannon_sampling_theorem), an 8 kHz sample rate can represent frequencies only up to **4 kHz** - and in practice the telephone channel is band-limited even further, to the classic [**300–3,400 Hz voice band**](https://en.wikipedia.org/wiki/Voice_frequency). That passband was chosen in the analog era to make speech *intelligible to humans*, not to a machine.

The problem is that the acoustic cues distinguishing **fricatives and sibilants** - *s*, *f*, *th*, *sh* - carry most of their energy **above 4 kHz**. Narrowband telephony simply throws that energy away, so the model literally never receives the signal that separates "fifteen" from "sixteen," or an *s* plural from a singular. This is the single largest pre-model accuracy lever. Delivering **wideband 16 kHz** or, better, **24 kHz** audio preserves that band and gives the model materially more to work with.

> **Careful caveat:** *upsampling* 8 kHz audio to 16 kHz before sending it to a wideband model does **not** recover the lost detail - the information was destroyed at capture. It can actually hurt, because the model now sees a wideband container with an empty top half. The fix is capturing and transporting wideband audio end to end, not resampling narrowband after the fact.

### 2. Lossy codecs and transcoding add quantisation noise

Phone audio is compressed for transport, and the codec leaves fingerprints the model has to see through. The PSTN standard, [**G.711**](https://en.wikipedia.org/wiki/G.711), uses **8-bit logarithmic [μ-law/A-law companding](https://en.wikipedia.org/wiki/%CE%9C-law_algorithm)** at 64 kbit/s - already a quantised approximation of the waveform. Lower-bitrate codecs (G.729 at 8 kbit/s, GSM) compress far harder and introduce spectral distortion that ASR models, often trained on clean PCM, are not used to.

Worse is **transcoding**: a call that hops Opus → G.711 → Opus across carrier boundaries is re-compressed at each leg, and the losses are *generational* - every transcode degrades the signal again, like photocopying a photocopy. A path with the **fewest codec hops** and a high-fidelity codec preserves the most signal for the model.

### 3. Packet loss and jitter create gaps the model fills with garbage

Telephony media rides [VoIP](/docs/blogs/what-is-voip), and on a congested path packets arrive late (**jitter**) or not at all (**loss**). To avoid audible silence, endpoints run [**packet loss concealment (PLC)**](https://en.wikipedia.org/wiki/Packet_loss_concealment), which *synthesises* plausible audio to bridge the gap. That synthetic fill is convincing enough for a human ear but is not real speech - and ASR transcribes it as phantom words or drops real ones. The jitter buffer that smooths playback also adds delay, which eats into the latency budget a live agent needs. A **low-latency, single-hop** media path minimises both loss and jitter, so the model sees continuous, in-order audio.

### 4. Mono mixing destroys speaker separation

How the call is recorded matters as much as how it is transported. If both parties are **mixed into a single mono channel**, then whenever they talk over each other the waveforms sum, and the model - plus any [diarization](https://en.wikipedia.org/wiki/Speaker_diarisation) step - has to untangle two voices from one signal. **Dual-channel (stereo) recording** keeps each leg of the call on its own track, so the caller and the agent are transcribed independently and overlap stops being a problem. For phone-based ASR, per-leg audio is one of the cheapest accuracy wins available.

### 5. Noise, echo, and signal-processing artifacts

Background noise and reverberation raise WER faster than almost anything else, because they bury the speech the feature extractor is trying to isolate. The telephony stack's own DSP can help or hurt here: aggressive **automatic gain control (AGC)**, **echo cancellation**, and **silence suppression / comfort noise** can clip or mangle quiet consonants. The right answer is **native noise cancellation in the media path** that cleans the signal *before* it reaches the model, rather than leaving the ASR engine to fight noise it should never have received.

### 6. The train/test mismatch nobody controls for

Underneath all of the above sits one principle from acoustic modelling: a model performs best on audio that resembles what it was trained on. Most modern ASR engines are trained heavily on **wideband, low-noise** data. Feed them **narrowband, companded, noisy telephony** and you have a textbook acoustic *mismatch* - the same model that scores single-digit WER on studio audio can degrade to **40–50% WER** on a legacy phone path. The model did not get worse; the input drifted away from what it learned. Closing that gap means delivering audio that looks more like the training distribution: wideband, denoised, and intact.

**The takeaway:** every one of these is a property of the **telephony layer**, decided before the ASR model ever runs. This is precisely the layer Vobiz owns. We do not build the ASR model - we make sure the audio reaching it is as clean as telephony allows, and we move it with the latency budget a live agent needs.

## How Vobiz handles transcription

[Vobiz](/docs/introduction) is the **telephony infrastructure** beneath your transcription stack - the transport, recording, and audio-quality layer that *powers* whichever ASR engine you choose. It is not a speech-to-text model and not an AI agent; it is the rails that get clean audio to and from them.

* **Direction-specific audio.** [Audio streaming](/docs/audio-streams) can send inbound L16 at 8 or 16 kHz, or μ-law at 8 kHz, to your ASR engine. Decode the payload using `start.mediaFormat` and avoid unnecessary transcoding.
* **Direct-carrier path, fewer codec hops.** Single-hop, direct-carrier connectivity minimises the transcoding that compounds losses across carrier boundaries, so the model sees the highest-fidelity signal the call can carry.
* **Streaming transport for real-time ASR.** Live call audio is delivered over [WebSocket bidirectional streaming](/docs/concepts/streaming-websockets) via [Stream](/docs/xml/stream), so streaming ASR can return partial words in real time and your agent can barge in.
* **Recording for batch transcription.** Native [call recording](/docs/solutions/call-recording) produces the stored audio your batch ASR and [post-call analytics](/docs/solutions/post-call-analytics) run against, available from [recordings](/docs/platform/voice/recordings) - keeping each call leg clean for accurate diarization.
* **Built for the latency budget.** Sub-80 ms single-hop, direct-carrier transport keeps the ASR → LLM → TTS turn under the \~1 second a natural conversation allows (legacy CPaaS paths hit 300–400 ms before the model even starts). It also minimises jitter and packet loss, so PLC rarely has to invent audio the model will mis-transcribe.
* **It powers your ASR, it does not replace it.** Bring Deepgram, Whisper, Sarvam, or any engine, and connect agents like Vapi, Retell, ElevenLabs, or Pipecat through the [integrations](/docs/integrations) hub. Vobiz moves and records the audio; you own the intelligence.

In short: the accuracy of your transcription is decided long before your ASR model runs, in the media path that carries the call. Vobiz is that media path.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is the difference between voice transcription and ASR?">
    They describe the same outcome from two angles. Voice transcription is the *result* - speech turned into written text. ASR (automatic speech recognition) is the *technology* that produces that result automatically, without a human typist.
  </Accordion>

  <Accordion title="What is a good Word Error Rate (WER) for ASR?">
    On clean, wideband audio, modern ASR engines often achieve single-digit WER (under 10%). On real-world telephony - narrowband 8 kHz audio with noise and accents - WER is much higher, historically **40–50%** on legacy paths. Improving the audio quality is usually the fastest way to lower WER.
  </Accordion>

  <Accordion title="What is the difference between streaming and batch transcription?">
    Streaming transcription returns text within a few hundred milliseconds as the person speaks, which is required for live voice agents. Batch transcription processes a complete recording afterward, can use more context, is usually slightly more accurate, and is used for analytics and compliance.
  </Accordion>

  <Accordion title="Why does phone-call transcription have so many errors?">
    Because traditional telephony is often **8 kHz narrowband** audio, which discards high-frequency detail, and phone calls add background noise, packet loss, and accents. Preserve the highest-quality source available, avoid unnecessary codec conversions, and configure the ASR decoder from the actual inbound media format.
  </Accordion>

  <Accordion title="Do audio codecs affect transcription accuracy?">
    Yes. Lossy codecs like G.711 (μ-law/A-law) and especially low-bitrate codecs add quantisation noise the model has to see through, and **transcoding** - re-compressing the call across multiple carrier hops - degrades the signal generationally. Fewer codec hops and a higher-fidelity codec preserve more of the speech the ASR engine needs.
  </Accordion>

  <Accordion title="Does upsampling 8 kHz phone audio to 16 kHz improve ASR?">
    No. Upsampling cannot recover frequency detail that was never captured; the consonant energy above 4 kHz was lost at the 8 kHz sampling stage. It can even hurt, because a wideband model then sees an empty upper band. The only real fix is capturing and transporting wideband (16–24 kHz) audio end to end.
  </Accordion>

  <Accordion title="Should I record calls in mono or dual-channel for transcription?">
    Dual-channel (stereo), where the caller and agent are on separate tracks. Mono mixes both voices into one waveform, so overlapping speech is hard to untangle and diarization suffers. Per-leg audio lets each side be transcribed independently and is one of the cheapest accuracy wins for phone-based ASR.
  </Accordion>

  <Accordion title="Does Vobiz provide speech-to-text?">
    Vobiz is the telephony infrastructure layer. It transports and records call audio and can stream inbound L16 at 8 or 16 kHz, or μ-law at 8 kHz, to your chosen ASR engine. It powers your speech-to-text and voice-AI stack rather than replacing it.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [What is a Voice API?](/docs/blogs/what-is-a-voice-api) · [What is VoIP?](/docs/blogs/what-is-voip) · [SIP vs WebSockets](/docs/concepts/sip-vs-websockets)
* [Audio streaming](/docs/audio-streams) · [WebSocket streaming](/docs/concepts/streaming-websockets) · [Stream element](/docs/xml/stream)
* [Detecting speech inputs with Gather](/docs/xml/gather/detecting-speech-inputs) · [Call recording](/docs/solutions/call-recording) · [Recordings](/docs/platform/voice/recordings)
* [Post-call analytics](/docs/solutions/post-call-analytics) · [Integrations](/docs/integrations)

## Sources

* Wikipedia, ["Speech recognition"](https://en.wikipedia.org/wiki/Speech_recognition).
* Wikipedia, ["Word error rate"](https://en.wikipedia.org/wiki/Word_error_rate).
* Wikipedia, ["Speaker diarisation"](https://en.wikipedia.org/wiki/Speaker_diarisation).
* Wikipedia, ["Connectionist temporal classification"](https://en.wikipedia.org/wiki/Connectionist_temporal_classification).
* Wikipedia, ["Hidden Markov model"](https://en.wikipedia.org/wiki/Hidden_Markov_model).
* Radford et al., OpenAI, ["Robust Speech Recognition via Large-Scale Weak Supervision" (Whisper)](https://cdn.openai.com/papers/whisper.pdf), 2022.
* Wikipedia, ["Voice frequency"](https://en.wikipedia.org/wiki/Voice_frequency) (the 300–3,400 Hz telephone band).
* Wikipedia, ["Nyquist–Shannon sampling theorem"](https://en.wikipedia.org/wiki/Nyquist%E2%80%93Shannon_sampling_theorem).
* Wikipedia, ["G.711"](https://en.wikipedia.org/wiki/G.711) and ["μ-law algorithm"](https://en.wikipedia.org/wiki/%CE%9C-law_algorithm).
* Wikipedia, ["Packet loss concealment"](https://en.wikipedia.org/wiki/Packet_loss_concealment).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and stream direction-labelled call audio to your ASR engine.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.