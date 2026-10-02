# What stops Calevate serving US clients — and what it costs to operate from India (7 Sep 2026)

**Status:** research memo, not a decision. Nothing in code or in
`docs/legal/LEGAL-OPS-PLAYBOOK.md` changes because of this file. It records the answer to
three founder questions so the next person inherits the evidence, not the conclusion:

1. What is actually limiting us from handling US clients?
2. What would we need, legally, to work with US clients?
3. What constraints apply to operating wholly from India, regardless of client geography?

Evidence classes follow hard rule 11. **REPO** = a statement already in this tree, cited
`file:line`; it is a claim carrying its own class, not proof. **WEB** = a page read on
7 Sep 2026 and linked in §6. **CODE** = read from source this session. **UNKNOWN** = no
source. Nothing here is legal advice; the playbook's own rule applies — a lawyer signs off
before any of it becomes a contract or a filing.

---

## 1. The binding constraint is a decision, not a law

- `docs/legal/LEGAL-OPS-PLAYBOOK.md` §0 (REPO) freezes scope: **India-only B2B, no foreign
  clients**, founder is a **sole proprietor** trading as "Calevate" (no company), AP + TS
  only, no GST registration at launch, Udyam MSME, Model B numbers (each client buys and
  KYCs their own Exotel/Plivo/Vobiz number), founder = DLT Telemarketer, each client = a
  Principal Entity. It closes with: if any of that changes — a foreign client among them —
  "this playbook is stale".
- `docs/legal/comet-legal-research.md` (REPO) lines 2–4 record that Part G (US TCPA) and
  the FEMA / FIRC / SOFTEX / EDF material were written BEFORE the freeze and are parked, not
  resolved.

So nothing forbids a US client. What a US client does is un-freeze §0, and everything in
§2–§4 is the price of un-freezing it.

---

## 2. US law that would bind us on day one

### 2.1 TCPA — the one that decides it

- The FCC's **Declaratory Ruling of 8 Feb 2024** brought AI-generated voices inside the
  TCPA's "artificial or prerecorded voice" restriction (WEB — Wiley alert, §6). Outbound
  MARKETING to a US number therefore needs **prior express written consent**;
  informational calls need prior express consent (WEB — Henson Legal; Ginsburg Law).
- Revocation rules effective **11 Apr 2025**: opt-outs "by any reasonable means", honoured
  within **10 business days** (WEB — Henson Legal).
- **One-to-one consent** (the Dec 2023 rule) was **vacated by the 11th Circuit in Jan 2025
  and eliminated by the FCC in Sept 2025** (REPO — `comet-legal-research.md` Part G;
  corroborated WEB — Ginsburg Law). So the consent standard is the pre-2023 one, which is
  still written consent for marketing.
- Statutory damages **$500–$1,500 per call, uncapped**, private right of action, the most
  active plaintiff's-bar statute in US consumer law (WEB — Henson Legal; Ginsburg Law).
  A 10,000-call campaign is $5M–$15M of theoretical exposure. A technology provider can be
  named directly; a client indemnity does not reliably shield it.
- **Inbound AI-answered calls do not raise TCPA consent** — the consumer initiated the
  call (REPO — Part G; consistent with WEB sources). This is the same argument
  `docs/ROADMAP.md` D-38 makes for India ("inbound is consent-clean").
- Comet's Part G conclusion (REPO, quoted): serving US outbound as "a solo,
  thinly-capitalized Indian founder carries meaningfully asymmetric risk relative to the
  deal size of any single SMB client." This memo agrees.

### 2.2 The founder is a person, not a company

- A sole proprietorship is a disregarded entity for US withholding: the **W-8BEN is filed
  in the founder's personal name**, PAN as Foreign TIN, valid three calendar years (WEB —
  Karbon guide). Every US client's AP team asks for it.
- Consequence: **personal assets stand behind every TCPA claim.** For India-only B2B the
  playbook judged that acceptable. For US outbound it is the constraint that compounds all
  the others.

### 2.3 State law on top

- **California B.O.T. Act (SB-1001)** — bot disclosure in commercial contexts; **Florida
  FTSA** and **Oklahoma OTSA** — written consent and per-day solicitation caps (WEB —
  Henson Legal). Our server-enforced `agents.ai_disclosure_line` (hard rule 5, D-163) is
  the right mechanism and would map onto these.
- **All-party recording consent** in 11–12 states — California, Florida, Illinois,
  Pennsylvania, Washington among them — and **when calling across state lines the
  strictest law applies** (WEB — SalesCaptain guide). Our product records every call by
  default; `recording_notice_line` (D-163) is a per-agent TOGGLE today. For a US number it
  would have to be **non-optional in those states**, which is a code change to the dial
  gate, not a setting.

### 2.4 HIPAA, if any client is a clinic

- Clinics are our best Indian vertical. In the US, PHI on a call means a **Business
  Associate Agreement with every vendor that touches it** — carrier, STT, LLM, TTS (WEB —
  Retell BAA article). For us that is the telephony provider, Bolna, Sarvam and Azure,
  each separately. **Whether Sarvam signs a US BAA: UNKNOWN**, and CLAUDE.md records that
  Sarvam ToS s.17.5 permits training on Inputs/Outputs absent a signed enterprise
  agreement — which a BAA would have to displace.

---

## 3. The product is built for India — and that is load-bearing, on purpose

CODE, read this session. A US tenant needs every row changed, and none is a flag:

| Hard-coded today | Where | US equivalent needed |
| --- | --- | --- |
| Calling window **09:00–21:00 IST**, platform-fixed | `apps/api/compliance/service.py:477` | A per-tenant timezone window (TCPA: 8am–9pm callee-local) |
| `IST = timedelta(hours=5, minutes=30)` | `apps/api/compliance/service.py:85` | Callee-local time, not a platform constant |
| Money is **NUMERIC INR** (hard rule 7) | `apps/api/billing/rates.py:31` | USD invoicing, or INR invoicing with FX exposure on us |
| DNC = TRAI's **DND registry**; `national_dnd_scrub_*` codes | `apps/api/compliance/national_dnd_routes.py` | FTC **National DNC Registry** subscription + state lists |
| Compliance gate requires a **PE–TM DLT chain** | playbook §0; `compliance/service.py` | No DLT in the US; the gate would need a per-country regime |
| Speech is **Sarvam** (Saaras STT, Bulbul TTS) — D-36 | CLAUDE.md | English STT/TTS provider; Sarvam's US-English quality UNKNOWN |
| Numbers via **Exotel / Plivo / Vobiz**, client-KYC'd (Model B) | playbook §0 | Twilio/US carrier; no Indian KYC regime applies |

The India-ness sits in the **dial gate**, which is where hard rule 5 wants it. That is a
feature for the Indian product and the reason a US tenant is an engineering project, not a
configuration.

---

## 4. Operating wholly from India — constraints that bite with ANY foreign client

REPO — `docs/legal/comet-legal-research.md` (GST/FEMA parts) unless marked WEB.

- **GST registration becomes effectively unavoidable.** Export of OIDAR-type services
  triggers registration exposure regardless of the ₹20 lakh threshold, because filing an
  **LUT (RFD-11)** for zero-rated export and documenting place of supply generally require
  a GSTIN. Once registered, **reverse charge applies to every foreign vendor bill** — Azure,
  OpenAI, Google, Bolna, Cloudflare, Sentry, Resend — at 100% IGST under
  Notification 10/2017-IT(R). Being unregistered today avoids that whole leg.
- **FEMA paperwork returns**: LUT before the first foreign invoice, **FIRC/BRC** per
  inbound payment, **SOFTEX/EDF** filing on roughly a 30-day cycle.
- **W-8BEN** to every US payer (WEB — Karbon), in the founder's personal name (§2.2).
- **Insurance stops being optional.** Tech E&O and cyber liability are expected by US
  buyers; some accept only a Lloyd's coverholder or a US-admitted carrier, i.e. a policy
  bought in the UK or Singapore rather than India (WEB — Sarvada note on Indian SaaS E&O
  coverage gaps).
- **Payment rails**: the playbook excluded Stripe Atlas and a US entity by decision, not
  by law. Receiving USD as a proprietor into an Indian account is legal and routine; the
  paperwork is the cost above.

---

## 5. What this memo recommends

1. **Inbound-only US, if anything, ever.** No TCPA consent question, no DLT, no DND; the
   remaining obligations are all-party recording consent and a US number. A different
   liability universe from outbound.
2. **Outbound US: not as an individual.** Sequence if it is ever wanted: a US LLC or an
   Indian Pvt Ltd → E&O + cyber cover → a TCPA-specialist review of the consent capture →
   the §3 engineering → first dial. Not in any other order.
3. **Strategic**: the US AI-receptionist market is the most crowded and best-funded
   segment there is; we would arrive without the Telugu/Indian-language edge that
   differentiates us at home and with all of the liability. The compliance depth already
   built (TRAI/DLT/DPDP/DND) is a moat precisely because it is hard and local.

Nothing in this file is "ours" to schedule — every item in §2 and §4 waits on something
outside the repo (an entity, an insurer, a lawyer, a registration). Per the tempo rule,
that is the only kind of deferral that is allowed to have a timeline, and each is named.

---

## 6. Sources read 7 Sep 2026 (WEB)

- Wiley — FCC extends TCPA to AI-generated voices:
  <https://www.wiley.law/alert-FCC-Extends-Regulatory-Reach-Over-AI-Announces-TCPA-Restrictions-Cover-AI-Generated-Voices-in-Outbound-Calls>
- Henson Legal — AI voice compliance, TCPA + state laws 2026:
  <https://www.henson-legal.com/ai-voice-compliance>
- Ginsburg Law Group — AI robocalls and TCPA consent rules:
  <https://ginsburglawgroup.com/2026/02/ai-robocalls-the-tcpa-consent-rules-you-need-to-know/>
- SalesCaptain — call recording laws by state 2026:
  <https://blog.salescaptain.com/call-recording-laws-by-state-2026-compliance-guide/>
- Retell — HIPAA BAAs for voice agents:
  <https://www.retellai.com/blog/do-retell-ais-voice-agents-have-hipaa-compliance-and-baas>
- Karbon — W-8BEN for Indian freelancers:
  <https://www.karboncard.com/blog/w-8ben-indian-freelancers-guide>
- Sarvada — SaaS Tech E&O insurance in India, coverage gaps:
  <https://sarvada.ai/startups-new-economy-insurance/saas-startup-tech-eo-insurance-india>

In-repo: `docs/legal/LEGAL-OPS-PLAYBOOK.md` §0; `docs/legal/comet-legal-research.md`
Part G and the GST/FEMA parts; `docs/ROADMAP.md` D-38, D-163.

Not read this session, so not cited: the FCC ruling text itself, 47 CFR §64.1200, the
FTC National DNC Registry fee schedule, any state statute in the original. **A lawyer reads
those before anything here becomes a contract.**
