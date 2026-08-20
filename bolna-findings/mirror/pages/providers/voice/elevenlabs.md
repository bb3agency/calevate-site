> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# ElevenLabs Voice Synthesis for Bolna Agents

> Configure ElevenLabs text-to-speech in Bolna voice agents, including Turbo v2.5, Flash v2.5 and Eleven v3. Covers models, voices, streaming settings, voice cloning, and latency tuning.

[ElevenLabs](https://elevenlabs.io/) is Bolna's default voice synthesizer. The `eleven_turbo_v2_5` model delivers natural-sounding English speech with the lowest latency of any ElevenLabs model.

***

## Quick config

```json theme={"system"}
"synthesizer": {
  "provider": "elevenlabs",
  "provider_config": {
    "voice": "Nila",
    "voice_id": "V9LCAAi4tTlqe9JadbCo",
    "model": "eleven_turbo_v2_5"
  },
  "stream": true,
  "buffer_size": 250,
  "audio_format": "wav"
}
```

To use your own ElevenLabs account (for voice cloning or custom voices), connect it at [platform.bolna.ai/auth/elevenlabs](https://platform.bolna.ai/auth/elevenlabs).

***

## Supported models

| Model                      | Best for                               |
| -------------------------- | -------------------------------------- |
| `eleven_turbo_v2_5`        | Low-latency English (recommended)      |
| `eleven_flash_v2_5`        | Fastest option; slightly lower quality |
| `eleven_v3_conversational` | Most expressive; 74 languages          |

`eleven_turbo_v2_5` is the standard choice for production agents. Use `eleven_flash_v2_5` when you need the absolute lowest time-to-first-audio.

`eleven_v3_conversational` is ElevenLabs' most expressive model and supports 74 languages. It ignores `speed`, `style` and `similarity_boost`, and accepts only three `temperature` values (see below).

***

## Key settings

| Setting        | Type    | Default | Description                                                                               |
| -------------- | ------- | ------- | ----------------------------------------------------------------------------------------- |
| `voice`        | string  | —       | Display name of the voice                                                                 |
| `voice_id`     | string  | —       | ElevenLabs voice ID (stable; use this, not the name)                                      |
| `model`        | string  | —       | ElevenLabs model (`eleven_turbo_v2_5`, `eleven_flash_v2_5` or `eleven_v3_conversational`) |
| `stream`       | bool    | `true`  | Enable streaming; always `true` for real-time calls                                       |
| `buffer_size`  | integer | `250`   | Characters to buffer before sending first audio chunk                                     |
| `audio_format` | string  | `wav`   | Output format — match your telephony provider                                             |

### Eleven v3 settings

`eleven_v3_conversational` takes a narrower set of voice settings than the Turbo and Flash models:

| Setting            | Behaviour on v3                                                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `temperature`      | Maps to stability, which v3 treats as three presets: `0.0` creative, `0.5` natural, `1.0` robust. Other values are rounded to the nearest preset. |
| `speed`            | Ignored                                                                                                                                           |
| `style`            | Ignored                                                                                                                                           |
| `similarity_boost` | Ignored                                                                                                                                           |

### buffer\_size guidance

`buffer_size` controls the trade-off between first-word latency and audio smoothness:

* **100–150** — fastest first word; can sound choppy if ElevenLabs response is slow
* **250** — balanced default; works well for most agents
* **400+** — smoothest speech; higher latency to first word

***

## Choosing a voice

ElevenLabs voices are identified by a `voice_id`. The `voice` name field is for reference only — Bolna uses `voice_id` to select the voice.

Browse voices in the [ElevenLabs Voice Library](https://elevenlabs.io/voice-library). Copy the voice ID from the URL or the voice details panel.

**Example voices:**

| Voice  | voice\_id              | Accent           |
| ------ | ---------------------- | ---------------- |
| Nila   | `V9LCAAi4tTlqe9JadbCo` | Neutral American |
| Rachel | `21m00Tcm4TlvDq8ikWAM` | Neutral American |
| Adam   | `pNInz6obpgDQGcFmaJgB` | Neutral American |

For a custom or cloned voice, use the voice\_id from your ElevenLabs account. See [Clone Voices](/docs/clone-voices) and [Import Voices](/docs/import-voices).

***

## audio\_format by telephony provider

| Telephony  | audio\_format          |
| ---------- | ---------------------- |
| Plivo      | `wav`                  |
| Exotel     | `wav`                  |
| Twilio     | `mp3` or `wav`         |
| Custom SIP | match codec negotiated |

***

## FAQ

<AccordionGroup>
  <Accordion title="Which model should I use: Turbo, Flash or v3?">
    Use `eleven_turbo_v2_5` for most production agents. It has the better quality/latency balance. Use `eleven_flash_v2_5` only if your primary constraint is time-to-first-audio and you've measured that Turbo is too slow. Use `eleven_v3_conversational` when expressiveness is the priority; it is the most expressive of the three, and Turbo remains the lower-latency option.
  </Accordion>

  <Accordion title="Why doesn't speed change anything on Eleven v3?">
    `eleven_v3_conversational` ignores `speed`, `style` and `similarity_boost`; the model does not act on them. Only `temperature` (stability) has an effect, and it accepts three values: `0.0`, `0.5` and `1.0`. Anything else is rounded to the nearest of those. Use Turbo or Flash if you need speed control.
  </Accordion>

  <Accordion title="How do I find a voice_id?">
    In the ElevenLabs dashboard, open any voice and look at the URL — the ID is the path component after `/voice/`. Alternatively, list voices via the ElevenLabs API. Always store the `voice_id`, not just the name; names can change.
  </Accordion>

  <Accordion title="Can I use a cloned voice?">
    Yes. Clone your voice in ElevenLabs, connect your ElevenLabs account to Bolna, then set `voice_id` to your cloned voice's ID. See [Clone Voices](/docs/clone-voices).
  </Accordion>

  <Accordion title="The audio sounds choppy. What should I do?">
    Increase `buffer_size` to 350–400. Choppy audio usually means the first audio chunk starts before ElevenLabs has generated enough audio to stream smoothly.
  </Accordion>
</AccordionGroup>

***

## Related

* [Audio Tab](/docs/agent-setup/audio-tab) — configure synthesizer in the dashboard
* [Clone Voices](/docs/clone-voices) — create a custom voice
* [Import Voices](/docs/import-voices) — use existing ElevenLabs voices
* [Cartesia](/docs/providers/voice/cartesia) — alternative low-latency synthesizer
* [Latency](/docs/concepts/latency) — how synthesis affects response time
