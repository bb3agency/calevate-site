> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# OpenAI Realtime Transcriber (Speech to Text)

> Integrate OpenAI's Realtime transcription API with Bolna Voice AI agents for low-latency, streaming speech recognition using GPT Realtime Whisper.

## What is OpenAI Realtime STT?

[OpenAI's Realtime API](https://platform.openai.com/docs/guides/realtime-transcription) provides a WebSocket-based streaming speech-to-text service. Unlike batch transcription, audio is streamed continuously and transcripts are returned with low latency as the caller speaks, making it well-suited for live voice agent conversations.

## Why choose OpenAI Realtime for voice AI transcription?

* **Ultra-low latency**: Streams audio and returns interim transcript deltas as the caller speaks, with final results delivered on turn boundaries.

* **Built-in server VAD**: `GPT Realtime Whisper` has voice activity detection built in — it automatically detects speech start and end without any manual configuration.

* **Streaming interim transcripts**: Partial transcripts arrive as the caller is still speaking, giving your agent an early signal to start processing.

* **Optional noise reduction**: Near-field noise reduction can be enabled to improve accuracy in office or call-centre environments.

* **Delay tuning**: The `delay` parameter lets you trade off transcription latency against accuracy — useful for noisy environments or accented speech.

## Which OpenAI models are supported?

| Model                  | Description                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------- |
| `GPT Realtime Whisper` | GA streaming transcription model. Natively designed for real-time sessions with built-in VAD. |

## Configurable parameters

These parameters appear in the **Audio** tab of the Bolna Playground when OpenAI is selected as the transcriber provider.

### Transcription Delay (`delay`)

Controls the trade-off between transcription speed and accuracy. A lower delay emits results sooner; a higher delay gives the model more audio context before committing to a transcript.

| Value     | Behaviour                                                |
| --------- | -------------------------------------------------------- |
| `minimal` | Fastest — best for simple, clean audio                   |
| `low`     | Low latency with good accuracy                           |
| `medium`  | **Default** — balanced for most use cases                |
| `high`    | Higher accuracy — useful for accents or background noise |
| `xhigh`   | Maximum accuracy — highest latency                       |

### Noise Reduction

Toggle on to enable near-field noise reduction. Recommended for call-centre or office environments where background noise is common.

## Supported languages

`GPT Realtime Whisper` supports a wide range of languages. Pass the ISO 639-1 code as the `language` parameter when configuring the transcriber.

Common supported languages include: `en`, `es`, `fr`, `de`, `hi`, `pt`, `ja`, `it`, `nl`, `zh`, `ko`, `ar`, `ru`.

## Next steps

Ready to configure OpenAI transcription for your voice AI agent? Open the **Audio** tab in the [Bolna Playground](/docs/agent-setup/audio-tab), select `openai` as the transcriber provider and `GPT Realtime Whisper` as the model, then tune the parameters above.

For related integrations:

* Compare with [Deepgram Flux](/docs/providers/transcriber/deepgram-flux) for an alternative with configurable turn detection
* Compare with [Deepgram Nova](/docs/providers/transcriber/deepgram) for a widely-deployed production alternative
* Learn about [multilingual support](/docs/customizations/multilingual-languages-support) for global agents
