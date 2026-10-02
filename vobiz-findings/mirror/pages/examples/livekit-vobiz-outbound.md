> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# LiveKit outbound calling

> Place outbound calls from a LiveKit AI voice agent via a Vobiz SIP trunk, with per-call dispatch metadata and end-of-call webhooks - Python example.

Make outbound calls from a LiveKit AI voice agent using Vobiz SIP trunking.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/LiveKit-Vobiz-Outbound">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/LiveKit-Vobiz-Outbound.git
cd LiveKit-Vobiz-Outbound
pip install -r requirements.txt
python agent.py dev
```

## Overview

The agent uses the LiveKit Python SDK to create an outbound SIP trunk pointing to Vobiz, then dials a destination number. When the call is answered, the person joins the LiveKit room and the AI agent handles the conversation.

## How it works

1. Call `lk.sip.create_sip_outbound_trunk()` with your Vobiz SIP domain, username, and password.
2. Call `lk.sip.create_sip_participant()` with the destination number.
3. LiveKit sends a SIP INVITE to Vobiz.
4. Vobiz dials the destination via PSTN.
5. When answered, the caller joins the room and the AI agent takes over.

## Key code

```python theme={null}
from livekit import api as livekit_api

lk = livekit_api.LiveKitAPI(
    url="YOUR_LIVEKIT_URL",
    api_key="YOUR_LIVEKIT_API_KEY",
    api_secret="YOUR_LIVEKIT_API_SECRET"
)

# Create outbound trunk pointing to Vobiz
trunk = await lk.sip.create_sip_outbound_trunk(
    livekit_api.CreateSIPOutboundTrunkRequest(
        trunk=livekit_api.SIPOutboundTrunkInfo(
            name="Vobiz Trunk",
            address="YOUR_VOBIZ_SIP_DOMAIN",
            auth_username="YOUR_VOBIZ_USERNAME",
            auth_password="YOUR_VOBIZ_PASSWORD",
            numbers=["YOUR_PHONE_NUMBER"]
        )
    )
)

# Dial a number
participant = await lk.sip.create_sip_participant(
    livekit_api.CreateSIPParticipantRequest(
        sip_trunk_id=trunk.sip_trunk_id,
        sip_call_to="+1234567890",
        room_name="call-room"
    )
)
```

## Environment variables

```bash .env theme={null}
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxx
VOBIZ_SIP_DOMAIN=your-domain.sip.vobiz.ai
VOBIZ_USERNAME=your-username
VOBIZ_PASSWORD=your-password
VOBIZ_PHONE_NUMBER=+919XXXXXXXXX
```

## Resources

* [LiveKit Agents docs](https://docs.livekit.io/agents)
* [LiveKit SIP integration](https://docs.livekit.io/sip)
* [Vobiz SIP Trunks](/docs/trunks)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.