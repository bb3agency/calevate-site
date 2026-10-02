> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Platform Concepts – SIP, WebSocket & Voice API Architecture

> Master core Vobiz telephony concepts - SIP signaling, RTP media, WebSocket streaming, callbacks, and when to choose SIP vs WebSockets for AI voice agents.

<Info>
  **What you'll learn**

  * How SIP signaling and RTP media work - the full protocol mechanics, not just the surface
  * How Voice XML WebSocket streaming connects phone calls directly to your AI pipeline
  * When to choose SIP (LiveKit, VAPI, Retell, call transfer) vs. WebSockets (Pipecat, direct Python, cost optimization)
  * How callbacks and webhooks enable real-time event notifications for call lifecycle events
  * Configuration patterns for callback URLs, authentication, and hierarchy
</Info>

## Available Concepts

<CardGroup cols={2}>
  <Card title="SIP Trunking" icon="phone" href="/docs/concepts/sip-trunking">
    How SIP actually works - the full INVITE→RTP message flow, signaling vs. media separation, codec negotiation, and how LiveKit, VAPI, Retell AI, and ElevenLabs each use SIP. Includes 10 real developer pitfalls.
  </Card>

  <Card title="Streaming WebSockets" icon="bolt" href="/docs/concepts/streaming-websockets">
    How Voice XML audio streaming works - WebSocket message types, G.711 µ-law encoding, the full audio conversion pipeline, Pipecat architecture, and direct Python integration with Vobiz.
  </Card>

  <Card title="SIP vs WebSockets" icon="scale-balanced" href="/docs/concepts/sip-vs-websockets">
    The definitive comparison - full decision matrix (10 factors), platform compatibility table, real cost numbers, latency breakdown, scaling trade-offs, and a 4-question decision flowchart.
  </Card>

  <Card title="Callbacks" icon="file-lines" href="/docs/concepts/callbacks">
    Understand how callbacks and webhooks work in Vobiz. Learn about callback URLs, event notifications, and real-time communication patterns.
  </Card>

  <Card title="Callback Configurations" icon="gear" href="/docs/concepts/callback-configurations">
    Configure callback endpoints for your applications. Set up URL endpoints, handle authentication, and manage callback parameters.
  </Card>

  <Card title="IP Whitelisting" icon="shield-halved" href="/docs/concepts/ip-whitelisting">
    Whitelist Vobiz IP addresses on your firewall to ensure uninterrupted SIP signaling, RTP media, and callback delivery.
  </Card>

  <Card title="Hangup Causes" icon="phone-slash" href="/docs/concepts/hangup-causes">
    Decode every Vobiz hangup code, source, and SIP cause from your call logs - with the exact next step to troubleshoot each disconnect reason.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.