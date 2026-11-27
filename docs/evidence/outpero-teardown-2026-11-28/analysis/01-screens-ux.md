# 01: Client screens and UX flows, Outpero (28 Nov 2026) compared with Calevate 0.5.98

Scope: every client-facing screen and flow. The developer platform is analysed in
`02-api-integrations.md`, call/script quality in `03-ai-quality.md`, money and operations in
`04-business-ops.md`. This file touches those only where a screen is involved, and points to
them instead of repeating them.

Founder rule (memory 729dfe15, 28 Nov 2026): Outpero is evidence of what owners expect, never a
template. Every proposal in §4 is a Calevate design: it starts from our data model (D-997:
the agent is staff; a campaign or an Inbound line is the job and holds the script), our hard
rules and our owner words (PLAN.md §6), not from Outpero's layout.

## 0. Evidence and method

| Source | What it is | Evidence class |
| --- | --- | --- |
| `../screens/app-routes.md` | Outpero app, screen by screen, logged in, 28 Nov 2026 | First-hand observation |
| `../ai-tests.md` | Rehearse, Swara edit, inbound clinic build, 28 Nov 2026 | First-hand observation |
| `../public-site-and-docs.md` | Outpero marketing, docs, API, 28 Nov 2026 | VENDOR-PUBLISHED |
| `../shots/*.jpg` | 31 Outpero screenshots, viewed for this analysis | First-hand |
| `../../outpero-vs-calevate-2026-11-28/LOG.md` + `shots/` | Same agent built on both, 28 Nov 2026 | First-hand |
| `docs/design/redesign-2026-11-28/PLAN.md` | The four redesign lanes now running | Repo plan |
| rememory 04ccf39c, 0425a8ae, a2fe78cd, 79070e65, 729dfe15 | Teardown and decision memories | Repo-internal claims |
| `apps/web/src/app/c/[slug]/**`, `apps/web/src/lib/**`, `apps/api/**` at `rel-0.5.98` (HEAD c34a0434e) | Our side, read and grepped for every row | Code read |

Method for our side: for each Outpero feature I grepped the client realm (and the api where a
screen needs a server read) before writing a verdict. "Not found" below means a grep for the
named terms returned nothing; the terms are given so the next reader can repeat it. Nothing was
run in a browser for this file; verdicts are from code, not from use.

Caveats on the evidence itself:

* **`../shots/01-home-1.jpg` is mislabelled.** It shows Calevate's "What your agents know"
  screen (our sidebar, "Trial 7 days 15 min", "A new version of Calevate…" bar), not Outpero's
  home. `01-home-2.jpg` is Outpero's AI employees list, not its home. The Outpero home card is
  in `01-to-12-core-3.jpg`. Anyone citing "01-home" should use core-3.
* Outpero's account was empty (1 draft employee, 0 calls), so Leads, Conversations,
  Performance and Instant analytics were seen as structure (filters, columns, KPIs) only. No
  claim here is about how Outpero's charts behave with data.
* Verdicts: **BETTER** (ours does more or does it more safely), **PARITY**, **WEAKER** (we have
  it, owners get less from it), **LACK** (not found), **DELIBERATE** (we chose not to, with the
  decision named).

Scoreboard of the 154 rows in §1 (counted from the tables; a row with a mixed verdict such as
"PARITY / LACK" counts under both): BETTER 46 · PARITY 53 · WEAKER 37 · LACK 12 ·
DELIBERATE 3 · not a gap 3.

---

## 1. Screen by screen

### 1.1 Global chrome (sidebar, header, floating help)

| # | Outpero | Calevate (file) | Verdict | Note |
| --- | --- | --- | --- | --- |
| G-1 | Sidebar in 4 short groups (AI employees / Results / Calling / Workspace), ~13 items | `lib/clientNav.ts` (36 items, 5 groups), `ClientSidebar.tsx` | WEAKER | Founder agreed (79070e65). **Lane 4** groups it and adds the trial sidebar. |
| G-2 | Employee list nested under "All employees" in the sidebar | none (Agents is one link) | WEAKER | Small accounts have 1 to 3 agents; jumping straight to one is two clicks for us. See P-27. |
| G-3 | Workspace switcher (business + email) at the top of the sidebar | `app/c/page.tsx` lists the person's workspaces; no in-shell switcher found (grep `AccountSwitcher|Switch account`) | WEAKER | Matters for agencies and multi-branch owners; see P-28. |
| G-4 | Search ⌘K | Admin only: `app/admin/AdminCommandPalette.tsx`; the client realm has none (grep `CommandPalette|⌘K` in `app/c` empty). A ready component exists: `components/interior/command-palette.tsx` | **LACK** | P-02. |
| G-5 | Header "0 on calls · 0.0/min" always shown | `components/console/liveCalls.tsx` `LiveCallsPill` (count, opens the call or the filtered log; hidden at zero; says "couldn't check" on a failed read) | PARITY | Ours does not show the money rate while calls run; see P-29. Hiding at zero is deliberate and fine. |
| G-6 | Notifications bell (alt+T) | `ClientTopHeader.tsx` `NotificationBell` over `/v1/notifications`, unread count, "N things need attention in all", marks seen on close | BETTER | Ours merges the attention queue, announcements and plan events and never draws a failed read as all-clear. |
| G-7 | Credits card pinned at the foot of the sidebar ("50 · 7–10 min of calls · Add credits") | `CreditChip` in the header (`TrialBanner.tsx`, `ClientTopHeader.tsx`), only when low or stopped; `CallingCreditTile.tsx` on the dashboard | PARITY | Ours stays quiet when healthy (one filled action per view). Outpero's "minutes left" translation is worth borrowing into our chip; see P-29. |
| G-8 | "Take the tour" for the whole app | Agent page only: `agents/[agentId]/tour/` (owner-started, `?tour=1`) | WEAKER | P-17. **Lane 4** grows the agent tour to 5 steps; an account-level tour is NEW. |
| G-9 | "Help and docs" link to a 27-topic help centre | No help link in `ClientTopHeader.tsx` or `ClientSidebar.tsx`; Pip (`ClientCopilotDock`) and ⓘ tips are the help | WEAKER | P-16. Pip answering in Telugu is stronger than a docs site; the gap is a human route and a browsable "how it works". |
| G-10 | Floating "Support and feedback" | Not found (grep `Contact support|Send feedback|Report a problem` in `app/c`, `components/copilot`) | **LACK** | P-16. `components/copilot/AnswerRating.tsx` rates Pip answers only. |
| G-11 | Dark theme toggle | Dormant by decision D-471 (light only); PLAN.md §8 | DELIBERATE | Founder 23 Oct 2026: "something light not dark". |
| G-12 | "Prefer the old look? Open the old app" | none | n/a | Not a gap; we migrate rather than keep two apps (quality bar: one way per problem). |
| G-13 | — | `ViewSwitch` (`components/MobilePreview.tsx`): the owner can preview any screen at phone width from a desktop | BETTER | Outpero has nothing like it. |
| G-14 | — | `TrialChip`, `TrialBanner.tsx`, `TrialLockNotice.tsx`: trial days and minutes always visible | BETTER | Outpero shows credits only. |

### 1.2 Home / dashboard

Outpero's home IS the new-employee card plus 14 photo templates (`core-3.jpg`). It shows no
results at all. Ours (`DashboardScreen.tsx`, 443 lines) is a results home.

| # | Outpero | Calevate (file) | Verdict | Note |
| --- | --- | --- | --- | --- |
| H-1 | Results on home | `DashboardScreen.tsx`: `Metric`s, `DailyCalls`, `OutcomeSplit`, `SentimentSplit`, `WeekRecap`, `LatestCalls`, `AgentsAtAGlance`, `PipNotes`, `PinnedCards` | BETTER | Outpero has none on home. Keep. |
| H-2 | — | `NextSteps.tsx`, `SetupChecklist.tsx`, `go-live/GoLiveGuide.tsx` | BETTER | A live checklist of what blocks going live. |
| H-3 | — | `CallingCreditTile`, `SpendThisMonth`, `CostPerLead` | BETTER | Cost per lead on home is unique in this comparison. |
| H-4 | — | `HeldNumberNotice`, `LineNotice`, `ExistingNumberPrompt`, `homeNotices.tsx`, missed calls today (`_ui/copy.ts:26`) | BETTER | Problems surface on home with one button each. |
| H-5 | — | `TrialCallPanel.tsx`, `TestCallStatus.tsx`, `TestCallTranscript.tsx` on home during the trial | BETTER | |
| H-6 | "What should your next AI employee do?" card is the first thing seen, every visit | Only in first run (`agents/first/BriefStep.tsx`) and `agents/new/BuildAgent.tsx` | WEAKER | For an account with no live agent the home should be the brief card; once there is work, results win. P-19. **Lane 1** builds the card; placing it on home is NEW. |
| H-7 | 14 photo trade templates with one-line use cases | AI-written per-business examples (`lib/useVerticalExamples.ts`, D-827) as placeholders; job starters exist for follow-ups (`follow-ups/Starters.tsx`: call new leads, qualify, missed-call call-back, appointment reminder, payment reminder, win back) | WEAKER | Ours is personalised but invisible until you type; theirs is browsable. P-20. |
| H-8 | "Copied a script from another Outpero employee? Paste it here" | Campaign duplicate (`CampaignHeaderActions.tsx`); no paste-a-script import found (grep `paste.*script|import.*script`) | WEAKER | P-21. |
| H-9 | — | `DailySummaryOffer.tsx` offers the evening summary from home | BETTER | |

### 1.3 Agents list

| # | Outpero (`01-home-2.jpg`) | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| A-1 | Card per employee: status pill, role, last active, job chip, voice chip, number chip | `agents/Roster.tsx` row: direction, language, numbers count, own AI model, calls total, last call, `ReadinessScore`, `VoiceTierBadge`, `LiveBadge` | PARITY | Same facts in a denser row. |
| A-2 | Stats on the card: Calls today / Leads / Qualified | Calls total and last call only (`Roster.tsx:243-247`) | WEAKER | An owner opens this list to ask "is it working today?". P-03. |
| A-3 | Chips All / Live / Paused / Draft with counts, job filter, sort, search | Active first, then the rest (`Roster.tsx:97-98`); counts in `agents/page.tsx:72-88`; no search, filter or sort | WEAKER | Matters past ~6 agents. P-03. |
| A-4 | "Test call" and play on every card | Row menu: Open / Open its settings / Delete (`Roster.tsx:258-266`) | WEAKER | P-03. |
| A-5 | Dashed "Hire a new employee — free to build, about 5 minutes" card | New agent button (`agents/page.tsx`) | PARITY | |
| A-6 | — | Delete with consequences stated first; a working agent is offered Switch off instead (`Roster.tsx` `DeleteDialog`) | BETTER | |
| A-7 | — | Readiness score per agent (`agents/AgentReadiness.tsx`) | BETTER | |

### 1.4 Agent page

Outpero: one employee = one job, 8 tabs (Overview · Campaigns · Call script · Training · Actions
· Outcomes · Voice · Settings), `15-employee-tabs-*.jpg`. Ours today: 4 tabs, D-997
(`agents/[agentId]/sections/agentSections.tsx`: Overview · Actions · Settings · Training), the
script lives on the job. **Lane 2** moves to six owner-word tabs (`script, knowledge, actions,
notes, voice, settings`).

| # | Outpero | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| E-1 | Header: status, role · job · voice · credits used; Live/Paused switch; View results; Rehearse; Test call | `sections/agentHeader.tsx`: On/Off switch (trial meaning "on for test calls"), Try it, Put it live, Show me around, this month's charge | PARITY | Lane 2 adds "Calls (n)". |
| E-2 | Overview: amber "listen before you let it loose" card + Going live checklist (3) | `sections/overview.tsx`, `SetupChecklist`, `AgentReadinessPanel`, `PendingBanner` | PARITY | Ours is a checklist with readiness; theirs has a sharper warning sentence. Keep ours; see 03 for the test-call habit. |
| E-3 | Campaigns tab inside the employee | Jobs are separate pages (D-997); Overview says where scripts live (`ScriptsMoved`) | WEAKER | **Lane 2** `script` tab lists the agent's jobs, one row each. |
| E-4 | Call script tab: 8 steps, chars 3,732/40,000, "Telugu enhance", copy/paste JSON, strictness 1–5, end rules, pre-call variables | Campaign / line script editor `agents/[agentId]/script/**` (`ScriptPartsEditor`, `FlowCanvas`, `SmallSteps`, `StepExamplesEditor`, `ScriptSizeMeter`, `ScriptLanguages.tsx`, push-backs, Q&A per step, step outcomes) | BETTER | Branching, step outcomes, push-backs and a size meter go beyond theirs. Builder words are the weakness; **Lane 3** owner words. |
| E-5 | Swara edit: tap and say a change, ~30 s, "updated" tags per step, Undo, "Helpful?" (`ai-tests.md` §2) | Pip proposals with a reviewed diff (`script/PipProposal.tsx`, `ProposalReview.tsx`, `scriptDiff.ts`, `ImprovementReview.tsx`), versions (`campaigns/ScriptVersions.tsx`) | PARITY | Ours shows the diff before applying (safer). Theirs applies then offers Undo (faster). Quality comparison is 03's. |
| E-6 | Rehearse: typed whole call in a side panel beside the script, same script, shows tool calls with reasons, ₹0.20/message | `components/improvement/TryChat.tsx` in the agent's Training tab, "Try it on" a job (`sections/tryOn.tsx`); runs the **published** agent (engine test chat has no draft, VENDOR-STATED 19 Oct 2026, cited in `TryChat.tsx`) | WEAKER | Owners edit on the campaign page and must leave it to try; a draft cannot be tried before it is live. P-14. |
| E-7 | Training: teach by text, photo, voice note; Facts and Rules typed with category; "Where X struggled on real calls"; try-it chat | `knowledge/TeachBox.tsx` (text, mic, photo/file, reviewed before saving), `WhatItKnows.tsx` (pinned facts win), Questions to answer from real calls (`useTeachQuestions`, badge on the tab), `knowledge/BusinessBasics.tsx`, `HowTheySpeak.tsx`, `CallInstructions.tsx` | BETTER | Knowledge belongs to the client and every agent carries it (D-689); theirs is per employee and filed "Hyderabad" as a service area and "9–6" as business timings (`app-routes.md`). |
| E-8 | Actions: Interakt, AiSensy, Meta WhatsApp, Custom API, Google Calendar, Other WhatsApp; API master switch; saved credentials | `agents/actions/**` (`Actions.tsx`, `BookingSetup.tsx`, `ToolDetail.tsx`, `AfterCallMove.tsx`), `integrations/whatsapp/**`, `integrations/ConnectedAccounts.tsx` | PARITY | Breadth comparison of providers belongs to 02. |
| E-9 | Outcomes: 4 labels with long editable definitions; capture fields auto-made per job, typed (Date seen on the clinic build); per-employee webhooks | Per-agent call outcomes drafted for the business, editable (`lib/api/callOutcomes.ts`, `PUT /v1/agents/{id}/call-outcomes`, `apps/api/agents/call_outcomes_routes.py`); what each call writes down per campaign and line (`settings/lead-details/LeadDetailsScreen.tsx`, D-1029); `panels/extractionRow.tsx` | PARITY | Ours lives under Settings → Lead details, not on the agent. **Lane 2** `notes` tab brings it to the agent. |
| E-10 | Voice: primary + "also speaks" 6 languages; ambient presets + volume; filters language / 11 moods / gender; 31 Premium + 23 Standard with ₹/min on each tab; per-voice character notes and badges | `agents/panels/delivery.tsx`, `components/engineCatalogueList.tsx`, `voicePreviewButton.tsx`; background sound row (`components/callHandlingVoiceRows.tsx:588-697`); 3 voices on the trial (LOG C8) | WEAKER | Price per minute: **Lane 4**. Breadth and filters: P-15 (NEW, depends on the admin's catalogue). Contradictory note C8-a: Lane 4. |
| E-11 | Settings: one job at a time; switching clears call history | One agent, many jobs (D-997) | BETTER | Ours never clears history to change work. |
| E-12 | "Answer when leads call back" (picks up where it left off) | Caller memory + call-backs, one switch (`panels/callerContinuity.tsx`, D-513/514), server-sent attestation | PARITY | Ours makes the owner accept the exact statement. |
| E-13 | "Call back missed callers" toggle on the employee | Follow-up starter `missed_call_callback` (`follow-ups/Starters.tsx`, `schema.d.ts:26611`) | WEAKER | Exists, but as a separate follow-up plan an inbound owner has to discover. P-05. |
| E-14 | Opening hours (24/7 or set) | Business opening hours, set once (`inbound/InboundLineScreen.tsx` `OutsideHoursSection`, `settings/business`) | PARITY | |
| E-15 | "Hand callers to a person" (number + when) | `panels/handover.tsx`, `handoverRow.tsx` | PARITY | |
| E-16 | "Callers hear" lines for a new caller vs a lead calling back | Opening per job (lines, campaigns); notices woven into the opening (`panels/openingNotices.tsx`, D-971) | PARITY | |
| E-17 | Recording notice switch + AI disclosure **optional** ("recommended") | Hard rule 5: truthful answers always, notices per agent, said in the agent's own opening | BETTER | Keep; it is a selling point (`public-site-and-docs.md` AUP: disclosure is the customer's duty). |
| E-18 | Call time limit chips + optional wrap-up line | `max_call_duration_s` (`panels/delivery.tsx:125`) | PARITY | Wrap-up line at the limit: not found (grep `wrap.?up`); minor, folded into P-25. |
| E-19 | "Say this and end": one fixed message, then hang up | Not found (grep `say this and end|announcement only|message only`) | **LACK** | Real owner need: "closed for Diwali", "we moved". P-25. |
| E-20 | Power prompting: "your prompt, nothing added" | none | DELIBERATE | Hard rule 5 and D-674 forbid dropping the truthful-answer block and the confidentiality rule; never offer it. |
| E-21 | Version history (last 3), Start from scratch, Archive | `ScriptVersions.tsx` (campaigns and lines), delete agent (archive keeps history, `Roster.tsx`) | PARITY | "Start from scratch" not found (grep `start from scratch|start over`); the brief card regenerates a job, so not proposed. |
| E-22 | Auto 8-step coach-mark tour when the employee is built | Owner-started 4-step tour (`tour/tourModel.ts`, D-855) | DELIBERATE | Our tour is owner-started on evidence (tourModel cites it); **Lane 4** grows it to 5. |
| E-23 | — | `sections/deletedAgent.tsx` (a deleted agent is read-only), `PromoWarning.tsx`, `PutLive.tsx` pending changes | BETTER | |

### 1.5 First run and onboarding

Covered at length by LOG.md and the redesign. Rows are kept so nothing is lost.

| # | Outpero | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| F-1 | One card: brief + language + "Natural spoken" + mic + templates + job radios | 4 steps, job at step 3 (`agents/first/**`, `lib/firstAgent.ts`) | WEAKER | **Lane 1** one card, three steps. |
| F-2 | 4 follow-up questions read from the brief, chips that fill the box, auto-advance on a tap | `QuestionsStep.tsx`: 3 questions, one off-target, one generic (LOG C5, C7) | WEAKER | Question quality is 03's; the chip-fills-box and tap-advances interaction is screen work. P-22 (NEW). |
| F-3 | Answers become 3 facts + 2 rules in Training | Reported fixed in 45ce56730 ("the owner's facts, rules and hours land where they are kept"); not re-verified here | PARITY (reported) | |
| F-4 | Build ~25 s with a ticking checklist | `LiveStage.tsx`, `AgentTakingShape.tsx` ("1 of 7 ready") | PARITY | |
| F-5 | Test call from a shared line OR in the browser; no ticks | Phone only (founder 19 Oct 2026, `sections/tryIt.tsx:5`); trial line missing (`platform_settings.trial_caller_number` null, memory a2fe78cd; OPERATIONS T-22); 937a0ee5a now says why and offers typing | **WEAKER (P0 while the line is missing)** | Operator task, not code. P-01 adds a no-line way to HEAR the agent without reversing the phone-only decision. |
| F-6 | — | 6 consent ticks before the first test call (4 documents, pledge, own number) | BETTER on law, heavier on friction | Must not change (PLAN.md §10 shared rules). P-01 lets the owner hear the voice before the ticks. |
| F-7 | Test call capped by credits only | 3-minute cap (D-904, 180 s); console `trial_call_max_seconds`, 300 recommended (729dfe15) | WEAKER | Operator setting. |
| F-8 | Workspace step: none on this run (existing account) | `/signup`: name, kind of business (8), billing email, proposed web address; LOG C1: the proposed address collided with the founder's live account with no warning before submit | WEAKER (defect) | P-23. Not covered by any lane. |
| F-9 | — | "Rytu Khata is set up" screen says what happens next and that nothing is charged (LOG C2) | BETTER | |
| F-10 | Brief box kept typed text intact | C3-a garbled input; reported fixed (memory a2fe78cd, `brief ?? ownBrief`); Lane 1 acceptance re-tests 800 chars | PARITY (reported) | |
| F-11 | — | Voice notes (3 × 30 s) and files (PDF, Word, Excel, CSV, photo) on the brief (`BriefDocuments.tsx`) | BETTER | Outpero takes a mic, not files. |
| F-12 | — | "Talk it through with Pip instead" | BETTER | |
| F-13 | Opening shown before the call | "It says first" stale (C11-d) | WEAKER | **Lane 1**. |

### 1.6 Campaigns: list, builder, results

| # | Outpero (`core-5`, `core-8`, `core-11`) | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| C-1 | List: Lists, New campaign, empty state | `campaigns/CampaignsListScreen.tsx`: status chips Running/Paused/Scheduled/Drafts/Finished/Stopped/Archived with counts, search | BETTER | |
| C-2 | Pre-gate modal "You need a phone number first … Continue anyway / Get a number" | `LaunchGate.tsx`, `blockerCopy.tsx`, `StartCampaign.tsx` (7 checks, each with Show me) | BETTER | Ours is a server gate (hard rule 5, SECURITY-COMPLIANCE §3). "Show me" dead (C13-a): **Lane 3**. |
| C-3 | Stepper Who · Contacts · When · Calls at once · Retries · Consent, ticks as sections fill | `FoldSection` coloured folds in one "Set up" tab | WEAKER | **Lane 3** splits into Script / People / Settings / Checks; tab-level counts carry the "ticks". |
| C-4 | Sticky right Summary (Employee, Calls from, Contacts, Window, Days, Retries, Starts) + Launch + "You can pause at any time" | `campaignSummary.tsx` is the pre-create review only; Start at the foot of Set up | WEAKER | **Lane 3** puts Start in the header. A live receipt of what will happen is NEW: P-09. |
| C-5 | Header "Nothing is dialled until you launch." | Not found as one sentence on the draft | WEAKER | One line in P-09. |
| C-6 | Campaign name prefilled "<role> · 28 Nov" | `NewCampaignSteps.tsx:200-207` offers the business's own example name in one tap | PARITY | |
| C-7 | Contacts: any phone format, duplicates skipped, required columns as chips, "spell the headers exactly", Add contact / Import CSV / Paste / Load from list / Add variable / Sample CSV | `ContactEditor.tsx` (Excel or CSV, 4 MB, extra columns become details, max 10 extra, skipped columns named), `contactList.ts` header detection, `LeadPicker.tsx` (from leads), `DraftPeople.tsx`, sample file (grep `sample` in `ContactEditor.tsx`) | PARITY | We guess the phone column (`contactList.ts:139`); they refuse to guess and ask. Showing the agent's required details as chips before upload: P-10. |
| C-8 | Consent: one self-attestation tick | `ConsentProvenance.tsx`: list source + consent date, server gate | BETTER | |
| C-9 | Calling window (IST, "empty = full permitted hours"), timezone, days chips | `ScheduleFields.tsx`, `ScheduleCards.tsx`, `callingWindow.ts`, `scheduleCopy.tsx` | PARITY | |
| C-10 | Holidays never-call list | Holidays exist for new-lead calling (`lead-sources/CallingPlan.tsx:299`, `apps/api/ingest/lead_policy.py:69`); not for campaigns (grep `holiday` in `campaigns/` empty) | **LACK** (campaigns) | P-11. |
| C-11 | "Never dial numbers on your DNC list — Always on" (locked toggle) | DNC enforced at dispatch (hard rule 5); `lead-sources/CallingPlan.tsx:369` "Always applied" lock for lead calls | PARITY | Showing the lock on the campaign too: P-09. |
| C-12 | Skip recently-called numbers (N days, any campaign) | Not found in `campaigns/`, `apps/api/campaigns`, `apps/api/compliance` (grep `recently|cooldown|frequency cap|contact_frequency`) | **LACK** | Protects the business's name and the number's spam rating. P-10. |
| C-13 | Start now / later; Repeat one-time / daily / weekly | `campaignForm.ts:205-241` StartMode `review / later / weekly`, repeat days, time, end date; `ArmingForms.tsx` ("a missed run is skipped, never called late") | PARITY | Daily = weekly with every day ticked. |
| C-14 | Calls at once: account channels / used elsewhere / available / this campaign's share, distribution, priority, live account line | `CampaignSettings.tsx`, `CampaignRun.tsx`, `campaignProgress.ts`; "You set 3. Your account runs up to 1" (C12-c) | WEAKER | Ours shows a default as the owner's choice (C12-c, unfixed by any lane): P-24. Their allocation screen confused even them ("awaiting activation" banners, `core-11.jpg`); do not copy its complexity. |
| C-15 | Auto-retry unanswered (one toggle) | Retry policy (`apps/api/campaigns/controls.py:79`, `call_timing.spread_retry_at`), `CampaignBoosters.tsx` | PARITY | |
| C-16 | Per-campaign suppression list (docs #bulk) | Not found (grep `suppress` in `campaigns/`) | WEAKER | Account DNC covers the legal need; a campaign-only exclusion ("not existing customers") is a convenience. Folded into P-10. |
| C-17 | Live panel, CSV export | `CampaignRun.tsx`, `CampaignResults.tsx`, `ContactResults.tsx`, `CampaignTimeline.tsx`, `CampaignCalls.tsx`, `CampaignQuestions.tsx` (Improve) | BETTER | Ours has Improve with questions callers asked. |
| C-18 | Limit 10 live campaigns per account | none found as a client-visible limit | n/a | Not a gap. |
| C-19 | — | Pip writes the script from sources (`PipGenerateBand.tsx`, `AddSource.tsx`, `SourcePicker.tsx`), line coach (`LineCoach.tsx`), DLT template choice (`NewCampaignSteps.tsx:359`) | BETTER | |
| C-20 | — | Campaign alerts per job (`JobAlerts.tsx`: tell us when a captured field is X) | BETTER | |
| C-21 | Email when a campaign finishes (Settings) | Not found (grep `campaign_finished|campaign.finished|campaign_completed` in `apps/api/notifications`, `apps/api/campaigns`; `notifications/service.py` kinds are attention, announcement, plan_finished, call_lines, campaign_improved) | **LACK** | P-12. |

### 1.7 Leads

| # | Outpero (`core-2.jpg`) | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| L-1 | KPIs Total / Qualified / Pending callback / Hot | Stage chips with counts (`leads/LeadsScreen.tsx:280-295`) | PARITY | |
| L-2 | Views Pipeline (kanban) / List / Cards | Table (`LeadTable.tsx`) and phone list with swipe actions (`LeadsPhoneList.tsx`); `StatusSelect.tsx:9` mentions "the board" but no board exists (grep `LeadBoard|BoardView|view=board` empty) | **LACK** (board) | P-06. |
| L-3 | Filters channels, employees, time, last contacted, outcomes, Hot only, more; group by interest | `leadFilters.ts` 17 lenses incl. captured-field facets (`FacetPanel.tsx`), assignee, campaign, follow-up, call-back open, direction, test calls; "Find leads by what they asked for" semantic search | BETTER | |
| L-4 | Sort most recent / priority | Column sort, stages in pipeline order (`leadsTable.ts:137`) | PARITY | |
| L-5 | Export | `Export CSV` behind `calls:read_raw` + audit, same lens as the table (`LeadsToolbar.tsx`) | BETTER | |
| L-6 | Call now on a lead (docs #leads) | `CallControl.tsx`, `DialerPicker.tsx`, `AddToCampaign.tsx`, `StartFollowUp.tsx`, `BulkActionBar.tsx`, `AssigneeSelect.tsx`, `InlineName.tsx`, `ColumnChooser.tsx` | BETTER | |
| L-7 | Notes on the call (docs #calllog) | Lead timeline renders `note` events (`leads/[leadId]/LeadTimeline.tsx:40`, `apps/api/crm/models.py:114`) but the only writer found is the blocked-call note (`crm/service.py:2883`); no owner note box (grep `addNote|add a note` empty) | **LACK** | P-07. |
| L-8 | — | Lead detail with captured fields and timeline (`LeadCaptured.tsx`, `LeadDetailScreen.tsx`) | PARITY | |

### 1.8 Conversations / call log / call page

| # | Outpero | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| K-1 | Conversations: refresh, Export CSV, KPIs Calls / Qualified / Credits used | `calls/CallsScreen.tsx`: filters (how it ended, when, which way, handled, campaign or line, call-back), saved views, export (owner, audited), live rows (`liveRows.tsx`), phone list with swipe (`CallsPhoneList.tsx`) | BETTER | Credits used on the log: not on ours; folded into P-24. |
| K-2 | "Recordings deleted after a while, transcript and summary kept" stated on the list | Retention sentence not found on the list (grep `retention|deleted after` in `calls/`; one hit in `TranscriptCard.tsx`) | WEAKER | One line, P-26. |
| K-3 | Call detail: recording, summary, sentiment, talk ratio, next step, transcript, extracted data, notes, share, call back | `calls/[callId]/**`: `RecordingCard`, `TranscriptCard` (redacted by default, raw behind role + audit), `CapturedDetails`, `InsightsCard`, `KeyMomentsCard`, `CallStepsCard`, `CallMistakesCard`, `CallQualityCard`, `CallVerdict`, `CallBackAction`, `AssistCard`, `DisclosureNotice` | BETTER | Talk ratio, notes and share are missing: P-07 (notes), P-26 (talk ratio, share). |
| K-4 | — | `make-a-call/MakeCallScreen.tsx`: one call to one person from the console | BETTER | Outpero places single calls only through the API. |
| K-5 | — | `callbacks/CallbacksScreen.tsx`, `follow-ups/**`, `attention/page.tsx`, `quality/QualityScreen.tsx`, `improve/page.tsx` | BETTER | Five follow-through screens Outpero lacks. |

### 1.9 Performance

| # | Outpero | Calevate (`performance/**`) | Verdict | Note |
| --- | --- | --- | --- | --- |
| P-a | Range 7/30/90/custom | Dates picker, clamped (`PerformanceScreen.tsx:84`), "Include my test calls" | PARITY | |
| P-b | Filters employee, channel, Issues only, min duration | none on the screen (grep `agent_id|direction` in `PerformanceScreen.tsx`) | WEAKER | P-24. |
| P-c | Live "in the last hour / 24 hours" | Header live pill only | WEAKER | Minor; P-24. |
| P-d | KPIs with prior-period compare: Calls, Connect rate, Conversion, Avg length, Leads, Success rate, Credits used | `StatsBand` calls, answer rate, leads, avg duration "vs the previous N days" (`PerformanceScreen.tsx:214-219`, `analyticsFigures.ts:68-118`) | PARITY | Conversion and credits used are absent from the band; P-24. |
| P-e | Calls over time (India days) | Activity over time with a brush (`PerformanceScreen.tsx:226`) | PARITY | |
| P-f | Conversion funnel | "From calls to <callers>" funnel | PARITY | |
| P-g | Outcomes | "How calls ended" | PARITY | |
| P-h | By channel | Not on the screen | WEAKER | P-24. |
| P-i | Busiest hours (India time) | Day × hour heatmap, calls or new leads (`PerformanceScreen.tsx:267-282`); `components/improve/BestHoursCard.tsx` | BETTER | |
| P-j | Employee leaderboard + export | Count by agent (`Breakdowns.tsx:35-37`), call length by agent (ridgeline) | PARITY | No export: P-24. |
| P-k | — | Call length ridgeline, day/week table, "who was on the call" with repeat callers, reply speed (`ReplySpeed.tsx`) | BETTER | |

### 1.10 Instant leads (new-lead calling)

| # | Outpero | Calevate (`lead-sources/**`) | Verdict | Note |
| --- | --- | --- | --- | --- |
| I-1 | Tabs Activity / Analytics / Queue / Sources | One screen "Leads & hours": plan, held leads, sources, delivery log | PARITY | |
| I-2 | Sources: generic webhook, Sheets, Meta via Zapier (docs), Zapier/Make | `sourceKinds.ts`: website form, Meta Lead Ads (native), Zoho, Sheets, custom POST, IndiaMART, 99acres, MagicBricks, Housing.com, LeadSquared | BETTER | Native Meta and Indian property portals. JustDial / Sell.Do: 02 G11. |
| I-3 | Calling policy: delay, window, out-of-window handling, retry ladder | `CallingPlan.tsx`: when to call, holidays, after-hours choice, answering machines, "Always applied" lock | PARITY | |
| I-4 | Queue / "Needs attention" / Call now | `HeldLeads.tsx` "Waiting for you"; `attention/page.tsx` | PARITY | |
| I-5 | Test webhook + activity log (accepted / dedup / rejected) | `TestLeadDrawer.tsx`, `DeliveryLog.tsx` | PARITY | |
| I-6 | Analytics: speed to lead (median), answered, qualified, never reached, hot waiting, callbacks, avg attempts; "Does calling faster convert?"; speed distribution; funnel; response-time trend; when leads arrive; attempts to reach; source performance table | Speed to lead is recorded as an operator metric only (`apps/api/core/alerting.record_speed_to_lead`, called from `ingest/service.py:718-772`); no client screen (grep `speed.to.lead` in `app/c` hits only Performance's reply speed, which is a different measure) | **LACK** | The single strongest proof of value for instant calling. P-04. |
| I-7 | Live pop-up when an instant lead starts being called | Desktop alerts (`settings/alerts/DesktopAlerts.tsx`: hot leads, failed calls, low credit) | WEAKER | Folded into P-08. |

### 1.11 Inbound / receptionist

| # | Outpero (`#/inbound`) | Calevate (`inbound/**`) | Verdict | Note |
| --- | --- | --- | --- | --- |
| N-1 | Status line "Not answering · 0 answered today" | Not on the Inbound list or line page (grep `today|answered` in `inbound/`) | WEAKER | P-05. |
| N-2 | Setup checklist 0/3: number · receptionist · attach | Line page folds Voice → Main task → Sources → Script → Actions → Outside hours → Numbers → Test call (`InboundLineScreen.tsx:1-12`), `PutLineLive.tsx`, `lineStatus.tsx` | PARITY | |
| N-3 | Tabs Overview / Calls / Messages / Missed callers | "Calls taken" fold (latest calls), Call logs filtered by line, Call-backs screen; no Messages or Missed callers view for a line | WEAKER | P-05. |
| N-4 | "Which number rings whom (0/0 live)" | Numbers fold on the line, `phone-number/NumberAssignment.tsx` | PARITY | |
| N-5 | "Hear it yourself — ring your number, or test in the browser" | Test call fold (phone only) | PARITY minus browser | Browser: P-01. |
| N-6 | Recording notice before the greeting, every caller | Notices said in the opening (D-971) | PARITY | |
| N-7 | Messages and call-back requests trigger an email + notification + "Messages from callers" | Call-backs (`callbacks/CallbacksScreen.tsx`), hot-lead alerts to the team (`settings/alerts`), WhatsApp alerts | PARITY | "Message for the owner" as its own kind: P-05. |
| N-8 | Missed-caller call-back once inside hours, never DNC | Follow-up starter (E-13) | WEAKER | P-05. |
| N-9 | — | Existing number forwarding (`phone-number/ExistingNumber.tsx`, D-746), spam-label checks (`SpamLabels.tsx`), line protection (`settings/line-protection`) | BETTER | Owners keep the number callers already know. |

### 1.12 Phone numbers

| # | Outpero (`13-*.jpg`) | Calevate (`phone-number/**`) | Verdict | Note |
| --- | --- | --- | --- | --- |
| U-1 | "Your number is who customers see"; no number → test calls on a shared line | `PhoneNumberScreen.tsx` two halves: numbers from Calevate, your existing number | BETTER | |
| U-2 | Mobile / Landline tabs, search, list with ₹649/mo each, 20 of 50, Load more | `OwnNumbers.tsx` search by city / digits, "Choose a number", our price `inr_per_month`, refusals in words (`number_price_not_attested`, `number_insufficient_credit`) | PARITY | Landline vs mobile choice not seen (grep `landline` hits only the forwarding half); UNVERIFIED whether the catalogue offers both. |
| U-3 | "Calls at once: 0 of 8" | Concurrency shown on the campaign (C-14) | PARITY | |
| U-4 | Rules card "Before you start calling" | `verify-business/**`, `agreements/**`, `do-not-call/**`, `messaging-consent/**`, outbound pledge | BETTER | |

### 1.13 Credits and billing

| # | Outpero | Calevate (`billing/**`) | Verdict | Note |
| --- | --- | --- | --- | --- |
| B-1 | KPIs balance, spent 24 h, calls 30 days, last top-up | `WalletHero.tsx`, `SpendPanel.tsx`, `SpendChart.tsx` | PARITY | |
| B-2 | Tabs Overview / Statement / Billing details | `tabs.ts`: credits, usage, statements, transactions (`TransactionsTab.tsx`, `StatementsView.tsx`, `statementCsv.ts`, `ReceiptSheet.tsx`, `invoice/page.tsx`) | BETTER | |
| B-3 | Spending by employee (7/30/90) | "Where the money went", per agent and per call (`SpendPanel.tsx:37`), `WhereItWent.tsx`, `CostPerResult.tsx` | BETTER | Cost per result beats spend share. |
| B-4 | "What calls cost": rates, ₹0 unanswered, 30-s blocks with worked examples, AI actions ~₹0.2 | `WhatCallsCost.tsx` (30-second steps D-681, rounding example at :166, GST position), `VoiceTiers.tsx` | PARITY | Prices are 04's. |
| B-5 | Add credits: 5 packs with free credits, talk time per tier, "Total with GST" live | `TopUp.tsx` (talk time per pack, smallest pack covering a month at :735), `AddCredit.tsx`, `LotsPanel.tsx` (frozen per-lot rates) | PARITY | |
| B-6 | — | `AutoRechargePanel.tsx`, `LowBalanceAlertPanel.tsx`, `UnfinishedPayments.tsx`, `PlatformFeeCard.tsx`, `InvoicedAccount.tsx` | BETTER | Outpero: no auto-debit. |

### 1.14 Settings, notifications, privacy

| # | Outpero (`#/settings`) | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| S-1 | General: business name, default language | `settings/business/**` (`ProfileSection`, `SetupWizard`, `BusinessCopySection`) | BETTER | AI-written business copy (D-827). |
| S-2 | Smart follow-ups (memory + call-backs, one switch) at account level | Per agent (`panels/callerContinuity.tsx`) | PARITY | |
| S-3 | In-app matrix: Bell / Pop-up per type (new results, reminders to call, morning brief, milestones, messages, opt-outs) + an always-on list | Bell feed (one list) + one desktop-alert switch (`DesktopAlerts.tsx`) | WEAKER | P-08. |
| S-4 | Results and email: which results count, campaign-finished email, daily results email (+ quiet days) | `settings/alerts/DailySummary.tsx`, `DailySummaryOffer.tsx`; campaign-finished: LACK (C-21) | PARITY / LACK | P-12. |
| S-5 | Instant email alerts within a minute, batched in busy spells, by result and by the owner's own captured answers, quiet hours, max per day (12), "Send me a sample" | "Who hears about hot leads" (`AlertsScreen.tsx`, D-967): owner email always, WhatsApp after consent, team list with verified numbers (`TeamList.tsx`); per-job field alerts (`campaigns/JobAlerts.tsx`); per-agent team alerts (`panels/teamAlerts.tsx`) | PARITY (channel BETTER) | WhatsApp to the team is the Indian owner's channel. Quiet hours, daily cap, batching, sample: not found (grep `quiet hours|quiet_hours`, `Send a test|sample alert`): P-08. |
| S-6 | Live call updates pop-up, per device, pause 1 h / rest of today | Desktop alerts on/off only | WEAKER | P-08. |
| S-7 | Account: email, status, member since, sign out, Google + optional password | "Your account" in the sidebar (`ClientSidebar.tsx:243-257`), first-party sessions (D-177) | PARITY | |
| S-8 | Remembered callers: per employee table Caller / Employee / Calls / Last outcome / Last call; banner when off | Switch only (`callerContinuity.tsx`); no list, no "forget this caller" (grep `forget|clear` empty there); person-level erasure in `data-rights/Erasure.tsx` | **LACK** | DPDP-shaped: an owner should see what is remembered. P-13. |
| S-9 | DNC: applies to every path incl. test calls; bulk add; columns Phone / Reason / Added | `do-not-call/**` (`SuppressedList.tsx`, `RestoreDialog.tsx`, `ConsentPosture.tsx`, `sources.ts`), national DND (`apps/api/compliance/national_dnd_routes.py`), platform DNC | BETTER | |
| S-10 | Saved credentials reused by every action | `integrations/ConnectedAccounts.tsx`, `agents/actions/AccountRow.tsx` | PARITY | |
| S-11 | Privacy: "What you've agreed to" with date and version; Export all calls (CSV); deletion by email | `agreements/**` (versions, accept panel), calls/leads export, `data-rights/**` (register, subject export, erasure), `caller-notice/**`, `breach-playbook/**`, `messaging-consent/**` | BETTER | Self-serve erasure vs Outpero's email-support. |
| S-12 | — | Team and roles (`settings/team/**`), AI model choice (`settings/models/**`), call notices (`settings/call-notices`), line protection, AI help (`ai-assist/**`) | BETTER | Outpero has one login per account. |

### 1.15 Developers

| # | Outpero | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| D-1 | `#/developers`: keys, quickstart, webhooks with events, API activity | `integrations/**` webhooks (signed, secret shown once, `DeliveryLog.tsx`, `EventChoices.tsx`), lead intake; no tenant API keys (grep `api_key_hash|client_api_keys` in `apps/api` empty) | **LACK** (keys, public API) | Owned by 02 (G1–G10). The screen consequence: a "For developers" page needs 02's G1 first. |

### 1.16 Help, tour, search, mobile

| # | Outpero | Calevate | Verdict | Note |
| --- | --- | --- | --- | --- |
| Q-1 | Help centre, 27 topics, "Last updated" on each | Pip in the header (`ClientCopilotDock`), ⓘ tips, `assistant/AssistantScreen.tsx` | WEAKER | P-16. |
| Q-2 | Public status page | none (status.outpero.com NXDOMAIN) | — | Ours: `apps/web/src/app/status/StatusScreen.tsx`. **BETTER.** |
| Q-3 | ⌘K search | none for clients | **LACK** | P-02. |
| Q-4 | Mobile bottom nav Home/Team/New/Leads/More (Aug, memory 694cc713; not re-observed 28 Nov) | Off-canvas sidebar ("Open navigation", `ClientTopHeader.tsx:70`), phone lists with swipe (`LeadsPhoneList.tsx`, `CallsPhoneList.tsx`), `responsive.test.ts`, phone-specific layouts (`LeadsToolbar.tsx:24`) | PARITY | A bottom bar for the three things owners do on a phone: P-27. |

---

## 2. Where we are ahead (keep these; do not trade them for Outpero's shape)

1. **Hard rule 5 on screen**: truthful answers always, notices woven into each agent's own
   opening (D-971); Outpero's AI disclosure is an optional switch (E-17).
2. **The compliance gate with words and Show me** (C-2, C-8, C-11): list source and consent date,
   not one tick. Keep the six Hear-it ticks (PLAN.md §10).
3. **Results home** (H-1 to H-5, H-9): cost per lead, missed calls today, next steps, held
   numbers. Outpero's home shows no results.
4. **One agent, many jobs** (E-11, D-997): changing work never wipes call history.
5. **Shared knowledge with review** (E-7): teach by text, mic, photo or file; nothing saved
   until kept; pinned facts; questions from real calls.
6. **Script editor depth** (E-4): step outcomes, push-backs, Q&A per step, branching, size meter,
   reviewed Pip diffs (E-5).
7. **Leads lens** (L-3, L-5, L-6): 17 filters including captured fields, semantic "what they
   asked for", bulk actions, assignee, follow-ups, audited export.
8. **Call page** (K-3): redacted transcript by default, key moments, steps reached, mistakes,
   quality, verdict, call-back from the page.
9. **Follow-through screens** (K-5): Needs attention, Improve, Call-backs, Follow-ups, Quality.
10. **Make a call** to one person from the console (K-4).
11. **Performance** heatmap, ridgeline, repeat callers, reply speed (P-i, P-k).
12. **Lead sources**: native Meta, IndiaMART, 99acres, MagicBricks, Housing, LeadSquared (I-2).
13. **Existing-number forwarding, spam labels, line protection** (N-9, U-1).
14. **Billing**: cost per result, auto-recharge, frozen lot rates, statements and receipts (B-3, B-6).
15. **Team, roles and WhatsApp alerts to the team** (S-5, S-12).
16. **Self-serve data rights, breach playbook, privacy notice builder** (S-11).
17. **Public status page** (Q-2), phone preview switch (G-13), trial chip (G-14).
18. **Failure honesty**: every read that fails says so in words (live pill, bell, charts). Outpero's
    failed test call left no record and no error (LOG O10).

---

## 3. What the redesign lanes already cover

| Lane (PLAN.md §10) | Rows it closes | Rows it only touches |
| --- | --- | --- |
| Lane 1 first screen | F-1, F-13, F-10 (re-test) | H-6 (card exists; home placement is P-19) |
| Lane 2 agent home tabs | E-3, E-9 (notes tab), E-1 ("Calls (n)") | A-2 (no) |
| Lane 3 campaign tabs | C-2 (Show me), C-3, C-12-b count | C-4 (Start in header; summary is P-09) |
| Lane 4 sidebar, tour, voice prices | G-1, E-10 (price), C8-a | G-8 (agent tour only), E-10 (breadth is P-15) |

Everything in §4 marked NEW is outside all four lanes.

---

## 4. Proposals for every WEAKER and LACK

Each is a Calevate design, not Outpero's. Effort: S (under a day), M (one to three days),
L (more, or crosses api + web + engine). "Lane" says who covers it.

### P-01 Hear it before a phone can ring (F-5, F-6, N-5) — NEW, M

Problem: the trial's shared line is unset (operator, OPERATIONS T-22), so a new owner finishes
setup and hears nothing. The founder chose phone-only test calls (19 Oct 2026,
`sections/tryIt.tsx:5`); this design does not reverse that.

Design: on Hear it, beside the phone box, **"Play its first words"**: the opening line and the
first step's first line, rendered in the chosen voice through the same preview path voice rows
use (`components/voicePreviewButton.tsx`), played in the page. It is a recording, not a call:
no microphone, nothing to consent to, no minutes used. Under it, the typed chat 937a0ee5a
already offers. When the line is unset the box says why in one line and offers both.

Acceptance: with `trial_caller_number` null, a trial owner hears the agent's opening in its voice
within 5 s of tapping; the text played equals the stored opening (compliance notices included,
never cut); no consent tick is bypassed for the phone call; no provider name on screen.
Dependencies: a server render of a short line in the agent's voice (preview path exists for
catalogue samples; a script-text render is UNVERIFIED and must be checked against the engine
docs before building). Operator still sets the trial line (T-22).

### P-02 "Find" for the client console (G-4, Q-3) — NEW, M

Design: a top-bar field "Find a person, call or screen" (Ctrl+K / ⌘K, and a search icon on a
phone). One list, grouped: People (lead name, last 4 digits of a phone, never the full number
in the URL), Calls (by person), Agents, Campaigns, Inbound lines, Screens (from the same
directory Pip uses, `apps/api/copilot/screens.py`), and a last row "Ask Pip: <typed text>".
Telugu typed in English letters matches Telugu names (transliteration is the Calevate twist).
Reuse `components/interior/command-palette.tsx`.

Acceptance: opens from the keyboard and the icon; arrow keys and Enter work; screen reader
announces groups; a search for 4 digits finds the lead; no phone number or name is put in a
URL or a log (hard rule 6); a role without `calls:read` sees no People group.
Dependencies: a lead search endpoint that takes a partial name or last digits (the leads lens has
`search`; confirm it matches partial digits).

### P-03 Agents list that answers "is it working today?" (A-2, A-3, A-4) — NEW, S

Design: each row gains one line "Today: 12 calls · 3 interested · last 4 min ago" from the
existing agent stats read; a **Try it** text action on the row (opens Training with the chat);
above the list, when there are more than five agents, a search box and the chips Working / Off /
Not live yet with counts.

Acceptance: the today line uses IST days; a failed stats read hides the line and says nothing
false; chips filter without a reload; at 375 px the row wraps without horizontal scroll.
Dependencies: agent stats must carry a today count and an interested count (UNVERIFIED that
`AgentStats` has them; add to the server read if not). Lane 2 owns `agents/page.tsx`: land after it.

### P-04 Speed-to-lead proof on Leads & hours (I-6) — NEW, M

Design: a "How fast we called" card at the top of Leads & hours: median seconds from a lead
arriving to its phone ringing, share rung within 60 s, leads never reached, leads waiting now;
a by-source table (leads, reached, interested, median speed), each row filtering the Leads
screen. Only when there are at least 30 leads in the range does it add "Called within a minute
vs later: interested rate", with the counts beside it so a small sample cannot mislead.

Acceptance: figures computed server-side over the tenant's own rows (RLS); after-hours held
leads are counted from release, not arrival, and the card says so behind ⓘ; ranges 24 h / 7 /
30 / 90 days IST; empty states say what will appear.
Dependencies: a client analytics endpoint; the raw timing exists only as an operator metric
(`apps/api/core/alerting.record_speed_to_lead`). 02 G12 flags the same gap from the intake side.

### P-05 Inbound "today" and the missed callers (N-1, N-3, N-7, N-8, E-13) — NEW, M

Design: the Inbound list opens with a strip per line: "Answered today 14 · Missed 2 · Waiting
for you 3", each a link. A **Missed** view lists callers who rang and were not answered or hung
up before speaking, with reason and one button "Call them back now". On the line page, under
Outside hours, a switch **"Call back missed callers"** that creates or enables the existing
`missed_call_callback` follow-up for this line, so the owner never meets the follow-ups screen
to get it. "Waiting for you" = call-backs and messages the caller left for the owner.

Acceptance: the switch reads back the follow-up's real state; DNC numbers are never called back
(gate unchanged); calls outside opening hours are called back inside them; counts are IST days.
Dependencies: whether the engine reports a caller who hung up before the agent spoke as a call
event is UNVERIFIED (check the ThinnestAI webhook docs in the snapshot before building).

### P-06 Lead "desk" view (L-2) — NEW, M

Design: a second view beside the table, **Desk**: one column per stage (the seven stages in
pipeline order), a card per person with name, last outcome, the one captured field the owner
marks most important, and the next call-back time. Move a card with a "Move to" menu (drag as a
shortcut only, never the only way, per PLAN.md §6 rule on dragging). On a phone the desk is a
stage picker with the cards below, not seven columns.

Acceptance: moving writes through the same status mutation as `StatusSelect.tsx` and is
audited; keyboard-only users can move a card; the chosen view is remembered per browser
(try/catch storage); the export still follows the table's lens.
Dependencies: none new on the server.

### P-07 Owner notes on a lead and a call (L-7, K-3) — NEW, S-M

Design: a note box on the lead page and on the call page ("Add a note for your team"), saved as
a `note` lead event (the type exists, `apps/api/crm/models.py:114`), shown in the timeline with
who wrote it. A note written on a call links back to that call.

Acceptance: notes are tenant-scoped with RLS and a cross-tenant zero-rows test; note text never
appears in logs (hard rule 6); editing is a new event, not an UPDATE if the events table is
append-only (check `APPEND_ONLY_TABLES` first); Pip can read notes only under the existing Pip
consent rules.
Dependencies: a POST route for owner notes.

### P-08 Alerts you can shape (S-3, S-5, S-6, I-7) — NEW, M

Design: one table on Alerts: rows are what happened (hot lead, call-back asked, message left,
failed call, low credit, campaign finished, opt-out), columns are where (bell, this computer,
email, WhatsApp). Money, numbers, a paused agent and call failures are marked "always" and
cannot be unticked, with the reason behind ⓘ. Below: **Quiet hours** (IST, default 9 PM–8 AM,
WhatsApp and email held and sent as one message at the end), **At most N a day** then one
digest, and **Send me a sample** per channel.

Acceptance: an always-on row cannot be switched off by the UI or the API; quiet hours never
delay a desktop alert the owner is watching; the sample is marked as a sample; WhatsApp stays
behind the owner's recorded consent (unchanged).
Dependencies: server-side preferences; the WhatsApp send path is template-bound (UNVERIFIED for
a digest template; check the approved templates).

### P-09 "Before it dials" receipt on a draft campaign (C-4, C-5, C-11, C-16) — Lane 3 partial, S

Design: on a draft, a compact receipt under the header (a side rail at 1280 px, a fold at
375 px): "Nothing is dialled until you start." then six lines, each a link to its tab: Agent and
the number it calls from · How many people (after DNC and duplicates) · When (window, days,
holidays) · Calls at once · Tries per person · Starts. The DNC line is fixed text "Never calls
anyone on your Do not call list" with a lock.

Acceptance: every line is read from the same form state `campaignSummary.tsx` uses (one source);
red text only where a check blocks start; each link opens the right tab through Lane 3's
`openCampaignSection()`.
Dependencies: Lane 3's tabs and helper.

### P-10 Respectful dialling across campaigns (C-7, C-12, C-16) — NEW, M

Design: in the campaign's Settings tab, **"Skip people we called in the last N days"** (default
on, 7 days, any campaign, any agent), and an account-wide guard in the dial gate: no person is
dialled more than a fixed number of times per IST day across campaigns, follow-ups and new-lead
calls. On People, before upload, the details the script uses appear as chips ("This script uses:
name, village") so the owner names columns to match. A campaign-only "Leave these people out"
list for one-off exclusions.

Acceptance: the skip and the cap are enforced in the dispatcher, not only the form; skipped
people are counted and listed with the reason; changing the setting on a running campaign
applies from the next dispatch tick.
Dependencies: a recent-dials index per tenant; the daily cap figure is a founder/ops choice (no
regulation number is claimed here).

### P-11 Holidays for campaigns (C-10) — NEW, S

Design: reuse the business holiday list from Leads & hours (`lead_policy.py` already holds
holidays) and show it in the campaign's When section as "Skips your holidays: 2 Dec, 25 Dec ·
Change", one list for the whole business.

Acceptance: a campaign never dials on a listed IST date; the list is edited in one place.
Dependencies: campaign dispatch reads the same holidays.

### P-12 Tell the owner when a campaign finishes (C-21, S-4) — NEW, S

Design: a bell item and an email "Your campaign <name> finished: 412 called, 63 interested,
9 asked to call back. See them", plus WhatsApp if consented; the per-kind switch in P-08.

Acceptance: sent once per finish (idempotent on campaign id + finish time); numbers match the
campaign's Progress tab; no phone numbers in the email.
Dependencies: none beyond P-08 for the switch.

### P-13 What your agents remember (S-8) — NEW, M

Design: under Data rights (or the agent's Settings, beside the memory switch) a list: caller
(masked number), agent, calls, last outcome, last call, with **Forget this caller**. When the
switch is off the list stays and says "Kept until you clear it".

Acceptance: masked numbers by default, raw behind role + audit (hard rule 5); Forget erases the
memory through the existing erasure path and leaves a deletion proof; RLS test.
Dependencies: a list endpoint over caller memory (`apps/api/compliance/caller_memory.py`).

### P-14 Try the draft beside the script (E-6) — NEW, L

Design: on the campaign and line Script tab, a docked **Try it** panel (closed by default, opens
to the right at 1280 px, as a sheet on a phone) that talks to the DRAFT, not the published
script, and shows actions as plain lines ("It would book Tue 10 AM", "It would send the WhatsApp
'location'") instead of doing them.

Acceptance: it never places a call or runs an action; a reply that would have run an action says
so; it is labelled as a text rehearsal; it costs the owner nothing on the trial.
Dependencies: the engine's test chat runs only the published agent (VENDOR-STATED, cited in
`TryChat.tsx`); a draft rehearsal needs either an engine draft endpoint (ask ThinnestAI) or our
own simulation on our Gemini over the compiled draft prompt (D-834 key). Choose after reading the
vendor reply; not buildable on a guess.

### P-15 A voice shelf worth choosing from (E-10) — NEW, M + operator

Design: voices grouped by "Speaks Telugu natively" / "Speaks Telugu too", filters by language,
man or woman, and tone (calm, warm, energetic), each with a 6-second sample in the business's own
opening and the price line from Lane 4.

Acceptance: only admin-enabled voices appear (clients never clone); no provider name; filters
work at 375 px.
Dependencies: the admin must add voices (Studio clones up to 25, CLAUDE.md, VENDOR-STATED
23 Oct 2026); tone tags are an admin field. Lane 4 covers price only.

### P-16 Help that a person answers (G-9, G-10, Q-1) — NEW, S + owner decision

Design: a "Help" menu in the header: Ask Pip, **How Calevate works** (8 short pages in owner
words: first agent, campaigns, inbound, leads, credits, numbers, notices and the law, your data),
and **Talk to us** (a WhatsApp chat or call-back request to the Calevate team, with the hours it
is answered).

Acceptance: every help page names its last-updated date; no provider name; Talk to us shows only
when a support contact is configured (console setting), never a dead link.
Dependencies: who answers support and on what number is an external decision (founder / ops);
until set, the menu shows Ask Pip and the pages only.

### P-17 Show me around, for the whole account (G-8) — NEW, S

Design: a 4-step owner-started tour from the Help menu: Dashboard (how today went) → Agents
(who works for you) → Leads (who to call back) → Credits. Same rules as the agent tour
(`tourModel.ts`): owner-started, under five steps, never switches tabs.

Acceptance: never auto-starts; dismissable with Esc; does not cover the item it describes on
a phone. Dependencies: Lane 4's tour model.

### P-18 Developer page (D-1) — see 02

The keys, public API, quickstart and API activity screens are designed in
`02-api-integrations.md` (G1, G2, G6, G8). The screen follows G1; nothing to add here.

### P-19 The brief card on home until something is live (H-6) — NEW, S (after Lane 1)

Design: while no agent is live, the dashboard's first block is Lane 1's card ("What should your
agent do?") with the trial line beneath; once one agent is live it shrinks to a "Give an agent a
new job" row under the results.

Acceptance: never shown to a role that cannot create agents; uses Lane 1's component unchanged.
Dependencies: Lane 1.

### P-20 Job starters you can see (H-7) — NEW, S

Design: under the brief card, six job cards written for this business by the D-827 copy:
Call new enquiries · Remind appointments · Collect payments · Win back old customers · Confirm
orders · Answer my calls. Tapping one fills the brief box with the business's own words and
picks the job. Reuse the follow-up starters' keys so one list of jobs exists.

Acceptance: no stock photos of other trades; every card's text is this business's; Telugu when
the account's language is Telugu.
Dependencies: Lane 1's card; the starter list in `follow-ups/Starters.tsx`.

### P-21 Copy a script from another job (H-8) — NEW, S

Design: on a Script tab, "Start from another script" lists this account's campaigns and lines;
picking one copies its steps into the draft for review, opening line included.

Acceptance: copying never puts anything live; notices are re-composed for the new job.
Dependencies: none.

### P-22 Follow-up questions that move by tap (F-2) — NEW, S

Design: when a question has choices, tapping one answers and moves on; "Something else" opens the
box. Never-say choices fill the box as editable lines.

Acceptance: back returns to the last answer; screen-reader focus moves to the new question.
Dependencies: Lane 1 owns `agents/first/**`; land after it. Question quality is 03's.

### P-23 Workspace address that cannot collide silently (F-8) — NEW, S

Design: the proposed web address is checked as it is typed; a taken one says "Taken. Try
rytu-khata-2" with the alternative filled in.

Acceptance: no submit with a taken address; reserved slugs refused with the reason.
Dependencies: an availability check on the signup route.

### P-24 Performance you can narrow (P-b, P-c, P-d, P-h, P-j, K-1, C-14) — NEW, S-M

Design: filters Agent · Campaign or line · Calls I made / Calls I answered; two more figures in
the band: **Interested rate** and **Spent** (from usage, shown only to billing roles); a
"Last hour" mini line above the band while calls are live; Download for each table. On campaigns,
"Calls at once" says "Up to 1 at a time (your account's limit)" until the owner sets a figure,
fixing C12-c.

Acceptance: every figure keeps "vs the previous N days"; spend respects `billing` access; IST.
Dependencies: analytics endpoints take the filters (UNVERIFIED which do today).

### P-25 "Just say this" lines (E-19, E-18) — NEW, M

Design: on an Inbound line, a switch **"Today, just say a message"** with the message and an
until-date ("Closed for Diwali, we reopen on 3 Nov. Leave your name after the tone" is the
owner's to write). Calls are answered with the message, the notices, and then end. A wrap-up
line at the call time limit on the same screen.

Acceptance: the AI disclosure and recording notice still play (hard rule 5); the message
switches itself off at the until-date; calls are logged as "Message played".
Dependencies: engine support for a fixed-message agent (UNVERIFIED; check the agent config docs).

### P-26 Small call-page and call-log truths (K-2, K-3) — NEW, S

Design: one line on Call logs saying how long recordings and transcripts are kept (from the
tenant's retention setting, never a constant); "Who talked more" bar on the call page; **Send to
a team member** (sends a link to someone on the team list; the link opens only for a logged-in
member with access; no public links).

Acceptance: retention text read from the server; the share never exposes raw transcript to a role
without `calls:read_raw`.
Dependencies: retention read for the tenant.

### P-27 A phone bar and quick agent links (G-2, Q-4) — NEW, S

Design: under 768 px, a bottom bar: Home · Leads · Calls · Pip · More. In the desktop sidebar,
the account's agents appear under Agents when there are five or fewer.

Acceptance: respects the safe-area inset; does not hide the Pip launcher; `screens.py` groups stay
equal to `clientNav.ts` (CI `screens_test.py`).
Dependencies: Lane 4 owns `clientNav.ts` and the sidebar: land after it.

### P-28 Switch business without signing out (G-3) — NEW, S

Design: the business name at the top of the sidebar opens a list of this person's workspaces.
Acceptance: switching keeps the session realm separation (D-177); no cross-tenant data cached
across the switch. Dependencies: the workspace list `app/c/page.tsx` already reads.

### P-29 Money while calls run (G-5, G-7) — NEW, S

Design: the live pill gains "· about ₹X a minute now" while calls run, and the credit chip says
"about N minutes left" from the server's figure.
Acceptance: both figures come from the server (hard rule 7; no browser arithmetic on money);
hidden for roles without billing access.
Dependencies: a server "minutes left" figure at the account's current mix (UNVERIFIED that it
exists; `TopUp.tsx` computes talk time per pack server-side).

---

## 5. Top 20 gaps, ranked by impact on an owner

| Rank | Gap | Rows | Proposal | Effort | Lane |
| --- | --- | --- | --- | --- | --- |
| 1 | A new owner cannot hear the agent at all on the trial (no shared line; no other way to hear it) | F-5, N-5 | Operator sets the trial line (T-22) + P-01 | M + ops | NEW |
| 2 | First run is 9 screens with the job asked late; owner-word jargon | F-1, F-13, E-4 | Lane 1 + Lane 3 owner words | — | Lanes 1, 3 |
| 3 | No proof of speed to lead for new-lead calling | I-6 | P-04 | M | NEW |
| 4 | Inbound has no "today" view, no missed callers, missed-caller call-back hidden in Follow-ups | N-1, N-3, N-8, E-13 | P-05 | M | NEW |
| 5 | Campaign draft is one long page; Show me dead; no receipt of what will happen | C-3, C-4, C-5, C-2 | Lane 3 + P-09 | S | Lane 3 partial |
| 6 | No cross-campaign "recently called" skip or per-person daily cap | C-12, C-16 | P-10 | M | NEW |
| 7 | Voice choice thin (3 voices), no prices, contradictory note | E-10 | Lane 4 (price, C8-a) + P-15 | M + admin | Lane 4 partial |
| 8 | Cannot rehearse the draft beside the script | E-6 | P-14 | L | NEW (vendor-dependent) |
| 9 | No search across people, calls and screens | G-4, Q-3 | P-02 | M | NEW |
| 10 | Agents list does not say whether each agent is working today | A-2, A-3, A-4 | P-03 | S | NEW |
| 11 | Sidebar of 36 items | G-1 | Lane 4 | — | Lane 4 |
| 12 | Alerts cannot be shaped: no quiet hours, caps, per-kind channels, sample | S-3, S-5, S-6, I-7 | P-08 | M | NEW |
| 13 | No human support route or browsable help | G-9, G-10, Q-1 | P-16 | S + decision | NEW |
| 14 | No lead desk (stage board) | L-2 | P-06 | M | NEW |
| 15 | No owner notes on leads or calls | L-7 | P-07 | S-M | NEW |
| 16 | No email/bell when a campaign finishes | C-21 | P-12 | S | NEW |
| 17 | Performance cannot be narrowed by agent, job or direction; no spend or interested rate in the band | P-b, P-d, P-h | P-24 | S-M | NEW |
| 18 | No "just say a message" mode for closures | E-19 | P-25 | M | NEW (engine check) |
| 19 | Owners cannot see or clear what agents remember about callers | S-8 | P-13 | M | NEW |
| 20 | No holidays on campaigns | C-10 | P-11 | S | NEW |

Just outside the 20: job starters on the brief card (P-20), workspace address collision (P-23),
"You set 3" default shown as a choice (P-24 fix), copy a script from another job (P-21),
tap-to-answer questions (P-22), account tour (P-17), brief card on home (P-19), phone bar
(P-27), workspace switcher (P-28), live spend rate (P-29), call-page share and talk ratio
(P-26), 3-minute trial cap (operator, F-7).

---

## 6. Not verified here

* No screen was opened in a browser for this file; every Calevate verdict is from code at
  `rel-0.5.98`. Fixes reported in commits 45ce56730, ac52ba316, 937a0ee5a and memory a2fe78cd
  (C3-a, C12-a, facts and hours from the brief) are taken as reported.
* Whether `AgentStats` carries today and interested counts (P-03), whether the leads search
  matches partial digits (P-02), which analytics endpoints take agent or job filters (P-24),
  whether a server "minutes left" figure exists (P-29).
* Engine questions (ThinnestAI): a draft test chat (P-14), a fixed-message agent (P-25), a
  "caller hung up before the agent spoke" event (P-05), rendering arbitrary script text in an
  agent's voice (P-01). Each must be answered from the vendor docs snapshot or by the vendor
  before its proposal is built.
* Whether the number catalogue offers landlines (U-2).
* Outpero's data screens with real data: their account was empty.
