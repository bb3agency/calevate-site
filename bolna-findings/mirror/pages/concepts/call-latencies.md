> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Understanding Call Latency Metrics in Bolna Voice AI

> Analyze call latency across transcription, LLM, and synthesis in Bolna Voice AI. Identify bottlenecks and optimize response times.

## Introduction

Bolna provides detailed latency metrics for every Voice AI execution, helping you monitor and optimize agent response speed. These metrics break down timing across the entire voice pipeline, from speech recognition to LLM processing to audio synthesis.

Access latency data via the [Get Execution API](/docs/api-reference/executions/get_execution) in the `latency_data` object.

***

## Latency Data Overview

### Top-Level Metrics

```json theme={"system"}
{
  "latency_data": {
    "stream_id": 129.56,
    "time_to_first_audio": 130.84,
    "region": "in",
    "transcriber": { ... },
    "llm": { ... },
    "synthesizer": { ... }
  }
}
```

| Field                 | Type     | Description                                                                 |
| --------------------- | -------- | --------------------------------------------------------------------------- |
| `stream_id`           | `float`  | Time (ms) to establish the audio stream connection                          |
| `time_to_first_audio` | `float`  | Time (ms) from end of caller's utterance to start of agent's audio response |
| `region`              | `string` | Geographic region code (e.g., `in` for India, `us` for United States)       |

<Tip>
  `time_to_first_audio` is the most important metric for perceived responsiveness. It represents how long the caller waits before hearing the agent speak.
</Tip>

***

## Pipeline Component Metrics

<Tabs>
  <Tab title="Transcriber">
    Converts spoken audio into text. Tracks how quickly speech is being transcribed.

    ```json theme={"system"}
    {
      "transcriber": {
        "time_to_connect": 226,
        "turns": [
          {
            "turn": 1,
            "turn_latency": [
              {
                "sequence_id": 1,
                "audio_to_text_latency": 20.12,
                "text": "hello who is there"
              },
              {
                "sequence_id": 2,
                "audio_to_text_latency": 19.96,
                "text": "hello who is this"
              }
            ]
          }
        ]
      }
    }
    ```

    | Field                   | Type      | Description                                            |
    | ----------------------- | --------- | ------------------------------------------------------ |
    | `time_to_connect`       | `integer` | Time (ms) to establish connection with the transcriber |
    | `turn`                  | `integer` | Sequential conversation turn number (starting at 1)    |
    | `sequence_id`           | `integer` | Incremental transcription update ID within a turn      |
    | `audio_to_text_latency` | `float`   | Time (ms) from audio input to transcribed text         |
    | `text`                  | `string`  | Transcribed text for this sequence                     |

    <Info>
      Multiple sequences per turn represent **incremental refinements**. The transcriber provides partial results that improve over time. The final sequence is the most accurate.
    </Info>
  </Tab>

  <Tab title="LLM">
    Generates the agent's response based on transcribed input.

    ```json theme={"system"}
    {
      "llm": {
        "time_to_connect": null,
        "turns": [
          {
            "time_to_first_token": 1633.04,
            "time_to_last_token": 1691.53,
            "turn": 1
          },
          {
            "time_to_first_token": 737.80,
            "time_to_last_token": 777.49,
            "turn": 2
          }
        ]
      }
    }
    ```

    | Field                 | Type              | Description                                                            |
    | --------------------- | ----------------- | ---------------------------------------------------------------------- |
    | `time_to_connect`     | `integer \| null` | Time (ms) to connect to the LLM provider (`null` if not applicable)    |
    | `turn`                | `integer`         | Sequential turn number                                                 |
    | `time_to_first_token` | `float`           | Time (ms) to receive the **first token**, critical for perceived speed |
    | `time_to_last_token`  | `float`           | Time (ms) to receive the **last token**, total generation time         |

    <Tip>
      **Time to First Token (TTFT)** is the key metric here. With streaming, the synthesizer starts converting text to speech as soon as the first tokens arrive, reducing overall latency.
    </Tip>
  </Tab>

  <Tab title="Synthesizer">
    Converts LLM text responses into spoken audio.

    ```json theme={"system"}
    {
      "synthesizer": {
        "time_to_connect": 271,
        "turns": [
          {
            "time_to_first_token": 599,
            "time_to_last_token": 800,
            "turn": 1
          },
          {
            "time_to_first_token": 317,
            "time_to_last_token": 518,
            "turn": 2
          }
        ]
      }
    }
    ```

    | Field                 | Type      | Description                                     |
    | --------------------- | --------- | ----------------------------------------------- |
    | `time_to_connect`     | `integer` | Time (ms) to connect to the TTS service         |
    | `turn`                | `integer` | Sequential turn number                          |
    | `time_to_first_token` | `integer` | Time (ms) to generate the **first audio chunk** |
    | `time_to_last_token`  | `integer` | Time (ms) to complete **all audio generation**  |

    <Info>
      Modern TTS systems stream audio. Playback begins before the entire response is synthesized, keeping the conversation flowing naturally.
    </Info>
  </Tab>
</Tabs>

***

## Identifying Bottlenecks

Use these thresholds to pinpoint performance issues across the pipeline:

<AccordionGroup>
  <Accordion title="High Transcriber Latency (>100ms per sequence)" icon="microphone">
    **Possible causes:**

    * Network issues with the transcription service
    * Need for a different transcription provider
    * Poor audio quality or background noise

    **Fix:** Try a different transcriber provider in your [Audio Tab](/docs/agent-setup/audio-tab) configuration, or improve audio input quality.
  </Accordion>

  <Accordion title="High LLM Time to First Token (>1000ms)" icon="brain">
    **Possible causes:**

    * LLM model is too large or complex
    * Prompts need optimization (too long or unstructured)
    * High load on the LLM service

    **Fix:** Consider a faster LLM model, optimize your prompt length, or try a different provider in your [LLM Tab](/docs/agent-setup/llm-tab).
  </Accordion>

  <Accordion title="High Synthesizer Latency (>500ms to first token)" icon="volume-high">
    **Possible causes:**

    * Network issues with the TTS service
    * Voice model is computationally expensive
    * Provider experiencing high load

    **Fix:** Try a different voice or TTS provider in your [Audio Tab](/docs/agent-setup/audio-tab) configuration.
  </Accordion>
</AccordionGroup>

***

## Related Pages

<CardGroup cols={3}>
  <Card title="Get Execution API" icon="code" href="/docs/api-reference/executions/get_execution">
    Retrieve execution details with latency data
  </Card>

  <Card title="Call Status List" icon="ballot-check" href="/docs/guides/post-call/list-phone-call-status">
    Track the full lifecycle of your calls
  </Card>

  <Card title="Hangup Status Codes" icon="phone-xmark" href="/docs/guides/post-call/list-phone-call-hangup-status">
    Understand call termination reasons
  </Card>
</CardGroup>
