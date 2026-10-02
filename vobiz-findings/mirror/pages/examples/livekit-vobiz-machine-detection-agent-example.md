> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Answering machine detection

> Detect whether an outbound LiveKit call reached a human or a voicemail machine on Vobiz before your AI agent begins speaking - Python example.

Detect whether an outbound call was answered by a human or an answering machine before your AI agent starts speaking.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Livekit-Vobiz-Machine-Detection-Agent-example">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Livekit-Vobiz-Machine-Detection-Agent-example.git
cd Livekit-Vobiz-Machine-Detection-Agent-example
pip install -r requirements.txt
python agent.py dev
```

## Overview

When making outbound calls at scale, many calls land on voicemail. This example shows how to detect a machine answer versus a human answer, and react accordingly - leaving a pre-recorded message for voicemail, or starting a live conversation with a human.

## How it works

1. The agent dials out via Vobiz SIP using LiveKit's outbound calling.
2. When the call connects, the agent listens for audio patterns.
3. If short silence followed by a beep is detected → voicemail detected.
4. If conversational speech is detected → human answered.
5. The agent responds appropriately for each case.

## Detection logic

| Signal | Classification | Agent action |
| - | - | - |
| Greeting + pause + beep | Answering machine | Leave pre-recorded message |
| "Hello?" or conversational speech | Human | Start live conversation |
| Long silence | Unknown | Default to human behavior |

## Environment variables

```bash .env theme={null}
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxx
VOBIZ_SIP_DOMAIN=your-domain.sip.vobiz.ai
VOBIZ_USERNAME=your-username
VOBIZ_PASSWORD=your-password
OPENAI_API_KEY=sk-...
VOICEMAIL_MESSAGE_URL=https://your-server.com/voicemail.mp3
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.