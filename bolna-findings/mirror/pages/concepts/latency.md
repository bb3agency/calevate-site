> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Latency in Real-Time Voice AI

> How Bolna measures and minimizes end-to-end latency in voice conversations, and what you can tune to improve response times.

Latency in a voice AI system is the time between when a caller finishes speaking and when they hear the agent start responding. Bolna targets **sub-600ms end-to-end** for a natural conversation feel.

***

## Where latency comes from

Every response goes through three processing stages, each adding latency:

```
Caller stops speaking
        ↓
   Endpointing (50–300ms)      ← How long before we decide they're done?
        ↓
   Transcription (50–150ms)    ← Speech-to-text processing time
        ↓
   LLM first token (100–400ms) ← Time to first token from the model
        ↓
   Synthesis first chunk (80–200ms) ← TTS time to first audio
        ↓
Caller hears first word
```

**Time to First Audio (TTFA)** is the total of these stages — the metric Bolna reports in `latency_data.time_to_first_audio` on each execution.

***

## Endpointing

Endpointing is the detection of when the caller has finished speaking. Setting it too low causes the agent to interrupt mid-sentence. Setting it too high adds noticeable dead air.

Bolna uses **voice activity detection (VAD)** with configurable `endpointing` delay (in milliseconds). The default is 250ms.

```json theme={"system"}
"transcriber": {
  "provider": "deepgram",
  "endpointing": 250
}
```

Increase to 400–500ms for callers who pause mid-sentence (non-native speakers, elderly). Decrease toward 100ms for fast-paced sales scripts.

***

## Transcription latency

Streaming transcribers (Deepgram, Azure, ElevenLabs) return partial transcripts in real-time, with the final transcript arriving 50–150ms after endpointing. The LLM inference begins as soon as the final transcript arrives.

Transcriber choice has a modest effect on latency. Deepgram Nova-3 is generally the fastest option.

***

## LLM latency

The LLM accounts for the largest share of latency. The key metric is **time to first token (TTFT)** — how long before the model starts streaming its response.

| Provider                           | Typical TTFT |
| ---------------------------------- | ------------ |
| OpenAI gpt-4.1-mini                | \~150ms      |
| OpenAI gpt-4.1                     | \~200ms      |
| Anthropic claude-sonnet-4-20250514 | \~250ms      |
| Gemini gemini-2.5-flash            | \~150ms      |

Shorter prompts, lower `max_tokens`, and `temperature` close to 0 all reduce TTFT. Avoid sending large knowledge-base results or long tool outputs back to the LLM unnecessarily.

***

## Synthesis latency

Bolna starts streaming synthesizer audio as soon as the LLM emits the first sentence. You don't wait for the full LLM response.

`buffer_size` controls how many characters to accumulate before sending the first audio chunk. Smaller buffers start audio sooner but can produce choppy speech if the synthesizer is slow to respond.

```json theme={"system"}
"synthesizer": {
  "provider": "elevenlabs",
  "stream": true,
  "buffer_size": 100
}
```

A buffer of 100–150 characters is typical. ElevenLabs Turbo and Cartesia are the lowest-latency synthesis options.

***

## Network and telephony

The call's geographic path also adds latency. A caller in India connecting to a US-hosted telephony provider adds \~100–200ms round-trip. Use a telephony provider with regional presence near your callers:

* India: Plivo, Exotel, Vobiz
* US/global: Twilio, Plivo

For the lowest latency within India, enable Indian server configuration — see [Indian Server Configuration](/docs/enterprise/indian-server-configuration).

***

## Reading latency data

Each completed execution includes:

```json theme={"system"}
"latency_data": {
  "time_to_first_audio": 189.69
}
```

`time_to_first_audio` is in milliseconds from the end of the caller's utterance to the start of the agent's audio response.

Monitor this across calls to detect regressions when you change providers, prompts, or model versions.

***

## Summary of tunable parameters

| Parameter                 | Where                       | Effect                                                                  |
| ------------------------- | --------------------------- | ----------------------------------------------------------------------- |
| `endpointing`             | transcriber config          | Reduce for faster response; increase to avoid mid-sentence interruption |
| `buffer_size`             | synthesizer config          | Reduce for faster first audio; increase for smoother speech             |
| `stream: true`            | synthesizer config          | Enable for streaming; never disable in production                       |
| LLM model choice          | `llm_config.model`          | Smaller models (gpt-4.1-mini, gemini-2.5-flash-lite) have lower TTFT    |
| `max_tokens`              | `llm_config`                | Lower cap reduces tail latency on long responses                        |
| Telephony provider region | `tools_config.input/output` | Match provider region to callers                                        |

See [Call Latencies](/docs/concepts/call-latencies) for per-provider benchmarks.
