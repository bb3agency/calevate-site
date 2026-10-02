> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# LiveKit IVR with DTMF

> Build an IVR menu in a LiveKit AI voice agent on Vobiz that responds to DTMF keypad input in addition to spoken voice commands - Python example.

Build an IVR (Interactive Voice Response) menu in LiveKit that responds to both voice commands and keypad presses (DTMF tones).

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-Livekit-IVR-DTMF-Example">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Livekit-IVR-DTMF-Example.git
cd Vobiz-Livekit-IVR-DTMF-Example
pip install -r requirements.txt
python agent.py dev
```

## Overview

Some callers are in noisy environments or prefer pressing keys over speaking. This example shows how to build a LiveKit agent that handles both speech input and DTMF keypad input simultaneously - providing a reliable IVR experience for all callers.

## How it works

1. The agent presents menu options via text-to-speech.
2. The agent listens for both speech ("press 1 for billing") and DTMF tones.
3. Whichever is detected first triggers the routing logic.
4. The appropriate sub-menu or action is invoked.

## IVR menu structure

```text theme={null}
"Welcome. Press 1 for Sales, 2 for Support, 3 for Billing, or say the department name."

1 or "sales"   → Sales agent
2 or "support" → Technical Support agent
3 or "billing" → Billing department
0 or "operator" → Human agent transfer
```

## DTMF detection

LiveKit forwards DTMF tones from the SIP leg through the SIP INFO method. The agent subscribes to DTMF events on the room and maps digits to menu choices.

```python theme={null}
@ctx.room.on("dtmf_received")
def on_dtmf(digit: str):
    if digit == "1":
        route_to_sales()
    elif digit == "2":
        route_to_support()
    elif digit == "3":
        route_to_billing()
```

## Environment variables

```bash .env theme={null}
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxx
OPENAI_API_KEY=sk-...
SALES_NUMBER=+919XXXXXXXXX
SUPPORT_NUMBER=+919XXXXXXXXX
BILLING_NUMBER=+919XXXXXXXXX
HUMAN_AGENT_NUMBER=+919XXXXXXXXX
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.