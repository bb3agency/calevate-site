> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# LiveKit inbound calling

> Route inbound calls from any Vobiz phone number to a LiveKit AI voice agent over SIP trunking with real-time audio streaming - Python example.

Accept inbound calls on a Vobiz phone number and route them to a LiveKit AI voice agent.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Livekit-vobiz-inbound">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Livekit-vobiz-inbound.git
cd Livekit-vobiz-inbound
pip install -r requirements.txt
python agent.py dev
```

## Overview

When someone calls your Vobiz number, the call is routed via SIP to LiveKit. A dispatch rule automatically spawns your AI agent into a room where the caller is connected. The agent handles the conversation using LiveKit's real-time audio pipeline.

## How it works

1. Caller dials your Vobiz number.
2. Vobiz SIP routes the call to your LiveKit SIP URI (configured as `inbound_destination` on your trunk).
3. LiveKit receives the call and applies the dispatch rule.
4. The dispatch rule auto-spawns your agent into the call room.
5. The AI agent greets the caller and handles the conversation.

## Setup requirements

* A Vobiz SIP trunk with `inbound_destination` set to your LiveKit SIP URI
* A LiveKit inbound SIP trunk with your Vobiz phone number
* A LiveKit dispatch rule configured to auto-spawn your agent

<Note>
  When entering the LiveKit SIP URI as the Vobiz `inbound_destination`, remove the `sip:` prefix. Enter `your-id.sip.livekit.cloud` not `sip:your-id.sip.livekit.cloud`.
</Note>

## Environment variables

```bash .env theme={null}
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxx
```

## Resources

* [LiveKit Agents docs](https://docs.livekit.io/agents)
* [LiveKit SIP integration](https://docs.livekit.io/sip)
* [Vobiz SIP Trunks](/docs/trunks)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.