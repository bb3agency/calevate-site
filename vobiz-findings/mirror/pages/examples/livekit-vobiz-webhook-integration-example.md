> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# LiveKit webhook & CRM integration

> Push Vobiz call events to your CRM in real time using HMAC-signed webhooks and LiveKit function tools - end-to-end Python example with sample payloads.

Stream call events to your CRM during a live conversation using LiveKit function tools and HMAC-signed webhooks.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Livekit-Vobiz-Webhook-Integration-Example">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Livekit-Vobiz-Webhook-Integration-Example.git
cd Livekit-Vobiz-Webhook-Integration-Example
pip install -r requirements.txt
python agent.py dev
```

## Overview

The agent loads call metadata from your CRM before the call connects, then dispatches signed webhook events throughout the call lifecycle. During the conversation, the agent has access to four function tools that send non-blocking HTTP POSTs to your backend without interrupting the audio stream.

## Agent function tools

| Tool | Description |
| - | - |
| `record_intent` | Log a custom intent note to the CRM mid-call |
| `lookup_crm` | Fetch customer data by phone number |
| `update_crm_note` | Append a note to the active customer record |
| `transfer_call` | Transfer the caller to a human agent via SIP REFER |

## Webhook events

| Event | When it fires |
| - | - |
| `call.started` | Immediately when the agent joins the room |
| `call.ended` | When the call disconnects |
| `intent.recorded` | When the agent calls `record_intent` |
| `crm.updated` | When the agent calls `update_crm_note` |

All webhook payloads are signed with HMAC SHA-256 using your `WEBHOOK_SECRET`.

## Key code

```python theme={null}
@llm.function_tool(description="Log a custom intent note to the CRM mid-call")
async def record_intent(context: llm.FunctionContext, intent: str):
    """Asynchronous webhook POST executed during audio streaming"""
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"{CRM_URL}/webhooks/intent",
            json={"intent": intent, "call_id": call_id},
            headers={"X-Signature": compute_hmac(payload)}
        )
```

## Environment variables

```bash .env theme={null}
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxx
CRM_URL=https://your-crm.example.com
WEBHOOK_SECRET=your-hmac-secret
OPENAI_API_KEY=sk-...
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.