# Changelog

Each deploy shows its version, commit and build date in the sidebar footer and on the sign-in
page (`apps/web/package.json` holds the version). Dates are IST.

## 0.5.88 — 27-Nov-2026

- When Pip writes a script again, an opening Pip wrote earlier is checked and rewritten
  if it breaks the rules, instead of being kept as if the owner wrote it. An owner's own
  opening is still never touched.
- In a call that is not in English, the opening must be in the language's own letters
  with no English sentence; single English words callers say may stay.

## 0.5.87 — 27-Nov-2026

- Rolling back the WhatsApp follow-up migration now clears its rows before tightening the
  check, instead of failing; nothing changes on screen.

## 0.5.86 — 27-Nov-2026

- Build fix: the answering line's Pip request uses the renamed request type, and test
  fixtures carry the new example limits; nothing changes on screen.

## 0.5.85 — 27-Nov-2026

- A script Pip writes is trimmed to fit the calling system before you see it: the longest
  step-by-step lists lose their last actions first (your own step text keeps every action).
- A line in English in a Telugu or Hindi call is sent back for Pip to write again in the
  call's language.
- "Too long for the calling system" now says in one line what to do.

## 0.5.84 — 26-Nov-2026

- Build fixes for the 0.5.83 script writer; nothing changes on screen.

## 0.5.83 — 26-Nov-2026

- Pip writes a script one step at a time from a plan the code builds from your own steps.
  Your step text is kept as you wrote it, the opening keeps its language and script, a
  "now a good time?" already in the opening is not asked again, and no step gains a call
  back you did not ask for.
- Pip can write each step's example turns, and an answering line can have one part
  rewritten on its own.

## 0.5.82 — 26-Nov-2026

- Test fix: the hot-lead alert test puts its call on an answering line, since alerts follow
  the call's campaign or line; nothing changes on screen.

## 0.5.81 — 26-Nov-2026

- Test registries catch up with the engine-outage work and the opening practice check;
  nothing changes on screen.

## 0.5.80 — 26-Nov-2026

- Build fix for 0.5.79 (a test line over the length limit); nothing changes on screen.

## 0.5.79 — 26-Nov-2026

- A scenario no longer keeps an extra way out that only names the step it already goes to
  (the "Not registered" card showed "App on the home screen" beside "Yes").
- The opening card on the flow shows two lines of a Telugu or Hindi opening, so "Edit in the
  script" no longer sits on top of the text.

## 0.5.78 — 26-Nov-2026

- Build fix for 0.5.77 (a sorted export list); nothing changes on screen.

## 0.5.77 — 26-Nov-2026

- After a call, a judgement about the caller (how comfortable or interested they were) is
  kept only when something the caller said shows it. The agent describing a feature is no
  longer noted as the caller's interest in it.

## 0.5.76 — 26-Nov-2026

- Every script is checked by one set of rules wherever it is written or saved. A line that
  asks the caller to say when they are done, or packs several actions into one turn, is
  flagged under that line.
- A script with a line that must be fixed can be saved but not put live or started: the
  owner sees "A line in the script needs fixing before calls can start." with Let Pip fix it
  and Show me.
- Each step can hold example turns, edited and reviewed on the script screens.

## 0.5.75 — 26-Nov-2026

- Scripts can carry example turns for each step (a few ways the agent says it, and what it
  says if the caller is confused, stuck or busy), and calls follow those examples. The old
  booking example exchanges are no longer shown to the agent, and the opening line is no
  longer repeated inside the script.

## 0.5.74 — 26-Nov-2026

- Pip no longer writes lines asking the caller to say when a step is done, lines with two
  actions, lines that open with a reaction, or a first step that asks again for permission
  the opening already got. These are now caught in Telugu, Hindi and English before you see
  a script, and noted on real calls. A confused "after what?" is read as a question, never as
  "done".

## 0.5.73 — 26-Nov-2026

- During calls the agent gives one action a turn and stops, never asks the caller to say when
  it is done, moves on only on their own "done", and repeats a step shorter when asked
  "what?". Its prompt no longer lists reaction words to open with, a step's example line is
  tone only, and slow-reply and listening words are in the call's own language.

## 0.5.72 — 26-Nov-2026

- When Pip rewrites one of its own scripts under new rules, it now replaces the script only
  when the rewrite has no warnings left, and puts it live on calls. A rewrite with warnings is
  dropped and your script stays as it was. Scripts you edited yourself are never rewritten.

## 0.5.71 — 26-Nov-2026

- A call greets the person by the newest name you gave them: a test call to a number that
  is one of your leads uses that lead's name (not your own), re-adding a number with a name
  updates it, and renaming a lead updates its campaign lists.
- A captured phone number is kept as a proper +91 number even when said with other words or
  stored as a plain number, so real mobiles are no longer flagged as not Indian.

## 0.5.70 — 26-Nov-2026

- A test call that meets the outage while getting the agent ready now counts toward pausing
  calls, so the banner shows and Call me pauses after two tries instead of timing out on
  every press.

## 0.5.69 — 26-Nov-2026

- Folding section headers read by their own name again for screen readers, and the Lead
  details page no longer has a link inside a button. Pressing anywhere on a header row still
  folds it; it looks the same.

## 0.5.68 — 26-Nov-2026

- While the phone service is not answering, the app says so in one line at the top ("Calls are
  paused ... Your calls resume by themselves"), with details behind a tap. Running campaigns show
  "Waiting for the phone service", and Call me is paused with its reason. All of it clears
  by itself when the service answers.
- A script saved on a line or campaign during an outage is kept and goes live by itself when
  the service answers again.
- Operators see the phone service's health on the ops page.

## 0.5.67 — 26-Nov-2026

- When the phone service stops answering, new calls are held everywhere instead of each one
  timing out, and resume by themselves (gently) once it answers. A call whose start we could
  not confirm is looked up before anyone is dialled again, and nobody loses an attempt or is
  marked failed because of the outage.

## 0.5.66 — 26-Nov-2026

- When the phone service stops answering, calls already placed or in progress are never
  marked failed or lost: our checks wait it out, and every call, recording, transcript and
  charge settles once it answers again, including inbound calls during a long outage.

## 0.5.65 — 26-Nov-2026

- A new campaign or line whose main task is a plain numbered list gets a first script held to
  it exactly: Pip reads each item as a named step with an outcome, in your order, and the
  draft's step outcomes say how it read them. Your main task text is never changed.

## 0.5.64 — 26-Nov-2026

- A long way out in your step list ("Still cannot log in after being guided step by step:
  offer a call back") is read as a way out, not folded into the step's outcome, and a "Rules:"
  line after your steps is no longer read as a way out.
- Pip no longer adds "cannot or will not reach it → call back" to every guided step.
- Suggested lead details never repeat one the campaign already records, such as a second
  outcome or a yes/no that another detail's choices already answer.

## 0.5.63 — 25-Nov-2026

- A side step in your list, like "Not registered", becomes a second scenario of the step
  after the one that leads to it, not a step after the last one, so the call never runs
  into it after closing.
- A call back is the last resort in every script: the agent guides the person through each
  step in detail, and Pip adds no call back to a step you gave no ways out.

## 0.5.62 — 25-Nov-2026

- When you give Pip a list of steps for a script, the writer now gets your own words, not
  Pip's summary of them. Pip had been shortening such lists and dropping the outcomes, so the
  writer never saw your steps and kept the old ones.

## 0.5.61 — 25-Nov-2026

- On the script canvas each card is only as tall as its own ways out, so short cards no
  longer carry empty space. A label that jumps to another step, like "→ 3.1 Login", is a
  link: click it to open that step.

## 0.5.60 — 25-Nov-2026

- A request to Pip can be up to 4,000 characters, so a full step list with outcomes and ways
  out fits without Pip shortening it.

## 0.5.59 — 25-Nov-2026

- When you give Pip your own list of steps, the script keeps them: the same steps in the same
  order, with your outcomes and ways out. Call back and end call stay places the call ends,
  never steps of their own, and a draft that drops, repeats or reorders a step is sent back
  to Pip before you see it.

## 0.5.58 — 25-Nov-2026

- The script canvas draws a line only from one step to the very next. A way out that jumps
  further ahead or back is a label on its scenario, like "Cannot log in → 7.1 Call back", so
  no lines run under the cards any more.

## 0.5.57 — 25-Nov-2026

- The campaign script canvas is calmer: a way out that ends the call (call back, end call,
  hand over) is a small label on its step, not a line across the screen. Lines now only join
  one step to another.

## 0.5.56 — 25-Nov-2026

- When Pip writes an action out as text instead of doing it, you no longer see the code: Pip
  is sent back to do it, and if it slips twice you get one plain sentence.

## 0.5.55 — 25-Nov-2026

- When Pip's last try at a new campaign or line script still breaks a rule, you get the
  script to review with those lines marked to fix, instead of no script.
- The failed card says your script is unchanged and points to Try again.

## 0.5.54 — 25-Nov-2026

- Steps Pip writes into the old step list with their ids are moved into the steps again, as
  before 0.5.53; only loose text there is ignored.

## 0.5.53 — 25-Nov-2026

- Pip writes a campaign or line script again on its own, up to three times, when a draft
  breaks a call rule, telling itself what the last one broke. You hear only if all fail.
- A textbook word in a line Pip writes is swapped for the everyday word from the spoken
  style list, instead of failing the draft.
- A change to a script now lands in its steps: Pip no longer writes new steps into an old,
  unused list, which made a draft fail or change nothing.
- A failed draft says your script is unchanged; the reasons sit behind "Why".

## 0.5.52 — 25-Nov-2026

- Campaign sections fold like the deal screen's: a white card with a coloured left edge, and
  one header row with the chevron, a tinted icon, the section's name in its colour and its
  description beside it. Folded, a section is just that row.

## 0.5.51 — 25-Nov-2026

- Agents keep each sentence to ten words or fewer, with full stops between, so the voice
  pauses where it should.
- The simulated calls keep a caller's last words when they hang up, so a caller who says
  "remove my number, bye" is heard and answered.

## 0.5.50 — 25-Nov-2026

- The simulated-call comparison runs on the server: the speaking rules it reads now ship
  in the image.

## 0.5.49 — 25-Nov-2026

- Each campaign and Inbound line guides callers on their phone when its own script does,
  whatever the agent's screen switch says; a booking line on the same agent no longer
  gets screen guidance.
- "Can you see it?" is asked after a silence only where the script guides the phone;
  elsewhere the agent asks whether they are still on the line.
- A campaign test call carries your name, so the agent greets you by it instead of
  asking.

## 0.5.48 — 25-Nov-2026

- Pip's script checks catch more and repair it: a step line that asks the caller about
  something the agent should judge itself (their goal, interest or comfort), one line that
  asks several things under one question mark, and a step placed after the close however
  the close is named. Every script is checked once more with them.

## 0.5.47 — 25-Nov-2026

- Admin: the script scorecard counts each problem once and names which check found it; the
  simulated calls can compare the current call prompt with a rebuilt one on our model.

## 0.5.46 — 25-Nov-2026

- Pip writes better scripts: the first step says in one sentence why we are calling, then
  asks one thing; no step asks for a name the list already has or for what the agent
  should judge itself (comfort, interest, whether the goal was met); every numbered item
  of the main task gets a step; nothing comes after the close; a way out is a real
  condition, not the next step's name; one action or one question per line; the agent
  never says it will note what the caller enters themselves.
- Every script Pip wrote and nobody has edited since is rewritten once under these rules
  and put live.
- On calls: an unclear reply after an instruction no longer counts as done; the agent asks
  what the caller sees instead of repeating the step; "tell me when done" is said in new
  words each time; sample phrases are used once a call.
- Calls cost less: the reusable part of every prompt now covers the whole script.

## 0.5.45 — 25-Nov-2026

- A call page no longer claims a step the call never reached. Captured details, notes,
  "goal met", the outcome and the summary all agree with how far the call actually got;
  a goal that was missed says "The call did not get as far as <step>".
- Each captured detail must rest on something said in the call; a detail nobody talked
  about shows as Not mentioned instead of a guess.
- Admin: a fixed set of test businesses scores the script writer, and fifteen simulated
  callers score a script or prompt before it reaches real calls.

## 0.5.44 — 25-Nov-2026

- A mistake heard on a campaign's test call is now repaired on that campaign. Before, test
  calls belonged to no campaign, so every mistake on them said "Our team has been told"
  and nothing was fixed.
- Saves say whether they worked, beside the button that saved: launching a campaign,
  restoring one, renaming a line or a pinned card, sending WhatsApp templates again,
  turning booking on, team alerts, notes, business set-up, call outcomes, low-balance
  alerts and agent details. Typing while a save is out is kept; a second press no longer
  sends twice; marking several leads or calls at once reports each one.
- The account Improve page, the weekly summary and "Give callers time" update live.

## 0.5.43 — 25-Nov-2026

- Screens say only what is true: a call that never rang no longer counts as calling someone;
  narrowed calling hours link to where they can be undone; the weekly summary names the
  outgoing answer rate; a number with too little history is not called steady; a call page
  card that fails names itself.
- A suggestion you turned down while Pip was thinking stays turned down. Step outcomes held
  back by a used-up AI allowance or an outage are written once it is back, instead of never.
  The WhatsApp card no longer tells you to rewrite the main task when the real cause is an
  outage or the allowance.
- Admin console: an agent's knowledge, its "check the voice platform now" and its numbers
  read every campaign and Inbound line that carries it, and a number that rings nobody says
  why.

## 0.5.42 — 25-Nov-2026

- Save flow works the way it looks: once saved, the unsaved changes clear and "Saved" shows;
  if it is refused, the reason shows right beside the button and your changes stay.
- A new Improve page in the sidebar looks across all your campaigns and Inbound lines: how
  each calling number is answering (and a warning if one may be labelled spam), a weekly
  summary Pip writes from your figures, a side-by-side of your campaigns with "Use what
  works", mistakes that repeat across campaigns, questions no agent could answer, people
  waiting on you, contact list health, cost per result, and everything Pip fixed by itself.

## 0.5.41 — 25-Nov-2026

- The call flow shows how the call goes on: a quiet dashed arrow from each scenario to the
  next step, and "Then step 3" or "Then end of call" in place of "No next yet". Your own
  Otherwise link replaces it.
- A way out written in a scenario ("if they cannot, offer to call back") is now a real branch
  you can see and change. Pip adds it when it writes a script, and existing scripts get theirs
  on their next check.

## 0.5.40 — 25-Nov-2026

- A campaign or Inbound line whose script asks the caller to do things on their phone gives
  callers time on its own: longer before a nudge, up to three nudges, and no hang-up for two
  minutes of quiet. "Give callers time" on Improve lets you switch it on or off yourself.
- Agents no longer add the voice platform's short filler whenever the caller pauses.
- Existing campaigns retry at a different time of day too, unless you changed their retries.
- A new second-opening test counts only calls made after it starts.
- Only the account owner can set up a campaign's WhatsApp follow-up, as on the WhatsApp page.

## 0.5.39 — 25-Nov-2026

- After giving the caller something to do, the agent invites them to say when it is done and
  waits; it never asks "is it done?" in the same breath. Script repair rewrites lines that did,
  Pip's writer never writes them, and the call page names it when it happens.
- Improve gains one-press fixes: call only in the hours people answer (counted by people, not
  dials, inside 9 am–9 pm, with Undo), retries at a different time of day, a re-call draft that
  starts with the best hours and the stronger opening, and an honest second-opening test that
  says whether the list is big enough, shows the chance the second is better, and switches to
  the winner by itself with Undo.
- The WhatsApp card sets up the follow-up for this campaign: Pip writes the message and picks
  who gets it; nothing is sent until WhatsApp approves it and you switch it on.
- The admin console shows, for each campaign and Inbound line, exactly what its agent is told
  and every setting sent, and whether it has changed since the last publish. Company training
  now gives way beside a long script instead of blocking a publish, and tells you.

## 0.5.38 — 24-Nov-2026

- Improve, on every campaign and Inbound line, shows where calls go wrong: how many callers
  reached each step and where most were lost (with "Fix this step"), the mistakes on its calls
  and whether each is fixed in the script, how many hang up in the first 20 seconds compared
  with your other campaigns (with "Rewrite the opening", notices kept), why people said no
  (with "Teach an answer"), and your latest test call's review.
- Each call now notes why the person said no, as one of a few plain reasons.

## 0.5.37 — 24-Nov-2026

- Every campaign and Inbound line keeps a history of its script: who changed it (you, a Pip
  draft, a Pip repair, Pip's outcomes, a restore) and when. "Versions" lists them with Put back
  on each.
- "Put back the flow from before Pip" brings back your own last version, and says which one.
  When there is nothing of yours to put back, or it is already your version, it says so
  instead of claiming it worked. Pip's automatic passes no longer overwrite what Put back
  restores.

## 0.5.36 — 24-Nov-2026

- Pip shows its work live: a "Working" header with a timer and Stop, a one-line plan of what
  it is doing next, each lookup as a step you can open to see what it read, and "Waiting for
  you" when it needs your yes. Stop ends the answer and cancels a script draft still being
  written; nothing half-written is saved.
- A script rewrite opens right under the confirmed card in Pip's chat (and on the campaign or
  Inbound line page): it shows what Pip is doing, then the changes line by line in red and
  green, with Keep (saves and puts it live) and Discard.
- Step outcomes hold for every caller, not one case (an outcome never names only Android when
  the call covers iPhone too), and all of them use one word for the person. Pip keeps the
  outcomes it wrote up to date and never touches one you typed or edited. "Let Pip rewrite
  the outcomes" in the call flow hands today's outcomes back to Pip.
- Alerts after a call are set on each campaign and Inbound line, for its own calls only; the
  agent's page keeps who hears and the in-call team message, which now reaches every
  campaign and line of that agent.
- The call page says "Looked up your information when it was needed" and names a stuck caller
  with no lookup as a mistake, instead of counting every reply.
- Remove a link in the call flow from the link itself, the box's menu, or the "Next" chip on
  a phone, with Undo.
- The Telugu speaking guide no longer offers the agreement tag at the end of a reply.

## 0.5.35 — 24-Nov-2026

- The call flow starts with the opening: a first box shows your opening line, with arrows
  into step 1 and a "Not now" path to a call back or the end of the call. Clicking it opens
  the script to edit the opening.
- Links that go back to an earlier step or skip a step are drawn around the boxes, never
  behind them, so every arrow visibly starts at its own box.
- Across Pip's actions, a mixed-up id, a campaign in a status the action does not take, or
  a check that used to fail only after Confirm is now caught before you are asked, with a
  plain reason; Pip corrects its own wrong ids and carries on.

## 0.5.34 — 24-Nov-2026

- Pip no longer gives up with "Agent not found" when it mixes up which id goes where: it
  is told what the id really is and tries again in the same answer. Asking Pip to rewrite a
  campaign's script now works for a campaign of any status that is not archived, a
  cancelled one included.
- When Pip cannot finish, it says plainly what did not happen and why, never a raw error
  or advice that does not fit.

## 0.5.33 — 24-Nov-2026

- Pip writes the outcome of every call step that has none, so you never fill them in by
  hand; a step waits for its outcome before the call moves on to the next one.
- Each call page shows "Where the call got to": the furthest step the caller actually
  reached, and progress is counted from the steps reached, not from what the agent said.

## 0.5.32 — 24-Nov-2026

- Agents say a filler such as "okay" at most once a call and never to open a reply, so replies
  no longer all start the same way. Pip's script writer follows the same limit.
- An agent names a button or a web address once, in the caller's language, and never repeats
  it in brackets or in English letters.
- Formal words from the language's avoid list stay out of calls even when an old script line
  has them; the call page names the word, and the turn where it was said.
- An agent searches your knowledge when the caller is stuck on a step, not only when asked
  about the business.
- Pip repairs the faulty lines of an existing campaign's or Inbound line's script by itself:
  after you save it, when a real call trips on one of its lines, and in an hourly check of
  scripts not yet checked. Only the faulty lines change; openings, notices and step outcomes
  are never touched, and a campaign keeps its previous script to switch back to.
- The call page says "Fixed in your script" or "Fixing it in your script" for a mistake the
  script caused, instead of "Our team has been told".

## 0.5.31 — 24-Nov-2026

- Key moments no longer pin a whole-call detail (an installation status, a call outcome, a
  progress) to one line the caller said; past calls lose those wrong pins too.
- A status or progress detail names only the furthest step the caller actually confirmed,
  never a later or finished state the call did not reach.

## 0.5.30 — 24-Nov-2026

- Every button that runs something shows the loading circle while it runs, across the client
  app and the admin console: saves, sends, sign-in codes, Pip's rewrites (Rewrite now keeps
  spinning while Pip is still writing), pagers and dialogs. Buttons that only open or close
  something stay still and are held while the pressed one works.
- A guard test fails the build if a button ever goes back to greying out with no spinner.

## 0.5.29 — 24-Nov-2026

- Pip rewrites a campaign's or Inbound line's script when asked, from any page: it no longer
  says it cannot, sends you to change it by hand, or pastes a draft into the chat.
- Pip's chat shows divider lines and # headings cleanly instead of as *** and #.

## 0.5.28 — 24-Nov-2026

- Company training is written in fixed sections: About the business, What it offers, Who
  its customers are, How agents speak, Names, Policies, Questions callers ask, Objections.
  Every line must come from your documents, overview or edits; Pip has to quote where, and
  a line whose quote is not in them is dropped. A campaign's opening, steps and reason for
  calling have no section, so they stay in that campaign's script.
- The tab is renamed Company training (old How they speak links still open it).
- A paused or cancelled campaign no longer shows a contact as calling after its last call
  rang out.
- Number rentals, number holds and the other jobs that walk every account resume where they
  stopped instead of skipping the newest accounts when they run long.

## 0.5.27 — 24-Nov-2026

- Company training describes your business: what it is, what it does and offers and who
  its customers are. A campaign's reason for calling, goal and call steps stay in that
  campaign's script.
- When your knowledge does not say what your business does, what you offer or who your
  customers are, Pip leaves that out and asks you for it on How they speak, with a button
  to write it under About the business.

## 0.5.26 — 24-Nov-2026

- Pip reads your documents whole when it writes the company training and campaign and line
  scripts: up to 40,000 characters together instead of 20,000, so a long manual is no
  longer cut to a fifth of itself beside your other files.
- An older version of a document is no longer read beside its live version.

## 0.5.25 — 24-Nov-2026

- Pip writes a campaign or Inbound line script from everything your agents know when no
  sources are picked for it. Before, it wrote from no knowledge at all, so the business
  described in your documents never reached the script.

## 0.5.24 — 24-Nov-2026

- Pip: asking for a campaign or Inbound line script to be rewritten always reaches that
  campaign or line. Pip had paired the right campaign with the account's other agent and
  the request was refused as "does not use this agent".

## 0.5.23 — 24-Nov-2026

- Call flow: a scenario has one script box with a language switch instead of a box per
  language, so a campaign speaking seven or eight languages can write a line in each. The
  main language opens first and a dot marks any language with no line yet.

## 0.5.22 — 24-Nov-2026

Fixes from ten parallel audits.

- Billing: refunds and other credit given back count as credit added again after any credit
  has lapsed, so statements add up; in a month with a gift trial, an older unpaid fee that
  pauses calls still sends its email.
- Pack credit expiry and the evening summary reach every account, however many there are.
- Campaigns: a finished campaign completes, and unanswered calls go back on the retry list,
  even while every line is busy. A campaign's Test call is judged against its goal.
- A line silenced for a missing truthful-answer rule is not switched back on early by a
  test copy.
- Pip's first draft never replaces a script you saved meanwhile, and saving the company
  training never wipes a newer version Pip wrote; you are told to edit the new one.
- Go-live guide: "Switch it on" is not shown done while the agent is silenced.
- Archive is off for an inbound line that still answers a number, and Delete shows only on
  archived campaigns that can be deleted.
- Admin: the closing screen updates as soon as an erasure finishes.

## 0.5.21 — 24-Nov-2026

Fixes from the 23 Nov test call, for every agent and language.

- On a call: the agent asks again in new words when an answer is unclear or off the point,
  moves to the next step only once the person confirms the last one, answers only what was
  asked (no unasked reassurance), asks the person to look rather than saying all is right, and
  varies how its replies start and end. Live agents pick this up without a republish.
- Scripts Pip writes: no second "is now a good time?", the campaign's own details are
  asked (name, call-back time and other number only when needed), screens and buttons are
  called by their real names, and lines no longer all open or end alike.
- After a call: the business name is spelt as on the account, key moments pin to the line
  where a value was settled, notes run to the end of the call, "Help Required" on an outgoing
  call holds only what the person asked for, and "Not mentioned" lists only details the
  script asks. Pip's "summarise again" spells the business name too.
- Call review: replies that all end with the same words are now named.
- Deploys refuse to put nginx on a certificate that expires within a day (D-1037).

## 0.5.20 — 23-Nov-2026

- Call flow: a scenario shows a script box only for the languages its campaign speaks (and any
  language it already has a line in), so a Telugu-only campaign no longer shows an empty
  English box.

## 0.5.19 — 23-Nov-2026

- Call flow: dragging a scenario's dot onto another scenario links them even when you let go
  on its edge or arrowhead; the scenario under the pointer is highlighted while you drag, and a
  drop that links nothing says why.

## 0.5.18 — 23-Nov-2026

- A test call or publish of a script that greets the caller by name and title no longer fails
  with "script did not read back as sent": the read-back checks the script as it was sent.
- Call outcomes save on their own a moment after you stop typing; there is no Save button.

## 0.5.17 — 23-Nov-2026

- Company training is written by Pip in the background when an account's first agent is made,
  goes live at once, and is rewritten when knowledge or the business profile changes, keeping
  and improving the owner's own edits. A draft that fails its fact check is never saved.
- Each step of a call flow has an outcome the agent reaches however the call goes; the
  scenarios are examples of reaching it.
- A scenario can be switched to "Say this line exactly"; the agent then says that step's line
  word for word in the caller's language.
- Pip writes scripts without a second greeting, unreachable or misnumbered steps, name-less
  titles, dead ends after "already done", missing tasks or promises the material does not make;
  call-back steps note the time and every spelling of a name gets its pronunciation.
- Only a trial an operator gives waives the plan fee and the monthly platform fee for the months
  it touches; the sign-up trial waives neither.
- What it notes and waiting suggestions are copied onto campaigns and lines that the 0.5.3
  move left empty.

## 0.5.16 — 23-Nov-2026

- Billing (D-1033): a trial month has no monthly plan fee on the statement, spend page or
  margin; credit given back after it lapsed lowers "credit expired" instead of showing as
  credit added. Lapsed credit can no longer be given back twice, a running trial charges
  nothing on the spend page, and a prepaid model upgrade is no longer on the statement twice.
- Campaigns: a second opening under test is checked for sales wording; an archived campaign
  cannot be scheduled and is not restarted when its line comes back.
- Numbers bought through Pip or by an operator go to the first Inbound line, like a client's
  own purchase; an operator purchase is held to the price its dialog showed.
- Alerts and after-call: an owner whose WhatsApp or email alert stood down for a team alert
  that failed or was cancelled is told; a re-read of a call that ended early reaches no
  outcome; two bookings of one lead at once make one call-back; more network failures retry.
- Pip follows the screens' rules for scheduling, call-back moves, team-alert addresses, notes
  and new agents, says when nothing changed, and audits what the screens audit.
- Admin: hosted-voice consent, spoken-style publishing and rate cards are safe against two
  operators at once; cut lists say there is more; business-type changes refresh the screens.
- Client screens: an archived first line or campaign no longer stalls the first run, and a
  failed read is said instead of telling a paying account to add credit.
- Security: a sign-in that overlaps a password change gets no session, and erasing a person
  removes their number from the saved test numbers.

## 0.5.15 — 23-Nov-2026

- An owner whose hot-lead email stood down for a team alert to the same inbox is told after
  all when that team alert fails.
- After-call actions each run in their own short database transaction, so a slow WhatsApp,
  CRM or sheet send no longer holds a connection open for all of them.
- Admin identity reviews: the queue reads up to 200 and says so when more are waiting.
- The stalled-calls alarm test follows where the notes list lives since 0.5.3.

## 0.5.14 — 23-Nov-2026

- Go live: a line on your number counts as live only once its agent is switched on too, and
  the last step shows that agent's switch beside the line. Before, the guide said "You're
  live" while callers heard nothing.

## 0.5.13 — 23-Nov-2026

- Knowledge: a note put back after an unapproved edit is in use again, and adding a link
  named like an existing item adds a new item instead of replacing it.
- Erasure reaches a caller's forwarded calls, and a repeat erasure's certificate counts only
  what it erased.
- Admin: the health board's "will break" count is right, Pip's reads of a named client are
  audited, and Spoken style frees room when an added entry is retired.
- A Sheets or LeadSquared delivery waiting to retry no longer shows as failed, a moved
  call-back drops its old reason, and a broken Google connection is retried and alerted.
- A running trial's free minutes no longer appear as charges on the month's statement.
- First run: an agent made again after deletion gets its own line or campaign, and renaming
  it renames it in their scripts.

## 0.5.12 — 23-Nov-2026

- A campaign's or Inbound line's script and What it notes are checked for length when you
  save them, against what actually goes on calls, so a long list can no longer fail at Start.
- Accepting a suggested detail on a live job that could not go live says it was saved and
  offers Save again.
- The campaigns list offers Resume once credit or the limit is sorted, or a complaint review
  is confirmed.
- Suggested lead details no longer re-check, and use AI allowance, when only a caller count
  changed.

## 0.5.11 — 23-Nov-2026

- Changing the agent on a running or paused campaign now changes the voice on its calls.
- Start resumes a campaign paused by a complaint review or the spending limit once that is
  sorted, and "Make a draft for the unanswered" says when it cannot run.
- A campaign's Results break down only that campaign's own details.
- A live line whose edit did not go live offers Put it live, and a live line whose agent is
  switched off says callers hear nothing.
- Leads keep the details of every campaign and line that called them, also after a campaign
  is archived, and search finds them; test calls no longer list details as Not mentioned.
- Platform wording changes, including the 0.5.10 name fix, now reach agents that are already
  live, and a line or campaign that refuses an update is shown as held back.
- Pip never says a change was made when it was refused or is waiting for your confirm, its
  changes to what a campaign or line notes reach live calls, and a long call-back note is
  refused instead of cut.

## 0.5.10 — 23-Nov-2026

- An agent no longer says a title such as గారు on its own when the call list has no name
  for the person: a script line with the caller's name and its title now reaches the agent
  as "name and title if known".

## 0.5.9 — 23-Nov-2026

- "Accept all" on suggested lead details saves them together and updates the agent once,
  instead of once per suggestion, so it no longer sits on "Accepting…".
- Pip no longer says a script was updated when its request was refused; you see why
  nothing changed instead.
- The note Pip passes to the script writer can be up to 2,000 characters, so a detailed
  rewrite request is no longer refused for length.

## 0.5.8 — 23-Nov-2026

- Approving a spoken-style entry you did not edit now approves the built-in words and keeps
  following them, so later corrections to the built-in words still reach calls. An approval
  of words that have since changed shows as needing review again. Approvals made before this
  are converted, and reach calls when the language is next published.

## 0.5.7 — 22-Nov-2026

- A script Pip writes when a campaign or Inbound line is made is now as good as one you ask
  for later: Pip reads its first draft back against the same brief and improves it before
  you see it.
- Pip's scripts now ask for each detail on the campaign's or line's "What it notes" at the
  right step, and never ask for what the call already knows.

## 0.5.6 — 22-Nov-2026

- Suggested lead details now start from what each campaign or Inbound line is for, and skip
  questions the script asks only to guide the call. An empty list gets a full starting set,
  with "Accept all".
- A new campaign or line, and a change to its main task or script, checks its details again
  on its own once Pip is on.

## 0.5.5 — 22-Nov-2026

- Lead details now shows a card for each campaign and each Inbound line, the same "What it
  notes" editor as on their own pages. Each card links to its campaign or line.
- "New ones start with" shows the details a new campaign or line begins with. "Use on
  campaigns and lines" puts them onto the ones you tick.
- Keeping drafted details asks which campaigns and lines get them. Ones you never changed
  are ticked for you.
- Suggested changes now belong to each campaign and line, and come from its own calls.
  They show on its card and on its What it notes.

## 0.5.4 — 22-Nov-2026

- A file replaced in What your agents know is listed once in a campaign's or line's
  Sources, and a campaign that picked it reads the new version, not the old copy.

## 0.5.3 — 22-Nov-2026

- What a call writes down now belongs to the campaign or the Inbound line it is for. Each
  campaign and each line has its own "What it notes" list, edited on its own page.
- Every campaign and line starts with the list its agent used, so nothing notes less than
  before. The agent's page no longer has "What it writes down".
- "Import from another campaign" (or "another line") copies another list into the editor;
  press Save to keep it.

## 0.5.2 — 22-Nov-2026

- A campaign's Agent section now only picks the agent. Its voice and call settings are
  changed on the agent's own settings page, and every campaign's calls follow them.

## 0.5.1 — 22-Nov-2026

- The step flow no longer cuts off the first step on its left edge.

## 0.5.0 — 22-Nov-2026

- On a campaign call that opens with the second opening or by checking the person's name,
  the agent now knows those were its first words, so it does not repeat or contradict them.
- An Inbound line keeps the opening it uses when it rings someone back.

## 0.4.99 — 21-Nov-2026

- An agent that only places or only answers calls no longer carries the second opening of
  an agent that does both, so it does not greet a second time with it.

## 0.4.98 — 21-Nov-2026

- A captured detail is kept only when the caller said it: a short reply answers only the
  question just asked, and nothing is copied from the agent's own lines or the business's
  wording.
- A call that finished what it set out to do gets no made-up next step or Needs you.
- Test calls never book a call back or count toward the needs-a-person nudge.

## 0.4.97 — 21-Nov-2026

- A campaign's Sources list, the knowledge list and file uploads load at once instead of
  after several seconds of retrying.

## 0.4.96 — 21-Nov-2026

- A caller speaking the agent's own language in English letters ("Naa phone Android andi")
  keeps the call in that language; only a request or two full sentences in another switch it.

## 0.4.95 — 21-Nov-2026

- Languages follow the account: any language switched on for it can be picked in onboarding,
  new agents, the business profile, Pip and WhatsApp templates.
- Business types come from one list; the first questions follow what the business does.
- Platform wording names no trade, and health rules follow what the business really does.

## 0.4.94 — 21-Nov-2026

- Operators set the calling limits in the console: how long a follow-up stays open, calls at
  once per campaign, tries per person and the longest gap between tries. Every default is
  the value used before.
- The agent's wording variety and the pause before a filler line are console settings too.
- Booking hours follow the business's hours for each weekday, including overnight hours.

## 0.4.93 — 21-Nov-2026

- Each agent is set as Selling or Helping customers, on its Settings or through Pip. A
  happy caller is marked interested only by a selling agent; existing agents stay Selling.
- When every agent of an account helps customers, the screens, emails and daily summary say
  callers instead of leads.

## 0.4.92 — 21-Nov-2026

- Pip writes an outbound opening that says who is calling, from which business and why,
  then asks if now is a good time; the steps start from the person's yes, ask about their
  situation instead of assuming it, and close on one next step.
- Pip knows the campaign's purpose, goal, audience and how the business got the numbers,
  and its review checks every claim against a word-for-word quote from the sources; a line
  that tells a person what they did is rewritten as a question.
- Outbound scripts plan a way out at each step: busy (call back), wrong person or not
  interested (polite close), "who is this" (who and why, then ask again), and for app
  set-up calls already installed, a different phone or stuck.
- Outbound openings may be up to 160 characters, so who, why and the question fit.

## 0.4.91 — 21-Nov-2026

- Pip in the chat can change what a campaign or an Inbound line says: it asks that page's
  script writer for a draft, which waits on the page for review, after a Confirm card that
  says it uses the AI allowance. When it shows a script it read, it says it is the current
  wording, never changes.
- Note for Pip takes 1,000 characters, with a count under the box.
- A page that loses its connection during a restart keeps trying for about 15 seconds
  before it says something did not load.
- Pip rewrites a script line that opens with a reaction such as "very good", and a step
  line that greets again or asks again whether now is a good time.

## 0.4.90 — 21-Nov-2026

- A lead that reached its goal weeks ago no longer comes back as a new Goal reached item
  every time it gets another call. Goal reached items are dated by when the lead reached
  the goal.

## 0.4.89 — 21-Nov-2026

- Agents open a reply with the point itself, the answer, step or question, instead of a
  reaction such as "చాలా మంచిది అండి" on every turn.
- Pip's Telugu example lines no longer open with "సరే అండి." or "మంచిది అండి." where it
  added nothing, so the scripts it writes stop doing it too.

## 0.4.88 — 21-Nov-2026

- Telugu agents are told to talk as friends do on the phone: the English words people use,
  everyday verbs with spoken endings, never written Telugu, and అండి or గారు at most once
  a reply.
- Pip sends back a script line that says అండి, గారు, ji or sir more than once.

## 0.4.87 — 20-Nov-2026

- Telugu agents stay in Telugu when a caller's Telugu reaches them written in English
  letters. Since 0.4.82 such lines were read as English and the agent answered in English.
- On-screen steps no longer push the agent towards English: the label is said word for word
  inside a sentence in the call's language.

## 0.4.86 — 20-Nov-2026

- A call where the caller hung up early is never counted as reaching the campaign's goal,
  even when the after-call reading said it was, so it no longer moves the person to Goal
  reached.
- A test call no longer makes a lead or a Goal reached item, even for a number that once had
  a real call. Each status move now records the call that caused it.
- A test call's page no longer shows a note about why it cannot be called back.

## 0.4.85 — 20-Nov-2026

- Pip's script writer no longer keeps English words in Telugu letters from the old
  script. One of its instructions still said to write English words in the call
  language's letters, and lines it kept from the current script were left as they were.

## 0.4.84 — 20-Nov-2026

- "Add to my draft" works when Pip rewrites a script by replacing steps. The steps it
  replaced started unticked, so the new ones were added beside them, went over the twelve
  step limit and were refused. When the new steps alone would not fit, the replaced ones
  now start ticked, and the button says how many steps the choice keeps if it is over.

## 0.4.83 — 20-Nov-2026

- Saving or test-calling a Telugu script no longer fails with "script did not read back as
  sent". 0.4.82 stopped sending the invisible joining mark to the voice, but the check that
  reads the script back still looked for it.

## 0.4.82 — 20-Nov-2026

- Telugu agents write English words like "call" and "app" in English letters again, as
  they did before 23 Oct; Telugu words stay in Telugu letters.
- The invisible joining mark that sat on every word cut short on the 20 Nov call (app,
  screen and install with a Telugu ending) is no longer sent to the voice.
- Replies open with one short, complete sentence and use commas only where a sentence needs
  one, so the voice is not handed the first few words as a piece of their own.
- Practice tests flag a reply whose first sentence has a comma.

## 0.4.81 — 19-Nov-2026

- Telugu calls are checked for a reply that only reacts ("సరేనండి." and nothing else) when
  the caller needed more, and a Telugu script step made only of a reaction is flagged.
- A caller saying "ఒక్క నిమిషం", "కొంచెం ఉండండి" or "ఇక చాలు" is understood as asking
  to wait or finishing.
- Pip can take you to Settings › Call notices.

## 0.4.80 — 19-Nov-2026

- Campaigns created before 16 Nov get the files and notes they were written from back, as
  picks from What your agents know. A campaign you have already picked for is left as it is.
- A number that answers calls and had no Inbound line gets one.

## 0.4.79 — 19-Nov-2026

- Accounts whose agents had the AI or recording notice on before 0.4.78 have the account
  switch back on, and their openings say it again.
- Switching a notice on checks every opening it reaches, Inbound lines and campaigns
  included, and names the one that has no room.
- A placed call always opens with what is saved now, right after a change too.
- Starting a campaign from Pip runs the same checks as the Start button.
- Putting back a campaign's script from before Pip reaches its calls; keeping Pip's draft
  is one step.
- A long test call to your own number is never cut by a setup being handed back.
- Minutes left after a trial ends match the limit that stops calling; a gift trial's month
  bills every paid call of the month.
- Key moments read the same time on the lead page and the call page; playback lights up the
  caller's lines too.
- A summary keeps what the caller said when it drops a feeling nobody said.
- Details from your contact list fill numbers, yes/no, choices and dates too, on the lead
  page as well.
- A short answer is no longer flagged as stopping the conversation.

## 0.4.78 — 19-Nov-2026

- The AI notice and the recording notice are now one switch each for the whole account,
  under Settings › Call notices. They cover every agent, Inbound line and campaign; inbound
  calls say them in the inbound opening, placed calls in the campaign's opening.
- Every agent now adapts when an answer changes the plan instead of repeating itself, never
  stops at "OK" without a next step, asks "anything else?" once, and closes when the caller
  is done. It uses a contact's name from your list instead of asking for it.
- A reply that stops the conversation short is now flagged on the call page.
- Each of the agent's replies on a call page shows its own time, and plays from the right
  spot. Key moments point at the line that settled the answer.
- A call summary no longer says how the caller felt unless they said it, and spells your
  business's name the way you do.
- On a placed call, details your contact list already holds are shown as from the list.
- One name per captured detail, and "nothing for you to do" said once.

## 0.4.77 — 19-Nov-2026

- "This number is mine" on a campaign's or Inbound line's test call now starts unticked and
  says what it does: a test call to a number you vouch for may ring at any hour.
- Start explains a full set of calling setups with what holds each one. A test call's setup
  no longer blocks Start or putting a line live: it is handed back first.
- A test call's setup is handed back on time; before, a draft line's could stay for good.
- Getting a new agent ready no longer uses one of your calling setups.
- A new lead's first call, or Call back, that could not start for a moment is booked again
  instead of being dropped; a call that never rang no longer counts against today's test
  calls.
- Call-backs from a campaign ring from that campaign's number.
- A second opening too long to be spoken in full is refused when you save it.
- Deleting a test call says so once.
- For invoiced accounts, minutes on a free trial no longer use up the plan's included
  minutes when the spend limit is worked out.

## 0.4.76 — 19-Nov-2026

- Example text on the campaign, opening-line, scenario and voice-notes screens no longer
  names another business; it reads as an instruction any business can follow.
- A language switched on for your account is shown by its own name on the first-agent
  screens, not as Telugu.
- A new agent created without a language speaks your business's first language.
- WhatsApp messages to your callers go out in the caller's language where that message is
  approved in it.
- When you upload a contact list, the person's name is taken from a name column such as
  "Name" or "Customer name", not from "Village name" or "Business name".
- When the voice platform briefly limits calls in one account or from one number, only that
  account or number waits; other accounts keep calling.
- Admin: a client's limit on calling setups can be raised on its Numbers page. Paid test
  calls per day and the longest own-number test call are console settings.

## 0.4.75 — 19-Nov-2026

- A campaign testing a second opening rings people again. Before this, every contact of
  such a campaign went to retry without ringing.

## 0.4.74 — 19-Nov-2026

- A test call that needs a calling setup when both are in use, with no test number to fall
  back to, now says so and names what holds them, instead of "Test calls are not available
  yet".
- The test call panel checks for a free setup before saying which number it rings from. When
  both are in use it says the call rings from our test number, or why it cannot ring right
  now.

## 0.4.73 — 18-Nov-2026

- On a paid account with a phone number, every test call now rings from your own number:
  an agent's Try it, and the Test call of an Inbound line or a campaign, live or not. For a
  line or campaign that is not live yet, a test setup is made for the call and removed
  about an hour later, so it uses one of your calling slots only for that time. If both
  your calling slots are busy, the test rings from our test number and the screen says so.
  Free trials, and paid accounts without a number yet, still ring from our test number.
- Each test call panel says which number it will ring from.
- A test copy of an agent can no longer overwrite the agent's own calling setup.
- The old per-agent "start a script test" option is gone from the admin console; test
  openings on a campaign instead.

## 0.4.72 — 18-Nov-2026

- Saving a setting on an agent that has no script of its own no longer fails with "This
  agent has nothing to say yet"; the change reaches its lines and campaigns.

## 0.4.71 — 18-Nov-2026

- Call flow: each agent response, in English and in Telugu, has Hear it in the agent's
  voice, like the script lines.

## 0.4.70 — 18-Nov-2026

- Call flow's scenario editor no longer has its own agent picker and voice settings: it
  uses the campaign's agent from Set up, and asks you to choose one there (with a link to
  Agent and its settings) when the campaign has none.
- Translate with Pip is removed from the Call flow.
- Each script line now has only Hear it in the agent's voice; the "How should it sound?"
  notes and "Also teach" under each line are gone, and notes saved there earlier no longer
  reach the agent.

## 0.4.69 — 18-Nov-2026

- Admin console: a client's Numbers page can dry-run, then run, handing that client's
  agents' calling setups to the lines and campaigns that use them.

## 0.4.68 — 18-Nov-2026

- Your agents are now like staff: an agent is its name, voice, languages, actions and
  settings, and only its work holds a calling setup — each live Inbound line and each
  running or paused campaign. Your existing agents keep working exactly as before until we
  move each one's setup onto the line or campaign that uses it, which keeps your callers on
  the same setup with no gap.
- Call-backs, "Call again", "Make a call", new-lead calls and follow-ups ring through the
  campaign that found the person, or the Inbound line they called. When an agent has no
  running campaign and no live line, the call is refused with what to do: start a
  campaign or put a line live.
- An Inbound line can now call people back.
- A number on an Inbound line that is not live yet shows "Not answering", with a button to
  put the line live (or to write its script first). Nothing goes live by itself.
- Testing, chatting with and running saved tests on an agent works without it holding a
  calling setup of its own.
- New script A/B tests on a single agent are retired; test openings on a campaign instead.
  A test already running can still be ended.

## 0.4.67 — 18-Nov-2026

- A script you save on a running or paused campaign reaches its very next call; before, it
  waited until the campaign was stopped. Clearing a campaign's own call settings while it
  runs puts its calls back on the agent's settings.
- When a campaign finishes, its calling agent slot is freed at once, so the next campaign
  can start straight away.
- If a change is saved but cannot reach calls yet, the campaign screen says your change is
  kept and to save again.
- Giving an Inbound line another agent's voice moves its numbers to that voice straight
  away, even while the line is a draft. A line's test call works while its agent is
  switched off, and an action you switched off for a line never runs on its calls.
- You cannot delete an agent while one of its Inbound lines is live; choose another agent
  for the line, or delete the line, first.
- A call made by a campaign or answered by an Inbound line shows the details that campaign
  or line notes, in the call list and on the call and lead pages. A campaign's "All its
  leads" shows its own details as columns and exports them, and lead search finds them.
- Saving "How they speak" is refused, naming the line or campaign, when it would make that
  line's or campaign's script too long for calls.
- Pip explains a mistake whose fix is waiting for you on a line or campaign, instead of
  failing to read the agent's mistakes.
- **Phones:** tapping anywhere in your account shows the next screen straight away, and a
  dropped signal no longer leaves Calevate stuck on "Updating"; the page reloads by itself.
  Long text boxes open at full height, and buttons, tabs and tick boxes are easier to tap.
- Scheduling a campaign no longer uses up one of your calling agents; it takes one only when
  the campaign starts. If none is free then, its card says so and it tries again every few
  minutes. A repeating campaign gives its calling agent back between runs.
- Calls shows the campaign or Inbound line each call came from; filter by one with **From**,
  and an Inbound line's page has **All its calls**.
- Tell my team can alert on a campaign's own details.
- A number that answers with an Inbound line shows that line on Phone numbers, with a button
  to change it in Inbound.
- Calls are checked against the number they actually ring from: an agent with no number of
  its own can call from your confirmed numbers, and a campaign calling from a number you have
  not confirmed is stopped before it rings. Readiness counts those numbers too.
- A campaign is checked for offers in the script its calls actually say.
- Pip no longer offers to change an agent's own script; it points you to the line or
  campaign. Pip can set a date range on Calls again.
- Refunds and credit packs: refunding a newer pack takes back that pack's credit, and a
  retried refund can no longer let a second refund through. Forwarded calls on a number you
  took back are billed again. Trial test calls on a Clear voice no longer use Studio minutes.
- A transcript you stop sending to your CRM is no longer sent on later retries.
- Call recordings are no longer lost when storage is slow, and a new opening line you save
  while Pip adds the notices is no longer replaced.
- **Test calls:** a test call of a campaign that hasn't started, or of a draft Inbound line,
  rings from our test number and no longer needs one of your calling setups. When Start, a
  test call or putting a line live needs a setup and none is free, the message lists what is
  using each one, with a link and what frees it, and **Ask us to raise your limit** emails us.
- Fixes for failed practice tests arrive as a draft from Pip on your Inbound line or
  campaign; if your agent works on several, choose where they go. The teach box keeps facts.
- Your AI helper works on your account in the background only once you turn Pip on.
- You can stop full phone numbers being sent to a connected system from Integrations.
- When someone asks to be erased, deliveries still waiting to go to your systems that name
  them are removed too.
- A free trial test call stays free if you add credit while it is still going. Refunding the
  same amount twice is checked as a new refund, and a won dispute returns your credit to the
  packs it came from. Bank-transfer accounts get an **Ask for bank details** button.
- A test call on a running campaign rings from your own number without disturbing its calls,
  and a new number goes to your first Inbound line whose agent is still working.
- The agent page opens faster on a phone; page numbers are easier to tap.
- When an agent can't be switched on, the notice has a button to the screen that fixes it,
  and a call that was talked through no longer says "Nothing was said".

## 0.4.66 — 17-Nov-2026

- Translate with Pip works both ways for scripts: a scenario with only Telugu gets its
  English, one with only English gets its Telugu; caller and agent responses get their
  Telugu. It sits under the description in its own orange bar, says how many boxes it will
  fill (or that there is nothing to translate), and shows Pip's reason there if a run fails,
  instead of in the Script section above.
- Scenario editor in colours: the name and description (blue), the English script (blue),
  the Telugu script (amber), caller and agent responses (pink), next scenarios (purple). The
  description's tip sits on its label's line, and Next scenarios is a narrower column.

## 0.4.65 — 17-Nov-2026

- Scenario editor: English on the left and Telugu in the middle, side by side (the scripts
  and every caller and agent response), the description across both, and Next scenarios
  in the right-hand column.
- Translate into Telugu with Pip: fills every empty Telugu box (scripts and caller and
  agent responses, in all scenarios) from its English, and saves it. What you wrote in
  Telugu stays; the flow from before can be put back.

## 0.4.64 — 17-Nov-2026

- Scenario editor laid out in three columns: the name and the English script on the left,
  the description in the centre, the script in the campaign's language (Telugu) on the
  right. Hindi script boxes are off for now.
- Next scenarios sit under the description and the Telugu script, across both columns.
- Questions and answers are now Caller and agent responses: the caller's words and the
  agent's answer in English on the left, their Telugu translation beside them, one row per
  pair, with Add a caller response for more. The agent gets both languages.

## 0.4.63 — 17-Nov-2026

- Call flow: choosing a scenario no longer scrolls the page to its editor; scroll down to it
  when you want it.

## 0.4.62 — 17-Nov-2026

- Call flow: the steps take the full width, and the chosen scenario's editor sits under
  them, across the page in three columns: name, description and next scenarios; the script
  with Hear it and how it should sound; questions and answers. Choosing a box scrolls to it.
- Before Pip writes or rewrites the script (Let Pip map the scenarios, Generate, a part in
  a language), the flow you had is kept aside. Put back the flow from before Pip switches to
  it, after a confirmation; the two swap, so the newer one can be brought back the same way.

## 0.4.61 — 17-Nov-2026

- **Teach the agent how to sound.** A note written under a scenario's line in Call flow
  ("slower", "say Rytu Khata as రైతు ఖాతా") is also taught to the agent, unless you untick
  it; a note already on the scenario has Teach [agent]. The agent keeps what it was taught
  and follows it on every call: its own, every campaign's and every inbound line's, from
  the next time each is put live (Start, Test call, Put live).
- The agent's page, under its voice settings, lists How it should sound: each note, its
  language and where it was taught, with a box to teach one there and an × to stop
  following one (kept, not deleted). Up to 20 at a time.

## 0.4.60 — 17-Nov-2026

- Call flow: the scenario's Script shows the campaign's agent, with a picker to choose one
  when there is none or change it, and Adjust its voice (speed, loudness, emotion), which
  changes how the agent sounds on every call.
- Each language's line has Hear it in the agent's voice (a Studio voice; it speaks the
  start of the line and uses one of the day's samples). A Clear voice points to Test call.
- Under each line, say how it should sound ("slower", "say Rytu Khata as రైతు ఖాతా"). The
  notes are kept on the scenario and the agent follows them on the calls after Save.

## 0.4.59 — 17-Nov-2026

- **Call flow in steps and scenarios.** Each column is a step of the call, and a step holds
  one or more scenarios, numbered 2.1, 2.2 and so on. Arrows run from each scenario's green
  dot to the left of the scenarios it can go on to, green for a yes, orange for a no.
- A scenario has a name, a description, its script in English and the campaign's languages,
  any number of questions and answers, and its next scenarios (several can be ticked,
  including End the call, Hand to a person and Offer a call back).
- Add a scenario from a step's header, add a whole step at the end, or right-click a box for
  Edit, Add a scenario below, Add a scenario in the next step, Move up or down and Delete.
  Right-click a step to add to it or insert a step before it. Dragging a green dot onto a
  box links them. A scenario's Step box moves it to another step.
- Let Pip map the scenarios now writes steps with several scenarios each and links them.
- The agent gets each scenario's script lines and answers in its instructions.


## 0.4.58 — 16-Nov-2026

- **Each campaign speaks through its own calling agent**, in the voice you chose. Your
  agent's own script and the numbers it answers stay exactly as they are, and several
  campaigns can use the same agent at once. A campaign's Test call rings that campaign.
- Each campaign keeps its own **What it notes** list, on its Set up page.
- If your account has no room for another campaign's calling agent, Start tells you
  plainly and says what to do.
- **Pip writes to the kind of call you are making** (a booking, a reminder, a payment,
  feedback and more), using only what your main task and sources say. Pick a tone and add a
  note before you press Generate; press **Why?** on any part to see where it came from; to
  change one part of a kept script, press **Ask Pip to change it**. Pip marks any line your
  sources do not back, and keeps the script short enough for your agent.
- When an agent makes a mistake on real calls, the fix is written as a draft on the line or
  campaign the call was on. Review it there before it goes live.
- Changing an agent's main language points you to each line and campaign to change its
  opening.
## 0.4.57 — 16-Nov-2026

- Call flow: Undo and Redo (also Ctrl+Z and Ctrl+Y) step through your changes until Save.
- Call flow: arrows are coloured by what they say: green for a yes, orange for a no, blue for
  any other condition. Click an arrow's words to change them. Drag the words (or the dot on
  an unlabelled arrow) to move the line; Straighten puts it back. The End the call, Hand to
  a person and Offer a call back boxes can be dragged anywhere. All of it is kept on Save.
- Campaign people: the tick box replaces the ⋯ "Take off this campaign" menu.

## 0.4.56 — 16-Nov-2026

- Campaign people: a tick box per person decides who is included in the campaign, and the
  box in the header includes (or leaves out) everyone. Included people are still called by
  their own status, so people already reached, opted out or out of tries are not rung again.
- A Status column after Phone shows each person's latest result: not called yet, spoke to
  the agent and what it came to (for example the app installed), no answer or busy with
  the next try, or not included. Name and Phone sit closer together.

## 0.4.55 — 16-Nov-2026

- **Inbound lines behave like agents on every safeguard.** A line you put live answers its
  numbers straight away; actions you switch off for a line stay off; when calling credit
  runs out, the healer holds an agent or maintenance is on, every line says the short "we
  cannot take your call" message.
- **Your first agent can always be heard.** If our AI is busy or your allowance is used up,
  its first work starts from a ready-made script you can change. Setting up asks at most
  three questions, and what you tell us reaches what your agent says.
- **Buying a number says plainly when your line is still a draft**, with a Put it live
  button; with no line yet it offers to make one. Go live ends with Put it live.
- **Test calls**: if your saved numbers don't load, it says so, and Save waits, so your saved
  list is never replaced by mistake. A test call and a chat with your agent take turns. Try
  it takes you straight to a line's or campaign's own test call.
- Start campaign waits until the campaign's checks have answered. The people on a running
  campaign show again what happened to each: tries, next try and the goal.
- A note or file you add to a campaign's Sources is used the next time Pip writes, even
  while it is still being made ready. Files up to 20 MB can be added.
- Adding a file no longer uses your AI allowance on suggestions you cannot see. Pip and the
  knowledge pages point you to Inbound lines and Campaigns for what calls say.
- An account keeps up to 50 inbound lines, and a campaign or line up to 200 sources.
- The admin console shows the first agent's voice by its name.

## 0.4.54 — 16-Nov-2026

- **A new first run that starts with your business.** Tell us about it, name your agent and
  pick its voice, then choose what it does first: answer your calls, or call people. Pip
  writes what your agent says for that work and trains every agent from your words.
- **Hear an inbound line before it has a number**: open the line and press Call me under
  Test call.
- **Try it on the business.** On an agent's Training tab, Try it asks what to try it on:
  "Just the business" tries it with what your business knows and no script; one of its
  Inbound lines or campaigns opens that line's or campaign's own test call.
- An agent's checklist and readiness score ask you to give it a job, an Inbound line or a
  campaign, instead of writing an opening line. Making a new agent is three steps: name,
  voice, then give it a job.
- **A campaign's Sources come from What your agents know**: tick the ones it should use.
  "Add a file or note" on a campaign puts it in What your agents know and picks it, and
  answers to questions a campaign's calls raised go there too.
- The first agent every new account gets, on the free trial and on paid plans, can be named
  and given a voice from the admin console. Agents already made keep theirs.

## 0.4.53 — 16-Nov-2026

- Call flow: the chosen step's panel has a Step number to move it, Insert a step after, and
  Add Yes / No, which adds "They say yes" (to the next step) and "They say no" (end the call)
  as ways out to change as needed. Its ways out show open from the start.

## 0.4.52 — 16-Nov-2026

- Test call: a test call still ringing or on the line has an End call button, which hangs it
  up.

## 0.4.51 — 16-Nov-2026

- The step that reads back and closes a call is named "Finalise the call" in every script Pip
  writes, and in the starting steps of a new agent; a booking is a step of its own before it.

## 0.4.50 — 16-Nov-2026

- Call flow folds and opens from its title, remembered in this browser, and "Open full
  screen" shows it over the whole window with the step editor beside it and Save flow.

## 0.4.49 — 16-Nov-2026

- Start campaign and Stop campaign ask first. Start says who will be called; when something
  stands in the way it lists each thing, holds the start and outlines the sections to fix in
  red. A refusal from the server shows in the same box.

## 0.4.48 — 16-Nov-2026

- Mobile view on a desktop browser now shows the page. It was blocked by the page's own
  security policy, which allowed frames only from the payment provider.

## 0.4.47 — 16-Nov-2026

- A campaign starts and stops any time. Stop campaign pauses it. Start carries on from where
  it stopped: it calls the people still waiting or with tries left, never anyone already
  reached, on do-not-call, or out of tries. A campaign stopped before this change starts again
  the same way, through the same compliance checks as a first start.
- Pause, Resume, "Stop for good" and Call the unreached again are gone; Start and Stop cover
  them. Duplicate stays.
- The agent, calling hours, retries and calls at once can be changed on a stopped campaign too.

## 0.4.46 — 16-Nov-2026

- Add people saves people to a campaign in any state, including a stopped one, without starting
  it. A stopped campaign does not call them; Call the unreached again or Duplicate carries them
  into a new draft. People not yet called can be taken off in any state.

## 0.4.45 — 16-Nov-2026

- **Inbound.** A new section in the sidebar, after Campaigns: what each of your numbers says
  when someone calls, and in which agent's voice. Each line has a main task, the sources Pip
  writes from, its script, which of the agent's actions it uses, its numbers and the calls it
  took. Several numbers can share one line. Every number you already have has a line ready,
  carrying what it says today; nothing changes for callers until you put a line live. A number
  you buy to take calls goes to your first line.
- **Agents have four tabs**: Overview, Actions, Settings and Training. Voice and What it notes
  are in Settings. Scripts now live in Inbound and Campaigns, and Overview links to both.

## 0.4.44 — 16-Nov-2026

- **How they speak.** The company training is now a tab of What your agents know, not a page of
  its own: write a few lines about your business and Pip writes how every agent speaks, from
  your words and everything already on that page. There is one place to add files, links and
  notes.
- **Sources.** What a campaign works from is called Sources everywhere you see it.
- The archived campaign row's Restore button no longer spills out of its box.

## 0.4.43 — 16-Nov-2026

- Script: a Call flow chart under the script shows each step and where the call goes next,
  by what the person says. Click a step to edit it, drag between steps to add a way out, or
  add steps; Save flow keeps the changes. "Let Pip map the scenarios" writes the likely ways
  a call goes (recognises you, doesn't remember, busy, not interested…) as steps with their
  branches, for review.
- Start campaign and Stop campaign show on Set up and Progress & results in every state,
  switched off with the reason when they can't be used. The Calls tab no longer carries them.
- On a desktop browser, a Wide / Mobile switch in the top bar shows the page in a phone-sized
  frame. Wide is the default; the switch is not shown on phones.

## 0.4.42 — 16-Nov-2026

- Editing a campaign script: every part has "Generate in [language]". Pip rewrites just that
  part in the language you pick and leaves the rest as it is. The result comes back for
  review, where you keep it or edit it further.

## 0.4.41 — 16-Nov-2026

- Script: a Language dropdown beside Generate picks the language Pip writes the script in. It
  replaces the language chips.
- Editing a script: add more questions and answers, and more push-back answers. Both parts
  show even when empty.

## 0.4.40 — 16-Nov-2026

- Campaigns list: every campaign has a Duplicate button, which makes a copy as a new draft
  and opens it.

## 0.4.39 — 16-Nov-2026

- Campaign page: Duplicate sits beside the campaign's name; Call the unreached again sits in
  Where it stands; Archive is left to the campaigns list.

## 0.4.38 — 16-Nov-2026

- Add people: the contacts file box is one compact row, leaving more room for the table.
- Deploys that change the server are about 50 seconds quicker: the database step is skipped
  when no database change came with the release, and the two background services are
  checked together.

## 0.4.37 — 16-Nov-2026

- Other call settings adds calls at once (changeable while the campaign runs), the number it
  calls from (changeable on a draft) and the kind of call, with how long permission lasts.
- Add people always shows the file upload, paste and add-one controls. On a stopped campaign
  they are shown switched off, with the reason.
- The contacts table shows 10 people a page, with page buttons.

## 0.4.36 — 16-Nov-2026

- Once a campaign has started, the compliance section shows the same question and choices as
  during set-up, with the original answer and date selected and fixed.

## 0.4.35 — 16-Nov-2026

- A campaign's agent, calling hours and retries can be changed while it runs or is paused.
  A new agent takes the campaign's script straight away; if that agent is already speaking
  another campaign, the change is refused and the old agent stays.
- The compliance section no longer repeats people, calls at once, hours, number and kind of
  call beside the checks.
- The old step-by-step new-campaign form is gone; Add people is the one way to add a list.

## 0.4.34 — 16-Nov-2026

- Set up shows every section whatever the campaign's state, including Add people and the
  compliance checks.
- People can be added, and people not yet called taken off, while a campaign runs or is
  paused. Each new number is still checked against do-not-call before it is dialled. A
  promotional campaign takes new people only before it starts, because its national
  do-not-disturb check covered the list it started with.
- Once a campaign has started, the compliance section shows what was answered before the
  first call.

## 0.4.33 — 16-Nov-2026

- Calls & recordings is one Calls section: the calls and their recordings, then who was called
  and how. Before the first call it says only that there are no calls yet.

## 0.4.32 — 16-Nov-2026

- Campaign buttons (Pause, Resume, Stop, Call the unreached again, Duplicate) sit in the row
  beside Collapse all and Expand all, after Start; Call the unreached again comes after Stop.
- The list of who was called is named Calls in the Calls & recordings tab.

## 0.4.31 — 16-Nov-2026

- A started campaign's People list, with who was called and each call, moves from Set up to
  the Calls & recordings tab.
- An archived campaign's Test call section no longer says it could not find the campaign.

## 0.4.30 — 16-Nov-2026

- Test call: save up to 10 test numbers for your account and pick one to call. A number you
  call is saved for next time; remove one with its ×. The same list shows on every campaign.

## 0.4.29 — 16-Nov-2026

- A mistyped or old account address takes you to the same page in your own account instead
  of "You do not have access".

## 0.4.28 — 16-Nov-2026

- Campaign pages remember which sections you folded, in this browser, until you open or fold
  them again or press Collapse all / Expand all.

## 0.4.27 — 16-Nov-2026

- Deploys: a website build made on the server no longer edits a tracked file, which had
  stopped every deploy after it.

## 0.4.26 — 16-Nov-2026

- Campaign pages: section titles, the tabs and the chosen script languages read in white on
  their colours.

## 0.4.25 — 16-Nov-2026

- Every page you open inside the app checks for a newer version and, if there is one, opens
  on it. A page brought back with the browser's Back button is checked too.
- A tab left open for more than 2 days says a new version is ready and updates after a
  5-second countdown, unless you are typing in a field; "Not now" stops it.

## 0.4.24 — 16-Nov-2026

- **Company training.** A new page in the sidebar, above Agents. Describe your business in your
  own words and add price lists, links or notes; Pip writes the training, and you keep it, edit
  it first or discard it. Every agent is given it before its own script, and a save brings
  every agent onto it at once. Where an agent's or a campaign's own script says something
  different, that script wins on its own calls.
- Campaign pages: the Test call list waits for its answer rather than showing nothing, and a
  few small fixes the checks asked for.

## 0.4.23 — 16-Nov-2026

- The GitHub build keeps the website's build cache between deploys, so each one compiles only
  what changed.

## 0.4.22 — 16-Nov-2026

- **Faster deploys, and no blank pages while one runs.** The website is built on GitHub's
  machines instead of the server, without the lint and type checks (CI runs those), and the
  server only unpacks it. The server's build, when it still builds (a rollback, or GitHub
  unavailable), goes into its own folder and is switched in at the end, keeping the last
  version's files for two days so open pages keep working.

## 0.4.21 — 16-Nov-2026

- **Your test calls are kept in the Test call section.** Each one made from the campaign is
  listed with its time, how it went and its length, with Play recording, Open the call and
  Delete. Delete takes it off the list after a confirm; the call itself stays in the call logs.
  The list refreshes by itself while a call is in progress or its recording is on its way.

## 0.4.20 — 16-Nov-2026

- Save changes or Close in Edit script brings you back to the Script section (and onto its Edit
  script button) instead of leaving the view somewhere further down the page. The same after
  keeping Pip's script.

## 0.4.19 — 16-Nov-2026

- The script's short read uses the names Edit script uses: Opening line (when it calls), The
  goal, Steps, Quick facts and When callers push back, with counts in words instead of
  "4 · objections 4".

## 0.4.18 — 16-Nov-2026

- **The campaign tabs are coloured pills**, each with its own colour (Set up green, Progress &
  results blue, Calls & recordings orange, Questions to answer pink, Improve violet); the one you
  are on is filled in, so it is easy to see.
- **The view no longer jumps when a section folds or opens.** Collapsing or expanding a section,
  Collapse all / Expand all, and Edit, Update or Cancel on a part of the script keep what you
  pressed where it was on screen.

## 0.4.17 — 16-Nov-2026

- **Languages for the script.** The Script section has a Languages row: pick one or more of the
  languages offered. Pip writes the script and the opening line in the first one (marked
  "main"); the agent opens every call in it and switches when a caller speaks one of the others,
  following the same steps and answers. One script, not one per language.
- The language moved out of Voice & call settings into the Script section.

## 0.4.16 — 16-Nov-2026

- **Delete an archived campaign** from the Archived list, beside Restore, while the app is being
  built. Its list of people and materials are deleted; its calls, recordings and charges stay in
  call logs and bills. A console switch, "Delete campaigns that already called" (on now), turns
  this off before launch.
- **One people section on a draft:** Add people keeps the Excel/CSV upload, paste and add one,
  and lists the people already added underneath. The separate People to call section is gone; a
  started campaign shows its list as People.
- **No more blank page during a deploy.** A page that loads while a new version is being put in
  place now says "Updating Calevate…" and reloads by itself once the new version is live.

## 0.4.15 — 16-Nov-2026

- **Start campaign** sits at the top of a draft's set-up, beside Collapse all and Expand all,
  and again at the bottom after Other call settings. Once every check passes and someone is on
  the list, one press starts it. Before then it takes you to the compliance checks and says
  what is left.
- Less space between that row of buttons and the Main task section.

## 0.4.14 — 16-Nov-2026

- A draft shows **People to call** only once someone has been added.
- The compliance card lists only the regulatory checks: "Publish your agent first" is gone from
  it (the agent's own section says it is not calling yet), and so are the greyed-out Launch
  button and the line under it. Launch appears in the card once every check is done.

## 0.4.13 — 15-Nov-2026

- **One layout for every campaign, whatever its status.** The **Set up** tab opens first and
  shows the campaign as entered: main task, materials, script, agent and its settings, test
  call, people, the compliance checks and other call settings. How it is going sits in its
  own **Progress & results** tab (where it stands, results, day by day, how it calls), beside
  Calls & recordings, Questions to answer and Improve.
- **New campaign opens the full set-up straight away.** It makes the draft at once, with the
  first agent that can call, and every section has its controls from the start instead of
  empty boxes. An unused draft can be deleted from the list.

## 0.4.12 — 15-Nov-2026

- **New campaign shows every section from the start**, in the same order and colours as a draft:
  Main task, Materials, Script, Agent and its settings, then Test call, Add people, People to
  call, the compliance checks and Other call settings, blank until there is something to show.
- **Delete a draft from the campaigns list.** A draft that never called anyone has a Delete
  button beside it, behind a confirm. A campaign that has started keeps its calls, charges and
  compliance records, so it is archived instead.

## 0.4.11 — 15-Nov-2026

- **A started campaign's page folds too**, with Collapse all and Expand all at the top: Where it
  stands (green), Results (blue) and Details (violet, holding the People, Calls, Questions,
  What happened, Improve, Task/materials/script and How it calls tabs).
- **Duplicate keeps the whole campaign.** A copy now carries the main task, the script, the
  second opening, the voice & call settings and the live materials, not only the old settings.
  Pip's unreviewed suggestion is not copied.

## 0.4.10 — 15-Nov-2026

- **Add people and People to call sit above the compliance checks**, so the list is built
  before the checks are answered. The line under Launch says to add people above.
- **"From your leads" is gone from Add people.** People come from an Excel or CSV file, a
  paste, or one at a time.

## 0.4.9 — 15-Nov-2026

- **The coloured fold sections are back** (founder's choice over 0.4.8's plain headings): each
  section's name is a coloured tab on its card, over its own tinted card.
- **Every section folds now**, on the draft page and on New campaign: Main task, Materials,
  Script, Agent and its settings, Test call, the compliance checks, Add people, People to call
  and Other call settings. **Collapse all** and **Expand all** sit at the top of the page.
- **Generate is part of the Script section**, so getting a script and reading it are one place.
- **Agent and its settings** is one section: the agent you pick and the voice & call settings
  this campaign changes. **Test call** is its own section.
- **Edit script no longer asks you to add the script again.** It opens the saved script as final
  wording with Edit on each part and a Save changes button; nothing is labelled "Added".

## 0.4.8 — 15-Nov-2026

- **Campaign screens look like the rest of the console.** The list, New campaign, a draft and a
  running campaign lose their coloured cards, side stripes and shadows: sections are headings
  on white, separated by space and thin lines, like the agent page.
- Step 4 keeps its folding, **Collapse all** and **Expand all**. Each section is now a plain
  heading with an arrow instead of a coloured tab; only a status beside it keeps its colour
  (amber for checks to answer).
- One green button leads: the test call's **Call me** is outlined, so the launch button stands
  out.
- The compliance question says **Mandatory under TRAI's TCCCPR 2018 and the DPDP Act 2023**,
  with the two laws' full names behind the ⓘ. The contacts file hint is two short lines.

## 0.4.7 — 15-Nov-2026

- Step 4's sections fold. Each name sits on the edge of its card as a coloured tab: press it to
  fold the card to a thin bar and press again to open it. **Collapse all** and **Expand all**
  sit beside the step's heading. Voice & call settings (blue, folded at first, saying how many
  settings this campaign changes), Mandatory Regulatory Compliance Checks (amber), Add people
  (green), People to call (violet) and Other call settings (dark).

## 0.4.6 — 15-Nov-2026

- The compliance card asks **Where did this list come from?** directly, marked as mandatory
  under TRAI's Telecom Commercial Communications Customer Preference Regulations, 2018 and the
  Digital Personal Data Protection Act, 2023. The old checklist rows, "You can fix this" badges
  and the "Record where this list came from" heading are gone.
- Adding people is no longer a compliance check: **Add people** is its own always-open section
  (Excel, CSV, paste, one at a time, or from your leads), above **People to call**. Its button
  shows only once there is someone to add. "File tips" is gone; the file hint says other
  columns tell the agent about each person.

## 0.4.5 — 15-Nov-2026

- **Mandatory Regulatory Compliance Checks** is now a full-width card lined up with the
  Agent and test call card above it, with the launch summary inside it rather than nested in
  a second box.

## 0.4.4 — 15-Nov-2026

- **Pip's campaign script no longer gives up after one try.** When its script breaks a call
  rule, Pip now fixes it again (two rounds by default, set in the console as "Assistant: repairs
  on a campaign script") instead of handing it to the backup assistant, which could not fit a
  whole Telugu script and cut it off.
- When Pip cannot write the script, the Script section says why (a call rule it kept breaking,
  the AI not answering, Pip stopping, or the AI allowance being used up) and offers **Try
  again**. A used-up allowance links to the AI allowance page instead. Generate becomes Try again
  too, with no Dismiss needed first.
- While Pip writes, the Script section shows how long it has been and that it usually takes
  about a minute, beside Stop.

## 0.4.3 — 15-Nov-2026

- **People to call** takes an Excel sheet (.xlsx) as well as a CSV, pasted rows, or names and
  numbers typed one at a time. The sheet is read on the server and checked like a CSV.
- **Other call settings** replaces "Start later or repeat" and the "How it calls" summary: the
  hours it may call (IST, 9 am to 9 pm), an optional later start, and **If nobody answers**: try
  again at the same time the next day until they are reached, on up to 5 days.

## 0.4.2 — 15-Nov-2026

- **Pip's campaign script is checked like every Pip script.** Before you see it, the call-mistake
  checks read it and Pip rewrites what they find (three questions in one turn and the like), and
  an opening line that breaks the opening rules is written again. What Pip could not fix, or kept
  as you had it, is listed above the changes, and a script written by the backup assistant says so.
- A campaign's first script is written whole for your business from the main task and materials,
  starting from your trade's steps, instead of as a change to an empty script.
- Generate now checks your AI allowance first, and is not available while viewing as the client.
- Creating a campaign: if one material is refused, pressing again adds only the ones not yet added.

## 0.4.1 — 15-Nov-2026

- "Before you launch" is now **Mandatory Regulatory Compliance Checks**: foldable, open by
  default, with "N checks to answer" or "All checks done" on its folded line. Launch stays
  disabled until every check is answered, and the server's compliance gate refuses it anyway.

## 0.4.0 — 15-Nov-2026

- **Agents hold default settings; campaigns override them (D-994).** Step 4 gains **Voice & call
  settings**: the agent's own value for language, speaking speed, longest call, silence
  handling, re-ask wait, background sound and filler lines, and a box per setting for this
  campaign's own. Start and Test call put them on the agent with the script; a save while the
  campaign holds the agent applies at once. The agent's stored defaults never change.
- The agent's Script tab says which campaign's script it is carrying, with a link to edit it there.

## 0.3.7 — 15-Nov-2026

- Step 4 is now **Agent and test call**: the list of your agents to choose from (while the campaign
  is a draft), then **Test call**, where the chosen agent rings your phone speaking this campaign's
  script. The second-opening test left this step; what a call says belongs in the script.

## 0.3.6 — 15-Nov-2026

- A campaign file that is already in your knowledge is no longer refused as a duplicate: the
  existing copy is attached to the campaign and used.

## 0.3.5 — 15-Nov-2026

- Uploading a material: a dashed box saying **Click to choose a file, or drag it here** replaces
  the browser's plain file field, and shows the chosen file's name and size.

## 0.3.4 — 15-Nov-2026

- A long main task wraps and opens folded to six lines with **Show more** / **Show less**;
  long material notes fold to three.

## 0.3.3 — 15-Nov-2026

- A page opened while a deploy swapped the server no longer shows "This screen stopped": a
  missing code file reloads the page once onto the new build.

## 0.3.2 — 15-Nov-2026

- **Let Pip, our AI agent, generate the script:** a band with a **Generate** button between
  Materials and Script, on the new campaign page and the campaign page. Pip writes the script
  from the main task and materials; it appears below for review.

## 0.3.1 — 15-Nov-2026

- **New campaign is one page**, a complete new design: 1 Main task (Save), 2 Materials (files,
  website and video links, notes), 3 Script (who speaks it, and Create and write the script with
  Pip). The Calls & recordings, Questions to answer and Improve tabs are there from the start,
  empty until the campaign calls. The four-step wizard, its why / goal / name fields and the
  step strip are gone; the name is made from the main task.
- The campaign page's main task shows as text with **Edit**; editing gives **Save** and **Cancel**.

## 0.3.0 — 15-Nov-2026

- **Hear it first:** ring your own phone with the campaign's script before Start.
- **Test a second opening:** half the people hear it, half the script's own; goals reached are
  compared per opening. The AI and recording notices are always said with it.
- **Improve tab** on a running campaign: best hours to call (IST answer rates), the opening test,
  a draft for the people never reached, and a WhatsApp follow-up from the Follow-ups page.
- Results card adds call backs booked and opt-outs.

## 0.2.0 — 15-Nov-2026

- **Campaigns own their script (D-992).** A new campaign starts with its main task. The
  campaign page then collects materials (files, links, notes), Pip writes the script from both,
  and Start puts only that script on the chosen agent, which is the voice.
- Campaign pages gain **Calls & recordings** and **Questions to answer** tabs; an answer is kept
  as a note learned from the calls, and the next script works it in.
- Suggestion review: **Review** opens a row on a tinted ground with **Update** and **Cancel**;
  once updated, only the final wording shows and the button reads **Edit**.
- **Always the latest version:** every page checks `/version.json` on load and reloads once
  to a newer deploy; an open page offers **Update now** when one lands, and never reloads over
  unsaved work.

## 0.1.0

- Everything before versioned releases.
