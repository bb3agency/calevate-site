# UI component catalogue: interior.dev and Pixel Perfect

This catalogue reviews two third-party component sources for the Calevate consoles: the client panel (`app.calevate.tech`) and the admin panel (`admin.calevate.tech`). Each component gets a verdict:

- **ADOPT** means use it, with at most mechanical fixes.
- **ADAPT** means take it, then fix or restyle what the section lists.
- **SKIP** means do not take it.

- **Part A** covers the 46 interior.dev components, from source.
- **Part B** covers the Pixel Perfect blocks.
- **Part C** is a ranked shortlist mapped to screens.

## Sources and licences

- **interior.dev.** Source `github.com/ddoemonn/interior`, MIT licence, "Copyright (c) 2026 ozzy". Components are distributed as a shadcn registry (`https://www.interior.dev/r/<name>.json`) and documented at `https://www.interior.dev/docs/<name>`. Each component is one `"use client"` file depending only on `motion` (`motion/react`) and Tailwind. Line numbers in Part A (`L123`) refer to upstream `components/interior/<name>.tsx` at commit `314800833bf01e23e6ae74c2a17fbdaac3688c84` (2026-09-10). The registry payloads used for this review are byte-identical to that commit. Copies taken into this repo must keep the MIT notice.
- **Pixel Perfect.** Source `github.com/vansh-nagar/Pixel-Perfect`, which has **no licence**. Part B sets out the position and the founder's decision to use the code regardless. No source from it is reproduced in this document.

## Already in this repo

`apps/web/src/components/interior/` holds 18 of the 46 components, plus a `toaster.tsx` that is not part of the upstream set of 46. The vendored copies differ from upstream mainly by swapping hard-coded `stone-*`/hex colours for Calevate tokens: `text-ink`, `text-ink-muted`, `text-ink-faint`, `border-line`, `bg-surface`, `brand`/`brand-bright`. Some also gain touch-target sizing (`touch:h-11`) or a `ScrollRegion` wrapper.

Only `tabs` (through `useTabs`, on billing), `load-more` (calls, lead detail) and `pagination` (leads footer) have consumers. The other vendored copies are listed as awaiting a decision in `apps/web/tests/componentConsumers.test.ts`, so adopting one means removing its entry there.

Existing in-repo pieces that several verdicts defer to, under the "one way per problem" rule:

- `components/ui.tsx`: `Disclosure`, `FilterChip`, `NoticeBox`, `ScrollRegion` and the `FIELD*` class constants.
- `lib/focusTrap` (`useFocusTrap`).
- `components/confirmDialog.tsx`.
- `components/navDrawer.tsx`.
- `components/formValidation.tsx`.
- `components/callAudioPlayer.tsx`.

---

## Part A: interior.dev (46 components)

| Verdict | Components |
|---|---|
| ADOPT (9) | copy-button, load-more, pagination, progress-bar, segmented-control, show-more, skeleton-swap, tabs, task-steps |
| ADAPT (23) | accordion, collapsible-banner, command-palette, drawer, dropdown, expanding-search, inline-validation, live-activity, loading-button, new-items-pill, password-strength, popover, reorder-list, scroll-spy, slider-detents, sortable-table, sticky-header, tag-input, tooltip-group, tree-view, typing-indicator, value-flash, wizard-steps |
| SKIP (14) | context-menu, filter-grid, floating-label, hide-on-scroll, hold-to-confirm, icon-morph, like-burst, long-press, modal, otp-input, reading-progress, ripple, streaming-text, swipe-deck |

### accordion
**What it does:** Bordered list of disclosure rows (single or multiple open) with spring height animation, measured via ResizeObserver; ships a headless `useAccordion` hook.

**Exports / API:** `Accordion`

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `readonly AccordionItem[]` (`{id, title, content, meta?}`) | required | `meta` renders right-aligned tabular text |
| type | `"single" \| "multiple"` | `"single"` | |
| defaultOpen | `readonly string[]` | `[]` | single mode keeps only first entry |
| open | `readonly string[]` | — | controlled |
| onOpenChange | `(open: string[]) => void` | — | |
| collapsible | `boolean` | `true` | `false` blocks closing the open row in single mode |
| maxPanelHeight | `number` | `220` | panel scrolls internally beyond this |
| headingLevel | `number` | `3` | `aria-level` on wrapper |
| className | `string` | `""` | |

Other exports: `useAccordion`, `useAutoHeight`, types `UseAutoHeightResult`, `AccordionEntry`, `AccordionHeaderProps`, `AccordionPanelProps`, `UseAccordionOptions`, `UseAccordionResult`, `AccordionItem`, `AccordionProps`.

**Behaviour that matters for reuse:**
- Height spring `DISCLOSE` stiffness 480 / damping 40 / mass 0.6; chevron `CHEVRON` 700 / 46 / 0.5 rotating 0→180; content opacity 0.18s ease `[0.23,1,0.32,1]` in, 0.14s ease `[0.4,0,1,1]` out (L14-29, L381-387).
- `useReducedMotion()` → every transition `{ duration: 0 }` (L252, L345, L360, L382).
- ARIA: `role="heading"` + `aria-level` wrapper (L315); button `aria-expanded`, `aria-controls`; panel `role="region"`, `aria-labelledby`, `aria-hidden` when closed (L182-217); closed panel also set `inert` imperatively (L304-311).
- Keys: ArrowDown/ArrowUp (wrap), Home, End move focus between headers (L188-201). All headers stay in tab order (no roving tabindex — matches APG accordion).
- `"use client"`; `useIsomorphicLayoutEffect` guard (L33-34); pre-measure SSR style `height: open ? "auto" : 0` avoids flash (L361-364). No portal.

**Browser APIs:** ResizeObserver (L61), `inert` property.

**Weaknesses / bugs:**
- Hard-coded colours: `divide-stone-200`, `border-stone-200`, `bg-white`, `dark:bg-[#1D1D1A]` (L267), `bg-stone-50` (L369), focus `focus-visible:shadow-[inset_0_0_0_1px_#4568FF]` (L318).
- `maxPanelHeight` 220 creates a nested scroller whose container is not focusable (L370-376) — long content (e.g. a transcript) becomes a scroll-trap inside a scroll page.
- Title is `truncate` (L321) — long titles are cut, no wrap option.
- Every panel is a `role="region"` (L212) — APG warns against region proliferation with many panels.
- Controlled mode still writes `setUncontrolled` (L144-147): harmless but dead state.

**Already in Calevate:** no (repo has its own `Disclosure` in `components/ui.tsx`).

**Fit for Calevate consoles:** Settings FAQ/help panes, admin ops config groups, knowledge-base doc metadata, billing "how credits are charged" explainers. Overlaps `ui.tsx` `Disclosure`.
**Verdict: ADAPT** — solid a11y and motion, but needs token recolouring, `maxPanelHeight` made optional (off by default), and should replace or merge with the existing `Disclosure` rather than sit beside it (one way per problem).

---

### collapsible-banner
**What it does:** Notice card with icon, title, foldable body (description/children/action) and a dismiss button; three states `open | folded | dismissed`.

**Exports / API:** `CollapsibleBanner`

| Prop | Type | Default | Notes |
|---|---|---|---|
| title | `ReactNode` | required | |
| description | `ReactNode` | — | body text |
| children | `ReactNode` | — | body extra |
| action | `ReactNode` | — | rendered in body `mt-2` |
| icon | `ReactNode` | info glyph | |
| dismissible | `boolean` | `true` | |
| state / defaultState | `BannerState` | — / `"open"` | controlled / uncontrolled |
| onStateChange | `(s: BannerState) => void` | — | |
| onDismiss | `() => void` | — | |
| dismissLabel | `string` | `"Dismiss notice"` | aria-label |
| dismissedMessage | `string` | `"Notice dismissed."` | polite live region |
| className | `string` | `""` | |

Other exports: `useCollapsibleBanner` (returns `state, open, folded, dismissed, fold, expand, toggle, dismiss, restore`), types `BannerState`, `UseCollapsibleBannerOptions/Result`, `CollapsibleBannerProps`.

**Behaviour that matters for reuse:**
- `DISCLOSE` spring 190 / 30 / 1; caret `NUDGE` 700 / 46 / 0.5; opacity 0.14s ease `[0.23,1,0.32,1]` with 0.05s delay when opening; body y −6→0 (L6-8, L173-179, L266-270).
- Reduced motion → `INSTANT` `{duration: 0}` everywhere (L173-174, L187-189, L231, L269).
- Toggle button `aria-expanded`/`aria-controls`; Escape on toggle folds (with `stopPropagation`) (L208-217); outer `role="region"` labelled by title (L195-196); body uses React 19 `inert={!open}` prop (L260); `role="status" aria-live="polite"` announces dismissal (L286-288).
- `"use client"`; no portal; no window access.

**Browser APIs:** none.

**Weaknesses / bugs:**
- Dismissed state only animates height/opacity to 0 (L183-193); the region, toggle and dismiss button stay in the DOM, accessibility tree and tab order — no `inert`/`aria-hidden` on the dismissed wrapper. Focus is left on an invisible button after dismiss; no focus hand-off.
- `restore` is exported but no UI path back from dismissed (L53); dismissal is not persisted (caller must do it).
- Title is `truncate` (L222, L239) — long compliance titles cut off at 320px.
- Hard-coded colours: `border-stone-200 bg-white dark:bg-[#1D1D1A]` (L197), `bg-stone-100/70 dark:bg-[#252522]` (L202), focus `#4568FF`/`#93B0FF` (L218, L250). No tone variants.
- Body indent fixed `pl-[46px]` (L270).

**Already in Calevate:** yes — vendored, local diff: adds `tone?: BannerTone` (`info|success|warning|danger`) recolouring the icon chip, and swaps stone/hex classes for tokens (`border-line`, `bg-surface`, `text-ink*`, brand focus ring `#16a05d`/`#22c55e`); used in: nothing — listed in `apps/web/tests/componentConsumers.test.ts:58` `AWAITING_A_DECISION`.

**Fit for Calevate consoles:** client dashboard notices (Clear voice rung unavailable, low credit balance, DLT registration pending, compliance gate warnings), admin "attestation missing" banners.
**Verdict: ADAPT** — the vendored tokenised copy is the right base, but fix the dismissed-but-focusable defect (add `inert` on the wrapper when dismissed and move focus) before giving it its first consumer.

---

### command-palette
**What it does:** Fuzzy-ranked command list with combobox input, active-row highlight and shortcut keycaps; inline, or as a portalled modal overlay when `open` is passed.

**Exports / API:** `CommandPalette`

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `CommandItem[]` (`{id, label, hint?, keywords?, shortcut?: string[]}`) | required | |
| onSelect | `(item) => void` | required | |
| onDismiss | `() => void` | — | Escape / outside click |
| open | `boolean` | — | defined ⇒ overlay mode via `PaletteLayer` |
| placeholder | `string` | `"Search commands"` | |
| emptyLabel | `string` | `"No command matches"` | |
| label | `string` | `"Command palette"` | aria-label of input and listbox |
| maxRows | `number` | `6` | fixed list height = rows×36 + gaps + padding |
| autoFocus | `boolean` | `false` | |
| className | `string` | `""` | |

Other exports: `useCommandPalette` (returns `query, setQuery, results, activeId, activeIndex, listRef, onKeyDown, pointerActivate, jump, move, run`), type `CommandItem`, `UseCommandPaletteOptions`, `CommandPaletteProps`.

**Behaviour that matters for reuse:**
- Ranking: subsequence match, +2 per char, +4×streak, +12 at index 0, +8 after boundary `[\s\-_/.:]`; keyword match −3; tie-break by `−label.length×0.05` then original order (L9, L28-64).
- Row `layout="position"` spring `CELL` 520 / 34 / 0.45; highlight crossfade `CROSSFADE` 260 / 34 / 0.8 (L7-8, L299-310). Overlay: scrim 0.2s ease `[0.23,1,0.32,1]` in, 0.15s `[0.4,0,1,1]` out; panel `PANEL` spring 420 / 36 / 0.9 from scale 0.96, y 12; exit scale 0.98, y 6 (L369-482).
- Reduced motion: layout off, transitions `{duration: 0}`, panel opacity-only (L299, L309, L450-475).
- ARIA: input `role="combobox"`, `aria-expanded` (always true), `aria-controls`, `aria-autocomplete="list"`, `aria-activedescendant` (L259-267); `ul role="listbox"`, `li role="option" aria-selected` (L285-298); count announced in `role="status"` after 400ms (L222-231, L352).
- Keys on input: ArrowUp/Down (wrap), Home, End, Enter (run), Escape (dismiss) (L130-150). Overlay adds a capture-phase document Escape listener (L393-403). Pointer highlight ignores synthetic moves (L123-128). List `onMouseDown` preventDefault keeps input focus (L287).
- Overlay: `createPortal` to `document.body` set in effect (L386-391, L421); scroll lock on `<html>` with scrollbar-gutter padding (L405-417); outside click requires pointerdown and click both outside (L431-441).

**Browser APIs:** timers (L223), `document` listeners.

**Weaknesses / bugs:**
- Overlay is not a dialog: no `role="dialog"`/`aria-modal`, no focus trap, background not `inert`, focus not restored to the opener on close (L421-490).
- `autoFocus` effect depends only on `[autoFocus]` (L214-216), so on re-open of the overlay the input is NOT focused again; overlay without `autoFocus` opens with focus left behind the scrim.
- `aria-expanded` hard-wired true (L264).
- Results only fuzzy-match local `items`; no async/loading/grouped sections, so server search (leads, calls) needs a wrapper.
- Hard-coded colours: `border-stone-200 bg-white dark:bg-[#1D1D1A]` (L240), `bg-stone-900/40` scrim (L445), `bg-stone-100` highlight (L310). Hint hidden below `sm` (L318). Width `max-w-[520px] w-full` — OK at 320px.
- Live-region copy hard-coded English "command(s) available" (L228).

**Already in Calevate:** no.

**Fit for Calevate consoles:** global Cmd+K for both consoles: jump to agent/campaign/lead, "Pause campaign", "Big red switch" (admin), switch tenant (admin), open billing. Static nav commands fit as-is; entity search needs async.
**Verdict: ADAPT** — good ranking and combobox semantics, but the overlay needs dialog semantics, `useFocusTrap`, focus-on-open/restore-on-close and tokens before it can be a console-wide surface.

---

### context-menu
**What it does:** Right-click / Shift+F10 / ContextMenu-key / touch long-press menu positioned at the pointer, viewport-clamped, portalled, with typeahead and separators.

**Exports / API:** `ContextMenu`

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `ContextMenuItem[]` (item `{id, label, shortcut?, icon?, disabled?, onSelect?}` or `{id, type:"separator"}`) | required | |
| children | `ReactNode` | required | wrapped in focusable trigger div |
| onSelect | `(id) => void` | — | fires after item `onSelect` |
| label | `string` | `"Context menu"` | menu aria-label |
| width | `number` | `224` | clamped to `vw − 16` (min 160) |
| disabled | `boolean` | `false` | |
| className | `string` | `""` | on trigger |

Other exports: `useContextMenu` (options add `margin=8`, `holdDuration=460`, `moveTolerance=8`; returns `isOpen, active, placement, openAt, close, triggerRef, triggerProps, menuRef, menuProps, getItemProps`), types `ContextMenuItem`, `ContextMenuPlacement`, `UseContextMenuOptions`, `ContextMenuProps`.

**Behaviour that matters for reuse:**
- Enter 0.2s ease `[0.23,1,0.32,1]` from opacity 0 / scale 0.96; exit 0.14s `[0.4,0,1,1]` to scale 0.98; `transformOrigin` at pointer (L19-21, L443-457).
- Reduced motion: opacity only, `{duration: 0}` (L443-450).
- ARIA: trigger `tabIndex=0`, `aria-haspopup="menu"`, `aria-expanded`, `aria-controls` when open, sr-only hint via `aria-describedby` (L259-263, L422-432); menu `role="menu"`, `aria-orientation="vertical"` (L312-316); items `button role="menuitem" tabIndex=-1`, `aria-disabled` (L345-350, L471).
- Focus: actual DOM focus moves to active item (roving by focus) or menu (L206-211); `close(true)` restores focus to trigger (L118-128). Keys: ArrowUp/Down (wrap, skip disabled/separators), Home/End, Tab closes, printable chars typeahead with 600ms buffer (L185-202, L317-343). Escape via capture-phase document listener with `stopPropagation` (L228-233).
- Closes on outside pointerdown, any outside scroll, window resize, window blur (L213-249). Long-press only for non-mouse pointers; click after long-press swallowed (L283-309).
- `createPortal` to `document.body` (set in effect, L402-403, L508-517); fixed position, `zIndex: 60`.

**Browser APIs:** `navigator.vibrate?.(10)` (L292), timers (L188, L289), `getBoundingClientRect`, `scrollIntoView`; all timers cleared on unmount (L251-257).

**Weaknesses / bugs:**
- Trigger is a generic `div` carrying `aria-expanded`/`aria-haspopup` with no role (L422-428) — invalid ARIA on a generic; also Enter on the wrapper opens the menu (L277), which hijacks Enter if the wrapper is e.g. a table row that should navigate.
- Hint text hard-coded English and omits long-press (L431).
- Hidden-functionality pattern: context menus are undiscoverable; every action must exist elsewhere.
- No submenus, no checkbox/radio items, no danger styling for destructive items.
- Fixed `ITEM_H = 32` / `SEP_H = 9` height maths (L23-24, L62-66) breaks if item markup changes.
- Hard-coded colours `bg-white dark:bg-[#1D1D1A]` (L460), `bg-stone-100` active (L477), focus `#4568FF` (L427).

**Already in Calevate:** no.

**Fit for Calevate consoles:** secondary accelerators on calls list rows (copy call id, open transcript, flag for QA), leads table rows, KB document rows, admin tenant rows — only as a duplicate of a visible row-actions button.
**Verdict: SKIP** — accessible-ish, but a right-click menu is a poor primary affordance for SMB users on phones/tablets; a visible kebab menu (dropdown-menu) covers the same need without hidden functionality.

---

### copy-button
**What it does:** Button that copies a string, morphing icon and label idle → copied/error with an auto-reset timer; headless `useCopyToClipboard` hook.

**Exports / API:** `CopyButton`

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `string` | required | empty string is a no-op |
| label | `string` | `"Copy"` | also the `aria-label` |
| copiedLabel | `string` | `"Copied"` | |
| errorLabel | `string` | `"Failed"` | |
| timeout | `number` | `2000` | ms before reset to idle |
| onCopy | `(value) => void` | — | |
| onError | `(reason: unknown) => void` | — | |
| disabled | `boolean` | `false` | |
| className | `string` | `""` | |

Other exports: `useCopyToClipboard({timeout=2000, onCopy, onError})` → `{copy, reset, status, copied}`; types `CopyStatus`, `UseCopyToClipboardOptions`, `CopyButtonProps`.

**Behaviour that matters for reuse:**
- Icon/label crossfade `CROSSFADE` spring 260 / 34 / 0.8; check path draw `DRAW` 0.26s ease `[0.23,1,0.32,1]`; tap `whileTap {y: 1}` with `CELL` 520 / 34 / 0.45; labels blur 3px + y 3 (L6-10, L161-162, L234-239).
- Reduced motion: `INSTANT` crossfade/draw and no tap motion (L142-145, L161).
- Clipboard: `navigator.clipboard.writeText`, falls back to hidden `textarea` + `document.execCommand("copy")`, restoring the prior selection (L20-48, L82-96). Unmount guard via `mounted` ref (L58-69, L98). Reset timer cleared in effect cleanup (L109-113).
- `role="status" aria-live="polite"` announces copied/failed (L247-249). `"use client"`; no portal.

**Browser APIs:** Clipboard API, `document.execCommand` (deprecated) fallback, `setTimeout`.

**Weaknesses / bugs:**
- `aria-label={label}` is the static "Copy" (L157): in a table of many copy buttons every one is named "Copy" with no object — caller must pass e.g. `label="Copy call ID"`, which then also becomes the visible text.
- Live region is nested inside the `<button>` (L247) — announcement support inside an interactive element whose name is overridden by `aria-label` is inconsistent across screen readers; safer outside the button.
- `execCommand` fallback is deprecated and runs only after `navigator.clipboard` throws/absent (L87, L92).
- Fixed `h-9` text button only — no icon-only variant for dense table cells.
- Hard-coded colours: `border-stone-200 bg-white`, `dark:bg-[#252522]`, `dark:hover:bg-[#2A2A27]`, focus `#4568FF` (L164).

**Already in Calevate:** no (repo has ad-hoc clipboard code in `components/legal/copyLink.tsx`, `app/admin/ops/opsLanguage.tsx`, `app/c/[slug]/caller-notice/page.tsx`, `app/c/[slug]/lead-sources/MetaSetupDetails.tsx`).

**Fit for Calevate consoles:** copy webhook/lead-source URLs, API ids, call/execution ids, caller-notice text, invitation links, support reference ids.
**Verdict: ADOPT** — small, correct, cleans up its timer; adopt the hook as the single clipboard path (replacing the four ad-hoc copies), with tokens, an icon-only variant and the live region moved outside the button.

---

### drawer
**What it does:** Side sheet (left/right) with spring slide, scrim tied to drag position, header-grip drag-to-dismiss, modal focus trap and scroll lock; portalled to body or rendered in its parent.

**Exports / API:** `Drawer`

| Prop | Type | Default | Notes |
|---|---|---|---|
| open | `boolean` | required | always controlled |
| onOpenChange | `(open) => void` | required | |
| title | `string` | required | `h2`, `aria-labelledby` |
| children | `ReactNode` | required | scroll body |
| description | `string` | — | truncated subtitle |
| footer | `ReactNode` | — | bordered footer |
| side | `"left" \| "right"` | `"right"` | |
| width | `number` | `320` | `maxWidth: calc(100% - 40px)` |
| container | `"viewport" \| "parent"` | `"viewport"` | viewport ⇒ portal + modal |
| closeLabel | `string` | `"Close panel"` | |
| dismissOnScrimClick | `boolean` | `true` | |
| className | `string` | `""` | |

Other exports: `useDrawer` (options `open, defaultOpen=false, onOpenChange, side="right", width=320, dismissRatio=0.38, modal=true`; returns `open, side, width, dragging, x, veil, setOpen, close, rootRef, panelRef, panelProps, gripProps`), types `DrawerSide`, `UseDrawerOptions`, `UseDrawerResult`, `DrawerProps`.

**Behaviour that matters for reuse:**
- Slide via `animate(x, …)` with `DISCLOSE` spring 150 / 27 / 1; off-screen offset `width + 24`; scrim opacity `1 − |x|/width` (L14-19, L56-60, L85-96).
- Drag: `drag="x"`, listener off, started only from the header grip; dismiss if travel > `width × dismissRatio` (0.38) or velocity > 520 px/s, else spring back; one-sided `dragElastic` 1 (L190-230).
- Reduced motion: `{duration: 0}` for the slide (L88). Drag still available.
- ARIA: panel `role="dialog"`, `aria-modal={modal}`, `aria-labelledby` title, `aria-describedby` sr-only hint, `tabIndex=-1` (L214-218, L336-340, L385-387).
- Focus: on open stores `document.activeElement`, focuses first focusable (or panel); on close restores if still connected (L107-120). Tab/Shift+Tab trap within panel; Escape closes with `stopPropagation` (L156-188). Closed panel `inert` (L98-105). Modal: every other `body` child set `inert` (L138-154); `<html>` overflow hidden with scrollbar-gutter compensation (L122-136).
- `createPortal(tree, document.body)` after mount; returns `null` on server (L318-321, L392-393). `"use client"`.

**Browser APIs:** pointer events via motion drag, `window.innerWidth`, `inert`.

**Weaknesses / bugs:**
- Modal mode inerts ALL other `body` children (L143-149), including toaster/live-region portals — a toast raised from inside the drawer (e.g. "saved") is inert/unannounced. Needs an allow-list.
- Escape only handled on the panel's `onKeyDown` (L161); nested popovers that do not `stopPropagation` (e.g. this kit's `dropdown`, its L210-212) will close the drawer on the same Escape.
- Panel stays mounted when closed (always in DOM, L323-390) — heavy children (audio player, transcript) keep running; no unmount-on-close option.
- No bottom-sheet variant for phones; `width` is a fixed px number (L296, L340).
- Hard-coded colours `bg-white dark:bg-[#1D1D1A]` (L341), scrim `bg-stone-900/25 dark:bg-black/55` (L334), focus `#4568FF` (L370). Hint copy hard-coded English (L386).

**Already in Calevate:** no (repo has `components/navDrawer.tsx` using `lib/focusTrap`, and `ReceiptSheet.tsx` as a dialog).

**Fit for Calevate consoles:** call detail (transcript + audio) from the calls list, lead detail from the CRM table, KB document detail, admin QA-sampling review pane, tenant quick-view.
**Verdict: ADAPT** — strongest modal implementation in this set (trap, restore, inert, scroll lock, drag), but reconcile with the repo's `useFocusTrap`, allow-list toaster portals from the inert sweep, add unmount-on-close and tokens.

---

### dropdown
**What it does:** Single-select listbox popover (select replacement) with sliding active highlight, checkmark on the selected row, and typeahead.

**Exports / API:** `Dropdown`

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `DropdownItem[]` (`{value, label, hint?, disabled?}`) | required | |
| value | `string` | — | controlled |
| defaultValue | `string` | — | |
| onChange | `(value) => void` | — | |
| label | `string` | `"Options"` | VISIBLE trigger text and listbox aria-label |
| placeholder | `string` | `"Select an option"` | sr-only only |
| disabled | `boolean` | `false` | |
| emptyLabel | `string` | `"Nothing to choose"` | |
| className | `string` | `""` | |

Other exports: `useDropdown` (adds `typeaheadDelay=600`; returns `open, openMenu, close, select, activeIndex, selectedIndex, selectedItem, itemId, rootRef, triggerProps, listProps, getItemProps`), types `DropdownItem`, `UseDropdownOptions`, `DropdownProps`.

**Behaviour that matters for reuse:**
- Popover enter spring `OPEN` 620 / 38 / 0.6 from opacity 0, scale 0.94, y −8, opacity 0.12s ease `[0.23,1,0.32,1]`; exit 0.12s `[0.4,0,1,1]` to scale 0.97, y −6; highlight `SLIDE` 700 / 46 / 0.5 translating `activeIndex × 32`; caret `NUDGE` 700 / 46 / 0.5; check `CELL` 520 / 34 / 0.45 (L6-18, L335-369, L393-397).
- Reduced motion: opacity-only enter, `NONE` `{duration: 0}` transitions (L298, L335, L341-346, L365-367).
- ARIA: trigger `aria-haspopup="listbox"`, `aria-expanded`, `aria-controls` when open (L172-178); `ul role="listbox" tabIndex=-1` with `aria-activedescendant` (L191-196); `li role="option" aria-selected aria-disabled` (L228-236). Focus moves to the list on open (L141-143) and back to trigger on close (L98-103).
- Keys: trigger ArrowDown/Enter/Space open at selection, ArrowUp opens at last (L180-188); list ArrowUp/Down (skip disabled, wrap), Home/End, Enter/Space select, Escape close, Tab close, printable typeahead (L197-225). Closes on outside pointerdown and window blur (L145-157). Buffer timer cleared on unmount (L165-170).
- No portal: absolutely positioned under the trigger (L349). `"use client"`.

**Browser APIs:** timers, `scrollIntoView`.

**Weaknesses / bugs:**
- Trigger shows the static `label`, not the chosen value (L313); the selection is only in sr-only text (L310-312) — sighted users must open it to see what is selected, so it is a "sort/menu" button, not a form select.
- Not portalled (L349): clipped by any `overflow-hidden/auto` ancestor (tables, drawers, cards).
- `min-w-[224px]` at `left-0` (L349) can overflow a 320px viewport when the trigger is right-aligned.
- Escape does `preventDefault` but not `stopPropagation` (L210-212) — closes an enclosing drawer/dialog too.
- Tab is `preventDefault`ed then focus returns to the trigger (L213-215) — user's Tab press is swallowed.
- No `name`/hidden input, so it does not participate in `<form>` submission.
- Hard-coded colours `border-stone-200 bg-white dark:bg-[#1D1D1A]` (L304, L349), `bg-stone-100` highlight (L358).

**Already in Calevate:** yes — vendored, local diff: tokens instead of stone/hex (`border-line`, `bg-surface`, `text-ink*`, `bg-ink/[0.06]`) and popover width `sm:min-w-[224px] max-w-[calc(100vw-2rem)]` (fixes the 320px overflow); used in: nothing — listed in `apps/web/tests/componentConsumers.test.ts:59` `AWAITING_A_DECISION`.

**Fit for Calevate consoles:** compact filter/sort pickers on calls list, leads table saved-view switcher, campaign status filter, usage period selector, admin tenant filter.
**Verdict: ADAPT** — keyboard model is good, but before a consumer: show the selected label on the trigger (or add a `showValue` mode), stop Escape propagation, portal or collision-handle the popover, and stop swallowing Tab.

---

### expanding-search
**What it does:** Icon button that springs open into a search field (anchored left or right), with debounced `onSearch`, clear button, optional result count and a polite announcement.

**Exports / API:** `ExpandingSearch` (props = `UseExpandingSearchOptions` & below)

| Prop | Type | Default | Notes |
|---|---|---|---|
| value / defaultValue | `string` | — / `""` | |
| onChange | `(v) => void` | — | every keystroke |
| onSearch | `(v) => void` | — | debounced |
| onSubmit | `(v) => void` | — | Enter (flushes debounce first) |
| open / defaultOpen | `boolean` | — / `false` | |
| onOpenChange | `(open) => void` | — | |
| debounce | `number` | `220` | ms |
| collapseOnBlur | `boolean` | `true` | only when query empty |
| disabled | `boolean` | `false` | |
| label | `string` | `"Search"` | aria-label of input and trigger |
| placeholder | `string` | `"Search"` | |
| resultCount | `number` | — | shows count slot + announcement |
| align | `"left" \| "right"` | `"right"` | |
| className | `string` | `""` | |

Other exports: `useExpandingSearch` (returns `open, focused, query, expand, collapse, toggle, clear, inputRef, triggerRef, rootProps, triggerProps, inputProps`), types `UseExpandingSearchOptions`, `UseExpandingSearchReturn`, `ExpandingSearchProps`.

**Behaviour that matters for reuse:**
- Width spring `DISCLOSE` 380 / 38 / 0.7 from 40px to full track width; input fade `CROSSFADE` 260 / 34 / 0.8 with 0.06s delay on open; clear button `CELL` 520 / 34 / 0.45 scale 0.86→1; right-aligned trigger slides by `−(expanded − 40)` (L13-22, L315-318, L343-347, L373-374, L397-399).
- Reduced motion: `INSTANT` `{duration: 0}` for all (L304-306, L346).
- Root `role="search"` (L311); input `type="search"`, `aria-label`, `aria-describedby` → live region, `enterKeyHint="search"` (L332-341); trigger `aria-expanded`, `aria-controls`; trigger `tabIndex −1` and input `0` when open (swap) (L218-234). Results announced after 500ms "N result(s) for <query>" (L286-298).
- Escape: clears if non-empty else collapses and refocuses trigger (L181-190). Blur-collapse skipped when focus stays inside, window lost focus, or query non-empty (L166-177).
- `useIsomorphicLayoutEffect` (L24-25); debounce timer cleared on unmount (L106-111). No portal.

**Browser APIs:** ResizeObserver (L278), `document.hasFocus()`, timers.

**Weaknesses / bugs:**
- Controlled `open` desync: `setOpen` early-returns on `openRef.current === next` and mutates `openRef` before the parent responds (L113-118); `openRef` only resyncs when `isOpen` changes (L102-104), so if a parent declines an open/close, later calls are silently ignored.
- Controlled `value` still writes `setOwnValue` (L122) — dead state, harmless.
- "Clear search" label and announcement copy hard-coded English (L294, L370).
- Collapsed state is a 40px icon — search hidden behind a click on desktop consoles where list search is primary.
- Hard-coded colours `border-[#4568FF] bg-white dark:bg-[#252522]` and `bg-stone-100/70 dark:bg-[#1D1D1A]` (L327-329), focus outline `#4568FF` (L375, L401).

**Already in Calevate:** no.

**Fit for Calevate consoles:** mobile/narrow headers of calls list, leads table, KB docs and admin tenants where toolbar space is tight; `onSearch` debounce maps to TanStack Query keys, `resultCount` to total from the API.
**Verdict: ADAPT** — useful debounce + announcement semantics, but fix the controlled-`open` ref desync and tokenise; on desktop list pages prefer an always-open field (the hook can drive that too).

---

### filter-grid
**What it does:** Radio-chip filter row with live per-filter counts above a fixed-height animated card grid that re-flows items as the filter changes.

**Exports / API:** `FilterGrid<T>`

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `readonly T[]` | required | |
| filters | `readonly FilterDefinition<T>[]` (`{id, label, match}`) | required | first filter is the fallback |
| getKey | `(item: T) => string` | required | |
| renderItem | `(item: T) => ReactNode` | required | |
| label | `string` | required | radiogroup aria-label |
| value / defaultValue | `string` | — | |
| onValueChange | `(id) => void` | — | fires only on change |
| columns | `number` | `3` | fixed column count |
| rowHeight | `number` | `72` | px |
| maxRows | `number` | `4` | grid scrolls beyond |
| gap | `number` | `8` | px |
| emptyLabel | `string` | `"Nothing matches this filter"` | |
| className | `string` | `""` | |

Other exports: `useFilterGrid` (returns `active, activeLabel, select, visible, counts, total`), types `FilterDefinition`, `UseFilterGridOptions`, `UseFilterGridResult`, `FilterGridProps`.

**Behaviour that matters for reuse:**
- Thumb `layoutId` shared spring `CELL` 520 / 34 / 0.45; card reflow `layout="position"` with `MOVE` 260 / 34 / 0.8 plus 0.2s ease `[0.23,1,0.32,1]`; exit 0.14s `[0.4,0,1,1]`; enter from opacity 0 / scale 0.97; `AnimatePresence mode="popLayout"` (L14-18, L195-197, L227-232, L290-299).
- Reduced motion: no `layoutId`, `layout=false`, `INSTANT` transitions (L195-197, L229, L294).
- ARIA: `role="radiogroup"` + `aria-label` + `aria-controls`; chips `role="radio"`, `aria-checked`, roving `tabIndex` (L203-220); sr-only "label, n of total" per chip (L266-268); `aria-live="polite"` summary "Label: n of total shown" (L323-325).
- Keys: Arrow Right/Down next, Left/Up previous (wrap), Home, End — selection follows focus (L169-193). If focus was inside the grid when filtering, it is restored to the grid after exit (L152-167).
- Counts computed by running every `match` over every item (L60-68). `"use client"`; no portal.

**Browser APIs:** none.

**Weaknesses / bugs:**
- `columns` is a fixed number, not responsive (L143, L284): default 3 columns × 72px rows is cramped at 320px; no breakpoints.
- Grid height derived from `total`, not `visible` (L144-145) — a narrow filter leaves a large empty box.
- Client-side only: counts and filtering require the full dataset in memory (L60-74) — incompatible with paginated server lists (leads, calls).
- Hard-coded colours: thumb `bg-stone-800 dark:bg-stone-100` (L231), cards `border-stone-200 bg-white dark:bg-[#1D1D1A]` (L299), focus border `#4568FF` (L237).
- Chips `whitespace-nowrap` with flex-wrap — OK at 320px but many filters stack in rows.

**Already in Calevate:** no (repo has `FilterChip` in `components/ui.tsx`).

**Fit for Calevate consoles:** small, fully-loaded collections only: agent roster by status, vertical templates gallery, voice picker by tier/language, admin voices catalogue.
**Verdict: SKIP** — client-side counts over a fixed-column grid do not suit Calevate's paginated server-filtered lists; the radiogroup chip pattern is worth copying into the existing `FilterChip` instead.

---

### floating-label
**What it does:** Text input whose label sits inside the field and springs up above it when focused or filled, with hint/error line and optional character counter.

**Exports / API:** `FloatingLabelInput`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | |
| value / defaultValue | `string` | — | |
| onChange | `(value, event) => void` | — | |
| onFocus / onBlur | `() => void` | — | |
| hint | `string` | — | also error text when `invalid` |
| invalid | `boolean` | `false` | red border + `aria-invalid` |
| id / name | `string` | auto / — | |
| type | `"text" \| "email" \| "password" \| "search" \| "tel" \| "url"` | `"text"` | |
| autoComplete, inputMode, maxLength | — | — | `maxLength` shows `n / max` counter |
| required / disabled / readOnly | `boolean` | `false` | |
| inputRef | `React.Ref<HTMLInputElement>` | — | merged |
| className | `string` | `""` | |

Other exports: `useFloatingLabel({value, defaultValue, disabled=false})` → `{ref, raised, focused, filled, length, instant, fieldProps}`; types `UseFloatingLabelOptions/Return`, `FloatingLabelInputProps`.

**Behaviour that matters for reuse:**
- Label spring `LIFT` 760 / 46 / 0.5 to y −32, x −12, scale 0.92 (L15-19, L224-230); first paint is instant (no animation for pre-filled/autofilled values) via `instant` flag (L55-75).
- Reduced motion: `INSTANT` (L166).
- Real `<label htmlFor>` (L221-222); `aria-required`, `aria-invalid`, `aria-describedby` → sr-only hint (L202-204, L274-278); visible hint and counter are `aria-hidden` (L249-271).
- Uncontrolled mode listens to native `input`/`change` (catches autofill/programmatic changes), with cleanup (L77-87). `useIsomorphicLayoutEffect` (L21-22). `"use client"`.

**Browser APIs:** native input event listeners.

**Weaknesses / bugs:**
- Passes both `value` and `defaultValue` to `<input>` (L194-195) — React warns when a controlled caller also supplies `defaultValue`.
- Error is just the hint text recoloured (L251-255); no live/alert announcement when `invalid` flips, and the visible counter is hidden from AT with no sr equivalent (L262).
- Float-label pattern loses the label-above-field clarity for long Indian-language labels and has no placeholder support; the repo already standardises on `FIELD`/`FIELD_LABEL` (stacked labels) in `components/ui.tsx`.
- Fixed geometry: `top-[32px]`, `pt-[20px]`, `h-10` and `RAISE = -32` are coupled magic numbers (L17, L179-181, L231).
- Hard-coded colours (upstream): focus `border-[#4568FF] dark:border-[#93B0FF]`, `bg-stone-100/70`, `dark:bg-[#252522]` (L183-186).

**Already in Calevate:** yes — vendored, local diff: tokens only (`bg-surface`, `border-brand`/`brand-bright` focus, `border-line bg-ink/[0.06]`, `text-ink*`), no behaviour change; used in: nothing — listed in `apps/web/tests/componentConsumers.test.ts:60` `AWAITING_A_DECISION`.

**Fit for Calevate consoles:** login/OTP-adjacent auth forms, marketing lead-capture forms; less so console settings forms, which already use stacked `FIELD_LABEL`.
**Verdict: SKIP** — a second form-field style contradicts the repo's single `FIELD` convention ("one way per problem"); delete the vendored copy rather than adopt it, unless auth pages deliberately want it.

---

### hide-on-scroll
**What it does:** Scroll container whose top bar slides away on scroll-down and returns on scroll-up (threshold-accumulated, rAF-throttled); headless `useHideOnScroll` works on an element or the window.

**Exports / API:** `HideOnScroll`

| Prop | Type | Default | Notes |
|---|---|---|---|
| bar | `ReactNode` | required | the hiding toolbar |
| children | `ReactNode` | required | scroll content |
| barHeight | `number` | `44` | px |
| hideAfter | `number` | `14` | px of downward travel |
| revealAfter | `number` | `10` | px of upward travel |
| topGuard | `number` | `24` | always shown within this |
| pinned | `boolean` | `false` | |
| maxHeight | `number` | `320` | container scroll height |
| label | `string` | `"Scrollable content"` | region aria-label |
| onHiddenChange | `(hidden) => void` | — | |
| className | `string` | `""` | |

Other exports: `useHideOnScroll<T>({hideAfter=14, revealAfter=10, topGuard=24, pinned=false, disabled=false})` → `{ref, hidden, atTop}`; types `UseHideOnScrollOptions`, `UseHideOnScrollResult`, `HideOnScrollProps`.

**Behaviour that matters for reuse:**
- Bar slide `DISCLOSE` spring 150 / 27 / 1 to y = −barHeight; divider fade `CROSSFADE` 260 / 34 / 0.8 when not at top (L6-7, L182-200).
- Reduced motion: `{duration: 0}` — bar still hides, just without animation (L167-169).
- Focus inside the bar pins it visible (L158-165, L184-185). Scroll region `role="region"`, `tabIndex=0`, `aria-label`, `scrollPaddingTop: barHeight + 8` so focused items are not hidden under the bar (L202-210).
- Ignores overscroll/rubber-band (`y < 0 || y > max`, L75); resets direction accumulator on reversal (L90); passive scroll listener (L110). `"use client"`; no portal.

**Browser APIs:** `requestAnimationFrame`/`cancelAnimationFrame` (L104, L123), ResizeObserver (L113-117), window resize/scroll listeners — all removed on cleanup (L119-125).

**Weaknesses / bugs:**
- Target captured once from `ref.current` (L52-53) with deps `[down, up, guard]` (L126): if the ref element mounts later (conditional render) the hook binds to `window` and never rebinds.
- `HideOnScroll` never passes `disabled` through (L160-165), so the component cannot disable it except via `pinned`.
- Bar `onBlur` does not check `relatedTarget` (L185), so moving focus between two controls in the bar flips `focusWithin` false→true.
- Hidden bar controls are not `inert` — still reachable by AT browse mode while visually hidden.
- Fixed `maxHeight` 320 inner scroller (L153, L209) — nested scrolling on pages; hard-coded `bg-white dark:bg-[#1D1D1A]`, gradients `from-white` (L180, L190, L215, L220).

**Already in Calevate:** no (a vendored `interior/sticky-header.tsx` exists, also unconsumed).

**Fit for Calevate consoles:** possibly the filter toolbar over a long transcript pane on mobile, or the mobile console top bar via the hook in window mode.
**Verdict: SKIP** — hiding toolbars hurts discoverability in data-dense consoles and nested 320px scrollers fight the page scroll; keep sticky headers instead.

### hold-to-confirm
**What it does:** A button that runs `onConfirm` only after the pointer or key is held for `duration` ms. A dark overlay sweeps left-to-right as the hold progresses; letting go early drains the progress back at `releaseRate`×.
**Exports / API:** `HoldToConfirm`

| Prop | Type | Default | Notes |
|---|---|---|---|
| onConfirm | `() => void` | required | fired once when the hold completes (L95) |
| children | `ReactNode` | required | idle face |
| onAbort | `() => void` | — | fired on early release (L126); NOT fired on Escape-reset (L164) |
| confirmLabel | `string` | `"Confirmed"` | committed face + live-region text |
| duration | `number` (ms) | `1800` | |
| resetAfter | `number` (ms) | `1600` | returns to idle after commit; `<= 0` disables (L242) |
| steps | `number` | `20` | hook granularity only; the component's sweep is continuous |
| releaseRate | `number` | `2.5` | drain speed multiplier |
| disabled | `boolean` | `false` | rendered as `aria-disabled`, not `disabled` |
| className | `string` | `""` | |

Other exports: `useHoldToConfirm(options)` → `{ bind, step, steps, phase, progress, reset }` (options add `moveTolerance = 10`, `haptic = true`); types `HoldPhase` (`"idle" | "holding" | "releasing" | "committed"`), `UseHoldToConfirmOptions`, `HoldToConfirmProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). Face crossfade spring `FACE = { stiffness: 260, damping: 34, mass: 0.8 }` (L12).
- Sweep is a `clipPath: inset(0 X% 0 0)` driven by a motion value (L235-239). Holding: linear, `duration*(1-from)/1000` s (L261-264). Release: `duration*from/releaseRate/1000` s, ease `[0.23, 1, 0.32, 1]` (L268-271). Commit: 0.12 s linear (L254).
- Reduced motion: `useReducedMotion()`; sweep snaps to 1 or 0 (L248-250). The face crossfade still uses the `FACE` spring (L326, L333).
- Keyboard: Space/Enter starts, keyup releases, `e.repeat` ignored, Escape resets while holding/releasing (L160-176). Blur releases (L177). Pointer moving more than `moveTolerance` px cancels (L150-156). Context menu is suppressed (L182).
- ARIA: `aria-describedby` points at an sr-only hint, "Press and hold for {seconds} seconds…" (L300-303). `role="status" aria-live="polite"` announces `confirmLabel` (L305-307).
- Window `blur` and `visibilitychange` release the hold (L129-142).
**Browser APIs:** requestAnimationFrame, `performance.now`, `navigator.vibrate?.(14)` (L94), `setPointerCapture`, window blur / visibilitychange listeners, setTimeout.
**Weaknesses / bugs:**
- Polluted accessible name. The hint span (L300), the status span (L305) and the opacity-0 `confirmLabel` face (L331-351) are all un-hidden descendants of the button. Name-from-content therefore reads roughly "{children} Confirmed Press and hold…" even while idle, and `aria-describedby` repeats the hint.
- The hook calls `setStep` every frame a step boundary is crossed (L108-112), but the component never reads `step`, so those are wasted re-renders.
- No destructive tone. Colours are hard-coded: `border-stone-200 bg-white text-stone-700 dark:bg-[#1D1D1A]` (L282) and the overlay `bg-stone-800 dark:bg-stone-100` (L293).
- `whitespace-nowrap` with no max width (L327) lets long labels overflow at 320 px.
- A hold confirms the gesture but captures no reason or typed target. That is weaker than the confirmation the API demands for outbound halt (`X-Confirm-Action`).
**Already in Calevate:** no.
**Fit for Calevate consoles:** Possible targets are the admin outbound halt ("big red switch", `app/admin/ops/OutboundHaltPanel.tsx`), deleting a KB document and un-suppressing a DNC number. All of these are already served by `components/confirmDialog.tsx`, or by typed reason + confirm.
**Verdict: SKIP.** It would be a second confirmation idiom beside `ConfirmDialog`, it cannot carry the reason the halt endpoint requires, and its accessible name is wrong as shipped.

### icon-morph
**What it does:** An icon button whose SVG paths morph between two or more shapes (menu/close, play/pause, plus/minus, check/close), with an optional crossfading text label.
**Exports / API:** `IconMorph`

| Prop | Type | Default | Notes |
|---|---|---|---|
| preset | `IconMorphPreset` | `"menu-close"` | L122 |
| shapes | `readonly MorphShape[]` | preset shapes | custom `{ d: string[], rotate? }` |
| mode | `"stroke" \| "fill"` | preset mode | |
| labels | `readonly string[]` | preset labels | becomes `aria-label` per state |
| active | `number \| boolean` | — | controlled index |
| defaultActive | `number \| boolean` | `0` | |
| onActiveChange | `(index: number) => void` | — | |
| size | `number` | `20` | px |
| strokeWidth | `number` | `1.75` | |
| showLabel | `boolean` | `false` | |
| semantics | `"label" \| "pressed" \| "expanded"` | `"label"` | |
| disabled | `boolean` | `false` | native `disabled` |
| className | `string` | `""` | |

Other exports: `useIconMorph(options)` → `{ index, count, slots, rotate, mode, label, labels, transition, labelTransition, setIndex, toggle }`, `iconMorphPresets`, and the types `MorphShape`, `IconMorphMode`, `IconMorphPreset`, `IconMorphSlot`, `IconMorphSemantics`, `UseIconMorphOptions`, `IconMorphProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). Path and rotate spring `CELL = { stiffness: 520, damping: 34, mass: 0.45 }` (L6). Label crossfade `CROSSFADE = { stiffness: 260, damping: 34, mass: 0.8 }` (L7). Label slide is `y: ±3` (L256).
- Morph works by animating the SVG `d` attribute (L241). `normalize` pads missing slots with a collapsed copy of a sibling path (L94-105), so shapes must share command structure.
- Reduced motion: both transitions become `{ duration: 0 }` (L163-164).
- ARIA: `aria-label={label}` changes per state (L207). `aria-pressed` / `aria-expanded` are set only when `semantics` asks, and are true only for `index === 1` (L208-209).
- `toggle` wraps modulo `count` (L146).
**Browser APIs:** none.
**Weaknesses / bugs:**
- `semantics="pressed"` changes the accessible name AND sets `aria-pressed` (L207-208). A toggle button should keep a stable name.
- `aria-expanded` cannot be paired with `aria-controls`. Props are not spread onto the button (L186, L203-216).
- With three or more shapes, pressed/expanded are true only at index 1 (L208-209).
- 36 px square target, `h-9` / `w-9` (L212-213), is below 44 px on touch.
- Colours are hard-coded: `border-stone-200 bg-white dark:bg-[#1D1D1A] focus-visible:ring-stone-400` (L212).
- The `onClick` slot is taken by `toggle` (L206), so a consumer reacts only through `onActiveChange`.
**Already in Calevate:** no.
**Fit for Calevate consoles:** The play/pause toggle in `components/callAudioPlayer.tsx`, which today swaps lucide `Play`/`Pause` with an `aria-label` toggle (L238), and the menu toggle in `components/navDrawer.tsx`.
**Verdict: SKIP.** It is purely cosmetic over controls that already work correctly, and the button chrome and ARIA cannot be adjusted without forking the file.

### inline-validation
**What it does:** A labelled text input that validates only after first blur. After that, a fix is accepted immediately and a new error appears after a debounce ("reward early, punish late"). It has a check/alert glyph and a reserved hint/error line.
**Exports / API:** `InlineValidation`

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | `string` | required | `<label htmlFor>` |
| value / onChange | `string` / `(v: string) => void` | required | controlled |
| validate | `(value: string) => string \| null` | required | returns error text or null |
| hint | `string` | — | swapped out while invalid |
| id / name | `string` | auto `useId` | |
| type | `"text"\|"email"\|"password"\|"tel"\|"url"\|"search"` | `"text"` | |
| placeholder / autoComplete / inputMode | — | — | passthrough |
| debounce | `number` (ms) | `400` | delay before an error shows |
| reserveLines | `number` | `1` | message box height = `reserveLines * 16` px |
| disabled / required | `boolean` | `false` | |
| className | `string` | `""` | |

Other exports: `useInlineValidation({ value, validate, debounce })` → `{ status, error, message, touched, commit, reset, fieldProps }`; types `ValidationStatus`, `Validator`, `UseInlineValidationOptions`, `UseInlineValidationReturn`, `InlineValidationProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). Crossfade spring `{ stiffness: 260, damping: 34, mass: 0.8 }` (L6). Glyph scale is 0.7→1 (L222, L240) and message slide is `y: ±3` (L256, L268).
- Not validated until `commit` (blur) sets `touched` (L59, L88-97). After that, a valid value settles synchronously (L64-70); an invalid one goes `"pending"` and then `"invalid"` after `debounce` (L73-85).
- Reduced motion: transitions become `{ duration: 0 }` (L152-153).
- ARIA: `aria-invalid` comes from `fieldProps` (L111). `aria-describedby` = hint id plus error id only while invalid (L169-171). The error copy is `role="status" aria-live="polite" aria-atomic="true"` (L280-288). The visible hint and error `<p>` elements are `aria-hidden`, with sr-only duplicates (L251-277).
**Browser APIs:** setTimeout.
**Weaknesses / bugs:**
- The error is clamped to `reserveLines` (default 1) with `-webkit-line-clamp` (L173-178, L249). Longer messages, for example Telugu copy, are cut off visually.
- Input text is `text-[13px]` (L204). Below 16 px, iOS zooms on focus, and the repo's `touch:text-base` convention (`globals.css:316`) is not applied.
- `fieldProps` is spread after the consumer-facing props (L203), so `onBlur` cannot be supplied.
- "valid" shows a check on any non-empty passing value (L62, L222), including optional fields.
- Colours are hard-coded: `border-red-500`, `focus:border-[#4568FF]`, `bg-stone-100/70`, `dark:bg-[#1D1D1A]` (L204-207).
**Already in Calevate:** no.
**Fit for Calevate consoles:** Agent builder fields, webhook URL (`integrations/WebhookForm.tsx`), team invite email, and DNC number entry (E.164). Submit-time wording already lives in `components/formValidation.tsx`.
**Verdict: ADAPT.** Fold the `useInlineValidation` timing hook into `formValidation.tsx`, so there is one validation voice, rather than adding the styled component as a second way.

### like-burst
**What it does:** A like toggle with a heart crossfade, an 8-spark burst and a rolling counter. Clicks are optimistic and debounced into one abortable commit, with rollback on error.
**Exports / API:** `LikeBurst`

| Prop | Type | Default | Notes |
|---|---|---|---|
| initialLiked | `boolean` | `false` | |
| initialCount | `number` | `0` | |
| onCommit | `(liked, signal: AbortSignal) => Promise<unknown>` | — | called once per settle window |
| onError | `(error: unknown) => void` | — | after rollback |
| onToggle | `(liked: boolean) => void` | — | immediate |
| settle | `number` (ms) | `400` | debounce before commit |
| label / activeLabel | `string` | `"Like"` / `"Liked"` | |
| format | `(n: number) => string` | `Intl.NumberFormat("en-US")` | L32-33 |
| disabled | `boolean` | `false` | |
| className | `string` | `""` | |
| ref | `Ref<LikeBurstHandle>` | — | React 19 ref-as-prop; `{ toggle }` |

Other exports: `useOptimisticLike(options)` → `{ liked, count, base, pending, burst, settled, toggle }`; types `LikeCommit`, `LikeBurstHandle`, `UseOptimisticLikeOptions`, `OptimisticLike`, `LikeBurstProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). `EASE = [0.23, 1, 0.32, 1]` (L12), `CELL = { stiffness: 520, damping: 34, mass: 0.45 }` (L13), `CROSSFADE = { stiffness: 260, damping: 34, mass: 0.8 }` (L14). Sparks: 8 of them, distance `13 + h*9`, `duration: 0.44` plus a per-spark delay (L20-30, L275). Filled heart scales from 0.55 (L252). Counter rolls `y: ±7` (L310-312).
- Commit: an in-flight request is aborted on each flush, a sequence number discards stale results, and a failure restores `truth` (L90-140). Unmount clears the timer and aborts (L156-165).
- Reduced motion: no sparks (L258), `y: 0`, and transitions become `{ duration: 0 }`.
- ARIA: `aria-pressed`, `aria-busy`, and a static `aria-label={label}` (L222-224). `role="status" aria-live="polite"` announces the settled state (L322-324).
**Browser APIs:** setTimeout, AbortController, `Intl.NumberFormat`.
**Weaknesses / bugs:**
- The live-region text is hard-coded English: "likes", "liked", "not liked" (L323).
- The default number format is `en-US` (L33), not Indian grouping.
- `onToggle?.(!liked)` uses the render-time `liked` (L227), not the hook's ref value.
- Colours are hard-coded: `bg-white dark:bg-[#1D1D1A] border-stone-200` (L230) and `bg-stone-800 dark:bg-stone-100` sparks (L266).
**Already in Calevate:** no.
**Fit for Calevate consoles:** There is no social "like" anywhere in either console. The nearest shape, starring a call for QA or pinning a lead, is served by TanStack Query optimistic mutations.
**Verdict: SKIP.** The product has no use for it, and its optimistic-commit logic duplicates what `useMutation` already gives the app.

### live-activity
**What it does:** A "Dynamic Island"-style pod for one background task. It shows a compact glyph and title or percent, and expands on hover, focus, error, or a 2.6 s peek to show title, detail, progress bar and an action button.
**Exports / API:** `LiveActivity`

| Prop | Type | Default | Notes |
|---|---|---|---|
| activity | `Activity \| null` | required | from `useLiveActivity` |
| onDismiss | `() => void` | — | close button shown only when not running |
| width | `number` | `300` | expanded width, px |
| dismissLabel | `string` | `"Dismiss activity"` | |
| label | `string` | `"Activity"` | region name |
| className | `string` | `""` | |

Other exports: `useLiveActivity({ linger = 2000 })` → `{ activity, start, update, succeed, fail, dismiss }`; types `Activity`, `ActivityPhase` (`"running" | "success" | "error"`), `ActivityInput`, `UseLiveActivityOptions`, `UseLiveActivityReturn`, `LiveActivityProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). Springs: `SURFACE { 420, 36, 0.9 }` (L12), `CROSSFADE { 260, 34, 0.8 }` (L13), `SMALL { 700, 46, 0.5 }` (L14), `FILL { 210, 34, 0.9 }` (L15). Eases: `EASE [0.23, 1, 0.32, 1]` (L16), `LEAVE [0.4, 0, 1, 1]` (L17). Check draw 0.3 s (L18); spinner 0.85 s linear, infinite (L20). `PEEK_FOR = 2600`, `LEAVE_DELAY = 160` (L22-23).
- Enter `{ y: -10, scale: 0.9, blur 6px }`, exit `{ y: -8, scale: 0.97, blur 3px, 0.16 s LEAVE }` (L246-269). Size animates to `ResizeObserver`-measured dimensions (L161-176).
- `succeed` auto-clears after `linger` (L81-93); `fail` stays until dismissed (L95-103). `start` replaces any current activity (L61-70), so only one exists at a time.
- Reduced motion: opacity-only enter/exit, `INSTANT`, and a static ring instead of the spinner (L247-248, L410-413).
- ARIA: `role="region"` with `aria-label` (L238-239). The hidden face gets `aria-hidden` + `inert` (L298-299, L319-320). `role="status" aria-live="polite"` says "{title} started/finished/failed." (L202-215, L391-393). Escape collapses a running pod or dismisses a settled one (L288-293).
- SSR: `useIsoLayoutEffect` (L27-28); `ResizeObserver` is guarded (L171).
**Browser APIs:** ResizeObserver, setTimeout.
**Weaknesses / bugs:**
- The peek effect depends on `activity` itself (L192). Every `update()` (a progress tick) restarts the 2.6 s peek, so a task updating faster than that never collapses.
- The progress bar has no `role="progressbar"` or `aria-valuenow` (L368-385); progress is visual only.
- Keyboard users cannot expand a running pod. The compact face has no focusable element (L296-315), so `onFocusCapture` never fires.
- Fixed `width` 300 (L124, L324) is wider than a 320 px viewport minus 16 px gutters. The local copy clamps the outer pod, but the inner face keeps `width: 300` and is clipped by `overflow-hidden` (L294).
- Announcements are English literals (L210-213). Colours are hard-coded: `bg-white dark:bg-[#252522]` (L294), `bg-[#4568FF]` (L374), `text-[#4568FF]` (L423).
**Already in Calevate:** yes, vendored. Local diff: Tailwind tokens (`border-line bg-surface text-ink`, `bg-brand`, success glyph `text-brand`) plus `maxWidth: min(${width}px, calc(100vw - 24px))`. The focus shadows still embed hex (`#16a05d` / `#22c55e`). Used in: nothing. It is listed in `AWAITING_A_DECISION` in `apps/web/tests/componentConsumers.test.ts:61`.
**Fit for Calevate consoles:** Campaign dispatch progress, KB document ingest/embedding, CSV lead import, and the admin vendor-spend recompute. It does not suit a live call's status, where a persistent row in the calls list is clearer.
**Verdict: ADAPT.** The shape fits long-running client jobs, but the peek-restart bug, the missing progressbar semantics and the keyboard gap must be fixed before it leaves the quarantine list.

### load-more
**What it does:** A "Load more" button with an IntersectionObserver sentinel that auto-loads near the end of a list. It caps consecutive auto-loads, pauses after an error until a manual retry, and shows "all caught up" at the end.
**Exports / API:** `LoadMore`

| Prop | Type | Default | Notes |
|---|---|---|---|
| onLoad | `() => unknown` | required | may be async; resolving `false` marks the end (L96) |
| hasMore | `boolean` | `true` | `false` forces the `"end"` state |
| auto | `boolean` | `true` | IntersectionObserver auto-load |
| rootRef | `RefObject<Element \| null>` | — | scroll root; `null` = viewport |
| rootMargin | `string` | `"600px 0px"` | |
| maxAutoLoads | `number` | `3` | auto runs before pausing |
| labels | `Partial<Record<LoadMoreStatus,string>>` | `"Load more"`, `"Loading"`, `"Couldn’t load. Try again"`, `"You’re all caught up"` | L228-233 |
| onError | `(error: unknown) => void` | — | |
| className | `string` | `""` | |

Other exports: `useLoadMore(options)` → `{ status, paused, sentinelRef, load }`; types `LoadMoreStatus` (`"idle" | "loading" | "error" | "end"`), `UseLoadMoreOptions`, `UseLoadMoreReturn`, `LoadMoreLabels`, `LoadMoreProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). Crossfade spring `{ stiffness: 260, damping: 34, mass: 0.8 }` (L7). Spinner 0.7 s linear, infinite (L9). Faces swap `{ y: 3, blur 3px }` ↔ rest (L329-333).
- The auto-run counter resets when the sentinel leaves view (L142-143). An error sets `blocked`, which stops auto-loading until a manual `load()` (L72-77, L106). A stale or unmounted resolution is ignored via `seq` / `alive` (L94, L105).
- Reduced motion: spinner static, transitions `{ duration: 0 }` (L279, L284).
- ARIA: `aria-busy` while loading, `aria-disabled` while loading or at the end (click guarded, L301-310), `aria-label` = current text (L303). `role="status" aria-live="polite" aria-atomic` announces only the error and end states (L344-346).
**Browser APIs:** IntersectionObserver (guarded, L132).
**Weaknesses / bugs:**
- `rootRef?.current` is read once when the effect runs, and the deps hold the ref object (L145, L155). A root attached after mount is never used, and the viewport is observed instead.
- `paused` is computed but the component discards it (L269), so a paused auto-load looks identical to idle.
- 32 px tall `h-8` (L311) on touch. Hard-coded focus colours: `focus-visible:shadow-[inset_0_0_0_1px_#4568FF]` (L311).
**Already in Calevate:** yes, vendored. Local diff: tone and hover classes moved to tokens (`text-ink`, `text-ink-muted`, `hover:bg-ink/[0.04]`), `touch:h-11` added, and brand focus colours, still hex `#16a05d` / `#22c55e`. Used in: `apps/web/src/app/c/[slug]/calls/CallsScreen.tsx:22` and `apps/web/src/app/c/[slug]/leads/[leadId]/page.tsx:39`.
**Fit for Calevate consoles:** Calls list and lead activity timeline (both in use). It also suits the KB documents list, the admin QA sampling queue and the audit log.
**Verdict: ADOPT.** It is already the repo's infinite-list idiom; only the `rootRef` read timing needs a fix if a scroll container other than the viewport is ever used.

### loading-button
**What it does:** A button that runs an async action and crossfades its face idle → pending (spinner) → success (check) / error (alert), then returns to idle after `resetAfter`.
**Exports / API:** `LoadingButton`

| Prop | Type | Default | Notes |
|---|---|---|---|
| onAction | `() => unknown` | required | sync throw and rejection both caught (L72-80) |
| children | `string` | required | text only, no nodes |
| pendingLabel | `string` | `children` | |
| successLabel | `string` | `"Done"` | |
| errorLabel | `string` | `"Try again"` | |
| resetAfter | `number` (ms) | `1400` | applies to success AND error |
| disabled | `boolean` | `false` | native `disabled` |
| onError | `(error: unknown) => void` | — | |
| className | `string` | `""` | |

Other exports: `useAsyncAction({ action, resetAfter = 1400, onError })` → `{ status, run, reset, pending }`; types `AsyncActionStatus`, `UseAsyncActionOptions`, `LoadingButtonProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). `whileTap { y: 1 }` with `CELL { stiffness: 520, damping: 34, mass: 0.45 }` (L6, L246-247). Face crossfade `CROSSFADE { 260, 34, 0.8 }` (L7) between `{ opacity: 1, y: 0, blur 0 }` and `{ opacity: 0, y: 3, blur 3px }` (L262-267). Spinner 0.85 s linear, infinite (L110).
- Re-entry while pending is ignored (L53). Results from a superseded run or an unmounted component are dropped via `runId` / `alive` (L61, L83-89).
- Reduced motion: no tap offset, still spinner, `{ duration: 0 }` (L199, L222, L246).
- ARIA: `aria-label` = current label (L243), `aria-busy` plus `aria-disabled` while pending (the button stays focusable, and the click is guarded at L248-252). A sibling `role="status" aria-live="polite"` announces success/error (L278-280).
**Browser APIs:** setTimeout.
**Weaknesses / bugs:**
- The error face auto-clears after 1.4 s (L65-69) and only says "Try again". The reason must be surfaced elsewhere through `onError`; Calevate's RFC-9457 `ProblemNotice` is not wired in.
- `type="button"` is fixed (L241), so it cannot be a form submit.
- It owns its own status, which duplicates TanStack `useMutation().isPending` and can disagree with it.
- `children: string` (L170) rules out an icon or `<kbd>`.
- Colours are hard-coded: `text-emerald-600` (L227), `text-red-600` (L233), `focus-visible:border-[#4568FF]`, `dark:bg-[#252522]` (L255).
**Already in Calevate:** yes, vendored. Local diff: tokens (`border-line bg-surface text-ink`, success tone `text-brand`), `touch:h-11`, and brand focus shadows. Used in: nothing. It is listed in `AWAITING_A_DECISION`, `apps/web/tests/componentConsumers.test.ts:62`.
**Fit for Calevate consoles:** "Send test call", "Re-sync knowledge base", "Save agent", "Recompute usage" (admin), and "Retry webhook delivery".
**Verdict: ADAPT.** The feedback is useful, but it should take `status` from the caller's `useMutation` (controlled mode), allow `type="submit"`, and route errors to `ProblemNotice` rather than a 1.4 s label.

### long-press
**What it does:** A button that fires `onLongPress` after a short hold (default 550 ms). Coloured text fills in steps as the hold progresses, and the button pops on fire.
**Exports / API:** `LongPressButton`

| Prop | Type | Default | Notes |
|---|---|---|---|
| onLongPress | `() => void` | required | |
| children | `ReactNode` | required | rendered twice (base + clipped overlay) |
| duration | `number` (ms) | `550` | |
| steps | `number` | `12` | fill granularity |
| disabled | `boolean` | `false` | `aria-disabled`, not `disabled` |
| className | `string` | `""` | |

Other exports: `useLongPress(options)` → `{ bind, step, steps, holding, fired, progress }` (options add `moveTolerance = 8`, `haptic = true`, `onCancel`); types `UseLongPressOptions`, `LongPressButtonProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). Fill `CELL { stiffness: 520, damping: 34, mass: 0.45 }` (L6). Fire pop `scale: [1, 1.045, 1]` with `POP { stiffness: 640, damping: 22, mass: 0.7 }` (L7, L197-198). The fill is a `clipPath inset` on an overlay copy (L213-223).
- rAF loop; it resets 260 ms after firing (L93-95). There is no release decay, unlike hold-to-confirm.
- Reduced motion: no pop, `{ duration: 0 }` fill (L181, L197-198, L219).
- Keyboard: Space/Enter starts (L132-137); keyup on Space/Enter/Escape ends (L139-142). Blur, pointer up/cancel/leave and window blur/visibility end the hold (L103-114, L129-143).
- sr-only hint "Press and hold for {n} seconds to confirm" via `aria-describedby` (L195, L225-227).
**Browser APIs:** requestAnimationFrame, `performance.now`, `navigator.vibrate?.(12)` (L90), `setPointerCapture`, window blur / visibilitychange, setTimeout.
**Weaknesses / bugs:**
- The hint span sits inside the button (L225-227), so it is part of the accessible name as well as the description.
- `LongPressButton` does not expose `onCancel`, `moveTolerance` or `haptic` (L163-170), although the hook supports them. The hook also does not return `reset` (L153-160).
- The hint rounds `550` to "0.6 seconds" (L226).
- Hard-coded colours: `border-[#4568FF] bg-[#4568FF]/[0.07]` (L203), `text-[#4568FF]` (L220), `dark:bg-[#252522]` (L204).
- No visible affordance tells the user to hold rather than click.
**Already in Calevate:** no.
**Fit for Calevate consoles:** None. Both consoles are desktop-first, and a 550 ms long-press is a touch idiom with poor discoverability for SMB owners.
**Verdict: SKIP.** No screen needs it, and where a deliberate gesture matters, `ConfirmDialog` is the repo's established answer.

### modal
**What it does:** A portalled dialog with backdrop, title/description, scrollable body and footer. It provides a focus trap, focus restore, `inert` siblings, a nested-modal Escape stack and scroll lock with scrollbar-gap compensation.
**Exports / API:** `Modal`

| Prop | Type | Default | Notes |
|---|---|---|---|
| open / onClose | `boolean` / `() => void` | required | controlled |
| title | `ReactNode` | required | `aria-labelledby` |
| description | `ReactNode` | — | `aria-describedby` when present (L410) |
| children / footer | `ReactNode` | — | |
| closeLabel | `string` | `"Close dialog"` | |
| showClose | `boolean` | `true` | |
| closeOnEscape / closeOnBackdrop / lockScroll | `boolean` | `true` | |
| initialFocusRef | `RefObject<HTMLElement \| null>` | — | otherwise first focusable, then panel |
| container | `HTMLElement \| null` | `document.body` | portal target |
| maxWidth | `number` | `440` | px |
| maxHeight | `string` | `"min(78vh, 620px)"` | |
| className | `string` | `""` | |

Other exports: `useModal(options)` → `{ target, titleId, descriptionId, overlayProps, panelProps, close }`; types `UseModalOptions`, `ModalOverlayProps`, `ModalPanelProps`, `UseModalResult`, `ModalProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). `createPortal` (L390); the target is set in an effect, so the first render returns `null` and it is SSR-safe (L138-140, L388). Scroll lock uses `useIsomorphicLayoutEffect` (L21-22, L142-146).
- Motion: backdrop open 0.2 s `EASE [0.23, 1, 0.32, 1]`, close 0.15 s `LEAVE [0.4, 0, 1, 1]` (L364-367). Panel opens from `{ opacity: 0, scale: 0.96, y: 12 }` with `SURFACE { 420, 36, 0.9 }` and opacity 0.16 s (L370-376), and leaves to `{ scale: 0.98, y: 6 }` over 0.15 s (L378-383). Reduced motion: opacity only, duration 0 (L349-361).
- Focus: initial focus goes to `initialFocusRef`, then the first focusable, then the panel (L208-211). Tab/Shift+Tab wrap (L218-243). A `focusin` listener pulls focus back to the panel (L191-201). The previously focused element is restored on close (L213-215).
- Every sibling of the overlay in the portal target gets `inert`, and prior values are restored (L148-167). Escape closes only the top of a module-level `stack` (L169-189). Backdrop close needs pointerdown AND click outside the panel (L245-257).
- `role="dialog"`, `aria-modal`, `tabIndex -1` panel (L264-271).
**Browser APIs:** `createPortal`, document keydown/focusin listeners, `getComputedStyle`, `inert` attribute, `getClientRects`.
**Weaknesses / bugs:**
- With a custom `container`, only that container's children are made inert (L151-159). The rest of the app stays interactive, despite `aria-modal`.
- By default focus lands on the header close button (the first focusable, L211, L433-441), not on the content or the safe action.
- The scroll lock and Escape stack are module globals (L47-48, L78). They are shared correctly within one bundle, but a second copy of the module would desync them.
- Hard-coded colours: `bg-stone-900/40 dark:bg-black/65` (L406), `bg-white dark:bg-[#1D1D1A]` (L413), `shadow-[inset_0_0_0_1px_#4568FF]` (L438).
**Already in Calevate:** no. The repo has `components/confirmDialog.tsx` and `components/aiExtraDialog.tsx` built on `lib/focusTrap.ts`, plus `navDrawer.tsx`, `authn/adminIdleTimeoutModal.tsx` and `billing/ReceiptSheet.tsx`.
**Fit for Calevate consoles:** In principle, the transcript viewer, the agent test-call sheet and admin attestation forms. All of these can use the existing focus-trap stack.
**Verdict: SKIP.** It would be a second dialog system beside `useFocusTrap`/`ConfirmDialog`, which the one-way-per-problem rule forbids. Only the enter/exit motion values and the scrollbar-gap compensation (L50-69) are worth borrowing into the existing component.

### new-items-pill
**What it does:** A floating "N new items" pill for a live-updating scroll container. While the reader is scrolled away, it keeps their place, counts unread arrivals, and jumps back to the live edge on click.
**Exports / API:** `NewItemsPill`

| Prop | Type | Default | Notes |
|---|---|---|---|
| count | `number` | required | usually `unread` from `useNewItems` |
| onJump | `() => void` | required | usually `jump` |
| anchor | `"top" \| "bottom"` | `"top"` | top = feed, bottom = chat |
| label | `(n: number) => string` | `` `${n} new item(s)` `` | L131 |
| max | `number` | `99` | above this shows "`{max}+ new items`" |
| className | `string` | `""` | |

Other exports: `useNewItems<T>({ itemCount, anchor = "top", threshold = 24 })` → `{ scrollProps: { ref, tabIndex: 0, style: { overflowAnchor: "none" } }, unread, pinned, jump }`; types `NewItemsAnchor`, `UseNewItemsOptions`, `UseNewItemsResult`, `NewItemsPillProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). Arrive spring `ARRIVE { stiffness: 540, damping: 34, mass: 0.5 }` with opacity 0.16 s `EASE [0.23, 1, 0.32, 1]` (L12-14, L181-185). Enter `{ scale: 0.94, y: ±10 }`, exit `{ scale: 0.96, y: ±5, 0.16 s }` (L169-180).
- When pinned, new items keep the view at the edge. When not pinned and top-anchored, `scrollTop` is shifted to preserve position (L76-93, using `useIsoLayoutEffect` L17-18). The browser's own `overflow-anchor` is disabled (L115).
- `jump()` focuses the scroller and `scrollTo` with `"smooth"`, or `"auto"` under reduced motion (L98-112). Reduced motion also gives the pill an opacity-only, instant animation.
- ARIA: the pill's `aria-label` is the phrase (L168). A `role="status" aria-live="polite"` announcement is debounced by 700 ms (L144-151, L219-221).
**Browser APIs:** scroll listener (passive), `Element.scrollTo`, setTimeout.
**Weaknesses / bugs:**
- The scroll listener effect depends only on `[anchor, threshold]` (L54-74). If the scroller mounts after the hook (a conditional or loading render), no listener is ever attached.
- Above `max`, the phrase is the literal "new items" and ignores a custom `label` (L153). That breaks translation.
- The scroller gets `tabIndex 0` but no role or name (L115). The repo's `ScrollRegion` supplies `role="region"` + label.
- The pill is `absolute` and needs a `relative` parent (L158-161). It is 32 px tall, `h-8` (L186).
- Hard-coded colours: `bg-white dark:bg-[#1D1D1A]`, `focus-visible:border-[#4568FF]` (L186).
**Already in Calevate:** yes, vendored. Local diff: tokens (`border-line bg-surface text-ink`, brand focus) and `touch:h-11`. Used in: nothing. It is listed in `AWAITING_A_DECISION`, `apps/web/tests/componentConsumers.test.ts:63`.
**Fit for Calevate consoles:** Calls list when new calls arrive by polling, the admin QA sampling queue, the live transcript of an in-progress call (`anchor="bottom"`), and the audit/event log.
**Verdict: ADAPT.** It is the right pattern for polled lists, but it needs the late-mount listener fix, the `max` phrase routed through `label`, and the scroller wrapped in `ScrollRegion`.

### otp-input
**What it does:** A segmented one-time-code input: N single-character cells with paste and SMS autofill distribution, arrow/Home/End navigation, a shake on error and a status line.
**Exports / API:** `OtpInput`

| Prop | Type | Default | Notes |
|---|---|---|---|
| length | `number` | `6` | |
| mode | `"numeric" \| "alphanumeric"` | `"numeric"` | |
| defaultValue | `string` | `""` | uncontrolled only |
| onChange / onComplete | `(value: string) => void` | — | |
| status | `"idle" \| "error" \| "success"` | `"idle"` | |
| errorMessage / successMessage / hint | `string` | `""` | |
| label | `string` | `"Verification code"` | group name + per-cell names |
| groupEvery | `number` | `3` | visual gap (`ml-3`) |
| disabled / autoFocus | `boolean` | `false` | |
| focusOnError | `boolean` | `true` | refocuses cell 0 on error |
| className | `string` | `""` | |
| ref | `Ref<OtpInputHandle>` | — | `{ clear, focus }` |

Other exports: `useOtpInput(options)` → `{ chars, value, length, complete, focusedIndex, getCellProps, focusAt, clear }`; types `OtpMode`, `UseOtpInputOptions`, `OtpCellProps`, `UseOtpInputReturn`, `OtpStatus`, `OtpInputHandle`, `OtpInputProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). Error shake `x: [0, -5, 4, -3, 0]` over 0.32 s `EASE [0.23, 1, 0.32, 1]` (L18, L376-378). A typed character enters from `{ scale: 0.97, y: 10, blur 6px }` over 0.22 s (L357, L416-427). The caret blinks over 1.06 s with `times [0, 0.5, 0.5, 1]` (L439-448). The status swap uses `CROSSFADE { 260, 34, 0.8 }` (L17, L358).
- Cells are `type="text"` with `inputMode` numeric/text. `autoComplete="one-time-code"` is on cell 0 only (L159-161). Multi-character input from autofill or paste is spread across cells (L130-145, L193, L239-243).
- Keyboard: Backspace clears the cell or steps back, Delete clears, ArrowLeft/Right/Home/End move (L195-237). Focusing a cell after an empty one redirects to the first empty cell (L244-251).
- Reduced motion: no shake, no blur/slide, static caret (L357-358, L377, L417, L439).
- ARIA: `role="group"` + `aria-label` (L372-373). Each cell is named "{label}, character i of n" (L392), with `aria-invalid` and `aria-describedby` → a `role="status"` sr-only message (L393-394, L474-476).
**Browser APIs:** Clipboard event data (`clipboardData.getData`), `HTMLInputElement.select`.
**Weaknesses / bugs:**
- `onComplete` fires on every commit while all cells are full (L117), so editing one character of a complete code submits again.
- There is no `name` or hidden aggregate input (L37-52), so it does not participate in a native `<form>` or password-manager save.
- Each cell is a tab stop (L390), so a 6-digit code costs six Tab presses.
- Cell text is transparent and drawn by an overlay span (L395, L408-433); verify under forced-colors. Font is `text-[15px]` (L395), and below 16 px iOS zooms on focus.
- The imperative `clear` calls `focusAt(0)` twice (L339-342 plus L149).
- Hard-coded colours: `border-[#4568FF]` (L401), `border-emerald-500` (L399), `bg-stone-100/70`, `dark:bg-[#1D1D1A]` (L404).
**Already in Calevate:** yes, vendored. Local diff: tokens (`border-brand`, `bg-surface`, success `text-brand`) and responsive wrapping (`max-w-[calc(100vw-2rem)]`, `flex-wrap justify-center`). Used in: nothing. It is listed in `AWAITING_A_DECISION`, `apps/web/tests/componentConsumers.test.ts:64`.
**Fit for Calevate consoles:** Admin MFA and step-up codes. These already use a single `inputMode="numeric" autoComplete="one-time-code"` field (`components/authn/signInForm.tsx:240-241`, `components/authn/stepUpPrompt.tsx:241-242`).
**Verdict: SKIP.** The existing single-field code input works better with autofill, password managers and the keyboard, and adopting this would add a second way with a re-submit bug.

### pagination
**What it does:** Numbered page navigation with sibling/boundary windowing, ellipses, a sliding "thumb" behind the current page, rolling digits and a debounced "Page X of Y" announcement.
**Exports / API:** `Pagination`

| Prop | Type | Default | Notes |
|---|---|---|---|
| count | `number` | required | total pages |
| page | `number` | — | controlled |
| defaultPage | `number` | `1` | uncontrolled |
| siblings | `number` | `1` | pages each side of current |
| boundaries | `number` | `1` | pages pinned at each end |
| onPageChange | `(page: number) => void` | — | |
| label | `string` | `"Pagination"` | `<nav aria-label>` |
| className | `string` | `""` | |

Other exports: `usePagination(options)` → `{ page, count, items, direction, thumbIndex, canPrev, canNext, goTo, prev, next }`, the pure `paginate(page, count, siblings, boundaries)`, and types `PaginationItem` (`number | "gap-l" | "gap-r"`), `UsePaginationOptions`, `PaginationProps`.
**Behaviour that matters for reuse:**
- `"use client"` (L1). The thumb slides `x = thumbIndex * (slot + 4)` with `CELL { stiffness: 520, damping: 34, mass: 0.45 }` (L6, L203-210). Digits roll in `x: 8 * direction` over 0.18 s `EASE [0.23, 1, 0.32, 1]` (L8-9, L243-246). The slot width is `max(32, 18 + digits*8)` px (L12).
- The window is at most `2*boundaries + 2*siblings + 3` items (L33), which is 7 with the defaults. `direction` comes from a ref of the previous page, read during render (L91-95).
- Reduced motion: `{ duration: 0 }` and no roll-in (L242-246).
- ARIA: `<nav aria-label>` (L191), `aria-current="page"` (L232), each button named "Page n" (L231), and the ellipsis is `aria-hidden` (L217). Prev/next use `aria-disabled` with a guarded click (L195-198, L257-260). An sr-only `role="status"` says "Page X of Y" after 500 ms (L181-188, L266-268).
**Browser APIs:** setTimeout.
**Weaknesses / bugs:**
- It is fixed-width and does not fit 320 px. 7 slots × 32 px + 6 × 4 px gaps + 2 arrows × 32 px + 2 × 4 px gaps = 320 px for 1-digit counts, and 3-digit counts reach 390 px. The upstream wrapper is a plain `<div className="relative">` (L202).
- Labels are English literals: "Previous page", "Next page", "Page {n}", "Page X of Y" (L184, L195, L231, L258). No props exist to translate them.
- The status region also announces on first mount (L181-188), not only on change.
- It has no page-size selector or "showing a–b of n" summary.
- Hard-coded colours: thumb `bg-stone-800 dark:bg-stone-100` (L209) and `focus-visible:shadow-[inset_0_0_0_1px_#4568FF]` (L19, L234).
**Already in Calevate:** yes, vendored. Local diff: the number strip is wrapped in `ScrollRegion` (`@/components/ui`) with a hidden scrollbar, plus `shrink-0` / `max-w-full` for narrow screens, a thumb in `bg-brand-strong`, and token colours. Used in: `apps/web/src/app/c/[slug]/leads/LeadsFooter.tsx:4`.
**Fit for Calevate consoles:** The leads CRM table (in use), plus the calls list if it moves to offset paging, admin tenants, the DNC list and the audit log.
**Verdict: ADOPT.** It is already in use with the 320 px fix applied locally; the remaining work is translatable labels and suppressing the mount-time announcement.

### password-strength
**What it does:** Segmented strength meter plus a checklist of rules for a password value, with a debounced screen-reader announcement. Ships a headless hook as well.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `string` | required | the password being typed |
| rules | `readonly PasswordRule[]` | `defaultPasswordRules` | length>=12, upper+lower, digit, symbol (L38-47) |
| labels | `readonly string[]` | `["Empty","Weak","Fair","Good","Strong"]` | indexed by score (L49) |
| announceDelay | `number` | `700` | ms before live-region text settles |
| showRules | `boolean` | `true` | renders the checklist |
| className | `string` | `""` | |

Other exports: `usePasswordStrength(value, opts)` returning `{score,max,label,rules,guessable,announcement}`; `defaultPasswordRules`; types `PasswordRule`, `EvaluatedRule`, `UsePasswordStrengthOptions`, `PasswordStrengthState`, `PasswordStrengthProps`.
**Behaviour that matters for reuse:**
- Springs: `CELL` stiffness 520 / damping 34 / mass 0.45 (bars, stagger `i * 0.03`s); `CROSSFADE` 260 / 34 / 0.8 (labels, rule ticks). `INSTANT` `{duration:0}` (L6-8).
- Score: 0 when empty; forced to 1 if `guessable` (COMMON/RUN/RUN_UP regexes, L10-12); else `min(rules.length, max(1, passed))` (L65-66).
- `useReducedMotion()` swaps every transition to `INSTANT`; no motion otherwise changes.
- ARIA: `role="meter"`, `aria-label="Password strength"`, `aria-valuemin/max/now/valuetext` (L147-152); per-rule `sr-only` "met"/"not met" (L238); `aria-live="polite"` paragraph debounced by `setTimeout(announceDelay)` with cleanup (L89-96, L244).
- "use client". No window access; SSR-safe.

**Browser APIs:** timers (`setTimeout`) only.
**Weaknesses / bugs:**
- Default rules are composition rules (case/digit/symbol, L41-46). Calevate's policy is length-per-realm plus blocklist (`components/authn/setPasswordForm.tsx:17-19,124`, `lib/authn/password`), so the default meter would contradict the server; rules must be replaced.
- COMMON regex is prefix-anchored only (`^(?:password|...)`, L10): "mypassword123" is not flagged.
- Hard-coded tones `bg-red-500`, `bg-amber-500`, `bg-emerald-500`, `bg-stone-300` (L110-115) and `bg-stone-200` tracks (L159) instead of tokens.
- "Commonly guessed" text is `aria-hidden` (L190) and always in the DOM at opacity 0; only reaches SR via the debounced announcement.
- Meter is not associated with the input (no `aria-describedby` wiring); caller must do it.

**Already in Calevate:** no.
**Fit for Calevate consoles:** set-password / change-password forms (`setPasswordForm.tsx`, `changePasswordForm.tsx`), team invite acceptance. Only the hook-plus-meter shape is useful once rules mirror `MIN_CHARS_BY_REALM` and the blocklist.
**Verdict: ADAPT** — good a11y skeleton, but the default composition rules conflict with the repo's length/blocklist policy and colours need tokens.

### popover
**What it does:** Click-triggered non-modal dialog anchored to its own trigger button, with side flipping, viewport/boundary clamping, an arrow and spring enter/exit.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| trigger | `ReactNode` | required | rendered inside the component's own `<button>` |
| children | `ReactNode` | required | panel content |
| label | `string` | required | `aria-label` of the dialog |
| open / defaultOpen / onOpenChange | `boolean` / `boolean` / `(open)=>void` | `undefined` / `false` / - | controlled or uncontrolled |
| side | `"top"\|"right"\|"bottom"\|"left"` | `"bottom"` | flips to opposite if no room (L118) |
| align | `"start"\|"center"\|"end"` | `"center"` | |
| offset / padding / arrowSize | `number` | `10` / `8` / `9` | px |
| boundary | `RefObject<HTMLElement \| null>` | - | clamp region instead of viewport |
| triggerClassName / className | `string` | `""` | |

Other exports: `usePopover<A>(opts)` returning `{anchorRef, floatingRef, panelRef, contentRef, arrowRef, side, update}`; types `PopoverSide`, `PopoverAlign`, `UsePopoverOptions`, `UsePopoverResult`, `PopoverProps`.
**Behaviour that matters for reuse:**
- Enter: `CROSSFADE` spring 260 / 34 / 0.8 with opacity `{duration:0.14, ease:[0.23,1,0.32,1]}`; from `scale 0.95` plus 6px offset by side (L38-43, L341-358). Exit: `scale 0.97`, `duration 0.13`, same ease.
- Reduced motion: opacity only, enter `duration:0`, exit `duration:0.1` (L342-357).
- `useIsoLayoutEffect` (`typeof document` check, L19) for SSR; positioning writes `style.left/top/maxWidth/maxHeight/transformOrigin` imperatively (L93-179). Min panel 160x88 (L16-17).
- ARIA: trigger `aria-haspopup="dialog"`, `aria-expanded`, `aria-controls` only while open (L314-316); panel `role="dialog"`, `aria-label`, `tabIndex=-1`.
- Focus: panel focused on open with `preventScroll` (L279-282); Escape (document capture listener) returns focus to trigger (L294-299). No focus trap; blur outside closes (L328-333); outside `pointerdown` closes (L287-292).
- No `createPortal`: rendered inline as `fixed left-0 top-0 z-50` (L327), with an origin-correction trick for transformed ancestors (L155-159).

**Browser APIs:** ResizeObserver, rAF, window scroll (capture) + resize listeners, all cleaned up (L189-213).
**Weaknesses / bugs:**
- No portal: an ancestor with `overflow:hidden` plus `transform`/`filter`/`contain` clips it; z-50 can lose to sibling stacking contexts (L327).
- Trigger is always the component's own `<button>` (L311); cannot wrap an existing icon button or table-row action without `usePopover`.
- Escape listener calls `stopPropagation` in capture phase on `document` (L296), which also swallows Escape for any nested dialog/combobox inside the panel.
- Closing via outside click does not restore focus to the trigger (only Escape does, L297).
- Hard-coded colours: `bg-white`, `dark:bg-[#1D1D1A]`, `border-stone-200`, `focus-visible:border-[#4568FF]` (L318, L359, L365).
- Origin correction reads back `parseFloat(wrap.style.left/top)` (L156-157), so anything else writing those styles breaks placement.

**Already in Calevate:** no. `app/c/[slug]/leads/ColumnChooser.tsx:13-17` uses a native `<details>` and names "shadcn/ui's Popover" as the eventual answer.
**Fit for Calevate consoles:** leads column chooser, saved-view menu, call-row "more" info, credit/usage tooltips-with-content, attestation details in admin ops.
**Verdict: ADAPT** — positioning hook is solid, but it needs a portal, token colours and an `asChild`-style trigger before it can replace `<details>`.

### progress-bar
**What it does:** Labelled determinate/indeterminate progress bar with a percent readout and a completion announcement.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | `number \| null` | required | `null` = indeterminate |
| max | `number` | `100` | `<=0` treated as fraction 0 (L33) |
| label | `string` | `"Progress"` | visible, `aria-labelledby` target |
| pendingLabel | `string` | `"Working"` | shown/announced when indeterminate |
| completeLabel | `string` | `"Complete"` | announced at 100% |
| className | `string` | `""` | |

No other exports besides `ProgressBarProps`.
**Behaviour that matters for reuse:**
- Fill: `scaleX` spring `FILL` 210 / 34 / 0.9 (L7, L91). Readout crossfade `CROSSFADE` 260 / 34 / 0.8.
- Indeterminate sweep: 2/5-width bar, `x` from `-100%` to `250%`, `duration 1.25`, `ease "easeInOut"`, `repeat: Infinity`; opacity `0.18`s (L96-106).
- Reduced motion: `INSTANT` transitions and the sweep is NOT rendered (L95).
- ARIA: `role="progressbar"`, `aria-labelledby`, `aria-valuemin/max`; `aria-valuenow`/`aria-valuetext` omitted when indeterminate (L37-42, L78-83). Live region `aria-live="polite"` with completeLabel/pendingLabel (L111-113).
- "use client"; `useId`; no window access.

**Browser APIs:** none.
**Weaknesses / bugs:**
- Reduced motion + indeterminate shows an empty track with no visual cue except the "Working" text (L91, L95).
- `exit={{opacity:0}}` on the sweep (L101) never runs: there is no `AnimatePresence` wrapper.
- Live region announces `pendingLabel` immediately and then never again for intermediate progress (by design), but it is rendered from first paint, so some SRs will not announce initial content.
- Upstream colours `bg-[#4568FF]`, `bg-stone-200/60`, `dark:bg-[#1D1D1A]` (L84, L89, L98); fixed in the Calevate copy.

**Already in Calevate:** yes — vendored at `components/interior/progress-bar.tsx`, local diff: colours swapped to tokens (`text-ink`, `text-ink-muted`, `bg-ink/[0.06]`, `bg-brand`, `dark:bg-brand-bright`), behaviour unchanged; used in: nothing — listed in `tests/componentConsumers.test.ts:65` `AWAITING_A_DECISION`.
**Fit for Calevate consoles:** KB document ingestion/embedding progress, CSV lead import, campaign dispatch progress (dialled of total), credit balance consumption, admin backfill jobs.
**Verdict: ADOPT** — already tokenised; wire it into KB upload and campaign progress, adding a static reduced-motion indeterminate cue.

### reading-progress
**What it does:** Thin scroll-progress bar for a page, element or scroll container, quantised into steps, with optional "N min left" estimate.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| target | `ScrollRef` | - | element whose read-through is measured |
| scroller | `ScrollRef` | - | scroll container; else window |
| steps | `number` | `24` | quantisation of progress |
| words | `number` | `0` | enables minutes estimate when >0 |
| wordsPerMinute | `number` | `220` | |
| label | `string` | `"Reading progress"` | `aria-label` |
| doneLabel | `string` | `"End"` | shown as "End · N min" |
| className | `string` | `""` | |

Other exports: `useReadingProgress(opts)` returning `{step,steps,progress,percent,minutesLeft,totalMinutes,complete}`; types `ScrollRef`, `UseReadingProgressOptions`, `ReadingProgressState`, `ReadingProgressProps`.
**Behaviour that matters for reuse:**
- Fill `FILL` spring 210 / 34 / 0.9; crossfade 260 / 34 / 0.8; tick draw `{duration:0.3, ease:[0.23,1,0.32,1], delay:0.08}` (L6-10).
- Reduced motion: all transitions `INSTANT` (L141-142, L211).
- ARIA: `role="progressbar"`, `aria-valuemin 0`, `aria-valuemax=steps`, `aria-valuenow=step`, `aria-valuetext` "N% read[, M min left]" (L153-159). Readouts `aria-hidden`.
- Window access only inside effects/callbacks; SSR-safe. rAF-throttled reads (L78-81).

**Browser APIs:** rAF, scroll (passive) + resize listeners, ResizeObserver (guarded `typeof ResizeObserver`, L86-87); all cleaned up (L96-102).
**Weaknesses / bugs:**
- Refs are read once per effect run (L74-75); if `target.current` is attached after mount (conditional render) it is never observed until deps change.
- `progressbar` semantics for a passive scroll indicator adds SR noise; nothing is live, but it is a focusable-in-browse-mode widget with little value.
- Hard-coded `bg-[#4568FF]`, `dark:bg-[#93B0FF]`, `bg-stone-100`, `dark:bg-[#1D1D1A]` (L160, L163).
- English-only "min left" string built inline (L145).

**Already in Calevate:** no.
**Fit for Calevate consoles:** long transcript view in a call detail drawer, legal pages (`/legal/*` already has a reader component), KB document preview. Marginal value in data consoles.
**Verdict: SKIP** — consoles are table/form-driven; a scroll meter on transcripts adds little over the native scrollbar.

### reorder-list
**What it does:** Vertical drag-to-reorder list (motion `Reorder`) with a full keyboard grab/move/drop/cancel model and live announcements.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | `readonly T[]` | required | |
| getId / getLabel | `(item:T)=>string` | required | label is used in announcements |
| onReorder | `(next:T[])=>void` | required | fires on every move |
| onCommit | `(next:T[])=>void` | - | fires on drop / keyboard step when not grabbed |
| disabled | `boolean` | `false` | |
| children | `(item:T)=>ReactNode` | required | row renderer |
| label | `string` | required | `aria-label` of group |
| className | `string` | `""` | |

Other exports: `useReorderList(opts)` returning `{grabbed,dragging,spoken,grab,drop,cancel,step,rowKeyDown,onDragStart,onDragEnd}`; types `UseReorderListOptions`, `ReorderListProps`.
**Behaviour that matters for reuse:**
- Layout spring `CELL` 520 / 34 / 0.45; `whileDrag {scale:1.02}` (L6, L210-211).
- Reduced motion: `INSTANT` transition, no drag scale (L208-211).
- Keyboard (L98-119): Space/Enter grab or drop, ArrowUp/Down move while grabbed, Escape restores snapshot; blur while held cancels (L209). Only acts when `event.target === currentTarget` (L100).
- ARIA: each row `role="button"`, `aria-pressed={held}`, `aria-describedby` hint, `tabIndex 0` (L202-205); `role="status" aria-live="polite"` announcements (L245-247).

**Browser APIs:** none directly (motion drag handles pointer events).
**Weaknesses / bugs:**
- Row content is wrapped in `aria-hidden` (L234): any button/link/input rendered via `children` is hidden from AT while still focusable.
- `role="button"` on each `Reorder.Item` (an `<li>`) overrides listitem semantics inside the `<ul>` group (L185-205).
- `style={{touchAction:"pan-x"}}` with whole-row `drag="y"` (L200, L212): on touch, vertical page scroll over the list is blocked; no dedicated handle.
- Pointer drag start/end produce no "grabbed" announcement, only "dropped" (L121-139).
- `step` emits `onCommit` per keystroke when not grabbed (L93), but `rowKeyDown` never calls `step` unless held, so that path is unreachable from the UI.
- Hard-coded `bg-white`, `dark:bg-[#1D1D1A]`, `border-[#4568FF]` (L213-220).

**Already in Calevate:** no.
**Fit for Calevate consoles:** extraction-schema field ordering (drives CRM columns), campaign call-sequence / retry ladder ordering, agent knowledge-base source priority, leads column order.
**Verdict: ADAPT** — strong keyboard model, but needs a drag handle, un-hidden content and listitem semantics before it hosts interactive rows.

### ripple
**What it does:** Material-style press ripple on a button, pointer- and keyboard-triggered, with minimum visible time and bounded concurrent ripples.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| children | `ReactNode` | required | |
| onPress | `() => void` | - | bound to `onClick` |
| disabled | `boolean` | `false` | |
| max | `number` | `4` | concurrent ripples |
| tintClassName | `string` | `"bg-stone-800/15 dark:bg-white/20"` | |
| className | `string` | `""` | |

Other exports: `useRipple({disabled,max,minVisible=220,fade=320})` returning `{bind, ripples, fadeDuration}`; types `RippleSpec`, `UseRippleOptions`, `RippleProps`.
**Behaviour that matters for reuse:**
- `BLOOM {duration:0.5, ease:"linear"}` scale from 0 to cover farthest corner (base 40px, L7-8, L60-81); opacity in `0.07`s linear, out `fade/1000`s with `ease [0.23,1,0.32,1]` (L233-238). Min visible 220ms before release (L95-98).
- Reduced motion: ripple starts at full scale (no bloom), opacity fade retained (L231, L234).
- Keyboard: Space/Enter spawn a centred ripple, keyup releases; ignores `e.repeat` (L170-180). Pointer capture on down (L159).
- Releases all on window blur and `visibilitychange` hidden (L135-144); timers cleared on unmount (L146-152).

**Browser APIs:** `performance.now`, `setTimeout`, pointer capture, window `blur`, `visibilitychange`.
**Weaknesses / bugs:**
- `useRipple` exposes `minVisible`/`fade` but `Ripple` does not forward them (L204).
- Hard-coded `bg-white`, `dark:bg-[#1D1D1A]`, `border-stone-200`, `ring-stone-400` (L213).
- `onKeyUp` accepts Escape as a release key (L177) but the native button still fires click on Space keyup, so no cancel semantics.
- Decorative only; no ARIA concerns, but it duplicates the button styling already in `components/ui` (`SECONDARY_BUTTON_SM` etc.).

**Already in Calevate:** no.
**Fit for Calevate consoles:** none needed; Calevate buttons already have a pressed state and the visual language is not Material.
**Verdict: SKIP** — decorative effect with no functional gain that adds a second button style.

### scroll-spy
**What it does:** Horizontal "On this page" chip nav that highlights the section currently in view and smooth-scrolls to sections on click.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| sections | `ScrollSpySection[]` (`{id,label}`) | required | ids must exist in the DOM |
| offset | `number` | `96` | px activation line from top |
| root | `RefObject<HTMLElement \| null>` | - | scroll container; else window |
| onChange | `(id)=>void` | - | |
| label | `string` | `"On this page"` | `nav` `aria-label` |
| className | `string` | `""` | |

Other exports: `useScrollSpy(opts)` returning `{activeId, activeIndex, scrollTo, getLinkProps, announce}`; types `ScrollSpySection`, `UseScrollSpyOptions`, `ScrollSpyProps`.
**Behaviour that matters for reuse:**
- Thumb `layoutId` spring `CELL` 520 / 34 / 0.45 (L6, L272-276). Click lock released after `RELEASE` 900ms, or on wheel/touchstart (L8, L108-115, L193-198). Announce after `SETTLE` 420ms (L7, L147-150).
- Reduced motion: `layoutId` dropped (no thumb glide), `scrollTo` and chip `scrollIntoView` use `"auto"` (L166, L250, L273).
- Activation line slides with scroll ratio so the last section can activate (L59-62); bottom-of-page forces last (L75-80).
- ARIA: `nav aria-label`, `ol` of links with `aria-current="location"` (L206); target gets `tabindex=-1` and focus with `preventScroll` (L190-191); `aria-live="polite"` label announce (L307-309).
- Modified clicks (meta/ctrl/shift/non-primary) fall through to native `href="#id"` (L208).

**Browser APIs:** rAF, ResizeObserver, scroll/resize/wheel/touchstart listeners, `scrollTo`, `scrollIntoView`, setTimeout; cleaned up (L126-135).
**Weaknesses / bugs:**
- `scrollIntoView({block:"nearest"})` on the active chip (L248-254) runs on mount and every change and can scroll the window vertically if the nav is off-screen.
- `ResizeObserver` constructed without a guard (L117), unlike reading-progress.
- `getElementById` lookups (L68, L120, L159) assume unique global ids; two instances or ids with tenant-generated values can collide.
- Hard-coded `bg-stone-800`, `dark:bg-stone-100`, `bg-stone-100/80`, `dark:bg-[#1D1D1A]` (L258, L276).
- `settleTimer` in a ref shared across effect runs (L147-154); works, but cleanup clears whichever timer is current.

**Already in Calevate:** no.
**Fit for Calevate consoles:** long settings pages (organisation, team, models, compliance), agent configuration page with many sections, admin tenant detail.
**Verdict: ADAPT** — useful for long settings/agent pages once the mount-time `scrollIntoView` is gated and colours tokenised.

### segmented-control
**What it does:** Radio-group segmented control with a sliding thumb that masks a second inverted label layer for crisp text during the slide.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| options | `SegmentedOption[]` (`{value,label,disabled?}`) | required | |
| label | `string` | required | radiogroup `aria-label` |
| value / defaultValue | `string` | - / `options[0].value` | controlled or uncontrolled |
| onValueChange | `(value)=>void` | - | only fires when value changes (L74) |
| className | `string` | `""` | |

Other exports: types `SegmentedOption`, `SegmentedControlProps`.
**Behaviour that matters for reuse:**
- Thumb position is a motion value animated with `CELL` spring 520 / 34 / 0.45 (L12, L58-69); thumb and mask translate in opposite percentages (L59-60).
- Reduced motion: `pos.set(index)` jump (L63-65).
- ARIA: `role="radiogroup"` + `aria-label`; each segment a `<button role="radio" aria-checked>` with `aria-disabled` and sr-only label; roving tabindex (`tabIndex` 0 on selected, -1 otherwise) (L119-190).
- Keys: Arrow Right/Down next, Left/Up previous (wrap, skipping disabled), Home first enabled, End last enabled; arrow keys move focus AND select (L101-115).
- "use client"; no window access.

**Browser APIs:** none.
**Weaknesses / bugs:**
- Equal-width grid with `whitespace-nowrap` labels (L14-15, L41) and `inline-block` root: 4+ long labels overflow at 320px; no wrapping or scroll.
- Visible labels are `aria-hidden` spans and the real buttons carry `sr-only` text (L128-140, L190); fine for AT, but browser find-in-page/translate hit the hidden layer.
- Disabled options are buttons without the `disabled` attribute (only `aria-disabled`, guarded `onClick`, L183-185) and share `cursor-default` (L188), so pointer users get no affordance that they are unavailable.
- Hard-coded `bg-stone-800`, `dark:bg-stone-100`, `text-stone-50`, `bg-stone-100/70`, `dark:bg-[#1D1D1A]`, focus `#4568FF` (L121, L145, L161, L188).
- If `value` matches no option, index falls back to 0 visually (L51) but `aria-checked` marks option 0 while the real value is something else.

**Already in Calevate:** no (billing page has its own `role="radiogroup"`: `app/c/[slug]/billing/page.tsx`).
**Fit for Calevate consoles:** calls list filter (All / Inbound / Outbound), usage period (Day / Week / Month), voice tier picker (Clear / Studio), inbound vs outbound agent toggle, admin health time range.
**Verdict: ADOPT** — correct radiogroup semantics and roving focus; only colours need tokenising, keep option counts small.

### show-more
**What it does:** Clamps content to N lines and expands to a capped height (scrollable beyond it) with a fade veil and a toggle button.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| children | `ReactNode` | required | |
| lines | `number` | `3` | collapsed height in line-heights |
| maxHeight | `number` | `320` | px cap when expanded; region scrolls past it |
| defaultExpanded / expanded / onExpandedChange | `boolean` / `boolean` / `(b)=>void` | `false` / - / - | |
| moreLabel / lessLabel | `string` | `"Show more"` / `"Show less"` | |
| label | `string` | `"Details"` | region `aria-label` when scrollable |
| className | `string` | `""` | |

Other exports: `useShowMore(opts)` returning `{contentRef, expanded, open, toggle, setExpanded, height, collapsedHeight, fullHeight, expandable, capped, scrollable}`; types `UseShowMoreOptions`, `UseShowMoreResult`, `ShowMoreProps`.
**Behaviour that matters for reuse:**
- Height spring `DISCLOSE` 190 / 30 / 1; veil, labels and chevron `SMALL` 700 / 46 / 0.5 (L10-22).
- Reduced motion: all `INSTANT` (L180, L195, L216).
- Measures `line-height` (fallback `fontSize * 1.5`) and `scrollHeight` in `useIsomorphicLayoutEffect` + ResizeObserver (L79-103). Pre-measure fallback `maxHeight: "${lines}lh"` (L182).
- ARIA: button `aria-expanded`, `aria-controls`; region gets `role="region"`, `aria-label`, `tabIndex 0` only when scrollable (L175-177, L204-205). Collapsing scrolls region to top (L160-162).
- Button hidden with `invisible pointer-events-none` when not expandable (L207).

**Browser APIs:** ResizeObserver, `getComputedStyle`, `scrollTo`.
**Weaknesses / bugs:**
- Clipped content stays in the accessibility tree and tab order when collapsed (no `inert`), so focusable children below the fold are reachable but invisible (L172-189).
- `ResizeObserver` unguarded (L100).
- `lh` unit fallback (L182) unsupported in older browsers; first paint may show full content.
- Upstream veil `from-white ... dark:from-stone-900` (L196) mismatches any non-white surface; Calevate copy uses `from-surface`.
- Line-height from the wrapper only; children with different `line-height` clamp mid-line.

**Already in Calevate:** yes — vendored at `components/interior/show-more.tsx`, local diff: tokens (`text-ink`, `from-surface`, `border-line`, `bg-surface`, brand green focus `#16a05d`/`#22c55e`), adds `touch:h-11` tap target and `touchAction: "manipulation"` on the button, drops an eslint comment; used in: nothing — listed in `tests/componentConsumers.test.ts:66` `AWAITING_A_DECISION`.
**Fit for Calevate consoles:** call summary / extraction notes in call detail, long agent prompts in agent view, KB document excerpts, admin QA reviewer notes, consent/DNC reason text.
**Verdict: ADOPT** — already tokenised and touch-sized; add `inert` on the clipped region when collapsed.

### skeleton-swap
**What it does:** Fixed-height box that crossfades between a delayed, minimum-duration skeleton and the real children to avoid flash-of-skeleton.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| ready | `boolean` | required | |
| children | `ReactNode` | required | |
| lines / lineHeight / barHeight | `number` | `3` / `21` / `9` | default skeleton geometry |
| reserve | `number` | `lines * lineHeight` | box height in px |
| delay | `number` | `120` | ms before skeleton appears |
| minVisible | `number` | `380` | ms skeleton stays once shown |
| label | `string` | - | `aria-label` + "<label> loaded" status |
| skeleton | `ReactNode` | - | custom placeholder |
| className | `string` | `""` | |

Other exports: `useSkeletonSwap({ready, delay=120, minVisible=380})` returning `{showSkeleton, busy}`; types `UseSkeletonSwapOptions`, `SkeletonSwapProps`.
**Behaviour that matters for reuse:**
- `CROSSFADE` spring 260 / 34 / 0.8 (L6-11); content animates opacity, `scale 0.99`, `blur(4px)`; skeleton exits with `blur(3px)` (L117-144).
- Reduced motion: opacity only, `duration:0` (L118-126, L141-144).
- Timers set/cleared per effect run (L34-48). Skeleton bar widths deterministic from `WIDTHS` (L13-18).
- ARIA: `aria-busy={!ready}` on shell; skeleton `aria-hidden`; optional `role="status"` "label loaded" (L106-107, L169-173); shell gets `tabIndex 0` only when content overflows (L94, L109).

**Browser APIs:** `setTimeout`, `performance.now`, ResizeObserver (guarded, L92).
**Weaknesses / bugs:**
- Fixed `height: box` (L110): real content taller than `reserve` scrolls inside the box instead of growing; callers must size `reserve` per screen.
- `aria-label` on a role-less `div` (L107) is ignored by most AT.
- Children are rendered (opacity 0) while loading, so stale or empty content is still in the AT tree under the skeleton (L113-133).
- Status span renders "loaded" text on first paint when `ready` starts true (L171).
- Upstream colours `bg-stone-200 dark:bg-white/15`, `text-stone-700` (L111, L155); Calevate copy uses `text-ink`, `bg-ink/10`.

**Already in Calevate:** yes — vendored at `components/interior/skeleton-swap.tsx`, local diff: colours only (`text-ink`, skeleton `bg-ink/10`); used in: nothing — listed in `tests/componentConsumers.test.ts:67` `AWAITING_A_DECISION`.
**Fit for Calevate consoles:** TanStack Query `isPending` states for billing balance cards, usage KPI tiles, agent summary cards, admin system-health tiles (fixed-size tiles suit the fixed `reserve`).
**Verdict: ADOPT** — the delay/minVisible hook is exactly right for Query loading; use it on fixed-size cards, not on variable-length lists.

### slider-detents
**What it does:** Custom horizontal slider whose thumb snaps magnetically to labelled detent values within a pull radius, with keyboard detent jumps and optional haptics.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| value / onValueChange | `number` / `(v)=>void` | required | controlled only |
| min / max / step | `number` | `0` / `100` / `1` | |
| detents | `readonly (number \| {value,label?})[]` | `[]` | |
| pull | `number` | `range * 0.045` | snap radius in value units (L73) |
| label | `string` | `"Value"` | visible, via `aria-labelledby` |
| format | `(v)=>string` | `String` | readout + `aria-valuetext` |
| disabled | `boolean` | `false` | |
| haptic | `boolean` | `true` | `navigator.vibrate(6)` on detent entry |
| className | `string` | `""` | |

Other exports: `useSliderDetents(opts)` (also takes `thumbSize`, `label`, `labelledBy`) returning `{trackRef, trackProps, detents, activeDetent, percent, dragging, valueText}`; types `SliderDetent`, `UseSliderDetentsOptions`, `SliderDetentsProps`.
**Behaviour that matters for reuse:**
- Carriage `useSpring` stiffness 520 / damping 34 / mass 0.45 (L11, L277); thumb grab scale 1.08 with `GRAB` 700 / 46 / 0.5; suffix crossfade 260 / 34 / 0.8 (L13-19).
- Reduced motion: `carriage.jump(target)` instead of `set`, other transitions `INSTANT` (L280-284).
- ARIA: track is `role="slider"`, `tabIndex 0`, `aria-orientation`, `aria-valuemin/max/now`, `aria-valuetext` ("value, detent label"), `aria-disabled`, `aria-labelledby` (L159-170).
- Keys: Arrows +/- step; Shift+Arrow and PageUp/PageDown jump to next/previous detent (or min/max); Home/End (L189-210).
- Pointer capture + focus on pointerdown, `touchAction: none`; releases on pointerup/cancel/lostcapture and window blur (L147-150, L171-188).

**Browser APIs:** `navigator.vibrate`, pointer capture, window `blur`; `Array.prototype.toSorted`/`findLast` (ES2023).
**Weaknesses / bugs:**
- `toSorted` / `findLast` (L138-140) need ES2023 runtime; older Safari/Android WebViews throw on PageUp/Shift+Arrow.
- Keyboard step `commit(value + direction * step)` (L197) does not re-snap to the step grid if `value` is off-grid (e.g. landed on a detent).
- Disabled track keeps `tabIndex 0` (L161) and only `pointer-events-none` (L341), so it is still focusable; keyboard is ignored silently.
- Fill bar is a `w-[2000px]` slab (L356): tracks wider than 2000px show a gap.
- `haptic` default `true` (L59, L250) vibrates on detent entry without user opt-in.
- Hard-coded `bg-stone-800`, `dark:bg-stone-100`, `border-white`, `bg-stone-200` (L347, L356, L385).

**Already in Calevate:** no (`components/marketing/roiCalculator.tsx` uses native `type="range"`).
**Fit for Calevate consoles:** agent settings with recommended values (speaking rate, silence timeout, interruption sensitivity), campaign concurrency / calls-per-minute cap, low-credit alert threshold, admin QA sampling percentage.
**Verdict: ADAPT** — detents map well to "recommended" agent tuning values, but fix ES2023 calls, disabled focus and default haptics first.

### sortable-table
**What it does:** ARIA-table (div grid) with click-to-sort headers that animate rows to new positions, plus an optional single-row "follow" mark.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| rows | `T[]` | required | client-side, all rendered |
| columns | `SortableColumn<T>[]` | required | `{id, header, width?, align?, numeric?, sortable?, value?, cell?}` |
| getRowId | `(row)=>string` | required | |
| label | `string` | required | table `aria-label` |
| rowHeight | `number` | `44` | px, fixed |
| maxHeight | `number` | - | body scroll cap |
| sort / defaultSort / onSortChange | `SortState \| null` / same / `(next)=>void` | - / `null` / - | controlled or uncontrolled |
| markable / onMarkChange | `boolean` / `(id\|null)=>void` | `false` / - | single "Follow" toggle column |
| getRowLabel | `(row)=>string` | - | names the mark button |
| className | `string` | `""` | |

Other exports: `useSortableRows(opts)` (adds `getValue`, `restoreOriginal=true`) returning `{sort, ordered, toggle, ariaSort}`; types `SortDirection`, `SortState`, `SortableColumn`, `OrderedRow`, `UseSortableRowsOptions`, `SortableTableProps`.
**Behaviour that matters for reuse:**
- Rows are absolutely positioned and animate `y: index * rowHeight` with `CELL` 520 / 34 / 0.45 and stagger `min(index, 8) * 0.018`s (L6, L15-16, L337-344). Arrow `SMALL` 700 / 46 / 0.5. Row dividers hide during reorder (`HIDE 0.12s ease [0.4,0,1,1]`, `SHOW 0.25s ease [0.23,1,0.32,1]`, settle 380ms) (L10-17, L413-427).
- Sort cycle asc, desc, original (L90-105); empty values always last; `Intl.Collator("en", {numeric:true, sensitivity:"base"})`; stable ties by original index (L60-84).
- Reduced motion: `duration 0` everywhere and no divider hide (L191, L341, L285).
- ARIA: `role="table"`, `aria-rowcount`, `aria-colcount`, `rowgroup`/`row`/`columnheader`/`cell`, `aria-sort` on headers, `aria-rowindex`, `aria-current` on marked row, `aria-pressed` mark buttons, `role="status" aria-live="polite"` sort message (L220-431).
- Settle timer cleared on unmount (L157-162).

**Browser APIs:** `setTimeout`, `Intl.Collator`.
**Weaknesses / bugs:**
- Client-side sort of the rows passed in; with server pagination it sorts only the current page. No virtualization: every row is mounted and body height is `rows.length * rowHeight` (L310).
- Fixed `rowHeight` with `truncate` cells (L348, L397): no wrapping, multi-line cells impossible; at 320px `minmax(0,1fr)` columns truncate to nothing and there is no horizontal scroll.
- `restoreOriginal` exists in the hook but is not forwarded by `SortableTable` (L172-179).
- Mark column copy hard-coded "Follow" (L235, L362).
- `getValue` uses `columns.find` per comparison (L164-169), O(n log n * cols); `columns` identity change recomputes order each render.
- Hard-coded `bg-white`, `dark:bg-[#1D1D1A]`, `border-stone-200`, `bg-[#4568FF]` (L218, L356-358).

**Already in Calevate:** no.
**Fit for Calevate consoles:** small bounded tables only: admin vendor spend by vendor, tenant list (if small), voices catalogue, agents list, billing credit lots. Not the leads CRM table (server pagination, saved views, column chooser) or calls list.
**Verdict: ADAPT** — good sort semantics and announcements for small admin tables, but it must accept server-driven sort and token colours, and should not be used for paginated CRM data.

### sticky-header
**What it does:** A card with its own scroll container whose large title/subtitle header condenses into a compact single-line title as the inner content scrolls.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| title | string | required | Also the `aria-label` of the scroll region (l.102) |
| children | ReactNode | required | Scrolling body |
| subtitle | string | undefined | Shown only in expanded state |
| leading | ReactNode | undefined | Slot left of title, `pointer-events-auto` |
| actions | ReactNode | undefined | Slot right of title |
| expandedHeight | number | 68 | px |
| compactHeight | number | 48 | px |
| maxHeight | number | 320 | px, max height of the scroll region |
| className | string | "" | Outer card |

Other exports: `useCondense<T>({ range = 48 })` -> `{ ref, progress: MotionValue<number>, condensed }`; types `UseCondenseOptions`, `UseCondenseResult`, `StickyHeaderProps`.
**Behaviour that matters for reuse:**
- Spring `SMOOTH = { stiffness: 240, damping: 44, mass: 0.6 }` (l.14) applied via `useSpring` to scroll progress; condense range = `max(64, travel*3)` (l.73).
- Transforms: big title `opacity [0,0.45]->[1,0]`, `scale 1-0.05p`; small title `opacity [0.55,0.9]->[0,1]`, `y (1-o)*6`; shadow/edge `opacity [0,0.12]->[0,1]` (l.79-90).
- Reduced motion: `useReducedMotion()`; when true the raw (unsprung) progress is used (l.75-77) — header still condenses, just without spring lag.
- ARIA: scroll container is `role="region"`, `tabIndex={0}`, `aria-label={title}` (l.99-102) so it is keyboard-scrollable; decorative layers `aria-hidden`; small title duplicate is `aria-hidden` (l.165).
- `scrollPaddingTop: short + 10` keeps focused items from hiding under the header (l.103).
- "use client"; uses `useScroll({ container: ref })` from motion (no direct window access). No portal.
**Browser APIs:** scroll events via motion's `useScroll`; none directly.
**Weaknesses / bugs:**
- Heading level hard-coded `<h2>` (l.155); cannot be h3 inside a page that already has h2s.
- Only container-scroll; it does not work as a page/window sticky header.
- Hard-coded colours: `border-stone-200 bg-white dark:bg-[#1D1D1A]` (l.94), focus `#4568FF`/`#93B0FF` (l.104), `from-white` gradients (l.111, 132).
- `subtitle` and `title` are `truncate` (l.155, 159) — long agent/tenant names clip with no tooltip.
**Already in Calevate:** yes — vendored, local diff: colour classes swapped to design tokens (`border-line bg-surface text-ink text-ink-muted`, brand focus `#16a05d`/`#22c55e`), no behavioural change; used in: nothing (listed in `tests/componentConsumers.test.ts:68` under `AWAITING_A_DECISION`).
**Fit for Calevate consoles:** card-scoped scroll panels: call detail transcript card, KB document chunk list, admin tenant detail side panels, compliance consent log card.
**Verdict: ADAPT** — already token-themed and unused; add a `headingLevel` prop before adopting it for the transcript card.

---

### streaming-text
**What it does:** Reveals a FIXED string character-by-character at a simulated token rate with a caret, plus Skip/Replay; it is a typewriter effect, not a consumer of a live token stream.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| text | string | required | Full final text; layout reserved up front |
| tokensPerSecond | number | 18 | Converted with `CHARS_PER_TOKEN = 4` (l.6) |
| autoStart | boolean | true | |
| showSkip | boolean | true | Skip/Replay button |
| label | string | "Streamed response" | Group `aria-label` |
| onDone | () => void | undefined | |
| className | string | "" | |

Other exports: `useStreamingText({ text, tokensPerSecond, autoStart, onDone })` -> `{ tokens, index, total, status, visible, start, pause, skip, reset }`; types `StreamingTextStatus` (`"idle"|"streaming"|"paused"|"done"`), `StreamingToken`, `UseStreamingTextOptions`, `StreamingTextProps`.
**Behaviour that matters for reuse:**
- rAF loop advancing `floor(carry/interval)` chars, frame delta capped at `MAX_FRAME_DELTA = 64` ms (l.15, 100-124).
- Caret blink: `duration: 1.06, times: [0,0.45,0.5,0.95], repeat: Infinity, ease: "linear"`; otherwise `CROSSFADE = spring { stiffness: 260, damping: 34, mass: 0.8 }` (l.8-13, 193-203).
- Reduced motion: text jumps to full and status -> "done" (l.93-98, 132-137); caret does not blink.
- ARIA: wrapper `role="group" aria-busy` while streaming (l.209-212); the visible paragraph is `aria-hidden` (l.215) and a `role="status" aria-live="polite"` sr-only span receives the whole text only when done (l.224-226).
- Full text rendered `invisible` underneath to reserve height (l.216) — no layout shift.
**Browser APIs:** `requestAnimationFrame`/`cancelAnimationFrame`, `performance.now()`.
**Weaknesses / bugs:**
- Any change to `text` resets the cursor to 0 (effect l.85-89), so feeding it a growing SSE buffer restarts the animation on every chunk — unusable for real streaming.
- Screen readers get nothing until done, then the entire text at once (l.224-226); long answers become one huge announcement.
- `tokenize`/`tokens` (l.21-34) is returned but unused by the component.
- Hard-coded caret `bg-stone-800 dark:bg-stone-100` (l.191), button `border-stone-200` etc. (l.245).
**Already in Calevate:** yes — vendored, local diff: colour classes to tokens (`bg-ink`, `text-ink`, `border-line`, `ring-brand`) plus `touch:h-9` on the button; used in: nothing (`tests/componentConsumers.test.ts:69`, awaiting a decision).
**Fit for Calevate consoles:** only for presenting an already-complete text with flourish (e.g. a stored post-call summary on first open). The dashboard copilot (`components/copilot/CopilotPanel.tsx`, real SSE via `lib/copilot/sse.ts`) needs an append-only renderer instead.
**Verdict: SKIP** — it animates a known string and resets on every text change, so it cannot render the copilot's real stream, and fake-typing stored data adds latency for no information.

---

### swipe-deck
**What it does:** Tinder-style stacked card deck; drag or arrow keys decide the top card left/right, with undo and a peek stack.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | readonly T[] | required | |
| itemKey | (item: T) => string | required | |
| itemLabel | (item: T) => string | required | Card `aria-label` + live announcement |
| children | (item: T) => ReactNode | required | Card body |
| onDecide | (item, choice: "left"\|"right") => void | undefined | |
| onUndo | (item) => void | undefined | |
| label | string | "Card deck" | |
| leftLabel / rightLabel | string | "Skip" / "Keep" | |
| undoLabel / emptyLabel | string | "Undo" / "Deck cleared" | |
| height | number | 180 | Card px height |
| threshold | number | 92 | px drag to commit |
| steps | number | 6 | Intent granularity |
| peek | number | 3 | Visible stack depth |
| className | string | "" | |

Other exports: `useSwipeDeck({ count, threshold=92, steps=6, flick=520, onDecide, onUndo, disabled=false })` returning `{ index, count, remaining, done, decisions, flow, intent, steps, threshold, armed, canUndo, decide, undo, clear, report, release, deckProps }`; types `SwipeChoice`, `SwipeIntent`, `SwipeDeckFlow`, `UseSwipeDeckOptions`, `UseSwipeDeckResult`, `SwipeDeckProps<T>`.
**Behaviour that matters for reuse:**
- Springs: `CELL {520, 34, 0.45}`, `DISCLOSE {150, 27, 1}`, `CROSSFADE {260, 34, 0.8}`; exit `x: dir*560` over `duration 0.3, ease [0.4,0,1,1]` (l.13-16, 312-322). Drag rotate `[-200,0,200]->[-8,0,8]`, fade `[-340,-150,0,150,340]->[0,1,1,1,0]` (l.267-268). `dragElastic={1}`, `bounceStiffness 260, bounceDamping 34`, `whileDrag scale 1.03` (l.334-340). Flick commits at `|vx| >= 520` and `|dx| >= 0.35*threshold` (l.113).
- Reduced motion: all transitions `{ duration: 0 }`, no `whileDrag` (l.316, 328, 340).
- Keyboard: deck is `role="group" aria-roledescription="card deck" tabIndex=0`; ArrowLeft/Right decide, Backspace/Delete undo, Escape clears intent (l.123-140). Non-top cards `aria-hidden` + `inert` (l.309-310). Polite live region announces "Label. Card n of N." (l.510-514); sr-only hint via `aria-describedby` (l.515-518).
- `window` blur and `visibilitychange` listeners, cleaned up (l.142-151). "use client".
**Browser APIs:** pointer drag (motion), `window`/`document` event listeners.
**Weaknesses / bugs:**
- Progress is a count of decisions, not item ids (l.51, 55): if `items` changes (e.g. a TanStack refetch prepends a row) the index points at a different item and `onDecide` fires for the wrong one (l.409-411).
- The whole card is `drag="x"` (l.334): any interactive child (audio scrubber, text selection) fights the drag.
- `inset-x-5` and fixed `height` (l.352, 396) — no content-driven height; long content is clipped by `overflow-hidden`.
- Buttons hidden via `inert` + `opacity-0` (l.474, 491-494); if focus is on Keep when the deck empties, focus is dropped.
- Backspace on the focused deck undoes (l.132) — surprising inside forms.
- Hard-coded accent `#4568FF`/`#93B0FF` (l.296, 423, 431, 492), `bg-white dark:bg-[#1D1D1A]` (l.294, 352).
**Already in Calevate:** no.
**Fit for Calevate consoles:** the only plausible screen is admin QA sampling of calls (pass/flag), but each card needs an audio player and transcript, which the drag surface and fixed 180px height defeat.
**Verdict: SKIP** — gesture-first triage does not suit desktop QA review with audio, and the index-based state is unsafe over refetching server data.

---

### tabs
**What it does:** WAI-ARIA tabs with a sliding "plateau" indicator and a directional panel slide; headless `useTabs` hook plus a styled `Tabs`.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| items | TabItem[] (`{ value, label, disabled? }`) | required | |
| value | string | undefined | Controlled |
| defaultValue | string | first enabled item | l.40-42 |
| onValueChange | (value: string) => void | undefined | |
| activation | "automatic" \| "manual" | "automatic" | Manual = arrows move focus only |
| renderPanel | (value: string) => ReactNode | undefined | Only the selected panel is rendered |
| label | string | "Tabs" | tablist `aria-label` |
| panelClassName / className | string | "" | |

Other exports: `useTabs(options)` -> `{ value, select, direction, tabListProps, getTabProps(item, index), getPanelProps(value) }`; types `TabItem`, `TabsActivation`, `UseTabsOptions`, `UseTabsReturn`, `TabsProps`.
**Behaviour that matters for reuse:**
- Indicator spring `INDICATOR { stiffness: 620, damping: 42, mass: 0.35 }` with `layout`; panel spring `PANEL { stiffness: 460, damping: 38, mass: 0.8 }`, enters from `x: direction*12` (l.7, 12, 227-249, 288-290).
- Reduced motion: transitions `{ duration: 0 }`, panel `initial={false}` (l.240, 288-290).
- ARIA: `role="tablist" aria-orientation="horizontal"`; tabs `role="tab" aria-selected aria-controls aria-disabled`, roving `tabIndex` 0/-1; panel `role="tabpanel" aria-labelledby tabIndex=0` (l.96-149).
- Keys: ArrowLeft/Right wrap and skip disabled, Home/End, Enter/Space (l.112-131).
- `useIsoLayoutEffect` (useLayoutEffect on client, useEffect on server) — SSR-safe (l.9-10, 195).
**Browser APIs:** `ResizeObserver` on the tab row, disconnected on cleanup (l.212-214).
**Weaknesses / bugs:**
- **Arrow-key focus is broken in the styled `Tabs`:** `getTabProps` supplies a `ref` that registers the button in `nodes` (l.105-108), but the button then passes its own `ref` (l.257-259), which overrides it. `nodes` stays empty, `focusAt` (l.61-68) focuses nothing, and in automatic mode the selection moves while focus stays on a button that now has `tabIndex=-1`. The vendored copy has the same override (`components/interior/tabs.tsx:267-268`); the billing page is unaffected because it spreads `getTabProps` without its own ref.
- `aria-controls` points at panels that are not rendered for unselected tabs (l.102 vs l.283) — dangling idrefs.
- Row is `flex w-full` with `shrink-0` tabs (l.225, 260): many tabs overflow at 320px (fixed locally with `ScrollRegion`).
- Hard-coded `bg-stone-50`, `#4568FF` focus (l.225, 260).
**Already in Calevate:** yes — vendored, local diff: tab row wrapped in `ScrollRegion` (`w-max`, horizontal scroll at narrow widths) and colours moved to tokens; used in: `src/app/c/[slug]/billing/page.tsx:19` (`useTabs` only; the styled `Tabs` is unused).
**Fit for Calevate consoles:** billing (already), agent workspace sections, call detail (transcript/extraction/audit), settings (team/models/voices), admin tenant detail.
**Verdict: ADOPT** — already the repo's tab primitive; fix the ref override (merge both refs) before anyone uses the styled `Tabs` component.

---

### tag-input
**What it does:** Chip/tag input with Enter/separator commit, paste splitting, Backspace two-step removal, duplicate/limit/validation rejection and SR announcements.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | string[] | undefined | Controlled |
| defaultValue | string[] | [] | |
| onChange | (tags: string[]) => void | undefined | |
| max | number | undefined | Hard limit |
| separators | string[] | [","] | Plus `\n\r\t` on paste (l.14-15) |
| allowDuplicates | boolean | false | Case-insensitive compare (l.121) |
| validate | (candidate, tags) => boolean | undefined | Boolean only |
| label | string | undefined | Else `aria-label="Tags"` |
| placeholder | string | "Add a tag" | |
| hint | string | "Enter adds · Backspace removes" | |
| className | string | "" | |

Other exports: `useTagInput(options)` -> `{ tags, draft, setDraft, armedIndex, flashed, rejection, announcement, inputProps, add, removeAt, max }`; types `TagRejection` (`"duplicate"|"limit"|"invalid"`), `UseTagInputOptions`, `TagInputProps`.
**Behaviour that matters for reuse:**
- `CHIP spring { stiffness: 700, damping: 46, mass: 0.5 }`, exit `{ duration: 0.18, ease: [0.4,0,1,1] }`, `CROSSFADE {260, 34, 0.8}`; rejection shows 2400 ms, duplicate flash 460 ms (l.6-10, 77-92).
- Reduced motion: chips enter with no animation, exit opacity only, `INSTANT` transitions (l.336-343, 374-375).
- Keyboard: Enter/separator add; Backspace on empty arms last chip then removes; ArrowLeft/Right move the armed chip; Delete removes armed; Escape disarms; IME `isComposing` respected (l.181-225).
- ARIA: `<label htmlFor>`, `aria-describedby` hint, `role="status" aria-live="polite" aria-atomic` announcements (l.311-317, 389, 437-439). Timers cleared on unmount (l.59-65).
**Browser APIs:** Clipboard paste event (`clipboardData.getData`), `setTimeout`.
**Weaknesses / bugs:**
- Only the last failure is kept (`failure` overwritten in the loop, l.109-131): pasting 500 numbers with 20 invalid reports one, adds the rest silently.
- `validate` returns boolean, so every invalid entry gets the generic "is not allowed here" (l.305) — no "not a valid E.164 number" message.
- Chip remove buttons are `tabIndex={-1}` (l.353): mouse or Backspace-arming only.
- Paste splits only if a separator is present (l.229); a single pasted value is not trimmed until committed.
- Hard-coded `focus-within:border-[#4568FF]`, `bg-stone-800` lit chip, `max-h-[116px]`, `max-w-56` (l.326, 346, 380).
- Every chip is an animated `motion.li` with `layout` — unsuitable for hundreds of entries.
**Already in Calevate:** no.
**Fit for Calevate consoles:** lead tags / saved-view filters, campaign labels, KB keywords, extraction-schema enum options, agent transfer-number allowlist (small sets). Not for bulk DNC lists (use CSV upload with a per-row error report).
**Verdict: ADAPT** — good keyboard/SR model; change `validate` to return a reason string and report every failure before using it for phone numbers.

---

### task-steps
**What it does:** Vertical checklist showing progress of a multi-step background job (pending / active spinner / done tick / error cross) with optional per-step meta.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| steps | TaskStep[] (`{ id, label, meta? }`) | required | |
| current | number | required | Index of active step; `>= length` = complete |
| failed | boolean | false | Marks `current` as error |
| label | string | "Task progress" | `<ol aria-label>` |
| className | string | "" | |

Other exports: `useTaskSteps({ steps, current, failed })` -> `{ rows, complete, failed, sentence }`; types `TaskStep`, `TaskStepStatus` (`"pending"|"active"|"done"|"error"`), `UseTaskStepsOptions`, `TaskStepsProps`.
**Behaviour that matters for reuse:**
- `POP spring { stiffness: 640, damping: 22, mass: 0.7 }` for tick/cross; `CELL { 520, 34, 0.45 }`; spinner `duration 0.8, linear, repeat Infinity`; active label shimmer `backgroundPosition ["120% 0","-120% 0"]` over `1.6s` linear infinite (l.6-8, 82, 192-199).
- Reduced motion: icons fade without scale; shimmer replaced by static text (l.150, 192).
- ARIA: `aria-current="step"` on active row (l.141); `role="status"` sr-only gets the progress sentence after a 500 ms debounce (l.118-123, 224-226); a second span with `aria-live` polite only when complete/failed (l.227-229).
- Meta shown only for done rows, otherwise `aria-hidden` (l.208-219).
**Browser APIs:** `setTimeout` (cleared).
**Weaknesses / bugs:**
- Spinner `<Arc spin />` keeps rotating under reduced motion (l.177 — `spin` is always true).
- Row status is purely visual (icon colour); done/error/pending rows carry no text for SR users browsing the list.
- Two live regions can announce the same completion twice ("All N steps complete" and "Run complete", l.224-229).
- Hard-coded `emerald-*`, `red-*`, `stone-*` and shimmer hex `#78716c`/`#1c1917` (l.149, 160, 194).
- Error state does not accept a reason string.
**Already in Calevate:** yes — vendored, local diff: tone/colour classes moved to tokens (`text-ink`, `text-ink-muted`, `text-ink-faint`); used in: nothing (`tests/componentConsumers.test.ts:70`, awaiting a decision).
**Fit for Calevate consoles:** agent publish flow (compose prompt -> push to engine -> compliance verify), KB document ingestion (upload -> chunk -> embed), campaign launch compliance gate checks, tenant provisioning in admin.
**Verdict: ADOPT** — already themed; stop the spinner under reduced motion and add sr-only status text per row when wiring it to publish/ingest.

---

### tooltip-group
**What it does:** Hover/focus tooltips that share a "warm" state within a group so moving between triggers skips the open delay and the tooltip glides between them (shared `layoutId`).
**Exports / API (`Tooltip`):**

| Prop | Type | Default | Notes |
|---|---|---|---|
| label | ReactNode | required | Tooltip content |
| children | ReactElement | required | Trigger; cloned with handlers + `aria-describedby` |
| side | "top" \| "bottom" | "top" | No left/right, no flipping |
| disabled | boolean | false | |
| openDelay / closeDelay / skipDelay | number | 200 / 120 / 400 (hook defaults) | ms |
| className / contentClassName | string | "" | |

`TooltipGroup` props: `children`, `openDelay=200`, `closeDelay=120`, `skipDelay=400`, `onWarmChange`, `className`. Other exports: `useTooltip(options)` -> `{ open, warm, skipped, travel, tooltipId, seat, triggerProps }`; types `TooltipTiming`, `TooltipGroupProps`, `UseTooltipOptions`, `TooltipTriggerProps`, `UseTooltipReturn`, `TooltipProps`.
**Behaviour that matters for reuse:**
- Springs: `RISE {560, 34, 0.6}`, `WARM {900, 48, 0.5}`, `GLIDE {520, 40, 0.75}` (layout), `SWAP {700, 44, 0.5}`; exit `duration 0.12, ease [0.4,0,1,1]`; cold entry `scale 0.9, y ±7, blur(4px)` (l.14-22, 472-495).
- Reduced motion: no `layoutId`, `initial={false}`, `{ duration: 0 }` (l.471-494).
- ARIA: `role="tooltip"` with id; trigger gets `aria-describedby` only while open (l.424-429, 469). Opens on keyboard focus only when `:focus-visible` (l.292-298, 366-370); Escape on trigger dismisses (l.375-377); pointerdown dismisses (l.361).
- External store via `useSyncExternalStore` with server snapshot `false` (SSR-safe, l.241-245, 327-346). Window blur / visibilitychange reset (l.199-213). Timers cleared on dispose.
- No portal: positioned `absolute` inside an inline-flex wrapper (l.454-465).
**Browser APIs:** `setTimeout`, `Element.matches(":focus-visible")`, window/document listeners.
**Weaknesses / bugs:**
- No portal and no collision handling (l.457-465): clipped by any `overflow-hidden`/`overflow-x-auto` ancestor — i.e. every scrolling data table and `ScrollRegion` in the consoles.
- Content is `pointer-events-none` and `whitespace-nowrap` inside `max-w-[220px] overflow-hidden` (l.459, 497, 516): long labels are cut with no ellipsis, and the tooltip cannot be hovered (WCAG 1.4.13 "hoverable").
- Escape only works while the trigger has focus (l.375); a mouse-hover tooltip with focus elsewhere cannot be dismissed by Escape (1.4.13 "dismissible").
- Touch: pointerdown dismisses, so tooltips never show on touch devices.
- `aria-describedby` added after focus (state update), so some screen readers announce the trigger before the description exists.
- Module-level counter `let groups = 0` (l.24, 100) — shared across all renders/requests; harmless as it only names `layoutId`.
- Hard-coded `border-stone-200 bg-white dark:bg-[#1D1D1A]` (l.503).
**Already in Calevate:** no (no `role="tooltip"` anywhere in `apps/web/src`; `components/ui.tsx:654` has `TermGloss`).
**Fit for Calevate consoles:** icon-only row actions in calls/leads tables, admin ops toolbars, voice picker badges.
**Verdict: ADAPT** — the group/skip-delay store is good, but it needs a portal plus collision-aware positioning (and hoverable content) before it can sit inside the consoles' scrolling tables.

---

### tree-view
**What it does:** Single-select ARIA tree with expandable branches, height-animated groups, roving focus and type-ahead.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| nodes | TreeNode[] (`{ id, label, meta?, children? }`) | required | |
| label | string | required | `role="tree"` `aria-label` |
| expanded | string[] | undefined | Controlled |
| defaultExpanded | string[] | [] | |
| onExpandedChange | (expanded: string[]) => void | undefined | |
| selected | string \| null | undefined | Controlled |
| defaultSelected | string \| null | null | |
| onSelectedChange | (selected: string) => void | undefined | |
| className | string | "" | |

Other exports: `useTreeView(options)` -> `{ rows, openSet, selectedId, tabStop, register, focusRow, setFocusId, toggle, select, handleKey }`; types `TreeNode`, `TreeRow`, `UseTreeViewOptions`, `TreeViewProps`.
**Behaviour that matters for reuse:**
- Open: height `duration 0.28, ease [0.23,1,0.32,1]`, opacity `0.18`; close: height `0.2`, opacity `0.14`, ease `[0.4,0,1,1]`; caret rotate spring `SMALL {700, 46, 0.5}` (l.6-16).
- Reduced motion: opacity-only, `{ duration: 0 }` (l.221, 330-343).
- ARIA: `role="tree"`, `treeitem` with `aria-level/posinset/setsize/expanded/selected`, `role="group"`, `li role="none"`, sr-only usage hint via `aria-describedby` (l.282-292, 329, 361-368).
- Keys: Up/Down, Right (expand / first child), Left (collapse / parent), Home/End, Enter/Space (select + toggle), printable-char type-ahead (l.139-194). Roving tabindex via `tabStop` (l.96-102, 292).
**Browser APIs:** none.
**Weaknesses / bugs:**
- Invalid HTML: `<ul role="group">` directly contains a `<div>` wrapper (l.327-348).
- Enter/Space and click both select AND toggle a branch (l.174-178, 295-298) — you cannot select a folder without collapsing/expanding it.
- `tree.rows.find` inside the recursive render (l.275) and `flatten` every render (l.94): O(n^2), fine for tens of nodes, not thousands.
- Indentation accumulates `ml-[13px] pl-[7px]` per level (l.346) — deep trees squeeze labels at 320px.
- No `*` (expand siblings) key; no multi-select; hard-coded `#4568FF` focus (l.300).
**Already in Calevate:** yes — vendored, local diff: colour classes to tokens (`bg-ink/[0.06] text-ink`, brand focus); used in: nothing (`tests/componentConsumers.test.ts:71`, awaiting a decision).
**Fit for Calevate consoles:** KB documents grouped by collection/source, extraction-schema field groups, admin ops config namespaces. Most Calevate data is flat and tabular.
**Verdict: ADAPT** — usable for KB/config hierarchies once select is decoupled from toggle and the `ul > div` markup is fixed; otherwise leave unused.

---

### typing-indicator
**What it does:** A chat-style "..." bubble with a travelling wave across three dots, plus a text label "X is typing"; a presence hook debounces pings from multiple typists.
**Exports / API (`TypingIndicator`):**

| Prop | Type | Default | Notes |
|---|---|---|---|
| typists | string[] | required | Names; non-empty = visible |
| sending | boolean | false | Collapses the bubble (send animation) |
| max | number | 2 | Names shown before "and N others" |
| size | number | 34 | Bubble height px; width = 2*size |
| showLabel | boolean | true | Visible text label |
| announceAfter | number | 700 | ms debounce before SR announcement |
| className | string | "" | |

Other exports: `useTypingPresence({ timeout = 3000, minVisible = 900 })` -> `{ typists, beat, sending, ping(name), send(name), clear(name), reset() }`; types `UseTypingPresenceOptions`, `TypingPresence`, `TypingIndicatorProps`.
**Behaviour that matters for reuse:**
- Wave: motion value animated 0->3, `duration: WAVE_MS = 1.25` s, linear, infinite loop (l.14, 250-255); per dot `scale [0,1]->[0.74,1]`, `opacity [0,1]->[0.32,1]` (l.208-209).
- Bubble: `SURFACE spring { stiffness: 380, damping: 30, mass: 0.8 }` with opacity `0.18 s ease [0.23,1,0.32,1]`; enter `scale 0.74`; exit `scale 0.4` over `0.26 s`; send collapse `scale 0.45` over `SEND_MS = 340` ms, ease `[0.4,0,1,1]` (l.16-22, 283-304). Label crossfade `CROSSFADE {260, 34, 0.8}`, `y ±7` (l.326-333).
- Reduced motion: wave stopped (`wave.jump(0)`), static dots `opacity-80`, all transitions `INSTANT` (l.246-248, 307-312).
- ARIA: bubble and visible label are `aria-hidden`; one `role="status" aria-live="polite" aria-atomic` sr-only span gets the label after `announceAfter` ms (l.259-263, 342-344).
- Presence hook: entries expire after `timeout`; the indicator stays at least `minVisible` ms once shown (l.56-100); all timers cleared on unmount (l.158-165). "use client", no window access.
**Browser APIs:** `setTimeout`, `Date.now()`; motion `animate`.
**Weaknesses / bugs:**
- Label verb is hard-coded English "is typing" / "are typing" (`describe`, l.178-190); no prop to change it, no i18n.
- Single bubble for all typists: two names become one bubble, "A and B are typing" (l.189) — no notion of sides.
- No avatar slot, no alignment/side prop, no per-party colour: dots `bg-stone-500` (l.213, 310), bubble `bg-stone-200 dark:bg-white/[0.09]` (l.281), transform origin fixed bottom-left `0% 100%` (l.282).
- Every label change is announced politely after 700 ms (l.259-263); there is no way to turn the announcement off except unmounting.
- `beat` is returned but unused by the component.

**Live call view (founder suggestion) — concrete assessment**

What the founder wants: in a live call view, the three dots show WHICH side (caller or agent) is currently speaking.

1. *Two parties / labels / avatars / alignment:* not supported. The API is one bubble, one roster, one bottom-left origin. Passing `typists={["Caller"]}` vs `["Agent"]` changes only the text; the dots never move sides. Barge-in (both talking) renders one bubble labelled "Caller and Agent are typing" — the word "typing" is wrong for voice and cannot be overridden.
2. *Data source:* There is no live-call view and no speaking-state stream in `apps/web/src` (the only `EventSource`/stream code is the copilot, `lib/copilot/sse.ts`). The worker runs Silero VAD inside the Pipecat pipeline (`apps/voice-worker/voice_worker/pipeline.py:65`), but nothing forwards speaking state to the API or browser. A live view is therefore new work on three layers (worker event -> api fan-out -> browser), and the event would have to be one of OUR normalized events (hard rule 2), never a Pipecat frame.
3. *Driving it from voice activity:* the hook's model (pings that expire after 3000 ms, `minVisible` 900 ms) suits keystrokes. Voice gives explicit start/stop edges, so drive `typists` directly from state (`speaking: "caller" | "agent" | "both" | null`). Keep a short hold (around the hook's `minVisible` idea) only to stop VAD flicker between words; the 3 s expiry would leave the dots up long after someone stopped talking. `send()` maps loosely to "turn ended, transcript line appended".
4. *Screen readers:* turns switch every few seconds; a polite announcement per switch (l.259-263) would talk over whatever the user is reading, and "Caller is typing / Agent is typing" every few seconds is noise. Speaking state should be `aria-hidden` visual only; announce the transcript lines (in a `role="log"` with `aria-live="polite"`) and, at most, call start/end. Do not use `role="status"` for the speaking indicator.
5. *Reduced motion:* the component already stops the wave; for a call view the static state also needs a non-motion cue (side position, colour, a "Speaking" text badge) because three still dots carry no information.
6. *Colour/theme:* every colour is a hard-coded stone class; side distinction needs tokens (e.g. brand for agent, neutral for caller).

**Recommendation:** do not use `TypingIndicator` as-is for the live call view. Reuse only the `Dot` wave idea (the motion-value wave, l.192-217, is ~25 lines) inside a new Calevate `SpeakingIndicator` that takes `side: "caller" | "agent"`, renders aligned with that side's transcript column (caller left, agent right, matching chat convention), uses token colours and an optional avatar, is `aria-hidden`, and is driven by explicit start/stop events with a ~300-500 ms hold. Build it only when the live-call event stream exists; until then there is nothing to drive it.
**Already in Calevate:** no.
**Fit for Calevate consoles:** live call monitor (future, see above); the dashboard copilot "assistant is thinking" state is a better fit for the component as written.
**Verdict: ADAPT** — the dot wave is worth lifting, but the component's single-bubble, "typing", announce-every-change design does not fit a two-party voice view and must be rebuilt as a side-aware, silent-to-SR speaking indicator.

---

### value-flash
**What it does:** Displays a number that rolls to its new value and briefly flashes green/up or red/down with an arrow glyph when it changes.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| value | number | required | Number only |
| format | (value: number) => string | undefined | Else `String(value)` |
| label | string | undefined | Prefix for SR announcement |
| hold | number | 900 | ms flash duration |
| announceAfter | number | 700 | ms debounce for SR |
| className | string | "" | |

Other exports: `useValueFlash<T>(value, { hold = 900, compare })` -> `{ direction: "up"|"down"|null, from, changeId, flashing }` (generic; `compare(next, prev)` returns a signed number); types `FlashDirection`, `UseValueFlashOptions<T>`, `ValueFlashState<T>`, `ValueFlashProps`.
**Behaviour that matters for reuse:**
- Springs: `CELL {520, 34, 0.45}`, `ROLL {460, 32, 0.55}`, `POP {640, 22, 0.7}`, `LIFT {380, 26, 0.7}`, `SETTLE {260, 34, 0.8}`; `CLEAR 0.16 s` and `DROP 0.14 s` with ease `[0.4,0,1,1]` (l.6-17). Roll in from `y ±0.85em, blur(5px)`, out to `±0.7em, blur(4px)`; scale pulse to `1.05` while flashing (l.136-176).
- Reduced motion: no scale, roll/arrow become opacity-only with `{ duration: 0 }` (l.138-139, 156-176, 190-205).
- ARIA: visual digits and arrow `aria-hidden`; sr-only `aria-live="polite"` span with `"label: value"` updated after `announceAfter` (l.117-122, 213-215). Direction is not announced.
- Timer cleared on change and unmount (l.79-91). "use client".
**Browser APIs:** `setTimeout`.
**Weaknesses / bugs:**
- `ValueFlash` takes `value: number` (l.97) and does not expose `compare`; Calevate money is decimal strings (`formatINR(value: string)`, `components/ui.tsx:1433`, hard rule 7), so using it as-is pushes rupee values through floats.
- Up = green, down = red is fixed (l.124-133): wrong for cost/spend/latency/abandon-rate where up is bad; colours `text-emerald-600`, `text-red-600`, `bg-emerald-500/[0.12]` hard-coded.
- Each instance owns a polite live region (l.213): a dashboard with ten tiles refreshing together produces ten announcements.
- `from` is computed but unused by the component.
**Already in Calevate:** no.
**Fit for Calevate consoles:** client billing credit balance / minutes used, admin system-health and vendor-spend tiles, campaign live counters (dialled/connected), on TanStack Query refetch.
**Verdict: ADAPT** — wrap `useValueFlash<string>` with a decimal-safe `compare`, add a "higher is better/worse" tone prop and an opt-out for the live region, then use it in `StatTile`.

---

### wizard-steps
**What it does:** Multi-step form shell: numbered step rail with connector bars, sliding panel per step, Back/Next/Finish buttons and a completion panel.
**Exports / API:**

| Prop | Type | Default | Notes |
|---|---|---|---|
| steps | WizardStep[] (`{ id, label, content }`) | required | |
| index | number | undefined | Controlled |
| defaultIndex | number | 0 | |
| onIndexChange | (index, direction: 1\|-1) => void | undefined | |
| onComplete | () => void | undefined | Called by Next on last step |
| complete | boolean | false | Shows completion panel |
| height | number | 184 | Fixed panel px height |
| backLabel / nextLabel / finishLabel | string | "Back" / "Next" / "Finish" | |
| completeLabel / completeHint | string | "All set" / "Step back to change anything" | |
| label | string | "Steps" | `<ol aria-label>` |
| className | string | "" | |

Other exports: `useWizard({ total, index, defaultIndex, onIndexChange, onComplete })` -> `{ index, direction, furthest, total, isFirst, isLast, next, back, goTo }`; types `WizardDirection`, `UseWizardOptions`, `UseWizardReturn`, `WizardStep`, `WizardStepsProps`.
**Behaviour that matters for reuse:**
- `RAIL spring { stiffness: 520, damping: 40, mass: 0.5 }` for tiles (`scale 0.92`->`1`) and connector `scaleX`; `CROSSFADE {260, 34, 0.8}` for panels entering from `x: d*22`, exiting to `x: d*-22` over `0.14 s ease [0.4,0,1,1]`; Back fades `0.16 s ease [0.23,1,0.32,1]` (l.7-11, 169-183, 246-248, 304-309, 355-364).
- Reduced motion: opacity-only variants and `{ duration: 0 }` everywhere (l.171-176, 185).
- ARIA/keys: visited steps are buttons with roving `tabIndex`, `aria-current="step"`, `aria-label "Step i of N: label"`; Arrow keys/Home/End move within visited steps only (capped at `furthest`) (l.187-199, 275-291); unvisited steps get sr-only text (l.293-296). Polite live region "Step n of N: label" (l.208-210).
- Focus management: after rail navigation focus goes to the new current step button; after Back/Next to the panel (`tabIndex=-1`, `preventScroll`) (l.153-167, 316-318).
- Derived state set during render (l.54-59) — the documented React pattern, not an effect.
**Browser APIs:** none (DOM `focus`, `querySelector`).
**Weaknesses / bugs:**
- No validation gate: Next always advances (l.79-85, 381-384); there is no `canAdvance`/`onBeforeNext`, so a form step with errors cannot block it.
- Fixed `height = 184` with an inner scroller (l.133, 321, 334): real form steps scroll inside a short box.
- When `complete` turns true the Next button unmounts (l.376); if it held focus, focus falls to `body`.
- `if (!step) return null` (l.201-202) with an empty `steps` array renders nothing silently.
- Hard-coded `bg-stone-800`, `#4568FF`/`#93B0FF` focus (l.241, 288, 395).
**Already in Calevate:** yes — vendored, local diff: colour classes to tokens (`bg-brand-strong`, `text-ink`, `border-line`, brand focus) and `touch:h-11` on the action row/buttons; used in: nothing (`tests/componentConsumers.test.ts:72`, awaiting a decision; `components/copilot/CopilotPanel.tsx:290` only cites it in a comment).
**Fit for Calevate consoles:** agent creation (vertical template -> voice -> script -> extraction schema -> publish), campaign creation (audience -> DLT/compliance -> schedule -> review), tenant onboarding in admin.
**Verdict: ADAPT** — good focus and ARIA handling, but it needs a per-step validation gate, content-driven height and focus handling on completion before it can host the agent or campaign wizard.


---

## Part B: Pixel Perfect (pixel-perfect.space)

This review covers seven block categories from Pixel Perfect (site `https://www.pixel-perfect.space/blocks/...`, source `https://github.com/vansh-nagar/Pixel-Perfect`): buttons, svg-animations, motion, svg-assets, text, borders and masks. For each block it gives a verdict for Calevate and enough detail to pull the block in later. The source state reviewed is commit **`818ecef0a542191061501a5fb2c8ab0ca2f70bf4`** on `main`, committed 2026-09-29.

### Licence situation

- **The upstream has no licence.** At commit `818ecef`, the GitHub API returns `license: null` for `vansh-nagar/Pixel-Perfect`, and the tree has no LICENSE, LICENCE or COPYING file.
- **The README grants nothing.** Its only statement about reuse is the tagline "Copy - Paste - Done".
- **The legal default is that no rights are granted.** Code published without a licence is all rights reserved by its author. A public repository plus a "copy-paste" tagline does not, on its own, grant permission to copy, modify or redistribute.
- **Copying is the founder's decision.** The founder has decided to use code from this repository despite this. That is an informed business decision about a known risk, not a licence grant.
- **How to remove the risk.** The author could add a licence (for example MIT) or give written permission. Asking costs one GitHub issue or email, and it is the only thing that removes the risk rather than accepting it.
- **Required attribution.** Any file taken from upstream must keep a header comment that credits `github.com/vansh-nagar/Pixel-Perfect`, names the upstream path and commit `818ecef0a542191061501a5fb2c8ab0ca2f70bf4`, and lists what was changed. The licence status must be re-checked before each new pull, because the author may add a licence or change the code.
- **Codrops ports are an exception.** Five text items describe themselves as ports of Codrops demos. The four upstream Codrops repositories behind them are MIT-licensed. For those effects, take the code from the Codrops repository under its MIT notice instead of from the port (see "Upstream provenance" at the end).
- **This document copies no source.** Every description below is a paraphrase of the behaviour, and every dependency is copied from the registry metadata or from import lines.

### How to read the tables

**Verdicts**

- **ADOPT**: usable as it stands in a sober B2B console, apart from the mechanical fixes under "Mechanical fixes for any block taken" below.
- **ADAPT**: worth pulling in, but it must be restyled to Calevate tokens, toned down (no loops, smaller motion), given correct semantics, and/or made to honour `prefers-reduced-motion`. "Marketing:" in a verdict means the block only suits the marketing site, where more flair is acceptable.
- **SKIP**: do not take it.

**Columns**

- **Repo path** is the file or files to fetch, relative to the upstream repository root.
- **npm deps** lists the external packages the file actually imports (React excluded). Sub-path imports appear as "entry points". When the registry item's `dependencies` differ from what the file imports, the cell adds "registry declares: ...". The registry often over-declares; for example, every `svg-N` asset declares GSAP and imports nothing.
- **Shadcn / internal deps** lists the registry item's `registryDependencies` (shadcn components such as `button`, `card`, `spinner`) and any `@/` or relative imports the file needs.
- **Reduced-motion?** records whether the file checks `prefers-reduced-motion` (through Motion's `useReducedMotion`, `matchMedia`, or a CSS media query). "No" means the block animates regardless.

**How the site categories map to registry folders**

The mapping comes from `src/lib/blocks/categories.ts` (the `BLOCK_CATEGORIES` list) and `src/lib/blocks/category-items.ts` (the resolver). The resolver puts a registry item in a category when the folder segment of its first file path matches the category's `source.folder`. It then applies the optional `nameEndsWith`, `nameNotEndsWith` and `exclude` filters.

| Site category (slug) | Registry folder | Filter |
|---|---|---|
| `buttons` | `buttons` | none |
| `svg-animations` | `svg` | name ends in `-animation` |
| `motion` | `motion-framer` | none |
| `svg-assets` | `svg` | name does not end in `-animation`; excludes `svg-5`, `svg-6`, `svg-8` |
| `text` | `text` | none |
| `borders` | `borders` | none |
| `masks` | `mask` | none |
| `svg-path` (not one of the seven reviewed here) | `svg-path-effects` | none |

**Counts.** Buttons 40. SVG animations 6. SVG assets 4 shown, plus 3 excluded from the site but present in the folder. Motion 18. Text 34 files (33 registry items plus 1 unregistered file). Borders 5. Masks 19. In total, 130 source files across these folders, all listed below, plus the one `svg-path-effects` file.

### Mechanical fixes for any block taken

These apply to every ADOPT and ADAPT row. Checked against `apps/web/package.json` at the time of writing.

- **`cn` helper.** Upstream blocks import a `cn` helper from `@/lib/utils`. That module does not exist in `apps/web`. `clsx` is installed and `tailwind-merge` is not. Decide on one class-merging helper before the first pull, and do not add a second.
- **shadcn components.** `@/components/ui/button` and `@/components/ui/spinner` (`registryDependencies` `button`, `spinner`, `card`) do not exist in `apps/web`. Rewrite any block that wraps them against Calevate's own primitives.
- **`framer-motion` imports.** Blocks importing `framer-motion` should be rewritten to import from `motion/react`. `apps/web` has `motion` ^13.1.1 and no `framer-motion`, and two copies of the same library must not be installed.
- **GSAP imports.** `apps/web` has `gsap` 3.15.0 and `@gsap/react` 2.1.2. The installed package ships `SplitText`, `ScrollTrigger`, `MorphSVGPlugin`, `InertiaPlugin` and `CustomEase`. Its README states that all GSAP plugins are free, including for commercial use, under GreenSock's "Standard 'no charge' license" (`gsap/package.json`, `gsap/README.md`, version 3.15.0). Upstream sometimes imports plugins from `gsap/src/...`. Normalise those to the public entry points (`gsap/SplitText`, `gsap/ScrollTrigger`).
- **Not installed.** Calevate does not use `three`, `react-icons`, or `next/font/google` loaded inside a component. Every block that needs them is SKIP below.
- **Reduced motion.** Every animated block must honour `prefers-reduced-motion` before it ships. Most upstream blocks do not.

### Buttons (site `/blocks/buttons`, 40 blocks)

Source: every registry item whose first file sits in `registry/new-york/buttons/` (`categories.ts` slug `buttons`, `source.folder: "buttons"`). 40 files, 40 registry items, no unregistered files. Most of the category is material styling (glass, chrome, metal, neumorphic, neon) that does not fit the console. The few worth taking are the behavioural ones.

| Block (registry name) | Repo path | What it does | npm deps | Shadcn / internal deps | Reduced-motion? | Verdict |
|---|---|---|---|---|---|---|
| `3d-button` | `registry/new-york/buttons/3d-button.tsx` | Chunky push button whose face sinks on press, with a hover lift. Eight colour presets. React state drives inline styles. | none (registry declares: `@gsap/react`, `gsap`) | imports `@/lib/utils` | No | SKIP: toy-like material. Console buttons stay flat. |
| `abhinav-bento-button` | `registry/new-york/buttons/abhinav-bento-button.tsx` | Large static tile-style button with a gradient face. | none | imports `@/lib/utils` | No | SKIP: decorative, with no behaviour to reuse. |
| `antinomy-button` | `registry/new-york/buttons/antinomy-button.tsx` | On hover the label slides aside while two pills bloom and merge behind an action word. The merge is an SVG blur plus colour-matrix ("gooey") filter. | `motion` (entry points: `motion/react`) | imports `@/lib/utils` | Yes | SKIP (console). Marketing: possible. It already respects reduced motion. |
| `bevel-button` | `registry/new-york/buttons/bevel-button.tsx` | Small dark button with a light-to-dark gradient stroke and stacked inset shadows for a chiselled look. Uses one CSS keyframe. | none | imports `@/lib/utils` | No | SKIP (console): off-palette. Marketing dark sections: ADAPT and retokenise the colours. |
| `blue-chrome-button` | `registry/new-york/buttons/blue-chrome-button.tsx` | Chrome-look button with a layered conic glow border and spring motion. | `framer-motion` | imports `@/lib/utils` | No | SKIP: chrome material. |
| `blur-toggle-button` | `registry/new-york/buttons/blur-toggle-button.tsx` | A click swaps between two icon/label states. The outgoing state blurs out as the incoming one blurs in. | `framer-motion`, `lucide-react` | none | No | ADAPT: good pattern for copy/copied, play/pause and enable/disable confirmations. Add reduced motion (instant swap), an accessible name and a live-region announcement. |
| `book-demo-button` | `registry/new-york/buttons/book-demo-button.tsx` | Lime square with marching dotted chevrons. On hover a dark panel expands sideways to reveal a label. | none | imports `@/lib/utils` | Yes (CSS media query) | SKIP (console). Marketing CTA: ADAPT and restyle away from lime. |
| `border-gradient-button` | `registry/new-york/buttons/border-gradient-button.tsx` | shadcn Button wrapped in an animated gradient border with a backdrop blur. | none | registryDependencies: `button`; imports `@/components/ui/button`, `@/lib/utils` | No | SKIP (console). Marketing: ADAPT if one highlighted CTA is wanted. |
| `cyber-button` | `registry/new-york/buttons/cyber-button.tsx` | Neon cyberpunk button with a glitch flicker that never stops. | `framer-motion` | imports `@/lib/utils` | No | SKIP: off-brand, and the motion never stops. |
| `framer-cta-button` | `registry/new-york/buttons/framer-cta-button.tsx` | Pill CTA carrying a third-party brand icon. Dark and light variants. | none (registry declares: `react-icons`) | imports `@/lib/utils` | No | SKIP: it imitates another product's brand. |
| `glass-button` | `registry/new-york/buttons/glass-button.tsx` | Frosted pill with backdrop blur and a gradient border. Ten colour presets. | none | imports `@/lib/utils` | No | SKIP: glass material. |
| `glass-circle-button` | `registry/new-york/buttons/glass-circle-button.tsx` | Circular frosted icon button with a conic gradient ring. | `lucide-react` | imports `@/lib/utils` | No | SKIP: glass material. |
| `glass-icon-button` | `registry/new-york/buttons/glass-icon-button.tsx` | Frosted pill with an inset icon capsule. | `lucide-react` | imports `@/lib/utils` | No | SKIP: glass material. |
| `glass-square-button` | `registry/new-york/buttons/glass-square-button.tsx` | Rounded-square frosted button with a diagonal gradient border. | none | imports `@/lib/utils` | No | SKIP: glass material. |
| `glassy-button` | `registry/new-york/buttons/glassy-button.tsx` | Chunky square glass/metal button with a floating shadow and a press state that dims the icon. | `lucide-react` | none | No | SKIP: material style. |
| `goe-button` | `registry/new-york/buttons/goe-button.tsx` | Icon button whose parts merge through an SVG gooey filter. | `framer-motion`, `lucide-react` | none | No | SKIP: novelty. |
| `learn-more-button` | `registry/new-york/buttons/learn-more-buttion.tsx` | Text link-button whose arrow and underline animate on hover. | `framer-motion` | none | No | SKIP (console). Marketing secondary CTA: ADAPT and add reduced motion. |
| `liquid-button` | `registry/new-york/buttons/liquid-button.tsx` | Frosted pill. On hover one stacked label slides out and a second slides in. | none | imports `@/lib/utils` | No | SKIP the glass. The stacked-label hover swap can be reused on marketing: ADAPT. |
| `liquid-gradient-button` | `registry/new-york/buttons/liquid-gradient-button.tsx` | Gradient button with an image overlay, a blend mode and a loading-spinner state. Eight presets. | `framer-motion` (registry declares: `framer-motion`, `lucide-react`) | registryDependencies: `spinner`; imports `@/components/ui/spinner`, `@/lib/utils` | No | SKIP: loud styling. Calevate needs its own pending-state button anyway. |
| `matte-dark-button` | `registry/new-york/buttons/matte-dark-button.tsx` | Static matte dark button with a layered depth shadow and a subtle radial grain. | none | imports `@/lib/utils` | No | SKIP: off-palette, with no behaviour. |
| `matte-shadow-button` | `registry/new-york/buttons/matte-shadow-button.tsx` | Near-identical sibling of matte-dark-button. | none | imports `@/lib/utils` | No | SKIP: duplicate of the above. |
| `metal-button` | `registry/new-york/buttons/metal-button.tsx` | Metallic face (silver, gold, copper and others) built from stacked gradients. | none | imports `@/lib/utils` | No | SKIP: material style. |
| `mitosis-button` | `registry/new-york/buttons/mitosis-button.tsx` | Share pill that buds gooey drops, which split into a row of icon buttons. | `lucide-react`, `motion` (entry points: `motion/react`) | imports `@/lib/utils` | Yes | SKIP: novelty, though it respects reduced motion. |
| `morph-button` | `registry/new-york/buttons/morph-button.tsx` | On hover the button outline morphs from one SVG path to another with GSAP MorphSVG. | `@gsap/react`, `gsap` (entry points: `gsap/MorphSVGPlugin`) | registryDependencies: `button`; imports `@/lib/utils` | No | SKIP. |
| `morph-image-button` | `registry/new-york/buttons/morph-image-button.tsx` | On hover an SVG mask shape morphs over an image with GSAP MorphSVG. | `@gsap/react`, `gsap` (entry points: `gsap/MorphSVGPlugin`) | registryDependencies: `button`; imports `@/components/ui/button`, `@/lib/utils` | No | SKIP. |
| `mouse-follower-button` | `registry/new-york/buttons/mouse-follower-button.tsx` | shadcn Button whose inner highlight tracks the pointer on hover. | none (registry declares: `@gsap/react`, `gsap`) | registryDependencies: `button`; imports `@/components/ui/button` | No | SKIP: novelty. |
| `orange-premium-button` | `registry/new-york/buttons/orange-premium-button.tsx` | Glossy gradient button with a soft glow. Eight presets. | none | imports `@/lib/utils` | No | SKIP: glossy material. |
| `pearl-toggle-button` | `registry/new-york/buttons/pearl-toggle-button.tsx` | Two-state pressed toggle with a pearl-like knob. Exposes `aria-pressed`. | `framer-motion` | none | No | SKIP: the value is the styling, and toggle semantics are already standard. |
| `premium-button` | `registry/new-york/buttons/premium-button.tsx` | Neumorphic button with stacked light and dark shadows. Eight presets. | none | imports `@/lib/utils` | No | SKIP: neumorphism has weak contrast. |
| `prism-glass-button` | `registry/new-york/buttons/prism-glass-button.tsx` | Draggable domed lens that refracts whatever sits behind it, using an SVG displacement map with chromatic fringing. | `framer-motion` | none | No | SKIP: heavy and decorative. |
| `radial-gradient-button` | `registry/new-york/buttons/radial-gradient-button.tsx` | Radial-gradient button with an inset glow and a spinner loading state. Eight presets. | `framer-motion` (registry declares: `framer-motion`, `lucide-react`) | registryDependencies: `spinner`; imports `@/components/ui/spinner`, `@/lib/utils` | No | SKIP. |
| `rainbow-glowing-button` | `registry/new-york/buttons/rainbow-glowing-button.tsx` | Dark pill whose blurred glow cycles through six hues on a timer. | none | none | No | SKIP: the colour cycling never stops. |
| `recessed-stepper-button` | `registry/new-york/buttons/recessed-stepper-button.tsx` | Minus/value/plus stepper sunk into a recessed track. | none | none | n/a (no animation) | ADAPT: a numeric stepper is useful (credit pack quantity, concurrency caps, retry counts). Restyle it flat, give it spinbutton semantics and label the +/- buttons. |
| `shiny-button` | `registry/new-york/buttons/shiny-button.tsx` | shadcn Button with a sheen that sweeps across through an animated CSS mask. | none (registry declares: `@gsap/react`, `gsap`) | registryDependencies: `button`; imports `@/components/ui/button`, `@/lib/utils` | No | SKIP (console). Marketing primary CTA: ADAPT, and turn the sweep off under reduced motion. |
| `silver-button` | `registry/new-york/buttons/silver-button.tsx` | Glossy silver pill with an embossed letterpress label. Slim and chunky variants. | none | imports `@/lib/utils` | No | SKIP: material style. |
| `soft-pill-button` | `registry/new-york/buttons/soft-pill-button.tsx` | Frosted pill with layered highlights and a gradient border. Primary and secondary variants. | none | imports `@/lib/utils` | No | SKIP: glass material. |
| `squircle-counter-button` | `registry/new-york/buttons/squircle-counter-button.tsx` | Squircle button showing a count whose digits animate when it changes. | `framer-motion` | none | No | ADAPT as a pattern only: an animated count change for badges such as unread QA samples. The squircle face is not needed. |
| `stripe-button` | `registry/new-york/buttons/stripe-button.tsx` | Static button with a crisp inset shadow, styled after a well-known payments brand. | none | imports `@/lib/utils` | n/a (CSS transition only) | ADAPT: the inset-shadow treatment is sober enough for a primary button. Retokenise it to Calevate colours instead of copying the other brand. |
| `toggle-button` | `registry/new-york/buttons/toggle-buttion.tsx` | Pill switch whose knob springs between the two ends, using Motion. | `framer-motion` | none | No | ADAPT: the spring is fine, but the markup has no switch semantics. Add `role="switch"`, `aria-checked`, keyboard support and reduced motion. |
| `visit-button` | `registry/new-york/buttons/visit-button.tsx` | Compact external-link button whose label and icon swap on hover. | `framer-motion`, `lucide-react` | imports `@/lib/utils` | No | SKIP (console). Marketing: optional. |

### SVG animations (site `/blocks/svg-animations`, 6 blocks)

Source: `registry/new-york/svg/` items whose registry name ends in `-animation` (the `categories.ts` filter is `nameEndsWith: "-animation"`). Its `exclude: ["barwave-svg-animation"]` names no existing item, so it removes nothing. The `svg-path-effects` folder is NOT part of this category. It feeds a separate site category, `svg-path`, and is listed near the end of this document.

| Block (registry name) | Repo path | What it does | npm deps | Shadcn / internal deps | Reduced-motion? | Verdict |
|---|---|---|---|---|---|---|
| `bar-wave-animation` | `registry/new-york/svg/bar-wave-animation.tsx` | A row of bars. The bar under the pointer and its neighbours rise, falling off with distance, then spring back. | `framer-motion` | none | No | ADAPT: the distance-falloff idea suits a hover on a call-volume histogram. Driven by audio level instead of the pointer, it becomes a live-call speaking indicator. Add reduced motion. |
| `bounce-smiley-animation` | `registry/new-york/svg/bounce-smiley-animation.tsx` | Cartoon smiley that bounces on a loop, blended with an SVG gooey filter. | `motion` (entry points: `motion/react`) | none | No | SKIP: mascot style. |
| `glow-card-animation` | `registry/new-york/svg/glow-card-animation.tsx` | Long keyframed scene of grouped SVG shapes drifting inside clipped cards, with a blur glow. | `motion` (entry points: `motion/react`) | none | No | SKIP: decorative animation exported from a design tool. |
| `liquid-pause-animation` | `registry/new-york/svg/liquid-pause-animation.tsx` | A liquid blob loops around a pause glyph through keyframes, with a gooey filter. | `motion` (entry points: `motion/react`) | none | No | SKIP: novelty. A recording player needs a plain play/pause. |
| `orbit-smiley-animation` | `registry/new-york/svg/orbit-smiley-animation.tsx` | Small smiley orbiting, with gooey blending. | `motion` (entry points: `motion/react`) | none | No | SKIP. |
| `smiley-orb-animation` | `registry/new-york/svg/smiley-orb-animation.tsx` | Larger multi-stage smiley orb scene. | `motion` (entry points: `motion/react`) | none | No | SKIP. |

### SVG assets (site `/blocks/svg-assets`, 4 blocks shown, plus 3 more in the folder)

Source: `registry/new-york/svg/` items whose name does NOT end in `-animation`, minus `exclude: ["svg-5", "svg-6", "svg-8"]`. All seven are static inline SVG components. Their registry entries declare `gsap` and `@gsap/react`, but none of the files imports anything. They are hand-exported illustrations (stacks of rects, paths and gradients). What each one depicts was not worked out from the source alone.

| Block (registry name) | Repo path | What it does | npm deps | Shadcn / internal deps | Reduced-motion? | Verdict |
|---|---|---|---|---|---|---|
| `svg-1` | `registry/new-york/svg/svg-1.tsx` | Static illustration built from nested square rects and a few paths. | none (registry declares: `@gsap/react`, `gsap`) | none | n/a (static) | SKIP (console). Marketing: only if the art suits, restyled through currentColor. |
| `svg-2` | `registry/new-york/svg/svg-2.tsx` | Static illustration (200x120 viewBox) of square rects and three paths, using dash arrays. | none (registry declares: `@gsap/react`, `gsap`) | none | n/a (static) | SKIP (console). Marketing: optional. |
| `svg-4` | `registry/new-york/svg/svg-4.tsx` | Larger static illustration of gradient-filled rects and paths. | none (registry declares: `@gsap/react`, `gsap`) | none | n/a (static) | SKIP (console). Marketing: optional. |
| `svg-9` | `registry/new-york/svg/svg-9.tsx` | The largest static scene (about 690 lines): many paths, lines and circles, plus a blur filter. | none (registry declares: `@gsap/react`, `gsap`) | none | n/a (static) | SKIP: heavy inline markup. |
| `svg-5` | `registry/new-york/svg/svg5.tsx` | Static gradient illustration. Excluded from the site listing. | none (registry declares: `@gsap/react`, `gsap`) | none | n/a (static) | SKIP. |
| `svg-6` | `registry/new-york/svg/svg6.tsx` | One hand-drawn-style curve-and-loop stroke. Excluded from the site listing. | none (registry declares: `@gsap/react`, `gsap`) | none | n/a (static) | SKIP. |
| `svg-8` | `registry/new-york/svg/svg8.tsx` | Static illustration of stacked bars. Excluded from the site listing. | none (registry declares: `@gsap/react`, `gsap`) | none | n/a (static) | SKIP. |

### Motion animations (site `/blocks/motion`, 18 blocks)

Source: `registry/new-york/motion-framer/` (`categories.ts` slug `motion`, `source.folder: "motion-framer"`). Despite the folder name, two blocks (`color-flair-button`, `inertia-arrow-card`) run on GSAP, and `dial-knob-motion` uses no animation library.

| Block (registry name) | Repo path | What it does | npm deps | Shadcn / internal deps | Reduced-motion? | Verdict |
|---|---|---|---|---|---|---|
| `car-lock-drive-motion` | `registry/new-york/motion-framer/car-lock-drive-motion.tsx` | Car illustration with a lock/drive pill switch. Switching to drive springs the car forward. | `framer-motion`, `lucide-react` | none | No | SKIP: illustrative toy. |
| `card-animation` | `registry/new-york/motion-framer/card-animation.tsx` | Hover card that plays the matrix-rain and burn-neon text effects and staggers its children in. | `lucide-react`, `motion` (entry points: `motion/react`; registry declares: `framer-motion`, `lucide-react`, `motion`) | registryDependencies: `button`, `card`; imports `../text/text-burn-neon`, `../text/text-matrix-rain`, `@/components/ui/button` | No | SKIP: depends on two text effects that are themselves SKIP. |
| `cd-envelope-player` | `registry/new-york/motion-framer/cd-envelope-player.tsx` | A CD slides out of a sleeve and spins up into a now-playing card. Play/pause eases the spin in and out. | `lucide-react`, `motion` (entry points: `motion/react`) | none | Yes | SKIP: skeuomorphic, though it respects reduced motion. |
| `coin-spin-animation` | `registry/new-york/motion-framer/coin-spin-animation.tsx` | A 3D coin with layered faces and an edge, spinning without stopping. | `framer-motion` | none | No | SKIP. |
| `color-flair-button` | `registry/new-york/motion-framer/color-flair-button.tsx` | Pill button where concentric colour circles bloom from whichever side the pointer entered. | `@gsap/react`, `gsap` | none | No | SKIP (console). Marketing CTA: ADAPT and add reduced motion. |
| `dial-knob-motion` | `registry/new-york/motion-framer/dial-knob-motion.tsx` | Rotary knob with bevelled discs and tick rings, set by dragging or the scroll wheel. | none | none | No | SKIP: knobs are a poor input for precise settings. Use sliders or number fields. |
| `fisheye-faq` | `registry/new-york/motion-framer/fisheye-faq.tsx` | FAQ list whose rows magnify with pointer distance, like a dock. The nearest row opens and its answer sharpens out of a blur. | `motion` (entry points: `motion/react`) | none | Yes | SKIP (console). Marketing FAQ: ADAPT with care, because the magnification hurts readability and keyboard users get no effect. |
| `free-premium-toggle` | `registry/new-york/motion-framer/free-premium-toggle.tsx` | Two-option pill. A highlight springs across to sit behind the selected option. | `framer-motion` | none | No | ADAPT: segmented control for monthly/annual or plan views. Add `role="radiogroup"` and `aria-checked` (today it is two plain buttons), plus reduced motion. |
| `hover-expand-player` | `registry/new-york/motion-framer/hover-expand-player.tsx` | Compact player pill that springs open on hover: the corners morph, the artwork grows and the controls sharpen out of a blur. | `framer-motion`, `lucide-react` | none | Yes | ADAPT as inspiration for the call-recording mini-player. It must also open on focus and on click, not on hover only. |
| `image-hover-animation` | `registry/new-york/motion-framer/image-hover-animation.tsx` | Image stack that scales and fades on hover. | `framer-motion` | none | No | SKIP. |
| `inertia-arrow-card` | `registry/new-york/motion-framer/inertia-arrow-card.tsx` | Notched card with a magnetic pill that flings with GSAP inertia. The component loads a Google font itself. | `@gsap/react`, `gsap`, `motion`, `next` (entry points: `gsap/InertiaPlugin`, `motion/react`, `next/font/google`; registry declares: `@gsap/react`, `gsap`, `motion`) | none | No | SKIP: novelty, and loading a font inside the component clashes with the app-wide font setup. |
| `logo-animation` | `registry/new-york/motion-framer/logo-animation.tsx` | Logo mark whose parts animate on hover, over a decorative backdrop with a gooey filter. | `framer-motion` | none | No | SKIP: the artwork is the source site's logo. |
| `milestone-odometer` | `registry/new-york/motion-framer/milestone-odometer.tsx` | Rolling odometer. Each digit is a vertical 0-9 strip moved by a motion value. The demo ticks the counter on a timer. | `framer-motion` | none | No | ADAPT: number ticker for usage minutes, credits and call counts. Feed it from data instead of the timer. Under reduced motion, render the final value. Keep the real number in accessible text. |
| `orbit-dot-motion` | `registry/new-york/motion-framer/orbit-dot-motion.tsx` | A dot orbiting in 3D using perspective and rotateY, without stopping. | `framer-motion` | none | No | SKIP. |
| `success-ripple-animation` | `registry/new-york/motion-framer/success-ripple-animation.tsx` | Rings expand outward while a checkmark draws itself by animating its path length. The whole thing loops. | `framer-motion` | none | No | ADAPT: play it once for success moments (campaign launched, payment received, agent published). Remove the loop and add reduced motion. |
| `tab-background-animation` | `registry/new-york/motion-framer/tab-background-animation.tsx` | Tab row where a highlight pill glides to the active tab through a shared layout id. | `framer-motion` | none | No | ADAPT: fits console tabs (call detail: transcript, recording, extraction). Add tablist/tab roles and arrow-key support. Today it is plain buttons only. |
| `text-editor-italic` | `registry/new-york/motion-framer/text-editor-italic.tsx` | Mock text editor in which a drifting cursor applies italics, with a neumorphic toolbar. | `framer-motion`, `lucide-react` | none | No | SKIP: a demo scene. |
| `yoga-invite-card` | `registry/new-york/motion-framer/yoga-invite-card.tsx` | Cream invite card with small entrance micro-animations. | `framer-motion` | none | No | SKIP: a demo scene. |

### Text animations (site `/blocks/text`, 34 files, 33 registry items)

Source: `registry/new-york/text/` (`categories.ts` slug `text`). One file, `text/scroll-typography/engine.tsx`, has no registry entry of its own and is reached through `index.ts`. Several items (`custom`, `engine`, `specs`, `effects`, `index`) carry generic names because they are parts of two multi-file systems. Five items describe themselves as ports of Codrops demos. The four upstream Codrops repositories behind them are MIT-licensed (see "Upstream provenance" at the end), so for those the upstream MIT source is cleaner to take than the port. Most effects in this folder replay on a loop (`repeat: -1`), and the loop must come out for any product use.

| Block (registry name) | Repo path | What it does | npm deps | Shadcn / internal deps | Reduced-motion? | Verdict |
|---|---|---|---|---|---|---|
| `custom` | `registry/new-york/text/animate-text/custom.tsx` | Three layout-aware text renderers from an "animate-text" catalogue that the generic stagger engine cannot express (shared slide, and kinetic centre and stack builds). | `@gsap/react`, `gsap` | imports `./engine` | No | SKIP (console). Marketing: only together with `engine`. |
| `engine` | `registry/new-york/text/animate-text/engine.tsx` | Generic stagger engine. It splits text and plays a declarative spec (from/to frames per phase, stagger origin, easing) using GSAP CustomEase. | `@gsap/react`, `gsap` (entry points: `gsap/CustomEase`) | none | No | ADAPT (marketing): a spec-driven engine is the cleanest way to keep headline reveals consistent. Add reduced motion, which it lacks. |
| `specs` | `registry/new-york/text/animate-text/specs.ts` | Data file of named stagger specs for `engine`. It says it was copied from an "animate-text" catalogue that does not state a licence. | none | imports `./engine` | n/a (data) | ADAPT with `engine` (marketing). Where the catalogue came from is unknown. |
| `gooey-text` | `registry/new-york/text/gooey-text.tsx` | Hover morph between two words through an SVG gooey filter. A port of a Codrops demo. | `@gsap/react`, `gsap` | none | No | SKIP. |
| `line-hover` | `registry/new-york/text/line-hover/line-hover.tsx` | Hover "decode" effects on lines of text. A port of four Codrops demos. | `@gsap/react`, `gsap` | none | No | SKIP (console). Marketing nav: optional. Take it from the MIT upstream. |
| `effects` | `registry/new-york/text/scroll-typography/effects.ts` | 29 scroll-triggered typography effect builders. A port of Codrops "On-Scroll Typography Animations". | `gsap` | none | n/a (builders; reduced motion is handled by the engine) | ADAPT (marketing long-form pages), taken from the MIT upstream. Console: SKIP. |
| `index` | `registry/new-york/text/scroll-typography/index.ts` | Barrel file re-exporting the scroll-typography engine and effects. | none | imports `./effects`, `./engine` | n/a | Same verdict as `effects`. |
| `(unregistered) scroll-typography engine` | `registry/new-york/text/scroll-typography/engine.tsx` | Component that splits text and ties one chosen effect to scroll position. It has no registry entry. | `@gsap/react`, `gsap` (entry points: `gsap/src/ScrollTrigger`, `gsap/src/SplitText`; no registry entry) | imports `./effects` | Yes (skips setup when reduce is set) | ADAPT with `effects` (marketing). |
| `text-assemble` | `registry/new-york/text/text-assemble.tsx` | Characters fly in from scattered positions as the block scrolls into view. | `@gsap/react`, `gsap` (entry points: `gsap/src/ScrollTrigger`, `gsap/src/SplitText`) | none | No | SKIP: busy. |
| `text-black-hole` | `registry/new-york/text/text-black-hole.tsx` | Letters stretch out from the centre as if pulled by gravity. | `@gsap/react`, `gsap` (entry points: `gsap/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |
| `text-block-transitions` | `registry/new-york/text/text-block-transitions.tsx` | Twelve block-wipe reveals where coloured bars sweep across the text. A port of Codrops "Text Block Transitions". | `@gsap/react`, `gsap` | none | No | ADAPT (marketing section headings), taken from the MIT upstream. Add reduced motion. |
| `text-broken-glass` | `registry/new-york/text/text-broken-glass.tsx` | Letters start shattered and rotated, then snap into place. | `@gsap/react`, `gsap` (entry points: `gsap/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |
| `text-burn-neon` | `registry/new-york/text/text-burn-neon.tsx` | Letters flicker, glow red, then settle white. | `@gsap/react`, `gsap` (entry points: `gsap/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |
| `text-fade` | `registry/new-york/text/text-fade.tsx` | Words brighten from dim to full as the paragraph scrolls past (a scrubbed ScrollTrigger). | `@gsap/react`, `gsap` (entry points: `gsap/ScrollTrigger`, `gsap/SplitText`) | none | No | ADAPT (marketing narrative copy). Under reduced motion, show full opacity. |
| `text-glitch-portal` | `registry/new-york/text/text-glitch-portal.tsx` | An RGB-split blur that collapses into clean text. | `@gsap/react`, `gsap` (entry points: `gsap/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |
| `text-gradient` | `registry/new-york/text/text-gradient.tsx` | Text clipped to a moving multi-colour gradient. It relies on an `animate-rainbow` utility and `--color-1..5` variables that the block does not ship. | none | none | No | SKIP: rainbow text is off-brand, and the block is incomplete without that theme CSS. |
| `text-highlight-wave` | `registry/new-york/text/text-highlight-wave.tsx` | When the headline enters the viewport, a highlight colour washes across it one character at a time, line by line. | `@gsap/react`, `gsap` | imports `@/lib/utils` | Yes | ADAPT (marketing hero and section emphasis). It already honours reduced motion. Retokenise the colours. |
| `text-inertia` | `registry/new-york/text/text-inertia.tsx` | Letters trail behind the pointer with GSAP inertia. | `@gsap/react`, `gsap` (entry points: `gsap/InertiaPlugin`, `gsap/SplitText`) | imports `@/lib/utils` | No | SKIP. |
| `text-inline-chip-reveal` | `registry/new-york/text/text-inline-chip-reveal.tsx` | Headline words sharpen from a hue-shifting glow into solid ink, around chips that sit inside the text flow. | `motion` (entry points: `motion/react`) | imports `@/lib/utils` | Yes | ADAPT (marketing): chips naming features (calls, leads, campaigns) inside a headline fit well. It already honours reduced motion. |
| `text-matrix-rain` | `registry/new-york/text/text-matrix-rain.tsx` | Columns of random symbols fall and lock into the real text, repeating on a timer. | `@gsap/react`, `gsap` (registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP: hacker aesthetic. |
| `text-reveal` | `registry/new-york/text/text-reveal.tsx` | Text reveal driven by a tweened value, on a loop. | `@gsap/react`, `gsap` (registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP: the loop never ends. |
| `text-reveal2` | `registry/new-york/text/text-reveal2.tsx` | The same reveal with jitter and colour-glitch keyframes. | `@gsap/react`, `gsap` (registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |
| `text-scatter` | `registry/new-york/text/text-scatter.tsx` | Characters scatter in 3D, then reassemble. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |
| `text-scatter1` | `registry/new-york/text/text-scatter1.tsx` | Variant of text-scatter. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |
| `text-typewriter-glitch` | `registry/new-york/text/text-typewriter-glitch.tsx` | Types, deletes, mistypes, then types the right word. | `@gsap/react`, `gsap` (registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP for headlines. A plain typewriter for a simulated live transcript on marketing is better built fresh. |
| `text-video` | `registry/new-york/text/text-video.tsx` | Text clipped to a background image. The demo hot-links a GIF from a third-party image host. | none | none | n/a (static) | SKIP: third-party hot-link. |
| `text-x-rotate` | `registry/new-york/text/text-x-rotate.tsx` | Characters flip in about the X axis with a stagger, on a loop. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP: the y-slide does the same job with less motion. |
| `text-x-rotate2` | `registry/new-york/text/text-x-rotate2.tsx` | Characters slide in vertically with a blur (SplitText), on a loop. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`) | none | No | SKIP: variant. |
| `text-y-animation` | `registry/new-york/text/text-y-animation.tsx` | Characters rise out of a clipped line with a stagger (SplitText), on a loop. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | ADAPT: the standard masked rise is the one text entrance worth having, for marketing headings and at most a subtle page-title entrance in the console. Play it once and add reduced motion. |
| `text-y-animation2` | `registry/new-york/text/text-y-animation2.tsx` | Variant of the y-slide. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP: variant of the above. |
| `text-y-animation3` | `registry/new-york/text/text-y-animation3.tsx` | Variant of the y-slide. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP: variant. |
| `text-y-animation4` | `registry/new-york/text/text-y-animation4.tsx` | Variant of the y-slide. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP: variant. |
| `text-z-rotate` | `registry/new-york/text/text-z-rotate.tsx` | Characters spin in about the Z axis with a stagger. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |
| `text-z-rotate2` | `registry/new-york/text/text-z-rotate2.tsx` | Variant of the z-spin. | `@gsap/react`, `gsap` (entry points: `gsap/src/SplitText`; registry declares: `@gsap/react`, `framer-motion`, `gsap`) | none | No | SKIP. |

### Borders and intersections (site `/blocks/borders`, 5 blocks)

Source: `registry/new-york/borders/` (`categories.ts` slug `borders`). All five are static Tailwind markup with no animation. The registry description of `star-border` mentions animated corners, but the file has none.

| Block (registry name) | Repo path | What it does | npm deps | Shadcn / internal deps | Reduced-motion? | Verdict |
|---|---|---|---|---|---|---|
| `border-1` | `registry/new-york/borders/border1.tsx` | Four dashed L-brackets, absolutely positioned, mark the corners of the parent. | none | none | n/a (static) | ADOPT: corner brackets frame an empty state or a drop zone (knowledge-base upload) quietly. Its tokens are already semantic (`muted-foreground`). |
| `border-2` | `registry/new-york/borders/border2.tsx` | The same corner brackets, solid. | none | none | n/a (static) | ADOPT: same use as border-1. |
| `intersection-1` | `registry/new-york/borders/intersection1.tsx` | Dashed circle centred where a horizontal and a vertical hairline cross. Both hairlines fade out at their ends. | none | none | n/a (static) | SKIP (console). Marketing section ornament: ADAPT. The greys are hard-coded. |
| `intersection-2` | `registry/new-york/borders/intersection2.tsx` | Frame around a centred child: diagonal-hatched gutter strips plus dashed rules that fade out through Tailwind v4 mask utilities. | none | none | n/a (static) | ADAPT (marketing): the hatched-gutter frame suits a feature panel. Its `mask-*-from-*` utilities are Tailwind v4, the version this repo uses. |
| `star-border` | `registry/new-york/borders/star-border.tsx` | Dashed box with a small four-point star SVG pinned to each corner. | none | imports `@/lib/utils` | n/a (static) | SKIP (console). Marketing: optional ornament. |

### Masks (site `/blocks/masks`, 19 blocks)

Source: `registry/new-york/mask/` (`categories.ts` slug `masks`). All are image reveals. Seventeen use plain GSAP, `noise-dissolve-reveal` uses GSAP with Three.js, and `noise-mask-reveal` uses Three.js alone. None checks reduced motion. There are two broad techniques: animating a `clip-path` shape (inset, circle, polygon), or animating a CSS `mask-image` gradient (conic, repeating-linear, repeating-radial, radial). These are marketing tools. Inside the console, image reveals have no job.

| Block (registry name) | Repo path | What it does | npm deps | Shadcn / internal deps | Reduced-motion? | Verdict |
|---|---|---|---|---|---|---|
| `aperture-mask-reveal` | `registry/new-york/mask/aperture-mask-reveal.tsx` | Six shutter blades twist open around the centre like a camera aperture. | `gsap` | none | No | SKIP: novelty. |
| `blinds-mask-reveal` | `registry/new-york/mask/blinds-mask-reveal.tsx` | The image shows through venetian-blind slats cut by an animated repeating-linear-gradient mask. | `gsap` | none | No | SKIP. |
| `brush-mask-reveal` | `registry/new-york/mask/brush-mask-reveal.tsx` | The image is painted in along a thick brush stroke, by animating the dash offset of a masking path. | `gsap` | none | No | ADAPT (marketing): the stroke-draw-as-mask technique carries over, for example to reveal a dashboard screenshot. Add reduced motion. |
| `center-split-reveal` | `registry/new-york/mask/center-split-reveal.tsx` | The image opens outward from a closed vertical seam, through an inset clip-path. | `gsap` | none | No | SKIP: the plain rectangle reveal covers this. |
| `clock-mask-reveal` | `registry/new-york/mask/clock-mask-reveal.tsx` | A conic-gradient mask sweeps a wedge around the centre like a clock hand. | `gsap` | none | No | ADAPT as a technique: the same conic-mask sweep can drive a radial progress or countdown ring (credit balance, campaign progress) without SVG. Add reduced motion. |
| `directional-mask-reveal` | `registry/new-york/mask/directional-mask-reveal.tsx` | The image wipes in from a chosen edge through an inset clip-path. | `gsap` | none | No | ADAPT (marketing screenshots): the simplest and calmest reveal. Add reduced motion. |
| `ink-blob-mask-reveal` | `registry/new-york/mask/ink-blob-mask-reveal.tsx` | An organic blob polygon splats down and spreads out to reveal the image. | `gsap` | none | No | SKIP. |
| `iris-mask-reveal` | `registry/new-york/mask/iris-mask-reveal.tsx` | A circular clip-path opens from wherever you click. | `gsap` | none | No | SKIP. |
| `keyhole-mask-reveal` | `registry/new-york/mask/keyhole-mask-reveal.tsx` | A keyhole-shaped clip pops in, tilts, then zooms through. | `gsap` | none | No | SKIP. |
| `mosaic-mask-reveal` | `registry/new-york/mask/mosaic-mask-reveal.tsx` | The image is rebuilt from a grid of tiles that pop in. | `gsap` | none | No | SKIP. |
| `noise-dissolve-reveal` | `registry/new-york/mask/noise-dissolve-reveal.tsx` | The image materialises through drifting noise in a Three.js fragment shader. | `gsap`, `three` | none | No | SKIP: pulls in Three.js for one effect. |
| `noise-mask-reveal` | `registry/new-york/mask/noise-mask-reveal.tsx` | Noise-cloud dissolve in a Three.js fragment shader. The file does not import GSAP, despite the registry listing it. | `three` (registry declares: `gsap`, `three`) | none | No | SKIP: Three.js. |
| `pinwheel-mask-reveal` | `registry/new-york/mask/pinwheel-mask-reveal.tsx` | N wedges sweep open around the centre, using a conic-gradient mask. | `gsap` | none | No | SKIP. |
| `rect-mask-reveal` | `registry/new-york/mask/rect-mask-reveal.tsx` | The image stays fixed while an inset clip-path rectangle grows from the centre. | `gsap` | none | No | ADAPT (marketing): a calm reveal for product shots. Add reduced motion. |
| `sonar-mask-reveal` | `registry/new-york/mask/sonar-mask-reveal.tsx` | Concentric rings cut by a repeating-radial-gradient mask thicken until the image is whole. | `gsap` | none | No | SKIP (console). A sonar ring suits a voice product, so marketing may ADAPT the motif, though not this reveal. |
| `spotlight-mask-reveal` | `registry/new-york/mask/spotlight-mask-reveal.tsx` | The image stays dark except for a soft radial-gradient circle that follows the pointer. | `gsap` | none | No | SKIP: pointer only, with no keyboard or touch equivalent. |
| `star-mask-reveal` | `registry/new-york/mask/star-mask-reveal.tsx` | A sparkle-shaped clip-path spins as it scales up. | `gsap` | none | No | SKIP. |
| `text-zoom-mask-reveal` | `registry/new-york/mask/text-zoom-mask-reveal.tsx` | The image shows through a giant hard-coded word ("PIXEL"), which then zooms away. | `gsap` | none | No | SKIP: hard-codes the source site's branding. |
| `wave-mask-reveal` | `registry/new-york/mask/wave-mask-reveal.tsx` | The image fills from the bottom behind a moving wave edge, like rising water. | `gsap` | none | No | SKIP. |

### Outside the seven categories: `svg-path-effects`

This folder backs the site category `svg-path`, not `svg-animations`. It is listed here because it sits beside the reviewed folders.

| Block (registry name) | Repo path | What it does | npm deps | Shadcn / internal deps | Reduced-motion? | Verdict |
|---|---|---|---|---|---|---|
| `guitar-svg` | `registry/new-york/svg-path-effects/guitar.tsx` | Six SVG guitar strings. Dragging across a string bends it into a quadratic curve that follows the pointer; past a threshold it snaps back with an elastic ease and plays the string's note. Each frame, the path is redrawn on the GSAP ticker. | `@gsap/react`, `gsap` | none | No | SKIP: a toy with sound. |

### Upstream provenance

These blocks describe themselves as ports of other people's work. Each GitHub repository below reported an MIT licence (`gh api repos/codrops/<repo> --jq .license.spdx_id` returns `MIT`) as of 2026-10-01.

| Pixel Perfect item | Stated origin | Upstream licence |
|---|---|---|
| `line-hover` | `github.com/codrops/LineTextHoverAnimations` | MIT |
| `gooey-text` | `github.com/codrops/GooeyTextHoverEffect` | MIT |
| `text-block-transitions` | `github.com/codrops/TextBlockTransitions` | MIT |
| `effects` and the scroll-typography engine | Codrops "On-Scroll Typography Animations", sets 1 and 2; `github.com/codrops/OnScrollTypographyAnimations` reports MIT | MIT |
| `specs`, `custom`, `engine` (animate-text) | An "animate-text" catalogue, with no URL or licence in the file | UNKNOWN |

For the four Codrops-derived effects, the MIT originals are the better source: they carry a real grant, and the MIT notice travels with them.

### Shortlist

**Console (ADOPT)**

- `border-1` and `border-2`, as corner brackets for empty states and the knowledge-base drop zone.

**Console (ADAPT: restyle, add semantics and reduced motion)**

- `tab-background-animation`: a sliding active-tab pill, for example on call detail.
- `free-premium-toggle`: a segmented control.
- `toggle-button`: a switch.
- `recessed-stepper-button`: a numeric stepper.
- `blur-toggle-button`: copy/copied style state swaps.
- `milestone-odometer`: a number ticker for usage, credits and call counts.
- `success-ripple-animation`: played once on success.
- `hover-expand-player`: inspiration for the recording mini-player.
- `bar-wave-animation`: a distance-falloff bar hover, or a speaking indicator.
- `clock-mask-reveal`: the conic-mask sweep as a progress ring.
- `stripe-button` and `squircle-counter-button`: as patterns only.

**Marketing site (ADAPT)**

- Headline entrances:
  - `text-y-animation`, played once.
  - `text-highlight-wave`.
  - `text-inline-chip-reveal`.
  - `text-fade`.
  - `engine` with `specs`.
- From the MIT upstreams: the scroll-typography `effects` and `text-block-transitions`.
- Image reveals: `rect-mask-reveal`, `directional-mask-reveal` and `brush-mask-reveal`.
- Section framing: `intersection-1` and `intersection-2`.
- One CTA treatment, chosen from `shiny-button`, `border-gradient-button`, `color-flair-button`, `book-demo-button`, `learn-more-button`, `bevel-button` and the `liquid-button` label swap.

**Everything else is SKIP.** That covers all glass, chrome, metal, neumorphic, neon and gooey buttons, the smiley and mascot SVG scenes, the static SVG assets, the novelty text effects, the Three.js reveals and the pointer-only effects.

---

## Part C: ranked shortlist

The list is ranked by value to the consoles: how many screens a component improves, multiplied by how little work it needs. "Fix first" names the defect from Part A or Part B that must be closed before the first consumer ships.

| # | Component (source) | Verdict | Screens it improves | Fix first |
|---|---|---|---|---|
| 1 | `tabs` (interior, vendored) | ADOPT | Billing (already `useTabs`); agent detail panels (prompt / voice / extraction / knowledge); call detail (transcript / extraction / audio); admin tenant detail | The styled `Tabs` button `ref` (L257-259) overrides `getTabProps().ref`, so the `nodes` map stays empty and arrow-key focus (L65) never moves. Merge the two refs. |
| 2 | `load-more` (interior, vendored) | ADOPT | Calls list and lead timeline (already used); admin audit log; QA sample queue | `rootRef` is read once when the effect runs (L145), so a late-mounted scroll container is ignored |
| 3 | `pagination` (interior, vendored) | ADOPT | Leads footer (already used); admin tenants list; DNC list; invoices | English-only labels; announces "Page X of Y" on mount |
| 4 | `skeleton-swap` (interior, vendored) | ADOPT | Credit balance and usage KPI cards; agent cards; admin health tiles; any TanStack Query fixed-size card | Use on fixed-size cards only, not variable-length lists |
| 5 | `copy-button` (interior) | ADOPT | Lead-source/webhook URLs; agent, call and execution ids; invitation links; support reference ids; admin tenant slug | Accessible name is always "Copy"; move the live region out of the button; replace the four ad-hoc clipboard copies |
| 6 | `segmented-control` (interior) | ADOPT | Usage period (7d / 30d / 90d); calls direction (inbound / outbound); Clear / Studio voice filter in the voice picker; admin spend grouping | Tokenise colours; long labels overflow at 320px |
| 7 | `task-steps` (interior, vendored) | ADOPT | Agent publish (compliance-line check, engine sync); KB document ingestion; campaign launch compliance gate (SECURITY-COMPLIANCE §3) | Stop the spinner under reduced motion; add sr-only per-row status |
| 8 | `progress-bar` (interior, vendored) | ADOPT | KB upload; campaign dial progress; CSV lead import; monthly credit consumption | Add a static indeterminate cue under reduced motion |
| 9 | `show-more` (interior, vendored) | ADOPT | Call summary and transcript excerpts in lists; agent prompt preview; lead notes; long legal and attestation text in admin | Clipped content stays focusable when collapsed; set `inert` |
| 10 | `drawer` (interior) | ADAPT | Lead detail opened from the leads table; call detail from the calls list; mobile nav (reconcile with `navDrawer.tsx`) | Its modal sweep makes toaster portals inert; Escape from an un-stopped nested popover closes it; unify with `useFocusTrap` |
| 11 | `command-palette` (interior) | ADAPT | Global Cmd+K in both consoles (jump to agent / campaign / lead, open billing); admin tenant switcher and the big red switch as a command | Not a real dialog: add `role="dialog"`, focus trap and restore; refocus the input on reopen (L214-216); async entity search |
| 12 | `dropdown` (interior, vendored) | ADAPT | Row actions on leads, calls, agents and campaigns (the replacement for context-menu); voice and model picker filters | Trigger shows a static label, not the value; no portal; Escape propagates (L210-212); Tab swallowed |
| 13 | `live-activity` (interior, vendored) | ADAPT | Running campaign status; KB ingestion; CSV import; admin bulk operations | Every `update()` restarts the 2.6s peek (L192), so a busy task never collapses; no `role="progressbar"`; not keyboard-expandable |
| 14 | `new-items-pill` (interior, vendored) | ADAPT | Polled calls list ("3 new calls"); live transcript scroll-back; admin QA queue | Scroll listener never attaches if the scroller mounts after the hook (L54-74); "99+" ignores a custom label |
| 15 | `collapsible-banner` (interior, vendored) | ADAPT | Low credit balance; DLT registration pending; Clear voice rung unavailable; big red switch engaged; admin "attestation missing" | A dismissed banner collapses to height 0 but stays focusable (focus lands on an invisible button); add `inert` |
| 16 | `value-flash` (interior) | ADAPT | Credit balance after a top-up; live campaign counters; admin vendor-spend and health numbers | Numbers only, which pushes INR through floats (hard rule 7). Wrap `useValueFlash<string>` with a decimal-safe `compare`; add a "higher is worse" tone |
| 17 | `sortable-table` (interior) | ADAPT | Small client-side admin tables: tenants, vendor spend by provider, voices, ops config rows | Client-side sort and fixed row heights only; not for the server-paginated leads table unless sort becomes controlled |
| 18 | `wizard-steps` (interior, vendored) | ADAPT | Agent creation; campaign setup (audience, script, schedule, compliance); tenant onboarding in admin | No per-step validation gate on Next; fixed 184px panel height |
| 19 | `tag-input` (interior) | ADAPT | Bulk DNC number entry (E.164); extraction-schema enum values; KB document tags; team invite emails | `validate` returns a boolean (no reason) and only the last rejection is reported |
| 20 | `typing-indicator`, as a new `SpeakingIndicator` (interior) | ADAPT | Live call view and admin QA live listen: which side, caller or agent, is speaking (the founder's proposal) | Single bottom-left bubble, a fixed "typing" label, announces every change. Lift only the dot wave, render it hidden from screen readers per side, and keep the transcript in a `role="log"`. No speaking-state event reaches the browser yet: a normalised event from `apps/voice-worker` through the API is the prerequisite (hard rule 2) |
| 21 | `tooltip-group` (interior) | ADAPT | Metric definitions on usage and billing (what a call-minute is, the Clear vs Studio rate); icon-only buttons in tables | No portal, so it is clipped inside scrolling tables; needs collision-aware positioning |
| 22 | `popover` (interior) | ADAPT | Leads `ColumnChooser` (currently a native `<details>` that names a Popover as its replacement); saved-view menus | No portal; trigger is always its own `<button>`; Escape handling swallows the key for nested content |
| 23 | `milestone-odometer` (Pixel Perfect) | ADAPT | Credit balance and call-count tickers on the client dashboard; admin spend totals | No licence (Part B); restyle; honour reduced motion; feed it strings, not floats, for INR |
| 24 | `border-1` / `border-2` (Pixel Perfect) | ADOPT | Empty states (no agents, no calls yet); KB upload drop zone | No licence (Part B); keep the attribution header |

All the interior.dev picks above already depend only on `motion`, which `apps/web` has (`motion ^13.1.1`). None of them needs a new dependency.
