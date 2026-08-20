> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Gladia Transcriber (Speech to Text)

> Integrate Gladia with Bolna Voice AI agents for real-time multilingual transcription. Supports code-switching, custom vocabulary, and sub-300ms latency.

## What is Gladia STT?

[Gladia](https://www.gladia.io/) is a state-of-the-art audio transcription and intelligence platform that provides real-time speech-to-text capabilities with industry-leading accuracy. Powered by their Solaria ASR model, Gladia delivers transcription with less than 300 milliseconds latency, making it ideal for voice AI agents, contact centers, and real-time communication applications.

Gladia combines advanced speech recognition with audio intelligence features like sentiment analysis, named entity recognition, and automatic language detection, providing a comprehensive solution for voice-driven applications.

## Why choose Gladia for voice AI transcription?

Gladia offers several features that make it a powerful choice for real-time speech recognition:

* **Ultra-Low Latency**: With sub-300ms latency, Gladia enables natural, responsive conversations without noticeable delays, essential for voice AI agents and real-time applications.

* **Extensive Language Support**: Supports over 100 languages interchangeably, making it suitable for global deployments and multilingual customer interactions.

* **Code-Switching Support**: Handles seamless language switching within conversations, accurately transcribing when speakers alternate between languages like English and Hindi (Hinglish) or other language combinations.

* **Custom Vocabulary**: Allows boosting recognition of specific words, phrases, brand names, or industry-specific terminology to improve accuracy for specialized use cases.

* **Native Mulaw Support**: Directly supports mulaw audio encoding used by Twilio, eliminating the need for audio conversion and reducing latency in telephony applications.

* **Audio Enhancement**: Built-in audio preprocessing improves transcription accuracy in challenging conditions with background noise or poor audio quality.

* **Configurable Endpointing**: Adjustable silence detection thresholds allow fine-tuning for different conversation styles and turn-taking patterns.

* **Sentiment Analysis**: Real-time sentiment detection helps understand caller emotions and enables dynamic agent responses.

## How does Bolna integrate with Gladia?

Bolna AI integrates Gladia's STT technology to enable real-time, high-accuracy speech transcription for its AI-powered voice agents. Here's how Bolna leverages Gladia:

* **Real-Time Voice Processing**:
  Bolna uses Gladia's streaming WebSocket API to convert spoken language into text in real time. The two-step connection process (session creation followed by WebSocket connection) ensures reliable, authenticated streaming with optimal performance.

* **Multilingual Voice Agent Support**:
  With support for over 100 languages, Bolna voice agents can handle conversations in virtually any language. When code-switching is enabled, agents can accurately transcribe conversations where speakers switch between languages.

* **Telephony Provider Optimization**:
  Bolna automatically configures audio encoding based on the telephony provider. For Twilio, it uses native mulaw at 8kHz (wav/ulaw); for Exotel and Plivo, it uses linear16 at 8kHz; and for web-based calls, it uses linear16 at 16kHz for optimal quality.

* **Audio Enhancement for Telephony**:
  Bolna enables Gladia's audio enhancer for telephony providers (Twilio, Exotel, Plivo) to improve transcription accuracy in real-world call conditions with background noise and varying audio quality.

* **Custom Vocabulary Integration**:
  Bolna supports passing custom vocabulary keywords to Gladia, allowing voice agents to accurately recognize company names, product names, and industry-specific terminology.

* **Intelligent Turn Detection**:
  Bolna leverages Gladia's configurable endpointing to accurately detect when users have finished speaking. The endpointing threshold can be adjusted to balance responsiveness with accuracy for different conversation styles.

* **Code-Switching for Multilingual Markets**:
  For markets like India where code-switching is common, Bolna configures Gladia to recognize both the primary language and English, enabling accurate transcription of mixed-language conversations.

## Which Gladia models are supported on Bolna AI?

| Model   | Description                                          |
| ------- | ---------------------------------------------------- |
| Solaria | Universal real-time STT model with sub-300ms latency |

Gladia's Solaria model is the default and recommended model for real-time voice agent applications.

## Next steps

Ready to configure Gladia transcription for your voice AI agent? Start by [setting up your transcriber in the Playground](/docs/agent-setup/audio-tab) or explore our [API documentation](/docs/api-reference/introduction) for programmatic integration.

For related integrations:

* Compare with [Deepgram transcriber](/docs/providers/transcriber/deepgram) for alternative transcription
* Explore [Azure transcriber](/docs/providers/transcriber/azure) for enterprise deployments
* Learn about [multilingual support](/docs/customizations/multilingual-languages-support) for global agents
* Configure [LLM providers](/docs/providers/llm-model/openai) to process transcribed text

Gladia's STT capabilities empower Bolna AI to deliver highly accurate, real-time speech-to-text transcription with ultra-low latency and comprehensive multilingual support, making voice interactions seamless across global markets.
