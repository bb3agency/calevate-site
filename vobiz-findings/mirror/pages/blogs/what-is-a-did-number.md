> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is a DID Number? Direct Inward Dialing Explained (2026)

> A DID number is a phone number that routes straight to a specific endpoint. How direct inward dialing works, DID types, porting, and DID vs virtual numbers.

*June 18, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

A DID number (Direct Inward Dialing number) is a real phone number that routes an incoming call straight to a specific destination, an extension, a SIP endpoint, or a webhook, without a human operator or a "press 1 for sales" menu in the way. Where a legacy office once needed a separate physical phone line for every number, a DID number lets one trunk carry hundreds or thousands of numbers, each mapped to its own destination in software.

That single idea, many numbers riding one connection, is what makes modern phone systems, cloud contact centres, and the [voice AI agents](/docs/solutions/ai-voice-agent) now answering real calls economically possible. This guide goes well past the dictionary definition: where DID came from, exactly how a call gets from the public network to your endpoint, the types of DID numbers, how a DID maps to a [SIP](/docs/blogs/what-is-sip) endpoint or webhook, E.164 formatting, number porting, how DIDs differ from virtual and toll-free numbers, and what changes when a DID number carries a voice AI agent.

<Note>
  **Key takeaways**

  * A **DID number** is a phone number that rings through directly to a specific endpoint (an extension, [SIP](/docs/blogs/what-is-sip-trunking) line, or webhook), instead of a shared operator or menu.
  * DID was created so one trunk could carry **many numbers**, replacing the old one-physical-line-per-number model. AT\&T introduced it in the 1960s.
  * A DID maps a dialed number (carried as **DNIS**) to a destination, defined in software, formatted in **[E.164](https://en.wikipedia.org/wiki/E.164)** (e.g. `+14155550101`).
  * DID types: **local, mobile, toll-free, and national/enterprise series**, all provisionable from one platform.
  * For voice AI, give **every agent its own DID** and provision it instantly, no 4–8-week telecom paperwork.
</Note>

## What is a DID number?

A **DID number** is a telephone number provisioned over a shared trunk that routes an inbound call directly to a specific destination, rather than to a switchboard operator or an IVR menu. The term comes from **Direct Inward Dialing (DID)**, the service that [provides multiple telephone numbers over one or more physical or virtual circuits to a PBX](https://en.wikipedia.org/wiki/Direct_inward_dial). In Europe and Oceania the same thing is called **DDI** (Direct Dial-In).

The one distinction that matters: a DID is *not* a physical line. It is a number that has been **assigned** to a trunk and **mapped** to an endpoint. You can have thousands of DIDs on a single [SIP trunk](/docs/concepts/sip-trunking), and you can re-point any of them, from an extension to a queue to a voicemail box to a software [endpoint](/docs/platform/voice/endpoints), without touching any hardware. That decoupling of *number* from *line* is the whole point of DID, and it is why "DID number" is essentially synonymous with the kind of provisionable, software-routable phone number every cloud platform sells today.

## A short history of direct inward dialing

Before DID, a business that wanted ten reachable numbers needed ten physical lines into its [PBX](https://www.twilio.com/docs/glossary/what-is-pbx-private-branch-exchange), one trunk per number. Scaling meant pulling more copper, and most internal extensions were simply unreachable from outside without going through the front-desk operator.

Direct Inward Dialing solved this. According to the historical record, the feature was [developed by AT\&T in the 1960s, patterned on the earlier IKZ service of the Deutsche Bundespost in Germany](https://en.wikipedia.org/wiki/Direct_inward_dial). The carrier would allocate a *block* of numbers to a business and deliver only the last few dialed digits to the PBX over a smaller set of trunks. The PBX read those digits and connected the caller to the matching extension. Suddenly a company could publish hundreds of direct numbers while paying for a fraction as many trunks.

The mechanism that makes this work is **DNIS** (Dialed Number Identification Service), the way the network tells the receiving system *which* number the caller dialed. DNIS is still the backbone of DID today; in [VoIP](/docs/blogs/what-is-voip), the dialed number simply arrives inside a SIP `INVITE` instead of as analog pulses. The economics that DID introduced, decouple numbers from lines, route in software, never changed; only the transport did.

## How DID numbers work

A DID call has the same shape whether it lands on a legacy PBX or a modern Voice API:

1. **A caller dials your DID** (for example `+1 415 555 0101`). The public switched telephone network routes the call toward the carrier that "owns" that number range.
2. **The carrier delivers the call to the trunk** the number is provisioned on, a [SIP trunk](/docs/platform/sip/overview) for VoIP, a PRI/T1 in the old world, passing along the **dialed number (DNIS)** and usually the caller's number (ANI / caller ID).
3. **The receiving system reads the dialed number** and looks up its routing rule, the DID-to-destination mapping you configured.
4. **The call is connected to the mapped destination**, a specific extension, a [SIP endpoint](/docs/platform/sip/inbound-trunks), an agent, a queue, or an application.

The crucial layer is step 3, the **DID mapping**. On a cloud platform, you don't edit a hardware dial plan; you point the number at a destination in software.

### Mapping a DID to a SIP endpoint or a webhook

In a programmable stack, a DID can resolve to one of two things:

* **A SIP endpoint.** The DID is mapped to a SIP URI or an [inbound trunk](/docs/platform/sip/inbound-trunks), and the carrier hands the call to your softswitch, PBX, or [SIP user agent](/docs/platform/voice/endpoints). This is the path most contact-centre and PBX deployments use, and it's how you bring numbers to your own infrastructure with [SIP trunking](/docs/platform/sip/overview).
* **A webhook (application control).** The DID is mapped to an HTTP application. When a call arrives, the platform fetches instructions from your URL and you reply with markup that controls the call, [play a message](/docs/xml/speak), [collect input](/docs/xml/gather), [dial another party](/docs/xml/dial), [record](/docs/xml/record), or [stream audio](/docs/audio-streams) to your software. This is how [VobizXML](/docs/xml/overview/how-it-works) works, and it's the model voice AI agents use to take real calls.

Either way, the DID is just the *address*; the mapping decides what happens. Because the mapping lives in software, you can re-route, A/B test, fail over, and scale to thousands of numbers without ever touching the number itself.

### E.164: how DID numbers are formatted

Globally, DID numbers are expressed in **[E.164](https://www.itu.int/rec/T-REC-E.164)**, the ITU-T international public telephone numbering plan. An E.164 number is [a maximum of 15 digits: a 1–3-digit country code followed by the national subscriber number](https://en.wikipedia.org/wiki/E.164), written with a leading `+` for international presentation, for example `+14155550101` (US) or `+919900112233` (India). Using E.164 consistently is what lets one [Voice API](/docs/blogs/what-is-a-voice-api) provision and route numbers across [130+ countries](/docs/account-phone-number) without ambiguity about national prefixes or trunk codes.

## Types of DID numbers

DIDs come in several flavours, and most platforms let you provision all of them from one place:

1. **Local (geographic) DIDs.** Tied to a city or region code (a +1 area code, an Indian STD code). They give a business a local presence and tend to lift answer rates because callers recognise the locality.
2. **Mobile DIDs.** Numbers in a country's mobile range. In markets where SMS and calls behave differently on mobile vs fixed numbers, a mobile DID matters for [deliverability and trust](/docs/best-practices/number-utilization).
3. **Toll-free DIDs.** National numbers (1-800 in the US, 1800 in India) where the *called party* pays. Used for support, sales, and brand lines.
4. **National / non-geographic DIDs.** Country-wide numbers not bound to a city, useful for a single national identity.
5. **Enterprise series (DID blocks).** A contiguous **range** of DIDs allocated together, ideal when you need one direct number per person, per branch, or, increasingly, **per software agent**. Vobiz provisions [all number types](/docs/account-phone-number/purchase-from-inventory), local, mobile, toll-free, and enterprise series, on demand.

## DID number specifications at a glance

| Property | What it means |
| - | - |
| **Full name** | Direct Inward Dialing number (DDI in EU/Oceania) |
| **Purpose** | Route a number directly to a specific endpoint, no operator |
| **Carried over** | SIP trunk (VoIP) or legacy PRI/T1 |
| **Dialed-number signal** | DNIS (the digits the caller dialled) |
| **Format standard** | [E.164](https://en.wikipedia.org/wiki/E.164), up to 15 digits, leading `+` |
| **Numbers per trunk** | Many (thousands), decoupled from physical lines |
| **Mapping target** | Extension, SIP endpoint, queue, or webhook/application |
| **Number types** | Local, mobile, toll-free, national, enterprise series |
| **Provisioning (legacy)** | 4–8 weeks of paperwork / manual KYC |
| **Provisioning (Vobiz)** | Instant, self-serve via eKYC |
| **Portability** | Yes, via local number portability (keep your number) |
| **Country coverage (Vobiz DID)** | 130+ countries |
| **Caller ID on outbound** | A DID can be used as the outbound caller ID |
| **Billing (Vobiz)** | Flat ₹0.65/min both ways (INR + GST) |
| **Reassign / re-route** | Instant, in software, no hardware change |

## DID vs virtual number vs toll-free

These terms overlap and are often used loosely, so here's the precise relationship:

| | DID number | Virtual number | Toll-free number |
| - | - | - | - |
| **Definition** | A number routed directly to a specific endpoint over a trunk | An umbrella term for any cloud number not tied to a physical line | A national number where the *callee* pays for the call |
| **Tied to a physical line?** | No | No | No |
| **Who pays** | Caller (standard rates) | Depends on the underlying number | Called party |
| **Typical use** | Direct lines, extensions, agent numbers | Forwarding, presence, tracking | Support / sales hotlines |
| **Geographic identity** | Local, mobile, national, or toll-free | Any | National, non-geographic |
| **Relationship** | A type of virtual number with direct routing | The broad category | A *type* of DID (toll-free DID) |

The short version: **a toll-free number is a kind of DID, and a DID is a kind of virtual number.** "Virtual number" describes *how* the number is provisioned (in the cloud, no copper); "DID" describes *how* it's routed (directly to an endpoint); "toll-free" describes *who pays*. A single number can be all three at once, a toll-free DID provisioned virtually. For more on the cloud-number side, see [what a landline number is](/docs/blogs/what-is-a-landline-number) and how it compares.

## Why DID numbers matter

* **Direct reachability.** Callers reach the right person, team, or system on the first ring, no operator, no menu maze. That's the original promise of [direct inward dialing](https://www.bandwidth.com/glossary/direct-inward-dialing-did), and it still drives faster resolution and better caller experience.
* **One trunk, many numbers.** You publish as many direct numbers as you need while paying for a fraction as many channels, the cost structure that makes large number estates affordable.
* **Software-defined routing.** Because the DID-to-destination mapping lives in software, you can re-route instantly, run [IVR](/docs/blogs/what-is-an-ivr), build [skills-based routing](/docs/solutions/contact-centre), add [call recording](/docs/solutions/call-recording), and fail over, all without telecom truck rolls.
* **Local presence at global scale.** Provision [local DIDs](/docs/account-phone-number/list-inventory-numbers) in dozens of markets so customers see a familiar number, while everything terminates on the same backend.
* **Number ownership and continuity.** With [porting](#how-number-porting-works), the DID is *yours*, you can move it between providers and keep your published identity.

### One DID per voice AI agent

The newest reason DIDs matter is voice AI. When you run [AI voice agents](/docs/solutions/ai-voice-agent), the cleanest architecture is to give **each agent (or each campaign, brand, or tenant) its own DID**, mapped to its own webhook or [SIP endpoint](/docs/platform/sip/inbound-trunks). That gives you:

* **Clean isolation and analytics** per agent, every call to that DID is unambiguously *that* agent's, which makes [post-call analytics](/docs/solutions/post-call-analytics) and reputation tracking trivial.
* **Independent caller ID** per agent on [outbound](/docs/solutions/automated-outbound-calling) calls.
* **Instant scale.** Spinning up a new agent shouldn't wait weeks for a number. Vobiz provisions DIDs **instantly via eKYC** and maps them to your endpoint or webhook in minutes, so launching the 50th agent is as fast as the first. Voice-AI builders like **Bolna** and **Sarvam.ai** run on exactly this model.

## Honest trade-offs

DID numbers are foundational, but they come with real considerations:

* **Regulatory provisioning.** Many countries require KYC, a local address, or business documentation before they'll assign a DID, and rules differ per country (Telnyx, for instance, publishes per-country DID requirements). This is why legacy provisioning can take **4–8 weeks**. Vobiz collapses that with self-serve **eKYC**, but the underlying regulations still apply, and in India that means [TRAI rules and DLT registration](/docs/best-practices/dlt-registration) for messaging.
* **Number reputation.** A DID used for high-volume outbound can get spam-flagged by carriers. Spreading traffic, warming numbers, and following [number-utilization best practices](/docs/best-practices/number-utilization) matters, Vobiz reports a 30% reduction in spam-flag rate on its network.
* **Emergency calling.** A DID isn't tied to a physical exchange, so emergency-service location (E911 in the US) must be explicitly registered, it isn't automatic the way a copper line's location is.
* **Porting lead time.** Keeping a number when you switch providers (porting) is a right in most countries, but it isn't instant, it's a coordinated carrier process that can take days.

### How number porting works

**Local number portability (LNP)** is [the ability of a customer to keep an existing telephone number when switching carriers, moving location, or changing service type](https://en.wikipedia.org/wiki/Local_number_portability). It exists precisely so a number you publish, your DID, is an asset you own, not something a carrier can hold hostage. In practice you submit a porting request to the *gaining* provider with proof of ownership; the losing and gaining carriers coordinate; and on a scheduled cutover the number's routing moves. The number, and therefore everyone's ability to reach you, is preserved throughout.

## How Vobiz handles DID numbers

[Vobiz](/docs/introduction) is telephony infrastructure built for voice AI, and DID provisioning is the front door:

* **Instant, self-serve provisioning.** Buy and activate DIDs via [eKYC](/docs/account-phone-number/purchase-from-inventory) in minutes, not the 4–8 weeks legacy telecom takes. All number types, **local, mobile, toll-free, enterprise series**, from one platform.
* **130+ countries for DID, 190+ for outbound.** Provision local numbers across [130+ countries](/docs/account-phone-number) and reach 190+ on outbound, all addressable through one unified API.
* **Map a DID to anything.** Point a number at a [SIP inbound trunk](/docs/platform/sip/inbound-trunks), a [voice endpoint](/docs/platform/voice/endpoints), or a [webhook driven by VobizXML](/docs/xml/overview/how-it-works), and re-route in software whenever you like.
* **Built for voice AI.** Sub-80 ms single-hop latency, [bidirectional audio streaming](/docs/audio-streams), barge-in, and outbound L16 playback at up to 24 kHz provide the media controls an agent needs. It **powers** Vapi, Retell, ElevenLabs, Pipecat, LiveKit, OpenAI, Gemini, and Bolna; it doesn't compete with your agent.
* **Secure & reliable.** SRTP media encryption and TLS 1.3 signaling; 99.99% uptime and 4.2+ MOS across 3M+ calls/day.
* **India-first, transparent pricing.** TRAI-compliant, eKYC, INR billing with GST, and a flat **₹0.65/min (65 paise) for both inbound and outbound**. Customers include **KPMG, Razorpay, Acko, Bolna, and Sarvam.ai**.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is a DID number?">
    A DID (Direct Inward Dialing) number is a phone number provisioned over a shared trunk that routes an incoming call directly to a specific destination, an extension, a SIP endpoint, or a webhook, without an operator or menu in between. Many DIDs can ride a single trunk, so the number is decoupled from any physical line.
  </Accordion>

  <Accordion title="What is the difference between a DID number and a regular phone number?">
    There's no contradiction, a DID *is* a regular phone number; "DID" describes how it's delivered. It's a number assigned to a trunk and mapped to an endpoint in software, rather than a number hardwired to a single physical line. Almost every cloud phone number today is technically a DID.
  </Accordion>

  <Accordion title="What is the difference between a DID number and a virtual number?">
    "Virtual number" is the broad category for any cloud number not tied to physical copper. "DID" specifically means a number routed directly to an endpoint. A DID is a type of virtual number, the two terms overlap, and most virtual numbers used for inbound calling are DIDs.
  </Accordion>

  <Accordion title="How does a DID number map to a SIP endpoint or webhook?">
    The platform stores a routing rule: when a call arrives for that DID, it reads the dialed number (DNIS) and connects the call to the mapped destination, either a SIP URI / inbound trunk for your own infrastructure, or an HTTP webhook that returns call-control instructions (like VobizXML) for application-driven calls.
  </Accordion>

  <Accordion title="Can I port my existing DID number to another provider?">
    Yes. Local number portability lets you keep your number when you switch providers. You submit a port request to the new provider with proof of ownership; the carriers coordinate a cutover and the number's routing moves while the number itself stays the same. It typically takes days, not minutes.
  </Accordion>

  <Accordion title="How fast can I get a DID number?">
    On legacy telecom it can take 4–8 weeks of paperwork and manual KYC. On a self-serve platform like Vobiz, you can provision a DID instantly via eKYC and map it to an endpoint or webhook in minutes, fast enough to give every new voice AI agent its own number on demand.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [Account phone numbers](/docs/account-phone-number) · [Purchase a number from inventory](/docs/account-phone-number/purchase-from-inventory) · [List inventory numbers](/docs/account-phone-number/list-inventory-numbers)
* [SIP trunking overview](/docs/platform/sip/overview) · [Inbound trunks](/docs/platform/sip/inbound-trunks) · [SIP trunking concept](/docs/concepts/sip-trunking)
* [What is a Voice API?](/docs/blogs/what-is-a-voice-api) · [What is a landline number?](/docs/blogs/what-is-a-landline-number) · [What is SIP trunking?](/docs/blogs/what-is-sip-trunking)
* [VobizXML: how it works](/docs/xml/overview/how-it-works) · [AI voice agent](/docs/solutions/ai-voice-agent) · [Number utilization](/docs/best-practices/number-utilization)

## Sources

* Wikipedia, ["Direct inward dial"](https://en.wikipedia.org/wiki/Direct_inward_dial).
* ITU-T, ["E.164: The international public telecommunication numbering plan"](https://www.itu.int/rec/T-REC-E.164).
* Wikipedia, ["E.164"](https://en.wikipedia.org/wiki/E.164).
* Wikipedia, ["Local number portability"](https://en.wikipedia.org/wiki/Local_number_portability).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a DID number and route your first programmable call in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.