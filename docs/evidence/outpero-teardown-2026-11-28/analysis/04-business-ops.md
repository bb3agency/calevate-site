# 04: business model and operations, Outpero against Calevate (28 Nov 2026)

Scope: pricing and what an owner pays, billing UX, numbers and KYC, concurrency, calling hours
and retries, DNC, caller memory and call-backs, notifications, data export and privacy,
consent records, compliance posture, positioning and go-to-market, customer proof.

Read-only analysis. Nothing in the code was changed.

## Sources and evidence classes

- **Outpero:** `../public-site-and-docs.md` (public pages, VENDOR-PUBLISHED, read 28 Nov 2026)
  and `../screens/app-routes.md` (first-hand in-app read, 28 Nov 2026). Calevate's side of
  the same build: `../../outpero-vs-calevate-2026-11-28/LOG.md` (first-hand, 28 Nov 2026).
- **Calevate:** code at `794e7acdc` (branch rel-0.5.98), read for this analysis. File paths
  are cited at each point. Decision IDs come from rememory. A decision memory is a claim
  about the past, so it is used only where the code agrees with it or where it is labelled.
- **Labels used below:** CODE (read in this tree), FIRST-HAND (the 28 Nov LOG),
  VENDOR-PUBLISHED (Outpero's pages), VENDOR-STATED (ThinnestAI by email, relayed),
  DECISION (a founder decision row, value not read from production), UNKNOWN.
- **What was not verified:** the production `platform_config` values, in particular the
  attested number price, the console `thinnest_max_concurrent_calls`, and the trial
  settings in force. Wherever these appear they are marked UNKNOWN or DECISION.

---

## 1. What an owner pays

### 1.1 Price facts side by side

| Item | Outpero (28 Nov) | Calevate (code) | Verdict |
|---|---|---|---|
| Per minute, everyday voice | Standard ₹5 + 18% GST = **₹5.90** paid (VENDOR-PUBLISHED /pricing) | Clear **₹4.50** on every pack, no GST (CODE `apps/api/billing/credit_packs.py:209-246`; `apps/api/billing/gst.py`, `apps/web/src/lib/gstStatus.ts:11`) | **BETTER**: 23.7% less cash for a buyer without GST registration; 10% less against ₹5.00 for a buyer who claims input credit |
| Per minute, top voice | Premium ₹6.8 + GST = **₹8.024** (the docs say ₹7) | Studio **₹6.00**, no GST (CODE, same file) | **BETTER**: 25.2% less cash; 11.8% less against ₹6.8 net |
| Volume price | Custom "from ₹3.5", by quote. The in-app packs add bonus credit, e.g. ₹50,000 + 4,000 free, which works out to ₹4.63 a Standard minute (FIRST-HAND #/billing/add) | Flat on all six packs (₹2,000 to ₹50,000). D-728 says Studio may fall towards ₹5 only once volume fills a Cartesia plan (DECISION) | **PARITY or better**: our flat ₹4.50 is below their best pack's effective ₹4.63 ex GST. We have no published volume price |
| Billing step | 30 s blocks, unanswered calls free | 30 s (CODE `apps/api/billing/rates.py:2810` `_CLIENT_PULSE_WHOLE_SECONDS = 30`) | PARITY |
| Platform or subscription fee | None | Built but off: `platform_fee_enabled` defaults False (D-707). The /pricing page says "No platform fee" while it is off (CODE `apps/web/src/app/pricing/page.tsx:201`) | PARITY |
| Phone number | ₹649/month + GST = ₹765.82, includes 1 channel | Monthly fee frozen per number from an operator-attested price (CODE `apps/api/billing/number_rental.py`, D-665). D-681 set the client rental at **₹499** (DECISION; the production attestation was not read) | Probably **BETTER**. Confirm the attested value before saying so publicly |
| Concurrency | ₹649/month for each extra channel (= 1 concurrent call) | **2 calls at once free** for a paying client, 1 on trial (CODE `apps/api/tenancy/call_lines.py:44-46`). More only by operator approval of a request (`call_line_requests`); no price and no self-serve purchase | **BETTER** on price up to 2 lines; **WEAKER** on self-serve above 2 |
| Free trial | 50 credits (about 10 Standard minutes), no card; the docs say 100 | 7 days and 15 minutes (D-853 code defaults `self_serve_trial_days` / `_free_minutes`; production values UNKNOWN). Each test call stops at 3 minutes, 10 a day (FIRST-HAND C11) | **WEAKER today**: no trial test call can ring at all (FIRST-HAND C11-a, P0), there is no browser call, and the 3-minute cap cuts a real walkthrough |
| Minimum top-up | Presets from ₹500 (docs). In-app packs start at ₹1,499 | `MIN_TOPUP_INR = ₹100` (CODE `apps/api/billing/payment_routes.py:233`); catalogue packs from ₹2,000 | PARITY or better |
| GST shown | "Total with GST" shown live (₹9,999 becomes ₹11,798.82) | Statement and pricing page say we charge no GST and issue no tax invoice (CODE `gst.py`, `GST_STATUS_SENTENCE`) | **BETTER** on cash price. **WEAKER** for a GST-registered buyer, who gets a bill of supply (Rule 49) and no input tax credit |
| Credit validity | "Credits never expire" (FIRST-HAND #/billing) | Bought credit lapses 12 months after purchase; credit bought before 27 Oct 2026 and free grants never lapse (D-897/D-900, Terms rev 19; CODE `apps/web/src/lib/legal/refunds.ts`) | **WEAKER**: a visible gap on the one screen where an owner decides to pay |
| Refunds | Two contradictory policies: the marketing site refunds unused credit within 180 days of closure; the app (3 Nov) says purchased credit is non-refundable | One policy, hash-guarded: unused credit forfeited at closure; refunds for duplicates, credit not delivered, our errors, and a top-up taken by mistake within 30 days (unspent part) (CODE `refunds.ts` §§2-4; D-980 caps a refund at unspent, unlapsed credit) | **BETTER** on consistency and on the 30-day mistaken top-up. PARITY on closure |
| Running out | Graceful goodbye at zero; a live call is capped to what the balance affords | Low-balance alert panel, auto-recharge, spend cap (CODE `billing/auto_recharge*.py`, `caps.py`, `billing/LowBalanceAlertPanel.tsx`) | **BETTER**: Outpero shows no auto-recharge |

### 1.2 Outpero's worked example, priced on our card

Outpero's example (/pricing): 2,000 connected calls of 1.5 minutes each is 3,000 billed
minutes on one number. Both sides bill in 30 s blocks, so the billed minutes are the same.

| | Outpero ex GST | Outpero paid (+18%) | Calevate paid (no GST) |
|---|---|---|---|
| Everyday voice, 3,000 min | ₹15,000 | ₹17,700 | Clear ₹13,500 |
| Number | ₹649 | ₹765.82 | N (DECISION ₹499) |
| **Month** | **₹15,649** | **₹18,465.82** | **₹13,500 + N** (₹13,999 at ₹499) |
| Top voice, 3,000 min + number | ₹21,049 | ₹24,837.82 | Studio ₹18,000 + N (₹18,499 at ₹499) |
| 1,000 contacts on 3 lines | Number + 2 channels ₹1,947/month (₹2,297.46 paid) | 2 lines free; a 3rd by request, at no fee in code | |

With N at ₹499, the Clear month comes to ₹4,466.82 (24.2%) less cash than Outpero Standard.
**This is our strongest commercial fact, and no public page states it.** /pricing reads the
live rate card and quotes no competitor (CODE `apps/web/src/app/pricing/page.tsx`).

### 1.3 Pricing moves

**P-1 (presentation). An all-in "what you actually pay" line on /pricing and in the app.**
- Show cash per minute with tax included, on both sides of a worked month, built from the live
  rate card plus the attested number price. Name no competitor in the client app. Mention
  Outpero only on a compare page (G-3) that carries a dated source line.
- Add a clear sentence for the GST-registered buyer: we charge no GST, so there is no input
  credit to claim, and the comparison should be made against their pre-GST price.
- Acceptance:
  - /pricing renders "A month of 3,000 minutes on Clear: ₹X, nothing added", with X computed
    from `GET /v1/public/rate-card`;
  - a test fails if any ₹ figure on the page is a literal;
  - the GST-registered sentence is present.
- Effort: S (half a day).

**P-2 (RECOMMENDATION). Keep ₹4.50 and ₹6.00. Do not cut to match the ₹3.5 "custom" tier.**
- The Clear floor in memory 204797e4 is ₹3.0708: a ₹3.00/min Studio band (VENDOR-STATED,
  ThinnestAI email of 7 Oct 2026) plus the 2.36% top-up fee (D-754). That leaves 31.8% before
  fixed costs at ₹4.50.
- A matching ₹3.50 would leave 12.3% ((3.50 − 3.0708) / 3.50), below `card_refusals`' 20%
  warning line (`credit_packs.py:205`).
- The vendor rate's recheck date has passed (memory 66aaedec, recheck 22 Nov). Re-read it
  before any price change.
- If a volume rung is wanted, the founder's own D-728 condition (Studio towards ₹5 only once
  volume fills a Cartesia plan) is the honest trigger. Today nothing qualifies.

**P-3 (RECOMMENDATION, founder decision). Credit validity.**
- Outpero says "Credits never expire" on its billing screen, and ours lapse after 12 months.
- Options:
  - (a) keep 12 months and state it beside the pack, as we already do (`TopUp.creditLapse`);
  - (b) extend to 24 months for packs of ₹10,000 or more;
  - (c) no expiry.
- (b) and (c) are material Terms changes (D-897 made rev 19 material, so every client
  re-accepts).
- Recommendation: (a) now. Raise (b) with the founder only if a lost sale names expiry as the
  reason. The lapse rule protects the liability side of a prepaid balance. Its cost shows only
  on one screen, and the sentence there is already honest.
- Effort: (a) 0; (b) M (a Terms revision, `credit_expiry_months_for` by pack, tests).

**P-4 (product). Buy extra calls at once without waiting for us.**
- Today a client asks, an operator approves, and the cap is applied in the client's workspace
  (`call_lines.py` docstring).
- Outpero sells lines at ₹649 each and self-serve. We cannot yet sell them freely: our
  account-wide vendor ceiling is 20 concurrent calls (VENDOR-STATED 23 Oct, `config.py:653-662`;
  the code default is 5), and that pool is shared by every client.
- RECOMMENDATION:
  - keep 2 lines free;
  - offer instant self-serve raises to 3 or 4 lines at no fee while the shared pool has
    headroom (`outbound_line_pool`);
  - queue anything above that for an operator.
  Price lines only once the vendor states what more concurrency costs us. No such figure is
  verified, so none is proposed here.
- Acceptance:
  - the Phone number screen offers "Add a line (up to 4)";
  - the raise applies through `sync_engine_call_lines` and is read back;
  - a pool at 80% of `thinnest_max_concurrent_calls` refuses the self-serve raise with a
    plain sentence.
- Effort: M.

---

## 2. Billing UX

| Capability | Outpero | Calevate | Verdict |
|---|---|---|---|
| Spend by agent | "Spending by employee" 7/30/90 days, with share, calls, minutes and per call | `by_agent` on the spend and history routes (CODE `billing/spend_routes.py:221,478`, `history_routes.py:101`); `WhereItWent.tsx`, `SpendPanel.tsx` | PARITY |
| Cost explainer | "What calls cost": rates, 30 s worked examples, ₹0 unanswered, AI actions ~₹0.2 | `WhatCallsCost.tsx`, `VoiceTiers.tsx`; `billing_step_seconds` on the card (CODE `payment_routes.py:458-460`) | PARITY. Check that we give a 30 s worked example ("40 s = one minute"); theirs is very clear |
| Statements | Monthly statement CSV, running balance | `StatementsView.tsx`, `statementCsv.ts`, `TransactionsTab.tsx`, `WalletLedgerPanel.tsx`, receipts | PARITY |
| Cost per result | Not shown | `GET /v1/analytics/cost-per-result` and `CostPerResult.tsx` (D-944) | **BETTER**. Lead with it in sales |
| Credit lots and expiry | Not applicable (no expiry) | `LotsPanel.tsx` shows "Lapses <date>" per purchase | Honest, but a reminder of P-3 |
| Talk time per pack | Packs show minutes on Standard and Premium | Rate per voice per pack | Small gap. Show "≈ N Clear minutes" on each pack (S) |
| AI actions billed | 0.05 to 0.25 credits per teach or rehearse message (and contradictory: 0.05 or ₹0.20) | Dashboard AI under an AI quota (`billing/ai_quota.py`) | We charge nothing per message. **BETTER**, and say so |

**B-1.** Show minutes on each pack card: "₹5,000 ≈ 1,111 Clear minutes or 833 Studio minutes",
computed from the pack's frozen rates and rounded down. Acceptance: the figures come from
`/v1/billing/topups/packs`, and a test checks floor(amount / rate). Effort: S.

---

## 3. Numbers and KYC

| Step | Outpero | Calevate | Verdict |
|---|---|---|---|
| KYC | PAN, then Aadhaar via DigiLocker, on the first purchase only. "Numbers in 5 minutes" | Manual review or DigiLocker (Aadhaar or PAN) (D-692), plus business details sent to the numbering authority in the client's own name through its own workspace (D-693; memory c7170e1b). KYC is refused during a trial (`trial_kyc_unavailable`) and the workspace is created on first payment (D-697) | **BETTER** on liability isolation (a complaint touches only that client's numbers). **WEAKER** on time to a number: credit, then KYC, then business details, then purchase, in sequence |
| Choice | Mobile and landline tabs, search, 50 listed | `number_catalog.py`, `engine_number_purchase.py`, bring-your-own via forwarding (`phone-number/existing-number`) | PARITY. Bring-your-own is **BETTER**: Outpero has none |
| Lapse handling | Auto-renews from credit; on failure it emails, retries and then releases | `number_rental.py` renewals, `number_holds` | PARITY (not traced end to end here) |

**N-1. Let a trial account start KYC and business details before it pays.**
- Today `trial_kyc_unavailable` makes them strictly sequential (memory 9ffe7db0).
- Collect and review KYC during the trial. Keep the number purchase, which costs money and is
  in the client's name, behind the first payment. The workspace is still created at first
  payment, so the business-details submission waits for it.
- Acceptance:
  - a trial owner can submit PAN or DigiLocker;
  - the review state carries over;
  - on first payment the business-details job is queued automatically.
- Effort: M. This touches the trial gates in `compliance/trial_access.py` and the dial-gate
  invariants (`scripts/check_compliance_invariants`).

---

## 4. Concurrency, calling hours, retries, list hygiene

| Item | Outpero | Calevate | Verdict |
|---|---|---|---|
| Per-campaign concurrency | 1–20 | Slider up to `campaign_max_concurrency` (default 10, ceiling 20; `config.py:252,1907`), clamped to plan ceiling, pool and account lines (`campaigns/service.py:623-635`) | PARITY on the ceiling. The 28 Nov LOG C12-c defect: the screen shows a default of 3 as if the owner chose it |
| Calling hours | Fixed: Bulk 09–21, Instant 06–22 | Outbound 09:00–21:00 IST, half-open, for every dial (`compliance/service.py:27,208-211,342`) | PARITY on bulk. Our instant-lead calls get the narrower window. Theirs at 06–22 reaches later leads; ours is the conservative reading (SEC-COMP §2.5). Keep it |
| Retries | 1–9 retries (10 attempts); 30 min, then 2 h, then next day | `campaign_max_retry_attempts` default 5, ceiling 10; gaps from `RETRY_GAP_MENU` (`config.py:255,1909`) | PARITY |
| Calling days, holidays | Days, plus a holiday never-call list on campaigns | Recurring days on campaigns (`campaigns/scheduling.py`); holidays exist only on the lead-intake policy (`ingest/lead_policy.py:69`) and follow-ups. **No holiday list found on campaigns** (grep `holiday` under `apps/api/campaigns`: none) | **LACK** on campaigns |
| Skip recently called, any campaign | Yes, N days | Not found (grep `recently_called`, `recent_contact`, `called_within` in `apps/api`: none). Not proven absent; a differently named rule may exist | **LACK** (unconfirmed) |
| Calls to one person a day | 3 per 24 h, all sources (API docs) | Not found (grep `frequency_cap`, `calls_per_number`: none) | **LACK** (unconfirmed). Also a complaint-risk control |
| Per-campaign suppression | Yes (new) | Campaign-level DNC and suppressed list (`do-not-call/SuppressedList.tsx`; `suppression` appears in 31 files) | PARITY |
| Live campaigns per account | 10 | No cap found | Not a gap |

**H-1. Cross-campaign "already called in the last N days" and a per-person daily cap.**
- Do this in `check_dispatch`, so that every path inherits it (campaigns, instant leads,
  callbacks).
- Default ON at 3 calls per 24 h per person per account, and a campaign skip of 7 days.
  These are RECOMMENDED defaults, not regulatory figures.
- Acceptance:
  - a new rule name in the gate;
  - the campaign screen states "N people skipped: called in the last 7 days";
  - a test dials the same number from two campaigns and an instant lead and gets the refusal.
- Effort: M.

**H-2. Holiday never-call dates on campaigns.** Reuse the `ingest/lead_policy` holiday shape
rather than adding a second one. Acceptance: a holiday date produces no dial and the screen
says "Holiday: not calling". Effort: S.

---

## 5. DNC coverage

| | Outpero | Calevate | Verdict |
|---|---|---|---|
| Coverage | The app says every path refuses a number on the list. The Help centre still says DNC is "not yet applied to Instant"; the API says it is | One gate, `check_dispatch`, for every dial: trial test calls, campaigns, instant leads, callbacks (`compliance/service.py`) | **BETTER** (one predicate, no contradictions) |
| Global and national | None visible | Platform-wide global suppression and recorded national preference scrubs (`compliance/national_dnd_routes.py`); DNC pushed into the client's own engine workspace (`engine_dnc.py`) | **BETTER** |
| Opt-out in call | Auto-added | `compliance/optout.py`, `workers/optout.py` | PARITY |

Move: none in product. Marketing should say it plainly (G-2).

---

## 6. Caller memory and call-backs

| | Outpero | Calevate | Verdict |
|---|---|---|---|
| Memory | "Smart follow-ups", one switch that both remembers callers and books call-backs. A "Remembered callers" table per employee, cleared there | Per-agent `caller_memory_enabled` drives ThinnestAI `pastConversations` recap or fresh. It needs the owner's accepted statement (version 3, D-971; `MEMORY_ON_SQL`, D-900) and refuses sensitive-data accounts. Our own store was removed (D-973) | PARITY on ability. **WEAKER** on visibility: we have no "who is remembered" table, because the memory lives in the engine |
| Known defect | – | Recap on a placed call resumed the last call and asserted its outcome ("we installed the app"), memory 45ac22b9. A founder decision on (a), (b) or (c) is pending | Open |
| Call-back at a time asked | Auto-reschedule, off by default | `CALL_BACK_TIME_RULE` when `callbacks_offered` (D-969); `callbacks/` module | PARITY |
| Missed-caller call-back | On by default, once, inside hours, never DNC | `missed_call_callback` starter (`follow_ups/starters.py`), not on by default | PARITY on ability. Theirs is on by default |
| Leads calling back | Every outbound employee answers its own leads | Inbound lines are a separate object | Product-lane topic, not analysed here |

**M-1.** Decide the recap-on-placed-call question (founder; memory 45ac22b9). Until then, for
outbound agents with memory on, the Settings screen should say in one line what a returning
person hears. This is a FOUNDER decision: the "Notices: hands off" rule applies, and nothing
in call behaviour changes without him.

**M-2.** Add a "Missed callers: call back once" one-tap switch on the inbound line that
creates the existing starter. Feature audit F1 #7 already ranks it as S.

---

## 7. Notifications

| Channel | Outpero | Calevate | Verdict |
|---|---|---|---|
| Bell | Per-type Bell and Pop-up settings for 6 types; always-on for money, numbers, campaigns and problems | One bell feed from the attention queue plus announcements (`notifications/service.py`, D-869), toned per kind. **No per-type preferences** | **WEAKER** |
| Pop-ups | Per type, per device, "pause 1 hour / rest of today"; live "instant lead being called" pop-up | Four kinds only (`lead_hot`, `call_failed`, `credit_low`, `inbound_stopped`), browser Notification API, **tab open only**; no service worker or PWA (`apps/web/src/lib/desktopAlerts.ts:34`; `apps/web/public` has no manifest) | **WEAKER** |
| Daily email | Daily results email, optionally on quiet days too; morning brief in-app | Owner daily summary at 20:58 IST, email plus counts-only WhatsApp, off by default (`workers/owner_digest.py`, D-944) | PARITY. Ours is evening and off by default |
| Instant email per call | Within a minute, batched in busy spells, filtered by outcome and by the owner's own captured-field answers, quiet hours, max 12 a day, "send me a sample" | Hot-lead email and WhatsApp (`workers/notifications.py`) and team alerts by email or the client's WhatsApp (`workers/team_alerts.py`, D-904). **No quiet hours, no daily cap, no field-answer filter, no batching found** | **WEAKER** on control. **BETTER** on reach: team routing and WhatsApp to staff |
| Milestones | First lead, 100/500/1,000 calls | None found (grep `milestone` in client app: none) | **LACK** (small) |
| Reminders to call people | "Waited 1 h+" or "qualified yesterday and not called" | Attention queue `lead_hot` and `call_needs_you` | PARITY on data; no time-based nudge |

**A-1. Alert preferences per kind** (bell, pop-up, email, WhatsApp) with quiet hours (IST) and
a daily cap.
- Keep money, number, KYC, inbound-stopped and failed-call alerts always on, as Outpero does;
  that split is sound.
- Acceptance:
  - one `notification_preferences` row per person, tenant-scoped with FORCEd RLS and a
    cross-tenant zero-rows test (hard rule 1);
  - quiet hours delay rather than drop: a held email goes out at the window's end;
  - the cap folds overflow into one "and N more" email;
  - tests cover a hot lead at 23:00 IST arriving at 08:00, and the 13th email of a day being
    folded.
- Effort: M–L.

**A-2. PWA and Web Push for the always-on kinds**, so an owner hears about a hot lead with the
tab closed (feature audit F1 #2, M–L). This is the retention lever for SMB owners, who live on
their phones.

**A-3. Owner-chosen triggers.** "Email me when <captured field> is <answer>", reading the
agent's extraction schema. Our typed fields make this exact where theirs is free text.
Effort: M.

**A-4.** Milestones (first lead, first booked result, 100 calls) as bell items. Effort: S.

**A-5.** Offer a morning time for the daily summary (08:00 IST) beside 20:58. Effort: S. The
cron claim is per day (CAS), so one send per day is unchanged.

---

## 8. Data export, privacy controls, consent records, retention

| | Outpero | Calevate | Verdict |
|---|---|---|---|
| Export | "Export all calls (CSV)" with transcripts; leads CSV | Calls CSV with full numbers, owner-only, audit-logged, typed code required (`crm/routes.py:255-295`, D-730); per-person subject export (`compliance/export_routes.py`) | **BETTER** on control. Check the friction: a typed code on every export may annoy owners, but it is deliberate |
| Deletion | By email to support | Self-serve erasure desk with a deadline queue (`data-rights/`, `rights_desk.py`, `deletion_proof.py`), and erasure pushed into the engine workspace | **BETTER** |
| Agreed terms record | "What you've agreed to", one version | `legal_acceptances` per document and revision; agreements screen; the pledge (`outbound_pledge.py`) | **BETTER** |
| Consent per contact | One checkbox per campaign | `consent_ledger` (append-only, hard rule 4), list source and consent date, spoken consent (`spoken_consent.py`), WhatsApp opt-in | **BETTER** |
| Retention | Recordings and transcripts kept with no limit while the account is active (in-app: recordings "deleted after a while") | Recording 90 days, transcript 365 days (anonymised), lead 1,095 days, consent log 2,555 days (`compliance/retention_defaults.py:15-64`) | **BETTER** for DPDP's storage-limitation principle. **WEAKER** if an owner wants old recordings: say so at the point they look for one |
| Sub-processors | Categories only, plus Supabase, Razorpay, PostHog | `/legal/subprocessors` | **BETTER** |
| Status page | None (status.outpero.com does not resolve) | `/status` (`apps/web/src/app/status/page.tsx`) | **BETTER** |

Move: none in product. These are sales assets (G-2).

---

## 9. Compliance posture: read this before writing marketing

The brief for this analysis said "AI disclosure mandatory for us vs optional for them". **That
is not what the code does.** The difference is real but narrower:

- **Mandatory for us:** truthful answers when a caller ASKS whether it is an AI or whether the
  call is recorded. This is composed into every prompt by `compose_engine_prompt` and verified
  on publish and on drift (hard rule 5). The dial gate also refuses an agent with no AI
  sentence on file.
- **Switchable for us:** what the agent VOLUNTEERS at the start of the call. Since D-1021 these
  are account switches, `organizations.notice_ai_enabled` and `notice_recording_enabled`, and
  both have `server_default=false()` (CODE `apps/api/tenancy/models.py:342-345`). When a switch
  is on, the notice is woven into the opening line (D-971).
- **Outpero:**
  - an "AI disclosure (recommended)" switch per employee;
  - a recording notice switch;
  - every inbound caller "first hears that the call is recorded" (VENDOR-PUBLISHED #inbound);
  - "Power prompting" keeps "says it's an AI when asked" (FIRST-HAND).
  Their truthful answer is a promise in the prompt. Ours is a server-enforced and
  publish-verified invariant.
- **Indian law:** memory eac6fcd2 records that research on 5 Nov 2026 found no Indian rule
  prescribing wording for AI or recording disclosure. That is REPORTED, not re-read here.

Claims we can make truthfully:
- "Every agent answers honestly, every time, when asked if it is an AI or if the call is
  recorded. We check this on every publish."
- DNC on every dial path.
- A consent record per list.
- Retention limits.
- One consistent refund policy.
- A public status page.
- Named sub-processors.

Claims we must not make: "every call announces it is AI". The default is off.

Whether the volunteered notices should default on is a FOUNDER decision. The "Notices: hands
off, UX first" memory applies, and this analysis does not recommend changing it.

Friction cost of our posture (FIRST-HAND C11-c, C12):
- six ticks before the first test call;
- seven gates before the first real call.
The law-driven ones stay. The move is ordering, not removal:
- take the four document acceptances as one "I accept" with expandable links;
- ask the pledge and the own-number tick at the first test call;
- ask list source and consent date at campaign launch.
- Acceptance: each `legal_acceptances` row is still recorded per document and revision.
- Effort: S–M (agreements UI only; the gates are unchanged).

---

## 10. Positioning, marketing, partners, proof

| | Outpero | Calevate | Verdict |
|---|---|---|---|
| Public pages | About 1,500 URLs built 4–22 Oct: 118 blog posts, 444 Q&A pages, 103 glossary terms, 58 compare, 14 alternatives, 171 city pages, 235 industry and industry×city pages | 11 public routes plus 8 legal documents (`apps/web/src/lib/site.ts:99-167`, `app/sitemap.ts`) | **WEAKER** on reach |
| Compare pages | 35 vendors, with competitor prices quoted (some dated "checked 30 July 2026") | None. /why-calevate argues against a salary, not a vendor | **LACK** |
| Partner or reseller programme | /partners/apply form and a partner portal link; **no terms published** | None (grep `white_label`, `referral`: none; `reseller` hits are number-supply code) | **LACK** |
| Done-for-you services | ₹14,999 to ₹1,00,000 agency packages | None (D-707 retired the managed tier) | Different motion. Not a gap to copy |
| Customer proof | "5,000+ businesses", no names, logos or metrics; agency stats show placeholder zeros | None by policy (`apps/web/src/app/page.tsx:50`: "No customer counts, logos, testimonials or case studies") | Even. **Our policy is the better ground: their 5,000+ is unsupported** |
| Languages marketed | 7 live; 18 language pages, including 4+ they say are not live | Offered set in `agents/languages.py` (3 per the 9 Oct gap report; staged Tamil and others) | WEAKER on breadth; out of scope here |
| Contradictions in their estate | Signup credits 50 vs 100; Premium ₹6.8 vs ₹7; sandbox 0.05 credits vs ₹0.20; test calls free vs charged; two refund policies; DNC on Instant yes vs no; 18 language pages vs 7 live; in-app bonus packs vs docs "no bonus packs" | Our figures are derived from one rate card; /pricing has no literal ₹ (`pricing/page.tsx:52`) | **BETTER** |

**G-1. A small, true content estate.** Not 1,500 programmatic pages.
- Whether Google's spam policies treat mass-generated city × industry pages as "scaled content
  abuse" was NOT re-read for this analysis. Check
  developers.google.com/search/docs/essentials/spam-policies before deciding on any page count.
- RECOMMENDATION:
  - about 20 hand-written pages where we hold facts: Telugu (our lead language), the 8 business
    kinds on /signup, and the 5 jobs (receptionist, missed-call call-back, lead call, campaign,
    reminder);
  - each with a real worked month from the live rate card;
  - each with a plain-language compliance section (TRAI hours, DNC, consent) linked to
    `/legal`.
- Acceptance:
  - each page is in `PUBLIC_ROUTES`, has no literal ₹ (the existing test pattern), and has a
    Telugu section reviewed by the founder;
  - the sitemap derives them.
- Effort: M (copy is the work; the founder writes the Telugu).

**G-2. A "the rules on every dial" page as the trust wedge.**
- Put each claim from §9's "can make" list beside the mechanism.
- Outpero's own Terms put AI and recording disclosure and TRAI duties on the customer (Terms
  §05/§07, AUP); ours enforce them in the product. Say that without naming them.
- Acceptance: every claim links to a public doc section; there are no superlatives.
- Effort: S.

**G-3. Compare pages, few and dated.**
- One page per real alternative a Telugu SMB weighs: a human telecaller, an IVR, a generic
  telecalling SaaS.
- At most one page names Outpero, only if the founder agrees. It must quote their figures with
  URL and date and show our live figures. It must not copy their wording or structure; the
  founder rule is "never copy Outpero".
- Acceptance:
  - a "checked on <date>" line;
  - a re-check reminder at 30 days, matching the rememory `recheck_after` convention.
- Effort: S per page.

**G-4. A partner programme with published terms.** Outpero has a form and no terms; publishing
terms is the better move.
- RECOMMENDATION:
  - a referral credit to the agency per referred paying client, paid as calling credit, not
    cash, which keeps it inside the wallet ledger;
  - the agency can be invited as a team member on the client's account rather than through
    sub-accounts.
- The amount is a founder decision. No figure is proposed, because none can be derived from a
  verified cost.
- Acceptance:
  - a public /partners page with the terms;
  - an attribution field at signup;
  - a ledger grant on the referred client's first payment, idempotent on that payment id.
- Effort: M. White-label or sub-accounts would be L and is not recommended yet.

**G-5. Proof without inventing it.**
- Switch on `public_quality_page_enabled` (`config.py:633`, currently False) once there are 10
  or more real calls a week. D-944 withholds p90 below 10 calls, which is the right floor.
- It would publish measured weekly reply speed per language and the answered share.
- Ask the first paying client for a named case study with written consent.
- Acceptance: the page shows only computed figures, and the 10-call floor holds.
- Effort: S, once the data exists. That depends on paying clients; it is not engineering.

---

## 11. Top 15 gaps, ranked by revenue and retention impact

| # | Gap | Area | Verdict | Move | Effort |
|---|---|---|---|---|---|
| 1 | No trial test call can ring (no shared test number) and there is no browser call | Trial | WEAKER (P0) | Set `trial_caller_number` in the ops console (an operator action) and add an in-browser test call; widen the 3-min cap for walkthrough agents | S (ops) + M (browser) |
| 2 | Our 24% cash-price advantage is stated nowhere | Pricing | Unused BETTER | P-1 all-in month on /pricing, plus the GST-registered buyer line | S |
| 3 | Instant alerts have no quiet hours, cap, per-kind preferences or field-answer triggers | Notifications | WEAKER | A-1 + A-3 | M–L |
| 4 | Alerts only while the tab is open (no PWA or push) | Notifications | WEAKER | A-2 | M–L |
| 5 | Six ticks before the first test call; seven gates before the first real call | Compliance UX | Friction | §9 re-ordering; the gates are unchanged | S–M |
| 6 | KYC cannot start until after payment | Numbers | WEAKER on time | N-1 | M |
| 7 | No cross-campaign "recently called" skip and no per-person daily cap (unconfirmed) | Hygiene | LACK | H-1 in `check_dispatch` | M |
| 8 | Extra calls at once only by operator request | Concurrency | WEAKER self-serve | P-4 instant raise to 3–4 within pool headroom | M |
| 9 | No compare or alternatives pages; 11 public routes against about 1,500 | GTM | LACK | G-1 + G-3 | M |
| 10 | No partner or reseller programme | GTM | LACK | G-4 with published terms | M |
| 11 | Credit lapses after 12 months against "never expire" | Pricing | WEAKER | P-3 (founder decision) | 0 / M |
| 12 | Recap-on-placed-call defect; no "remembered callers" view | Caller memory | Open defect / WEAKER | M-1 founder decision; then a read-only list from the engine if the vendor exposes one (UNKNOWN) | S after decision |
| 13 | No holiday list on campaigns | Hours | LACK | H-2 | S |
| 14 | Missed-caller call-back not on by default and not one tap | Inbound retention | PARITY, buried | M-2 | S |
| 15 | No public proof | Proof | Even | G-5 once data exists; first case study with consent | S (blocked on clients) |

Where we are already ahead and should say so, not build:
- per-minute price;
- 2 free calls at once;
- no GST;
- DNC on every path, plus global and national scrubs;
- the consent ledger;
- self-serve erasure;
- retention limits;
- one consistent refund policy, with a 30-day mistaken top-up refund;
- cost per result;
- auto-recharge;
- a status page;
- named sub-processors;
- bring-your-own number.
