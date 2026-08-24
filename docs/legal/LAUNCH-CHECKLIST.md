# Calevate — Founder Launch Checklist (external action ↔ what the code already does)

**What this is.** A single ordered list of the things a *person* must do — register, appoint,
sign, decide — to take Calevate from "nothing in production" to a lawful first client, with
each action tied to the code or config that is **already built and waiting for it**. It is a
bridge, not a new plan:

- The **canonical sequence, costs and legal reasoning** live in `LEGAL-OPS-PLAYBOOK.md`
  §16 (sequenced checklist A–D) and §21 (one-page shopping list). This file does not restate
  them — it points at them and adds the column the playbook cannot have: *what in this
  repository is already done, so the only thing left is the external step.*
- The **obligation-to-code map** is `../LEGAL-SURFACE.md`. Where a row below says "gate
  built", that map is the evidence.
- Precedence: the **playbook wins** over this file; this file wins over nothing. If they ever
  disagree, fix this file.

**The one framing fact (LEGAL-SURFACE §0):** *nothing is in production.* Almost every item
below is blocked on a founder decision or an external registrar, **not** on engineering. The
code side of the compliance surface is substantially built; the gates exist and refuse the
unsafe path today. What is missing is the paperwork that turns the gates from theatre into
enforcement.

> ⚠ **Not legal advice.** The unknowns the playbook lists (§20) — presumptive tax, AP
> professional tax, voice-as-biometric, the exact DPA retention numbers — go to a CA or an
> Indian telecom/IT advocate **before** money moves or the first outbound call originates
> (root `CLAUDE.md` hard rule 11: a REPORTED/UNRESOLVED item is a question for a
> professional, never a fact to wire in).

---

## Phase A — Before taking any money (all external; no code blocks this)

| # | Founder action | Cost / time | Code already waiting | Status |
|---|---|---|---|---|
| A1 | Fix the trade name; Terms say "Calevate is a product of **[legal name]**, sole proprietor" | 0 / 1 h | `LEGAL_ENTITY_NAME` token in `apps/web/src/lib/legal/placeholders.ts`; every `/legal/*` page renders it | ☐ |
| A2 | **Udyam (MSME)** registration under the founder's PAN | ₹0 / 15 min–1 day | Nothing to wire — it is the proof the *next* steps consume (bank, DLT, gateway) | ☐ |
| A3 | Proprietorship **current account** in the trade name (savings only for a single test charge) | min balance / 2–4 days | Settlement account for Razorpay; not modelled in code | ☐ |
| A4 | **Appoint a Grievance Officer** (may be the founder) and a data-protection contact | 0 / same day | `GRIEVANCE_OFFICER_NAME/DESIGNATION/EMAIL` + `DATA_PROTECTION_CONTACT_NAME/EMAIL` tokens; `/legal/grievance` and `/legal/privacy §14` already publish them; gates **DP-8, DP-9, S-2** built | ☐ **cheapest unmet statutory obligation — closes two instruments** |
| A5 | Fill the remaining founder blanks in `placeholders.ts` (address, phone, support email, effective date, jurisdiction city, refund/notice/return windows) | 0 / 1 h | 18 declared `{{TOKEN}}`s, each with its source in `placeholders.ts`; `PRIMARY_HOSTING_LOCATION` already filled (D-180). `tests/legal.test.tsx` asserts every token used is declared and vice-versa | ☐ |
| A6 | **Advocate review** of the 8 legal documents, then flip `PENDING_LEGAL_REVIEW` → `false` | lawyer fee / 1 review | All 8 documents (Privacy, Terms, AUP, DPA, Sub-processors, Refunds, Grievance, Cookies) are written and typed in `apps/web/src/lib/legal/`. The draft banner is on every page and **cannot be removed as a side effect** — `tests/legal.test.tsx` fails if `PENDING_LEGAL_REVIEW` is flipped without deleting the assertion that guards it | ☐ **nothing on `/legal/*` may be shown to a client, regulator or gateway until this is done** |
| A7 | **Razorpay** (or peer) KYC → one test payment | MDR only / 2–3 days | `apps/api/billing/payments.py` — Razorpay-only (`PROVIDER = "razorpay"`), INR-only (`SUPPORTED_CURRENCY = "INR"`), gateway-hosted (no card data stored). Gateway onboarding needs A4–A6 pages live | ☐ |
| A8 | **CA one-hour**: ITR head (business/profession), advance tax, AP professional tax (PTEC), and confirm **not** electing 44ADA reflexively | ₹2k–10k / 1 meeting | No code; a books folder is enough at this size (playbook §5) | ☐ |

**GST is deliberately NOT in Phase A** (playbook §4). Below ₹20 lakh all-India services
turnover, inter-state supply does not force it. The billing code already refuses to issue a
GST tax invoice without a GSTIN and issues a **proforma / bill of supply** instead
(`billing/invoice.py`, gate **GST-3**). Set a calendar reminder at a ₹15 lakh run-rate.

---

## Phase B — Before the first **inbound** live call (no DLT, no GST, no Calevate carrier account)

Inbound reception is the lawful launch shape that needs the *least* paper (playbook §10.1,
§16-B). The code path is built; it waits on the client's number.

| # | Action | Who | Code already waiting | Status |
|---|---|---|---|---|
| B1 | Client opens Exotel/Plivo/Vobiz, does carrier KYC, buys the DID **in their own name** (Model B) | Client | — | ☐ |
| B2 | Client hands over per-tenant API credentials + number | Client | Secrets are stored **per tenant**, never one global carrier key (hard rule; engine isolation in `apps/api/engine/`). Envelope-encrypted in Postgres, KEK env-only | ☐ |
| B3 | Connect Bolna inbound for that tenant | You | VoiceEngine adapter (`engine/bolna.py`) + webhook receiver (source-IP verified, dedupe) + reconciliation poller | ☐ |
| B4 | Recording + AI disclosure set on the inbound agent | You | `agents.ai_disclosure_line` / `recording_notice_line` NOT NULL; both **enabled default TRUE** (`agents/models.py:252-257`); "answer truthfully if asked" is appended server-side and cannot be withdrawn | ☐ |
| B5 | Client accepts the **DPA + AUP** | You + client | `/legal/dpa`, `/legal/acceptable-use` (behind the A6 banner until reviewed) | ☐ |

---

## Phase C — Before **any outbound** (callback or campaign) — the gate is real and refuses today

Outbound is off in code until the DLT chain is Active. These are the blockers the campaign
launch path already enforces (playbook §10, §16-C; gates **T-1…T-9**):

| # | Action | Who | Code already waiting | Status |
|---|---|---|---|---|
| C1 | Register as **Telemarketer (TM)** on one DLT portal (founder PAN + Udyam) | You | `platform_state.tm_id`; blocker `tm_registration_missing` blocks **every** tenant's outbound at once until it exists | ☐ ~₹5,900 |
| C2 | Client registers as **Principal Entity (PE)**, headers, content templates | Client | `dlt_registrations(pe_id, status, tm_link_status)`; blockers `pe_registration_missing → pe_registration_not_active → tm_link_not_active`, sequenced | ☐ |
| C3 | **PE–TM chain Active** both sides | Both | The gate above will not clear until the link is Active | ☐ |
| C4 | Correct **number series** — 140 for promotional; never 160-for-promo; never a raw mobile for a blast | Client + you | `number_series_mismatch`, `number_not_registered`, `dlt_template_missing/_not_approved/_mismatch` | ☐ |
| C5 | DND scrub + consent artefacts | You (product) + operator | `preference_scrub_runs` re-checked every dispatch tick (verdict expires 23:59:59 IST); tenant DNC honoured before CAS to running; `consent_provenance_missing` refuses `purchased_list`. **T-5 is honestly marked PARTIAL** — the scrub reference is an accountable operator assertion, not a queried-back scrub; it becomes real with the C1 DLT login | ☐ |
| C6 | Calling hours | product | `09:00–21:00` IST default; a campaign may only narrow it | ✅ built |

**The big red switch** (global outbound halt) and per-campaign gates exist independently of
the above.

---

## Phase D — Sub-processor paperwork (parallel with A–C; the one whole-product data-protection gap)

No sub-processor DPA has been signed (gates **DP-11 downward / F-10 / S-5 protection leg**).
Every caller's raw speech reaches **Microsoft Azure OpenAI in East US 2 on every turn** —
so this is not optional hygiene, it is the transfer basis for the product's core data flow.

| # | Action | Priority | Note |
|---|---|---|---|
| D1 | Sign **Microsoft** Azure OpenAI DPA | **highest** | Receives raw caller speech in real time |
| D2 | Sign Google, Resend, Sentry, Cloudflare (R2), hosting DPAs | high | Click-through where offered |
| D3 | Record **Bolna**'s residency term in the contract **before** `ENGINE=bolna` | high | The pilot scorecard is an empty template; BYOK forecloses Bolna India routing (F-12), so this is a commercial decision, not a config toggle |
| D4 | Keep the **sub-processor register truthful** — US LLM says US | ongoing | Single source is `apps/web/src/lib/legal/subprocessors.ts`; never claim "data stays in India" |

---

## The unknowns that gate the launch but only a professional can close (playbook §20)

- **Voice = biometric SPDI?** (gate **S-6** / OPERATIONS §2 gate 37) — an advocate's yes/no.
  Governs the whole product until 13 May 2027, i.e. the exact window client #1 goes live.
  The code already treats call audio as if it may be SPDI; nothing in the tree may answer the
  question.
- **CERT-In 6-hour breach reporting** applicability — treat as binding; the runbook
  (`runbooks/data-breach-notification.md`) exists, the Data Protection Board's reporting
  channel is an outstanding lookup (DP-12).
- **Exact DPA retention numbers** — uploaded campaign contacts still have no clock by design
  (DP-13); the period is a founder+counsel DPA commitment, not a code default to invent.
- **Model B + TM + client DID** confirmed as the intended TCCCPR pattern for AI outbound —
  written confirmation from a telecom advocate (playbook §20).

---

*Update this file when a founder action lands, when the code that backs a row changes, or
when the playbook's §16 sequence changes. If a foreign client, incorporation, GST, or
self-provisioned numbers ever come back, this file is stale — reopen the playbook first.*
