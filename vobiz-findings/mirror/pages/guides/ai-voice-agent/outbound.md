> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Build an outbound AI voice agent

> Set up an AI-powered voice agent on Vobiz that places outbound calls - dial out from your agent platform over Vobiz SIP trunking with full control.

This guide shows the pattern for placing outbound calls with **your** AI voice agent over Vobiz. Vobiz provides the SIP trunk and caller-ID number that carry the call to the public phone network; your agent platform (Vapi, Retell, ElevenLabs, LiveKit, Bolna, Ultravox, or a self-hosted pipeline) drives the conversation once the call connects.

<Note>
  The exact steps differ per platform. This guide explains the **shared outbound pattern** and the credentials you map between systems. For click-by-click steps and screenshots, follow your platform's integration page under [Integrations](/docs/integrations).
</Note>

## How outbound works

```text theme={null}
Your app / platform → AI agent platform → Vobiz outbound SIP trunk → phone network → recipient
```

Your platform authenticates to your Vobiz **outbound trunk** with a SIP domain, username, and password, then dials the recipient using your Vobiz number as caller ID.

## Prerequisites

* A [Vobiz account](https://console.vobiz.ai) with **active balance** (outbound calls consume credit).
* A Vobiz phone number to use as caller ID.
* An account on your chosen AI voice platform, with an agent already created.

## Step 1: Create an outbound trunk in Vobiz

<Steps>
  <Step title="Create the trunk">
    In the [Vobiz Console](https://console.vobiz.ai), go to **SIP Trunk → Outbound Trunks → Trunks** and click **+ Create Trunk**. Name it (for example, `AI Agent Outbound`).
  </Step>

  <Step title="Attach a credential">
    Under **Authentication & Linking**, select an existing credential or create a new one, then save the trunk.
  </Step>

  <Step title="Copy the connection details">
    From the **Authentication & Linking** section, copy:

    | Field | Example |
    | - | - |
    | SIP domain | `<your_unique_domain>.sip.vobiz.ai` |
    | Username | `<your_username>` |
    | Password | `<your_password>` |

    Use the **exact** SIP domain - never a generic `sip.vobiz.ai`.
  </Step>
</Steps>

## Step 2: Connect the trunk on your AI platform

Paste the three Vobiz values into your platform's outbound SIP trunk. The field names vary, but the mapping is always the same:

| Vobiz value | Common platform field name |
| - | - |
| SIP domain | Gateway URL / Address / Termination URI |
| Username | SIP username / `auth_username` |
| Password | SIP password / `auth_password` |
| Your Vobiz number | Caller ID / `from` / `numbers` |

<Warning>
  When a platform asks for a **Termination URI** or **Address**, enter the SIP domain **without** the `sip:` prefix - hostname only.
</Warning>

Examples of how this looks per platform (see each integration page for full steps):

* **Vapi / Retell / ElevenLabs**: add a SIP trunk credential with the domain + username + password, then import your Vobiz number as a BYO SIP number.
* **LiveKit**: `create_sip_outbound_trunk(address=sip_domain, auth_username=username, auth_password=password, numbers=[your_number])`.
* **Ultravox / Bolna**: pass the Vobiz credentials in the call-start request or provider settings.

## Step 3: Place a call

Trigger an outbound call from your platform (a single call, a batch, or via the platform API). Select your imported Vobiz number as the caller ID and your AI agent as the assistant. When the recipient answers, your agent speaks.

<Check>
  Your AI agent can now place outbound calls through Vobiz SIP infrastructure.
</Check>

## Self-hosted pipelines (Pipecat / Dograh / custom)

If you run your own pipeline, you can dial out with the Vobiz Call API and let Vobiz fetch a `<Stream>` instruction that points at your WebSocket:

```bash theme={null}
curl -X POST https://api.vobiz.ai/api/v1/Account/YOUR_AUTH_ID/Call/ \
  -H "X-Auth-ID: YOUR_AUTH_ID" \
  -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "+918011223344",
    "to": "+919148223344",
    "answer_url": "https://your-server/answer",
    "answer_method": "POST"
  }'
```

Your `/answer` route returns a `<Stream>` response and audio flows over the WebSocket. See [WebSockets](/docs/integrations/websockets) and [Pipecat](/docs/integrations/pipecat).

## Optional: call transfer to a human

Most platforms support transferring the AI call to a live agent (blind/cold transfer over SIP REFER). The agent constructs a SIP URI like `sip:+15550001234@<your-sip-domain>` and initiates the transfer. Enable **Call Transfer (SIP REFER)** on your Vobiz trunk and configure the destination on the platform. See the transfer sections of the [LiveKit](/docs/integrations/livekit#part-6-sip-call-transfer) and [Vapi](/docs/integrations/vapi-dashboard) guides.

## Troubleshooting

* **401 Unauthorized**: the username/password on the platform trunk don't match your Vobiz outbound trunk.
* **Call fails silently / doesn't connect**: you used a generic `sip.vobiz.ai` instead of your exact `<id>.sip.vobiz.ai`, or left a `sip:` prefix on the domain.
* **Insufficient balance**: outbound calling needs Vobiz credit - top up in the Console.
* **Phone number format error**: use E.164 (`+919148223344`); confirm the number is active in Vobiz.

## Next steps

* Pick your platform's step-by-step guide in [Integrations](/docs/integrations).
* Answer inbound calls too → [Build an inbound AI voice agent](/docs/guides/ai-voice-agent/inbound).
* Place programmatic calls → [Make a Call](/docs/call/make-call).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.