> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Agent-to-agent handoff

> Transfer an active Vobiz call from one LiveKit AI agent to a specialized agent mid-conversation while preserving full conversation context and history.

Transfer an active call from one LiveKit AI agent to another specialized agent mid-conversation - without dropping the call.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-Livekit-Agent-to-Agent-Handoff-Example">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Livekit-Agent-to-Agent-Handoff-Example.git
cd Vobiz-Livekit-Agent-to-Agent-Handoff-Example
pip install -r requirements.txt
python agent.py dev
```

## Overview

A front-line agent handles the initial greeting and intent detection. When the caller needs specialized help (billing, support, etc.), the front-line agent passes control to a specialist agent. The handoff is seamless - the caller stays in the same room and hears no interruption.

## How it works

1. The **reception agent** greets the caller and determines their intent.
2. Based on intent, the agent calls `pass_control_to_billing` or a similar tool.
3. The reception agent leaves the room.
4. The **specialist agent** joins the same room and takes over the conversation.
5. The specialist receives context from the handoff payload.

## Agent function tools

| Tool | Description |
| - | - |
| `pass_control_to_billing` | Hand off to the Billing department specialist |
| `pass_control_to_support` | Hand off to the Technical Support specialist |
| `pass_control_to_sales` | Hand off to the Sales specialist |

## Environment variables

```bash .env theme={null}
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxx
OPENAI_API_KEY=sk-...
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.