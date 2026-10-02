> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP Trunking

> SIP is the signaling standard behind nearly every modern phone call. Learn how SIP trunking on Vobiz powers AI voice agents and PBX integrations.

For Voice AI developers, SIP is the **vital bridge between the global telephone network (PSTN)** and modern application infrastructure. It translates standard phone calls into digital streams your AI agents can interact with.

<Warning>
  **The Golden Rule of Telephony:** SIP is a *signaling protocol only*. It handles call routing and setup, but carries absolutely **zero audio**. The actual voice data travels completely separately over **RTP (Real-time Transport Protocol)**. Grasping this split is critical.
</Warning>

## How SIP works

SIP operates similarly to HTTP, using text-based requests and responses to negotiate settings like audio codecs via SDP (Session Description Protocol). It typically runs over UDP for speed, but supports TCP and TLS for secure, reliable signaling.

### Signaling vs. Media (RTP)

<CardGroup cols={2}>
  <Card title="SIP: The Signaling Layer" icon="globe">
    * Runs via UDP, TCP, or TLS
    * Text-based messages (like HTTP)
    * Negotiates codecs and ports
    * Handles ringing, answering, hanging up
    * Zero audio bytes ever pass through SIP
  </Card>

  <Card title="RTP: The Media Layer" icon="tower-broadcast">
    * Always runs over UDP (prioritizes speed)
    * Binary packets, 20ms audio frames
    * Carries G.711 µ-law or G.722 audio
    * Direct path between endpoints
    * Fully distinct from SIP servers
  </Card>
</CardGroup>

<Note>
  When you hit the classic "one-way audio" bug during testing, SIP negotiation succeeded flawlessly. The isolated failure is in the RTP path, likely blocked by symmetric NAT or restrictive UDP firewall rules.
</Note>

### The SIP handshake flow

```text SIP Packet Timeline theme={null}
PSTN CALLER                           YOUR ENDPOINT
Caller   ─── INVITE (SDP offer) ───▶  Endpoint
Caller   ◀── 100 Trying ────────────  Endpoint
Caller   ◀── 180 Ringing ───────────  Endpoint
Caller   ◀── 200 OK (SDP answer) ───  Endpoint
Caller   ─── ACK ───────────────────▶ Endpoint

Caller   ◀══ RTP AUDIO STREAM (UDP) ══▶ Endpoint

Caller   ─── BYE ───────────────────▶ Endpoint
Caller   ◀── 200 OK ────────────────  Endpoint
```

## SIP trunking for voice AI

A **SIP Trunk** is a virtual phone line that connects your infrastructure directly to a carrier like Vobiz. When someone dials your number, Vobiz sends a SIP INVITE to your platform - LiveKit, Vapi, or your own server.

**Call routing path:**

<Steps>
  <Step title="PSTN">
    Caller dials your number
  </Step>

  <Step title="Vobiz">
    Authenticates the call and forwards the INVITE to your SIP URI
  </Step>

  <Step title="Platform">
    LiveKit / Vapi answers and negotiates the codec
  </Step>

  <Step title="AI Agent">
    RTP audio flows to your STT → LLM → TTS pipeline
  </Step>
</Steps>

## Advantages

* **Universal Access** - It is the absolute global standard for telephony.
* **Native Transfer Support** - Includes REFER techniques allowing invisible, live human agent hand-offs.
* **Enterprise PBX integration** - Plugs directly into corporate PBX systems - Asterisk, FreeSWITCH, Teams, Cisco.
* **G.722 wideband audio** - Gives you 16 kHz instead of 8 kHz - doubles speech recognition accuracy in noisy environments.

## Disadvantages

* **Connection setup delay** - SIP handshakes add \~1 second before audio starts. Not ideal for sub-second latency requirements.
* **Firewall configuration** - RTP uses random UDP ports (typically 10000–20000). Your firewall must allow that range outbound.
* **AI barge-in complexity** - SIP wasn't designed for streaming tokens or mid-sentence interruptions - you may need middleware to bridge them.
* **Silent failures** - Misconfigured ACLs or URI routes fail quietly - calls just drop with no error log. Test end-to-end before production.

## Platform compatibility

### LiveKit - primary SIP hub

LiveKit runs a dedicated SIP service that ingests trunks cleanly and exposes callers as standard SIP participants in your WebRTC rooms. It preserves native encryption, Krisp noise filtering, and call transfer support.

[View Implementation](/docs/integrations/livekit)

### VAPI - unified telephony

VAPI exposes unified SIP destinations that accept bring-your-own trunks. It supports custom SIP headers, enabling dynamic AI context injection from CRM lookups directly from the incoming INVITE.

[View Implementation](/docs/integrations/vapi-dashboard)

### Retell AI - elastic integration

Retell AI supports two connection paths: direct bridging from Vobiz, or dynamic API registration hooks that give you fine-grained control over application flow before SIP connectivity is established.

[View Implementation](/docs/integrations/retellai-dashboard)

### ElevenLabs - native SIP integration

ElevenLabs Conversational AI connects directly to PSTN phone calls via SIP trunking - no intermediary platform required. Point a Vobiz SIP trunk at ElevenLabs' SIP endpoint and inbound calls are answered directly by an ElevenLabs AI agent. ElevenLabs also provides standalone TTS, STT, and voice cloning services that other SIP-based pipelines (LiveKit agents, etc.) can consume as a voice synthesis layer.

[View Implementation](/docs/integrations/elevenlabs-dashboard)

## Common Developer Pitfalls

<Warning>
  **01. Wrong username in SIP credentials**

  Your Vobiz dashboard display name is not your SIP username. Use the credential username you created in the Trunks section - anything else returns 401.
</Warning>

<Warning>
  **02. Do not hardcode platform IPs**

  SaaS AI platforms (Vapi, LiveKit) rotate egress IPs. Hardcoding them in your firewall ACL will cause silent disconnections. Use hostname-based rules instead.
</Warning>

<Warning>
  **03. One-way audio = blocked UDP**

  If the call connects but audio only flows one way, SIP signaling worked - the problem is your firewall blocking RTP (UDP). Open ports 10000–20000.
</Warning>

<Warning>
  **04. International calls return 403**

  International dialing is off by default. Enable it in the console under your account settings before calling international numbers.
</Warning>

## When to choose SIP

<CardGroup cols={3}>
  <Card title="LiveKit / Vapi / Retell integration" icon="display" />

  <Card title="Live call transfers to a human agent" icon="phone" />

  <Card title="Enterprise PBX (Asterisk, Cisco)" icon="globe" />

  <Card title="Regulated environments (HIPAA, PCI)" icon="microchip" />

  <Card title="Standard PSTN phone numbers required" icon="bolt" />

  <Card title="High call volume at scale" icon="circle-check" />
</CardGroup>

<Tip>
  **Want to skip SIP entirely?** If you want to route audio directly from your app without a phone number, [WebSocket streaming](/docs/concepts/streaming-websockets) is simpler and lower latency for server-side pipelines.
</Tip>

## What developers usually do next

<CardGroup cols={2}>
  <Card title="Create your first SIP trunk" icon="bolt" href="/docs/quick-start">
    Step-by-step console walkthrough - outbound + inbound (5 min)
  </Card>

  <Card title="Connect Vapi" icon="plug" href="/docs/integrations/vapi-dashboard">
    Route SIP directly into a Vapi AI agent (3 min)
  </Card>

  <Card title="WebSocket streaming" icon="bolt" href="/docs/concepts/streaming-websockets">
    Skip SIP - stream audio directly from your server (10 min read)
  </Card>

  <Card title="SIP vs WebSockets" icon="scale-balanced" href="/docs/concepts/sip-vs-websockets">
    Full decision matrix - 10 factors, real latency numbers (10 min read)
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.