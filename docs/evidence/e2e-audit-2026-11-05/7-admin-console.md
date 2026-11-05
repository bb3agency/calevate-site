# Lane 7: admin console (operator side), phase 1 audit, 5 Nov 2026

Scope: `apps/web/src/app/admin/**`, `apps/web/src/app/(auth)/auth/admin/**`, `apps/api/admin/**`,
`apps/api/ops/**` (config catalogue, platform settings), admin Pip (`apps/api/copilot/admin_*`),
admin auth (`apps/api/authn/`), and the call-lines request flow (`apps/api/tenancy/call_line*`).
No code was changed. Screenshots and captured API responses:
`C:/Users/jumes/AppData/Local/Temp/claude/a50a3f0a872c1724/0c51a750-0b23-4950-961e-84972febca40/scratchpad/audit/7-admin-console/`
(file names `<route>-<width>.png|txt`, `<route>-api.json`; `T` = the seeded tenant
`sunrise-homes`, id `01a1aad8-dd07-7ab1-a72e-ce6e56ab972a`). `catalog.txt` there is a dump of all 143
console settings with their default, description length, label and description.

## 0. How this was checked, and what the local stack could not show

- Signed in to the admin realm headless (password, then the emailed six-digit code read from the
  local `outbox_messages` row; nothing printed). Crawled 16 routes at 1440 and 375 px, then 6 more.
- **The local API process is older than the tree.** It answers 404 for `GET /v1/admin/call-line-requests`
  (added today), and its business-copy response has no `capabilities` / `caller_noun`. The local
  database is at alembic `c4e7a2f9d1b8`; `call_line_requests` (migration `e3b8d1f6a924`) does not
  exist there. So the call-lines request flow was **checked from code only**, not driven. I did not
  restart anything (brief).
- **No ARQ worker runs locally**: 23,844 `outbox_messages` rows are `pending`, oldest 10 Oct 2026.
  Findings that depend on that are marked "local cause" and judged only for what the screen does with it.
- The local DB holds 7,704 live organisations (test residue), which makes per-tenant walks slow. Where a
  finding is about speed, I say so and do not extrapolate to production's tenant count.
- Not checked: admin Pip conversations (would spend model calls), destructive levers (halt, replay,
  release, erase), email delivery of the operator notice, the real ThinnestAI read-back of
  `allottedCallLines`.

## 1. Map

### 1.1 Screens (admin realm)

| Route | File | Purpose |
|---|---|---|
| `/auth/admin/sign-in` | `(auth)/auth/admin/sign-in/page.tsx` | Password, then emailed 6-digit code (`MFA_REQUIRED_REALMS={"admin"}`, D-170) |
| `/auth/admin/bootstrap`, `forgot-password`, `reset-password` | `(auth)/auth/admin/*` | First operator setup link; password reset |
| `/admin` | `admin/page.tsx` | Client directory, search, filters, paging, credit left per client |
| `/admin/health` | `admin/health/page.tsx`, api `admin/health.py` | Client health board, worst first, healthy clients omitted |
| `/admin/spend`, `/admin/payments` | `admin/spend/*`, `admin/payments/*` | Fleet money board; payments |
| `/admin/holds` | `admin/holds/HoldsScreen.tsx`, api `admin/holds*.py` | Held accounts |
| `/admin/kyc-reviews` | `admin/kyc-reviews/page.tsx`, api `compliance/kyc_admin_routes.py` | Identity review queue |
| `/admin/calling-numbers` | `admin/calling-numbers/page.tsx` | Calling numbers across clients |
| `/admin/qa-sampling`, `/[sampleId]` | `admin/qa-sampling/*` | Call quality sample review (redacted transcript only) |
| `/admin/announcements` | `admin/announcements/*` | Platform announcements |
| `/admin/assistant` | `admin/assistant/page.tsx`, api `copilot/admin_*.py` | Admin Pip (unmasked by design, D-788) |
| `/admin/new` | `admin/new/NewClientScreen.tsx` | New client wizard (business type required, D-722) |
| `/admin/operators` | `admin/operators/*`, api `admin/operator_routes.py` | Admin accounts |
| `/admin/view-as` | `admin/view-as/page.tsx` | Enter a client's dashboard as operator |
| `/admin/ops` | `admin/ops/OpsSurface.tsx` + panels | Status strip; big red switch; protective slowdown; TM registration; stuck (dead-letter) outbox replay; audit tamper check; engine drift; knowledge drift; unknown-state |
| `/admin/ops/config` | `admin/ops/config/*`, api `ops/config_catalog.py`, `config_routes.py`, `config_service.py` | 143 platform settings in 15 sections, plus money panels: rate card, FX, number price, TTS plan fee, engine minute price, model pricing, data-use approvals, credentials |
| `/admin/ops/alerts` | `admin/ops/alerts/AlertsScreen.tsx`, api `ops/alerts_service.py` | Alarm episodes by window, emailed / not sent |
| `/admin/ops/healer` | `admin/ops/healer/*` | Auto-healer incidents, retries, money reviews |
| `/admin/ops/voices` | `admin/ops/voices/hosted/*` | Voice catalogue, clones, Studio readiness, own-model card |
| `/admin/ops/voice-comparison`, `spoken-style`, `reply-speed`, `reply-times`, `pip-quality`, `call-mistakes`, `whatsapp`, `maintenance`, `dnc`, `kit` | `admin/ops/*` | Quality and ops tools; `kit` is the component kit |
| `/admin/tenants/[id]` | `tenants/[tenantId]/TenantDetail.tsx`, `TenantShell.tsx`, `HealthSummary.tsx`, `accountFacts.ts`, `BusinessCopyPanel.tsx`, `BusinessTypeBanner.tsx`, `UsagePanel.tsx`, `MarginPanel.tsx`, ... | Client overview: facts, health summary, business examples + capability profile (read-only), knowledge queue |
| `.../numbers` | `numbers/NumbersScreen.tsx`, `CallLinesPanel.tsx`, `WorkspacePanel.tsx`, `EngineNumbersPanel.tsx`, `ForwardingCard.tsx` | Numbers, existing-number forwarding, **Calls at once** (raise / decline a request), voice workspace |
| `.../commercials` | `commercials/CommercialsScreen.tsx`, `TermsForm.tsx` | Dated terms: platform fee, ceilings, **"Concurrent calls"** (`concurrency_ceiling`) |
| `.../credits`, `spend`, `invoice` | `credits/*`, `spend/*`, `invoice/*` | Wallet, grants, corrections, trial |
| `.../kyc` | `kyc/KycScreen.tsx`, `KycReviewPanel.tsx`, `KycRecordForm.tsx`, `NumberApprovalPanel.tsx` | KYC review (masked owner ID), DigiLocker require, number approval |
| `.../readiness` | `readiness/ReadinessScreen.tsx` | Blockers before first call, "ours" vs "theirs" |
| `.../profile`, `lead-details`, `feature-flags`, `llm-model`, `call-handling`, `lifecycle`, `closure`, `activity`, `members`, `invitations`, `dnd-scrub`, `campaign-setup`, `agents`, `agents/[agentId]/prompt` | `tenants/[tenantId]/*` | Per-client settings, audit activity, agent prompt view |

### 1.2 Jobs and data paths in scope

| Path | Where | What |
|---|---|---|
| Client taps "Need more? Ask us" | `tenancy/call_line_requests.py` | One open request per client (partial unique index), operator notice via outbox job `notify_call_lines_request` |
| Bell lists open requests | `admin/layout.tsx:398-460`, `GET /v1/admin/call-line-requests` | One row per client linking to `?focus=call-lines` |
| Operator raises lines | `tenancy/call_lines.set_call_lines` | Updates `organizations.call_lines`, closes the request in the same transaction, queues `sync_engine_call_lines` |
| Engine cap sync | `workers/engine_workspaces.py:439-473` | Sets ThinnestAI `allottedCallLines`; daily sweep repairs drift (log only) |
| Campaign pacing | `workers/campaign_dispatch.py:9, 388, 693-695` | Outbound pool from `thinnest_max_concurrent_calls`, per-tenant `concurrency_ceiling` clamped by call lines |
| Dead-letter replay | `ops/routes.py`, `reliability/service.replay_dead_letters:1111` | Counts by job; resend failed rows |
| Live apply of console changes | `ops/live_apply_routes.py`, `LiveApplyStatus.tsx` | "Applied to N of M live agents" |
| Client health walk | `admin/health.py:711-760` | Enters every tenant's own RLS session per request |
| Business copy refresh | `admin/business_copy_routes.py` | GET + POST refresh only; capability profile has no override |
| Admin Pip tools | `copilot/admin_tools.py`, `admin_actions.py` | 14 reads, 8 actions (halt, KYC review, workspace provision, number release, voice set, healer retry/resolve/attest rate) |

## 2. Findings

Severity: P0 money/law/data or core flow broken for a client; P1 wrong or broken with a workaround;
P2 confusing/ugly/slow; P3 polish. There is **no P0** I could prove.

| ID | Sev | Where | What happens (observed) | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| A7-01 | P1 | `admin/tenants/[tenantId]/accountFacts.ts:226-230`; `HealthSummary.tsx:62-63`; api `billing/wallet_routes.py:112` | The client overview reads the wallet through the view-as session (`GET /v1/billing/wallet`), but that route is `realm="client"` and refuses view-as with 403 `impersonation_not_available_here` (`core/auth.py:896-905`). So the overview's "Credit" and "Trial and payment" facts and the health summary's credit check can never be read for any client. | Read the wallet from an admin-realm route (the Credits page's source) so the overview can state credit and runway. | `_admin_tenants_T-api.json`: `GET /v1/billing/wallet` 403 | 6 (truthful UI), operator cannot see why calls stopped |
| A7-02 | P1 | `api/ops/alerts_service.py:107` vs open counts; `AlertsScreen.tsx:276-295` | Alerts at the default 7-day window: "14 alarms of the emailed kind are still happening with no email sent. Check the rows marked 'not sent' below", counts Emailed 14 / Needs a look 27 / Noted 6, and then "No alarms in this window". The list filters `last_seen_at >= now() - days` while the open counts are not windowed, so an open alarm last seen before the window is counted but cannot be found. | Open (uncleared) alarms always listed, whatever the window; the window only limits cleared ones. | `_admin_ops_alerts-1440.png/.txt`; API `{"episodes":[],"open_by_severity":{"attention":27,"page":14,"record":6}}`; at `days=30` the 14 page alarms appear (all last seen 10 Oct). Local cause for the alarms staying open: no worker clears them. | 6 |
| A7-03 | P1 | `admin/ops/OpsStatusStrip.tsx:61-73`; `api/ops/routes.py` (dead-letter read) | The Ops strip shows green "Stuck messages 0" and green "Live agents 0 drifted". Locally 23,844 outbox messages have been pending since 10 Oct (nothing delivered) and 70 live agents are "Not yet checked" ("The counts below are not evidence yet", same page). "Stuck" counts only `failed` rows; a stalled queue with nothing failed reads healthy, and "0 drifted" is shown green with zero agents checked. | Strip shows queue age (oldest pending) and turns warn when the outbox is not draining; drift shows "Not checked" (unknown tone) when `not_yet_checked == live`. | `_admin_ops-1440.png`, `_admin_ops-1440.txt`; `select min(created_at) from outbox_messages where status='pending'` = 2026-10-10. Local cause: no worker. | 6 |
| A7-04 | P1 | `admin/ops/OutboxReplayPanel.tsx:226-314`; `reliability/service.py` | "See why a job failed" is not possible from the console: the dead-letter panel shows only job name and count; `outbox_messages.last_error` (already sanitised, `reliability/service.py:813-829`) is never served. Job names are raw (`sync_engine_call_lines`). An operator must replay blind. | Per job: last error (sanitised), oldest age, and a plain job label; replay one job at a time from there. | Code read; `grep last_error` finds no route or screen reading it | Operator cannot fix what a client asks |
| A7-05 | P1 | `api/ops/config_catalog.py:435-441`; `calevate_shared/config.py:601` | Setting "Simultaneous calls on the ThinnestAI workspace": default **5**, description "5 on pay-as-you-go, 10 on Pro". ThinnestAI raised our PAYG account to **20** concurrent on 23 Oct 2026 (VENDOR-STATED, `docs/vendor/thinnest-replies-2026-10-12.md` line 2235 "concurrent calls (now 20)"; later "already increased", figures UNKNOWN, line 2293). The value feeds the outbound pool (`engine/dial_lines.py:87`, `campaign_dispatch.py:9`). The description steers an operator to a stale ceiling. Live production value NOT CHECKED. | Description names no vendor figure that can expire, or names the current one with its source and date; operator sets the attested ceiling. | Code + vendor reply file | 6, hard rule 11 |
| A7-06 | P1 | `tenancy/call_lines.py:109-150`; `call_line_requests.close_on_raise`; `workers/engine_workspaces.py:458-473` | Raising a client's calls at once closes its request (the client's bell says it was done) in the same transaction as the DB change, before `allottedCallLines` reaches ThinnestAI through the outbox. If the sync fails or dead-letters, the client is told "raised" while the engine still caps it, and the operator's panel shows only "Saved" (the response has no sync state). Drift found by the daily sweep is a log line, not an alarm (`engine_workspaces.py:450-453`). | Panel shows "Sent to the voice platform / waiting / failed" from the sync; client notice waits for the read-back or says "being applied"; drift raises an alarm. | Code read (not driven: local API lacks the route) | 6 |
| A7-07 | P2 | `admin/tenants/[tenantId]/BusinessCopyPanel.tsx:73-79`, `CAPABILITY_ROWS` | The tenant overview crashed ("This operator screen stopped") because the business-copy response had no `capabilities` and the panel does `data.capabilities[key]` unguarded. Local cause: API process older than web. But one panel's missing field takes down the whole client screen; web and API deploy separately (hard rule 3 spirit), so a deploy-order skew does the same in production. | Treat a missing profile as "Not judged yet"; give panels their own error boundary. | `_admin_tenants_T-1440.png/.txt`; console `TypeError: Cannot read properties of undefined (reading 'takes_bookings')` at BusinessCopyPanel.tsx | 6 |
| A7-08 | P2 | `BusinessCopyPanel.tsx:84-91`; `admin/business_copy_routes.py` (GET, POST refresh only) | The capability profile (Takes bookings, Health business, ...) is read-only. When the AI judges a business wrongly (the class behind "Main crops grown" on a support agent), an operator can only "Write again at our cost" and hope. | An operator override per capability, audited, that the generator respects. | Code read | 1 (per-business data must be correctable) |
| A7-09 | P2 | `commercials/TermsForm.tsx:48, 60, 106, 204`; `billing/terms.py:204` | Commercials shows "Concurrent calls" default 10, hint "Engine capacity for this account." The engine capacity is the separate **Calls at once** control on Numbers (default 2, `tenancy/call_lines.py:40`), and dispatch takes the smaller (`campaign_dispatch.py:693-695`). Two numbers for one idea; the hint is false. | One control (Calls at once) or relabel the terms field "Most campaign calls at once (capped by Calls at once)". | Code read; `_admin_tenants_T_commercials-1440.txt` | 6, "one way per problem" |
| A7-10 | P2 | `tenancy/models.py:44-45`; `CallLinesPanel.tsx:136-143` | Calls at once accepts 1-50 per client with no reference to the account-wide ceiling (setting default 5; vendor 20). An operator can grant more than the account carries without a warning. | Show the account ceiling and the sum already granted beside the field. | Code read | 6 |
| A7-11 | P2 | `api/ops/config_catalog.py:533-538` vs `config_controls.py:237-239`, `engine/thinnest_customers.py:57-66` | "ThinnestAI plan" description says "3 on pay-as-you-go, 100 on Pro, 1,000 on Scale"; the same row's option hint says "Up to 100 client workspaces" for Pay as you go (raised 23 Oct, §28.1). The row contradicts itself. `calevate_shared/config.py:602-607` comment repeats the stale 3. | Description defers to the option hint (single source `PLAN_CUSTOMER_CAPS`). | Code read | 6, hard rule 11 |
| A7-12 | P2 | `config_catalog.py:268-274` | "ThinnestAI voice band sold as Clear": "Studio band (Pro and above; the default)". Studio band is on our PAYG account since 23 Oct (VENDOR-STATED, §28; CLAUDE.md). | Drop the plan claim or date it. | Code read | hard rule 11 |
| A7-13 | P2 | `config_catalog.py` (all), rendered `/admin/ops/config` | Console settings are not one line: 47 of 143 descriptions exceed 100 characters and 28 exceed 140; the description column is about 530 px, so these wrap to two or three lines (`_admin_ops_config-1440.png`, "Public reply speed page"). Several carry internal notes rather than what the setting does: "Waiting on the founder's decision" (`public_quality_page_enabled`), "(OPERATIONS gate W-6)" (`whatsapp_coexistence_enabled`), "Live at ThinnestAI since 21 Oct 2026" (`thinnest_own_rules`, `thinnest_test_chat_call_mode`); vendor field names in labels: "(full BYOK)", "(ownRules)", "(callInstructions)", "(Test Chat call mode)"; raw values in prose: "production for real verifications; sandbox only with a test account". | One plain line per setting (<= ~100 chars); the second sentence moves behind the existing "Details". | `catalog.txt` (full list with lengths) | 4 |
| A7-14 | P2 | `config_catalog.py` own-model rows; `calevate_shared/config.py` defaults | Defaults contradict each other: "Our language model for agents with none chosen" says "Not 2.5 (Google refuses it to our project)", while `platform_llm_model` and `llm_tier_standard_model` default to `gemini-2.5-flash-lite` (`agents/assist_leg.py:94-97` says that id 404s on our project). The config screen offers both without saying which one is unusable on our key. REPORTED from repo comments; Google behaviour not re-verified this session. | The console marks a model id our key cannot serve, or the defaults agree. | Code read, `catalog.txt` lines 15, 50, 64 | 6, hard rule 11 |
| A7-15 | P2 | `admin/ops/config/LiveApplyStatus.tsx:33-38`; `lib/api/opsLiveApply.ts:46` | "Queued: live agents are about to be updated. Changed: `ai_notice_introduces_agent`, 04 Nov, 09:05 pm" shown with a spinner 22 hours later. The key is raw and no longer exists in code (grep finds it nowhere in `apps/` or `packages/`). "About to" never ages. | Plain label for the change; after a threshold say "Not started after N hours: check the worker" in warn tone. Local cause for the stall: no worker. | `_admin_ops_config-1440.png` | 4, 6 |
| A7-16 | P2 | `admin/health.py:711-740` | Client health walks every tenant in its own session per request (1-minute poll). Locally (7,704 tenants) it returned 500 `TimeoutError` (pool) after 107 s; the screen showed "Loading…". The module already logs `client_health_walk_over_budget` at 5 s and names the fix (materialise). Production tenant count is small today; the design does not scale and fails as a 500. | Materialised health table refreshed by a job; screen reads it. | `curl /v1/admin/client-health` 500 in 106.7 s, trace `9303bcf539434c3fa185d089f1755fe8`, frame `admin/health.py:738` -> `db/session.py:554` | 6 |
| A7-17 | P2 | `admin/tenants/[tenantId]/readiness/ReadinessScreen.tsx` | "Ours to clear: Campaigns waiting on a DND scrub ... The check is made by a registered telemarketer on an access provider's DLT platform". D-692 records that Calevate is not a registered telemarketer and that whether promotional voice can go out without one is open for counsel (`docs/ROADMAP.md:929`). The screen tells the operator it is theirs to clear with a "Record the scrub" button while no operator can honestly perform that check. | Mark it "Blocked: needs a telemarketer (open legal question)", not "ours to clear"; or hide promotional until counsel answers. | `_admin_tenants_T_readiness-1440.txt` | 6, law |
| A7-18 | P2 | `admin/tenants/[tenantId]/TenantShell.tsx:138-142`; `components/admin/credit.tsx`; `admin/service.py:1268-1289` | Header reads "Credit left Clear 0 min · Studio 0 min ₹5,000.00" in warn tone. Minutes come from credit lots; a balance not held in a lot shows ₹5,000 and 0 minutes together. Seeded data (`SEED_OPENING_CREDIT_INR` with no lot); whether production can hold a balance outside lots is UNVERIFIED. | Minutes and balance agree, or the screen says "₹5,000 not yet in a pack". | `_admin_tenants_T_numbers-1440.txt`; API `credit_inr":"5000.00","minutes_left":[...0,...0]` | 6 |
| A7-19 | P2 | `copilot/admin_tools.py`, `admin_actions.py` | Admin Pip has no read of open call-line requests, no raise/decline action, and no dead-letter detail. An operator asking Pip "who asked for more lines?" or "why did that job fail?" gets nothing. | Add `admin_call_line_requests` read and a confirm-gated `admin_set_call_lines` action; DLQ detail read. | Code read (tool list) | Operator cannot act from Pip |
| A7-20 | P2 | `authn/service.py:22-30`, D-170 | The admin second factor is an emailed code only. NIST SP 800-63B rev 4 §3.1.3.1: "Email SHALL NOT be used for out-of-band authentication"; §2.2.2: verifiers SHALL offer a phishing-resistant option at AAL2. The repo records the cost honestly (D-170); this is a known-risk decision, listed so phase 2 can weigh a passkey for the cross-tenant admin realm. | Offer a passkey (WebAuthn) for operators; keep email as fallback. | https://pages.nist.gov/800-63-4/sp800-63b.html read 5 Nov 2026 | Security standard |
| A7-21 | P2 | `/admin/kyc-reviews`; bell `layout.tsx:396` | Identity review queue took 26 s locally (7.7k tenants) and the page showed "Loading…" at 6 s. The bell loads this queue on every admin page. Local data volume; production unknown. | Queue reads only waiting records with an index; bell uses a count. | `curl /v1/admin/kyc/reviews` 200 in 26.4 s | 2-ish (slow) |
| A7-22 | P3 | `readiness/ReadinessScreen.tsx`, `kyc/KycRecordForm.tsx` | Raw codes on screen: `national_dnd_scrub_missing`, `kyc_missing`, `outbound_pledge_missing`, `agreements_not_accepted`; KYC status options printed as `not_started — ...`, `in_review — ...`. | Plain labels; codes behind "Details". | `_admin_tenants_T_readiness-1440.txt`, `_admin_tenants_T_kyc-1440.txt` | 4 |
| A7-23 | P3 | `config_catalog.py:396-399` (and reply-time, hot-facts rows) | Platform-wide settings (reply targets, public reply speed page, facts known by heart) are filed under the "ThinnestAI" subheading and appear there even on the test engine. | Own subsection ("Call quality"). | `_admin_ops_config-1440.png` | 4 |
| A7-24 | P3 | `admin/ops/RateCardPanel.tsx:493` | "deliberately frozen at ₹95 to the dollar" typed in the UI, while the refusal floor beside it is served by the API. A second spelling of a money fact. | Serve the frozen rate with the floor. | Code read | hard rule 7 spirit, one source |
| A7-25 | P3 | `numbers/CallLinesPanel.tsx:67, 92` | Section "Calls at once" holds a row also labelled "Calls at once" (doubled heading at 375 px). | Row label "Limit". | `_admin_tenants_T_numbers-375.png` | 4 |
| A7-27 | P3 | `admin/page.tsx` (directory table, filter chips) | At 375 px the client list is a sideways-scrolling table: "Credit left" and "Last call" (the columns that answer "why did their calls stop") sit off-screen, and the state and account-type chip rows run past the edge. No page-level overflow. | Stack each client as a card on narrow screens with credit left visible. | `_admin-375.png`, `_admin-375.txt` overflow list | 5 |
| A7-26 | P3 | `config_catalog.py` `healer_founder_whatsapp`, `whatsapp_template_healer_page` | "E.164 number", "pages the founder": internal format and a person instead of a role. | "WhatsApp number for alarm pages (with +91)". | `catalog.txt` | 4 |

Checked and clean (no finding):

- **Business-specific words** in admin web and backend (`clinic|patient|doctor|real estate|farm|crop|rytu|salon|bhk|plot`): only the business-type list (owned by the lead-details lane), a historical note in `admin/business_type.py:5`, and `PatientCallerRow` (a caller-pace preset, not health). Admin Pip prompt has one example, an alarm code. Clean.
- **Masking**: KYC owner ID shown masked (`KycReviewPanel.tsx:74`); QA review uses the redacted transcript and refuses rather than blank (`QaReviewScreen.tsx:47-49,163`); dead-letter panel serves counts and job names only, never payloads (`ops/routes.py:190-195`). Admin Pip is unmasked by design (D-788).
- **Mobile 375 px**: no page-level horizontal overflow on any of the 22 routes crawled
  (`scrollWidth == clientWidth`); the client directory scrolls inside its own region (A7-27).
- **Failed reads**: health board says "we cannot say whether any client is in trouble" on error (`health/page.tsx:176-196`); the bell says "we could not read every queue" (`layout.tsx:420-440`); the alert board explains an empty board.
- **Call-lines bell**: one row per client, links to the control at the number asked; decline takes a reason the client reads (code read).

## 3. Research notes

- **Operator MFA**: NIST SP 800-63B rev 4 (read 5 Nov 2026, https://pages.nist.gov/800-63-4/sp800-63b.html):
  §3.1.3.1 "Email SHALL NOT be used for out-of-band authentication"; §2.2.2 verifiers "SHALL offer at
  least one phishing-resistant authentication option at AAL2". Changes A7-20: a passkey option for
  the admin realm is the standard fix; D-170's emailed code can stay as fallback.
- **Quota-increase requests**: the code cites AWS Service Quotas (request PENDING until APPROVED or
  DENIED). In that model the request is APPROVED when the quota is applied, not when it is decided;
  that is the shape A7-06 asks for (close on the engine's read-back). I did not re-read the AWS page
  this session; the pattern claim is the repo's (`tenancy/call_line_requests.py:3-8`), REPORTED.
- **Status pages / health strips**: an unknown is not a pass (the repo's own rule, `OpsStatusStrip`
  already has an "Unknown" tone). A7-03 is the repo applying its own rule inconsistently; no external
  source needed.

## 4. Proposed fixes, grouped so lanes do not collide

**Group 1: tenant overview truth** (A7-01, A7-07, A7-18)
Files: `apps/web/src/app/admin/tenants/[tenantId]/accountFacts.ts`, `HealthSummary.tsx`,
`BusinessCopyPanel.tsx`, `TenantDetail.tsx` (panel boundaries), `apps/api/admin/routes.py` (an
admin-realm wallet summary if the Credits page's source is not reusable), `apps/api/admin/service.py`
(`_directory_credit`), `apps/web/src/components/admin/credit.tsx`.

**Group 2: ops board truth and dead letters** (A7-02, A7-03, A7-04, A7-15)
Files: `apps/api/ops/alerts_service.py` (open alarms outside the window), `AlertsScreen.tsx`,
`apps/api/ops/routes.py` + `apps/api/reliability/service.py` (oldest pending age, per-job last error),
`OpsStatusStrip.tsx`, `OutboxReplayPanel.tsx`, `EngineDriftPanel.tsx`, `LiveApplyStatus.tsx`,
`apps/web/src/lib/api/opsLiveApply.ts`, `apps/api/ops/live_apply_routes.py` (reason labels).

**Group 3: calls at once, end to end** (A7-06, A7-09, A7-10, A7-19 call-lines half)
Files: `apps/api/tenancy/call_lines.py`, `call_line_requests.py`, `call_lines_routes.py`,
`apps/workers/engine_workspaces.py` (sync result recorded, drift alarm), `CallLinesPanel.tsx`,
`commercials/TermsForm.tsx`, `CommercialsScreen.tsx`, `apps/api/billing/terms.py` (label only, or
retire `concurrency_ceiling` as an operator field with a two-step deprecation per hard rule 8),
`apps/api/copilot/admin_tools.py`, `admin_actions.py`. Needs a migration only if sync state is stored.

**Group 4: console settings catalogue** (A7-05, A7-11, A7-12, A7-13, A7-14, A7-23, A7-26)
Files: `apps/api/ops/config_catalog.py` (descriptions, subsections), `packages/shared/src/calevate_shared/config.py`
(comments; `thinnest_max_concurrent_calls` default only after the founder attests the current ceiling),
`apps/api/ops/config_controls.py`. Test: `tests/ops_config_catalog_test.py` could assert a length cap.

**Group 5: capability override** (A7-08)
Files: `apps/api/admin/business_copy_routes.py`, the business-copy service and its prompt input,
`BusinessCopyPanel.tsx`, migration for an override column. Coordinate with the lane that owns
`GeneratedCopy` and lead-detail suggestions.

**Group 6: readiness and KYC wording** (A7-17, A7-22, A7-25)
Files: `readiness/ReadinessScreen.tsx`, the readiness blocker source in `apps/api/campaigns/service.py`
/ `compliance/preference_scrub.py` (owner flag "needs telemarketer"), `kyc/KycRecordForm.tsx`,
`CallLinesPanel.tsx`.

**Group 7: scale of per-tenant walks** (A7-16, A7-21)
Files: `apps/api/admin/health.py` (materialise), `apps/api/compliance/kyc_admin_routes.py`,
`apps/web/src/app/admin/layout.tsx` (bell uses counts).

**Group 8: admin second factor** (A7-20) — founder decision first (D-170 is his); then
`apps/api/authn/` and the admin sign-in pages.

Environment notes for phase 2 (not code findings): the local API container must be restarted and
migrated to head (`e3b8d1f6a924`) before the call-lines flow can be driven; a local worker is needed to
judge outbox, live-apply and alarm clearing in the browser.
