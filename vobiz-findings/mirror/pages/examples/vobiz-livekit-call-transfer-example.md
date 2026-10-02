> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Call transfer agent

> Transfer an active Vobiz call to any E.164 phone number via SIP REFER from inside a LiveKit AI voice agent - full code, payloads, and trunk setup.

Transfer an active call to any E.164 phone number or department via SIP REFER from a LiveKit AI agent.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-Livekit-Call-Transfer-Example">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Livekit-Call-Transfer-Example.git
cd Vobiz-Livekit-Call-Transfer-Example
pip install -r requirements.txt
python agent.py dev
```

## Overview

The AI agent handles the conversation and, when instructed, performs a cold SIP REFER transfer to any phone number. The agent constructs the SIP URI dynamically - the caller is transferred and the agent disconnects.

## How it works

1. Caller requests a transfer (e.g. "Transfer me to sales" or "Transfer me to +1 555 000 1234").
2. The agent calls the `transfer_call` function tool.
3. The agent sends a SIP REFER to `sip:+15550001234@your-vobiz-domain`.
4. Vobiz routes the call to the destination.
5. The agent leaves the room - the transfer is complete.

## Agent function tool

```python theme={null}
@llm.function_tool(description="Transfer the caller to an E.164 phone number directly")
async def transfer_call(context: llm.FunctionContext, phone_number: str):
    sip_uri = f"sip:{phone_number}@{VOBIZ_SIP_DOMAIN}"
    await context.room.local_participant.perform_rpc(
        destination_identity="sip",
        method="transfer",
        payload=sip_uri
    )
```

## Preset department transfers

Configure preset destinations in `.env` and map them to named tools:

| Command | Destination |
| - | - |
| "Transfer to billing" | `BILLING_NUMBER` |
| "Transfer to support" | `SUPPORT_NUMBER` |
| "Transfer me to \[number]" | Any E.164 number |

## Environment variables

```bash .env theme={null}
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxx
VOBIZ_SIP_DOMAIN=your-domain.sip.vobiz.ai
OPENAI_API_KEY=sk-...
BILLING_NUMBER=+919XXXXXXXXX
SUPPORT_NUMBER=+919XXXXXXXXX
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.