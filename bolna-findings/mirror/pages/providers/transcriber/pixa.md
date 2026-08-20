> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Pixa Transcriber (Speech to Text)

> Integrate Pixa with Bolna Voice AI agents for accurate Hindi speech transcription. Optimized for Indian language recognition with real-time streaming support.

## What is Pixa STT?

[Pixa](https://heypixa.ai/) (HeyPixa) is a speech-to-text platform specifically optimized for Hindi and Indian language transcription. Pixa provides real-time streaming transcription through a WebSocket API, making it ideal for voice AI agents serving Indian markets where accurate Hindi recognition is essential.

Pixa's models are trained on diverse Hindi datasets, enabling high accuracy for regional accents, conversational speech patterns, and the natural variations found in spoken Hindi across different regions of India.

## Why choose Pixa for voice AI transcription?

Pixa offers several features that make it a strong choice for Hindi speech recognition:

* **Hindi Language Expertise**: Pixa's models are specifically optimized for Hindi transcription, delivering high accuracy for native Hindi speakers and various regional accents.

* **Real-Time Streaming**: WebSocket-based streaming API provides continuous transcription as audio is received, enabling responsive voice agent interactions.

* **Multiple Audio Encodings**: Supports linear16, linear32, mulaw, and alaw audio encodings, ensuring compatibility with various telephony providers and audio sources.

* **Multiple Model Options**: Offers both the native pixa-1 model optimized for Hindi and a whisper-1 model for broader language support.

* **Low Latency Design**: Designed for real-time applications with minimal delay between speech and transcription output.

* **Telephony Integration**: Native support for common telephony audio formats makes integration with Twilio, Exotel, and Plivo straightforward.

## How does Bolna integrate with Pixa?

Bolna AI integrates Pixa's STT technology to enable real-time Hindi speech transcription for its AI-powered voice agents. Here's how Bolna leverages Pixa:

* **Real-Time Hindi Voice Processing**:
  Bolna uses Pixa's streaming WebSocket API to convert Hindi speech into text in real time. This enables AI agents to understand and respond to Hindi-speaking users without noticeable delays.

* **Hindi Market Voice Agents**:
  For businesses serving Indian customers, Pixa's Hindi-optimized transcription ensures accurate understanding of customer queries, names, addresses, and other Hindi content that general-purpose transcribers might struggle with.

* **Telephony Provider Optimization**:
  Bolna automatically configures audio encoding based on the telephony provider. For Twilio, it uses mulaw at 8kHz; for Exotel and Plivo, it uses linear16 at 8kHz; and for web-based calls, it uses linear16 at 16kHz.

* **Intelligent Turn Detection**:
  Since Pixa relies on final transcript markers rather than VAD events, Bolna implements intelligent turn detection based on the is\_final flag, with configurable timeout handling for edge cases.

* **Utterance Timeout Handling**:
  Bolna monitors for stuck utterances and implements force-finalization when transcripts don't receive final confirmation within the configured timeout, ensuring conversations continue smoothly.

* **Connection Management**:
  Bolna handles WebSocket connection lifecycle including authentication, heartbeat messages, and graceful disconnection to ensure reliable transcription throughout calls.

## Which Pixa models are supported on Bolna AI?

| Model     | Description                                               |
| --------- | --------------------------------------------------------- |
| pixa-1    | Native Hindi-optimized speech recognition model (default) |
| whisper-1 | Whisper-based model for broader language support          |

## Next steps

Ready to configure Pixa transcription for your Hindi voice AI agent? Start by [setting up your transcriber in the Playground](/docs/agent-setup/audio-tab) or explore our [API documentation](/docs/api-reference/introduction) for programmatic integration.

For related integrations:

* Compare with [Sarvam transcriber](/docs/providers/transcriber/sarvam) for comprehensive Indian language support
* Explore [Deepgram transcriber](/docs/providers/transcriber/deepgram) for multilingual alternatives
* Learn about [multilingual support](/docs/customizations/multilingual-languages-support) for global agents
* Configure [LLM providers](/docs/providers/llm-model/openai) to process transcribed text

Pixa's Hindi-optimized STT capabilities empower Bolna AI to deliver accurate, real-time speech-to-text transcription for Indian market voice agents, ensuring seamless Hindi conversations with high recognition accuracy.
