> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# ElevenLabs Transcriber (Speech to Text)

> Integrate ElevenLabs Scribe with Bolna Voice AI agents for real-time, low-latency speech transcription. Supports word-level timestamps & VAD-based endpointing.

## What is ElevenLabs Scribe STT?

[ElevenLabs](https://elevenlabs.io/) Scribe is a state-of-the-art real-time speech-to-text (STT) model designed for low-latency transcription in voice AI applications. The Scribe v2 Realtime model delivers accurate transcription across 90 languages with approximately 150ms latency, making it ideal for conversational AI agents, customer support systems, and interactive voice applications.

ElevenLabs Scribe combines advanced deep learning with real-time streaming capabilities, providing precise word-level timestamps, automatic language detection, and intelligent voice activity detection (VAD) for natural conversation flow.

## Why choose ElevenLabs Scribe for voice AI transcription?

ElevenLabs Scribe offers several features that make it a powerful choice for real-time speech recognition:

* **Ultra-Low Latency**: With approximately 150ms latency (excluding network overhead), Scribe v2 Realtime enables natural, responsive conversations without noticeable delays.

* **Extensive Language Support**: Supports 90 languages with high accuracy, making it suitable for global voice AI deployments and multilingual applications.

* **Word-Level Timestamps**: Provides precise timestamps for each transcribed word, enabling accurate synchronization and detailed conversation analysis.

* **Automatic Language Detection**: Detects the spoken language automatically during transcription, supporting code-switching scenarios where speakers switch between languages.

* **VAD-Based Endpointing**: Uses intelligent voice activity detection to determine when a speaker has finished talking, ensuring accurate turn-taking in conversations.

* **High Accuracy**: Achieves industry-leading word error rates, outperforming many competitors on standard benchmarks like FLEURS and Common Voice.

* **Streaming WebSocket API**: Real-time streaming via WebSocket enables continuous transcription as audio is received, perfect for live voice agent interactions.

## How does Bolna integrate with ElevenLabs Scribe?

Bolna AI integrates ElevenLabs Scribe STT technology to enable real-time, high-accuracy speech transcription for its AI-powered voice agents. Here's how Bolna leverages ElevenLabs:

* **Real-Time Voice Processing**:
  Bolna uses ElevenLabs' streaming WebSocket API to convert spoken language into text in real time. The low-latency design ensures that AI agents can understand and respond to user input without perceptible delays, creating natural conversation experiences.

* **Multilingual Voice Agent Support**:
  With support for 90 languages, Bolna voice agents can handle conversations in virtually any language. The automatic language detection feature allows agents to adapt to the speaker's language dynamically.

* **Intelligent Turn Detection**:
  Bolna leverages ElevenLabs' VAD-based commit strategy to accurately detect when users have finished speaking. Configurable silence thresholds (0.3 to 3.0 seconds) allow fine-tuning for different conversation styles and use cases.

* **Telephony Provider Optimization**:
  Bolna automatically configures audio encoding based on the telephony provider. For Twilio, it uses mulaw at 8kHz; for Exotel and Plivo, it uses linear16 at 8kHz; and for web-based calls, it uses linear16 at 16kHz for optimal quality.

* **Word-Level Latency Tracking**:
  Bolna tracks per-word latency using ElevenLabs' timestamp data, providing detailed analytics on transcription performance and helping optimize voice agent responsiveness.

* **Code-Switching Detection**:
  When language detection is enabled, Bolna can identify when speakers switch between languages within a conversation, tracking per-word language breakdown for multilingual scenarios.

## Which ElevenLabs models are supported on Bolna AI?

| Model                | Description                                       |
| -------------------- | ------------------------------------------------- |
| scribe\_v2\_realtime | Real-time speech recognition with \~150ms latency |

## Next steps

Ready to configure ElevenLabs transcription for your voice AI agent? Start by [setting up your transcriber in the Playground](/docs/agent-setup/audio-tab) or explore our [API documentation](/docs/api-reference/introduction) for programmatic integration.

For related integrations:

* Compare with [Deepgram transcriber](/docs/providers/transcriber/deepgram) for alternative transcription
* Explore [ElevenLabs synthesizer](/docs/providers/voice/elevenlabs) for a complete ElevenLabs ecosystem
* Learn about [multilingual support](/docs/customizations/multilingual-languages-support) for global agents
* Configure [LLM providers](/docs/providers/llm-model/openai) to process transcribed text

ElevenLabs Scribe STT capabilities empower Bolna AI to deliver highly accurate, real-time speech-to-text transcription with ultra-low latency, making voice interactions seamless and responsive.
