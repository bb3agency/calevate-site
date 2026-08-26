# Comet deep-research brief — Calevate legal, tax & finance setup

> **This is a RESEARCH BRIEF, not a legal document and not legal advice.** It is the prompt
> to paste into Comet (or another deep-research agent). Nothing it returns is operative
> until an Indian advocate and a practising Chartered Accountant have reviewed it. It does
> not live in `apps/web/src/lib/legal/` because it is not client-facing copy.
>
> Companion: `docs/LEGAL-SURFACE.md` is the audit of what the CODE already does and does
> not satisfy. This brief covers what the FOUNDER must set up around it — entity, tax,
> banking, cross-border money, and the foreign-client exposure the audit does not reach.

---

## HOW TO USE

Paste everything below the line into Comet. Fill the `<<FILL>>` values first — they change
the answers materially (GST thresholds and jurisdiction are state-dependent).

---

# RESEARCH TASK

You are researching the complete legal, tax, regulatory and financial setup required for
an Indian solo founder to lawfully operate and monetise a B2B SaaS product that places and
receives **real telephone calls using AI voice agents**, selling to **both Indian and
foreign business customers**.

I need practical, decision-grade, citation-backed answers — not a generic "how to register
a startup in India" article. Assume I am technically sophisticated and legally a beginner.

## GROUND RULES FOR YOUR RESEARCH

1. **Cite primary sources.** Government portals, bare acts, gazette notifications, RBI/GST
   circulars, TRAI regulations, and the vendors' own published terms. Give the URL and the
   date you retrieved it. Where you can only find a secondary source (a law-firm summary, a
   news article), **say so explicitly and label it as secondary** — do not present it as
   settled law.
2. **Distinguish "the law says" from "what people actually do".** I want both, clearly
   separated. Where common practice is technically non-compliant but widespread, say that
   plainly and tell me the actual enforcement risk.
3. **Indian law moved a lot in 2023–2026** (DPDP Act 2023 + DPDP Rules 2025, the
   Telecommunications Act 2023, TCCCPR amendments, GST changes). Verify commencement dates —
   several DPDP provisions are notified but **not yet in force**. Tell me what is in force
   **today** versus what commences later, with dates.
4. **Flag every place my plan is actually illegal or unworkable**, not just suboptimal. I
   would rather hear "you cannot do this" now.
5. Give **numbers**: registration fees, professional fees, annual compliance costs,
   timelines in days, tax rates, thresholds. Ranges are fine; "it depends" alone is not.
6. Where an answer depends on my state, my turnover, or my customer's location, **give me
   the decision rule**, not a single answer.

## MY SITUATION

- Indian citizen, currently **a student**, working as a **freelancer**.
- **No registered business, no company, no LLP, no proprietorship registration, no GST
  number, no Import-Export Code, no professional tax registration.** Nothing exists yet.
- Home state: `<<FILL: your state, e.g. Telangana>>`
- Current freelance income: `<<FILL: approximate annual, INR>>`
- Expected first-year SaaS revenue: `<<FILL: your estimate, INR>>`
- I intend to do **everything legally**, including paying the right taxes, from the start.
- I am the sole founder. No employees yet; possibly contractors later.

## WHAT THE PRODUCT IS (read this carefully — it drives most of the regulatory answers)

**Calevate** is a multi-tenant B2B SaaS. Client businesses (initially small and medium
Indian businesses, Telugu-language-first) get **AI phone agents** that:

- **Answer inbound calls** to the client's business number (reception, support, FAQ,
  appointment booking), and
- **Place outbound calls** — instant callback to a new lead, and bulk campaigns from an
  uploaded contact list.

### How it technically works (this matters for data-protection and telecom law)

1. A phone call is carried by an **Indian telecom provider** (Exotel / Plivo / Vobiz class)
   over a regular Indian phone number.
2. The live call is orchestrated by a **rented third-party voice platform (Bolna)** whose
   orchestrator is **hosted in the United States (AWS us-east-1)**.
3. Speech-to-text and text-to-speech run on **Sarvam AI (an Indian vendor)**.
4. The **language model** runs on **Microsoft Azure OpenAI in East US 2 (United States)**,
   with OpenAI-direct and Google Gemini as additional configured providers. **This means the
   caller's transcribed speech crosses the Indian border in real time, on every turn of every
   call.** There is no longer any India-residency claim made to clients about this leg.
5. After the call, we store: the **audio recording**, the **raw and redacted transcript**, an
   AI-written **summary**, **sentiment**, and **structured fields extracted from the
   conversation** (client-defined — e.g. name, budget, interest, appointment time) which
   populate a mini-CRM.
6. Our own application (dashboards, CRM, billing, admin) runs on a **VPS**, with recordings
   in object storage (Cloudflare R2 class).

### The commercial model

- Setup fee + monthly retainer with included minutes + per-minute overage, billed in **INR**.
- We metre every call and record our own cost per unit in an append-only ledger.
- We would collect payment via an Indian payment gateway (Razorpay class) and, for foreign
  clients, some cross-border mechanism I have not yet chosen.

### The compliance-relevant roles we have already worked out (verify these are right)

- For the **caller's** personal data, we believe **Calevate is a Data Processor** and the
  **client business is the Data Fiduciary**.
- For **client account data** (their users, billing, KYC), **Calevate is the Data Fiduciary**.
- Under India's telemarketing regime, we believe **the client is the Principal Entity (PE)**
  and **Calevate is the Telemarketer (TM)**, requiring DLT registration.
- Our agents always answer truthfully if asked whether they are an AI or whether the call is
  recorded; whether they **volunteer** that at call start is a per-client toggle.

**Please confirm or correct each of these four role assignments with citations.**

---

# THE QUESTIONS

## PART A — Entity: what do I actually need to register, and when?

A1. Can a **student** legally own and run a business / be a company director in India? Are
there restrictions from university rules, scholarships, or education loans I should check?
Does being a student affect anything legally at all, or only contractually?

A2. Compare, for exactly my situation, with **setup cost, annual compliance cost, time to
register, and what each one protects me from**:
   - Operating as an **unregistered individual freelancer** (just my PAN)
   - **Sole Proprietorship** (and what "registering" one even means in India — is there such
     a thing, or is it just GST / Shops & Establishment / Udyam?)
   - **One Person Company (OPC)**
   - **LLP**
   - **Private Limited Company**

A3. **At what point does it become genuinely unsafe to remain a proprietorship** for this
specific business? I am carrying: other businesses' customer data, telecom compliance
liability, and contractual indemnities. **Personal unlimited liability** is the thing I want
quantified. Give me the trigger conditions to incorporate.

A4. Do any of my **customers or vendors** force an entity on me regardless of the law?
Specifically:
   - Will a payment aggregator (Razorpay / Cashfree / PayU) onboard an individual with no GST?
   - Will **Stripe / Paddle / Lemon Squeezy / Wise** onboard an Indian individual?
   - Will the **DLT telemarketer registration** accept a proprietorship, or does it demand a
     company with CIN/GST? (I have seen a vendor's DLT guidance ask for **CIN, GST
     certificate, company PAN, and MOA** — check whether an unregistered individual can
     register as a Telemarketer at all.)
   - Will a mid-size Indian business sign a services contract with an individual?

A5. **Udyam / MSME registration** — is it worth it, what does it actually get me, and can a
student freelancer get it?

A6. What is the **cheapest lawful starting configuration**, and what is the **migration path**
from it to a Pvt Ltd later? What breaks or costs money when I convert (contracts, GST number,
bank account, DLT registration, payment gateway, IP assignment)? Is there anything I should do
**now** purely to make that conversion painless later?

## PART B — GST

B1. What is the GST registration **threshold for services** in my state, and what is the
current position on **mandatory registration regardless of turnover** for:
   - inter-state supply of services within India,
   - supply through an e-commerce operator,
   - **export of services**?
   State clearly which of these force registration on me even at zero revenue.

B2. Calevate is SaaS with a per-minute usage component. Confirm the correct **SAC code** and
**GST rate** (we currently use SAC 998315 at 18% — verify), and whether the telephony/minutes
component is classified differently from the software component.

B3. **Place of supply** rules for my case: Indian client in my state; Indian client in another
state; foreign business client; foreign individual. Which of CGST+SGST / IGST / zero-rated
applies to each, and what determines it.

B4. **Export of services**: explain the conditions a supply must meet to qualify (including
the "distinct person" trap and the requirement that payment be received in convertible
foreign exchange). Then explain the two routes — **LUT/bond (export without payment of IGST)**
vs **pay IGST and claim refund** — with the actual filing mechanics, forms, and which one a
solo founder should pick.

B5. **OIDAR** — Online Information Database Access and Retrieval services. This is the one I
understand least and I think it may be central. Explain:
   - whether **Calevate is an OIDAR service** (it is automated, delivered over the internet,
     with minimal human intervention — but it also places real phone calls),
   - what changes if my customer is a **foreign business** vs a **foreign individual**,
   - the reverse-charge position when I **buy** services from foreign vendors (Microsoft Azure,
     OpenAI, Google, Bolna, Cloudflare, Sentry, Resend) — **do I owe Indian GST under reverse
     charge on my own vendor bills, and does that obligation exist even if I am unregistered?**
   This last point worries me most. Answer it precisely.

B6. Once registered: what returns do I file, how often, what do they cost me in CA fees, and
what are the penalties for getting it wrong? What is the **ongoing monthly burden** in hours
and rupees?

B7. **e-invoicing (IRN)** — at what turnover does it kick in, and what would I have to build?

## PART C — Receiving money from foreign clients (FEMA / RBI)

C1. What is the **lawful mechanism** for an Indian individual/entity to receive payment for
services exported to a foreign business? Walk through the whole chain.

C2. **FIRC / FIRA / e-BRC** — what are they, who issues them, why do I need them, and what
happens at GST-refund or income-tax time if I do not have them?

C3. **Purpose codes** — which one applies to SaaS/software services, and what goes wrong if
my bank applies the wrong one?

C4. **SOFTEX filing** — does it apply to SaaS/software service exports for someone my size?
Is it mandatory, what is the threshold, and what is the penalty for not filing? (I have seen
conflicting information; please settle it with a primary source.)

C5. Compare the practical options for actually collecting foreign payment, with **fees, FX
spread, settlement time, compliance paperwork generated, and whether they onboard an Indian
individual vs an Indian company**:
   - Direct SWIFT wire to an Indian current account
   - **Wise Business / Payoneer**
   - **Stripe** (via Stripe India, or Stripe Atlas + a US entity)
   - **Razorpay / Cashfree international collections**
   - **Paddle / Lemon Squeezy** as merchant-of-record
   - PayPal

   Explain the **merchant-of-record** model specifically — does it remove my GST/VAT
   obligations in the customer's country, and at what cost?

C6. **Do I need an Import-Export Code (IEC)** for services export? Yes or no, with the rule.

C7. **EEFC account** — what is it, do I need one, when is it worth it?

C8. Is there any **legal problem with an unregistered individual receiving foreign currency**
for services? What exactly is the risk if I just receive it in my savings account?

C9. The **Stripe Atlas / US entity** question, which a lot of Indian founders do: if I set up
a US LLC or C-Corp to collect payments while I live and work in India — what are the
consequences? Cover **Permanent Establishment risk, transfer pricing, FEMA ODI rules (does an
Indian resident need RBI permission to own a foreign entity?), US tax filings (5472/1120),
and whether this is actually legal for a resident Indian to do.** Be blunt about whether this
is a good idea or a trap.

## PART D — Income tax

D1. As a freelancer/proprietor: does **presumptive taxation under s.44AD or s.44ADA** apply to
a SaaS business? Which one, what is the turnover limit, and what is the catch? Is running a
software product "profession" or "business" for this purpose?

D2. **Advance tax** — schedule, thresholds, penalties for underpayment.

D3. What **books of account** must I maintain, and when does a **tax audit** become mandatory?

D4. **TDS**: (a) will my Indian business clients deduct TDS on my invoices, at what rate,
under which section, and how do I reclaim it? (b) **do I have to deduct TDS when I pay foreign
vendors** (Microsoft, OpenAI, Google, Bolna)? Explain **Equalisation Levy** and s.195
withholding on payments to non-residents, whether they apply to cloud/API spend, and what
Form 15CA/15CB obligations I pick up.

D5. How does the tax picture change under a **Pvt Ltd** (corporate rate, dividend/salary
extraction, and the real effective tax rate on money reaching my pocket)?

D6. Are there **startup tax benefits** I qualify for — DPIIT recognition, s.80-IAC — and are
they worth the paperwork at my size?

## PART E — Telecom regulation (this is the highest-risk area — treat it seriously)

E1. **TRAI / TCCCPR 2018 as amended**: explain the **Principal Entity vs Telemarketer**
model, DLT registration on the operator blockchains, header and content-template
registration, and **140-series vs 160-series** number classes. Confirm which of these bind
Calevate as the Telemarketer and which bind my client as the PE.

E2. What does it cost, how long does it take, and **what entity documents does DLT
registration demand**? Can an individual/proprietorship register as a Telemarketer?

E3. **Consent and DND/DNC**: what is the lawful basis for placing an outbound business call
in India? What is scrubbing, how often must it happen, and what are the penalties and
disconnection risks for violations? Does the liability sit with the PE, the TM, or both?

E4. **Does an AI voice agent service need any DoT licence?** Cover **Other Service Provider
(OSP) registration** (and the 2020/2021 liberalisation), and whether the **Telecommunications
Act 2023** brings anything new for a company that is not itself a carrier but automates calls
over one. Am I a "telecom service provider" in any sense?

E5. **Call recording legality in India.** Is it lawful to record a business call, must the
other party be notified, and what does the case law actually say? (I am aware of a tension
between older authority and more recent decisions — please explain the current position and
what a cautious operator does.)

E6. **Is a voice recording "biometric information"** under the SPDI Rules 2011, given the
definition includes voice patterns? This is genuinely unresolved as far as I can tell, and it
matters enormously: if yes, the consent and cross-border-transfer duties are much heavier,
and they bind until the SPDI Rules are repealed. Give me the best available answer and tell
me how confident it is.

E7. **Is there any Indian law requiring an AI to identify itself as an AI on a phone call**
as at today's date? If not, is anything proposed?

## PART F — Data protection

F1. **DPDP Act 2023 + DPDP Rules 2025**: what is actually **in force today**, and what
commences later, with dates? Confirm the position of the cross-border transfer provision
(s.16) and whether any restricted-country list has been notified.

F2. Until DPDP fully commences, the **IT Act s.43A + SPDI Rules 2011** are operative. What do
they require of me right now — especially the **"comparable level of protection" test for
transferring sensitive personal data outside India**?

F3. **The border question, stated plainly:** my callers' speech is transcribed and sent to
**Microsoft Azure OpenAI in the United States in real time, on every turn of every call**, and
recordings/transcripts are stored. Is this lawful today? What must I do to make it lawful —
consent, contract, notice, or something else? Answer for both the **current SPDI regime** and
the **post-commencement DPDP regime**.

F4. **Processor obligations**: what must be in the contract between me and my client
(Data Processing Addendum), and what must flow **down** to my sub-processors? My sub-processor
chain is: Bolna (voice platform, US), Sarvam AI (speech, India), Microsoft Azure OpenAI (US),
OpenAI, Google, Exotel/Plivo/Vobiz (telephony, India), Cloudflare (storage/CDN), the VPS host,
Sentry (errors), Resend (email). **None of these DPAs are signed yet.** Which ones can I
execute by clicking an online standard DPA, and which need negotiation?

F5. **Grievance Officer** and data-protection contact: is appointing one mandatory for me
today, under which instrument, what must be published, and can it be me?

F6. **Breach notification**: to whom, in what time, in what form — under DPDP, under CERT-In
directions (the 6-hour rule), and under any contract I sign. Are CERT-In's 2022 directions
binding on me, and what logging retention do they impose?

F7. **Consumer Protection Act 2019 / E-Commerce Rules 2020** — do these apply to a B2B SaaS
sold to small proprietor-run businesses? Does that change what my Terms must contain and
whether an arbitration clause survives?

## PART G — Foreign clients (this is where I am most exposed and least informed)

**Assume a foreign client uses Calevate to call people in their own country.** The AI voice
agent is calling real phone numbers abroad. Cover:

G1. **United States — TCPA.** I understand the FCC has ruled that AI-generated voices count
as an "artificial or prerecorded voice" under the TCPA. Explain: what consent is required
before an AI agent may call a US number, what **statutory damages per call** are, whether
class actions are realistic, the **state-level mini-TCPA statutes** (Florida, Oklahoma,
Washington), and the **National/state Do-Not-Call** obligations. **Tell me honestly whether a
solo Indian founder should serve US outbound calling at all**, and what the exposure looks
like if a client misuses the system.

G2. **US call-recording consent** — the **one-party vs two-party (all-party) consent states**
(California, Florida, Illinois, Pennsylvania, Washington and others). What must the agent say,
and when? What happens on an interstate call between a one-party and a two-party state?

G3. **US state AI-disclosure laws** — California's bot-disclosure law and any comparable
state statutes: must the agent announce it is a bot, and in what contexts?

G4. **EU/UK.** Cover **GDPR** (my role as processor or controller, Article 28 contracts,
lawful basis for recording, and the **international transfer** rules — SCCs, the UK IDTA,
adequacy, and the fact that India has no adequacy decision), plus the **ePrivacy Directive**
on unsolicited marketing calls. Also: does the **EU AI Act** apply to a voice agent, and what
does its transparency obligation (interacting-with-AI disclosure) require and from what date?

G5. **Do I need to register or appoint a representative in any of these jurisdictions**
(GDPR Article 27 EU representative, UK representative)? What does that cost?

G6. **Which foreign markets are realistically safe** for a solo Indian founder to serve, and
which should I contractually refuse? Propose specific **Acceptable Use Policy restrictions
and contractual geographic carve-outs** that reduce my exposure.

G7. **Contractual risk transfer**: since my client controls who gets called and whether they
had consent, how do I structure indemnities so the consent risk sits with them — and be
honest about **where that fails** (i.e. where a regulator or plaintiff comes after me anyway,
regardless of what my contract says).

## PART H — Contracts and documents I need

H1. List the **complete document set** a SaaS like this needs, in priority order, with a note
on which I can adapt from a good template and which genuinely need a lawyer:
Terms of Service · Privacy Policy · Data Processing Addendum · Sub-processor list ·
Acceptable Use Policy · Refund & Cancellation Policy · Grievance Redressal · Cookie notice ·
Master Services Agreement · SLA · Order Form / quote.

H2. **What must legally appear** on the website for (a) a payment aggregator to onboard me and
(b) statutory compliance — contact details, a working phone number, registered address, GSTIN,
grievance officer, refund policy.

H3. **Liability caps and indemnities** for a solo founder: what cap is normal, what will an
Indian SMB client actually accept, and where should the cap be **uncapped** (typically
telecom/consent breaches caused by the client).

H4. Is **professional indemnity / cyber liability insurance** available and affordable in
India at my size? What does it cost and what does it actually cover?

H5. **IP**: who owns the agent configuration, the extraction schema, the transcripts, the
recordings, and any model improvements? What should my contract say?

## PART I — How do people actually do this? (answer with real, current practice)

I1. **How do Indian solo founders and freelancers actually structure this in practice?** I
want the honest, common patterns — including the ones that are technically sloppy — with the
real risk of each:
   - Freelancing on a personal PAN with no GST until the threshold
   - Proprietorship + GST + current account
   - Pvt Ltd from day one
   - US LLC + Indian subsidiary/branch
   - Merchant-of-record (Paddle / Lemon Squeezy) to avoid global tax complexity

I2. **What is the most common expensive mistake** Indian SaaS founders make in year one on
tax, FEMA, or GST? Give concrete examples and what it cost them.

I3. At what revenue does each of these become worth it: **GST registration** (if not already
mandatory), **a CA on retainer**, **incorporation**, **a lawyer**, **insurance**?

I4. **What does a competent CA actually cost** monthly/annually for a business like mine in
India, and what should I expect them to handle vs what stays mine?

I5. Are there **founder-friendly programs** worth using — Startup India / DPIIT recognition,
state startup policies (especially `<<FILL: your state>>`), incubators that provide legal and
CA support?

## PART J — Give me a sequenced action plan

J2 is the deliverable I care about most. Produce:

J1. A **decision tree**: "if your first client is Indian and you expect < INR X, do A; if you
have any foreign client, do B; the moment you do C, you must have D."

J2. **A dated, sequenced checklist** from where I am today (nothing registered) to lawfully
invoicing my first Indian client, and then my first foreign client. For each step give:
**what it is, who does it (me / CA / lawyer / registrar), what it costs, how long it takes,
what it blocks, and what breaks if I skip it.** Separate clearly:
   - what I must do **before taking any money at all**
   - what I must do **before my first outbound campaign call**
   - what I can defer, and until what trigger

J3. **The stop-list**: things I must NOT do, in plain language.

J4. **A list of everything you could not verify** or where sources conflicted — with what you
found and what a professional would need to settle it. **Do not fill gaps with plausible
guesses.** I would rather have a clearly-marked unknown than a confident wrong answer.

---

## CONTEXT: WHAT IS ALREADY DONE (do not re-research these; verify only if you think we got it wrong)

We have already built and audited a substantial compliance surface in code, including:
tax-invoice generation with correct particulars and place-of-supply logic; a refusal to issue
a tax invoice without a supplier GSTIN (proforma instead); append-only usage and consent
ledgers; per-tenant data isolation; PII redaction in transcripts by default; a DNC/DND list
and campaign compliance gate; erasure with a deletion certificate; retention sweeps; a breach
notification runbook; and eight drafted legal documents (Privacy, Terms, AUP, DPA,
Sub-processors, Refunds, Grievance, Cookies) which are **unreviewed by an advocate** and carry
a draft banner.

**The blanks that block all of it are exactly the things this brief is about**: legal entity
name, entity registration number, GSTIN, registered address, contact phone, grievance officer,
data-protection contact, jurisdiction city, and the DLT telemarketer ID.

A direct competitor in the same market operates as a **private limited company with a
published GSTIN**, and publishes a Refund & Cancellation Policy, a Privacy Policy naming a
Grievance Officer, a Security & Sub-processors page, and an Acceptable Use Policy. Treat that
as the **minimum credible bar**, and tell me what it implies about the entity I need.

---

## OUTPUT FORMAT

- Organise by the Parts above (A–J).
- Every factual claim gets a **source link and retrieval date**.
- Mark each answer's confidence: **CONFIRMED (primary source)** · **REPORTED (secondary
  source only)** · **UNRESOLVED (sources conflict or none found)**.
- End with **Part J's sequenced checklist as a table** I can work through.
- Then end with a short section: **"Questions to take to a CA"** and **"Questions to take to
  an advocate"** — separated, because I will book them separately.
