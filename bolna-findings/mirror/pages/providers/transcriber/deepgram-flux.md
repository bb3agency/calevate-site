> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Deepgram Flux Transcriber (Speech to Text)

> Use Deepgram's next-generation Flux models with Bolna Voice AI agents for ultra-low-latency streaming transcription and intelligent turn detection.

## What is Deepgram Flux?

Deepgram Flux is Deepgram's latest generation of speech-to-text models, purpose-built for real-time conversational AI. Unlike Nova models that rely on external Voice Activity Detection (VAD) for turn boundaries, Flux models have turn detection built directly into the model — producing a richer event stream that lets Bolna start responding sooner and handle barge-ins more accurately.

## Why choose Deepgram Flux for voice AI transcription?

* **Speculative LLM responses**: Bolna can start generating an LLM response on `EagerEndOfTurn` before the speaker has fully stopped, cutting perceived response time significantly.

* **Accurate barge-in detection**: The `StartOfTurn` event fires as soon as speech begins, allowing Bolna to interrupt playback with zero VAD delay.

* **Language Identification (Flux Multi)**: `flux-general-multi` identifies the spoken language per turn and returns it alongside the transcript, enabling dynamic multilingual handling without pre-configuring a language.

* **Configurable turn sensitivity**: End-of-turn thresholds and timeouts are exposed as tunable parameters, so you can balance responsiveness against accuracy for your specific use case.

## Which Deepgram Flux models are supported on Bolna AI?

| Model                 | Description                                                   |
| --------------------- | ------------------------------------------------------------- |
| `Flux (English)`      | English-only Flux model optimised for accuracy and latency    |
| `Flux (Multilingual)` | Multilingual Flux model with built-in Language Identification |

## Configurable parameters

### EndOfTurn Threshold (`eot_threshold`)

Controls how confident the model must be that the speaker has finished their turn before emitting a final transcript.

| Value | Behaviour                                                   |
| ----- | ----------------------------------------------------------- |
| `0.5` | Responds sooner, higher chance of cutting off the speaker   |
| `0.7` | **Default** — balanced for most voice agent use cases       |
| `0.9` | Waits longer, reduces false endings on incomplete sentences |

**Range:** `0.5` – `0.9` (step `0.05`)

***

### EndOfTurn Timeout (`eot_timeout_ms`)

Maximum silence duration (in milliseconds) the model waits after the last detected speech before forcing an EndOfTurn event. Acts as a safety net when the model's confidence score alone is insufficient.

| Value               | Behaviour                                                 |
| ------------------- | --------------------------------------------------------- |
| `300 ms` – `900 ms` | Aggressive — good for fast back-and-forth interactions    |
| `1 s`               | **Default** — works well for most voice agent use cases   |
| `2 s` – `3 s`       | Patient — useful for agents that ask open-ended questions |

**Options:** `300 ms`, `400 ms`, `500 ms`, `600 ms`, `700 ms`, `800 ms`, `900 ms`, `1 s`, `2 s`, `3 s`

***

### Eager EndOfTurn (`eager_eot_threshold`)

When enabled, Flux emits an `EagerEndOfTurn` event before the final `EndOfTurn`. Bolna uses this to start LLM inference speculatively — if the speaker continues (`TurnResumed`), the speculative request is cancelled; if the speaker stops (`EndOfTurn`), the response is already in flight.

Enable this toggle to activate eager turn detection. When enabled, set the **Eager Threshold**:

| Value | Behaviour                                                                 |
| ----- | ------------------------------------------------------------------------- |
| `0.3` | Triggers very early — maximum latency reduction, higher cancellation rate |
| `0.5` | **Default** — good balance between speed and accuracy                     |
| `0.9` | Triggers late — nearly as conservative as standard EndOfTurn              |

**Range:** `0.3` – `0.9` (step `0.05`)

<Tip>
  Enable Eager EndOfTurn with a threshold of `0.4`–`0.5` for the lowest perceived response latency. If you see frequent mid-sentence interruptions, raise the threshold or disable it.
</Tip>

## Next steps

Ready to configure Deepgram Flux for your voice AI agent? Open the **Audio** tab in the [Bolna Playground](/docs/agent-setup/audio-tab), select `Flux (English)` or `Flux (Multilingual)` as your transcriber model, and tune the parameters above.

For related integrations:

* Compare with [Deepgram Nova](/docs/providers/transcriber/deepgram) for a widely-deployed production alternative
* Learn about [multilingual support](/docs/customizations/multilingual-languages-support) for global agents
* Explore [LLM providers](/docs/providers/llm-model/openai) to process transcribed text
