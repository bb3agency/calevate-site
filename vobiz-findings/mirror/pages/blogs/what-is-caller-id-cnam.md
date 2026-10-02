> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is Caller ID and CNAM? How Caller Name Display Works (2026)

> Caller ID shows the number; CNAM shows the name. How the CNAM dip against LIDB works, the 15-char limit, STIR/SHAKEN, branded calling, and answer rates.

*July 1, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

Caller ID is the line of text a phone shows before you answer: usually a number, and sometimes a name. CNAM (Caller ID Name) is the piece that turns that number into a name like "ACME BANK" or "Razorpay." The two are constantly conflated, but they are different mechanisms, controlled by different parties, and understanding the split is the difference between calls that get answered and calls that get ignored or flagged as spam.

This guide goes past the dictionary version: what caller ID actually transmits, what CNAM is and where the name really comes from, how the CNAM "dip" against the LIDB database works in the United States, the 15-character limit nobody warns you about, how caller ID relates to branded calling and STIR/SHAKEN, and why all of this decides your answer rate, with a specific lens on what matters when the call carries a voice AI agent.

<Note>
  **Key takeaways**

  * **Caller ID** is the signaling that delivers the calling number (and optionally a name); **CNAM** is the separate database lookup that resolves that number to a displayed name.
  * The displayed name is **not set by the caller** in the US, the recipient's carrier looks it up via a **CNAM "dip"** against the [LIDB](https://en.wikipedia.org/wiki/Line_Information_Database) database, and it is **capped at \~15 characters**.
  * CNAM is **US-centric** and **legacy**; the modern successors are **branded calling** (logo, name, reason) and **[STIR/SHAKEN](https://en.wikipedia.org/wiki/STIR/SHAKEN)** call attestation.
  * Caller ID, name, and attestation together drive **answer rates** and whether carriers label your number "Spam Likely."
  * Vobiz is the **telephony infrastructure** under this, managing number reputation and presentation so your agent's calls actually connect; it does not replace your agent.
</Note>

## What is caller ID?

Caller ID is the telephone-network feature that delivers information about the calling party to the called party before, or as, the call is answered. On the legacy network it is transmitted as data between the first and second ring; on IP networks it travels inside the SIP signaling that sets up the call. [Caller ID can convey two distinct things](https://en.wikipedia.org/wiki/Caller_ID): **Calling Number Identification** (the number, sometimes called CNID) and **Calling Name Presentation** (the name, the part handled by CNAM).

The one distinction that matters: **the number and the name are delivered by different mechanisms.** The calling number rides along with the call signaling itself. The name does **not**, in the North American system, the originating carrier typically sends only the number, and the *receiving* side fills in the name from a database. That single architectural fact explains almost every "why does my business name not show up?" question in telephony.

There is also a privacy dimension. A caller can request that their number be withheld (Calling Line Identification Restriction, the `*67` prefix in the US), in which case the recipient sees "Private," "Restricted," or "Blocked" instead of the number. When you place programmable calls, the number you present is your [caller ID](/docs/account-phone-number), and choosing and managing those numbers well is the foundation of everything below.

## What is CNAM?

**CNAM stands for Caller ID Name** (the underlying standard is **Calling Name Presentation, or CNAP**). It is the system that resolves a phone number into the human-readable name shown on the recipient's screen, "ACME BANK," "CITY HOSPITAL," "J SMITH." Where the number is part of the call, the name is a *lookup result*.

Here is the part most people get wrong: **CNAM is not a field you fill in on the outbound call.** In the US, you do not "send" your name with the call. Instead, your number is registered, with a 15-character name string, in a distributed set of carrier-operated databases. When you call someone, *their* carrier looks up *your* number in those databases and renders whatever name it finds. So two different recipients on two different carriers can see two different names (or no name at all) for the exact same call, because each carrier decides whether and where to perform the lookup.

CNAM is also distinctly **a North American (primarily US) feature**. Much of the rest of the world either has no name-display layer or implements it differently, in Canada and some other systems the originating side can assert the name. Understanding that CNAM is US-centric, carrier-controlled, and database-driven is the key to using it.

## How caller ID and CNAM work (the CNAM "dip")

When a call comes in, here is the actual sequence on the North American network:

1. **The call is signaled.** The originating carrier sends the call toward the destination, carrying the **calling number** (and, increasingly, a STIR/SHAKEN attestation token, more below).
2. **The terminating carrier decides whether to do a name lookup.** Displaying a name is the *receiving* carrier's job and cost, not the caller's. Some carriers always dip; some never do; many do it selectively.
3. **The CNAM "dip."** To get the name, the terminating carrier queries a CNAM database, an action called a **dip**. The authoritative store is the **[Line Information Database (LIDB)](https://en.wikipedia.org/wiki/Line_Information_Database)**, a set of regional carrier-run databases that map numbers to name records. Each lookup costs a small **dip fee**, [commonly in the range of $0.002 to $0.006 per query](https://en.wikipedia.org/wiki/Calling_Name_Presentation).
4. **The name is rendered, truncated to \~15 characters.** [CNAM records are limited to short strings, typically up to 15 characters](https://en.wikipedia.org/wiki/Calling_Name_Presentation), including spaces. "ACME FINANCIAL SERVICES LLC" does not fit, you get something like "ACME FINANCIAL." Choosing that 15-character string is a real decision.

A few consequences fall straight out of this design:

* **Who controls the name:** the company that owns the number sets the CNAM record (via their carrier or number provider), but the *terminating* carrier decides whether to display it. Control is split.
* **Why names disagree across carriers:** different carriers dip different databases, with different propagation lag, so updates can take time and may never reach every carrier uniformly.
* **Why mobile is unreliable:** to save on dip fees, many mobile carriers historically did *not* perform CNAM dips at all, which is a big reason your business name often fails to appear on mobile phones, the dominant device today.
* **The cost asymmetry:** the caller pays to *store* a name; the recipient's carrier pays to *display* it. That economic split is why CNAM coverage is patchy.

This is the legacy mechanism, and its limits (mobile gaps, 15 characters, no proof the name is true) are exactly what branded calling and STIR/SHAKEN were created to fix.

## Caller ID vs CNAM vs branded caller ID

These three layers stack on top of each other. They are not alternatives so much as successive generations of "tell the recipient who's calling."

| | Caller ID (number) | CNAM (name) | Branded caller ID |
| - | - | - | - |
| **What it shows** | The calling phone number | A short text name | Verified name, logo, call reason |
| **Where the value lives** | In the call signaling | In carrier databases (LIDB) | In a branded-calling registry / display service |
| **Who sets it** | The caller / number owner | Number owner registers; carrier displays | Brand, after vetting |
| **Who displays it** | Recipient's device | Terminating carrier (the "dip") | Carrier + device app (Android/iOS) |
| **Length limit** | Number (E.164) | \~15 characters | Full name + logo |
| **Truthfulness** | Spoofable | Spoofable; unverified | Vetted / verified brand |
| **Coverage** | Near-universal | US-centric, patchy on mobile | Carrier- and device-dependent |
| **Cost model** | Bundled with the call | Storage + per-dip fees | Brand pays for vetting/display |
| **Era** | 1980s onward | 1990s onward | 2020s, current |

The progression is clear: caller ID answers "what number," CNAM tries to answer "what name" (badly, on mobile), and **branded calling** answers "what verified brand, with a logo and a reason for calling." Branded calling is the direction the industry is moving, the major carriers have aligned on shared **[Branded Calling ID](https://www.ctia.org/news/branded-calling-id-launch)** programs to present vetted business identity on the screen. It depends on the call being authenticated, which is where STIR/SHAKEN comes in.

## STIR/SHAKEN, spam labeling, and call attestation

CNAM and caller ID share a fatal flaw: the number can be **spoofed**. Robocallers forge caller ID to impersonate banks, agencies, and even your local area code ("neighbor spoofing"). The industry's answer is **STIR/SHAKEN**, a framework for cryptographically signing the calling number so the receiving network can verify it was not forged.

* **STIR** (Secure Telephone Identity Revisited) is the set of IETF standards. The core mechanism is a signed token, **PASSporT**, defined in [RFC 8224](https://www.rfc-editor.org/rfc/rfc8224), that carries the asserted calling identity through the SIP signaling.
* **SHAKEN** is the deployment profile for carriers, specified in [RFC 8588](https://www.rfc-editor.org/rfc/rfc8588). It adds an **attestation** claim to the token, the originating carrier states how confident it is that the caller is entitled to use that number:
  * **Full (A) attestation** - the carrier knows the customer and verified they own the number.
  * **Partial (B) attestation** - the carrier knows the customer but not the number.
  * **Gateway (C) attestation** - the carrier just passed the call through; it can vouch for nothing.

In the US, the FCC has [mandated STIR/SHAKEN as the framework for combating spoofed robocalls](https://www.fcc.gov/call-authentication), and attestation level now influences how downstream carriers treat a call. A call with **A-level attestation** from a number with a clean history is far more likely to be delivered cleanly; a poorly-attested call from a number with abuse complaints is the one that gets a red **"Spam Likely"** or **"Scam Likely"** label, applied by carrier analytics partners and shown on the recipient's screen.

This is the crucial 2026 reality: **caller ID, CNAM, attestation, and number reputation are now evaluated together.** Getting the name right (CNAM) means little if your number is poorly attested or has a bad reputation, the carrier will label it regardless. Presentation and trust are now one problem.

## Why caller ID matters for answer rates

Every layer above exists for one commercial reason: **people answer calls they trust and ignore calls they don't.** An unknown number, a missing name, or a "Spam Likely" tag is a connection you paid to place and will never recover. For any outbound program, support callbacks, appointment reminders, [automated outbound calling](/docs/solutions/automated-outbound-calling), and especially a voice AI agent that only delivers value once the call connects, presentation directly drives ROI.

Three things move the needle, in order of impact:

1. **Number reputation.** Carriers and their analytics partners score each number on call patterns, volume, duration, and complaints. A number that dials thousands of one-second calls gets flagged fast. Good [number utilization](/docs/best-practices/number-utilization), rotating numbers sensibly, not over-dialing a single DID, keeping connect rates healthy, is the single biggest lever.
2. **Attestation.** Calls signed with Full (A) attestation from a number you legitimately own clear carrier filters more reliably than unauthenticated traffic.
3. **Name and brand presentation.** A correct, recognizable CNAM name, and, increasingly, a branded-calling identity, lifts answer rates when the recipient's carrier actually displays it.

A note on numbers: we don't quote a universal "branded calling lifts answer rates by X%" figure, those statistics are vendor-specific and vary wildly by industry. What is consistent and verifiable is the *mechanism*: flagged and nameless numbers are answered less, and reputation plus attestation determine flagging. Vobiz's own measured result on the infrastructure side is a **30% reduction in spam-flag rate** for traffic on its network, achieved by managing reputation and presentation at the carrier layer rather than leaving it to chance.

## How Vobiz handles caller ID and reputation

[Vobiz](/docs/introduction) is the **telephony infrastructure** beneath voice applications, the rails that carry your calls to the public network. It does not build the AI agent or the dialer; it powers them. Voice-AI builders on Vapi, Retell, ElevenLabs, Pipecat, and LiveKit, and enterprises like KPMG, Razorpay, and Acko, run their calls over Vobiz so that caller ID, attestation, and reputation are handled correctly at the carrier layer.

* **Number provisioning and presentation.** Self-serve, instant [phone number](/docs/account-phone-number) provisioning via eKYC, DIDs in **130+ countries** and outbound connectivity to **190+**, with all number types (local, mobile, toll-free, enterprise series). The number you present as caller ID is yours to choose and manage from one [purchase flow](/docs/account-phone-number/purchase-from-inventory).
* **Number reputation management.** Vobiz delivers a **30% reduction in spam-flag rate** by managing number reputation at the network level, and its [number utilization](/docs/best-practices/number-utilization) guidance helps you keep DIDs healthy so they don't get labeled.
* **Clean, direct-carrier routing.** A single-hop, direct-carrier-connect architecture at **sub-80 ms** latency and **4.2+ MOS** call quality, across **3M+ calls/day** at **99.99% uptime**, means well-presented calls also sound clean when answered.
* **Programmable control over the call.** Once a call connects, route it with [`<Dial>`](/docs/xml/dial), branch with an [IVR](/docs/solutions/cloud-ivr), [transfer](/docs/solutions/call-transfer) it, or [record](/docs/solutions/call-recording) it, all from the [Voice API](/docs/blogs/what-is-a-voice-api) and [VobizXML](/docs/xml/response).
* **India-first compliance.** For Indian traffic, Vobiz is TRAI-compliant with [DLT registration](/docs/best-practices/dlt-registration) support and built-in [calling-regulation](/docs/compliance/india/calling-regulations) guardrails, the regional equivalent of getting your presentation and consent right.
* **Infrastructure, not a walled garden.** Vobiz powers *your* agent and *your* numbers. It manages the rails, caller ID, reputation, attestation-ready routing, so your application controls the conversation.

For the deeper context on reputation and contact strategy, see Vobiz's notes on [number utilization](/docs/best-practices/number-utilization), the [outbound campaign manager](/docs/best-practices/outbound-campaign-manager), and the [contact centre](/docs/solutions/contact-centre) stack.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is the difference between caller ID and CNAM?">
    Caller ID is the broad feature that delivers information about the calling party, primarily the calling number, in the call signaling. CNAM (Caller ID Name) is the separate database lookup that resolves that number to a displayed name. The number travels with the call; the name is looked up by the recipient's carrier.
  </Accordion>

  <Accordion title="Who controls the name that shows up on caller ID?">
    In the US, the number's owner registers a CNAM record (up to \~15 characters) through their carrier or number provider, but the recipient's terminating carrier decides whether to perform a lookup (a "dip") and display it. Control is split, which is why the same call can show different names on different carriers.
  </Accordion>

  <Accordion title="What is a CNAM dip?">
    A CNAM dip is a query the terminating carrier makes against a caller-name database (the LIDB) to turn an incoming number into a displayed name. Each dip costs a small fee, commonly $0.002 to $0.006, which is why many mobile carriers skip it and your business name often fails to appear on mobile phones.
  </Accordion>

  <Accordion title="Why isn't my business name showing on caller ID?">
    Usually because the recipient's carrier did not perform a CNAM dip (common on mobile to save fees), your CNAM record hasn't propagated to that carrier's database, or your name exceeds the \~15-character limit. Branded calling and STIR/SHAKEN attestation are the modern fixes for reliable, verified name display.
  </Accordion>

  <Accordion title="Is CNAM the same as STIR/SHAKEN?">
    No. CNAM displays a name; STIR/SHAKEN cryptographically verifies that the calling number was not spoofed. CNAM answers "what name," STIR/SHAKEN answers "is this number authentic." A trustworthy call increasingly needs both, plus a clean number reputation, to avoid a "Spam Likely" label.
  </Accordion>

  <Accordion title="Does caller ID and CNAM work outside the United States?">
    Caller ID (the number) is near-universal worldwide, but CNAM as a carrier-database name lookup is largely a North American (primarily US) feature. Other regions either lack a name-display layer or implement it differently, with the originating side asserting the name rather than the recipient's carrier looking it up.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [What is a Voice API?](/docs/blogs/what-is-a-voice-api) · [What is number masking?](/docs/blogs/what-is-number-masking) · [What is a landline number?](/docs/blogs/what-is-a-landline-number)
* [Phone numbers & DIDs](/docs/account-phone-number) · [Purchase a number from inventory](/docs/account-phone-number/purchase-from-inventory) · [Number utilization & reputation](/docs/best-practices/number-utilization)
* [Automated outbound calling](/docs/solutions/automated-outbound-calling) · [Outbound campaign manager](/docs/best-practices/outbound-campaign-manager) · [Contact centre](/docs/solutions/contact-centre)
* [DLT registration](/docs/best-practices/dlt-registration) · [India calling regulations](/docs/compliance/india/calling-regulations)

## Sources

* Wikipedia, ["Caller ID"](https://en.wikipedia.org/wiki/Caller_ID).
* Wikipedia, ["Calling Name Presentation"](https://en.wikipedia.org/wiki/Calling_Name_Presentation).
* Wikipedia, ["Line Information Database"](https://en.wikipedia.org/wiki/Line_Information_Database).
* IETF, ["Authenticated Identity Management in the Session Initiation Protocol (SIP)" (RFC 8224)](https://www.rfc-editor.org/rfc/rfc8224), February 2018.
* IETF, ["PASSporT Extension for SHAKEN" (RFC 8588)](https://www.rfc-editor.org/rfc/rfc8588), May 2019.
* FCC, ["Combating Spoofed Robocalls with Caller ID Authentication (STIR/SHAKEN)"](https://www.fcc.gov/call-authentication).
* Wikipedia, ["STIR/SHAKEN"](https://en.wikipedia.org/wiki/STIR/SHAKEN).
* CTIA, ["Branded Calling ID"](https://www.ctia.org/news/branded-calling-id-launch).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and place your first programmable call, with caller ID and reputation handled, in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.