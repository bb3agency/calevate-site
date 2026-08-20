> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Soniox Transcriber (Speech to Text)

> Integrate Soniox real-time STT with your Bolna Voice AI agents for multilingual transcription with native code-switching and low-latency turn detection.

## What is Soniox STT?

[Soniox](https://soniox.com/) Speech-to-Text is a real-time automatic speech recognition (ASR) platform built around a single multilingual model. Instead of running a separate recognizer per language, one Soniox model transcribes whatever is spoken — including mid-sentence switches between languages (for example Hinglish) — in a single streaming connection.

Bolna uses Soniox's real-time `stt-rt-v5` model, which combines high accuracy across 60+ languages, per-token language identification, and semantic endpoint detection for natural turn-taking.

## Why choose Soniox for voice AI transcription?

* **Native multilingual, one connection**: A single model handles all supported languages and code-switches between them automatically. There is no per-language switching — the agent simply understands the caller, even when they mix languages.

* **Code-switching (Hinglish and more)**: Soniox is built for real-world speech where callers move between English and a regional language within the same sentence, which is common across Indian markets.

* **Semantic endpoint detection**: Soniox detects when a speaker has actually finished their turn (rather than waiting on a fixed silence timer) and signals it immediately, so Bolna can respond sooner without cutting people off.

* **Per-token language identification**: Each transcribed token carries its detected language, giving downstream logic an accurate, real-time view of what the caller is speaking.

## How Bolna uses Soniox for STT

Bolna connects to Soniox over a single streaming WebSocket and biases it using **language hints**:

* **Multilingual (auto-detect)**: Select the multilingual option and Bolna hints the supported set, letting Soniox detect and code-switch on its own — ideal for callers who mix English and a regional language.

* **Single language**: Select a specific language (for example Hindi) and Bolna hints that language so Soniox does its best for it throughout the call, while still handling the occasional English word naturally.

Both telephony (8 kHz) and web calls (16 kHz) are supported, and interim results stream continuously so barge-in stays responsive.

## Which Soniox models are supported on Bolna AI?

| Model                     | Description                                                                                                |
| ------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `Soniox v5` (`stt-rt-v5`) | Real-time multilingual model with code-switching, language identification, and semantic endpoint detection |

## Supported languages

Soniox on Bolna supports multilingual auto-detect plus the following languages:

* **English** — `en`
* **English (India)** — `en-IN`
* **Hindi** — `hi`
* **Bengali** — `bn`
* **Tamil** — `ta`
* **Telugu** — `te`
* **Gujarati** — `gu`
* **Kannada** — `kn`
* **Malayalam** — `ml`
* **Marathi** — `mr`
* **Punjabi** — `pa`

<Tip>
  For callers who naturally mix English with a regional language, select the **multilingual** option rather than a single language — Soniox identifies and code-switches in one stream, so you do not need to pre-configure a language.
</Tip>

## Next steps

Ready to use Soniox for your voice AI agent? Open the **Audio** tab in the [Bolna Playground](/docs/agent-setup/audio-tab), select `Soniox v5` as your transcriber, and choose multilingual or a specific language.

For related integrations:

* You can connect your own Soniox account by adding your `SONIOX` key in [provider settings](/docs/providers)
* Compare with [Sarvam](/docs/providers/transcriber/sarvam) for Indian-language transcription
* Learn about [multilingual support](/docs/customizations/multilingual-languages-support) for global agents
