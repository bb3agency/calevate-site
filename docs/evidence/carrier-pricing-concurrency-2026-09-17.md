<!-- EVIDENCE CLASS, AND IT IS THE STRONGEST CARRIER EVIDENCE THIS REPOSITORY HOLDS.

     Landed VERBATIM, 17 Sep 2026. A research agent with BROWSER CONTROL signed up, logged
     in, and called provider APIs with live credentials; the founder relayed the result. That
     makes the Vobiz figures AUTHENTICATED-VENDOR-CONSOLE — read out of the account itself,
     not off a marketing page — which is a class nothing else in `docs/evidence/` has.

     Read the "Access actually achieved" section before trusting any row: the three
     providers were reached to three different depths, and the report says so per cell.
       * Vobiz  — authenticated console AND Account API. Highest confidence.
       * Exotel — logged in, but plan/rate data is KYC-gated and returned nothing. The
                  numbers in its column are BLOG MIDPOINTS the report labels as estimates
                  and tells you not to quote. Do not quote them.
       * Plivo  — signup BLOCKED (work-email rule rejected both a Gmail address and
                  calevate.tech), so every Plivo figure is from public pages, not an
                  account.

     NOT EDITED, and that is deliberate: the reconciliation against this repository's own
     model, the corrections it forces, and what it does NOT settle are in
     `carrier-plivo-vs-exotel-2026-09-16.md`'s addendum, so this file stays what it is —
     the reading, not our reading of the reading. -->

# Vobiz vs Plivo vs Exotel — Decision-Grade Pricing & Concurrency

All figures ex-GST (18% GST applies on top everywhere unless stated). "NOT FOUND" = genuinely not published/exposed anywhere reachable, with the last path tried noted.

## Access actually achieved

- **Vobiz** — full authenticated console + Account API access (KYC-verified trial account, auth_id `MA_KXXH10VG`). This is the only provider where console/API figures were directly confirmed, not inferred.
- **Exotel** — logged into `my.exotel.com` and called the Account API directly with the account's live key/token; account is `Trial`, `KycStatus: notstarted`. No plan, rate, or billing data is exposed pre-KYC through either the console or the API — genuinely sales/KYC-gated, confirmed two independent ways.
- **Plivo** — signup blocked for this account on both a Gmail address ("Please use a work email address") and the calevate.tech domain ("This email domain isn't allowed at this time"), on both the classic and new signup flows — matches what you saw directly. No console or API access was possible; all Plivo figures below come from Plivo's own public pricing and documentation pages (India selected), not an authenticated account.

## A finding that changes the shape of this whole comparison

Your model is: **client already owns a DLT-registered Indian number from any carrier, and hands it to us to link onto our SIP trunk** — not a number any of these three sell you. I checked whether that is actually possible on each platform, since it wasn't in your original question list but turned out to be load-bearing:

- **Vobiz explicitly blocks it.** Its own docs state: *"You cannot port a number from another provider (including Plivo) into Vobiz. There is no number transfer/porting flow... buy a new Vobiz number"* ([Buy a Phone Number guide](https://www.vobiz.ai/docs/buy-a-phone-number)). The trunk "Assign Number" endpoint only accepts numbers "already in your account inventory," i.e. bought from Vobiz ([Assign Number docs](https://www.vobiz.ai/docs/trunks/assign-number)). There is no SIP-forwarding or IP-trunk path for an externally-issued number in any Vobiz doc found.
- **Plivo claims support**, but only vaguely: *"Use your existing numbers on Plivo using SIP forwarding or via your own RespOrg"* ([Phone Numbers page](https://www.plivo.com/phone-numbers/)). RespOrg is a US/FCC porting concept with no direct Indian equivalent (India uses TRAI/MNP), and no India-specific process, fee, or mechanism for this is published anywhere. Native number porting on Plivo is stated as US/Canada only ([Number Porting docs](https://www.plivo.com/docs/numbers/number-porting)).
- **Exotel is silent.** Its SIP trunking guides describe mapping an Exotel-issued DID/Exophone to a trunk ([Map Phone Number to Trunk](https://developer.exotel.com/api/map-phone-number-to-trunk), [Flow & API Configuration Guide](https://support.exotel.com/support/solutions/articles/3000133452-flow-and-api-configuration-guide-for-voice-ai-contact-centre-platforms-via-exotel-virtual-sip-trunk)) but never states whether a client-owned number from another Indian carrier can be attached instead.

**Practically: none of the three has a documented, self-serve way to run your actual model (client's own pre-existing DLT number, hosted on your trunk).** All pricing below is computed on the assumption each client's number is instead purchased/issued through whichever provider you pick — the only configuration any of them actually document. This is the single biggest open question in this whole report, bigger than any per-minute rate, and I'd confirm it with each provider's sales team before committing.

---

## Part 1 — Concurrency

| # | Question | Vobiz | Plivo | Exotel |
|---|---|---|---|---|
| 1a | Default included concurrency | 3 concurrent + 1 CPS, per account ([Vobiz Account API](https://api.vobiz.ai/api/v1/accounts/MA_KXXH10VG), authenticated) | 50 concurrent + 2 CPS (India, Pay-As-You-Go) ([India concurrency docs](https://www.plivo.com/docs/voice/concepts/india-concurrency)) | Starter tier = 10 (third-party comparison figure — Exotel's own console/API expose no plan data pre-KYC) |
| 1b | Max ceiling | No hard ceiling found; scaled linearly to qty 100 in console pricing preview | 50 self-serve (India); beyond that, support ticket, then Enterprise (custom, ≥₹1,00,000/mo) | "Theoretically infinite" per marketing, but Exotel says to notify them above 20 concurrent — effectively sales-gated past that |
| 1c | HOW it's priced | Per-concurrent-call, paid in fixed packs (not bundled, not free) | Bundled free up to 50 (India PAYG); above that, free-on-request via ticket, or forced onto Enterprise | Plan-tier bundled (Starter/Growth/Enterprise), not per-unit |
| 1d | Exact price + minimum purchasable increment | ₹499 per concurrency unit, sold ONLY in blocks of 10 (min buy = 10 units = ₹4,990/mo); CPS ₹1,299/unit in blocks of 3 (min ₹3,897/mo) — confirmed via `/channel-pricing-preview` API and console stepper | NOT FOUND — no per-unit price anywhere; increases beyond 50 are "raise a support ticket," no stated fee | NOT FOUND — plan tiers only, no per-unit add-on price published |
| 1e | Per-account or per-number | **Per ACCOUNT** — confirmed: the same `concurrent_calls_limit` field appears on both the Voice API and SIP Trunk account overview, shared across every number/trunk on the account | Per ACCOUNT — "ONE account-level pool, combined inbound+outbound, spans both Voice API and SIP trunking" ([Account Limits docs](https://www.plivo.com/docs/voice/concepts/account-limits)) | Not explicitly stated per-account vs per-number in any reachable doc; industry-standard CPaaS behavior is per-account, but NOT CONFIRMED for Exotel specifically |
| 1f | Inbound/outbound separate pools? | No — single combined counter, not split by direction | No — combined inbound+outbound in one pool | NOT FOUND |
| 1g | CPS vs concurrency separately priced? | **Yes** — CPS (₹1,299/3-pack) and concurrency (₹499/10-pack) are two independent, separately-purchased limits | Yes as a *limit* (CPS = concurrency ÷ 25 formula), but **not separately priced** — no CPS price found | NOT FOUND (no pricing for either) |
| 1h | At the limit: queued or rejected? | NOT independently load-tested; no console documentation of behavior found | **Concurrency limit: rejected immediately** (error 5030 Voice API / 5190 Zentrunk), not queued. **CPS limit: inconsistent across Plivo's own docs** — Outbound Call API says queued/dequeued at a configured rate; the SIP-trunk (Zentrunk) path is described elsewhere as rejected ("pace your dialer"); inbound CPS breach = rejected, dropped. This is a genuine unresolved contradiction in Plivo's own documentation, flagged rather than guessed at. | NOT FOUND for Voice/streaming API; general docs mention default outbound CPS≈60/min (~1 CPS) but not the reject/queue behavior at breach |
| 1i | How long a raise takes | Self-serve, instant provisioning via console/API (purchase → immediate quota per the pricing-preview API); actual post-payment activation delay not independently timed | Via support ticket — **no stated turnaround time anywhere** | Via sales/onboarding conversation — no stated turnaround time |
| 1j | SIP trunk concurrency = channels priced per channel? | Effectively yes — the same account-wide `concurrent_calls_limit` applies uniformly to SIP-trunk-connected calls and Voice API calls; no separate "per channel" pricing exists | Not stated — no channel-based pricing/mapping found anywhere on the SIP trunking technical specs page | NOT FOUND |

**⚠️ Flagged contradictions found in the providers' own material (not resolved, reported as-is):**
- Plivo's dedicated marketing page for SIP trunking claims "unlimited concurrent calls," directly contradicting Plivo's own India-specific concurrency docs (50-default, hard reject at limit). The India-specific technical docs are treated as authoritative here.
- Plivo's CPS-breach behavior (queued vs rejected) differs by product path within Plivo's own documentation, as noted in 1h.

### Verdict: most concurrent calls for the least money

| Concurrency needed | Vobiz | Plivo | Exotel | Cheapest |
|---|---|---|---|---|
| **5 concurrent** | Must buy the minimum 10-pack even though only 2 more are needed: **₹4,990/mo** | **₹0/mo** — inside the free 50-slot India default | Inside Starter default (10); plan price NOT FOUND | **Plivo** (free), if the account existed |
| **30 concurrent** | Must buy 3×10-packs (30 units, capacity 33): **₹14,970/mo** | **₹0/mo** — still inside the free 50-slot default | Exactly at Growth-tier default (30); plan price NOT FOUND | **Plivo** (free) |
| **100 concurrent** | Buy 10×10-packs (100 units, capacity 103): **₹49,900/mo**, self-serve, instantly quotable | Exceeds the 50 self-serve cap — requires a support ticket and likely the ≥₹1,00,000/mo Enterprise plan; **exact figure NOT FOUND** | Enterprise custom tier; **NOT FOUND**, sales-only | **Vobiz** is the only one with an actual self-serve, published number at this tier — Plivo/Exotel may end up cheaper after a sales call, but neither publishes a number to compare against |

Bottom line: **Plivo is structurally the cheapest for concurrency up to 50** (it's free, where Vobiz forces you into a paid 10-pack for even 4-5 slots) — but Plivo's account is currently unreachable for you. **Above 50 concurrent, Vobiz is the only provider that gives you an actual price without a sales call.**

---

## Part 2 — Cost table (every cell: a number, or NOT FOUND + source of the gap)

| Item | Vobiz | Plivo | Exotel |
|---|---|---|---|
| Outbound to mobile (₹/min) | **0.38** (SIP-trunk connected call) — [Vobiz Account API, authenticated](https://api.vobiz.ai/api/v1/accounts/MA_KXXH10VG) | **0.38** (India domestic) — [Voice Pricing India](https://www.plivo.com/voice/pricing/in/) | **NOT FOUND** in rate-card form (KYC/API-gated); Exotel's own blog states a market range of ₹0.80–1.00/min — [Exotel: Migrating from Twilio](https://exotel.com/blog/migrate-twilio-to-exotel-voice-ai-india/) (marketing blog, not a rate card) |
| Outbound to landline (₹/min) | Not separately priced from mobile in the rate card found | Not separately priced from mobile on the India page | NOT FOUND |
| Inbound (₹/min) | **0.38** (same connected-call rate; no directional split found) — same source | **0.38** — same source | NOT FOUND; blog range ₹0.30–0.50/min (same caveat as above) |
| Billing increment | **60 seconds**, full minute rounded up — `pricing_tier.billing_increment_seconds=60`, [Vobiz Account API](https://api.vobiz.ai/api/v1/accounts/MA_KXXH10VG) | **Contradiction found**: "Pulse is 30 seconds" on the [India voice pricing page](https://www.plivo.com/voice/pricing/in/) vs. explicit 60/60 (India Zentrunk) on the [Billing Concepts docs](https://www.plivo.com/docs/faq/billing-and-invoices/billing-concepts) — unreconciled, flagged, not guessed | NOT FOUND — no billing-increment figure published anywhere reachable |
| Billing trigger (ring vs answer) | Billed on talk time (billsec) per CDR; a flat ₹0.02 fee applies to non-connected calls — i.e., effectively billed from **answer** | Explicit: **"When the call is answered, not when it starts ringing"** for both Voice API and Zentrunk — [Billing Concepts docs](https://www.plivo.com/docs/faq/billing-and-invoices/billing-concepts) | NOT FOUND — no explicit statement found in any reachable doc |
| Bidirectional WebSocket streaming charge | **₹0.06/min, separate add-on line**, stacks on top of the 0.38 connected-call rate → **0.44/min combined** — [Vobiz Account API](https://api.vobiz.ai/api/v1/accounts/MA_KXXH10VG) | **₹0.00/min — included free**, per Plivo's own India and US pricing pages ([SIP Trunking Pricing India](https://www.plivo.com/sip-trunking/pricing/in/)). A third-party blog claims $0.004/min separately — lower-confidence, contradicted by Plivo's own page, not used | NOT FOUND — Exotel's AgentStream/Voicebot docs state latency figures (<50ms) but no price anywhere ([docs.exotel.com AgentStream](https://docs.exotel.com/exotel-agentstream/streamkit-cloud)) |
| SIP trunk charge | Included in the 0.38/0.44 per-minute rate; no separate trunk fee found | Included in the 0.38/min rate; no separate trunk fee found | NOT FOUND as an Exotel rate-card figure. A general market range (₹0.42–1.68/min) appears in an Exotel blog discussing self-hosted alternatives — not attributed as Exotel's own price ([Self-hosted vs managed TCO](https://exotel.com/blog/self-hosted-vs-managed-tco-ai-voice-telephony/)) |
| Monthly DID rental | **₹500–600/mo** local (varies by circle) + ₹100 one-time setup; ₹1,000/mo for 92-series; 140/160-series "on request" only — [Vobiz console buy-number flow](https://console.vobiz.ai/) | **₹200/mo**, no setup fee stated — [Phone Numbers page](https://www.plivo.com/phone-numbers/) | NOT FOUND as an official figure. Third-party/own-blog mentions: Exophone rental ~₹499/mo (from prior Exotel console session); a separate blog cites a general "₹84–252/mo" local-DID range not attributed to Exotel specifically |
| Brought-in (BYON) number hosting charge | **Not applicable — explicitly blocked**, see cross-cutting finding above | NOT FOUND — claimed possible via "SIP forwarding/RespOrg" but no India process, mechanism, or fee published | NOT FOUND — no statement either way |
| Minimum commitment / platform fee / prepaid minimum | **None found** for the base tier; trial wallet ₹25, no stated monthly minimum. Only the concurrency/CPS packs (₹4,990 / ₹3,897 minimums) are forced purchases if you need more than the free base | **None** for Pay-As-You-Go (₹1,000 free credit, pure usage-based) up to a ₹2,00,000/mo usage cap, beyond which Enterprise (≥₹1,00,000/mo) is required | NOT FOUND for the Voice/Streaming API. (Exotel's unrelated "Business Phone System" product has published plan fees of ₹9,999/₹19,999/₹49,499/mo, but that is a different product line, not the Voice API/SIP-trunk product relevant here — not used) |
| Setup/KYC fees | Account already KYC-verified (trial); ₹100 per-DID setup fee is the only setup charge found | NOT FOUND — signup itself is blocked before any KYC/setup page is reachable | NOT FOUND — KYC required before any fee page is exposed; `KycStatus: notstarted` confirmed via direct API call |
| Multi-client hosting on one account — extra cost | Each client = one more Vobiz-issued DID (₹500–600/mo) sharing the account's single concurrency/CPS pool; no per-client platform fee found | Each client = one more Plivo-issued DID (₹200/mo) sharing the account's single concurrency pool; no per-client platform fee found | NOT FOUND |

---

## Part 3 — Worked total, ONE client, ex-GST

Assumptions stated explicitly: streaming active on every call; 2 simultaneous calls (within each provider's free/base concurrency, so no concurrency add-on needed at this scale); one number rented from the provider itself (since a true brought-in number could not be confirmed as possible on any of the three — see cross-cutting finding).

| Minutes/month | Vobiz (₹0.44/min combined + ₹550/mo DID*) | Plivo (₹0.38/min + ₹200/mo DID) | Exotel (ESTIMATE ONLY — see caveat) |
|---|---|---|---|
| 500 | 500×0.44 + 550 = **₹770/mo** | 500×0.38 + 200 = **₹390/mo** | ~₹824/mo — **estimate**, blended 0.65/min midpoint of Exotel's own blog range + ₹499 Exophone; excludes unknown streaming & platform fees |
| 2,000 | 2,000×0.44 + 550 = **₹1,430/mo** | 2,000×0.38 + 200 = **₹960/mo** | ~₹1,799/mo — same caveats |
| 10,000 | 10,000×0.44 + 550 = **₹4,950/mo** | 10,000×0.38 + 200 = **₹4,000/mo** | ~₹6,999/mo — same caveats |

*Vobiz DID taken at the ₹550 midpoint of the ₹500–600 range found; ₹100 one-time setup not amortized into the monthly figure.

**Exotel's column is explicitly NOT a quote** — it blends the midpoints of a self-published blog range (not a rate card), and it is missing streaming pricing and any platform/plan fee entirely (both NOT FOUND). Treat it as directional only.

## Part 4 — Worked total, TEN clients on ONE account, 2,000 min each (20,000 min total), 20 concurrent, ex-GST

| Component | Vobiz | Plivo | Exotel |
|---|---|---|---|
| Usage (20,000 min × combined rate) | 20,000×0.44 = **₹8,800** | 20,000×0.38 = **₹7,600** | 20,000×0.65 (estimate) = **~₹13,000** |
| 10 DIDs | 10×550 = **₹5,500** | 10×200 = **₹2,000** | 10×499 (estimate) = **~₹4,990** |
| Concurrency add-on for 20 total | Included base = 3; need 3 packs of 10 (30 units) to clear 20 → **₹14,970/mo** | 20 ≤ free 50-slot default → **₹0** | 20 ≤ "notify above 20" threshold, but no plan price → **NOT FOUND** |
| CPS add-on (assumption: min viable pack) | 1 pack of 3 CPS as a conservative minimum → **₹3,897/mo** (this quantity is an assumption — actual need depends on your dialing pace, not specified) | Included in the free CPS-scales-with-concurrency formula → **₹0** | NOT FOUND |
| **Total/month** | **₹28,177 + one-time ₹1,000 DID setup (10×₹100)** | **₹9,600** | **~₹17,990 (estimate) + unknown streaming fee + unknown plan fee** |
| For reference: revenue at ₹5/min × 20,000 min | ₹100,000/mo | ₹100,000/mo | ₹100,000/mo |
| Implied gross margin | ~72% | ~90% | Unknown — cost floor likely understated (missing streaming + plan fee) |

---

## Part 5 — One-line verdicts

- **Vobiz: MARGINAL.** Cleanest, most transparently priced platform of the three (confirmed via live console/API), with healthy margins at ₹5/min — but it categorically cannot host a client's own pre-existing number, which conflicts directly with your stated operating model. **The single unknown that would flip this to "viable": whether you're willing/able to have every client obtain a fresh Vobiz-issued number (and re-do DLT registration against Vobiz) instead of bringing their existing one.**
- **Plivo: MARGINAL, unreachable today.** On paper the cheapest per-minute rate with free streaming and free concurrency up to 50 — the best economics of the three if the billing increment really is 60s and not the conflicting 30s figure. But your account is currently blocked from signing up (needs a verified corporate domain email), and BYON for India is an unconfirmed marketing claim, not a documented process. **The single unknown that would flip this to "viable": getting a Plivo account created at all (a business email domain or a direct sales conversation), and resolving the 30s-vs-60s billing-increment contradiction.**
- **Exotel: NOT VIABLE to price today.** Every number that matters — per-minute rate, streaming price, DID rental, concurrency pricing, billing increment/trigger — is genuinely locked behind KYC and a sales conversation; confirmed via both the console and a direct authenticated API call returning no plan data. Only a self-published blog range (not a rate card) exists. **The single unknown that would flip this to assessable: completing real KYC (needs actual business documents) or getting a sales quote — there is no self-serve path to a number.**

## Part 6 — Could not reach

- Exotel: outbound/inbound official rate card, SIP trunk per-minute charge, DID monthly rental, WebSocket/streaming price, billing increment, billing trigger, concurrency/CPS pricing, minimum commitment, setup/KYC fees, BYON feasibility — all blocked behind KYC (`KycStatus: notstarted`, confirmed via [direct API call](https://api.exotel.com/v1/Accounts/calevate1.json)) and/or a sales conversation. Only "Talk to our Telephony Expert" chat remains untried, not attempted (low expected yield given the API/console both refuse to expose plan data pre-KYC).
- Plivo: any authenticated console/API figure at all (signup blocked on two email domains, which matches your own experience); per-unit concurrency price above the free 50; resolution of the 30s-vs-60s billing-increment contradiction; India-specific BYON mechanism, process, and fee.
- Vobiz: behavior at the concurrency/CPS limit (queued vs rejected) — not independently load-tested, no documentation found describing it; true BYON of any kind — explicitly not supported, not merely "not found."

---

### Files behind this report
- `research/vobiz_findings.json` — raw authenticated Vobiz console/API data
- `research/plivo_findings.json` — raw Plivo public-page findings with source URLs
