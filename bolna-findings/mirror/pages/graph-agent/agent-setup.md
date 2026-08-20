> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Agent Setup

> Configure the welcome message, LLM, voice, and conversation behaviour for your graph agent.

With no node or transition selected, the inspector shows the **Agent setup** tab. This is where you configure everything that applies to the agent as a whole, rather than to a specific node.

***

## Agent Basics

The first collapsible section contains top-level agent settings.

| Field               | Description                                                                                                                                                                                     |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Agent name**      | The display name for this agent in the Bolna dashboard.                                                                                                                                         |
| **Start node**      | The entry-point node for every new call. Equivalent to clicking **Make start node** on a node in the canvas.                                                                                    |
| **Welcome message** | The first thing the agent says when a call connects, before any node is active. Supports `{variable}` tokens — see [Variables](/docs/graph-agent/variables).                                         |
| **Global prompt**   | System-level prompt applied to every LLM call in this agent. Use it for persona, language rules, guardrails, and pronunciation rules. This is the `agent_information` field in the JSON schema. |

***

## Welcome message

The first thing the agent says when a call connects, before any node is active.

```
Hi there! Thanks for calling Acme support. How can I help you today?
```

You can use `{variable}` tokens in the welcome message. Any tokens here are discovered by the [Variables panel](/docs/graph-agent/variables) so you can set test values.

***

## LLM settings

Controls the response LLM used across all nodes that don't override it individually.

| Field                | Description                                                                                                                                                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Provider**         | The LLM provider (e.g. OpenAI, Anthropic, Google).                                                                                                                                                                                   |
| **Model**            | Specific model name. Choose from the dropdown of supported models for the selected provider.                                                                                                                                         |
| **Temperature**      | Controls response randomness. Lower values (0.0–0.5) produce consistent, predictable output. Higher values (0.8–1.5) produce more varied responses. GPT-5 models accept only `1`.                                                    |
| **Max tokens**       | Cap on the number of tokens in each response. On GPT-5 models this budget is shared with reasoning tokens.                                                                                                                           |
| **Reasoning effort** | For models that support it. The control offers only the values the selected model accepts, so the options change when you switch models. Higher effort increases latency and cost; stay at the lowest one or two settings for voice. |

<Tip>
  Individual nodes can override these settings in their **LLM overrides** section. The agent-level settings serve as the default for any node that doesn't override them.
</Tip>

***

## STT settings (speech-to-text)

Configures the transcriber that converts the caller's voice to text.

| Field               | Description                                                                              |
| ------------------- | ---------------------------------------------------------------------------------------- |
| **Transcriber**     | Select from supported STT providers.                                                     |
| **Advanced config** | JSON editor for provider-specific settings (e.g. language hints, keywords, punctuation). |

***

## TTS settings (text-to-speech)

Configures the voice synthesis that converts the agent's text responses to audio.

| Field               | Description                                                                           |
| ------------------- | ------------------------------------------------------------------------------------- |
| **Language**        | The primary language for voice synthesis.                                             |
| **Advanced config** | JSON editor for synthesizer-specific settings (voice ID, speaking rate, pitch, etc.). |

***

## Conversation settings

Controls call-level behaviour: timeouts, silence handling, backchanneling, and special modes.

### Timing

| Setting                   | Description                                                                 | Default |
| ------------------------- | --------------------------------------------------------------------------- | ------- |
| **Welcome message delay** | Seconds to wait after the call connects before playing the welcome message. | 0       |
| **Hang up after silence** | Seconds of total silence before the agent ends the call.                    | —       |
| **Call terminate**        | Hard timeout in seconds for the entire call.                                | —       |

### Interruption

| Setting                              | Description                                                                                                                                         |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Number of words for interruption** | Minimum words the user must speak before the agent considers it an interruption and stops speaking. Lower values make the agent more interruptible. |

### Backchanneling

Backchanneling plays short filler phrases ("Mm-hmm", "I see") while the agent is processing, so the caller doesn't experience dead silence.

| Setting         | Description                                                |
| --------------- | ---------------------------------------------------------- |
| **Enabled**     | Toggle backchanneling on or off.                           |
| **Start delay** | Seconds to wait before the first backchannel phrase plays. |
| **Message gap** | Minimum seconds between backchannel phrases.               |

### Online check

Periodically checks whether the user is still on the line.

| Setting           | Description                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Enabled**       | Toggle online check on or off.                                                                                                 |
| **Trigger after** | Seconds of silence before checking if the user is still there.                                                                 |
| **Check message** | The phrase the agent says to check (e.g. "Are you still there?"). Supports multilingual object (`{"en": "...", "hi": "..."}`). |

### Voicemail detection

| Setting                | Description                                                           |
| ---------------------- | --------------------------------------------------------------------- |
| **Enabled**            | Toggle voicemail detection on or off.                                 |
| **Detection duration** | Seconds to wait while determining whether the call went to voicemail. |

### Discard pre-welcome utterance

When enabled, any speech detected before the welcome message finishes playing is discarded. Useful for outbound calls where the recipient often says "Hello?" before the agent starts speaking.

***

## Extra agent config

An advanced JSON editor for any agent configuration keys not covered by the fields above. Changes here are merged into `agent_config` when the agent is saved. Use this for platform-specific settings not yet exposed in the UI.

<Warning>
  Only keys the platform knows about are written on save. Unknown keys are dropped. Check the [API reference](/docs/api-reference/agent/create) for a full list of accepted fields.
</Warning>
