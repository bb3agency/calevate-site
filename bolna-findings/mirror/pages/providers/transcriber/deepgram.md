> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Deepgram Real-Time Transcription for Bolna Voice Agents

> Configure Deepgram Nova-3 or Nova-2 streaming speech-to-text in your Bolna voice agent. Covers models, endpointing, multilingual config, and troubleshooting.

[Deepgram](https://deepgram.com/) is Bolna's default transcriber for English. Its streaming Nova-3 model delivers sub-150ms transcription latency, making it the fastest option for real-time voice AI.

***

## Quick config

```json theme={"system"}
"transcriber": {
  "provider": "deepgram",
  "model": "nova-3",
  "language": "en",
  "stream": true,
  "encoding": "linear16",
  "sampling_rate": 16000,
  "endpointing": 250
}
```

Set this in your agent's `tools_config.transcriber` block. See [Create Agent API](/docs/api-reference/agent/v2/create) for the full schema.

To use your own Deepgram account, connect it at [platform.bolna.ai/auth/deepgram](https://platform.bolna.ai/auth/deepgram).

***

## Supported models

| Model                     | Languages     | Best for                             |
| ------------------------- | ------------- | ------------------------------------ |
| `nova-3`                  | English       | Lowest latency; recommended default  |
| `nova-3-medical`          | English       | Clinical terminology                 |
| `nova-2`                  | 30+ languages | Multilingual; see supported list     |
| `nova-2-phonecall`        | English       | Phone audio with background noise    |
| `nova-2-conversationalai` | English       | Optimized for AI agent conversations |
| `nova-2-meeting`          | English       | Multiple speakers                    |
| `nova-2-medical`          | English       | Medical terminology                  |
| `nova-2-finance`          | English       | Financial and trading terminology    |
| `nova-2-atc`              | English       | Air traffic control                  |
| `nova-2-drivethru`        | English       | Fast-food/quick-service ordering     |
| `nova-2-automotive`       | English       | In-car applications                  |
| `flux`                    | English       | Flux model (English only)            |
| `flux-multilingual`       | Multiple      | Flux multilingual                    |

**Recommendation:** Use `nova-3` for English agents. Use `nova-2` with `language` set explicitly for non-English.

***

## Key settings

| Setting         | Type    | Default    | Description                                   |
| --------------- | ------- | ---------- | --------------------------------------------- |
| `model`         | string  | `nova-3`   | Model variant                                 |
| `language`      | string  | `en`       | BCP-47 language code — always set explicitly  |
| `stream`        | bool    | `true`     | Enable streaming; never disable in production |
| `encoding`      | string  | `linear16` | Audio encoding format                         |
| `sampling_rate` | integer | `16000`    | Hz — match your telephony provider            |
| `endpointing`   | integer | `250`      | ms of silence before final transcript         |

### Endpointing guidance

* **250ms** — default; works well for fluent English speakers
* **350–500ms** — better for non-native speakers, elderly callers, or callers who pause mid-sentence
* **100–150ms** — fast-paced scripts; reduces dead air but may interrupt on pauses

***

## Multilingual config

Set `language` explicitly. Auto-detect adds 100–200ms latency and occasionally misclassifies.

```json theme={"system"}
"transcriber": {
  "provider": "deepgram",
  "model": "nova-2",
  "language": "hi",
  "stream": true,
  "encoding": "linear16",
  "sampling_rate": 16000
}
```

For Indian languages, [Sarvam](/docs/providers/transcriber/sarvam) may give better accuracy. See [Multilingual Voice Agents](/docs/customizations/multilingual-languages-support).

***

## FAQ

<AccordionGroup>
  <Accordion title="Should I use nova-3 or nova-2?">
    Use `nova-3` for English — it's faster and more accurate. Use `nova-2` when you need a non-English language or a domain-specific variant (`nova-2-phonecall`, `nova-2-medical`, etc.).
  </Accordion>

  <Accordion title="Why is my agent interrupting callers mid-sentence?">
    Your `endpointing` value is too low. Increase it to 350–500ms. If callers have a strong accent or speak with filler words ("um", "uh"), a higher endpointing value gives them more time to complete their thought.
  </Accordion>

  <Accordion title="What encoding and sampling_rate should I use?">
    Match the telephony provider's output: Plivo and Exotel use `linear16` at 16000 Hz. Twilio uses `mulaw` at 8000 Hz. If you use the wrong values, transcription accuracy degrades.
  </Accordion>

  <Accordion title="Does Deepgram work with inbound calls?">
    Yes — the same transcriber config applies to both outbound and inbound calls. There's no separate configuration.
  </Accordion>
</AccordionGroup>

***

## Related

* [Audio Tab](/docs/agent-setup/audio-tab) — configure transcriber in the dashboard
* [Latency](/docs/concepts/latency) — how transcription affects end-to-end response time
* [Deepgram Flux](/docs/providers/transcriber/deepgram-flux) — the Flux model variant
* [Sarvam transcriber](/docs/providers/transcriber/sarvam) — Indian languages
* [Azure transcriber](/docs/providers/transcriber/azure) — enterprise multilingual option
