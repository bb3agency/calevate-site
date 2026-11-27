# Outpero vs Calevate: same agent built from scratch (28 Nov 2026)

Job: Rytu Khata guided app install (outbound, Telugu). Calevate side: a fresh trial account
(founder signs up). Outpero side: the founder's existing Outpero account (test business name
"Sri Estates", 50 credits). Driven by Claude in the founder's Chrome; the founder takes the
test calls. Same brief and same facts on both sides (brief.txt).

Evidence class: first-hand observation in the product, 28 Nov 2026. Screenshots in shots/.

Note: an Outpero "AI employee" and a Calevate "agent" are not the same object. An Outpero
employee bundles the job type (Instant / Bulk / Inbound), script, training, voice and calling
settings. A Calevate agent is the voice + script; campaigns (outbound lists) and inbound lines
are separate objects that use an agent. Compare by what the owner has to do and gets, not
screen for screen.

## Outpero

| # | Time (IST) | Screen | What the owner does / sees | Clicks/typing |
|---|---|---|---|---|
| O1 | 28 Nov | New employee (`#/employees/new`) | One card: "What should your AI employee do?" with a language picker (default English; Telugu picked), "Natural spoken" tick (on by default), a free-text brief box, Templates button, microphone ("Describe it by voice"), and 3 job radios: Instant (calls new leads in seconds), Bulk (works through a list), Inbound (answers incoming calls). Trade templates below (BFSI, Real estate, Coaching, Hospital, Car dealer, Interiors...). | Bulk, language Telugu, typed the 636-char brief, Continue |
| O2 | 28 Nov | Quick details 1 of 4 | "Do you charge farmers to use the app?" sub-line "So your test call sounds like your business." Free-text, Skip / Next, "Skip all and build", "Edit brief". The question is generated from the brief (it says "farmers" and "the app"). | Answer: free for farmers (founder) |
| O3 | 28 Nov | Quick details 2 of 4 | "Where is your business located?" free text. | Hyderabad, Telangana |
| O4 | 28 Nov | Quick details 3 of 4 | "When can the agent call farmers?" choices 9am-6pm / 10am-5pm / Any time / Other. Tapping a choice moves on by itself. | 9am to 6pm |
| O5 | 28 Nov | Quick details 4 of 4 | "Anything they must never say or promise?" chips: Never offer discounts / guarantee returns / quote a final price / promise a call-back time / share other customers' details, plus free text one per line. Chips fill the text box. Button "Build my employee". | the two founder picked |
| O6 | 28 Nov | Building (about 25 s) | "Building your employee... Planning the call and choosing a voice." Checklist ticks: Reading your brief, A few quick details, Planning the call step by step, Choosing a voice. No disclaimer modal this time (22 Oct had one with an own-number tick). | none |
| O7 | 28 Nov | Employee page, Call script tab | Employee "Tarun", Draft, "App Support Agent", P09 voice Telugu, 0 credits used. Buttons: Not published toggle, View results, Rehearse, Test call, Publish. Tabs: Overview, Campaigns, Call script, Training, Actions, Outcomes, Voice, Settings. Banner "Tarun isn't live yet... AI can get things wrong, so listen to a call first." An 8-step coach-mark tour opens. Script: 8 steps, 3,732 / 40,000 chars, "Telugu enhance" tick, Copy/paste. Swara panel (tap and say your change; suggestion chips). Strictness slider Flexible 2/5. "When the call ends": built-in rule + extra rules. Pre-call variables Lead Name, Phone. Full script text: outpero_script.txt. | none |

### Outpero's generated script, first read (O7)
- Opening (spoken word for word): a name check only ("Hello, am I speaking to {Lead Name}?"). Who/why comes in step 1.
- 8 steps: 1 reason for call (who, registered on website, what the app does, offer; don't-remember and busy handled inside), 2 install + login in ONE step, 3 language, 4 My Farms, 5 first expense AND first sale in one step, 6 congratulate + close, 7 busy -> call back, 8 not interested, plus an empty FAQ step. Each step: an English instruction plus one Telugu example line.
- Faults seen in the text: "it's free for farmers in Hyderabad, Telangana" (location answer misused as a condition of the price); offers "a quick WhatsApp guide" and "support 9am to 6pm" (calling hours turned into support hours; no WhatsApp action configured); examples bundle actions and ask the farmer to report back ("అయ్యాక చెప్పండి", "అయ్యిందా?"); step 4 asks farm details "one at a time" yet its example lists name, location and size together; step 5 asks the farmer for the expense to "help enter it", a data-collection framing rather than a screen walkthrough. Business name rendered in Telugu letters (రైతు ఖాతా) throughout.
- Good: ordered like the brief; don't-remember, busy and not-interested paths present; natural code-mixed Telugu (English app words kept); took 25 s and 4 questions.
| O8 | 28 Nov | 8-step coach-mark tour (auto-started) | 1 What Tarun says (draft, opening word for word, click anything to change) · 2 Change it by talking (Swara: tap the mic or type, rewrites the script, undo) · 3 Your campaigns (Campaigns tab; banner "Tarun needs a phone number to run campaigns", Get a number; counters Campaigns/Contacts called/Qualified/Running now) · 4 What it knows (Training tab: "Tell Tarun something", type or teach from a photo or voice, Teach button; costs: text 0.1 credits, photo 0.05, voice note 0.25; "Try it (text)" chat; already 3 facts + 2 rules made from the quick answers, e.g. "Prices: Free for farmers") · 5 What it can do (Actions: API actions switch off; Interakt, AiSensy, Meta Cloud API WhatsApp, Custom API, Google Calendar, Other WhatsApp; saved credentials) · 6 What it captures (Outcomes: "How calls are labelled" Qualified / Interested / Callback / Not interested with Edit wording; "What to capture" + Add field; Post-call webhooks) · 7 Its voice (Primary language Telugu, "Also speaks" English/Hindi/Tamil/Kannada/Malayalam/Marathi; Ambient sound ON, Office; voice list filtered Telugu/mood/gender; Premium voices 31 ₹6.8/min "OUTPERO SPECIAL", Standard 23; selected P09) · 8 Now hear it -> "Open the test call". | Next x7 |
| O9 | 28 Nov | Test call dialog | "Runs your latest saved script, live or not. Uses credits like any call." Two ways: "Talk here in the browser" (microphone, no phone needed) or "Call my phone" (rings from Outpero's shared test line; number box pre-filled). "Tarun has no number yet. Buy or assign one." Cost line: "Tarun's calls use 6.8 credits a minute (Premium voice). About 7 minutes of calling left." | stopped for founder OK |

### Outpero build: totals so far
- Screens from "new employee" to a callable draft: 6 (brief card, 4 quick questions, build wait), then the employee page with an auto tour.
- Owner input: 1 brief (636 chars), 4 answers (2 typed, 1 tap, 2 chips), 1 Build click. About 2 minutes of owner time; 25 s build.
- No sign-up, KYC, agreement or number step before the first test call (account already existed; test calls ride a shared line).
- Cost to test: 6.8 credits/min shown before the call.
| O10 | 28 Nov | Test call (founder, several tries) | Dialog "Ringing your phone now... The call appears in Tarun's calls once it ends", button "I've finished the call". The phone rang; the founder heard only SILENCE on every try. Afterwards the employee header reads "Ready" with the switch at "Paused" (was "Draft" / "Not published"). Conversations: 0 calls, ₹0 credits used, "No conversations yet"; balance still 50. So the failed calls were not charged and left no record, no transcript and no error shown to the owner. | Call me (founder) |

**Outpero test call result: FAILED (silence), no record, no charge, no error message.** Not retried further to save credits; cause unknown from our side (their test line or engine).

## Calevate (fresh trial account)

The founder was already signed in to Calevate, so the account step (Google or email code) was
skipped: /signup opened straight on the workspace form. A truly new client would see one more
screen first. Screenshots from here are c##.jpg (numbering continues from Outpero's).

| # | Time (IST) | Screen | What the owner does / sees | Clicks/typing |
|---|---|---|---|---|
| C1 | 28 Nov | /signup "Create your Calevate workspace" | Business name, Kind of business (8 choices: Shop/food/produce, Salon/local service, Automobile/repairs, Clinic/health, Real estate, Insurance, Education/coaching, Something else), Billing email optional. Typing the name proposes a web address (/c/rytu-khata) with Change. Right panel: an illustrated live call + lead card. "Free trial starts now, with test calls to your phone. Calling customers opens after credit and verification." | name "Rytu Khata", web address changed to rytu-khata-trial (the proposed one is the founder's live account's: no warning was shown before submit), kind "Something else", Create workspace |
| C2 | 28 Nov | "Rytu Khata is set up" (about 8 s) | What happens next: free trial started, meet your first agent, it rings your phone; go live later = add credit, verify business, choose number. "Nothing is charged during your free trial." Button Meet your agent. | Meet your agent |
| C3 | 28 Nov | /agents/first "Meet your agent" step 1 of 4 "About your business" | Header shows "Trial · 7 days · 15 min". Box "About your business" (0/4000), "Or say it" (Telugu or English, 3 x 30 s recordings), "Or add a file" (PDF, Word, Excel, CSV, text or a photo, up to 3, 20 MB). Continue; "Talk it through with Pip instead"; "Skip for now". Right: "1 of 7 ready, 14%" card (Your agent / Voice / Its first work / What it knows). Sidebar shows "Agreements 4 outstanding". | typed brief + the 4 facts (803 chars) |

**DEFECT C3-a (P1, Calevate): typing into "About your business" lost characters and gained text.**
Typing the same 803-character text that Outpero's box took intact produced 821 characters:
"Help farmers view their farm data" was put in FRONT of what was typed (no space), and about 20
keystrokes were dropped ("teir", "phne", "rytukata", "Help the install", "Hyderaad", "Never hare",
"call-ack"). Likely cause (not yet confirmed in code): the box is re-written while the owner types
(the live "Checking ... 1 of 7 ready" card / an autosave or suggestion inserting "What it knows"
example text), so keystrokes arriving during a re-render are lost. A real owner typing fast, or a
phone keyboard, gets a garbled brief that then drives the whole agent. Fixed here by setting the
text in one go; recorded as a defect to fix.
| C4 | 28 Nov | "A few details next" (about 12 s) | "Reading what you wrote... Working out what a caller would still ask"; "Skip the questions". Card 2 of 7 ready, 29%. | Continue |
| C5 | 28 Nov | Question 1 of 3 | "What are the main regional districts or areas in Telangana that you serve?" ("helps the agent confirm if the caller is in your service area"). A service-area question that does not fit an app; Outpero asked nothing like it. | skipped (fairness: not a fact Outpero got) |
| C6 | 28 Nov | Question 2 of 3 | "What languages besides Telugu should the agent offer to use?" chips Hindi / English / Kannada / Marathi. | English (Outpero's Telugu employee speaks English too) |
| C7 | 28 Nov | Question 3 of 3 | "What is one thing every caller should know about you?" generic, not read from the brief. | skipped |
| C8 | 28 Nov | Step 2 of 4 "Name and voice" | Name pre-filled "Anjali" (the founder's other account already has an agent called Anjali). First language Telugu / Hindi / English; "It also speaks" Hindi, English ticked. "Choose its voice" reveals 3 voices: Platform default, Clear: Disha (Telugu accent), Studio: Akshita (picked, "In use"), Divya. "3 of 3 voices can be chosen today." Card: 4 of 7 ready, 57%. | Choose its voice, Continue |

**DEFECT C8-a (P2, Calevate): the voice card contradicts itself.** Under "Voice: Akshita · Studio" it says "No woman's voice speaks this language yet, so it has the closest voice we have", while the list shows Akshita and Divya as "Speaks Telugu".
**GAP C8-b: voice choice.** Calevate: 3 voices, no filters, no per-voice price shown here (Studio "billed at the Studio rate"). Outpero: 31 Premium + 23 Standard Telugu voices with mood/gender filters, price per minute on the tab, ambient background sound.

| C9 | 28 Nov | Step 3 of 4 "What first?" | "What should Anjali do first? Pick one. You can add the other later." Answer my calls / Call people, each with a 3-chip picture. Asked although the brief says "Call farmers"; Outpero takes the job type on its first screen beside the brief. Picking starts "Pip is writing what it says..." | Call people |
| C10 | 28 Nov | Writing (about 30 s) | "Pip is writing what it says..." then "Written. Hear it next." Card 6 of 7, 86%. The card's "Says first" stays "Written when Pip writes its script." after the script is written (stale). | Hear it |
| C11 | 28 Nov | Step 4 of 4 "Hear it" | "Hear Anjali on your phone. It rings you as if you were the first person on your list." Box: **"No test call right now. Test calls are not available yet. Please try again later."** + "Change what it says". Three notes (it's an AI and says so when asked; only knows what you told it; version one). "It says first: Written when Pip writes its script." (still not shown). Mobile number +91. "Test calls use your 15 free trial minutes: 15 left, about 5 calls. Each call stops at 3 minutes. 10 a day." Before it rings, 6 ticks: Privacy Policy, Terms of Service, Acceptable Use, Data Processing Addendum, no-cold-calls pledge, "This number is my own". | stopped |

**BLOCKER C11-a (P0 for the trial, Calevate): no test call is possible.** The founder confirmed the cause: no shared test number is set up, so trial test calls cannot ring. A new client reaches the end of setup and cannot hear the agent at all; the message gives no reason and no date. Outpero: test call from its shared line, OR "Talk here in the browser" with the microphone (no phone, no number needed). Calevate has no browser-call option on this screen.
**GAP C11-b: a 3-minute cap per trial test call** would cut the Rytu Khata walkthrough (our real calls ran 4-5 minutes). Outpero's test call is limited only by credits (about 7 minutes left).
**GAP C11-c: six consent ticks before the first test call** (4 legal documents + pledge + own number) vs Outpero's none on this run (a single disclaimer + own-number tick on 22 Oct). Ours is the stronger compliance position (hard rule 5 / DPDP); the cost is friction at the moment of first value.
**DEFECT C11-d (P2): "It says first" never shows the opening** on step 4 even though the script is written; the owner cannot read the first line before the call.
| C12 | 28 Nov | "Change what it says" -> campaign "Your first calls" (Draft) | Lands on the campaign set-up page, not an agent page. Full read in calevate_script.txt. | none |

### Calevate's generated script, first read (C12), against Outpero's (O7)
- **No opening line at all** ("No opening line yet."). Outpero: a name-check opener. Ours would ring with nothing to say first. **DEFECT C12-a (P0).**
- 5 steps, more bundled than Outpero's 8: step 3 = open app + log in + choose Telugu; step 4 = My Farms + first expense + first sale. Step 5 "Confirm all steps are done" invites the "you finished" claim the founder's 27 Nov call showed. Outpero split language, farm and expense/sale into separate steps.
- The brief went in verbatim as the "Main task", including "Call only between 9am and 6pm" and the two never-rules; none became Quick facts (0) or calling hours ("When to call" From/To empty, 9am-9pm cap). Outpero turned the 4 answers into 3 facts + 2 rules in Training and asked the hours as a setting.
- Good: step outcomes ("done when they confirm the icon is on their home screen"); busy / no interest / technical issue branches; 5 push-back answers; Q&A per step; "free app" used where it fits (no "free in Hyderabad" mistake); no invented WhatsApp or support hours.
- The campaign page says "It rings from our test number" while step 4 said test calls are unavailable: the two screens disagree.
- Seven to-dos/blocks stand between this draft and a first real call (fix a line, credit, verify business, pledge, updated terms, confirm numbers, list source + consent date), plus "7 checks" vs "0 of 6 done" counting mismatch. **DEFECT C12-b (P2): 7 vs 6 checks.**
- "Calls at once: You set 3. Your account runs up to 1" on a campaign the owner never set: a default of 3 shown as the owner's choice. **DEFECT C12-c (P3).**
| C13 | 28 Nov | Compliance checks, "Show me" on "A line in the script needs fixing" | Clicking "Show me" changed nothing visible on screen (no scroll, no highlight). The owner is not told which line. **DEFECT C13-a (P2).** | Show me |

## Scorecard so far (28 Nov, before any Calevate call)

| Area | Outpero | Calevate | Who is ahead, by how much |
|---|---|---|---|
| Time, brief to a callable draft | ~2 min owner time, 6 screens, build 25 s | ~4 min, 9 screens (workspace, about, wait, 3 questions, name/voice, what first, writing 30 s, hear it) | Outpero, ~2x faster |
| Job type | first screen, with the brief | step 3, after name and voice, though the brief said it | Outpero |
| Follow-up questions | 4, all read from the brief and on point (price, place, hours, never-say chips) | 3: one off-target (districts served), one generic (one fact), one useful (languages) | Outpero, clearly |
| Answers turned into knowledge | 3 facts + 2 rules in Training | 0 quick facts; brief pasted as the main task; hours not applied | Outpero |
| Script structure | 8 steps, opener = name check, examples in Telugu per step | 5 steps, NO opening line, outcomes per step, push-back answers, Q&A | Mixed: ours has outcomes/branches, theirs splits steps better; our missing opening is a P0 |
| Script faults | wrong fact mixing (free "in Hyderabad"), invented WhatsApp + support hours, bundled actions in examples, "tell me when done" | heavier bundling (farm+expense+sale in one step), "confirm all steps are done" close | Roughly even; different faults |
| Voices | 54 Telugu voices, filters, price shown, ambient sound | 3 voices, contradictory note | Outpero, far |
| Hear it before going live | shared test line OR browser call; no ticks needed | blocked: no shared test number; no browser call; 6 ticks; 3-min cap | Outpero (theirs failed with silence today, but the path exists) |
| Compliance before first real call | none seen on this run | 7 gates (credit, KYC, pledge, terms, numbers, list source, consent date) | Calevate stronger on law; heavier on friction |
| Input reliability | typed text intact | typed text lost ~20 characters and gained a stray phrase | Outpero; ours is a P1 bug |
| Test call result | FAILED: silence on every try, no record, no error, no charge | not possible (no shared number) | Neither heard a call |
