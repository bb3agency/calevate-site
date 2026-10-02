> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Build an AI Voice Agent

> Connect leading conversational AI platforms - Vapi, Retell, ElevenLabs, Pipecat, LiveKit - directly to real phone numbers using Vobiz SIP trunking.

This guide walks through connecting leading conversational AI platforms directly to real phone numbers using Vobiz.

## Introduction

An AI Voice Agent is a conversational system that can listen, process speech, and reply with human-like audio over a telephone call. Pairing Vobiz's SIP and telecom infrastructure with providers like **Vapi**, **Retell AI**, or **ElevenLabs** lets you build powerful inbound customer support systems or outbound calling campaigns.

Vobiz routes telephone audio (RTP streams) to these AI providers out of the box using standard SIP or WebSocket connections - no manual WebRTC stream handling required.

## How it works

The architecture of an AI Voice Agent generally consists of three parts:

<Steps>
  <Step title="The Telecom Layer (Vobiz)">
    Provides the actual phone number (DID), handles the SIP trunking, and manages the lifecycle of the phone call.
  </Step>

  <Step title="The Interconnect">
    Vobiz forwards the call to your server or directly to an AI integration platform using a SIP URI or a Stream (WebSocket).
  </Step>

  <Step title="The AI Layer">
    The AI provider (Vapi, Retell, Pipecat, etc.) runs Speech-to-Text (STT), routes context to an LLM, generates text, and converts it back using Text-to-Speech (TTS).
  </Step>
</Steps>

## Prerequisites

Before setting up your first agent, ensure you have:

* A registered [Vobiz account](/docs/quick-start)
* An active phone number purchased in the Vobiz dashboard
* An account with your preferred AI Voice provider

## Choose your AI provider

Vobiz supports all major AI voice platforms. Select the one that fits your stack and follow the step-by-step integration guide.

<Columns cols={2}>
  <Card title="VAPI" icon="bolt" href="/docs/integrations/vapi-dashboard">
    Low-latency conversational AI via SIP.
  </Card>

  <Card title="Retell AI" icon="comments" href="/docs/integrations/retellai-dashboard">
    Natural-sounding AI phone conversations.
  </Card>

  <Card title="ElevenLabs" icon="microphone-lines" href="/docs/integrations/elevenlabs-dashboard">
    Ultra-realistic AI voice agents.
  </Card>

  <Card title="Pipecat" icon="python" href="/docs/integrations/pipecat">
    Open-source Python voice AI framework.
  </Card>
</Columns>

## All integrations

[View integrations page →](/docs/integrations)

<Columns cols={3}>
  <Card title="VAPI" icon="bolt" href="/docs/integrations/vapi-dashboard">
    Most popular
  </Card>

  <Card title="Retell AI" icon="comments" href="/docs/integrations/retellai-dashboard">
    Natural conversations
  </Card>

  <Card title="ElevenLabs" icon="microphone-lines" href="/docs/integrations/elevenlabs-dashboard">
    Realistic voices
  </Card>

  <Card title="LiveKit" icon="signal-stream" href="/docs/integrations/livekit">
    WebRTC + SIP
  </Card>

  <Card title="Pipecat" icon="python" href="/docs/integrations/pipecat">
    Open source
  </Card>

  <Card title="Bolna.ai" icon="circle-check" href="/docs/integrations/bolna">
    Production ready
  </Card>

  <Card title="Ultravox" icon="brain" href="/docs/integrations/ultravox">
    Multimodal AI
  </Card>
</Columns>

## What's next?

<Columns cols={2}>
  <Card title="Build an inbound voice agent" icon="phone-arrow-down-left" href="/docs/guides/ai-voice-agent/inbound">
    Step-by-step setup for receiving calls and routing them to your AI agent.
  </Card>

  <Card title="Build an outbound voice agent" icon="phone-arrow-up-right" href="/docs/guides/ai-voice-agent/outbound">
    Run automated outbound campaigns with AI agents over Vobiz trunks.
  </Card>

  <Card title="Migrating from Plivo?" icon="arrow-right-arrow-left" href="/docs/guides/plivo-to-vobiz">
    Move your existing Plivo voice app to Vobiz - near 1:1 API, with an interactive converter.
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.