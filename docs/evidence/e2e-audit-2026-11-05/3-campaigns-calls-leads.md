# Lane 3: campaigns, calls, leads (client realm), phase 1 audit, 5 Nov 2026

Scope: Dashboard, Needs attention, Campaigns (list, wizard, launch gate, run, pause/stop),
dispatch (read-only), Call logs and call detail, Leads and lead detail, Follow-ups and
Call-backs (as they touch leads), Performance, notifications bell, Do not call, Messaging
consent, Leads & hours.

How it was checked: code read (file:line below); the real app driven headless against
`localhost:3000` / `localhost:8000`, account `sunrise-homes`, owner session, browser zone set
to `America/New_York` on purpose so any screen leaning on the viewer's zone would show it;
read-only SQL against the dev database `calevate` to confirm what the screens should say.
Screenshots and page text: `C:/Users/jumes/AppData/Local/Temp/claude/a50a3f0a872c1724/0c51a750-0b23-4950-961e-84972febca40/scratchpad/audit/3-campaigns-calls-leads/`
(`<route>-1440.png|txt`, `<route>-375.png|txt`, `<route>-api.json` = GET responses seen,
`home-*.png`, `attention-1440.*`, `wiz-*` = new-campaign wizard walk, `dbg.cjs` = console
capture). No code changed.

Seed facts the screens were compared against (SQL, 5 Nov 2026): 6 calls (0 test calls), all
`completed`; 6 lead rows: new 1, contacted 2, interested 1, hot 1, won 1 (3 in the lead band);
5 draft campaigns; the only agent is `draft`, `inbound`.

## What I could not check, and why

- **Call detail rendered nothing usable**: both call-detail pages crash to "This screen
  stopped" (`_calls_01a1aad8-*-1440.png`). Cause (console, `dbg.cjs`): `TypeError ... reading
  'map'` at `calls/[callId]/CapturedDetails.tsx:34` because the API response has no
  `unclear_fields`. The API container (`calevate-ui-check-api`) started 08:35 UTC; the commit
  that added `unclear_fields` (`d7125ac8e`) is 09:22 UTC, and the container does not reload.
  So this is an environment skew, not proof of a production defect. The transcript, summary,
  verdict, mistakes, recording and raw-transcript gate were therefore reviewed in code only.
  Restarting the API was out of bounds (shared by other lanes).
- **Running / paused / completed campaign views**: no campaign can launch on this account
  (agent inbound and draft, KYC, pledge, terms), so the run view, pause/stop and results were
  read in code, not seen.
- **Notifications bell at 375 px** showed no unread dot in one capture (`home-375.png`) while
  1440 px showed "1"; not re-run, UNVERIFIED.
- The API returned bursts of `429 rate_limited` during the crawl (other lanes share it,
  `_calls_*-api.json`); every screen except call detail recovered on retry. Not a finding.

## 1. Map

| What | Where (file) | What it is for |
|---|---|---|
| Dashboard screen | `apps/web/src/app/c/[slug]/DashboardScreen.tsx`, `page.tsx` | Home: week figures, actions, next steps, agents, charts, money, latest calls |
| This week band + actions | `WeekRecap.tsx` (`WEEK_KEYS` calls, answer rate, new leads, avg length) | Reads `/v1/analytics/stats` (IST days, test calls INCLUDED by default) and `/v1/dashboard` (`calls_7d`, rolling 168 h) |
| Stat labels/hints | `analyticsFigures.ts` | "New leads" = interested/hot/won |
| Next steps | `NextSteps.tsx`, `SetupChecklist.tsx` | Setup checklist, hot leads waiting |
| Your agents | `AgentsAtAGlance.tsx` | Per-agent last call, status |
| Calls each day / How calls ended / How callers sounded | `DailyCalls.tsx`, `OutcomeSplit.tsx`, `SentimentSplit.tsx` | From `/v1/dashboard` (`daily_7d`, outcome, sentiment; rolling 7 days) |
| Credit and spend | `CallingCreditTile.tsx`, `SpendThisMonth.tsx`, `CostPerLead.tsx`, `moneyRow.tsx` | Wallet minutes/rupees; month spend; cost per lead (7 IST days, `/v1/analytics/cost-per-result`) |
| Daily summary offer | `DailySummaryOffer.tsx` | Turns on the evening summary |
| Latest calls | `LatestCalls.tsx` | Last calls list |
| Dashboard API | `apps/api/crm/service.py` ~2840-3010 (`since_7d = now - 7 days`) | Counts, `leads_new_7d`, `hot_leads_open`, `daily_7d` |
| Stats API | `apps/api/analytics/service.py` (`_CALLS_IN_RANGE`, `_LEADS_IN_RANGE`, `stats`) | IST-day windows, optional test-call filter (calls only) |
| Cost per result API | `apps/api/analytics/proof.py:286-420` | Spend / answered (no test calls) / leads (test calls not excluded) / goals |
| Lead definition | `apps/api/crm/lead_definition.py` (`LEAD_BAND`, `BECAME_LEADS_SQL`) | The one definition of a lead |
| Needs attention | `attention/page.tsx`, `attention/rows.tsx`; API `apps/api/crm/attention.py` | Queue of things to act on; bell reads the same (`/v1/notifications`) |
| Campaigns list | `campaigns/CampaignsListScreen.tsx` | List, tabs, per-row consent-source blocker only |
| New campaign wizard | `campaigns/NewCampaignFlow.tsx`, `NewCampaignSteps.tsx`, `campaignForm.ts`, `choices.tsx`, `contactList.ts`, `ConsentProvenance.tsx`, `LeadPicker.tsx`, `ScheduleFields.tsx` | 4 steps: what it's for, who to call (CSV/paste/leads + list source), when, review |
| Launch gate UI | `campaigns/LaunchGate.tsx`, `blockerCopy.tsx`, `LaunchConfirm.tsx` | Renders server blockers by rule, owner, fix link |
| Campaign detail / run / results | `campaigns/CampaignScreen.tsx`, `CampaignRun.tsx`, `CampaignResults.tsx`, `ContactResults.tsx`, `CampaignStateNotice.tsx`, `CampaignHeaderActions.tsx`, `CampaignTimeline.tsx` | Detail, progress, pause/resume/stop, results |
| Launch gate API | `apps/api/campaigns/service.py:1218` `launch_blockers`, `:1400` `launch_campaign`; routes `campaigns/routes.py:1016,1037` | Exhaustive blockers then DNC scrub then CAS to running |
| Scheduled start | `apps/api/campaigns/scheduling.py:887-898` | Calls `launch_campaign` (same gate) |
| Resume / credit resume | `campaigns/routes.py:1324`, `campaigns/controls.py:525` | No launch gate; dial-time gate still applies |
| Dispatch tick | `apps/workers/campaign_dispatch.py` (big red switch `:1010`, `check_dispatch` `:1019`) | Per-contact gate, then dial |
| Per-dial gate | `apps/api/compliance/service.py` (09:00-21:00 IST, DNC uncached per contact) | Hard rule 5 enforcement |
| Call logs | `calls/CallsScreen.tsx`, `callColumns.tsx`, `CallsPhoneList.tsx`, `CallAgain.tsx` | Filters, export, saved views, list |
| Call detail | `calls/[callId]/*` (`CallDetailScreen`, `TranscriptCard`, `transcriptAccess`, `RecordingCard`, `CallVerdict`, `CallMistakesCard`, `CapturedDetails`, `InsightsCard`, `CallBackAction`) | Transcript (redacted by default), summary, verdict, next step, mistakes, recording |
| Call detail API | `apps/api/crm/service.py:590-680` (`column = "text" if raw else "text_redacted"`), raw route `crm/routes.py:420-442` (`calls:read_raw` + audit) | Hard rule 5 |
| Leads list | `leads/LeadsScreen.tsx`, `LeadsToolbar.tsx`, `LeadsFooter.tsx`, `LeadTable.tsx`, `LeadsPhoneList.tsx`, `StatusSelect.tsx` | Every contact by status; search; export (`calls:read_raw`) |
| Lead detail | `leads/[leadId]/*` (`LeadCaptured.tsx`) | Captured details, stage, owner, history, call now / call back |
| Lead status writer | `apps/workers/pipeline.py:3254` `_advance_lead_status`, `:3660` | After-call status moves (test calls included) |
| Performance | `performance/PerformanceScreen.tsx`, `PerformanceCharts.tsx`, `Breakdowns.tsx`, `ReplySpeed.tsx`, `copy.ts`; API `apps/api/crm/performance.py`, `analytics/service.py` | Figures, funnel, outcomes, heatmap, durations, periods, who was on the call, reply speed |
| Daily summary | `apps/api/notifications/daily_summary.py` | Evening email/WhatsApp figures |
| Follow-ups | `follow-ups/*`; starters `apps/api/follow_ups/starters.py` | Lead journeys; starters derived from the account's own date fields |
| Call-backs | `callbacks/CallbacksScreen.tsx` | Promised calls, 9am-9pm |
| Do not call | `do-not-call/*`, `copy.ts` | Tenant + platform DNC, opt-in-only switch |
| Messaging consent | `messaging-consent/*` | WhatsApp opt-ins |
| Leads & hours | `lead-sources/*` (`CallingPlan.tsx`, `TestLeadDrawer.tsx`, `sourceKinds.ts`) | Form/ad sources, when new leads are called |

## 2. Findings

Hard rule 5 / compliance gate: **no bypass found.** Every path to `running` either goes
through `launch_campaign` → `launch_blockers` (button `campaigns/routes.py:1037`, schedule
`scheduling.py:898`) or is a resume (`routes.py:1324`, `controls.py:536`) that is still held by
the per-contact `check_dispatch` (`campaign_dispatch.py:1019`) plus the big-red-switch read
(`:1010`). The wizard hides Promotional unless open (`choices.tsx:118`) and refuses Next until
the list source is answered (`wiz-3-375.png`: "Answer both questions about your list."). The
launch screen listed 5 and 7 blockers on the two drafts (`_campaigns_01a1aad9-*-1440.png`).
Raw transcript is `calls:read_raw` + audit (`crm/routes.py:420-442`); default read is
`text_redacted` (`crm/service.py:614`). IST: every time seen rendered in IST under a
New-York browser (e.g. campaign `created_at 09:10 UTC` shown "05 Nov, 02:40 pm").

| ID | Sev | Where | What happens (observed) | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| L3-01 | P1 | Leads screen header and footer, `leads/LeadsFooter.tsx:42`, `LeadsToolbar` count | Leads page says "6 leads" / "Showing 6 of 6 leads"; dashboard says "New leads 3". The 6 includes New and Contacted rows, which `crm/lead_definition.py:1-8` says are people, not leads ("one that means everyone says people"). Same thing counted two ways. | Count says "6 people" (or "6 contacts"); "leads" only for the interested/hot/won band. Export copy (`LeadsScreen.tsx:222`) the same. | `_leads-1440.png`, `home-1440.png`, SQL counts above | Numbers agree; lead definition |
| L3-02 | P1 | `apps/api/crm/lead_definition.py:39-47` (`BECAME_LEADS_SQL`), used by `analytics/proof.py:347`, `analytics/service.py:99`, `notifications/daily_summary.py:105`, `crm/service.py:2964` | A test call's lead moves into the band like a real one (`workers/pipeline.py:3660-3667` calls `_advance_lead_status` with no test-call check; lead `source='test_call'` exists, `pipeline.py:3593`). Lead counts never exclude test calls, while answered calls do (`proof.py:344`, `daily_summary.py:103`). So the owner's own test calls lower "Cost per lead" on the dashboard, Billing and the daily summary, and the Performance switch "Include my test calls" off still counts their leads. | Lead counts exclude leads whose only band-reaching calls were test calls (join the status_change to a non-test call, or filter `source <> 'test_call'` with the reclassification rule), everywhere `BECAME_LEADS_SQL` is read, and honour `test_calls` in `_LEADS_IN_RANGE`. | code read; Performance toggle `PerformanceScreen.tsx:94,100` | Money figure truthful; one definition |
| L3-03 | P1 | Needs attention `apps/api/crm/attention.py` (kinds at :193-864), bell `/v1/notifications` | Two calls are tagged "Needs you" (a step the business must take, `crm/outcomes.py:13-21`): Anitha, Lakshmi ("asked to be called back after Diwali"). Needs attention and the bell show 1 item, the hot lead only. No `needs_you` source exists. | "Needs you" calls not yet handled appear in Needs attention and the bell, with "Open the call". Workaround today: Call logs filter "Needs you" + "Not handled yet". | `attention-1440.txt`, `_calls-api.json` (`attention.total=1`), `_calls-1440.png` | Truthful UI; core flow |
| L3-04 | P2 | Dashboard and Performance "Answer rate", `crm/performance.py:46` `CONNECTED_SQL`, hint `analyticsFigures.ts:21` | A caller who "hung up during the greeting" (19 s, `hung_up_early`) counts as answered; home shows 100% answer rate with the hint "Calls that reached a real conversation". | Either exclude `hung_up_early` from answered, or change the hint to "Calls someone picked up". Decide once; apply in `CONNECTED_SQL` users (dashboard, proof, daily summary, performance). | `home-1440.txt`, `_performance-1440.txt` ("Answered 6"), SQL call `01a1aad8-e476` | Truthful UI |
| L3-05 | P2 | Home mixes three windows and two test-call rules: `WeekRecap.tsx:73` uses `/v1/dashboard calls_7d` (rolling 168 h, test calls included, `crm/service.py:2870`) to choose figures vs quiet; the band uses `/v1/analytics/stats` (7 IST days, test calls included, `analytics/routes.py:166`); `CostPerLead` uses 7 IST days with test calls excluded from answered calls | Figures under "This week" and "Cost per lead, 7 days" can disagree on the same screen (the band's answered includes test calls, the cost tile's does not). | One window (7 IST days) and one test-call rule for every home figure; say "your test calls are not counted" once. | code read | Numbers agree |
| L3-06 | P2 | Call detail `calls/[callId]/CapturedDetails.tsx:34` (`detail.unclear_fields.map`) | One missing optional field blanks the whole call screen ("This screen stopped"). Seen here because the API process was older than the web; the same happens in any web/api version skew during a deploy. | Read optional arrays defensively (`?? []`) on the call screen, or isolate cards in their own error boundary so the transcript still shows. | `calldetail-1440.png`, console in `dbg.cjs` run | Truthful UI / robustness |
| L3-07 | P2 | Campaign list `CampaignsListScreen.tsx:258,452` | "Six-month check-up reminders" shows no problem in the list, but its page lists 5 launch blockers (agent, inbound only, KYC, pledge, terms). The list only shows the list-source blocker. | List row carries "Can't launch yet: N things to fix" from the same `blockers` the detail uses. | `_campaigns-1440.png` vs `_campaigns_01a1aad9-0c7e-*-1440.png` | Numbers agree; truthful |
| L3-08 | P2 | `blockerCopy.tsx` `national_dnd_scrub_missing` ("Waiting for today's national do-not-disturb check." owner `calevate`, "We handle this") | Shown on the promotional draft. `campaigns/service.py` (comment above `national_dnd_blocker`) says the scrub needs a Registered Telemarketer relationship Calevate does not hold, so promotional outbound does not dial at all today (REPORTED in repo, not re-verified). "We handle this" promises something that is not coming. | For promotional drafts: "Promotional calls are not available yet. Change this to a service call." with a button. | `_campaigns_01a1aad9-0d26-*-1440.txt` | Truthful UI |
| L3-09 | P2 | Launch checklist, KYC and pledge rows (server sentences from `kyc_blocker`, `outbound_pledge_blocker`, no `BLOCKER_COPY` entry by design) | Two 3-line paragraphs ("Indian telecom rules require the subscriber of a phone connection to be verified…"); both rows link "Verify your business". | One short line each ("Verify your business first." / "Accept the no-cold-calls promise.") with the reason behind "Why?", keeping the state the server adds. | `_campaigns_01a1aad9-0c7e-*-1440.png` | Plain language (~60 chars) |
| L3-10 | P2 | Lead detail `leads/[leadId]/LeadCaptured.tsx:35` | Six rows read "Not said", including Name on a lead named Anitha Reddy. The call screen follows the founder's 11 Oct rule (only said details are rows, `CapturedDetails.tsx:10-13`); the lead screen does not. | Same rule as the call screen: said details as rows, the rest as one "Not mentioned" chip line; Name row uses the lead's name. | `_leads_01a1aad8-e425-*-1440.png` | Truthful; one way per problem |
| L3-11 | P2 | Lead detail "No longer asked" rows | Field keys and raw values reach the owner: "Bhk size", "Budget lakhs", value `site_visit`. | Labels from the schema version that captured them; enum values through their option label; never a key. | same screenshot | Plain language (no field keys) |
| L3-12 | P2 | Leads status tabs at 375 px (`LeadsScreen` segmented control) | Only All / New / part of "Contacted 2" are visible; Interested, Hot, Won, Lost are off-screen with no scroll cue (control is 823 px wide in a 375 px view). | Wrap, or a select on phones, or a visible scroll edge. | `_leads-375.png`, overflow list in `_leads-375.txt` | Mobile 375 px |
| L3-13 | P2 | Leads & hours `lead-sources/*` | Each source shows internal ids: "7b900996 · key ···fce98c4f". A source reads "Receiving: On" while "Called by: Nobody yet", with nothing saying its leads will not be called. | Hide ids behind "Details"; when no agent calls a receiving source, say "Leads arrive but nobody calls them. Choose an agent." | `_lead-sources-1440.txt` | Plain language; truthful |
| L3-14 | P2 | Performance "How fast your agent answered" `performance/ReplySpeed.tsx` | Heading values say "this week" and the table is a fixed 4 weeks while the page range is 7 Oct to 5 Nov and the test-call switch is on; "Slow wait this week: Too few calls" sits over "1 call in 10 waited longer" with 0 calls timed. | Follow the page range, or say plainly "Last 4 weeks, not the dates above"; drop the "1 call in 10" line when nothing was timed. | `_performance-1440.png` | Truthful; numbers agree |
| L3-15 | P2 | Dashboard credit tile `CallingCreditTile.tsx:78-90` | "Calling credit left: No minutes left · Healthy · ₹5,000 in your account" and an "Add credit" home action. Cause here: the seed writes a ledger top-up with no credit lot (`scripts/seed_dev.py:486`), breaking the lots-equal-balance invariant (`billing/lots.py` `_CLOSE_LOT` comment). The tile still lets the status word and the minutes contradict. | Tile: status word from the same fact as the headline (0 minutes is not "Healthy"); log a mismatch between lot sum and balance. Seed: open a lot (billing lane). | `home-1440.png`, wallet JSON in `_calls_*-api.json` | Truthful UI |
| L3-16 | P2 | Performance "Who was on the call" `performance/Breakdowns.tsx:180` (`testCalls: false`) | Ignores the page's "Include my test calls" switch (always off), so with the switch on, this panel and the rest of the page count different calls. It says so in its note. | Follow the switch, or move the switch so it visibly does not cover this panel. | code; `_performance-1440.txt` | Numbers agree |
| L3-17 | P3 | Performance glance vs reply speed | Same average shown as "1:56" and "116 s" on one screen. | One format (`formatDuration`). | `_performance-1440.png` | Consistency |
| L3-18 | P3 | Home "Your agents" vs "Latest calls" | Same last call shown as "05 Nov, 01:32 pm" (end) and "05 Nov, 01:30 pm" (start). | Use the start time in both. | `home-1440.txt` | Numbers agree |
| L3-19 | P3 | Hot lead definition | `analytics/service.py:85` `HOT_STATUSES = ("hot","won")`; dashboard `hot_leads_open`, daily summary and campaign results count `hot` only. | One definition (hot only, or name the other "hot or won"). | code | One definition |
| L3-20 | P3 | Calls window column | `crm/performance.py:86` windows calls by `created_at`; `analytics/service.py:92` and dashboard by `started_at`. Two Performance panels can differ by calls created before midnight and started after. | `started_at` everywhere. | code | Numbers agree |
| L3-21 | P3 | Performance funnel "Interested" (`performance.py` `qualified`: leads with a connected call in range) vs band "New leads" (became a lead in range) | Equal here (3 and 3), but different definitions sit on one page under near-identical names. | Rename funnel step "Became interested" and use `became_lead_at`, or explain behind ⓘ. | code; `_performance-1440.txt` | Lead definition |
| L3-22 | P3 | `campaigns/contactList.ts:267-271` `SAMPLE_CSV` | Sample file column `booking_time` with "Tuesday 4pm": booking-shaped for every business. | A neutral extra column or one from the account's own lead details. | code | Nothing hardcoded per business |
| L3-23 | P3 | Leads & hours "When to call 09:00–21:00" vs everywhere else "9am to 9pm" | Two time styles. | "9am to 9pm". | `_lead-sources-1440.txt` vs `NewCampaignSteps.tsx:534` | Consistency |
| L3-24 | P3 | Messaging consent "Opt-ins last 365 days. Your evidence, not a DLT record." | "DLT" is jargon to an owner. | Drop it or put it behind "Why?". | `_messaging-consent-1440.png` | Plain language |
| L3-25 | P3 | `calls/[callId]/TranscriptCard.tsx:302` | "This call is older than English reviews." | "English is not available for older calls." | code | Plain language |
| L3-26 | P3 | Lead detail History | "0 entries, Nothing has happened yet" on a lead with 1 call and a status "Set after a call". Seed writes no `lead_events`; the pipeline does (`pipeline.py:3633-3645`). UNVERIFIED for production. | Confirm with a real pipeline lead; if any path skips the event, History must still show the call. | `_leads_01a1aad8-e425-*-1440.png` | Truthful (unverified) |
| L3-27 | P3 | Dev seed `scripts/seed_dev.py` | Real-estate account seeded with dental campaigns ("Six-month check-up reminders", "Whitening enquiry follow-up"). Dev-only, but it is what every reviewer looks at. | Neutral or real-estate names. | `_campaigns-1440.png` | Nothing hardcoded per business |
| L3-28 | P3 | `performance/ReplySpeed.tsx:21-26` | Own date formatter beside `istDayLabel` (`analyticsFigures.ts:28`). | Use the shared one. | code | One way per problem |

Counts: **P0 0, P1 3, P2 13, P3 12.**

Out of lane, noticed in passing: `components/patientCallerRow.tsx` (clinic word "patient" in
a shared agent-settings component, used by `agents/panels/callHandling.tsx:121`); `lib/
verticalExamples.ts` holds eight per-vertical example rows as the fallback before AI copy
lands (leads search placeholder "3BHK in Gachibowli" here). For the agents / onboarding lanes.

## 3. Research notes

- Calling window. The code enforces 09:00-21:00 IST (`compliance/service.py:27,192`, citing
  SEC-COMP §2.5 and TRAI's 12 Feb 2025 amendment). I did not re-verify this window this
  session: a search found TRAI's press release on the second TCCCPR amendment
  (https://cms.trai.gov.in/sites/default/files/2025-02/PR_No.11of2025.pdf, 12 Feb 2025) but
  not the window text; one vendor blog claims 10:00-21:00 for SMS "Service Explicit" from
  28 Oct 2025, which is about SMS, single-source and UNVERIFIED. No fix in this file depends
  on it; route to counsel/OPERATIONS if anyone wants to change the window.
- Answer-rate definition (L3-04): no regulation involved; it is a product definition, and
  the fix is to make the label say what the number counts.
- Cost per lead (L3-02): `lead_definition.py` already cites the ad-platform convention
  (spend over leads submitted); test calls are not leads under that convention either, so the
  fix follows the repo's own stated standard.

## 4. Proposed fixes, grouped so lanes do not collide

**A. Lead counting (backend)**: L3-02, L3-19, L3-20, L3-21. Files: `apps/api/crm/lead_definition.py`,
`apps/api/analytics/service.py`, `apps/api/analytics/proof.py`, `apps/api/crm/performance.py`,
`apps/api/notifications/daily_summary.py`, `apps/api/crm/service.py` (dashboard block),
`apps/api/campaigns/results.py`; tests beside each.

**B. Home figures (web + dashboard API)**: L3-04, L3-05, L3-15 (tile half), L3-18. Files:
`apps/web/src/app/c/[slug]/WeekRecap.tsx`, `DashboardScreen.tsx`, `analyticsFigures.ts`,
`CallingCreditTile.tsx`, `AgentsAtAGlance.tsx`, `apps/api/crm/service.py` (window), and the
`CONNECTED_SQL` decision in `apps/api/crm/performance.py` (coordinate with A).

**C. Needs attention**: L3-03. Files: `apps/api/crm/attention.py`, `apps/web/src/app/c/[slug]/attention/rows.tsx`, notifications source if separate.

**D. Leads screens**: L3-01, L3-10, L3-11, L3-12, L3-26. Files: `apps/web/src/app/c/[slug]/leads/LeadsFooter.tsx`,
`LeadsToolbar.tsx`, `LeadsScreen.tsx`, `[leadId]/LeadCaptured.tsx`, `lib/leadLabels.ts`; API
`GET /v1/leads/{id}/captured` labels if keys come from there.

**E. Campaigns UI**: L3-07, L3-08, L3-09, L3-22. Files: `apps/web/src/app/c/[slug]/campaigns/CampaignsListScreen.tsx`,
`blockerCopy.tsx`, `LaunchGate.tsx`, `contactList.ts`; the list API (`campaigns/routes.py`
summary) to carry the blocker count; the KYC/pledge server sentences in
`apps/api/compliance/*` only if the short line moves server-side.

**F. Call detail robustness and copy**: L3-06, L3-25. Files: `apps/web/src/app/c/[slug]/calls/[callId]/CapturedDetails.tsx`,
`CallDetailScreen.tsx`, `TranscriptCard.tsx`. Then re-run this lane's call-detail check
against a current API (transcript redaction default, raw gate, recording, verdict, mistakes).

**G. Performance**: L3-14, L3-16, L3-17, L3-28. Files: `apps/web/src/app/c/[slug]/performance/ReplySpeed.tsx`,
`Breakdowns.tsx`, `PerformanceScreen.tsx`.

**H. Small copy/settings screens**: L3-13, L3-23, L3-24. Files: `apps/web/src/app/c/[slug]/lead-sources/*`, `messaging-consent/*`.

**I. Dev seed** (billing/dev lane): L3-15 (lot), L3-27. File: `scripts/seed_dev.py`.
