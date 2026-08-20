> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Maya Voice Synthesis for Bolna Agents

> Configure Maya Research Maya 2 Native text-to-speech in Bolna voice agents. Covers voices, supported languages, mid-call language switching, and telephony audio.

[Maya Research](https://www.mayaresearch.ai/) is a text-to-speech provider built for Indian languages. The `Maya 2 Native` model streams speech over a persistent WebSocket, with two voices — **Ananya** and **Arjun** — each covering all eleven supported languages.

***

## Quick config

```json theme={"system"}
"synthesizer": {
  "provider": "maya",
  "provider_config": {
    "voice": "Ananya",
    "voice_id": "Ananya",
    "model": "Maya 2 Native",
    "language": "en"
  },
  "stream": true,
  "buffer_size": 400
}
```

***

## Supported voices

Maya has two voices. Both speak every supported language — voice and language are chosen independently.

| Voice    | Gender |
| -------- | ------ |
| `Ananya` | Female |
| `Arjun`  | Male   |

Voice matching is case-sensitive on Maya's side — `ananya` is rejected. Bolna normalizes casing for you, so `voice: "ananya"` still resolves to `Ananya`.

***

## Supported languages

| `language` | Language                                |
| ---------- | --------------------------------------- |
| `hi`       | Hindi                                   |
| `bn`       | Bengali                                 |
| `gu`       | Gujarati                                |
| `kn`       | Kannada                                 |
| `ml`       | Malayalam                               |
| `mr`       | Marathi                                 |
| `or`       | Odia                                    |
| `pa`       | Punjabi                                 |
| `ta`       | Tamil                                   |
| `te`       | Telugu                                  |
| `en`       | Indian English                          |
| `auto`     | Maya detects the language per utterance |

Region-qualified ASR codes like `hi-IN` are trimmed down to the primary subtag (`hi`) automatically. This is also how Bolna switches Maya's language mid-call — a fresh config frame goes out over the same WebSocket, so the call never reconnects.

***

## Key settings

| Setting       | Type    | Default         | Description                                                                     |
| ------------- | ------- | --------------- | ------------------------------------------------------------------------------- |
| `voice`       | string  | `Ananya`        | `Ananya` or `Arjun`                                                             |
| `voice_id`    | string  | —               | Accepted alongside `voice` so configs shaped like other providers still resolve |
| `model`       | string  | `Maya 2 Native` | Maya's TTS model                                                                |
| `language`    | string  | `en`            | One of the codes above; `auto` lets Maya detect it per utterance                |
| `stream`      | bool    | `false`         | Enable streaming over the persistent WebSocket                                  |
| `buffer_size` | integer | `400`           | Characters buffered before the first chunk is sent                              |

***

## How streaming works

A call runs on a single persistent WebSocket connection. Sentence segmentation happens on Maya's side, so LLM output is forwarded to Maya as it arrives — Bolna does no client-side chunking of the text.

Maya only closes out a turn on a `flush`, so every text fragment is sent as non-final. If the LLM's final piece of text for a turn is empty, Bolna sends a single whitespace character before the flush — otherwise Maya never emits an end-of-turn event and the turn does not close.

On interruption, Bolna sends a `clear` frame and drops any audio frames that keep arriving until Maya confirms with `cancelled`.

***

## Audio output

Maya streams audio at 24 kHz throughout. Bolna handles the conversion depending on where the audio is going:

* **Telephony** — downsampled to 8 kHz and mu-law encoded
* **Web** — left at Maya's native 24 kHz, no resampling

Handoff and prewarm clips are generated with a one-shot HTTP call rather than the WebSocket. On telephony configs, this HTTP response is converted straight to mu-law in-process, skipping the usual transcode step.

***

## FAQ

<AccordionGroup>
  <Accordion title="Which voice should I use — Ananya or Arjun?">
    Both voices cover all eleven supported languages, so the choice is purely about which voice fits your agent's persona — `Ananya` (female) or `Arjun` (male).
  </Accordion>

  <Accordion title="Can I switch languages mid-call?">
    Yes. Set `language` to the code you need, or use `auto` to let Maya detect it per utterance. Bolna sends language switches as a config update over the existing WebSocket, so the call never reconnects.
  </Accordion>

  <Accordion title="Do I need to pass a region-qualified language code?">
    No. Codes like `hi-IN` are automatically reduced to the primary subtag (`hi`) that Maya expects.
  </Accordion>

  <Accordion title="Is Maya available for both telephony and web agents?">
    Yes. Bolna downsamples and mu-law encodes Maya's audio for telephony, and leaves it at native 24 kHz for web.
  </Accordion>
</AccordionGroup>

***

## Related

* [Audio Tab](/docs/agent-setup/audio-tab) — configure synthesizer in the dashboard
* [Sarvam](/docs/providers/voice/sarvam) — alternative Indian-language synthesizer
* [ElevenLabs](/docs/providers/voice/elevenlabs) — Bolna's default English synthesizer
* [Multilingual support](/docs/customizations/multilingual-languages-support) — configuring language switching
* [Latency](/docs/concepts/latency) — how synthesis affects response time
