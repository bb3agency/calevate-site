> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Number Masking

> Connect two parties through proxy DIDs so neither sees the other's real number, two-way call masking for ride-hailing, delivery, and marketplaces on Vobiz.

## What is Number Masking?

Number masking connects two people over a phone call without revealing either person's real number. Instead of dialing each other directly, both parties dial a **masking number** - a virtual DID you control - and Vobiz bridges the call in the middle, showing only the masking number as caller ID. The driver never gets the rider's number, the delivery agent never gets the customer's, and once the transaction is over, the connection can be switched off entirely.

It is the privacy layer behind nearly every two-sided marketplace: ride-hailing, food and grocery delivery, classifieds, real estate, dating, and field services all use it so two strangers can coordinate a real-world handoff without permanently exchanging contact details.

With Vobiz, masking is a real-time application decision. When a masking number is dialed, Vobiz calls your server, your backend decides who the call is really for and what caller ID to show, and returns a single [`<Dial>`](/docs/xml/dial) instruction. You keep all the number-mapping logic and data on your own infrastructure.

## The Problem It Solves

A phone number is permanent, personally identifiable information. The moment one party hands it to another, it can be saved, shared, scraped, or sold - and the other person can call or message forever. For two-sided platforms this is a real liability: delivery partners and drivers face harassment, customers get spam, and the business carries the privacy and compliance risk of exposing personal numbers it never needed to expose.

Number masking removes the exposure at the source. Because the only number that ever appears on either handset is a DID you own, the real numbers stay private on your backend. And because routing is decided fresh on every call, you can **expire the mapping** when the ride ends or the order is delivered - turning a permanent contact detail into a temporary, revocable channel. That is data minimization in practice, the posture that regimes like India's DPDP Act and the GDPR expect.

## How Vobiz Powers Number Masking

For true two-way masking you provision **two** masking DIDs and attach both to a single Vobiz [application](/docs/platform/voice/applications) with an Answer URL. When either number is dialed, Vobiz POSTs the call details (`From`, `To`) to your webhook. Your server resolves the dialed number to a real destination, authorizes the caller, and returns telephony XML that bridges the call while overriding the caller ID with your masking number.

The mechanism is deliberately simple - a two-row lookup keyed by the number that was dialed, with **cross-mapped caller IDs** so each party always sees one consistent number for the other:

| Dialed number | Allowed caller | Bridges to | Caller ID shown |
| - | - | - | - |
| `M1` | the agent | the customer | `M2` |
| `M2` | the customer | the agent | `M1` |

Two numbers, rather than one, is what lets the system encode *direction* reliably: a single number can't tell "connect to the customer" from "connect to the agent" when both parties dial it. The agent always dials `M1` and sees `M2` for the customer; the customer always dials `M2` and sees `M1` for the agent.

Everything composes with the masked leg when you need it - [call recording](/docs/solutions/call-recording) for quality and disputes, a [cloud IVR](/docs/solutions/cloud-ivr) greeting before bridging, [call logs and analytics](/docs/platform/voice/call-logs), and [call transfer](/docs/solutions/call-transfer). Vobiz's sub-80 ms, single-hop architecture keeps the bridge feeling instant and leaves your webhook plenty of headroom inside the timeout budget, and DIDs provision self-serve in 130+ countries.

<Card title="Build it: two-way number masking (Python)" icon="code" href="/docs/examples/vobiz-two-way-number-masking-python">
  A complete FastAPI reference, clone, configure two DIDs, and place a masked call in minutes.
</Card>

## Use Cases & Scenarios

* **Ride-hailing and mobility.** A driver and rider coordinate the pickup point through masking numbers. After drop-off, the platform expires the mapping so neither can contact the other again - eliminating post-ride harassment in both directions.
* **Food and grocery delivery.** A delivery partner calls to confirm the gate or a substituted item while the customer's number stays private. Once delivered, the connection is cut off, and the business retains the call log for support without ever exposing personal numbers.
* **Online marketplaces and classifieds.** Buyers and sellers negotiate over the phone through a listing-bound masking number, so numbers can't be harvested for spam and the conversation stays inside the platform.
* **Real estate and rentals.** Prospective tenants and brokers talk about a property without the broker building a contact list of leads to cold-call later.
* **Field services and healthcare.** Technicians, dispatchers, and patients coordinate ETAs and appointments from a masked business number, protecting both the staff member's and the customer's personal lines.

## Why Choose Vobiz?

Vobiz gives you the masking primitive - a `<Dial>` with a `callerId` override returned from your own webhook - and gets out of the way. The number-to-number mapping, the authorization rules, and the lifecycle (create the pairing when a transaction starts, expire it when it ends) all live on your backend; Vobiz never asks you to hand over your customers' numbers. You provision masking DIDs instantly through eKYC instead of waiting weeks on carrier paperwork, the platform runs on India-first, sub-80 ms infrastructure that keeps bridges crisp under bursty marketplace traffic, and TLS 1.3 signaling with SRTP media plus TRAI/DPDP/GDPR/HIPAA alignment gives a privacy feature the compliance footing it needs.

<Card title="Learn how number masking works" icon="book-open" href="/docs/blogs/what-is-number-masking">
  The full explainer, one-way vs two-way, the direction problem, and a step-by-step call flow.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.