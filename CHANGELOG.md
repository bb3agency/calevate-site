# Changelog

Each deploy shows its version, commit and build date in the sidebar footer and on the sign-in
page (`apps/web/package.json` holds the version). Dates are IST.

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
