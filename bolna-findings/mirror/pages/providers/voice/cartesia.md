> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Cartesia Text to Speech with Bolna Voice AI agents

> Enable Cartesia voices in Bolna Voice AI agents for expressive, customizable AI voices using their latest voice models for multilingual Indian voices.

## What is Cartesia text-to-speech API?

[Cartesia](https://cartesia.ai/) is a state-of-the-art text-to-speech (TTS) API that generates high-fidelity, natural-sounding speech for AI voice applications. Cartesia uses advanced neural network models to replicate human speech patterns, delivering expressive and realistic audio output that enhances user engagement in conversational AI systems.

Cartesia TTS API is optimized for real-time voice synthesis with ultra-low latency, making it ideal for AI voice assistants, virtual customer support agents, conversational AI chatbots, and automated business communication systems. The platform offers multilingual voice support, customizable voice characteristics, and high-quality prosody that adapts to different use cases including customer service automation, sales outreach, appointment scheduling, and interactive voice response (IVR) systems.

## Why use Cartesia TTS for AI voice agents?

Cartesia text-to-speech API offers powerful capabilities that make it an excellent choice for building conversational AI applications and voice automation systems:

**Ultra-low latency voice synthesis**: Cartesia delivers real-time speech generation with minimal delay, ensuring natural conversation flow in AI voice assistants and customer support bots. This low-latency performance is critical for interactive applications where response time directly impacts user experience.

**Natural-sounding neural voices**: Powered by advanced deep learning models, Cartesia produces human-like speech with natural prosody, intonation, and emotional expression. The neural TTS technology creates voices that sound authentic and engaging, improving user trust and satisfaction in AI interactions.

**Multilingual and accent support**: Cartesia supports multiple languages and regional accents, enabling businesses to deploy AI voice agents for global audiences. This multilingual capability is essential for international customer support, sales automation, and localized voice experiences.

**Customizable voice characteristics**: Businesses can fine-tune voice parameters to match their brand identity and use case requirements. Adjust speaking rate, pitch, and emotional tone to create distinct voice personas for different AI agent roles.

**Scalable API infrastructure**: Cartesia's cloud-based TTS API scales automatically to handle high-volume voice synthesis requests, making it suitable for enterprise-grade conversational AI deployments and large-scale voice automation campaigns.

**Sonic model family**: Cartesia's Sonic models, including Sonic 3.5 and the Sonic 3.6 beta, deliver state-of-the-art voice quality with improved naturalness and expressiveness for demanding voice AI applications.

## How to integrate Cartesia TTS with Bolna voice AI agents

Bolna provides seamless integration with Cartesia's text-to-speech API, enabling you to build sophisticated AI voice agents with natural-sounding speech synthesis. The integration supports real-time voice generation for various conversational AI use cases.

### Use cases for Cartesia voice synthesis in Bolna

**AI customer support automation**: Deploy Cartesia-powered voice agents that handle customer inquiries with empathetic, professional speech. The natural voice quality helps build trust and improves customer satisfaction in automated support interactions.

**Sales and lead qualification bots**: Create AI sales agents with persuasive, engaging voices that can conduct outbound calls, qualify leads, and schedule appointments. Cartesia's expressive speech synthesis makes automated sales conversations feel more human and authentic.

**Appointment scheduling and reminders**: Build voice AI systems that handle appointment booking, confirmations, and reminders with clear, friendly speech. The low-latency synthesis ensures smooth, real-time conversations.

**Healthcare voice assistants**: Develop HIPAA-compliant voice agents for patient intake, appointment scheduling, and health information delivery. Cartesia's natural voices create comfortable, trustworthy interactions in healthcare settings.

**E-commerce and order management**: Implement AI voice agents that assist with product inquiries, order tracking, and customer service. The multilingual support enables global e-commerce voice automation.

**Survey and feedback collection**: Automate survey calls and feedback collection with conversational AI agents that use natural speech to improve response rates and data quality.

### Cartesia voice configuration in Bolna

Bolna supports flexible configuration of Cartesia TTS parameters including voice selection, speaking rate, and language settings. You can configure Cartesia voices through the Bolna Playground interface or programmatically via the API for custom voice AI agent deployments.

## Supported Cartesia TTS models

Bolna supports the following Cartesia text-to-speech models for AI voice synthesis:

| Model           | Description                                                                  |
| --------------- | ---------------------------------------------------------------------------- |
| `sonic-3`       | Stable Sonic 3 release. 42 languages                                         |
| `sonic-3.5`     | Stable Sonic 3.5 release, recommended for production agents. 42 languages    |
| `sonic-preview` | Sonic 3.6 beta, shown as **Sonic 3.6 (Beta)** in the dashboard. 42 languages |

All three models work with every Cartesia voice available in Bolna.

<Note>
  Sonic 3.6 is in beta. Its output may change as Cartesia iterates on the model, so use `sonic-3.5` for production agents that need stable output.
</Note>

## Getting started with Cartesia TTS integration

Ready to build AI voice agents with Cartesia text-to-speech? You can configure Cartesia voices through the [Bolna Playground](/docs/agent-setup/engine-tab) for quick testing or use the [Bolna API](/docs/api-reference/introduction) for programmatic integration in production applications.

To connect your own Cartesia API account, visit the [Cartesia integration page](https://platform.bolna.ai/auth/cartesia) in your Bolna dashboard.

### Compare voice synthesis providers

Explore alternative TTS providers to find the best fit for your AI voice agent requirements:

* [ElevenLabs TTS](/docs/providers/voice/elevenlabs) - Premium voice cloning and expressive synthesis
* [Deepgram TTS](/docs/providers/voice/deepgram) - Ultra-low latency voice generation
* [AWS Polly](/docs/providers/voice/aws-polly) - Cost-effective cloud-based speech synthesis
* [Azure TTS](/docs/providers/voice/azure) - Enterprise-grade multilingual voices

### Related documentation

* [Configure multilingual support](/docs/customizations/multilingual-languages-support) for global voice AI deployments
* [Voice AI agent configuration](/docs/agent-setup/engine-tab) in the Bolna Playground
* [API reference](/docs/api-reference/introduction) for programmatic voice agent creation

Cartesia TTS integration enables Bolna to deliver natural, expressive, and low-latency voice synthesis for conversational AI applications across customer support, sales automation, healthcare, and more.
