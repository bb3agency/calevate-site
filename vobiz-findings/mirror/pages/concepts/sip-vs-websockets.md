> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP vs WebSockets

> Compare SIP and WebSocket architectures for connecting phone calls to AI voice agents - pick the right fit for latency, cost, and deployment speed.

These are the two fundamental architectures for connecting phone calls to AI voice agents. The choice is not about which is "better" - it depends entirely on what you are building, your platform choices, and your priorities between deployment speed and total ownership.

<CardGroup cols={2}>
  <Card title="SIP Trunking" icon="phone" href="/docs/concepts/sip-trunking">
    Telephony industry standard - robust, enterprise-ready, and mandatory when you need call transfer, PBX integration, or managed platforms like LiveKit, VAPI, and Retell AI.
  </Card>

  <Card title="WebSocket Streaming" icon="bolt" href="/docs/concepts/streaming-websockets">
    Developer-native path - highly cost-effective at scale, more direct, and ideal for custom AI pipelines built with Pipecat or bare-metal code.
  </Card>
</CardGroup>

## Architectural Comparison

The two approaches operate at completely different layers of the stack. SIP is a telephony-layer protocol. WebSocket streaming is an application-layer transport.

### SIP Trunking Path

<Steps>
  <Step title="PSTN">Caller dials phone number</Step>
  <Step title="SIP Trunk (Vobiz)">PSTN → SIP INVITE routed to endpoint URI</Step>
  <Step title="Platform SIP Endpoint">LiveKit / VAPI / Retell terminates SIP, creates room</Step>
  <Step title="RTP Audio">UDP audio stream directly to platform</Step>
  <Step title="AI Agent">Receives WebRTC audio, runs STT → LLM → TTS</Step>
  <Step title="RTP Audio (back)">TTS audio back to caller via UDP</Step>
</Steps>

### WebSocket Streaming Path

<Steps>
  <Step title="PSTN">Caller dials phone number</Step>
  <Step title="Vobiz Webhook">Fetches your webhook, receives VoiceXML stream directive</Step>
  <Step title="WebSocket (wss://)">Direct TCP connection established to your server</Step>
  <Step title="Your Server">Receives base64 µ-law audio directly from Vobiz</Step>
  <Step title="AI Pipeline">STT → LLM → TTS logic driven entirely by your code</Step>
  <Step title="WebSocket (back)">µ-law voice audio sent back over same socket connection</Step>
</Steps>

<Info>
  **Important architectural nuance:** These two architectures are not completely mutually exclusive. You can use a generic SIP Trunk provider to route a call to Vobiz, and then use a Vobiz VoiceXML `<Stream>` directive to pipe that exact call to your custom WebSocket server. SIP handles the initial routing; WebSocket handles the audio layer.
</Info>

## Full Decision Matrix

| Evaluation Factor | SIP Trunking | WebSocket Streaming |
| - | - | - |
| **Developer Profile** | Telephony admins, DevOps, or teams comfortable with SIP/RTP concepts | Python / Node.js engineers - WebSocket + async patterns are familiar |
| **Setup Complexity** | High - trunk config, IP ACLs, SIP URI routing, codec negotiation, firewall rules | Low/Medium - VoiceXML webhook + WebSocket server handling JSON |
| **Call Setup Latency** | 1–5 seconds (SIP INVITE handshake + PSTN routing overhead) | Near-instant (WebSocket TCP handshake + Vobiz webhook fetch) |
| **Audio Transport Latency** | Lower - UDP/RTP has no retransmission. Dropped packets are skipped, preserving real-time flow. | Slightly higher - TCP guarantees delivery. Retransmitted packets can add jitter on poor networks. |
| **Audio Quality Support** | G.711 8kHz or G.722 16kHz (HD wideband, if chosen carrier supports) | G.711 µ-law 8kHz (PSTN floor, same as standard SIP) |
| **Infrastructure Cost** | Vobiz trunk rate + AI platform fee (LiveKit/VAPI/Retell markup) | Vobiz channel rate + raw AI API costs only. No platform markup. |
| **Live Call Transfer** | Supported - blind and warm transfer via SIP REFER | Supported - Vobiz handles call transfer on the WebSocket path as well |
| **Enterprise PBX Integration** | Native - Avaya, Cisco UCM, Teams Direct Routing demand SIP | Not applicable - no standard bridge to existing PBX infra |
| **Turn-Taking / Interruption** | Abstracted - handled completely by the managed platform | Manual - you must build VAD + async pipeline cancellation |
| **Horizontal Scaling** | Carrier-layer - add trunk channels without touching server infra | Process-layer - you must scale WebSocket workers/containers |

## Platform Compatibility Matrix

| Platform | SIP Trunking | WebSocket Streaming | Role in Architecture |
| - | - | - | - |
| [LiveKit](/docs/integrations/livekit) | ✅ Primary | - | Complete AI voice platform. SIP trunk terminates into LiveKit SIP Service. AI agent runs as LiveKit participant. |
| [VAPI](/docs/integrations/vapi-dashboard) | ✅ Primary | - | Managed AI voice platform. BYO SIP trunk or direct SIP URI. PSTN calls route exclusively through SIP trunking. |
| [Retell AI](/docs/integrations/retellai-dashboard) | ✅ Primary | - | Managed AI voice platform. Elastic SIP trunk or Register Phone Call API (SIP URI dialing). |
| [ElevenLabs](/docs/integrations/elevenlabs-dashboard) | ✅ Primary | - | Conversational AI platform with native SIP integration. Connects directly to PSTN phone calls via SIP trunking. |
| [Pipecat](/docs/integrations/pipecat) | - | ✅ Primary | Open-source Python pipeline framework. Designed exclusively around WebSocket transport. No native SIP support. |
| [Direct Python (Vobiz)](/docs/integrations/websockets) | - | ✅ Primary | Bare-metal WebSocket handler against Vobiz streaming API. Maximum control, maximum ownership. |
| [Bolna](/docs/integrations/bolna) | Supported | ✅ Primary | Managed voice AI orchestration layer. Can integrate via WebSocket streams or via SIP trunk configuration. |
| [Ultravox](/docs/integrations/ultravox) | Supported | ✅ Primary | Real-time AI voice platform. Primary integration via WebSocket audio; SIP via intermediary transport. |

## Cost Analysis

The Vobiz channel rate is **identical for both paths** in spirit - the difference comes from whether you add a managed AI platform layer on top (SIP path) or own the pipeline yourself (WebSocket path). All pricing below is in INR.

### SIP Trunking Cost Stack

| Item | Cost | Notes |
| - | - | - |
| Vobiz SIP channel | ₹0.45/min | 45 paise per minute, inbound + outbound |
| Phone number (DID) | ₹500/month | Per active Vobiz number |
| Managed AI platform | Their pricing | LiveKit, VAPI, Retell, ElevenLabs each charge their own per-minute or subscription rate. **Main cost driver at scale.** |
| STT (e.g. Deepgram) | Included or API | VAPI/Retell include STT; LiveKit needs your own API key |
| LLM (e.g. GPT-4o) | API key required | Pass-through or bundled per-minute rate |
| TTS (e.g. ElevenLabs) | API key required | Per character or per minute |

**Vobiz base cost:** ₹0.45/min + ₹500/month per number. Total = Vobiz rate + AI platform fees + STT/LLM/TTS API costs.

### WebSocket Streaming Cost Stack

| Item | Cost | Notes |
| - | - | - |
| Vobiz channel rate | ₹0.65/min | 65 paise per minute, inbound + outbound |
| Phone number (DID) | ₹500/month | Same as SIP |
| **No managed AI platform** | ₹0 | You build the pipeline yourself. **This is the key saving.** |
| STT (e.g. Deepgram) | Direct API rate | Pay STT provider directly |
| LLM (e.g. GPT-4o-mini) | Direct API rate | Pay OpenAI / Anthropic / Google directly |
| TTS (e.g. Cartesia / ElevenLabs) | Direct API rate | Choose your TTS provider |
| Server compute | Cloud infra | One process per concurrent call |

**Vobiz WebSocket rate:** ₹0.65/min + ₹500/month per number. Total = Vobiz rate + direct AI API costs only. **No platform markup.**

<Tip>
  **The bottom line:** Under 50,000 calls/month, the platform premium is often worth the saved engineering time. Above 50,000 calls/month, owning the pipeline (WebSocket path) pays off significantly.
</Tip>

## Latency Analysis

**SIP has lower audio transport latency than WebSocket streaming.** SIP uses UDP/RTP - a fire-and-forget protocol that never retransmits dropped packets, keeping audio delivery strictly real-time. WebSocket runs over TCP, which guarantees delivery by retransmitting lost packets - useful for data, but a source of jitter for live audio on poor networks.

If latency is the only factor you care about, SIP wins. But latency is rarely why developers choose WebSocket streaming. They choose it for the **ecosystem** - direct access to AI frameworks (Pipecat), raw STT/LLM/TTS APIs, full pipeline control, and lower cost.

| Path | Vobiz Telephony Layer | Notes |
| - | - | - |
| Both paths | \< 50ms | Audio delivery from PSTN to your server |
| SIP | UDP/RTP | No retransmission; dropped packets skipped |
| WebSocket | TCP | Retransmissions add jitter on poor networks |

## When to Choose SIP

* You need to integrate with **enterprise PBX** (Avaya, Cisco UCM, Microsoft Teams Direct Routing)
* You're using a **managed AI platform** (LiveKit, VAPI, Retell, ElevenLabs)
* You need **maximum audio quality** (G.722 wideband)
* **Live call transfer** must work without custom code
* You want **carrier-layer scaling** (add trunk channels without touching infra)

## When to Choose WebSockets

* You're building a **custom AI pipeline** (Pipecat, direct Python, Node.js)
* You want **direct access** to STT/LLM/TTS APIs
* **Total cost** matters more than platform abstraction
* You want **full control** of the pipeline (interruption, VAD, turn-taking)
* You're comfortable scaling **WebSocket workers** yourself

## Migration Path

You don't have to commit to one architecture forever:

1. **Start with SIP + managed platform** for fastest time-to-market
2. **Validate product-market fit** with low engineering investment
3. **Migrate to WebSocket streaming** once volume justifies engineering ownership
4. Use Vobiz `<Stream>` directive to bridge: SIP trunk routes call → WebSocket pipes audio to your server


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.