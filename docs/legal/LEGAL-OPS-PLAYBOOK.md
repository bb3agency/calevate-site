# Calevate — India-only legal & ops playbook (final scenario)

> **Status:** Working playbook for a solo founder. **Not legal advice, not a filing, not a contract.**
> Confirm GST/IT/PT numbers with a CA and DLT/number KYC with a telecom lawyer before you spend money or originate the first outbound campaign.
> **As of:** 24 August 2026.
> **Scope freeze:** India-only B2B. No foreign clients. No FEMA / FIRC / LUT / IEC / SOFTEX / Stripe Atlas in this plan.

---

## 0. Final scenario (this is the source of truth)

You are a **sole developer / freelancer** shipping **Calevate** as a full B2B SaaS.

| Decision | Final choice |
|---|---|
| Legal person | **You** (individual / sole proprietor). Calevate is a **product / trade name**, not a separate company. |
| Geography | **Andhra Pradesh + Telangana only** at launch. Telugu-first. |
| Customers | Indian SMB businesses in AP and TS. **No foreign clients.** |
| Money in | Paid subscriptions / retainers / usage from those clients. |
| Money out | Your own SaaS/vendor bills (Bolna, Azure/OpenAI, Sarvam, Cloudflare, etc.). |
| GST | **Not at launch.** Watch the ₹20 lakh all-India services threshold and the triggers in §4. |
| Banking | Personal savings only for a tiny test. **Current account** once money is recurring. |
| Entity proof | **Udyam (MSME)** first. GST later if a trigger hits. |
| Phone numbers | **Model B.** Client buys and KYCs the number on **their** Exotel / Plivo / Vobiz account. |
| Your carrier account | **Not required** for client live traffic. Only if Calevate itself needs a demo/sales/support DID. |
| DLT | **You = Telemarketer (TM)** once. **Each client = Principal Entity (PE).** They bind your TM-ID in the PE–TM chain. |
| Bolna | Orchestrator only. Does **not** issue Indian numbers and does **not** replace DLT or carrier KYC. |
| Outbound | Off until TM-ID exists **and** that client’s PE–TM chain is Active. |
| Inbound-only reception | Can go live **without** DLT TM (still need client number + Bolna + legal pages). |

If any of the above changes (foreign client, you resell numbers, you incorporate), this playbook is stale. Re-open those chapters.

---

## 1. What Calevate is (compliance-relevant)

Calevate is multi-tenant B2B SaaS. Client businesses get AI phone agents that:

- **Answer inbound** calls (reception, support, FAQ, booking).
- **Place outbound** calls (instant callback, bulk campaigns from an uploaded list).

Technical stack that drives law (do not pretend this is “just software”):

1. Call is carried by an **Indian licensed operator / UL-VNO class vendor** (Exotel / Plivo / Vobiz).
2. Live call is orchestrated by **Bolna** (third-party voice platform; US-hosted orchestrator in the original architecture).
3. STT/TTS: **Sarvam AI** (India).
4. LLM: **Azure OpenAI / other US providers** — transcribed speech can leave India on every turn.
5. After the call you store: recording, transcript, summary, sentiment, extracted CRM fields.
6. App/dashboard on a VPS; recordings in object storage.

Commercial model: setup + monthly retainer + included minutes + overage, billed in **INR**.

### Roles (keep these; they are still the working assignments)

| Role question | Working assignment | Notes |
|---|---|---|
| Caller’s personal data | Client = **Data Fiduciary**; Calevate = **Data Processor** | Put this in the DPA. |
| Client account / billing / login data | Calevate (you) = **Data Fiduciary** | Your Privacy Policy. |
| TCCCPR commercial voice/SMS | Client = **Principal Entity (PE)**; you = **Telemarketer (TM)** | Joint liability. Do not assume the contract moves TRAI off you. |
| AI / recording disclosure | Agent answers truthfully if asked; volunteering at start is a per-client toggle | Safer default: announce recording + AI on outbound and inbound. |

---

## 2. What you already decided *not* to do

Do **not** spend time or money on these until the freeze lifts:

- Foreign clients / US outbound / EU clients
- TCPA, GDPR Art. 27 representative, EU AI Act as a go-to-market workstream
- IEC, LUT (RFD-11), FIRC/FIRA/e-BRC, SOFTEX/EDF, EEFC
- Stripe Atlas / US LLC / ODI
- Merchant-of-record (Paddle / Lemon Squeezy) as a tax strategy
- Buying a pool of numbers in your name and renting them to clients (**Model A**)
- Registering a Private Limited / OPC **just to launch** (optional later for liability)

These were researched earlier and parked. They are **not** blockers for this scenario.

---

## 3. Legal shape: freelancer = sole proprietor

There is **no separate “freelancer registration”** in India. The moment you invoice under a trade name and run a product, you are a **sole proprietor**. You and the business are the **same legal person**.

Consequences:

- Contracts are with **you** (or “You trading as Calevate”).
- Tax is on **your** ITR (business/profession).
- DLT TM-ID, bank account, Razorpay merchant, Udyam all attach to **your PAN**.
- **Unlimited personal liability.** A TRAI fine, a data incident, or a client indemnity can reach personal assets. That is the price of not incorporating.
- Being a **student** does not bar you from owning a business or being a proprietor. Check only **university / scholarship / education-loan contracts** (those are contractual, not a Companies Act bar).

You do **not** need to incorporate Calevate as its own company. Register the **parent/legal person** (you). Calevate is the product. On invoices and Terms say:

> Calevate is a product operated by **[Your legal name / trade name]**, sole proprietor.

DLT headers can later represent the product brand under that entity.

---

## 4. GST (Andhra Pradesh + Telangana)

### 4.1 Threshold

- Services, normal-category states (AP and TS both are): **₹20 lakh** aggregate turnover in a financial year.
- Goods thresholds (₹40 lakh) are irrelevant; you sell services.

**Aggregate turnover** = all taxable + exempt + export supplies under the same PAN, India-wide. Even though you only *want* AP+TS clients, one stray Karnataka invoice still counts toward the ₹20 lakh bucket.

### 4.2 AP client vs TS client

You sit in AP. A Hyderabad client is an **inter-state supply of services**.

That does **not** force GST below ₹20 lakh. **Notification No. 10/2017–Integrated Tax** (13 Oct 2017) exempts persons making **inter-state supplies of taxable services** from compulsory registration under CGST s.24, if turnover is below the s.22 threshold (₹20 lakh here).

So your guess is right for this freeze: **no GST at launch**.

### 4.3 When GST becomes mandatory anyway

Register **before** the first invoice that trips a trigger:

| Trigger | Forced? |
|---|---|
| All-India service turnover exceeds ₹20 lakh | Yes |
| You start selling through an e-commerce operator that requires TCS/GSTIN | Often yes — avoid that channel until registered |
| Client refuses to pay without a GST tax invoice / ITC | Commercial, not statutory — still a real sales block |
| You later take **foreign** clients (export of services / LUT) | Out of scope now; would reopen LUT + GSTIN |
| Reverse charge on specified services **as a registered person** | Only after you are registered |

### 4.4 What you issue without GST

- **Bill of supply / commercial invoice**, not a GST tax invoice.
- No CGST+SGST / IGST line.
- You cannot give the client Input Tax Credit.
- Mid-size clients may still accept this at small ticket sizes; some will not.

### 4.5 SAC / rate (for when you do register)

Working assumption from the product brief: **SAC 998315**, **18%**. Reconfirm with a CA when you register. Telephony-minutes vs software as a mixed supply is a CA question, not something to invent.

Place of supply once registered:

- AP client, you in AP → CGST + SGST
- TS client → IGST
- (Foreign — parked)

### 4.6 Reverse charge on *your* vendor bills

You will pay Bolna, Azure, OpenAI, Cloudflare, etc.

- **Unregistered (now):** you generally are **not** the “registered person” who must self-assess IGST under RCM on import of services. You just pay the vendor. Indian vendors add GST to the bill; that GST is a cost (no ITC).
- **After you take GST:** RCM on import of services from foreign vendors becomes live. Budget for it. Confirm with the CA the day you file REG-01.

Do not treat this paragraph as a licence to ignore invoices. Keep every vendor PDF.

### 4.7 OIDAR

Calevate is automated SaaS plus real phone calls. It **likely** looks like OIDAR, but the voice leg is a classification grey area. **Irrelevant to launch** while you are unregistered and India-only. Flag for the CA at GST registration.

### 4.8 Returns / e-invoicing (later)

Once registered: GSTR-1 + GSTR-3B (monthly or QRMP if eligible). E-invoicing IRN is a **high turnover** regime (crores, not your year-one size). Ignore IRN until a CA says you crossed the notified limit.

---

## 5. Income tax (always on, even with no GST)

GST-unregistered ≠ tax-free.

| Item | What to do |
|---|---|
| ITR | File as individual with **business/profession** income. Keep a simple books folder (receipts, Razorpay settlement CSVs, vendor bills). |
| Advance tax | If estimated tax for the year **> ₹10,000**, pay in instalments (default: 15 Jun / 15 Sep / 15 Dec / 15 Mar). Interest under s.234B/234C if you skip. |
| Presumptive tax (44AD / 44ADA) | **Unresolved for a product SaaS.** 44ADA is for specified professions; 44AD is for eligible business. A software *product* with minutes metering may be “business” not “profession.” **Ask the CA. Do not self-elect 44ADA because “I’m a developer.”** |
| Tax audit | Triggered by turnover / presumptive opt-out rules. Unlikely in month one. Know the question exists. |
| TDS **on you** | Indian business clients may deduct TDS on your invoices (often s.194J / 194C depending on characterisation — **CA**). You claim it in ITR against Form 26AS / AIS. |
| TDS **by you** | No employees → no salary TDS. Paying foreign vendors: s.195 / equalisation levy is a live technical question once amounts are material. At tiny Azure bills, still **ask the CA once**; do not invent a 15CA/15CB process from a blog. |
| Books | Save every invoice you raise and every subscription you pay. A single Drive/Notion ledger is enough until turnover is real. |

---

## 6. Andhra Pradesh extras

| Item | Why |
|---|---|
| **Professional tax (PTEC)** | AP levies PT on professions / trades / self-employed. Constitutional cap **₹2,500/year**. Slabs exist (often nil below a monthly income band). **Confirm with a local CA whether a solo home proprietor must take PTEC now.** Do not ignore it for two years and then get a notice. |
| **Shops & Establishment** | Not always day-one for a laptop-only home operator. Very useful as **second business proof** if the bank or DLT wants more than Udyam. Apply if asked. |
| University / hostel / rental | If the “office” is a hostel or parents’ house, keep a simple consent letter for bank KYC. |

Telangana PT/S&E only matters if **you** (not the client) establish an office there.

---

## 7. Banking and collecting money

### 7.1 Personal savings vs current account

| Phase | Account | Reality |
|---|---|---|
| First test payment, 1 tiny client | Existing **savings** can work on some freelancer/unregistered Razorpay KYC | Banks watch commercial patterns. Freezes happen. |
| Recurring SaaS, several clients, gateway at real limits | **Proprietorship current account** in trade name | This is the real requirement. RBI treats current/transaction accounts as the commercial pipe. Razorpay’s own startup guidance expects a current account for full merchant settlement. |

You do **not** need a second *personal* savings account. You need a **business-use current account**.

RBI KYC for a proprietorship current account typically wants the proprietor’s ID **plus two proofs in the firm/trade name** (Udyam, S&E, GST later, utility bill, registration certificate, etc.). Udyam is usually the first of those two.

### 7.2 Payment gateway (India-only)

Razorpay / Cashfree / PayU class.

Typical docs:

- Personal PAN + Aadhaar
- Cancelled cheque / bank statement of the **settlement** account
- Udyam (or GST / S&E)
- Live website with **Terms, Privacy, Refunds, Contact, Grievance**

Without GST they can still onboard a proprietor; limits and underwriting vary. If they demand GSTIN, that is a **vendor policy**, not a GST Act threshold — either pick another aggregator or take voluntary GST.

Foreign collection products are **out of scope**.

### 7.3 Mixing money

Do not run rent, food, and client settlements in one savings account once Calevate is real. It wrecks ITR, 26AS reconciliation, and any future GST/IT notice.

---

## 8. Udyam (MSME) — do this first

- Portal: official Udyam registration (Aadhaar + PAN, self-declaration).
- **Cost:** ₹0.
- **GST is not required** to obtain Udyam.
- This is your government **proof of business existence** for bank, DLT, carriers, and gateways.
- You can use a **trade name** (e.g. your name trading as Calevate) consistent with PAN.

Udyam is **not** limited liability and **not** a company.

---

## 9. Phone numbers — Model B only

### 9.1 The two architectures (and why A is off)

**Model A — you buy numbers and rent them out**

- Looks like unlicensed telecom resale (UL-VNO is a licensed category).
- You become subscriber of record; client is only an “end-user” on paper.
- 160-series / “transactional only” numbers **cannot** carry promotional/cold outbound.
- Reassignment on churn likely needs fresh KYC.
- **Do not do this** as a solo proprietor with no corporate veil.

**Model B — client owns the connection (YOUR CHOICE)**

- Client’s entity is on the CAF / carrier KYC.
- Client is PE on DLT.
- You are TM.
- Bolna uses **their** API credentials.
- You are **not** the DoT subscriber of their DID.

### 9.2 What “we don’t worry about carrier KYC” means

True for **client live numbers**.

False if:

- Calevate needs its own demo / sales / support number, or
- A client says “just give me a number” (that is Model A — refuse or send them to Exotel/Plivo).

### 9.3 Plivo / Exotel / Vobiz (client side)

Indian virtual numbers are **not** “rent a US DID in one API call.”

Plivo (and peers) require, before an Indian number:

- India-registered business docs (COI **or Udyam**, plus PAN/GST as they list)
- Often an **India data region** account
- KYC **before** outbound is enabled
- Extra pack for **160-series** (PE, CAF, sometimes regulator licence / NOC — 160 is not a generic SMB toy)

Address proof often must **match the city** of the number (Exotel class of rule).

Sub-accounts: useful so the **client’s main account** owns the number and you operate via delegated keys. Numbers are typically billed/owned at the account that rented them.

### 9.4 10-digit vs 140 vs 160

| Number class | Allowed traffic | Who can get it | Inbound reception? | Cold / promo outbound? |
|---|---|---|---|---|
| Ordinary 10-digit / local DID / virtual landline | Inbound support; careful with any “commercial outbound” | Client KYC with carrier | **Yes — default for reception** | **No** as a telemarketing path. Using it for promo/campaigns is how people get tagged UTM. |
| **140-series** | Promotional / telemarketing outbound | PE + TM + DLT + 140 assignment | Poor / not a reception line | **Yes**, with consent + DND + templates as required |
| **160 / 1600-series** | Transactional / service only (OTP, order status, booking confirm) | Tight. Large parts reserved for **regulated BFSI / specified** entities. Undertaking: no promo. | Not your generic inbound DID | **No.** Misuse = disconnection + penalties |

Competitor “₹649/month transactional numbers” are almost certainly **service-only**. That restriction is **regulatory**, not a nice-to-have contract clause.

**AI-specific number ban:** none found. TCCCPR treats the call by category (promo vs service), not by “human vs bot.” Disclose autodialer/robo where the form asks.

### 9.5 Concurrency

Concurrency is **channels / account trunk**, not “one number = one call.” A single DID can fan many simultaneous sessions; media rides channels. Buy channels on the **client’s** carrier account if they need concurrency.

### 9.6 Bolna

Bolna is **BYOA / BYOC**:

```
Client carrier (Exotel / Plivo / Vobiz / SIP)
        ↕ webhooks / SIP
      Bolna
        ↕
  STT + LLM + TTS
```

Bolna publish connect flows for Exotel, Plivo, Vobiz: Account SID / Auth / number go in **per tenant**. “Connect” means **use the client’s already-provisioned number**, not “Bolna sells 140/160.”

Inbound and outbound both work **if the carrier number and account allow that direction**.

**Unresolved:** exact Bolna SIP/BYO-trunk field list — read current Bolna docs when you implement; do not freeze an old screenshot into the product.

---

## 10. DLT and Telemarketer registration

### 10.1 When TM is mandatory

| Product mode | TM registration |
|---|---|
| Inbound-only (customer called the business) | **Not required** for TCCCPR telemarketing |
| Outbound callback / campaigns / promo / bulk | **Required** before the first such call |
| SMS commercial headers | Same PE–TM world |

### 10.2 What you register as

**Telemarketer / Aggregator / Platform — not Enterprise/PE** (unless you also send as yourself).

One operator portal is enough (Jio TrueConnect / Airtel DLT / Vi Vilpower / Tata / BSNL). You get a **TM-ID** recognised across the DLT mesh.

**Fee (vendor schedules, treat as REPORTED):** about **₹5,000 + 18% GST = ₹5,900** one-time on first portal. Some operators quote further TM/operator fees (~₹5,000 + GST) and ~₹1,500-class renewals. Pay what the portal shows; do not argue with a blog.

**Time:** often **48–72 hours** after KYC, not guaranteed.

### 10.3 Documents (no GST required)

Any **one strong proof of entity** plus PAN and signatory ID:

- Business / personal **PAN** (proprietor)
- **Udyam** **or** GST REG-06 **or** Shops & Establishment **or** COI (you won’t have COI)
- Aadhaar / passport of authorised signatory (you)
- Authorisation letter (you authorising yourself is fine as proprietor)
- Bank details sometimes

GST is **not** mandatory for TM signup if Udyam/S&E is accepted. Portals differ; if one rejects Udyam, try another operator or add S&E.

### 10.4 The PE–TM chain (this is the part you clarified)

**Wrong:** “Client registers DLT for the number and types my TM-ID in the first signup form.”

**Right:**

1. **You** already have a TM-ID.
2. **Client** signs up as **Enterprise / Principal Entity** with *their* PAN/Udyam/GST. They get a **PE-ID**.
3. Client registers **headers** and **content templates** under *their* PE (SMS; voice follows the same PE world / 140–160 assignment).
4. Client → **PE–TM Chain / Manage Telemarketer → New Chain** → paste **your TM-ID**.
5. **You** accept in the TM login. Client may need to approve again. Status must be **Active**.
6. **Separately**, client buys the DID on Exotel/Plivo and finishes **carrier KYC**. DLT does not create the phone number.

Exotel-class vendors publish *their* TM-ID for clients who use that vendor as TM. You are the TM **for Calevate**, so they use **your** TM-ID, not Exotel’s, unless Exotel is the TM of record (don’t mix those models).

### 10.5 What the client still must do (onboarding friction)

This **kills zero-touch self-serve** for outbound. Budget sales time:

1. Have a business proof (GST/Udyam/S&E).
2. Open Exotel/Plivo (India), submit KYC, wait for number (days; city-matched address).
3. Register PE on a DLT portal (fee on their side).
4. Headers + templates.
5. Bind your TM-ID; you accept.
6. Hand you Account SID, token, number, and (for outbound) consent/DND process.
7. You store credentials per tenant and connect Bolna.

Illustrative elapsed time once documents exist: **about 1–2 weeks**, not 10 minutes. (160-series BFSI packs can be longer and may be unavailable to a kirana/SMB.)

Inbound-only can skip steps 3–5.

### 10.6 Registered TM vs unregistered (UTM)

| | Registered TM | Unregistered |
|---|---|---|
| Legal | Lawful intermediary | UTM |
| Routing | PE↔TM chain / traceability | Easy to flag as spam |
| 140 / campaign outbound | Possible when PE is set up | Don’t |
| Complaint handling | Consent logs, chain | Fast resource disconnection (TRAI has shortened AP action windows; UTM notices are mass-issued) |
| Penalties | Graded (commentary: ₹2 lakh / ₹5 lakh / ₹10 lakh ladders appear in 2025 amendment explainers — confirm live text with counsel) | Same plus disconnection |
| Enterprise sales | Client can verify TM-ID | Serious PE will not bind you |

### 10.7 Liability — do not lie to yourself

TCCCPR practice: **PE and TM are jointly in the frame.**

If the client uploads a list with no consent and your platform dials it:

- Contractual indemnity helps **between you and them**.
- TRAI / access provider can still suspend **your** TM resources and **their** PE headers.
- You must still **DNC/DND scrub**, keep consent artefacts, expire stale consent, and refuse the send in product (you already sketched this in code).

**Inbound** does not need prior telemarketing consent (the person called in). **Recording** and **data** rules still apply.

### 10.8 140 vs 160 vs your product modes

- Reception / support inbound → ordinary DID, no TM required.
- “We missed your call, here’s a callback you requested” → still treat as regulated outbound; get TM + PE chain; prefer explicit callback consent in the widget.
- Cold / promo campaign → **140** + PE templates + DND + TM. Refuse if they only have a 160 or a raw mobile.
- OTP / “your order shipped” → 160 **if they are even eligible**; most SMBs will not be. Do not fake 160 eligibility.

---

## 11. SMS and WhatsApp (when you add them)

### SMS

If the client is PE and you are TM, SMS headers/templates stay **theirs**. Content liability is still **joint** if you transmit.

### WhatsApp

- **Not DLT/TCCCPR.** Meta BSP / WABA / template approval.
- **Client should own the WABA.** You get agency/BSP access they can revoke.
- India WABA verification wants GST / COI / S&E matching the business name.
- Same number *can* sometimes do voice + SMS + WhatsApp, but WhatsApp verification is a separate OTP process and the number must not already be on consumer WhatsApp. Confirm per carrier. Do not promise “one number, three channels” in sales until you have tested that carrier.

---

## 12. Data protection (still on, even India-only)

Foreign **clients** are frozen. Foreign **sub-processors** are not. Speech can still go to **US Azure OpenAI** on every turn.

### 12.1 What law applies today (24 Aug 2026)

- **DPDP Act 2023 + DPDP Rules 2025:** notified Nov 2025. **Administrative** pieces (Board, etc.) started then. **Consent-manager** pieces ~Nov 2026. **Substantive** duties (notice, consent, breach to Board, s.16 transfers, repeal of IT Act s.43A) are staggered to **~13–14 May 2027**.
- **Until substantive DPDP commences:** **IT Act s.43A + SPDI Rules 2011** still matter for sensitive personal data and the “comparable protection” cross-border test.
- **CERT-In 2022 directions:** 6-hour incident reporting + logging retention — treat as binding if you are in scope (connected systems / service provider). Keep logs. Have a breach runbook. Do not invent “we’re too small.”

### 12.2 Voice as biometric

**Unresolved.** SPDI definition of biometric includes voice patterns. Conservative operator: treat recordings/voiceprints as sensitive, get consent, contract the US sub-processors, minimise retention. Do not claim “India-only data” while Azure US is on the live path.

### 12.3 What you must ship in product + paper

- Privacy Policy (you as fiduciary for account data; processor for call content).
- DPA with each client (processor clauses, sub-processor list, deletion, breach notice).
- Sub-processor list: Bolna, Sarvam, Azure/OpenAI/Gemini, Exotel/Plivo/Vobiz (theirs), Cloudflare/R2, VPS, Sentry, Resend, etc.
- Click-through DPAs where the vendor offers them (Microsoft, Google, Cloudflare). Bolna — check; do not assume.
- Grievance Officer: can be **you**. Publish name, email, Indian phone, address (IT Rules / consumer e-commerce hygiene; payment gateways look for this).
- Recording: cautious practice = announce. Case law on one-party recording is messy; do not rely on “India is one-party” as a slogan.
- Default PII redaction, retention sweeps, erasure certificate — you already built these; keep the draft banner until an advocate reviews.

### 12.4 Consumer Protection / E-commerce Rules

B2B SaaS to tiny proprietors can still be argued into “e-commerce entity” territory by a gateway or a consumer forum. Put the statutory contact + refund + grievance pages up regardless.

---

## 13. Contracts and website (minimum credible bar)

Your competitor bar: Pvt Ltd + GSTIN + Refund + Privacy with named GO + sub-processors + AUP. You will not match Pvt Ltd/GSTIN at launch. Match **everything else**.

### Must publish before Razorpay live

1. Terms of Service  
2. Privacy Policy  
3. Refund & Cancellation  
4. Grievance Redressal (named human = you)  
5. Contact (Indian phone + address + email)  
6. Acceptable Use (no cold-call abuse, no US/EU outbound, no non-consented lists, no 160-for-promo)  
7. Cookie notice if you use analytics cookies  

### Must have in the folder (even if not all public)

8. Data Processing Addendum (client signs or clickwrap)  
9. Sub-processor list  
10. Order form / quote  
11. Optional MSA/SLA for high-touch  

Have an **advocate** review before you take serious volume. Templates + draft banner are not a defence.

### Contract points for Model B

- Client warrants they are subscriber of record and PE.
- Client warrants consent / DND / purpose limitation for every number they upload.
- Client indemnifies you for list/consent/header misuse.
- You still cap your liability (e.g. 3–12 months fees) **except** you may leave **their** telecom/consent breaches uncapped **their** side.
- IP: client owns their recordings, transcripts, CRM fields, agent config they created; you own the platform, models’ generic improvements, and product IP.
- Termination: they keep the number (it was always theirs). You delete or export per DPA. You revoke API keys.

Insurance (cyber / PI) is optional at this size; shop later when revenue exists. Availability in India for tiny proprietors is hit-and-miss.

---

## 14. Product / engineering obligations that are “legal”

These are not registrations. If you skip them, the TM registration is theatre.

- Per-tenant carrier credentials (never one global Exotel key for all clients).
- Refuse outbound if PE–TM chain / consent / DND gate fails.
- Append-only consent + usage ledger (you already designed this).
- No tax invoice without GSTIN — proforma / bill of supply only (you already designed this).
- Campaign compliance gate.
- Recording announcement toggle default ON.
- Honest answer to “are you an AI?”
- Geographic AUP: no US/EU/UK outbound in this freeze.
- Sub-processor page stays truthful (US LLM = say US).

---

## 15. What you pay vendors vs what you register

You will pay subscriptions (Bolna, cloud, LLM, email). That does **not** require GST registration by itself.

Keep invoices. After GST, ask the CA about RCM on foreign SaaS.

Paying those vendors does **not** make you a telecom licensee.

---

## 16. Sequenced checklist (this scenario only)

### A. Before taking any money

| # | What | Who | Cost | Time | If skipped |
|---|---|---|---|---|---|
| A1 | Decide trade name; Terms say you are the proprietor | You | 0 | 1 hour | Confused invoices |
| A2 | Udyam | You | 0 | 15 min–1 day | Bank / DLT / gateway friction |
| A3 | Current account (or accept savings **only** for a single test charge) | You + bank | min balance | 2–4 days | Gateway caps / freeze risk |
| A4 | Publish Terms, Privacy, Refunds, Grievance, Contact, AUP | You (+ advocate later) | 0–lawyer | 1–3 days | Razorpay reject; IT Rules hole |
| A5 | Razorpay (or peer) KYC → test payment | You | MDR only | 2–3 days | Cannot collect |
| A6 | Folder for books (invoices, settlements, vendor bills) | You | 0 | 1 hour | ITR pain |
| A7 | Confirm with CA: ITR head, advance tax, AP professional tax, 44AD/44ADA **no** | CA | ₹2k–10k one-shot | 1 meeting | Wrong ITR |

GST is **not** in this list.

### B. Before first **inbound** live call (client’s number)

| # | What | Who | Cost | Time | If skipped |
|---|---|---|---|---|---|
| B1 | Client opens Exotel/Plivo/Vobiz, KYC, buys DID | Client | their rental | days | No number |
| B2 | Client gives you API credentials + number | Client | 0 | 1 hour | Cannot connect |
| B3 | You store per-tenant secrets; connect Bolna inbound | You | Bolna bill | hours | Dead air |
| B4 | Recording / AI disclosure on the inbound agent | You | 0 | hours | Privacy/complaint risk |
| B5 | DPA + AUP accepted by client | You + client | 0 | same day | Processor hole |

**No TM. No Calevate carrier account. No GST.**

### C. Before first **outbound** campaign or automated callback

| # | What | Who | Cost | Time | If skipped |
|---|---|---|---|---|---|
| C1 | You register **TM** on one DLT portal | You | ~₹5,900 | 2–3 days | UTM / disconnect |
| C2 | Client registers **PE**, headers, templates | Client | their DLT fee | days | No chain |
| C3 | PE–TM chain Active both sides | Both | 0 | 1–2 days | Messages/calls fail or illegal |
| C4 | Right number class (140 for promo; not 160-for-sales; not raw mobile for blast) | Client + you | their DID | days | Penalty + cut |
| C5 | DND/DNC scrub + consent artefacts in product | You | engineering | before send | Joint liability |
| C6 | Client PE–TM + consent checklist in your onboarding UI | You | engineering | before send | Sales will skip it |

### D. Defer until a trigger

| Item | Trigger |
|---|---|
| GSTIN + LUT | ₹20 lakh **or** client blockage **or** foreign clients (foreign = new playbook) |
| Shops & Establishment | Bank/DLT asks, or you rent an office |
| AP Professional Tax | CA says you are in the slab |
| Own Exotel/Plivo account | You want a Calevate demo/support DID |
| Pvt Ltd / OPC | Liability, fundraising, or mid-size clients refuse to contract an individual |
| Advocate review of 8 legal docs | Before any non-trivial volume or first outbound |
| Cyber / PI insurance | When monthly revenue makes premium rational |
| WhatsApp WABA | When you sell WhatsApp; client owns WABA |
| e-invoicing | Crore-scale turnover |

---

## 17. Decision tree (India-only, this entity)

```
First rupee?
  └─ Udyam + (savings test OR current account) + legal pages + Razorpay

First call inbound only?
  └─ Client DID + client carrier KYC + Bolna + DPA. No TM. No your carrier.

Any outbound (callback, campaign, promo)?
  └─ STOP until your TM-ID + their PE + Active chain + correct series + scrub.

Client wants YOU to give them a number for ₹X/month?
  └─ NO (Model A). Send them to Exotel/Plivo. Or lose the deal.

Turnover → ₹20 lakh or ITC demanded?
  └─ GST. Then RCM on foreign vendors becomes your problem.

Foreign client appears?
  └─ Stop. This playbook does not cover it.
```

---

## 18. Stop-list (plain language)

1. Do not resell Indian numbers from a pool in your name.  
2. Do not run promo/cold outbound on 160-series or ordinary 10-digit mobiles.  
3. Do not originate outbound without TM + Active PE–TM chain.  
4. Do not assume the client’s indemnity saves you from TRAI.  
5. Do not use a personal savings account as the permanent merchant settlement account.  
6. Do not skip ITR because you skipped GST.  
7. Do not tell clients data stays in India if Azure US hears the transcript.  
8. Do not take US/EU/UK outbound “just this once.”  
9. Do not put your TM-ID into the client’s **PE registration form** as if they were registering as you. They register as PE, then bind you.  
10. Do not open a Calevate carrier account “just in case” and park client traffic on it — that recreates Model A.  
11. Do not file 44ADA because a YouTube CA said “all freelancers.”  
12. Do not issue a GST tax invoice without a GSTIN (proforma / bill of supply only).

---

## 19. Hybrid later?

Model B for everyone is the launch rule.

A future “we provision the number for self-serve” tier is **Model A** and is **unsafe** for a proprietor. If you ever do it: incorporate first, get written VNO/reseller status from a licensed operator, and still keep promo off those DIDs unless 140 + PE is real.

---

## 20. What this does *not* settle (honest unknowns)

Take these to professionals. Do **not** fill with guesses.

**CA**

- 44AD vs 44ADA vs regular books for a metered SaaS.  
- Advance-tax computation on your actual numbers.  
- AP PTEC applicability for a home proprietor.  
- SAC 998315 and mixed supply (software + minutes) when GST starts.  
- Whether any subscription you pay already needs 15CA/15CB / s.195 at your size.  
- QRMP vs monthly once GST exists.

**Advocate (telecom + IT)**

- Written confirmation Model B + TM + client DID is the intended TCCCPR pattern for AI outbound (it matches PE–TM docs; voice-AI is still thin in primary text).  
- Voice recording = biometric under SPDI?  
- CERT-In 6-hour rule applicability to a tiny SaaS.  
- Review of Terms / Privacy / DPA / AUP.  
- Whether any DoT “end-user list” issue appears if you ever touch Model A.

**Telecom lawyer (only if you reopen Model A)**

- Can a SaaS sit as authorised reseller under a UL-VNO without its own licence?  
- s.3(7) Telecommunications Act 2023 vs disclosed end-users.  
- Number reassignment quarantine.

**Bolna / carrier docs (you)**

- Current Exotel/Plivo/Vobiz “connect” fields.  
- Whether one DID can be voice + SMS + WhatsApp on that carrier.

---

## 21. One-page shopping list (launch)

Print this.

- [ ] Trade name + “Calevate is a product of [name], sole proprietor”  
- [ ] Udyam  
- [ ] Current account (after first test)  
- [ ] Razorpay + cancelled cheque  
- [ ] Website: Terms, Privacy, Refunds, Grievance (you), Contact, AUP  
- [ ] DPA + sub-processor list  
- [ ] Books folder  
- [ ] CA 1-hour: ITR + PT + presumptive **no**  
- [ ] Bolna account  
- [ ] Onboarding UI: client pastes Exotel/Plivo keys + number  
- [ ] Inbound-only live  
- [ ] **Before outbound:** TM-ID (~₹5,900)  
- [ ] Client PE + headers/templates + PE–TM Active  
- [ ] Scrub + consent gate on  
- [ ] GST: not yet; calendar reminder at ₹15 lakh run-rate  

**Not on the list:** company, GST, IEC, LUT, your own DID, foreign payments, Model A.

---

## 22. How the pieces fit (single diagram)

```
You (PAN) ── Udyam ── Current A/c ── Razorpay ── INR from AP/TS clients
        │
        ├── DLT TM-ID  (only when outbound exists)
        │         ▲
        │         │ PE–TM chain
        │         │
Client ─┴── DLT PE-ID + headers/templates
        │
        └── Exotel/Plivo/Vobiz account + DID (their KYC)
                    │
                    ▼
                  Bolna  ── Sarvam / Azure / your app
```

You are the **software + TM**.  
They are the **subscriber + PE + paying customer**.  
Bolna is **neither** a carrier nor a DLT principal.

That is the entire lawful launch shape for this freeze.

---

*End of playbook. Update this file if you take a foreign client, incorporate, take GST, or start provisioning numbers yourself.*
