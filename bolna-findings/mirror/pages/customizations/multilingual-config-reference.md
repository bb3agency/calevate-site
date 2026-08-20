> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Multilingual Config Reference

> The multilingual_config object reference for building Bolna multilingual voice agents over the API. Per-language transcriber, synthesizer, prompts, handoff messages, and language switching.

When you build an agent through the [dashboard](/docs/customizations/multilingual-languages-support), Bolna generates the multilingual configuration for you. If you create or update agents over the API instead, you provide that configuration directly through the `multilingual_config` object.

This page documents the object: where it lives, every field, its validation rules, and how Bolna expands it for the call.

***

## Where it lives

`multilingual_config` sits inside `tools_config` on the first task of the agent payload you send to `POST /v2/agent`:

```json theme={"system"}
{
  "agent_config": {
    "tasks": [
      {
        "tools_config": {
          "transcriber": { "provider": "deepgram", "model": "nova-3", "language": "en" },
          "synthesizer": { "provider": "elevenlabs", "provider_config": { "voice_id": "..." } },
          "multilingual_config": {
            "enabled": true,
            "active_language": "en",
            "languages": { }
          }
        }
      }
    ]
  }
}
```

The top-level `transcriber` and `synthesizer` act as the **base**. Each language in `multilingual_config.languages` starts from that base and applies its own overrides on top. The agent opens the call in `active_language`.

***

## Top-level fields

| Field                     | Type    | Required | Default | Description                                                                                                                          |
| ------------------------- | ------- | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `enabled`                 | boolean | yes      | `false` | Must be `true` for multilingual to take effect. When `false` (or omitted), the object is dropped and the agent runs single-language. |
| `active_language`         | string  | no       | `"en"`  | Language code the agent starts the call in. Must be a key in `languages`.                                                            |
| `languages`               | object  | yes      | —       | Map of language code to a per-language config. Minimum **2** languages.                                                              |
| `switch_tool_description` | string  | no       | —       | Overrides the description of the `switch_language` tool the LLM uses to change languages mid-call.                                   |

<Warning>
  Two validation rules are enforced on agent create and update:

  1. `languages` must contain at least **2** entries.
  2. `active_language` must be one of the keys in `languages`.

  Failing either returns `Invalid multilingual config` and the agent is not saved.
</Warning>

***

## Per-language entry

Each value in `languages` is keyed by an [ISO 639-1 code](#supported-languages) and has this shape:

```json theme={"system"}
{
  "hi": {
    "transcriber": {
      "language": "hi"
    },
    "synthesizer": {
      "provider": "sarvam",
      "provider_config": {
        "voice_id": "anushka",
        "model": "bulbul:v2"
      }
    },
    "system_prompt": "आप एक सहायक एजेंट हैं। हिंदी में संक्षेप में उत्तर दें।",
    "handoff_message": "ठीक है, मैं हिंदी में बात करता हूँ।",
    "agent_name": "राज"
  }
}
```

| Field             | Type   | Required | Description                                                                                                                                                                                                             |
| ----------------- | ------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `transcriber`     | object | no       | Speech-to-text override for this language. If omitted, the base transcriber is used with the language code applied. Must include `language`; extra provider fields are allowed (for example `model`, `language_hints`). |
| `synthesizer`     | object | yes      | Text-to-speech config for this language. Requires `provider` and `provider_config`. Optional `buffer_size`. Extra fields are allowed.                                                                                   |
| `system_prompt`   | string | no       | Prompt activated while the agent speaks this language. Write it in the language's native script.                                                                                                                        |
| `handoff_message` | string | no       | Message played when the agent switches to this language.                                                                                                                                                                |
| `agent_name`      | string | no       | Agent name used while speaking this language.                                                                                                                                                                           |

### How overrides layer onto the base

* **Transcriber**: the per-language `transcriber` is merged onto the base transcriber, then the `language` field is resolved to the provider's expected format (for example Sarvam `hi` becomes `hi-IN`). If you omit `transcriber`, the base transcriber is reused with the language code set to the entry's key.
* **Synthesizer**: if the per-language `provider` matches the base, only the differing keys (including a shallow merge of `provider_config`) are applied. If the `provider` differs, the per-language synthesizer replaces the base entirely. For `sarvam`, `smallest`, `cartesia`, `openai`, `pixa`, and `polly`, the language is resolved into `provider_config.language` automatically.

This lets each language use a different STT and TTS provider. A common setup uses Deepgram for English transcription and Sarvam for Hindi, with ElevenLabs voice for English and Sarvam voice for Hindi.

***

## Language switching

Once `multilingual_config` is enabled, Bolna injects a `switch_language` tool so the LLM can change language mid-call, and runs language detection in parallel so the agent can follow the caller automatically.

* **Prompt-driven**: describe when to switch in your prompt (for example "switch to Hindi if the user speaks Hindi"). The LLM calls `switch_language` and the transcriber, synthesizer, and active system prompt all switch together.
* **Auto-detection**: after a few conversation turns Bolna identifies the dominant language and switches system messages to match. See [Auto-Switch Languages](/docs/customizations/auto-switch-multilingual-messages).
* **`switch_tool_description`**: customize how the switch tool is described to the LLM when you need tighter control over switching behavior.

***

## Full example

A two-language agent (English primary, Hindi secondary) with a different STT and TTS provider per language:

```json theme={"system"}
{
  "agent_config": {
    "tasks": [
      {
        "tools_config": {
          "transcriber": {
            "provider": "deepgram",
            "model": "nova-3",
            "language": "en"
          },
          "synthesizer": {
            "provider": "elevenlabs",
            "provider_config": {
              "voice_id": "21m00Tcm4TlvDq8ikWAM",
              "model": "eleven_turbo_v2_5"
            }
          },
          "multilingual_config": {
            "enabled": true,
            "active_language": "en",
            "switch_tool_description": "Switch the conversation language when the caller changes language.",
            "languages": {
              "en": {
                "synthesizer": {
                  "provider": "elevenlabs",
                  "provider_config": {
                    "voice_id": "21m00Tcm4TlvDq8ikWAM",
                    "model": "eleven_turbo_v2_5"
                  }
                },
                "system_prompt": "You are a helpful assistant. Keep replies short.",
                "agent_name": "Alex"
              },
              "hi": {
                "transcriber": {
                  "language": "hi"
                },
                "synthesizer": {
                  "provider": "sarvam",
                  "provider_config": {
                    "voice_id": "anushka",
                    "model": "bulbul:v2"
                  }
                },
                "system_prompt": "आप एक सहायक एजेंट हैं। हिंदी में संक्षेप में उत्तर दें।",
                "handoff_message": "ठीक है, मैं हिंदी में बात करता हूँ।",
                "agent_name": "राज"
              }
            }
          }
        }
      }
    ]
  }
}
```

***

## Supported languages

| Language   | Code | Language | Code | Language | Code |
| ---------- | ---- | -------- | ---- | -------- | ---- |
| English    | `en` | Hindi    | `hi` | Bengali  | `bn` |
| Assamese   | `as` | French   | `fr` | Gujarati | `gu` |
| Indonesian | `id` | Kannada  | `kn` | Malay    | `ms` |
| Malayalam  | `ml` | Marathi  | `mr` | Odia     | `od` |
| Punjabi    | `pa` | Spanish  | `es` | Tamil    | `ta` |
| Telugu     | `te` | Urdu     | `ur` | Dutch    | `nl` |

Provider support varies by language. Pick an STT and TTS provider per language that covers it. For Indian languages, Sarvam covers the widest set.

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Multilingual Support" icon="earth-americas" href="/docs/customizations/multilingual-languages-support">
    Set up the same agent from the dashboard
  </Card>

  <Card title="Auto-Switch Languages" icon="shuffle" href="/docs/customizations/auto-switch-multilingual-messages">
    Auto-detect and switch system messages by language
  </Card>

  <Card title="Non-English Prompts" icon="language" href="/docs/guides/writing-prompts-in-non-english-languages">
    Write per-language prompts in native scripts
  </Card>

  <Card title="Create Agent API" icon="code" href="/docs/api-reference">
    Full agent creation API reference
  </Card>
</CardGroup>
