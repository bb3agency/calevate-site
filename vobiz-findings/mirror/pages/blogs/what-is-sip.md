> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is SIP (Session Initiation Protocol)? The Complete 2026 Guide

> SIP sets up and ends almost every internet call. What SIP is, how it works (methods, message flow, registration), components, trunking, and security.

*June 10, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

Almost every call that travels over the internet, a softphone, a contact centre, a WhatsApp call, a voice AI agent, is set up by **SIP**. It is the dial tone of modern telephony: the protocol that locates the other party, rings them, agrees on how the audio will flow, and tears the call down when someone hangs up. Most explanations stop at "it's a signaling protocol." This guide goes the whole way, the actual methods, a real message flow, how endpoints are found, why production needs Session Border Controllers, how SIP trunking and channels work, and how to secure it all.

<Note>
  **Key takeaways**

  * **SIP (Session Initiation Protocol)** is a text-based signaling protocol for creating, modifying, and ending real-time sessions, defined in [IETF RFC 3261](https://www.rfc-editor.org/rfc/rfc3261).
  * SIP only does **signaling**; the audio rides a separate protocol (**RTP/SRTP**), negotiated via SDP.
  * It works through **methods** (`INVITE`, `REGISTER`, `BYE`, `REFER`…) and **response codes** (`180 Ringing`, `200 OK`, `486 Busy`), modeled on HTTP.
  * SIP runs on **port 5060** (unencrypted) or **5061** (TLS). It underpins **[SIP trunking](/docs/concepts/sip-trunking)**, VoIP, video, and presence.
</Note>

## What is SIP?

[SIP, the Session Initiation Protocol, is an application-layer signaling protocol for initiating, maintaining, modifying, and terminating real-time sessions](https://en.wikipedia.org/wiki/Session_Initiation_Protocol) involving voice, video, or messaging. It is defined by the IETF in [RFC 3261](https://www.rfc-editor.org/rfc/rfc3261) (June 2002, which obsoleted the original RFC 2543 from 1999).

SIP is deliberately **modeled on HTTP**, it is text-based, request/response, and human-readable. If you understand "GET a page," you can understand "INVITE a participant." What SIP does *not* do is carry the audio: it sets the call up and gets out of the way while the media flows separately. That separation is the single most important thing to understand about SIP.

### A brief history of SIP

SIP was first standardized by the IETF as RFC 2543 in 1999, then substantially revised as the [RFC 3261](https://www.rfc-editor.org/rfc/rfc3261) version still in use today. It emerged as the open, lightweight alternative to the older and more complex H.323 protocol. Its HTTP-like simplicity, plain-text messages, familiar request/response patterns, is a big part of why it won: it was easy for developers to implement and debug. Two decades later, that same simplicity is why SIP is the default way to connect everything from desk phones to modern voice AI agents to the public telephone network.

## How SIP works

A SIP exchange runs two layers together:

* **Signaling (SIP):** the messages that set up and control the call.
* **Media (RTP/SRTP):** the actual voice/video, described and negotiated inside SIP using the **Session Description Protocol (SDP)**, which codecs, which IP and port.

SIP messages travel over [port 5060 for unencrypted traffic or 5061 for TLS-encrypted signaling](https://en.wikipedia.org/wiki/Session_Initiation_Protocol), over UDP or TCP. When you build call flows on Vobiz, you don't hand-write SIP, you describe the flow in [VobizXML](/docs/xml/overview/how-it-works) and Vobiz speaks SIP to the carrier for you.

### SIP transport: UDP, TCP, or TLS

SIP can run over different transports, and the choice matters in production. **UDP** is the traditional default, fast and lightweight, but individual messages can be lost on a congested network, so the protocol has to retransmit. **TCP** adds reliable, ordered delivery, which helps when SIP messages grow large (for example, with many codec options). **TLS** (on port 5061) encrypts the signaling end to end and is the right choice for any trunk exposed to the public internet. The transport is negotiated per hop; a good provider lets you require TLS so that credentials, caller IDs, and call metadata never travel in the clear.

### SIP methods (requests)

The core RFC 3261 requests:

| Method | What it does |
| - | - |
| `INVITE` | Start a session (place a call) |
| `ACK` | Confirm a final response to an INVITE |
| `BYE` | End a session (hang up) |
| `CANCEL` | Cancel a pending INVITE |
| `REGISTER` | Tell the network where a user can be reached |
| `OPTIONS` | Query capabilities |
| `REFER` | Transfer a call (defined in RFC 3515) |

### SIP responses

Responses mirror HTTP status classes: **1xx** provisional (`100 Trying`, `180 Ringing`), **2xx** success (`200 OK`), **3xx** redirection, **4xx** client error (`404 Not Found`, `486 Busy Here`), **5xx** server error, **6xx** global failure. These show up in your [SIP call logs](/docs/platform/sip/call-logs) when you debug a call.

### Common SIP response codes you'll meet

When a call doesn't connect, the SIP response code tells you exactly why, and reading it is far faster than guessing. The ones you'll see most:

* **`486 Busy Here`**, the called party is on another call.
* **`480 Temporarily Unavailable`**, the endpoint is registered but isn't answering.
* **`487 Request Terminated`**, the caller hung up, or the `INVITE` was cancelled, before the call was answered.
* **`408 Request Timeout`**, no response in time, usually a routing or network problem.
* **`603 Decline`**, the callee actively rejected the call.
* **`404 Not Found`**, the number or user doesn't exist on that route.
* **`401`/`407`**, authentication required; the endpoint must supply credentials.

If you're debugging dropped or failing calls, the response code in the logs is the first place to look, it turns a vague "calls don't work" into a specific, fixable cause.

### A real SIP call, message by message

```text theme={null}
Caller                              Callee
  | ---------- INVITE ------------->|   "let's start a call" (+ SDP offer)
  | <-------- 100 Trying -----------|   "working on it"
  | <-------- 180 Ringing ----------|   phone is ringing
  | <-------- 200 OK ---------------|   answered (+ SDP answer / codecs)
  | ---------- ACK ---------------->|   confirmed, call is up
  | ====== RTP/SRTP media =========>|   audio flows (NOT over SIP)
  | <===== RTP/SRTP media ==========|
  | ---------- BYE ---------------->|   hang up
  | <-------- 200 OK ---------------|   confirmed, call ended
```

That `INVITE → 180 → 200 OK → ACK → media → BYE` loop is the heartbeat of every SIP call. The `INVITE` and `200 OK` each carry an **SDP** body that offers and answers the media details (codec, IP, port).

### Transactions and dialogs

SIP groups messages into **transactions** (a request and its responses, like `INVITE` + `100`/`180`/`200`) and **dialogs** (the whole peer-to-peer relationship for a call, identified by Call-ID, tags, and CSeq). You rarely touch these directly, but they're why SIP can reliably match a `BYE` to the right call.

### How endpoints are found: registration

Before a phone can receive calls, it tells the network where it is, using `REGISTER`. A **registrar** records that binding (user → current address). When someone calls, a **proxy** consults that record to route the `INVITE`. This is what lets a single number reach you whether you're on a desk phone, a laptop, or a mobile app, see [How IP phones use SIP registration](/docs/concepts/sip-trunking) for the trunking equivalent.

### NAT, firewalls, and Session Border Controllers

Most endpoints sit behind NAT and firewalls, which break naive SIP/RTP. In production, a **Session Border Controller (SBC)** at the network edge handles NAT traversal, topology hiding, security, and trunk control. With Vobiz this is managed for you, with controls like [IP access control lists](/docs/platform/sip/ip-access-control-list) and [credentials](/docs/platform/sip/credentials) on your trunks.

## SIP components

* **User Agent (UA):** your endpoint, a softphone, IP phone, or app. It acts as a client (UAC, sends requests) and a server (UAS, responds).
* **Proxy server:** routes SIP requests toward the destination and enforces policy.
* **Registrar:** records where each user is currently reachable (via `REGISTER`).
* **Redirect server:** returns the address of the next hop instead of forwarding.
* **Session Border Controller (SBC):** sits at the edge for security, NAT traversal, and trunk control.

## What SIP is used for

* **VoIP calling** and **[SIP trunking](/docs/concepts/sip-trunking)**, connecting phone systems and apps to the public network.
* **Video conferencing** and **multimedia** sessions.
* **Instant messaging and presence** (who's online/available).
* **Call control features**, [transfer](/docs/solutions/call-transfer) (`REFER`), hold, and [conferencing](/docs/xml/conference).

## SIP trunking and channels

A **SIP trunk** is the productized use of SIP: a virtual connection that links your phone system or application to the public telephone network. Instead of a fixed bundle of physical lines, a trunk carries many simultaneous calls, each concurrent call is a **channel** (sometimes called a session or a "trunk channel"). You provision the number of channels you need and scale on demand, rather than installing PRI circuits.

On Vobiz, you configure [outbound trunks](/docs/platform/sip/outbound-trunks) and [inbound trunks](/docs/platform/sip/inbound-trunks) separately, secure them with [credentials](/docs/platform/sip/credentials) and [IP ACLs](/docs/platform/sip/ip-access-control-list), and route inbound calls with an [origination URI](/docs/platform/sip/origination-uri). For the full picture, see [What is SIP trunking?](/docs/blogs/what-is-sip-trunking) and the [SIP trunking overview](/docs/platform/sip/overview).

### How many SIP channels do you need?

Because a channel is one concurrent call, sizing comes down to your busy-hour volume and average call length. A quick estimate: channels ≈ (calls per hour × average minutes per call) ÷ 60, plus headroom for spikes. A support line handling 120 calls an hour at four minutes each needs roughly eight channels (120 × 4 ÷ 60), and you'd provision ten to twelve to absorb peaks. The big advantage over a legacy PRI is that you change this number in software as traffic grows, no ordering new circuits, no waiting weeks for an install. Under-provision and callers hit busy signals; over-provision and you pay for capacity you don't use, so it's worth watching your concurrency in the dashboard and adjusting.

## Benefits of SIP

* **Interoperability**, an open IETF standard, so equipment and providers from different vendors work together.
* **Scalability**, add channels in software; no physical lines.
* **Flexibility**, one protocol for voice, video, and messaging.
* **Cost**, replaces expensive PRI/T1 circuits with pay-as-you-go.
* **Mobility**, registration lets a user be reachable on any device.
* **Programmability**, paired with a [Voice API](/docs/blogs/what-is-a-voice-api), SIP becomes scriptable: [IVR](/docs/solutions/cloud-ivr), [recording](/docs/xml/record), [transfer](/docs/solutions/call-transfer), and real-time [audio streaming](/docs/audio-streams).

## SIP security

A SIP endpoint on the public internet is a target for toll fraud, eavesdropping, and registration hijacking. Secure it with:

* **Encryption**, **TLS** for the SIP signaling (port 5061) and **SRTP** for the media.
* **Authentication**, digest auth on `REGISTER`/`INVITE`; strong [credentials](/docs/platform/sip/credentials).
* **A Session Border Controller**, to shield internal infrastructure, handle NAT, and rate-limit.
* **[IP access control lists](/docs/platform/sip/ip-access-control-list) and geo-permissions**, only accept traffic from known sources; block high-risk destinations.
* **Monitoring**, watch your [SIP call logs](/docs/platform/sip/call-logs) and [recordings](/docs/platform/sip/recordings) for anomalies.

## SIP vs VoIP vs SIP trunking

Quick disambiguation: **VoIP** is the broad category (voice over IP). **SIP** is the signaling protocol most VoIP uses. A **SIP trunk** is one VoIP service built on SIP, your connection to the public phone network. For the full breakdown, see [SIP vs VoIP](/docs/blogs/sip-vs-voip) and [What is SIP trunking?](/docs/blogs/what-is-sip-trunking).

## How Vobiz uses SIP

[Vobiz](/docs/introduction) runs SIP as the signaling layer of a network built for voice AI, not retrofitted from a BPO-era stack:

* **[Secure SIP trunks](/docs/platform/sip/overview)** with global failover and direct carrier connect, configure [outbound](/docs/platform/sip/outbound-trunks) and [inbound](/docs/platform/sip/inbound-trunks) trunks independently.
* **Sub-80 ms latency** single-hop (vs 300–400 ms legacy) so signaling and media feel instant.
* **SRTP media encryption + TLS 1.3 signaling** by default, with [IP ACLs](/docs/platform/sip/ip-access-control-list) and trunk [credentials](/docs/platform/sip/credentials) against fraud.
* **Instant eKYC provisioning**, DID in 130+ countries / outbound to 190+, all number types, plus [bring-your-own-carrier](/docs/account-phone-number/byoc).
* **Programmable**, blind/attended transfer via `REFER`, dynamic routing, [recording](/docs/xml/record), and real-time [audio streaming](/docs/audio-streams) to your own STT/LLM/TTS, described in [VobizXML](/docs/xml/overview/how-it-works).
* 99.99% uptime, 4.2+ MOS at 3M+ calls/day, flat ₹0.65/min in and out.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What does SIP stand for?">
    SIP stands for Session Initiation Protocol, the signaling protocol that sets up, manages, and ends real-time communication sessions like voice and video calls.
  </Accordion>

  <Accordion title="Is SIP the same as VoIP?">
    No. VoIP is the broad category of voice over IP; SIP is the signaling protocol most VoIP uses to set up calls. SIP is one part of how VoIP works.
  </Accordion>

  <Accordion title="What port does SIP use?">
    SIP typically uses port 5060 for unencrypted signaling and port 5061 for TLS-encrypted signaling, over UDP or TCP.
  </Accordion>

  <Accordion title="Does SIP carry the voice of a call?">
    No. SIP only handles signaling. The audio is carried separately by RTP, or SRTP when encrypted, negotiated via SDP inside the SIP messages.
  </Accordion>

  <Accordion title="What is a SIP INVITE?">
    `INVITE` is the SIP method that starts a session, it's how one party requests a call with another, carrying the SDP that offers codecs and media addresses.
  </Accordion>

  <Accordion title="What is SIP registration?">
    Registration (`REGISTER`) tells the network where a user is reachable. A registrar stores that binding so incoming calls can be routed to the right device.
  </Accordion>

  <Accordion title="How many calls can a SIP trunk handle?">
    A SIP trunk's capacity is set by its **channels** (concurrent sessions). Unlike a fixed PRI (23 or 30 channels), you provision channels in software and scale on demand.
  </Accordion>

  <Accordion title="Is SIP secure?">
    SIP can be secured with TLS for signaling, SRTP for media, digest authentication, IP access control lists, and a Session Border Controller. Unencrypted SIP on the public internet is vulnerable to fraud and eavesdropping.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [SIP trunking overview](/docs/platform/sip/overview)
* [Outbound SIP trunks](/docs/platform/sip/outbound-trunks) · [Inbound SIP trunks](/docs/platform/sip/inbound-trunks)
* [SIP credentials](/docs/platform/sip/credentials) · [IP access control lists](/docs/platform/sip/ip-access-control-list) · [Origination URI](/docs/platform/sip/origination-uri)
* [SIP trunking concept](/docs/concepts/sip-trunking) · [SIP vs WebSockets](/docs/concepts/sip-vs-websockets)
* [VobizXML, how it works](/docs/xml/overview/how-it-works)

## Sources

* IETF, ["SIP: Session Initiation Protocol" (RFC 3261)](https://www.rfc-editor.org/rfc/rfc3261), June 2002.
* Wikipedia, ["Session Initiation Protocol"](https://en.wikipedia.org/wiki/Session_Initiation_Protocol).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Secure, low-latency SIP trunks with global failover
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.