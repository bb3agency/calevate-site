# Comet research brief — phone number provisioning, ownership and DLT

> **RESEARCH BRIEF, not legal advice.** Companion to `comet-research-brief.md`.
> This one asks a single narrow question that `D-47` (ROADMAP §6) explicitly left open
> and that `apps/api/compliance/kyc.py` names in its header as "Not settled, and therefore
> not built".

---

# RESEARCH TASK

I run an Indian B2B SaaS (**Calevate**) that gives client businesses **AI voice agents**
that answer and place real phone calls over Indian telecom infrastructure. I need to
settle **who legally holds the phone connection**, because two viable architectures exist
and I do not know which is lawful, which is cheaper, and which moves liability off me.

Answer with **primary sources** (DoT instructions/circulars, TRAI regulations, the
Telecommunications Act 2023, the operators' own published terms). Mark every answer
**CONFIRMED (primary source)** / **REPORTED (secondary only)** / **UNRESOLVED**. Do not
fill gaps with plausible guesses — a clearly-marked unknown is more useful to me than a
confident wrong answer.

## WHAT I ALREADY KNOW (do not re-research; correct me only if I am wrong)

These are established from primary/authoritative sources already:

1. DoT discontinued **"bulk connections"** and replaced them with **"business
   connections"** (instructions 31 Aug 2023, expanded May 2024). To issue one, the
   licensee must obtain the entity's **CIN / business licence / trade registration**, the
   **customer address**, the **GST certificate where applicable**, and a **list of
   end-users** with name, designation and identity-document details.
2. A DoT circular of **16 June 2025** extends the same KYC protocols to **internet
   telephony / cloud numbers** — a virtual number is not a lesser thing than a SIM.
3. **Telecommunications Act 2023 s.3(7)** obliges authorised entities to identify their
   users. Fraudulently obtaining a telecom identifier **on another person's identity**
   carries up to **3 years and ₹50 lakh**.
4. **Exotel** requires KYC plus a **Customer Acquisition Form (CAF)**, requires the address
   proof to **match the city the number is bought in**, and **blocks outgoing calls until
   KYC is verified**.
5. **DLT Principal Entity (PE) registration overlaps but does NOT subsume connection KYC.**
   PE registration is held by an access provider for headers and templates; it carries no
   address tied to the number's city, no end-user list and no CAF.
6. DLT registration **does accept sole proprietorships and individuals** (PAN + a
   proof-of-entity document such as GST certificate or Shops & Establishment licence);
   it does not strictly require a company with CIN. One-time entity registration is
   roughly ₹5,900, with a further ~₹5,000 + GST per operator for telemarketer
   registration. **Verify this — it is currently REPORTED, from vendor fee schedules.**

## THE TWO ARCHITECTURES I AM CHOOSING BETWEEN

### Model A — I hold the connections ("buy numbers in bulk and allocate them")

I take business connections in **my own entity's name**, hold a pool of numbers, and
allocate one to each client for a monthly fee. A direct competitor does exactly this and
sells numbers to clients at **₹649/month**. Their numbers are contractually
**transactional/service-only, not for promotional calling.**

### Model B — the client holds the connection

The **client** buys their own number in their **own entity's name**, with their own KYC and
their own address. The client registers as **Principal Entity (PE)** on DLT under their own
PAN/GST/CIN. **I register as the Telemarketer (TM)** and am linked to their PE. My platform
triggers calls on their number over API, but the subscriber of record is them, and they pay
the DLT and connection fees.

---

# THE QUESTIONS

## PART 1 — Model A: is bulk-buy-and-allocate lawful for a non-licensee?

1.1 **The core question my own research could not settle:** must a **non-licensee reseller**
itself hold the **CAF**, or does furnishing the client entity's documents to the licensed
operator (e.g. Exotel's UL-VNO entity) discharge me? The sources I found describe the
**LICENSEE's** obligation and are silent on the reseller's. Settle this if it is settleable,
and say plainly if it is not.

1.2 Is the **"list of end-users"** requirement in the business-connection instructions the
mechanism that legitimises Model A? I.e. if I hold connections in my name and honestly
furnish each client as the end-user, am I compliant — or does the obligation still require
the *using* entity to be the subscriber?

1.3 **Does allocating a phone number to a client for a monthly fee constitute reselling
telecom services**, and does that require any DoT authorisation, licence or registration
that I do not have? Cover the **UL-VNO** category and whether an unlicensed SaaS can lawfully
do this at all.

1.4 **Where exactly does Telecommunications Act 2023 s.3(7) bite in Model A?** If a client
uses a number registered in my name to make calls, is that "obtaining a telecom identifier
on another person's identity", or is that provision aimed only at fraud? What does a
compliant Model A operator have to do to stay clear of it?

1.5 The competitor sells numbers at ₹649/month on a **transactional/service-only** basis.
**Why would a number be contractually restricted to service-only?** Is that a 160-series
constraint, a DLT header-category constraint, a TSP contractual term, or a legal one? And
what does that imply about whether Model A can ever support **promotional/cold outbound**?

1.6 **Is the competitor's model actually lawful?** Do not assume it is. If they are exposed,
say where.

## PART 2 — Model B: client-owned connection, me as operator

2.1 Is Model B **clearly lawful** and does it remove the Part 1 problems entirely?

2.2 **Can a third party (me) operate calls on a connection held by someone else?** Check the
published terms of **Exotel, Plivo, Knowlarity, Ozonetel and Twilio India** for whether:
   - a sub-account or delegated-access model exists,
   - API credentials may lawfully be shared with or issued to a vendor,
   - the TSP's terms permit an agency/third-party to originate traffic on the client's
     account.
   Quote the actual clause where you can find it.

2.3 **What onboarding friction does Model B impose on the client, concretely?** List every
step, form, document, fee and realistic elapsed time from "client says yes" to "first
outbound call is legal". I need to know whether this kills a low-touch sales motion.

2.4 In Model B, **does TM liability still attach to me?** Specifically: if the client (as PE)
supplies a list without consent and my platform dials it, is the liability the PE's, the
TM's, or **joint**? Cite TCCCPR. **Do not assume Model B moves liability off me** — I want to
know exactly what stays.

2.5 What happens on **termination**? If the client owns the number and leaves, do I lose
anything? If I own it (Model A) and they leave, can I lawfully reassign the number to
another client, or does that trigger a fresh KYC and a quarantine period?

## PART 3 — Concurrency and technical reality

3.1 **How many simultaneous calls can run on one Indian DID/virtual number?** Is concurrency
a property of the **number**, the **trunk/channels**, or the **account**? What do Exotel and
Plivo actually sell — per-number channel limits, or account-level concurrency?

3.2 For **inbound**, can one number receive many simultaneous calls, and what is the actual
purchasable unit?

3.3 If a client brings their own number/trunk, does my rented voice platform (**Bolna**)
support **BYO-trunk / SIP connect**, and what does that integration require? (Bolna publishes
"connect" guides for Exotel, Plivo and Vobiz — confirm what "connect" means in practice and
whether the number can stay in the client's account.)

## PART 4 — 140 vs 160 series, and what each model can dial

4.1 Explain the **140-series (promotional)** vs **160-series (transactional/service)** number
classes: who can get each, what documents, and what traffic each is permitted to carry.

4.2 **Which model (A or B) can lawfully do cold/promotional outbound**, and what is required
— DLT header registration, content-template approval, consent artefacts, DNC scrubbing?

4.3 Is there a **number class an AI voice agent may not use at all**? Is there any restriction
specific to automated or AI-originated voice calls?

## PART 5 — SMS and WhatsApp (the reason I am asking)

5.1 If the client owns the number and is the PE, **can they also use it for SMS** with their
own registered header and templates, and does that keep DLT content liability with them?

5.2 **WhatsApp is a separate regime.** Explain: WABA (WhatsApp Business Account), the BSP
(Business Solution Provider) model, template approval, and **who must own the WABA** — me or
the client. Is WhatsApp under DLT/TRAI at all, or purely under Meta's own policy? What
Indian-law obligations attach to WhatsApp business messaging?

5.3 **Can one phone number carry voice + SMS + WhatsApp simultaneously**, or does each channel
need its own number? This is a practical blocker I need answered precisely.

5.4 If I build SMS and WhatsApp on the **client's** identity throughout, **what liability
genuinely stays with me** as the software that sends?

## PART 6 — Give me a recommendation

6.1 A side-by-side comparison of Model A and Model B on: **legality/confidence, my liability,
client onboarding friction, my margin, scalability, and exit/termination risk.**

6.2 **A hybrid**: is it sensible to run Model B for high-touch managed clients and Model A
only for a low-touch/self-serve tier — or does Model A's risk make it unusable at any tier
for a solo founder with no corporate veil yet?

6.3 **What does the entity choice do to this?** Does either model become materially safer or
outright require a **Private Limited Company** rather than a proprietorship?

6.4 **The stop-list**: what must I not do here, in plain language.

6.5 **Everything you could not verify**, with what you found and what a telecom lawyer would
need to settle it.

---

## OUTPUT FORMAT

Organise by Parts 1–6. Every factual claim gets a **source link and retrieval date** and a
confidence label. End with a **decision table** (Model A vs Model B vs Hybrid) and a short
**"questions for a telecom lawyer"** list.
