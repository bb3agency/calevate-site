> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is Number Masking? How Two-Way Call Masking Works

> Number masking hides both parties' real phone numbers behind a proxy DID. Here's how one-way and two-way call masking work, with a full call flow.

*June 12, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

Number masking is a telephony technique that lets two people call each other without ever seeing each other's real phone number. Instead of dialing the other person directly, each party dials a **proxy number** (a virtual DID), and the platform bridges the two legs in the middle. The driver never gets the rider's number, the delivery agent never gets the customer's, and neither can call the other after the transaction ends.

If you have booked a cab, ordered food, or sold something on a marketplace and spoken to the other person through an in-app "Call" button, you have used number masking, even if you never noticed. That is the point: done right, it is invisible.

This guide explains what number masking is, how it works at the signaling level, the difference between one-way and two-way masking (and why two-way needs *two* numbers), a step-by-step call flow, who uses it, why it matters for security and privacy regulation, and how to build it.

<Note>
  **Key takeaways**

  * **Number masking** routes a call through a proxy DID so neither caller sees the other's real number, only the masking number shows as caller ID.
  * **One-way masking** hides one side; **two-way masking** hides both and works in both directions, which is why it typically uses **two masking numbers**.
  * It is a **security and compliance** control too: a leaked number is an OTP/SIM-swap attack vector, and masking supports data-minimization duties under **GDPR (EU)**, **CCPA (US)**, and the **DPDP Act (India)**.
  * On [Vobiz](/docs/introduction), masking is a [`<Dial>`](/docs/xml/dial) with a `callerId` override returned from your webhook, you own the number-mapping logic and the data.
</Note>

## What is number masking?

**Number masking** (also called *call masking*, *proxy calling*, or *number anonymization*) puts a virtual phone number between two parties so each sees the proxy number instead of the other's real number. The real numbers stay on a server and are never exposed over the phone network.

A [phone number is personally identifiable information](https://gdpr-info.eu/art-4-gdpr/), once one party has the other's real number, they can call or message them forever, share it, or sell it. Masking removes that risk by making the **caller ID** the masking number rather than the real number. [Caller ID is the service that transmits a caller's number to the called party](https://en.wikipedia.org/wiki/Caller_ID); masking overrides what gets transmitted so the recipient sees a number you control. Because the masking number is a DID you rented, it is the only number that ever appears, the real numbers stay private on both ends.

## How number masking works

Every call has two halves: **signaling** (set up, ring, answer, hang up) and **media** (the audio). Masking is a signaling-time decision, you change *who connects to whom* and *what caller ID is shown*, while the audio bridges normally over [RTP/SRTP](/docs/concepts/sip-trunking).

The lifecycle of a masked call:

1. **A party dials the masking number.** Your customer taps "Call," which dials a masking DID (`M`), not the other person's real number.
2. **The carrier delivers the call to your platform.** Because the DID points at an [application](/docs/platform/voice/applications) with an **Answer URL**, the platform receives the call and needs instructions.
3. **The platform calls your webhook.** It `POST`s the call details, crucially `From` (who is calling) and `To` (which masking number they dialed), to your Answer URL. See [how XML webhooks work](/docs/xml/overview/how-it-works).
4. **Your backend resolves the mapping.** Your server decides who the call is meant for and what caller ID the other side should see, and returns [XML](/docs/xml/response).
5. **The platform bridges a second leg.** Your XML returns a [`<Dial>`](/docs/xml/dial) with a `callerId` override to the real destination, showing the masking number.
6. **Both legs bridge; audio flows.** Each party sees only the masking number.

The decisive line is the caller ID override, returned the moment the masking number is dialed:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="919000000002" timeout="30">
    <Number>918888800002</Number>
  </Dial>
</Response>
```

Here the platform dials the real customer (`918888800002`) but shows them the masking number (`919000000002`). The [`callerId` attribute on `<Dial>`](/docs/xml/dial) is what makes this masking rather than a plain forward.

## One-way vs two-way number masking

**One-way masking** hides one party, for example, an outbound campaign that shows a single branded masking number so the agent's personal mobile stays private. It can often use a single number.

**Two-way masking** hides *both* parties, *in both directions*, the pattern behind ride-hailing, delivery, and marketplaces. Either party can initiate, and neither learns the other's number. It is harder, because a single number cannot tell which direction a call is meant to go.

| | One-way masking | Two-way masking |
| - | - | - |
| **Who is hidden** | One party | Both parties |
| **Who can initiate** | Usually one side | Either side |
| **Numbers needed** | Often one DID | Typically two DIDs |
| **Typical use** | Outbound campaigns, click-to-call | Ride-hailing, delivery, marketplaces |

## Why two-way masking needs two numbers

Imagine a field agent (FE), a customer, and a single masking number `M` both are told to call.

* The agent dials `M`. Your server thinks: "Someone dialed `M`, connect them to the customer." Correct.
* The customer dials the *same* `M`. Same rule fires, "connect them to the customer", and tries to call the customer, who just dialed. The logic collapses. A single number cannot encode *direction*.

The robust design uses **two masking numbers** with **cross-mapped caller IDs**:

* **`M1`** is the number the agent dials to reach the customer.
* **`M2`** is the number the customer dials to reach the agent.
* Agent dials `M1` → customer is dialed and **sees `M2`**. Customer dials `M2` → agent is dialed and **sees `M1`**.

So each party always sees one consistent number for the other, and direction is encoded in *which number was dialed* (the `To`). Your mapping table becomes a deterministic two-row lookup:

| Dialed number (`To`) | Allowed caller | Connect to | Caller ID shown |
| - | - | - | - |
| `M1` | the agent | the customer | `M2` |
| `M2` | the customer | the agent | `M1` |

That two-row lookup is the entire brain of a two-way masking system.

## A full two-way call flow

Say the agent is `+91 98888 00001`, the customer `+91 98888 00002`, and you provisioned `M1 = +91 90000 00001` and `M2 = +91 90000 00002`.

```text theme={null}
Agent (98888 00001) ── dials ──▶ M1 (90000 00001)
        │
  Vobiz ── POST /answer (From=agent, To=M1) ──▶ Your backend
        │                                        resolve(): dial customer, show M2
        ◀── <Dial callerId="M2"><Number>98888 00002</Number></Dial> ──┘
        │
  Vobiz dials the customer, who sees M2 ── both legs bridge
```

When the **customer** calls the agent, it is the mirror image: they dial `M2`, your webhook resolves `To=M2` to "dial the agent, show `M1`," and the agent's phone rings showing `M1`, same code path, opposite row.

Three things make this production-grade: the webhook is **stateless** (every request carries `From` and `To`), **idempotent** (retries yield the same XML, no double-dialing), and it **authorizes the caller** (only the registered party for that masking number is bridged).

## Number masking vs call forwarding

The distinction is in *what is hidden* and *who controls routing*.

| | Call forwarding | Caller ID blocking | Number masking |
| - | - | - | - |
| **What happens** | Calls to A ring at B | Caller ID withheld ("Private") | Calls route through a proxy DID |
| **Real numbers hidden?** | No, B often sees A | Originator hidden; recipient not | **Both** |
| **Two-way?** | No | No | **Yes** (two DIDs) |
| **Who controls routing** | Carrier/PBX config | Carrier feature | **Your application** |
| **Re-contact after?** | Possible | Possible | **Blocked** (mapping can expire) |

Masking's key advantage: because routing is an *application* decision made on every call, you can **expire the mapping** when the ride ends or the order is delivered, exactly the [data minimization](https://gdpr-info.eu/art-5-gdpr/) privacy law asks for.

## Who uses number masking: US and Indian players

If an app has an in-app "Call" button between two strangers, masking is usually underneath it. By category, with platforms known to use masked calling on both sides of the world:

* **Ride-hailing.** US: **Uber**, **Lyft**. India: **Ola**, **Uber**, **Rapido**.
* **Food and grocery delivery.** US: **DoorDash**, **Uber Eats**, **Instacart**. India: **Swiggy**, **Zomato**, **Blinkit**, **Zepto**.
* **Marketplaces and classifieds.** US: **Airbnb**, **OfferUp**. India: **Meesho**, **OLX**.
* **Real estate.** US: **Zillow**. India: **NoBroker**, **Housing.com**, **MagicBricks**.
* **Home and field services.** India: **Urban Company**; US: **Thumbtack**, **Angi**, coordinating ETAs through a [contact-centre](/docs/solutions/contact-centre) or dispatch app.
* **Surveys and research.** Market-research firms, CSAT/NPS callbacks, and political or academic polling call respondents from a masking number, so the respondent's real number isn't exposed to the interviewer a rotating panel of callers can't be traced back to one person. The same pattern protects whistle-blower and grievance hotlines, where the caller must stay anonymous but still needs a real conversation, and it gives you a logged, optionally [recorded](/docs/solutions/call-recording) record of every response call for quality control without ever storing the respondent's number in the clear. (See the [call survey example](/docs/examples/vobiz-call-survey-xml-python).)
* **Hospitality, dating, and healthcare.** Hotel aggregators (**OYO**), dating apps, and telehealth clinics all let two people talk before, or instead of, exchanging a personal number.

In every case the reason is the same: a phone number is a liability once it leaks. Masking turns a permanent contact detail into a temporary, revocable channel.

## Why number masking matters for security

Privacy is the headline, but masking is also a **security control**. A phone number is increasingly a *credential*, the second factor for OTP logins, the recovery handle for email and banking, the anchor for SIM-swap attacks. Leaking it widens your customers' attack surface and yours.

* **It shrinks the attack surface.** Real numbers never reach the other party's handset, so they can't be saved, scraped at scale, or fed into SIM-swap and OTP-phishing attempts.
* **It contains a breach.** The real-number mapping lives only in your backend, where you can encrypt it at rest, scope access, and delete it on schedule, rather than scattering numbers across millions of devices.
* **It stops harassment structurally.** Because the connection is revocable, post-transaction stalking of drivers, delivery partners, and customers is prevented by design, not by policy.
* **It secures the call path.** Every call runs over your platform, so you can enforce [TLS 1.3 signaling and SRTP media](/docs/concepts/sip-trunking), [authenticate webhooks](/docs/concepts/validating-callbacks) before acting on them, and keep an auditable [call log](/docs/platform/voice/call-logs).

The principle is **data minimization applied to telephony**: expose the least number information necessary, for the shortest time, over the most secure path.

## Number masking and privacy regulation: EU, US, and India

No statute literally says "thou shalt mask phone numbers." But across the EU, US, and India, privacy law treats a phone number as protected personal data and pushes hard toward *data minimization* and *privacy by design*, and masking is the standard way to satisfy those duties. For two-sided platforms, exposing real numbers is a compliance liability; masking is how you avoid it.

| Region | Key regulation | What it requires | How masking helps |
| - | - | - | - |
| **EU / EEA** | [GDPR Art. 5](https://gdpr-info.eu/art-5-gdpr/) & [Art. 25](https://gdpr-info.eu/art-25-gdpr/) | Process only necessary personal data; build privacy in by default | Real numbers never exposed or stored on devices; minimal, revocable mapping |
| **USA** | [CCPA / CPRA](https://oag.ca.gov/privacy/ccpa), [TCPA](https://en.wikipedia.org/wiki/Telephone_Consumer_Protection_Act_of_1991), HIPAA | Know/delete/opt-out rights; consent for calls; protect health data (PHI) | Less personal information exposed; masked clinic numbers protect patient and practitioner lines |
| **India** | [DPDP Act, 2023](https://en.wikipedia.org/wiki/Digital_Personal_Data_Protection_Act,_2023); TRAI / DoT caller-ID rules | Consent and purpose limitation; caller ID must be a number you own | Masking uses *your own* DIDs as caller ID (compliant) while minimizing exposure. See [India calling regulations](/docs/compliance/india/calling-regulations) |

Two takeaways. Masking is a clean way to demonstrate **privacy by design**, because the architecture, not a policy promise, keeps numbers private. And in India it is also the *operationally* compliant way to set caller ID: a non-owned number is rejected as `Unknown Caller ID` (see [Hangup Causes](/docs/concepts/hangup-causes)), so masking with your own DIDs satisfies both the privacy and the telecom rules at once.

## Benefits of number masking

Pulling it together, masking delivers privacy, safety, and operational control in one feature:

* **Privacy by default**, neither real number is ever transmitted, so it can't be saved, shared, or sold.
* **Less harassment and spam**, revocable connections structurally end post-transaction contact, a real safety win for drivers, delivery partners, and customers.
* **Higher trust and call rates**, users engage more when they know their number stays private.
* **Full records on your terms**, every call passes through your platform, so you keep [call logs](/docs/platform/voice/call-logs), recordings, and analytics without holding either party's number on the device.
* **A stronger compliance posture**, masking maps directly onto data-minimization and privacy-by-design duties under DPDP, GDPR, and US privacy law.

## Trade-offs and how to build it

Masking is simple in concept and unforgiving in detail. Plan for these: true two-way needs **two DIDs** per direction (reuse a pool across pairings as you scale); callers must be **registered** (a borrowed phone is rejected); your Answer URL must respond **sub-second** before the webhook times out; webhooks must be **idempotent** and served over **HTTPS** with [callback validation](/docs/concepts/validating-callbacks); and the **mapping lifecycle** (create on order, expire on delivery) is a feature, not an afterthought.

At a high level, a two-way masking service is four parts: provision two masking [DIDs](/docs/account-phone-number); create an [application](/docs/platform/voice/applications) with an Answer URL and attach both DIDs; write the `/answer` webhook (resolve `From`/`To` → authorize → return a [`<Dial callerId=…>`](/docs/xml/dial) or a [`<Speak>`](/docs/xml/speak) + [`<Hangup>`](/docs/xml/hangup) rejection); and manage the mapping store. We maintain a complete, runnable reference:

<Card title="Tutorial: Build two-way number masking (Python)" icon="code" href="/docs/examples/vobiz-two-way-number-masking-python">
  FastAPI + Vobiz XML. Clone, configure two DIDs, and place a masked call in minutes.
</Card>

## How Vobiz handles number masking

[Vobiz](/docs/introduction) is the telephony infrastructure that makes masking a few lines of XML rather than a carrier project. You bring the routing logic; Vobiz owns the DIDs, terminates the call, and performs the bridge.

* **The whole mechanism is one `<Dial callerId=…>`** returned from your webhook, all number-mapping data stays on your backend.
* **Instant DIDs in 130+ countries** via [eKYC](/docs/sub-accounts/kyc/overview), with outbound to 190+ countries, no 4–8 week carrier paperwork.
* **Sub-80 ms, single-hop latency** (legacy CPaaS is 300–400 ms), so the bridge feels instant and your webhook has timeout headroom.
* **3M+ calls/day at 99.99% uptime and 4.2+ MOS**, masking traffic is bursty, and the platform scales with it.
* **Composable:** [recording](/docs/solutions/call-recording), [logs and analytics](/docs/platform/voice/call-logs), [IVR](/docs/solutions/cloud-ivr), and [call transfer](/docs/solutions/call-transfer) all layer onto the masked call.
* **Compliant by design:** TLS 1.3, SRTP, TRAI-compliant, DPDP/GDPR/HIPAA aligned.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is number masking in simple terms?">
    Number masking puts a virtual phone number between two people so they can call each other without seeing each other's real number. Each party dials a proxy number, and the platform connects them in the middle while showing only the proxy as caller ID.
  </Accordion>

  <Accordion title="What is the difference between one-way and two-way number masking?">
    One-way masking hides a single party (for example, hiding an agent's number on outbound calls). Two-way masking hides both parties and works in both directions, so either side can initiate and neither learns the other's number. Two-way masking typically uses two masking numbers, one per direction.
  </Accordion>

  <Accordion title="Why does two-way masking need two phone numbers?">
    A single masking number cannot tell which direction a call should go, if both parties dial the same number, the routing logic cannot distinguish "connect to customer" from "connect to agent." Two numbers encode direction in the number that was dialed: one routes agent→customer, the other customer→agent.
  </Accordion>

  <Accordion title="Can the masked connection be turned off after a transaction?">
    Yes. Because routing is decided by your backend on every call, you can expire the number mapping when a ride ends or an order is delivered. After expiry, dialing the masking number no longer connects the parties.
  </Accordion>

  <Accordion title="Is number masking legally required?">
    No single law names masking as mandatory. But privacy regulations, GDPR in the EU, CCPA/CPRA and HIPAA in the US, and the DPDP Act in India, treat a phone number as protected personal data and require data minimization and privacy by design. Masking is the standard way to meet those duties, and in India it is also the compliant way to set caller ID (you must use a DID you own).
  </Accordion>

  <Accordion title="How do I build number masking with Vobiz?">
    Provision two masking DIDs, attach them to a Vobiz application with an Answer URL, and write a webhook that resolves the dialed number to a destination and returns a <code>{'<Dial callerId="…">'}</code> instruction. Our <a href="/docs/examples/vobiz-two-way-number-masking-python">Python tutorial</a> is a complete, runnable reference.
  </Accordion>
</AccordionGroup>

## Sources

* [RFC 3261 - SIP: Session Initiation Protocol](https://www.rfc-editor.org/rfc/rfc3261) (IETF)
* [Caller ID](https://en.wikipedia.org/wiki/Caller_ID) (Wikipedia)
* [GDPR Article 4 - Definitions (personal data)](https://gdpr-info.eu/art-4-gdpr/) · [Article 5 - data minimisation](https://gdpr-info.eu/art-5-gdpr/) · [Article 25 - data protection by design and by default](https://gdpr-info.eu/art-25-gdpr/)
* [California Consumer Privacy Act (CCPA / CPRA)](https://oag.ca.gov/privacy/ccpa) (California Attorney General)
* [Telephone Consumer Protection Act of 1991 (TCPA)](https://en.wikipedia.org/wiki/Telephone_Consumer_Protection_Act_of_1991) · [Digital Personal Data Protection Act, 2023](https://en.wikipedia.org/wiki/Digital_Personal_Data_Protection_Act,_2023) (India)

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and place your first programmable call in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.