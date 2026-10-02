> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Toll-Free vs Local vs Mobile Numbers: The 2026 Guide

> Toll-free vs local vs mobile numbers compared: US prefixes, area codes, A2P/10DLC, SMS deliverability, cost, caller perception, and when to use each type.

*June 19, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

The choice between **toll-free vs local** (and, increasingly, mobile) numbers shapes how customers perceive your business, who pays for the call, and whether your texts even get delivered. These are the three **types of phone numbers** most US businesses pick between when they stand up a phone line, a contact center, or a voice AI agent, and they are not interchangeable. A toll-free number signals national scale and shifts call costs to you. A local number reads as a real neighbor and lifts answer rates. A mobile number is what your customers carry in their pocket, and in the US it is governed by a completely different messaging rulebook.

This guide goes past the marketing copy: the exact US toll-free prefixes (800/888/877/866/855/844/833), how NPA-NXX area codes encode local presence, why the US has no distinct "mobile" prefix, how A2P/10DLC and toll-free verification gate SMS deliverability, a 14-row comparison table, decision rules for each use case, and how a programmable telephony layer like [Vobiz](/docs/introduction) provisions all three.

<Note>
  **Key takeaways**

  * **Toll-free** numbers (US prefixes **800, 888, 877, 866, 855, 844, 833**) are free to the caller because the *receiving business pays*; they signal national, established scale.
  * **Local** numbers are tied to a geographic **area code (NPA-NXX)** and read as a real neighbor, which measurably lifts outbound answer rates.
  * The US has **no distinct mobile prefix** - a mobile number looks like any local 10-digit number; what differs is **A2P/10DLC registration** for business texting and reliable handset reachability.
  * For **SMS deliverability**, the type matters: toll-free needs *toll-free verification*, local/mobile business texting needs *10DLC registration*, and short codes are a separate high-throughput lane.
  * With [Vobiz](/docs/introduction) you provision local, mobile, and toll-free numbers from one API at a flat **₹0.65/min both ways** and point them at any voice AI stack (Vapi, Retell, ElevenLabs, Pipecat, LiveKit).
</Note>

## What is a toll-free number?

A [toll-free telephone number](https://en.wikipedia.org/wiki/Toll-free_telephone_number) is a number that is **free for the caller to dial - because the business that owns it pays for the inbound call** instead. The defining mechanic is the reversed billing: on the legacy network this was "inbound WATS," and the principle survives today. As the encyclopedic reference on the North American Numbering Plan notes, "calls to the toll-free numbers are charged to the receiving party, and are free to the caller if dialed from land-line telephones, but may incur mobile airtime charges for cellular service."

In the US and the rest of the North American Numbering Plan, toll-free numbers are identified by a fixed set of **3-digit prefixes** that sit where an area code normally would:

| Prefix | Status |
| - | - |
| **800** | The original toll-free code (in service since the 1960s) |
| **888** | Active |
| **877** | Active |
| **866** | Active |
| **855** | Active |
| **844** | Active |
| **833** | Active (most recently opened) |

Future codes - **822, 880–887, and 889** - are [reserved for toll-free use](https://en.wikipedia.org/wiki/Toll-free_telephone_numbers_in_the_North_American_Numbering_Plan) but not yet in general circulation. Note that **888, 877, 866, etc. are not interchangeable with 800**: 1-800-555-0100 and 1-888-555-0100 are *different numbers* that may belong to different owners.

**How they are assigned.** Toll-free numbers are not "bought" like a domain; they are administered through a shared registry. A [Responsible Organization (RespOrg)](https://en.wikipedia.org/wiki/Toll-free_telephone_numbers_in_the_North_American_Numbering_Plan) reserves and points each number in the SMS/800 database, the central system overseen under FCC contract. The registry is run today by [Somos](https://www.somos.com/), the official toll-free numbering administrator. This is why a provider effectively acts as your RespOrg when you order a toll-free number.

**Vanity numbers.** Because toll-free prefixes are memorable, businesses often pay for a **vanity** number that spells a word on the keypad (1-800-FLOWERS). Vanity numbers are a marketing asset: easier to recall on radio, billboards, and packaging, at the cost of limited availability.

**Toll-free is not a feature of one country.** Other countries have their own freephone ranges (the UK's 0800, India's 1800 series), and there is even a **Universal International Freephone Number (UIFN)** scheme for a single number that works across participating countries. This guide focuses on the US/NANP system.

## What is a local number?

A local number is a standard **geographic** number tied to a specific city or region through its area code. In the [North American Numbering Plan](https://en.wikipedia.org/wiki/North_American_Numbering_Plan), every 10-digit number follows the **NPA-NXX-XXXX** structure:

* **NPA** - the 3-digit *Numbering Plan Area*, i.e. the **area code** (212 for Manhattan, 415 for San Francisco, 312 for Chicago).
* **NXX** - the 3-digit *central office / exchange* code, historically the local switch serving a neighborhood.
* **XXXX** - the 4-digit *subscriber number* that identifies the specific line.

The whole address scheme rolls up into the global [E.164](https://en.wikipedia.org/wiki/E.164) standard, where a US number becomes `+1` (country code) followed by the 10 NANP digits.

The strategic value of a local number is **local presence**. When you call someone from a number that shares their area code, the call reads as a neighbor rather than an unknown national entity. In outbound and contact-center work this is a real, measurable effect: matching the recipient's area code lifts answer and pickup rates compared with an unfamiliar or out-of-region number. That's why a realtor, a clinic, or a regional sales team will deliberately use a number in the same area code as the customers they serve.

**Local numbers are not limited to one location.** Cloud telephony decouples the number from a physical exchange, so a single business can hold local numbers in dozens of area codes - a "virtual local presence" in every market it sells into - without an office in any of them. You provision them from inventory the same way you would any number; with Vobiz you [purchase a local number from inventory](/docs/account-phone-number/purchase-from-inventory) and assign it to an application in minutes.

## What is a mobile number?

Here is the fact that trips up most people coming from outside the US: **the United States has no distinct mobile-number prefix.** Unlike India (where mobile numbers start with a 6–9 series) or the UK (07…), a US mobile number is drawn from the *same* NPA-NXX geographic pool as a landline or VoIP number. You generally **cannot tell from the digits alone** whether `+1 415 555 0100` rings a desk phone, a cell phone, or a cloud number. This is a consequence of [number portability](https://en.wikipedia.org/wiki/North_American_Numbering_Plan): a subscriber can carry a number from a landline carrier to a mobile carrier and back.

So what does "mobile number" actually mean operationally in the US? Two things:

1. **Handset reachability.** A mobile number terminates on a smartphone the customer carries, so it is reachable anywhere with coverage - ideal for two-way conversations, missed-call return, and SMS/RCS that the person reads within minutes.
2. **A2P / 10DLC for business texting.** When a *business* (an Application) sends SMS to *people* (Person) over an ordinary local/mobile-style 10-digit number, US carriers require the traffic to run on **10DLC** - Application-to-Person 10-Digit Long Code. To send A2P traffic you must **register your brand and each campaign** with The Campaign Registry; only then do carriers grant the throughput and protect deliverability. Unregistered A2P traffic over a long code is increasingly filtered or blocked.

This A2P regime is why "which number type can I text from?" has a non-obvious answer in the US - it depends less on the digits and more on **registration**:

* **Local / mobile-style long codes** → business texting requires **10DLC registration** (brand + campaign vetting). Best for conversational, locally branded messaging.
* **Toll-free numbers** → can send SMS, but require separate **toll-free verification** to reach full carrier deliverability. Good for nationwide, mid-volume A2P.
* **Short codes** → a dedicated 5–6 digit number purpose-built for the *highest* SMS throughput (think bank OTP at scale); not tied to an area code, voice-incapable, and the most expensive/slowest to provision.

Mobile reachability and the A2P rulebook are exactly why message-heavy fintech and commerce flows live or die on getting the number type *and* its registration right.

## Toll-free vs local vs mobile: the key differences

| Dimension | Toll-free | Local | Mobile (US) |
| - | - | - | - |
| **US identifier** | 800/888/877/866/855/844/833 prefix | Geographic area code (NPA-NXX) | No distinct prefix - looks like a local 10-digit number |
| **Who pays for the call** | The business (receiving party) | The caller (standard rates) | The caller / their plan |
| **Caller perception** | National, established, "real company" | Local neighbor, regional trust | Personal, immediate |
| **Best for inbound** | Nationwide support / sales lines | Region-specific service | Direct two-way contact |
| **Outbound answer rate** | Lower (reads as marketing) | Higher (area-code match) | High (personal) |
| **Geographic tie** | None (national) | Tied to an area code | None (portable) |
| **SMS capable** | Yes (with toll-free verification) | Yes (with 10DLC registration) | Yes (with 10DLC registration) |
| **A2P registration** | Toll-free verification | 10DLC (brand + campaign) | 10DLC (brand + campaign) |
| **Vanity option** | Yes (1-800-FLOWERS) | Limited | No |
| **Coverage** | National + some international freephone | One region (provision many for multi-market) | National |
| **Provisioning** | RespOrg / registry-administered | From inventory, instant | From inventory, instant |
| **Voice AI fit** | National IVR & support agents | Local-presence outbound agents | Personal reminders / follow-ups |
| **Typical use case** | Customer service hotlines | Field sales, clinics, local CX | OTP, alerts, conversational SMS |
| **One non-obvious gotcha** | Calls from cell phones may use the caller's airtime | Number ≠ physical office; register E911 address | Digits don't reveal it's mobile |

## When to use which

### Use a toll-free number when…

You want a **single national line** that signals scale and removes any cost barrier to the customer. Toll-free is the classic choice for **support and sales hotlines** printed on packaging, websites, and ads, especially for a brand selling across the whole country. It is also the right pick when you want a **memorable vanity** number for offline marketing. The trade-offs: callers increasingly recognize toll-free as "a company line" (which can *lower* outbound answer rates), and the cost of the call sits with you.

### Use a local number when…

You are doing **region-specific** work or **outbound** calling where pickup rate matters. A local number that matches the recipient's area code reads as a neighbor and consistently out-answers a toll-free or unknown number, the reason field sales, recruiting, clinics, and local service businesses lean local. It is also right when you want to project presence in **multiple markets**: provision a local number per metro and route them all into one [voice application](/docs/platform/voice/applications). For business SMS from a local number, plan for [10DLC registration](https://en.wikipedia.org/wiki/North_American_Numbering_Plan) up front.

### Use a mobile-style number / mobile reachability when…

Your value is in **two-way, conversational** contact a person will pick up or read on their phone, OTP delivery, appointment reminders, delivery updates, and conversational SMS. In the US this is a local 10-digit number on a 10DLC campaign; the "mobile" part is about *reachability and texting behavior*, not the prefix. If you need very high SMS throughput (large OTP or alert volumes), evaluate a **short code** instead of a single long code.

### Use more than one (the realistic answer)

Most serious deployments use a mix: a **toll-free** main line for national inbound, a **bank of local numbers** for outbound presence per region, and **10DLC-registered** numbers for the SMS layer. The point of a programmable platform is that you can hold all three behind one API and one set of routing rules.

## How Vobiz handles numbers

[Vobiz](/docs/introduction) is **telephony infrastructure** - the programmable rails under your phone system or voice AI agent, not an agent or CX suite itself. It powers voice-AI builders (Vapi, Retell AI, ElevenLabs, Pipecat, LiveKit) and runs the numbers, SIP, and Voice API beneath them. On number types specifically:

* **All number types from one API.** Provision **local, mobile, toll-free, and enterprise** numbers through a [unified phone-number API](/docs/account-phone-number) - [browse inventory](/docs/account-phone-number/list-inventory-numbers) and [purchase from inventory](/docs/account-phone-number/purchase-from-inventory) - instead of separate workflows per type.
* **Instant, self-serve provisioning.** Numbers, DIDs, and APIs are provisioned in **minutes via eKYC**, not the 4–8 weeks of paperwork legacy carriers require. **DID provisioning in 130+ countries**; **outbound connectivity to 190+ countries**.
* **Flat, symmetric pricing.** A single **₹0.65/min (65 paise)** rate for **both inbound and outbound** - no inbound/outbound asymmetry - with enterprise pricing above \~50,000 minutes/month.
* **Built for voice AI.** Point any number at a [voice application](/docs/platform/voice/overview) over [SIP](/docs/platform/sip/overview) or WebSocket with **sub-80 ms** single-hop latency, barge-in, bidirectional streaming, and outbound L16 playback at up to 24 kHz.
* **Programmable routing on every number.** Layer IVR, call transfer, recording, and dynamic routing through the [Voice API](/docs/blogs/what-is-a-voice-api) regardless of whether the number is toll-free, local, or mobile.
* **Reliable at scale.** 99.99% uptime, 4.2+ MOS, with SRTP/TLS 1.3 encryption - the same rails that fintechs like Razorpay and Acko, enterprises like KPMG, and voice-AI builders like Bolna run on.

A toll-free hotline, a fleet of local outbound numbers, and a 10DLC texting layer can all live behind the same Vobiz account and routing logic.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="Is toll-free or local better for business?">
    Neither is universally better - it depends on direction and intent. **Toll-free** is better for a single national inbound hotline that signals scale and removes the caller's cost. **Local** is better for region-specific service and for outbound calling, where an area-code match lifts answer rates. Many businesses use both.
  </Accordion>

  <Accordion title="What are the US toll-free prefixes?">
    The active US toll-free prefixes are **800, 888, 877, 866, 855, 844, and 833**. They are not interchangeable: 1-800 and 1-888 versions of the same digits are different numbers. Codes like 822, 880–887, and 889 are reserved for future toll-free use.
  </Accordion>

  <Accordion title="Can you tell if a US number is a mobile number?">
    Usually not from the digits alone. The US has no distinct mobile prefix - mobile, landline, and VoIP numbers all come from the same geographic NPA-NXX pool, and numbers can be ported between line types. You need a carrier/HLR lookup to determine the current line type.
  </Accordion>

  <Accordion title="Which number type can I send business SMS from?">
    All three can send SMS, but with different rules. Local and mobile-style **long codes** require **10DLC** brand + campaign registration. **Toll-free** numbers require separate **toll-free verification**. For the highest throughput, a dedicated **short code** is a separate option. Registration, not the prefix, is what gates deliverability.
  </Accordion>

  <Accordion title="Who pays for a toll-free call?">
    The business that owns the toll-free number pays for the inbound call, which is why it's free to the caller. Note that calls placed from a mobile phone may still consume the caller's plan minutes even though no separate long-distance charge applies.
  </Accordion>

  <Accordion title="Do local numbers work for a business in multiple cities?">
    Yes. Cloud telephony decouples a number from a physical exchange, so you can hold local numbers in many area codes at once and route them all into one application - a virtual local presence in every market without a physical office there.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [What is a landline number?](/docs/blogs/what-is-a-landline-number) · [What is a Voice API?](/docs/blogs/what-is-a-voice-api) · [What is VoIP?](/docs/blogs/what-is-voip)
* [Phone numbers overview](/docs/account-phone-number) · [Purchase a number from inventory](/docs/account-phone-number/purchase-from-inventory) · [List inventory numbers](/docs/account-phone-number/list-inventory-numbers)
* [Voice platform overview](/docs/platform/voice/overview) · [SIP trunking overview](/docs/platform/sip/overview) · [Vobiz introduction](/docs/introduction)

## Sources

* Wikipedia, ["Toll-free telephone number"](https://en.wikipedia.org/wiki/Toll-free_telephone_number).
* Wikipedia, ["Toll-free telephone numbers in the North American Numbering Plan"](https://en.wikipedia.org/wiki/Toll-free_telephone_numbers_in_the_North_American_Numbering_Plan).
* Wikipedia, ["North American Numbering Plan"](https://en.wikipedia.org/wiki/North_American_Numbering_Plan).
* Wikipedia, ["E.164"](https://en.wikipedia.org/wiki/E.164).
* Somos, ["Toll-Free numbering administrator"](https://www.somos.com/).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a local, mobile, or toll-free number and place your first programmable call in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.