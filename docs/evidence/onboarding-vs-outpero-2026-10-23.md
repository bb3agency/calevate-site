# Calevate's first-run onboarding against Outpero's, and the research for a better one — 23 October 2026

**What this is.** It sets the flow a new Calevate client walks today (main at 318d5208, read from
the code) beside Outpero's as the founder walked it on 22 Oct 2026
(`outpero-onboarding-2026-10-22.md`). Then it lists the research that should shape ours and a
proposed flow. **The proposal is not built.** It waits for the founder's answers in §6.

The founder's direction, 23 Oct 2026: take Outpero's flow as the inspiration and the core, not a
copy, and build a version that is better in function, UI/UX, backend and features, and that is
backed by research on conversion.

---

## 1. Calevate today, sign-up to the phone ringing

All file references are under `apps/web/src/` and `apps/api/`.

1. **`/signup`, screen A: the account.**
   - Two ways in: Continue with Google, or a work email with a six-digit code, then name and
     password.
   - The page exists only while the console switch `self_serve_signup` is on; it defaults to off
     (`tenancy/signup.py:254-284`).
2. **`/signup`, screen B: the workspace.**
   - Business name and kind of business are required. Workspace URL and billing email are optional.
   - It creates the organization, the 7-day / 15-minute trial (`billing/trials.start_new_account_trial`)
     and the queued business-copy job. It creates no agent (D-853).
   - The success panel leads to **"Set up {name}" → `/c/{slug}/setup`**.
   - There is no tick box for terms here.
3. **The business setup wizard (D-695), 8 steps.**
   - One topic each: hours, branches, services and prices, common questions, staff, booking rules,
     who takes a call, languages.
   - Every step can be skipped. Steps 1–3 (and 7 where it applies) block only going live, never a
     test call.
   - The last screen offers **"Build your first agent"**.
4. **First agent, `/c/{slug}/agents/first` (D-854).**
   - A meter with nine pieces; "Account created" already counts as one.
   - Two doors:
     - **Pip:** a chat beside a live agent card. The owner must first tick and turn Pip on (D-788).
     - **"I'll set it up myself":** StartFromJob, with Answer my calls (locked on a trial) or Call my
       leads, a name, and the language (default Telugu).
   - The finale, **"Your agent calls you"**: a number field and "Call me". It runs `/prepare`, then
     `POST /v1/trial/calls`, and follows the call to "Your first call is done" with a link to the
     call page.
5. **Hidden blockers before that call can ring.** None of them is mentioned on the first-agent
   screen:
   - **agreements** (privacy, terms, acceptable use, DPA) accepted at `/c/{slug}/agreements`;
     getting an agent ready refuses without them (`agents/service.py:2608`);
   - **the no-cold-calls pledge**, accepted at `/verify-business`.
   - Also: calling hours 9:00–21:00 IST, India numbers only, the do-not-call list, 10 calls a day,
     15 minutes in total, each call cut at 3 minutes, one shared trial line for the whole platform.
6. **After the call.**
   - The call page shows the verdict, summary, captured details, recording and transcript.
   - Nothing marks it as a trial call. The finale shows no transcript in place.
   - The dashboard then shows FirstAgentInvite, SetupChecklist (first day only, D-852's nudges after
     that), the TrialCallPanel and WeekRecap.
7. **Other things that matter for comparison:**
   - There is no product tour anywhere in the client app.
   - No voice is chosen when an agent is created, and "Hear it" appears only after a voice is chosen.
   - The phone number for the test call is only typed: no code is sent and nothing is ticked.

**Minimum path** (email sign-up, manual door, everything skipped): about 10 screens, 6 typed
fields plus 1 menu, and about 24 clicks, including two detours (agreements, pledge) that the flow
never points to.

## 2. Outpero, 22 Oct 2026 (summary; detail in the evidence file)

Sign-up (Google) lands in a setup that takes over the dashboard. On the left is a four-step rail:
**Set them up → Describe the job → Hear & refine → Train them**, with a live "Your employee" card.

1. **The job:** one of three cards (instant lead, bulk, inbound), each with a three-chip picture.
2. **The language:** one of seven; English is always on, and one more language can be added.
3. **The brief:** typed, spoken, or a trade template (Real estate was used unchanged).
4. **The build:** "Building your AI employee", a visible four-line checklist. In the middle it asks
   up to three generated questions (business name, a trade multi-select, location), each skippable.
5. **The disclaimer:** "A few honest words". It's an AI, it only knows what you told it, it's version
   one. One tick box: the number is my own.
6. **The test call, dressed as the job:** a mock list of 500 contacts with the owner as row 1.
   "Launch calling". The phone rang in about 15 s. The founder judged it excellent: replies under
   500–600 ms, barge-in handled, natural Telugu.
7. **After the call:** "That was Gayatri's first call · version one" → Call again / Change her
   script; "Here's what she caught". The end screen: "Gayatri is on your team", +300 bonus credits on
   going live, and the credits left shown as calls left.
8. **The agent page:** a 10-step coach-mark tour.
9. **The cost:** the test call was charged at the voice's rate (₹13.60), and the tour calls it
   "free".

## 3. The distance, item by item

| Moment | Outpero | Calevate today | Gap |
|---|---|---|---|
| After sign-up | straight into building the agent | 8-step business wizard first | **Large.** Our first impression is a form about hours and branches, not the product |
| What the client tells us first | the JOB, then the language | hours, branches, services… | Ours asks for facts before the client knows why |
| Describing the agent | one brief (type, speak or template), then ≤3 generated questions | Pip chat (after a consent tick) or a job picker | We have no "describe it in your own words" path and no template brief by trade |
| Using the trade | template chips, generated multi-select | the kind of business is known at sign-up but not used to pre-fill the agent | We already know the trade and don't use it |
| Watching it being built | 4-line build checklist, about 10 s | none: "Create agent" and a draft appears | No labour-illusion moment |
| Voice | picked for you, no preview | none picked until Pip or the voice tab | Both weak; ours blocks the meter |
| Before the call | one disclaimer, one tick | agreements page + pledge page, neither signposted | **Large.** Two hidden detours |
| The test call | dressed as the chosen job | a plain "Call me" field | Ours doesn't show the job happening |
| Agent name | screen says Gayatri, the call says Sanjana | the agent says its own name (prompt) | We are already right |
| After the call | what it caught + Call again / Change script, end screen | "Your first call is done" + a link | Ours stops short of the reward and the next step |
| What it caught | snake_case keys, raw ISO date | human labels (extraction schema) | We are better; keep it |
| Teaching | 2 facts made from the onboarding answers | wizard answers go to the business profile, not to pinned facts | Similar in effect: the profile feeds every agent (D-689) |
| Tour | 10 steps, auto-started | none | Need a short one |
| Cost of the test call | charged, called "free" | counted against the 15 trial minutes | Ours is honest; keep it |
| Phone check | tick box | nothing | Both weak |

**Where we are already ahead, to keep:**
- typed extraction with human labels;
- the agent's name is consistent;
- calls redacted by default;
- an honest trial meter;
- practice tests and suggested fixes after a call (D-844), which Outpero has no equivalent of in
  onboarding;
- Pip for anyone who prefers to talk it through;
- compliance enforced on the server (disclosure, DNC, hours, pledge).

## 4. Research that should shape it

The evidence class is given for each item; hard rule 11 applies.

1. **Endowed progress.** People given a head start finish more often. Nunes & Drèze, *J. Consumer
   Research* 32(4), 2006, the car-wash cards. The often-quoted "about twice the completion" comes
   from secondary write-ups; the paper itself was not read here (REPORTED). Our meter's "Account
   created, 1 of 9" already does this. Outpero's rail starts at step 1 with nothing done.
2. **The IKEA effect.** People value what they built themselves, **but only if they finish it**.
   Norton, Mochon & Ariely, *J. Consumer Psychology* 2012 (abstract at scholars.duke.edu, read).
   This argues for a few real decisions by the owner, the job, the brief and the call, and against
   a long form they may abandon.
3. **The labour illusion / operational transparency.** Showing the work being done raises perceived
   value more than a bare progress bar. Buell & Norton, *Management Science* 57(9), 2011; the details
   come from secondary accounts (REPORTED). Outpero's "Reading your brief → Planning the call →
   Choosing a voice" is this effect. Ours should show the real steps it takes: the script, the voice,
   the greeting, the two notice sentences.
4. **Tours: short and started by the user.**
   - Chameleon's benchmarks (VENDOR-PUBLISHED): 3-step tours complete about 66–72% of the time;
     after 5 steps, below 50%; 7 or more steps, about 16%.
   - Tours the user starts complete far more often than ones that start themselves: 2019, "123% more
     likely"; 2024, 64% against a 33.5% average.
   - Outpero's 10-step tour starts automatically.
5. **Front-loaded tutorials don't help.** NN/g's study of 70 users on 4 apps found deck-of-cards
   tutorials gave no gain in success or time, and users saw the tasks as harder. It recommends
   help in context instead (nngroup.com/articles/mobile-tutorials, read).
6. **Show the value before asking for effort.** Several vendor guides (VENDOR-PUBLISHED, no
   peer-reviewed study found) say to get to the first value moment before asking for setup. For us
   the value moment is **hearing your own agent on your own phone**. Everything before the call
   should be only what the call needs.
7. **One question to personalise.** Hotjar's single question on expertise lifted installs 26% for
   those who answered (Appcues case study, VENDOR-PUBLISHED). Outpero's job question plays this role.
   We already ask the kind of business at sign-up and could use it more.
8. **Free test calls get abused.** A free outbound call to any typed number is the voice version of
   SMS pumping and toll fraud (Twilio Verify fraud guidance and others, VENDOR-PUBLISHED).
   - The recommended controls: verify the destination before calling, throttle per number and per
     time window, and restrict destinations to the countries served.
   - We already restrict to India and to 10 calls a day per account. We do not verify the number.
8a. **TRAI.** The TCCCPR 2018 Second Amendment (12 Feb 2025) brings autodialler and robocall
   intimation and tighter consent validity (law-firm summaries, read). Nothing found exempts or
   addresses a test call to the caller's own number. Our trial runs under the documented D-697
   reasoning and the pledge. No change is proposed on this point without the founder.
9. **Others describe-to-agent.**
   - Bolna Agent Studio: a short description becomes a call-ready agent in 5–8 minutes.
   - Smallest Atoms: four questions, then about 30 s to generate.
   - Retell: a draft can be web-called before publishing.
   - All VENDOR-PUBLISHED docs. Describe-then-generate is now the industry default; a chat is the
     less common choice.

## 5. A proposed flow (to be confirmed with the founder; not built)

**Name: "Meet your agent".** It replaces the wizard as the first thing after sign-up. The wizard
stays, reached from the checklist and Settings.

1. **The rail and the card.** The rail has four steps: **Its job → Tell it about you → Hear it →
   Make it yours**. The live agent card (D-854's `AgentTakingShape`) sits beside it the whole time.
   The meter starts done at "Account created".
2. **Its job.** Three cards, Answer my calls / Call new leads instantly / Call my list, each with a
   three-chip picture. On a trial all three are open and test-callable (D-853); the locked "Answer my
   calls" in StartFromJob is fixed. Then the language: a primary, plus the languages it also speaks.
3. **Tell it about you.** One box, with:
   - a **trade brief pre-filled from the kind of business given at sign-up**, which Outpero cannot
     do because it asks the trade later;
   - template chips for other trades;
   - optionally a microphone.
   
   Then **up to three generated questions**, each skippable. Their answers are written into the
   **business profile** (hours, branch, services), so the wizard is partly filled without being
   shown. Pip stays available as "Talk it through with Pip instead".
4. **The build, shown.** The real steps tick as they happen: writing its script, choosing a voice
   for {language}, writing its greeting, adding the AI notice. The voice is chosen for them, with
   **"Hear it" and "Change"** on the card before the call. Outpero offers no preview.
5. **One consent screen before the call.** The honest words (it's an AI; it knows only what you
   told it; this is version one), **plus, folded into the same screen**:
   - the agreements;
   - the no-cold-calls pledge;
   - "this number is mine".
   
   This replaces two hidden detours with one visible step. It needs a legal check: one tick box
   standing for several documents.
6. **The test call, dressed as the job.**
   - Call my list: "your list, you're number 1".
   - New leads: "a new enquiry just came in: you".
   - Answer my calls: "it answers as if you had rung {business}".
   - While it rings, the call is followed live. It is counted honestly against the trial minutes,
     never called "free".
7. **After the call, the reward and the next step.** "That was {name}'s first call · version one".
   - What it caught, with human labels and dates in words.
   - The summary, the recording, the transcript in place.
   - **One suggested improvement from the call** (D-844's practice tests and fixes).
   - Buttons: Call again / Change its script / Go to {name}.
   - The end screen: "{name} is on your team", ticks, trial minutes left as calls left, and "add
     credit to go live" (an incentive only if the founder decides one).
8. **Make it yours: a tour the client starts.** At most five steps on the agent page (script,
   Pip, test, teach, voice), offered as "Show me around" and never forced. Help in context
   everywhere else.
9. **What else changes:**
   - The trial label on the call page.
   - Signposting for anything that still blocks.
   - The first business-copy run is re-queued after the brief, so examples use what the owner said.

## 6. Questions for the founder

Asked in the conversation of 23 Oct 2026. The founder's answers, the same day, now **D-855**:

1. **"Meet your agent" replaces the 8-step wizard as the first run.** The wizard stays reachable from
   the dashboard checklist and Settings. Up to three generated questions fill the profile basics.
2. **The guided form is the main path.** Pip is offered as "Talk it through with Pip instead".
3. **One pre-call screen, separate short ticks:** agreements, the no-cold-calls pledge, and "this
   number is mine". Nothing hidden, nothing bundled.
4. **No phone-number code (OTP) at all.** The current typed number stays, with the 10-calls-a-day
   limit.
5. **All three jobs are open on a trial.** "Answer my calls" is tested by the agent ringing the owner
   and greeting them as if they had called the business.
6. **Speaking the brief is built now.** The owner's recording goes to **Sarvam speech-to-text**.
7. **Languages: three for now** (Telugu, Hindi, English). The founder said the rest "can be built now
   itself"; what that means is asked in §7.
8. **A go-live reward** (like Outpero's +300 credits) is **documented as a possible feature only**.
9. **The test call is shown as the call itself**, with no mock contact list.
10. **Test calls keep using the 15 free trial minutes** (each capped at 3), and the screen says so
    plainly.
11. **Phone screens first,** then desktop.
12. **Build quality:** use every installed UI/UX and backend skill.

Not answered yet: Q8 (the sign-up switch) and Q10 ("agent" or "employee"); see §7.

**Follow-up answers, 23 Oct 2026** (the founder took every recommendation):

- **Word for it:** "agent" stays; we do not switch to "employee".
- **Languages:** Tamil, Kannada, Malayalam and Marathi are built now but stay hidden from clients
  until each language has a reviewed disclosure sentence and a test call checked. Whether ThinnestAI
  supports them is asked of Ashutosh; it is UNKNOWN.
- **Spoken brief:**
  - Up to 3 recordings of 30 s each (90 s in total), with the words shown after each.
  - The audio is deleted as soon as it is turned into text.
  - The screen says the recording is turned into text and the audio is not kept, and names no
    provider (D-679).
- **Script and questions:**
  - Written by the existing script-writer ladder: the account's Gemini, then Azure, then the
    disclosed Sarvam fallback.
  - The script is applied straight away as version one, not held as a proposal.
  - The follow-up questions come from a fixed set tied to the business profile: location, what you
    offer and prices, opening hours, how bookings work, plus a trade multi-select.
- **Voice and name:**
  - The automatically picked voice is **Studio**, so clients hear the full potential (founder, 23
    Oct 2026). This reverses the earlier "Clear" recommendation. Clear is offered under "Change". If
    Studio is not ready, or the account has used its trial Studio minutes, a Clear voice is used and
    the card says so.
  - The agent's name is suggested to suit the voice and language, so the screen and the call agree;
    the owner can rename it.
- **"Call new leads instantly":** the end screen shows one line, "Connect your lead form later",
  linking to the lead-intake webhook.
- **During the call:** its state (ringing, talking, ended) and a timer; the full transcript right
  after.
- **Pip:** the D-854 chat stays as "Talk it through with Pip instead" inside the same screen; the
  two-door screen becomes the new flow.
- **Sign-up switch:** whether `self_serve_signup` is on in production is not known here. The flow
  serves new sign-ups and invited owners alike.

## 6a. Build facts gathered for D-855 (main at 318d5208, from the code)

**Already exists and will be reused:**
- **Speech-to-text.** Sarvam is already called for the knowledge teach box's voice notes
  (`apps/workers/kb_teach.py:219-240`): `saaras:v3`, `mode=codemix`, clips under 30 s, uploaded to
  `POST /v1/kb/teach/upload` (3 MB), worker job, web polls every 1.5 s. Recorder:
  `knowledge/TeachBox.tsx` (webm, 30 s).
  - Sarvam's docs, read 23 Oct 2026 at docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe:
    the REST call is for audio under 30 s; `saaras:v4` is now the default; WebM/Opus and MP4/AAC are
    accepted; te-IN, hi-IN and en-IN are supported.
  - Price: ₹0.49/min pay-as-you-go (sarvam.ai/api-pricing, read the same day; VENDOR-PUBLISHED).
  - iOS Safari records WebM/Opus only from 18.4; before that MP4/AAC, so the recorder must
    feature-detect (WebKit blog; secondary sources).
- **Starters.** Ready-made scripts per trade (`agents/starters.py`), with two jobs, `answer_calls` and
  `call_leads`, and no AI. `POST /v1/agents` with `starter` creates the agent.
- **A description-to-script writer** (`apps/workers/script_assist.py` `draft_script`). It is reached
  only through Pip as a proposal to review. The model ladder is the account's Gemini leg, then Azure,
  then the disclosed Sarvam fallback.
- **Business copy** (Gemini) with a per-business `script_brief`, and static per-trade briefs in
  `verticalExamples.ts` for 8 trades.
- **Business profile:** `PATCH /v1/business-profile`, partial by section.
- **Voices:** the operator-enabled catalogue (`GET /v1/agents/engine-catalogue`) and
  `VoicePreviewButton`.
- **Agreements:** `GET /v1/legal/readiness` and `POST /v1/legal/acceptances`, one per document, real
  session only. **Pledge:** `GET/POST /v1/compliance/outbound-pledge`.
- **Trial call:** `POST /v1/trial/calls`. An answer-only agent opens with its own receptionist line
  (D-853).
- **Instant lead calling:** the ingest webhook `POST /hooks/v1/ingest/{webhook_id}` (speed-to-lead).
- **Design system:** `StepFlow`, `WizardSteps`, `TaskSteps` (build checklist), `streaming-text`,
  `progress-bar`, `successRipple`, motion tokens, and D-854's `AgentTakingShape` / `FirstCall`.

**Must be built:**
1. A brief recording endpoint and job, separate from the knowledge teach box and its permission.
2. A job that writes up to 3 follow-up questions from the brief.
3. Mapping their answers into the business profile.
4. A route that writes the script from the brief and applies it to the new agent.
5. A third job, separating "call new leads instantly" from "call my list".
6. An automatic voice pick, because publishing refuses an agent with no voice (`VOICE_REQUIRED`).
7. A "this number is mine" record.
8. The combined pre-call screen.
9. A first-run marker and routing. `setup_started_at` cannot serve, because a profile PATCH sets it.
10. The result screen.

**Not available:** a live transcript during the call. `/v1/live` notes carry no text.

## 7. Possible features recorded, not scheduled

- **Go-live reward.** Bonus credits or minutes when the client first tops up or the agent first goes
  live on the client's own number (Outpero: +300 credits on going live on own number). The amount,
  the trigger and its money handling (append-only ledger, grant lots that expire per D-840) are for
  the founder.
