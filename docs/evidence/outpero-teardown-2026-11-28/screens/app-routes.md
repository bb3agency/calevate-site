# Outpero app (app.outpero.com), screen by screen, 28 Nov 2026

Account: founder's "Sri Estates" (empty: 1 draft employee "Tarun", 0 calls, 50 credits). Data
screens therefore show empty states; their structure (filters, columns, KPIs) is recorded.
Evidence: first-hand, Claude in Chrome. Screenshots in ../shots/ (NN-name-N.jpg).

## Global chrome
- Sidebar: workspace switcher (business + email), Search (⌘K), Home; AI EMPLOYEES: All
  employees (count) with the employee list nested under it, Hire an employee; RESULTS: Leads,
  Conversations, Performance; CALLING: Campaigns, Instant leads, Incoming calls; WORKSPACE:
  Numbers & channels, Credits & billing, Settings; Developers; "Prefer the old look? Open the
  old app" (legacy.outpero.com); credits card "50 · 7–10 min of calls · Add credits".
- Header: breadcrumb, "0 on calls · 0.0/min" live indicator, Take the tour, Help and docs,
  dark theme toggle, Notifications (alt+T). Floating "Ask Swara" and Support and feedback.

## #/ Home
The home IS the new-employee card: "What should your next AI employee do?" + language picker
(Telugu, Hindi, Tamil, Kannada, Malayalam, Marathi, English) + "Natural spoken" tick + brief box
+ Templates + mic + Continue; job radios Instant / Bulk / Inbound. 14 photo templates with a
one-line use case each: BFSI; Real estate; Coaching & tuition; Hospital & clinic; Car & bike
dealership; Interiors & construction; Local services; Jewellery & fashion; Hotels & restaurants;
Travel & tours; Solar & home improvement; Recruitment & staffing; Wholesale & distribution;
Other. "Copied a script from another Outpero employee? Paste it here". "Show setup steps".

## #/employees AI employees
"One employee per job. Give it a number to go live." Chips All / Live / Paused / Draft with
counts; job filter; sort Recently hired; search. Card: initial, name, status pill, role, last
active, job chip, voice chip (P09 · te-IN), number chip, stats Calls today / Leads / Qualified,
Test call, play, more. Dashed card "Hire a new employee — Free to build · ready in about 5 minutes".

## #/leads Leads & Results
"Everyone your employees have spoken with." Export. KPIs Total leads, Qualified, Pending
callback, Hot leads. Sort Most recent / Priority. Views Pipeline / List / Cards. Filters
channels, employees, time, Last contacted, outcomes, Hot only, More filters; Group by Interest
level. Empty state explains what lands here.

## #/conversations Conversations
"Every call your employees handled." Refresh, Export CSV; recordings deleted after a while,
transcript and summary kept. KPIs Calls / Qualified people / Credits used.

## #/performance Performance
Range 7/30/90/Custom, employee, channel, Issues only, min duration. Live "in the last hour / 24
hours". KPIs with prior-period compare: Calls, Connect rate, Conversion, Avg call length, Leads,
Success rate (clean calls), Credits used. Charts: Calls over time (India days), Conversion
funnel, Outcomes, By channel, Busiest hours (India time), Employee leaderboard + export.

## #/campaigns Campaigns
"Call a list in your calling hours, with retries." Lists, New campaign; empty state.

## #/campaigns/new New campaign (reached via "Continue anyway")
Pre-gate modal "You need a phone number first — you can build the campaign and upload your list,
but it can't launch until the employee has its own number. The shared Outpero line is only for
test calls." (Continue anyway / Get a number). Form header "Nothing is dialled until you launch."
Stepper: Who · Contacts · When · Calls at once · Retries · Consent (ticks as sections fill).
Right sticky Summary (Employee, Calls from, Contacts, Window, Days, Retries, Starts) + "Launch
campaign" + "You can pause the campaign at any time."
- Who's calling: Campaign name (prefilled "<role> · 28 Nov"), Employee picker, warning
  "Tarun is switched off. Switch it on before launching — everything here can still be built",
  Calls go out from (number).
- Contacts: "Any phone format. Duplicates are skipped." The employee's required columns shown as
  chips (lead_name, phone) "Spell the headers exactly as below — anything else we'll ask you
  about after the upload, and anything missing arrives empty on the call." Add contact / Import
  CSV / Paste / Load from list / Add variable / Sample CSV.
- When to call: calling window (Asia/Kolkata, "Empty means the full permitted hours"),
  timezone, calling days chips, Holidays never-call list, "Never dial numbers on your
  do-not-call list — Always on" (locked toggle), Skip recently-called numbers (N days, any
  campaign), Schedule Start now / Schedule for later, Repeat One-time/….
- Calls at once (NEW since Aug): Account channels / Assigned to other campaigns / Available /
  This campaign's share; Distribution "Automatic · share the remaining channels"; "Priority when
  capacity is limited: Normal"; live account line "0 connected · 0 preparing or ringing · 4
  awaiting confirmation"; "Channels are simultaneous calls, not starts per minute"; banners
  "Calling availability is being verified" and "Updated allocation controls are awaiting
  activation for this account".
- Retries: Auto-retry unanswered (busy, no answer, failed) toggle.
- Consent: one checkbox (contacts consented; e.g. form, opt-in, existing customers).

## #/instant Instant leads
"Every new lead, called while they still remember you." Tabs Activity / Analytics / Queue /
Sources; Connect a source; requires an instant-lead employee ("Building one is free"). 3-step
explainer (lead arrives from ad/form/CRM → employee calls right away → result here).
Analytics (#/instant/analytics): ranges 24h/7d/30d/90d; KPIs Speed to lead (median), Leads,
Answered, Qualified, Never reached (gave up), Hot waiting (queue now), Callbacks, Avg attempts;
charts "Does calling faster convert?" (qualify rate by first-call delay <30s/30–60s/1–5m/>5m),
Speed-to-lead distribution (<10s…>5m), Lead funnel, Response-time trend, When leads arrive
(hour, India time), Attempts to reach, Source performance table (Leads, Connect, Qualify, Avg
speed; click to filter).

## #/inbound Incoming calls (NEW — inbound shipped; Aug/Oct said "coming soon")
"Calls to your number, answered." Status "Not answering · 0 answered today". Setup checklist
0/3: Get a phone number · Hire a receptionist ("Answers calls, books and takes messages") ·
Attach it to your number. Tabs Overview / Calls / Messages / Missed callers. "Who answers",
"Which number rings whom (0/0 live)", "Hear it yourself — ring your number, or test in the
browser" (Test call).

## #/numbers Numbers & channels
"Your number is who customers see." "No number yet — you need one to go live. Until then, test
calls use a shared line." Choose a number: Mobile / Landline tabs, search, list of +91 mobile
numbers each "Mobile · ₹649/mo" (20 of 50, Load more), pick then Next. "Calls at once: 0 of 8
calls at once". Rules card "Before you start calling": only consenting people, no bought or
scraped lists; calling hours fixed by Outpero (bulk 9 AM–9 PM, instant callbacks 6 AM–10 PM);
opt-outs added to DNC automatically; "your business is the caller"; DND/DLT may apply; Learn more.

## #/billing Credits & billing
"1 credit = ₹1. Credits never expire." KPIs Credits balance (Low balance, Never expires), Spent ·
24 hours, Calls · 30 days, Last top-up. Tabs Overview / Statement / Billing details. "Spending by
employee" (7/30/90 days; Spent, Calls, Average per call, Average call length; table Employee,
Spent, Share, Calls, Minutes, Per call). Note: 30-second blocks explain why spend/talk time is a
little above the rate; unanswered never charged. "What calls cost": Standard ₹5/min (More
natural), Premium ₹6.8/min (Most lifelike); ₹0 for unanswered/busy/ringing; 30-s blocks with
worked examples (under 30 s = half a minute; 40 s = one minute); incoming calls billed the same;
phone number ₹649/mo (one per employee taking real calls); building/training/testing free; AI
actions (draft a script, a suggestion, a chat rehearsal) about ₹0.2 each; at 0 credits new calls
blocked and a live call capped to what the balance affords. "How channels work →".
(Aug: Value ₹3 tier existed and a ₹1,899/employee hire fee; both gone. Oct: ₹5/₹6.8 confirmed.)

## #/billing/add Add credits
"Packs add free credits." Talk time shown for Standard / Premium. Packs: ₹1,499 (299 min std);
₹2,999 +100 free (619 min); ₹9,999 +500 free (2,099 min); ₹24,999 +1,650 free (5,329 min);
₹50,000 +4,000 free (10,800 min). Or enter an amount. "Total with GST" shown live (₹9,999 →
₹11,798.82, i.e. 18% GST). Continue (not pressed).

## #/settings Settings
"Your business, account and callers' privacy." Tabs: General · Account & security · Remembered
callers · Do-not-call list · Credentials · Privacy & data.
General:
- Business name ("Your employees introduce themselves with it"), Default language (Telugu +
  English default).
- Smart follow-ups (one switch for two linked abilities): employees remember callers (greet a
  returning contact with what they said last time) AND book call-backs at the time asked, "with
  everything already learned"; keeps number + history only for that caller's own future calls;
  turning off keeps memory, clear it here.
- In the app: Bell / Pop-up per type: New results, Reminders to call people (waited 1h+ or
  qualified yesterday and not called), Morning brief, Milestones (first lead, 100/500/1,000
  calls), Messages from callers, Opt-outs. Always-on (cannot switch off): credits and payments,
  numbers and verification, campaigns pausing/finishing, a blocked or paused employee, call problems.
- Results and email: which results count (All / Qualified only / Off); email when a campaign
  finishes; daily results email (+ "send it on quiet days too").
- Instant email alerts: within a minute of a call ending with someone to follow up; a busy spell
  batched into one email; which results (asked for call back / qualified / interested) plus
  chosen answers from the owner's own post-call fields (e.g. Very/Somewhat/Not Interested; mark a
  field primary in Outcomes); quiet hours; max emails a day (12); "Send me a sample" with
  instructions to move it from Promotions/Spam to Primary.
- Live call updates: pop-up when an instant lead starts being called (bulk only counted in the
  top bar); per device; pause 1 hour / rest of today.
- #/settings/account: email, status, member since; Sign out; Google sign-in plus optional password ("Google keeps working").
- #/settings/memory Remembered callers: per employee; table Caller / Employee / Calls / Last outcome / Last call; banner when Smart follow-ups is off ("kept until you clear it").
- #/settings/dnc Do-not-call list: "Never dialled by any of your employees: campaigns, new-lead calls, call-backs, redials and test calls all refuse a number on this list, even when a campaign's skip setting is off." Bulk add / Add number; columns Phone, Reason, Added. (Aug docs said DNC did NOT apply to instant calls: CLOSED since.)
- #/settings/credentials Saved credentials: API keys/tokens saved once, reused by any Custom API or WhatsApp action on any employee; change once, every action picks it up next call.
- #/settings/privacy: "What you've agreed to" permanent record with date and policy version (Terms & Privacy, version 2026-07-25); "Export all calls (CSV)" with names, outcomes, summaries, captured answers and transcripts; deletion by email to support.

## #/developers (NEW since Aug: public API v1)
"Use your AI employees from anywhere — place calls from your CRM, n8n, Make or Zapier, run
campaigns, and get every outcome back by webhook. Calls keep every rule they follow today —
your number, calling hours, do-not-call and credits." Tabs Overview / API keys / Webhooks /
API activity. 3-step onboarding: create key → GET /me then a dry-run call (dials nobody) →
receive results by webhook. Quickstart in cURL / Node / Python: base https://api.outpero.com/v1,
Bearer key, Idempotency-Key on writes, POST /v1/calls {employee_id, phone, name, variables,
dry_run}. At a glance: keys, endpoints, requests and errors (30 days). Downloads: API
documentation (docs.outpero.com/#api), n8n/Make/Zapier guides (+ n8n workflows to import),
Postman collection, OpenAPI specification (docs.outpero.com/developers/openapi.json).
- Keys: "never put one in a web page or an app people can download".
- Webhooks: "signed, and retried automatically if your server is down" (Aug: unsigned URL
  token). Add endpoint dialog: URL, description, events: All events including future ones,
  call.completed (reached the person, with outcome, summary, answers, transcript),
  call.not_connected (no answer after every attempt, cancelled, or on DNC), lead.created (every
  conversation's result — single calls, campaigns and incoming calls), call.inbound_answered,
  call.inbound_missed, campaign.status_changed (started, paused, finished or stopped);
  "Include call transcripts" switch.
- API activity: every request, newest first, cleared after a while; request bodies never
  stored; filter All / Succeeded / Errors.

## Employee page (#/employees/<id>/…)
Header: initial, name, status pill, role · job · voice · credits used; switch (Paused/Live),
View results, Rehearse ("Type through a whole call — same script, same rules"), Test call, more.
Tabs: Overview · Campaigns · Call script · Training · Actions · Outcomes · Voice · Settings.
- overview: amber card "Listen to a call before you let this loose on customers — call it
  yourself two or three times — interrupt it, go quiet, ask something it wasn't expecting.
  Every real call reaches a real person and can't be undone." Going live checklist (1 of 3):
  Apply latest changes ✓ · Give it a phone number · Launch your first campaign. About this
  employee. Quick actions: Test call, Edit script, Teach an answer, Get a number. What it does:
  "Calls your lists — 0 running · 0 campaigns — Change the job in Settings."
- training: "Tell <name> something — type, or teach from a photo or your voice" (text 0.1 credits,
  photo 0.15, voice note 0.25; saving free). "What <name> knows: Facts · 3 Rules · 2" with
  filter All/Facts/Rules, search, each item typed (Fact/Rule) with a category (Pricing,
  Locations, Hours, Policy), edit/delete. Built from the 4 quick answers: Prices "Free for
  farmers"; Areas you cover "Hyderabad, Telangana" (WRONG: the business location became a
  service area); Timings "9am to 6pm" (WRONG: the calling hours became business timings);
  two Never rules. "Where <name> struggled on real calls" (auto from calls). "Try it (text)
  ₹0.20 per message". Guidance card: facts vs rules; "Ten clear facts work better than a brochure."
- actions: "During and after the call"; API actions master switch (off: no custom API or
  WhatsApp send runs; Google Calendar has its own setting); tiles Interakt, AiSensy, Meta Cloud
  API (WhatsApp), Custom API (any web API), Google Calendar, Other WhatsApp; Saved credentials.
- post-call (Outcomes): "How calls are labelled" — 4 labels each with a long editable
  definition written like a classifier prompt (Qualified = closed outright; Interested = reacted
  to THAT OFFER with interest, with explicit NOT-interested exclusions; Callback; Not interested
  = EXPLICIT spoken refusal only, with CRITICAL notes against over-labelling). "What to capture"
  — fields auto-generated for this job: Preferred Callback Time (free text), Interest Level
  (Very/Somewhat/Not Interested), Farm Name, Farm Location, First Expense, First Sale (free
  text); Add field. Post-call webhooks per employee: trigger (Every call…), URL, Add; delivery
  includes outcome, summary, captured fields (snake_case keys listed) and optional transcript.
- voice: Primary language (every call opens in it) + Also speaks (English, Hindi, Tamil,
  Kannada, Malayalam, Marathi). Ambient sound presets with descriptions (Office, Call centre,
  Restaurant/café, Quiet room, Retail store) + volume 40%. Voice list filters: language, mood
  (Authoritative, Calm, Clear, Confident, Conversational, Energetic, Expressive, Friendly,
  Professional, Soft, Warm), gender. Premium 31 voices ₹6.8/min "most natural-sounding"
  (P-codes; "OUTPERO SPECIAL · Great Telugu · <mood>" badges; one-line character notes; groups
  "Speaks Telugu" / "Other voices — may also speak Telugu"); Standard 23 ₹5/min "great everyday
  quality" (S-codes). Play button per voice. Note under Premium "Worth it for your primary
  customer-facing voice."
- settings:
  - What it does: one job at a time (Instant / Bulk / Inbound with one-line meaning); switching
    pauses the employee until the new script is applied, clears call history, saves a script
    version you can restore.
  - Incoming calls: "Answer when leads call back" (picks up where the call left off; off = a
    lead called in the last two weeks gets an automatic call-back instead); "Call back missed
    callers" (hung up before speaking or failed on our side → one call-back inside hours, never
    DNC); Opening hours (24/7 or set hours); "Hand callers to a person" (number + when; whole
    call billed); "Callers hear" separate lines for a new caller and for a lead calling back
    (300 chars, default lines); "Every caller first hears that the call is recorded."
  - General: phone number, name, role, employee ID (copy).
  - On every call: Recording notice switch; **AI disclosure (recommended)** switch — optional.
  - Call time limit chips 1m/2m/5m/10m/15m or seconds; optional wrap-up line (300).
  - "Say this and end": plays one fixed message then hangs up (no conversation) (800 chars).
  - Advanced prompting: "Power prompting — your prompt, nothing added" (drops their speaking
    style, turn-taking and language layers; keeps core safety: never invents facts, says it's
    an AI when asked, knows when to end).
  - Version history: Published version Live + timestamp. Danger zone: Start from scratch
    (rebuild script, number stays), Archive (history and leads kept).

## Inbound employee (Ishita) "Answer calls" tab (#/employees/<id>/inbound)
KPIs Calls today, Qualified (all time), Want a call back, Not reached (hung up or no answer).
Incoming calls: "Answers every call to its number"; Call back missed callers (Recommended, on by
default); Opening hours (Open 24/7 / Set hours); Hand callers to a person (number + when, e.g.
"they ask about a booking"); "Callers hear" = the opening line; "Every caller first hears that the
call is recorded." Number card ("No number attached … can't receive calls until a number is
attached", Get a number). "Want a call back" queue ("All clear"). Call log with Filters/Columns.

## Global
- Notifications drawer: tabs All / People / Updates, Mark all read, settings gear; first item
  "Your credit balance is running low — calls stop once it reaches ₹0 — top up any time from
  the Billing page".
- Search palette (Ctrl/⌘K): "Search employees and pages…" lists employees (with role) and pages.
- Support bubble (bottom right): "How's the new Outpero?" 5-face rating; "Talk to our team":
  Email support, Help & guides. (The separate purple sparkle button is "Ask Swara".)
