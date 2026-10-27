# UI component catalogue, Part D: uiarc (Arc)

> **Superseded for decisions by `docs/design/KIT.md` (24 Oct 2026).** The founder then
> asked for most of the components below that this review marked SKIP, and installed the
> Radix packages. What was built, and which component won where two overlapped, is in
> KIT.md; this file remains the per-component review of the Arc source.

This is Part D of the UI component catalogue (Parts A to C, interior.dev and Pixel Perfect, are in `docs/design/UI-COMPONENTS.md`). It reviews the uiarc ("Arc") components the founder chose for the Calevate consoles: the client panel (`app.calevate.tech`, routes under `apps/web/src/app/c/[slug]/`) and the admin panel (`admin.calevate.tech`, `apps/web/src/app/admin/`). It uses the same verdicts:

- **ADOPT** means use it, with at most mechanical fixes (the token mapping every Arc component needs counts as mechanical).
- **ADAPT** means take it, then fix or restyle what the section lists.
- **SKIP** means do not take it.

The founder said some of these may override components already in the repo, and that this is fine. Where an Arc component duplicates one of ours, each section says which one wins under the "one way per problem" rule (root `CLAUDE.md`, Quality bar). Where Arc's should win, it also says what moving the callers takes.

## Source, licence and drift check

- **Source.** The shadcn registry at `https://uiarc.dev/r/<name>.json`, fetched 24 Oct 2026. uiarc's own docs page for each item is saved beside it as `docs.md`. Upstream repository: `github.com/kuratlielia/arc-library`. The commit recorded at fetch time is `2f89ed7f38751cdbbb7052380abe36962c3cdf45` (2026-10-23). The registry payloads carry no commit id, so this pairing comes from the fetch record, not from the files.
- **Licence.** MIT, "Copyright (c) 2026 Elia Kuratli" (`docs/design/uiarc/LICENSE`). Every component reviewed here has `meta.tier: "free"` in its `registry-item.json`. Any file copied into `apps/web` must keep the MIT notice, either as a header naming the upstream and its licence or through a `LICENSE` beside the copies, as `apps/web/src/components/interior/LICENSE` does for interior.dev.
- **Pro items are excluded.** `login-immersive` and `login-split` (two of the founder's linked login blocks) are Arc Pro. Pro is uiarc's paid tier, outside the free registry items this review covers, so they were not fetched and are not reviewed.
- **Where the code lives.** `docs/design/uiarc/registry/<name>/` holds `<name>.tsx`, `<name>.module.css`, any helper file the item ships (`use-today.ts`, `use-copy-feedback.ts`, `media.ts`, `arc-provider.tsx`, `*-data.ts`, `*-art.ts`, `stats-band-world.ts`), `docs.md` and `registry-item.json`. `docs/design/uiarc/FETCH-REPORT.txt` lists each item with its tier, file count and dependencies. It also records one failure: the `arc-motion-tokens` docs page returned HTTP 404, and that item has no docs page.
- **Drift check.** Each `registry-item.json` lists every file with a `content_sha256`. A file whose SHA-256 no longer matches has drifted from what this review read. All files now match, for all 83 items. `arc-motion-tokens` ships two files that share the basename `motion-tokens.ts`: `registry/motion-tokens.ts` (the presets, `81235a2b…`) and `lib/motion-tokens.ts` (a one-line re-export, `bec65d2e…`). The first fetch saved only the second. The presets were restored from the same registry URL and match their hash. They are at `registry/arc-motion-tokens/motion-tokens.ts`, and the alias is at `registry/arc-motion-tokens/lib/motion-tokens.ts`.
- **Imports assume the install layout.** Components import `../lib/motion-tokens`, `../lib/use-today`, `../lib/use-copy-feedback` and `../../lib/media`. Blocks import `../../button/button` and similar paths. These paths resolve under the registry install targets (`@components/arc/<name>/…`, `@components/arc/lib/…`), not inside `docs/design/uiarc/registry/` as it is laid out. That is expected for a snapshot, and no import names a file that is absent.
- **Sample media is not shipped.** `sign-in/media.ts`, `changelog-feed/media.ts` and `page-header` point at same-origin `/media/people/*.jpg` and `/media/photos/*.jpg`. Those images are not part of the registry.

## How a component is adopted

1. Copy the `.tsx`, its `.module.css` and any helper into `apps/web/src/components/arc/<name>/`, plus `motion-tokens.ts` into `apps/web/src/components/arc/lib/`. Keep the MIT header, and add `apps/web/src/components/arc/LICENSE`.
2. Map Arc's tokens to Calevate's (see "Styling and architecture" below). Do not import `foundation.css` at `:root`. Re-express `motion-tokens.ts` from Calevate's motion values, so there is one motion scale.
3. Restore a visible keyboard focus ring (`ring-brand`), because Arc's components rely on a global rule in `foundation.css` that Calevate does not have.
4. Make the fixes listed in the component's section (ADAPT), and remove anything decorative that the section flags.
5. Give it a consumer in the same change. Where it replaces an existing component, move every caller and delete the old one in the same change.
6. `apps/web/tests/componentConsumers.test.ts` fails on any module under `src/components/` that nothing imports, unless it is named in `AWAITING_A_DECISION`. Copy a file only when its consumer lands with it. Do not add Arc files to that list. If adopting a component retires an interior copy that is on the list (`show-more`, `collapsible-banner`, …), remove that entry too.
7. Any `@radix-ui/*` package is a new npm dependency. That is a supply-chain decision under root `CLAUDE.md` hard rule 9, and `docs/design/REDESIGN-2.md` says "No new npm dependency without asking the founder". Every section that needs Radix names an in-repo primitive that can stand in for it.

---

## Styling and architecture: Arc compared with Calevate

All of this is read from the code in `docs/design/uiarc/registry/`.

**How Arc components are built**

- **Client components with CSS Modules.** Each component is a `"use client"` React file with a sibling `<name>.module.css`. There are no Tailwind classes in the components. Class names come from `styles.x` and are joined with `[…].filter(Boolean).join(" ")` (for example `badge/badge.tsx`).
- **Tokens are global CSS custom properties from `arc-foundation/foundation.css`.** No component imports this file. The install docs say to import it once in the root layout. It defines:
  - a neutral ramp (`--neutral-0..11`);
  - role tokens: `--background`, `--surface`, `--surface-raised`, `--surface-muted`, `--foreground`, `--text-secondary`, `--text-muted`, `--border`, `--border-subtle`, `--border-strong`;
  - an accent: `--accent`, `--accent-strong`, `--accent-subtle`, `--accent-foreground`. The default is a near-black neutral, and eight `data-accent` palettes are on `<html>`;
  - selection-control tokens: `--control-on`, `--control-track`, `--control-thumb`, …;
  - status: `--success`, `--warning`, `--danger`;
  - shadows: `--shadow-resting`, `--shadow-raised`, `--shadow-floating`;
  - a brand gradient: `--arc-gradient*`;
  - spacing, radii (`--radius-control` 18px, `--radius-panel` 26px, `--radius-surface` 34px, `--radius-pill`) and control heights (`--control-height-sm/md/lg` = 36/44/50px);
  - a type scale on the Geist and Inter fonts;
  - eases and durations (`--duration-fast` 160ms, `--duration-standard` 240ms, …);
  - a four-colour chart palette (`--series-1..4`), derived from the accent with relative `oklch()` colour.
- **Dark mode** is `:root[data-theme="dark"]`. It redefines the same tokens, and 7 component CSS files also carry their own `[data-theme="dark"]` rules.
- **Focus.** Pointer focus draws no ring by design (`--focus-ring: transparent`). Keyboard focus comes from one global rule at the end of `foundation.css`. It sets `:focus-visible { outline: 2px solid <accent mix> !important }`, and `:focus:not(:focus-visible)` with `outline: none !important`, with text fields, menu items, options and `tabindex="-1"` targets exempted. Many component CSS files set `outline: none` on their own focus targets and depend on this global rule to put the ring back.
- **Motion.**
  - **Presets.** Every component except `scroll-area`, `expandable-text` and `slot-text` imports the shared presets from `arc-motion-tokens` (`motionTokens`):
    - durations from 0.12 to 0.48s;
    - eases `enter`, `exit`, `standard` and `inOut`;
    - springs `snappy` (0.26s) and `smooth` (0.4s), plus `morph`, `responsive` and `gentle`, all with `bounce: 0` where set;
    - staggers;
    - blur radii of 2, 4 and 8px for "text and content crossfades".
  - **How it is applied.** Animation runs through `motion/react` (`AnimatePresence`, `layout`, `useMotionValue`, springs).
  - **Character.** Arc's signature is the blur-and-slide text swap, width morphs and rolling digits. Many components animate label changes this way.
- **Reduced motion is handled in two places.**
  - In JS: 80 of the 82 `.tsx` files (components plus `avatar/arc-provider.tsx`) call `useReducedMotion()` and swap springs for instant or opacity-only transitions.
  - In CSS: 75 of the 82 CSS files carry `@media (prefers-reduced-motion: reduce)`.
- **Pointer and touch.**
  - Hover styles sit behind `@media (hover: hover) and (pointer: fine)` in 64 CSS files.
  - Only 3 files have a `(pointer: coarse)` rule.
  - Control sizes come from `--control-height-sm` (36px) and `-md` (44px). Many inner controls are smaller (24 to 36px).
  - The 44px minimum is therefore not systematic.
- **Accessibility primitives.**
  - Most components hand-roll their ARIA: combobox, listbox, spinbutton, meter, tree, slider and live regions.
  - The overlays and menus use Radix: `@radix-ui/react-dialog`, `-popover`, `-dropdown-menu`, `-tooltip`, `-switch`, `-accordion` and `-tabs`. Where Radix provides the behaviour, the keyboard model is in the package, not in these files.
  - Strings are English literals or English defaults in props.
  - Number and date formatting defaults to `en-US`. The calendars compute "today" from the device clock (`calendar/use-today.ts`).
- **Framework.** The code is framework-agnostic. `avatar/arc-provider.tsx` lets an app pass `next/link` and `next/image` in. `changelog-feed` imports `next/image` directly.

**How Calevate's are built**

- **Tailwind v4 utilities on role tokens** declared in `apps/web/src/app/globals.css` and exposed through `@theme inline`:
  - surfaces and lines: `--app`, `--surface`, `--surface-muted`, `--line`;
  - text: `--text`, `--text-muted`, `--text-faint` (the utilities `text-ink`, `text-ink-muted` and `text-ink-faint`);
  - brand: `--brand`, `--brand-strong`, `--brand-deep`, `--brand-bright`, `--brand-soft`;
  - status: `--warn*` and `--danger*`;
  - charts: `--chart-warn`, `--chart-danger`, `--chart-neutral`;
  - elevation: `--elevation-1..3`;
  - a z-index scale: `--z-dropdown` 30, `--z-drawer` 40, `--z-assistant` 50, `--z-modal` 60, `--z-toast` 70;
  - motion: 140, 150, 200 and 280ms with `--ease-out-strong`.
- **No CSS Modules.** Shared looks are class-string constants in `components/ui.tsx` (`FIELD`, `PRIMARY_BUTTON`, `MODAL_PANEL`, `SITE_STRIP`, …).
- **Light only (D-471).** `:root` pins `color-scheme: light`, and the `.dark` block is dormant. Arc's dark theme and accent palettes have no use here.
- **Focus** is explicit on each control: `focus-visible:ring-2 focus-visible:ring-brand`. No global outline rule exists.
- **Touch.** A `touch:` variant (`@media (pointer: coarse)`) raises targets to 44px (`touch:min-h-11`).
- **Motion** is mostly CSS (`@starting-style`, utilities gated by `prefers-reduced-motion: no-preference`), with `motion` used in a few vendored components. The redesign brief (`docs/design/REDESIGN-2.md`) asks for a calm, plain style, with motion only where it explains state.
- **Money** is decimal strings (hard rule 7, `formatINR`). Time is IST (D-709, `formatIST*`).

**Token clashes.** `foundation.css` and `globals.css` both define these names, with different values:

- `--surface`;
- `--surface-muted`;
- `--text-muted`;
- `--danger`;
- `--duration-fast` (160ms against 150ms);
- `--ease-in-out`;
- `--shadow-raised`.

`--text-muted` also means a different thing in each. In Arc it is the faintest text, `oklch(59% 0 0)`. In Calevate it is the secondary text, `#475569`. Importing `foundation.css` at `:root` would recolour the existing consoles and add a second, `!important` focus indicator.

**What an adaptation always involves**

1. **A scoped token map, not `foundation.css`.** Define Arc's names on a wrapper (or rewrite them in the copied CSS) in terms of Calevate's tokens:

   | Arc token | Calevate token |
   |---|---|
   | `--foreground` | `--text` |
   | `--text-secondary` | `--text-muted` |
   | `--text-muted` | `--text-faint` |
   | `--border` | `--line` |
   | `--surface-muted` | `--surface-muted` |
   | `--accent`, `--control-on`, `--control-fill` | `--brand` |
   | `--accent-strong` | `--brand-strong` |
   | `--accent-subtle` | `--brand-soft` |
   | `--warning` | `--warn` |
   | `--danger` | `--danger` |
   | `--success` | `--brand` (Calevate has no `--success`) |
   | `--shadow-raised`, `--shadow-floating` | `--elevation-2`, `--elevation-3` |
   | `--series-1..4` | `--brand`, `--chart-warn`, `--chart-danger`, `--chart-neutral` |

   Radii come down to Calevate's (`--radius-card` 14px). The fonts stay PP Mori.
2. **Focus ring.** Restore `focus-visible` rings on every control whose CSS sets `outline: none`.
3. **Touch.** Raise every interactive element to 44px on coarse pointers.
4. **Strings.** Move every English literal to a prop, and default number and date formatting to `en-IN` and `Asia/Kolkata`.
5. **Motion.** Drop the blur crossfades, rolling digits and width morphs that do not explain a state change. Keep the reduced-motion paths.
6. **Z-index.** Replace hard-coded z-indexes (dialog and bottom-sheet 50/51, hover-card, toast-stack and the menus 60, tooltip 90) with Calevate's `--z-*` scale.
7. **Radix.** Replace Radix with the in-repo primitive where one exists:
   - `useFocusTrap` and `ModalDialog` for dialogs and sheets;
   - `RowMenu` for menus;
   - `interior/popover` and `usePopoverPlacement` for popovers;
   - `InfoTip` instead of hover tooltips.

---

## Summary: the founder's 71 components

The founder's list names 71 items. One of them, `login`, maps to two Free registry items (`sign-in` and `login-centered`), so 72 registry items are reviewed in Part A.

| Verdict | Count | Components |
|---|---|---|
| ADOPT | 0 | none. Every component needs at least the token, focus-ring and touch-size work above, plus the fixes in its section. |
| ADAPT | 23 | button-group, swipe-actions, search-field, inline-edit, number-field, tag-input, slider, calendar, date-picker, date-range-picker, expandable-text, bottom-sheet, hover-card, toast-stack, announcement-bar, usage-meter, bar-chart, sparkline, json-viewer, timeline, notification-center, stats-band, changelog-feed |
| SKIP | 48 | action-button, split-button, floating-button-group, expanding-button-group, copy-button, action-swap, confirm-morph, password-strength, expanding-search, money-input, mention-input, shortcut-recorder, combobox, multi-select, morph-select, chip-group, billing-toggle, plan-comparison, comparison-table, radio-group, switch, elastic-slider, rich-text-editor, file-dropzone, scroll-area, accordion, expandable-card, dialog, alert, toast, cookie-consent, countdown, onboarding-checklist, badge, metric-card, line-chart, donut-chart, brush-chart, gauge, activity-heatmap, ridgeline, sortable-data-table, filter-toolbar, text-shimmer, page-header, empty-states, login (sign-in, login-centered), slot-text |

"New npm" in the table below lists dependencies that `apps/web/package.json` does not have. `motion` (^13.1.1) and `lucide-react` (^1.31.0) are already there.

| Component | Verdict | Overlaps / would replace (Calevate) | New npm | Screen(s) |
|---|---|---|---|---|
| action-button | SKIP | `components/actionButton.tsx` wins (13 importers) | none | none |
| split-button | SKIP | `console/rowMenu.tsx` (menu half) | `@radix-ui/react-dropdown-menu` | none |
| button-group | ADAPT | menu half duplicates `RowMenu`; no joined action group exists | `@radix-ui/react-dropdown-menu` (removable via `RowMenu`) | possibly `calls/[callId]` and `leads/[leadId]` header actions (no screen has asked) |
| floating-button-group | SKIP | `leads/BulkActionBar.tsx` | `@radix-ui/react-tooltip` | none |
| expanding-button-group | SKIP | none | none | none |
| copy-button | SKIP | `interior/copy-button.tsx` wins (11 importers) | none | none |
| action-swap | SKIP | `actionButton.tsx`, `ui.tsx` `ToggleSwitch` | none | none |
| confirm-morph | SKIP | `confirmDialog.tsx` (36), `typedConfirmation.tsx` win | none | none |
| swipe-actions | ADAPT | none for the gesture; its menu duplicates `RowMenu` | `@radix-ui/react-dropdown-menu` (removable via `RowMenu`) | founder: calls and leads on mobile. `c/[slug]/calls`, `c/[slug]/leads` as a phone-only list; possibly `attention` |
| password-strength | SKIP | `passwordInput.tsx`, `authn/setPasswordForm.tsx` | none | none (policy is length only) |
| search-field | ADAPT | would become THE search field, replacing about 12 hand-rolled search inputs | none | `leads`, `campaigns`, `knowledge`, `messaging-consent`, `admin`, `admin/ops/config`, `admin/ops/dnc`, `admin/ops/voices/hosted` |
| expanding-search | SKIP | `interior/command-palette.tsx` (admin Cmd+K) | none | none |
| inline-edit | ADAPT | `leads/InlineName.tsx` stays for table cells | none | `leads/[leadId]` heading, agent and campaign renames |
| number-field | ADAPT | `type="number"` in 10 files; `ConfigInput.tsx` | none | `campaigns/new` (concurrency), agent call cap, admin prompt sections. Never money |
| money-input | SKIP | `ui.tsx` `FIELD_GROUP` + ₹ affix, `ConfigInput` `money_inr`, `billing/TopUp.tsx` | none | none (float money, no lakh grouping) |
| tag-input | ADAPT | none as a component | none | agent extraction panel (enum choices) |
| mention-input | SKIP | none | none | none |
| shortcut-recorder | SKIP | `<kbd>` hints only | none | none |
| combobox | SKIP | `console/searchSelect.tsx` wins | none | none |
| multi-select | SKIP | checkbox lists (`leads/FacetPanel.tsx`, `ColumnChooser.tsx`) | none | none |
| morph-select | SKIP | native `<select>`, `SearchSelect` | none | none |
| chip-group | SKIP | `ui.tsx` `FilterChip` wins (22 sites) | none | none |
| billing-toggle | SKIP | `interior/segmented-control.tsx` | none | founder: billing page. No monthly/annual period exists to toggle |
| plan-comparison | SKIP | `marketing/rateCard.tsx`, TopUp pack chooser | `@radix-ui/react-switch` (through `switch`) | founder: billing page. No plans to compare |
| comparison-table | SKIP | none (`dataTable.tsx` for data) | none | at most `pricing` / `roi` if marketing asks |
| radio-group | SKIP | `console/choiceCards.tsx` wins | none | none |
| switch | SKIP | `ui.tsx` `ToggleSwitch` wins (27 sites, 24 files) | `@radix-ui/react-switch` | none |
| slider | ADAPT | would replace `ui.tsx` `RANGE_INPUT` (3 callers) | none | agent voice tuning, call-handling pauses, `roi` |
| elastic-slider | SKIP | `RANGE_INPUT`, Arc `slider` | none | none |
| calendar | ADAPT | none (native date inputs) | none | engine for date-picker and date-range-picker |
| date-picker | ADAPT | native `type="date"` in 11 files (only as THE date control across all of them) | none | `campaigns/new`, lead-sources calling plan, admin rate cards, DLT registration |
| date-range-picker | ADAPT | `calls/CallsScreen.tsx` From/To + `lib/callFilters.ts` | none | `calls` custom range. Founder said campaigns, but campaigns take a start instant, not a range |
| rich-text-editor | SKIP | none (script fields are plain textareas) | none | founder: script page. Does not fit (HTML output; `javascript:` links pass) |
| file-dropzone | SKIP | `components/fileDrop.tsx` wins (5 screens) | none | founder: knowledge page. `FileDrop` is already there |
| scroll-area | SKIP | `ui.tsx` `ScrollRegion` wins (25 uses) | none | none |
| accordion | SKIP | `ui.tsx` `Disclosure` wins (36 uses) | `@radix-ui/react-accordion` | none |
| expandable-card | SKIP | `ui.tsx` `Disclosure` | none | none |
| expandable-text | ADAPT | replaces `interior/show-more.tsx` (0 callers) and the `Quote` clamp in `script/ProposalReview.tsx` | none | `agents/[agentId]/script`, `calls/[callId]`, `leads/[leadId]`, `knowledge` |
| dialog | SKIP | `modalDialog.tsx`, `confirmDialog.tsx`, `MODAL_*` win | `@radix-ui/react-dialog` | none |
| bottom-sheet | ADAPT | becomes the phone mode of `console/drawer.tsx` (28 caller files) | `@radix-ui/react-dialog` (removable via `useFocusTrap`) | founder: mobile viewport. Every `Drawer` on phones |
| hover-card | ADAPT (conditional) | `console/infoTip.tsx` stays for help; `interior/popover` placement | `@radix-ui/react-popover` (removable) | founder: desktop viewport. Lead and call row previews, admin tenants |
| alert | SKIP | `ui.tsx` `NoticeBox` / `ProblemNotice` (the D-771 notice style) | none | none |
| toast | SKIP | `interior/toaster.tsx` | none | none |
| toast-stack | ADAPT | would replace `interior/toaster.tsx` (3 files move) | none | both console shells |
| announcement-bar | ADAPT | renders through `ui.tsx` `SITE_STRIP`; absorbs `TrialBanner`'s dismissal | none | founder: "using this soon". Client and admin shells, public pages |
| cookie-consent | SKIP | none. `lib/legal/cookies.ts` explains why there is no banner | none (registry `button`, `switch`) | none |
| countdown | SKIP | `lib/authn/useCountdown.ts` | none | none |
| usage-meter | ADAPT | would replace `script/ScriptToolbar.tsx` `RoomLeft`; `ProgressBar` and `TrialMeter` stay | none | founder: "of great use". `billing` Usage tab, trial call panel |
| onboarding-checklist | SKIP (borrow 3 patterns) | `console/checklist.tsx` wins (16 sites) | none | founder: onboarding. Patterns go into `Checklist` on dashboard, `setup`, `go-live` |
| badge | SKIP | `console/statusPill.tsx` wins (79 files) | none | none |
| metric-card | SKIP | `console/metric.tsx` wins (85 uses) | none | none |
| line-chart | SKIP | none | none | none (no series for it) |
| bar-chart | ADAPT | would replace `DailyCalls.tsx`, `performance/PerformanceCharts.tsx` HourHistogram, `billing/SpendChart.tsx` | none | dashboard, `performance`, `billing` |
| donut-chart | SKIP | `OutcomeSplit.tsx`, `SentimentSplit.tsx`, `billing/WhereItWent.tsx` | none | none |
| brush-chart | SKIP | none | none | founder: leads and campaigns. Neither has a dated series |
| sparkline | ADAPT | none | none | dashboard tiles (`daily_7d`), billing spend headline |
| gauge | SKIP | `illustration/trialMeter.tsx` (different job) | none | founder: "rate our agent or script". Display only, cannot collect a rating |
| activity-heatmap | SKIP | none | none | founder: analytics. No endpoint has the data |
| ridgeline | SKIP | none | none | founder: analytics. No endpoint has the data |
| sortable-data-table | SKIP | `console/dataTable.tsx` wins (26 files) | none | none |
| filter-toolbar | SKIP | `leads/LeadsToolbar.tsx`, `FacetPanel.tsx`, `MoreFilters.tsx`, `FilterChip` win | none | none |
| json-viewer | ADAPT | none (raw `<pre>` today) | none | `agents/actions` tool test result, `integrations` delivery log |
| timeline | ADAPT | replaces `leads/[leadId]/LeadTimeline.tsx` (1 caller) | none | `leads/[leadId]` |
| text-shimmer | SKIP | `globals.css` `text-shimmer` utility wins | none | none |
| page-header | SKIP | `console/pageHeader.tsx` wins (72 files) | `@radix-ui/react-dropdown-menu`, `@radix-ui/react-tabs` | none |
| notification-center | ADAPT | sits on top of the bell → `attention` link (`ClientTopHeader.tsx`); admin `AttentionBell` | `@radix-ui/react-popover` (removable via `interior/popover`) | founder: "should be used already". Client and admin top-bar bells |
| empty-states | SKIP | `console/emptyState.tsx` + `emptySketch.tsx` win | none | none |
| login (sign-in, login-centered) | SKIP | `app/(auth)/auth/sign-in`, `authPage.tsx`, `authn/*` win | none | none. login-split and login-immersive are Pro |
| stats-band | ADAPT | `console/metric.tsx` stays for the consoles | none | founder: analytics and mockups. Marketing pages (`/`, `pricing`, `roi`, `why-calevate`, `industries`, `solutions`) and mockups |
| slot-text | SKIP | `console/valueFlash.tsx` | none | none |
| changelog-feed | ADAPT | none as a whole | none | founder: after launch. A release-notes page or "What's new" |

Two findings apply to almost every section and are not repeated as defects each time:

- **Focus ring.** The focus ring depends on `foundation.css`'s global rule, which Calevate lacks. Copied as they are, most Arc controls show no keyboard focus.
- **Strings and formatting.** Strings are hard-coded English, and number and date formatting defaults to `en-US`.

---

## Part A: the components

Sections follow the founder's order. `L123` refers to the component's `.tsx` in `docs/design/uiarc/registry/<name>/`, and `css L12` to its module CSS.

### action-button
**What it does:** A single async button that runs `onAction`, then morphs its label and trailing icon idle (arrow) → pending (spinner) → success (drawn tick), with the width springing to each label, and resets after `resetAfterMs`.

**Exports / API:** `ActionButton` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | idle text; also the visually hidden accessible name (L115) |
| successLabel | `string` | `"Saved"` | |
| pendingLabel | `string` | `"Saving"` | |
| onAction | `() => void \| Promise<void>` | required | a rejection returns to idle (L100-102) |
| resetAfterMs | `number` | `2400` | `0` keeps the success face |
| onActionError | `(error: unknown) => void` | — | the only error path; nothing is shown in the button |
| ...rest | `ButtonHTMLAttributes` minus `onClick`, `onDrag*`, `onAnimationStart` | — | spread onto `motion.button`; `className`, `disabled`, `type` (default `"button"`), `tabIndex` (default `0`) |

Other exports: type `ActionButtonProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both already in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Native `<button>`; visible content is `aria-hidden` (L111) and a visually hidden copy of `label` names it (L115).
- Pending sets `aria-busy` and `aria-disabled` but not `disabled`, so focus stays on the button through the save (L109-110); a second press while pending is ignored (L93).
- A `role="status"` span with the pending/success word sits INSIDE the button (L116). Its text is part of the button's accessible name, so the name becomes "Save Saving" / "Save Saved" while it runs, and a live region inside a named button is announced unreliably.
- No focus style in the module CSS; it relies on Arc's global `:focus-visible` outline (`arc-foundation/foundation.css` L187-191), which Calevate does not have.
- Reduced motion: `whileTap` dropped, width jumps, labels and icons swap with instant fades, tick drawn at once (L54, L67, L78, L110, L113); CSS stops the spinner and transitions (css L20).
- Touch target: `min-height: var(--control-height-md)` = 44px (css L2).

**Mobile:** `display: inline-flex`, `white-space: nowrap` (css L2, L7): a long label does not wrap and can overflow a 320px column. Hover shadow only under `(hover: hover) and (pointer: fine)` (css L3).

**Issues found in the code:**
- Accessible name changes during the action (status span inside the button, L115-116) — the exact defect `components/actionButton.tsx` was written to avoid (its header comment, L9-15).
- No error face: a failure silently snaps back to the idle label (L100-102); the caller must render the error elsewhere.
- Hard-coded English defaults `"Saved"`/`"Saving"` (L83).
- The arrow icon is always present at idle (L113) — fine for "Continue", wrong for a plain Save; no prop to omit it.
- Decorative motion: blur-in icons and a width spring on every label change (L26-35, L56); the drawn tick is the only part that explains state.
- Arc tokens collide by name with Calevate's (`--surface`, `--text-muted`, `--danger` mean different values in `apps/web/src/app/globals.css`); the fill is `var(--foreground)` (near-black, css L2), not Calevate's `bg-brand-strong` primary.
- Registry description calls it "a compact button for frequent toolbar actions"; the code is a 44px primary-weight button.

**Overlaps in Calevate:** `apps/web/src/components/actionButton.tsx` (`ActionButton`: `loading` prop, inline spinner, label kept mounted so the name never changes, brand fill; 13 importing files) and `apps/web/src/components/interior/loading-button.tsx` (`LoadingButton` + `useAsyncAction` with idle/pending/success/error and a sibling live region; 0 importers, listed in `apps/web/tests/componentConsumers.test.ts` `AWAITING_A_DECISION`). Ours wins: it keeps a stable accessible name, uses the brand primary, and is already the one primary-with-spinner. Arc's success-tick-and-reset idea is what `LoadingButton` already offers; if a success face is wanted, adopt `LoadingButton` (or add a success state to ours) rather than a third button.

**Where in Calevate:** none needed. Save-style buttons on `app/c/[slug]/settings/*` and `app/admin/tenants/[tenantId]/*` already use `components/actionButton.tsx`.

**Verdict: SKIP** — duplicates `components/actionButton.tsx` with a worse accessible-name behaviour, no error state and a non-brand fill.

**Source:** `docs/design/uiarc/registry/action-button/`

---

### split-button
**What it does:** A two-part pill: a main action button and a chevron that opens a Radix dropdown of related actions; the main label morphs letter by letter when it changes.

**Exports / API:** `SplitButton` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | main button text; also builds the chevron's name (L103) |
| actions | `SplitButtonAction[]` (`{label, onSelect?, disabled?, destructive?, icon?}`) | required | items keyed by `label` (L106) |
| onClick | `() => void` | — | main action |
| disabled | `boolean` | — | disables both halves |
| icon | `ReactNode` | — | morphs when the icon element type changes (L25-30) |
| variant | `"primary" \| "secondary"` | `"primary"` | |

Other exports: types `SplitButtonAction`, `SplitButtonProps`.

**Dependencies:** npm: **`@radix-ui/react-dropdown-menu` (new)**, `motion`, `lucide-react`. Registry: `arc-motion-tokens`.

**Accessibility:**
- Two native buttons. Main button content is `aria-hidden` (L95); a visually hidden `aria-live="polite"` span with `label` inside the button names it (L101). The live region sits inside the button, so the docs.md claim that a label change is announced is not reliable.
- Chevron: Radix `Trigger` with `aria-label={`${label} more actions`}` (L103); menu semantics, arrow keys and Escape-to-trigger come from Radix DropdownMenu (docs.md L98-105; not verifiable from this source), with `loop` set (L105).
- No focus style in the module CSS; relies on Arc's global outline.
- Reduced motion: glyph morph becomes a fade, width jumps (L48, L81, L97); CSS drops press scale and menu transform (css L49-54).
- Sizes: main half 44px tall (css L5); chevron 38px wide (css L14); `secondary` variant 36px tall, chevron 32px wide (css L24, L26) — under 44px.

**Mobile:** No wrap or collapse; docs.md says to give the secondary variant (142px minimum, css L25) its own row on phones. Menu `collisionPadding={12}` keeps it on screen (L105).

**Issues found in the code:**
- New Radix dependency for a menu Calevate already has (`RowMenu`).
- Hard-coded English concatenation `"${label} more actions"` (L103).
- No `href` items (navigation must go through `onSelect`), no `hint`/disabled reason, no per-item accessible name; `key={action.label}` breaks on duplicate labels (L106).
- Menu `z-index: 60` (css L32) equals Calevate's `--z-modal`, above `--z-dropdown` (30) and `--z-drawer` (40): the menu would paint over an open drawer's scrim.
- Per-letter blur morph with stagger (L18-19, L81) is decorative motion.
- No pending/loading state on the main half.

**Overlaps in Calevate:** `apps/web/src/components/console/rowMenu.tsx` (`RowMenu`: portal, APG menu button, `href` items, `hint`, `ariaLabel`, `tone: "danger"`, `z-dropdown`, `touch:min-h-11` items and `touch:h-11 touch:w-11` trigger; 16 importing files) covers the menu half. No split button exists today. If one is needed, compose `PRIMARY_BUTTON` + `RowMenu` rather than take a second menu implementation.

**Where in Calevate:** no current screen has one default action with close variants; `app/c/[slug]/leads/LeadsToolbar.tsx` "Export this view as CSV" is a single action. Not determined from the source that any screen needs it.

**Verdict: SKIP** — its value is the Radix menu, which duplicates `RowMenu` and adds a new dependency; a split button, if ever needed, is `PRIMARY_BUTTON` plus `RowMenu`.

**Source:** `docs/design/uiarc/registry/split-button/`

---

### button-group
**What it does:** Related actions joined into one bordered surface with hairline dividers, a single highlight that glides between segments on hover/press/focus, optional collapse to icons when the row overflows, and an optional trailing chevron opening a Radix dropdown menu.

**Exports / API:** `ButtonGroup` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `ButtonGroupItem[]` | required | `{id, label, reserve?, icon?, iconOnly?, content?, onSelect?, href?, disabled?}` |
| menu | `ButtonGroupMenu` (`{label, items: ButtonGroupMenuItem[]}`) | — | items `{id, label, icon?, onSelect?, href?, disabled?, destructive?}` |
| label | `string` | required | group `aria-label` |
| variant | `"outline" \| "solid"` | `"outline"` | |
| size | `"sm" \| "md"` | `"md"` | |
| orientation | `"horizontal" \| "vertical"` | `"horizontal"` | |
| collapseLabels | `boolean` | `true` | horizontal only; icon segments drop labels on overflow (L214-233) |
| disabled | `boolean` | `false` | disables every segment and the menu |
| className | `string` | — | |
| style | `CSSProperties` | — | |

Other exports: types `ButtonGroupVariant`, `ButtonGroupSize`, `ButtonGroupOrientation`, `ButtonGroupItem`, `ButtonGroupMenuItem`, `ButtonGroupMenu`, `ButtonGroupProps`.

**Dependencies:** npm: **`@radix-ui/react-dropdown-menu` (new)**, `motion`, `lucide-react`. Registry: `arc-motion-tokens`.

**Accessibility:**
- `role="group"` with `aria-label` (L316). Every segment is in the Tab order; Arrow keys along the orientation (RTL-aware, L270-272), Home and End also move focus (L264-278). This is a group, not an APG toolbar, so no roving tabindex.
- A disabled segment uses `aria-disabled` and stays focusable (L300, L312); the whole-group `disabled` uses native `disabled` (L312).
- Collapsed/icon-only segments get `aria-label` and a `title` tooltip (L307-308); otherwise a visually hidden copy of the label (L311-312).
- A label that changes within 1s of its own press ("Copied") is announced once through a polite live region (L280-294, L322).
- Highlight follows keyboard focus only when `:focus-visible` (L253-260); module CSS has no outline of its own.
- Reduced motion: highlight jumps, text swaps with instant fades (L124, L182-185); CSS removes press scale and menu transform (css L83-87).
- Sizes: `md` segments `calc(44px - 2px)` = 42px tall (css L3, L18); `sm` 34px; chevron `bg-h - 6px` wide = 38px (css L22). Menu items 36px (css L73).

**Mobile:** `overflow-x: auto` with a hidden scrollbar (css L4-5): a group wider than the screen scrolls sideways with no visible cue. `collapseLabels` measures the parent with ResizeObserver and swaps to icons (L219-233). Touch press sets the highlight (L235-250).

**Issues found in the code:**
- New Radix dependency for the chevron menu, which duplicates `RowMenu`.
- `href` segments and menu items render plain `<a href>` (L311, L335), not `next/link`: a full page load inside the Next.js app and no realm-aware `href()`.
- Hidden horizontal scroll (css L4-5) hides segments at 320px if `collapseLabels` is off or segments have no icons.
- Menu `z-index: 60` (css L63) collides with Calevate's `--z-modal`.
- Decorative motion: blurred text crossfade on label change (L72-73) and the gliding highlight.
- Segments slightly under 44px on touch (42px md, 34px sm, 38px chevron).
- Group `aria-disabled` dims to `.52` opacity (css L11) without a reason being shown.

**Overlaps in Calevate:** `apps/web/src/components/interior/segmented-control.tsx` (20 importing files) covers single-choice selection; ButtonGroup is for actions, not selection, so that is not a duplicate. The menu half duplicates `apps/web/src/components/console/rowMenu.tsx` (16 importing files), which wins. There is no joined action group in Calevate today (no `role="toolbar"` anywhere under `apps/web/src`).

**Where in Calevate:** possible in `app/c/[slug]/calls/[callId]` (call header actions) or `app/c/[slug]/leads/[leadId]` header actions; not determined from the source that those screens want joined segments rather than separate buttons.

**Verdict: ADAPT** — usable as a joined action strip only after replacing the Radix menu with `RowMenu`, swapping `<a>` for `next/link`, raising segment height to 44px on touch (`touch:min-h-11`) and mapping tokens; otherwise SKIP if no screen asks for it.

**Source:** `docs/design/uiarc/registry/button-group/`

---

### floating-button-group
**What it does:** A tray of separate soft buttons (an APG toolbar) with one shared highlight that morphs to the hovered or keyboard-focused button; a `floating` variant raises it with a shadow for overlays such as a selection toolbar. Icon-only items show their label in a Radix tooltip. Despite the name, it does not position itself; the caller places it.

**Exports / API:** `FloatingButtonGroup` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `readonly FloatingButtonGroupItem[]` | required | actions `{type?: "action", id, label, icon?, iconOnly?, onSelect?, disabled?, pressed?, shortcut?, reserveLabels?}` or `{type: "separator", id?}` |
| label | `string` | required | toolbar `aria-label` |
| variant | `"muted" \| "floating"` | `"muted"` | |
| size | `"sm" \| "md"` | `"md"` | |
| orientation | `"horizontal" \| "vertical"` | `"horizontal"` | |
| iconOnly | `boolean` | `false` | item `iconOnly` wins |
| tooltipSide | `"top" \| "bottom" \| "left" \| "right"` | top (row) / right (column) | |
| onAction | `(id: string) => void` | — | after the item's `onSelect` |
| className | `string` | — | |
| style | `CSSProperties` | — | |

Other exports: types `FloatingButtonGroupVariant`, `FloatingButtonGroupSize`, `FloatingButtonGroupOrientation`, `FloatingButtonGroupAction`, `FloatingButtonGroupSeparator`, `FloatingButtonGroupItem`, `FloatingButtonGroupProps`.

**Dependencies:** npm: **`@radix-ui/react-tooltip` (new)**, `motion`. Registry: `arc-motion-tokens`, `tooltip` (`registry/tooltip/tooltip.tsx`, itself on `@radix-ui/react-tooltip`).

**Accessibility:**
- `role="toolbar"`, `aria-label`, `aria-orientation` (L247-249); roving tabindex (one tab stop, L128, L270); Arrow keys skip disabled items and wrap, Home/End (L211-233). Arrow keys are not RTL-aware (L215-216).
- `aria-pressed` for mode toggles (L268), `aria-disabled` keeps disabled items focusable (L269); separators `role="separator"` (L256).
- Every button has `aria-label={itemLabel}` (L267). A label change ("Copied") changes the name; there is no live region, so the change is not announced.
- The shared highlight is described as "the toolbar's only hover and focus indicator" (L111); it appears on keyboard focus only (L278-283). Without Arc's global outline there is no ring; the highlight is a 7% foreground tint (css L7), weak against WCAG 2.4.11/1.4.11 and invisible under forced colors.
- Tooltips appear on hover/focus only, not on tap.
- Reduced motion: highlight lands in place (L161, L171), text swaps with instant fades (L72); CSS shortens transitions (css L71-74).
- Sizes: items 36px (`md`) or 30px (`sm`) tall (css L4, L16) — under 44px.

**Mobile:** `flex-wrap: nowrap` and the tray "keeps its natural size and never wraps" (css L1, L14): a long tray overflows a 320px screen. `touch-action: manipulation` on items (css L34). Icon-only labels live in hover tooltips, which a phone cannot reach.

**Issues found in the code:**
- New Radix tooltip dependency (and a second registry component) for a title-on-hover.
- No visible focus indicator in Calevate without adding `focus-visible:ring-2 focus-visible:ring-brand`.
- Touch targets 30/36px.
- Side tooltip `z-index: 90` (css L62) is above Calevate's `--z-toast` (70).
- Hard-coded `:root[data-theme="dark"]` block (css L21-27) is dead weight in a light-only product (D-471).
- Decorative motion: morphing highlight and blurred label crossfade (L65-66).

**Overlaps in Calevate:** `apps/web/src/app/c/[slug]/leads/BulkActionBar.tsx` is a hand-built sticky selection toolbar (`role="group"`, `aria-label="Bulk actions"`), the case the `floating` variant is aimed at. It holds selects (stage, owner), not only buttons, so FloatingButtonGroup cannot replace it as is. No generic toolbar exists.

**Where in Calevate:** not determined from the source that any screen needs an icon toolbar; the bulk bar on `app/c/[slug]/leads` is the only candidate and is better kept as is.

**Verdict: SKIP** — needs a new Radix dependency, has sub-44px targets and a weak focus indicator, and Calevate has no icon-toolbar use; the one selection toolbar it could serve holds selects it cannot render.

**Source:** `docs/design/uiarc/registry/floating-button-group/`

---

### expanding-button-group
**What it does:** A pill of icon buttons where one always shows its label; pointing at or focusing another slides the label over to it. An action can confirm in place (icon becomes a drawn tick, label becomes a past-tense word). On touch, the first tap reveals the label and a second tap runs the action.

**Exports / API:** `ExpandingButtonGroup` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `readonly ExpandingButtonGroupItem[]` | required | `{id, label, icon, onSelect?, doneLabel?, tone?: "neutral" \| "danger", disabled?}`; `onSelect` may return `false` or a promise |
| label | `string` | required | toolbar `aria-label` |
| size | `"sm" \| "md"` | `"md"` | |
| defaultExpanded | `string \| null` | `null` | resting expanded id; falls back to the first enabled item (L206-207) |
| onAction | `(id: string) => void` | — | before the item's `onSelect` |
| confirmDuration | `number` | `1400` | ms the done face stays |
| className | `string` | — | |
| style | `CSSProperties` | — | merged into the `--ebg-*` vars (L336) |

Other exports: types `ExpandingButtonGroupSize`, `ExpandingButtonGroupTone`, `ExpandingButtonGroupItem`, `ExpandingButtonGroupProps`.

**Dependencies:** npm: `motion`. Registry: `arc-motion-tokens`.

**Accessibility:**
- `role="toolbar"`, `aria-label`, `aria-orientation="horizontal"` (L340-342); roving tabindex (L152, L209); ArrowLeft/Right wrap, Home/End (L322-333), not RTL-aware.
- Each button `aria-label={item.label}` at all times (L149), `aria-disabled` keeps disabled items focusable (L150), `aria-busy` while a promise runs (L151).
- Done word announced via a polite `role="status"` region, with a zero-width space so repeats re-announce (L228-229, L363).
- Only keyboard focus (`:focus-visible`) expands (L278-286). No focus outline in the module CSS.
- Reduced motion: width jumps, label/icon swap instantly (L64-66, L130-131, L159); CSS stops the busy pulse (css L40-44).
- Sizes hard-coded in px: 28px (`sm`) and 36px (`md`) tall (L47-50) — under 44px.

**Mobile:** Two-tap model on touch (L265-276): the first tap only reveals the label. Widths spring on every hover/focus, so neighbours move; on a phone, revealing one label shifts every other button.

**Issues found in the code:**
- Errors are swallowed: a thrown or rejected `onSelect` sets `result = false` and shows nothing (L252-257); no error face, no `onError`.
- Busy state is only an opacity pulse on the icon (css L13-14); no spinner, nothing visible under reduced motion beyond `opacity: .6`.
- Geometry in px constants (L47-50) rather than `--control-height-*`; touch targets 28/36px.
- Content jumps: the layout moves under the pointer by design; meaning sits behind hover (labels hidden until pointed at), which a phone user cannot scan.
- Decorative motion: blur on label slide (L60-61), icon pop (L70), width spring on every hover.
- Dark-theme block (css L17-18) unused here.

**Overlaps in Calevate:** none (no expanding icon group exists).

**Where in Calevate:** none recommended. Call and lead actions on `app/c/[slug]/calls/[callId]` and `app/c/[slug]/leads/[leadId]` should be labelled buttons; hiding labels behind hover works against the plain, phone-first console.

**Verdict: SKIP** — hover-revealed labels, sub-44px targets, swallowed errors and motion that moves layout under the user do not fit a phone-first SMB console.

**Source:** `docs/design/uiarc/registry/expanding-button-group/`

---

### copy-button
**What it does:** Copies `value` to the clipboard and crossfades the icon (copy → drawn tick / alert) and label ("Copied" / "Failed") in a cell sized to the widest state, then resets.

**Exports / API:** `CopyButton`

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `string` | required | |
| label | `string` | `"Copy"` | idle text and `aria-label` (L46) |
| className | `string` | — | |
| iconOnly | `boolean` | `false` | 36px square (css L123) |
| variant | `"outline" \| "plain"` | `"outline"` | |
| disabled | `boolean` | — | |
| onCopied | `() => void` | — | called only on success (L38-40) |

Other exports: type `CopyButtonProps`; from `use-copy-feedback.ts`: `useCopyFeedback(duration = 1900)` returning `{state, activeKey, copy, reset}`, type `CopyFeedbackState`.

**Dependencies:** npm: `motion`, `lucide-react`. Registry: `arc-motion-tokens`. Files: `copy-button.tsx`, `copy-button.module.css`, `use-copy-feedback.ts` (installed to `@components/arc/lib/`, matching the `../lib/use-copy-feedback` import, L6).

**Accessibility:**
- Native button named by `aria-label={label}` (L46); visible text `aria-hidden` (L59).
- A sibling `role="status" aria-live="polite"` span announces `"<label>: Copied"` / `"<label>: Could not copy"` (L66) — outside the button, which is the reliable placement.
- No focus style in the module CSS.
- Reduced motion: instant fades, no scale, no stroke draw (L29, L53-54, L62-63; css L126).
- Size: `min-height: var(--control-height-sm)` = 36px; icon-only 36px square (css L109, L123) — under 44px.

**Mobile:** `width: max-content; max-width: 100%` (css L109); reserves the widest label so it never shifts (L60). No touch-size bump.

**Issues found in the code:**
- Clipboard path is `navigator.clipboard.writeText` only (`use-copy-feedback.ts` L28-35): fails on insecure origins and older WebViews with no `execCommand` fallback. Calevate's `copyText` has that fallback.
- Hard-coded English: `"Copy"`, `"Copied"`, `"Failed"`, `"Could not copy"` (L33, L36, L60, L66); no props for the copied/error words.
- Default `aria-label` "Copy" repeats identically across rows of a list.
- 36px targets on touch.
- `.button:active` press scale in CSS (css L110-111) on top of motion; fine, but duplicates Calevate's `press` utility.

**Overlaps in Calevate:** `apps/web/src/components/interior/copy-button.tsx` (`CopyButton`, `copyText`, `useCopyToClipboard`; 11 importing files including `app/c/[slug]/leads/LeadTable.tsx`, `app/c/[slug]/leads/[leadId]/LeadDetailScreen.tsx`, `app/c/[slug]/calls/[callId]/CallHeader.tsx`). Ours wins: `execCommand` fallback, required `label` naming WHAT is copied, `copiedLabel`/`errorLabel` props, `touch:h-11 touch:w-11`, brand tokens and focus ring, and `copyText` is the one clipboard path that `RowMenu` items reuse.

**Where in Calevate:** already served by ours on `app/c/[slug]/calls/[callId]`, `app/c/[slug]/leads/[leadId]`, `app/c/[slug]/leads`, `app/c/[slug]/lead-sources`, `app/c/[slug]/caller-notice`, `app/admin/payments`, `app/admin/ops/dnc`, `app/admin/ops/config`.

**Verdict: SKIP** — a weaker duplicate of the vendored copy button (no clipboard fallback, hard-coded words, 36px target).

**Source:** `docs/design/uiarc/registry/copy-button/`

---

### action-swap
**What it does:** A pill that cycles through a list of states on press (for example Follow → Following, or Send → Sending → Sent → back), optionally running an async `onAction` with a working face (pending label or a folded round spinner) and a failure face, morphing width, tone, icon and letters on springs.

**Exports / API:** `ActionSwap` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| states | `ActionSwapState[]` | required | `{id, label, icon?, tone?: "neutral" \| "accent" \| "success" \| "warning" \| "quiet", pendingLabel?, holdFor?}` |
| value | `string` | — | controlled state id |
| defaultValue | `string` | first state's id | |
| onValueChange | `(value: string, state: ActionSwapState) => void` | — | |
| onAction | `(next, current) => void \| PromiseLike<unknown>` | — | a promise shows the working face; rejection shows `failureLabel` |
| failureLabel | `string` | `"Try again"` | |
| size | `"sm" \| "md" \| "lg"` | `"md"` | 36 / 44 / 50px (css L5-7) |
| ...rest | `ButtonHTMLAttributes` minus `children`, `onChange`, `onClick`, `value`, `onDrag*`, `onAnimationStart` | — | `className`, `disabled`, `style`, `type`, `tabIndex` |

Other exports: types `ActionSwapTone`, `ActionSwapState`, `ActionSwapProps`.

**Dependencies:** npm: `motion`, `lucide-react`. Registry: `arc-motion-tokens`.

**Accessibility:**
- Native button; `aria-label={view.label || activeState.label}` (L196), so the accessible name changes with each state, including to "Try again".
- Working keeps focus (`aria-disabled` + `aria-busy`, not `disabled`, L196); fewer than two states disables it (L140).
- A sibling polite `role="status"` span announces the new state, the pending label or failure (L147, L152, L161, L204).
- No `aria-pressed` for two-state toggles (Follow/Following), so the on/off state is conveyed only by the changing name.
- No focus style in the module CSS.
- Reduced motion: instant swaps, no press scale, no fold spring (L80, L120, L185, L196-199); CSS stops the spinner (css L39).

**Mobile:** `white-space: nowrap`, pill hugs content (css L4); 44px at `md`.

**Issues found in the code:**
- Hard-coded English `"Working"` (L161) and `"Try again"` (L128).
- The rejection reason is discarded (L158, L164): no `onError`, so the caller cannot show why it failed.
- `MIN_WORKING` holds the spinner at least 450ms even when the server answered (L37, L163).
- Decorative motion: per-letter blur morph with stagger (L52-53, L120), success icon clip-path wipe (L59-61), padding fold to a circle (L184-185).
- A state machine that cycles on press is easy to misread for actions that change customer data; it is a toggle without toggle semantics.

**Overlaps in Calevate:** partial overlap with `apps/web/src/components/actionButton.tsx` (async with spinner) and `ui.tsx` `ToggleSwitch` (26 callers, per the brief's inventory) for on/off state. No cycling-state button exists.

**Where in Calevate:** none recommended. On/off settings use `ToggleSwitch`; one-shot actions use `ActionButton`.

**Verdict: SKIP** — a toggle without `aria-pressed`, a name that changes, and the most decorative motion of the set; Calevate already covers both of its jobs.

**Source:** `docs/design/uiarc/registry/action-swap/`

---

### confirm-morph
**What it does:** An inline destructive-action button: pressing it morphs the same pill into a question with Cancel and Confirm, then a spinner, then a result with Undo (or an error with Retry). Confirm can be a press, a press-and-hold, or a press followed by a cancellable countdown. Unanswered questions and results time out back to rest.

**Exports / API:** `ConfirmMorph` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `ReactNode` | required | resting text |
| icon | `ReactNode` | — | |
| prompt | `ReactNode` | `label` + "?" | |
| confirmLabel | `string` | `"Delete"` | |
| cancelLabel | `string` | `"Cancel"` | |
| pendingLabel | `string` | `"Deleting"` | |
| doneLabel | `string` | `"Deleted"` | |
| errorLabel | `string` | `"Couldn’t finish"` | |
| retryLabel | `string` | `"Retry"` | |
| undoLabel | `string` | `"Undo"` | |
| undoingLabel | `string` | `"Restoring"` | |
| tone | `"danger" \| "neutral"` | `"danger"` | |
| confirmMode | `"press" \| "hold" \| "countdown"` | `"press"` | |
| holdDuration | `number` | `1000` | ms |
| countdown | `number` | `3` | seconds |
| countdownLabel | `string` | `"${pendingLabel} in"` | |
| onConfirm | `() => void \| Promise<unknown>` | — | rejection → error face |
| onUndo | `() => void \| Promise<unknown>` | — | adds Undo |
| onCancel | `() => void` | — | also on Escape, outside press, timeout |
| state | `ConfirmMorphState` | — | controlled |
| defaultState | `ConfirmMorphState` | `"idle"` | |
| onStateChange | `(state: ConfirmMorphState) => void` | — | |
| confirmTimeout | `number` | `6000` | ms; `0` off |
| resultTimeout | `number` | `5000` | ms; `0` off |
| cancelOnOutsidePress | `boolean` | `true` | |
| disabled | `boolean` | `false` | |
| className | `string` | — | |
| ref | `Ref<HTMLDivElement>` | — | root; takes focus while pending |

Other exports: types `ConfirmMorphState` (`"idle" \| "confirming" \| "pending" \| "done" \| "error"`), `ConfirmMorphMode`, `ConfirmMorphProps`.

**Dependencies:** npm: `motion`, `lucide-react`. Registry: `arc-motion-tokens`.

**Accessibility:**
- Focus follows the morph: Confirm while asking, root (`tabIndex={-1}`) while counting/pending, Undo or Retry on a result, trigger at rest — but only if focus was already inside (L194-198, L349-358).
- Question face is `role="group"` labelled by the prompt (L129, L438); leaving faces get `inert` (L130).
- Escape cancels a question or dismisses a result (L360-365); Enter confirms from the question except on a button (L366-371); hold mode works with held Enter/Space (L374-379) and has an sr-only "Press and hold" description (L389, L403).
- Polite `role="status"` region announces each step (L441).
- Reduced motion: width jumps, faces fade without blur or stagger (L110-111, L257); spinner slows to 1.6s rather than stopping (css L140).
- Focus is drawn by fill only: `.root, .root :focus { outline: none; }` and 6-8% tints on `:focus-visible` (css L121-122, L132-136) — weak contrast and invisible under forced colors.
- Sizes: pill 36px (`--control-height-sm`, css L24); Cancel/Confirm/Undo/Retry `36px - 8px` = 28px tall (css L73) — well under 44px.

**Mobile:** The question face grows inline to prompt + Cancel + Confirm; `.prompt` caps at 16rem and ellipsises (css L65-66), so a long consequence is cut. On a 320px row the pill can push neighbours. Outside press cancels (L341-347).

**Issues found in the code:**
- Timeouts pause only for pointer hover and a hidden tab (L264-288, L434-435), not for keyboard focus or a screen reader: the question cancels itself after 6s and the Undo disappears after 5s for those users (WCAG 2.2.1 Timing Adjustable).
- The prompt is truncated with an ellipsis (css L65-66): the consequence, which is the point of a confirmation, can be lost.
- 28px answer buttons beside each other on a phone invite a mis-tap on the destructive answer.
- Focus indicator removed (css L121-122).
- Hard-coded English: defaults (L169-170), `"Undone"` (L239), `"Cancelled"` (L244), `" is available."` (L241), `"Keep holding to …"` with `toLowerCase()` (L325, breaks for non-Latin scripts), `"… seconds"` (L335), `"Press and hold"` (L403).
- Thrown/rejected errors are discarded (L226, L231): the error face shows a generic `errorLabel`, never the server's reason (Calevate's `ProblemNotice` pattern shows the problem).
- `onContextMenu` preventDefault and `user-select: none` in hold mode (L391, css L96).
- Decorative motion: blur-in parts with stagger, popping success disc, rolling digits (L101-109, L137-166).

**Overlaps in Calevate:** `apps/web/src/components/confirmDialog.tsx` (`ConfirmDialog` on `ModalDialog`: consequence as the description, Cancel first, focus on the container, refusal shown in the panel, `pending` label; 36 importing files) and `apps/web/src/components/typedConfirmation.tsx` (type-to-confirm; 23 importing files). Ours wins for every irreversible action (DNC un-suppress, removing access, turning off an endpoint): the modal gives room for the consequence and the server's refusal. ConfirmMorph could only add value for small, reversible actions with a real Undo; Calevate has no such inline-confirm pattern today.

**Where in Calevate:** none recommended for client screens. Destructive actions on `app/c/[slug]/do-not-call` (`RestoreDialog.tsx`, `SuppressedList.tsx`) and `app/c/[slug]/settings/*` already use `ConfirmDialog`.

**Verdict: SKIP** — self-cancelling timers, a removed focus ring, 28px answer buttons and a truncated consequence make it weaker than `ConfirmDialog` for the irreversible actions Calevate confirms.

**Source:** `docs/design/uiarc/registry/confirm-morph/`

---

### swipe-actions
**What it does:** A list whose rows slide horizontally to reveal leading (left) and trailing (right) actions, like a mail inbox. Only one row is open at a time; a long swipe commits the outermost action and the row slides out and collapses. Every row also gets a "More actions" dropdown with the same actions as the non-gesture path.

**Exports / API:** `SwipeActions` (list; also the default export), `SwipeActionsRow` (row)

`SwipeActions`:

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | `aria-label` of the `<ul>` (L75) |
| children | `ReactNode` | required | `SwipeActionsRow`s, keyed, direct children (wrapped in `AnimatePresence`, L76) |
| className | `string` | — | |

`SwipeActionsRow`:

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | names the row in "More actions for {label}" (L301) |
| leading | `SwipeAction[]` | `[]` | revealed by swiping right; outermost = index 0 |
| trailing | `SwipeAction[]` | `[]` | revealed by swiping left; outermost = last |
| fullSwipe | `boolean` | `true` | long swipe commits the outermost action |
| children | `ReactNode` | required | row content |
| className | `string` | — | |

`SwipeAction`: `{label: string; icon: ReactNode; tone?: "neutral" \| "accent" \| "danger"; onSelect: () => void; keepRow?: boolean}` (L12-21). No `id`, `href`, `disabled` or async result.

Other exports: types `SwipeAction`, `SwipeActionsProps`, `SwipeActionsRowProps`.

**Dependencies:** npm: **`@radix-ui/react-dropdown-menu` (new)**, `motion`, `lucide-react`. Uses `useEffectEvent` from `react` (L3, L270, L274), exported by the installed React 19.2.4. Registry: `arc-motion-tokens`.

**Gesture handling (from the code):**
- Pointer events on the row's content layer: `onPointerDown/Move/Up/Cancel` (L297). Only the primary pointer, and only the left mouse button (L198).
- `touch-action: pan-y` on the content (css L11): the browser keeps vertical panning; horizontal movement is delivered to the handlers.
- Axis lock: nothing happens until the pointer has moved 8px (`SLOP`, L49, L209). If `|dy| > |dx|` the gesture is locked to "y" and ignored for the rest of the press (L210, L206); otherwise it locks to "x", re-bases `startX` so the row does not jump, and takes `setPointerCapture` (L211-216). If the browser starts a vertical scroll it fires `pointercancel`; with no x lock nothing moves (L225-238).
- Drag: row follows the finger (`x.set`, L218-219); past its stop it rubber-bands (`rubberBand`, L56, L175-182). A side with no actions does not move (limit 0, L179).
- Stops and threshold: open stop = number of actions × 76px (`ACTION`, L47, L111). Full-swipe commit threshold = `max(openWidth + 48, rowWidth × 0.56)` (L114), with 20px hysteresis once armed (L165). Arming stretches the outermost action across the row and calls `navigator.vibrate?.(8)` on touch (L168-172).
- Velocity: last 80ms of up to 12 samples (L82-88, L220-221). Release (L184-194): commit if armed and not flicked back (`outward > -900`), or if flung (`distance > open && outward > 900px/s && distance + v×0.1s > threshold`); otherwise snap open if the projected travel passes half the open width, else close. Springs carry the release velocity, and a home-bound spring is clamped so it does not overshoot into the opposite side (L130-133).
- Tap vs swipe: a click after an x-locked drag is swallowed (L230, L240-245); a tap on an open row closes it instead of activating the row's link (L237).
- Group: one open row; a pointerdown outside the open row or Escape anywhere closes it (L64-71).
- Removal: on commit the row slides off; if the item is still in the list 1.4s later (the action failed or kept it), the row slides back (L157-159). Undo that re-adds the item while leaving slides it home (L273-281).

**Accessibility:**
- `<ul role="list" aria-label>` with `<li>` rows (L75, L288).
- Keyboard/screen-reader alternative: each row's "More actions for {label}" Radix dropdown holds every leading and trailing action (L283, L299-311). The revealed swipe buttons are `tabIndex={-1}` and `aria-hidden` (L346-347). After a removing action, focus moves to the next (or previous) row's More button, else the list (L247-257, L305-306).
- The menu trigger cancels `pointerdown` and opens on click (`event.detail > 0`) so a swipe starting on it still moves the row (L300-301); keyboard opening is Radix's.
- `.more:focus-visible { outline: none; }` and `.list:focus-visible { outline: none; }` (css L8, L18): inside Arc the global `!important` outline still wins; in Calevate, without that rule, the More button has no focus indicator.
- Touch targets: More button 32×32px (css L15) — under 44px. Revealed actions are 76px wide and the row is at least 64px tall (L47, css L11). Menu items 36px (css L47).
- Reduced motion: the row jumps to its stops, rows fade instead of collapsing height (L118, L128, L153, L284-290); CSS drops menu motion (css L59-64).
- Not RTL-aware: leading is always the left edge (L57, css L28-29).

**Mobile:** Built for phones. Row content has `user-select: none` and `-webkit-touch-callout: none` (css L11), which blocks long-press selection and copy of anything in the row (a phone number, a name). Haptic `vibrate` does nothing where the Vibration API is absent.

**Table vs list:** The component renders its own `<ul>`/`motion.li` (L75, L288); it cannot wrap `<tr>` rows. `LeadTable` and the call log are real `<table>`s through `components/console/dataTable.tsx` (`DataTable`, inside `ScrollRegion`, L296-297 there) on every width, and the leads table scrolls sideways on a phone with the name column pinned (`LeadTable.tsx`, `pin`). Putting `touch-action: pan-y` rows inside that horizontal `ScrollRegion` would also fight the table's own sideways scroll. Using swipe-actions on these screens therefore means a separate phone-width list rendering (for example `sm:hidden` list + `hidden sm:block` table) of the same rows, not a change to `DataTable`.

**What the Radix dropdown is used for:** only the per-row "More actions" menu (L299-311), the accessible path to the swipe actions. Calevate's `RowMenu` (`components/console/rowMenu.tsx`) does the same job (APG menu button, portal, `href` items, disabled `hint`, `tone: "danger"`, `z-dropdown`, `touch:h-11 touch:w-11` trigger, `touch:min-h-11` items) and is already the "More" menu in `LeadTable.tsx` (L88-98 there). Replacing Radix with `RowMenu` removes the new dependency; the swallow-on-pointerdown trick (L301) and the focus hand-off after removal (L305) must be kept when doing so.

**Issues found in the code:**
- New Radix dependency for a menu `RowMenu` already provides.
- `fullSwipe` defaults to `true` (L90): a long swipe commits with no confirmation and no built-in Undo. For destructive Calevate actions (adding a number to do-not-call) this must be `false` or the action must not be offered as a swipe.
- `onSelect` is synchronous (L18) with no pending or error state: the row slides away before the server answers; failure shows nothing except the row sliding back after 1.4s (L159).
- Hard-coded English `"More actions for ${label}"` (L301).
- Focus indicator removed on the More button and list (css L8, L18); More button 32px.
- `user-select: none` / `-webkit-touch-callout: none` on row content (css L11) blocks copying numbers from call and lead rows.
- The document-level Escape handler closes the open row on any Escape, including one meant for a dialog, and does not check `defaultPrevented` (L67).
- `ACTION` 76px and `SLOP` 8px are constants, not props (L47, L49).
- Menu `z-index: 60` (css L42) collides with Calevate's `--z-modal`.
- Not RTL-aware (leading = left).

**Overlaps in Calevate:** none for the gesture. The menu half duplicates `apps/web/src/components/console/rowMenu.tsx` (16 importing files), which wins.

**Where in Calevate:** founder's note — "especially for caller page, lead page and other relevant pages in mobile viewport for faster actions". Concretely: `app/c/[slug]/calls` (call log; rows today carry one link and no row menu) and `app/c/[slug]/leads` (rows today have Call, status, owner and a `RowMenu` with Open lead, Open the last call, Copy phone number), as a phone-width list beside the existing `DataTable`. Candidate swipe actions are non-destructive, `keepRow: true` ones: call back (the existing `CallControl` flow), copy number (`copyText`), set status. `app/c/[slug]/calls/[callId]` and `app/c/[slug]/leads/[leadId]` are single records, not lists, so swipe rows do not apply there; their action buttons should stay visible. `app/c/[slug]/attention` (the bell's list) is another list where swipe-to-dismiss fits, if its items have a dismiss action (not determined from the source).

**Verdict: ADAPT** — the gesture engine (axis lock, velocity projection, rubber band, tap-vs-swipe, focus hand-off) is sound and is what the founder asked for on phone lists; take it with `RowMenu` in place of Radix, `fullSwipe` off by default, async `onSelect` with a visible failure, `user-select` restored on row text, a 44px More button with the brand focus ring, localisable labels, and a phone-only list rendering for the calls and leads screens.

**Source:** `docs/design/uiarc/registry/swipe-actions/`

---

### password-strength
**What it does:** A new-password field with a show/hide toggle, a four-segment strength meter, a checklist of rules with a rolling "N more" count, and an error row that shakes the field once per new error. Scoring is local (`estimateStrength`, L146-153): the level is the share of rules met spread over four steps, held at step 1 ("Too short") below `shortLength`.

**Exports / API:** `PasswordStrength` (forwardRef to the `<input>`; also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | visible `<label htmlFor>` (L282) |
| value | `string` | — | controlled |
| defaultValue | `string` | `""` | uncontrolled |
| onValueChange | `(value: string, strength: PasswordStrengthResult) => void` | — | called after the native `onChange` (L285) |
| rules | `PasswordRule[]` | `defaultPasswordRules` | default = length ≥12, upper+lower, number, symbol (L124-134) |
| error | `string` | — | sets `aria-invalid`, shows the error row, shakes once per new value (L264-271) |
| revealed | `boolean` | — | controlled reveal |
| onRevealedChange | `(revealed: boolean) => void` | — | |
| messages | `PasswordStrengthMessagesInput` | English defaults (L56-67) | every user-facing string is overridable |
| shortLength | `number` | `8` (via `estimateStrength`) | |
| countCharacters | `(password: string) => number` | `countCodePoints` | |
| ...rest | `InputHTMLAttributes<HTMLInputElement>` minus `type`/`value`/`defaultValue`/`children` | — | spread onto the input after the autocomplete/spellcheck defaults (L284) |

Other exports: `estimateStrength`, `createPasswordRules`, `defaultPasswordRules`, `countCodePoints`, `defaultPasswordStrengthMessages`, types `PasswordRule`, `PasswordStrengthResult`, `PasswordStrengthLevels`, `PasswordStrengthMessages`, `PasswordStrengthMessagesInput`, `PasswordStrengthProps`, `PasswordRuleLabels`, `PasswordRuleOptions`, `EstimateStrengthOptions`.

**Dependencies:** npm: `motion` (in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Reveal button: static name "Show password" plus `aria-pressed`, `aria-controls` the input (L287) — the same pattern `components/passwordInput.tsx` argues for.
- Meter: `role="meter"` with `aria-valuemin/max/now/valuetext` (L291); per-rule `srOnly` ", met"/", not met" (L312); a `role="status"` summary after every change (L321); the input's `aria-describedby` carries the error and the rules list (L279).
- Input defaults `autoComplete="new-password"`, `autoCapitalize="off"`, `autoCorrect="off"`, `spellCheck={false}` (L284), but they sit before `{...props}`, so a caller can override them.
- Reduced motion: a hydration-gated `reduced` flag (L157-159, L239-241) swaps every variant to a plain fade and skips the shake (L267); CSS kills transitions and the reveal keyframes (css L53-57).
- Focus: the shell darkens its border on `:focus-within` (css L10); the reveal button has no focus style of its own and relies on Arc's global `:focus-visible` outline in `foundation.css`.
- Touch target: reveal button 34×34px (css L21), under 44px.

**Mobile:** Input font rises to `--text-base` on `(pointer: coarse)` so iOS does not zoom (css L15). Shell `min-height: var(--control-height-md)` = 44px (css L8). The strength word has a fixed 4.5rem slot (css L35), so a longer translated word is clipped by `nowrap`.

**Issues found in the code:**
- The default rules are composition rules (mixed case, number, symbol, L116-131). Calevate's policy is length only: `lib/authn/password.ts::passwordRule` says "Length is the only rule: no required symbols, digits or capitals" (NIST SP 800-63B-4). With only a length rule, `estimateStrength` gives level 4 "Strong" to any password at or past the floor (L151), so the meter carries no information.
- Default counting is code points (L97); Calevate's `passwordProblem` counts UTF-16 units deliberately to stay at least as strict as the server. `countCharacters` can be set, but the default disagrees.
- The reveal button has no `onMouseDown` preventDefault and no caret restore, so a click moves focus to the button and the caret position is not put back; `passwordInput.tsx` L178-197, L229 handle both.
- Decorative motion: blur on the strength word, the rolling digits and the error copy (L162-173, L227); a blur keyframe on reveal (css L17-20); a sideways shake on error (L270).
- Hard-coded English defaults (L56-67, L116-121); all overridable through `messages` and `createPasswordRules({ labels })`.
- Tones use `--danger/--warning/--success` (css L3-5); Calevate has `--danger` and `--warn`, no `--success` (brand green would be the mapping).

**Overlaps in Calevate:** `apps/web/src/components/passwordInput.tsx` (`PasswordInput`, "the ONE password input", imported by 4 files: `components/authn/fields.tsx` for the auth forms, plus `integrations/ConnectedAccounts.tsx`, `lead-sources/AddSourceDrawer.tsx`, `lead-sources/RotateDrawer.tsx`) and `components/authn/setPasswordForm.tsx` (hint from `passwordRule`, length check from `passwordProblem`). `PasswordInput` wins: it already has the same a11y pattern plus caret preservation, and Arc's meter has nothing to score under a length-only policy.

**Where in Calevate:** would be `app/(auth)/auth/reset-password`, `app/signup` (via `CreateAccountForm`), `app/(auth)/auth/accept-invitation`; none needs a strength meter under the current rule.

**Verdict: SKIP** — a share-of-rules meter contradicts the length-only password policy and the reveal is weaker than `PasswordInput`; at most, the "N more characters" count for the length floor could be added to `setPasswordForm`'s hint without this component.

**Source:** `docs/design/uiarc/registry/password-strength/`

---

### search-field
**What it does:** A labelled `type="search"` input with a leading magnifier and a clear button that appears in a reserved slot once there is a value; clearing refocuses the field.

**Exports / API:** `SearchField` (forwardRef to the `<input>`)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | always rendered as a VISIBLE `<label>` (L14) |
| value | `string` | required | controlled only |
| onValueChange | `(value: string) => void` | required | every keystroke, no debounce |
| ...rest | `InputHTMLAttributes<HTMLInputElement>` minus `type` | — | spread onto the input (L15) |

Other exports: type `SearchFieldProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Native `<label htmlFor>` (L14); `type="search"` gives the searchbox role; the browser's own cancel button is hidden (css L13) and replaced by `aria-label="Clear search"` (L17).
- Clear returns focus to the input (L13) because the button unmounts.
- No Escape-to-clear handler; no live announcement of results (the caller owns that).
- Reduced motion: the clear button only fades (L17); CSS removes transitions (css L17).
- Focus: field shows focus by border colour only (css L6); the clear button relies on the global `foundation.css` focus outline.
- Touch target: clear button 24×24px (css L14-15), under 44px.

**Mobile:** Shell `min-height: var(--control-height-md)` = 44px (css L4). Input font is `--text-sm` (14px) with no coarse-pointer override (css L10), so iOS Safari zooms on focus; `password-strength` handles this (its css L15), this one does not.

**Issues found in the code:**
- No option to hide the label visually; `LeadsToolbar.tsx` uses `aria-label="Search leads"` with no visible label, so a caller would need a `hideLabel` addition.
- Hard-coded English `"Clear search"` (L17).
- Clear button 24px on touch; input 14px on touch (see above).
- Decorative blur-and-scale on the clear button (L17).
- `tabIndex={0}` on a `<button>` is redundant (L17).
- No `maxLength` default; callers must pass it (Leads search is capped at 60 by the API, `LeadsToolbar.tsx` L98-99).

**Overlaps in Calevate:** No shared search component exists. The pattern is hand-rolled (lucide `Search` icon absolutely positioned over `FIELD_INLINE_ICON` from `components/ui.tsx`, or a bare `type="search"`), in up to 12 screen files that match the pattern: `c/[slug]/leads/LeadsToolbar.tsx`, `c/[slug]/campaigns/CampaignsListScreen.tsx`, `campaigns/ContactEditor.tsx`, `campaigns/ContactResults.tsx`, `knowledge/WhatItKnows.tsx`, `messaging-consent/ConsentLookup.tsx`, `admin/page.tsx`, `admin/ops/config/ConfigSearch.tsx`, `admin/ops/dnc/DncScreen.tsx`, `admin/ops/voices/hosted/AddVoicesDrawer.tsx`, `admin/ops/voices/hosted/HostedVoicesScreen.tsx`, `admin/ops/AuditChainPanel.tsx` (each needs reading before it is moved; the two command palettes and the marketing mockups are excluded). Arc's should become THE search field, with those callers moved in the same change.

**Where in Calevate:** `/c/[slug]/leads` (name/number search; the "what did they ask for" box is a submit-on-Enter form and needs an `onSubmit` path, `LeadsToolbar.tsx` L126-148), `/c/[slug]/campaigns`, `/c/[slug]/knowledge`, `/c/[slug]/messaging-consent`, `/admin`, `/admin/ops/config`, `/admin/ops/dnc`, `/admin/ops/voices/hosted`.

**Verdict: ADAPT** — the right size of component for one-way search, but add `hideLabel`, a 44px touch clear target, 16px text on coarse pointers, an Escape-to-clear key and a translatable clear label, drop the blur, and map tokens to `FIELD_INLINE_ICON`'s look.

**Source:** `docs/design/uiarc/registry/search-field/`

---

### expanding-search
**What it does:** An icon button that morphs into a search combobox and drops a results panel; it ranks a caller-supplied in-memory `items` array (title start > word start > substring > meta/keyword, L56-68), groups results, shows `suggestions` when empty, and collapses on Escape, on choosing, or on blur with an empty query. This is a different component from the interior `expanding-search` reviewed in `docs/design/UI-COMPONENTS.md` L353-399 (that one had `onSearch` debounce and `resultCount`; this one has neither).

**Exports / API:** `ExpandingSearch` (also default)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | names the button, input and listbox |
| items | `ExpandingSearchItem[]` | required | `{ id, title, meta?, group?, icon?, keywords? }` |
| suggestions | `ExpandingSearchItem[]` | `[]` | shown before typing |
| suggestionsLabel | `string` | `"Recent"` | |
| placeholder | `string` | `label` | |
| onSelect | `(item: ExpandingSearchItem) => void` | — | fired after collapse (L265-268) |
| onExpandedChange | `(expanded: boolean) => void` | — | |
| expandedWidth | `number` | `360` | capped by the container width (L216) |
| maxResults | `number` | `6` | |
| anchor | `"start" \| "end"` | `"end"` | |
| emptyHint | `string` | `"Try a shorter word or check the spelling."` | |
| className | `string` | — | |

Other exports: types `ExpandingSearchItem`, `ExpandingSearchProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Input is `role="combobox"` with `aria-expanded`, `aria-controls`, `aria-autocomplete="list"`, `aria-activedescendant` (L291-293); results `role="listbox"` with `role="group"` sections and `role="option"` rows with `aria-selected` (L151-177).
- Keys: ArrowUp/Down wrap, Enter chooses, Escape collapses and returns focus to the trigger (L270-282). Input is `inert` while collapsed (L291); `flushSync` makes it focusable inside the click so a touch keyboard opens (L234-239).
- `role="status"` announces counts (L263, L332).
- Clear button is `tabIndex={-1}` (L307): pointer only.
- Reduced motion: width jumps (L232), panel skips the unfold and only fades (L94, L100-104), rows drop layout animation (L156, L165).
- Touch target: trigger 44px (css L2 `--control-height-md`); options `min-height: 48px` (css L35); clear 28px (css L23).

**Mobile:** Grows to the container width, never past it (L216). Panel `max-height: min(22rem, 60vh)` (css L28): `vh`, not `dvh`. Panel `z-index: 40` literal (css L26), which equals Calevate's `--z-drawer`, not `--z-dropdown` (30).

**Issues found in the code:**
- No query callback: the component filters `items` itself and exposes no `onQueryChange`/`onSearch`, so it cannot drive a server-side search. Calevate's list searches go to the API (`LeadsToolbar.tsx` L96-99, capped at 60 characters by the API).
- Enter with no active option does nothing (L278); there is no submit path for a free-text query.
- Hard-coded English: `"Recent"`, the empty hint, `"No results for"`, `"Results for"`, `"result(s)"`, `"item(s)"`, `"Clear search"` (L186, L263, L307, L326-327).
- Decorative motion: morph with overshoot (`spring.morph`, L232), blur on the clear button and on view swaps (L284, L321), gliding highlight (L139-142).
- Collapsing on blur clears the typed query (L247, L303) only when empty, but choosing or Escape always discards it.

**Overlaps in Calevate:** `apps/web/src/components/interior/command-palette.tsx` via `app/admin/AdminCommandPalette.tsx` (jump to an entity from a known list). For list filtering, the hand-rolled search fields listed under `search-field`. Neither should give way to this.

**Where in Calevate:** none that fits; the only in-memory "jump to" need is already the admin command palette.

**Verdict: SKIP** — a client-side ranker behind a decorative morph; Calevate's searches are server-side and desktop list pages want an always-open field (`search-field`).

**Source:** `docs/design/uiarc/registry/expanding-search/`

---

### inline-edit
**What it does:** Click-to-edit text: the display is a `<button>` that turns into an input or auto-growing textarea with identical metrics; Enter or blur saves optimistically through `onSave`, a drawn check confirms, a rejected promise rolls the text back with a "Couldn't save … Try again" message, and Escape cancels.

**Exports / API:** `InlineEdit` (also default)

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `string` | required | external changes replace the text when not editing or saving (L139-145) |
| onSave | `(next: string) => void \| Promise<unknown>` | required | reject to roll back (L252-268) |
| label | `string` | required | accessible name; also lower-cased into messages (L251, L303) |
| validate | `(next: string) => string \| null \| undefined` | — | message shown under the field (L238-240) |
| placeholder | `string` | `""` | |
| multiline | `boolean` | `false` | Shift+Enter adds a line (L291) |
| variant | `"title" \| "body"` | `"title"` | type size via CSS (css L4-5) |
| as | `"span" \| "p" \| "h1" \| "h2" \| "h3"` | `"span"` | element holding the text |
| className | `string` | — | |

Other exports: none (type `InlineEditProps` is exported).

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Uses React `useEffectEvent` (L3), available in React 19.2 (apps/web has 19.2.4). Registry: `arc-motion-tokens`.

**Accessibility:**
- Display button `aria-label="<label>: <value>"` plus a hint "Activate to edit." (L321-322, L354); keyboard activation selects all, a click puts the caret where it landed (L229-233).
- Field: `aria-label`, `aria-invalid`, `aria-describedby` hint "Enter saves, Escape cancels." (L311-313, L355). Focus returns to the display after Enter or Escape (L196-205).
- Status: `role="status"` "Saving…"/"saved" (L251, L256, L356); the error row is `aria-live="polite"` (L93).
- The no-change case sends nothing (L246), which matters for the leads table (`InlineName.tsx` L25-27).
- Reduced motion: hydration-gated flag (L46-51); text and icons fade only, size changes snap (L173); CSS stops the spinner and transitions (css L73).
- Touch target: save/cancel 28×28px (css L53), under 44px; the pencil is an `<svg>` with an `onClick` (L346), not a button (the display button covers keyboard use).

**Mobile:** Room for the actions is reserved with `padding-inline-end: 66px` on every line (css L8), which costs width at 320px. The pencil appears only on hover for fine pointers (css L36-40); on touch it is always visible.

**Issues found in the code:**
- The whole text is a `<button>`, so it cannot also be a link. `InlineName.tsx` keeps the lead name as a `<Link>` to the lead and puts a separate pencil beside it (its docstring L37-39); Arc cannot express that.
- No `maxLength` prop; the field is not reachable from props (`fieldProps`, L311-314). The lead name column is capped at 120 by the API (`InlineName.tsx` L85-86).
- Failure is owned inside the component (L304-308); on the leads table the row owns one shared error slot (`InlineName.tsx` L29-35, `RowFailure.tsx`), so the in-cell message would duplicate it.
- Hard-coded English: "Saving", "saved", "Couldn't save … is back.", "Try again", "Save", "Cancel editing", "Activate to edit.", the key hints (L251, L256, L307, L340-341, L354-355); `label.toLowerCase()` (L303) breaks for scripts without case and for proper nouns.
- Decorative motion: blur on text and icons (L53-66), drawn tick (L69-73), width morph while typing (L175).
- Blur saves (L295-301), matching `InlineName`, but a blur caused by a failed `validate` leaves the field open with no focus (L240 only refocuses for key/button).

**Overlaps in Calevate:** `apps/web/src/app/c/[slug]/leads/InlineName.tsx` (1 caller: `leads/useLeadRowKit.tsx`). `InlineName` wins on the table (link + edit, row-level failure, `maxLength`, per-lead accessible names). Arc's is a candidate only where the text is not a link.

**Where in Calevate:** `/c/[slug]/leads/[leadId]` (the lead's name in the page heading, `LeadDetailScreen.tsx` L195, not editable today), and an agent's or campaign's own name on its detail screen if renaming in place is wanted; not `/c/[slug]/leads` table cells.

**Verdict: ADAPT** — the save/rollback/validate model is sound for a heading-style rename, but it needs a `maxLength` pass-through, 44px touch actions, translatable strings, no blur, and an option to defer failure display to the caller; do not replace `InlineName`.

**Source:** `docs/design/uiarc/registry/inline-edit/`

---

### number-field
**What it does:** A bounded numeric stepper: minus and plus buttons that repeat and accelerate while held, arrow/Page/Home/End keys, a typed draft that applies live while valid, odometer-style rolling digits, a "Max/Min" note when a limit refuses a press, and optional label scrubbing.

**Exports / API:** `NumberField`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | `<label htmlFor>` (L453) |
| value | `number` | — | controlled |
| defaultValue | `number` | `0` | |
| onValueChange | `(value: number) => void` | — | clamped value (L334) |
| min | `number` | `0` | |
| max | `number` | `Number.MAX_SAFE_INTEGER` | |
| step | `number` | `1` | values snap to `min + n*step` (L282) |
| largeStep | `number` | `step * 10` | PageUp/Down, Shift+Arrow |
| description | `string` | — | animated hint row |
| disabled | `boolean` | — | |
| id | `string` | `useId()` | |
| prefix | `NumberFieldAffix` | — | `string \| (value) => string` |
| suffix | `NumberFieldAffix` | — | e.g. `n => n === 1 ? " seat" : " seats"` |
| scrub | `boolean` | `false` | drag the label |
| locale | `string` | `"en-US"` | |
| formatOptions | `{ minimumFractionDigits?, maximumFractionDigits?, useGrouping? }` | follows `step` precision | |
| size | `NumberFieldSize` (`"sm" \| "md" \| "lg"`) | `"md"` | |
| limitHint | `boolean \| ((edge: "min" \| "max", limit: number) => string)` | `true` | |

Other exports: types `NumberFieldProps`, `NumberFieldAffix`, `NumberFieldSize`.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Input `role="spinbutton"` with `aria-valuenow`, `aria-valuetext` (prefix + formatted + suffix), `aria-valuemin/max` (L464-466); `inputMode` numeric/decimal/text by sign and precision (L464).
- Keys: ArrowUp/Down (Shift for large), PageUp/Down, Home/End to limits when not typing, Enter commits or selects, Escape reverts the draft (L389-397).
- Step buttons: named "Increase/Decrease <label>", `aria-controls` the input, stay focusable at a limit with `aria-disabled` (L218-226); keyboard/AT click takes one step (`detail === 0`).
- `aria-live="polite"` announces button/limit changes (L329-330, L475).
- Reduced motion: wheels jump, digits only fade, no strain kick (L118, L126, L313); CSS removes transform transitions (css L67-71). `useReducedMotion` here is not hydration-gated, unlike the other Arc fields.
- Touch target: step buttons 34px at `md`, 28px at `sm`, 40px at `lg` (css L2-4, L23), all under 44px.

**Mobile:** Default width 196px, capped at 100% (css L2, L15). Scrub uses `touch-action: pan-y` so vertical scroll still works (css L12). Held-press repeat suppresses the context menu (L224).

**Issues found in the code:**
- Values are JS numbers with `toFixed`-based rounding (L280, L282, L284); fine for counts, wrong for money (hard rule 7) — must not be used for rupees.
- `locale` defaults to `"en-US"`; with `"en-IN"` the display uses `Intl` parts (L69-78, L278), so lakh grouping would follow the locale, but the default does not.
- Hard-coded English: "Increase"/"Decrease" (L222), "Max"/"Min" (L448), ", maximum"/", minimum" (L329).
- Decorative motion: blur on digit wheels and words (L83-85, L101, L143), sideways strain kick and icon shake at a limit (L314-316), rubber-band scrub (L66, L430).
- `limitHint` note is `nowrap` (css L10) and sits beside the label in a row as wide as the control (css L7); a long translated note crowds the label at 164-196px.
- No error/invalid prop beyond the out-of-range warning tint (css L19).

**Overlaps in Calevate:** No stepper exists. Numeric entry is `type="number"` in 10 files (e.g. `campaigns/NewCampaignSteps.tsx` L415 "Calls at the same time", 1-10; `agents/panels/delivery.tsx` L141 call cap in seconds) and `type="text" inputMode="numeric"` in `admin/ops/config/ConfigInput.tsx` L289-291. Arc's would be the bounded-small-integer control, not a replacement for every numeric field.

**Where in Calevate:** `/c/[slug]/campaigns/new` (concurrency 1-10), `/c/[slug]/agents/[agentId]` delivery panel (call cap), admin agent prompt sections `replyLength`/`voiceTuning`/`callCap` under `/admin/tenants/[tenantId]/agents/[agentId]/prompt`.

**Verdict: ADAPT** — a correct spinbutton for small bounded counts; needs 44px touch steppers, translatable labels, `en-IN` default, the strain/blur motion removed, and must be fenced off from money.

**Source:** `docs/design/uiarc/registry/number-field/`

---

### money-input
**What it does:** A large currency amount field with a currency menu, live digit grouping that preserves the caret, faint "ghost" fraction digits, quick-add chips, min/max checking and an amount that scales down to fit. The value is an integer count of minor units (paise for INR).

**Exports / API:** `MoneyInput` (forwardRef to the `<input>`; also default)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | |
| hideLabel | `boolean` | `false` | label becomes sr-only and `aria-label` is set (L482, L492) |
| value | `number \| null` | — | minor units, controlled |
| defaultValue | `number \| null` | `null` | |
| onValueChange | `(value: number \| null, details: MoneyInputDetails) => void` | — | `details = { currency, major: number \| null, formatted }` |
| currency | `string` | — | ISO 4217, controlled |
| defaultCurrency | `string` | `"USD"` | |
| onCurrencyChange | `(currency: string) => void` | — | |
| currencies | `string[]` | `["USD","EUR","GBP","JPY","CAD","AUD","CHF","INR"]` | one code hides the menu |
| min | `number` | — | minor units; checked on blur |
| max | `number` | — | minor units; typing past it is refused |
| quickAdd | `number[]` | `[10, 50, 100]` | MAJOR units; `[]` hides |
| step | `number` | one major unit | Arrow keys; Shift ×10 |
| locale | `string` | `"en-US"` | |
| description | `string` | — | |
| error | `string` | — | replaces the built-in range message |
| disabled | `boolean` | `false` | |
| name | `string` | — | hidden input posting minor units (L556) |
| id | `string` | — | |
| className | `string` | — | |
| onBlur | `(event: FocusEvent<HTMLInputElement>) => void` | — | |

Other exports: types `MoneyInputDetails`, `MoneyInputProps`.

**How the value is held and emitted (hard rule 7):**
- Internally the draft is a canonical STRING such as `"1234.5"` (L100, L229); it is converted to a JS `number` of minor units by `toMinor` (L102-106): `Number(whole) * 10 ** digits + Number(fraction)`. Integer digits are capped at 12 (L68, L310), so the largest value is under 10^14 paise, inside `Number.MAX_SAFE_INTEGER`; the minor-unit integer itself is exact.
- Emitted: `value` as a `number` of paise, and `details.major = minor / 100` (L274), which is a binary float (e.g. 1015900 / 100 is exact, but arbitrary paise values divided by 100 are not representable). `details.formatted` comes from `Intl.NumberFormat` on that float (L256, L274).
- Calevate's money crosses the wire as decimal STRINGS (`formatINR` in `components/ui.tsx` L1475 never parses; `billing/TopUp.tsx` holds `amount` as a string and sends `amountInr: amount`, L85, L321; `ConfigInput.tsx` L292 "never `number`: a number input hands back a float"). Using this component means converting paise integer to a rupee string at the boundary (string arithmetic, not `major` or `toFixed` on a float), and the hidden `name` input posts paise, not the rupee string the API takes.
- `fromMinor` rounds a non-integer `value` with `Math.round` (L109) silently.
- Arrow/chip arithmetic (L342, L373-381) is integer addition on minor units: exact.

**Currency and locale:**
- INR is in the default list; `Intl` with `currencyDisplay: "narrowSymbol"` gives the ₹ symbol (L81).
- en-IN lakh grouping is NOT supported in the field. Grouping is a fixed three-digit regex (`groupInteger`, L122) and `partsOf` inserts a separator every three places (L138); only the group and decimal CHARACTERS come from the locale (L95-98). With `locale="en-IN"` the visible field shows `1,234,567.00` while `aria-valuetext`, the announcement and the range text, which use `Intl` (L256, L471, L493), say `₹12,34,567.00` — the screen and the screen reader disagree.
- With `currencies={["INR"]}` the menu hides but the ISO code "INR" is still printed beside the amount (L529); there is no prop to hide it.
- Defaults are `"USD"` and `"en-US"` (L214-215).

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Input `type="text" role="spinbutton"`, `inputMode` decimal/numeric, `aria-valuenow` in major units (a float), `aria-valuetext` formatted, `aria-valuemin/max`, `aria-invalid`, `aria-describedby` range/hint/error (L491-494).
- Keys: ArrowUp/Down (Shift ×10), PageUp/Down ×10, Enter settles the fraction; Backspace over a group separator deletes the digit before it (L337-352). Paste accepts "$1,234.56", "1.234,56 €" (L354-369).
- Currency menu: button `aria-haspopup="listbox"`, `aria-expanded`, `aria-controls`; listbox with `aria-activedescendant`, Arrow/Home/End/Enter/Space/Escape/Tab and type-ahead (L503-525, L448-467); closes on outside pointerdown (L417-422).
- Error is `role="alert"` (L549); a polite status announces chips, steps, limits and currency changes (L270, L284, L444, L557).
- Reduced motion: hydration-gated flag (L70-74); glyphs fade, no kick, no scale animation (L163-164, L266, L395); CSS zeroes transition durations (css L77).
- Touch target: control 76px tall (css L6); currency button 36px (css L38); chips 30px (css L61); menu options 36px (css L50) — the last three are under 44px.

**Mobile:** Font drops one step and padding narrows under 420px (css L76); the amount scales to fit rather than scroll (L385-401). Menu width `min(256px, calc(100vw - 2rem))` uses `vw` (css L47); menu `z-index: 30` literal (css L47), equal to Calevate's `--z-dropdown`.

**Issues found in the code:**
- Number in/out with a float `major` (above): a hard-rule-7 hazard at the boundary.
- No lakh grouping; visible and spoken amounts disagree under `en-IN` (above).
- Hard-coded English: "Maximum/Minimum is", "The minimum/maximum is", "to", "Up to", "At least", "Empty", "Quick add", "Add", "Currency" (L270, L471-474, L493, L515, L533, L538).
- No negative amounts (the sanitizer drops "-", L290-311); fine for top-ups, not for adjustments.
- `min` is only checked on blur (L474), so a below-minimum amount can be submitted from a form without a blur if the caller does not re-check.
- Decorative motion: rolling, blurred glyphs (L154-158), sideways kick on refusal (L66-67, L266), symbol roll (L193-195), menu blur (L512), message blur (L550).
- The input text is transparent and painted by a mirror (css L25); behaviour under Windows forced-colors is not determined from the source.
- Hard-coded radii 14px on menu highlight and options (css L49-50).

**Overlaps in Calevate:** `components/ui.tsx` `FIELD_GROUP` + `FIELD_GROUP_AFFIX` with a "₹" affix (used for ₹ in `agents/first/QuestionsStep.tsx` L354-358; the other two affix uses are "+91" and a map pin), `admin/ops/config/ConfigInput.tsx` `money_inr` (string draft, `inputMode="decimal"`, absolutely positioned ₹, L289-354), and `c/[slug]/billing/TopUp.tsx` "Other amount" (string state, bare ₹ span, L323-336). All three hold rupees as strings and stay the winners for money; Arc's would have to be rebuilt around a string value to replace them.

**Where in Calevate:** the candidate is `/c/[slug]/billing` top-up "Other amount" (₹ min/max from `MIN_TOPUP_INR`/`MAX_TOPUP_INR`) and `/admin/ops/config` `money_inr` settings, and `/admin/ops` rate cards (`RateCardPanel.tsx`, `ModelPricingPanel.tsx`); none should take it as written.

**Verdict: SKIP** — it holds and emits money as JS numbers with a float `major`, cannot group in lakhs, and shows a USD-first currency menu Calevate never needs; the existing string-based `FIELD_GROUP` ₹ pattern is correct under hard rule 7. The caret-preserving grouping is the one idea worth re-implementing on a string value.

**Source:** `docs/design/uiarc/registry/money-input/`

---

### tag-input
**What it does:** A chip field: Enter or comma adds the trimmed draft as a tag, case-insensitive duplicates are refused with a pulse on the existing tag, Backspace at the start picks the last tag and a second Backspace removes it, arrows move the pick, blur commits the draft. This is a smaller component than the interior `tag-input` reviewed in `docs/design/UI-COMPONENTS.md` L1493-1530: no `max`, no `validate`, no paste splitting, no `separators`.

**Exports / API:** `TagInput`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | visible `<label htmlFor>` (L132) |
| value | `string[]` | — | controlled |
| defaultValue | `string[]` | `[]` | |
| onValueChange | `(value: string[]) => void` | — | |
| placeholder | `string` | `"Add a tag"` | |
| description | `string` | — | animated hint, wired to `aria-describedby` |
| id | `string` | `useId()` | |

Other exports: type `TagInputProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Native label and `aria-describedby` hint (L132, L144); an `aria-live="polite"` region says "Added", "Removed", "already added", "selected. Press Backspace to remove it." (L98-108, L147).
- Keys: Enter/comma add; Backspace/Delete remove the picked tag; Backspace at start picks the last; ArrowLeft/Right move the pick; Escape clears the pick (L109-122). There is no IME `isComposing` guard on Enter (L114), unlike `inline-edit` L291.
- Each tag's remove button is a normal tab stop, named "Remove <tag>" (L143).
- Reduced motion: no layout animation, opacity only (L129-130, L139-143); CSS drops transitions (css L34).
- Focus: shell border + `--focus-ring` shadow (css L8; `--focus-ring` is `transparent` in `foundation.css`, so only the border shows).
- Touch target: tags 28px tall, remove buttons 22×22px (css L11-12), under 44px.

**Mobile:** The shell grows with wrapped rows on a spring (L72-82, L133). Tags are `white-space: nowrap` with no max-width or ellipsis (css L11), so a long email or URL overflows the field at 320px.

**Issues found in the code:**
- No validation: any trimmed string becomes a tag, so an invalid email or a non-E.164 number is accepted with no message.
- No limit and no bulk paste: a pasted list "a, b, c" becomes one tag containing commas, because only the `,` key splits (L114).
- Tag `key` is the tag text (L139); safe only because duplicates are refused case-insensitively, but `remove` filters by exact text (L108).
- Hard-coded English: placeholder and every announcement (L58, L100-108).
- Decorative motion: blur-in tags and placeholder (L137, L141-142), gliding pick ring (L84-97), scale pulse on duplicates (L105).
- `--accent`/`--accent-subtle` on the pick ring (css L23) need mapping to `--brand`/`--brand-soft`.

**Overlaps in Calevate:** none as a component. The interior verdict's candidates map to existing controls: bulk DNC entry is a textarea taking up to 2,000 numbers per add (`c/[slug]/do-not-call/NumberField.tsx` L92, `lib/api/dnc.ts` `MAX_NUMBERS_PER_ADD = 2000`), extraction enum choices are a one-per-line textarea (`agents/panels/extraction.tsx` L125-133, parsed by `parseEnumValues` in `extractionDraft.ts`), and team invites take one email at a time (`settings/team/InviteForm.tsx`). The DNC textarea wins (thousands of entries, per-row reasons); invites need no multi-value field.

**Where in Calevate:** `/c/[slug]/agents/[agentId]` extraction panel (enum choices, a handful of values) is the one real fit; not `/c/[slug]/do-not-call` and not `/c/[slug]/settings/team`.

**Verdict: ADAPT** — usable for short enum lists once it gains a `validate` returning a reason, paste splitting on commas and newlines, an IME guard, max-width with ellipsis on tags, 44px touch removal and translatable copy; it is not a bulk-entry control.

**Source:** `docs/design/uiarc/registry/tag-input/`

---

### mention-input
**What it does:** An auto-growing textarea with `@person` and `#channel` mentions: typing a trigger opens a positioned suggestion listbox, choosing inserts an atomic token (caret steps over it, one Backspace removes it), and the value is plain text plus a `mentions` array with offsets.

**Exports / API:** `MentionInput` (forwardRef to a `MentionInputHandle`; also default)

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `MentionValue` | — | `{ text, mentions }`, controlled |
| defaultValue | `MentionValue` | `{ text: "", mentions: [] }` | |
| onChange | `(value: MentionValue) => void` | — | |
| people | `MentionPerson[]` | — | omit to disable `@` |
| channels | `MentionChannel[]` | — | omit to disable `#` |
| onMentionAdd | `(mention: Mention) => void` | — | |
| onSubmit | `(value: MentionValue) => void` | — | with `submitOnEnter` |
| submitOnEnter | `boolean` | `false` | |
| placeholder | `string` | — | |
| minRows | `number` | `1` | |
| maxRows | `number` | `8` | then scrolls |
| placement | `"auto" \| "top" \| "bottom"` | `"auto"` | |
| maxSuggestions | `number` | `6` | |
| disabled | `boolean` | — | |
| name | `string` | — | on the textarea |
| id | `string` | — | |
| aria-label | `string` | — | there is no `label` prop |
| aria-describedby | `string` | — | |
| className | `string` | — | |

Other exports: `serializeMentions`, `mentionText`, types `MentionKind`, `MentionPerson`, `MentionChannel`, `Mention`, `MentionValue`, `MentionInputHandle` (`focus`, `insert`, `openSuggestions`, `clear`, `textarea`), `MentionInputProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Textarea `role="combobox"` with `aria-autocomplete="list"`, `aria-haspopup="listbox"`, `aria-expanded`, `aria-controls`, `aria-activedescendant` (L460-467); listbox and options with `aria-selected` (L489-495).
- Keys: ArrowUp/Down, Enter or Tab choose, Escape dismisses (with `stopPropagation`), atomic Backspace/Delete over tokens (L286-318). IME guard only on submit (L314), not on choosing with Enter (L295).
- Polite count announcement (L445, L476).
- Reduced motion: height snaps, panel fades only (L358, L401, L414, L444, L484); the module CSS has no `prefers-reduced-motion` block.
- No visible label support; callers must provide `aria-label` or an external `<label htmlFor={id}>`.
- Touch target: options are about 42px (28px avatar plus 7px padding each side, css L94-112); not set as a `min-height`.

**Mobile:** Popover is 272px wide with `max-width: 100%` and `z-index: 30` literal (css L81-83); `auto` placement flips above when less than 300px is below (L379). Textarea font is `--text-base` (css L30), so no iOS zoom.

**Issues found in the code:**
- Inserts through `document.execCommand("insertText")` (L261), a deprecated API kept only for undo-stack support; there is a direct-edit fallback (L263-274).
- Trigger search looks back only 48 characters (L127) and person queries allow one space (L136).
- Avatar is a raw `<img>` from a caller URL (L502-505).
- Hard-coded English: "person/people", "channel/channels", "No matches", "No people/channels match" (L445, L489, L515).
- `scrollbar-width: none` on the backdrop (css L59).

**Overlaps in Calevate:** none. There is no comment, note or mention feature in the consoles; the copilot panel (`components/copilot/CopilotPanel.tsx`) uses a plain textarea.

**Where in Calevate:** none today.

**Verdict: SKIP** — no Calevate surface mentions people or channels, and it would bring a deprecated `execCommand` path for a feature nobody has asked for.

**Source:** `docs/design/uiarc/registry/mention-input/`

---

### shortcut-recorder
**What it does:** A button that records a key chord ("mod+shift+k") with live key caps, conflict and browser-reserved warnings with "Use anyway", reset and clear; the file also ships `ShortcutKeys`/`ShortcutKbd` key-cap display, a platform-aware shortcut model, a `usePressedKeys` hook and a searchable `ShortcutList` cheatsheet.

**Exports / API:** `ShortcutRecorder` (also default)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | |
| hideLabel | `boolean` | `false` | |
| value | `string \| null` | — | controlled |
| defaultValue | `string \| null` | `null` | |
| onValueChange | `(value: string \| null, details: { replaced?: ShortcutBinding }) => void` | — | |
| resetValue | `string \| null` | `defaultValue` | |
| bindings | `ShortcutBinding[]` | `[]` | shortcuts already in use |
| warnReserved | `boolean` | `true` | ⌘W, ⌘C etc. (L224-228) |
| requireModifier | `boolean` | `true` | F-keys exempt |
| platform | `Platform` (`"mac" \| "other"`) | detected | |
| placeholder | `string` | `"Record shortcut"` | |
| description | `string` | — | |
| disabled | `boolean` | `false` | |
| id | `string` | — | |
| className | `string` | — | |

Other exports: `ShortcutKeys`, `ShortcutKbd`, `Kbd` (deprecated alias), `ShortcutList`, `usePressedKeys`, `usePlatform`, `keyId`, `normalizeShortcut`, `shortcutFromEvent`, `matchesShortcut`, `shortcutTokens`, `formatShortcut`, types `Platform`, `ShortcutToken`, `ShortcutKbdProps`, `KbdProps`, `ShortcutKeysProps`, `ShortcutBinding`, `ShortcutRecorderProps`, `ShortcutListItem`, `ShortcutListGroup`, `ShortcutListProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Recorder is a `<button aria-pressed>` labelled by the label plus its own spoken value (L364-368); while recording it swallows keys (`preventDefault` + `stopPropagation`, L317-320) except bare Tab; Escape cancels, Backspace clears (L322-323).
- `role="status"` announces recording, set, cleared and conflicts (L282, L289, L337, L419).
- `ShortcutKeys` is `role="img"` with a spoken label (L190).
- `usePressedKeys` adds window-level capture listeners (L146-149).
- Reduced motion: hydration-gated flag (L112-117); chips fade only (L237, L372); CSS block at css L81.
- Touch target: reset/clear actions 32×32px (css L34).

**Mobile:** Not meaningful on a phone: recording needs a hardware keyboard, and the platform guess defaults to "mac" on the server (L119, L125).

**Issues found in the code:**
- Hard-coded English throughout: placeholder, "Press keys", "Recording…", "Use anyway", "Cancel", "Reserved for", "Already used by", the reserved-shortcut labels and the key names (L77-82, L224-228, L289, L329, L337, L350-352, L379, L411-412).
- Platform detection reads `navigator.platform` (L120), a deprecated property, as a fallback.
- A breathing dot animates while recording (css L29).

**Overlaps in Calevate:** none for recording. For display, two inline `<kbd>` hints exist (`app/admin/AdminCommandPalette.tsx` L71, `components/interior/command-palette.tsx` L188); `ShortcutKeys` could replace them, but that alone does not justify the file.

**Where in Calevate:** none. Shortcuts are fixed (⌘/Ctrl+K in `AdminCommandPalette.tsx` L48) and not user-configurable; the client console's users are mostly on phones.

**Verdict: SKIP** — Calevate has no user-defined shortcuts and its clients rarely have a keyboard; the two existing `<kbd>` hints are not worth a 513-line module.

**Source:** `docs/design/uiarc/registry/shortcut-recorder/`

---

### combobox
**What it does:** A text input with `role="combobox"` that filters a popover listbox as you type (label plus optional `keywords`) and sets one value; a clear button resets it.

**Exports / API:** `Combobox` (forwardRef to the `<input>`)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | visible `<label>`; listbox is named `` `${label} options` `` (L258) |
| options | `ComboboxOption[]` (`{value, label, disabled?, keywords?}`) | required | `keywords` also match the query (L105) |
| value | `string` | — | controlled |
| defaultValue | `string` | `""` | uncontrolled |
| onValueChange | `(value: string) => void` | — | called with `""` on clear (L150) |
| description | `string` | — | hint under the field, wired via `aria-describedby` (L73, L211, L247) |
| placeholder | `string` | `"Search or select…"` | the chosen label replaces it while searching (L209) |
| emptyMessage | `string` | `"No matches found"` | `role="status"` row (L277) |
| className | `string` | — | applied to the inner `.control` row, not the root (L199) |
| ...inputProps | `Omit<InputHTMLAttributes<HTMLInputElement>, "value" \| "defaultValue" \| "onChange" \| "placeholder">` | — | `id`, `disabled`, `onFocus` are read; the rest spread on the input (L202) |

Other exports: types `ComboboxOption`, `ComboboxProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both already in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- APG-style editable combobox: `role="combobox"`, `aria-expanded`, `aria-controls` (only while open), `aria-autocomplete="list"`, `aria-activedescendant` (L206-215); options `role="option"` with `aria-selected`/`aria-disabled` (L267-269).
- Keys: ArrowDown/ArrowUp open, then move through enabled options with wrap (L165-178); Enter picks (L179-184); Escape closes and drops the query (L185-190). No Home/End handling.
- Focus and click both open the list (L216-220); picking returns focus to the input (L144); the clear button keeps focus via `onMouseDown` preventDefault (L234).
- Reduced motion: `useReducedMotion` swaps springs for instant/opacity-only (L77, L94, L236-239, L252-254); CSS `@media (prefers-reduced-motion)` removes transitions (css L28).
- Touch target: field `min-height: var(--control-height-md)` = 44px (css L3); options `min-height: 36px` (css L22); clear button 22x22px (css L14).

**Mobile:** Popover is absolutely positioned under the field, full field width, not portalled (css L18); list caps at `min(300px, 40vh)` with contained overscroll (css L20). Closes on any outside `pointerdown` (L127-136). Hover styles only under `(hover: hover) and (pointer: fine)` (css L4, L15).

**Issues found in the code:**
- Tab away while open does not close the list: there is no `onBlur`; only outside pointerdown (L127-136) and Escape (L185) close it, so the popover stays painted after keyboard focus leaves.
- Option ids are built from the raw value, `` `${controlId}-option-${option.value}` `` (L215, L263): a value containing a space yields an id that `aria-activedescendant` cannot reference.
- Touch targets under 44px: options 36px (css L22), clear 22px (css L14).
- `z-index: 80` on the popover (css L18) sits above Calevate's `--z-modal 60` and `--z-toast 70`.
- `40vh` (css L20); Calevate uses `dvh`.
- Decorative motion: the chosen label rises in with a blur (L95-96), the clear button scales in with blur (L236-238), the empty row fades in with blur (L277), the popover scales from 0.97 (L252).
- Hard-coded English: `"Search or select…"`, `"No matches found"` (L60-61), `"Clear selection"` (L233), `" options"` suffix (L258).
- No loading or error state for async option lists.
- Arc tokens (`--accent`, `--focus-ring`, `--surface-raised`, `--shadow-floating`, `--radius-panel`) need mapping to Calevate's.

**Overlaps in Calevate:** `apps/web/src/components/console/searchSelect.tsx` (`SearchSelect`, APG select-only combobox with list autocomplete). One caller: `app/admin/qa-sampling/QaQueueScreen.tsx`. SearchSelect already closes on blur (searchSelect.tsx L118), uses index-based option ids (L102, L150), has 44px touch rows and clear button (`touch:min-h-11`, `touch:h-11 touch:w-11`, L129, L160), sits at `z-dropdown` (L140), and supports a `null` "every option" row (`allLabel`) and per-option `hint`. Arc adds `keywords`, disabled options and a `description` line. SearchSelect wins; if `keywords` or disabled options are needed, add them to SearchSelect rather than adopt a second combobox.

**Where in Calevate:** `app/admin/qa-sampling` (the existing SearchSelect caller); any long single-pick list (tenant picker in `app/admin`, agent picker in `app/c/[slug]/calls`).

**Verdict: SKIP** — SearchSelect already covers this pattern and is closer to Calevate on blur handling, ids, touch size and z-index; Arc's version would need those fixes plus the blur motion removed just to reach parity.

**Source:** `docs/design/uiarc/registry/combobox/`

---

### multi-select
**What it does:** A button trigger that shows the first `maxVisible` selected labels as chips plus a rolling "+N" count, opening a `listbox` with `aria-multiselectable` whose options toggle on and off; a clear button empties it.

**Exports / API:** `MultiSelect`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | rendered as a `<span>`, joined into the trigger's `aria-labelledby` (L109-110) |
| options | `MultiSelectOption[]` (`{value, label, disabled?}`) | required | |
| value | `string[]` | — | controlled |
| defaultValue | `string[]` | `[]` | |
| onValueChange | `(value: string[]) => void` | — | |
| placeholder | `string` | `"Select options"` | |
| description | `string` | — | rendered under the control, NOT linked by `aria-describedby` (L137) |
| maxVisible | `number` | `2` | chips shown before "+N" |
| disabled | `boolean` | `false` | |
| className | `string` | — | on the root |

Other exports: types `MultiSelectOption`, `MultiSelectProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both already in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Trigger is a `<button>` with `aria-haspopup="listbox"`, `aria-expanded`, `aria-controls`, and `aria-labelledby` = label + an sr-only list of the selected labels (L110-111); chips are `aria-hidden` (L112).
- Menu `role="listbox"` `aria-multiselectable="true"` (L127); each option is a `<button role="option">` with `aria-selected`/`aria-disabled` (L131).
- Keys on the trigger: Enter/Space open or close; Enter while open toggles the highlighted option; ArrowDown/ArrowUp move with wrap; Escape closes (L94-105).
- Reduced motion: separate `slotFade`/`chipStill`/`fade` variants (L43-46, L114-125) and CSS transitions off (css L37).
- Touch target: trigger 44px (`--control-height-md`, css L5); options 38px (css L32); clear 22x22px (css L25).

**Mobile:** Menu absolutely positioned under the trigger, not portalled (css L30). Outside `pointerdown` closes (L81-85). Chips cap at `9rem` and ellipsize (css L18).

**Issues found in the code:**
- The highlighted option is never exposed to assistive tech: focus stays on the trigger button and there is no `aria-activedescendant` (L110), so arrow-key movement is silent to a screen reader.
- Options are focusable `<button>`s with default tabindex (L131): Tab from the trigger walks into every option instead of leaving the widget.
- No `max-height` or scroll on the menu (css L30): a long option list runs off the screen.
- Escape does not `preventDefault`/`stopPropagation` (L98); whether a surrounding `Drawer` or `ModalDialog` also reacts was not determined from the source.
- Touch targets under 44px: options 38px, clear 22px (css L25, L32).
- `z-index: 80` (css L30) is above Calevate's modal and toast layers.
- Decorative motion: chips grow from 0.9 with a blur (L38-42), the "+N" count rolls with blur (L48-52), the check draws itself (L55-58).
- Hard-coded English: `"Select options"` (L61), `"Clear selections"` (L121), the "+" prefix (L115).
- `description` is not associated with the control (L137).

**Overlaps in Calevate:** No multi-select dropdown exists (no `aria-multiselectable` anywhere in `apps/web/src`). Multi-pick is done with checkbox lists: `app/c/[slug]/leads/FacetPanel.tsx` (checkboxes with counts per value), `app/c/[slug]/leads/ColumnChooser.tsx` (checkboxes inside the shared portalled `Popover`, `<legend>`-labelled), and `FilterChip` rows. Those are native, keyboard-correct and already in use; they win.

**Where in Calevate:** Candidates would be `app/c/[slug]/leads` (MoreFilters) and `app/c/[slug]/campaigns` (LeadPicker), both of which already solve multi-pick another way.

**Verdict: SKIP** — the keyboard model is broken for screen-reader users (no active-descendant, options in the tab order) and the menu cannot scroll; Calevate's checkbox-in-Popover pattern already does the job natively.

**Source:** `docs/design/uiarc/registry/multi-select/`

---

### morph-select
**What it does:** A single-choice select whose pill-shaped trigger itself grows (width, height and corner radius on springs) into the option panel; groups, type-ahead, an auto search field above eight options, and the picked label "flies" from the list into the trigger.

**Exports / API:** `MorphSelect` (also default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | accessible name of trigger and list |
| hideLabel | `boolean` | `false` | sr-only label |
| items | `MorphSelectItem[]` (`MorphSelectOption \| MorphSelectGroup`) | required | option: `{value, label, icon?, meta?, keywords?, disabled?}`; group: `{label, options}` |
| value | `string \| null` | — | controlled |
| defaultValue | `string \| null` | `null` | |
| onValueChange | `(value: string, option: MorphSelectOption) => void` | — | |
| placeholder | `string` | `"Select"` | |
| searchable | `boolean \| "auto"` | `"auto"` | auto = more than 8 options (L139) |
| searchPlaceholder | `string` | — | falls back to selected label, then `"Search"` (L405) |
| panelWidth | `number` | `272` | px |
| maxListHeight | `number` | `296` | px |
| align | `"start" \| "end"` | `"start"` | |
| name | `string` | — | adds a hidden input (L458) |
| disabled | `boolean` | `false` | |
| className | `string` | — | |

Other exports: types `MorphSelectOption`, `MorphSelectGroup`, `MorphSelectItem`, `MorphSelectProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both already in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Trigger `<button role="combobox">` with `aria-haspopup="listbox"`, `aria-expanded`, `aria-controls`, `aria-activedescendant` (L384-385); with search on, the input becomes the combobox and the trigger is made `inert` with `tabIndex=-1` (L386, L403-404).
- Full listbox keyboard model: arrows, PageUp/PageDown (8), Home/End, Enter, Space, Alt+ArrowUp commits, Escape closes and refocuses the trigger, Tab closes without picking, printable type-ahead (L306-342). Focus leaving the root closes it (L351-354).
- Groups are `role="group"` labelled by their heading (L445-446); a polite live region announces search result counts (L363, L459).
- Reduced motion via `useReducedMotion` gated on hydration (L83-86) jumps sizes and swaps to fades (L170, L223-227, L391-392); CSS transitions zeroed (css L81-83).
- Touch target: trigger 44px (`--control-height-md`, css L2, L23); options 36px (css L69); search clear 24px (css L48); close hit 36px (css L50).

**Mobile:** Not portalled; the shape grows in place over content with `z-index: 30` when open (css L4). Panel width `min(panelWidth, 100vw - 2rem)` (css L57). Hover highlight follows only `pointerType === "mouse"` (L436).

**Issues found in the code:**
- A `<p>` empty-state element sits directly inside `role="listbox"` (L451), which only permits options and groups.
- `.shape { overflow: clip }` (css L10) contains the trigger at `inset: 0` (css L24), so a focus ring drawn outside the trigger's box is clipped.
- Decorative motion throughout, which REDESIGN-2 flags: the trigger morphs its width, height and radius (L158-183), the chosen label flies across with blur (L107-111, L267-276), the list face fades in with blur (L424-425), the highlight glides (L218-235).
- Touch targets under 44px: options 36px, clear 24px, close 36px (css L48, L50, L69).
- Hard-coded English: `"Select"` (L121), `"Search"` (L405), `` `Search ${label}` `` (L403), `"Clear search"` (L408), `` `Close ${label}` `` (L414), `"option"/"options"/"No matches"` with English pluralisation (L363), `"No matches for"` (L451).
- `toLowerCase()` rather than locale-aware lowering for search and type-ahead (L103, L289).
- Hard-coded radii outside tokens: `OPEN_RADIUS = 22` (L79), `border-radius: 16px` (css L63, L69).
- Not portalled: inside a `Card`, `Drawer` or `ScrollRegion` with overflow hidden the open panel is clipped.
- No loading/error state. About 27 KB of TSX for one select.

**Overlaps in Calevate:** Native `<select>` (127 occurrences under `apps/web/src/app` and `components`, e.g. `app/c/[slug]/leads/StatusSelect.tsx`, `AssigneeSelect.tsx`) and `components/console/searchSelect.tsx` for long lists. The native select wins on a phone (OS picker, no clipping, no JS) and SearchSelect wins for searchable lists; replacing 127 native selects would buy only motion.

**Where in Calevate:** Any `<select>` in `app/c/[slug]/*` and `app/admin/*`; no screen needs what it adds.

**Verdict: SKIP** — its reason to exist is the morph and the flying label, which is the decorative motion Calevate's calm aesthetic rules out; it also has listbox-content and clipping defects.

**Source:** `docs/design/uiarc/registry/morph-select/`

---

### chip-group
**What it does:** A wrapping row of toggle chips (multi or single choice) where selecting grows a check into the chip on springs, neighbours glide, and long sets fold behind a "+N more" / "Show less" chip with a height morph.

**Exports / API:** `ChipGroup` (also default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| options | `ChipOption[]` (`{value, label}`) | required | |
| value | `string[]` | required | controlled only |
| onValueChange | `(value: string[]) => void` | required | |
| label | `string` | required | `aria-label` of the group |
| multiple | `boolean` | `true` | single mode can still clear the chosen chip (L223) |
| maxVisible | `number` | `Infinity` | selected chips stay visible when folded (L211-214) |
| className | `string` | — | |

Other exports: type `ChipOption`, `ChipGroupProps`.

**Dependencies:** npm: `motion` (already in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- `role="group"` with `aria-label` (L245); each chip a `<button aria-pressed>` (L172); the overflow chip has `aria-expanded` (L193).
- Roving tabindex: one tab stop (last focused, else first selected, else first) (L218-219); ArrowLeft/Right/Up/Down with wrap, Home, End move focus (L232-241).
- Exiting chips are `aria-hidden` and `tabIndex=-1` while they animate out (L172); swapping text is hidden from AT while it fades (L126-132).
- Reduced motion: `useReducedMotion` jumps width lag and height (L56, L86, L110), fades only (L171, L174); CSS transitions and press scale off (css L35-38).
- Touch target: chip body height `var(--control-height-sm)` = 36px (css L9).

**Mobile:** Wraps with `flex-wrap` (css L4); labels ellipsize at chip `max-width: 100%` (css L7, L17). Hover only under fine pointers (css L22).

**Issues found in the code:**
- Chip height 36px (css L9), below Calevate's 44px touch target.
- Hard-coded English: `"Show less"` and `` `+${hidden} more` `` (L188).
- The overflow chip has `aria-expanded` but no `aria-controls` (L193).
- Single mode (`multiple={false}`) still uses `aria-pressed` buttons (L172), so a one-of-N choice is not announced as one.
- No disabled chip, no per-chip count slot (FacetPanel's "(12)" counts have nowhere to go), no loading state.
- Decorative motion: width-lag springs, check that grows, blurs and draws itself (L145-181), staggered reveal (L248), height morph (L73-122).
- `.check` colour is `--accent-strong` and the selected tint is `--accent` mixes (css L13, L20); needs mapping to `--brand`.

**Overlaps in Calevate:** `apps/web/src/components/ui.tsx` `FilterChip` (L1369): `aria-pressed` button, `touch:min-h-11`, Calevate focus ring. 22 JSX call sites in 14 files (e.g. `app/c/[slug]/calls/CallsScreen.tsx` 4, `app/admin/page.tsx` 4, `app/c/[slug]/campaigns/ContactResults.tsx` 2, `LeadPicker.tsx` 2, `leads/MoreFilters.tsx`, `billing/WalletLedgerPanel.tsx`). FilterChip wins. ChipGroup's roving tabindex and fold-with-pinned-selection are the two ideas worth porting into a thin wrapper around FilterChip if a long chip row ever needs them.

**Where in Calevate:** `app/c/[slug]/calls` (outcome filters), `app/c/[slug]/leads` (MoreFilters), `app/c/[slug]/campaigns`, `app/c/[slug]/billing` (ledger filter), `app/admin`.

**Verdict: SKIP** — FilterChip already serves 22 call sites at the right touch size; ChipGroup adds a 36px chip and decorative morphing that would have to be removed.

**Source:** `docs/design/uiarc/registry/chip-group/`

---

### billing-toggle
**What it does:** A pill radiogroup (default "Monthly" / "Yearly" with a "Save 20%" badge) whose thumb glides to the chosen option; a companion `BillingPrice` rolls a price to a new amount via `AnimatedCounter` and shows a struck-through previous price.

**Exports / API:** `BillingToggle` (also default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `string` | required | controlled only |
| onValueChange | `(value: string) => void` | required | |
| options | `BillingToggleOption[]` (`{value, label, badge?, activeBadge?}`) | `DEFAULT_OPTIONS` (Monthly/Yearly, "Save 20%") (L33-36) | badge text is a literal string the caller supplies |
| label | `string` | `"Billing period"` | radiogroup name |
| size | `"md" \| "lg"` | `"md"` | |
| className | `string` | — | |

Other exports: `BillingPrice` (`amount: number`, `currency?: string` default `"$"`, `period?: string`, `was?: number`, `decimals?: number` default `0`, `className?: string`, L141-150), types `BillingToggleOption`, `BillingToggleProps`, `BillingPriceProps`.

**Dependencies:** npm: `motion` (already in apps/web). Registry: `arc-motion-tokens`, `animated-counter` (present at `registry/animated-counter/`).

**Accessibility:**
- `role="radiogroup"` with `aria-label`; options are `<button role="radio" aria-checked>` with roving `tabIndex` (L98, L113-119).
- Arrow keys select and focus with wrap; Home/End select first/last (L88-95). Selection follows focus.
- Thumb and sizer copies are `aria-hidden` (L52, L102, L125).
- Reduced motion: `useReducedMotion` jumps the thumb and swaps badge text with a plain fade (L67, L105, L130, L156, L178-196); CSS transitions off (css L105-107).
- Touch target: option height `--_h` 34px (md) or 42px (lg) (css L4, L20, L43).

**Mobile:** `inline-flex` with `max-width: 100%` and `white-space: nowrap` options (css L8-9, L52): long translated labels overflow rather than wrap. `BillingPrice` wraps its parts (css L111).

**Issues found in the code (prices and money):**
- `BillingPrice.amount` and `was` are `number` (L142, L147); hard rule 7 requires INR decimal strings. `was.toFixed(decimals)` (L183) formats a binary float.
- Currency is a `"$"` default string prefix (L155), not INR formatting; `AnimatedCounter` defaults to `locale = "en-US"` (`animated-counter.tsx` L67) and `BillingPrice` does not pass a locale (L170), so 100000 renders as `100,000`, not Indian grouping `1,00,000` as `formatINR` produces (`ui.tsx` L1475-1486).
- The component does no discount maths: "Save 20%" and any `activeBadge` such as "You save $48" are caller-typed strings (L12-15, L35). A caller would have to compute the saving; nothing ties the badge to the prices.
- Touch target 34px at `md` (css L4).
- Hard-coded English defaults: `"Monthly"`, `"Yearly"`, `"Save 20%"` (L34-35), `"Billing period"` (L66).
- Decorative motion: badge and period text swap with vertical travel and blur (L38-42), digit columns roll (animated-counter).
- `:root[data-theme="dark"]` rules (css L34-37, L95-98) are unused in light-only Calevate.

**Does Calevate's billing have a period to toggle?** No, from the code:
- `app/c/[slug]/billing/WalletHero.tsx`: a prepaid wallet; the hero is balance plus runway in days (module comment L18-31).
- `app/c/[slug]/billing/TopUp.tsx`: credit is bought as packs from `useCreditPacks` or a free-form amount (L22-38, L88, L199-205); `lib/api/billing.ts` `TopUpRequest` sends `{packId}` or `{amountInr: string}` (L84-95); `CreditPackOut` carries every rupee figure as a string (`schema.d.ts` L16638-16662).
- `app/c/[slug]/billing/PlatformFeeCard.tsx`: one optional monthly platform fee, `formatINR(amount)` "a month", paid separately (L35-43, L109-118). There is no annual option.
- `app/pricing/page.tsx`: "one pricing model for every client (D-707)": prepaid credit at a six-rung pack card plus an optional monthly fee, "no negotiated plan" (L46-58), "there is no separate plan to negotiate" (L290-291).
- `grep -i "yearly|annual|billing period"` over `apps/web/src` finds no billing use (only sitemap `changeFrequency` and legal text).
The two-way switch that does exist on pricing is the voice switch in `components/marketing/rateCard.tsx` (two native radios, Clear vs Studio, L42-53, L115-122), and the billing screen's own tab/period switches use the interior `SegmentedControl` (`BillingScreen.tsx` L7, `SpendChart.tsx` L9).

**Overlaps in Calevate:** `components/interior/segmented-control.tsx` (20 importing files, including `billing/BillingScreen.tsx` and `billing/SpendChart.tsx`) and the rateCard voice radios. Both win.

**Where in Calevate:** Founder's note: "billing page" (`app/c/[slug]/billing`). The billing page has no monthly/annual period and no plans, so there is nothing for it to toggle.

**Verdict: SKIP** — Calevate sells prepaid credit packs with a single optional monthly fee, so a monthly/yearly toggle has no state to represent; its price companion also takes float numbers and formats with `$` and en-US grouping, against hard rule 7.

**Source:** `docs/design/uiarc/registry/billing-toggle/`

---

### plan-comparison
**What it does:** A self-contained pricing block: a Team vs Studio feature matrix with a Monthly/Yearly segmented control that counts the per-seat price, a "Show differences only" switch that collapses shared rows, and Select buttons with a sliding selected rail.

**Exports / API:** `PlanComparison` (also default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| (none) | — | — | takes no props; plans, prices and features are module constants (L12-30) |

Other exports: none.

**Dependencies:** npm: `lucide-react`, `motion` (both already in apps/web); transitively **`@radix-ui/react-switch` (new)** through the `switch` registry dependency (`registry/switch/switch.tsx` L5, `switch/registry-item.json`). Registry: `arc-motion-tokens`, `button` (`registry/button/button.tsx`, `button.module.css`), `segmented-control` (`registry/segmented-control/segmented-control.tsx`, `segmented-control.module.css`), `switch` (`registry/switch/switch.tsx`, `switch.module.css`). Imported as `../../button/button`, `../../segmented-control/segmented-control`, `../../switch/switch`, `../../lib/motion-tokens` (L6-9), i.e. the block expects to sit one folder deeper than components (`blocks/plan-comparison/`).

**Accessibility:**
- ARIA table built from divs: `role="table"`, `row`, `columnheader`, `rowgroup`, `rowheader`, `cell` (L89-108); hidden per-cell plan names for the stacked layout (L107-108, css L44).
- Prices are `aria-live="polite" aria-atomic="true"` (L95); the chosen plan is announced in a `role="status"` footer (L115).
- Select buttons use `aria-pressed` (L96). The billing control is Arc `SegmentedControl` (`aria-pressed` buttons in a `role="group"`, roving tabindex, `segmented-control.tsx` L65-67).
- Reduced motion: `useReducedMotion` skips the number tween (L43-46, L58), height animation (L105) and rail spring (L97); CSS transitions off (css L83-85).
- Touch target: feature rows 44px (css L37); the Select button size comes from Arc `Button`.

**Mobile:** Layout keys off the block's measured width via ResizeObserver: `xs` ≤340, `sm` ≤540, `md` ≤720 (L69-77); at `sm` the feature name spans above its two values (css L64-76). Server render starts at `"lg"` (L68) until the client measures.

**Issues found in the code (prices and money):**
- Prices are `number` constants in dollars (`pricing: Record<Plan, Record<Billing, number>>`, L27-30) with a literal `"$"` and `"per seat / month"` (L95) and footer "Prices in USD per seat" (L115); hard rule 7 needs INR decimal strings.
- No discount maths: the yearly price is a separate hand-typed number and "save up to 23%" is a literal string (L84), not derived from the prices.
- `AnimatedNumber` rounds every frame with `Math.round` (L51), so a non-integer price such as 4.50 ends on 5 when motion is on but shows 4.5 under reduced motion (L58); the two modes disagree.
- The polite live region on the price (L95) is updated on every animation frame through `setDisplayValue` (L51).
- Hard-coded copy and data: headings, feature labels, plan names, "Selected", "Select Team" (L16-25, L83-96, L115). Not reusable without rewriting the file.
- `docs.md` does not match the code: it describes a "light blur" on rows (no blur in L105) and 640px/365px breakpoints (code uses 540/340, L72).
- The selection state (`selected`, L66) goes nowhere: no callback or prop.

**Does Calevate have plans to compare?** No. `app/pricing/page.tsx` says "one pricing model for every client (D-707)", prepaid packs plus an optional monthly platform fee, "no negotiated plan" (L46-58, L290-291). The client billing screen (`BillingScreen`, `WalletHero`, `TopUp`, `PlatformFeeCard`, `WhatCallsCost`) shows a wallet, packs and per-voice rates, not tiers. The nearest comparison Calevate shows is packs × two voices, already rendered by `components/marketing/rateCard.tsx` from server strings.

**Overlaps in Calevate:** `components/marketing/rateCard.tsx` (pack columns, voice switch, every ₹ figure from `GET /v1/public/rate-card`) on `/pricing`; `TopUp` `PackChooser` on the billing screen. Those win.

**Where in Calevate:** Founder's note: "billing page" (`app/c/[slug]/billing`). Calevate has no plans or seats for it to compare, so there is no place for it there.

**Verdict: SKIP** — a sample-data block for per-seat monthly/yearly plans, priced in dollar floats, that pulls in a new Radix dependency through `switch`; Calevate's prepaid pack model has nothing for it to show.

**Source:** `docs/design/uiarc/registry/plan-comparison/`

---

### comparison-table
**What it does:** An "us versus them" feature table with a highlighted own column, sticky header, section bands, check/partial/minus marks, an "Only differences" switch, a competitor picker that stacks to two columns below `stackBelow`, and an optional CTA in the own column.

**Exports / API:** `ComparisonTable`; the default export is `ComparisonTableBlock` (a preview wrapper, L205-209).

| Prop | Type | Default | Notes |
|---|---|---|---|
| title | `string` | `"How Relay compares"` | |
| description | `string` | sample sentence (L75) | |
| columns | `ComparisonColumn[]` (`{id, name, caption?, highlight?}`) | `comparisonColumns` (sample) | `highlight` marks the own column |
| sections | `ComparisonSection[]` (`{id, title, rows}`; row `{id, feature, hint?, values}`) | `comparisonSections` (sample) | |
| differencesOnly | `boolean` | — | controlled |
| defaultDifferencesOnly | `boolean` | `false` | |
| onDifferencesOnlyChange | `(value: boolean) => void` | — | |
| compareWith | `string` | — | controlled competitor in stacked view |
| onCompareWithChange | `(id: string) => void` | — | |
| cta | `{ label: string; href?: string; onClick?: () => void; doneLabel?: string }` | — | |
| stickyTop | `number` | `0` | |
| maxHeight | `number \| string` | — | caps height, makes the scroller a focusable `region` (L147) |
| stackBelow | `number` | `640` | |
| className | `string` | — | |

Other exports: `ComparisonTableBlock`, types `ComparisonColumn`, `ComparisonRow`, `ComparisonSection`, `ComparisonValue` (re-exported from `comparison-table-data.ts`), plus sample data `comparisonColumns`, `comparisonSections` in that file.

**Dependencies:** npm: `lucide-react`, `motion` (both already in apps/web). Registry: `arc-motion-tokens` only; `meta.builtFrom` names Switch and Button but the code uses neither (it draws its own switch, L131-135).

**Accessibility:**
- ARIA grid of divs: `table`, `rowgroup`, `row`, `columnheader`, `rowheader`, `cell` (L112-196); marks carry sr-only "Included"/"Partial"/"Not included" (L63, L67, L70).
- "Only differences" is a native checkbox with `role="switch"` wrapped in a label (L131-135); a polite live line states which rows show (L199).
- Competitor picker is `aria-pressed` buttons in a labelled group (L138-145).
- `maxHeight` makes the scroller `tabIndex=0`, `role="region"`, labelled by the title (L147).
- Reduced motion: `useReducedMotion` swaps to opacity fades and zero durations (L89, L116, L154-167, L187-189); only the thumb transition is removed in CSS (css L90-92).
- Touch target: picker buttons 36px (css L21); CTA `--control-height-sm` 36px (css L73).

**Mobile:** Container query `compare` tightens the grid at 820/640px (css L79-88); below `stackBelow` it shows own + one competitor with a horizontally scrolling picker (L107, css L19-20).

**Issues found in the code:**
- The "Only differences" checkbox is `opacity: 0` over the label (css L11) and no rule draws focus on the visible track, so keyboard focus is invisible.
- Notes are only rendered for `"partial"` (L65-69); a `note` on `true`, `false` or a string value is dropped silently.
- With both `href` and `onClick` in `cta`, the button branch renders and `href` is ignored (L185).
- Default export is the preview with `maxHeight="min(760px, 82vh)"` (L206); `vh`, not `dvh`.
- Touch targets 36px (css L21, L73).
- Decorative motion: sticky header `backdrop-filter: blur(14px)` (css L27), checks draw on scroll into view (L61), cells scale from 0.8 (L167), CTA label swaps with blur (L189).
- Hard-coded English: "Feature", "Only differences", "Compare … with", "Included", "Partial", "Not included", "Showing only rows that differ"/"Showing all rows", sample title (L63-74, L113, L132, L138, L180-182, L199).
- Sample data names competitors and prices in dollars (`comparison-table-data.ts` L25-30).

**Overlaps in Calevate:** `components/console/dataTable.tsx` (real `<table>`) for data; `components/marketing/rateCard.tsx` for the one comparison Calevate publishes (packs × voices). No us-vs-them surface exists.

**Where in Calevate:** At most a marketing page (`app/pricing`, `app/roi`), e.g. Clear vs Studio voices; naming competitors would also need a decision, since client-facing text names no vendor (D-679).

**Verdict: SKIP** — no Calevate screen needs a competitor matrix, and its focus, note and touch-size defects would all need fixing for a page that does not exist; revisit as ADAPT only if marketing asks for a comparison page.

**Source:** `docs/design/uiarc/registry/comparison-table/`

---

### radio-group
**What it does:** A fieldset of native radio inputs drawn as bordered rows with an optional description; one highlight box glides to the chosen row while the dot springs in.

**Exports / API:** `RadioGroup`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | `<legend>` |
| options | `{ value: string; label: string; description?: string }[]` | required | |
| value | `string` | required | controlled only |
| onValueChange | `(value: string) => void` | required | |
| name | `string` | `useId()` | |

Other exports: none.

**Dependencies:** npm: `motion` (already in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Native `<fieldset>`/`<legend>` and `<input type="radio">` wrapped in `<label>` (L44-50): one tab stop and arrow keys come from the browser.
- Highlight and dot are `aria-hidden` (L45, L48).
- Reduced motion: `useReducedMotion` places the highlight instantly and the dot without a spring (L25, L33, L48); CSS transitions off (css L30).
- Touch target: no `min-height`; row height is `padding: var(--space-3)` plus text (css L8).
- No hard-coded user-facing strings.

**Mobile:** Rows stack in a grid (css L4); hover only under fine pointers (css L9); no-JS/server paint styles the checked row directly (css L12).

**Issues found in the code:**
- No visible keyboard focus: the radio input is `position: absolute; opacity: 0` (css L13) and nothing styles the row on `:focus-visible`, so the outline the browser draws on the input is invisible (the WCAG 2.4.7 / F78 failure `ChoiceCard` documents and fixes).
- No `disabled` for the group or per option.
- The ResizeObserver effect depends only on `options.length` (L37-43); swapping options of the same length keeps observing old row nodes.
- Highlight glide on the morph spring (L16) is mild state-explaining motion, acceptable once tokens are mapped; colours use `--control-on` (css L5, L24).

**Overlaps in Calevate:** `components/console/choiceCards.tsx` (`ChoiceCard`/`ChoiceCards`): native radio or checkbox, `sr-only` input with `has-[:focus-visible]:ring-2` on the label, disabled, `icon`, `description` via `aria-describedby`. Used in 7 files (`app/c/[slug]/campaigns/ConsentProvenance.tsx`, `do-not-call/RestoreDialog.tsx`, `integrations/AddDestinationDrawer.tsx`, `lead-sources/AddSourceDrawer.tsx`, `components/forwarding/ModeChoice.tsx`, `components/engineCatalogueList.tsx`, `app/admin/ops/config/ConfigInput.tsx`). `components/console/chooser.tsx` (`Chooser`/`ChooserItem`, 4 files) is a navigation list of jobs, not a value choice, so it does not overlap. ChoiceCards wins; the short-option case is covered by the interior `SegmentedControl`, as its module comment says.

**Where in Calevate:** The ChoiceCards screens above (consent source, DNC restore reason, forwarding mode, destination/source pickers).

**Verdict: SKIP** — ChoiceCards is the same native pattern with visible keyboard focus, disabled state and description wiring; Arc's version lacks all three.

**Source:** `docs/design/uiarc/registry/radio-group/`

---

### switch
**What it does:** A Radix Switch root (a `<button role="switch">`) with a 42x24 track whose thumb stretches while pressed and slides on a spring; the optional `label` renders inside the button.

**Exports / API:** `Switch` (forwardRef, also default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | — | rendered inside the button and also set as `aria-label` unless one is passed (L143, L149) |
| ...props | `ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>` | — | Radix props: `checked`, `defaultChecked`, `onCheckedChange`, `disabled`, `name`, etc.; pointer/key/blur handlers are chained (L106, L135-141) |

Other exports: type `SwitchProps`.

**Dependencies:** npm: **`@radix-ui/react-switch` (new)**, `motion`. Registry: `arc-motion-tokens`. The Radix package is a new supply-chain dependency (root CLAUDE.md hard rule 9) needing the founder's approval.

**Accessibility:**
- Radix renders `role="switch"` with `aria-checked`; Space/Enter toggle (button behaviour).
- `aria-label` duplicates the visible label text (L143); no slot for a hint or description.
- Reduced motion: no stretch, no spring (L122, L126, L147); CSS transitions off (css L12).
- Touch target: `min-height: var(--control-height-md)` = 44px on the whole button including label (css L1).

**Mobile:** Inline-flex button; hover only under fine pointers (css L9); `-webkit-tap-highlight-color: transparent` (css L1).

**Issues found in the code:**
- `.switch:focus-visible { outline: none; }` (css L10). In Arc the global `foundation.css` `:focus-visible` rule wins with `!important` (foundation.css L189-191); Calevate does not ship that rule, so taken as-is the switch shows no keyboard focus.
- The label is a child of the `<button>` (L149), so a sentence-long label, a hint line or a warning under it (what `ToggleSwitch`'s `hint` and `children` carry) cannot be expressed.
- Decorative motion: thumb stretch on press and a 1.16 scale pulse on change (L114-125, L147).
- Hard-coded geometry kept in sync by comment between TS and CSS (`size`, `travel` L97-99 vs css L4, L7).
- Colours via `--control-track/-on/-thumb` tokens (css L4-8) need mapping to `--brand`/`--line`.

**Overlaps in Calevate:** `apps/web/src/components/ui.tsx` `ToggleSwitch` (L175-219): native `<input type="checkbox" role="switch">` in a `<label>`, `label` + `hint` + `children`, a disabled guard in the handler (L202-208), brand focus ring via `peer-focus-visible:ring-2` (`SWITCH_TRACK`, L226-227), no dependency. 27 JSX call sites in 24 files (e.g. `app/c/[slug]/agents/[agentId]/script/ScriptSections.tsx` 3, `app/admin/ops/voices/hosted/VoiceDrawer.tsx` 2, `billing/AutoRechargePanel.tsx`, `do-not-call/ConsentPosture.tsx`, `settings/phone-numbers/PhoneNumbersScreen.tsx`, `components/authn/staySignedInRow.tsx`). ToggleSwitch wins; replacing it would move 27 sites onto a new npm dependency and lose `hint`/`children`.

**Where in Calevate:** The 24 ToggleSwitch files (agent actions and panels, script sections, auto-recharge, DNC consent posture, knowledge permissions, lead sources, phone numbers, admin hosted voices).

**Verdict: SKIP** — it needs a new Radix dependency to do what the native `ToggleSwitch` already does at 27 call sites, with less room for the hint text Calevate's settings rely on and no keyboard focus ring outside Arc's foundation CSS.

**Source:** `docs/design/uiarc/registry/switch/`

---

### slider
**What it does:** A single-value or two-thumb range slider drawn with `role="slider"` divs. The thumb follows the pointer 1:1, stretches like rubber past its limits, settles on the step grid with release momentum, and shows a value bubble with rolling odometer digits while it is dragged or focused from the keyboard.

**Exports / API:** `Slider` (generic `Slider<T extends SliderValue = number>`)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | Visible label in a `<span>`; it names a single thumb through `aria-labelledby` |
| value | `T` (`number \| [number, number]`) | — | Controlled. A pair makes it a range slider (L159) |
| defaultValue | `T` | — | Uncontrolled. With neither prop set the value is `[min]`, or `[min, max]` for a range (L160) |
| onValueChange | `(value: T) => void` | — | Fires on every step during a drag |
| onValueCommit | `(value: T) => void` | — | Fires on release, on a key press, or on a clicked mark |
| min | `number` | `0` | |
| max | `number` | `100` | |
| step | `number` | `1` | Values of 0 or less fall back to 1 (L157) |
| largeStep | `number` | a tenth of the range | Used by PageUp, PageDown and Shift+arrow |
| marks | `(number \| SliderMark)[]` | — | Ticks. A labelled mark prints under the track and can be clicked |
| minStepsBetweenThumbs | `number` | `0` | Range mode only |
| format | `(value: number) => string` | `toLocaleString("en-US")` (L164) | Formats the readout, the bubble AND `aria-valuetext`: one function for all three |
| showValue | `boolean` | `true` | Readout beside the label (`aria-hidden`) |
| thumbLabels | `[string, string]` | `` `${label}, minimum` `` / `` `${label}, maximum` `` (L373) | Range thumb names |
| start / end | `ReactNode` | — | Adornments either side of the track |
| name | `string` | — | One hidden `<input>` per thumb (L401) |
| disabled | `boolean` | — | `aria-disabled`, `tabIndex -1`, 50% opacity |
| className | `string` | — | |

Other exports: types `SliderValue`, `SliderMark`, `SliderProps`; `default` export.

**Dependencies:** npm: `motion` (already in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- Each thumb is `role="slider"` with `aria-valuemin`, `aria-valuemax`, `aria-valuenow`, `aria-valuetext`, `aria-orientation` and `aria-disabled` (L138-139). A single thumb is named by the label `<span>`; range thumbs get `aria-label` (L392).
- Keys (L333-356): arrows, Shift+arrow (large step), PageUp/PageDown, Home/End. A key at a limit plays a small "bump" spring instead of doing nothing (L349-352).
- Focus: focusing from the pointer sets `data-quiet` (L222-229), but no CSS rule reads `data-quiet`. The ring therefore depends on the browser's `:focus-visible` heuristic and Arc's global outline rule in foundation.css. The module CSS has no focus style of its own.
- Hit area: the thumb is 22px (css L2) with a `::after` at `inset: -11px`, so the hit area is 44px (css L23). The control row is `--control-height-md` (44px, css L12).
- Reduced motion: `useReducedMotion` jumps the thumbs, removes the rubber band (L265), and swaps the digit roll for a fade (L87, L109). CSS turns off transitions (css L45).
- Mark labels are `aria-hidden` and clickable `<span>`s (L397-398). That is acceptable because the keyboard reaches every value.
- There is no `aria-describedby` prop. The scale words under Calevate's sliders (`${id}-scale`) cannot be attached.
- Forced colours: the thumb, track and fill are background colours (css L13, L15, L22), with no `@media (forced-colors)` rule. Not tested; a native `<input type="range">` keeps a system rendering there.

**Mobile:** `touch-action: pan-y` on the control (css L12), so a vertical swipe still scrolls the page. The bubble sits higher on `pointer: coarse` so the fingertip does not hide it (css L28). It fills its column (`width: 100%`).

**Issues found in the code:**
- `format` drives both the visible text and `aria-valuetext` (L30, L139). `voiceTuning.tsx` shows `multiplierLabel(value)` but speaks "Normal" / "1.20 times normal" (voiceTuning.tsx ~L164). Arc cannot express that split.
- The default formatter is hard-coded to `"en-US"` (L164).
- English is hard-coded in the default range names ", minimum" / ", maximum" (L373).
- The header has no slot beside the readout. `voiceTuning.tsx` puts a Reset button there; Arc only offers `start`/`end` beside the track (L384, L396).
- There is no `id` prop, and the label is a `<span>` with a generated id (L156, L377). A caller cannot point a `<label htmlFor>` at it or wire its own description.
- Decorative motion: the rolling odometer digits with a blur filter (L81-85, L95), and the bubble's blur and scale entrance (L126-129). Moving a value does not need digits that spin. Under the Stripe/Notion brief this is decoration.
- `data-quiet` is set but unused in CSS (L138).
- Colours come only from Arc tokens (`--control-track`, `--control-fill`, `--control-thumb`, `--foreground`). They need mapping to `--line` and `--brand-strong`; no literals besides `#000` in the mask (css L41).
- No loading or error state; none is expected for a slider.

**Overlaps in Calevate:** `RANGE_INPUT` in `apps/web/src/components/ui.tsx` (L1021), a styled native `<input type="range">` with a 16px thumb (24px on touch) and a `focus-visible` ring. It has 3 callers: `app/c/[slug]/agents/panels/voiceTuning.tsx` (L167), `components/callHandlingRows.tsx` (L129), and `components/marketing/roiCalculator.tsx` (L182). Every caller pairs it with a `<label htmlFor>`, `aria-describedby` scale words and its own `aria-valuetext`. One way per problem: Arc may replace `RANGE_INPUT` only if it gains `id`, `aria-describedby`, a separate value-text function and a header action slot. All 3 callers must move in the same change, which is a small move. Otherwise the native input wins: it is simpler, correct in forced colours, and already right on touch.

**Where in Calevate:** `app/c/[slug]/agents/[agentId]` voice tuning (speed, loudness, emotion), the call-handling rows (pause length, `components/callHandlingRows.tsx`, used by `app/c/[slug]/agents/panels/callHandling.tsx` and the admin `tenants/[tenantId]/agents/[agentId]/prompt/sections/callHandling.tsx`), and marketing `app/roi`.

**Verdict: ADAPT.** The interaction model and keyboard support are sound, and the 44px hit area beats `RANGE_INPUT`. It must first gain `id`, `aria-describedby`, a value-text function separate from `format`, a header action slot and an `en-IN`/Intl default. The rolling-digit blur should go. Adopt it only as the single replacement for `RANGE_INPUT`, with all 3 callers moved.

**Source:** `docs/design/uiarc/registry/slider/`

---

### elastic-slider
**What it does:** A single-value slider styled as a rubber band. The track stretches and thins past either end and springs back with a bounce, the thumb swells under the finger, and the value tag trails the thumb and swings with its speed. Marks act as detents, with a tick "pop" and a phone vibration.

**Exports / API:** `ElasticSlider`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | Visible `<span>`; names the thumb via `aria-labelledby` |
| value | `number` | — | Controlled |
| defaultValue | `number` | `min` | |
| onValueChange | `(value: number) => void` | — | |
| onValueCommit | `(value: number) => void` | — | |
| min / max | `number` | `0` / `100` | |
| step | `number` | `1` | |
| largeStep | `number` | a tenth of the range | |
| marks | `(number \| ElasticSliderMark)[]` | — | Detents within 7px (L49) |
| format | `(value: number) => string` | `toLocaleString("en-US")` (L73) | Also the `aria-valuetext` |
| showValue | `boolean` | `true` | Readout fades out while the tag shows (css L7) |
| startIcon / endIcon | `ReactNode` | — | Pushed outward by the stretch |
| name | `string` | — | Hidden input |
| disabled | `boolean` | — | |
| className | `string` | — | |

Other exports: types `ElasticSliderMark`, `ElasticSliderProps`; `default` export.

**Dependencies:** npm: `motion` (already in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- `role="slider"` with value attributes and `aria-labelledby` (L280). Keys are the same set as `slider` (L230-252).
- **The thumb sets `outline: none` (css L24) and the module has no replacement focus style.** In Arc this is rescued by the global `!important` `:focus-visible` rule in `arc-foundation/foundation.css`. Calevate does not ship that rule; it uses per-element `focus-visible:ring-2`. Dropped into Calevate as is, the thumb has no visible keyboard focus (WCAG 2.4.7).
- Hit area: a 24px thumb with `::after inset: -12px`, so 48px (css L2, L26).
- Reduced motion: the stretch, sway and tick pop are off (L111, L143, L163, L217); CSS transitions are off (css L40).

**Mobile:** `touch-action: pan-y` (css L13). The tag floats higher on coarse pointers (css L30). Touch drags into a detent call `navigator.vibrate(6)` (L144).

**Issues found in the code:**
- Missing focus indicator outside Arc's foundation (css L24), as above.
- Decorative motion throughout: the bounce `snapBack` with bounce .42 (L47), the track `scaleX`/`scaleY` stretch (L101-103), the tag swing `rotate` from velocity (L111), and the tick pop to 2.1x scale (L143). None of this explains state; it is personality motion, outside a calm product's brief.
- Haptic vibration on detents (L144): an unrequested side effect.
- `"en-US"` default formatting (L73).
- No range mode, no `id` or `aria-describedby`, and no separate value text. These are the same gaps as `slider`.

**Overlaps in Calevate:** `RANGE_INPUT` (`components/ui.tsx` L1021, 3 callers) and the Arc `slider` above. It is a second slider beside both. One way per problem means at most one slider ships, and `slider` is the stronger candidate.

**Where in Calevate:** none. Every slider use (voice tuning, call-handling pauses, the ROI calculator) is served by one slider component.

**Verdict: SKIP.** It duplicates `slider` with more decorative motion, haptics and no visible focus outside Arc's global CSS. Nothing in Calevate needs a rubber-band slider.

**Source:** `docs/design/uiarc/registry/elastic-slider/`

---

### calendar
**What it does:** A month grid for picking one day. It always shows six weeks, months slide sideways on a strip, the selected disc glides between days, and an optional Today button is available. It is used inside `date-picker` and is also usable inline.

**Exports / API:** `Calendar`

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `Date` | — | Selected day, compared by local Y/M/D |
| onChange | `(date: Date) => void` | — | |
| month | `Date` | — | Controlled visible month |
| onMonthChange | `(month: Date) => void` | — | |
| minDate / maxDate | `Date` | — | Days outside are `disabled` |
| disabledDates | `CalendarDateMatcher` (`(date: Date) => boolean`) | — | |
| locale | `string` | `"en-US"` (L113) | Month title, weekday names and day `aria-label` |
| className | `string` | — | |
| showToday | `boolean` | `false` | Today button |

Other exports: `useToday` (re-exported from `use-today.ts`), helpers `addDays`, `addMonths`, `sameDay`, `startOfDay` (L313), type `CalendarDateMatcher`.

**Dependencies:** npm: `motion`, `lucide-react` (both already in apps/web). Registry: `arc-motion-tokens`. Helper file `use-today.ts` installs to `@components/arc/lib/use-today.ts`; it is shared with `date-range-picker` and the two copies are byte-identical.

**How "today" is computed (`use-today.ts`):** `useSyncExternalStore` reads `new Date()` and builds a `YYYY-MM-DD` key from `getFullYear/getMonth/getDate`, which is the **browser's local zone** (use-today L4, L24). The key is turned back into a local-midnight `Date` (L5-8). It is `undefined` on the server and during hydration (L25, L27). It re-reads at the next local midnight, on tab visibility, and on window focus (L11-23). **All dates in the component are local-time `Date` objects at local midnight** (calendar L28-38). There is no time-zone prop and no use of `Asia/Kolkata`. A viewer whose device is not on IST sees the wrong "today", and so do `minDate` and Today-relative logic (D-709).

**Month and day names:** the month title, weekday names and per-day `aria-label` come from `Intl.DateTimeFormat` / `toLocaleDateString(locale, …)` (L162-164, L272). The weekday header truncates the Intl short name to its first two UTF-16 units (`day.slice(0, 2)`, L305). That is safe for English but can cut a Telugu or other Indic short weekday mid-cluster. The button and header strings are hard-coded English: "Today", "Previous month", "Next month" (L300-302).

**Accessibility:**
- `<section aria-labelledby>` with an `h2` month title (L288-297); the heading level is fixed at 2. A polite live region announces the month on navigation (L298).
- Grid: `role="grid"` and `role="row"`, with day `<button role="gridcell">`, `aria-selected`, `aria-current="date"` and a full-date `aria-label` (L261-282). The weekday header row is `aria-hidden` (L305), so the grid has no `columnheader`s; the full-date label compensates.
- Roving tabindex: one tab stop per month (L192-195, L275). Arrows, Home/End (week), PageUp/PageDown (month) and Shift+PageUp/PageDown (year) move focus and skip disabled days up to 42 tries (L211-241). Enter and Space select.
- The pane sliding away is `inert` and `aria-hidden` (L102).
- Reduced motion is honoured only after hydration (L120-121): the strip jumps, the title swaps in place, and CSS transitions are off (css L48-51).
- Forced colours: the selected state is a background disc (`.highlightFill`, css L35) behind a text-colour change, with no `forced-colors` rule. In Windows High Contrast the selected day may be indistinguishable. Not tested.

**Mobile:** width is `min(100%, 328px)` (css L1). Day cells are `aspect-ratio: 1` in a 7-column grid with 4px gaps (css L20, L29): about 43px at full width, about 37px at a 320px viewport with 16px gutters. That is below 44px. The previous/next buttons are 32x32 (css L14-15). The header wraps under 260px through a container query (css L4).

**Issues found in the code:**
- "Today" is the device's local date, not IST (use-today L24). This breaks D-709 for any viewer off IST.
- Values are local-midnight `Date`s. Calevate's date fields are `YYYY-MM-DD` strings meaning an IST day (`istDateStamp` in `ui.tsx` L1613, `scheduleStartAt` in `lib/api/campaigns.ts` L301). An adapter is needed in both directions, and it must not go through `toISOString()`.
- The week always starts on Sunday (`-month.getDay()`, L41; Home/End L232-233). There is no `weekStartsOn`, unlike `date-range-picker`.
- `"en-US"` default locale (L113); English strings at L300-302; `slice(0, 2)` weekday truncation (L305).
- Touch targets below 44px: nav buttons and phone-width day cells.
- There is no form `name` or hidden input, and no error or invalid state.
- Motion: the strip slide explains navigation. The disc glide with staggered number-colour hand-off (L166-181) is ornamental but quiet.

**Overlaps in Calevate:** none as a component. Calevate enters dates with native `<input type="date">`: 19 occurrences in 11 files, for example `campaigns/NewCampaignSteps.tsx` L305 and L342, `calls/CallsScreen.tsx` L259 and L263, `lead-sources/CallingPlan.tsx` L324, and the admin `ops/RateCardPanel.tsx`, `ops/ModelPricingPanel.tsx`, `ops/voices/hosted/VoiceDrawer.tsx` and `tenants/[tenantId]/DltRegistrationPanel.tsx`. Adopting a calendar makes it the one date control under one way per problem, so those inputs move with it (through `date-picker` / `date-range-picker`).

**Where in Calevate:** as the engine of `date-picker` and `date-range-picker`, not inline on any current screen.

**Verdict: ADAPT.** The keyboard model and grid semantics are good. Before use it needs an IST "today" (a `useToday` keyed on `Asia/Kolkata`), a `YYYY-MM-DD` string API, Intl-safe weekday labels, translatable strings, a week-start option and 44px targets on touch.

**Source:** `docs/design/uiarc/registry/calendar/`

---

### date-picker
**What it does:** A labelled trigger button showing the formatted date with rolling digits. It opens a popover `Calendar` with a footer offering a "Clear" button and a status line. Picking a day closes the popover after 300ms.

**Exports / API:** `DatePicker` (extends `ButtonHTMLAttributes<HTMLButtonElement>` minus `value`/`onChange`; extra button props spread onto the trigger, L105)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | Real `<label htmlFor>` (L103) |
| value | `Date` | — | Controlled only; there is no uncontrolled state |
| onChange | `(date: Date \| undefined) => void` | — | `undefined` on Clear |
| description | `string` | — | `aria-describedby` hint |
| placeholder | `string` | `"Select a date"` | |
| minDate / maxDate | `Date` | — | Passed to `Calendar` |
| disabledDates | `CalendarDateMatcher` | — | |
| locale | `string` | `"en-US"` | |
| format | `Intl.DateTimeFormatOptions` | `{ month: "short", day: "numeric", year: "numeric" }` | |
| showToday | `boolean` | — | |
| id, className, disabled, …button props | | | `id` defaults to `useId()` |

Other exports: none.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`, `calendar`; it imports `../calendar/calendar` (L8).

**"Today", time zone and names:** the opening month uses `new Date()`, the device's local clock (L50, L84). Inside, the `Calendar` uses the local `useToday`, as described in the calendar section. The value is a local-midnight `Date`. The display text comes from `Intl.DateTimeFormat(locale, format)` and `formatToParts` (L55, L61-62). English is hard-coded in "Select a date" (L45), `` `${label} calendar` `` (L120), "Clear", `` `Selected ${…}` `` and "Choose a day" (L125).

**Accessibility:**
- The trigger is a real button with `aria-haspopup="dialog"` and `aria-expanded` (L105). ArrowDown, Enter or Space opens it; Escape closes it (L92-95, L120).
- On open, focus goes to the calendar's tab-stop day (L73-75). On close, focus returns to the trigger if it was inside (L78-82).
- The popover is `role="dialog"` with no `aria-modal` and no focus trap. Tabbing out closes it (L97-100); a click outside closes it (L66-70).
- The value is read from an sr-only copy; the animated text is `aria-hidden` (L107-108).
- Reduced motion switches roll and blur to an instant fade (L37, L56); CSS transitions are off (css L34).

**Mobile:** the trigger is `--control-height-md` (44px, css L5). The popover is `position: absolute` under the trigger, `z-index: 20`, `width: min(320px, calc(100vw - 32px))` (css L20). It goes full-field width under 360px (css L22). It is not a bottom sheet and not portalled, so an ancestor with `overflow: hidden` clips it. The footer "Clear" button is `padding: 4px 8px` (css L27), far below 44px.

**Issues found in the code:**
- Local-clock "today" and local `Date` values (L50, L84, plus Calendar's), against D-709.
- `z-index: 20` (css L20) is under Calevate's `--z-dropdown: 30`, so a sticky bar or another dropdown can cover it.
- Not portalled: it is clipped inside cards or drawers with `overflow: hidden` (Calevate's `drawer.tsx` and modal panels scroll).
- The "Clear" target is tiny (css L27) and always offered. There is no `required`/no-clear mode, which a mandatory field such as a campaign start date needs.
- There is no form `name`, no `invalid`/error state and no uncontrolled mode.
- Decorative motion: per-part rolling date text with blur (L31-35), a footer status "rise" with blur (L39-43), and the popover scale-in.
- The `Intl.DateTimeFormat` is rebuilt on every render (L55), a minor cost.
- Hard-coded English and the `"en-US"` default, as listed above.

**Overlaps in Calevate:** native `<input type="date">` (19 occurrences, 11 files; see calendar). The native control gives a phone its own date wheel or sheet, takes and returns an IST-neutral `YYYY-MM-DD` string, and is fully accessible. `campaignForm.ts` (~L171) records the choice of two native fields "because a date picker and a time picker are what a phone renders usefully". Replacing it under one way per problem means moving all 11 files.

**Where in Calevate:** the campaign start date and "Stop after" date in `app/c/[slug]/campaigns/new` (`NewCampaignSteps.tsx` L305, L342), `campaigns/ArmingForms.tsx`, `campaigns/ConsentProvenance.tsx`, `lead-sources/CallingPlan.tsx`, and the admin `ops/RateCardPanel.tsx`, `ops/ModelPricingPanel.tsx`, `ops/voices/hosted/VoiceDrawer.tsx` and `tenants/[tenantId]/DltRegistrationPanel.tsx`.

**Verdict: ADAPT.** Take it only if the founder wants one custom date control across all 11 files. It must first be fixed for IST today, a `YYYY-MM-DD` string value, translatable copy, a portal at `--z-dropdown`, a bottom sheet (or the native input) on phones, 44px targets and a no-Clear required mode. Otherwise the native input should stay, because it is already correct on the phones most clients use.

**Source:** `docs/design/uiarc/registry/date-picker/`

---

### date-range-picker
**What it does:** A trigger that springs open into a panel holding a preset rail (Today, Yesterday, Last 7 days, and so on) and one or two month grids. The user clicks a start and an end, the range highlight stretches across each week, and Apply or Cancel commits or abandons the draft. The formatted label "flies" back into the trigger.

**Exports / API:** `DateRangePicker`

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `DateRange \| null` | — | Controlled (`{ start: Date; end: Date }`, inclusive) |
| defaultValue | `DateRange \| null` | `null` | |
| onChange | `(range: DateRange) => void` | — | Called on Apply only |
| label | `string` | `"Date range"` | Accessible name only; there is no visible label (L576) |
| placeholder | `string` | `"Select dates"` | |
| presets | `DateRangePreset[]` | `defaultDateRangePresets` (L73-82) | `{ label, range: (today) => DateRange }` |
| minDate / maxDate | `Date` | — | |
| weekStartsOn | `0 \| 1` | `0` (Sunday) | |
| locale | `string` | `"en-US"` | |
| months | `"auto" \| 1 \| 2` | `"auto"` | Two months when the boundary is at least 712px wide (L102, L403) |
| boundary | `() => HTMLElement \| null` | viewport | Element the panel keeps inside |
| className | `string` | — | |

Other exports: `defaultDateRangePresets`, `useToday` (re-export), types `DateRange`, `DateRangePreset`, `DateRangePickerProps`; `default` export.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`. Helper `use-today.ts` is the same file as calendar's.

**"Today", time zone and names:** `today` comes from the shared local-clock `useToday` (L268; see calendar). Presets compute from that local today (L73-82), so "Today" and "Last 7 days" are the device's days, not India's. All range ends are local-midnight `Date`s (L57-71). Month titles, weekday names and day labels use `Intl.DateTimeFormat`, including `formatRange` for the label (L283-290). The weekday header is again truncated with `.slice(0, 2)` (L227), though full names are kept as `aria-label` on `columnheader`s. English is hard-coded in all default preset labels (L74-81), "No dates" and the plural "day"/"days" (L563-564), the status sentences "Start … Choose an end date." (L565), "Pick an end date" (L624), "Presets" (L593), "Previous month"/"Next month" (L600-602), and "Cancel"/"Apply" (L628-629).

**Accessibility:**
- Trigger: `aria-haspopup="dialog"`, `aria-expanded`, `aria-controls`, and an `aria-label` of label plus value (L575-576). It is `disabled` until hydration supplies today (L576).
- Panel: `role="dialog"` with `aria-label`, non-modal, no focus trap. Escape closes it and returns focus (L468-470); blur or a click outside closes it without applying (L461-474).
- Grid: `role="grid"`, `columnheader` with full weekday names (L225-228), `gridcell` with `aria-selected` for in-range days (L243), buttons with full-date labels and `aria-current="date"`. Roving tab stop (L538-544). Arrows, Home/End, PageUp/PageDown and Shift+PageUp/PageDown work, clamped to min/max (L509-526). Enter or Space through the native button picks a day.
- Presets are `aria-pressed` buttons in a `role="group"`, with arrow keys between them (L528-536, L593-596). A polite live region speaks the draft and the day count (L565, L632).
- Reduced motion: `useReducedFlag` after hydration (L88-91) replaces springs with jumps and fades; CSS durations are 0 (css L209-211). `prefers-contrast: more` strengthens the border (css L213-215). No `forced-colors` rule; the range bar and ends are backgrounds (css L127-129).

**Mobile:** under 712px of boundary width it becomes one month with a horizontally scrolling preset row (L403-404, css L187-196). Panel width is `min(352px, available)`. Cells are clamped to 32-42px (L568), so about 37px at a 320px viewport. Preset buttons and nav buttons are 32px (css L73, L96-97); Cancel and Apply are `--control-height-sm` (36px, css L165). It scrolls the **window** to bring Apply into view (L379-397), which does nothing if the page scrolls inside a container. Whether Calevate's shells scroll the window is not determined from the source. The open root is `z-index: 30` (css L14), equal to Calevate's `--z-dropdown`. It is not portalled.

**Issues found in the code:**
- Local-clock today and local `Date`s (L268, L57-71); presets are device-day presets (L73-82). Against D-709.
- **Bug: presets ignore `minDate`/`maxDate`.** `choosePreset` (L499-507) sets the draft with no clamping, and Apply (L442-448) commits it. With `minDate` set, "Year to date" can apply a start before the minimum.
- There is no visible label, only `aria-label` (L576). Calevate form fields show a `FIELD_LABEL`.
- The trigger is `width: max-content` (css L38), not a full-width field.
- Touch targets of 32-37px (cells, presets, nav, actions).
- Heavy decorative motion: the trigger-to-panel surface morph (L308-344), the shared-layout label "flight" between trigger and footer (L566, L582, L619), word-by-word blur roll (L104-109, L124-133), the content `faceIn` blur (L111-115), and the gliding preset highlight (L547-559). Only the month slide and the range stretch explain state.
- Hard-coded radii in JS (`TRIGGER_RADIUS = 18`, `PANEL_RADIUS = 26`, L102) and CSS (`12px`, css L69, L78), outside tokens.
- There is no form `name` or hidden input.

**Overlaps in Calevate:** two native date inputs act as a range in `app/c/[slug]/calls/CallsScreen.tsx` (L254-266). These are "From"/"To" with `min`/`max` cross-limits and the hint "India time, both days included", shown when the range select is `custom`. The presets live in `lib/callFilters.ts` `RANGES` (Any time, Today, 7 days, 30 days, Custom), and the IST window is computed by `callWindow` from `istDateStamp()` (`lib/callFilters.ts` L52-65). Arc's preset rail would replace that select plus the two inputs. Its presets must be rebuilt on the IST day (`shiftDay` on `istDateStamp()`), not on `useToday`.

**Where in Calevate:** `app/c/[slug]/calls` (the custom range filter). On the **campaigns page** (founder's note), dates are not entered as a range. `NewCampaignSteps.tsx` takes a single start date plus time in IST (L303-310) or weekly days plus a time plus an optional "Stop after" date (L313-344). `campaignForm.ts` holds them as `startDate`/`startTime` strings joined by `scheduleStartAt` into an explicit `+05:30` instant (`lib/api/campaigns.ts` L301-306). The calling window is two `<input type="time">` (`NewCampaignSteps.tsx` L394-398); `ScheduleCards.tsx` only displays IST times. There is no start-and-end range for this picker to fill on the campaigns page; it fits campaign **results/history filtering**, if added, not campaign creation. Other candidates are date filters on `usage/`, `spend/` and admin `spend/`, which currently have no range picker (none found in those folders).

**Verdict: ADAPT.** It is useful for the calls filter, once rebuilt on IST days with `YYYY-MM-DD` strings, presets clamped to min/max, translatable labels, a visible label, 44px touch targets and the decorative morph and blur cut back. It does not fit campaign creation, which takes a start instant, not a range.

**Source:** `docs/design/uiarc/registry/date-range-picker/`

---

### rich-text-editor
**What it does:** A `contentEditable` rich-text editor with Markdown shortcuts as you type, a floating selection toolbar (bold, italic, strike, code, link, H1, H2, quote) that morphs into a link field, a "/" block menu, its own undo history, and HTML and Markdown output. The converters and sanitiser are built in.

**Exports / API:** `RichTextEditor` (`forwardRef<RichTextEditorHandle, RichTextEditorProps>`)

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `string` | — | Controlled **HTML**; rewritten only when it differs from the last emitted HTML (L570-571) |
| defaultValue | `string` | — | Initial HTML, sanitised on load (L813) |
| defaultMarkdown | `string` | — | Used when no HTML is given (L823) |
| onChange | `(value: RichTextValue) => void` | — | `{ html, markdown, text, empty }` (L549-554, L690) |
| onHistoryChange | `(state: { canUndo; canRedo }) => void` | — | |
| placeholder | `string` | `"Start writing"` | |
| blockHint | `string` | `"Type / for blocks"` | |
| readOnly | `boolean` | `false` | |
| autoFocus | `boolean` | `false` | |
| aria-label | `string` | `"Editor"` | |
| className / style | `string` / `CSSProperties` | — | |

Other exports: the `RichTextEditorHandle` methods (`focus`, `getHTML`, `getMarkdown`, `getText`, `setHTML`, `setMarkdown`, `clear`, `undo`, `redo`, `element`, L556-567); functions `normalizeUrl`, `markdownToHtml`, `htmlToMarkdown`, `sanitizeHtml`; types `BlockType`, `RichTextValue`, `RichTextEditorProps`; `default` export.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Output format, and fit for the script field:** the editor's native value is **HTML** (`value`/`defaultValue`/`setHTML`). `onChange` also hands out Markdown and a `text` string. `text` (`plainOutput`, L541-543) joins each block's `textContent` with `\n`. It drops list markers, heading levels, quote marks and link URLs, so formatting the user applied disappears silently. The agent script is spoken by the voice agent, and the prompt rules forbid markdown, bullets, asterisks and headings. `packages/shared/src/calevate_shared/engine.py` ~L2813 says "No markdown", and root CLAUDE.md says "When touching agent prompts". The editor's whole value is producing headings, lists, bold, code and links. Store its HTML or Markdown and the TTS reads the markup aloud. Store its `text` and the toolbar is a lie about what is kept. **It does not fit a field that must be plain spoken text.** The current plain `<textarea>`s are the correct control (`agents/[agentId]/script/ScriptSections.tsx` L141 and L501, `SectionEditor.tsx` L101, `HandWritten.tsx` L53 with `maxLength`). uiarc's own docs.md (L22, L215) also says to use a textarea for plain text.

**XSS review:**
- `dangerouslySetInnerHTML`: not used anywhere in the file.
- `innerHTML` writes:
  - L165: into a `<template>`, which is inert.
  - L223: returns the sanitised string.
  - L495: re-wraps a styled span from the editor's own DOM.
  - L515: a constant.
  - L719: an undo snapshot of the editor's own DOM.
  - L813: `load(sanitizeHtml(html))`.
- `document.execCommand` (deprecated) is used for bold, italic and strike (L985), `unlink` (L1058) and `createLink` (L1062).
- Paste (L1276-1326) always calls `preventDefault`.
  - Clipboard HTML goes through `sanitizeHtml` (L182-224): `DOMParser`, so the parsed document runs no scripts. It keeps a tag allowlist (L176-179), drops `script`/`iframe`/`img`/`svg` and similar (L178), and removes every attribute except an `href` that passes `safeUrl` (L19: `https:`, `http:`, `mailto:`, `tel:`, `/`, `#`).
  - Clipboard plain text becomes a text node, or goes through `markdownToHtml`, which HTML-escapes before building tags (L32-33).
  - Drop is blocked (L1197, L1478).
- **Defect: the link field bypasses the URL allowlist.** `normalizeUrl` (L22-28) returns any input that starts with a scheme unchanged (regex L25), including `javascript:` and `data:`. `applyLink` writes it with `setAttribute("href", url)` or `execCommand("createLink", …, url)` (L1047, L1062, L1066), and `safeUrl` is never consulted. `cleanClone` keeps `href` (L523), so the `html` and `markdown` handed to `onChange` (L685-690) carry the `javascript:` link. docs.md L216 says that output is "clean"; the code does not support that claim. A later `load()` would strip it, but any consumer that renders the stored HTML would not. `safeUrl` also admits `//host` (protocol-relative) through its `/` arm (L19).

**Accessibility:**
- The editor is `role="textbox"` with `aria-multiline`, `aria-label` and `aria-readonly` (L1467-1470). The "/" menu is a `listbox` with `option`s driven by `aria-activedescendant` (L1471-1472, L1551-1553). A polite live region announces link changes (L1482).
- Toolbar: `role="toolbar"` with arrow keys between buttons and Escape back to the text (L1443-1455), reached by Alt+F10 (L1250). It appears only when text is selected. Buttons carry `aria-pressed` (L640-642).
- The editor has `outline: none` (css L14), and Arc's global focus rule excludes `[contenteditable]`. Apart from the caret there is no visible focus indicator.
- Tab is captured inside list items (indent and outdent) and code blocks (L1251-1262), so a keyboard user cannot Tab out from there. Whether another escape key exists is not determined from the source.
- Shortcuts: Ctrl/Cmd+Z/Y/B/I/E/K and Ctrl+Shift+X; Ctrl+U is swallowed (L1242-1249). Ctrl+K and Ctrl+E shadow browser shortcuts on Windows and Android.
- Reduced motion swaps the toolbar and menu springs for fades (L621, L1493-1496).

**Mobile:** the toolbar is absolutely positioned within the root and clamped to its width (L1389, L1492). Tool buttons are 32px high (css L116). The toolbar needs a text selection to appear. How it interacts with the native selection callout on Android or iOS is not determined from the source. Blocks are reachable by typing "/".

**Issues found in the code:**
- The `javascript:` link defect above (L22-28, L1062, L1066).
- Its output (HTML or Markdown) conflicts with plain spoken text; `text` silently drops structure (L541-543).
- English is hard-coded throughout: "Start writing", "Type / for blocks", "Editor" (L649-650), toolbar labels (L1502-1511), the `SLASH_ITEMS` labels (L594-604), "Formatting", "Blocks", "Link address", "Paste or type a link", "Link added"/"Link removed" (L1079, L1489, L1523-1524, L1551). Shortcut hints use Mac glyphs (`⌘B`, L1502-1506) on Windows and Android.
- It relies on `document.execCommand` (L985, L1058, L1062), which is deprecated.
- No `maxLength` or character count; Calevate script fields are length-capped.
- There is no visible focus ring (css L14).
- Decorative motion: blur on the toolbar face swap (L616-620), and gliding highlights and size springs (L1359-1441).
- At 1,566 lines it is a large surface to own for a feature the product forbids.

**Overlaps in Calevate:** none as a rich editor. The script fields are plain `<textarea>`s in `app/c/[slug]/agents/[agentId]/script/` (`ScriptSections.tsx`, `SectionEditor.tsx`, `HandWritten.tsx`, `ProposalEditors.tsx`, `PipAsk.tsx`), and those are correct for spoken text.

**Where in Calevate:** founder's note: "script page" (`app/c/[slug]/agents/[agentId]/script`). It does not fit, for the reasons above. No other Calevate field needs headings, lists or links typed by a client. Knowledge-base text is uploaded as files or links (`knowledge/AddDocument.tsx`).

**Verdict: SKIP.** A spoken script must be plain text, and this editor exists to produce markup. Its link field also emits unsanitised `javascript:` hrefs. Keep the textareas.

**Source:** `docs/design/uiarc/registry/rich-text-editor/`

---

### file-dropzone
**What it does:** A dashed drop target (a button that opens the hidden file input) with a pointer-following glow while dragging. It keeps its own list of files, where each row shows a thumbnail or type icon, its size, and an upload phase (uploading with an animated percentage, uploaded with a drawn check, or failed with Retry). Files can also be pasted while the pointer or focus is over it.

**Exports / API:** `FileDropzone`

| Prop | Type | Default | Notes |
|---|---|---|---|
| accept | `string` | — | Checked in JS for dropped and picked files (L304-305) |
| multiple | `boolean` | `true` | |
| maxFiles | `number` | `5` | Overflow is refused with a message |
| onFilesChange | `(files: File[]) => void` | — | |
| label | `string` | `"Add files"` | |
| description | `string` | `"Drop files here or choose from your device"` | |
| defaultItems | `FileDropzoneItem[]` | — | Rows present at mount |
| onUpload | `FileDropzoneUpload` | — | `(item, { onProgress, signal }) => Promise<void>`; starts automatically on add (L330) |
| maxSize | `number` | — | Bytes; larger files fail without uploading |
| listPlacement | `"below" \| "inside"` | `"below"` | |
| note | `string` | `` `Accepted: ${accept}` `` or `` `Up to ${maxFiles} files` `` (L396) | |
| dropLabel | `string` | "Drop to upload" / "Drop to add files" / "Drop to add the file" (L395) | |
| compactAt | `number` | — | Folds the prompt once the list reaches this size |

Other exports: `formatFileSize`, types `FileDropzoneStatus`, `FileDropzoneItem`, `FileDropzoneUpload`, `FileDropzoneProps`; `default` export.

**Dependencies:** npm: `motion`, `lucide-react` (both in apps/web). Registry: `arc-motion-tokens`.

**Accessibility:**
- The target is a real `<button>` that clicks a hidden `<input type="file" tabIndex={-1} aria-hidden>` (L419, L435). `aria-describedby` points at the description and note.
- Rows: a `progressbar` with `aria-valuenow` and a per-file label (L184); Retry and Remove buttons named with the file name (L193, L196). Up and Down arrows move between rows; Delete or Backspace removes a row (L358-374). After removal, focus goes to the neighbour or back to the target (L347).
- Messages: an error row with `role="alert"` (L105) and a polite `role="status"` announcer (L438). Animated text keeps an sr-only plain copy (L83-86).
- Reduced motion: every enter, exit, shake and blur falls back to a fade or instant (L79, L87-89, L136, L246, L250); CSS transitions are off (css L111-114).

**Mobile:** the whole target is one tap area. Remove is 32x32 (css L100); Retry is 30px high (css L95) and becomes icon-only under 440px (css L97); under 300px the file icon hides (css L99). Rows are at least 58px (css L69). The default description, "Drop files here …", shows on touch devices too.

**Issues found in the code:**
- **No `disabled` prop** (props L18-34). `AddDocument.tsx` passes `disabled` when the plan does not allow uploads.
- **No `validate` callback**, only `accept` and `maxSize` (L304-316). `AddDocument.tsx` uses `validate={sizeProblem}`, and the design note there explains that only size is checked client-side so the API's `.doc` → "Save as .docx" remediation is not hidden.
- Empty (0-byte) files are accepted (L311). `FileDrop` refuses them ("That file is empty.", fileDrop.tsx L298).
- **The component owns the file list** (`useState` items, L203) and marks a row "Uploaded" when `onUpload` resolves (L290-293). `FileDrop` is caller-controlled "so the control never claims a file arrived that the server refused" (fileDrop.tsx L29-31).
- The failure reason is the raw `Error.message` (L296), so a server or vendor message reaches the client verbatim. Calevate routes errors through `ProblemNotice` with user-safe copy, and client-facing text must name no provider (D-679).
- The default note prints the raw `accept` string, for example "Accepted: .pdf,.docx,…" (L396). Calevate states accepted kinds in words (`knowledge/uploadCopy.ts` `ACCEPTED_KINDS_SENTENCE`).
- English is hard-coded in all defaults and messages (L176, L193, L196, L202, L293, L298, L319, L329, L345, L352, L395-396, L402).
- Decorative motion: the pointer-following edge glow and wash (L236-248), "sheets" that fan on hover, the shake on refusal (L49-50, L137, L250), blur text swaps (L44-46, L86-89), the drawn check (L110-115), and rows that "land" with blur (L164-166). The progress bar and its percentage explain state; the rest is ornament.
- A document-level `paste` listener is armed whenever the pointer hovers or focus is inside (L376-392).
- Touch targets of 30-32px (css L95, L100).

**Overlaps in Calevate:** `apps/web/src/components/fileDrop.tsx` `FileDrop`, THE file control. It is used by 5 screens: `app/c/[slug]/knowledge/AddDocument.tsx`, `app/c/[slug]/campaigns/ContactEditor.tsx`, `app/c/[slug]/verify-business/page.tsx`, `app/admin/payments/PaymentsScreen.tsx` and `app/admin/ops/voices/hosted/VoiceDrawer.tsx`. Side by side:

| | Calevate `FileDrop` | Arc `FileDropzone` |
|---|---|---|
| Control | `<label>` around a focusable sr-only `<input type="file">`; Tab reaches the input itself | `<button>` that clicks an `aria-hidden`, `tabIndex -1` input |
| Kinds and size stated before choosing | `hint` (required), in the server's words | `note` defaults to the raw `accept` string |
| Validation | caller's `validate`, else `accept` + `maxBytes` + empty file | `accept` + `maxSize` only; empty files pass |
| Disabled | yes | no |
| State owner | caller (`files`, `sending`) | component (internal list, auto-upload) |
| Progress | `sending.percent`, `null` = unknown (no fake bar) | per-row spring-animated percentage |
| Multiple files | optional; one in flight | list of up to `maxFiles`, parallel uploads, Retry |
| Phone copy | "or drag it here" hidden on touch (`touch:hidden`) | "Drop files here" on touch too |
| Remove target | 32px | 32px (Retry 30px) |
| Motion | colour change on drag-over | glow, shake, blur, fanning sheets |

One way per problem: `FileDrop` wins. Arc's per-row list with Retry and an `aria-valuenow` per file is the one idea worth folding into `FileDrop` if a multi-file screen ever needs it. That means adding to the existing control, not adding a second one.

**Where in Calevate:** founder's note: "knowledge base page" (`app/c/[slug]/knowledge`, `AddDocument.tsx` L99-107). That page sends one file at a time with real byte progress and a client-side size check only. `FileDrop` already does exactly this, and Arc lacks the `disabled` and `validate` the page depends on.

**Verdict: SKIP.** `FileDrop` is the established control and is stricter on validation, disabled state, honest progress and server truth. Arc's version would need those added and its decorative motion removed, leaving a second file control. Borrow the multi-row Retry pattern into `FileDrop` only if a screen needs it.

**Source:** `docs/design/uiarc/registry/file-dropzone/`

---

### scroll-area
**What it does:** A native scrolling container that hides the platform scrollbars and draws thin overlay bars. The bars appear while scrolling or on hover and can be dragged or paged. Edges fade (CSS mask) in proportion to the content hidden beyond them. A vertical mouse wheel scrolls horizontal strips, and scroll snap is optional.

**Exports / API:** `ScrollArea` (`forwardRef<HTMLDivElement, ScrollAreaProps>`; extends `HTMLAttributes<HTMLDivElement>` minus `onScroll`)

| Prop | Type | Default | Notes |
|---|---|---|---|
| children | `ReactNode` | — | |
| orientation | `"vertical" \| "horizontal" \| "both"` | `"vertical"` | |
| fade | `number` | `28` | Edge fade length in px; `0` disables it |
| scrollbars | `"auto" \| "always"` | `"auto"` | |
| hideDelay | `number` | `900` | ms |
| maxHeight | `CSSProperties["maxHeight"]` | — | |
| snap | `CSSProperties["scrollSnapType"]` | — | |
| label | `string` | — | Optional. When set, the viewport becomes `role="region"` with `aria-label` |
| wheelToHorizontal | `boolean` | `true` | Horizontal orientation only |
| viewportClassName / viewportStyle / viewportRef | | — | |
| onScroll | `(event: UIEvent<HTMLDivElement>) => void` | — | |
| onEdgeChange | `(edges: ScrollAreaEdges) => void` | — | |

Other exports: types `ScrollAreaEdges`, `ScrollAreaProps`; `default` export.

**Dependencies:** npm: none beyond React. Registry: none (registry-item.json lists no dependencies).

**Accessibility:**
- Scrolling is native, so keys, touch momentum and screen-reader scrolling work. The viewport is always `tabIndex={0}` (L189).
- `role="region"` and `aria-label` are applied **only if `label` is passed** (L189). Without it, the result is a focusable, unnamed `<div>`, even when nothing overflows.
- The overlay tracks are `aria-hidden` (L181), which is right, since native scrolling remains.
- The native scrollbars are hidden (`scrollbar-width: none` and `::-webkit-scrollbar { display: none }`, css L10, L13). The replacement thumb is a pseudo-element background (css L52-60), which forced-colours mode is likely to erase; there is no `forced-colors` rule. Users then lose all visible scroll position. Not tested.
- The track page-scroll respects `prefers-reduced-motion` (L177-178); CSS transitions are off (css L77-79).

**Mobile:** on touch the bars show only while scrolling (css L63-68; hover rules gated by `hover: hover`). `-webkit-overflow-scrolling: touch` and `overscroll-behavior-x: contain` are set (css L9, L11). The track hit area is 11px (css L43-44); on phones the bars are indicators, not targets.

**Issues found in the code:**
- An unnamed focusable stop when `label` is omitted (L189). Calevate's `ScrollRegion` makes `label` required for exactly this reason.
- The platform scrollbars are hidden (css L10, L13), with a forced-colours risk as above.
- The edge-fade mask (css L19-32) dims the first and last rows of a table or list. On Calevate's money tables (credit ledger, invoice), a faded column edge reads as missing content.
- Per-instance `ResizeObserver` + `MutationObserver` (L99-110) and a non-passive `wheel` listener on horizontal areas (L129-141).
- Hard-coded pixel geometry (`MIN_THUMB = 28`, L43; 11px tracks, css L43-44) and `color-mix` on `--foreground` (css L56, L70), with no Calevate token mapping.

**Overlaps in Calevate:** `ScrollRegion` in `apps/web/src/components/ui.tsx` (L1199-1223). It is a plain `overflow-x-auto` div with `role="region"`, a **required** `aria-label` and `tabIndex={0}`, and native scrollbars. It has 25 uses in 20 files, including the wide tables that the mobile rules require to sit in a `ScrollRegion`. One way per problem: `ScrollRegion` wins. Moving 20 files onto a component that hides native scrollbars and allows an unnamed region is a regression. The only idea worth borrowing is `onEdgeChange` or a scroll shadow as an optional hint on `ScrollRegion`.

**Where in Calevate:** wherever `ScrollRegion` is used today (data tables in `leads/`, `calls/`, `billing/`, admin tables, `lib/legal/document.tsx`). Arc adds nothing these need.

**Verdict: SKIP.** `ScrollRegion` is simpler, keeps native scrollbars, and enforces an accessible name. Arc's overlay bars and edge mask are cosmetic and weaken forced-colours and keyboard clarity.

**Source:** `docs/design/uiarc/registry/scroll-area/`

---

### accordion
**What it does:** A single-open, collapsible list of title and content rows built on Radix Accordion. Motion drives the panel height on a spring, rotates the chevron, and "settles" the content with a short blur.

**Exports / API:** `Accordion`

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `AccordionItem[]` (`{ title: string; content: ReactNode }`) | required | `title` is a string only |
| defaultOpen | `number` | `0` | Index of the item open at mount. **The first item opens by default** (L38-39); pass `-1` for none |
| size | `"md" \| "lg"` | `"md"` | `lg` is for page-level FAQs |

Other exports: types `AccordionItem`, `AccordionProps`; `default` export.

**Dependencies:** npm: **`@radix-ui/react-accordion` (new; apps/web has no `@radix-ui/*`)**, `motion`, `lucide-react`. Registry: `arc-motion-tokens`. The Radix package is a supply-chain addition (root CLAUDE.md hard rule 9) that needs the founder's approval (REDESIGN-2.md: no new npm dependency without asking).

**Accessibility:**
- Semantics come from Radix (L42-55): `Root` `type="single" collapsible`, `Header`, `Trigger` and `Content`. docs.md (L99) says Radix wires `aria-expanded`, `aria-controls` and region labelling. That wiring and the keyboard model live in the Radix package, not in this source, so they are not determined from the source here.
- The heading level is whatever `AccordionPrimitive.Header` renders; `Accordion` exposes no prop to change it.
- Closed panels stay mounted (`forceMount`, L50) and get `visibility: hidden` after collapsing (L22), which removes them from the accessibility tree.
- The trigger is `--control-height-lg` (50px, css L4); `lg` is 76px, or 68px under 520px (css L11, L14).
- Reduced motion uses zero-duration variants (L35-36, L46); CSS transitions are off (css L15).

**Mobile:** full width, with tall triggers that meet 44px. `lg` shrinks type and padding under 520px (css L14).

**Issues found in the code:**
- It requires a new npm dependency (L5) for what the native `<details>`/`<summary>` element already provides.
- `defaultOpen` defaults to `0` (L38-39), so the first item is open unless told otherwise. Calevate's `Disclosure` defaults closed.
- There is no `className`, no heading-level prop, no icon or subtitle, no `onToggle`, and no "multiple open" mode (props L12-18).
- `title` is `string`, so no rich titles. Item keys use `${title}-${index}` (L43).
- Decorative motion: the content blur "focus pull" on open (L24-25, L31).
- Colours come only from Arc tokens (`--border`, `--foreground`, `--text-secondary`, `--text-muted`) and need mapping.

**Overlaps in Calevate:** `Disclosure` in `apps/web/src/components/ui.tsx` (L280). It is built on native `<details>`/`<summary>` with a real `h2`/`h3`/`h4` inside the summary, `card` and `inline` variants, `icon`, `subtitle`, `defaultOpen=false`, `onToggle` and `touch:min-h-11`. It has 36 uses in 31 files, for example `billing/WhatCallsCost.tsx`, `billing/UsageTab.tsx`, `leads/FacetPanel.tsx`, `leads/MoreFilters.tsx`, `calls/[callId]/CallDetailScreen.tsx`, `agents/[agentId]/script/SectionEditor.tsx`, `settings/alerts/AlertsScreen.tsx`, and admin `ops/config/ConfigSection.tsx`. One way per problem: `Disclosure` wins. Replacing it would move 31 files onto a component with fewer options and a new dependency.

**Where in Calevate:** none beyond the places `Disclosure` already serves, such as the billing explainers, filter panels, script sections, call detail and admin config.

**Verdict: SKIP.** It needs a new Radix dependency to do less than the native-`<details>` `Disclosure` already does across 31 files. The only gain is a spring height animation, which a calm product does not need.

**Source:** `docs/design/uiarc/registry/accordion/`

---

### expandable-card
**What it does:** A single bordered card whose header button opens a details panel below it; the box springs in height (and optionally in width, up to `expandedWidth`) and changed words of the description roll in place.

**Exports / API:** `ExpandableCard` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| title | `string` | required | rendered as `<strong>` inside the header button (L118) |
| description | `string` | — | summary line; changed words animate via `RollingText` (L44-51) |
| children | `ReactNode` | required | panel content |
| defaultExpanded | `boolean` | `false` | uncontrolled only; there is no `expanded`/`onExpandedChange` |
| width | `number` | — | collapsed width cap in px; fills container when omitted |
| expandedWidth | `number` | `width` | expanded width cap in px |
| ...rest | `ComponentPropsWithoutRef<"article">` minus `title`, `children`, animation and drag handlers | — | spread on the `motion.article`; `className`, `style`, `onKeyDown` are merged (L53, L100-115) |

Other exports: type `ExpandableCardProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both already in apps/web/package.json). Registry: `arc-motion-tokens`.

**Accessibility:**
- Header is a native `<button>` with `aria-expanded` and `aria-controls` (L117); the panel stays mounted and is `inert` while closed (L121-122).
- Escape anywhere in the card collapses it and returns focus to the trigger (L100-106).
- The rolling description keeps an sr-only copy and hides the animated words (L45-49).
- No heading element: the title is a `<strong>` (L118), so the card does not appear in a screen reader's heading list.
- Touch target: trigger `min-height: 64px` (css L8).
- Reduced motion: `useReducedMotion` sets every transition to `{ duration: 0 }` (L62, L83, L119, L122-123) and the word roll skips its enter/exit (L48); CSS transitions off (css L22).
- Forced colors: not determined from the source.

**Mobile:** Fills its container when `width` is unset (css L2-3); measured by ResizeObserver (L64-72) so it never exceeds the track. Hover fill only under `(hover: hover) and (pointer: fine)` (css L9).

**Issues found in the code:**
- Title is not a heading (L118); Calevate's `Disclosure` puts a real `h2/h3/h4` in its `summary` (ui.tsx L303, L316-320) for UX-DOCTRINE §2.
- Decorative motion: the description's word roll blurs and lifts each changed word (L38-42); the width morph (L74-89) explains nothing a height change does not.
- Uncontrolled only: no `expanded` / `onExpandedChange`, so a screen cannot open it from a URL or close it after an action.
- Arc radius `--radius-surface` (2.125rem) and `--shadow-resting` (css L3) do not map to Calevate's `--radius-card 14px`; magic `innerWidth - 2` for the border (L123).
- Requires JS for anything to open; a native `<details>` does not.

**Overlaps in Calevate:** `components/ui.tsx` `Disclosure` (`variant="card"`, native `<details>` with a real heading, `onToggle`), used in 31 files. Under one way per problem `Disclosure` wins: it is semantic, works before hydration, and already has every caller.

**Where in Calevate:** none beyond what `Disclosure` already covers (e.g. settings and billing explainers).

**Verdict: SKIP** — duplicates `Disclosure` with weaker semantics (no heading, JS-only) and its distinguishing features (rolling words, width morph) are decorative motion.

**Source:** `docs/design/uiarc/registry/expandable-card/`

---

### expandable-text
**What it does:** Clamps long text to N lines with a soft mask over the last line and a "Read more / Show less" toggle that appears only when the text really overflows; opening animates the height, closing scrolls the text's start back into view.

**Exports / API:** `ExpandableText` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| children | `ReactNode` | required | full text stays in the accessibility tree while clamped |
| lines | `number` | `3` | collapsed line count; measured with a probe element in the text's own line height (L79-93) |
| expanded | `boolean` | — | controlled |
| defaultExpanded | `boolean` | `false` | |
| onExpandedChange | `(expanded: boolean) => void` | — | |
| moreLabel | `string` | `"Read more"` | |
| lessLabel | `string` | `"Show less"` | |
| ...props | `HTMLAttributes<HTMLDivElement>` minus `children` | — | `className`, `style`, `onFocusCapture` merged (L44, L135-136, L144) |

Other exports: type `ExpandableTextProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both present). Registry: none (`registryDependencies` is empty and the file does not import `../lib/motion-tokens`; durations and ease are local, L32-35).

**Accessibility:**
- Toggle is a native button with `aria-expanded` / `aria-controls` (L155); the inactive label is `aria-hidden`, so the name is the current label (L157-160).
- Keyboard focus landing on a link or button below the clamp opens the text (L134-140).
- Reduced motion: read only after hydration (L37-42); when reduced, the state jumps with no animation (L102) and `scrollIntoView` uses `behavior: "auto"` (L129); CSS transitions off (css L19).
- Touch target: toggle `min-height: 28px` (css L10), below the 44px Calevate floor (`touch:min-h-11`).
- Forced colors: the fade is a CSS mask, not a colour (L68-71); otherwise not determined from the source.

**Mobile:** Clamp is plain CSS at rest (`max-height: calc(lines * 1lh)`, css L4) so it follows width and font changes; `overflow-wrap: anywhere` (css L3) prevents a long token from widening a 320px screen.

**Issues found in the code:**
- Toggle 28px tall (css L10); needs a coarse-pointer 44px height.
- Decorative motion: the two labels crossfade with `blur(2px)` and a 4px drift (css L15-17); open runs 500-600ms (L34), slow for a text toggle.
- `overflowing` starts `true` (L48), so short text shows a toggle in the server HTML until the first client measurement removes it.
- Hard-coded English defaults "Read more" / "Show less" (L44); overridable by prop.
- Arc tokens (`--text-secondary`, `--leading-body`, `--tracking-body`, css L1) need mapping to `text-ink-muted` and Calevate's text scale.

**Overlaps in Calevate:** `components/interior/show-more.tsx` (`ShowMore` / `useShowMore`), which has 0 callers in `apps/web/src`; and a hand-rolled clamp in `app/c/[slug]/agents/[agentId]/script/ProposalReview.tsx` (`Quote`, L440-465: a character-count threshold, `line-clamp-4`, and a toggle with no `aria-expanded`). Arc's measures real overflow instead of counting characters. Replace `ShowMore` (nothing to move) and move the one hand-rolled `Quote` onto it.

**Where in Calevate:** `app/c/[slug]/agents/[agentId]/script/ProposalReview.tsx` (before/after quotes); long free text on `app/c/[slug]/calls/[callId]` (e.g. `CallVerdict`, `KeyMomentsCard`) and `app/c/[slug]/leads/[leadId]` (`LeadCaptured` notes); knowledge source descriptions under `app/c/[slug]/knowledge`.

**Verdict: ADAPT** — the best clamp in either kit (real overflow measurement, focus-opens, full text for screen readers); fix the 28px toggle, drop the label blur, shorten the duration, map tokens, and delete `interior/show-more.tsx` in the same change.

**Source:** `docs/design/uiarc/registry/expandable-text/`

---

### dialog
**What it does:** A centred modal built on Radix Dialog: portalled overlay with backdrop blur, a header with title, optional description and a close button, and a body slot; spring entrance, and the title/description crossfade when they change while open.

**Exports / API:** `Dialog`, `DialogContent`

`Dialog`:

| Prop | Type | Default | Notes |
|---|---|---|---|
| open | `boolean` | — | controlled |
| defaultOpen | `boolean` | `false` | |
| onOpenChange | `(open: boolean) => void` | — | |
| ...props | `ComponentPropsWithoutRef<typeof DialogPrimitive.Root>` | — | e.g. `modal` (L15-19) |

`DialogContent`:

| Prop | Type | Default | Notes |
|---|---|---|---|
| title | `string` | required | Radix `Dialog.Title`; changes crossfade (L55) |
| description | `string` | — | Radix `Dialog.Description`; string only |
| children | `ReactNode` | required | body |
| ...props | `ComponentPropsWithoutRef<typeof DialogPrimitive.Content>` | — | `className`, `onPointerDownOutside` merged (L42-53); `onOpenAutoFocus` etc. pass through |

Other exports: `DialogTrigger` (= Radix `Trigger`, L22), `DialogClose` (= Radix `Close`, L23), type `DialogContentProps`.

**Dependencies:** npm: **`@radix-ui/react-dialog` (new)**, `motion`, `lucide-react`. Registry: `arc-motion-tokens`.

**Accessibility:**
- Focus trap, Escape, focus return, `role="dialog"` and `aria-labelledby/-describedby` come from Radix, not from this file; Calevate has no Radix installed, so those behaviours are not verifiable in this tree.
- Close button `aria-label="Close dialog"` (L55), 32px square (`var(--space-8)`, css L20).
- A press that began while the dialog was leaving does not close the reopened dialog (L45-52).
- Reduced motion: opacity-only fades (L66, L68), keyframe fallback reduced (css L30-36).
- Forced colors: not determined from the source.

**Mobile:** Centred card `min(100vw - 2rem, 440px)` with `max-height` in `dvh` (css L3). It does not become a bottom sheet on a phone.

**Issues found in the code:**
- No actions/footer slot: buttons go in the body, so there is no phone stacking rule (Calevate's `MODAL_ACTIONS` stacks full width, primary on top).
- Centred on phones, unlike Calevate's modal frame, which sits at the bottom edge where the thumb is (ui.tsx L1080-1095).
- Decorative: `backdrop-filter: blur(7px)` on the overlay (css L1; uiarc's own docs.md flags its frame cost on low-end devices); title/description swap with blur (L35-40).
- Layering: overlay `z-index: 50`, content `51` (css L1, L3) collide with Calevate's `--z-assistant: 50` and sit under `--z-modal: 60` (globals.css L271-272); a dialog opened from the assistant panel would tie with it.
- Hard-coded English `"Close dialog"` (L55) with no prop; overlay colour `oklch(10% 0 0 / .46)` outside tokens (css L1).
- Close button 32px, below the 44px touch floor.
- `title` and `description` are strings only; `ModalDialog.description` takes `ReactNode` (modalDialog.tsx L33-34).

**Overlaps in Calevate:** `components/modalDialog.tsx` (`ModalDialog`: portal, `useFocusTrap`, `MODAL_*` frame), `components/confirmDialog.tsx` (`ConfirmDialog`, 36 caller files), the `MODAL_SCRIM/PANEL/ACTIONS` constants in `components/ui.tsx` (also used directly by `aiExtraDialog.tsx`, `voiceButton.tsx`, `agents/[agentId]/script/PutLive.tsx`). `ModalDialog` wins: it already holds the focus contract (container focus, Cancel first) that `ConfirmDialog` documents, is a bottom sheet on phones, and needs no dependency. Replacing it would mean a new Radix dependency plus re-verifying every `ConfirmDialog` caller's focus order.

**Where in Calevate:** none; every modal already goes through `ModalDialog` / `ConfirmDialog`.

**Verdict: SKIP** — a duplicate of `ModalDialog` that adds a Radix dependency, centres on phones, has no actions slot, and adds blur.

**Source:** `docs/design/uiarc/registry/dialog/`

---

### bottom-sheet
**What it does:** A modal sheet (Radix Dialog) that rises from the bottom edge and rests at detents (default 45% and 92% of the viewport); it follows the finger, rubber-bands past the top detent, projects a flick's velocity to pick a detent or dismiss, and dims the backdrop in proportion to its position.

**Exports / API:** `BottomSheet` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| trigger | `ReactNode` | — | wrapped in Radix `Trigger asChild` (L77) |
| open | `boolean` | — | controlled |
| defaultOpen | `boolean` | `false` | |
| onOpenChange | `(open: boolean) => void` | — | |
| title | `string` | required | Radix `Dialog.Title` |
| description | `string` | — | when absent `aria-describedby` is cleared (L358) |
| detents | `number[]` | `[.45, .92]` | fractions of viewport height; sorted, non-positive dropped (L86-87) |
| initialDetent | `number` | `0` | index into sorted detents |
| onDetentChange | `(index: number) => void` | — | |
| closeLabel | `string` | `"Close"` | close button `aria-label` |
| className | `string` | — | on the sheet surface |
| children | `ReactNode` | required | scrolls only at the tallest detent |

Other exports: `BottomSheetClose` (= Radix `Close`, L385), type `BottomSheetProps`.

**Dependencies:** npm: **`@radix-ui/react-dialog` (new)**, `motion`, `lucide-react`. Registry: `arc-motion-tokens`.

**Accessibility:**
- Focus trap, Escape and focus return come from Radix (not verifiable in this tree); initial focus goes to the sheet container (L359), which matches Calevate's `ConfirmDialog` choice.
- Grabber is a button with `aria-expanded` and "Expand sheet / Collapse sheet" (L365); ArrowUp/ArrowDown move one detent, Home/End jump (L318-324); Enter/Space toggles smallest/tallest (L314-317).
- With focus on the sheet, ArrowDown/PageDown/Space first expand, then scroll the body (L336-346); focusing an element below the fold expands (L330-333).
- Detent changes announced in a polite live region (L135, L379).
- Reduced motion: detents jump and the sheet fades (L126, L151-159); CSS transitions off (css L67-69).
- Touch targets: close `2rem` (css L52); grabber `1.25rem` tall (css L42), though the whole header is the drag handle (css L36).

**Mobile:** Built for it: height `calc(max-detent * 100dvh + extension)` with a `100vh` fallback (css L18-19), `env(safe-area-inset-bottom)` padding (css L22), `touch-action: none` on the header (css L36), body touch drags move the sheet until fully open and then scroll natively (L225-266, `passive: false` with `preventDefault`). Width `min(100%, 36rem)` (css L17), so on desktop it is a centred bottom sheet too.

**Issues found in the code:**
- No unsaved-edits guard: a downward flick dismisses (L218-220), which is easier to trigger by accident than Escape; Calevate's `Drawer` asks first while `dirty` or a `useUnsavedGuard` draft exists (drawer.tsx L57-63, L160-167).
- No footer/actions slot pinned above the safe area; `Drawer` has one, plus `DrawerSubmit` bound to `formId` (drawer.tsx L49-55, L227-233).
- Hard-coded English: "Sheet expanded", "Sheet collapsed", "Sheet at N percent height" (L135), "Expand sheet" / "Collapse sheet" (L365).
- Layering: overlay `z-index: 50`, sheet `51` (css L2, L11) vs Calevate `--z-drawer: 40` / `--z-assistant: 50` / `--z-modal: 60`.
- Overlay colours `oklch(...)` outside tokens, plus a dark-theme rule Calevate does not ship (css L2-3).
- Close button 32px (css L52), below 44px.
- Radix modal behaviour toward the rest of the page (whether siblings become hidden or inert) is not in this source; `Drawer` deliberately leaves the page reachable so a toast raised from inside it is still announced (drawer.tsx L7-8). Check this before adopting.
- On desktop it remains a bottom sheet (css L17); the founder note scopes it to phones.

**Overlaps in Calevate:** `components/console/drawer.tsx` (`Drawer`: side panel from `sm`, a full-height sheet from the bottom on phones via `inset-x-0 bottom-0 top-3`, `useFocusTrap`, footer, dirty guard; no drag-to-dismiss, no detents, no swipe gesture; 28 caller files) and the `MODAL_*` frame (a bottom sheet on phones, no gesture). One way per problem: do not add a third sheet. Arc's gesture and detent engine should become `Drawer`'s phone presentation (below `sm`), on `Drawer`'s own contract (portal, `useFocusTrap`, footer, dirty guard) instead of Radix. Then no `Drawer` caller moves.

**Where in Calevate:** founder's note: "mobile viewport". The phone branch of every `Drawer`: `billing/AddCredit.tsx`, `billing/ReceiptSheet.tsx`, `billing/StatementsView.tsx`, `lead-sources/*Drawer.tsx`, `integrations/AddDestinationDrawer.tsx`, `agents/[agentId]/script/ScriptBuilder.tsx` / `ScriptToolbar.tsx`, `data-rights`, `messaging-consent` (all under `app/c/[slug]/`).

**Verdict: ADAPT** — the gesture and detent work is good and Calevate has none, but it must ship as `Drawer`'s phone mode on `useFocusTrap` rather than Radix, keep the dirty guard and footer, use `--z-drawer`, 44px controls and translatable labels.

**Source:** `docs/design/uiarc/registry/bottom-sheet/`

---

### hover-card
**What it does:** A read-only preview card (Radix Popover, `role="tooltip"`) that opens after 500ms of mouse hover or on keyboard focus, opens almost at once when moving between triggers, stays open while the pointer travels into it, and toggles on tap; ships a `HoverCardProfile` person layout.

**Exports / API:** `HoverCard` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| children | `ReactElement` | required | the trigger; must take a ref and be focusable (Radix `Anchor asChild`, L136) |
| content | `ReactNode` | required | the preview |
| side | `"top" \| "bottom" \| "left" \| "right"` | `"bottom"` | |
| align | `"start" \| "center" \| "end"` | `"start"` | |
| openDelay | `number` | `500` | ms before the first card opens |
| closeDelay | `number` | `140` | ms grace after the pointer leaves |
| className | `string` | — | on the card surface |

Other exports: `HoverCardProfile` (props `name: string` required, `role?: string`, `avatar?: string \| ReactNode`, `bio?: string`, `stats?: HoverCardStat[]` default `[]`, `meta?: ReactNode`), types `HoverCardProps`, `HoverCardStat` (`{ label: string; value: string \| number }`), `HoverCardProfileProps`.

**Dependencies:** npm: **`@radix-ui/react-popover` (new)**, `motion`. Registry: `arc-motion-tokens`.

**Accessibility:**
- Content is `role="tooltip"` and the trigger gets `aria-describedby` only while open (L136, L152).
- Focus never moves into the card (`onOpenAutoFocus` prevented, L153), so anything focusable inside it cannot be reached by keyboard: Tab from the trigger leaves to the next page element and the blur schedules a close (L147).
- Keyboard focus opens it only on `:focus-visible` (L146); Escape closes it and keeps it closed while the pointer rests (L109, L154).
- Hover is mouse/pen only (`pointerType !== "touch"`, L133); touch toggles on tap (L139-145).
- Reduced motion: scale and travel dropped, short fade kept (L65, L88-89); profile rows skip the stagger (L191); portrait blur off (css L20).

**Mobile:** Card `18.5rem`, capped at Radix's available width or `100vw - 24px` (css L2). On touch a tap toggles it (L143), but the click handler does not `preventDefault`, so a trigger that is a link also navigates on the same tap.

**Issues found in the code:**
- Hover-only content model: the doctrine behind `InfoTip` says a hover-only tip "is unreachable on a phone and by keyboard" (console/infoTip.tsx docstring; UX-DOCTRINE §8.2, §8.6). Here focus reaches the trigger but never the card's content.
- `role="tooltip"` on rich content (image, `<dl>`, L192-202).
- Tap on a link trigger both opens the card and follows the link (L140-145).
- Page-global module state (`snapshot`, `closedAt`, L21-34) allows one card per page across React roots.
- Layering: `z-index: 60` (css L2) equals Calevate's `--z-modal`; Calevate puts popovers at `--z-dropdown: 30`.
- `HoverCardProfile` stat `value: string | number` (L165) invites raw numbers; Calevate money must arrive as formatted INR strings (hard rule 7).
- Decorative motion: stagger on profile rows (L191), portrait blur-in (css L7).
- `<img>` instead of `next/image` (L184-185).

**Overlaps in Calevate:** `components/console/infoTip.tsx` (`InfoTip`, click toggletip, 67 caller files), `TermGloss` in `components/ui.tsx` (reveals on hover, focus and tap), and `components/interior/popover.tsx` (`Popover` plus an exported `usePopoverPlacement`). `InfoTip` wins for explanations. Hover-card would only add a second pattern for redundant previews, and if taken, its Radix positioning can be replaced by `usePopoverPlacement`.

**Where in Calevate:** founder's note: "desktop viewport". At most a pointer-fine-only preview whose content is also on the trigger's click destination: a lead-name preview in `app/c/[slug]/leads` (`LeadTable`) linking to `leads/[leadId]`, an agent preview in `app/c/[slug]/calls` rows, tenant rows under `app/admin/tenants`. Never the only place a fact appears.

**Verdict: ADAPT** — usable only as a desktop enhancement with redundant content. It needs: a gate on `(hover: hover) and (pointer: fine)` with no tap toggle; no focusable content; Radix swapped for `usePopoverPlacement`; `--z-dropdown`; INR strings. Without those conditions, SKIP.

**Source:** `docs/design/uiarc/registry/hover-card/`

---

### alert
**What it does:** An inline message card with a tone icon (info / success / warning / danger), a title, optional details and an optional dismiss button; height springs when copy changes, and presence collapses height on dismiss.

**Exports / API:** `Alert` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| tone | `"info" \| "success" \| "warning" \| "danger"` | `"info"` | `danger` gets `role="alert"`, the rest `role="status"` (L75) |
| title | `string` | required | |
| children | `ReactNode` | — | details; strings crossfade on change (L84) |
| open | `boolean` | — | controls presence; hiding collapses height and fades |
| onDismiss | `() => void` | — | shows the dismiss button; uncontrolled alerts collapse first, then call it (L98, L102) |
| ...props | `HTMLAttributes<HTMLDivElement>` | — | spread on the alert box |

Other exports: types `AlertTone`, `AlertProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both present). Registry: `arc-motion-tokens`.

**Accessibility:**
- `role="alert"` for danger, `role="status"` otherwise (L75); outgoing copy is `aria-hidden` while it fades (L31-34).
- Dismiss button `aria-label={`Dismiss: ${title}`}` (L87), 28px (css L12).
- No focus management on dismiss: the button unmounts with focus on it (L102-105).
- Reduced motion: opacity-only swaps, height jumps (L73-74, L56, L99-100); CSS press transition off (css L15).

**Mobile:** Flex row with `min-width: 0` copy (css L2, L6); no phone-specific rules; dismiss 28px below the 44px floor.

**Issues found in the code:**
- The visual is what Calevate removed: a rounded, bordered, shadowed card (css L2) with a tone-coloured icon (L22, css L11). D-771 rule (3) and `apps/web/tests/noticeStyle.test.tsx` require a notice to be a 2px left tone rule on white with ink text, no `rounded`, and no icon medallion ("The medallion was the slop").
- Decorative motion: title, details and icon swap with blur and scale (L24-28, L77-78).
- Hard-coded English in the dismiss label (L87).
- Tones `info/success/warning/danger` differ from Calevate's `NoticeTone` `ok/warn/stop/neutral` (ui.tsx L904).
- No action slot; `NoticeBox` has `action` inline at the end of the bar.

**Overlaps in Calevate:** `components/ui.tsx` `NoticeBox` (152 files), `ProblemNotice` (281 files: renders API problems with remediation, field list, retry, trace reference), `RestrictionNote`, `NOTICE_BASE` / `NOTICE_BAR`. Calevate's set wins: it encodes a founder decision and is pinned by `noticeStyle.test.tsx`. Replacing it would touch over 400 files and reintroduce the rejected style.

**Where in Calevate:** none.

**Verdict: SKIP** — it is the tinted, iconed notice card that D-771 deleted and a test now forbids; `NoticeBox` / `ProblemNotice` already cover every case.

**Source:** `docs/design/uiarc/registry/alert/`

---

### toast
**What it does:** A single success-style toast surface (check icon, title, description, close button) that rises in, can be swiped sideways to dismiss, and auto-closes after `duration` when it is controlled; no provider, queue or viewport.

**Exports / API:** default export `Toast` (no named component export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| title | `string` | required | |
| description | `string` | — | |
| open | `boolean` | `true` | |
| onOpenChange | `(open: boolean) => void` | — | the auto-dismiss timer runs only when this is passed (L81) |
| duration | `number` | `4500` | ms; `<= 0` disables |

Other exports: type `ToastProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both present). Registry: `arc-motion-tokens`.

**Accessibility:**
- The toast element itself is `role="status"`, `aria-live="polite"`, `aria-atomic` (L120-122); it mounts and unmounts with its content.
- Close `aria-label="Dismiss notification"` (L147), 2rem (css L66-70).
- The timer does not pause on hover or focus (L80-84; uiarc's docs.md says so too).
- Reduced motion: fades only, and drag is turned off after hydration (L97-100, L130); check path draw skipped (L136).

**Mobile:** `width: min(100%, 26rem)` (css L3); positioning is left to the caller; horizontal swipe via motion `drag="x"` (L130).

**Issues found in the code:**
- The icon is always a success check (L134-137, css L22-25), so an error raised through it would show a tick.
- No pause on hover or focus (L80-84).
- Uncontrolled use never auto-dismisses, because the timer needs `onOpenChange` (L81).
- Decorative blur on text swaps (L12-14).
- Hard-coded English close label (L147); close 32px.

**Overlaps in Calevate:** `components/interior/toaster.tsx` (`ToastProvider` / `useToast`: tones, queue, pause on hover/focus, sr-only announcer, `z-toast`, safe-area inset), mounted by `app/admin/layout.tsx` and `app/c/[slug]/layout.tsx`. Calevate's wins; Arc's is a fragment of a system.

**Where in Calevate:** none.

**Verdict: SKIP** — a single success-only surface with no queue, tones or hover pause; `toaster.tsx` (or `toast-stack` below) covers it.

**Source:** `docs/design/uiarc/registry/toast/`

---

### toast-stack
**What it does:** A Sonner-style toast system: a provider-scoped store, a `useToastStack()` hook (`toast`, `update`, `dismiss`, `count`), and a viewport that tucks older toasts behind the front one and fans them into a list on hover, focus or tap. Toasts have types including `loading`, can be updated in place (icon, copy and height morph), carry one action, swipe right to dismiss, and pause while the stack is open, being dragged, or the tab is hidden.

**Exports / API:** `ToastStack` (also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | `"Notifications"` | region name; `" (Alt+T)"` appended when `hotkey` (L462) |
| position | `"bottom-right" \| "bottom-center" \| "bottom-left"` | `"bottom-right"` | |
| contained | `boolean` | `false` | pins inside nearest positioned ancestor |
| visibleToasts | `number` | `3` | rest wait, `inert` (L366) |
| hotkey | `boolean` | `true` | Alt+T focuses the stack (L427-440) |
| className | `string` | — | |

Other exports: `ToastStackProvider` (`children`, `duration` default `5000`, `limit` default `12`, L171), `useToastStack` (L177-181), types `ToastType` (`"success" \| "info" \| "warning" \| "error" \| "loading"`), `ToastAction` (`label`, `onClick(id)`), `ToastOptions` (`id?`, `type?`, `title`, `description?`, `action?`, `duration?`), `ToastStackApi`, `ToastStackProviderProps`, `ToastStackProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both present). Registry: `arc-motion-tokens`.

**Accessibility:**
- Viewport is a labelled `<section>` with `aria-live="polite"`, `aria-relevant="additions text"` (L462); each toast prefixes an sr-only type word (L376); outgoing copy `aria-hidden` (L184-187).
- Escape on a focused toast dismisses it (L356-360); when a focused toast leaves, keyboard focus moves to the next toast or back to where it came from (L272-279, L416-425).
- Timers pause on hover, keyboard focus, drag and hidden tab (L398, L409, L264-269); `loading` never expires (L98).
- Touch targets: action 28px, close 28px (css L41-42).
- Reduced motion: geometry jumps and opacity fades (L247-252, L281); spinner stops (css L60); transitions off (css L57-61).

**Mobile:** Under `30rem` the viewport centres across the width (css L9); touch has no hover, so a tap on a card opens or closes the stack (L343-347, L442-447); swipe right to dismiss with a 0.4-width projection threshold (L333). No `safe-area-inset-bottom` in the viewport offset (css L2, L9).

**Issues found in the code:**
- Errors are announced politely in the same region as everything else (L462), and they still auto-dismiss, only 1.6 times later (L98).
- Collapsed, only the front toast's content is visible (`content: 0` for tucked toasts, L119); the rest need hover, focus or tap.
- `useToastStack` throws outside a provider (L166). Calevate's `useToast` returns a working no-op by design, so screens render in unit tests and the a11y sweep without a shell (toaster.tsx L176-190).
- Not portalled: the fixed viewport renders where `<ToastStack />` is placed (L462), which `modalDialog.tsx`'s docstring explains is unsafe inside a transformed or sticky ancestor.
- Layering: `z-index: 60` (css L2) is below Calevate's `--z-toast: 70` and equal to `--z-modal`.
- No `env(safe-area-inset-bottom)` (css L2, L9); `toaster.tsx` has it.
- Hard-coded English: type labels "Success / Info / Warning / Error / In progress" (L80), "Dismiss notification" (L386), "Notifications" and "(Alt+T)" (L394, L462).
- Action and close buttons 28px (css L41-42).
- Decorative motion: text and icon swaps blur (L89-96).
- Naming differs from Calevate: `type: "error"` vs `tone: "danger"`, string ids vs numeric.

**Overlaps in Calevate:** `components/interior/toaster.tsx` is THE toast system (`ToastProvider`, `useToast`). Its callers are the two providers in `app/admin/layout.tsx` and `app/c/[slug]/layout.tsx`, plus one `toast()` call in `components/improvement/MakeCallTest.tsx` (L84-90). Arc's adds update-in-place (a `loading` toast that becomes its result), swipe, Escape, hidden-tab pause and focus hand-off, none of which `toaster.tsx` has. Replacing ours moves those 3 files.

**Where in Calevate:** both console shells (`app/c/[slug]/layout.tsx`, `app/admin/layout.tsx`); the save-and-confirm flows that today have one caller (`MakeCallTest`), and any long action that wants "Saving…" then "Saved" in one toast.

**Verdict: ADAPT** — a stronger version of what `toaster.tsx` does, and only 3 files to move. To replace ours it needs: a no-op default context; a portal; `--z-toast`; the safe-area inset; error toasts that do not auto-dismiss (or are announced assertively); 44px touch controls; translatable labels; no blur; and `tone` names kept so `MakeCallTest` reads the same.

**Source:** `docs/design/uiarc/registry/toast-stack/`

---

### announcement-bar
**What it does:** A slim bar for the top of a page that shows one or more messages, each with an optional call to action and a live countdown. With several messages it rotates them every 6s, rising each new one in while the bar springs to the new height, and optionally shows previous / pause-ring / next controls. Dismissing collapses the bar and, with an `id`, remembers it in `localStorage`.

**Exports / API:** `AnnouncementBar` (`forwardRef<HTMLElement>`, also the default export)

| Prop | Type | Default | Notes |
|---|---|---|---|
| messages | `Announcement[]` | required | `{ id: string; message: ReactNode; action?: AnnouncementAction; countdown?: { to: Date \| string \| number; label?: string } }` (L17-24) |
| id | `string` | — | dismissal remembered under `arc-announcement:<id>` (L59) |
| open | `boolean` | — | controlled; stored dismissal ignored when set (L178) |
| defaultOpen | `boolean` | `true` | |
| onOpenChange | `(open: boolean) => void` | — | called with `false` on dismiss |
| index | `number` | — | controlled visible message |
| defaultIndex | `number` | `0` | |
| onIndexChange | `(index: number) => void` | — | |
| interval | `number` | `6000` | ms per message |
| autoPlay | `boolean` | `true` | off under reduced motion (L214) |
| controls | `boolean` | `false` | previous / pause / next, only with 2+ messages |
| dismissible | `boolean` | `true` | |
| tone | `"neutral" \| "inverted"` | `"neutral"` | muted band, or foreground-coloured band |
| onAction | `(announcement: Announcement) => void` | — | after the action's own `onClick` |
| onCountdownEnd | `(announcement: Announcement) => void` | — | once at zero |
| label | `string` | `"Announcements"` | `aria-label` of the section |
| className | `string` | — | on the section |

`AnnouncementAction`: `{ label: string; href?: string; onClick?: () => void }` (L11-15).

Other exports: `clearAnnouncementDismissal(id)` (L61-63), types `Announcement`, `AnnouncementAction`, `AnnouncementBarProps`.

**Dependencies:** npm: `motion`, `lucide-react` (both present). Registry: `arc-motion-tokens`.

**Accessibility:**
- Role: a `<section aria-label>` (L249), so a named region landmark; with 2+ messages `aria-roledescription="carousel"` and each message a `group` / `slide` labelled "n of total" (L250, L155). It is not `role="status"` or `role="alert"`.
- Live region: the message viewport is `aria-live="off"` while rotating and `"polite"` otherwise (L258), so a single message is polite.
- Pause ring is a toggle with `aria-pressed` (L267); previous/next have `aria-controls` (L266, L274). With the default `controls={false}`, several messages rotate with no pause control; rotation pauses only on mouse hover, focus inside, or a hidden tab (L205-215). That fails WCAG 2.2.2 Pause, Stop, Hide for a pointer-less, focus-less reader.
- Countdown is `role="timer"`, `aria-live="off"`, labelled "N days H hours M minutes" (L126, L130).
- Dismiss: `aria-label="Dismiss"` with no subject (L276); the bar unmounts with focus on the button and nothing receives focus afterwards (L187-191, L248-249).
- No Escape handling.
- Touch targets: icon buttons `--icon: 32px` (css L5, L35); the CTA has `padding: 0` and no min-height (css L31).
- Reduced motion: no auto-rotation (L214), fades instead of rises, no height spring (L80, L239, L251-253), digit swaps fade (L97-98); CSS transitions off (css L58-60).

**Mobile:** Under a 560px container the mirror column drops and the message reads from the start edge (css L52-56); messages wrap and the viewport springs to the new height (L233-241). `text-wrap: balance` (css L13).

**Sticky:** No. `.collapse` has no `position` (css L2): the bar scrolls with whatever contains it. In Calevate's shells that is enough, because the strips sit above the header outside the scrolling `<main>` (`SHELL_MAIN_CLASS` is `overflow-y-auto`, ui.tsx L1263), so anything mounted there stays in view.

**Dismissal and its persistence:**
- Stored in `localStorage` under `arc-announcement:<id>` with the value `"dismissed"` (L59, L188). Storage errors are swallowed (L62, L180, L188). There is no expiry, and the key is not scoped to an account or user. `localStorage` is per browser profile, so a dismissal does not follow a person to another device, and on a shared device one person's dismissal hides it for the next.
- It is read in a `useLayoutEffect` (L177-184). Comment L181 says a dismissed bar "never flashes", but that holds only for a client-side mount; on a server-rendered page the bar is in the HTML (open by default, L175) and shows until hydration hides it.
- `remembered` is only ever set to `true` (L183). If the `id` prop changes while mounted (a new campaign), the bar stays hidden until remount.
- Calevate precedents to follow instead: `TrialBanner` keys by account and IST day (`calevate:trial-strip-closed:<slug>:<istDateStamp>`, `app/c/[slug]/TrialBanner.tsx`, `trialStripClosedKey`), reads after mount, and labels its close "Close until tomorrow". `components/forwarding/ExistingNumberPrompt.tsx` keys by slug (`calevate:existing-number-prompt:<slug>`, L11).

**Link / CTA:** `action.href` renders a plain `<a>` (L151-152), not `next/link`, so in-app links do a full navigation. It does not pass through `useClientRealm().href(...)`, which the client shell uses to carry an operator's view-as session (`TrialBanner` builds its credits link that way). `action.onClick` and `onAction` both fire (L152-153). The CTA always appends an arrow glyph (L152-153).

**Tones:** Only `neutral` (`--surface-muted` band, css L5) and `inverted` (foreground-coloured band, css L6). There is no `warn` or `stop`. Calevate's site strip is "a hairline under white, ink text, and a tone dot before the sentence. Never a tinted band" (ui.tsx `SITE_STRIP` docstring, L927-931); D-771 and the `TrialBanner` comment ("A site strip, not a tinted band") say the same. Both Arc tones are tinted bands.

**Stacking with the existing strips:**
- The client shell (`app/c/[slug]/layout.tsx` L92-99) renders, top to bottom: `OfflineBanner` (`components/offline.tsx`, `SITE_STRIP`, `role="status"`, renders nothing while online), `MaintenanceBanner` (`components/maintenance.tsx`, `SITE_STRIP`, `role="status"`, only while a window is scheduled or draining), `ViewAsBanner` (`app/c/[slug]/ViewAsBanner.tsx`, an amber-arm marker with an exit button, `SITE_STRIP` for the pending arm), `TrialBanner`, then `ClientTopHeader`. The admin shell has only `OfflineBanner` above `TopHeader` (`app/admin/layout.tsx` L713).
- Every existing strip renders nothing when it has nothing to say. An announcement bar should do the same: return `null` with no empty landmark (Arc returns `null` only for an empty `messages` array or when closed, L243-249).
- Suggested placement: last in that stack, after `TrialBanner` and directly above the header. The strips above it state the window's condition or who is looking; an announcement is lower priority. Since `TrialBanner` exists because a full-width strip "took half the first screen" on a phone, consider holding the announcement back while Offline, Maintenance or View-as is showing. These are recommendations, not code facts.
- `components/interior/collapsible-banner.tsx` has no callers in `apps/web/src`. It is an in-page notice card (`role="region"`, dismissal announced via a polite status), not a site strip. If the announcement bar lands, that unused file is the second way to do a dismissible notice.

**Issues found in the code:**
- Tinted bands only (css L5-6), against `SITE_STRIP` and D-771; no tone dot, no `warn` / `stop` tone.
- Default rotation with no pause control (L48, L214-215): WCAG 2.2.2.
- Decorative motion: message faces rise with `blur(4px)` (L75-79), countdown digits roll (L92-101), the CTA arrow nudges on hover (css L48).
- Countdown time: `new Date(to)` (L104) parses a zone-less string in the viewer's local zone, and the remaining time uses the device clock `Date.now()` (L112). Calevate's standard is IST (D-709), and `MaintenanceBanner` uses server-provided values instead (`backIn(seconds)`, maintenance.tsx). Pass an absolute instant with an offset and prefer a server-sent remaining duration.
- Hard-coded English: "Announcements" (L168), "Previous announcement" (L266), "Pause announcements" / "Resume announcements" (L267), "Next announcement" (L274), "Dismiss" (L276), "n of total" (L155), "days / hours / minutes" (L126), the unit mark "d" (L131).
- `message: ReactNode` is rendered inside a `<p>` (L156), so a caller passing a block element produces invalid HTML.
- The persistence defects listed above: SSR flash, `remembered` never reset, unscoped key, no expiry.
- Focus lost on dismiss (L187-191).
- Touch targets 32px and an unsized CTA (css L5, L31, L35).
- `inverted` tone uses `--background` / `--foreground` swaps (css L6); its forced-colors behaviour is not determined from the source.

**Overlaps in Calevate:** `SITE_STRIP` in `components/ui.tsx` (one class string; 4 files: `ViewAsBanner.tsx`, `maintenance.tsx`, `offline.tsx`, `ui.tsx`). `TrialBanner.tsx` hand-rolls the same strip with a dismiss. `interior/collapsible-banner.tsx` is unused. None of them is a general announcement component, so Arc's would be the first. Under one way per problem it should render through `SITE_STRIP` (white, hairline, tone dot, ink), and `TrialBanner`'s close-and-remember logic should become its persistence, so a dismissible site strip is done one way.

**Where in Calevate:** founder's note: "important, we will be using this soon". Client shell `app/c/[slug]/layout.tsx` (after `TrialBanner`, above `ClientTopHeader`); admin shell `app/admin/layout.tsx` (after `OfflineBanner`, above `TopHeader`); public pages (`app/page.tsx`, `pricing`, `roi`, `status`), where the server-rendered flash of a dismissed bar matters most.

**Verdict: ADAPT** — the mechanics (collapse, rotation pause rules, countdown cell, `clearAnnouncementDismissal`) are worth keeping, but it must be restyled onto `SITE_STRIP` with `NoticeTone` dots, fixed in these ways:
- persistence: account- or user-scoped key, read so a dismissed bar does not flash, reset when `id` changes;
- rotation: off unless pause controls are shown;
- CTA: `next/link` through the realm `href`;
- focus moved on dismiss, 44px controls, translatable labels;
- countdown driven by an absolute instant shown in IST;
- placed last in the strip stack, and render nothing when there is nothing to announce.

**Source:** `docs/design/uiarc/registry/announcement-bar/`

---

### cookie-consent
**What it does:** A bottom consent bar (Customize / Reject all / Accept all) that springs into a per-category preferences panel and, once a choice is saved, folds into a 44px cookie button that reopens it; the choice is reported through `onChange` and optionally kept in `localStorage`.

**Exports / API:** `CookieConsent` (forwardRef, handle `CookieConsentHandle`)

| Prop | Type | Default | Notes |
|---|---|---|---|
| categories | `CookieCategory[]` (`{id, label, description?, required?, defaultEnabled?}`) | `defaultCookieCategories` | required ones render "Always on" instead of a switch |
| value | `CookieConsentValue \| null` | — | controlled; `null` = not decided |
| defaultValue | `CookieConsentValue \| null` | `null` | |
| onChange | `(value, detail: {action: CookieConsentAction; updatedAt: Date}) => void` | — | |
| storageKey | `string` | — | `localStorage` key (L123-128) |
| version | `string` | `"1"` | a stored choice for another version is ignored (L116) |
| preferencesOpen | `boolean` | — | controlled panel |
| defaultPreferencesOpen | `boolean` | `false` | |
| onPreferencesOpenChange | `(open: boolean) => void` | — | |
| policy | `{label: string; href?: string; onClick?: () => void}` | — | renders `<a>` or `<button>` (L298-300) |
| position | `"bottom" \| "bottom-left" \| "bottom-right"` | `"bottom"` | |
| strategy | `"fixed" \| "absolute"` | `"fixed"` | |
| showReopenButton | `boolean` | `true` | |
| reopenSide | `"left" \| "right"` | bar side, or left | |
| labels | `Partial<CookieConsentLabels>` | English defaults (L96-107) | |
| className | `string` | — | |

Other exports: `readCookieConsent(storageKey, version)`, `defaultCookieCategories`, types `CookieCategory`, `CookieConsentValue`, `CookieConsentAction`, `StoredCookieConsent`, `CookieConsentHandle` (`openPreferences`, `closePreferences`, `reset`), `CookieConsentLabels`, `CookieConsentProps`; default export.

**Dependencies:** npm: `motion`, `lucide-react` (both already in apps/web). Registry: `arc-motion-tokens`, `button`, `switch` (imports `../button/button` and `../switch/switch`, L8-9; Calevate has its own `ToggleSwitch` and button class constants, so both would arrive as second implementations).

**Accessibility:** Bar and panel are `role="dialog"` with `aria-modal={false}` (L312, L324); the bar is described by its message, the panel labelled by its `<h2 tabIndex={-1}>` which takes focus on open (L326, L169). Escape closes the panel and returns focus to the bar or chip (L292-296, L219-222). Each switch is labelled by its `<label htmlFor>` and described by its hint (L335-341); Save carries a hidden "N of M optional categories allowed" description (L348-349). Reject all and Accept all have equal weight (L317-318). Reduced motion: `useReducedMotion` swaps blurred faces for a plain fade and jumps the surface geometry (L181, L281-284, L307-309); CSS drops transitions (css L66-68). Touch targets: the chip is 44px (css L44), the close button 32px (css L28), bar and panel buttons are `size="sm"` (Arc's `--control-height-sm`, 36px). Keyboard focus is drawn only by Arc's global `:focus-visible` rule in `foundation.css` L187-192, which Calevate does not have.

**Mobile:** The layer is fixed 16px from the viewport edges (css L2); the bar clamps to the layer width (max 660px) and stacks message above actions below a 560px bar width (L140, L313; css L16-19), with a two-row action grid below a 300px container (css L56-59). The panel list scrolls inside `min(46vh, 300px)` (css L31). No `env(safe-area-inset-bottom)` handling.

**Issues found in the code:**
- Default copy is hard-coded English and generic (L90-107: "your cart", "show relevant ads on other sites"); the screen-reader count is a hard-coded English template (L349).
- `46vh` in the list cap (css L31): Calevate uses `dvh`, never `vh`.
- Layer `z-index: 60` (css L2) equals Calevate's `--z-modal 60`, so it would sit level with `ModalDialog`.
- Close button 32px (css L28) and `sm` buttons (36px) are under the 44px touch target.
- Decorative motion: blurred faces rising in (L145-149), the whole surface springing width/height/radius between three shapes (L276-290), entry scale from .98 (L307). Under the Calevate motion rule this is morph for its own sake.
- Fixed bottom position with no safe-area inset covers the home-indicator area on a notched phone.
- No visible focus in Calevate without the Arc foundation focus rule.

**Overlaps in Calevate:** none as a component. The question is whether Calevate needs one, and the source answers it: `apps/web/src/lib/legal/cookies.ts` (the "Cookies & Tracking" notice, served by `app/legal/[slug]`) states that the public pages set no cookies (§1, L66-75), that the only cookies are the strictly-necessary first-party `__Host-` session cookies minted by `apps/api/authn/cookies.py` (L14-20), that there are no analytics, ad, pixel or third-party scripts (L84-87), and that "If we ever add analytics, a chat widget or any other non-essential technology, this page changes first and a consent mechanism appears with it" (§5, L256-258). A grep of `apps/web/src` finds no `document.cookie` writes and no analytics or tag-manager scripts (`lib/security/csp.ts` L44 says the same). Strictly necessary cookies need no consent banner, so there is nothing for this component to ask.
- Separate finding, outside this component: the same notice says "there is no `localStorage` anywhere in the tree" (L54) and "No local storage anywhere on this service" (L90), but seven client-console modules write `localStorage`: `app/c/[slug]/TrialBanner.tsx` L110, `app/c/[slug]/agents/[agentId]/tour/tourModel.ts` L144, `app/c/[slug]/caller-notice/useBlankValues.ts` L46, `app/c/[slug]/integrations/oauthReturn.ts` L68, `components/forwarding/ExistingNumberPrompt.tsx` L16, `lib/copilot/attachments.ts` L385, `lib/desktopAlerts.ts` L57. They are functional preferences (dismissed strips, a seen tour, a notification opt-in), not tracking, but the published notice is now false about them and should be corrected.

**Where in Calevate:** nowhere today. It becomes relevant only on the day a non-essential cookie or tracker is added, which `lib/legal/cookies.ts` §5 already ties to a notice change. Founder's note: checked as asked; Calevate sets no non-essential cookies.

**Verdict: SKIP** — Calevate sets only strictly-necessary first-party session cookies and its published notice explains why there is no banner; a consent bar would assert tracking that does not exist. Revisit only if analytics or a third-party script is ever added, and then with Calevate's own switch and buttons in place of Arc's.

**Source:** `docs/design/uiarc/registry/cookie-consent/`

---

### countdown
**What it does:** A live countdown to a fixed instant, drawn as digit wheels per unit (days/hours/minutes/seconds) in a large or compact pill variant, which morphs into a completion label when the target passes.

**Exports / API:** `Countdown`

| Prop | Type | Default | Notes |
|---|---|---|---|
| target | `Date \| number \| string` | required | number = epoch ms; offset-less string = wall time in `timeZone`, else UTC (L12-17, L53-63) |
| timeZone | `string` | — | IANA zone for an offset-less string |
| units | `CountdownUnit[]` | `["days","hours","minutes","seconds"]` | largest shown unit absorbs the rest (L40, L66-68) |
| variant | `"large" \| "compact"` | `"large"` | |
| completeLabel | `ReactNode` | `"Live now"` | |
| onComplete | `() => void` | — | fires once while mounted (L154-161) |
| label | `string` | `"Time remaining"` | accessible name |
| clock | `() => number` | `Date.now` | inject a server-synced clock (L30-31, L43) |
| ref | `Ref<HTMLDivElement>` | — | |
| className | `string` | — | |

Other exports: `toEpoch(target, timeZone?)`, type `CountdownUnit`, `CountdownProps`; default export.

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** Root is `role="timer"` with `aria-label` (L190); the visible digits are `aria-hidden` (L192) and a screen-reader-only sentence such as "2 days, 4 hours" is rendered beside them (L185, L214), dropping seconds above one minute so it is not chatty. Not focusable, no keyboard model needed. Reduced motion: wheels jump (L104), the label swap fades without blur or scale (L186-188), the shell stops springing (L177), and CSS stops the pulse (css L46-48). Ticking pauses when the tab is hidden or the element is off screen (L123-125) while completion stays armed (L144-150).

**Mobile:** The large variant sizes digits with `clamp(1.75rem, 12.5cqi, var(--text-5xl))` in a container query and keeps an even column floor so four groups fit at 320px (css L20-24). The compact pill is 32px tall (css L9), not interactive.

**Issues found in the code:**
- Unit names are hard-coded English (`NAMES`, L41), as are `"Live now"` (L113), `"Complete"` and the plural rule `${...}s` (L185); none go through Intl, so Telugu needs a rewrite.
- Default clock is the device clock (L43); Calevate's IST rule is satisfied only if callers pass ISO instants with an offset (or `timeZone: "Asia/Kolkata"` for wall-time strings) and, for anything that matters, a server-synced `clock`.
- Decorative motion: blurred digit wheels (L87), blur/scale label swap (L188), an infinite pulse ring on completion (css L41-43).
- No error state: an unparseable target renders an empty `role="timer"` (L118-119, L152).

**Overlaps in Calevate:** `apps/web/src/lib/authn/useCountdown.ts` (`useCountdown(deadline)`, one interval keyed on an absolute deadline, D-174) already drives every countdown the product shows: OTP resend cooldowns in `components/authn/signInForm.tsx`, `createAccountForm.tsx`, `emailVerificationPanel.tsx`, `stepUpPrompt.tsx` ("Send a new code in 23s" as plain `tabular-nums` text) and the admin idle-timeout warning in `components/authn/adminIdleTimeoutModal.tsx` (one call in each of those 5 files). Trial and grace deadlines are deliberately shown as IST dates, not ticking clocks (`app/c/[slug]/TrialCallPanel.tsx` L70, `billing/PlatformFeeCard.tsx` L147-148), and the admin screens record a decision not to repeat a server-computed `days_remaining` as a countdown (`app/admin/tenants/[tenantId]/AccountStateBanner.tsx` L20-23). `useCountdown` wins.

**Where in Calevate:** no screen needs a display countdown. The only candidates are the resend cooldowns and the admin idle modal, where a digit-wheel display adds motion to a 30-second wait that a sentence already explains.

**Verdict: SKIP** — Calevate's countdowns are one-line cooldowns served by `useCountdown`, and its deadlines are stated as IST dates by design; the wheel display is decorative and its strings are English-only.

**Source:** `docs/design/uiarc/registry/countdown/`

---

### usage-meter
**What it does:** An allowance meter: a title with a status badge (free / "Almost full" / over), a rolling headline total, a segmented bar of up to four categories against a limit (with a hatched overflow and limit marker once usage passes it), and a legend whose buttons preview or pin one category.

**Exports / API:** `UsageMeter`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | title and group label |
| segments | `UsageMeterSegment[]` (`{id: string; label: string; value: number}`) | required | display order, "up to four read clearly" (L20); colours are steps of the accent (css L2) |
| limit | `number` | required | same unit as segments |
| unit | `string` | `""` | appended as a suffix only (L189) |
| decimals | `number` | `1` | digits after the point, used for rounding and display (L185, L189) |
| freeLabel | `string` | `"Free"` | legend row for the remainder |
| overLabel | `string` | `"Over limit"` | legend row for the overage |
| warnAt | `number` | `.9` | share of the limit at which status becomes `near` |

Other exports: type `UsageMeterSegment`, `UsageMeterProps`; default export. The internal `StatusBadge` (L138) is not exported (and would clash by name with `ui.tsx` `StatusBadge` if it were).

**How it decides state (from the code):** `total` = sum of segment values rounded to `decimals` (L186); `status` is `"over"` when `total > limit`, `"near"` when `total >= limit * warnAt`, else `"ok"` (L188). There is exactly one threshold and three fixed tones: neutral, warning (`--warning` tint, `CircleAlert`), danger (`--danger` tint, `TriangleAlert`) (L154, css L8-14). Over the limit, the bar's span becomes the total so the overflow is drawn past a 2px limit marker, hatched and tinted danger on highlight (L199-218, L309-315; css L31-36). Values and limit are plain `number`s; there is no string or decimal input path, and text is produced with `value.toFixed(decimals)` (L189).

**Dependencies:** npm: `motion`, `lucide-react` (both present). Registry: `arc-motion-tokens`.

**Accessibility:** Root is `role="group"` labelled by the title (L295). The track is `role="img"` whose `aria-label` is a full sentence ("Minutes: 412.0 of 500 used. Clear 300.0, Studio 112.0. 88.0 free.") (L289, L306). It is not `role="meter"` or `role="progressbar"` and carries no `aria-valuenow/min/max/valuetext`. Rolling digits are `aria-hidden` with an sr-only "X of Y used" beside them (L301-302). Status changes, and a growing overage, are announced once each in a polite live region (L290-293, L336). The legend is a roving-tabindex group: Arrow keys and Home/End move, Enter/Space pins (`aria-pressed`), Escape unpins (L275-283, L317-334); each button is labelled "label, value unit" (L320). Pointer: mouse hover previews; touch taps on the track pin a category (L273-274). Reduced motion: `useReducedMotionSafe` (L44-47) jumps every spring and swaps text with a plain fade (L67, L114, L212, L240, L249); CSS drops transitions (css L61). Touch target of a legend button is padding `var(--space-2)` around two text lines (css L40, L44, L50); its exact height is not determined from the source, and the bar itself is a 14px tap strip (css L24). No focus style of its own: keyboard focus relies on Arc's global foundation rule, which Calevate lacks.

**Mobile:** The legend is an `auto-fit` grid of 108px minimum columns, so it wraps to two columns on a phone (css L39); the caption ellipsizes on one line (css L19-20); the long label wraps beside the status badge (css L4-5). Touch pins rather than hovers (L274).

**Issues found in the code:**
- Numbers only. Calevate's minute figures arrive as decimal strings (`minutes_used: string`, `overage_minutes: string` in `lib/api/schema.d.ts`; UsageTab prints them "as sent", `billing/UsageTab.tsx` L147-151) and money is `spend_used_inr: string` (hard rule 7). The meter would need `Number()` for geometry and the server string for every displayed figure; as written it re-derives the displayed total and remainder in float (L186-187) and prints `toFixed` output, which is a second, browser-side computation of a billed quantity.
- Formatting is inconsistent and not Indian: the ticker groups with `Intl.NumberFormat("en-US")` (L80), the badge, caption, sr text and legend labels use ungrouped `toFixed` (L189), so the visible "1,234.5" and the spoken "1234.5" differ; neither is `en-IN` (Calevate's `formatCount` uses `en-IN`, `ui.tsx` L1446-1448).
- `unit` is suffix-only (L189), so "₹" cannot be placed; an empty unit produces a caption starting with a space (" of 500 used", L287).
- A false zero: the headline renders `0` until the meter is hydrated and scrolled into view (L184, L285), and segments start at 0 (L194). Calevate's rule is that a skeleton is not a number (UsageTab L106-110).
- `limit` of 0 (pay as you go, `included_minutes` 0) makes every use "over" and the share `Infinity`% (L188, L286); the component has no "no limit" state.
- "Over" is always painted as an error. In Calevate going past included minutes is billed overage on a plan that allows it, not a fault, and the spending cap cannot be exceeded (calls pause, UsageTab L112-121), so the danger tone and "Over limit" would mislabel both cases. The tone needs to be the caller's choice.
- Hard-coded English beyond the two label props: "Almost full" and "… over" / "… free" (L288), the caption templates (L287), the summary sentence (L289), the announcements (L293), "by category" (L317).
- No loading, error or disabled state; negative segment values are not guarded.
- Decorative motion: odometer digit wheels with blur (L92-122), blurred text swaps (L57-61), icon pop with scale and blur (L62-66), staggered segment reveal (L241).
- Colours are accent steps (css L2) and `--warning`/`--danger`; Calevate would map to `--brand` steps and `--chart-warn`/`--chart-danger`.

**Overlaps in Calevate:**
- `app/c/[slug]/agents/[agentId]/script/ScriptToolbar.tsx` `RoomLeft` (L139-161): a single-value allowance bar done the Calevate way: `role="meter"` with `aria-valuemin/max/now/valuetext`, brand → warn under 10% left → danger over, and the words beside it.
- `components/interior/progress-bar.tsx` `ProgressBar` (7 caller files): task progress (`role="progressbar"`), not an allowance; it stays for progress.
- `components/illustration/trialMeter.tsx` `TrialMeter`: a 16px decorative ring (`aria-hidden`, L31) for the top-bar trial chip; it stays as a glyph.
- The usage figures themselves are shown as `Metric` tiles and sentences, not bars: `billing/UsageTab.tsx` L124-176 (minutes used vs `included_minutes`, extra minutes), the cap section L385-407 ("Used so far" vs "In force this month"), `TrialCallPanel.tsx` L73-77 ("Free minutes left: N of M"), `TrialBanner.tsx` L58-64 (low at under 10% of free minutes).
Under one way per problem, an adapted UsageMeter should become THE allowance meter and absorb `RoomLeft` (one caller) in the same change; `ProgressBar` and `TrialMeter` stay because they answer different questions.

**Where in Calevate:** `app/c/[slug]/billing` Usage tab (`UsageTab.tsx`): minutes used against included minutes, segmented Clear vs Studio from the per-band rows already on that tab (L220-224); the spending-limit section (minutes or rupees used against the cap in force). `app/c/[slug]/TrialCallPanel.tsx`: free trial minutes left. `/c/[slug]/usage` and `/c/[slug]/credits` are retired redirects into billing tabs (`usage/page.tsx`, `credits/page.tsx`, D-525), so the meter lives on the billing tabs. Agent Studio trial minutes (`trial_studio_minutes`, console default 15): the web schema exposes only the fallback reason `studio_minutes_used` (`lib/api/schema.d.ts` L13237, `lib/firstAgent.ts` L290), not a used/limit pair, so a Studio-trial meter needs the API to publish those two figures first. Founder's note: "will be of great use".

**Verdict: ADAPT** — the segmented allowance with a limit marker and announced threshold changes is a real need on the billing Usage tab and the trial panel, but it must take server decimal strings for display (numbers for geometry only), format `en-IN`, gain a "no limit" state and a skeleton instead of a 0, let the caller choose whether going over is billed overage (warn) or an error, expose `role="meter"` with `aria-value*` like `RoomLeft`, move every string to props, drop the odometer and blur, and restyle to brand/chart tokens; then replace `RoomLeft` with it.

**Source:** `docs/design/uiarc/registry/usage-meter/`

---

### onboarding-checklist
**What it does:** A getting-started card with a progress ring and "N of M done", one expanded step at a time (description, error, one action button), steps the person ticks off by hand or by running the action, finished steps striking through and folding into a "N completed" disclosure, and a Hide/Show toggle for the whole card.

**Exports / API:** `OnboardingChecklist`

| Prop | Type | Default | Notes |
|---|---|---|---|
| title | `string` | required | |
| doneTitle | `string` | `"You’re all set"` | title once all are done |
| steps | `OnboardingStep[]` (`{id, title, description?, actionLabel?, onAction?: () => void \| Promise<void>}`) | required | `onAction` resolves to check the step off, throws to show `error.message` (L17-18) |
| defaultCompleted | `string[]` | `[]` | read once at mount (reducer init, L225) |
| onCompletedChange | `(completed: string[]) => void` | — | |
| defaultHidden | `boolean` | `false` | read once at mount |
| onHiddenChange | `(hidden: boolean) => void` | — | |
| className | `string` | — | |

Other exports: type `OnboardingStep`, `OnboardingChecklistProps`; default export.

**Dependencies:** npm: `motion`, `lucide-react` (both present). Registry: `arc-motion-tokens`.

**Accessibility:** `<section aria-labelledby>` with an `h3` title (L304, L308; level fixed). Progress ring is `role="progressbar"` with `aria-valuemin/max/now` and `aria-valuetext="N of M steps done"` (L144). Each step has a `role="checkbox"` button (`aria-checked`, labelled by the step title) and a title button with `aria-expanded`/`aria-controls` opening a `role="region"` panel (L160, L190-192). Arrow Up/Down, Home, End walk step titles (L286-294). After a step settles, focus moves to the next step's action or title (L240-250, L257); reopening a completed step focuses its checkbox (L248, L265). Leaving rows are `inert` (L186, L212); the hidden body is `inert` (L317). Errors are `role="alert"` (L196); a `role="status"` region announces "X done. N of M complete." (L68, L73, L345). The action button uses `aria-disabled` and `aria-busy` while pending (L198). Reduced motion: `useReducedMotion` after hydration (L222-224) zeroes height springs and swaps blur rises for fades (L94-112); CSS drops transitions and the spinner (css L67-70). Touch targets: checkbox 40px (css L27), title row 40px (css L36), Hide and action buttons `--control-height-sm` 36px (css L13, L46), completed toggle 44px (css L56). No focus style of its own (relies on Arc's foundation rule).

**Mobile:** Container query hides the Hide label below 380px, leaving a 36px icon button (css L18). Description is capped at 46ch (css L43). No other phone-specific layout.

**Issues found in the code:**
- Completion is owned by the browser: `defaultCompleted` is read once (L225), there is no controlled `completed` prop, and a step without `actionLabel` is "checked off by hand" (L15), so a person can tick a step that is not done and a server change after mount is never reflected. Calevate's checklists show only states the server answered (`console/checklist.tsx` L132-133, §52).
- Only two states, done and not done; no waiting, blocked or disabled-with-reason.
- The step action is a callback button only (L198); there is no link, so "Open" into another route (`setup?step=…`) would need `router.push` inside `onAction`.
- A thrown error's `message` is shown verbatim (L276); Calevate shows API failures through `ProblemNotice`, not raw messages.
- Hide state is local (L89, L280-283); Calevate persists dismissal on the server (`SetupChecklist.tsx` L71-80, `useSetupAction`).
- Heading level fixed at `h3` (L308); Calevate's `Checklist` takes `headingLevel`.
- Hard-coded English: `"You’re all set"` (L220), "Setup progress" and "steps done" (L144), `"Step"` (L55), the status messages (L68, L73), `"That didn’t work. Try again."` (L276), Show/Hide and "checklist" (L312-313), "Steps to do" (L319), "completed" / "Completed steps" (L328-334).
- Touch targets of 36-40px (above) are under 44px.
- Decorative motion: blurred title and count swaps, rolling count digits, icon pop with blur (L99-112, L125-138); the 720ms struck-through pause before a row folds (L45) does explain the change.

**Overlaps in Calevate:** `apps/web/src/components/console/checklist.tsx`. Its `Checklist` (done / todo / waiting / blocked rows with `detail`, `link`, `action`, `disabledReason`, a `role="progressbar"` bar, a native `<details>` collapse that still says "2 of 4 done", `headingLevel`) is used 9 times in 8 files: `app/c/[slug]/SetupChecklist.tsx` (dashboard and Settings > Business), `agents/[agentId]/sections/overview.tsx`, `caller-notice/FillPanel.tsx`, `campaigns/LaunchGate.tsx`, `setup/SetupDone.tsx`, `verification/page.tsx`, `admin/ops/voices/hosted/OwnModelCard.tsx` and `StudioVoicesCard.tsx`. `ChecklistRows` (status pills and InfoTips) has 7 more uses. The ordered flows are different components: `setup/SetupWizard.tsx` (one topic per step, interior `ProgressBar`, progress from the server), `go-live/GoLiveGuide.tsx` and `agents/first` (`StepRail`/`StepScreen` from `agents/first/shell.tsx`, strict order). Arc's own doc comment says to "use a step form when the order is strict" (L24), so it does not compete with those.
**Which wins:** `console/checklist.tsx` wins. It is server-truthful, has the four states the product needs, links into routes, and is already the single checklist across both consoles. Merge by borrowing, not replacing: (1) the "current step" pattern, where the first unfinished row is expanded with its description and one primary action while the rest stay one line, would suit the dashboard `SetupChecklist`; (2) folding done rows into a "N completed" disclosure would shorten long lists; (3) moving focus to the next row's action after one completes. Each would be added to `Checklist` behind props, with state still passed in from the server and no manual check-off.

**Where in Calevate:** dashboard `/c/[slug]` (`DashboardScreen.tsx` L279 mounts `SetupChecklist`), `/c/[slug]/settings/business`, `/c/[slug]/setup` (SetupDone), `/c/[slug]/agents/[agentId]` overview, `/c/[slug]/campaigns` launch gate, `/c/[slug]/verification`, `/c/[slug]/caller-notice`. Founder's note: "onboarding flow and other parts of Calevate" — served today by `Checklist`, with the borrowed patterns above.

**Verdict: SKIP** (as a component; borrow three patterns into `console/checklist.tsx`) — Arc's checklist trusts the browser for completion and has only done/not-done, while Calevate's checklist is server-driven with waiting/blocked/disabled rows and links, and already has 16 call sites.

**Source:** `docs/design/uiarc/registry/onboarding-checklist/`

---

### badge
**What it does:** A tinted, bordered pill with an optional icon whose label and icon cross-fade and whose width springs when its text changes.

**Exports / API:** `Badge`

| Prop | Type | Default | Notes |
|---|---|---|---|
| tone | `BadgeTone` (`"neutral" \| "success" \| "info" \| "warning" \| "danger"`) | `"neutral"` | |
| size | `BadgeSize` (`"sm" \| "md"`) | `"md"` | 22px / 26px min height (css L3, L23) |
| icon | `ReactNode` | — | `aria-hidden` (L75) |
| ...props | `HTMLAttributes<HTMLSpanElement>` | — | spread on the root `<span>` incl. `className`, `children` |

Other exports: types `BadgeTone`, `BadgeSize`, `BadgeProps`; default export.

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** A plain `<span>`; outgoing text copies are `aria-hidden` while they fade so only the current word is read (L25-29). No role or live region, so a changed state is not announced. Reduced motion: instant fades, no width spring (L39, L61, L69, L75-76); CSS shortens colour transitions (css L50-52). Not interactive.

**Mobile:** `white-space: nowrap` and `overflow: clip` (css L14-16) mean a long label overflows its row or is clipped at 320px rather than wrapping.

**Issues found in the code:**
- Hover changes border and background (css L20-22) on a non-interactive element, which reads as clickable.
- Tinted capsule with border for every tone (css L44-48); `warning` and `success` text is drawn in `--warning`/`--success` on a 10-11% tint, contrast not determined from the source.
- No wrap option; long or Telugu labels clip (css L14-16).
- Decorative motion: blurred text rise (L19-20), icon pop with blur (L21), width spring (L64).
- `sm` uses a literal `11px` (css L23).

**Overlaps in Calevate:** `apps/web/src/components/console/statusPill.tsx` `StatusPill`, "THE ONE STATE MARK" in both consoles (79 files): a 6px tone dot and the word, deliberately with no fill, border or capsule (D-771, L23-33), a `wrap` option for 320px (L43), and the console's change mark on a state change (`statusPillShell.tsx`). `components/ui.tsx` `StatusBadge` (L503-516, 3 uses) is a lead/call-status wrapper over `StatusPill`. StatusPill's doc states that a tag which is not a state is plain `text-meta text-ink-muted` text (L32-33). `StatusPill` wins.

**Where in Calevate:** none; every state mark is `StatusPill`.

**Verdict: SKIP** — a tinted capsule is the look the founder rejected in D-771, and `StatusPill` already covers state marks in 79 files with wrapping and a change mark.

**Source:** `docs/design/uiarc/registry/badge/`

---

### metric-card
**What it does:** A bordered, shadowed card holding a label, an optional signed change chip coloured up/down, a rolling animated number with suffix, and a context line; every text change rises in from a blur.

**Exports / API:** `MetricCard`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | |
| value | `number` | required | rendered by `AnimatedCounter` with `animateOnView` (L47) |
| suffix | `string` | — | |
| context | `string` | required | line under the number |
| change | `string` | — | leading `+` → green "up", `-`/`−` → red "down" (L46) |

Other exports: type `MetricCardProps`.

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`, `animated-counter` (imports `../animated-counter/animated-counter`, L6; present in the registry folder).

**Accessibility:** An `<article>` with no heading or label (L45). The number's screen-reader text is an sr-only span inside `AnimatedCounter` while the digits are `aria-hidden` (`animated-counter.tsx` L78-79). The change chip's direction is colour plus sign. Reduced motion: text swaps become instant fades (L12, L17), the chip does not scale (L46). Not interactive.

**Mobile:** Below 380px the padding drops to `--space-4` and the top row wraps (css L6). One card per metric; layout of a row of cards is the caller's.

**Issues found in the code:**
- `value: number` (L8) cannot carry Calevate's money or minute figures, which are server decimal strings formatted by `formatINR` (hard rule 7); `Metric` takes a `ReactNode`.
- `AnimatedCounter` defaults to `locale = "en-US"` (`animated-counter.tsx` L67) and MetricCard does not pass one, so 1,00,000 renders as 100,000.
- No null or loading state: there is no "—" for an unknown value (the retired `StatTile` had `value ?? "—"`, `ui.tsx` L425).
- Colour by sign only (css L17-18): a fall in failed calls is good news painted red; there is no tone prop.
- Card chrome (border, shadow, 24px padding, css L1-2) contradicts Calevate's flat KPI strip.
- Decorative motion: blurred rises on label, context and chip (L11), digit wheels, and a count-up on scroll into view (L47).

**Overlaps in Calevate:** `apps/web/src/components/console/metric.tsx` `Metric` and `MetricRow`: "the unit of a KPI strip", a label, a `ReactNode` value, a hint, a `tone` whose meaning the hint states (WCAG 1.4.1), `tabular-nums`, `overflow-wrap:anywhere`, and the console's change flash when a polled value moves (L13-54). `<Metric` is used 85 times in 23 files (billing UsageTab, SpendChart, performance, admin). `components/ui.tsx` `StatTile` (L391-431) has no callers anywhere in `apps/web/src`, so it is dead code and can be deleted. `Metric` wins.

**Where in Calevate:** none; every KPI figure is a `Metric`.

**Verdict: SKIP** — `Metric` already serves 85 call sites with string values, tones and change marking; MetricCard's number-only value, en-US digits and sign-coloured chip would regress money display and colour meaning.

**Source:** `docs/design/uiarc/registry/metric-card/`

---

### line-chart
**What it does:** A multi-series line (and optional area) chart drawn in hand-rolled SVG, with nice-number gridlines, a crosshair scrubbed by pointer or keyboard, a following tooltip, series toggles, and morphing between data ranges.

**Exports / API:** `LineChart`

| Prop | Type | Default | Notes |
|---|---|---|---|
| data | `LineChartDatum[]` (`{key, label, axisLabel?, values: Record<string, number \| undefined>}`) | required | a missing value counts as zero (L28-29) |
| series | `LineChartSeries[]` (`{key, label, color?, dashed?, area?}`) | required | |
| label | `string` | required | figure name |
| unit | `string` | `""` | suffix |
| height | `number` | `220` | plot px |
| formatValue | `(value: number, series: LineChartSeries) => string` | `grouped.format` (en-US) | tooltip and table |
| formatTick | `(value: number) => string` | en-US compact ("1.2K") | value axis |
| hiddenSeries / defaultHiddenSeries | `string[]` | — / `[]` | |
| onHiddenSeriesChange | `(hidden: string[]) => void` | — | |
| onActiveChange | `(index: number \| null, datum: LineChartDatum \| null) => void` | — | |
| loading | `boolean` | `false` | dims lines, `aria-busy` |
| emptyLabel | `string` | `"No data for this range"` | |
| legend | `boolean` | `series.length > 1` | |
| categoryLabel | `string` | `"Date"` | first column of the sr table |
| curve | `"smooth" \| "linear"` | `"smooth"` | monotone cubic, clamped to the data (L103-124) |
| ref | `Ref<HTMLElement>` | — | |
| className | `string` | — | |

Other exports: types `LineChartSeries`, `LineChartDatum`, `LineChartProps`; default export.

**How it draws:** SVG paths written straight to the DOM by one `paint` function (L233-269); no chart library. Axes: y ticks in an HTML gutter riding the animated scale (L160-165, L415-417), x labels thinned to one per 76px counted back from the latest (L168-174). Tooltip: an `aria-hidden` HTML bubble that flips sides at the edge (L262-268, L402-409). Colour: series 1 is `var(--accent)`, then two neutral greys (`PALETTE`, L80); it does not use `--series-1..4`.

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** `<figure aria-label>` (L378). The plot is `role="slider"` (`aria-valuemin/max/now`, `aria-valuetext` "label: series value, …") with Arrow, PageUp/Down, Home, End and Escape (L355-362, L386); keyboard focus selects the latest point (L388). An sr-only summary sentence (L424) and a full sr-only `<table>` with caption and `scope` headers (L425-429) are the text alternative; a polite region says "Loading" (L430). Legend toggles are `aria-pressed` buttons (L380). Reduced motion: `useReducedMotionSafe` (L144-147) jumps morphs, scale, draw-in and crosshair (L296, L313, L320, L328, L339); CSS drops transitions (css L57-58). The plot has `outline: none` (css L18), so in Calevate, without Arc's global focus rule, the focused slider shows no ring. Legend toggles are 32px tall (css L5).

**Mobile:** Width follows the container (ResizeObserver, L277-287); `touch-action: pan-y` keeps vertical scrolling while a horizontal drag scrubs, with pointer capture, and lifting the finger clears the crosshair (css L18, L363-368, L387).

**Issues found in the code:**
- Number formatting is en-US (L81-82): the default axis reads "1.2K", not lakh/crore; callers must pass `formatValue`/`formatTick` built on `en-IN`.
- Values are `number`; money would need converting from Calevate's strings and the tooltip would print a float unless `formatValue` maps back.
- A missing value is drawn as zero (L28-29, L205), which turns a gap in the data into a false zero.
- Hard-coded English: "explore by" (L386), "series shown" (L372), "Choose a series to show" (L411), "Loading" (L430), and the defaults "No data for this range" and "Date".
- No visible keyboard focus in Calevate (css L18), 32px toggles.
- Decorative motion: left-to-right draw-in (L326-332), morphing on every range change (L291-304), springing tooltip.
- Light-only Calevate ignores the dark rules; colours need mapping to `--brand` and `--chart-*`.

**Overlaps in Calevate:** none. Every chart in the client console is a hand-built bar or bar list (`DailyCalls.tsx`, `OutcomeSplit.tsx`, `performance/PerformanceCharts.tsx`, `billing/SpendChart.tsx`); a search of `apps/web/src/app` finds no line or `polyline` chart, and apps/web has no chart library dependency.

**Where in Calevate:** no current screen. The APIs behind performance (`lib/api/performance.ts`: funnel, outcomes, hours) and the dashboard (`daily_7d`) return no multi-period series that a line would serve better than the existing daily bars.

**Verdict: SKIP** — no Calevate screen has a series that needs a line, and adopting it without one would be a half-wired component; if a trend view is added later, it is a solid base once formatting, gaps, focus and strings are fixed.

**Source:** `docs/design/uiarc/registry/line-chart/`

---

### bar-chart
**What it does:** A single-series column chart in hand-rolled SVG with a headline that shows the period average at rest and the scrubbed bar's value while scrubbing, an optional dashed average line, nice-number gridlines, and zoom/morph animation when the range changes.

**Exports / API:** `BarChart`

| Prop | Type | Default | Notes |
|---|---|---|---|
| data | `BarChartDatum[]` (`{key, label, axisLabel?, value: number}`) | required | one series only |
| label | `string` | required | |
| period | `string` | required | e.g. "Sep 15–21, 2026" |
| unit | `string` | `""` | suffix |
| averageLabel | `string` | `"Daily average"` | |
| valueLabel | `string` | `"Total"` | headline label while scrubbing |
| categoryLabel | `string` | `"Day"` | sr table first column |
| showAverage | `boolean` | `true` | |
| height | `number` | `176` | |
| formatValue | `(value: number) => string` | en-US, 0 decimals (L60) | |

Other exports: types `BarChartDatum`, `BarChartProps`; default export.

**How it draws:** SVG `<path>` columns with a rounded data end (L75-79), bars placed counting back from the latest so the newest stays pinned right (L81-93); gridlines and tick labels ride an animated scale from 0 (L64-72, L129-146); axis labels are measured and thinned to fit (L156-174). No tooltip: the headline above the plot is the readout (L353-357). Colour: one soft step of `--accent`, the scrubbed bar full accent (css L26-28); it does not use `--series-*`.

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** `<figure>` with an sr-only `figcaption` (L351-352); the SVG is `role="img"` with a summary sentence (average, highest, lowest) (L347, L360). A transparent overlay is `role="slider"` with Arrow, PageUp/Down (7 bars), Home, End, Escape (L327-334, L381-383). An sr-only `<table>` (L385-389) and a polite announcement of the new period (L390). Reduced motion: every spring jumps (L86, L107, L117, L292, L298, L310) and text swaps fade (L182). The scrubber has `outline: none` (css L44), so no focus ring in Calevate without Arc's global rule.

**Mobile:** `touch-action: pan-y` on the scrubber (css L44); drag scrubs, release clears (L335-340); bars cap at 28px wide and 58% of the slot (L59). For 24 bars at 320px each slot is about 13px, and axis labels thin to fit.

**Issues found in the code:**
- Single series only; Calevate's `DailyCalls` is a four-way stacked column (completed / no answer / failed / still running).
- The headline average and the summary's average are computed in the browser in float (L236, L319, L347). For calls that is harmless; for money it is a rupee figure the server did not produce (hard rule 7; `billing/WhereItWent.tsx` L23-28 records why the browser does no money arithmetic).
- Empty data has no empty state: the header shows an average of 0 and the period (L236, L354-356), a false zero, and the slider stays focusable (L381).
- Values from 0 upward only (L64); negatives (refund corrections) cannot be drawn.
- en-US formatting by default (L60); "Avg" (L319), "No data" (L344), "Highest"/"Lowest" (L347) and "explore by" (L381) are hard-coded English.
- Decorative motion: staggered grow-in (L104-112), zoom on range change (L291-294), blurred rolling digits in the headline (L177-220).
- Dark-theme rules (css L30-32) are dead weight in light-only Calevate.

**Overlaps in Calevate:** the bars Calevate already draws by hand with `div`s and token colours: `app/c/[slug]/DailyCalls.tsx` (stacked, per-bar totals printed, sr-only table, IST date labels without constructing a Date), `performance/PerformanceCharts.tsx` `HourHistogram` (24 hourly bars, sr-only table, `min-w-[620px]` scroller) and `Funnel`/`Outcomes` (horizontal bars), `billing/SpendChart.tsx` `SpendOverTime` (daily spend from `bigint` paise, `formatINR` titles, sr-only table). None has keyboard scrubbing; all print their numbers or a table so nothing depends on hovering. Replacing them is one way per problem only if all the vertical-bar charts move: `HourHistogram` and `SpendOverTime` fit a single series; `DailyCalls` would need a stacked mode added.

**Where in Calevate:** `/c/[slug]/performance` (calls by hour), `/c/[slug]/billing` spend over time, and `/c/[slug]` dashboard calls per day if stacking is added.

**Verdict: ADAPT** — keyboard scrubbing, gridlines and the sr table are an improvement over the hand-built columns, but it needs a stacked mode for `DailyCalls`, an empty state, `en-IN` and string-to-prop English, the average hidden (or server-supplied) for money, a visible focus ring, brand/`--chart-*` colours and the grow/zoom/blur motion cut to a plain update; then all three vertical bar charts move to it in one change.

**Source:** `docs/design/uiarc/registry/bar-chart/`

---

### donut-chart
**What it does:** A donut of parts of one whole in hand-rolled SVG, with small parts grouped into "Other", a centre readout that rolls between the total and the active segment, a synced legend that toggles or selects segments, and arcs that morph between datasets.

**Exports / API:** `DonutChart`

| Prop | Type | Default | Notes |
|---|---|---|---|
| data | `DonutChartDatum[]` (`{key, label, value: number, color?}`) | required | values of 0 or less are dropped (L77) |
| label | `string` | required | |
| unit | `string` | `""` | |
| formatValue | `(value: number) => string` | en-US, 1 decimal (L71) | |
| totalLabel | `string` | `"Total"` | |
| size | `number` | `208` | diameter px |
| thickness | `number` | `24` | ring px |
| groupBelow | `number` | `.04` | share below which parts join Other |
| maxSegments | `number` | `6` | counting Other |
| otherLabel | `string` | `"Other"` | |
| activeKey / defaultActiveKey | `string \| null` | — / `null` | |
| onActiveChange | `(key: string \| null) => void` | — | |
| hiddenKeys / defaultHiddenKeys | `string[]` | — | |
| onHiddenKeysChange | `(keys: string[]) => void` | — | |
| legendAction | `"toggle" \| "select"` | `"toggle"` | |
| legend | `boolean` | `true` | |
| emptyLabel | `string` | `"No data yet"` | |
| ref | `Ref<HTMLElement>` | — | |
| className | `string` | — | |

Other exports: types `DonutChartDatum`, `DonutChartProps`; default export.

**How it draws:** Annular sectors with constant pixel gaps and rounded corners computed in code (L107-135) and written to the DOM once per frame (L247-260); no chart library. No axes or tooltip: the centre readout and the legend carry the values (L388-415). Colour: `var(--series-1..4)` in first-seen key order, then neutral steps; Other is a fixed grey (L65-68, L190-197).

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** `<figure aria-label>` (L381). Legend rows are buttons, `aria-pressed` (toggle or selected), labelled "label, value, share" (L401), with Arrow/Home/End roving and Escape (L349-357). Without a legend the ring itself is a focusable `role="group"` walked with arrows and Enter/Space (L358-369, L383). An sr-only summary (L377, L416), a polite region announcing hide/show and the walked segment (L230, L368, L417), and an sr-only table that expands Other into its members (L418-422). Shares under 1% read "<1%" (L73). Reduced motion: jumps arcs and lift, no drum roll (L154, L164, L296-300, L317, L400); CSS drops transitions (css L48). Legend rows are 40px tall (css L32). No focus style of its own.

**Mobile:** The ring is `size` px wide and the SVG scales down to its container (L382; docs say it scales to narrower containers); the legend sits below the ring and moves beside it at a 460px container width (css L5). Touch: the ring takes clicks to select (L340-343); hover preview is mouse only (L335-339).

**Issues found in the code:**
- The total and every share are computed in the browser in float (L186, L229, L346, L411). For money (the Calevate case for a spend split) that is a second implementation of a bill; `billing/WhereItWent.tsx` L23-28 forbids exactly this.
- en-US formatting (L71-72); hard-coded English in "Use the arrow keys to read each segment" (L379), "Includes" (L346), "and N more" (L378), "shown"/"hidden" (L230), "Press a segment to show or hide it" (L396), table headers "Segment/Value/Share" (L420), plus the Total/Other/"No data yet" defaults.
- Colours default to Arc's `--series-*` palette (L67), which is not Calevate's brand/`--chart-*` set and is not tied to meaning (a "failed" outcome would get whatever colour its index gets).
- Toggling segments off changes the total the centre shows (L185-186), so the headline number depends on UI state.
- Decorative motion: sweep reveal (L301-305), segments lifting out on hover (L313-320), drum-roll centre (L161-165).
- 40px legend rows (css L32) are under 44px.

**Overlaps in Calevate:** `app/c/[slug]/OutcomeSplit.tsx` (how calls ended: horizontal bars in one colour, longest first, words and count on each row, chosen as the dashboard's one split chart per REDESIGN-2, L6-14), `SentimentSplit.tsx` (counts as one sentence, by founder decision, L5-8), `performance/PerformanceCharts.tsx` `Outcomes` (bars toned by outcome with `--chart-warn/-danger`), and `billing/WhereItWent.tsx` (spend split as rows of server rupee strings, no browser arithmetic). The sorted bar lists are the better encoding for five to eight outcomes on a 320px phone and they already win.

**Where in Calevate:** none.

**Verdict: SKIP** — Calevate's part-of-whole views are sorted bar lists and sentences by founder decision, and the money split forbids the browser-side totals and shares a donut computes.

**Source:** `docs/design/uiarc/registry/donut-chart/`

---

### brush-chart
**What it does:** A dense time series in two parts: a main line or area plot with a value axis, date axis, crosshair tooltip and event markers, and an overview strip under it where a window is dragged, resized or redrawn to zoom the main plot.

**Exports / API:** `BrushChart`

| Prop | Type | Default | Notes |
|---|---|---|---|
| data | `BrushChartDatum[]` (`{ date: Date \| number; value: number }`) | required | ascending order; `value` is a JS number |
| label | `string` | required | names the figure, plot and slider |
| unit | `string` | `""` | appended after a space |
| formatValue | `(value: number) => string` | `en-US` grouped, 1 decimal (L65, L161) | tooltip and table |
| formatTick | `(value: number) => string` | `en-US` compact, e.g. "12K" (L64, L161) | value axis only |
| formatDate | `(date: Date) => string` | `en-US`, `timeZone: "UTC"` (L66-67) | tooltip and live announcement only |
| annotations | `BrushChartAnnotation[]` (`{ date, label, description? }`) | `[]` | event markers on both plots |
| range | `[number, number]` | none | controlled window, epoch ms |
| defaultRange | `[number, number]` | whole series | |
| onRangeChange | `(range: [number, number]) => void` | none | fires on every drag frame (L337) |
| minSpan | `number` | 7 days (L161) | |
| height | `number` | `240` | main plot px |
| overviewHeight | `number` | `52` | strip px |
| emptyLabel | `string` | `"No data yet"` | shown when fewer than 2 points (L180) |
| ref | `Ref<HTMLElement>` | none | the `<figure>` |
| className | `string` | none | |

Other exports: types `BrushChartDatum`, `BrushChartAnnotation`, `BrushChartProps`; default export.

**How it draws:** SVG paths built per render from the points in view (L238-241); past two points per pixel each pixel column keeps its low and high (L121-138). Zoomed out it cross-fades to a centred seven-point average with a low/high band (L172-178, L242-244). The value axis is an HTML gutter on the right (L426-428, css L6), the date axis HTML labels under the plot (L429-431); ticks from `niceTop` (four rows or fewer, L77-81) and calendar ticks (L84-111). Tooltip is one HTML bubble placed beside the nearest point and kept inside the plot (L289-301).

**Dependencies:** npm: `motion`. Both in apps/web/package.json; nothing new. Registry: `arc-motion-tokens`.

**Accessibility:** The plot is `role="group"` with `aria-roledescription="chart"`, focusable, and its name tells the reader to use arrows (L388). Plot keys: Left/Right step points, PageUp/PageDown jump an eighth, Home/End, Escape clears (L304-312). The window and both handles are `role="slider"` with `aria-valuetext` dates (L443-445); keys move by a point (Shift x10), `+`/`-` zoom, `0` or Escape reset (L349-366). Readings are announced in a polite live region (L449); a visually hidden summary (L450) and a hidden data table of the points in the current window (L451-455) give screen-reader access to values. The tooltip is `aria-hidden` (L411). Event markers react to pointer hover only (L406-407); a keyboard user meets an event only when the crosshair lands within half a day of it (L283) or in the hidden table. Reduced motion: `useReducedMotionSafe` (L141-144) skips the glide (L197), the axis spring (L229), the draw-in (L265) and the tooltip spring (L299); CSS drops transitions (css L67-69). Focus: `.plot`, `.window` and `.handle` set `outline: none` (css L7, L58, L60) and rely on Arc foundation's global `:focus-visible` rule, which Calevate's globals.css does not have, so as copied these focus targets show no ring. No forced-colors handling.

**Mobile:** Plot and strip keep `touch-action: pan-y` (css L7, L47), so vertical page scroll survives and a horizontal drag reads values. Touch press shows the tooltip and lift hides it (L389-390). Handles are 28 x 44 px (css L60), matching the docs. Event markers are 24 px (css L22-24). At 320 px the plot is the width minus a fixed 44 px gutter (css L6); date ticks need 76 px each (L85), so about three labels fit; the tooltip caps at `min(220px, 100%)` (css L31).

**Issues found in the code:**
- Dates are UTC throughout: tick labels use fixed `en-US` UTC formatters (L66-71) that `formatTick`/`formatDate` cannot replace (`timeTicks` L84-111, `shortDate` in the window text L372, slider value text L444-445, the hidden table L454). A Calevate IST day passed as its instant (IST midnight = 18:30 UTC the day before) is labelled one day early. The only workaround is to encode each IST date as `Date.UTC(y, m, d)`. D-709 conflict.
- Numbers default to `en-US` (L64-65): compact "12K" rather than Indian grouping.
- `value: number` (L11): a money series (Calevate sends decimal strings) has to be converted to floats before it can be drawn, and `formatValue` gets the float back, not the original string (hard rule 7).
- The tooltip's "% vs a week earlier" compares with the point seven indexes back (L370-371), so it is only right for gap-free daily data.
- Hard-coded English: "Use left and right arrows to read values." (L388), "seven day average" (L419), "vs a week earlier" (L420), "Window start"/"Window end" and " window" (L443-445), " to " and "Showing" (L372, L384), table headers "Date"/"Event" (L453), "No data yet" (L161).
- Colours: `--series-1` for line, area, band and overview (css L11-14, L52-53) and `--series-2` for events (css L21, L25, L37, L54) are Arc tokens. Calevate has no `--series-*`; mapping `--series-1` to `--brand` (#16a05d, 3.38:1 on white, passes the 3:1 graphic floor) works. There is no second Calevate chart hue for events: `--chart-warn` #fbbf24 is 1.67:1 on white and failed the dataviz validator's lightness and contrast checks. Also uses `--surface-raised`, `--shadow-floating`, `--border-strong`, `--text-xs`, which Calevate does not define.
- Only an empty state; no loading or error state.
- Decorative motion: the line draws in from the left on first view (L260-269, 0.9 s, L62), and the tooltip trails on a spring (L285-286). The value-axis spring (L221-231) explains a rescale and can stay.
- The hidden table renders every point in the window (L454); a full multi-year daily series is hundreds of rows in the DOM.

**Overlaps in Calevate:** none. `billing/SpendChart.tsx` and `DailyCalls.tsx` are fixed-window bar charts, not a zoomable series.

**Where in Calevate:** Founder's note: leads page and campaigns page. Neither screen has a time series. Leads data comes from `useLeadsUnderLens`, `useLeadFacets`, `useLeadTimeline`, `useSavedViews` and friends in `lib/api/leads.ts`; `LeadListOut` holds `items`, `total`, `status_counts_matching_search` and column metadata, with no per-day counts. Campaigns: `CampaignResults.tsx` reads `CampaignResultsOut` (totals: `calls`, `connected_calls`, `pickup_rate`, `outcomes`, `sentiment`, `recent_leads`, `credits_spent_inr`) and `campaignProgress.ts` reads `ProgressOut` (contact status counts, `launched_at`, `next_retry_at`, `retries_waiting`); neither holds a dated series. The per-day series the API does serve: `DashboardDayOut` (`daily_7d`, 7 days, dashboard `app/c/[slug]`), `SpendSeriesOut.days` (`billing/SpendChart.tsx`, 7/30/90 days, max 92, decimal strings, `timezone: "Asia/Kolkata"`), and `DayReplyTimes` (admin `ops/reply-times`). None is long or dense enough to need a brush (the default `minSpan` is already 7 days).

**Verdict: SKIP**: no screen the founder named has a series for it to draw, and the UTC-only axis labels would mis-date IST buckets. It becomes worth taking only if a per-day leads or calls endpoint is built; that is a product decision first.

**Source:** `docs/design/uiarc/registry/brush-chart/`

---

### sparkline
**What it does:** A small line chart with a caption (label, headline value, change). The line can be scrubbed by pointer or keyboard to read past points.

**Exports / API:** `Sparkline`

| Prop | Type | Default | Notes |
|---|---|---|---|
| data | `number[]` | required | fewer than 2 points is padded (L139) |
| label | `string` | required | |
| value | `string` | none | headline; shown only when set |
| change | `string` | none | the aside text when not scrubbing |
| tone | `"accent" \| "success" \| "warning" \| "danger"` | `"accent"` | colours line, fill and aside |
| width | `number` | `160` | sets the aspect ratio only; the drawn width is measured (L176-182) |
| height | `number` | `52` | as above |
| labels | `string[]` | none | one per point, e.g. a date |
| formatValue | `(value: number, index: number) => string` | `en-US` grouping (L30) | scrubbed headline |
| area | `boolean` | `true` | tinted fill under the line |
| interactive | `boolean` | `true` | pointer and keyboard scrubbing |

Other exports: type `SparklineProps`; default export.

**How it draws:** One SVG in its own pixel space; a monotone cubic curve sampled densely (L89-105) so it never swings past the data, polyline plus a filled path, end dot drawn as a zero-length round-capped stroke (L254). There is no axis, gridline or min/max label; the y range is the data's own min to max (L90-91). Scrubbing dims the line after the cursor (L250) and swaps the caption to the point's value and label (L215-217).

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** The plot becomes `role="slider"` when interactive, with `aria-valuetext` "<label or Point n of m>: <value>" (L227-228). Keys: Left/Down back, Right/Up forward, PageUp/PageDown by a sixth, Home/End, Escape (L219-226). The figure's `aria-label` carries label, value and change (L143, L234). The SVG is `aria-hidden` (L241). Reduced motion: draw shows at once (L188), morph and cursor jump (L198, L208), text roll fades (L68); CSS drops transitions (css L26). Focus: `.plot` sets `outline: none` (css L14) and relies on Arc's global focus rule, absent in Calevate. No forced-colors handling.

**Mobile:** `touch-action: pan-y` on the interactive plot (css L15); a touch drag scrubs and lift returns to the latest value (L231). The SVG width follows the container and height scales with it (L179): at 288 px wide the default ratio gives a 94 px tall plot. The label truncates (css L1); the headline and aside do not wrap.

**Issues found in the code:**
- Empty data draws a flat line at 0 with no message (L139); there is no empty, loading or error state.
- `en-US` grouping by default (L30).
- Hard-coded English: ", explore values" (L228), "Latest" and "Point n of m" (L228), "n of m" in the aside (L217).
- Decorative motion: every caption change rolls per character with a blur (`rise` L27, `Roll` L46-81), the line draws in over 0.84 s on first view (L32, L186-192), and the end dot springs in (L254).
- Tones use status colours (css L2: `--accent`, `--success`, `--warning`, `--danger`) for a trend line, so "warning" and "danger" read as alerts. In Calevate `accent` maps to `--brand`.
- `amountIn` parses the caption to decide the roll direction (L29); an INR string like "₹1,20,000.50" parses, but the direction is cosmetic only.

**Overlaps in Calevate:** none. `components/console/metric.tsx` (`Metric`, `MetricRow`) and `ui.tsx` `StatTile` show a value with a hint but no trend line.

**Where in Calevate:** Beside dashboard tiles in `app/c/[slug]` (`DashboardScreen.tsx`) from `daily_7d` totals; beside the spend headline in `app/c/[slug]/billing` from `SpendSeriesOut.days` (draw from the converted numbers, keep `value` as `formatINR` of the decimal string); admin `app/admin/health` has only `calls_7d` vs `calls_prev_7d`, which is two numbers, not a series.

**Verdict: ADAPT**: the curve, the scrub slider and the token use are sound. Before use: drop the blur roll and the draw-in, map `tone` to Calevate tokens (`--brand`, `--chart-*`), switch to `en-IN`, take the English strings as props, add an empty state, and add a focus ring.

**Source:** `docs/design/uiarc/registry/sparkline/`

---

### gauge
**What it does:** A 270-degree ring meter that fills to `value` between `min` and `max`, shows the percentage in the centre, and optionally names the band the value falls in.

**Exports / API:** `Gauge`

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `number` | required | clamped into range |
| min | `number` | `0` | |
| max | `number` | `100` | `max <= min` becomes `min + 1` (L36) |
| label | `string` | required | caption and meter name |
| detail | `string` | none | second caption line |
| tone | `"accent" \| "success" \| "warning" \| "danger"` | `"accent"` | used when no threshold matches |
| thresholds | `GaugeThreshold[]` (`{ from, tone, label }`) | none | highest band reached sets tone and status text |

Other exports: types `GaugeThreshold`, `GaugeProps`; default export.

**How it draws:** An SVG arc path rebuilt from a motion value each frame (L27-33, L51), over a faint track of the same colour (css L7-9). The centre readout is HTML: digits plus a fixed "%" (L98) and the band label (L99).

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** `role="meter"` with `aria-valuemin/max/now` and `aria-valuetext` "<n>%, <band>" (L95). The readout and SVG are `aria-hidden` (L96-97). Not focusable and has no keyboard model, correctly so for a read-only meter. The figure also carries an `aria-label` (L94) that repeats the meter's name and value, so some screen readers announce it twice. Band meaning is named in text, not colour alone (L99). Reduced motion lands at once (L61) and swaps text with a fade (L23); CSS drops transitions (css L22). No forced-colors handling.

**Mobile:** Ring is `min(100%, 176px)` wide with fixed aspect ratio (css L5), so it shrinks in a narrow column. Nothing to tap.

**Issues found in the code:**
- Display only: no `onChange`, no input, no focus. It cannot collect a rating.
- The readout is always a percentage of the range (L37-38, L98); it cannot say "8 of 10".
- Decorative motion: the ring fills and the number counts up when scrolled into view (L59-66), and caption text swaps with a blur rise (L14, L21-24).
- The band label is blank until the first fill finishes (L99).
- Colours are Arc `--accent/--success/--warning/--danger` (css L2); Calevate has `--brand`, `--warn`, `--danger`.

**Overlaps in Calevate:** `components/illustration/trialMeter.tsx` (`TrialMeter`, a decorative `aria-hidden` ring of trial left, 1 caller: `app/c/[slug]/TrialBanner.tsx`). Different job (decorative glyph beside text), so no replacement is called for. `StatTile`/`Metric` cover plain figures.

**Where in Calevate:** Founder's note: "rate our agent or script". As written, the gauge can only show a score, not let a person give one. No rating input exists anywhere in `apps/web/src/app`. The scores the API serves: an agent test run's `TestScoreOut` (`passed`, `judged`, `total`, `unreliable`, `setting`, `check`, `ours`) used by `app/c/[slug]/agents/[agentId]/test/` (`TestResults.tsx` groups failing tests by what fixes them, `testCopy.ts` reads `score.passed`/`score.judged`); and `app/c/[slug]/quality`, whose screen states its headline is the defect count, not the pass rate (`QualityScreen.tsx` L38-40, `QualityReport.tsx` L15-17). A percentage ring would put the pass rate back as the headline on the quality screen.

**Verdict: SKIP**: it cannot collect a rating, and for the scores that exist "8 of 10 tests right" in words is clearer than a percent ring with a count-up. A rating the user sets needs an input control (radio group or segmented control), not a meter.

**Source:** `docs/design/uiarc/registry/gauge/`

---

### activity-heatmap
**What it does:** A contribution-style calendar, one square per day, weeks as columns, with five tint levels, a total line, a level legend that highlights days, a tooltip, and optional day selection.

**Exports / API:** `ActivityHeatmap`

| Prop | Type | Default | Notes |
|---|---|---|---|
| days | `ActivityDay[]` (`{ date: "YYYY-MM-DD"; count: number }`) | required | gaps count as zero |
| label | `string` | required | grid name |
| period | `string` | required | ends the summary "N contributions in {period}" |
| unit | `{ one: string; other: string }` | `contribution(s)` (L87) | noun |
| thresholds | `[number, number, number]` | quarters of busiest day (L70) | |
| weekStartsOn | `0 \| 1` | `0` (Sunday) | |
| selectedDate | `string \| null` | `null` | |
| onSelectDate | `(date: string) => void` | none | enables `aria-selected` |
| actions | `ReactNode` | none | beside the summary |
| locale | `string` | `"en-US"` | |
| className | `string` | none | |

Other exports: types `ActivityDay`, `ActivityHeatmapProps`; default export.

**How it draws:** HTML spans in CSS grid rows, sized by a container-query `clamp(9px, ..., 15px)` cell (css L17); level colours are `color-mix` tints of the accent over a neutral (css L2), which is a single-hue sequential ramp. Month labels above, alternate weekday labels pinned left (L343-347, css L22). One shared tooltip bubble glides between cells (L238-261).

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** `role="grid"` (`aria-readonly`, described by the legend sentence) with seven `role="row"` rows and `role="gridcell"` days carrying count and long date in `aria-label` (L329-341, L370). Roving tabindex (L197, L337). Keys: Up/Down a day, Left/Right a week, Home/End, Enter/Space select, Escape hides the tooltip (L289-303). The legend is a group of `aria-pressed` toggle buttons with its own roving tabindex and arrow keys (L388-393, L305-312). The total is in a `role="status"` span (L358); the highlight caption is polite (L382). Tooltip `aria-hidden` (L399). Dates are parsed and formatted as UTC calendar days (L60, L74, L172-174); for day strings that is correct, and no "today" is computed from the browser clock. Reduced motion: hydration-safe hook (L91-95), fades only (css L78-83). Focus relies on Arc's global rule (`.grid` `outline: none`, css L25). No forced-colors handling; with colours forced every level would look the same.

**Mobile:** Cells are 9-15 px and legend swatches 15 x 20 px (css L17, L58), far under 44 px. A year at the 9 px floor needs about 670 px, so at 320 px the grid scrolls sideways inside its own scroller, which starts at the latest weeks via `direction: rtl` (css L16). The scroller itself is not focusable. A tap selects and the tooltip lingers 2.4 s (L278, L339). Below a 440 px container the caption shortens (css L54).

**Issues found in the code:**
- Empty `days` falls back to a hard-coded start of `2025-01-01` with length 0 (L65): an empty grid, no message. No loading or error state.
- Hard-coded English: "contribution(s)" (L87), "No ..." (L219, L338), range text "1 to", "or more", "–", "+" (L222-223), "day/days", "with" (L224-225), "in" (L351, L357), "Less"/"More" (L387, L395), "Darker squares mean more ..." (L381), "Highlight days with ..."/"Highlight days by level" (L388-390).
- Decorative motion: diagonal wave reveal (L182-192, css L37-39), digit-by-digit blur roll of the total (L105-144), blur rise on the period and caption (L147-155), tooltip glide and width morph (L248-250).
- The tooltip bubble uses `--background` (css L68), which Calevate does not define.
- `weekStartsOn` defaults to Sunday; Calevate has no stated week-start rule (not determined from the source).

**Overlaps in Calevate:** none. `performance/PerformanceCharts.tsx` `HourHistogram` is a 24-bucket hour-of-day chart, not a calendar.

**Where in Calevate:** Founder's note: "analytics". The analytics data does not have the shape this needs. `app/c/[slug]/performance` reads `PerformanceOut` (`days`, `funnel`, `outcomes`, `busiest_hours_ist` as 24 numbers, rates), which is aggregates over a window with no per-day counts. The longest per-day series served are `SpendSeriesOut.days` (max 92 days of decimal strings, `billing`) and `daily_7d` (7 days, dashboard). Admin `health` (`ClientHealthOut`: `calls_7d`, `calls_prev_7d`) and `spend` (`FleetSpendOut`: monthly totals per tenant) are not daily either.

**Verdict: SKIP**: no endpoint gives months of daily counts. Its targets are 9-15 px on a phone-first product, and its decoration (wave, rolls) is the kind REDESIGN-2 rules out.

**Source:** `docs/design/uiarc/registry/activity-heatmap/`

---

### ridgeline
**What it does:** One smoothed density curve per series, stacked and overlapping, shaded by median; hovering or arrowing lifts a ridge and reads its median, middle half, range and the share at or below a value.

**Exports / API:** `Ridgeline`

| Prop | Type | Default | Notes |
|---|---|---|---|
| series | `RidgelineSeries[]` (`{ id, label, values: number[] }`) | required | raw observations |
| label | `string` | required | |
| unit | `string` | `""` | appended with no space (L120) |
| formatValue | `(value: number) => string` | `en-US`, 1 decimal, true minus (L54, L120) | |
| domain | `[number, number]` | data plus room | |
| overlap | `number` | `2.4` | rows a ridge may rise |
| rowHeight | `number` | `30` | px |
| bandwidth | `number` | Silverman per series (L68-74) | |
| tint | `boolean` | `true` | shade by median, show scale |
| active | `string \| null` | none | controlled lifted id |
| defaultActive | `string \| null` | `null` | |
| onActiveChange | `(id: string \| null) => void` | none | |
| emptyLabel | `string` | `"No data yet"` | |
| ref | `Ref<HTMLElement>` | none | |
| className | `string` | none | |

Other exports: types `RidgelineSeries`, `RidgelineProps`; default export.

**How it draws:** A Gaussian kernel density per series on 96 samples (L80-90), normalised to the tallest peak (L143-144); SVG paths are written imperatively each frame outside React (L166-196). The lifted ridge is a copy drawn on top with its quartile band and median (L319-324). HTML tick labels along the bottom (L307-311), row labels in a left gutter (L326-328). Single hue: `--series-1` mixed with `--surface` by median (L299-300).

**Dependencies:** npm: `motion` (present). Registry: `arc-motion-tokens`.

**Accessibility:** Plot is `role="group"`, `aria-roledescription="ridgeline chart"`, focusable, with key help in its name (L304-305). Keys: Up/Down choose a ridge, Left/Right move the reading by one tick step, Home/End, Escape (L283-295). The lifted ridge's stats are read in a polite live region (L346). A hidden table gives every series' median, quartiles, min, max and count (L347-351). Tooltip `aria-hidden` (L330). Reduced motion draws final shapes at once (L101-104, L212; css L55-58). Focus relies on Arc's global rule (`.plot` `outline: none`, css L5). No forced-colors handling.

**Mobile:** `touch-action: pan-y` (css L5); a tap lifts a ridge (L306). Leaving is only cleared for a mouse (L306), so after a tap the tooltip stays until blur. Under 420 px the label gutter drops to 36 px (L153-154), leaving row labels 26 px wide (L327), so any label longer than about three characters is truncated (css L33). Tooltip is at least 170 px (css L38).

**Issues found in the code:**
- Row labels are unreadable at phone width (L153-154, L327).
- `en-US` numbers (L54-55); the hidden table's count is unformatted (L350); `unit` is appended with no space (L120).
- Hard-coded English: "Median", "Middle half", "Range", "at or below" (L333-336, L341), the key help (L305), the screen-reader sentence (L301), table headers (L349), "No data yet".
- Decorative motion: ridges roll in as a wave (L214-224) and the lifted ridge floats up 6 px (css L17-18).
- `--series-1`, `--surface-raised`, `--shadow-floating`, `--border-subtle` are Arc tokens.

**Overlaps in Calevate:** none.

**Where in Calevate:** Founder's note: "analytics". It needs raw observations per group, and none of the analytics endpoints serve them: `PerformanceOut` (`app/c/[slug]/performance/PerformanceCharts.tsx`) is counts and rates; `ClientHealthOut` (`app/admin/health`) is 7-day totals and signals; `FleetSpendOut` (`app/admin/spend`) is monthly money per tenant. The nearest data, `DayReplyTimes` on `app/admin/ops/reply-times`, is per-day percentiles (`reply_typical_ms`, `reply_slow_ms`, `reply_worst_ms`), not raw values, and that screen is admin-only.

**Verdict: SKIP**: there is no distribution data to feed it. It is also an expert chart for an SMB owner on a phone, and its labels collapse below 420 px.

**Source:** `docs/design/uiarc/registry/ridgeline/`

---

### sortable-data-table
**What it does:** A real `<table>` with sortable headers, optional row selection (checkbox column, row click, shift-range, count line with Clear selection), spring row reordering, and a stacked card layout under 620 px.

**Exports / API:** `SortableDataTable`

| Prop | Type | Default | Notes |
|---|---|---|---|
| rows | `T[]` (`T extends Record<string, unknown>`) | required | |
| columns | `DataColumn<T>[]` (`{ key, label, sortable?, render?, numeric?, width? }`) | required | sort reads `row[key]` directly |
| rowKey | `keyof T \| ((row: T) => string)` | required | |
| caption | `string` | `"Data table"` | visually hidden |
| emptyMessage | `string` | `"No rows to show"` | |
| defaultSort | `SortState` (`{ key, direction }`) | none | uncontrolled only |
| onSortChange | `(sort: SortState) => void` | none | |
| selectable | `boolean` | `false` | |
| selectedKeys | `string[]` | none | controlled |
| defaultSelectedKeys | `string[]` | none | |
| onSelectionChange | `(keys: string[]) => void` | none | |
| itemName | `{ one: string; other: string }` | `row/rows` | count noun |

Other exports: types `SortDirection`, `SortState`, `DataColumn`, `SortableDataTableProps`; default export. `SortDirection`, `SortState` and `DataColumn` share names, but not shapes, with `components/console/dataTable.tsx`.

**Dependencies:** npm: `lucide-react`, `motion` (both present). Registry: `arc-motion-tokens`.

**Accessibility:** Explicit table roles so semantics survive the phone layout (L272-297). `aria-sort` on sortable headers (L283), sort buttons labelled with the current direction (L284), and a status line "Sorted by ..." (L213, L308). Keys: Left/Right/Home/End across header controls, Up/Down/Home/End down the row checkboxes, Escape clears selection (L246-267). Hidden native checkboxes with the focus outline drawn on the visible box (css L37, L43); indeterminate select-all (L113). Reduced motion turns off row layout animation (L293) and transitions (css L113-116).

**Mobile:** Under 620 px rows fold into two-line cards and the header becomes a horizontally scrolling strip of sort buttons (css L68-106). Those buttons are 32 px tall (css L84) and Clear selection is 30 px (css L53), under 44 px. In the folded layout non-primary cells lose their column names: `data-label` is set (L295) but no CSS reads it, so values appear without labels. Above 620 px the table has `min-width: 560px` in an `overflow-x: auto` scroller (css L3, L5) that is not focusable, so a keyboard user cannot scroll it.

**Issues found in the code:**
- No decimal sort: non-number values fall to an `Intl.Collator({ numeric: true })` (L42, L143), which compares digit runs as integers, so "9.5" sorts before "9.25" ascending. Calevate money is decimal strings (hard rule 7), and `DataTable` has a `decimal` kind for exactly this.
- Numeric alignment is detected only for JS numbers (L148), so a decimal-string money column is left-aligned unless `numeric: true` is passed.
- The sort cycle is asc then desc then asc (L209-214), with no way back to the server's order.
- The sort is not controllable (no `sort` prop); the selection label uses the first column's raw value (L294).
- Hard-coded English: defaults at L126, "Sorted by ... ascending/descending" (L213), "selected", "Selection cleared", "of" (L204, L220), "Select all rows" (L279), "Sort by", "currently" (L284), "Select" (L294), "Clear selection" (L306).
- Decorative motion: blur rise on the count (L50-86), blur and scale on the sort arrow (L105) and the Clear button (L306). The row reorder spring (L293) explains the sort and is fine.
- No loading or error state.

**Overlaps in Calevate:** `components/console/dataTable.tsx` (`DataTable`), imported by 26 files: admin `ops/alerts`, `ops/dnc`, `ops/maintenance`, `ops/reply-times`, `spend`, `tenants/[tenantId]/activity`, `commercials`, `credits`, `spend`; client `billing/SpendChart.tsx`, `billing/StatementsView.tsx`, `callbacks`, `calls/callColumns.tsx`, `calls/CallsScreen.tsx`, `campaigns/CampaignsListScreen.tsx`, `campaigns/ContactResults.tsx`, `do-not-call/SuppressedList.tsx`, `integrations/EndpointList.tsx`, `LatestCalls.tsx`, `lead-sources/DeliveryLog.tsx`, `lead-sources/SourcesList.tsx`, `leads/LeadTable.tsx`, `quality/QualityReport.tsx`, `settings/team/teamRows.tsx`, `settings/team/TeamScreen.tsx`, `components/copilot/workspace/Routines.tsx`. `DataTable` has `sort.kind` `decimal`/`time`/`number`/`text` (L27, L75-87), asc → desc → original (L106-112), controlled sort, `partialNote` for paged data (L200), `hideBelow` and `pin` columns, `ScrollRegion` (L296), live arrivals with `NewItemsPill`, value flash, and a `touch:min-h-11` sort button (L322). **DataTable wins.** Replacing it would mean moving 26 importers to a component that sorts money wrongly. Row selection in Calevate already lives with the leads screen (`leads/BulkActionBar.tsx`).

**Where in Calevate:** none (every table route above already uses `DataTable`).

**Verdict: SKIP**: `DataTable` already does this, sorts money correctly, and has 26 callers. Arc's version adds only selection and a card fold, and the card fold drops the column names.

**Source:** `docs/design/uiarc/registry/sortable-data-table/`

---

### filter-toolbar
**What it does:** A row of removable filter chips with "Clear all" and a "No filters applied" note, plus an optional Add filter button that grows into a two-step menu (pick a field, then one value).

**Exports / API:** `FilterToolbar`

| Prop | Type | Default | Notes |
|---|---|---|---|
| filters | `FilterChip[]` (`{ id, label, value? }`) | required | applied filters |
| onRemove | `(id: string) => void` | required | |
| onClearAll | `() => void` | none | the button renders even when unset (L454) |
| children | `ReactNode` | none | extra actions |
| label | `string` | `"Active filters"` | group name |
| addFilter | `{ fields: FilterField[]; onAdd: (filter, field) => void; label?: string; align?: "start" \| "end" }` | none | mounts `FilterMenu` |

Other exports: `FilterMenu` (props `fields`, `onSelect`, `active` default `[]`, `label` default `"Add filter"`, `align` default `"end"`, L14-23, L217); types `FilterChip`, `FilterOption` (`{ value, label?, hint?, icon? }`), `FilterField` (`{ id, label, icon?, options }`), `FilterMenuProps`, `FilterToolbarProps`; default export. `FilterChip` shares its name with `ui.tsx` `FilterChip`.

**Dependencies:** npm: `lucide-react`, `motion` (both present). Registry: `arc-motion-tokens`.

**Accessibility:** Toolbar is `role="group"` (L438). Each chip's remove button names the filter (L442), and focus moves to the neighbouring chip or the trigger after removal (L411-418). Changes are announced in a status line (L126-133, L457). Trigger: `aria-haspopup="dialog"`, `aria-expanded`, `aria-controls`, and Up/Down open it (L362-364). Panel is `role="dialog"` (L370) containing a `role="menu"` of `menuitem`/`menuitemradio` with roving tabindex, arrows, Home/End, typeahead, Right to drill in, Left to go back (L139-197). Escape closes and returns focus (L264-283, L360); it also closes on blur out and on outside pointer press (L308-322, L361). There is no focus trap, so it behaves as a non-modal popover. Reduced motion jumps the morph and uses fades (L258, L273, css L70).

**Mobile:** Under 520 px the toolbar stacks into a column (css L69). The panel is `min(16rem, 100vw - space-8)` wide (css L41) and flips or shifts within the nearest clipping ancestor (L203-213, L246-252). It renders in place with no portal, so it is clipped by any `overflow` ancestor (the code says so, L215-216). Sizes: chip remove 24 px (css L15), trigger, chips, menu items and Clear all 36 px (`--control-height-sm`, css L8, L19, L28, L55), back button 28 px (css L46). All are under 44 px.

**Issues found in the code:**
- One value per field: the chip id is the field id and a new pick replaces the old (L16, L341); values are `menuitemradio` (L188). There is no multi-select.
- The chip's `value` is the option's display label, not its `value` (L341), and the checked state compares labels (L349). A caller has to map labels back to API values.
- "Clear all" shows with `onClearAll` unset and does nothing (L454).
- Hard-coded English: "Add filter" (L217), "Active filters" (L398), "No filters applied" (L446), "Clear all" (L454), "Back to fields" (L374), "Remove ..." (L442), "Added", "Removed", "changed to", "any", "All filters cleared" (L126-133).
- Decorative motion: the trigger morphs into the panel on a spring with a blur and scale face-out (L229-283), text swaps with a blur rise (L42-47, L50-73), chips enter with blur and scale (L429-434), and wrapped chips glide (L95-124).
- No loading or error state for options; no counts unless passed as `hint`.

**Overlaps in Calevate:** The leads filters, all read: `leads/LeadsToolbar.tsx` (search, the "What did they ask for?" question form, Columns, Export, and a phone-only "Filters" button that folds the panel and counts filters in use), `leads/MoreFilters.tsx` (a `Disclosure` titled "More filters · N in use" holding the `Assigned to me` `FilterChip`, `FacetPanel` and `SavedViewBar`), `leads/FacetPanel.tsx` (per captured field, a `<fieldset>` with a `<legend>` and checkbox chips; several values per field; each value shows the server's count over the other filters; "Clear these filters"; skeleton and `ProblemNotice` states), `leads/SavedViewBar.tsx` (a select of saved views plus save and delete), and `ui.tsx` `FilterChip` (an `aria-pressed` toggle with `touch:min-h-11`, imported by 6 files: `ConfigSearch.tsx`, `WalletHistory.tsx`, `BookingSetup.tsx`, `CallsScreen.tsx`, `LeadPicker.tsx`, `MoreFilters.tsx`). Arc's model (one value per field, label as value, no counts, a 16 rem in-place menu) is narrower than `FacetPanel`. **Calevate's components win.** Replacing them would mean rebuilding multi-select, counts, the retired-value marker and the phone fold inside Arc's menu.

**Where in Calevate:** none. The leads screen (`app/c/[slug]/leads`) and calls screen (`app/c/[slug]/calls`) already have their filters.

**Verdict: SKIP**: single-value-per-field and display-label values do not fit the multi-value, counted facets of the leads screen. Its menu is a decorative morph with 24-36 px targets.

**Source:** `docs/design/uiarc/registry/filter-toolbar/`

---

### json-viewer
**What it does:** A collapsible JSON tree with values coloured by type, a search that highlights matches and opens their branches, paging for long arrays and objects, expand all and collapse all, copy value and copy path per row, and a bar showing the current path.

**Exports / API:** `JsonViewer` (`forwardRef<HTMLDivElement>`, L206)

| Prop | Type | Default | Notes |
|---|---|---|---|
| data | `unknown` | required | already-parsed value; no string parsing |
| rootName | `string` | `"root"` | |
| defaultExpandDepth | `number` | `1` | |
| expanded | `string[]` | none | controlled open paths |
| defaultExpanded | `string[]` | none | |
| onExpandedChange | `(paths: string[]) => void` | none | |
| searchable | `boolean` | `true` | |
| query | `string` | none | controlled |
| defaultQuery | `string` | `""` | |
| onQueryChange | `(query: string) => void` | none | |
| pageSize | `number` | `50` | |
| copyable | `boolean` | `true` | |
| onCopy | `(detail: JsonViewerCopyDetail) => void` | none | receives the copied text |
| onSelect | `(detail: { path, value, type }) => void` | none | receives the row's value |
| showPath | `boolean` | `true` | |
| maxHeight | `number \| string` | `420` | |
| label | `string` | `"JSON"` | tree name |
| className | `string` | none | |

Other exports: types `JsonValueType`, `JsonViewerCopyDetail`, `JsonViewerProps`; default export.

**Dependencies:** npm: `lucide-react`, `motion` (both present). Registry: `arc-motion-tokens`.

**Accessibility:** Follows the WAI-ARIA tree pattern: `role="tree"` (L471), `role="treeitem"` with `aria-level`, `aria-posinset`, `aria-setsize`, `aria-expanded`, `aria-selected`, and roving tabindex (L479-481). Keys: Up/Down, Home/End, Right opens or enters, Left closes or goes to the parent, Enter/Space toggles or shows more, `/` jumps to search, Ctrl/Cmd+C copies the value and Shift adds the path (L405-439). In search, Enter and Shift+Enter step through matches, Escape clears, Down enters the tree (L399-403); the match count is live (L459) and copies are announced (L366-377, L526). The row copy buttons sit inside the treeitem with `tabIndex={-1}` (L187), so the keyboard reaches them only through Ctrl/Cmd+C or the path bar's copy button (L524). Each treeitem's `aria-label` contains the primitive value (L445-449). Reduced motion, or more than 400 visible rows, makes row changes instant (L443); scroll jumps (L307). CSS drops transitions (css L90).

**Mobile:** Rows are 30 px (css L24); toolbar buttons 34 px, in-search buttons 26 px, row copy actions 26 px, path copy 30 px (css L14, L17, L57, L68). All under 44 px. Under 420 px the indent narrows and keys cap at 40 % (css L84-88). Rows never wrap: long strings are cut with an ellipsis and the full text is only in a `title` for strings over 40 characters (L506). On a phone `title` is unreachable, so the full value can only be copied, not read.

**Issues found in the code:**
- No redaction of its own: it renders, searches, puts into `aria-label`, and hands to `onSelect` and `onCopy` whatever `data` holds (L291, L372, L445-449). Hard rules 5/6 have to be met before the data reaches it (the API sends only what this reader may see) and by the caller, which must never log `onSelect`/`onCopy` payloads.
- `copyable` defaults to `true`. On a payload holding a customer's details, copy-to-clipboard is one tap away for every row.
- Takes parsed data only. A truncated body (`DeliveryLog`'s `payload.data.truncated`) will not parse, so the caller needs a `<pre>` fallback.
- Syntax colours reuse status tokens: strings `--success`, numbers `--accent`, booleans `--warning` (css L40-42).
- Hard-coded English: "Search keys and values", "Search JSON" (L455), "Previous match"/"Next match" (L460-461), "Expand all"/"Collapse all" (L466-467), "Copy value"/"Copy path"/"Copied"/"Copy failed" (L187, L510-511), "Show N more", "hidden" (L447, L493-494), "item(s)/key(s)" (L106), "page" (L523), "JSON" (L209).
- Decorative motion: the copy glyph swaps with a blur and scale (L190-192). The row unfold and the moving highlight (L483, L490) explain state.
- No empty, loading or error state (the caller owns those).

**Overlaps in Calevate:** none as a component. Raw payloads are shown as plain `<pre>` in two places: `app/c/[slug]/integrations/DeliveryLog.tsx` L199-207 (the delivered body as a string, possibly truncated, shown only to a `calls:read_raw` reader with an audit row, in a focusable `role="region"`) and `app/c/[slug]/agents/actions/ToolRow.tsx` L283-285 (`JSON.stringify(test.data.payload, null, 2)` inside a `ScrollRegion`). `agents/[agentId]/script/ScriptToolbar.tsx` L174 is prose instructions, not JSON. No admin screen shows a JSON payload (grep of `app/admin` for `<pre` and pretty-printed `JSON.stringify` found none).

**Where in Calevate:** `app/c/[slug]/agents/actions` (tool test result, `ToolRow.tsx`) and `app/c/[slug]/integrations` (`DeliveryLog.tsx`, only when the body parses and is not truncated, otherwise keep the `<pre>`).

**Verdict: ADAPT**: a correct APG tree that beats a `<pre>` for nested tool and webhook payloads. Before use: default `copyable` to false on customer-data payloads, keep the server-side gate and audit as the only door to raw bodies, add the `<pre>` fallback, raise touch targets to 44 px, map the type colours to non-status tokens, take strings as props, and add a focus ring.

**Source:** `docs/design/uiarc/registry/json-viewer/`

---

### timeline
**What it does:** A newest-first activity feed grouped by day under sticky day headings, with relative times for today, expandable detail rows, and new events sliding in at the top with an announcement.

**Exports / API:** `Timeline`

| Prop | Type | Default | Notes |
|---|---|---|---|
| events | `TimelineEvent[]` (`{ id, at: string \| number, actor?, title, meta?, detail?: ReactNode, avatar?, icon?, tone?: "neutral" \| "success" \| "danger" }`) | required | any order |
| now | `number` | required | epoch ms; caller ticks it |
| label | `string` | required | region name |
| timeZone | `string` | `"UTC"` | day groups and clock times |
| locale | `string` | `"en-US"` | |
| maxHeight | `number \| string` | none | makes the feed scroll |
| scrollToNew | `boolean` | `true` | |
| defaultExpanded | `string[]` | `[]` | |
| headingLevel | `2 \| 3 \| 4 \| 5 \| 6` | `3` | day labels |
| className | `string` | none | |

Other exports: types `TimelineEvent`, `TimelineProps`; default export.

**Dependencies:** npm: `lucide-react`, `motion` (both present). Registry: `arc-motion-tokens`.

**Accessibility:** `role="region"` (L250); each day is a `role="heading"` with `aria-level` (L255) over an `<ol>` (L260). Rows with `detail` are buttons with `aria-expanded`; `aria-controls` is set only while open (L154). Up/Down/Home/End move among expandable rows only (L239-247); rows without detail are plain divs and are not focusable (L141). `<time dateTime>` with the full time in hidden text (L159). New events are announced in a status line (L185, L273). Reduced motion: hydration-safe hook (L68-72), instant or 0.15 s fades (L138-139), shorter feather transition (css L51).

**Mobile:** The trigger is 12 px padding around a 20 px line, about 44 px tall (css L34, L39). Under 420 px padding tightens (css L50); the time column keeps at least 2.75 rem (css L43). With `maxHeight` the scroller has no tabindex (L251, css L6). If no row is expandable, a keyboard user cannot scroll it.

**Issues found in the code:**
- `timeZone` defaults to `"UTC"` (L174), so day groups and clock times are UTC unless the caller passes `"Asia/Kolkata"` (D-709). With that set, `dayKey` (L103-107) and "Today"/"Yesterday" (L211, L218) follow IST from the caller's `now`, not the browser zone.
- The relative-time switch compares the heading text to the English word "Today" (L263), so translating the label breaks it.
- Hard-coded English: "Now", "just now", "m", "h", "minute(s) ago", "hour(s) ago" (L109-115), "Today"/"Yesterday" (L218), "update(s)" (L257-258), "New update:" (L185).
- Decorative motion: on scroll into view each marker pops and the connecting line draws down, staggered (L132-151, L226-233); new content rises with a blur (L152); the day count rolls digit by digit (L94-101).
- No empty, loading or error state and no paging (`events: []` renders an empty region).
- The `avatar` `<img>` takes any URL (L149); not an issue for icon-only events.

**Overlaps in Calevate:** `app/c/[slug]/leads/[leadId]/LeadTimeline.tsx` (1 caller: `LeadDetailScreen.tsx`). It renders an `<ol>` of events with an icon medallion per type, title, detail, call-moment links, the IST stamp via `formatIST`, the actor ("Calevate" or the colleague's name), a count line, `Skeleton`, `ProblemNotice` with retry, `EmptyState`, and `LoadMore` for earlier history. It has no day grouping and no expand-in-place. Under one way per problem, Arc's `Timeline` can replace `LeadTimeline`'s row list (one caller to move), with `LeadTimeline` keeping its states, count line and `LoadMore` around it. Mapping: `title`, `detail` as the expandable body (with `CallMoments`), `icon` from `EVENT_STYLES`, `actor` from `actor_kind`/`actor_name`, `at` from `occurred_at`.

**Where in Calevate:** `app/c/[slug]/leads/[leadId]` (lead history). Possible later fit: `app/admin/tenants/[tenantId]/activity`, which today is a `DataTable`.

**Verdict: ADAPT**: day grouping, expandable rows and the arrival announcement improve the lead history, and the move is one caller. Pass `timeZone="Asia/Kolkata"` and `locale="en-IN"`, take every string as a prop (and stop comparing against "Today"), drop the pop, draw and blur reveal, make the scroller focusable, and keep `LeadTimeline`'s loading, error, empty and Load more around it.

**Source:** `docs/design/uiarc/registry/timeline/`

---

### text-shimmer
**What it does:** Sweeps a soft highlight band across one short status line ("Thinking", "Generating summary") while `active` is true; when it turns false the band glides off and the text settles to solid. A changed label rises in with a blur and the line springs to its new width.

**Exports / API:** `TextShimmer`

| Prop | Type | Default | Notes |
|---|---|---|---|
| children | `string` | required | one short line; a string only, so no inline markup (L29) |
| active | `boolean` | `true` | sweep while work is ongoing; false glides the band off (L66-75) |
| duration | `number` | `1.8` | seconds per sweep; a pause of `duration * .32` between passes (L59) |
| as | `"span" \| "p" \| "div" \| "h2" \| "h3" \| "h4"` | `"span"` | rendered tag |
| className | `string` | — | |
| id | `string` | — | |

Other exports: `TextShimmerProps`, default export `TextShimmer`.

**Dependencies:** npm: `motion`. Registry: `arc-motion-tokens`.

**Accessibility:** sets `aria-busy` on the outer tag while active (L102) and tells the caller to announce completion from its own live region (L25); it has no live region of its own. Reduced motion: `useReducedMotion` read after hydration (L40-42) stops the sweep (L48, L54), turns the label swap into a plain fade (L106-109) and skips the width spring (L87). The sweep also pauses off screen (`useInView`, L43) and in a hidden tab (`usePageInView`, L44). CSS drops the gradient under `forced-colors: active` and where `color-mix` is unsupported (css L8-9); selection stays readable (css L7). Nothing is focusable.

**Mobile:** inline element capped at `max-width: 100%` (css L3-4); while the width springs the label is forced to one line (`white-space: nowrap`, css L6), so a long label on a 320px screen can overflow for the duration of the morph.

**Issues found in the code:**
- Decorative motion beyond the state it explains: the label change animates `y` plus a `blur()` filter (L106-108) and a width spring (L89). REDESIGN-2's calm aesthetic and the emil/no-slop view keep the sweep (it does say "working") but not the blur crossfade.
- The resting colour while active is `color-mix(currentColor 12%, var(--text-muted))` (css L2): an ink line dims to near-muted for the whole operation. Calevate's utility keeps `currentColor` as the base. Contrast of the dimmed base against Calevate surfaces is not determined from the source.
- JS-driven: one `ResizeObserver` (L94-100), a motion value transform rebuilding a 9-stop gradient string per frame (L47), and two effects per instance. Calevate's utility is pure CSS.
- `children: string` only: Calevate callers such as `TestSummary.tsx` interpolate a plural helper into the text, which still works as a string, but any caller passing a fragment would not type-check.

**Overlaps in Calevate:** `apps/web/src/app/globals.css` L548-571: the `text-shimmer` keyframes and `@utility text-shimmer` (gradient `currentColor 35% / --brand-strong 50% / currentColor 65%`, 2.4s linear, painted only under `prefers-reduced-motion: no-preference` and `forced-colors: none`, contrast of the worst frame asserted by `tests/contrastTokens.test.ts` per the comment above it). Used in 20 files (21 including globals.css), e.g. `c/[slug]/calls/[callId]/CallVerdict.tsx`, `billing/TopUp.tsx`, `campaigns/LaunchConfirm.tsx`, `knowledge/TeachBox.tsx`, `components/copilot/CopilotPanel.tsx`. One way per problem: the Calevate utility wins. It is already contrast-tested, needs no JS, and every caller is a one-class `<span>`. Arc's two real advantages (pause off screen; glide-off on finish) do not justify a second shimmer.

**Where in Calevate:** none new. Existing pending labels ("Putting it live…", "Reading your call…", "{assistant} is thinking…") already use the utility.

**Verdict: SKIP** — Calevate's CSS utility does the same job with tested contrast and no runtime cost; Arc's version adds blur and width morphs that the redesign doctrine rejects.

**Source:** `docs/design/uiarc/registry/text-shimmer/`

---

### page-header
**What it does:** A self-contained project page demo: breadcrumbs, title with status badge, description, member avatars, Follow/Share/New-issue actions that fold into a Radix overflow menu when space runs out, Radix tabs with animated counts, and a header that condenses into a compact bar on scroll. All content is hard-coded sample data.

**Exports / API:** `PageHeader` — takes **no props** (L223). docs.md says the same ("No props", "sample data declared at the top of page-header.tsx").

| Prop | Type | Default | Notes |
|---|---|---|---|
| — | — | — | none: title, people, tabs, issues, files and URL are module constants (L25-87) |

Other exports: default export `PageHeader`. Internal, not exported: `OverflowMenu` (L117-141), `OverviewPanel`, `IssuesPanel`, `UpdatesPanel`, `FilesPanel`.

**Dependencies:** npm: `@radix-ui/react-dropdown-menu` (**new**), `@radix-ui/react-tabs` (**new**), `lucide-react`, `motion`. Registry: `arc-motion-tokens`, `animated-counter`, `avatar-group`, `avatar`, `badge`, `button`, `progress`.

**Accessibility:** Radix tabs give `tab`/`tabpanel` roles and arrow keys (L400, L450-475); the overflow menu is a Radix dropdown with `loop` (L129-140), icon trigger labelled "More actions" (L130). Breadcrumb `nav` with `aria-current="page"` (L405-410); the hidden breadcrumb or compact bar is made `inert` when not shown (L405, L412). The compact bar's "back to top" moves focus to the `h2` (`tabIndex={-1}`, L308-311, L435). Completing an issue moves focus to the next row's toggle (L344-358). The visual toast layer is `aria-hidden` and a separate polite `role="status"` mirrors it (L478-486). Reduced motion: `useReducedMotion` swaps every transition for `still`/fade (L92, L103, L106-110, L396), CSS drops transitions (css L158-161). Touch targets: tabs 44px (css L43), issue check button 32x32 (css L74), menu items 36px (css L117), Button `sm` = `--control-height-sm` 36px.

**Mobile:** container queries fold the root crumb, hide labels and the file date (css L131-154), the tab row scrolls sideways with a fade mask (css L41, L137) and keeps the active tab in view (L275-284). The frame has a fixed `height: 640px` (css L2) with its own inner scroller (css L53), and on phones `clamp(560px, calc(100svh - 48px), 760px)` (css L156): a page-in-a-box with a nested scroll, not a page header.

**Issues found in the code:**
- Not a reusable component: no props at all (L223); Calevate would have to rewrite it to get a header out of it.
- Sample data and placeholder hosts: `PROJECT_URL = "https://northline.example/..."` (L25), portraits at `/media/people/*.jpg` (L28-34) that the registry does not ship.
- Decorative motion: blur crossfades on breadcrumb/compact bar/title (`filter: blur(...)`, L396-397, L405, L412, L434), title scale to .62 on condense (L434), panel slide on tab change (L98-102).
- A second toast system inside the block (L245, L268-272, L478-486) beside Calevate's `interior/toaster.tsx`.
- Hard-coded English throughout ("More actions", "Breadcrumb", "Project sections", "Mark {id} done", notices L316-382); dates as English strings ("Sep 19", "Yesterday", L57-86) rather than IST-formatted instants.
- The Radix dropdown and Radix tabs are two new npm packages for behaviour Calevate already has (`console/rowMenu.tsx`, `interior/tabs.tsx`).

**Overlaps in Calevate:** `apps/web/src/components/console/pageHeader.tsx` (`PageHeader`: `title`, `description`, `status`, `actions`, `back`, `headingLevel`, `className`), imported by 72 files under `apps/web/src`. Calevate's wins: it is a real prop-driven header that follows the shell's `h1` rule and wraps actions full width on a phone; Arc's is a demo. Condense-on-scroll already exists as `interior/sticky-header` and `console/stickyPageBar.tsx`; the overflow menu is `console/rowMenu.tsx`; tabs are `interior/tabs`.

**Where in Calevate:** none. Ideas worth borrowing into `console/pageHeader.tsx` only if the founder wants them: folding secondary actions into a `RowMenu` when the row is too narrow (L247-261 hysteresis `LEAD_MIN 240` / `LEAD_RETURN 272`).

**Verdict: SKIP** — a no-prop demo needing two new Radix packages; Calevate's `PageHeader` (72 files) is the one header.

**Source:** `docs/design/uiarc/registry/page-header/`

---

### notification-center
**What it does:** A bell button with an unread-count badge that opens a Radix popover holding a notification list: All/Unread views, rows that expand to show details with Mark read/unread and Dismiss, Mark all read, Clear read, and an empty state. Every change animates (rolling counts, height springs, blur swaps).

**Exports / API:** `NotificationCenter`

| Prop | Type | Default | Notes |
|---|---|---|---|
| notifications | `NotificationItem[]` | required | read ONCE into local state (L113); later prop changes are ignored |
| label | `string` | `"Notifications"` | trigger label, panel heading, content `aria-label` |
| onReadChange | `(notification: NotificationItem, read: boolean) => void` | — | fired per item, also per item on Mark all read (L145) |
| onDismiss | `(notification: NotificationItem) => void` | — | fired per item, also per item on Clear read (L163) |
| open | `boolean` | — | controlled open state |
| onOpenChange | `(open: boolean) => void` | — | |
| avoidCollisions | `boolean` | `true` | passed to Radix `Popover.Content` |

`NotificationItem` (L11-20): `id: string`, `title: string`, `description?: string`, `time: string` (pre-formatted by the caller), `read?: boolean`, `tone?: "info" \| "success" \| "warning"`, `actor?: { name: string; photo: string }`.

Other exports: types `NotificationItem`, `NotificationCenterProps`; default export `NotificationCenter`.

**Data model, state and behaviour:**
- Read/unread: per item `read?` flag held in component state; badge = count of unread, shown as `9+` above nine (L176). Read state lives in the browser until the caller persists it through `onReadChange`.
- Grouping: none. Items render as one flat list in the order given (L194-225); docs.md's "grouped information" is not in the code. No date sections, no per-kind grouping.
- Actions per row: expand (the whole row text is a toggle, L202), then Mark read/unread and Dismiss (L215-221). Bulk: Mark all read (L144-150), Clear read (L162-167). There is no per-item link or primary action: a row cannot navigate anywhere.
- Live updates: none. `useState(initial)` (L113) copies the prop on mount, so a poll that adds or removes notifications never reaches the list or the badge. To be fed by a query it must be made controlled (items from props, read state from the caller).
- Empty state: "All clear / New updates will appear here." or "Nothing unread" (L227-229). It renders whenever the visible list is empty, including before data has loaded; there is no loading or error state.
- Popover vs panel: always a Radix popover (`side="bottom"`, `align="center"`, L180), width `min(424px, 100vw - 24px)`, max-height `min(590px, 100vh - 24px)` (css L6). No bottom-sheet variant on phones.

**Dependencies:** npm: `@radix-ui/react-popover` (**new**), `lucide-react`, `motion`. Registry: `arc-motion-tokens`, `avatar`.

**Accessibility:** trigger `aria-label` includes the unread count (L174); Radix supplies Escape to close, outside-click close, focus into the content and back to the trigger (behaviour of Radix Popover, not code in this file; Radix Popover is non-modal unless `modal` is set, and it is not set here). Content is labelled (L180) and has a close button "Close notifications" (L183). The summary line is `aria-live="polite"` (L182); outgoing animated copies are `aria-hidden` while fading (`Swap`, L46-49). View switch is a `role="group"` of `aria-pressed` buttons (L187-188); the list is `role="list"`/`listitem` (L194-196); each row toggle has `aria-expanded` and a label that says "unread" (L202). Focus is handed to the next row after Mark read in the Unread view and after Dismiss (L133-137, L152-155), and to the active view button after bulk actions (L149, L166). No arrow-key navigation within the list; every row and action is a Tab stop. Reduced motion: every transition becomes `instant`/fade (L169, L175-176, L197-198), CSS removes animations (css L79). Touch targets: trigger 42px (css L1), close 30px (css L19), view buttons 31px (css L23), row actions 30px (css L49), all below 44px.

**Mobile:** at ≤380px padding tightens and "Mark all read" hides its text (css L78). Height uses `100vh` (css L6), not `dvh`, so on a phone with the URL bar shown the panel can extend under it. z-index 90 (css L6) sits above Calevate's `--z-toast 70` and `--z-modal 60`.

**Issues found in the code:**
- No live updates (L113): the defining feature for a header bell fed by a 60-second poll.
- At ≤380px `.markAll span { display: none }` (css L78) leaves the button with only an `aria-hidden` icon (L190): no accessible name on a phone.
- Empty state claims "All clear" with no loading or failed state, which is exactly the "nothing needs you" sentence Calevate refuses to show without the server saying zero (`attention/page.tsx` header comment; `console/emptyState.tsx` cites BUILD-LOG §52 for the same rule).
- Tones are `info | success | warning` only (L17); Calevate's attention kinds use `bg-danger` for calls not answered, failed calls and failed deliveries (`attention/rows.tsx` `KIND_COPY`).
- Dismiss falls back to focusing the Unread view button even when the All view is shown (L155).
- `<time>` has no `dateTime` (L210); `time` is a free string, so IST formatting is the caller's job (acceptable, via `formatIST`).
- Hard-coded English: "Notifications", "Close notifications", "Show notifications", "All", "Unread", "Mark all read", "Mark read", "Mark unread", "Dismiss", "Clear read", "read", "All clear", "Nothing unread", "View all updates", "From {name}", "This update is ready to review.", and an English plural `update${n === 1 ? "" : "s"} waiting for you` (L124).
- Decorative motion: bell rotates -12deg on open (L175), rolling odometer counts with blur (L55-69), blur-in of "Mark all read" (L190), cascade exits (L43, L197).
- `100vh` and z-index 90 (css L6) against Calevate's `dvh` rule and z scale.

**Overlaps in Calevate:**
- Client console: `apps/web/src/app/c/[slug]/ClientTopHeader.tsx` renders the bell as a `Link` to `/c/[slug]/attention` (not a popover). Its count is `useAttention(session).data?.total` from `lib/api/attention.ts` (`GET /v1/attention`, refetch every 60s via `livePoll`), no badge until the query answers, no badge at zero, a warn dot and an explanatory label when the read failed, `99+` cap, `touch:h-11`. The same feed drives `useDesktopAlerts` (`lib/desktopAlerts.ts`), which keeps a per-tab "seen" set so only new items notify. The attention screen (`attention/page.tsx`, `attention/rows.tsx`) lists items from the server: `AttentionItemOut` = `id`, `kind` (10-value enum), `title`, `detail`, `href`, `occurred_at`, `rule`; `AttentionOut` adds server-counted `counts` and `total` (the list is capped, newest 50). Rows sort by urgency (`byUrgency`), each whole row is a link to the fix with the action named ("Add credits", "Reconnect", …), time in IST via `formatIST`. There is **no read/unread or dismiss state on the server**: an item leaves the queue when the problem is fixed.
- Admin console: `apps/web/src/app/admin/layout.tsx` `AttentionBell` (around L373-470) is already a popover, built on `components/interior/popover.tsx` (portal, Escape, focus return), listing two queue counts (held accounts, identity checks to review) with links, "Could not read" per failed queue and a `?` badge.

**Replace or sit on top:** it would **sit on top of** the attention link, not replace it. The `/attention` screen stays the full list (filters, server counts, the shortfall line, the copilot hook). A client-console popover would show the few most urgent items from the same `useAttention` query (no extra request), each row a link to its fix, plus "See everything that needs you" to `/attention`. Mark read, Dismiss and Clear read do not fit attention items: hiding an open problem is what the attention queue exists to prevent. If the founder wants an unread badge, it needs either a per-user server-side "seen" record (a new tenant-scoped table with RLS, hard rule 1) or a per-device seen set like `desktopAlerts`; that is a product decision, not a component one. The admin bell is a two-line count summary and does not need this block.

**Radix:** `@radix-ui/react-popover` is a new dependency (hard rule 9, REDESIGN-2 "no new npm dependency without asking"). `components/interior/popover.tsx` (5 files import it, including the admin bell) already gives portal, placement, Escape and focus return, so the Radix piece can be replaced without the new package.

**Where in Calevate:** client top bar bell (`app/c/[slug]/ClientTopHeader.tsx`) as a preview popover over `/c/[slug]/attention`. Founder's note: "should be used already at this point".

**Verdict: ADAPT** — the panel layout, view switch and focus hand-off are good, but it must become controlled (items from `useAttention`, L113 removed), rows must be links with Calevate's urgency tones including danger, read/dismiss dropped or backed by a decided store, a loading and failed state added, Radix swapped for `interior/popover`, touch targets raised to 44px, `dvh`, Calevate z scale, and the blur/rotate motion removed.

**Source:** `docs/design/uiarc/registry/notification-center/`

---

### empty-states
**What it does:** A demo card with four tabs (No results, Offline, Caught up, Not found) over one SVG illustration whose ten primitives spring and morph between scenes on a hand-written rAF spring engine, with a simulated action per scene ("Clear filters", "Try again" after a fake wait, …).

**Exports / API:** `EmptyStates` — takes **no props** (L166). docs.md: "No props".

| Prop | Type | Default | Notes |
|---|---|---|---|
| — | — | — | none: scenes, copy and timings are module constants (L22-50); shapes are in `empty-states-art.ts` (`FRAMES`, `KINDS`, `VIEW`, `shapePath`) |

Other exports: default export `EmptyStates`. `empty-states-art.ts` exports types `SceneId` (`"search" \| "offline" \| "inbox" \| "map"`), `Phase`, `Kind`, `Prim`, `Frame` and constants `KINDS`, `VIEW`, `FRAMES`.

**Dependencies:** npm: `motion`. Registry: `arc-motion-tokens`, `button`.

**Accessibility:** tabs implement `role="tablist"`/`tab`/`tabpanel` with roving `tabIndex`, Left/Right (wrapping), Home/End (L252-259, L276-288). The SVG is `role="img"` with a per-frame `aria-label` (L290); a polite live region announces the result of each action (L170, L240-248, L319). Reduced motion: the engine crossfades a frozen ghost layer instead of travelling (L132-149), text swaps drop `y`/blur (L267-271), parallax is off (L198-201), CSS drops transitions (css L50-52). Tab height `min-height: 30px` (css L8), below 44px.

**Mobile:** container-query padding and smaller tab text below 420px (css L3, L13); tabs scroll sideways (css L6). Parallax only for `(hover: hover) and (pointer: fine)` and mouse pointers (L199, L262).

**Issues found in the code:**
- Not reusable: no props (L166); the four scenes and their geometry are fixed in `empty-states-art.ts`, so a Calevate empty state (calls, leads, campaigns, knowledge) cannot be drawn with it.
- The actions are simulated with `setTimeout` (L246-249), and the copy names sample data ("Emma Collins", "sync.northwind.example", "/projects/atlas-2023", L29-50).
- Decorative motion: pointer parallax sway (L123-128, L261-265), blur text crossfades (L269), staggered shape morphs (L53-55). Calevate's empty-state doctrine says "no motion" (`emptySketch.tsx` header).
- A per-instance rAF physics engine (L93-164) is heavy for an empty list.
- Hard-coded English throughout; tabs 30px tall.

**Overlaps in Calevate:** `apps/web/src/components/console/emptyState.tsx` (`EmptyState`: `message`, `hint`, `action`, `illustration`, `align`, `className`; 66 files) and `console/emptySketch.tsx` (`EmptySketch`: a static, `aria-hidden`, token-only skeleton of the screen's own rows by `kind` — calls, leads, campaigns, callbacks, knowledge, numbers, deliveries, actions, attention, chat — or custom `rows`; 31 files). Both are explicit about "never generic artwork" and "no motion". Calevate's pair wins.

**Where in Calevate:** none.

**Verdict: SKIP** — a fixed four-scene showcase with decorative physics; Calevate's `EmptyState` + `EmptySketch` is the one empty state and is deliberately static.

**Source:** `docs/design/uiarc/registry/empty-states/`

---

### login (sign-in, login-centered)
**What it does:** Two Free variants of uiarc's login block. `sign-in` (docs "Variant: Email code") is a compact card: email, then a six-digit emailed code, then a signed-in summary, with a passkey button and Google/Apple/GitHub buttons. `login-centered` (docs "Variant: Centered") is a full-screen, passkey-first sign-in and sign-up card over an animated ring backdrop, with email-code fallback and the same three SSO buttons. In both, every network step is simulated with `setTimeout`.

Not fetched: `login-split` and `login-immersive` are **Arc Pro** (`sign-in/docs.md` "Access: Arc Pro" for Variant: Split and Variant: Immersive, "the source and install command need Pro"); they are not licensed here and their source is not in the registry folder. The docs also list a Free "Variant: Sign up" (`signup-form`) that was not fetched either.

**Exports / API (sign-in):** `SignIn`

| Prop | Type | Default | Notes |
|---|---|---|---|
| demoCode | `string` | `"123456"` | the code the simulated email "contains"; printed in the field description (L294) |
| onSignIn | `(account: SignInAccount, method: SignInMethod) => void` | — | fired after the simulated success (L177) |

Other exports: types `SignInMethod` (`"Email code" \| "Passkey" \| "Google" \| "Apple" \| "GitHub"`), `SignInAccount` (`{ name, email, photo? }`), `SignInProps`; default export `SignIn`.

**Exports / API (login-centered):** `LoginCentered`

| Prop | Type | Default | Notes |
|---|---|---|---|
| demoCode | `string` | `"482913"` | printed as "Demo code: …" (L404) |
| fullScreen | `boolean` | `false` | `min-height: 100dvh`, no frame (css L3) |
| demoEmail | `string` | `"maya@northwind.studio"` | account the simulated passkey/SSO resolves to |
| termsHref | `string` | `"#terms"` | a `#` link is intercepted as a demo (L345-351) |
| privacyHref | `string` | `"#privacy"` | same |
| onSignIn | `(email: string, method: LoginMethod, mode: "sign-in" \| "sign-up") => void` | — | |
| className | `string` | — | |

Other exports: types `LoginMethod`, `LoginCenteredProps`; default export `LoginCentered`.

**Dependencies:** npm: `lucide-react`, `motion` (both present; `FingerprintPattern`, used by login-centered L5, exists in the installed lucide-react 1.31.0). Registry: sign-in: `arc-motion-tokens`, `avatar`, `button`, `input`, `otp-input`, plus `lib/media.ts` shipped as its third file; login-centered: `arc-motion-tokens`, `button`, `input`, `otp-input`.

**What `media.ts` loads (sign-in):** `sign-in/media.ts` (identical to `changelog-feed/media.ts`) is a list of sample people and photos with **same-origin relative paths** (`/media/people/*.jpg`, `/media/photos/*.jpg`, `/media/people/portrait/*.jpg`, L21-87). No remote URL and no third-party host appears in it or in either block, so Calevate's CSP (`img-src 'self' data: blob: …` in `lib/security/csp.ts`) would allow them and nothing leaks to another origin. The image files themselves are **not** shipped by the registry and `apps/web/public/` has no `media/` folder, so the photos would 404 and `Avatar` would fall back to initials (avatar `onError`). sign-in uses it only for five sample teammates (L42-48).

**Social sign-in:** both blocks hard-code Google, Apple and GitHub buttons (sign-in L27, L280-282; login-centered L43, L387-389), with the four-colour Google "G" in literal hex fills (sign-in L29-35; login-centered L34-40), and a passkey path (sign-in L279; login-centered L380-385). Calevate uses only Google, for the client realm, through its own OAuth flow (`components/authn/googleSignIn.tsx`, callback at `app/(auth)/auth/google/callback`), and renders the button only when `GET /v1/auth/client/sign-in-options` says Google is on. Calevate has no Apple, GitHub or passkey sign-in (no `webauthn`/`passkey` anywhere under `apps/web/src` or `apps/api`). Both blocks would show three buttons that cannot work.

**Accessibility:** both: a polite `role="status"` region mirrors each step ("Sending a code", "Code didn't match", sign-in L325, login-centered L433); focus moves to the email field or the success heading on step change (sign-in L160-165, login-centered L193-199) and into the code field after an error (sign-in L215, login-centered L285); the resend button uses `aria-disabled` and a label with the remaining seconds (sign-in L297, login-centered L407); inputs come from Arc `Input` (label, `aria-describedby`, `role="alert"` error) and `OtpInput`. login-centered's mode switch keeps both labels in one cell and gives the button an `aria-label` (L370-371). Reduced motion: step slides become fades (sign-in L66-68, login-centered L56-58), the ring backdrop drift is off (login-centered L147, css L88-91), the passkey pulse rings are not rendered (L89). Touch: Buttons are 44px (`md`) and the resend/text buttons `--control-height-sm` 36px (sign-in css L38, login-centered css L45); sign-in's inline "Did you mean" and "Sign up" text buttons have zero padding (css L19); login-centered legal links are 32px (css L64).

**Mobile:** sign-in is a card `width: min(100%, 432px)` (css L1) with tighter SSO buttons in narrow containers (css L69). login-centered is a three-row grid with `min-height: 640px` (css L2), `100dvh` when `fullScreen` (css L3), and container rules below 400px (css L80-86). Ring drift is pointer-only (L140-147).

**Issues found in the code:**
- Simulated auth throughout: `later(…, 800/700/900/1100)` instead of requests (sign-in L187-195, L209-216, L246; login-centered L225-229, L252, L262-271, L279-291). Wiring them to Calevate means rewriting every handler.
- No password step. Calevate's `signInForm.tsx` is password first, then the emailed code only when `POST /login` answers `otp_required`; neither block has a password field.
- The demo code is printed in the UI (sign-in L294, login-centered L404) — the exact "dev OTP bypass" class Calevate's `signInForm.tsx` header (§5.7 defect 3) and `tests/authnSourceGuards.test.ts` exist to keep out.
- Hard-coded claims the server never made: "It expires in 10 minutes" (sign-in L287), "Remembered for 30 days" (sign-in L315, login-centered L422), a fixed 30-second resend timer started on the client (sign-in L26, L155-159) where Calevate starts its countdown from the server's cooldown and `Retry-After`.
- Enumeration and personalisation: sign-in builds a display name from the typed address and greets "Welcome back, {first name}" (L57-63, L312); Calevate's form deliberately renders one fixed sentence for unknown address, wrong password and deactivated account (§5.7 defect 2) and does not print the address on the code step.
- Unsupported providers and passkeys (above); Arc brand text "Sign in to Arc", "Welcome to Arc" and the Arc mark (sign-in L265; login-centered L368, L381, L419).
- Decorative motion: blur step transitions, rolling resend digits with blur (sign-in L71-85), drawn success ring and badge pop (sign-in L307-310, login-centered L415-417), pointer-driven ring parallax backdrop (login-centered L51, L130-154, L357-365).
- Hard-coded English everywhere, including the "or" divider and the domain-typo map (sign-in L49).
- `OtpInput` is one input per digit (`otp-input.tsx` L147-160, `autoComplete="one-time-code"` only on the first box); Calevate's `interior/otp-input.tsx` is one real input laid over boxes, chosen for platform autofill and a single screen-reader announcement.

**Overlaps in Calevate:** `app/(auth)/auth/sign-in/page.tsx` (client realm) and `app/(auth)/auth/admin/sign-in` (admin realm), framed by `components/authPage.tsx` (`AuthPageFrame`, `AuthCard`, `AuthHeading`; showcase aside from `lg` up, `overflow-y-auto` so nothing is clipped), the form in `components/authn/signInForm.tsx` (realm passed as a literal, server-decided OTP step, one `useCountdown` on an absolute deadline, `submitOnce` guard), `components/authn/googleSignIn.tsx`, `components/authn/fields.tsx`, `components/passwordInput.tsx` and `components/interior/otp-input.tsx` (4 files import it). Calevate's flow wins on every security property above; the Arc blocks are presentation over fake handlers.

**Where in Calevate:** none as components. One idea worth taking into `signInForm.tsx` or `createAccountForm.tsx`: sign-in's "Did you mean name@gmail.com?" typo suggestion (L49-55, L270-272), localised and offered without claiming the account exists.

**Verdict: SKIP** — both Free variants are simulated passwordless/passkey demos with Apple/GitHub buttons Calevate does not support and a visible demo code; Calevate's realm-split, server-driven sign-in is the one sign-in. login-split and login-immersive are Arc Pro and not available.

**Source:** `docs/design/uiarc/registry/sign-in/`, `docs/design/uiarc/registry/login-centered/`

---

### stats-band
**What it does:** A band of three or four headline numbers that count up from zero the first time they scroll into view, each with an optional tiny visual (sparkline, 90-day uptime strip, histogram, dotted world map) and a context line that replaces the detail line on hover or focus.

**Exports / API:** `StatsBand` (`forwardRef<HTMLElement>`)

| Prop | Type | Default | Notes |
|---|---|---|---|
| stats | `Stat[]` | `exampleStats` (sample "Deploys", "API uptime", "Median response time", "Edge regions") | three or four read best; layout caps at 4 columns (L202-203) |
| layout | `"plain" \| "divided"` | `"plain"` | `divided` rules a hairline grid |
| title | `string` | — | `h2`; without it the section is `aria-label="Key numbers"` (L196) |
| description | `string` | — | |
| duration | `number` | `1.6` | seconds per count-up; also sets the visual draw time (L203) |
| locale | `string` | `"en-US"` | number formatting (L187) |
| className | `string` | — | |

`Stat` (`stats-band-data.ts` L14-32): `value: number`, `prefix?`, `suffix?`, `decimals?` (default 0), `notation?: "standard" \| "compact"`, `label`, `detail?`, `context?`, `visual?: StatVisual`. `StatVisual`: `{kind:"trend"; values}` \| `{kind:"uptime"; days}` \| `{kind:"distribution"; bins; max; marker}` \| `{kind:"map"; points: [lon, lat][]}`.

Other exports: types `Stat`, `StatVisual`, `StatsBandLayout`, `StatsBandProps`; `StatsBandBlock` (a preview with a layout switcher) is the **default export** (L226-236), not `StatsBand`.

**The world file:** `stats-band-world.ts` (1,307 bytes) is not a map library or GeoJSON: it is a hand-coded 80 x 30 land bitmask, 30 hex strings of 20 digits (L5-12), spanning 168° W to 192° E and 76° N to 56° S with Antarctica omitted (L2-3), expanded to a flat `boolean[]` (`worldLand`, L17-20). 757 cells are land; `WorldMap` draws one SVG `<circle>` per land cell plus one larger circle per point, each point snapped to the nearest land cell within two cells (stats-band.tsx L143-164). No network fetch.

**Dependencies:** npm: `motion`. Registry: `arc-motion-tokens`, `segmented-control` (only for the `StatsBandBlock` preview, L6, L229).

**Accessibility:** a real `<dl>` with `dt` label and `dd` figure (L202-215); screen readers get only the final value through an sr-only span while the animated digits are `aria-hidden` (L91-100); visuals are `aria-hidden` (L214), so their information exists only as the visual (a sparkline or uptime strip has no text equivalent unless the caller writes one into `detail`/`context`). A stat with `context` gets `tabIndex={0}` (L205) on a `div` with no role, so keyboard users can focus it to reveal the context line (css L63-69); both detail and context are always in the DOM, the swap is visual only (css L26-28). Reduced motion read after hydration (L33-42): numbers show final values (L79) and CSS stops drawing (css L142-150). Final width is reserved under the counting digits so layout never shifts (L95-98).

**Mobile:** container queries re-flow to two columns under 800px and one under 520px (css L103-140); hover-less devices show the context on `:focus` (css L66-70).

**Issues found in the code:**
- Money as floats: `value: number` with a `prefix` such as "$" (data L16-18) and `animate(0, stat.value)` (L81). Hard rule 7 keeps INR as decimal strings; a rupee stat would have to pass through `Number()`.
- Locale `en-US` by default (L187) and `Intl` compact units ("K", "M", L55) rather than Indian grouping (lakh/crore) through `formatINR`/`formatCount`.
- Count-up from zero is decorative (L64-102): on a dashboard the number a person needs is the final one, and Calevate signals a changed value with `valueFlash`, not by replaying from zero.
- Uptime `--h` maps each 0.01% of downtime to visible height (L124); a single bad day dominates the strip — a design choice to know about.
- Sample data names fictional numbers (`stats-band-data.ts` L46-67).
- The default export is the demo, so `import StatsBand from …` gets the preview with a SegmentedControl.

**Overlaps in Calevate:** `apps/web/src/components/console/metric.tsx` (`Metric`/`MetricRow`, 24 files: the console KPI unit, with `flashValue` for changes and token tones) and `ui.tsx` `StatTile` (defined, no callers outside `ui.tsx`). For in-console analytics `Metric` wins. Calevate has no marketing stats band; marketing mockups live in `apps/web/src/components/marketing/home/mockups/` and `marketing/solutions/solutionMockups.tsx`.

**Where in Calevate:** marketing pages (`app/page.tsx` home, `app/pricing`, `app/roi`, `app/why-calevate`, `app/industries`, `app/solutions`) and their mockups, where a count-up on first view is acceptable; possibly `app/status` (uptime strip) if it shows real measured numbers. Not the client console KPIs (`DailyCalls.tsx`, `performance/`, `billing/`, `usage/`), which keep `Metric`. Founder's note: "analytics, other stuff, even mockups".

**Verdict: ADAPT** — for marketing and mockups only: map to Calevate tokens, default `locale` to `en-IN` and route money through decimal strings (`formatINR`) rather than `value: number`, export `StatsBand` as the default, keep the dotted map (small, local, no fetch), and give each visual a text equivalent; console analytics stay on `Metric`.

**Source:** `docs/design/uiarc/registry/stats-band/`

---

### slot-text
**What it does:** Renders a string or number as a row of slot-machine reels: each character spins through digits or the alphabet to its new value, reels stop left to right, and widths spring as characters enter or leave.

**Exports / API:** `SlotText`

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `string \| number` | required | numbers go through `format` |
| format | `(value: number) => string` | `value.toLocaleString("en-US")` (L149) | |
| duration | `number` | `.9` | seconds the first reel spins |
| stagger | `number` | `.07` | seconds between reels stopping |
| spins | `number` | `1` | extra full turns per digit |
| align | `"start" \| "end"` | `"end"` for numbers, `"start"` for strings (L150) | which end reels are matched from |
| announce | `boolean` | `false` | polite live announcement of the new value (L164) |
| className | `string` | — | |
| style | `CSSProperties` | — | |

Other exports: `SlotTextProps`; default export `SlotText`.

**Dependencies:** npm: `motion`. Registry: none (it does not import `motion-tokens`; its easing is a local constant, L36).

**Accessibility:** the real text sits in an sr-only span (L164) and the reels are `aria-hidden` (L165); `announce` makes that span `aria-live="polite"`, off by default. Reduced motion (read after hydration, L41-44) jumps reels and widths to the final state (L117-121, L132). Nothing is focusable. No forced-colors rule (none needed: glyphs are plain text).

**Mobile:** `white-space: nowrap` on the root (css L1) — a long string never wraps and can overflow at 320px.

**Issues found in the code:**
- Breaks Telugu and other complex scripts: `Array.from(text)` (L151) splits by code point, so a Telugu syllable made of a consonant plus a vowel sign or virama becomes separate reels and the glyphs cannot shape. `classOf` only knows Latin letters and ASCII digits (L46); anything else jumps without spinning.
- `en-US` grouping by default (L149); numbers as `number` (money as float, hard rule 7, if used for rupees).
- Decorative motion: velocity-based `blur()` on the strip (L107-110), random letter shuffles (L64-66), spins for their own sake. Calevate's doctrine keeps motion to state changes; a changed number already has `valueFlash`.
- Each character is a `motion.span` with two springs and a `ResizeObserver`-free `getBoundingClientRect` per change (L114-128): costly for long strings.

**Overlaps in Calevate:** `apps/web/src/components/console/valueFlash.tsx` (`useChangeFlash`, `compareDecimal`, `FLASH_MS`; 8 files): marks a changed value without parsing money. Calevate's approach wins for console numbers.

**Where in Calevate:** none in the consoles. A marketing "launch moment" (for example a pricing figure on `app/pricing`) is the only fit, and only for Latin-script digits.

**Verdict: SKIP** — decorative motion that cannot render Telugu correctly; `valueFlash` already covers "this number changed".

**Source:** `docs/design/uiarc/registry/slot-text/`

---

### changelog-feed
**What it does:** A release-notes feed: title and subtitle, a Subscribe pill that morphs into an email field and then a "Subscribed" confirmation, New/Improved/Fixed filter chips with counts, a sticky month bar that tracks scroll and jumps between months, and expandable entries with details, a photo (`next/image`) or a code block with a copy button.

**Exports / API:** `ChangelogFeed`

| Prop | Type | Default | Notes |
|---|---|---|---|
| entries | `ChangelogEntry[]` | `exampleEntries` (L51-66, fictional "Halden" product) | newest first; each belongs to a month by key |
| months | `ChangelogMonth[]` | `exampleMonths` (Sep-Jun 2026, L32-37) | newest first |
| title | `string` | `"Changelog"` | `h2` |
| subtitle | `string` | `"Halden 4.12 shipped on September 18, 2026"` | |
| endNote | `string` | `"That is everything since Halden 4.5 in June."` | |
| defaultOpen | `string[]` | the newest entry's id (L268) | |
| className | `string` | — | |

`ChangelogEntry` (L18): `id`, `month`, `date` (display string), `iso`, `version`, `kind: "new" \| "improved" \| "fixed"`, `title`, `summary`, `details: string[]`, `media?`. `ChangelogMedia` (L14-16): `{type:"photo"; src: StaticImageData \| string; alt; caption; width?; height?}` or `{type:"code"; file; code}`. `ChangelogMonth` (L19): `key`, `label`, `short`.

Other exports: types `ChangelogKind`, `ChangelogMedia`, `ChangelogEntry`, `ChangelogMonth`, `ChangelogFeedProps`. Not exported: `SubscribeControl`, `EntryRow`, `EntryMedia`, `RollingNumber`.

**Dependencies:** npm: `lucide-react`, `motion`; also imports `next/image` (L4), which `next` already provides. Registry: `arc-motion-tokens`, `copy-button`, plus `lib/media.ts` as its third file.

**What `media.ts` is for here:** only the sample photos (L9, L30): `photo("terracotta-waves")` etc. resolve to same-origin `/media/photos/*.jpg` paths. No remote host. The JPEGs are not shipped by the registry, so the sample entries' photos would 404 until real images are supplied; with real entries `lib/media.ts` is not needed at all. Sample code is sample data too: the `@halden/node` `verifyWebhook` snippet (L39-45) and the `edge.halden.example` DNS snippet (L47-49) belong to the fictional product.

**Accessibility:** entry rows are buttons with `aria-expanded`/`aria-controls` (L209), chips are `aria-pressed` toggles in a labelled group (L329-339), month buttons are labelled "Jump to {month}" with `aria-current` (L362-370), the visible count is `aria-hidden` with a polite sr-only mirror (L344-350), each month section is labelled by its `h3` (L376-387). The scroll region is focusable (`tabIndex={0}`, `aria-label="Release notes"`, L373) so keyboard users can scroll it. Subscribe: sr-only label for the email input (L158), `aria-invalid` (L159), Escape returns to idle (L141), a polite status line (L173). Reduced motion: `useReducedMotion` collapses transitions to `instant` (L72, L199, L266), the shake is skipped (L134), CSS zeroes all transition durations (css L134-137). Touch targets: chips 34px (css L34), month buttons 28px (css L63), subscribe pill 38px (css L13), subscribe submit 28px (css L22), undo 26px (css L26).

**Mobile:** at ≤640px the header stacks and rows become a two-row grid (css L111-125); at ≤480px the month count, year and the "N updates" line are hidden (css L127-132). The list is a fixed-height inner scroller: 560px (css L69), 520px on phones (css L118) — a nested scroll on a page.

**Issues found in the code:**
- Subscribe is fake: `submit` validates the address and switches to "Subscribed" (L130-140) with no callback prop and no request; "Undo" just clears it (L143). It must be wired to a real subscription or removed.
- Hard-coded English: kind labels (L23-27), "Subscribe", "Email address", "Subscribe to release notes", "Subscribed", "Undo", "Enter a valid email address", "Filter by type", "Show all", "updates", "of {n} updates", "No updates", "Jump to …", "Release notes", English pluralisation (L316, L360). The month label is split on a space into month and year (L357), which assumes an English "Month YYYY" label.
- Dates are caller strings (`date`, `iso`) — fine for IST if the caller formats with `formatIST`; nothing computes "today".
- Decorative motion: blur on entry, panel and chip changes (L69-71, L204-206, L225), rolling counts (L76-95), subscribe pill width morph with a shake (L134, L151), shared-layout month pill (L366).
- Fixed-height nested scroller (css L69, L118).
- `next/image` with remote `src` strings would need `images.remotePatterns` in `next.config.ts` and CSP `img-src`; with same-origin images it does not.

**Overlaps in Calevate:** no changelog or "What's new" screen exists (`grep changelog` finds none). Pieces overlap: `CopyButton` vs `components/interior/copy-button`, filter chips vs `ui.tsx` `FilterChip`, expandable rows vs `ui.tsx` `Disclosure`.

**Where in Calevate:** a future public release-notes page beside `app/resources` or `app/status`, or a "What's new" panel in the client console once clients exist. Founder's note: "future, when we go live and roll out changes".

**Verdict: ADAPT** — a sound structure for release notes, once the fake Subscribe is wired or dropped, sample data and `lib/media.ts` removed, `CopyButton` swapped for `interior/copy-button`, chips for `FilterChip`, the nested scroller made optional, touch targets raised, strings localisable, and the blur motion removed.

**Source:** `docs/design/uiarc/registry/changelog-feed/`

---

---

## Part B: supporting registry items

These items are pulled in as registry dependencies of the founder's components. They get no verdict of their own: each is taken only if a component that needs it is adopted, and the paragraph names the Calevate piece that wins where they overlap.

**arc-foundation** (`registry/arc-foundation/foundation.css`, 192 lines; registry dependency `arc-motion-tokens`). The global token sheet every Arc component assumes is loaded once at the root: neutrals `--neutral-0..11`, `--background`, `--foreground`, `--surface*`, `--text-secondary`, `--text-muted`, `--border*`, `--accent*` (default neutral dark grey, eight `data-accent` palettes), `--control-*` including `--control-height-sm/md/lg` 2.25/2.75/3.125rem, radii (`--radius-control` 1.125rem, `--radius-panel` 1.625rem), shadows, type scale, spacing, durations and eases, `--series-1..4` chart colours, a full `[data-theme="dark"]` set, and a global focus rule with `!important` (L186-191: `:focus:not(:focus-visible)` gets `outline: none !important`; every `:focus-visible` gets an accent outline). No founder component lists it as a registry dependency (Arc's install docs say to import it once by hand). No npm deps. It collides with Calevate's `globals.css`: `--surface`, `--surface-muted`, `--text-muted`, `--danger`, `--duration-fast` (160ms vs 150ms), `--ease-in-out` and `--shadow-raised` exist in both with different values, and `--text-muted` means different things (Arc's faintest text, `oklch(59% 0 0)`; Calevate's secondary text, `#475569`). Importing it at `:root` would recolour the existing consoles and add a second focus indicator next to Calevate's `focus-visible:ring-2 ring-brand`. The dark theme is unused (Calevate is light only, D-471). Overlap: `apps/web/src/app/globals.css` wins; Arc components need a scoped mapping layer (Arc names to Calevate tokens, e.g. `--foreground` to `--text`, `--text-secondary` to `--text-muted`, `--text-muted` to `--text-faint`, `--border` to `--line`, `--accent` to `--brand`) rather than this file.

**arc-motion-tokens** (`registry/arc-motion-tokens/motion-tokens.ts`, registry path `registry/motion-tokens.ts`, target `@components/arc/motion-tokens.ts`; plus `lib/motion-tokens.ts`, a one-line re-export alias targeted at `@components/arc/lib/motion-tokens.ts`, which is the path components import as `../lib/motion-tokens`). Exports `motionTokens`: durations `instant .12 / fast .16 / exit .18 / standard .24 / considered .48` s, eases `enter / exit / standard / inOut` as cubic-bezier arrays, springs `responsive` and `gentle` (stiffness/damping) and `snappy` .26 / `smooth` .4 / `morph` .42 (`visualDuration`, `bounce: 0`), staggers, and blur radii `subtle 2 / soft 4 / text 8` px. Pulled in by every founder component in this section except slot-text (text-shimmer, page-header, notification-center, empty-states, sign-in, login-centered, stats-band, changelog-feed) and by every supporting item here except arc-motion-tokens itself; `FETCH-REPORT.txt` records its docs page as HTTP 404. No npm deps. Overlap: Calevate's motion tokens are CSS (`--duration-fast/base/slow/press`, `--ease-out-strong`, `--ease-in-out-strong`, `--ease-drawer` in `globals.css`); the values differ (150/200/280ms vs 160/240/480ms). If Arc components are adopted, this file should be re-expressed from Calevate's values so there is one motion scale, and the `blur` radii are the part the redesign doctrine would leave unused.

**tooltip** (`registry/tooltip/tooltip.tsx`). A Radix hover/focus tooltip (`content`, `children`, `side`) with a shared "warm" timer so moving between triggers opens the next one instantly (L26, L60-79), z-index 90 (css L1). None of this section's components pulls it; across the registry only `floating-button-group` does. npm: `@radix-ui/react-tooltip` (**new**), `motion`. Overlap: `apps/web/src/components/console/infoTip.tsx` (64 files), a click toggletip chosen because a hover-only tip is unreachable on a phone; InfoTip wins.

**animated-counter** (`registry/animated-counter/animated-counter.tsx`). Animates a `value: number` with `prefix`, `suffix`, `decimals`, `label`, `animateOnView`, `locale` (default `"en-US"`, L67), splitting `Intl.NumberFormat` parts so changed digits roll (L25). Pulled in by page-header (tab counts); elsewhere by `billing-toggle` and `metric-card`. npm: `motion`. Issues for Calevate: `number` money (hard rule 7) and `en-US` grouping. Overlap: `console/metric.tsx` plus `console/valueFlash.tsx`, which show changed values without parsing money; Calevate's win.

**button** (`registry/button/button.tsx`). `Button` extends native button props with `variant: "primary" | "secondary" | "ghost" | "danger"`, `size: "sm" | "md" | "lg"` (36/44/50px via `--control-height-*`, css L32-34) and `loading` (spinner, `aria-busy`, `aria-disabled`, L106-117); presses scale .96-.985 by width (L21-24) and label changes crossfade with blur (L28-31). Pulled in by page-header, empty-states, sign-in, login-centered (and `cookie-consent`, `plan-comparison`). npm: `motion`. Overlap: `ui.tsx` `PRIMARY_BUTTON`/`SECONDARY_BUTTON`/`DANGER_BUTTON`/`QUIET_ICON_BUTTON` class constants (`PRIMARY_BUTTON` alone appears in 140 files), `components/actionButton.tsx` (13 files, inline spinner, `aria-busy`) and `interior/loading-button` (no callers). Replacing the class constants would touch well over a hundred files; Calevate's constants win, and `size="sm"` (36px) is below the 44px touch rule.

**segmented-control** (`registry/segmented-control/segmented-control.tsx`, default export only). `options: Segment[]` (`value`, `label`, `accessory?`), `value`, `onValueChange`, `label`, `onOptionIntent`, `className`; a `role="group"` of `aria-pressed` buttons with roving tabindex and arrow/Home/End keys (L44-68), a sliding highlight with a fixed `layoutId="selection"` (L68), so two controls on one page without a `LayoutGroup` share the highlight animation. Pulled in by stats-band (preview only) and `plan-comparison`. npm: `motion`. Overlap: `components/interior/segmented-control.tsx` (`SegmentedControl` with `SegmentedOption`, imported by 20 files, including the attention filter); Calevate's wins.

**avatar-group** (`registry/avatar-group/avatar-group.tsx`). `members: { name, src?, status? }[]`, `max` (4), `size`, `label` ("Team members"); a `role="group"` stack with a "+N" overflow and animated entry/exit, keyed by `member.name` (L28), so two members with the same name collide. Pulled in by page-header only. npm: `motion`; registry: `avatar`. Overlap: none as a group; single avatars are `ui.tsx` `Avatar`. Calevate has no member-stack UI today.

**avatar** (`registry/avatar/avatar.tsx` plus `arc-provider.tsx`). `Avatar` (`name`, `src`, `size` sm/md/lg/xl = 28/36/48/88px, `status` online/offline) renders `role="img"` with the name as label, an image through `ArcImage` that falls back to Latin initials on error (L9-19). `arc-provider.tsx` is a context (`ArcProvider`, props `link` and `image`) that lets an app swap the `<a>`/`<img>` Arc renders for `next/link`/`next/image`; without it Arc renders plain elements with an eslint disable for `no-img-element`. Pulled in by notification-center, page-header, sign-in (and avatar-group). npm: `motion`. Overlap: `ui.tsx` `Avatar` (initials only; used outside `ui.tsx` by `app/c/[slug]/ClientSidebar.tsx`); Calevate's is enough for a product that shows no profile photos, and `ArcProvider` would be one more provider in the tree.

**progress** (`registry/progress/progress.tsx`). `Progress` (`value`, `max`, `label`, `showValue`, plus div props): `role="progressbar"` with `aria-valuenow/min/max` and `aria-valuetext` as a percentage (L47), spring-driven fill and counted label, a check that pops in at 100% (L52); the default accessible name is the English "Progress" (L47). Pulled in by page-header only. npm: `lucide-react`, `motion`. Overlap: `components/interior/progress-bar.tsx` (`ProgressBar`, 7 files) and `illustration/trialMeter.tsx`; Calevate's wins.

**input** (`registry/input/input.tsx`). `Input` (forwardRef) extends native input props with required `label`, `description`, `error`; wires `htmlFor`, `aria-describedby` and `aria-invalid`, and the error message is `role="alert"` with word-by-word blur swaps (L17-19, L39, L65, L69-80); height `--control-height-md` 44px (css L5). Pulled in by sign-in and login-centered. npm: `motion`. Overlap: `ui.tsx` `FIELD*` class constants (`FIELD` in 154 files) and `components/authn/fields.tsx` `AuthField`; Calevate's win.

**otp-input** (`registry/otp-input/otp-input.tsx`). `OtpInput` (`length` 6, `value`, `onChange`, `label`, `description`, `error`, `autoFocus`, `disabled`, `inputMode`, `className`): one `<input maxLength={1}>` per digit in a labelled group, each labelled "{label}, digit N of M", `autoComplete="one-time-code"` only on the first box (L147-160), a sliding focus ring and blur-in glyphs; slots 42x48px, 44px tall under 360px (css L5, L26). Pulled in by sign-in and login-centered. npm: `motion`. Overlap: `components/interior/otp-input.tsx` (4 files: `signInForm`, `createAccountForm`, `emailVerificationPanel`, `stepUpPrompt`), deliberately ONE real input over drawn boxes so platform autofill fills the whole code and a screen reader announces one field; Calevate's wins.

---

## Part C: adoption plan

**Ranking.** The list is ranked by value to the founder's named screens: how much a component improves them, against how little work and dependency cost it brings. "Fix first" names the defect from the component's Part A section that must be closed before its first consumer ships.

**Shared prerequisite.** Every row assumes the work in "What an adaptation always involves":
- the scoped token map;
- focus rings;
- 44px touch targets;
- strings as props;
- `en-IN` and IST;
- `--z-*`;
- the decorative motion removed.

**Dependencies.** None of the recommended rows needs a new npm dependency once its Radix piece is swapped for the in-repo primitive named.

| # | Component | Verdict | Founder's screen | Screens it improves | Fix first | Dependency cost |
|---|---|---|---|---|---|---|
| 1 | announcement-bar | ADAPT | "important, we will be using this soon" | Client shell (`app/c/[slug]/layout.tsx`, after `TrialBanner`), admin shell, public pages | Render through `SITE_STRIP` with a tone dot, not a tinted band. Scope the localStorage dismissal key to the account and stop the flash before hydration. Turn rotation off unless there is a pause control (WCAG 2.2.2). Use `next/link` for the CTA. Show the countdown in IST. | none |
| 2 | usage-meter | ADAPT | "will be of great use" | `c/[slug]/billing` Usage tab (minutes against included, Clear and Studio segments, spending cap); trial call panel; replaces `RoomLeft` in `script/ScriptToolbar.tsx` | Display decimal strings; use numbers only for geometry. Add `role="meter"` and `aria-value*`. Add a "no limit" (pay-as-you-go) state and a skeleton instead of a false 0. Let the caller choose whether going over is a warning or an error. A Studio-trial meter also needs the API to publish used and limit. | none |
| 3 | notification-center | ADAPT | "should be used already at this point" | Client top-bar bell (`ClientTopHeader.tsx`) as a preview over `c/[slug]/attention`; admin `AttentionBell` | Make it controlled from `useAttention`, because it reads `notifications` once (L113). Make rows into links with Calevate's urgency tones. Drop read and dismiss, because attention items have no read state on the server. Add loading and failed states. Use `dvh`. | none. Swap `@radix-ui/react-popover` for `interior/popover` |
| 4 | swipe-actions | ADAPT | "caller page, lead page … mobile viewport" | `c/[slug]/calls` and `c/[slug]/leads` as a phone-only list next to the `DataTable` (it cannot wrap `<tr>` rows); possibly `attention` | Swap Radix for `RowMenu`. Turn `fullSwipe` off by default. Make `onSelect` async with a visible failure. Restore `user-select` so phone numbers can be copied. Make the More button 44px with a focus ring. Offer only non-destructive swipes (call back, copy number, set status). | none. Swap `@radix-ui/react-dropdown-menu` for `RowMenu` |
| 5 | bottom-sheet | ADAPT | "mobile viewport" | The phone mode of `console/drawer.tsx`, and so every Drawer (billing AddCredit, receipts, statements, lead-sources, integrations, data-rights …) | Ship it inside `Drawer`, on `useFocusTrap`. Keep Drawer's footer and unsaved-edits guard. Use `--z-drawer`. Do not add it as a third sheet. | none. Swap `@radix-ui/react-dialog` for `useFocusTrap` |
| 6 | bar-chart, then sparkline | ADAPT | "analytics" | `c/[slug]` dashboard (`DailyCalls`), `performance` (hour histogram), `billing` (`SpendChart`); sparkline on dashboard tiles (`daily_7d`) and the billing spend headline | Bar chart: add a stacked mode, an empty state and `en-IN` formatting, and hide the browser-computed average for money. Move all three bar charts in one change. Sparkline: map tones to tokens and add an empty state. | none |
| 7 | stats-band | ADAPT | "analytics, other stuff, even mockups" | Marketing pages and mockups only; console KPIs stay on `Metric` | Route money through `formatINR` strings, not `value: number`. Default to `en-IN`. Export `StatsBand` rather than the demo. Give each visual a text equivalent. | none |
| 8 | toast-stack | ADAPT | none | Replaces `interior/toaster.tsx` in both console shells (3 files move) | Keep a no-op default context. Render in a portal at `--z-toast`. Stop error toasts from auto-dismissing, or announce them assertively. Add the safe-area inset. | none |
| 9 | expandable-text | ADAPT | none | Script proposal quotes, call and lead summaries, knowledge; replaces `interior/show-more.tsx` and the hand-rolled `Quote` clamp | Use a 44px toggle, remove the label blur and shorten the open. Delete `show-more` and remove its `AWAITING_A_DECISION` entry. | none |
| 10 | timeline | ADAPT | none | `c/[slug]/leads/[leadId]` (replaces `LeadTimeline`, 1 caller) | Pass `timeZone="Asia/Kolkata"` (the default is UTC). Stop comparing against the word "Today". Keep LeadTimeline's loading, error, empty and Load more states. | none |
| 11 | search-field | ADAPT | none | About 12 hand-rolled search inputs (leads, campaigns, knowledge, admin config, DNC, voices) | Add `hideLabel`, a 44px clear button, 16px text on touch and Escape to clear. Move every caller in the same change. | none |
| 12 | date-range-picker (on calendar) | ADAPT | "campaigns page" | `c/[slug]/calls` custom range. Campaigns take a start instant or weekly days, not a range, so the founder's screen does not fit. | Use IST days and `YYYY-MM-DD` strings. Clamp presets to min and max (L499-507). Add a visible label. | none |
| 13 | json-viewer | ADAPT | none | Agent action test results, integrations delivery log | Default `copyable` to false. Keep the server gate as the only door to raw bodies (hard rules 5 and 6). Keep a `<pre>` fallback. | none |
| 14 | slider, number-field, inline-edit, tag-input, date-picker, hover-card, button-group, changelog-feed | ADAPT | hover-card: "desktop viewport"; changelog-feed: after launch | See each section | Take each only when a screen needs it, and then as the one control of its kind (slider replaces `RANGE_INPUT` with all 3 callers; date-picker only as THE date control across all 11 files) | none, once Radix is swapped where named (hover-card, button-group) |

**The founder's other named screens, where the answer is not an Arc component:**

- **Knowledge base: file-dropzone (SKIP).** `components/fileDrop.tsx` is already the file control on `c/[slug]/knowledge` (`AddDocument.tsx`). It is stricter on validation, the disabled state, honest progress and server truth. Its multi-row Retry pattern is the one idea worth porting into `FileDrop`.
- **Billing page: billing-toggle and plan-comparison (SKIP).** Calevate sells prepaid credit packs with one optional monthly platform fee. The code has no monthly/annual period and no plans to compare. Both components also carry float prices with `$` and `en-US` formatting (hard rule 7).
- **Script page: rich-text-editor (SKIP).** The script is spoken, and the prompt rules forbid markdown. The editor emits HTML, and its link field lets `javascript:` hrefs through (L22-28).
- **Rate our agent or script: gauge (SKIP).** The gauge is a display (`role="meter"`) and cannot collect a rating. Collecting a rating needs an input. The in-repo candidates are `interior/segmented-control` or `console/choiceCards`, plus an API to store it. Neither exists today.
- **Leads and campaigns analytics: brush-chart (SKIP).** Neither screen's API returns a dated series. The only daily series are the dashboard's `daily_7d`, billing's spend days and admin reply times.
- **Analytics: activity-heatmap and ridgeline (SKIP).** No endpoint serves months of daily counts, or raw observations per group. Revisit them only if such an endpoint is built, which is a product decision.
- **Onboarding: onboarding-checklist (SKIP as a component).** `console/checklist.tsx` is server-driven, with waiting, blocked and disabled rows. Borrow three patterns into it:
  - the current step expanded, with one action;
  - done rows folded into "N completed";
  - focus moved to the next step.
- **Login.** `sign-in` and `login-centered` are passwordless demos with Apple, GitHub and passkey buttons that Calevate does not support, so both are SKIP. `login-split` and `login-immersive` are Pro and not available.

**Dependency cost of the recommended set: none.** Five recommended rows ship with a Radix package upstream:

| Component | Radix package upstream | In-repo replacement |
|---|---|---|
| notification-center | `@radix-ui/react-popover` | `interior/popover` |
| hover-card | `@radix-ui/react-popover` | `usePopoverPlacement` |
| swipe-actions | `@radix-ui/react-dropdown-menu` | `RowMenu` |
| button-group | `@radix-ui/react-dropdown-menu` | `RowMenu` |
| bottom-sheet | `@radix-ui/react-dialog` | `useFocusTrap` |

Taking any of them as published instead would add those packages, which needs the founder's approval and a supply-chain review (hard rule 9). The SKIP set would have added `@radix-ui/react-switch`, `@radix-ui/react-accordion`, `@radix-ui/react-tabs` and `@radix-ui/react-tooltip`.
