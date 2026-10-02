> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is WebRTC? How It Works, APIs, Codecs & Voice AI (2026 Guide)

> WebRTC explained: how it works (getUserMedia, signaling, SDP, ICE/STUN/TURN, SRTP), the core APIs, codecs, WebRTC vs SIP, and WebRTC for voice AI.

*June 18, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

WebRTC (Web Real-Time Communication) is the technology that lets a browser or mobile app capture a microphone and camera and stream that audio and video directly to another peer, with no plugin, no download, and sub-second latency. It is the engine under video calls in your browser tab, click-to-call buttons on websites, and the new wave of voice AI agents that pick up a mic in the page instead of a phone line. If you are building real-time voice or video into software, WebRTC is where the call begins.

This guide goes well past the one-line definition: how a WebRTC connection is built step by step, the three core JavaScript APIs, the codecs it negotiates, how it punches through NATs and firewalls with ICE/STUN/TURN, where it differs from [SIP and WebSockets](/docs/concepts/sip-vs-websockets), the honest trade-offs (no phone network on its own), and what changes when WebRTC is carrying a voice AI agent that also needs to reach real phone numbers.

<Note>
  **Key takeaways**

  * **WebRTC** is an open standard for peer-to-peer real-time audio, video, and data directly between browsers and apps, no plugins required.
  * A connection = **capture media (`getUserMedia`) → exchange an SDP offer/answer over your own signaling channel → find a network path with ICE/STUN/TURN → stream encrypted media over SRTP.**
  * The three APIs that matter: **`RTCPeerConnection`** (the connection), **`MediaStream`** (the mic/camera tracks), and **`RTCDataChannel`** (arbitrary data).
  * WebRTC mandates encryption: media is always **SRTP**, key-exchanged over **DTLS**. There is no unencrypted mode.
  * WebRTC **does not reach the public phone network (PSTN) by itself** and needs a TURN relay when peer-to-peer fails, that is exactly the gap an infrastructure layer like [Vobiz](/docs/introduction) fills.
</Note>

## What is WebRTC?

[WebRTC is a free, open-source project and a set of W3C and IETF standards that give browsers and mobile applications real-time communication over simple APIs](https://webrtc.org/). The one distinction that matters: unlike older real-time stacks that needed a Flash plugin or a native SIP softphone, WebRTC ships *inside* the browser. Any modern browser (Chrome, Firefox, Safari, Edge) can capture a mic and camera and open an encrypted, low-latency media connection to another peer using nothing but JavaScript.

It is two things at once. To web developers it is a [JavaScript API surface defined by the W3C](https://www.w3.org/TR/webrtc/), most importantly `RTCPeerConnection`. To network engineers it is a [bundle of IETF protocols, RTP/SRTP for media, ICE for connectivity, DTLS for keying, SDP for negotiation, formalized in RFC 8825](https://www.rfc-editor.org/rfc/rfc8825). When people say "WebRTC," they usually mean both layers working together to move audio, video, or data peer-to-peer in real time.

## How WebRTC works (step by step)

A WebRTC session looks deceptively simple to the user, "click and you're talking", but underneath it runs a precise handshake. Here is the full sequence.

### 1. Capture media with getUserMedia

The browser asks the user for permission and grabs the microphone and/or camera through [`navigator.mediaDevices.getUserMedia()`](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), which returns a `MediaStream`. For a voice agent, this is just the mic. Those tracks are added to the connection and become what the other side will hear or see.

### 2. Create an RTCPeerConnection

Each peer creates an [`RTCPeerConnection`](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection), the object that manages the whole call: the media tracks, the encryption, the network path, and the codecs. You configure it with a list of ICE servers (the STUN/TURN servers it can use to find a route, more below).

### 3. Negotiate with an SDP offer and answer

The two peers have to agree on *what* they will send (codecs, resolutions, encryption parameters, media directions). They do this by exchanging a [Session Description Protocol (SDP)](https://www.rfc-editor.org/rfc/rfc8866) document. The caller generates an **offer** (`createOffer()`), the callee replies with an **answer** (`createAnswer()`), and each applies the other's description. SDP is plain text and lists every codec, fingerprint, and ICE candidate the peer supports.

### 4. Signaling, the part WebRTC leaves to you

Here is the most-missed point in every beginner's WebRTC project: **WebRTC does not define how the offer and answer get from one peer to the other.** That transport, called *signaling*, is your job. Most apps push SDP and ICE candidates over a [WebSocket](/docs/concepts/streaming-websockets), an HTTP endpoint, or a message broker. WebRTC handles the media; you build (or buy) the signaling channel that introduces the two peers.

### 5. NAT traversal with ICE, STUN, and TURN

Almost no device sits on a public IP, they live behind home routers, corporate firewalls, and carrier-grade NAT. To find a path between two such peers, WebRTC uses [Interactive Connectivity Establishment (ICE)](https://www.rfc-editor.org/rfc/rfc8445), which gathers candidate addresses and tests them until one works:

* **STUN (Session Traversal Utilities for NAT)** lets a peer discover its own public IP and port as seen from the internet, so two peers can try to connect directly. STUN is cheap and works for the majority of connections.
* **TURN (Traversal Using Relays around NAT)** is the fallback. When two peers genuinely cannot reach each other directly (symmetric NAT, strict firewalls), a [TURN](https://www.rfc-editor.org/rfc/rfc8656) server *relays* all the media between them. TURN works almost everywhere but costs bandwidth and adds a hop, so it is used only when STUN fails, typically a meaningful minority of real-world calls.

### 6. Secure the path: DTLS and SRTP

Once ICE picks a route, the peers run a **DTLS** handshake over it to exchange keys, then encrypt every media packet with [Secure Real-time Transport Protocol (SRTP)](https://www.rfc-editor.org/rfc/rfc3711). This is not optional, [WebRTC mandates that all media and data are encrypted](https://www.rfc-editor.org/rfc/rfc8825); there is no plaintext mode. The DTLS fingerprints exchanged in the SDP are what prevent a man-in-the-middle from hijacking the keying.

### 7. Stream media (and, optionally, data)

With a route found and keys exchanged, audio and video flow as SRTP-protected [RTP](https://www.rfc-editor.org/rfc/rfc3550) packets, peer-to-peer where possible, relayed through TURN where not. A jitter buffer on each side smooths out packet timing, and the connection continuously adapts bitrate to the available network. If the app also opened an `RTCDataChannel`, arbitrary messages (chat, game state, file chunks, agent control signals) ride the same encrypted transport.

## The core WebRTC APIs

For all the protocol machinery underneath, the developer-facing surface is small. Three objects do most of the work:

| API | What it does |
| - | - |
| [**`RTCPeerConnection`**](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection) | The heart of WebRTC. Manages the peer connection: SDP negotiation, ICE candidate gathering, encryption (DTLS/SRTP), codec selection, and the flow of media tracks. |
| [**`MediaStream`** / `getUserMedia`](https://developer.mozilla.org/en-US/docs/Web/API/MediaStream) | Represents the audio and video tracks captured from the user's mic and camera (or screen). These tracks are what you add to the connection to be sent. |
| [**`RTCDataChannel`**](https://developer.mozilla.org/en-US/docs/Web/API/RTCDataChannel) | A bidirectional channel for arbitrary data over the same encrypted transport, used for chat, file transfer, telemetry, or control messages alongside the call. It runs over SCTP and can be configured reliable or unreliable, ordered or unordered. |

A minimal voice call is roughly: `getUserMedia()` for the mic → add the track to a `new RTCPeerConnection()` → `createOffer()` / `createAnswer()` → trade SDP and ICE candidates over your signaling channel → media flows. Everything else (NAT traversal, encryption, retransmission) the browser handles for you.

## WebRTC codecs

WebRTC peers negotiate codecs in the SDP and pick the best one both sides support. The browser ships a mandatory set so interoperability is guaranteed.

| Type | Codec | Notes |
| - | - | - |
| **Audio** | [**Opus**](https://www.rfc-editor.org/rfc/rfc6716) | The default and the one that matters for voice. Adaptive **6–510 kbps**, wideband/full-band, built-in noise and packet-loss handling. Mandatory in WebRTC. |
| **Audio** | **G.711 (PCMU/PCMA)** | 64 kbps, narrowband. Mandatory for interop, mainly used when bridging to the legacy phone network. |
| **Video** | **VP8** | Royalty-free, mandatory to implement. The classic WebRTC baseline. |
| **Video** | **H.264** | Mandatory to implement; widely hardware-accelerated; needed for interop with many SIP/telecom systems. |
| **Video** | **VP9** | Better compression than VP8, supports scalable (SVC) encoding. |
| **Video** | **AV1** | Newest, best compression, increasingly supported, heavier to encode. |

For voice and especially [voice AI](/docs/blogs/what-is-a-voice-api), **Opus is the codec to care about**, its wideband, adaptive audio gives speech-to-text far more signal than the 8 kHz G.711 ceiling, and it degrades gracefully under packet loss.

## WebRTC vs SIP and WebSockets

These three get conflated, but they solve different problems and often work together.

| | WebRTC | SIP | WebSockets |
| - | - | - | - |
| **What it is** | Browser/app media engine (audio, video, data) | Signaling protocol to set up calls | Persistent two-way browser↔server channel |
| **Carries media?** | Yes (SRTP) | No (signals only; media is RTP) | Not natively (carries any bytes you frame) |
| **Reaches the PSTN?** | Not by itself | Yes, the telecom standard | No |
| **Encryption** | Mandatory (DTLS/SRTP) | Optional (TLS + SRTP) | Optional (WSS/TLS) |
| **Typical use** | In-browser/in-app calling | Trunking, carrier interconnect | Streaming audio frames to a server pipeline |

In practice they combine. A common voice-AI architecture: a browser uses **WebRTC** to capture the mic and stream it, a server bridges that into a **SIP** trunk to reach a phone number, and a separate **[WebSocket](/docs/concepts/streaming-websockets)** streams raw audio into the STT → LLM → TTS pipeline. WebRTC is for the *edge* (browser/app), SIP is for the *phone network*, and WebSockets are for *server-side media transport*. For a deeper treatment of the last two, see [SIP vs WebSockets](/docs/concepts/sip-vs-websockets) and the [audio streaming](/docs/audio-streams) docs.

## WebRTC for voice AI

Voice AI is pulling WebRTC into the foreground because the most natural place for many agents to live is *in the browser or app the user is already in*, no phone call required. A support widget, an in-app assistant, or a web demo can capture the mic with `getUserMedia` and stream it straight to the agent's pipeline. What matters here is different from a classic video call:

* **Latency budget.** A natural conversational turn has to fit under roughly one second across capture + transport + STT + LLM + TTS. WebRTC's peer-to-peer media and tight jitter buffers help, but every extra hop (and every TURN relay) eats into that budget.
* **Audio fidelity.** Opus at wideband/24 kHz gives the speech model more to work with than narrowband telephony audio, which directly improves recognition accuracy.
* **Barge-in.** A real conversation lets the human interrupt. That requires genuinely [bidirectional, streaming media](/docs/audio-streams), not record-then-respond.
* **The PSTN bridge.** Most agents also need to take or place real phone calls. WebRTC handles the web edge; reaching a phone number still requires a [SIP trunk](/docs/platform/sip/overview) or [Voice API](/docs/platform/voice/overview) behind it. The web mic and the phone line have to meet in the middle.

This is why "WebRTC vs telephony" is a false choice for AI builders, you usually need both, bridged: WebRTC for the app, a carrier path for the phone.

### The honest trade-offs

WebRTC is powerful, but it is not magic, and a production deployment runs into real limits:

* **No PSTN on its own.** WebRTC connects browsers and apps to each other. It cannot dial a phone number without a media server or [SIP](/docs/blogs/what-is-sip) gateway bridging it to the carrier network.
* **TURN costs real money.** When peer-to-peer fails, all media relays through your TURN servers, that is bandwidth you pay for, and a hop that adds latency. At scale, TURN is a genuine infrastructure line item, not a footnote.
* **Signaling is your problem.** WebRTC deliberately leaves signaling undefined. You have to build and operate a reliable channel to exchange SDP and ICE candidates, and keep it up.
* **NAT and firewall variability.** ICE handles most networks, but strict corporate firewalls and symmetric NAT can still force relays or, rarely, fail, which is why a well-provisioned TURN fleet matters.
* **Server-side scaling.** Pure peer-to-peer breaks down beyond a couple of participants or when you need recording, transcription, or an AI pipeline in the path, that calls for a media server (SFU/MCU) or a streaming bridge.

## How Vobiz handles WebRTC

[Vobiz](/docs/introduction) is the **telephony infrastructure layer** under voice AI, it does not build the agent; it powers the agents you build (Vapi, Retell, ElevenLabs, Pipecat, LiveKit, and more). For WebRTC specifically, that means handling the parts WebRTC leaves to you and bridging the web edge to the phone network:

* **WebRTC across web, iOS, and Android with live PSTN.** Vobiz supports [WebRTC application setup](/docs/integrations/webrtc-application-setup) on browser and mobile, and bridges those sessions to real phone numbers, so a mic in a web page can talk to (or as) a phone call.
* **The PSTN bridge built in.** Reach the phone network through Vobiz [SIP trunking](/docs/platform/sip/overview) and the [Voice API](/docs/platform/voice/overview), DID provisioning in **130+ countries** and outbound connectivity to **190+**, so your WebRTC edge connects to actual numbers.
* **AI media controls.** Bidirectional [WebSocket audio streaming](/docs/concepts/streaming-websockets) with barge-in, inbound L16 at 8 or 16 kHz, and outbound L16 playback at up to 24 kHz, connected to your STT → LLM → TTS loop through [`<Stream>`](/docs/xml/stream) or the [Audio Streams API](/docs/audio-streams).
* **Built for the latency budget.** Sub-80 ms single-hop, event-driven telephony with direct carrier connect (vs 300–400 ms on legacy CPaaS), so the transport leg of the conversation stays small.
* **Secure by default.** SRTP media encryption and TLS 1.3 signaling, matching WebRTC's own mandatory-encryption posture end to end.
* **It powers your stack, not a locked-in agent.** Voice-AI builders like **Bolna**, fintechs like **Razorpay** and **Acko**, and enterprises like **KPMG** run on Vobiz infrastructure, you keep your agent; Vobiz provides the rails.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What does WebRTC stand for?">
    WebRTC stands for Web Real-Time Communication. It is an open standard (W3C APIs plus IETF protocols) that lets browsers and mobile apps stream audio, video, and data peer-to-peer in real time without plugins.
  </Accordion>

  <Accordion title="Is WebRTC peer-to-peer?">
    By design, yes, media flows directly between peers whenever the network allows it. When two peers cannot reach each other directly (strict NAT or firewalls), a TURN server relays the media instead. Setup (signaling) always goes through a server you provide.
  </Accordion>

  <Accordion title="What is the difference between WebRTC and SIP?">
    WebRTC is a browser/app media engine that carries the actual audio and video (over SRTP). SIP is a signaling protocol that sets up calls and is the standard for reaching the public phone network. WebRTC alone cannot dial a phone number; it is often bridged to SIP to do so.
  </Accordion>

  <Accordion title="Do I need STUN and TURN servers for WebRTC?">
    Almost always. STUN helps peers discover their public address for a direct connection and is needed for most calls. TURN is the relay fallback for when a direct path is impossible, and you pay for its bandwidth. Production WebRTC needs both configured.
  </Accordion>

  <Accordion title="Can WebRTC make phone calls?">
    Not on its own, WebRTC connects browsers and apps, not the phone network. To call a real number you bridge WebRTC to a SIP trunk or Voice API, which is what an infrastructure layer like Vobiz provides alongside WebRTC support on web, iOS, and Android.
  </Accordion>

  <Accordion title="Is WebRTC encrypted?">
    Yes, always. WebRTC mandates encryption: media uses SRTP with keys exchanged over a DTLS handshake, and there is no unencrypted mode. The DTLS fingerprints in the SDP protect the keying from man-in-the-middle attacks.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [What is VoIP?](/docs/blogs/what-is-voip) · [What is SIP?](/docs/blogs/what-is-sip) · [What is a Voice API?](/docs/blogs/what-is-a-voice-api)
* [SIP vs WebSockets](/docs/concepts/sip-vs-websockets) · [Streaming over WebSockets](/docs/concepts/streaming-websockets) · [Audio streaming](/docs/audio-streams)
* [WebRTC application setup](/docs/integrations/webrtc-application-setup) · [`<Stream>` element](/docs/xml/stream) · [Voice platform overview](/docs/platform/voice/overview)

## Sources

* W3C, ["WebRTC: Real-Time Communication in Browsers"](https://www.w3.org/TR/webrtc/).
* WebRTC project, ["Real-time communication for the web"](https://webrtc.org/).
* MDN Web Docs, ["WebRTC API"](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API).
* IETF, ["Overview: Real-Time Protocols for Browser-Based Applications" (RFC 8825)](https://www.rfc-editor.org/rfc/rfc8825).
* IETF, ["Interactive Connectivity Establishment (ICE)" (RFC 8445)](https://www.rfc-editor.org/rfc/rfc8445).
* IETF, ["The Secure Real-time Transport Protocol (SRTP)" (RFC 3711)](https://www.rfc-editor.org/rfc/rfc3711).
* IETF, ["Definition of the Opus Audio Codec" (RFC 6716)](https://www.rfc-editor.org/rfc/rfc6716).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and bridge your WebRTC app to the phone network in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.