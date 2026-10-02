> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is VoIP? How It Works, Types, Costs & Setup (2026 Guide)

> VoIP turns phone calls into internet data. How it works (codecs, SIP, RTP), the types of VoIP, equipment, bandwidth, call quality, costs, and setup.

*June 10, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

VoIP is how the overwhelming majority of phone calls travel today, as data over the internet, not as electrical current down a copper wire. It's the layer under softphones, cloud contact centres, WhatsApp calls, and the voice AI agents now answering real phone numbers. If you're choosing a phone system or wiring calls into software, understanding VoIP is the starting point.

This guide goes well past the dictionary definition: how a VoIP call is built packet by packet, the codecs and bandwidth involved, the components of a VoIP network, the five types of VoIP, the equipment you need, how to keep call quality high, what it costs, and how to choose a provider, with a specific lens on what matters when VoIP carries a voice AI agent.

<Note>
  **Key takeaways**

  * **VoIP (Voice over Internet Protocol)** carries voice as data packets over IP networks instead of the circuit-switched phone network.
  * A call = **digitize → encode with a codec → packetize → signal with [SIP](/docs/blogs/what-is-sip) → stream media over RTP/SRTP → reassemble.**
  * A standard **G.711** call uses \~**85–90 kbps** per direction; **Opus** scales from **6 to 510 kbps** and adapts to the network.
  * There are \~**5 types** of VoIP (ATA, softphone, mobile, cloud PBX, programmable/API). For voice AI, the ones that matter are programmable + low-latency.
  * VoIP's weak points (jitter, power/internet dependency, security, E911) are real but solvable with the right network.
</Note>

## What is VoIP?

[Voice over Internet Protocol (VoIP) is a set of technologies for voice communication over Internet Protocol (IP) networks](https://en.wikipedia.org/wiki/Voice_over_IP). The one distinction that matters: the legacy telephone network is **circuit-switched**, it opens a dedicated path for the whole call, while VoIP is **packet-switched**, breaking your voice into small packets that share the network with all other internet traffic. That single change is why VoIP is cheap, global, and programmable, and also why call quality depends on the network underneath.

## How VoIP works (step by step)

1. **Digitization.** Your analog voice is sampled (typically 8,000 times a second, 8 kHz, for telephony) and turned into digital values.
2. **Encoding with a codec.** A codec compresses that audio. The two you'll meet most:
   * **G.711**, the PSTN-grade codec, \~**64 kbps** of audio (≈85–90 kbps with IP/UDP/RTP overhead). Pristine but heavy.
   * **Opus**, modern, [adaptive from **6 to 510 kbps**](https://en.wikipedia.org/wiki/Voice_over_IP) with built-in noise and echo handling; the default for AI-grade audio.
3. **Signaling (SIP).** The call is set up by the [Session Initiation Protocol (SIP)](https://www.rfc-editor.org/rfc/rfc3261). SIP messages (`INVITE`, `200 OK`, `BYE`) run over [ports 5060 (unencrypted) or 5061 (TLS)](https://en.wikipedia.org/wiki/Session_Initiation_Protocol).
4. **Media (RTP/SRTP).** SIP carries no audio; once the call connects, the voice streams over **RTP**, or **SRTP** when encrypted.
5. **Jitter buffer & playback.** The receiver buffers packets to smooth out jitter, reorders them, decodes, and plays them back as sound.

The catch: because the network is best-effort, [latency, jitter, and packet loss can degrade quality](https://en.wikipedia.org/wiki/Voice_over_IP) if the path is poor, which is why the *provider's* routing and codec choices matter as much as your internet speed.

## How much bandwidth does VoIP use?

A single VoIP call is light by modern standards:

| Codec | Audio bitrate | Per call (with overhead) |
| - | - | - |
| **G.711** | 64 kbps | \~85–90 kbps each way |
| **G.729** | 8 kbps | \~30 kbps each way |
| **Opus** | 6–510 kbps (adaptive) | \~30–40 kbps typical |

As a rule of thumb, budget **\~100 kbps per concurrent call** for a clean G.711 call, less with Opus. The bigger driver of *quality* isn't raw bandwidth, it's **latency and jitter**, which is where provider network design wins or loses.

## Components of a VoIP network

A working VoIP deployment is more than "the internet." The pieces:

* **VoIP endpoints**, IP phones and softphones (apps) that originate and receive calls.
* **An IP-PBX or call-control server**, routes calls internally and connects to the outside world (or a cloud platform that does this for you).
* **Network hardware**, routers and switches that should prioritize voice traffic (QoS).
* **A Session Border Controller (SBC)**, at the edge for security, NAT traversal, and trunk control.
* **A connection to the PSTN**, a [SIP trunk](/docs/concepts/sip-trunking) or [Voice API](/docs/blogs/what-is-a-voice-api) that reaches real phone numbers.

With a cloud platform like Vobiz, most of this is managed, you bring endpoints and an app, and the [SIP trunking](/docs/platform/sip/overview) and SBC layers are handled for you.

## The 5 types of VoIP

1. **ATA / adapter-based.** A small box (an Analog Telephone Adapter) that plugs a legacy analog phone into VoIP, the cheapest way to keep familiar handsets.
2. **Softphone.** An app on a laptop or desktop (a headset plus software), popular for remote teams.
3. **Mobile VoIP.** Calling apps on a smartphone over Wi-Fi or data.
4. **Cloud PBX / business VoIP.** A hosted phone system for an organization, extensions, [IVR](/docs/solutions/cloud-ivr), voicemail, and [recording](/docs/solutions/call-recording).
5. **Programmable / API VoIP.** Voice built *into your own software* via APIs and [VobizXML](/docs/xml/overview/how-it-works). This is the category that powers contact centres, campaigns, and **voice AI agents**, and it's where Vobiz lives.

## What equipment do you need to set up VoIP?

* **A stable internet connection** (\~100 kbps of headroom per concurrent call).
* **An endpoint**, an IP phone, a softphone app, an ATA for legacy handsets, or, for programmable VoIP, just your application and an API key.
* **A provider**, a [SIP trunk](/docs/platform/sip/overview), a cloud PBX, or a [Voice API](/docs/blogs/what-is-a-voice-api).
* **(For production)** a Session Border Controller and encryption (SRTP/TLS) to secure trunks and block toll fraud.

With programmable VoIP, "setup" collapses to provisioning a [number](/docs/account-phone-number/purchase-from-inventory) and pointing a webhook at your app, minutes, not weeks.

## VoIP call quality and QoS

Because voice rides a shared network, quality depends on three things: **latency** (delay), **jitter** (variation in packet arrival), and **packet loss**. To keep calls crisp:

* **Apply Quality of Service (QoS)** on your network so voice packets get priority over bulk data.
* **Use wideband codecs (Opus)** where possible for HD audio.
* **Choose a low-latency provider**, a single-hop, direct-carrier path beats public-internet routing. (Vobiz runs sub-80 ms single-hop vs the 300–400 ms many legacy platforms hit.)
* **Monitor**, watch MOS, jitter, and loss in your [call logs](/docs/platform/voice/call-logs).

## VoIP vs landline (PSTN)

| | Landline (PSTN) | VoIP |
| - | - | - |
| **Network** | Circuit-switched | Packet-switched (IP) |
| **Cost** | Per-line, distance-sensitive | Low, distance-agnostic |
| **Setup time** | Days–weeks, on-site | Minutes, self-serve |
| **Mobility** | Fixed location | Any device, anywhere |
| **Scaling** | Add physical lines | Provision in software |
| **Number types** | Local only | Local, mobile, toll-free, global |
| **Programmability** | None | Routing, IVR, recording, streaming via API |
| **HD audio** | No (8 kHz) | Yes (wideband / 24 kHz with Opus) |
| **Analytics** | None | Recording, transcription, call analytics |
| **Power outage** | Works (line-powered) | Needs power + internet |
| **Emergency (E911)** | Precise location | Location must be registered |

## Advantages of VoIP

* **Lower cost**, [one shared network for voice and data slashes communication costs](https://en.wikipedia.org/wiki/Voice_over_IP).
* **Global reach**, numbers and routing anywhere, no distance premium.
* **Programmability**, embed calling in apps; add [IVR](/docs/solutions/cloud-ivr), [recording](/docs/xml/record), [transfer](/docs/solutions/call-transfer), and real-time [streaming](/docs/audio-streams).
* **HD audio**, wideband codecs beat the 8 kHz landline ceiling, which also helps speech recognition.
* **Elastic scaling**, add capacity in software for spiky or seasonal traffic.
* **Feature-rich**, voicemail, conferencing, analytics, and more, all in software.

## Disadvantages of VoIP (and how they're solved)

* **Power + internet dependency.** Unlike a line-powered landline, VoIP needs both. *Mitigation:* UPS, failover internet, mobile fallback.
* **Latency & jitter.** Packets can arrive late or out of order, causing lag or choppiness. *Mitigation:* low-latency carrier routing, a jitter buffer, and **QoS** to prioritize voice, the difference between a 300 ms legacy path and a sub-80 ms one.
* **Security.** An unprotected trunk on the internet is exposed to toll fraud and eavesdropping. *Mitigation:* encrypt signaling and media (TLS + SRTP), put an SBC in front, and use [IP access control lists](/docs/platform/sip/ip-access-control-list).
* **Emergency-call location.** VoIP numbers aren't tied to a physical exchange, so E911/emergency location must be registered. *Mitigation:* register service addresses; use the local emergency framework.

## VoIP, SIP, and SIP trunking, how they relate

These terms get used interchangeably but aren't the same. **VoIP** is the broad category (voice over IP). **[SIP](/docs/blogs/what-is-sip)** is the signaling protocol most VoIP uses to set up calls. A **[SIP trunk](/docs/blogs/what-is-sip-trunking)** is one productized VoIP service: the connection that links your phone system or app to the public telephone network. Some VoIP also uses [WebRTC and WebSocket streaming](/docs/concepts/sip-vs-websockets) instead of SIP, for example, browser-based calling. For the full comparison, see [SIP vs VoIP](/docs/blogs/sip-vs-voip).

## How much does VoIP cost?

VoIP pricing is usually **per-minute** or **per-seat**, far below legacy per-line plus long-distance models. The exact number depends on destination, volume, and features, and many providers price in USD with asymmetric inbound/outbound rates. [Vobiz](/docs/introduction) keeps it flat and INR-native: **₹0.65/min (65 paise) for both inbound and outbound**, with enterprise pricing above \~50,000 minutes a month. Compared with a traditional PRI (per-circuit fees, long-distance charges, and on-site maintenance), VoIP's pay-as-you-go model is dramatically cheaper to start and scale.

## VoIP use cases

* **Cloud contact centres**, route, queue, record, and analyze at scale.
* **Remote and distributed teams**, softphones and mobile apps replace desk lines.
* **Click-to-call in apps and websites**, via [WebRTC](/docs/integrations/webrtc-application-setup).
* **Voice AI agents**, connect Vapi/Retell/ElevenLabs/Pipecat to real numbers over [SIP or WebSocket](/docs/integrations).
* **Notifications, OTP, and reminders**, programmable [outbound calls](/docs/solutions/automated-outbound-calling).

## VoIP for voice AI, what actually matters

When VoIP carries a voice AI agent, the priorities shift from "cheap minutes" to **conversation quality in real time**:

* **Latency budget.** A natural turn has to fit under \~1 second across telephony + STT + LLM + TTS. Legacy VoIP at 300–400 ms eats that budget before the model runs.
* **Audio fidelity.** 24 kHz wideband audio (Opus) gives speech-to-text more signal than the 8 kHz norm.
* **Barge-in & streaming.** The caller has to be able to interrupt; that needs bidirectional [audio streaming](/docs/audio-streams), not record-then-process.

## How Vobiz delivers VoIP

[Vobiz](/docs/introduction) is VoIP infrastructure **built for voice AI, not retrofitted from a BPO-era stack**:

* **Sub-80 ms latency** on a single-hop, event-driven architecture with direct carrier connect (vs 300–400 ms legacy).
* **AI media controls**, with bidirectional [audio streaming](/docs/audio-streams), barge-in, and outbound L16 playback at up to 24 kHz.
* **Instant eKYC provisioning**, API key to live call in minutes (not 4–8 weeks); DID in **130+ countries**, outbound to **190+**, all number types via [SIP trunking](/docs/platform/sip/overview) or [BYOC](/docs/account-phone-number/byoc).
* **Programmable**, routing, [IVR](/docs/solutions/cloud-ivr), [recording](/docs/xml/record), transfer, and a full [Voice API](/docs/blogs/what-is-a-voice-api).
* **Secure & reliable**, SRTP/TLS 1.3; 99.99% uptime; 4.2+ MOS at 3M+ calls/day; flat ₹0.65/min.
* **It powers your stack, not a locked-in agent**, voice-AI builders like **Bolna**, fintechs like **Razorpay** and **Acko**, and enterprises like **KPMG** run on Vobiz.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What does VoIP stand for?">
    VoIP stands for Voice over Internet Protocol, carrying voice calls as data over IP networks instead of the traditional circuit-switched telephone network.
  </Accordion>

  <Accordion title="How much internet speed does VoIP need?">
    Budget roughly **100 kbps per concurrent call** for a clean G.711 call (less with Opus). Consistent low latency and low jitter matter more than raw bandwidth.
  </Accordion>

  <Accordion title="Is VoIP the same as SIP?">
    No. VoIP is the broad category; SIP is the signaling protocol most VoIP uses to set up calls. SIP is one part of how VoIP works.
  </Accordion>

  <Accordion title="Does VoIP work in a power cut?">
    Not on its own, VoIP needs power and internet. Use a UPS, backup connectivity, or mobile fallback. A line-powered landline keeps working; that's its one durable edge.
  </Accordion>

  <Accordion title="What equipment do I need for VoIP?">
    An internet connection, an endpoint (IP phone, softphone, or ATA, or just your app for programmable VoIP), and a provider (SIP trunk, cloud PBX, or Voice API).
  </Accordion>

  <Accordion title="What codecs does VoIP use?">
    Common ones are **G.711** (64 kbps, PSTN-grade), **G.729** (8 kbps, bandwidth-saving), and **Opus** (6–510 kbps, adaptive, AI-grade). Opus is preferred for high-fidelity, low-latency calls.
  </Accordion>

  <Accordion title="Is VoIP secure?">
    It can be, with TLS for signaling, SRTP for media, IP access control lists, and a Session Border Controller. Unencrypted VoIP on the public internet is exposed to fraud and eavesdropping.
  </Accordion>

  <Accordion title="Is VoIP good enough for a voice AI agent?">
    Yes, if the latency and audio path are right. Prioritize low-latency telephony, bidirectional streaming, barge-in, and formats that match your STT and TTS providers.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [What is SIP?](/docs/blogs/what-is-sip) · [SIP vs VoIP](/docs/blogs/sip-vs-voip) · [What is SIP trunking?](/docs/blogs/what-is-sip-trunking) · [What is a Voice API?](/docs/blogs/what-is-a-voice-api)
* [SIP trunking overview](/docs/platform/sip/overview) · [Audio streaming](/docs/audio-streams) · [VobizXML, how it works](/docs/xml/overview/how-it-works)
* [Cloud IVR](/docs/solutions/cloud-ivr) · [Call recording](/docs/solutions/call-recording) · [WebRTC integration](/docs/integrations/webrtc-application-setup)

## Sources

* Wikipedia, ["Voice over IP"](https://en.wikipedia.org/wiki/Voice_over_IP).
* IETF, ["SIP: Session Initiation Protocol" (RFC 3261)](https://www.rfc-editor.org/rfc/rfc3261), June 2002.
* Wikipedia, ["Session Initiation Protocol"](https://en.wikipedia.org/wiki/Session_Initiation_Protocol).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and place your first programmable VoIP call in minutes
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.