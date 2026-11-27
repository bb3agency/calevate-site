# Calevate master plan after the Outpero teardown (28 Nov 2026)

Written 28 Nov 2026 (IST) on `rel-0.5.98` (worktree `rel596`, HEAD `01c56b73b`). Read-only on
code: this file is the only thing written. It turns the five teardown analyses, the
side-by-side build log and the redesign plan into one dependency-ordered build.

**Founder rule (rememory 729dfe15, 28 Nov 2026):** Outpero is evidence of what owners expect,
never a template. Claude decides, proceeds and lists its choices; nothing below asks the
founder a question except where a standing decision says that subject is his (notices,
D-692, money he has not set, support staffing). Every design is Calevate's own, built on our
data model (D-997: the agent is staff, a campaign or an Inbound line is the job and holds the
script), our hard rules and our owner words (redesign PLAN §6).

**Tempo (CLAUDE.md):** there is no later. Waves below are dependency order, not a calendar.
The only things that wait are named external blockers.

## How to read the IDs

Every analysis item keeps its own ID, prefixed with its source so identical labels in
different files cannot collide:

| Prefix | Source file | Its own IDs |
| --- | --- | --- |
| `UX·` | `analysis/01-screens-ux.md` | rows G-1..Q-4 (154 rows), proposals P-01..P-29, top-20 ranks |
| `API·` | `analysis/02-api-integrations.md` | matrix A1..E5 (36 rows), designs G1..G12, ranks 1..15 |
| `AIQ·` | `analysis/03-ai-quality.md` | scorecard rows 1..30, improvements G1..G15, ranks 1..15 |
| `BIZ·` | `analysis/04-business-ops.md` | P-1..P-4, B-1, N-1, H-1, H-2, M-1, M-2, A-1..A-5, §9 ordering, G-1..G-5, ranks 1..15 |
| `MKT·` | `analysis/05-market-research.md` | regulation rows R1..R8 (§4 table, in order), patterns T1..T11 (§3), opportunities L1..L10 (§6), table stakes TS (§2) |
| `LOG·` | `../outpero-vs-calevate-2026-11-28/LOG.md` | O1..O10, C1..C13 and defects C3-a, C8-a, C8-b, C11-a..d, C12-a..c, C13-a |
| `RD·` | `docs/design/redesign-2026-11-28/PLAN.md`, `COLOUR-OPTIONS.md` | §1..§11, lanes 1-4 |

Plan items are `W<workstream>.<n>`. Evidence classes follow hard rule 11: CODE (read in this
tree), FIRST-HAND (the 28 Nov product walks), VENDOR-PUBLISHED, VENDOR-STATED, REPORTED,
**UNVERIFIED**. Effort is engineering hours for one agent lane.

---

## 1. Executive summary

### Where we stand, by count

| Analysis | Rows compared | Calevate ahead | Even | Behind | Not built at all |
| --- | --- | --- | --- | --- | --- |
| UX·01 client screens | 154 | BETTER 46 | PARITY 53 | WEAKER 37 | LACK 12 (+3 DELIBERATE, 3 not a gap) |
| API·02 developer platform | 36 | BETTER 14 | PARITY 8 | WEAKER 4 | LACK 10 |
| AIQ·03 AI quality | 30 | BETTER 9 (+2 mixed) | PARITY 7 | WEAKER 11 | UNKNOWN 1 |
| BIZ·04 money and operations | 15 ranked gaps | 13 advantages to say, not build | | 15 gaps | |
| MKT·05 market | 18 vendors + 3 others | 10 open lead positions | | | |
| LOG side-by-side build | 1 brief, both products | law, outcomes, branches | | 2 P0, 1 P1, 4 P2, 1 P3 defects | |

**Where we lead.** Compliance that the product enforces rather than the customer promises
(truthful answers on every call, one dial gate for every path, consent ledger, self-serve
erasure, retention limits, A2P declaration gate D-941); a results home with cost per lead;
one agent with many jobs; shared, reviewed knowledge; script depth (step outcomes,
push-backs, branches, reviewed Pip diffs, 30 versions, the healer); a 17-lens leads view;
native Meta, IndiaMART and property-portal intake; signed webhooks with immediate-kill
rotation and opt-in transcripts; seven in-call action kinds with a 6 s budget; and price:
Clear ₹4.50 against Outpero Standard ₹5.90 paid, a 3,000-minute month **24.2% less cash**
(₹13,999 vs ₹18,465.82, with the number at the D-681 ₹499 DECISION value, attestation not
read; BIZ·04 §1.2).

**Where we are behind, and by how much.**
- **A new trial owner cannot hear the agent at all** (LOG·C11-a P0): no shared test line, no
  other way to hear it, a 3-minute cap that cuts a 4-5 minute walkthrough.
- **First run is ~2x slower**: ~4 min and 9 screens against ~2 min and 6 (LOG scorecard); the
  redesign lanes cut it to 3 steps (done, pending release).
- **No public API**: 0 operations against Outpero's 37, no keys, no events feed, no
  published docs (API·02 §0).
- **Call quality measured behind the rule text**: bundled actions in 9 turns, four bare
  "Okay"s taken as done, two false completion summaries on the 27-28 Nov founder calls;
  every fix since 0.5.96 is code-only, unmeasured (AIQ·03 §1, version caveat).
- **Voices 3 vs 54**, no filters (LOG·C8-b).
- **Public estate 11 routes vs ~1,500 URLs**, no compare pages, no partner programme
  (BIZ·04 §10).
- **No per-person daily cap and no cross-campaign recently-called skip** (UX·C-12, API·A7,
  BIZ·H-1), now decided.

### The 10 moves that matter most

1. **Make "Hear it" work today** (W1.1-W1.3): operator sets the shared trial line (T-22) and
   `trial_call_max_seconds` 300; then "Play its first words" so an owner hears the agent
   even without a line.
2. **Verify the TRAI Third Amendment at the Gazette** (W0.1) and settle what it means for
   D-692, the D-941 enforcement date and the number series, before anything else is said
   about compliance.
3. **3 calls per person per 24 h on every dial path, plus a 7-day recently-called skip**
   (W0.3, W0.4), enforced in `check_dispatch`.
4. **A release cannot change in-call rules without a live Telugu call-sim run on real-call
   personas** (W3.1), plus a first-run end-to-end eval (W3.3).
5. **Rehearse the real script**: typed rehearsal of a campaign's or line's script, tool calls
   and turn checks inline (W3.2, merges UX·P-14 and AIQ·G2).
6. **Post-call truth by construction**: summaries built from the step state, capture fields
   that are data, sharper outcome definitions (W3.5, W3.6, W3.12).
7. **Public API keystone**: tenant keys with RBAC scopes, a curated frozen `/api/v1`,
   failure-state webhooks (W2.1-W2.4).
8. **Inbound "today" and missed callers**, with a one-tap missed-caller call-back (W4.1,
   W4.2).
9. **Alerts the owner can shape** (quiet hours, daily cap, per-kind channels, campaign
   finished) and phone push (W5.1-W5.4).
10. **Show the proof we already have**: an all-in price month on /pricing and in the app,
    minutes per pack, and the speed-to-lead card (W9.1, W9.2, W8.1).

### Decisions already taken (Claude, under 729dfe15), each with its reason

| Decision | Reason |
| --- | --- |
| Calls to one person capped at **3 per 24 h** per account across every dial path (campaign, new-lead, follow-up, call-back, missed-caller call-back, Pip, one call, API) | One predicate in the gate protects the person from every door; matches the market default (Outpero API docs) without claiming a regulatory figure |
| Meta Page tokens stored as the client's **sealed saved credential** (`integration_credentials`, AAD tenant + credential) to allow self-serve connect | Sealed client credentials are now the repo's one way (`actions/credentials.py`); the env-only argument in `ingest/meta.py:86-110` ("no runtime secret-fetching client") no longer holds; needs a decision row superseding it |
| Owner **"Never" rules enforced by a post-call check and a publish check**, without changing D-1017 storage (they stay pinned facts) | AIQ·G9 found no checker reads them; enforcing at the readers keeps D-1017's one fact store |
| Trial test-call cap **recommended 300 s** (operator console `trial_call_max_seconds`; code default 180 per D-904 unchanged) | Real guided calls ran 4-5 minutes (LOG·C11-b); a console value, not a code change |
| Prices shown **to two decimals** everywhere a rupee rate appears | One format, no "₹4.5" vs "₹4.50" drift; still printed from the server's decimal string (hard rule 7) |
| Colour = **Khata ledger** (A): paper cream, ink navy, green for money, vermilion stamp accent; ruled texture only on hero/brief surfaces | Decided in 729dfe15; built as `8c65bc7c0` |

Further choices made while writing this plan are listed in §7.

---

## 2. Critical and compliance first (W0)

These come before every other workstream because each one either changes what may be
dialled or what may be claimed.

### W0.1 Verify the TRAI Third Amendment (Sep 2026) at the primary source

- **Claim to verify.** MKT·R4 (`analysis/05-market-research.md` §4, SECONDARY: PolicyEdge,
  AZB) and `docs/evidence/trai-tcccpr-third-amendment-2026-09-18.md` (REPORTED: a carrier's
  summary) say the TCCCPR Third Amendment, notified 18 Sep 2026: defines application-to-person
  calls to include **autodialled, prerecorded and artificial-voice** calls; requires the
  sender to **declare the activity and its originating numbers (CLIs) in advance** to the
  originating operator, recorded on DLT, or the calls count as UCC; allows a ₹0.05/min
  termination charge with 140xx/1600xx/1601xx exempt; triggers action on 3 complaints plus an
  AI flag; permits enquiry-based calls for 7 days if the enquiry is kept verifiably; requires
  legacy consents to be registered on the operators' consent platform; adds a 15-day consumer
  appeal. Effective date ~17 Nov 2026 is **REPORTED** (rememory 8a05aded; Gazette not read;
  `trai.gov.in` is egress-blocked here and PR 119/2026 is a scanned PDF).
- **What our product does today (CODE).** D-692 (8 Oct 2026, rememory 89c3461c / 11927871):
  outbound needs verified KYC + the no-cold-calls pledge; the DLT entity chain, bound-DLT
  number and series checks are inactive. D-941 (30 Oct 2026, rememory 79fc3eca;
  `apps/api/compliance/autodialer.py`, `compliance/service.py:47`) restored a calling-number
  (A2P) declaration: the client confirms its numbers and authorises Calevate to file them;
  from the live setting `a2p_declaration_enforced_from` (default 2026-11-17 IST)
  `check_dispatch` refuses `a2p_declaration_missing` / `a2p_number_undeclared`.
  OPERATIONS gate 59 stays open on (f) who the Sender is on a ThinnestAI number, (g) the
  filing route, (h) the Gazette date.
- **Task (verification, not code).** A human outside the container fetches the Gazette of
  India notification (egazette.gov.in) of the TCCCPR (Third Amendment) Regulations, 2026, and
  TRAI PR 119/2026 as text; save both hash-pinned under
  `docs/evidence/trai-third-amendment-gazette-2026/` with URL and read date; answer, quoting
  the operative text: (1) the definition covering artificial voice; (2) who declares, to whom,
  in what form, per sender / per number / per objective; (3) the commencement date;
  (4) whether "recorded on DLT" makes DLT registration of the sender itself mandatory;
  (5) the complaint trigger; (6) the enquiry window and what "verifiable form" means;
  (7) legacy-consent registration; (8) the 15-day appeal; (9) whether the 18 Jun 2024
  direction RG-25/(18)/2023-QoS ("Senders shall not use any other 10-digit fixed line/mobile
  number for making Promotional/Service/Transactional voice calls", PRIMARY,
  founder-relayed, `primary-legal-findings-2026-09-20.md` §1) still stands as amended.
- **Design consequences, either way.**

  | Gazette says | Product consequence | Who decides |
  | --- | --- | --- |
  | As reported: artificial voice = A2P, CLI declaration mandatory | D-941 stays; set `a2p_declaration_enforced_from` to the true commencement date (operator); the declaration text names the verified regulation; filing route from ThinnestAI (§5) | operator + engineering |
  | Declaration must be on DLT **and** the sender must hold a DLT entity registration | D-692's "no client DLT" is contradicted; the dormant DLT tables and gates (kept under hard rule 8) are the fastest path back; outbound for unregistered clients would have to stop on the commencement date | **founder** (D-692 is his) |
  | 10-digit numbers barred for commercial voice (RG-25 stands) | Ordinary mobile numbers for outbound campaigns are exposed; 140-series (promotional) / 1600-1601 (service) numbers via ThinnestAI become a requirement; number catalogue and a series refusal (none exists today: `SERIES_FOR_CLASSIFICATION`, cited in the trai evidence file, is absent from `apps/api`, grep 28 Nov 2026) | **founder** + vendor |
  | Not as reported (narrower) | Relax the D-941 wording to the verified scope; no client claim changes | engineering |
  | Commencement already passed with no declaration filed | Operator files every `calling_numbers_unfiled` number at once (admin Calling numbers board); no client is told it is compliant until filed (hard rule 11) | operator |

  Either way: the complaint threshold (W0.5), the 7-day enquiry window (W0.6) and legacy
  consents (W0.7) are re-read from the same text.
- **Acceptance.** The evidence folder holds the Gazette text and its hash; OPERATIONS gate 59
  (h) is closed or re-opened with the quote; the setting equals the Gazette date; a decision
  row records whether D-692 stands (founder).
- **Verified by.** Reading the saved text; `tests/` for the D-941 gate already pin the day
  (`autodialer.ist_today` fixture); a gate test moved to the new date.
- **Effort.** 2 h of engineering after the human fetch; the fetch itself is external.
- **Dependencies.** External: a human with egress to egazette.gov.in / trai.gov.in; ThinnestAI
  answers to §40 items 1-2 (sender, filing route); counsel gate K-3. Founder: D-692 revisit.
- **Owner impact.** Outbound keeps working lawfully, or stops for a stated reason before a
  carrier disconnects the account; no owner is told "you are compliant" on a paraphrase.

### W0.2 The notices default is a fact, not a marketing line

- **Fact (CODE).** The volunteered AI-disclosure and recording-notice switches are account
  switches since D-1021 (`organizations.notice_ai_enabled`, `notice_recording_enabled`,
  `server_default=false()`, `apps/api/tenancy/models.py:342-345`). Truthful answers when
  asked are always on (hard rule 5). BIZ·04 §9.
- **Rule for every lane.** No public page, sales line, compare page or Pip answer may say
  "every call announces it is AI" or "every call says it is recorded". The truthful claim is:
  "Every agent answers honestly, every time, when asked if it is an AI or if the call is
  recorded. We check this on every publish." MKT·R5: no Indian statute found requiring AI
  disclosure (SECONDARY, UNVERIFIED as a negative; counsel to confirm).
- **Task (allowed: a copy guard, not a behaviour change).** A test over `apps/web/src/app/**`
  public routes and `apps/web/src/lib/legal/**` refusing the phrases "every call announces",
  "always announces", "every call says it is AI" (case-blind), so marketing cannot drift
  into the false claim. 1 h. Verified by `pnpm -C apps/web test`.
- **Founder item, not a task.** Whether the volunteered notices should default ON for new
  accounts. Memory 8c5065c9 / notices-ux-first: nothing in notice composition, defaults,
  weaving or verification changes without him. This plan proposes nothing on it.

### W0.3 Calls to one person: at most 3 per 24 h, every dial path (DECIDED)

- **Problem.** No cross-source per-person frequency cap (API·A7 LACK, `compliance/service.py`
  person rules at :890-1022; BIZ·04 §4 "unconfirmed"; UX·C-12). A complaint-risk control
  today, a harassment vector the day the API ships (API·G3b, rank 3). D-1044's account
  Improve page already counts "people rung by 2+ campaigns in 7 days" with "no exclusion
  mechanism to press".
- **Design.** A new person-level rule `person_contact_pacing` in `person_level_refusal`
  (`compliance/service.py`): attempted-or-connected outbound calls to one E.164 within the
  tenant in a rolling 24 h, counted from `calls` (index `(tenant_id, to_e164, created_at)`
  added by migration, no new table), refused at the 4th with `opens_at` = the instant the
  oldest of the three ages out. Transient, never SETTLED (`compliance/service.py:215-240`
  doctrine), so a campaign contact retries in its next window. N is a console setting
  `person_daily_call_cap` (default 3). Per account, never across accounts (RLS: one tenant
  cannot learn another's dials). **Claude choice:** a test call to the owner's own attested
  number (`own_number_attested`) is counted by the existing trial daily cap (10), not this
  rule, so an owner rehearsing at first value is not blocked after three tries. Inbound
  answering is never counted.
- **Acceptance.** Four calls to one number via four doors (campaign, new-lead, follow-up,
  one call) in 24 h: the 4th refused `person_contact_pacing` with `opens_at`; a campaign
  contact refused is retried, never settled; the refusal sentence appears in the campaign's
  skipped list and Make a call ("Called 3 times today. Can call again at 4:10 PM"); the rate
  census and `scripts/check_compliance_invariants` stay green.
- **Verified by.** New `tests/person_contact_pacing_test.py` (four doors, retry, IST
  boundary, cross-tenant isolation); `make coverage-ratchet`.
- **Effort.** 6 h. **Dependencies.** None external. Decision row (reserve via `reserve_id`).
- **Owner impact.** The business's name and number spam rating are protected without the owner
  having to think about it.

### W0.4 Skip people called recently, any campaign (7 days)

- **Problem.** UX·C-12 LACK, BIZ·H-1 (rank 7), BIZ·04 §4.
- **Design.** Campaign Settings tab: "Skip people we called in the last 7 days" (default on,
  1-30 days, any campaign, any agent); enforced in the campaign dispatcher (not only the
  form) as a campaign-scoped transient refusal `recently_called`; skipped people counted
  and listed with the reason; a change on a running campaign applies from the next tick.
  D-1044's "rung by 2+ campaigns" card gains its button ("Turn on Skip recent calls").
- **Acceptance.** A number called by campaign A on day 1 is skipped by campaign B on day 3
  and dialled on day 8; the People tab shows "N skipped: called in the last 7 days".
- **Verified by.** Dispatcher test with two campaigns and an instant lead; web test on the
  setting. **Effort.** 6 h. **Dependencies.** Lane 3 (campaign tabs) merged; W0.3 migration
  (same index).

### W0.5 Complaint trigger against the verified text

- **Problem.** The reported Third Amendment lowers the trigger to 3 unique complaints in 10
  days with an AI flag (trai evidence §1 row 6). `campaigns/complaint_spike.py` already
  measures a sender window of 10 days (`SENDER_WINDOW_DAYS = 10`) beside the 24 h campaign
  window (CODE); its threshold was written for the old "fifth complaint".
- **Design.** After W0.1, set the sender-window threshold to the Gazette figure; pause and
  page as today. **Acceptance.** Third complaint in 10 days pauses outbound for the account.
  **Effort.** 2 h after W0.1. **Dependency.** W0.1.

### W0.6 Enquiry evidence, 7 days, on every intake source

- **Problem.** MKT·R4 / §4(c): enquiry-based calls allowed 7 days if the enquiry is kept
  verifiably. Portal presets carry a 7-day permission (API·C3, WEBHOOKS §2.3/2.7); whether
  Meta, website-form, Sheets and custom POST leads carry the same window is UNVERIFIED.
- **Design.** One rule in `ingest/lead_policy.py`: every intake source stores the enquiry
  receipt (raw payload ref in object storage, hard rule 2 pattern) and the window opens at
  receipt; the lead page shows "Asked on 28 Nov, 10:14 AM via Meta form" with the evidence
  link (role + audit). **Acceptance.** A lead older than 7 days without other consent is not
  called. **Effort.** 6 h. **Dependency.** W0.1 for the figure.

### W0.7 Legacy consents and the operators' consent platform

- External until the platform's registration route is known. Recorded so nobody claims our
  `consent_ledger` is that platform (trai evidence §1 row 8). Founder/ops item.

### W0.8 DPDP: what agents remember, retention said where it matters

- UX·S-8 LACK (P-13) and UX·K-2 are DPDP-shaped (notice, storage limitation). Built in W7.3
  and W12.9. MKT·R7: DPDP consent managers ~13 Nov 2026, main duties ~13 May 2027
  (SECONDARY). Counsel gate K-3.

### W0.9 Recording consent

- MKT·R6: no single statute found (UNVERIFIED). Counsel gate K-3. No product change; the
  recording notice stays the founder's (W0.2).

### W0.10 Comparative advertising

- **Claude choice:** no public page names Outpero in this plan; compare pages are against the
  real alternatives a Telugu SMB weighs (human telecaller, IVR, generic telecalling software)
  (BIZ·G-3). Naming a competitor carries a trade-mark and comparative-advertising risk that a
  dated price line does not remove; revisit only with counsel.

---

## 3. Workstreams

Format per item: **Problem** (evidence) · **Design** (Calevate-native) · **Acceptance** ·
**Verified by** · **Effort** · **Dependencies** (internal / EXTERNAL) · **Owner impact**.
"Keep" items (we are ahead) are listed in §3.14 so none is dropped.

### W1 Hear it: trial calling and first run

**W1.1 Shared trial line (operator).** Problem: `platform_settings.trial_caller_number` null
since 18 Nov (D-1020, rememory a81c1223); every trial and shared-line test call refuses
`trial_calling_not_ready` (LOG·C11-a P0, UX·F-5, BIZ rank 1, AIQ footnote). Design: ops
console → Calling limits and pacing → Free trials → Shared trial number; pick a
developer-workspace number no client recorded (buy one if none), "Set it up now"
(`POST /v1/ops/trial-number/line`), smoke test per `runbooks/trial-calling.md`. Acceptance:
a trial Hear-it call rings and is recorded with transcript. Verified by the admin smoke
`POST /v1/admin/tenants/{id}/trial/test-call` and one founder call. Effort 0.5 h ops.
EXTERNAL: operator. Impact: the P0 goes.

**W1.2 Trial call length 300 s (operator, DECIDED).** UX·F-7, LOG·C11-b. Set
`trial_call_max_seconds` 300 in the console; the Hear-it copy reads the live value ("Each call
stops at 5 minutes"), never a literal. Acceptance: a 4.5-minute guided call is not cut.
Verified by a trial call; web test that the copy reads the panel value. 0.5 h ops + 1 h if
any copy is literal. EXTERNAL: operator.

**W1.3 "Play its first words" (UX·P-01).** Problem: no way to hear the agent without a line
(UX·F-5, F-6, N-5). Design: on Hear it and the campaign/line Test call fold, beside the phone
box, a button that plays the opening line and the first step's first line in the chosen
voice, rendered server-side through the voice preview path
(`components/voicePreviewButton.tsx` lineage); no microphone, no consent, no minutes; text
played = stored opening including any woven notices (never cut). When the line is unset the
box says why in one line and offers this plus typing. Acceptance: with the line null, sound
within 5 s; played text equals stored text; no provider named; no consent tick bypassed for
the phone call. Verified by an API test on the render route (fake engine), web test, a
browser check at 375/1280 px. Effort 8 h. Dependencies: EXTERNAL ThinnestAI Q1 (can a short
arbitrary text be rendered in an agent's voice; else a direct TTS render inside the engine
adapter seam, hard rule 2, on our Cartesia key for Studio voices only); metered as test
audio, absorbed. Impact: first value in seconds.

**W1.4 Browser test call: founder item, vendor question.** The founder chose phone-only test
calls (D-825; rememory a81c1223, 33944051). ThinnestAI's only web call is the website widget
with a public key that authorises nothing and bypasses the dial gate, trial minutes and caps
(snapshot 2026-11-26 `channels/website.md:9-29`). Ask ThinnestAI for a server-minted
single-use web-call session with `maxCallSeconds` and a reference (§5 Q5). If offered, the
founder decides whether to reverse D-825. No build until both.

**W1.5 Consent ticks in the right order (BIZ·04 §9, rank 5; LOG·C11-c; UX·F-6).** Design: the
four document acceptances become one "I accept the Privacy Policy, Terms, Acceptable Use and
Data Processing Addendum" row with each document a link that expands in place; the pledge
and "This number is my own" stay separate ticks; each `legal_acceptances` row is still written
per document and revision. List source and consent date stay at campaign launch. Acceptance:
four rows per accept; the server gate (`agreements_blocker`) unchanged; screen reader reads
each link. Verified by API test (four rows), web test. Effort 4 h. Dependencies: RD lane 1
merged (owns Hear-it). **Claude choice, flagged:** RD §10 said "must not change the 6 Hear-it
ticks" for the redesign lanes; this is a separate change with its own decision row, the
records unchanged.

**W1.6 Start KYC during the trial (BIZ·N-1, rank 6).** Problem: `trial_kyc_unavailable` makes
credit → KYC → business details → number strictly sequential (memory 9ffe7db0). Design: a
trial owner may submit PAN or DigiLocker and be reviewed; the number purchase and the
business-details submission stay behind the first payment (the workspace is created then,
D-697); on first payment the business-details job is queued automatically. Acceptance:
review state carries over; no number bought on trial; `scripts/check_compliance_invariants`
green. Verified by `tests/trial_test_calls_test.py` extension, KYC route tests. Effort 8 h.
Dependencies: `compliance/trial_access.py` owner (lane W1). EXTERNAL: Cashfree account live
(OPERATIONS K-2).

**W1.7 Screens that agree about the test line (LOG·C12).** The campaign page said "It rings
from our test number" while Hear it said unavailable. Verify after 937a0ee5a that both read
`blocked_rule`; if not, the campaign Test call fold reads the same panel. 1 h. Dependency:
lane 3 merged.

**W1.8 Workspace address that cannot collide (UX·P-23, F-8, LOG·C1).** Design: availability
check as typed; a taken address says "Taken. Try rytu-khata-2" with it filled in; reserved
slugs refused with the reason. Acceptance: no submit with a taken address. Verified by API
test on a new `GET /v1/signup/slug-availability` (rate-limited, no tenant data beyond
taken/free), web test. Effort 3 h.

**W1.9 Follow-up questions that move by tap (UX·P-22, F-2).** Tapping a choice answers and
moves on; "Something else" opens the box; Never-say choices fill the box as editable lines;
back returns to the last answer; focus moves to the new question. Effort 3 h. Dependency: RD
lane 1 merged. Question quality is W3.11.

**W1.10 Re-run the side-by-side build on 0.5.99.** Re-do LOG C1-C13 by hand once the release
holds the redesign, W1.1-W1.3 and the 0.5.98 fixes; record as
`docs/evidence/outpero-vs-calevate-2026-11-28/RERUN.md`. Closes the "reported fixed, not
re-verified" rows: LOG·C3-a, C11-d, C12-a, C12-b, C13-a, C8-a, UX·F-3, F-10. Effort 2 h.

### W2 Public API and integrations

Hard rules on every item: engine isolation (HR2), FORCEd RLS and a zero-rows test on every
new table (HR1), new ledgers in `APPEND_ONLY_TABLES` (HR4), no PII in logs (HR6), every
dial through `check_dispatch` (HR5), NUMERIC money as strings (HR7).

**W2.1 Machine principal: tenant API keys with RBAC scopes (API·G1, A1, A2; rank 1).**
Design as API·02 §G1: `api_keys` table (hash with platform pepper, scopes text[] ⊆
creator's permissions, optional agent and CIDR allow-lists, 90-day expiry with renewal
nudge, `cvk_live_` / `cvk_test_` prefix + CRC); bearer honoured only under `/api/v1/`;
cookie routes keep refusing every bearer; `Origin`/`Sec-Fetch-Site: cross-site` refused,
no CORS; creation is a human step-up act (D-730 pattern); `Principal.kind="api_key"`,
audit rows carry the key id. `calls:read_raw` never grantable. Acceptance: API·G1 items 1-7.
Verified by new `tests/api_keys_test.py`, rate census, redaction test. 12 h. No external
dependency (GitHub secret-scanning registration is a later external step).

**W2.2 Curated public surface `/api/v1` (API·G2, A3, A4 replay header, A5, A8; rank 2).**
Thin adapters over existing service functions with frozen response models in
`apps/api/public_api/schemas.py`: me, balance, agents, numbers, calls (one call for every
mode via `crm/one_call.OneCallIn`, `opens_at` on refusal, `?wait=30` long-poll), leads (typed
captured fields), `POST leads` through `ingest_lead`, campaigns (create, contacts,
launch-check, launch/pause/resume/stop), dnc (DELETE needs a reason, audited; a spoken
opt-out cannot be removed), inbound-calls. `Idempotent-Replayed` header added (A4's small
gap). `scripts/check_public_api_snapshot.py` in `ci.yml` (additive-only enforced).
Acceptance: API·G2 items 1-5. Verified by the route-walk test asserting the gate is called,
snapshot gate. 10 h first slice (me, agents, calls, leads, dnc) + 16 h the rest.
Dependency: W2.1.

**W2.3 Visible rate limits, per-key limits, adaptive daily dial budget (API·G3a, A6; rank
12).** IETF `RateLimit-Policy`/`RateLimit` header fields (check the current draft number
before writing), per key and per tenant over the existing `core/ratelimit.py` profiles;
daily API-placed-call budget from paid state (trial lower), spend caps remain the ceiling.
Per-person pacing is W0.3. 4 h. Dependency: W2.1.

**W2.4 Failure-state webhook events (API·G4a, B1; rank 4).** Add `call.not_connected` (our
reason vocabulary incl. gate rule and `opens_at`), `call.inbound_missed` (with any scheduled
missed-caller call-back), `campaign.status_changed` (started, paused with why: big red
switch, spend cap, credits, owner; resumed, stopped), `lead.consent_changed`, `dnc.added`
(masked phone by default). Keep `campaign.completed`, `call.updated`. Each event gets a
payload test and a `docs/WEBHOOKS.md` row. 7 h. No dependency on W2.1.

**W2.5 Webhook breaker that holds and replays, with a client notice (API·G4b, B3; rank 9).**
After 72 h of all-failed deliveries the endpoint is paused (not deactivated), held deliveries
kept, the owner emailed once per pause (dedupe key) and a bell item posted (W5); Resume replays
in `created_at` order through `resend_delivery`. 5 h. Dependency: W5.1 for the bell kind.

**W2.6 Test event, `*` without future events, machine-managed endpoints, delivery-log
filters (API·G4c, B5, B7; rank 13).** `POST /v1/integrations/endpoints/{id}/test` signed
synthetic envelope `"test": true`; `*` = all current events, future ones opt-in per endpoint;
a key with new scope `webhooks:manage` may create endpoints only for events without
personal-data opt-ins (raw phone, transcript, recording stay a human step-up act, D-730);
`?endpoint_id=&status=&event=` on the log. 5 h. Dependency: W2.1 for the machine half.

**W2.7 Events feed with a durable per-key cursor (API·G5, B9; rank 10).** Append-only
`integration_events` row per fan-out event (30-day sweep, masking at read per key scope,
erasure sibling of `retention._erase_outbox_messages`); `GET /api/v1/events?after=&type=`,
`GET /api/v1/events/next` + `POST …/ack`. Same `id` as the webhook. 9 h. Dependency: W2.1,
W2.4.

**W2.8 API activity log (API·G6, E2; rank 11).** `api_requests` partitioned table (route
template, never raw path or query; status, problem code, trace id, latency, replay flag),
written via Redis stream + worker, never on the request transaction; dashboard last 100 with
filter, "Explain this error" from `remediation`, per-key 24 h health. ≤1 ms p95 added.
7 h. Dependency: W2.1.

**W2.9 Self-serve Meta Lead Ads connect + live proof (API·G7, C4; rank 5; DECIDED storage).**
"Connect Facebook Page" OAuth (`pages_show_list`, `leads_retrieval`, `pages_manage_metadata`),
app subscribes the Page to `leadgen`; per-tenant Page token in `integration_credentials`
sealed (AAD tenant + credential id), superseding the env-only rule in `ingest/meta.py:86-110`
by decision row; `meta_page_token_invalid` with Reconnect; Page-id spoofing still impossible
(keyed by lead source). 14 h. EXTERNAL: Meta app with Advanced Access to `leads_retrieval`
(Meta App Review + Business Verification of the Calevate legal entity); OPERATIONS §2b live
delivery gate; `graph.facebook.com` egress-blocked here, so the live read is a human test.

**W2.10 Published developer docs, public OpenAPI, Postman (API·G8, A10, E3; rank 6).**
`calevate.tech/developers` generated from `public-openapi.json` and WEBHOOKS.md (CI fails on
drift); each operation states its gate and possible refusal codes (route annotation);
Telugu-first zero-code worked example "IndiaMART enquiry → Telugu call → Google Sheet"; no
provider named (D-679); Postman regenerated on release. The client-realm "For developers"
screen (UX·DEV-1, P-18: keys, quickstart, webhooks, activity) lives under Integrations. 8 h.
Dependency: W2.2.

**W2.11 n8n community node, Make/Zapier/Pabbly templates (API·G8b, E1; rank 7).**
`n8n-nodes-calevate` generated from the OpenAPI, trigger node on the events feed or webhooks,
published to npm under our org with provenance, no postinstall, `pnpm audit` clean (HR9);
private Make/Zapier/Pabbly templates; replaces the one sentence at `IntegrationsScreen.tsx:146`.
13 h. Dependency: W2.2, W2.7. EXTERNAL: Zapier and Make public-app review for public listings.

**W2.12 Sandbox keys on the fake engine (API·G9; rank 8).** `cvk_test_` keys run tenant config
on `ENGINE=fake` selected inside the adapter seam; `livemode=false` column on calls, leads,
integration_events; real signed webhooks marked `"livemode": false`; never billed, zero vendor
egress (asserted); hidden unless "Show test data"; erased after 7 days. 18 h, riskiest (column
across tables). Dependency: W2.1, W2.2, W2.4.

**W2.13 Versioning policy and `api_version` on envelopes (API·G10, A9; rank 14).** WEBHOOKS.md
§0 policy (additive-only within a version, enforced by the W2.2 snapshot gate), date-pinned
`Calevate-Version` per key, `api_version` on every envelope; transforms built only at the
first breaking change. 3 h. No dependency.

**W2.14 JustDial and Sell.Do intake presets (API·G11, C5; rank 15).** `ingest/portals.py`
presets with sender-id dedupe and the 7-day permission, fixture tests from each vendor's
published push format. 4 h each. EXTERNAL: the formats, read at source (HR11), or from the
client's account manager.

**W2.15 Speed-to-lead from the intake side (API·G12).** Routed to W8.1; the API path must
report the same timing (test that an API-created lead appears in the card).

**W2.16 MCP / agent-facing API (MKT·TS "moving into table stakes", MKT·T3).** An MCP server
over the public `/api/v1` with the same key and scopes, read-mostly (calls, leads, balance)
plus "place a call" behind `leads:dispatch`. 6 h. Dependency: W2.2. Claude choice: after
the n8n node, because the n8n stack is what Indian SMB integrators use (API·02 rank 7).

**W2.17 WhatsApp as a channel, not a link (MKT·L8, T7).** One knowledge base for calls and
WhatsApp replies is existing direction (D-1041 follow-ups); WhatsApp Business Calling is beta
in India (UNVERIFIED GA). Recorded as an external watch: no build until Meta states GA and
pricing.

### W3 AI quality and the eval gate

Root finding (AIQ·03 §1 net): our design is ahead, our measured output on 27-28 Nov was
behind; every 0.5.96-0.5.98 fix is code-only. Rule from here: no in-call rule ships without
a measured run.

**W3.1 Live Telugu call-sim release gate on real-call personas (AIQ·G1; rank 1; rows 16-19).**
(a) Personas from the founder's real calls (21:35, 00:48 and every later founder test call):
caller lines from `transcript_turns.text_redacted`, name/number redacted, under
`scripts/fixtures/call_sim/recorded/rytu/`, `expected_flags` from the founder's notes;
(b) `uv run python -m scripts.eval_calls --live --holder campaign:<id>` against the release
candidate's composed prompt on the VPS, report committed under `docs/evidence/call-sim/`,
required by the release checklist whenever `engine.py`, `call_script.py` or
`spoken_style.json` changes; (c) existing kinds `several_actions`, `done_without_signal`,
`moved_on_unclear`, `claimed_complete`. Acceptance: 0 of each and 0 report-back asks across
≥10 live runs per persona; `tests/call_sim_test.py` equality ratchet only shrinks.
Effort 16 h. Dependencies: VPS run access (ours); founder's call notes for flags.

**W3.2 Rehearse the real script (AIQ·G2 rank 2, row 15; UX·P-14, E-6; MKT·L1, T3).**
Design (one item, two analyses merged): "Rehearse" docked on the campaign and Inbound line
Script tab (closed by default; right panel at 1280 px, sheet on a phone), typing through the
holder's **current saved script** using the test copy republished with that script
(`agents/paid_test_calls.refresh_test_copy`, `copy_call_live` guard); every tool the engine
returns (`apps/api/engine/test_chat.py:47-52` `tools`, `tool_results`) shown in owner words
with "not run" ("Would hang up", "Would book a call-back for 5 PM", "Looked up: prices");
`turn_checks.turn_problems` on each reply as a quiet flag with "Fix this in the script" (a
part ask). Nothing contacts a person (test window open, opt-out `recorded_in_test`); free on
trial within the AI quota. Acceptance: a not-yet-launched campaign can be rehearsed before
Start; a reply with two actions shows the flag; every tool appears with "not run". Verified
by web test with a mocked turn carrying two tools; API test that the copy carries the
holder's script. Effort 12 h. Dependencies: **D-960 gap** (a test copy is never given the
client's knowledge, rememory 4704409e) must be closed first: a holder for copies in
`engine_facts.sync_business_facts` (migration), 4 h, inside this item. **Claude choice:**
rehearsal runs the holder's saved script, never an unsaved Pip proposal of a live holder,
which keeps the founder's 10 Oct "no hidden draft twin" decision (rememory 33944051). A
vendor draft endpoint is asked (§5 Q3) only as a later improvement.

**W3.3 First-run end-to-end eval (AIQ·G3, rank 3; rows 1-4; LOG·C3-a, C5-C7, C12-a).** Two
`tests/fixtures/script_writer_cases/cases/` entries from the raw brief (`brief.txt`
verbatim; a fictional English inbound clinic brief), recorded answers, scored on: opening
present and passing `placed_opening_problems`; one step per owner task; pinned facts ≥ facts
in brief; Never-rules present; calling window applied; no service-area question for a remote
business. Acceptance: both pass recorded in CI and `--live` on the VPS. Verified by
`uv run python -m scripts.eval_script_writer --cases first_run_rytu,first_run_clinic_inbound`.
8 h.

**W3.4 Simulated-call gate before the owner sees a draft (AIQ·G4, rank 4; MKT·L1).** After
`campaign_script._write` stores a draft, an outbox job runs three personas (cooperative,
stuck, stops early) via the test copy; findings attach as `script_checks` warnings with turn
numbers; failing steps go back to `write_script(mode="steps")` once; metered to the AI
allowance like the healer (D-985). Owner sees "Tried it 3 ways: 1 problem". 10 h.
Dependency: W3.1 harness, W3.2 copy knowledge fix.

**W3.5 Summaries and statuses from the step state (AIQ·G5, rank 5; row 25).** Summary in two
parts: a code-built "where it got to" clause from `StepProgress` and model prose restricted to
what the caller wanted and said, completion verbs refused by the call-page check; markers
dropped unless the quote is found in its anchored turn after `_plain` (extend
`moments.said_on` to Latin quotes). Acceptance: on `golden_transcripts.json` plus the redacted
21:35 and 00:48 transcripts, no "done/complete/all steps" when the last non-branch step is not
reached; zero markers whose quote is absent. Verified by the extraction golden run. 10 h.
Note: first extraction stays on Sarvam (`GEMINI_EXTRACTION_DEFAULT is False`); the change is
in how the summary is composed, not the leg.

**W3.6 Capture fields are data; judgements come from steps and outcomes (AIQ·G6, rank 6; row
24).** `apps/workers/lead_fields_draft.py` refuses, and `field_suggestions` never offers, a
status/progress/outcome/result field when the holder has steps or outcomes (reuse
`job_details` "heard_detail", memory 5b5faada); proposed fields typed (`date`, `enum`,
`number`). Acceptance: Rytu redraft has no status-type field. 4 h.

**W3.7 Targeted edit mode for free-form Pip changes (AIQ·G7, rank 7; rows 9-10; UX·E-5).**
`WriteRequest("edit")`: one small request maps the instruction to `{paths, change_per_path}`;
only those steps or lines are rewritten; untouched stages byte-identical (asserted); a global
rule fans out as `fields=` per step; one-line "What Pip changed" per review row; run timed in
`holder_script_written`. Acceptance: on the four Swara instructions (ai-tests.md §2) on the
Rytu script, all honoured, unchanged steps identical, p50 ≤ 40 s on the VPS. 12 h.

**W3.8 Sensitivity rails from what the business does (AIQ·G8, rank 8).** `BusinessFit` gains a
`sensitive` set read from the brief (health advice, money advice, legal advice, urgent
danger), each mapped to writer rules and a judge rule in `call_rules.CALL_RULES` (one record,
four readers); urgent danger yields a side step whose words the writer writes and the owner
reviews; numbers obey `_NUMBER_BULLETS`. No trade name in code (memory not-clinic-centric).
Acceptance: the clinic case gets an urgent side step and a never-advise rule; an app business
gets none; the judge fails a practice caller given a diagnosis. 10 h.

**W3.9 Owner "Never" rules enforced, storage unchanged (AIQ·G9, rank 9; row 12; DECIDED).**
Never-rules stay pinned facts (`kb_facts`, origin `quick_fact`, `teach/pinned.py pin_pairs`,
CODE: no distinct marker). Design: (1) **publish check**: a reader classifies the account's
pinned facts into prohibitions (model-classified once per fact hash, cached; the owner's words
kept verbatim) and runs them against the holder's script like `script_lint.unbacked_promise`
(a rule naming a promise: "never promise a call-back time" vs an offered call-back with a
time); a breach is a blocking `script_checks` problem with the step named; (2) **post-call
check**: the post-call judge reads the same prohibitions and records a `call_mistakes` kind
`owner_rule_broken` with the turn, feeding the existing healer and Improve cards.
Acceptance: a practice caller asking "call me at 5?" fails when the agent promises 5 PM under
that rule; a script offering a call-back time is refused at publish. Verified by
`test_conversations` judge fixture, lint test. 8 h. Founder item only if D-1017 storage must
change; this design does not change it.

**W3.10 Native-language turn checks beyond word lists (AIQ·G10, rank 10; rows 16-18).** Keep
the word-list fast path (Telugu words added 28 Nov: సెటప్, స్టార్ట్ చే, సేవ్ చే, 729dfe15); add a
model-judged per-turn counter in the sim and rehearsal for non-English turns (actions asked,
report-back asked) returning counts only; calibrated on the founder-annotated turns of 21:35
and 00:48. Acceptance: finds the nine bundled turns of 00:48 and both report-back asks, no
false flags. Labelled fixture, no new Telugu written by us. 8 h.

**W3.11 Questions that separate place, service area, calling window and opening hours
(AIQ·G11, rank 11; rows 2-3; LOG·C5).** `QUESTIONS_INSTRUCTION` distinguishes `location` from
areas served; the pinned-fact step labels each ("Based in", "Serves", "Calls between",
"Open"); the script writer reads the labels so "free" is never conditioned on "based in".
Measured by W3.3. 4 h.

**W3.12 Outcome definitions an owner can make precise (AIQ·G12, rank 12; row 23; UX·E-9).**
`BusinessOutcome` gains bounded `counts_when` / `not_when`, drafted per job, two short lines in
the editor, rendered into extraction. Acceptance: a polite "I'll think about it" is not "Not
interested" on golden transcripts. Migration on the outcomes store. 6 h.

**W3.13 Early stop: say what is left and offer the later, measured (AIQ·G13, rank 13; row
19).** Sim persona that stops after step N; scorecard kind `left_unsaid`. Acceptance: 0
`claimed_complete`, 0 `left_unsaid` over 10 live runs. 3 h. Dependency: W3.1.

**W3.14 Numbers on emergency and price lines, checked (AIQ·G14, rank 14; row 21).** Add a fee
and an urgent number to the clinic case; `turn_checks.spoken_number` and digit-by-digit in the
sim; amounts the English way per D-1024. 3 h. Dependency: W3.1, W3.8.

**W3.15 Let the owner see what the agent is told (AIQ·G15, rank 15; rows 26-27).** A read-only
view of the OWNER part of the compiled prompt (never the platform rules, D-674). **Claude
choice:** the three-position stick-to-script dial proposed in AIQ·G15 is **not** built: the
founder fixed strictness at two levels on 10 Oct and 23 Oct (rememory 33944051, f25e3e68),
and per-step "say it word for word" already covers exact words. Acceptance: the view never
shows `CONFIDENTIALITY_MARKER` text or the truthful-answer block; publish read-back unchanged.
4 h.

**W3.16 Caller-memory recap on a placed call (BIZ·M-1, rank 12; rememory 45ac22b9).** Founder
item (a/b/c pending). Until he decides, one line on the agent Settings when memory is on for
an outbound agent: what a returning person hears. Copy only, 1 h; call behaviour untouched
(notices-ux-first).

**W3.17 Facts vs rules taxonomy on screen (AIQ row 12).** Covered by W3.9 at the readers; the
What it knows tab labels pinned Never lines "Rule" from the same classification (display
only, storage unchanged). 2 h. Dependency: W3.9.

### W4 Inbound receptionist

**W4.1 Inbound "today" strip and Missed view (UX·P-05; N-1, N-3, N-7; UX rank 4).** Inbound list
opens with a strip per line: "Answered today 14 · Missed 2 · Waiting for you 3" (IST day),
each a link; a Missed view per line lists callers not answered or who hung up before speaking,
with reason and "Call them back now" (through the gate, W0.3 counted); "Waiting for you" =
call-backs and messages left for the owner. Acceptance: counts IST; failed read says so.
10 h. EXTERNAL: ThinnestAI Q2 (is a caller who hung up before the agent spoke a call event?);
until answered the Missed view lists what our events do carry and says so.

**W4.2 One-tap "Call back missed callers" (UX·E-13, N-8; BIZ·M-2, rank 14).** On the line page
under Outside hours, a switch that creates or enables the existing `missed_call_callback`
follow-up for this line and reads its real state back; once, inside opening hours, never DNC,
counted by W0.3. **Claude choice:** ON by default for lines created after this release,
existing lines untouched (no silent behaviour change on a live account). 4 h.

**W4.3 "Message for the owner" as its own kind (UX·N-7).** A caller message is a typed item in
"Waiting for you" and an alert kind in W5.1 ("message left"), distinct from a call-back
request. 4 h. Dependency: W5.1.

**W4.4 "Today, just say a message" (UX·P-25, E-19, E-18).** On a line: a switch with the
owner's message and an until-date; calls answered with the notices (as the account's switches
say, hard rule 5 untouched), the message, then end; logged "Message played"; auto-off at the
until-date; a wrap-up line at the call time limit on the same screen. 10 h. EXTERNAL:
ThinnestAI Q4 (fixed-message agent); not buildable on a guess.

**W4.5 Leads who call back the number a campaign rang from (BIZ·04 §6 row "Leads calling
back").** UNVERIFIED what happens today when a campaign's lead rings the campaign's calling
number. Task: trace `apps/api/inbound` routing and the engine's `answersCalls` for outbound
agents; then design: the call lands on the agent's Inbound line if it has one, else a minimal
answer that recognises the lead and offers a call-back. 2 h trace + 8 h build if needed.

**W4.6 Hand-off with context (MKT·T5).** When an agent passes a caller to a person
(`panels/handover.tsx`), send the person a WhatsApp note with the caller's masked number and a
two-line reason before the transfer rings, if the team member has consented. 6 h. EXTERNAL:
ThinnestAI Q8 (is there a pre-transfer hook or is our action budget enough).

**W4.7 Inbound test in the browser (UX·N-5).** Same founder item as W1.4.

### W5 Alerts and notifications

**W5.1 Alerts you can shape (UX·P-08; S-3, S-5, S-6; BIZ·A-1; BIZ rank 3; UX rank 12).** One
table on Alerts: rows = what happened (hot lead, call-back asked, message left, failed call,
low credit, campaign finished, opt-out, webhook paused), columns = bell, this computer, email,
WhatsApp. Money, numbers, KYC, a paused agent, inbound stopped and call failures are "always"
and cannot be unticked (UI and API), reason behind ⓘ. Quiet hours (IST, default 9 PM-8 AM,
held, never dropped, one message at the end), at most N a day then one digest, "Send me a
sample" per channel (marked sample). `notification_preferences` row per person, FORCEd RLS,
zero-rows test. Acceptance: hot lead at 23:00 IST arrives 08:00; the 13th email folds into
"and N more"; always-on rows refuse an API write. 14 h. EXTERNAL: a WhatsApp digest template
approved (UNVERIFIED that one exists).

**W5.2 Campaign finished (UX·P-12, C-21, S-4).** Bell item + email (+ WhatsApp if consented):
"Your campaign <name> finished: 412 called, 63 interested, 9 asked to call back. See them";
idempotent on campaign id + finish time; figures equal the Progress tab; no phone numbers.
3 h. Dependency: W5.1 for its switch.

**W5.3 Owner-chosen triggers on captured answers (BIZ·A-3; UX·S-5).** "Email me when <captured
field> is <answer>" reading the holder's typed extraction schema; extends `JobAlerts.tsx`
(per job) to the account Alerts page. 6 h.

**W5.4 Phone push with the tab closed (BIZ·A-2, rank 4; UX·I-7).** PWA manifest + service
worker + Web Push for the always-on kinds and the live "new lead is being called" pop-up;
per device, pause 1 hour / rest of today. HR9: no new dependency without a lockfile review;
VAPID keys via the secrets manager. 14 h.

**W5.5 Milestones (BIZ·A-4).** First lead, first booked result, 100/500/1,000 calls as bell
items. 2 h.

**W5.6 Morning summary option (BIZ·A-5).** 08:00 IST beside 20:58 for the daily summary; CAS
per day unchanged. 2 h.

**W5.7 Reminders to call people (BIZ·04 §7 "Reminders").** Time-based nudge: a hot lead waiting
1 h+ or interested yesterday and not called, as a bell item from the attention queue. 3 h.

### W6 Campaigns and lists (after redesign lane 3)

**W6.1 "Before it dials" receipt (UX·P-09; C-4, C-5, C-11, C-16; UX rank 5).** On a draft, a
compact receipt under the header (side rail at 1280 px, fold at 375 px): "Nothing is dialled
until you start." then six linked lines (agent and number, people after DNC/duplicates/recent
skips, when incl. holidays, calls at once, tries per person, starts); DNC line fixed with a
lock. One source with `campaignSummary.tsx`; links via lane 3's `openCampaignSection()`. 4 h.

**W6.2 People: the script's details as chips, and "Leave these people out" (UX·P-10 parts;
C-7, C-16).** Before upload, "This script uses: name, village" chips; a campaign-only
exclusion list for one-off "not existing customers". Account DNC stays the legal control.
6 h.

**W6.3 Holidays for campaigns (UX·P-11, C-10; BIZ·H-2, rank 13).** Reuse the business holiday
list in `ingest/lead_policy.py:69`; campaign When section shows "Skips your holidays: 2 Dec, 25
Dec · Change"; dispatch reads the same list; "Holiday: not calling" on the run. One list for
the business. 4 h.

**W6.4 Copy a script from another job (UX·P-21, H-8).** "Start from another script" on a Script
tab lists this account's campaigns and lines; copies steps and opening into the draft for
review; never puts anything live; notices re-composed for the new job by the existing weave
(no change to notice behaviour). The founder's 23 Oct "JSON copy/paste through the same
validation" (f25e3e68 item 6) is the same seam: add "Paste a script" through the same
validation. 5 h.

**W6.5 "Calls at once" says the truth (LOG·C12-c P3; UX·C-14, P-24 part).** Until the owner
sets a figure: "Up to 1 at a time (your account's limit)". 1 h.

**W6.6 Add calls at once without waiting for us (BIZ·P-4, rank 8; UX·U-3).** Phone number
screen "Add a line (up to 4)": instant raise to 3-4 while the shared pool has headroom
(`outbound_line_pool`), through `sync_engine_call_lines` with read-back; above 4 or at ≥80% of
`thinnest_max_concurrent_calls`, queued for an operator with a plain sentence; no price until
the vendor states what more concurrency costs. 8 h. EXTERNAL: ThinnestAI Q7 (concurrency
above 20 and its cost).

**W6.7 Pre-campaign cost estimate (MKT·L7).** Moved to W9.4.

### W7 Leads and CRM views

**W7.1 Lead desk view (UX·P-06, L-2; UX rank 14).** "Desk" beside the table: one column per
stage in pipeline order; card = name, last outcome, the owner's most important captured field,
next call-back; "Move to" menu (drag only as a shortcut); on a phone a stage picker with cards
below; writes through `StatusSelect.tsx`'s mutation, audited; keyboard-movable; view remembered
per browser (try/catch). Fixes the dangling "the board" mention at `StatusSelect.tsx:9`. 8 h.

**W7.2 Owner notes on a lead and a call (UX·P-07, L-7, K-3; UX rank 15).** "Add a note for your
team" on the lead and call pages, saved as a `note` lead event (`crm/models.py:114`) with
author; a call note links back; edits are a new event if the table is append-only (check
`APPEND_ONLY_TABLES` first); text never logged (HR6); Pip reads notes only under existing
consent. RLS zero-rows test. 5 h.

**W7.3 What your agents remember (UX·P-13, S-8; BIZ rank 12; W0.8).** Under Data rights and
beside the memory switch: caller (masked), agent, calls, last outcome, last call, "Forget this
caller" through the existing erasure path with a deletion proof; "Kept until you clear it"
when the switch is off. Memory lives in the engine since D-973, so the list's source is
EXTERNAL: ThinnestAI Q6 (list/delete a contact's past conversations per workspace). Until
answered: list from our own `calls` grouped by caller where memory was on, labelled as "calls
it may remember", with Forget calling the engine contact erasure already pushed to the client
workspace. 8 h.

**W7.4 Find, for the client console (UX·P-02; G-4, Q-3; UX rank 9).** Top-bar "Find a person,
call or screen" (Ctrl/⌘K, search icon on a phone); groups People (name, last 4 digits, never a
number in a URL or log), Calls, Agents, Campaigns, Inbound lines, Screens (from
`apps/api/copilot/screens.py`), "Ask Pip: <text>"; Telugu typed in English letters matches
Telugu names; reuse `components/interior/command-palette.tsx`; no People group without
`calls:read`. 10 h. Dependency: confirm the leads `search` matches partial digits (UNVERIFIED;
add if not).

### W8 Analytics, including speed-to-lead

**W8.1 Speed-to-lead proof on Leads & hours (UX·P-04, I-6; API·G12; MKT·T6; UX rank 3).**
"How fast we called" card: median seconds from arrival (or after-hours release, said behind ⓘ)
to ringing, share rung within 60 s, never reached, waiting now; by-source table filtering
Leads; "Called within a minute vs later: interested rate" only from 30 leads, counts beside it;
ranges 24 h/7/30/90 IST; server-side over the tenant's rows (RLS). New client analytics
endpoint over the timing `core/alerting.record_speed_to_lead` already sees
(`ingest/service.py:718-772`). No industry "lead goes cold" statistic in copy (UNVERIFIED,
MKT·T6). 10 h.

**W8.2 Performance you can narrow (UX·P-24; P-b, P-c, P-d, P-h, P-j, K-1; UX rank 17).**
Filters Agent · Campaign or line · direction; Interested rate and Spent (billing roles only) in
the band, both "vs the previous N days"; "Last hour" mini line while calls are live; Download
per table; credits used on the call log for billing roles. 8 h. Dependency: which analytics
endpoints take filters (UNVERIFIED; extend).

**W8.3 Agents list answers "is it working today?" (UX·P-03; A-2, A-3, A-4; UX rank 10).** Row
line "Today: 12 calls · 3 interested · last 4 min ago" (IST), a **Try it** text action opening
the rehearsal (W3.2), search and chips Working / Off / Not live yet above five agents; failed
read hides the line. 5 h. Dependency: RD lane 2 merged (owns `agents/page.tsx`); `AgentStats`
today/interested counts (UNVERIFIED; add).

**W8.4 Call-page truths (UX·P-26 parts; K-3).** "Who talked more" bar on the call page; "Send to a
team member" (a link that opens only for a logged-in member with access; never public; raw
transcript only with `calls:read_raw`). 5 h. The retention line is W12.9.

**W8.5 Per-call quality scorecard, included (MKT·L5, T4; TS).** `CallQualityCard`,
`CallMistakesCard` and `CallVerdict` exist (CODE); make the scorecard visible as an account
column on Call logs and a weekly average on Performance, with "what the agent didn't know"
linked to Questions to answer. Sales point: included, where SquadStack and Retell charge. 6 h.

**W8.6 Published Telugu quality numbers (MKT·L2; BIZ·G-5).** Switch on `public_quality_page_enabled`
(`config.py:633`) once ≥10 real calls a week (D-944 floor); measured weekly reply speed per
language and answered share; method on the page. Engineering 2 h; EXTERNAL: real call volume.

### W9 Billing and pricing presentation

**W9.1 All-in month on /pricing and in the app (BIZ·P-1, rank 2).** "A month of 3,000 minutes on
Clear: ₹X, nothing added" computed from `GET /v1/public/rate-card` plus the attested number
price; cash per minute shown; a sentence for the GST-registered buyer (we charge no GST, so no
input credit; compare against their pre-GST price); no competitor named in the app; a test
fails on any literal ₹ figure. Two decimals (DECIDED). 4 h. EXTERNAL: operator confirms the
attested number price (D-681 ₹499 is DECISION; production attestation not read).

**W9.2 Minutes on each pack (BIZ·B-1; UX·B-5; G-7).** "₹5,000 ≈ 1,111 Clear minutes or 833 Studio
minutes" from `/v1/billing/topups/packs` frozen rates, floor(amount / rate), server-computed.
3 h.

**W9.3 Money while calls run (UX·P-29; G-5, G-7).** Live pill gains "about ₹X a minute now"; the
credit chip says "about N minutes left"; both from the server, hidden without billing access.
5 h. Dependency: a server minutes-left figure (UNVERIFIED that it exists; add).

**W9.4 Honest cost estimate before a campaign starts (MKT·L7; UX·C-4).** On the W6.1 receipt:
"About ₹A to ₹B for this list" from people count, the account's own answered rate and median
answered length over 30 days (fallback: stated as unknown, never a guess), 30-second steps,
retries; computed server-side in NUMERIC. 6 h. Dependency: W6.1.

**W9.5 Say we charge nothing per AI message (BIZ·04 §2).** One line on What calls cost:
building, teaching, rehearsing and Pip are inside the AI allowance, never per message. 1 h.

**W9.6 30-second worked example check (BIZ·04 §2 row "Cost explainer").** Confirm
`WhatCallsCost.tsx:166` gives "40 s = one minute"-style examples; add if not. 1 h.

**W9.7 Keep ₹4.50 and ₹6.00 (BIZ·P-2, RECOMMENDATION accepted).** No price change. Before any
future change, re-read the Studio band rate (recheck date 22 Nov passed, memory 66aaedec):
operator/vendor item §5 Q9. No volume rung until D-728's condition is met.

**W9.8 Credit validity (BIZ·P-3, rank 11).** Founder item. Recommendation: keep 12 months and the
honest sentence beside each pack (option a); (b) 24 months for ≥₹10,000 or (c) no expiry are
material Terms changes (D-897, every client re-accepts).

**W9.9 Bill of supply clarity (BIZ·04 §1.1 GST row).** The statement already says no GST and no
tax invoice; add the same sentence at checkout. 1 h.

**W9.10 Fixed monthly or outcome pricing (MKT·T10, T11).** **Claude choice:** not offered. Per
minute stays (market default, prepaid wallet ledger); cost per result already shown (D-944).

### W10 Voices

**W10.1 A voice shelf worth choosing from (UX·P-15, E-10; LOG·C8-b; UX rank 7; MKT·T9).** Groups
"Speaks Telugu natively" / "Speaks Telugu too"; filters language, man or woman, tone (calm,
warm, energetic); a 6-second sample in the business's own opening; the lane-4 price line; only
admin-enabled voices (clients never clone); no provider name; 375 px. 8 h web + admin field for
tone tags 3 h. EXTERNAL: the admin adds and auditions Telugu voices (Studio clones up to 25,
VENDOR-STATED 23 Oct 2026) and tags tone; "test Premium Telugu voices by ear first" (founder 10
Oct, rememory 6279091e).

**W10.2 Price per voice (UX·E-10 price; LOG·C8-b).** DONE in RD lane 4 (`e4ba74de2`), pending
release. Remaining gap from RD §11: lane 4 must confirm `/v1/billing/topups/packs` answers a
trial account; if refused the row says "Price shown when you add credit" (verify in W1.10).

**W10.3 Contradictory voice note (LOG·C8-a).** DONE in lane 4 (note only when the server's pick
says `fallback`); verify in W1.10.

**W10.4 Ambient sound (UX·E-10).** Exists (`callHandlingVoiceRows.tsx:588-697`); surface it in
the Voice tab with a sample. 2 h.

### W11 Go-to-market: pages, proof, partners

**W11.1 "The rules on every dial" trust page (BIZ·G-2; MKT·L4).** Each true claim from BIZ·04 §9
beside its mechanism, linked to a public doc section: truthful answers verified on every
publish, DNC on every path plus national scrubs, consent record per list, retention limits,
calling hours, one refund policy, status page, named sub-processors, A2P declaration filed for
you (only once W0.1 and the filings make it true). No "every call announces AI" (W0.2). No
superlatives. 5 h copy + 2 h page.

**W11.2 Compare pages, few and dated (BIZ·G-3; MKT §5).** Three pages: vs a human telecaller, vs
an IVR, vs generic telecalling software; each with a live-rate-card worked month and a
"checked on <date>" line with a 30-day recheck. No page names Outpero (W0.10). 3 h each.

**W11.3 A small, true content estate (BIZ·G-1; MKT·L10).** ~20 hand-written pages: Telugu, the 8
business kinds on /signup, the 5 jobs (receptionist, missed-call call-back, lead call,
campaign, reminder); each with a live worked month and a plain compliance section linked to
`/legal`; in `PUBLIC_ROUTES`, no literal ₹, sitemap-derived. Before deciding the count, read
Google's spam policies on scaled content (developers.google.com/search/docs/essentials/spam-policies),
not re-read here. 12 h engineering; the Telugu sections are the founder's to write (memory
no-competitor-wording; founder writes Telugu wording).

**W11.4 Partner programme with published terms (BIZ·G-4, rank 10; MKT·L9).** Public /partners
page with terms; attribution field at signup; referral reward paid as calling credit through the
wallet ledger, idempotent on the referred client's first payment id; agency invited as a team
member on the client's account (no sub-accounts or white-label yet). 10 h. Founder item: the
reward amount (no figure derivable from a verified cost).

**W11.5 Proof without inventing it (BIZ·G-5, rank 15; MKT·L6).** W8.6 public quality page, and the
first paying client's named case study with written consent. The homepage policy "No customer
counts, logos, testimonials or case studies" (`app/page.tsx:50`) stays until then. EXTERNAL:
paying clients.

**W11.6 Trust on the handset (MKT·L3, R8, T2).** One public line once true: "Your business name
shows on the caller's screen" requires CNAP showing the client's KYC name on its own-name number
(D-693) — UNVERIFIED that every operator meets the 1 Nov 2026 CNAP direction and that a
ThinnestAI-rented number shows the client's name (§5 Q10). Truecaller for Business
evaluation: EXTERNAL, pricing UNVERIFIED. No claim until verified.

**W11.7 Say the advantages we already have (BIZ·04 §11 "say so, not build"; UX §2; API §4).** One
sales sheet and the developer page carry: per-minute price, 2 free calls at once, no GST, DNC
everywhere, consent ledger, self-serve erasure, retention limits, 30-day mistaken top-up refund,
cost per result, auto-recharge, status page, named sub-processors, bring-your-own number,
signed webhooks with instant kill, consent-aware intake, seven in-call actions, required
idempotency, RFC 9457 errors, Pip-built integrations. 3 h.

### W12 Remaining UX after the redesign

The redesign (RD lanes 1-4, Khata palette) is done pending release: lane 1 `31b5dbd3c`, lane
2 `596d8645e`, lane 4 `e4ba74de2`, palette `8c65bc7c0`. **Lane 3 (campaign tabs) had no commit
visible in `git log --all` when this was written; treated as being merged per the brief.**
Items below are what the lanes leave.

**W12.1 Brief card on home until something is live (UX·P-19, H-6).** Lane 1's card is the
dashboard's first block while no agent is live; then a "Give an agent a new job" row under the
results; never for a role that cannot create agents. 3 h. Dependency: lane 1.

**W12.2 Job starters you can see (UX·P-20, H-7).** Six cards under the brief card written for this
business by D-827 copy (call new enquiries, remind appointments, collect payments, win back,
confirm orders, answer my calls), filling the box; keys shared with `follow-ups/Starters.tsx`;
no stock photos; Telugu when the account's language is. 4 h.

**W12.3 Help a person answers (UX·P-16; G-9, G-10, Q-1; UX rank 13).** Header Help menu: Ask Pip,
How Calevate works (8 owner-word pages, last-updated date on each), Talk to us (WhatsApp or
call-back request) shown only when a support contact is configured (console). 6 h. Founder
item: who answers and on what number and hours.

**W12.4 Show me around, for the whole account (UX·P-17, G-8).** 4-step owner-started tour from
Help (Dashboard → Agents → Leads → Credits), same rules as `tourModel.ts`. 3 h. Dependency:
lane 4's tour model.

**W12.5 Phone bar and quick agent links (UX·P-27; G-2, Q-4).** Under 768 px: Home · Leads · Calls ·
Pip · More, safe-area aware, not hiding Pip; agents listed under Agents in the sidebar when five
or fewer; `screens.py` groups stay equal to `clientNav.ts`. 4 h. Dependency: lane 4.

**W12.6 Switch business without signing out (UX·P-28, G-3).** Business name at the top of the
sidebar opens this person's workspaces; D-177 realm separation kept; no cross-tenant cache. 4 h.

**W12.7 Hard-coded colours that ignore tokens (RD §8 table).** Verify whether `8c65bc7c0` moved
the listed literals (`successRipple.tsx`, `collapsible-banner.tsx`, `floating-label.tsx`,
`otp-input.tsx`, `live-activity.tsx`, `load-more.tsx`, `modelLogo.tsx`, `iconTile.tsx`,
`StartCampaign.tsx:50`, `UpdateWatcher.tsx`, scrims, `FoldSection` series tones); move any left
to `text-danger`/`text-warn`/tokens; contrast tests and `test:a11y-browser` green. 3 h.

**W12.8 Redesign leftovers from RD §11.** Pip screen-directory token budget after the new groups
(a 16 Nov memory, REPORTED, put the prompt 40 tokens over 17,500; find the check and run it);
`screens_test.py` run in CI after lane 4 (not run on this host). 2 h.

**W12.9 Retention said on Call logs (UX·P-26 part, K-2; BIZ·04 §8).** One line from the tenant's
retention setting (never a constant): recordings 90 days, transcripts 365 days anonymised, per
`compliance/retention_defaults.py:15-64`. 2 h.

**W12.10 Owner-words guard holds (RD §6).** Lane 3's `ownerWords.test.ts` stays green for every
lane here; new screens use the §6 words. 0 h (rule).

**W12.11 Remaining LOG defects closed by lanes or 0.5.98, re-verified in W1.10.** LOG·C3-a (P1,
fixed `brief ?? ownBrief`, lane 1 re-tests 800 chars), C11-d (lane 1), C12-a (P0, `45ce56730`),
C12-b (lane 3), C13-a (lane 3 `openCampaignSection()`), C8-a (lane 4), C9 "What first?" (lane
1 removes it), C10 stale "Says first" (lane 1).

### W13 Operations, vendor and platform

**W13.1 Number price attestation read (BIZ·04 §1.1).** Operator reads the production attested
rental; W9.1 and any public claim wait for it. 0.5 h.

**W13.2 Landline numbers in the catalogue (UX·U-2).** UNVERIFIED whether the catalogue offers
landlines; §5 Q11. MKT row Vomyra claims mobile-style numbers get far higher pickup (vendor claim,
UNVERIFIED) — no product claim from it.

**W13.3 Self-serve signup state (MKT·05 §5 "self-serve signup is off", REPORTED).** LOG·C1 shows
/signup creating a workspace for a signed-in founder; verify for a new visitor in W1.10.

### 3.14 Keep: where we are ahead (do not trade away)

From UX·01 §2 items 1-18, API·02 §4, BIZ·04 §11 tail, AIQ rows marked BETTER. No build; W11.7
says them. Specifically kept: hard rule 5 on screen (UX·E-17; E-20 "power prompting" stays
DELIBERATE: never offered), the compliance gate with Show me (UX·C-2, C-8, C-11), results home
(UX·H-1..H-5, H-9), one agent many jobs (UX·E-11), shared reviewed knowledge (UX·E-7), script
depth (UX·E-4, E-5; AIQ rows 6, 8, 11, 28, 29), leads lens (UX·L-3, L-5, L-6), call page
(UX·K-3), follow-through screens (UX·K-5), Make a call (UX·K-4), performance heatmap/ridgeline
(UX·P-i, P-k), lead sources (UX·I-2), number forwarding and spam labels (UX·N-9, U-1, U-4),
billing (UX·B-2, B-3, B-6), team and WhatsApp alerts (UX·S-5, S-12), data rights (UX·S-9,
S-11), status page (UX·Q-2), phone preview and trial chip (UX·G-13, G-14), notifications bell
(UX·G-6), failure honesty (UX §2.18, LOG·O10). Dark mode stays dormant (UX·G-11, D-471); one app
(UX·G-12); owner-started tours (UX·E-22).

---

## 4. Sequencing: waves, lanes, file ownership, releases

Rules for every wave:
- **File ownership is exclusive inside a wave.** A lane that needs another lane's file asks it or
  waits for its merge.
- **Migrations serialise at merge:** each migration's `down_revision` is re-pointed to the
  current head when its lane merges; `alembic heads` must print one head before the release.
- **Before any push:** `make db-reset`, `make redis-reset`, `make coverage-ratchet`, reading
  `make`'s own exit status and requiring a `COVERAGE RATCHET:` line (hard rule 10); then
  `uv run ruff`, `uv run mypy apps packages` (after `uv sync --all-packages --group errors`),
  `uv run lint-imports`, OpenAPI snapshot freshness, `make web-check` (incl.
  `test:a11y-browser`), and the gates enumerated in `.github/workflows/ci.yml` (read it, do not
  recall it, hard rule 12).
- **Every UI change:** browser check at 375 px and 1280 px on the node mock API, screenshots in
  the lane's `shots/`; design skills read first (memory design-skills-always).
- **Call-behaviour changes** (anything in `engine.py`, `call_script.py`, `spoken_style.json`)
  ship only with a W3.1 live sim report, once W3.1 exists.
- **Notices are untouched in every lane** (opening-notice weave, defaults, verification).

### Wave 0: now, no code (runs in parallel with everything)

| Item | Who |
| --- | --- |
| W1.1 trial line, W1.2 300 s, W13.1 number price read | operator |
| §5 vendor email to ThinnestAI (Q1-Q11) | Claude drafts, founder sends (signed Umesh) |
| W0.1 Gazette fetch | a human with egress |
| §5 founder items | founder |
| Merge redesign lanes 1-4 + palette; confirm lane 3 | release owner |

### Wave A, release 0.5.99: hear it, protect people, measure, say the price

| Lane | Items | Owns (exclusive) | Migration |
| --- | --- | --- | --- |
| A1 Gate | W0.3, W0.4, W0.5 (after W0.1), W0.2 guard test | `apps/api/compliance/service.py`, new `apps/api/compliance/pacing.py`, `apps/workers/campaign_dispatch.py`, `apps/api/campaigns/complaint_spike.py`, `apps/api/core/config.py` (new settings only), `apps/web/src/app/c/[slug]/campaigns/CampaignSettings.tsx` (skip setting only), new `tests/person_contact_pacing_test.py`, `tests/recently_called_test.py`, `apps/web/tests/noFalseNoticeClaims.test.ts` | yes (calls index) |
| A2 Eval | W3.1, W3.3, W3.13, W3.14 (fixtures half) | `scripts/eval_calls.py`, `scripts/call_sim/**`, `scripts/eval_script_writer.py`, `scripts/fixtures/call_sim/**`, `tests/fixtures/script_writer_cases/**`, `tests/call_sim_test.py`, `docs/evidence/call-sim/**`, release checklist in `docs/OPERATIONS.md` (its row only) | no |
| A3 Hear it | W1.3, W1.5, W1.7, W1.8, W1.9 | `apps/web/src/app/c/[slug]/agents/first/**`, `apps/api/agents/trial_panel.py`, new `apps/api/agents/first_words_audio.py`, `apps/api/engine/` (render method only, HR2), `apps/api/tenancy/signup_routes.py` (slug check), `apps/web/src/app/signup/**`, agreements accept UI `apps/web/src/app/c/[slug]/agreements/**` | no |
| A4 Price | W9.1, W9.2, W9.5, W9.6, W9.9 | `apps/web/src/app/pricing/**`, `apps/web/src/app/c/[slug]/billing/TopUp.tsx`, `WhatCallsCost.tsx`, `apps/api/billing/payment_routes.py` (pack minutes field) | no |
| A5 Inbound | W4.1 (events we have), W4.2, W12.9 | `apps/web/src/app/c/[slug]/inbound/**` (lane 3's back-link line excepted), `apps/api/inbound/**` routes for counts, `apps/api/follow_ups/starters.py` (enable path), `apps/web/src/app/c/[slug]/calls/CallsScreen.tsx` (retention line only) | no |
| A6 Small UX | W6.5, W12.7, W12.8, W3.16 copy | `campaigns/CampaignSettings.tsx` concurrency line **(coordinate with A1: A6 lands after A1)**, colour literals listed in W12.7, `agents/[agentId]/sections/settings*` memory line | no |

Ships in 0.5.99: per-person cap and recent-call skip, first words played, consent in one tick,
signup collision fixed, tap-to-answer questions, all-in price and minutes per pack, inbound today
and one-tap missed call-back, retention line, Calls-at-once truth, colour literals, the live sim
gate itself (as a release requirement from this release on).

### Wave B, release 0.6.0: API keystone, rehearsal, post-call truth, alerts, leads, analytics

| Lane | Items | Owns | Migration |
| --- | --- | --- | --- |
| B1 API core | W2.1, W2.2 (first slice then rest), W2.3, W2.13, W2.8 | `apps/api/core/auth.py` (machine path), new `apps/api/public_api/**`, new `apps/api/api_keys/**`, `apps/api/core/ratelimit.py` (headers), `scripts/check_public_api_snapshot.py`, `.github/workflows/ci.yml` (its step only), `docs/WEBHOOKS.md` §0, `apps/web/src/app/c/[slug]/integrations/developers/**` (new) | yes (`api_keys`, `api_requests`) |
| B2 Webhooks | W2.4, W2.5, W2.6, W2.7 | `apps/api/integrations/**`, `apps/workers/webhooks*.py`, `docs/WEBHOOKS.md` (event rows), `apps/web/src/app/c/[slug]/integrations/DeliveryLog.tsx`, `EventChoices.tsx` | yes (`integration_events`) |
| B3 Rehearse + edit | W3.2 (incl. D-960 copy knowledge), W3.7, W3.15 | `apps/api/teach/try_chat.py`, `apps/api/engine/test_chat.py`, `apps/api/agents/paid_test_calls.py`, `apps/api/agents/engine_facts.py`, `apps/workers/campaign_script.py`, `apps/workers/script_writer.py`, new `apps/web/src/components/rehearse/**`, the Rehearse dock slot in `agents/[agentId]/script/**` | yes (copy KB holder) |
| B4 Post-call truth | W3.5, W3.6, W3.12, W3.9 (post-call half) | `apps/workers/extraction.py`, `apps/workers/step_truth.py`, `apps/workers/lead_fields_draft.py`, `apps/api/crm/moments.py`, `packages/shared/src/calevate_shared/business_outcomes.py`, `apps/workers/business_outcomes_draft.py`, `tests/fixtures/golden_transcripts.json` | yes (outcome fields) |
| B5 Alerts | W5.1, W5.2, W5.3, W5.5, W5.6, W5.7, W4.3 | `apps/api/notifications/**`, `apps/workers/notifications.py`, `apps/workers/owner_digest.py`, `apps/workers/team_alerts.py`, `apps/web/src/app/c/[slug]/settings/alerts/**`, `campaigns/JobAlerts.tsx` | yes (`notification_preferences`) |
| B6 Leads | W7.1, W7.2, W7.4 | `apps/web/src/app/c/[slug]/leads/**`, `apps/api/crm/routes.py` (notes, search), `apps/web/src/app/c/[slug]/calls/[callId]/**` (note box only), `ClientTopHeader.tsx` (Find field only), `components/interior/command-palette.tsx` | no |
| B7 Analytics | W8.1, W8.2, W8.3, W8.5 | `apps/web/src/app/c/[slug]/lead-sources/**`, `performance/**`, `agents/page.tsx` + `agents/Roster.tsx`, `apps/api/analytics/**` | no |

B3 also owns the W3.9 publish-check half in `apps/api/agents/script_lint.py` and
`script_checks.py`; B4 owns the judge half in `call_rules.py`. Ships in 0.6.0: public API
v1 (keys, calls, leads, campaigns, DNC, agents, balance, inbound), docs page draft, failure
events, breaker, test event, events feed, activity log, rehearsal of the real script,
targeted Pip edits, truthful summaries, typed capture fields, sharper outcomes, owner Never
rules enforced, alert preferences, campaign finished, desk, notes, Find, speed-to-lead,
narrowed performance, agents "today".

### Wave C, release 0.6.1: simulation gate, sensitivity, campaigns, push, voices, GTM, help

| Lane | Items | Owns | Migration |
| --- | --- | --- | --- |
| C1 AI rails | W3.4, W3.8, W3.10, W3.11, W3.17 | `apps/workers/first_run.py`, `apps/api/first_run/questions.py`, `apps/api/agents/business_fit*.py`, `call_rules.py` (after B4 merged), `apps/workers/script_sim_gate.py` (new) | no |
| C2 Campaigns | W6.1, W6.2, W6.3, W6.4, W9.4, W6.6 | `apps/web/src/app/c/[slug]/campaigns/**`, `apps/api/campaigns/**` (except complaint_spike), `ingest/lead_policy.py` (holiday read), `apps/web/src/app/c/[slug]/phone-number/**`, `apps/api/tenancy/call_lines.py` | maybe (exclusion list) |
| C3 Push | W5.4 | `apps/web/public/manifest*`, new service worker, `apps/web/src/lib/desktopAlerts.ts`, push routes in `apps/api/notifications/push*.py` | yes (push subscriptions) |
| C4 Voices | W10.1, W10.4 | `components/engineCatalogueList.tsx`, `agents/panels/delivery.tsx`, admin voice catalogue screens | yes (tone tags) |
| C5 GTM | W11.1, W11.2, W11.3, W11.4, W11.7, W2.10 public page | `apps/web/src/app/(public)/**` new routes, `apps/web/src/lib/site.ts`, `app/sitemap.ts`, new `apps/web/src/app/partners/**`, `apps/api/billing/referrals.py` (new), signup attribution field | yes (referral attribution) |
| C6 Help + shell | W12.1-W12.6, W9.3, W8.4, W7.3, W1.6 | `ClientTopHeader.tsx` (Help menu, after B6), `ClientSidebar.tsx`, `clientNav.ts` + `apps/api/copilot/screens.py`, `DashboardScreen.tsx`, `apps/web/src/app/c/[slug]/data-rights/**`, `compliance/trial_access.py`, `apps/api/compliance/caller_memory.py` | maybe (KYC trial state) |

Ships in 0.6.1: simulated-call gate before review, sensitivity rails, question separation,
campaign receipt, holidays, chips, copy a script, cost estimate, self-serve extra lines, phone
push, voice shelf, trust page, compare pages, content estate, partner programme, help menu,
account tour, phone bar, workspace switcher, money while calls run, call-page share and talk
ratio, remembered callers, KYC on trial.

### Wave D, release 0.6.2: the externally gated items

| Lane | Items | Gate |
| --- | --- | --- |
| D1 | W2.9 Meta self-serve | Meta App Review + Business Verification |
| D2 | W2.11 n8n node + templates, W2.16 MCP | W2.2, W2.7 merged; Zapier/Make review for public listings |
| D3 | W2.12 sandbox | W2.1, W2.2, W2.4 merged |
| D4 | W4.4 say-a-message, W4.1 hung-up-before-speaking, W4.6 hand-off note, W1.3 voice render (if a vendor change is needed) | ThinnestAI Q1, Q2, Q4, Q8 |
| D5 | W2.14 JustDial, Sell.Do | published formats |
| D6 | W8.6 quality page, W11.5 case study | ≥10 real calls a week; a paying client's consent |
| D7 | W0.6, W0.7 enquiry evidence and consent platform | W0.1 Gazette text |

Wave D lanes start the moment their gate opens; nothing in them waits on a calendar.

---

## 5. External asks, ready to send

### ThinnestAI (draft for the founder to send, signed Umesh)

| # | Question | Plan item |
| --- | --- | --- |
| Q1 | Can we render a short arbitrary text (≤300 chars) in a given agent's voice and language, as audio we can play in our dashboard, without a call? If not, is a catalogue-voice preview with custom text possible? | W1.3 (UX·P-01) |
| Q2 | When a caller rings a number and hangs up before the agent speaks, or the call fails on your side, do we receive a call event? Which fields, and is it distinguishable from an answered call? | W4.1 (UX·P-05) |
| Q3 | Can the test chat run an agent's unpublished draft configuration? Does the test chat of a test-copy agent return `tools` and `tool_results` for every tool call? | W3.2 (UX·P-14) |
| Q4 | Can an agent be configured to play one fixed message (after our notices) and end the call with no conversation, switchable by API with an end date? | W4.4 (UX·P-25) |
| Q5 | Can you mint a server-side, single-use web-call session for one person, with `maxCallSeconds` and our reference returned on the call events, so a browser test call passes our gate and limits? | W1.4 |
| Q6 | Can we list and delete what caller memory (`pastConversations`) holds per contact in a customer workspace? Is there a per-call override of `pastConversations` on place-call? | W7.3, W3.16 |
| Q7 | What does concurrency above our 20-call pool cost, and can it be raised per customer workspace? | W6.6 (BIZ·P-4) |
| Q8 | Is there a hook before a transfer rings the person, so we can send them a note with the caller's reason? | W4.6 |
| Q9 | Please re-state the current Studio-band and Premium-band per-minute rates for our pay-as-you-go account (our recheck date of 22 Nov has passed). | W9.7 (BIZ·P-2) |
| Q10 | On a number a client rents through us, whose KYC name does CNAP show? Who is the Sender under the Third Amendment, and by what route and form do we declare the client's calling numbers (follow-up to email §40 items 1-2)? Can you offer 140-series and 1600/1601-series numbers? | W0.1, W11.6 |
| Q11 | Does your number catalogue offer landlines as well as mobiles, and at what monthly price? | W13.2 (UX·U-2) |

### Operator actions

| Action | Plan item |
| --- | --- |
| Set the shared trial number (OPERATIONS T-22) and smoke-test | W1.1 |
| Set `trial_call_max_seconds` = 300 | W1.2 |
| Set `a2p_declaration_enforced_from` to the Gazette commencement date; file every `calling_numbers_unfiled` number | W0.1 |
| Read and confirm the attested number rental | W13.1, W9.1 |
| Confirm `person_daily_call_cap` = 3 once shipped | W0.3 |
| Add and audition Telugu voices; tag tone | W10.1 |
| Configure the support contact (number, hours) once the founder names an owner | W12.3 |
| Switch on `public_quality_page_enabled` at ≥10 real calls a week | W8.6 |
| Meta app: App Review for `leads_retrieval`, Business Verification of the Calevate entity | W2.9 |
| Zapier / Make public-app review (only for public listings) | W2.11 |
| Register the `cvk_` key prefix with GitHub secret scanning (terms first) | W2.1 |
| Cashfree KYC account live (OPERATIONS K-2) | W1.6 |
| Fetch the Gazette text (egress) | W0.1 |

### Founder items (his by standing decision)

1. **Notice defaults**: whether the volunteered AI and recording notices default on for new
   accounts (today both off, D-1021). Nothing changes without him (notices-ux-first).
2. **D-692 after W0.1**: whether "no client DLT" stands once the Gazette is read, and the
   140/1600-series question for outbound numbers.
3. **Caller-memory recap on placed calls** (rememory 45ac22b9): (a) keep recap and reword, (b)
   fresh for outbound, (c) accept.
4. **Browser test call** (D-825 phone-only) if ThinnestAI offers Q5.
5. **Referral reward amount** for the partner programme (W11.4).
6. **Credit expiry** (W9.8): recommendation keep 12 months.
7. **Support owner**: who answers "Talk to us", on what number, what hours (W12.3).
8. **Telugu copy** for the content estate and native review of new `call_words.json` entries
   (W11.3, W3.10).
9. **Counsel gate K-3**: recording consent, AI disclosure negative, comparative advertising.

---

## 6. Traceability

Every analysis item → plan item → wave. "Keep" = §3.14 (no build, W11.7 says it). "Lane n" =
redesign, done pending release.

### UX·01 rows

| ID | Verdict | Plan | Wave |
| --- | --- | --- | --- |
| G-1 | WEAKER | RD lane 4 | done |
| G-2 | WEAKER | W12.5 | C |
| G-3 | WEAKER | W12.6 | C |
| G-4 | LACK | W7.4 | B |
| G-5 | PARITY | W9.3 | C |
| G-6 | BETTER | Keep | — |
| G-7 | PARITY | W9.2, W9.3 | A, C |
| G-8 | WEAKER | lane 4 (agent tour) + W12.4 | C |
| G-9, G-10 | WEAKER, LACK | W12.3 | C |
| G-11 | DELIBERATE | Keep (D-471) | — |
| G-12 | not a gap | Keep | — |
| G-13, G-14 | BETTER | Keep | — |
| H-1..H-5, H-9 | BETTER | Keep | — |
| H-6 | WEAKER | lane 1 + W12.1 | C |
| H-7 | WEAKER | W12.2 | C |
| H-8 | WEAKER | W6.4 | C |
| A-1, A-5 | PARITY | Keep | — |
| A-2, A-3, A-4 | WEAKER | W8.3 | B |
| A-6, A-7 | BETTER | Keep | — |
| E-1 | PARITY | lane 2 ("Calls (n)") | done |
| E-2 | PARITY | Keep | — |
| E-3 | WEAKER | lane 2 | done |
| E-4 | BETTER | Keep; lane 3 owner words | done |
| E-5 | PARITY | W3.7 | B |
| E-6 | WEAKER | W3.2 | B |
| E-7 | BETTER | Keep | — |
| E-8 | PARITY | Keep (breadth: W2) | — |
| E-9 | PARITY | lane 2 notes tab + W3.12 | B |
| E-10 | WEAKER | lane 4 price + W10.1, W10.4 | C |
| E-11 | BETTER | Keep | — |
| E-12, E-14, E-15, E-16 | PARITY | Keep | — |
| E-13 | WEAKER | W4.2 | A |
| E-17 | BETTER | Keep | — |
| E-18 | PARITY | W4.4 (wrap-up line) | D |
| E-19 | LACK | W4.4 | D |
| E-20 | DELIBERATE | Keep (never offered) | — |
| E-21 | PARITY | Keep (W6.4 adds paste) | C |
| E-22 | DELIBERATE | Keep | — |
| E-23 | BETTER | Keep | — |
| F-1 | WEAKER | lane 1 | done |
| F-2 | WEAKER | W1.9, W3.11 | A, C |
| F-3 | PARITY (reported) | W1.10 re-verify, W3.3 | A |
| F-4 | PARITY | Keep | — |
| F-5 | WEAKER P0 | W1.1, W1.3, W1.4 | 0, A |
| F-6 | BETTER (friction) | W1.5 | A |
| F-7 | WEAKER | W1.2 | 0 |
| F-8 | WEAKER defect | W1.8 | A |
| F-9, F-11, F-12 | BETTER | Keep | — |
| F-10 | PARITY (reported) | lane 1 re-test, W1.10 | A |
| F-13 | WEAKER | lane 1 | done |
| C-1, C-8, C-17, C-19, C-20 | BETTER | Keep | — |
| C-2 | BETTER | Keep; Show me lane 3 | done |
| C-3 | WEAKER | lane 3 | done |
| C-4, C-5 | WEAKER | W6.1 | C |
| C-6, C-9, C-13, C-15 | PARITY | Keep | — |
| C-7 | PARITY | W6.2 | C |
| C-10 | LACK | W6.3 | C |
| C-11 | PARITY | W6.1 (lock line) | C |
| C-12 | LACK | W0.4, W0.3 | A |
| C-14 | WEAKER | W6.5 | A |
| C-16 | WEAKER | W6.2 | C |
| C-18 | not a gap | — | — |
| C-21 | LACK | W5.2 | B |
| L-1, L-4, L-8 | PARITY | Keep | — |
| L-2 | LACK | W7.1 | B |
| L-3, L-5, L-6 | BETTER | Keep | — |
| L-7 | LACK | W7.2 | B |
| K-1 | BETTER | W8.2 (credits used) | B |
| K-2 | WEAKER | W12.9 | A |
| K-3 | BETTER | W7.2, W8.4 | B, C |
| K-4, K-5 | BETTER | Keep | — |
| P-a, P-e, P-f, P-g, P-j | PARITY | W8.2 (export) | B |
| P-b, P-c, P-h | WEAKER | W8.2 | B |
| P-d | PARITY | W8.2 | B |
| P-i, P-k | BETTER | Keep | — |
| I-1, I-3, I-4, I-5 | PARITY | Keep | — |
| I-2 | BETTER | Keep; W2.14 | D |
| I-6 | LACK | W8.1 | B |
| I-7 | WEAKER | W5.4 | C |
| N-1, N-3 | WEAKER | W4.1 | A |
| N-2, N-4, N-6 | PARITY | Keep | — |
| N-5 | PARITY minus browser | W1.3, W1.4 | A |
| N-7 | PARITY | W4.3 | B |
| N-8 | WEAKER | W4.2 | A |
| N-9 | BETTER | Keep | — |
| U-1, U-4 | BETTER | Keep | — |
| U-2 | PARITY | W13.2 | 0 |
| U-3 | PARITY | W6.6 | C |
| B-1, B-4, B-5 | PARITY | W9.2, W9.6 | A |
| B-2, B-3, B-6 | BETTER | Keep | — |
| S-1, S-9, S-11, S-12 | BETTER | Keep | — |
| S-2, S-7, S-10 | PARITY | Keep | — |
| S-3, S-6 | WEAKER | W5.1, W5.4 | B, C |
| S-4 | PARITY/LACK | W5.2 | B |
| S-5 | PARITY | W5.1, W5.3 | B |
| S-8 | LACK | W7.3 | C |
| DEV-1 | LACK | W2.1, W2.10 | B, C |
| Q-1 | WEAKER | W12.3 | C |
| Q-2 | BETTER | Keep | — |
| Q-3 | LACK | W7.4 | B |
| Q-4 | PARITY | W12.5 | C |

UX·01 proposals: P-01 W1.3 (A) · P-02 W7.4 (B) · P-03 W8.3 (B) · P-04 W8.1 (B) · P-05 W4.1,
W4.2 (A/D) · P-06 W7.1 (B) · P-07 W7.2 (B) · P-08 W5.1 (B) · P-09 W6.1 (C) · P-10 W0.3, W0.4,
W6.2 (A/C) · P-11 W6.3 (C) · P-12 W5.2 (B) · P-13 W7.3 (C) · P-14 W3.2 (B) · P-15 W10.1 (C) ·
P-16 W12.3 (C) · P-17 W12.4 (C) · P-18 W2.10 (B/C) · P-19 W12.1 (C) · P-20 W12.2 (C) · P-21
W6.4 (C) · P-22 W1.9 (A) · P-23 W1.8 (A) · P-24 W8.2, W6.5 (B/A) · P-25 W4.4 (D) · P-26 W8.4,
W12.9 (C/A) · P-27 W12.5 (C) · P-28 W12.6 (C) · P-29 W9.3 (C). UX top-20 ranks 1-20 map
through these proposals (rank 1 P-01+T-22, 2 lanes 1/3, 3 P-04, 4 P-05, 5 lane 3+P-09, 6 P-10,
7 P-15, 8 P-14, 9 P-02, 10 P-03, 11 lane 4, 12 P-08, 13 P-16, 14 P-06, 15 P-07, 16 P-12, 17
P-24, 18 P-25, 19 P-13, 20 P-11).

### API·02

| ID | Verdict | Plan | Wave |
| --- | --- | --- | --- |
| A1, A2 | LACK | W2.1 | B |
| A3 | LACK | W2.2 | B |
| A4 | BETTER (header WEAKER) | W2.2 | B |
| A5 | PARITY | W2.2 (launch-check on API) | B |
| A6 | WEAKER | W2.3 | B |
| A7 | LACK | W0.3 | A |
| A8 | BETTER | Keep | — |
| A9 | WEAKER | W2.13 | B |
| A10 | LACK | W2.10 | B/C |
| B1 | WEAKER | W2.4 | B |
| B2, B6, B8 | BETTER | Keep | — |
| B3 | PARITY | W2.5 | B |
| B4 | PARITY+ | W2.6 filters | B |
| B5 | LACK | W2.6 | B |
| B7 | BETTER | W2.6 machine half | B |
| B9 | LACK | W2.7 | B |
| C1, C6, C7 | PARITY | Keep | — |
| C2, C3 | BETTER | Keep; W0.6 | D |
| C4 | WEAKER | W2.9 | D |
| C5 | PARITY | W2.14 | D |
| D1, D3, D4, D5 | BETTER | Keep | — |
| D2 | PARITY | Keep | — |
| E1 | LACK | W2.11 | D |
| E2 | LACK | W2.8 | B |
| E3 | LACK | W2.10 | B/C |
| E4, E5 | BETTER | Keep | — |
| G1..G12 | designs | W2.1, W2.2, W2.3+W0.3, W2.4-W2.6, W2.7, W2.8, W2.9, W2.10-W2.11, W2.12, W2.13, W2.14, W2.15→W8.1 | A-D |
| ranks 1-15 | | 1 W2.1 · 2 W2.2 · 3 W0.3 · 4 W2.4 · 5 W2.9 · 6 W2.10 · 7 W2.11 · 8 W2.12 · 9 W2.5 · 10 W2.7 · 11 W2.8 · 12 W2.3 · 13 W2.6 · 14 W2.13 · 15 W2.14 | |
| Aug table (memory 777dd436) | | W11.7 says only the still-true rows | C |

### AIQ·03

| Row | Verdict | Plan | Wave |
| --- | --- | --- | --- |
| 1 brief intake | WEAKER obs | lane 1, W1.10, W3.3 | A |
| 2 questions | WEAKER obs | W3.3, W3.11, W1.9 | A, C |
| 3 answers → knowledge | WEAKER obs | W3.3, W3.11 | A, C |
| 4 opening | BETTER/LACK | W3.3 (first-run opening) | A |
| 5 step structure | mixed | W3.3, W3.1 | A |
| 6, 7, 8, 11, 14, 28, 29, 30 | BETTER | Keep (30: thin coverage → W3.1) | A |
| 9 edit speed | UNKNOWN | W3.7 (timed) | B |
| 10 edit faithfulness | WEAKER | W3.7 | B |
| 12 facts vs rules | WEAKER | W3.9, W3.17 | B, C |
| 13, 22, 23, 26, 27 | PARITY | Keep; 23 → W3.12; 26-27 → W3.15 | B |
| 15 rehearsal | WEAKER | W3.2 | B |
| 16, 17, 18 | PARITY/WEAKER obs | W3.1, W3.10 | A, C |
| 19 early stop | WEAKER obs | W3.13 | A |
| 20 unverified claims | WEAKER obs (fixed in code) | W3.1 measures | A |
| 21 numbers | BETTER in rules | W3.14 | A/C |
| 24 capture fields | WEAKER | W3.6 | B |
| 25 summaries | WEAKER | W3.5 | B |
| G1..G15 | | W3.1, W3.2, W3.3, W3.4, W3.5, W3.6, W3.7, W3.8, W3.9, W3.10, W3.11, W3.12, W3.13, W3.14, W3.15 | A-C |
| ranks 1-15 | | same order as G1..G15 | |
| footnote: no test number, 3-min cap | | W1.1, W1.2 | 0 |

### BIZ·04

| ID | Plan | Wave |
| --- | --- | --- |
| §1.1 per-minute, top voice, refunds, running out, billing step, platform fee, min top-up, volume | Keep / W11.7 | — |
| §1.1 number | W13.1, W9.1 | 0, A |
| §1.1 concurrency | W6.6 | C |
| §1.1 free trial | W1.1-W1.3 | 0, A |
| §1.1 GST | W9.1, W9.9 | A |
| §1.1 credit validity | W9.8 (founder) | — |
| §1.2 worked example | W9.1 | A |
| P-1 | W9.1 | A |
| P-2 | W9.7 (keep prices) | — |
| P-3 | W9.8 | founder |
| P-4 | W6.6 | C |
| §2 billing UX rows, B-1 | W9.2, W9.5, W9.6 | A |
| §3 KYC, N-1 | W1.6 | C |
| §3 choice, lapse | Keep | — |
| §4 concurrency C12-c | W6.5 | A |
| §4 calling hours | Keep (09-21 for instant too) | — |
| §4 holidays, H-2 | W6.3 | C |
| §4 recently called, per-person, H-1 | W0.3, W0.4 | A |
| §5 DNC | Keep / W11.1 | C |
| §6 memory, M-1 | W3.16, founder item 3 | A |
| §6 missed-caller, M-2 | W4.2 | A |
| §6 leads calling back | W4.5 | B |
| §7 bell, pop-ups, A-1 | W5.1 | B |
| A-2 | W5.4 | C |
| A-3 | W5.3 | B |
| A-4 | W5.5 | B |
| A-5 | W5.6 | B |
| §7 reminders | W5.7 | B |
| §8 export friction | Keep (deliberate, D-730) | — |
| §8 retention | W12.9 | A |
| §9 claims / notices default | W0.2, W11.1 | A, C |
| §9 ordering | W1.5 | A |
| §10 public pages, G-1 | W11.3 | C |
| G-2 | W11.1 | C |
| G-3 | W11.2, W0.10 | C |
| G-4 | W11.4 | C |
| G-5 | W8.6, W11.5 | D |
| §10 languages breadth | out of scope (staged languages, `agents/languages.py`) | — |
| ranks 1-15 | 1 W1.1-W1.3 · 2 W9.1 · 3 W5.1/W5.3 · 4 W5.4 · 5 W1.5 · 6 W1.6 · 7 W0.3/W0.4 · 8 W6.6 · 9 W11.2/W11.3 · 10 W11.4 · 11 W9.8 · 12 W3.16/W7.3 · 13 W6.3 · 14 W4.2 · 15 W11.5 | |

### MKT·05

| ID | Plan | Wave |
| --- | --- | --- |
| R1 2nd amendment, 140/1600 | W0.1 (series question) | 0 |
| R2 1600 phased mandate (RBI/SEBI/PFRDA clients) | W0.1; a BFSI client cannot use a 10-digit number for service calls: refuse BFSI service campaigns off 1600 once verified | 0/D |
| R3 140/1600 tagging | W0.1, W11.6 | — |
| R4 3rd amendment | W0.1, W0.5, W0.6, W0.7 | 0, A, D |
| R5 AI disclosure | W0.2 | A |
| R6 recording consent | W0.9 | counsel |
| R7 DPDP | W0.8, W7.3 | C |
| R8 CNAP | W11.6, §5 Q10 | — |
| T1 setup effort | lanes 1-3 | done |
| T2 caller trust | W11.6 | — |
| T3 simulation | W3.2, W3.4 | B, C |
| T4 QA scoring | W8.5 | B |
| T5 hand-off | W4.6 | D |
| T6 speed-to-lead | W8.1 | B |
| T7 WhatsApp | W2.17 | external |
| T8 missed-call call-back | W4.2 | A |
| T9 voice choice | W10.1 | C |
| T10 fixed monthly | W9.10 (not offered) | — |
| T11 outcomes | W9.10 | — |
| TS MCP / agent API | W2.16 | D |
| L1 | W3.2, W3.4 | B, C |
| L2 | W8.6 | D |
| L3 | W11.6 | — |
| L4 | W11.1 | C |
| L5 | W8.5 | B |
| L6 | W11.5 | D |
| L7 | W9.4 | C |
| L8 | W2.17 | external |
| L9 | W11.4 | C |
| L10 | W11.3 | C |

### LOG

| ID | Plan | Wave |
| --- | --- | --- |
| O1-O10 | evidence for W1, W3, W10 (O10 silent failure → Keep failure honesty) | — |
| C1 collision | W1.8 | A |
| C2 | Keep | — |
| C3-a P1 | lane 1 + W1.10 | A |
| C5-C7 | W3.3, W3.11 | A, C |
| C8 name prefill "Anjali" | no action (names are per account) | — |
| C8-a P2 | lane 4 + W1.10 | A |
| C8-b | W10.1 | C |
| C9 | lane 1 | done |
| C10 stale | lane 1 | done |
| C11-a P0 | W1.1, W1.3 | 0, A |
| C11-b | W1.2 | 0 |
| C11-c | W1.5 | A |
| C11-d P2 | lane 1 + W1.10 | A |
| C12 copy disagreement | W1.7 | A |
| C12-a P0 | `45ce56730` + W3.3 + W1.10 | A |
| C12-b P2 | lane 3 | done |
| C12-c P3 | W6.5 | A |
| C13-a P2 | lane 3 | done |
| Script faults (bundling, "confirm all done") | W3.1, W3.3 | A |

### RD (redesign)

| ID | Plan | Wave |
| --- | --- | --- |
| §2 tabs, §3 campaign tabs, §4 sidebar, §5 first card, §6 words, §7 tour/prices, lanes 1-4 | done pending release (lane 3 unconfirmed in git) | — |
| §8 colour | `8c65bc7c0` done; literals W12.7 | A |
| §9 founder decisions 1-4 | decided under 729dfe15 (six tabs, Khata, trial sidebar until first minute, "Inbound" stays) | done |
| §11 packs endpoint on trial | W10.2 / W1.10 | A |
| §11 Pip directory budget, screens_test | W12.8 | A |

---

## 7. Choices Claude made while writing this plan

1. Test calls to the owner's own attested number are outside the 3-per-person cap and stay
   under the trial's 10-a-day cap (W0.3).
2. The per-person cap is per account, never cross-account (RLS).
3. UX·P-14 and AIQ·G2 merged into one rehearsal (W3.2) on the holder's saved script via the
   test copy; no hidden draft twin (keeps 33944051).
4. AIQ·G15's three-position strictness dial not built; strictness stays two levels
   (33944051, f25e3e68).
5. Missed-caller call-back defaults on only for new lines (W4.2).
6. The four document acceptances become one tick with links; pledge and own-number stay
   separate (W1.5), against RD §10's lane rule, with its own decision row.
7. No public page names Outpero (W0.10).
8. No fixed monthly or outcome pricing (W9.10); prices unchanged (W9.7).
9. MCP after the n8n node (W2.16).
10. Owner Never rules identified by classification at check time, so D-1017 storage is
    untouched (W3.9).
11. Remembered-callers list falls back to our own call rows, labelled, until the engine can
    list memory (W7.3).

## 8. Not verified here

- The Gazette text, commencement date and every Third Amendment provision (REPORTED/SECONDARY).
- The trai evidence file says outbound is refused off 140/160 via
  `campaigns/service.SERIES_FOR_CLASSIFICATION`; a grep of `apps/api` on 28 Nov 2026 finds no
  such name, consistent with D-692 making series checks inactive. Treat that evidence line as
  stale: today nothing refuses a 10-digit number for outbound.
- Redesign lane 3's merge state (no commit in `git log --all` at writing).
- Production values: number rental attestation, trial days and minutes, concurrency pool,
  self-serve signup for a new visitor.
- `AgentStats` today/interested counts; leads search on partial digits; analytics filters; a
  server minutes-left figure; a WhatsApp digest template; the WhatsApp Business Calling GA.
- Every ThinnestAI capability in §5.
- No test, browser run or eval was executed for this plan.
