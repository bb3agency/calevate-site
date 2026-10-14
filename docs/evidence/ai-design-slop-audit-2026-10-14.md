# AI-design slop audit: apps/web, 14 Oct 2026

Method: `.claude/skills/audit-ai-design-slop` (MengTo, pinned in `.claude/skills/DESIGN-SKILLS-PIN.md`),
removal test first, findings grouped by root cause. Fixed under `no-ai-design-slop` as the gate, in the
"calm and plain" direction already approved for redesign #2 (`docs/design/REDESIGN-2.md`). Decision row: D-771.

Prompt: the founder's screenshot of the client trial chip (14 Oct 2026), "this can be a lot better instead
of looking like ai slop".

## Checked scope

- Source: every `.tsx`/`.ts` under `apps/web/src` (tests excluded), scanned for hand-rolled pills, tinted
  blocks, decorative lucide glyphs, gradients, blur, coloured or raw-palette classes, hex literals, emoji
  and filler words.
- Rendered: the marketing homepage at 1280×800, running locally with `next dev`. The client and admin
  consoles need an API, and none was running on this host. They were checked from source and, after the
  fix, from a throwaway fixture page (see "Unknowns").
- Light palette only. The product ships light-only (D-471), and nothing adds `.dark`.

## Verdict

The consoles had already lost most of the generated look in redesign #2, and the notices pass on
11 Oct 2026 continued that. What was left was concentrated in **status display**. One shared `StatusPill`
existed, but a second shared badge (`StatusBadge`) painted lead states on a raw Tailwind rainbow that
included violet, and about 35 screens drew their own pastel pill. The trial chip the founder flagged was
the clearest example: a rounded-full warn-tinted pill with a border and a gift glyph. The other leftovers
were tinted notice blocks that the 11 Oct rule had banned but that came in through `NOTICE_TONES`,
decorative glyphs on buttons (rocket, sparkles, wand, gift), and a marketing hero with floating blurred
blobs layered on top of the founder's grid. **The first thing to remove** was the pill: one status
definition (dot plus word, no fill, no border), with every caller moved onto it.

## Counts by category

| Category | Class | Instances found | Fixed in this pass |
| --- | --- | --- | --- |
| A. Hand-rolled or second-system status pills (fill, border, rounded-full) | Slop pattern | 2 shared definitions + 37 call sites in 30 files | all except the assistant (`components/copilot/**`), which belongs to the assistant lane (see Unknowns). The phone-number screens were migrated in a second pass, once their lane had finished |
| B. Tinted notice blocks through `NOTICE_TONES` (fill, border, all text in tone colour) | Slop pattern | 14 blocks in 10 files | all. `SenderAttestation.tsx` was migrated in the second pass, and `NOTICE_TONES` is deleted |
| C. Decorative glyph standing in for meaning | Slop pattern | 19 uses (Gift ×2, Rocket ×3, Sparkles ×6, Wand2, Zap/Hourglass/Layers/CircleAlert in one disclosure, BadgeIndianRupee and row glyphs in one list, BotMessageSquare ×3 as "AI") | all except the navigation-rail glyphs (kept, see below) and the assistant robot (handed to the assistant lane) |
| D. Decorative gradients, glows and blur | Slop pattern | 2 floating blurred blobs ×4 heroes, 3 radial brand glows behind mockups, 1 gradient fill on a button, 1 shimmering gradient text on a hex palette | all |
| E. Decorative numbering and eyebrow chrome | Slop pattern | numbered eyebrows "00"–"04" on pricing, ROI, industries and solutions (13); the hero's bordered, shadowed eyebrow pill | all |
| F. Raw palette or hex outside tokens | Quality defect (system) | `StatusBadge` slate/sky/violet/amber/emerald/rose; mockup kit violet ×2; `#16a05d`/`#22c55e` focus rings ×4 and a hex shimmer in `components/interior/` | all |
| G. Top-bar status controls as three bordered pills (live calls, credit, trial) | Slop pattern | 3 | all |

Emoji in UI copy: **none** (the only emoji are in code comments). Filler copy ("supercharge", "seamless",
"unlock" as hype): **none**; the hits were literal key-locking language in the admin secrets panel.
Default indigo: **none**. Violet: three places, all in category F.

## Findings

| Priority | Class | Pattern | Evidence | Harm | Remove or fix |
|---|---|---|---|---|---|
| P1 | Slop pattern | Trial chip as a pastel gift pill | `app/c/[slug]/TrialBanner.tsx:252-256`: `rounded-full border … border-warn-line bg-warn-soft text-warn` plus `<Gift>`. When the trial had ended, the chip only opened a popover, so adding credit took two taps. | A gift reads as a present, not an account that has stopped. The tint and border were the same loudness as every other pill. Rule: removal test; ux-writing "say what happened and what to do next". | Plain bar control. A purpose-drawn trial meter (ring = what is left of the trial) replaces the gift. Ended: "Trial ended · Add credit" as one link straight to credits. |
| P1 | Slop pattern | Two badge systems plus ~35 hand-rolled pills | `components/ui.tsx:497-546` `StatusBadge` (raw `violet-100`, `sky-100`, `emerald-100`…) vs `components/console/statusPill.tsx`. Hand-rolled examples: `agents/AgentBadge.tsx:119,135`, `agents/page.tsx:104`, `agreements/documents.tsx:24`, `campaigns/campaignStatus.tsx:23`, `callbacks/CallbacksScreen.tsx:162`, `knowledge/SubmittedList.tsx:126,143`, `knowledge/UploadList.tsx:65`, `KnowledgeGaps.tsx:92`, `integrations/DeliveryLog.tsx:104`, `lead-sources/DeliveryLog.tsx:58`, `quality/QualityReport.tsx:23`, `settings/line-protection/LineProtectionScreen.tsx:246`, `admin/operators/OperatorRow.tsx:25,103,108`, `admin/ops/alerts/AlertsScreen.tsx:324`, `admin/ops/spoken-style/SpokenStyleScreen.tsx:48`, `admin/layout.tsx:494`, `marketing/home/mockups/kit.tsx:87,114`. | A row of pastel capsules makes every state equally loud, so the eye cannot tell "live" from "deleted". Two shared definitions means drift ("one way per problem", CLAUDE.md). Rule: component repetition; the system gate. | One `StatusPill`: a 6px tone dot and the word, with no fill and no border. A tag that is not a state ("Test call", "Google Sheet", "In use") becomes plain meta text. `StatusBadge` now maps lead and call states to the four tones and renders `StatusPill`. Every caller moved. |
| P1 | Slop pattern | Tinted notice blocks that slipped past the 11 Oct rule | `billing/{LotsPanel:63,SpendPanel:233,UsageTab:112,471,WalletHero:109,151}`, `lead-sources/{MetaRecovery:92,MetaSetupDetails:47,55,TestLeadDrawer:68}`, `TrialBanner.tsx:147` (a full-width warn band), `marketing/security/mockups.tsx:64,187,233`. | This is the "cream card, every line in the tone colour" look the founder rejected on 11 Oct (memory b441cc04). | `NOTICE_BASE` + `NOTICE_BAR[tone]` (left rule, ink text). Site strips use `SITE_STRIP` + a tone dot. |
| P2 | Slop pattern | Glyphs as decoration | `campaigns/LaunchConfirm.tsx:145,215`, `LaunchGate.tsx:160` (Rocket); `script/{ScriptToolbar:132,AssistPanel:170}`, `KnowledgeGaps.tsx:275`, `admin/ops/voices/hosted/VoiceDrawer.tsx:142` (Sparkles); `script/HandWritten.tsx:94` (Wand2); `admin/…/credits/GrantPanel.tsx:269` (Gift); `billing/WhereItWent.tsx:44-98` (a coloured glyph per money row); `settings/models/OrganizationDefault.tsx:90` (Sparkles as a bullet); `agents/LaneGuide.tsx:41,92,97,102`; `copilot/{CopilotDock:247,AskAssistant:35}` (a robot for "ask about this screen"). | They add no information that the label lacks. Rockets and sparkles are the stock "AI product" vocabulary, and a robot misstates what the assistant does. Rule: "art-direct iconography to the subject"; removal test. | Removed. The assistant glyph is left to the assistant lane (D-772 gives it its own face). |
| P2 | Slop pattern | Decorative stacking in the marketing heroes | `marketing/home/hero.tsx:56-60` (grid + 2 floating blurred blobs + `mk-float` loop), `pageShell.tsx:190-191`, `why/pageHero.tsx:38-39`, `home/closing.tsx:59-63`; a bordered, shadowed eyebrow pill at `hero.tsx:66`; radial brand glows at `pricing/page.tsx:168`, `roi/page.tsx:224`, `home/howItWorks.tsx:59`. | Three layers do one job (look "techy"). The blobs move forever behind the reading line. Rule: decorative stacking, motion theater. | Blobs and their keyframes removed. The founder-requested ruled grid stays as the one texture (globals.css records the request). The eyebrow is plain text. The radial glows are gone, and mockups sit on the plain ground. |
| P2 | Slop pattern | Decorative 00–04 numbering | `pricing/page.tsx:227-444`, `roi/page.tsx:170-234`, `industries/page.tsx:85`, `solutions/page.tsx:350` (`<Eyebrow index>`). | The sections are not a sequence. DESIGN-SKILLS-PIN.md rejected `number-details` for this reason. | `index` dropped at every call site and removed from `Eyebrow`. The three real ordered steps on the homepage keep their numbers. |
| P2 | Quality defect | Off-token colour | `StatusBadge` raw palette (above); `components/interior/{show-more:190,sticky-header:107,wizard-steps:291,task-steps:197}` hex focus rings and shimmer; `actionButton.tsx:80` gradient fill. | Bypasses the tokens, so a palette change misses them. The shimmer animates forever. | Token classes only. The shimmer becomes a static `text-ink` label (the step's spinner already shows that it is working). The button fill becomes flat `bg-brand-strong`. |
| P3 | Slop pattern | Three bordered capsules in the top bar | `console/liveCalls.tsx:52,73`, `ClientTopHeader.tsx:119` (credit), the trial chip. | Equal weight for three unrelated facts, all next to the bell. | One `BAR_STATUS` class: a quiet, borderless text control with a hover ground. |

## Kept on purpose (removal test failed: deleting them would lose meaning)

- Navigation-rail glyphs (`lib/clientNav.ts`, `app/admin/adminNav.ts`) are wayfinding at a glance and are
  the convention, including `Sparkles` on "AI help" and `Bot` on "Agents" (an agent is the bot). The one
  generic-AI glyph that describes the wrong thing, the robot on "Assistant", belongs to the assistant lane
  (D-772).
- Count badges on the bell and the sidebar (`rounded-full bg-danger`) are a count, not a state.
- Filter chips (`FilterChip`, `FacetPanel`, `ConfigForm` reason pills, `TenantShell` tabs) and suggestion
  chips (`AssistPanel`, `SectionEditor`, `CopilotPanel` questions, `Routines` examples) are controls, and
  their shape tells the user they can be pressed.
- The homepage's numbered "Three things happen" steps are a real sequence.
- The founder-requested marketing grid (`.mk-grid-lines`).
- `components/illustration/disconnectedCall.tsx`, the 404 figure.

## Unknowns

- The client and admin consoles could not be rendered against real data: there is no API on this host,
  and the earlier mock servers lived in a previous session's scratchpad. The redesigned trial chip (both
  states), the trial strip and `StatusPill` (every tone) were rendered from a throwaway fixture route at
  desktop width and looked at, and the route was deleted afterwards. The marketing home and /pricing were
  looked at after the change.
  Every other console screen was verified by the unit and a11y suites, not by eye.
- Second pass, after the phone-number lane finished: `OwnNumbers.tsx` (the step marks), `PhoneNumberScreen.tsx`
  (the number's state) and `SenderAttestation.tsx` (two tinted blocks) were migrated.
  `TrialLockNotice.tsx` already used the quiet `NoticeBox` and needed no change.
- Not edited, by instruction (another agent owns it). The assistant UI (`components/copilot/**`) still has its own pills: `CopilotPanel.tsx:256`
  ("Using:") and `workspace/TasksList.tsx:79` and `workspace/ActivityLog.tsx:138` (status). The
  `admin/ops` voice-response-time page was also left alone.
- Dark palette: dormant (D-471). The `dark:` variants were left as they were.
