> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is SIP Trunking?

> SIP trunking connects your phone system to the internet, replacing physical phone lines. Here's what it is, how it works, and how to choose a provider.

*June 10, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

SIP trunking is the modern way to connect a phone system to the public telephone network over the internet, no copper lines, no rigid channel counts, no waiting weeks for a carrier. If you're building voice applications or wiring a contact centre (or a voice AI agent) to real phone numbers, the SIP trunk is the pipe that carries every call.

This guide explains what SIP trunking is, how it actually works under the hood, how it differs from legacy PRI and from "VoIP" in general, and what to look for in a provider.

<Note>
  **Key takeaways**

  * A **SIP trunk** is a virtual phone line that connects your PBX or app to the public telephone network (PSTN) over IP, using the [Session Initiation Protocol](https://www.rfc-editor.org/rfc/rfc3261).
  * SIP handles **signaling** (setting up/tearing down calls); the audio itself rides on a separate media protocol (RTP/SRTP).
  * It replaces legacy **PRI/T1/E1** lines, far more elastic, cheaper to scale, and provisioned in minutes instead of weeks.
  * For voice AI, the trunk's **latency, codec quality, and programmability** matter as much as price.
</Note>

## What is SIP trunking?

A **SIP trunk** is a virtual connection that lets your private telephone system place and receive calls over the internet instead of over physical phone lines. Technically, [SIP trunking is a Voice over IP (VoIP) service based on the Session Initiation Protocol](https://en.wikipedia.org/wiki/SIP_trunking), it lets an internet telephony service provider (ITSP) deliver telephone service to a customer running a SIP-capable IP-PBX or application.

Where a traditional "trunk" was a bundle of physical lines between your office and the telephone company, a SIP trunk is **software-defined**: one IP connection that can carry many simultaneous calls, scale up or down on demand, and reach numbers anywhere in the world. The same trunk can also carry video and other [streaming media](https://en.wikipedia.org/wiki/SIP_trunking), but voice is the primary use.

## How SIP trunking works

To understand a SIP trunk, separate two things that legacy telephony bundled together: **signaling** (the "who's calling whom, ring it, answer it, hang up") and **media** (the actual audio).

1. **Signaling (SIP).** [SIP is an application-layer signaling protocol for initiating, maintaining, modifying, and terminating real-time sessions](https://en.wikipedia.org/wiki/Session_Initiation_Protocol). It's text-based and modeled on HTTP. When a call starts, SIP messages (`INVITE`, `200 OK`, `ACK`, `BYE`) negotiate the call between your system and the provider. SIP clients typically use ports **5060** (unencrypted) or **5061** (TLS-encrypted), per the [SIP specification](https://en.wikipedia.org/wiki/Session_Initiation_Protocol).
2. **Media (RTP/SRTP).** SIP itself carries no audio. Once a call is set up, the voice streams over the **Real-time Transport Protocol (RTP)**, or its encrypted form **SRTP**, negotiated via the Session Description Protocol (SDP) inside the SIP messages.
3. **The two domains.** A SIP-trunk deployment splits into a **private domain** (your IP-PBX or app) and a **public domain** (the carrier's access to the PSTN). A network-border element (a session border controller) sits between them, and [the ITSP is responsible to the applicable regulatory authority](https://en.wikipedia.org/wiki/SIP_trunking) for call handling, identity, and lawful interception in the public domain.

The net effect: your application speaks SIP to the provider, the provider hands the call off to the global telephone network, and audio flows over RTP, all over your existing internet connection.

## SIP trunking vs PRI: what it replaces

For decades, businesses bought **PRI** (Primary Rate Interface) circuits, a T1 in North America carried 23 voice channels; an E1 in much of the world carried 30. Each circuit was a fixed, physical commitment.

SIP trunking replaces that model:

| | Legacy PRI / T1 / E1 | SIP trunk |
| - | - | - |
| **Medium** | Dedicated physical circuit | Software over your internet/IP |
| **Capacity** | Fixed (23 or 30 channels) | Elastic, add channels on demand |
| **Provisioning** | Weeks, on-site install | Minutes, self-serve |
| **Geography** | Tied to the local exchange | Numbers and routing anywhere |
| **Cost** | Per-circuit, long contracts | Per-channel/per-minute, pay-as-you-go |

For most teams, a SIP trunk is cheaper, faster to turn up, and far easier to scale for spiky or seasonal traffic.

## SIP trunking vs VoIP, what's the difference?

People use "VoIP" and "SIP trunking" interchangeably, but they're not the same. **VoIP** is the broad category, *any* voice carried over IP. **SIP** is the specific signaling protocol most VoIP uses to set calls up, and a **SIP trunk** is one productized application of it: connecting your system to the PSTN. (Analogy: VoIP is "email"; SIP is "SMTP"; a SIP trunk is "your mail server's connection to the internet.") Some VoIP also rides on other signaling, for example, browser calling uses [WebRTC and WebSocket streaming](/docs/concepts/sip-vs-websockets) rather than SIP.

## Is SIP trunking secure?

A raw SIP trunk on the public internet can be a target for toll fraud and eavesdropping, so production trunks should be encrypted end to end: **TLS** for the SIP signaling and **SRTP** for the media. Look for a provider that supports TLS 1.3 signaling and SRTP media encryption by default, plus controls like IP access control lists and geo-permissions to block fraud.

## What to look for in a SIP trunk provider

* **Latency and hops**, fewer network hops mean clearer, more natural calls (critical for voice AI).
* **Codec/sample-rate**, higher-fidelity audio improves both human calls and speech recognition.
* **Provisioning speed**, instant, self-serve setup vs weeks of paperwork.
* **Global reach & number types**, DIDs where you need them; local, mobile, toll-free.
* **Programmability**, APIs for routing, recording, IVR, and real-time call control.
* **Reliability & failover**, high uptime with automatic regional failover.
* **Security & compliance**, SRTP/TLS, plus the regulatory coverage for your markets.

## How Vobiz handles SIP trunking

[Vobiz](/docs/introduction) provides **secure, low-latency [SIP trunks](/docs/concepts/sip-trunking) with global failover**, purpose-built for voice AI, not retrofitted from a BPO-era stack:

* **Sub-80 ms latency** on a single-hop, event-driven architecture with direct carrier connect (legacy CPaaS often sits at 300–400 ms).
* **Instant, self-serve provisioning** of trunks, numbers, and APIs via eKYC, go from API key to a live call in minutes, not the 4–8 weeks legacy carriers take.
* **DID provisioning in 130+ countries** and **outbound connectivity to 190+**, across all number types (local, mobile, toll-free, enterprise), managed through [one unified API](/docs/platform/sip/overview).
* **Programmable call control**, dynamic routing, [call transfer](/docs/solutions/call-transfer), [IVR](/docs/solutions/cloud-ivr), [recording](/docs/solutions/call-recording), and real-time [audio streaming](/docs/audio-streams) to your own STT/LLM/TTS stack.
* **Secure by design**, SRTP media encryption with TLS 1.3 signaling.
* **Carrier-grade reliability**, 99.99% uptime, 99.99% call-initialization rate, and a 4.2+ MOS at 3M+ calls a day.
* **Transparent pricing**, a flat ₹0.65/min for both inbound and outbound (INR + GST).

Because Vobiz is the **telephony layer**, it connects cleanly to whatever you build on top, [Vapi, Retell, ElevenLabs, Pipecat, LiveKit, and more](/docs/integrations), without locking you into a particular agent or CX product.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is a SIP trunk in simple terms?">
    A SIP trunk is a virtual phone line that connects your phone system or application to the public telephone network over the internet, so you can make and receive calls without physical phone lines.
  </Accordion>

  <Accordion title="What is the difference between SIP and SIP trunking?">
    SIP (Session Initiation Protocol) is the signaling protocol that sets up and tears down calls. SIP trunking is the service that uses SIP to connect your system to the PSTN, it's the productized application of the protocol.
  </Accordion>

  <Accordion title="Is SIP trunking the same as VoIP?">
    Not exactly. VoIP is the broad category of voice over IP; SIP is the protocol most VoIP uses for signaling; a SIP trunk is one specific VoIP service, your connection to the public phone network.
  </Accordion>

  <Accordion title="How many concurrent calls can a SIP trunk handle?">
    Unlike a fixed PRI (23 or 30 channels), a SIP trunk's capacity is elastic, you provision the number of concurrent channels you need and scale up or down on demand.
  </Accordion>

  <Accordion title="Does SIP trunking work for voice AI agents?">
    Yes. A SIP trunk gives a voice AI agent real phone numbers and PSTN reach. For AI, prioritize low latency, high-fidelity audio, and programmability, the call has to feel natural in real time.
  </Accordion>
</AccordionGroup>

## Sources

* IETF, ["SIP: Session Initiation Protocol" (RFC 3261)](https://www.rfc-editor.org/rfc/rfc3261), June 2002.
* Wikipedia, ["SIP trunking"](https://en.wikipedia.org/wiki/SIP_trunking).
* Wikipedia, ["Session Initiation Protocol"](https://en.wikipedia.org/wiki/Session_Initiation_Protocol).

<Card title="Build on Vobiz SIP trunking" icon="rocket" href="/docs/quick-start">
  Provision a secure, low-latency SIP trunk and place your first call in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.