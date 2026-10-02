> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Build an inbound AI voice agent

> Set up an AI-powered inbound voice agent on Vobiz that answers incoming calls and routes audio to your agent platform over SIP trunking - step-by-step guide.

This guide shows the pattern for answering inbound phone calls with **your** AI voice agent over Vobiz. Vobiz provides the phone number and the SIP rails that carry the call; your agent platform (Vapi, Retell, ElevenLabs, LiveKit, OpenAI Realtime, or a self-hosted pipeline) runs the conversation.

<Note>
  The exact UI steps differ per platform. This guide explains the **shared inbound pattern** and the values you map between the two systems. For click-by-click steps and screenshots, follow your platform's integration page under [Integrations](/docs/integrations).
</Note>

## How inbound works

```text theme={null}
Caller dials your Vobiz number → Vobiz inbound trunk → your AI platform's SIP endpoint → your AI agent answers
```

Vobiz receives the call on your number and forwards it to your agent platform. There are two transport styles, depending on the platform:

* **SIP** (Vapi, Retell, ElevenLabs, LiveKit, OpenAI Realtime, 3CX) - Vobiz routes the call leg to the platform's SIP URI. No server of your own is required.
* **WebSocket `<Stream>`** (Pipecat, Dograh, custom) - Vobiz POSTs your `answer_url`, you return a `<Stream>` XML response, and audio flows over a WebSocket to your own server.

## Prerequisites

* A [Vobiz account](https://console.vobiz.ai) with a phone number.
* An account on your chosen AI voice platform, with an agent/assistant already created.
* Access to the **SIP Trunk** section of the [Vobiz Console](https://console.vobiz.ai).

## Pattern A: SIP platforms

This is the path for most managed platforms.

<Steps>
  <Step title="Get the platform's inbound SIP URI">
    In your AI platform, create an **inbound** SIP trunk and copy its SIP URI, for example:

    * Vapi: `<trunk_id>.sip.vapi.ai` (the Trunk ID is read via the Vapi API, not the dashboard)
    * LiveKit: `<your-sip-uri>.sip.livekit.cloud`

    Strip any `sip:` prefix - you enter the **hostname only**.
  </Step>

  <Step title="Whitelist the Vobiz gateway IP on the platform">
    Configure the platform's inbound trunk to accept calls from the Vobiz gateway:

    | Setting | Value |
    | - | - |
    | Gateway IP | `13.233.44.61` |
    | Port | `5060` |
    | Netmask | `32` |
    | Protocol | `UDP` |
    | Inbound | Enabled |

    On platforms that use an allow-list (for example, LiveKit's **Allowed Addresses**), you can use `0.0.0.0/0` while testing and tighten it to the Vobiz gateway in production.
  </Step>

  <Step title="Create a Vobiz inbound trunk">
    In the [Vobiz Console](https://console.vobiz.ai), go to **SIP Trunk → Inbound Trunk** and create a trunk:

    * **Transport**: `UDP`
    * **Primary URI**: the platform SIP URI from Step 1 (hostname only, no `sip:`)
    * Link your Vobiz phone number to this trunk and save.
  </Step>

  <Step title="Assign your agent and test">
    On the platform side, attach your AI agent/assistant to the inbound number, then dial your Vobiz number from any phone. Your agent should answer.
  </Step>
</Steps>

<Check>
  Calls to your Vobiz number now route to your AI agent automatically.
</Check>

## Pattern B: self-hosted WebSocket platforms

For Pipecat, Dograh, or a custom pipeline you run yourself, Vobiz reaches your server over HTTP/WebSocket instead of SIP.

<Steps>
  <Step title="Create a Vobiz application">
    In the [Vobiz Console](https://console.vobiz.ai), open **Applications → Create New Application**. Set the **Answer URL** to your server's `/answer` route and the method to `POST`.
  </Step>

  <Step title="Assign your number to the application">
    Go to **Phone Numbers**, select your number, and assign it to the application.
  </Step>

  <Step title="Return a Stream response">
    When a call comes in, Vobiz POSTs your `answer_url`. Return a `<Stream>` response pointing at your WebSocket:

    ```xml theme={null}
    <Response>
      <Stream bidirectional="true" keepCallAlive="true">
        wss://your-server/ws
      </Stream>
    </Response>
    ```

    Vobiz opens the WebSocket and sends a `start` event followed by inbound `media` events. Decode incoming audio using `start.mediaFormat`. For the AI response, send `playAudio` with raw mono audio that matches its declared `contentType` and `sampleRate`. Inbound and outbound formats can differ. See the [Stream XML reference](/docs/xml/stream) and the [WebSockets integration](/docs/integrations/websockets).
  </Step>
</Steps>

## Credential and URI mapping

| Direction of trust | Value | Where it lives |
| - | - | - |
| Vobiz → platform (where to send the call) | Platform SIP URI, e.g. `<id>.sip.vapi.ai` | Vobiz inbound trunk **Primary URI** |
| Platform trusts Vobiz | Gateway IP `13.233.44.61` (UDP/5060) | Platform inbound trunk allow-list |

## Troubleshooting

* **Call disconnects immediately**: confirm the platform's SIP URI is entered **without** the `sip:` prefix, and that your Vobiz number is linked to the inbound trunk.
* **Caller hears nothing / agent never answers**: verify the gateway IP `13.233.44.61` is whitelisted on the platform, and that your agent is published and attached to the number.
* **Wrong domain**: use the platform's exact SIP URI - a generic host won't authenticate.

## Next steps

* Pick your platform's step-by-step guide in [Integrations](/docs/integrations).
* Build outbound calling too → [Build an outbound AI voice agent](/docs/guides/ai-voice-agent/outbound).
* Stream verb details → [Stream XML reference](/docs/xml/stream).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.