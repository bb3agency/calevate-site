# The Calevate interface kit

This is the reference the screen lanes build from. Every shared component, what it takes,
when to use it and when not to, and the feedback standard every action follows. The living
version is the admin page **`/admin/ops/kit`**: every component on this page is rendered
there in every state with real props, and that page is what the browser checks run against
(375, 768 and 1280 px).

Sources: the founder's answers for this wave (rememory `f7d9f716`), the Arc catalogue
(`docs/design/UIARC-COMPONENTS.md`, source in `docs/design/uiarc/`), `docs/design/REDESIGN-2.md`
and `docs/design/UI-COMPONENTS.md`. Where this file and the catalogue disagree about which
component wins, this file records the decision that was built.

## Rules that hold for every component

- **One way per problem.** Each problem below has one component. If a screen needs
  something the kit does not do, extend the kit component (and this file); never write a
  second one beside it.
- **Tokens, not values.** Tailwind utilities on the role tokens in `src/app/globals.css`
  (`bg-surface`, `text-ink-muted`, `border-line`, `bg-brand-strong`, `text-warn`,
  `text-danger`, `--series-1..6` for charts). No raw hex, no CSS modules, no Arc
  `foundation.css`. The product is light only (D-471); the dormant `.dark` palette is carried
  by the tokens, so no component needs `dark:` utilities.
- **Arc token map** (what every adapted Arc file was rewritten to): `--foreground` →
  `--text`; `--text-secondary` → `--text-muted`; `--text-muted` → `--text-faint`; `--border`
  → `--line`; `--accent`/`--control-on` → `--brand`; `--accent-strong` → `--brand-strong`;
  `--accent-subtle` → `--brand-soft`; `--warning` → `--warn`; `--success` → `--brand`;
  `--shadow-raised/floating` → `shadow-raised`/`shadow-overlay`; `--series-1..4` →
  `--series-1..6`; radii → `rounded-md` / `rounded-card` (14px). Fonts stay PP Mori.
- **Focus.** Every control draws `focus-visible:ring-2 focus-visible:ring-brand` itself; there
  is no global outline rule to lean on.
- **Touch.** Under a coarse pointer every target is at least 44px (`touch:min-h-11`,
  `touch:h-11 touch:w-11`); text inputs are 16px there so iOS does not zoom.
- **Layers.** Only the `z-*` utilities (`tests/zIndex.test.ts`). Floating panels anchored to
  a trigger (popover, menu, tooltip, hover card) are portalled on **`z-popover`**, above
  dialogs and drawers, so a menu opened inside a drawer is never painted under it. In-flow
  dropdowns that open inside their own component use `z-dropdown`.
- **Motion.** Only where it explains state. CSS for entries (`popover-enter`, `modal-enter`,
  `sheet-enter`, `scrim-enter`); `motion/react` only for gestures and lists, with the numbers
  from `components/arc/motion.ts` (which mirror the CSS tokens; a test keeps them equal).
  Under `prefers-reduced-motion` nothing moves; opacity changes may remain.
- **Words.** Every visible English string is a prop with a default. Client text never names
  a vendor (D-679). No emoji.
- **Numbers, money, time.** Counts through `formatCount` (en-IN, lakh grouping). Money is a
  decimal string end to end (hard rule 7) and is printed through `formatINR` /
  `formatRupeeRate`; a `₹` is never glued to a bare value (`tests/formatterGuard.test.ts`).
  Dates and times are IST through the `formatIST*` helpers; "today" is `istDateStamp()`.
- **Licence.** Files adapted from Arc keep a header naming uiarc and its MIT licence; the
  licence text is `components/arc/LICENSE`.

## Radix: where it is used and where it is not

The seven `@radix-ui` packages were installed for this wave. They are used where they give
correct behaviour the in-repo code did not have; where an in-repo primitive was already
correct it stayed.

| Package | Used? | Why |
|---|---|---|
| `react-popover` | Yes: `arc/popover.tsx` (and `InfoTip`, `NotificationCenter`, `HoverCard`, the multi-select and date pickers) | Collision-aware placement, focus in and back, dismiss that respects nested layers. Non-modal, so toasts stay announced. Replaced `interior/popover`. |
| `react-dropdown-menu` | Yes: `arc/menu.tsx` (`Menu`, `RowMenu`) | APG menu keyboard model, type-ahead, collision handling. Non-modal. A click with no pointer press (screen-reader virtual cursor, voice control) toggles it, which Radix alone does not. Replaced `console/rowMenu.tsx`. |
| `react-tooltip` | Yes: `arc/tooltip.tsx` | Grouped delay (`TooltipProvider` in `app/providers.tsx`). |
| `react-dialog` | No | `ModalDialog`/`ConfirmDialog`/`Drawer` keep `lib/focusTrap`: a Radix modal dialog hides the rest of the page from assistive tech, which would silence the toast stack while a dialog is open. |
| `react-switch` | No | `ToggleSwitch` (ui.tsx) is a native `role="switch"` checkbox: already correct. |
| `react-accordion` | No | `Disclosure` (native `<details>`, now with an exclusive `name` group) is already correct. |
| `react-tabs` | No | `interior/tabs` is correct and tested. |

The three unused packages are supply-chain surface with no consumer; removing them from
`apps/web/package.json` is a founder call (they were installed on request).

## The feedback standard

The founder's rule (24 Oct 2026): every action shows **pending**, then **success** or
**failure**, on the control that was pressed; a failure also reaches the toast stack with
the server's plain sentence and its error code; a reversible success may offer **Undo**.

### `useActionFeedback(mutation, options)` — `components/arc/feedback.tsx`

Pass every TanStack mutation a screen creates through it. It watches the mutation (so
`mutate`, `mutateAsync` and `run` all work), returns `{ status, run, error, reset }`, and
raises the toasts. Each settled submission is announced once.

| Option | Type | Purpose |
|---|---|---|
| `errorTitle` | `string` | Title of the failure toast ("Could not save the script"). The server's own title wins when the problem has one. |
| `errorDisplay` | `"toast"` (default) \| `"inline"` | `inline` when the screen shows `ProblemNotice` beside the control (forms); the button still shows its error face. |
| `successToast` | `string \| (data, vars) => string \| null` | Only when the result lands where the person is not looking, or there is an Undo. Most saves need none: the button's tick says it. |
| `successDescription` | `string \| (data, vars) => string \| undefined` | One more sentence. |
| `undo` | `(data, vars) => void` | Only where reversing is safe and the server can do it. Never for a call placed, a message sent or money moved. |
| `undoLabel` | `string` | Default "Undo". |

Create the feedback where the mutation is created, and pass `feedback.status` (not the
mutation) down to the component that renders the button.

### `ActionButton`

| Prop | Type | Purpose |
|---|---|---|
| `children` | `ReactNode` | The idle label, a verb ("Save changes"). It is also the accessible name in every state. |
| `status` | `"idle" \| "pending" \| "success" \| "error"` | From `useActionFeedback` / `useAsyncAction`. |
| `pendingLabel` | `ReactNode` | Default: the idle label beside a spinner. |
| `successLabel` | `ReactNode` | One past-tense word: "Saved", "Sent", "Copied". Default "Done". |
| `errorLabel` | `ReactNode` | Default "Try again". |
| `variant` | `primary` \| `primary-lg` \| `primary-sm` \| `secondary` \| `secondary-sm` \| `danger` | The `ui.tsx` button looks. |

All four faces share one grid cell, so the button never changes width. While pending it is
`aria-busy` and ignores presses but keeps focus (`aria-disabled`, not `disabled`). The
outcome is spoken from a status line outside the button, so it never joins the name.
Success shows for two seconds, then the idle label returns; an error stays until the next
press.

### `useAsyncAction(fn, options)`

The same contract for actions that are not mutations (copying, a download, a browser
permission). A throw or rejection is the failure.

### The toast stack — `components/arc/toast.tsx`

Mounted once per realm (`app/c/[slug]/layout.tsx`, `app/admin/layout.tsx`), portalled on
`z-toast`. `useToast()` returns `{ toast, update, dismiss }`; outside a provider it is a
no-op, so a screen in a unit test does not crash.

- `toast({ id?, kind, title, description?, code?, action?, duration? })`, `kind` one of
  `success`, `info`, `warning`, `error`, `loading`. Reusing an `id` replaces the toast in
  place (a `loading` toast becomes its result).
- Bottom-right on a desktop, newest nearest the edge; full width at the top on a phone, so
  it never covers the thumb's actions or a bottom sheet.
- Successes and notes leave after 5 s; errors and `loading` stay until replaced or closed.
  Hover, focus or a hidden tab pauses the countdown. Swipe sideways or press Escape on a
  toast to dismiss it.
- Errors are announced assertively, everything else politely, from two live regions; the
  cards themselves are not live regions.

### What a toast is not for

- A success the button already shows.
- A form error that belongs beside its field (`ProblemNotice`, field messages).
- Anything the person must decide before continuing (`ConfirmDialog`).

### The guard — `tests/feedbackGuard.test.ts`

It derives every hook that returns a mutation from the source (a `use*` function whose body
returns `useMutation(...)` or another such hook, to a fixed point) and fails any file in
`src/app` or `src/components` that assigns one to a name without passing that name to
`useActionFeedback` in the same file, or that calls one without assigning it.
`tests/fixtures/feedbackBaseline.ts` lists the sites that predate the standard: it only
shrinks. Moving a screen's mutation onto the standard makes its entry stale, and the guard
then fails until the entry is deleted.

### Do / don't

- Do put the state on the button the person pressed. Don't show a separate spinner beside it.
- Do keep `ProblemNotice` inline for a form, with `errorDisplay: "inline"`.
- Don't toast a success that is visible where the person is looking.
- Don't offer Undo for anything that already left the building (a call, a WhatsApp message,
  a charge).
- Don't disable a button to show it is busy; `status="pending"` does that and keeps focus.

## Overlays

### `Popover` — `components/arc/popover.tsx`

`trigger` (one focusable element), `children`, `label` (the panel's name), `open?`,
`defaultOpen?`, `onOpenChange?`, `side?`, `align?`, `offset?`, `className?`.
`PopoverClose` wraps a close control inside. `FLOATING_PANEL` is the shared surface class
for every floating panel. Use for a small form or a list anchored to a control. Not for
help text (`InfoTip`) or actions (`Menu`).

### `InfoTip` — `components/console/infoTip.tsx`

The ⓘ toggletip: tap, click or Enter opens it; Escape or a press outside closes it; focus
moves in. For explanation a reader can do without. Never for a compliance sentence, an
error or a refusal: those stay on the page.

### `Menu`, `RowMenu` — `components/arc/menu.tsx`

`Menu`: `trigger`, `items`, `label`, `align?`, `side?`. `RowMenu`: the ⋯ button for one row,
`label` = the row's name ("More actions for Reception"), `items`, `align?`, `className?`.
`MenuItem`: `{ id, label, onSelect?, href?, tone?: "danger", disabled?, hint?, ariaLabel?,
icon?, separated? }`. A disabled item keeps its reason as the hint. A destructive item is
red and still goes through `ConfirmDialog` when it cannot be undone.

### `Tooltip` — `components/arc/tooltip.tsx`

`content`, `children` (an icon button with its own `aria-label`), `side?`. Pointer devices
only in practice; it repeats the control's name and never holds information found nowhere
else.

### Escape and layers

`lib/focusTrap` closes a dialog or drawer on Escape only when the key was pressed inside
it; an Escape pressed in a menu, popover or nested dialog opened from it closes only that
layer.

## Inputs

Every kit field puts a visible label above the control, optional help under the label, and its own error under the control. `Field` (`components/arc/field.tsx`) does the wiring once: `aria-describedby` → hint + error, `aria-invalid` while there is an error, the message drawn by `FieldMessage` (`components/formValidation.tsx`). A form using `useFormValidation` passes `validation.message(name)` as `error`. Inputs are 16px on a coarse pointer (global rule in `globals.css`), so iOS never zooms. Validation is said on leaving a field or on submit, never per keystroke.

Choosing the right control:

| Need | Use |
|---|---|
| Filter a list by text | `SearchField` (`ExpandingSearch` in a phone toolbar) |
| One value from many (find by typing) | `Combobox` |
| Several values from a list | `MultiSelect` (≤5 options on screen: checkboxes or `ChipGroup`) |
| Toggle filters over what is shown | `ChipGroup` (built on `ui.tsx` `FilterChip`) |
| A short list of free-text values | `TagInput` |
| Rename a heading in place | `InlineEdit` (leads table keeps `InlineName`) |
| A small bounded count | `NumberField` — never money |
| Rupees | `MoneyInput` — decimal string, lakh grouping |
| One day / a span of days | `DatePicker` / `DateRangePicker` (`Calendar` inline) |
| "About here" on a scale | `Slider` / `RangeSlider` (`SliderTrack` inside a composite) |
| 2–4 one-word options | `SegmentedControl` (`interior/segmented-control.tsx`) |
| ≤6 options with a line of help | `RadioGroup` |
| Few weighty options with a sentence each | `ChoiceCard` (`console/choiceCards.tsx`) |
| This month / All time over a money view | `PeriodToggle` |
| On/off setting | `ToggleSwitch` (`ui.tsx`) |

### Field (`arc/field.tsx`)
`Field({ label, hideLabel?, hint?, error?, id?, className?, children: (control) => ReactNode })` — spread `control` (`id`, `aria-describedby`, `aria-invalid`) onto the control. `FIELD_FLUSH` = `FIELD` without its top margin, for a control inside a positioned wrapper.

### SearchField / ExpandingSearch (`arc/search-field.tsx`)
`SearchField({ label, hideLabel?, value, onValueChange, onSearch?, debounceMs = 300, clearLabel = "Clear search", slashToFocus?, maxLength = 100, ...input })`. `onValueChange` every keystroke; `onSearch` once the typing settles, at once on Enter and on clear (never the same query twice). Escape empties the box (a second Escape is left to the page). Clear button 44px on touch. `ExpandingSearch` (same props + `openLabel`) is an icon button below `sm` that opens full width, closes on Escape or on blur when empty and returns focus to the button.
Do: one `slashToFocus` per screen; send `onSearch` to the API. Don't: hand-roll `Search` icon + `FIELD_INLINE_ICON`.

### Combobox (`arc/combobox.tsx`) — replaces `console/searchSelect.tsx`
`Combobox({ label, hideLabel?, hint?, error?, options: {value,label,hint?,disabled?}[], value: string|null, onChange, allLabel?, placeholder?, onQueryChange?, loading?, loadingText?, emptyText?, clearLabel?, disabled? })`. APG select-only combobox: typing filters, arrows skip disabled options, Enter picks, Escape restores the chosen label. `allLabel` adds a leading "every option" row and a clear button (`null` = all). `onQueryChange` switches to server search (no local filtering) with `loading`. The list opens inside the component on `z-dropdown` so it scrolls with its form.

### MultiSelect (`arc/multi-select.tsx`)
`MultiSelect({ label, hideLabel?, hint?, error?, options, value: string[], onChange, emptyLabel = "Any", countLabel?, filterFrom = 9, filterLabel?, selectAllLabel = "Choose all", clearLabel = "Clear", disabled? })`. A field-styled button summarising the choice ("Booked, Call back" / "3 chosen") opens a popover of native checkboxes; a filter box appears from `filterFrom` options. Emits in the caller's option order.

### ChipGroup (`arc/chip-group.tsx`)
`ChipGroup({ mode: "single", value: string|null, onChange } | { mode: "multiple", value: string[], onChange }, label, chips: {value,label}[], allLabel?, className? })`. `role="group"` named by `label`; each chip is `FilterChip` (`aria-pressed`). Chips filter what is shown; to choose a form value use `RadioGroup` or `MultiSelect`.

### TagInput (`arc/tag-input.tsx`)
`TagInput({ label, hint?, error?, value: string[], onChange, suggestions?, placeholder?, maxTags = 30, maxLength = 40, validate?, duplicateMessage?, limitMessage?, removeLabel?, disabled? })`. Enter or comma adds; Backspace in an empty box removes the last; arrows pick a suggestion. Duplicates (case-insensitive), the limit and `validate` refusals are said under the field.

### InlineEdit (`arc/inline-edit.tsx`)
`InlineEdit({ value, onSave(next), status?, label, as?, textClassName = "text-heading", maxLength = 120, placeholder?, validate?, errorMessage?, editLabel?, saveLabel = "Save", cancelLabel = "Cancel", savedLabel = "Saved", disabled? })`. Pass `status` from `useActionFeedback(mutation, { errorDisplay: "inline" }).status` and call `feedback.run(next)` in `onSave`. Pending keeps the field open and busy; success closes it with a short "Saved"; failure keeps the typed text and shows the reason. Unchanged text sends nothing; Escape cancels; blur saves. Not for a table cell that is also a link.

### NumberField (`arc/number-field.tsx`)
`NumberField({ label, hint?, error?, value: number|null, onChange, min = 0, max?, step = 1, largeStep = step×10, unit?, optional?, decreaseLabel?, increaseLabel?, clampedMessage?, disabled? })`. `role="spinbutton"` with value text; Arrow keys (Shift = large), PageUp/PageDown, Home/End; typing applies on blur or Enter, Escape reverts; typing past a limit is pulled back and said. Steppers 44px on touch. en-IN digits. NEVER for money.

### MoneyInput (`arc/money-input.tsx`)
`MoneyInput({ label, hideLabel?, hint?, error?, value: string, onChange(string), min?: string, max?: string, paise = true, quickAmounts?: string[], quickAmountsLabel?, belowMinMessage?, aboveMaxMessage?, disabled?, required?, name? })`. The value is the canonical decimal string the API takes ("12500.00", "" when empty); it never passes through `Number`. The box groups 1,25,000 while typing and keeps the caret; keystrokes that are not an amount are refused; limits are compared as paise in `BigInt` and said on blur. Helpers: `toPaise`, `compareMoney`, `canonicalMoney`, `groupTyped`. `paise={false}` for whole rupees. A 4-decimal rate is not this field.

### Calendar / DatePicker / DateRangePicker (`arc/calendar.tsx`, helpers `arc/ist-dates.ts`)
Dates are IST calendar days `"YYYY-MM-DD"`; "today" is `todayIST()` (`istDateStamp`); turn one into an instant for the API with `istDateToInstant` (`ui.tsx`). Weeks start Monday.
- `Calendar({ selected: ISODate | {start,end} | null, onSelect, min?, max?, isDisabled?, initialMonth?, rangeAnchor?, label?, previousMonthLabel?, nextMonthLabel?, todayLabel?, focusOnMount? })` — APG grid: arrows day/week, Home/End week ends, PageUp/PageDown month (Shift: year), Enter/Space picks; disabled days are announced and refuse; today is underlined and `aria-current="date"`; cells 44px on touch.
- `DatePicker({ label, hideLabel?, hint?, error?, value: ISODate|null, onChange, min?, max?, isDisabled?, placeholder?, clearable?, clearLabel?, disabled? })`.
- `DateRangePicker({ label, …, value: {start,end}|null, onChange, min?, max?, presets = defaultRangePresets(), presetsLabel?, pickEndHint?, clearLabel? })` — presets Today, Yesterday, Last 7 days, Last 30 days, This month, Last month (all IST); two taps pick a span in either order.
Helpers: `addDays`, `addMonths`, `monthGrid`, `weekdayIndex`, `startOfMonth`, `endOfMonth`, `daysBetween`, `isISODate`, `formatDateLong/Short/Range`, `formatMonth`.

### Slider / RangeSlider / SliderTrack (`arc/slider.tsx`) — replaces `ui.tsx` `RANGE_INPUT`
`Slider({ label, hideLabel?, hint?, value, onChange, min, max, step = 1, valueText?, spokenText?, scale?: ReactNode[], marks?: number[], labelAction?, disabled?, id? })` — native range input with the value as words beside the label (`spokenText` when the shown text is a symbol), a filled track, scale captions and preset marks; 24px thumb on touch. `RangeSlider({ …, value: [lo, hi], onChange, lowerLabel = "From", upperLabel = "To" })` — two thumbs that cannot cross. `SliderTrack` is the bare input for a composite that draws its own label (ROI calculator).

### RadioGroup (`arc/radio-group.tsx`)
`RadioGroup({ label, hint?, error?, options: {value,label,hint?,disabled?}[], value: string|null, onChange, inline?, name?, disabled? })` — native radios in a `fieldset role="radiogroup"`, each with an optional line of help.

### PeriodToggle (`arc/period-toggle.tsx`)
`PeriodToggle({ value: "month"|"all", onChange, label = "Show", monthLabel = "This month", allLabel = "All time" })` — `SegmentedControl` with the two periods named once. "This month" is the IST calendar month. (uiarc's billing-toggle, reshaped: there are no monthly/annual plans.)

### Kept, not replaced
- `SegmentedControl` (`interior/segmented-control.tsx`, 21 callers) is the kit's segmented control.
- `ToggleSwitch` (`ui.tsx`) is a native `role="switch"` checkbox and stays; no bare `Switch` was needed.
- `ChoiceCard` stays for weighty choices; `FilterChip` stays the chip primitive.
- `InlineName` (leads table) stays: its name is a link.

### Do / don't
- Do keep every refusal as a sentence that says how to fix it, under the field.
- Do send money and dates as the strings the API takes; never `Number(amount)`, never `new Date("YYYY-MM-DD")`.
- Don't put `type="number"` or `type="date"` in a new screen; use `NumberField` / `MoneyInput` / `DatePicker`.
- Don't hand-roll a search box, a radio list or a range input.

## Charts and figures

Plain SVG on Calevate tokens; no chart library. Kit page: `/admin/ops/kit#charts`. Tests: `apps/web/tests/kit/charts.test.tsx`.

### Rules every chart follows
- **Two renderings of one dataset.** The marks are `aria-hidden`; a real `<table>` (visually hidden, revealed by "Show as table") carries the numbers for screen readers and as relief when colours are hard to tell apart. Hover readouts are a pointer enhancement only.
- **Series colours** are `--series-1..6` (globals.css; utilities `bg-series-1…`), assigned by the series' position in the caller's list and never cycled. Brand green leads. Validated with the dataviz skill's `validate_palette.js`: every slot at least 3:1 on the surface, worst adjacent CVD ΔE 11.0, normal-vision ΔE 18.1. A 7th part folds into "Other". Text never wears a series colour.
- **Sequential magnitude** (heatmap) is one hue: `color-mix(in oklab, var(--series-1) N%, var(--surface))`.
- **Money and minutes** arrive as decimal strings (hard rule 7). Pass `Number(wire)` only for geometry and the exact text from `formatINR` / `formatCount` through `display`; a reader never sees a browser-derived float.
- **Time** labels are formatted by the screen in IST before they reach a chart (`istShortDay` in `chart-core.tsx`, or `formatIST*` in `ui.tsx`); charts never convert a zone.
- **States:** every chart takes `loading`, `error` (plain words, rendered as `role="alert"`), `empty` (the screen's own sentence) and `loadingLabel`. Loading reuses `Skeleton` at the plot's height, so nothing jumps.
- **Marks:** 2px lines, bars at most 24px with a 4px rounded data end and a square foot, a 2px surface gap between touching marks, hairline gridlines, compact en-IN ticks (`1.2L`, `12K`). No draw-in animation; hover emphasis transitions are `motion-safe:` only.
- **Responsive:** plots measure their container (`ResizeObserver`); horizontal bars and legends are HTML so labels wrap instead of being cut. No horizontal page overflow at 375px.

### `chart-core.tsx` (shared pieces)
`SERIES`, `seriesColor(i)`, `formatCompact(n)`, `istShortDay(instant)`, `niceTicks(max, count?)`, `useMeasuredWidth`, `usePlotWidth`, `Legend`, `ChartFrame`, `ChartTooltip`, types `ChartStateProps`, `ChartTable`, `LegendItem`. Build a new chart on `ChartFrame` so it inherits states, the table and the toggle.

### Sparkline (`arc/sparkline.tsx`)
`values: number[]`, `label: string` (spoken with first and last value), `summary?`, `tone?: "brand" | "neutral"`, `area?`, `height?`. An image, not a plot: no axes, no scrubbing. Fewer than two points renders "—". Use beside a figure (`Metric trend`), never alone as the only carrier of a number.

### LineChart (`arc/line-chart.tsx`)
`title`, `hideTitle?`, `description?`, `labels: string[]` (formatted by the screen), `series: { label, values: (number|null)[], display?: string[] }[]`, `area?` (single series only), `height?` (200), `formatTick?`, `labelColumn?`, + states. `null` is a gap, never zero. Crosshair readout on hover. Use for change over time; not for parts of a whole.

### BarChart (`arc/bar-chart.tsx`)
`categories: string[]`, `series: { label, values: number[], display?: string[] }[]`, `orientation?: "vertical" | "horizontal"`, `stacked?`, `showValues?` (horizontal: value at the tip), `height?`, `formatTick?`, `labelColumn?`, + states. Vertical is SVG columns; horizontal is HTML rows (wrapping labels: agent names, Telugu titles). All-zero data is the empty state. Use for magnitude per category or per day.

### DonutChart (`arc/donut-chart.tsx`)
`segments: { label, value, display? }[]`, `centerValue?`, `centerLabel?`, `otherLabel?` ("Other"), `size?`, `labelColumn?`, `shareColumn?`, + states. At most six parts; the rest fold into Other. Legend carries words and share. Use only when the whole is meaningful (how calls ended, where credit went).

### ActivityHeatmap (`arc/activity-heatmap.tsx`)
`cells: { weekday: 0..6 (Mon first), hour: 0..23, count }[]` (the server's IST buckets), `weekdays?`, `unit?` ("calls"), `fewerLabel?`, `moreLabel?`, + states. 7 × 24 grid, five brand steps, key "Fewer → More", table of 7 rows × 24 hours.

### BrushChart (`arc/brush-chart.tsx`)
`labels`, `values`, `display?`, `seriesLabel`, `defaultRange?: [from, to]` (default the last quarter), `onRangeChange?`, `startLabel?`, `endLabel?`, `rangeText?(from, to)`, `height?`, + states. Detail is a `LineChart` of the window; the overview strip has a draggable window and two edges that are `role="slider"` (arrows ±1 bucket, Page Up/Down ±7, Home/End), and the selection is said in words (polite live region). Use for long dated series (leads per day over a quarter, a campaign since launch).

### Ridgeline (`arc/ridgeline.tsx`)
`series: { label, values: number[] }[]` (raw durations), `formatValue?` (default m:ss), `maxValue?` (cut a long tail), `rowHeight?`, column labels, + states. Gaussian KDE with Silverman bandwidth; one colour (same measure), median tick; table gives median, middle half, count. Use to compare call lengths across agents or weeks.

### Gauge — agent readiness (`arc/gauge.tsx`)
`value: number | null` (0–100), `label`, `bands?` (default `READINESS_BANDS`: <50 Needs work, <80 Nearly ready, ≥80 Ready), `pendingText?`, `fixes?: { id, label, detail?, points?, href?, action? }[]`, `fixesTitle?`, `allDoneText?`, `pointsLabel?`, `size?`. `role="meter"` with the band in `aria-valuetext`; the band is always written, never colour alone. `null` is "—" with its reason, never 0. Presentational: the score and fixes come from the server (Lane B). Use on each agent and on the dashboard.

### Metric / MetricRow (`console/metric.tsx`) — the one KPI unit
uiarc `metric-card` was reviewed and lost; `Metric` gained `delta?: { text, direction: "up"|"down"|"flat", good?: boolean, context? }` (colour from `good`, not from the sign — fewer failed calls is good news) and `trend?: ReactNode` (a `Sparkline`). Unknown value is "—" with a hint.

### StatsBand (`arc/stats-band.tsx`)
`items: { label, value (formatted string), flashValue?, delta?, trend?: number[], hint?, tone? }[]`, `label?` (region name), `className?`. Data in, `MetricRow` + `Metric` out — not a second KPI component. Use for the headline row of an analytics screen.

### UsageMeter (`arc/usage-meter.tsx`)
`label`, `used: number`, `limit: number` (≤0 = no limit, no bar), `usedText`, `limitText?`, `caption?`, `valueText?`, `warnAt?` (0.9), `overTone?: "warn" | "danger"` (billed overage is warn; a hard stop is danger), `segments?` (up to four parts), `hint?`, `variant?: "block" | "inline"`, `noLimitText?`. `role="meter"`; the figures read are the caller's strings. Use for trial minutes, the spending cap, the instructions budget. Not for task progress (`interior/progress-bar` stays for that).

### Timeline (`arc/timeline.tsx`)
`Timeline` (`label?`) wraps `TimelineItem` (`title`, `detail?`, `meta?`, `icon?` lucide, `markerClassName?`, `children?` for rich bodies). An `<ol>` with a CSS rail; no reveal animation. Use for lead, call and campaign history.

### Countdown (`arc/countdown.tsx`)
`target` (ISO instant), `serverNow?` (corrects a wrong device clock), `label?`, `doneText?`, `units?`, `showTarget?` (IST date after the count). `formatRemaining(seconds, units?)`. Built on `lib/authn/useCountdown` (one ticking engine). `role="timer"`, not live. Past two days show an IST date (`formatIST`) instead of a countdown.

### Do / don't
- Do pass formatted `display` text for money; don't let a chart format rupees.
- Do give every chart a `title` (it names the table) and an `empty` sentence in the screen's words.
- Don't use two y-axes; draw two charts.
- Don't add a seventh series colour; fold or facet.
- Don't put a number on every mark; the table and readout carry them.

### Screens still to migrate (dashboard/analytics lane unless noted)
- `apps/web/src/app/c/[slug]/DailyCalls.tsx` → `BarChart` (vertical) or `LineChart`.
- `apps/web/src/app/c/[slug]/OutcomeSplit.tsx`, `apps/web/src/app/c/[slug]/SentimentSplit.tsx` → `DonutChart` or horizontal `BarChart`.
- `apps/web/src/app/c/[slug]/performance/PerformanceCharts.tsx` (HourHistogram and the rest) → `BarChart`; hour-by-weekday → `ActivityHeatmap` (needs Lane B's endpoint).
- `apps/web/src/app/c/[slug]/billing/SpendChart.tsx` → `BarChart`/`LineChart` with `display` from `formatINR`; `billing/WhereItWent.tsx` → `DonutChart`.
- `apps/web/src/app/c/[slug]/billing/UsageView.tsx` (and UsageTab figures) → `UsageMeter` for minutes and the cap; `StatsBand` for the headline.
- `apps/web/src/app/c/[slug]/TrialCallPanel.tsx` / `TrialBanner.tsx` free-minutes line → `UsageMeter` (TrialBanner is owned by the structure lane).
- Readiness gauge on each agent and the dashboard → `Gauge` once Lane B ships the score endpoint.
- Leads / campaigns dated series → `BrushChart` once Lane B ships the series.
- Already migrated: `leads/[leadId]/LeadTimeline.tsx` renders through `Timeline`/`TimelineItem`; `agents/[agentId]/script/ScriptToolbar.tsx` `RoomLeft` renders through `UsageMeter` (inline).

## Structure, overlays and gestures

### Dialogs and sheets — `ModalDialog`, `ConfirmDialog`, `Drawer` (+ `arc/bottom-sheet`)

One dialog family. Below 640px every one of them is a **bottom sheet**: anchored to the bottom edge, rounded top, safe-area padding, and a grab strip (`SheetHandle`) that drags it down to close. From 640px `ModalDialog`/`ConfirmDialog` are a centred card and `Drawer` a right-hand side panel.

- Drag rules (`useSheetDrag`): only from the grab strip (the body scrolls), 1:1 tracking with pointer capture, rubber band upwards, closes on release past 30% of the sheet's height **or** a downward flick faster than 0.5 px/ms. Off for a mouse, above 640px and under reduced motion; Escape, the scrim and the close/cancel button always work.
- `Drawer` with unsaved typing (`dirty` or `useUnsavedGuard` inside) springs back and asks "Close without saving?" instead of closing.
- Focus contract is `lib/focusTrap` (in, cycle, Escape, back to opener). The page behind is NOT made inert, on purpose: a toast raised from inside a sheet must still be announced.
- `ConfirmDialog` — for irreversible actions only. Props: `title`, `confirmLabel` (a verb, never "OK"), `pendingLabel`, `successLabel?`, `status?: FeedbackStatus` (from `useActionFeedback`; supersedes `pending`), `pending?` (legacy), `confirmDisabled?`, `error` (rendered inside), `onCancel`, `onConfirm`, `children` (the consequence). The confirm button is the kit `ActionButton` (danger): pending → tick or "Try again" on the button; Cancel waits while pending. Cancel is first in DOM order; focus lands on the container.
- Do: use `ConfirmDialog` for removing access, deleting, stopping a live feed. Don't: confirm reversible things — offer Undo in the success toast instead.

### `NotificationCenter` (`arc/notification-center`)

The top-bar bell in both shells. A popover listing what needs attention.

Props: `label` (bell's accessible name, includes the count or the failure in words), `title?`, `count?` (the server's total — never `items.length`), `state: "ready" | "loading" | "error"`, `partial?` (some sources failed: warn dot, list still shown), `items: { id, title, detail?, meta?, href?, at? (ISO, shown IST), tone?: "default" | "warn" | "danger" }[]`, `heading`, `seeAll?: { href, label }`, `shortfall?`, `emptyText`, `loadingText`, `errorText`, `onRetry?`, `onDismiss?` (once the server records dismissals; report its result with `useActionFeedback`), `dismissLabel?`, `closeLabel?`.

- Badge: `99+` cap; nothing at 0, while loading, or unknown. Failure = warn dot (`data-testid="attention-unchecked"`), never a "?" or a fake 0.
- Row links and "See all" close the popover (the bar stays mounted across navigation).
- Wired: client `ClientTopHeader` (useAttention, newest 6, tone by kind, "The newest 6 of N." shortfall, retry refetches) and admin `AttentionBell` (held accounts + identity checks as two rows with "n waiting").

### `SwipeActions` (`arc/swipe-actions`)

Phone row gesture (founder 24 Oct): swipe right reveals `primary` (Call back), swipe left reveals `secondary` (Mark status, Call back later, Send WhatsApp follow-up). With a mouse or keyboard the same actions are in the row's ⋯ `RowMenu`.

Props: `label` (row name), `primary?: SwipeAction`, `secondary?: SwipeAction[]`, `children` (the row), `className?`. `SwipeAction = { id, label, icon?, onSelect, tone?: "danger", disabled?, hint?, status?: FeedbackStatus, confirm?: { title, body, confirmLabel, pendingLabel, error? } }`.

- Built on CSS scroll-snap (modern-web-guidance `swipe-to-reveal`), no JS gesture code: the browser owns momentum, vertical-scroll disambiguation and keyboard scrolling. A swipe only REVEALS; nothing commits on swipe (a call must be a deliberate press).
- `confirm` routes through `ConfirmDialog`, which closes itself when that action's `status` becomes `success`.
- Undo is the caller's: `useActionFeedback(m, { successToast, undo })`.
- Disabled actions show their `hint` in the menu (e.g. WhatsApp without consent on record) rather than disappearing.
- Wrap each `<li>` of a phone list; keep the row's own link inside `children`.

### `HoverCard` (`arc/hover-card`)

Desktop-only preview of a row's record on a resting pointer or keyboard focus (500ms open, 150ms close). Props: `trigger` (the row link), `children` (read-only facts), `label`, `openDelay?`, `closeDelay?`, `side?`, `align?`, `className?`. Renders the trigger alone where `(hover: hover) and (pointer: fine)` is false. Never holds an action or the only copy of a fact; does not take focus.

### `AnnouncementBar` (`arc/announcement-bar`)

The site strip (D-771: white, hairline, tone dot, no tinted band). Props: `title` (always shown), `detail?` (from `sm`), `tone?: "info" | "success" | "warn" | "critical"`, `action?: { href, label }`, `onDismiss?` (omit = cannot be closed), `dismissLabel?`, `dismissStatus?: FeedbackStatus` (busy ignores repeat presses), `role?: "status" | "alert" | "region"`, `label?`. Presentational: the caller remembers dismissal. The trial strip (`TrialBanner.TrialStrip`) now renders through it. Lane B's announcements endpoint + admin composer plug in here: shell reads the active announcement for the viewer's audience, renders `AnnouncementBar` above the top bar, `onDismiss` → dismissal mutation through `useActionFeedback`. Feed it through `platformAnnouncementProps(announcement)` (server tone `warning` → `warn`, a link with no label reads "Learn more", `critical` → `role="alert"`): the admin composer at `/admin/announcements` previews with the same function, so the preview is what clients see.

### `ButtonGroup`, `SplitButton` (`arc/button-group`)

- `ButtonGroup` — a record's header actions in priority order; `phoneVisible` (default 1) and `desktopVisible` (default 3) shown as buttons, the rest in a ⋯ `Menu`. Props: `label`, `actions: { id, label, icon?, onSelect?, href?, status?, successLabel?, pendingLabel?, tone?: "danger", disabled?, hint? }[]`, `moreLabel`, `phoneVisible?`, `desktopVisible?`. First action is primary. Each button is an `ActionButton` carrying its own state.
- `SplitButton` — one action and its variants behind a chevron. Props: `children`, `onClick`, `status?`, `pendingLabel?`, `successLabel?`, `disabled?`, `items: MenuItem[]`, `menuLabel`, `variant?: "primary" | "secondary"`.
- Don't use a segmented/joined look for actions; that is for choosing a value (`SegmentedControl`).

### `PageHeader` (console, unchanged contract + `meta`)

Still THE page header (73 callers). New: `meta?: ReactNode` — a quiet row of a record's facts under the description. For more than one primary + one secondary action, pass a `ButtonGroup` as `actions`.

### `FilterToolbar`, `SelectionBar` (`arc/filter-toolbar`)

- `FilterToolbar` is layout, not a filter engine: `search?` (always visible), `filters?` (folded behind "Filters · n" below `sm`), `tools?` (columns, export), `active?: { id, label, onRemove }[]` (each removable), `onClearAll?` (shown for 2+), `count?: { shown, total?, noun, nounPlural? }` → "12 of 1,340 leads" (polite status), label overrides `filtersLabel`, `clearAllLabel`, `activeLabel`, `removeLabel`.
- `SelectionBar` — "3 leads selected", bulk actions (`children`, kit `ActionButton`s), "Clear selection"; sticky to the bottom with safe-area padding; renders nothing at 0.

### `DataTable` (console, unchanged contract + `selection`, `empty`)

Still THE table (28 callers): sortable headers with `aria-sort`, stretched row link, column hiding, live arrivals. New, opt-in:
- `selection?: { selected: ReadonlySet<string>; onChange(next); rowLabel(row); allLabel? }` — a checkbox column with a select-all that shows the mixed state; selected rows tint. Pair with `SelectionBar`.
- `empty?: ReactNode` — shown in place of rows (use `EmptyState`).

## Content

### ScriptEditor — `components/arc/script-editor.tsx` (+ `arc/spoken-text.ts`)
The structured script editor: named section blocks, `{{variable}}` fields, a character budget per section and overall, a "How it will sound" preview. **Its value is plain text only**: every keystroke and paste goes through `toSpokenPlainText` (removes markdown emphasis, headings, quotes, list markers, HTML tags, emoji; keeps line breaks, Indian scripts and `{{key}}` underscores) and a status line says when formatting was removed.

| Prop | Type | Purpose |
|---|---|---|
| sections | `{id, title, hint?, value, maxChars?, placeholder?, rows?}[]` | controlled; one textarea each |
| onChange | `(id, value) => void` | receives sanitised plain text |
| variables | `{key, label, sample?}[]` | insert buttons; `label` shown under the box; `sample` fills the preview |
| totalMaxChars | `number` | whole-script meter |
| previewAction | `ReactNode` | the screen's voice-preview button, in the preview header |
| showPreview | `boolean` (true) | hide when the screen shows its own preview |
| onSave / status / saveBlockedReason | `() => void` / `FeedbackStatus` / `string \| null` | built-in save `ActionButton`; the reason holds it |
| strings | `Partial<ScriptEditorStrings>` | every visible word |

States: within budget, near (≥90%, amber), over (`aria-invalid`, "N characters over"), unknown field (red chip + sentence), formatting removed, empty preview. Counting is code points (Python `len`), same as `scriptModel.chars`. Helpers: `scriptOverBudget(sections, total?)`, `unknownVariables(sections, variables)` — hold the save on either.
Use for any client-authored text the agent works from or speaks. Do not use for free notes (plain `FIELD` textarea). No contenteditable chips: they break Telugu IMEs and Android paste.

### TierComparison — `components/arc/tier-comparison.tsx`
Clear vs Studio. `tiers: {id, name, ratePerMinute: decimal string, summary?, includes[], bestFor, cta?}[]`, `currentId`, `onChoose(id)`, `chooseStatus` + `choosingId` (feedback on the chosen button), `guidance` ("Which is right for me?"), `title`, `strings`. Rates print through `formatRupeeRate`; never pass a number or a constant; never name a provider (D-679). Cards stack on phones, two columns from `md`; current tier has a brand ring and the words "Your agents use this".

### Checklist — `components/console/checklist.tsx` (merged, not a second checklist)
New props (all opt-in, the 25 existing callers unchanged): `emphasizeNext` (first actionable todo row tinted, labelled "Next", link as `PRIMARY_BUTTON_SM`), `foldDone` (done rows fold into an "N done" disclosure), `allDoneLabel`, `countLabel(done,total)`, `nextLabel`, `foldedLabel(n)`. When a row turns done while focus was in the list, focus moves to the next step's action. State still comes only from the server — no manual tick-off (Arc's model was refused for that reason).

### EmptyState — `components/console/emptyState.tsx`
`variant`: `first-use` (default; `illustration` = `EmptySketch`, `action`), `filtered` (`onClear`, `clearLabel`, no drawing), `restricted` (lock, why + who can, never an action), `error` (renders `ProblemNotice` with `error` + `onRetry` — a failed read is never "nothing here").

### ExpandableText — `components/arc/expandable-text.tsx`
Clamp to `lines` (default 4) with Show more/less only when it measurably overflows (ResizeObserver). Full text stays in the DOM; focus inside the hidden part opens it; no height animation. Props: `lines`, `moreLabel`, `lessLabel`, `defaultExpanded`, `textClassName`. Replaces `interior/show-more` (deleted). Not for sections a reader opens by choice — that is `Disclosure`.

### Accordion — `components/arc/accordion.tsx` + `Disclosure` in `ui.tsx`
`Disclosure` (native `<details>`) stays the one mechanism; it gained `name` (exclusive group), `showLabel`, `hideLabel`. `Accordion` = a list of Disclosures with one generated group name: `items: {id, title, subtitle?, content}[]`, `exclusive` (true), `defaultOpenId`, `variant`, `headingLevel`. `@radix-ui/react-accordion` is not used.

### JsonViewer — `components/arc/json-viewer.tsx` (admin)
`value`, `label`, `expandDepth` (2), `pageSize` (50), `moreLabel` ("Show {n} more"). Branches are buttons with `aria-expanded`; type shown by colour and spelling; leaves copy their value, branches copy as JSON. Renders what it is given — redact before (hard rule 6).

### TextShimmer — `components/arc/text-shimmer.tsx`
A standalone working line (`role="status"`) on the `text-shimmer` utility. `announce={false}` inside a control. Inside an `ActionButton`, use its pending face instead.

### ChangelogFeed — `components/arc/changelog-feed.tsx`
`entries: {id, date (ISO), title, body, tags?, href?, hrefLabel?}[]`, `label`, `emptyMessage`, `headingLevel`. Dates are the IST day with a `<time dateTime>`.

### CopyButton — `components/interior/copy-button.tsx` (kept)
Already shows ✓ / ✕ on the button and announces politely; a failure now also raises an error toast with `errorHint` (the manual way round). The one clipboard path (`copyText`).

### Kept, not replaced
- **Alert** → `ui.tsx` `NoticeBox` / `ProblemNotice`: the D-771 notice style and the one failure surface (headline, sentence, remediation, field list, retry, trace id). Arc's alert would be a second.
- **Scroll area** → `ui.tsx` `ScrollRegion` (native scrolling, labelled, keyboard reachable).
- **Slot text** → `console/valueFlash.tsx` `FlashValue`: a changed polled value tints once; rolling digits decorate and were not built.
- **Cookie consent** → no banner: everything stored is functional (see `/legal/cookies` §3, revision 6).


## What the screen lanes still move

The kit is built; these call sites predate it. Each lane moves its own screens and deletes
the old code in the same change.

**Every lane**
- Every screen mutation onto `useActionFeedback` + `ActionButton`: the 352 entries in
  `apps/web/tests/fixtures/feedbackBaseline.ts`, grouped by file. Delete each entry as its
  site moves; the guard fails until you do.
- `ConfirmDialog` callers pass `status={feedback.status}` instead of `pending`.
- Hand-rolled search boxes → `SearchField`; native `type="date"` → `DatePicker`;
  native `type="number"` → `NumberField`; hand-rolled radio lists → `RadioGroup`;
  hand-built rows of `FilterChip`s → `ChipGroup` (sites listed under Inputs above).
- Empty lists with filters or permissions → the `EmptyState` variants; long notes →
  `ExpandableText`; standalone working lines → `TextShimmer`.

**Dashboard and analytics**: `DailyCalls`, `OutcomeSplit`, `SentimentSplit`,
`performance/PerformanceCharts`, `billing/SpendChart`, `billing/WhereItWent`,
`billing/UsageView`, `TrialCallPanel` onto the chart kit (list under Charts above); the
readiness `Gauge` on the dashboard and each agent, `ActivityHeatmap`, `Ridgeline` and the
`BrushChart` timelines once Lane B's endpoints land; `SetupChecklist` turns on
`emphasizeNext` and `foldDone`; `StatsBand` for headline rows.

**Calls, leads and campaigns**: `SwipeActions` on the phone lists (right = Call back, left =
Mark status / Call back later / Send WhatsApp follow-up, the same actions in the row's ⋯
menu) and `HoverCard` previews on desktop; `ButtonGroup` for the call, lead and campaign
header actions; `FilterToolbar` on calls and campaigns (leads keeps `LeadsToolbar` until it
moves), `DataTable` `selection` + `SelectionBar` (leads' `BulkActionBar` merges in);
`DateRangePicker` for the calls From/To.

**Agents, script, billing, settings, onboarding, notifications, admin**: `ScriptEditor` on
the script page (its sections map to `opening_line`, `goal`/`outbound_purpose`, each stage's
`instruction` and `ending`; `VariableBar` and the caret insert in `ScriptBuilder` then go);
`TierComparison` and `PeriodToggle` on billing; `MoneyInput` for the top-up custom amount
and `ConfigInput`'s money kind; `JsonViewer` for the actions tool-test result (the
integrations delivery log stays plain text: its test pins the body byte for byte); `AnnouncementBar` above both shells once Lane B's announcements
endpoint lands, with `onDismiss` through `useActionFeedback`; `NotificationCenter`'s
`onDismiss` when the server records dismissals. Modals built directly on `MODAL_PANEL`
(such as `aiExtraDialog`) move onto `ModalDialog` to get the sheet's grab strip.

## How the kit is verified

- `/admin/ops/kit` renders every component in every state, and is in the axe sweep
  (`tests/a11y.test.tsx`).
- `apps/web/tests/kit/*.test.tsx` cover each family's states, keyboard behaviour and value
  contracts (money as strings, IST dates, plain-text scripts).
- Guards that bind kit code: `feedbackGuard`, `componentConsumers` (every kit module has a
  consumer), `zIndex`, `formatterGuard`, `responsive`, `emojiGuard`, `genericCopyGuard`,
  `lightOnly`, `contrast`.
- In a real browser (headless Chromium against the schema mock, recipe in rememory
  `2908e1f2`): the page at 375, 768 and 1280 px with no horizontal overflow, with reduced
  motion, a live save that succeeds and then fails, a menu opened inside a drawer painted
  above it, Escape closing only the menu and then the drawer, and the confirm dialog's
  pending and success states.
