> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Voice APIs Overview

> APIs for discovering TTS providers, models, and voices for use in Bolna agents.

The Voice APIs follow a two-step lookup flow:

1. **Get providers + models** — discover which TTS providers and models are available for a given language
2. **Get voices** — fetch the paginated voice list for a specific provider + model

## Endpoints

```
GET /api/v1/voice-config/tts
GET /api/v1/voice-config/tts/voices
```

## Flow

```
GET /api/v1/voice-config/tts?language=hi
  → returns providers[] each with models[]

Pick a provider.id and a model.id

GET /api/v1/voice-config/tts/voices?language=hi&provider_id=<id>&model_id=<id>&page=1&page_size=100
  → returns items[] of voices
```

Once you have the `voice_id` from a voice item, use it in your agent's `synthesizer_config`:

```json theme={"system"}
"synthesizer_config": {
  "provider": "elevenlabs",
  "voice_id": "iWNf11sz1GrUE4ppxTOL",
  "model": "eleven_turbo_v2_5"
}
```
