> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Machine Detection

> Detect answering machines and voicemail on global outbound calls with Vobiz AMD - configure sync or async mode, silence timeout, callback delivery, and tuned profiles for AI voice agents.

Detect answering machines on outbound calls with synchronous or asynchronous detection modes.

## Introduction

<Warning>
  **Important: Not a Separate Endpoint.** Machine detection is **NOT a separate API endpoint**. It is configured as parameters when making a call using `POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/`. This page documents the machine detection parameters and callback format.
</Warning>

Machine detection allows you to identify when an answering machine picks up your outbound call instead of a human. You can configure Vobiz to either hang up automatically or continue the call when a machine is detected.

<Note>
  Machine detection is only supported on outbound calls initiated via the [Make Call API](/docs/call/make-call). Set the `machine_detection` parameter to enable this feature.
</Note>

## Synchronous Machine Detection

When you set `machine_detection=true` or `machine_detection=hangup` when making a call, Vobiz analyzes the audio after the call is answered to determine if a machine answered.

| Field | Type | Required | Description |
| - | - | - | - |
| `machine_detection` | string | No | Set to "true" to continue the call or "hangup" to automatically hang up when a machine is detected. |
| `machine_detection_time` | integer | No | Time in milliseconds to analyze audio. Default: 5000. Range: 2000–10000. |
| `machine_detection_maximum_speech_length` | integer | No | Maximum speech duration in milliseconds. Default: 5000. Range: 1000–6000. |
| `machine_detection_initial_silence` | integer | No | Maximum silence after answer in milliseconds. Default: 4500. Range: 2000–10000. |
| `machine_detection_maximum_words` | integer | No | Maximum number of sentences. Default: 3. Range: 2–10. |
| `machine_detection_initial_greeting` | integer | No | Maximum greeting length in milliseconds. Default: 1500. Range: 1000–5000. |

## Asynchronous Machine Detection

To act on a detected answering machine, set the `machine_detection_url` parameter when making an outbound call. Vobiz detects the answering machine in the background and invokes `machine_detection_url` with the results.

| Field | Type | Required | Description |
| - | - | - | - |
| `machine_detection_url` | string | No | Callback URL invoked when machine detection completes. Vobiz sends detection results to this URL. |
| `machine_detection_method` | string | No | HTTP method used to invoke machine\_detection\_url. Default: POST. |

<Tip>
  **Benefit:** Asynchronous detection allows your application to handle the call immediately while detection happens in the background, providing better user experience.
</Tip>

## Tuning for AI voice agents

The AMD defaults describe a **human dialer's** call: a person dials, stays quiet, hears "Hello?", and starts talking. Every default is sized for that — a short greeting, a couple of sentences, a few seconds of analysis.

An AI agent behaves differently. It starts its greeting the instant the leg is answered, so the agent and the answering machine are speaking **at the same time** through the whole analysis window. Two things go wrong:

* **The clean sample never forms.** A human pickup is "Hello?" followed by a pause. If the agent is already talking, the callee answers over it, and the silence-then-greeting shape the classifier looks for is never there.
* **The window is too tight for a machine.** A voicemail greeting runs 5–15 seconds. With a 5000 ms window and a 1500 ms greeting allowance, the decision is made from the first fragment of it — which is the part that sounds most like a person saying hello.

Both are fixed the same way: **hold the agent silent until detection resolves**, and widen the windows so the classifier gets an unambiguous sample.

### What each knob does with an AI caller

| Parameter | Raise it when | Lower it when |
| - | - | - |
| `machine_detection_time` | You want an unambiguous decision and can tolerate the wait. This is the ceiling on every other timer. | Dead air is costing you answered calls. |
| `machine_detection_initial_silence` | Callees pick up and wait, or the network adds post-answer delay. A slow "hello" should not be read as a machine. | You would rather treat a long silence as voicemail immediately. |
| `machine_detection_initial_greeting` | Callees give longer greetings — a name, a company, an accented or slower delivery. | Voicemail greetings are slipping through as human. |
| `machine_detection_maximum_words` | A chatty human ("Hello? Hello, who's this?") is being classified as a machine. | You want the decision made from the first utterance only. |
| `machine_detection_maximum_speech_length` | Humans who keep talking are flipping to machine. | You want long continuous speech treated as a recording sooner. |

### Starting profiles

Pick by what you are optimising for, then validate against your own call recordings — answer behaviour varies by country, carrier, and audience.

<CodeGroup>
  ```json Balanced (recommended) theme={null}
  {
    "machine_detection": "true",
    "machine_detection_url": "https://example.com/amd",
    "machine_detection_method": "POST",
    "machine_detection_time": 4000,
    "machine_detection_initial_silence": 4000,
    "machine_detection_initial_greeting": 2500,
    "machine_detection_maximum_words": 5,
    "machine_detection_maximum_speech_length": 4000
  }
  ```

  ```json High accuracy theme={null}
  {
    "machine_detection": "hangup",
    "machine_detection_url": "https://example.com/amd",
    "machine_detection_method": "POST",
    "machine_detection_time": 8000,
    "machine_detection_initial_silence": 8000,
    "machine_detection_initial_greeting": 3000,
    "machine_detection_maximum_words": 10,
    "machine_detection_maximum_speech_length": 6000
  }
  ```

  ```json Low latency theme={null}
  {
    "machine_detection": "true",
    "machine_detection_url": "https://example.com/amd",
    "machine_detection_method": "POST",
    "machine_detection_time": 2500,
    "machine_detection_initial_silence": 2500,
    "machine_detection_initial_greeting": 1500,
    "machine_detection_maximum_words": 3,
    "machine_detection_maximum_speech_length": 2500
  }
  ```
</CodeGroup>

| Profile | Use it for | Trade-off |
| - | - | - |
| **Balanced** | A live AI agent that should hold a real conversation with whoever answers | \~4 s before the agent's first word. Most humans tolerate this only if the line is not silent — see [Gating the agent on the result](#gating-the-agent-on-the-result). |
| **High accuracy** | Voicemail-drop campaigns, or anything where a wrong classification is expensive | Up to 8 s of dead air. Use `hangup` so machine-answered calls cost nothing beyond the window. |
| **Low latency** | Warm lists where nearly everyone is a human and speed matters | More voicemails classified as human. Your agent will talk to some recordings. |

<Warning>
  **The agent must not speak during the analysis window.** These values are only worth setting if your application actually holds the first utterance until the result arrives. An agent that greets on answer puts its own speech into the window, and no combination of timers recovers from that.
</Warning>

### Gating the agent on the result

Use **asynchronous** detection so the media path is live while detection runs, and gate the greeting on the callback:

<Steps>
  <Step title="Place the call with machine_detection_url set">
    Pass one of the profiles above to [Make a Call](/docs/call/make-call). Detection runs in the background.
  </Step>

  <Step title="Answer with something that is not silence">
    Return XML that holds the leg without speaking words the classifier will pick up — a [`<Wait>`](/docs/xml/wait) sized to your `machine_detection_time`, or hold music. Silence on a fresh pickup makes people hang up or say "hello?" repeatedly.
  </Step>

  <Step title="Branch on the callback">
    `Machine: false` → connect the caller to the agent and let it greet. `Machine: true` → play your recorded message, or hang up.
  </Step>

  <Step title="Fall back if the callback is late">
    Set a deadline just past `machine_detection_time`. If nothing has arrived, treat the call as human — a live person on hold is the more expensive mistake.
  </Step>
</Steps>

<Tip>
  **Waiting for the beep instead.** If your goal is to leave a message rather than classify the pickup, the [`<Wait>` `silence` parameter](/docs/xml/wait/machine-detection) is the better tool — it continues the flow the moment the greeting stops, instead of guessing at its length. Pair it with `machine_detection` for the branch and `<Wait silence="true">` for the timing.
</Tip>

<Card title="Working example: AMD before the agent speaks" icon="robot" href="/docs/examples/livekit-vobiz-machine-detection-agent-example" horizontal>
  A LiveKit agent that classifies the pickup before starting its conversation, and leaves a recorded message on voicemail.
</Card>

## Parameters Sent to machine\_detection\_url

When machine detection completes, Vobiz sends these parameters to your machine\_detection\_url:

| Field | Type | Description |
| - | - | - |
| `From` | string | The caller ID number used to initiate the call. |
| `Machine` | boolean | `true` if a machine was detected. |
| `To` | string | Destination of the call. |
| `RequestUUID` | string | Unique identifier for the call request. |
| `ALegRequestUUID` | string | Identifier for the first leg of the call (multi-leg calls). |
| `CallUUID` | string | Unique identifier for the call. |
| `IfMachine` | string | `"continue"` or `"hangup"`, reflecting the `machine_detection` value set when initiating the call. |
| `Direction` | string | Direction of the call. Always `"outbound"` (machine detection is only supported on outbound calls). |
| `ALegUUID` | string | Unique identifier for the A leg of the call. |
| `Event` | string | Event that triggered this notification. Always `"MachineDetection"`. |
| `CallStatus` | string | Status of the call. Always `"in-progress"`. |

### Example Callback Response

```json JSON Sent to machine_detection_url theme={null}
{
  "From": "+12025550000",
  "Machine": true,
  "To": "+12025551111",
  "RequestUUID": "9834029e-58b6-11e1-b8b7-a5bd0e4e126f",
  "ALegRequestUUID": "9834029e-58b6-11e1-b8b7-a5bd0e4e126f",
  "CallUUID": "97ceeb52-58b6-11e1-86da-77300b68f8bb",
  "IfMachine": "continue",
  "Direction": "outbound",
  "ALegUUID": "97ceeb52-58b6-11e1-86da-77300b68f8bb",
  "Event": "MachineDetection",
  "CallStatus": "in-progress"
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.