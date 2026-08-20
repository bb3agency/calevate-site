> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Routing Calls Through Indian Servers

> Configure your voice agent to process calls on Indian servers for data residency compliance and lower latency.

## Overview

If your business requires data residency in India or you want to achieve the lowest possible latency for calls to Indian phone numbers, you can configure your agent to route calls through Bolna's Indian servers.

This guide explains the configuration requirements to ensure your calls are processed entirely on Indian infrastructure.

## Requirements

To route calls through Indian servers, your agent configuration must meet **all** of the following requirements:

### 1. Telephony Provider

Use **Plivo** as your telephony provider.

<Note>
  Twilio is not supported for Indian server routing. If you use Twilio, calls will be processed on US servers.
</Note>

### 2. Transcriber (Speech-to-Text)

Use one of these transcription providers:

* Deepgram
* Azure
* Sarvam
* ElevenLabs
* Smallest

**If using Deepgram**, additional requirements apply:

| Requirement  | Supported Values                                                                    |
| ------------ | ----------------------------------------------------------------------------------- |
| **Model**    | `nova-2`, `nova-3`, and their variants (e.g., `nova-2-phonecall`, `nova-3-general`) |
| **Language** | `hi` (Hindi), `multi-hi` (Multilingual Hindi), `en-IN` (Indian English)             |

### 3. Synthesizer (Text-to-Speech)

Use one of these voice synthesis providers:

* ElevenLabs
* Sarvam
* Azure TTS
* Cartesia

<Note>
  Some ElevenLabs voices may not be available in the India region. If you encounter issues, try selecting a different voice.
</Note>

### 4. LLM (Language Model)

Use one of these LLM providers:

* Azure OpenAI

### 5. Provider API Keys

Use Bolna's default provider integrations. Do not connect your own API keys for the transcriber, synthesizer, or LLM providers.

<Warning>
  If you connect your own API keys for any provider (transcriber, synthesizer, or LLM), calls will automatically route through US servers regardless of other configuration settings.
</Warning>

## Quick Checklist

Before deploying your agent for Indian server routing, verify:

| Component         | Requirement                                      | Status   |
| ----------------- | ------------------------------------------------ | -------- |
| Telephony         | Plivo                                            | Required |
| Transcriber       | Deepgram, Azure, Sarvam, ElevenLabs, or Smallest | Required |
| Deepgram Language | `hi`, `multi-hi`, or `en-IN` (if using Deepgram) | Required |
| Synthesizer       | ElevenLabs, Sarvam, Azure TTS, or Cartesia       | Required |
| LLM               | Azure OpenAI                                     | Required |
| Custom API Keys   | None connected                                   | Required |

## Troubleshooting

If your calls are not routing through Indian servers, check the following:

1. **Telephony Provider**: Ensure you're using Plivo, not Twilio
2. **Deepgram Language**: If using Deepgram, verify the language is set to `hi`, `multi-hi`, or `en-IN`
3. **Custom API Keys**: Check that you haven't connected your own API keys for any provider in the Providers section
4. **Provider Selection**: Verify all providers (transcriber, synthesizer, LLM) are from the supported lists above

## Related Resources

* [Supported Telephony Providers](/docs/supported-telephony-providers)
* [Plivo Setup Guide](/docs/plivo)
* [Understanding Latency Metrics](/docs/concepts/call-latencies)
