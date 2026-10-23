# Client screens design audit, 23 Oct 2026

Read-only audit of the client dashboard (`apps/web/src/app/c/[slug]/**` and the shared
components it renders), looking for the same class of defect the founder called "AI slop" in
the old Background sound row. Commit `be75168c` is the reference fix (`BackgroundSoundRow`,
`components/callHandlingVoiceRows.tsx`). Nothing in the source tree was changed.

## Method

- Skills followed: `audit-ai-design-slop` (the workflow, P0-P3 scale, the removal test),
  `no-ai-design-slop`, `emil-design-eng`, `critique-information-density`,
  `critique-visual-hierarchy`, `form-design`, `ux-writing`. The repo's `.claude/skills/` are
  the same skill set.
- Rendered screens: `next dev` on port 3061 (`web-mock` in `.claude/launch.json`) against a
  local stand-in API on port 8061 (scratchpad `mockaudit/server.mjs`). That API answers every
  GET in `src/lib/api/openapi.json` with an example built from the response schema, and uses
  hand-copied fixture shapes for the shell reads (`/v1/me`, `/v1/billing/wallet`, the agents,
  call handling; shapes from `tests/fixtures/sharedReads.ts`). All data is synthetic.
- Viewports: 375x812 for every screen listed below; 1280x800 for call handling and the agent
  page.
- Screens rendered: Settings > Call handling (with Pause and "If the caller goes quiet"
  open), Agents list, the agent page tabs (Overview, Voice, Settings, Training, Actions,
  Script), Meet your agent (Its job, Tell it about you, Questions), Dashboard, Calls, Call
  detail, Leads, Billing plus the Add credit drawer, New campaign step 1, Verify your
  business, Knowledge base, Your phone number, Settings > Alerts, Settings > Line protection.
- Every finding cites what was seen on screen, the source line, or both. Where the generated
  data made a screen unreadable, that is listed under "Unverified".

**Data artefacts, not findings:** "NaN Oct" on the dashboard chart, "₹inr per min",
"Label", "remediation", raw ISO timestamps on Training and Billing, "e.g. Ravi Kumar" as the
campaign name placeholder, and the "not in your agent list" option on Your phone number all
come from the generated API answers.

## Verdict

The founder's complaint is not limited to one row. The same pattern is used all over the
client side. A choice of 2-5 short options is drawn as a grid of page-wide radio cards. One
of those cards is usually a "default" option that repeats another card word for word. Next
to it sits a bare number box whose label explains the format. On a phone, every card stacks
to full width. That turns a one-tap decision into 400-600 px of scrolling (measured: the
Pause editor is 406 px tall and the "If the caller goes quiet" editor is 624 px).

The second big problem is order and length on the screens an owner opens most:

- The agent header's buttons break word by word at 375 px.
- The agent Overview puts compliance fine print above the agent's calls.
- The agent Settings tab is 5,002 px tall on a phone, with the agent's name and job at the
  bottom.
- The dashboard shows the same facts two or three times.

The fix with the most leverage is to drop the card grid and do what `be75168c` did: use
`SegmentedControl` with a one-line hint and a "use the default" checkbox, starting with the
four rows that still use `CallHandlingCard`.

## Ranked findings

Priority uses the skill's scale. P1 materially harms comprehension or interaction. P2 is
repeated slop or inconsistency. P3 is minor polish. Rank is by impact on an owner using a
phone, with the agent page, first run, calls, leads and settings first.

| # | Pri | Screen | file:line | Pattern | Why it hurts the owner | Fix (existing parts) | Effort |
|---|---|---|---|---|---|---|---|
| 1 | P1 | Settings > Call handling, and Agent > Settings (same rows) | `components/callHandlingRows.tsx:167-191` (PauseRow) | **Full-width radio cards with a redundant default.** At 1280 px, "Calevate default (0.25 s)" sits beside "Quick (0.25 s)": the same value twice. There are 5 cards plus a "Custom" card. Editor height is 406 px at 375. | Two cards that mean the same thing make the owner wonder what the difference is. The answer is "follow the default", and that is a different kind of decision from picking a speed. A one-tap choice costs half a screen. | Same shape as `be75168c`. A checkbox: "Use the {source}: Quick (0.25 s)". When it is unticked, show `SegmentedControl` with Quick / Relaxed / Unhurried / Custom, then `FIELD_HINT` with that preset's existing `hint`, inside `max-w-md`. | S |
| 2 | P1 | Same | `components/callHandlingRows.tsx:192-217` | **Bare number input in seconds** (`type="number"`, step 0.05, labelled "Seconds") for Custom. | An owner has no feel for "0.35 s" typed into a box. The valid range (0.2-3 s) only shows up as an error after a wrong entry. | `RANGE_INPUT` slider from `minMs` to `maxMs`, showing a live value as `BackgroundSoundRow` does, with "Quick" and "Unhurried" at the ends of the scale. | S |
| 3 | P1 | Same | `components/callHandlingVoiceRows.tsx:222-243, 295-318` (SilenceRow) | **Two card grids in one editor**, each with a default card. The phrase group's default card reads "Calevate default / The standard question" and sits beside "The standard question / Asked in the caller's language": the same option twice (seen at 375). Editor height is 624 px. | It is the founder's exact complaint, twice in one form. | Ask: checkbox "Use the default (asks after 8 s)", then `SegmentedControl` After a set time / Never ask. Phrase: checkbox for the default, then `SegmentedControl` Standard question / Our own words, with the text input revealed by Our own words. | M |
| 4 | P1 | Same | `components/callHandlingVoiceRows.tsx:245-265, 337-360` | **Bare number inputs.** "Seconds of quiet before asking" (5-180) is a number box. "Hang up after this many seconds of silence (empty: Calevate default, 20 s)" puts the rule for an empty box inside the label. | A label that teaches syntax ("empty: …") is a missing control. On a phone the 7-rem box with a long wrapped label reads as unfinished. | `RANGE_INPUT` with a live value for both, as in `be75168c`. The hang-up default becomes the same "use the default" checkbox, not an empty-box convention. | S |
| 5 | P1 | Same | `components/callHandlingVoiceRows.tsx:451-472` (FillerLinesRow) and `components/callHandlingRows.tsx:317-338` (HangUpRow) | **3 cards for 3 short options**, one of them the default. HangUp: default / On / Off. Filler: default / Standard lines / Our own lines. | Same pattern as #1. For HangUp, "Calevate default" and "On" are the same today. | HangUp: a default checkbox plus `ToggleSwitch` (`components/ui.tsx`), keeping the amber "stays connected, and charged" note. Filler: a default checkbox plus `SegmentedControl` Standard / Our own. | S |
| 6 | P1 | Agent page header (every tab), 375 px | `app/c/[slug]/agents/[agentId]/sections/agentHeader.tsx:139-170` | **Buttons crushed at phone width.** The switch, "Try it" and "Put it live" share one wrapping row with `flex-1`. "Put / it / live" and "Try / it" break one word per line, and the `…` menu drops to its own line. The header plus "Show me around" takes about 450 px before the tabs (screenshots of Overview, Training, Voice). | Every agent tab starts more than half a screen down. The primary action looks broken. | Below `sm`: put the switch row on its own line, then "Try it" and "Put it live" as a two-up row (`whitespace-nowrap`), with `RowMenu` beside the title. Move "Show me around" into the `RowMenu` items. Keep the existing `PRIMARY_BUTTON` / `SECONDARY_BUTTON`. | S |
| 7 | P1 | Agent > Overview | `app/c/[slug]/agents/[agentId]/sections/overview.tsx:87-103`; `agents/panels/openingNotices.tsx:200-218` | **Order is the reverse of the owner's priority.** It runs: checklist, then two compliance switches with quoted sentences, then two paragraphs of fine print ("These switches never change it…", "The notice sentences are written by us…"), then Latest calls last. The comment on line 54 says calls are "the first thing an owner checks after is it live". | The owner has to scroll past legal mechanics to see what the agent did today. | Move `<LatestCalls>` directly under the checklist. Collapse the two `text-xs` paragraphs into the section's `InfoTip`, keeping the "Write an opening line" link inline. | S |
| 8 | P1 | Agent > Settings | `app/c/[slug]/agents/[agentId]/sections/settingsTab.tsx:49-82` | **5,002 px tall at 375; identity at the bottom.** Order: call cap, worst-case cost, pause, hang-up, silence, filler, sound, handover (two paragraphs before its switch), memory (four bullet facts), Model, then "What it is" (name, job, language), then delete. | The owner who wants to rename the agent or change its language scrolls past every timing knob. | Put the "What it is" section first. Keep call handling as `SettingRow` summaries (already compact once #1-#5 land). Move the handover rules (`agents/panels/handover.tsx:190-198`) into an `InfoTip`. | S |
| 9 | P2 | Agent > Settings > What it does | `app/c/[slug]/agents/DirectionChoice.tsx:66-90` | **Icon-topped card radios for 3 short options** (Answer calls / Make calls / Both, each with a `PhoneIncoming`-style icon and a line). The same question is drawn as **plain radios** on Your phone number (`phone-number/NumberAssignment.tsx:121`) and as large cards in first run. | One question drawn three ways. The icon tiles add height without information. | `SegmentedControl` Answer / Make / Both with a `FIELD_HINT` line, in both places. | S |
| 10 | P2 | Agent > Settings > Longest one call may run | `agents/panels/delivery.tsx:126-171` vs `agents/new/BuildAgentForm.tsx:43-58` | **Same setting, two units and two save patterns.** The agent page asks for seconds in a bare number box with inline "Set limit / Cancel" buttons. New agent asks for minutes. Every other row in the section uses `SaveBar`. | "600" seconds makes the owner do arithmetic. A second save pattern in one section is the drift the quality bar warns about. | Minutes, as in `BuildAgentForm`, through a `RANGE_INPUT` or a `select` of round values, with "Use the standard limit" as the checkbox. Save through `SaveBar`. | S |
| 11 | P2 | Agent > Voice | `components/engineCatalogueList.tsx:139-150` | **A "Platform default" card** in a half-empty two-column grid above the voice list ("The voice the platform picks when none is chosen."). Call handling calls the same idea "Calevate default". | It is the redundant default option again. "Platform" is vague to an owner, and the wording differs between tabs. | A "Use the default voice" checkbox above the list, in the `be75168c` form. Use one word for the default across screens ("Calevate default", per `lib/api/callHandling.ts:70`). | S |
| 12 | P2 | Meet your agent, step 1 | `app/c/[slug]/agents/first/JobStep.tsx:62-90` | **Nested containers.** Each job card holds a grey inner box with three numbered circles ("1 A customer rings 2 It answers…"). At 375 only 1.5 of the 3 jobs are above the fold. | The first decision of the product needs scrolling to compare three options. The numbered mini-flow repeats the card's own line. | Remove the inner grey box and its numbered list. Keep the title and the one line. All three cards then fit above the fold. | S |
| 13 | P2 | Meet your agent, all steps | `agents/first/MeetYourAgent.tsx:263` ("Step 2 of 4"), `agents/first/AgentTakingShape.tsx:104` ("3 of 9"), `agents/first/QuestionsStep.tsx:141` ("Question 1 of 5") | **Three progress counters on one screen** (seen together on the questions step). | Three numbers that disagree about how far along the owner is. | Keep the rail's "Step n of 4" and the question counter. Drop the "n of 9" count from the collapsed agent card and keep the ticks inside the card. | S |
| 14 | P2 | Dashboard | `app/c/[slug]/DashboardScreen.tsx:264-330` | **Facts repeated.** "3 hot leads waiting" (What needs you) and the "Hot leads waiting" tile. "Your 2 agents · 1 switched on" and a "Your agents" list further down. "See calls" twice. "Add an agent" twice. Two metric grids (This week: 3 tiles, then 4 more). Struggles cards are repeated from Training. | The page is long on a phone and the eye cannot find what changed. Duplication reads as generated filler. | Remove the "Today at a glance" tiles that repeat What needs you or This week (Hot leads waiting, New leads). Remove the "Your 2 agents" line (the list below covers it). Keep one "Add an agent". | M |
| 15 | P2 | Dashboard vs Agents list vs agent page | `app/c/[slug]/AgentsAtAGlance.tsx:111-114`; `lib/agentState.ts:180-186`; `agents/AgentBadge.tsx:57-61` | **One agent, three status vocabularies.** The dashboard says "Working" / "Draft", the roster and agent page say "Live" / "Being set up", and `STATUS_COPY` says "Switched on". | The owner cannot match the dashboard row to the agent page. | `AgentsAtAGlance` renders `liveState(agent)`'s label and tone (the `LiveBadge` source) instead of its own words. | S |
| 16 | P2 | Settings rows on phone (call handling, agent settings, everywhere `SettingRow` shows a value) | `components/console/settingRow.tsx:48-50, 62` | **Value alignment changes with label length.** At 375, "Quick (0.25 s) Change" wraps to the left under its label, "Off Change" stays right-aligned, and "Asks after 8 s… / Change" splits over two lines with Change alone on the right. | The eye has no column to scan, so the list looks unfinished. | Below `sm`, always stack the value and action under the label, left-aligned (the `control` layout already does this). From `sm`, keep the right column. | S |
| 17 | P2 | Script (hand-written) | `agents/[agentId]/script/HandWritten.tsx:50-51, 55, 69`; `script/PipAsk.tsx:67` | **Duplicate CTA and syntax-as-instruction.** "Let Pip turn it into steps" renders twice on one screen. The hint asks the owner to "Put the greeting on the line after one that reads [OPENING]". The brief textarea is `font-mono`. | Two identical buttons make the owner ask which one to press. A markup token is a developer's convention. A monospace font makes a plain-language brief feel like code. | Keep one `AskAssistant` (PipAsk). Use the opening-line editor that already exists for the greeting instead of a token. Remove `font-mono`. | S |
| 18 | P2 | Leads, 375 px | `leads/LeadsToolbar.tsx:66-171`; `leads/LeadsScreen.tsx:230-272` | **Toolbar before data.** Two search boxes, Columns, Export, a lone ⓘ wrapped onto its own line (`LeadsToolbar.tsx:169`), a restriction note, the stage `SegmentedControl` (scrolls; "Contacted" is cut), Pip, the count with a second ⓘ, then More filters. The first lead row starts at about 590 px. | The owner opens Leads to call someone and sees controls first. | Put Columns, Export and the export ⓘ in one `RowMenu`/`Dropdown` ("…"). Join the two search boxes with "What did they ask for?" under More filters. Keep stage + count on one line. | M |
| 19 | P2 | New campaign, step 1 | `campaigns/NewCampaignSteps.tsx:122-158` (`ChoiceCards`), used for `CLASSIFICATIONS` (2 options, `campaigns/choices.tsx:85-105`) | **Page-wide cards for 2 options.** `ChoiceCards` is also a private copy of `CallHandlingCard`. | Same pattern as #1. A second component for one job is a "one way per problem" breach. | `SegmentedControl` Promotional / Service with the hint below. Keep cards only for the 5 consent sources (`ConsentProvenance.tsx`), where the neutral equal-weight list is a stated compliance requirement. | S |
| 20 | P2 | Cross-cutting | 12 card-radio implementations: `CallHandlingCard` (`callHandlingRows.tsx:53`), `ChoiceCards` (`NewCampaignSteps.tsx:122`), `DirectionChoice.tsx`, `ConsentProvenance.tsx:74`, `do-not-call/RestoreDialog.tsx:158`, `integrations/AddDestinationDrawer.tsx:88`, `lead-sources/AddSourceDrawer.tsx:135`, `forwarding/ExistingNumberGuide.tsx:147`, `forwarding/ModeChoice.tsx:41`, `llmModelPicker.tsx:251`, `engineCatalogueList.tsx` `ChoiceCard`, `agents/first/shell.tsx:90` `ChoiceCard` | **One pattern, many hand-rolled copies** around `CHOICE_CARD` classes. | Each copy drifts (check icon, hint colour `text-ink-faint` vs `text-ink-muted`, grid columns). Each one tempts the next author to use cards for 2 options. | Use one `ChoiceCard` component next to `choiceCard.ts`, kept for choices that really need a line each (5+ options, or options with previews). Short choices move to `SegmentedControl`. | M |
| 21 | P3 | Billing | `billing/BillingScreen.tsx:376-430` | **Everything on one page.** Runway, balance, unfinished payments, auto-recharge form, credit lots table, then Usage / Transactions / Statements, spending, charges and the spending limit. At 375, "About 10 days of calling left" is set larger than the balance. | The owner's two questions ("how much is left", "add credit") are answered at the top. Everything else is a long scroll of equal-weight blocks. | Move auto-recharge and the lots table into the existing `SegmentedControl` tabs (or a `Drawer`), so the page reads balance, add credit, then history. | M |
| 22 | P3 | Verify your business | `verify-business/page.tsx:164-204, 173` | **Card stack with a nested grey box** (the pledge quote is `bg-surface-muted` inside a `Card`), and the date is "23/10/2026" while every other screen says "23 Oct". | Nested containers add no hierarchy, and the date format is inconsistent. | Quote with the `border-l-2` blockquote used in `openingNotices.tsx`. Format with the shared IST formatter (`formatIST`). | S |
| 23 | P3 | Agents list | `app/c/[slug]/agents/page.tsx` (`LaneGuide`) | **An explainer card on a list page** ("How changes take effect · Show"), the same weight as the Deleted group. | It competes with the roster for attention and is read once at most. | Move it to an `InfoTip` on the page description. | S |
| 24 | P3 | Agent > Training, Knowledge base, Dashboard | `KnowledgeGaps` / `TeachBox` | **The same "Where it struggled" and "Teach your agents" blocks on three screens.** | Repetition, though each does work in its own place. | Keep it on Training and Knowledge. On the dashboard keep only the count, with a link (`hideWhenClear` already exists). | S |

## Patterns that repeat (fix once, fixes many)

1. **`CallHandlingCard` grids.** Used 15 times across `PauseRow`, `HangUpRow`, `SilenceRow`
   (two groups) and `FillerLinesRow`. One pattern migration covers findings 1, 3 and 5:
   - a "Use the {source}: {summary}" checkbox;
   - `SegmentedControl`;
   - a `FIELD_HINT` line;
   - a `max-w-md` column.

   After that, `CallHandlingCard` has no callers and is deleted.
2. **Bare `type="number"` boxes** for bounded values. Five are left in the client tree:
   - `callHandlingRows.tsx:200`;
   - `callHandlingVoiceRows.tsx:253` and `:346`;
   - `agents/panels/delivery.tsx:142`;
   - `agents/new/BuildAgentForm.tsx`.

   `RANGE_INPUT` with a live value replaces each one. The campaign "Calls at the same time"
   box (1-10) suits a `select`.
3. **The redundant default option.** The owner is shown a card for "the default" next to the
   option it resolves to:
   - call handling, four rows;
   - the "Platform default" voice card;
   - the "Platform default" model card (`engineCatalogueList.tsx:318`, admin and client).

   Use the checkbox form everywhere, with one word for the default.
4. **Card radios for 2-3 options outside call handling:**
   - direction (Answer / Make / Both);
   - campaign category (Promotional / Service).

   Both become `SegmentedControl` plus a hint.
5. **Fine print above the fold.** Explanatory `text-xs` paragraphs sit before the control
   they explain:
   - opening notices;
   - handover;
   - memory;
   - the call-cap ⓘ duplicated as a footer line.

   Put the explanation in `InfoTip` or `Section`'s `info`, and keep one line visible.
6. **Status and default wording drift:**
   - "Working" / "Live" / "Switched on";
   - "Draft" / "Being set up";
   - "Calevate default" / "Platform default".

   Use one source: `liveState`, plus `sourceLabel` in `lib/api/callHandling.ts`.

## Fix lanes (no two lanes touch the same file)

| Lane | Scope | Files it owns | Findings |
|---|---|---|---|
| A: Call-handling rows | Migrate four rows to the `be75168c` form, delete `CallHandlingCard`, fix `SettingRow` phone layout | `components/callHandlingRows.tsx`, `components/callHandlingVoiceRows.tsx`, `components/console/settingRow.tsx`, `tests/callHandling.test.tsx` | 1, 2, 3, 4, 5, 16 |
| B: Agent page | Header at 375, Overview order, Settings order and fine print, direction control, call-cap unit and save, voice default, script duplicate CTA | `agents/[agentId]/sections/agentHeader.tsx`, `sections/overview.tsx`, `sections/settingsTab.tsx`, `agents/panels/openingNotices.tsx`, `agents/panels/handover.tsx`, `agents/panels/delivery.tsx`, `agents/DirectionChoice.tsx`, `components/engineCatalogueList.tsx`, `agents/[agentId]/script/HandWritten.tsx`, `script/PipAsk.tsx`, `agents/page.tsx` | 6, 7, 8, 9, 10, 11, 17, 23 |
| C: First run | Job cards, progress counters | `agents/first/JobStep.tsx`, `agents/first/AgentTakingShape.tsx` (`MeetYourAgent.tsx` and `QuestionsStep.tsx` only if needed) | 12, 13 |
| D: Dashboard, leads, calls | Dashboard duplicates, status vocabulary, leads toolbar | `DashboardScreen.tsx`, `AgentsAtAGlance.tsx`, `KnowledgeGaps.tsx` (dashboard use only), `leads/LeadsToolbar.tsx`, `leads/LeadsScreen.tsx` | 14, 15, 18, 24 |
| E: Campaigns, billing, verify, numbers | Campaign category control, the `ChoiceCard` consolidation outside lanes A-B, billing order, verify-business nesting and date, number-assignment direction control | `campaigns/NewCampaignSteps.tsx`, `campaigns/ConsentProvenance.tsx`, `do-not-call/RestoreDialog.tsx`, `integrations/AddDestinationDrawer.tsx`, `lead-sources/AddSourceDrawer.tsx`, `components/forwarding/*`, `billing/BillingScreen.tsx`, `verify-business/page.tsx`, `phone-number/NumberAssignment.tsx`, plus a new shared `components/console/ChoiceCard.tsx` | 19, 20, 21, 22, and the phone-number half of 9 |

Ordering and dependencies:

- Lanes A-D can run in parallel.
- Lane E creates `ChoiceCard.tsx`. Lane B's `engineCatalogueList.tsx` adopts it afterwards,
  or keeps its local copy until E lands.
- Lane B's direction control and lane E's `NumberAssignment.tsx` should use the same three
  labels (Answer / Make / Both).

## Unverified

- **Agent > What it notes, Script in steps mode, Actions forms.** The generated data did not
  produce a readable state. These were not audited beyond the hand-written script view.
- **Call detail audio player.** It did not render with the mock. The rest of call detail
  looked orderly; no finding.
- **Real voice names and language notes on the Voice tab.** The mock filled labels
  generically. Only the default card and the layout are judged.
- **Lead table at 375 with real columns.** The table scrolls inside its `ScrollRegion`
  (403 px wide in a 345 px region). Whether real column widths fit was not tested.
- **Not rendered:** Settings > Team, Business profile, Lead details, Models, Phone numbers;
  Campaign steps 2-4; Agreements; Integrations; Lead sources; Do-not-call; Data rights. Only
  the source-level card-radio patterns listed above were checked there.
- **Provider names (D-679).** No voice or model provider was named on any rendered screen.
  WhatsApp (Alerts) and the calendar service logo (Actions) are the client's own channels
  and accounts, not call providers.
- **1280 px was checked only for call handling and the agent page.** Other screens are judged
  at 375.

**The single change with the largest effect:** migrate the four remaining
`CallHandlingCard` rows to the `be75168c` form (lane A). It removes the founder's named
pattern from both settings screens at once, and on a phone the call-handling editors drop
from 400-600 px each to about one screen in total.
