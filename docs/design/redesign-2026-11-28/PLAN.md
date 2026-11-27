# Redesign, 28 Nov 2026: plan

Why: the founder built the same agent on Outpero and on Calevate side by side on 28 Nov
2026 and agreed with seven criticisms (first screen, one home per agent, the campaign
wall, the trial sidebar, builder jargon, tour and voice prices, colour). Evidence:
`docs/evidence/outpero-vs-calevate-2026-11-28/LOG.md` and `shots/` (o##.jpg Outpero,
c##.jpg Calevate). That folder is on the `rel596` worktree and not yet on main; the lane
that merges first carries it.

This plan **evolves REDESIGN-2** (`docs/design/REDESIGN-2.md`, approved 10 Oct 2026); it
does not replace it.

| REDESIGN-2 | After this plan |
| --- | --- |
| Calm and plain; one filled action per view; resting content has no shadow; hairlines before boxes | **Stays** |
| Type roles `text-title/heading/body/meta/figure`; 4px grid; 6px controls, 14px cards | **Stays** |
| `NoticeBox` / `ChecklistRows` for messages and blockers | **Stays** |
| Campaign `FoldSection` coloured tabs on tinted cards (founder, 15 Nov) | **Stays**, inside each campaign tab |
| Tabs only for peer views of one thing (UX-DOCTRINE D-655) | **Stays**; every new tab set below is peer views of one agent or one campaign |
| Agent page = Overview / Actions / Settings / Training (D-997, founder 16 Nov) | **Changes** to six owner-word tabs (§2); founder confirmation needed, see §9 |
| Campaign page "Set up" tab holds every set-up section on one scroll | **Changes**: split into Script / People / Settings / Checks (§3) |
| First run: About → Name and voice → What first? → Hear it | **Changes**: job, language and brief on one first card; "What first?" goes (§5) |
| Sidebar: one long list for every account | **Changes**: short trial sidebar until the first test call; groups renamed (§4) |
| Palette: white + green | **Changes**, direction not yet chosen (§8) |

Dark mode stays dormant (D-471, light only). The `.dark` block keeps compiling and its
contrast tests keep passing; no lane spends effort on it.

---

## 1. Information architecture

```
Dashboard
Agents ─┬─ Anjali  (agent home, six tabs)
        │    What it says ── its campaigns and its inbound line, each one row
        │                     └─ opens /campaigns/{id} or /inbound/{id}
        │                        with "Agents › Anjali › <job>" as its back link
        │    What it knows · Actions · What it notes · Voice · Settings
        └─ + New agent
Campaigns (all campaigns, every agent)   Inbound (every line)
Calls · Leads · …
```

* **The data model does not change.** D-997 stands: the agent is staff with no script of
  its own; a campaign or an inbound line is the job and holds the script. "Campaigns inside
  the agent home" is a navigation fact, not a storage one: the agent home lists the agent's
  jobs, and a job page opened from there knows its agent and offers the way back.
* **No route moves.** `/c/{slug}/campaigns/{id}` and `/c/{slug}/inbound/{id}` stay the one
  address of a job (one way per problem; every link in the product, in Pip's screen
  directory and in alerts keeps working). The back link reads the job's `agent_id`; when
  the owner came from the Campaigns list (`?from=list`, or no referrer) it says "All
  campaigns" as today.
* "Change what it says" from first-run step 4 opens the campaign's **Script** tab
  (`/campaigns/{id}?tab=script`), whose header now says "Anjali · Your first calls", so the
  owner can see they are still inside Anjali's work.

## 2. Agent home: six tabs

Tab ids are fixed here so lanes 2 and 4 build against the same ids.

| id | Label | Holds | Comes from |
| --- | --- | --- | --- |
| `script` | **What it says** | The opening notices and the truthful-answer guarantee (first, never behind a tap); then one row per job: name, kind (calls people / answers calls), state pill, its opening line, "Change what it says ›"; then "Give it another job" (new campaign for this agent / new inbound line). Pending-changes banner and setup checklist stay at the top. | Overview (`ScriptsMoved`, `OpeningNotices`, `SetupChecklist`, `PendingBanner`, `AgentReadinessPanel`, `CallerHelpSuggestion`) |
| `knowledge` | **What it knows** | Today's Training tab unchanged (teach box, gaps badge, try-it chat, practice callers) | `training` |
| `actions` | **Actions** | Unchanged | `actions` |
| `notes` | **What it notes** | What a call writes down for a lead (captured fields), the outcome labels, link to the account's Lead details | Settings (`captured`) |
| `voice` | **Voice** | Voice picker with price per minute (§7), first language, "also speaks" | Settings → Voice |
| `settings` | **Settings** | How it handles calls, alerts, model, what it is, leads and calling hours link, delete | Settings |

* The header keeps the name, On/Off switch, Try it, Put it live, Show me around, and gains
  **"Calls (n)"**, a text link to `/calls?agent_id=` (latest calls leave the tab body).
* `script` opens first. Hard rule 5's truthful-answer block and the two notice switches
  were Overview's because Overview opened first (doctrine §8 rule 7); they move with the
  first-tab position, so the rule is kept, not relaxed.
* `LEGACY_SECTIONS` grows: `overview → script` (it is the new first tab), `training →
  knowledge`, `test → knowledge`, `captured → notes`, `voice → voice` (no longer settings),
  `calls → script`, `model/advanced → settings`. `script` now resolves to a real tab, so
  every old "Edit its script" link lands where its words are.
* `/agents/{id}/script` and `/agents/{id}/test` keep redirecting through `tabRedirect.ts`.

## 3. Campaign page: tabs

Today one "Set up" tab holds 13 sections (main task, sources, Pip generate, script and call
steps, agent, what it notes, alerts, test call, add people, schedule, 7 checks, other
settings, start). It splits by the owner's question:

| State | Tabs (in order) |
| --- | --- |
| Draft | **Script** · **People** · **Settings** · **Checks (n left)** |
| Launched | **Progress** · **Calls** · **Script** · **People** · **Settings** · **Improve (n)** |

| Tab | Sections (each keeps its `FoldSection` tone) |
| --- | --- |
| Script | What this campaign is for (main task), Files and notes it can use (sources), Pip generate band, Script (opening, call steps, push-backs), Agent, What it notes, **Test call** (bottom, the moment that proves the script) |
| People | Add people (file, paste, one by one), the people list; after launch "By person" |
| Settings | When it calls (schedule cards, start later), Other call settings, Alerts |
| Checks | `LaunchGate` (the compliance checks) and, below it, **Start campaign** |
| Progress | Where it stands, Results, Day by day (today's Progress tab) |
| Calls | Today's "Calls & recordings" |
| Improve | Today's Improve tab, with "Questions to answer" as its first section and the open count on the tab |

* **Start campaign stays visible on every tab** of a draft, in the page header (today it is
  in the FoldGroup actions and at the foot of Set up). Disabled with the reason in words
  ("3 checks left. Open Checks") until the gate passes. One filled button per view: it is
  the only filled button in the header.
* **Every jump to a section switches tab first.** `StartCampaign.tsx` `blockerSection()`,
  `PipScriptAsk` (`campaign-materials`), `CampaignWorkspace` (`campaign-script`) and
  `DraftPeople` (`peopleSectionId`) scroll to an element id. With tabs, the element may not
  be mounted. One helper `openCampaignSection(sectionId)` maps a section id to its tab, sets
  `?tab=`, waits for the panel, then scrolls and outlines it. This is also the fix for
  defect C13-a ("Show me" did nothing).
* `?tab=` aliases: `setup → script`, `questions → improve`; `progress`, `calls`, `improve`
  keep their meaning (`lib/api/accountImprove.ts` links to `?tab=improve`).
* Collapse all / Expand all stay, per tab.
* The tab pills keep their `accent` per tab (`Tabs variant="pills"`).

## 4. Sidebar

### Trial sidebar (until the first test call)

Shown while `GET /v1/trial` says `on_trial: true` **and** `minutes_used == 0`. Read once in
`ClientSidebar`; while that read is loading or fails, the full sidebar shows (never hide a
screen on a guess).

```
Dashboard
Your agent            → /agents/first while first run is due, else /agents
Make a call
Call logs
Pip
──────────
Credits & billing
Show everything ▾     (expands the full grouped list in place; remembered per browser)
```

* No "Agreements 4 outstanding" badge in the trial sidebar. The agreements are asked where
  they matter, in the Hear-it step's ticks (C11), and the server gate is unchanged
  (`agreements_blocker`); hiding a count bypasses nothing.
* The list is a **filter over `clientNavigation()`** at render time (`TRIAL_NAV_HREFS`), so
  `clientNav.ts` stays the single literal that `apps/api/copilot/screens_test.py` parses,
  and Pip can still name every screen.

### Full sidebar (grouped, about 7 visible per group)

| Group | Items |
| --- | --- |
| (none) | Dashboard · Needs attention · Improve |
| **Calling** | Agents · Campaigns · Inbound · Make a call · Phone numbers |
| **Results** | Call logs · Leads · Follow-ups · Call-backs · Performance · Quality |
| **Knowledge** | What your agents know |
| **Rules & records** | Agreements · Verify your business · Do not call · Messaging consent · Leads & hours · Data rights · Your privacy notice · If data leaks |
| **Account** | Business profile · Lead details · Team · Alerts · Line protection · Call notices · AI model · Integrations · Credits & billing · AI help |
| footer | Pip |

* Groups other than the first are collapsible, open by default; the group holding the
  current page is always open.
* **Moving an item between groups or renaming a group changes `screens_test.py`'s
  equality gate**, so lane 4 edits `apps/api/copilot/screens.py` (`group=` per screen) in
  the same commit. Python is not run on this host; CI runs that test, and the lane says so
  in its report.

## 5. First run: one first card

```
┌ What should your agent do? ──────────────── in [Telugu ▾] ┐
│ [ brief box ......................................... ]   │
│ [Examples]  [Add a file]                   [🎤] [Continue]│
│ ( Call people: works through a list )                     │
│ ( Answer my calls: picks up your number )                 │
└───────────────────────────────────────────────────────────┘
Examples for your kind of business: [card] [card] [card]
```

* **One card**: brief box, language picker in the title line, voice note (existing
  `RecordBrief`, 3 × 30 s), Add a file (existing `BriefDocuments`), the job as two radio
  rows (`answer_calls`, `call_leads`), and Examples (existing `useVerticalExamples` text,
  inserting into the box on tap). The two job rows carry today's chip pictures in small.
* **Steps become three:** About your business (the card) → Name and voice → Hear it.
  `STEPS` in `lib/firstAgent.ts` drops `work`; the rail shows 3.

**No backend change. How the card maps to today's API:**

| On the card | Sent when | Call |
| --- | --- | --- |
| Brief text | Continue | `PUT /v1/first-run/brief` (unchanged) |
| Files, voice notes | as added | `POST /v1/kb/uploads` + `/documents`, `POST /recordings` (unchanged) |
| Language | Name and voice → Continue | `PUT /v1/first-run/agent` `language_primary` (prefilled from the card) |
| Job | right after `/agent` succeeds | `POST /v1/first-run/work` `{job}` |

* The job cannot be posted at Continue: `post_work` writes the campaign's main task from the
  brief **and the follow-up answers** (`first_run/work.py` `_main_task`), and is refused
  with `first_run_no_agent` before `/agent` (`routes.py:440-466`). So the card's job is held
  in the browser (`sessionStorage`, key per slug, every access in try/catch) and posted
  after `/agent`, exactly where "What first?" posted it.
* **If the held job is lost** (another device, cleared storage), `resumeStage` finds an
  agent with no `line_id`/`campaign_id` and shows the existing `WorkStep` once. It stays
  in the code as that fallback; it is never on the rail.
* The questions step stays between the card and Name and voice, unchanged.
* **Must not regress:** the brief box must not lose or gain characters while the owner
  types (defect C3-a). Acceptance includes typing 800 characters fast in the browser and
  reading them back.

## 6. Owner words (every lane uses this table)

Client-facing text only. Code identifiers, API fields and admin screens keep their names.

| Builder word on screen today | Owner word |
| --- | --- |
| Scenario / scenarios | What the caller might say |
| Next scenarios | What can happen next |
| Let Pip map the scenarios | Let Pip plan what callers might say |
| Add a scenario below / Delete scenario | Add another reply / Remove this reply |
| Outcome (of a step), "once the step's outcome is reached" | Done when… |
| Way out / Add a way out | Then go to… |
| "Drag to another step to add a way out", "drag its green dot" | "Pick where it goes next" (a button with a step list; dragging stays as a shortcut, never the only way) |
| Drag to move this line; double-click to straighten it | (tooltip only on pointer devices; no instruction text) |
| Call flow | Call steps |
| Main task | What this campaign is for |
| Sources / materials | Files and notes it can use |
| Generate / Generate in | Let Pip write it / Write it in |
| When callers push back / push-back | If they say no or not now |
| How closely it follows the steps / Follow the steps closely | Stick to the steps: Loosely / Closely |
| Exact words | Say it word for word |
| Opening / opening line | First thing it says |
| Mandatory Regulatory Compliance Checks | Before it can call |
| Training (tab) | What it knows |
| Captured fields / extraction | What it notes |
| Publish / published / unpublished | Put it live / live / not live yet |
| Draft (pill) | Not live yet |
| Variable / call variable / "Add variable" | Detail about the person / Add a detail |
| Holder, slot, rung, band, tier (if ever on a client screen) | (never shown) Clear voice / Studio voice |
| Hand-over to a person | Pass to a person |

Words that stay because they are the domain vocabulary (CLAUDE.md): agent, campaign,
Inbound, Pip, Clear, Studio, Do not call.

**Guard:** lane 3 adds `apps/web/tests/ownerWords.test.ts`, scanning `src/app/c/**` and
the client-used shared components for the left-column words in string literals and JSX
text (case-insensitive: `scenario`, `way out`, `green dot`, `Mandatory Regulatory`,
`call flow`, `main task`), with no allow-list. Lanes 1, 2 and 4 keep it green.

## 7. Tour and voice prices

### Tour (lane 4)

The agent-page tour exists (D-855, `agents/[agentId]/tour/`, owner-started from "Show me
around", 4 steps, `?tour=1` only from a link the owner clicks). It is kept owner-started
and grows to **5 steps** (onboarding-design: user-started tours under five steps finish far
more often; `tourModel.ts` cites the evidence), pointing at the new tab ids:

1. **What it says** (`script` tab): "Its words for each job. Change them here."
2. **Ask Pip to change it** (Pip launcher): unchanged.
3. **What it knows** (`knowledge` tab): "Facts and answers callers need."
4. **Voice** (`voice` tab): "Play the voices. Each shows its price a minute."
5. **Try it before callers do** (Try it): unchanged, last, because it is the next action.

The tour never switches tabs (the unsaved-edits guard reason in `tourModel.ts` stands).
The first-run result screen keeps linking with `?tour=1`.

### Voice picker with price per minute (lane 4)

* Each voice row and the Clear/Studio headings show **"₹X a minute"**.
* **Where the figure comes from (never hard-coded):** the rate is per credit lot and per
  pack, operator-attested, frozen on the lot (`clear_inr_per_min` / `studio_inr_per_min`).
  The one door on the client side is `app/c/[slug]/billing/lots.ts` `lotRate()` /
  `packRate()`; tier labels come from the server (`tierLabels`).
  1. An open lot exists → `lotRate(firstOpenLot, tier)` from `useWalletLots`, "₹X a minute".
  2. No lot (trial or empty wallet) → the lowest `packRate(pack, tier)` from
     `useCreditPacks`, "from ₹X a minute", and on trial "Free during your trial".
  3. Neither readable → no figure; the row says "Price shown when you add credit". Never a
     guessed number.
* The figure is the server's decimal string printed with `formatRupeeRateExact`; no
  arithmetic in the browser (hard rule 7).
* An AI model surcharge, when the agent's model has one
  (`client_surcharge_inr_per_minute`, `lib/api/llmModels.ts`), is a separate line under the
  heading ("+ ₹Y a minute for the AI model"), never summed in the browser.
* Client text names no provider (D-679): "Clear" and "Studio" only.
* Also fixes C8-a (the "no woman's voice speaks this language" note under a voice that
  speaks it): the note shows only when the server's pick says `fallback`.

## 8. Colour

**Decided: A, "Khata ledger"** (28 Nov 2026; tokens, roles, ratios and what is left for each lane are in `COLOUR-OPTIONS.md`). Background: the founder rejected "forest green + warm off-white + warm accent" on 28 Nov as
too close to Outpero's structure (off-white + grey + one strong hue). The tokens in
`globals.css` now carry the ledger palette. Fixed already:

* Light only (D-471). No large dark panels (founder, 23 Oct 2026: "something light not
  dark"). Green stays the brand.
* Token **names** stay, so every screen picks the palette up without edits; new roles (an
  accent, a tinted hero surface) are added as tokens beside them.
* Every text token at 4.5:1 on every surface (`tests/contrastTokens.test.ts`,
  `tests/contrast.test.ts`); the real-Chromium axe gate (`test:a11y-browser`) runs both
  token blocks.

**Hard-coded colours that will not follow a palette change** (client realm and shared kit):

| File | Literal | Note |
| --- | --- | --- |
| `components/successRipple.tsx:53-54,101,111,123` | `#dc2626`, `#ffffff` | error disc and tick stroke |
| `components/UpdateWatcher.tsx:197-198` | `#fafafa`, `#171a1c` | fallbacks inside `var()`; harmless but will drift |
| `app/c/[slug]/campaigns/StartCampaign.tsx:50` | `#b91c1c` | fallback inside `var(--danger, …)` |
| `components/interior/collapsible-banner.tsx:23-24` | `text-amber-600`, `text-red-600` | should be `text-warn` / `text-danger` |
| `components/interior/floating-label.tsx:186,236,255` | `border-red-500`, `text-red-600` | invalid state |
| `components/interior/otp-input.tsx:189` | `border-rose-500` | invalid state |
| `components/interior/live-activity.tsx:483`, `load-more.tsx:243` | `text-red-600` | error text |
| `components/console/section.tsx:100` | `dark:text-rose-400` | dark only |
| `components/console/modelLogo.tsx:17,24` | `bg-white`, `text-slate-600` | logo tile |
| `components/console/iconTile.tsx:27` | `bg-white` | icon tile |
| `components/ui.tsx:1273,1531,1570`, `routeLoading.tsx:17`, `arc/button-group.tsx:210` | `bg-black/40`, `bg-black/5` | scrim and washes; neutral by design, re-check on a warm ground |
| `campaigns/FoldSection.tsx:79-95` | `series-*` tones | tokens, but chart colours used as section identity; a palette change must re-check them |

`text-white` (39) and `bg-white` (18) also appear on filled buttons and badges; they are
correct while the fills stay dark enough, and the palette lane re-checks each pairing.

## 9. Decisions for the founder before the screen lanes start

1. **Agent page tabs.** On 16 Nov the founder cut the agent page from 7 tabs to 4 and
   retired its Script tab (D-997). The 28 Nov direction asks for Script, Knowledge, Actions,
   Outcomes, Voice, Settings. §2 reconciles them: six tabs, "What it says" lists the
   agent's jobs (the script still lives on the job). Confirm six, or keep four with "What
   it says" replacing Overview.
2. **Palette direction** (§8).
3. **Trial sidebar trigger**: `minutes_used == 0` hides the long list until the first test
   call has used a minute. Alternative: until the first run is finished.
4. **"Inbound"** stays as the sidebar word (founder, 16 Nov), or becomes "Answering calls".

---

## 10. Lanes

Four screen lanes, after the current bug-fix lanes merge. Each branches from main at that
point. File ownership is exclusive; a lane that needs a change in another lane's file asks
that lane, or waits for its merge.

**Shared rules for every lane:**

* Must not change: compliance gates (`LaunchGate`, dial gate copy, the 6 Hear-it ticks,
  `agreements_blocker`), the opening-notice switches and truthful-answer block (hard rule
  5), notices behaviour (memory "notices-ux-first"), campaign coloured folds (memory
  "campaign-coloured-folds"), compliance and money sentences verbatim, the API and OpenAPI
  client.
* Never break a link: an old route or `?section=` / `?tab=` value redirects or aliases.
* Owner words from §6. Short lines, one button per problem, the reason behind ⓘ (memory
  "buttons-not-paragraphs").
* Checks: `pnpm -C apps/web typecheck`, `lint`, `test` (the lane's tests plus `a11y`,
  `responsive`, `simpleCopy`, `ownerWords`), `test:a11y-browser`; a browser check at 375
  px and 1280 px with the node mock API; screenshots in `shots/`.

### Lane 1: first screen and Meet your agent

* **Owns:** `apps/web/src/app/c/[slug]/agents/first/**`, `apps/web/src/lib/firstAgent.ts`,
  `apps/web/src/lib/useVerticalExamples.ts`; tests `firstAgent.test.tsx`,
  `auditW7FirstAgent.test.tsx`, `trialTestCalls.test.tsx` (first-run parts),
  `waitUntilReadyClient.test.tsx` (first-run parts).
* **Does:** §5. The one card; three steps; job held and posted after `/agent`; `WorkStep`
  kept as fallback only; "It says first" shows the opening once written (C11-d); "Change
  what it says" links to `/campaigns/{id}?tab=script` or `/inbound/{id}`.
* **Acceptance:** a new trial owner goes card → questions → name and voice → hear it with
  no "What first?" screen; reload on any step lands on the same step; a lost job shows
  `WorkStep` once; 800 typed characters read back intact; Hear-it ticks unchanged.
* **Must not change:** `/v1/first-run/**`, the Hear-it consent ticks, the trial minute caps.

### Lane 2: agent home with tabs

* **Owns:** `apps/web/src/app/c/[slug]/agents/[agentId]/AgentWorkspace.tsx`,
  `.../[agentId]/sections/**`, `.../[agentId]/tabRedirect.ts`, `.../[agentId]/page.tsx`,
  `.../[agentId]/loading.tsx`, `apps/web/src/app/c/[slug]/agents/page.tsx` (list);
  tests `agentDetail.test.tsx`, `agentScreensAudit.test.tsx`, `agentScreensPhone.test.ts`,
  `agentScreensShortCopy.test.ts`, `agentGoLive.test.tsx`, `agentLiveConfirmation.test.tsx`,
  `routeBundleSplit.test.ts` (agent parts).
* **Does:** §2. Tab ids exactly `script, knowledge, actions, notes, voice, settings`;
  `LEGACY_SECTIONS` aliases; header "Calls (n)"; moves sections between tabs; places the
  voice picker in `voice` (lane 4 owns the picker's insides).
* **Acceptance:** every old `?section=` value opens the tab that now holds it; the
  truthful-answer block and notice switches are in the first tab; a deleted agent is still
  read-only; tab chunks still load lazily.
* **Must not change:** `script/**` (lane 3), `tour/**` (lane 4), `panels/delivery.tsx`
  internals (lane 4).

### Lane 3: campaign page tabs

* **Owns:** `apps/web/src/app/c/[slug]/campaigns/**` (except `FoldSection.TONE`, which
  stays as it is), `apps/web/src/app/c/[slug]/agents/[agentId]/script/**` (the script
  editor campaigns and inbound lines use), the back link on
  `apps/web/src/app/c/[slug]/inbound/InboundLineScreen.tsx`, new
  `apps/web/tests/ownerWords.test.ts`; tests `campaign*.test.tsx`, `scenario*.test.tsx`,
  `flowLayout.test.ts`, `addToCampaign.test.tsx`, `accountImprove.test.tsx` (link only).
* **Does:** §3 tabs; `openCampaignSection()`; Start campaign in the header; `?tab=`
  aliases; "Agents › Anjali" back link; §6 words across the script editor and campaign
  screens; the owner-words guard.
* **Acceptance:** each blocker's "Show me" lands on its tab and outlines the section
  (C13-a); `?tab=setup` and `?tab=questions` still open the right place; coloured folds
  unchanged; the 7-vs-6 checks count agrees (C12-b); "Pick where it goes next" works with
  no drag.
* **Must not change:** compliance check rules and wording, `LaunchGate` logic, `TONE`.

### Lane 4: sidebar, tour and voice picker

* **Owns:** `apps/web/src/lib/clientNav.ts`, `apps/web/src/app/c/[slug]/ClientSidebar.tsx`,
  `apps/web/src/components/sidebarCollapse.tsx`, `apps/web/src/app/c/[slug]/ClientShellFallback.tsx`,
  `apps/api/copilot/screens.py` (groups only), `.../agents/[agentId]/tour/**`,
  `apps/web/src/components/engineCatalogueList.tsx`, `apps/web/src/components/voicePreviewButton.tsx`,
  `apps/web/src/app/c/[slug]/agents/panels/delivery.tsx`, `apps/web/src/app/c/[slug]/agents/new/VoiceStep.tsx`;
  tests `clientPageTitle.test.ts`, `copilotNavigation.test.tsx`, `responsive.test.ts` (nav
  parts), `agentTour.test.tsx`, `engineCataloguePicker.test.tsx`, `agentVoice.test.tsx`,
  `voiceChoiceIsTheClients.test.ts`, `engineModelBand.test.tsx`.
* **Does:** §4 trial filter and groups; §7 tour (after lane 2's tab ids land, or against
  the ids fixed in §2) and prices.
* **Acceptance:** a trial account with no minutes used sees 6 items and "Show everything";
  any other account sees the grouped list; `screens.py` groups match `clientNav.ts`
  (CI's `screens_test.py`); every voice shows a server figure or "Price shown when you add
  credit", never a typed number; no provider name on any client screen.
* **Must not change:** the routes in `clientNav.ts` (only groups, order and labels per
  this plan), the agreements gate.

### Order

Lanes 1, 3 and 4 can start together. Lane 2 starts with them but lands before lane 4's tour
step (the tour points at lane 2's tab ids). Lane 1's "Change what it says" link depends on
lane 3's `?tab=script`; until lane 3 merges, `?tab=script` falls back to the default tab,
which is the same page.

## 11. Not verified here

* That `/v1/billing/topups/packs` answers a trial account (lane 4 checks before relying on
  it; if refused, the price row shows "Price shown when you add credit").
* The new sidebar groups' effect on Pip's screen directory size. A 16 Nov memory (REPORTED)
  says adding Inbound left a copilot prompt 40 tokens over a 17,500 budget; the budget check
  was not located here. Lane 4 finds it before renaming groups.
* `screens_test.py` and every other Python test: not run on this host.
