> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# LiveKit all-features example

> A single LiveKit agent example demonstrating inbound, outbound, transfers, DTMF, answering machine detection, and webhooks together on Vobiz.

A single LiveKit agent that demonstrates all major Vobiz integration features - inbound calling, outbound dialing, call transfers, DTMF handling, and CRM webhooks - in one working example.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Livekit-Vobiz-All-feature-Example">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Livekit-Vobiz-All-feature-Example.git
cd Livekit-Vobiz-All-feature-Example
pip install -r requirements.txt
python agent.py dev
```

## Overview

This example combines all Vobiz + LiveKit capabilities into a single production-ready agent. Use it as a starting point when you want to build an agent that can handle complex call scenarios without switching between multiple codebases.

## Features

* **Inbound calling** - accept calls on your Vobiz number
* **Outbound dialing** - initiate calls programmatically
* **Department transfers** - route callers to Billing, Support, or Sales via SIP REFER
* **Escalation to human** - cold transfer to a human agent
* **DTMF detection** - respond to keypad inputs during the call
* **CRM webhooks** - stream events to your backend in real time

## Agent function tools

| Tool | Description |
| - | - |
| `transfer_to_billing` | Transfer the caller to the Billing department |
| `transfer_to_support` | Transfer the caller to Technical Support |
| `escalate_to_human` | Cold transfer to a human staff member |
| `record_intent` | Log intent to CRM mid-call |

## Environment variables

```bash .env theme={null}
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxx
VOBIZ_SIP_DOMAIN=your-domain.sip.vobiz.ai
VOBIZ_USERNAME=your-username
VOBIZ_PASSWORD=your-password
OPENAI_API_KEY=sk-...
BILLING_NUMBER=+919XXXXXXXXX
SUPPORT_NUMBER=+919XXXXXXXXX
HUMAN_AGENT_NUMBER=+919XXXXXXXXX
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.