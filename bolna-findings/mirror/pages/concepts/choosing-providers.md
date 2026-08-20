> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Choosing Providers

> How to pick the right transcriber, LLM, and voice synthesizer for your Bolna agent based on language, latency, and quality requirements.

Every Bolna agent uses three provider categories: a **transcriber** (speech-to-text), an **LLM** (language model), and a **synthesizer** (text-to-speech). This page helps you choose the right combination for your use case.

<Note>
  Provider model lineups change frequently. The specific model names here are current examples — always check the relevant [LLM provider page](/docs/providers) or the provider's own docs for the latest recommended model.
</Note>

***

## Quick Decision Guide

| Primary concern                       | Transcriber     | LLM                            | Synthesizer           |
| ------------------------------------- | --------------- | ------------------------------ | --------------------- |
| English, lowest latency               | Deepgram Nova-3 | `gpt-5.4-mini`                 | ElevenLabs Turbo v2.5 |
| Indian languages (Hindi, Tamil, etc.) | Sarvam          | `gpt-5.4-mini` or Sarvam       | Sarvam                |
| European multilingual                 | Azure Speech    | `gpt-5.4`                      | Azure TTS             |
| Enterprise / data residency           | Azure Speech    | Azure OpenAI                   | Azure TTS             |
| Cost-sensitive high volume            | Deepgram Nova-2 | `deepseek-v4-flash`            | AWS Polly             |
| Complex reasoning or sensitive domain | Deepgram Nova-3 | `gpt-5.4` or `claude-sonnet-5` | ElevenLabs            |

***

## Transcribers (speech-to-text)

Language support is the primary selection factor — most transcribers are optimized for specific language families.

| Provider            | Best for                   | Notes                                                 |
| ------------------- | -------------------------- | ----------------------------------------------------- |
| **Deepgram Nova-3** | English                    | Fastest; best accuracy for English                    |
| **Deepgram Nova-2** | Many languages             | Broader language coverage                             |
| **ElevenLabs**      | English                    | High accuracy; slightly higher latency                |
| **Azure Speech**    | Enterprise, many languages | Strong multilingual; good for EU                      |
| **AssemblyAI**      | English                    | High accuracy; async features                         |
| **Sarvam**          | Indian languages           | Best for Hindi, Tamil, Bengali, Telugu, Marathi, etc. |
| **Gladia**          | European languages         | Good multilingual coverage                            |
| **Soniox**          | English                    | Low latency option                                    |

Key settings: `endpointing` (silence detection), `language` (always set explicitly — auto-detection adds latency), `encoding` / `sampling_rate` (must match your telephony provider).

***

## LLMs (language models)

Quality tier and latency are the primary selection factors. See each provider's page for current model names.

| Tier                      | When to use                                                   | Examples                                                |
| ------------------------- | ------------------------------------------------------------- | ------------------------------------------------------- |
| **Fast / cost-efficient** | Most agents — lead qualification, reminders, scheduling, FAQs | `gpt-5.4-mini`, `gemini-2.5-flash`, `deepseek-v4-flash` |
| **High quality**          | Complex reasoning, financial/medical, sensitive conversations | `gpt-5.4`, `gpt-5.5`, `claude-sonnet-5`                 |
| **Enterprise**            | Data residency requirements                                   | Azure OpenAI                                            |
| **Custom / self-hosted**  | On-premise or proprietary models                              | [Custom LLM](/docs/customizations/using-custom-llm)          |

**LLM provider pages:**

<CardGroup cols={3}>
  <Card title="OpenAI" icon="o" href="/docs/providers/llm-model/openai">
    GPT-5.4-mini, GPT-5.4, GPT-5.5
  </Card>

  <Card title="Anthropic" icon="a" href="/docs/providers/llm-model/anthropic">
    Claude Sonnet 5, Haiku 4.5, Opus 4.8
  </Card>

  <Card title="Google Gemini" icon="g" href="/docs/providers/llm-model/gemini">
    Gemini 2.5 Flash, Gemini 3.x
  </Card>

  <Card title="Azure OpenAI" icon="microsoft" href="/docs/providers/llm-model/azure-openai">
    GPT-5.x via Azure infrastructure
  </Card>

  <Card title="DeepSeek" icon="d" href="/docs/providers/llm-model/deepseek">
    DeepSeek V4 Flash, V4 Pro
  </Card>

  <Card title="OpenRouter" icon="r" href="/docs/providers/llm-model/openrouter">
    Unified gateway — all providers
  </Card>
</CardGroup>

***

## Synthesizers (text-to-speech)

Latency and language are the primary selection factors. Always enable `stream: true`.

| Provider          | Best for                       | Notes                                                                    |
| ----------------- | ------------------------------ | ------------------------------------------------------------------------ |
| **ElevenLabs**    | Natural English voices         | Bolna default; Turbo models are fastest                                  |
| **Cartesia**      | Lowest latency English         | Very fast time-to-first-audio                                            |
| **Azure TTS**     | Multilingual, enterprise       | Strong across many languages                                             |
| **AWS Polly**     | Cost-sensitive workloads       | Lower cost; neural voices available                                      |
| **Deepgram Aura** | English                        | Fast and accurate                                                        |
| **Rime**          | Natural conversational English | Good prosody for dialogue                                                |
| **Sarvam**        | Indian languages               | Native voices for Hindi, Tamil, Telugu, and more                         |
| **Smallest AI**   | Ultra-low latency              | Optimized for real-time                                                  |
| **Maya**          | Indian languages               | 11 languages, 2 voices, mid-call language switching without reconnecting |

Key settings: `stream: true` (always enable), `buffer_size` (100–250 chars typical), `audio_format` (must match your telephony provider).

***

## Telephony providers

| Provider              | Best for                          | Notes                                         |
| --------------------- | --------------------------------- | --------------------------------------------- |
| **Plivo**             | India + global                    | Default for most Bolna deployments            |
| **Exotel**            | India                             | Strong local support; DLT compliance built in |
| **Twilio**            | US / global                       | Widest geographic reach                       |
| **Vobiz**             | India                             | Competitive rates                             |
| **Custom SIP (BYOT)** | On-premise / bring your own trunk | See [SIP Trunking](/docs/sip-trunking/byot-setup)  |

***

## Related

* [Providers overview](/docs/providers)
* [Supported Telephony Providers](/docs/supported-telephony-providers)
* [Latency tuning](/docs/concepts/latency)
* [Custom LLM setup](/docs/customizations/using-custom-llm)
* [Multilingual Voice Agents](/docs/customizations/multilingual-languages-support)
