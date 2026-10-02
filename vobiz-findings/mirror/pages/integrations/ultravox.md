> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Ultravox Integration

> Run Ultravox conversational AI over Vobiz SIP trunking - configure your trunk, dispatch outbound calls, and reach 130+ countries including India.

Setting up **outbound calls** with Ultravox and Vobiz is straightforward: send Ultravox a request to start a call along with your Vobiz credentials, and Ultravox handles the rest.

## What you'll build

A programmatic outbound calling integration where Ultravox places calls through your Vobiz SIP trunk, with the Ultravox AI agent driving the conversation once the call is answered.

## Prerequisites

* **Ultravox account** with API key and an agent → [Ultravox dashboard](https://app.ultravox.ai)
* **Vobiz account** with a SIP trunk → [Vobiz Console](https://console.vobiz.ai)
* **A Vobiz phone number** to use as caller ID

## Step 1: Gather your credentials

You need three pieces of information to connect the two systems.

| Source | Item | Where to get | Value / description |
| - | - | - | - |
| Ultravox | API key | [Ultravox keys](https://app.ultravox.ai) | `YOUR_API_KEY` |
| Ultravox | Agent ID | [Ultravox dashboard](https://app.ultravox.ai) | `YOUR_AGENT_ID` |
| Vobiz | SIP domain | [Vobiz trunks](https://console.vobiz.ai) | `YOUR_DOMAIN.sip.vobiz.ai` |
| Vobiz | Username | [Vobiz trunks](https://console.vobiz.ai) | `YOUR_USERNAME` |
| Vobiz | Password | [Vobiz trunks](https://console.vobiz.ai) | `YOUR_PASSWORD` |
| Vobiz | From number | [Vobiz numbers](https://console.vobiz.ai) | `+91XXXXXXXXXX` |

## Step 2: Place an outbound call

Unlike inbound calls, you don't need to add a URI to Vobiz. Send a `POST` request to Ultravox, and Ultravox pushes the call to Vobiz.

```bash theme={null}
curl -X POST "https://api.ultravox.ai/api/agents/YOUR_AGENT_ID/calls" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "medium": {
      "sip": {
        "outgoing": {
          "to": "sip:+919XXXXXXXXX@YOUR_VOBIZ_DOMAIN.sip.vobiz.ai",
          "from": "YOUR_VOBIZ_NUMBER",
          "username": "YOUR_VOBIZ_USERNAME",
          "password": "YOUR_VOBIZ_PASSWORD"
        }
      }
    },
    "firstSpeakerSettings": { "user": {} }
  }'
```

## Step 3: Critical parameters explained

* **`to`** - destination URI. Format: `sip:NUMBER@VOBIZ_DOMAIN`.
* **`from`** - your caller ID. Most SIP providers (including Vobiz) reject the call if this doesn't match a number you actually purchased from them.
* **`firstSpeakerSettings: { "user": {} }`** - required for outbound calls. It tells the AI to wait for the human to say "hello" before speaking, so the AI doesn't finish its greeting while the call is still connecting.

## Step 4: Call lifecycle

1. **Request** - you run the curl. Ultravox returns a `callId` immediately.
2. **Invite** - Ultravox sends a SIP `INVITE` to your Vobiz domain using your credentials.
3. **Ringing** - the destination phone starts ringing. SIP billing starts now.
4. **Connect** - the user picks up and says "hello".
5. **Conversation** - Ultravox detects the speech and the AI agent starts the conversation.

## Troubleshooting

If the call doesn't ring, use this API to see why Vobiz rejected it:

```bash theme={null}
# Replace CALL_ID with the ID returned by the create-call request
curl -X GET "https://api.ultravox.ai/api/calls/CALL_ID/sip/logs" \
  -H "X-API-Key: YOUR_API_KEY"
```

Common SIP error codes:

| Code | Meaning |
| - | - |
| 403 Forbidden | Wrong username/password or your IP isn't allowed. |
| 407 Proxy Authentication Required | Normal - Ultravox should handle it automatically using your password. |
| 480 Temporarily Unavailable | The destination number is busy or turned off. |

## Next steps

* See the [Ultravox documentation](https://docs.ultravox.ai) for advanced agent configuration.
* Read about [Vobiz SIP trunks](/docs/trunks) to manage your trunk credentials.
* Track call records in the [Vobiz Console](https://console.vobiz.ai).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.