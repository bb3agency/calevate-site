> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Azure Transcriber (Speech to Text)

> Integrate Azure Speech-to-Text with Bolna Voice AI for real-time, multilingual, high-accuracy transcriptions and enterprise-grade scalability.

## What is Azure Speech-to-Text?

Azure Speech-to-Text, part of Microsoft Azure Cognitive Services, offers cloud-based automatic speech recognition (ASR). It converts spoken language into text using advanced deep learning models—enabling real-time transcription, batch processing, and support for custom model training. It’s designed to handle enterprise-grade workloads with high accuracy and multi-language capabilities.

## Why choose Azure for speech transcription?

Azure offers a variety of features that make it a leading STT solution:

* **Real-Time Streaming & Batch Transcription**: Supports both low-latency streaming for live interactions and batch processing for recorded files.

* **Speaker Diarization & Language Identification**: Detects speaker turns and identifies languages in multi-party, multilingual scenarios.

* **Noise Reduction**: Advanced noise suppression techniques improve transcription accuracy in challenging audio conditions.

* **Secure & Scalable**: Fully managed service with options for resource control, webhook callbacks, and deployment across regions.

## How does Bolna integrate with Azure Speech-to-Text?

Bolna AI integrates Azure’s STT technology to enable real-time, high-accuracy speech transcription for its AI-powered voice agents. Here’s how Bolna leverages Azure:

* **Live Conversation Transcription**:
  Bolna uses Azure's real-time streaming to convert user speech into text with minimal delay, enabling dynamic agent interaction.

* **Multi-Language, Multi-Speaker Context**:
  With speaker diarization and language detection, Bolna agents accurately follow multilingual or multi-party calls.

* **Speaker Identification and Context Retention**:
  Bolna uses Azure’s speaker diarization capabilities to differentiate between the agent and the caller in conversations. This feature helps in maintaining context and structuring responses effectively.

* **Recording & Post-Call Analysis**:
  Bolna supports batch transcription of stored calls via REST, using callbacks/webhooks to asynchronously retrieve results for insights, compliance, and analytics.

## Next steps

Ready to configure Azure Speech-to-Text for your voice AI agent? Start by [setting up your transcriber in the Playground](/docs/agent-setup/audio-tab) or explore our [API documentation](/docs/api-reference/introduction) for programmatic integration.

For related integrations:

* Compare with [Deepgram transcriber](/docs/providers/transcriber/deepgram) for alternative transcription
* Explore [Azure OpenAI](/docs/providers/llm-model/azure-openai) for a complete Azure ecosystem
* Learn about [data residency options](/docs/enterprise/data-residency) for compliance
* Configure [multilingual support](/docs/customizations/multilingual-languages-support) for global agents
* You can also connect your own Azure account and use it with [Bolna AI](https://platform.bolna.ai/auth/azure)

Integrating Azure Speech-to-Text with Bolna empowers voice AI agents to deliver seamless, real-time, and highly accurate transcriptions across diverse languages and speaker scenarios.e.
