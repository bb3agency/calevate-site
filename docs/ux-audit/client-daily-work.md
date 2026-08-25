# UX audit — the client's daily-work screens

**Date:** 25 August 2026
**Scope:** `apps/web/src/app/c/**` — `/c`, `/c/[slug]`, `/leads`, `/leads/[leadId]`,
`/calls`, `/calls/[callId]`, `/attention`, `/performance`, `/quality`, `/campaigns`,
`/campaign-review`, `/knowledge`, `/lead-sources`, and the shell `layout.tsx`.
**Method:** read-only source review of every route above plus `components/ui.tsx`,
`components/interior/**` and the enforced floors in `apps/web/tests/{a11y,contrast,responsive}.test.*`.
**Nothing in this audit was edited.** Every finding names a file and line.

## Evidence class of the principles cited

Every principle below is **VENDOR-PUBLISHED** — a named design authority's own page, read
25 Aug 2026, cited at the point of use. No statistic is quoted; where a source states a
qualitative rule, the rule is what is cited. Nothing here is inferred from a figure sitting
in this repo (hard rule 11).

| Tag | Source | URL | Read |
| --- | --- | --- | --- |
| **PD** | NN/g, *Progressive Disclosure* | https://www.nngroup.com/articles/progressive-disclosure/ | 25 Aug 2026 |
| **VH** | NN/g, *Visual Hierarchy in UX: Definition* | https://www.nngroup.com/articles/visual-hierarchy-ux-definition/ | 25 Aug 2026 |
| **CARD** | NN/g, *Cards: UI-Component Definition* | https://www.nngroup.com/articles/cards-component/ | 25 Aug 2026 |
| **DEEP** | NN/g, *Deep Linking is Good Linking* | https://www.nngroup.com/articles/deep-linking-is-good-linking/ | 25 Aug 2026 |
| **PROMISE** | NN/g, *A Link is a Promise* | https://www.nngroup.com/articles/link-promise/ | 25 Aug 2026 |
| **FREE** | NN/g, *User Control and Freedom (Heuristic #3)* | https://www.nngroup.com/articles/user-control-and-freedom/ | 25 Aug 2026 |
| **PAGE** | GOV.UK Design System, *Pagination* | https://design-system.service.gov.uk/components/pagination/ | 25 Aug 2026 |

---

## Top 5 to fix first

Ranked by **user pain × frequency**. Each is a full finding below; this is the queue order.

1. **[L1 / CL2] The two highest-traffic lists have a hard 100-row ceiling and no way past
   it.** `/leads` and `/calls` fetch `limit: 100`, print an honest "Showing 100 of 1,240",
   and then offer no control that reaches row 101 — no pagination, no load-more, no
   infinite scroll. On any account past its first fortnight the majority of the client's
   own data is permanently unreachable through the UI. The API already takes
   `{limit, offset}` (`lib/api/leads.ts:270,301`), and `components/interior/pagination.tsx`
   and `load-more.tsx` are already written and unused. **Blocker.**

2. **[CP1] A campaign has no URL.** `campaigns/page.tsx:667` holds the open campaign in
   `useState`, so a running campaign cannot be bookmarked, deep-linked, sent to a
   colleague, or returned to with Back — Back leaves the console entirely. Every other
   detail surface in this product is a route. **Blocker.**

3. **[L2] `/leads` puts eight stacked bands of chrome between the page top and the first
   lead.** Search, view toggle, column chooser, export, status chips, owner chips, the
   facet rail, saved views, two permanent instruction paragraphs, the restriction note and
   the bulk bar all render before the table. Nothing is primary and the data is below the
   fold on a laptop. **Major.**

4. **[LD1 / LD2 / LD4] The lead detail screen cannot do what a lead detail screen is
   for.** It shows history beautifully but offers no stage change, no note (even though
   `note` timeline events are already styled at `leads/[leadId]/page.tsx:87`), no callback,
   and no way to read past the newest 50 events. A user who opens a lead to work it must
   go back to the table. **Major.**

5. **[CD1] "View the lead this call created" goes to the leads list, not the lead.**
   `calls/[callId]/page.tsx:301-308` renders that link with `detail.lead_id` in hand and
   sends the reader to `/c/{slug}/leads` — an unfiltered 100-row table. A one-token fix on
   the single most-followed link on the call screen. **Major.**

**Severity totals: 3 blocker · 21 major · 15 minor (39 findings).**

---

## Cross-cutting

### C1 — 18 of the 19 built `interior/` primitives are imported by nothing · **major**

- **Where:** `apps/web/src/components/interior/` (19 files, 5,855 lines). The only one with
  a consumer outside its own directory is `toaster.tsx` (7 importers).
- **Verified by:** `grep -rn "components/interior" --include=*.tsx --include=*.ts src | grep -v '^src/components/interior'`
  → 7 hits, all `interior/toaster`.
- **What is wrong:** `pagination.tsx` (281), `load-more.tsx` (349), `show-more.tsx` (253),
  `sticky-header.tsx` (182), `collapsible-banner.tsx` (306), `tabs.tsx` (310),
  `tree-view.tsx` (371), `task-steps.tsx` (232), `wizard-steps.tsx` (424),
  `live-activity.tsx` (474), `new-items-pill.tsx` (224), `skeleton-swap.tsx` (176),
  `progress-bar.tsx` (116), `dropdown.tsx` (429), `floating-label.tsx` (280),
  `loading-button.tsx` (282), `otp-input.tsx` (481), `streaming-text.tsx` (269) are dead.
- **Why it is wrong:** this is the repo's own "one way per problem, and migrate rather than
  accumulate" rule inverted — the solutions exist and the screens hand-roll around them.
  Several findings below (L1, CL2, LD4, A3, L2, CP3, Q1) each have their fix already
  sitting in this directory, which is why this finding leads.
- **Fix:** do not delete them. Adopt them in the order this audit lists:
  `pagination`/`load-more` → L1, CL2, LD4, A3; `collapsible-banner`/`show-more` → L2, Q1,
  CR2; `wizard-steps` → CP3; `tabs` → LS1. Anything still unimported after that queue is
  drained is genuinely dead and can go in one commit with a decision-log entry.

### C2 — 21 nav items in one sidebar, with the triage screen demoted · **major**

- **Where:** `c/[slug]/layout.tsx:73-140`; the skip-link comment at `:490` already counts
  "the sidebar is 21 links".
- **What is wrong:** `Needs attention` sits in the secondary **Operations** group
  (`:91`) next to `Campaign review` — a screen most accounts see once in their lifetime
  (see CR1). Meanwhile the primary group carries `Quality` and `Performance`, both weekly-
  or monthly-cadence reads, at the same weight as `Leads` and `Call logs`.
- **Why it is wrong:** VH — hierarchy is expressed by placement, and top-and-left reads as
  most important; grouping the daily triage queue with a once-ever screen inverts the
  signal. The shell itself contradicts the grouping: it puts an unread-count bell for
  `attention` in the header (`:359-386`), which is a promotion the sidebar never made.
- **Fix:** move `Needs attention` into the primary group, directly under `Dashboard`.
  Move `Quality` and `Campaign review` into a new `Reports & reviews` group. Leave
  `Performance` primary. This is a change to one array; nothing else reads it (`:152` is
  the single consumer for both title and highlight, which is good — see G3).

---

## `/c` — the account junction

### AP1 — it is called a picker and cannot pick · **major**

- **Where:** `c/page.tsx:79-99`.
- **What is wrong:** a user who belongs to two accounts gets `org_required` from the API
  and is shown an error card telling them to "open the link for the one you want". The
  file's own docstring (`:24-27`) names this honestly. But a person who does not have that
  link — which is exactly the person who landed here — is at a dead end after a successful
  sign-in.
- **Why it is wrong:** FREE — the user is in a state they did not choose with no marked
  exit. The reward for authenticating is a refusal.
- **Fix:** this needs a backend endpoint (`GET /v1/me/organizations` returning
  `[{slug, name, role}]`); it is an engineering task, not an external blocker, so per the
  repo's tempo rule it is "the next thing done" rather than a deferral. Front-end shape:
  when the list has one entry, keep today's `window.location.replace`; when it has more,
  render a `Card` per organization with name, role and slug, ordered by most recently
  used. Until the endpoint lands, the error card should at minimum offer the sign-in link
  it already has plus a "contact your account manager" line.

---

## `/c/[slug]` — the dashboard

**This screen is the reference implementation for the rest of the console** and most of it
should be copied, not changed — see the Good list. Two findings.

### D1 — the charts are unreadable to a screen reader and to a keyboard · **major**

- **Where:** `c/[slug]/page.tsx:341` (`title={...}` on the stacked day column);
  `performance/page.tsx:231` (funnel bar) and `:341` (hour column).
- **What is wrong:** the only per-bar detail is a `title` attribute on a non-focusable
  `<div>`. `title` is not announced reliably by assistive technology and never appears on
  keyboard focus. The stacked breakdown on the dashboard chart (completed / no answer /
  failed / still running per day) exists **only** in that tooltip — the visible label under
  each column is the day total alone (`:335`), so the four-way split is available to
  sighted mouse users and nobody else.
- **Why it is wrong:** the chart is non-text content conveying information with no text
  alternative. It also fails the repo's own bar: `tests/a11y.test.tsx` imports and sweeps
  `DashboardPage` and `PerformancePage`, so this passed the floor without the floor
  covering it.
- **Fix:** give each chart a visually-hidden data table as its text alternative — the
  numbers are already in hand (`data.daily_7d`, `data.busiest_hours_ist`). Pattern:
  wrap the chart in `<figure>`, render the existing bars with `aria-hidden`, and follow
  with `<table class="sr-only">` of day × class counts. Keep the `title` for the mouse.
  This is one shared component for all three charts, which also removes the third
  hand-rolled bar renderer.

### D2 — nothing on the home screen links to `Needs attention` · **minor**

- **Where:** `c/[slug]/page.tsx:96-286`. The tiles link to `/leads` (`:119`), `/usage`
  (`:199`) and `/calls` (`:221`).
- **What is wrong:** the queue of things the platform stopped — the one list with a
  time cost attached to ignoring it — is reachable from the home screen only via the
  header bell, which renders no badge at all when the count is zero or unknown
  (`layout.tsx:379-385`, correctly).
- **Why it is wrong:** VH — the dashboard is the daily entry point and should rank the
  day's work; blocked calls outrank average call length.
- **Fix:** add a fifth `StatTile`-shaped panel (or promote `KnowledgeGaps`' neighbour slot)
  reading "Needs your attention · N" from the `useAttention` query the shell already runs,
  linking to `/attention`. Render nothing rather than a zero when the query has not
  answered, exactly as the bell does.

---

## `/c/[slug]/leads`

### L1 — no pagination; row 101 is unreachable · **blocker**

- **Where:** `leads/page.tsx:151` (`PAGE_SIZE = 100`), `:216` (`{ limit: PAGE_SIZE }`),
  `:1036-1054` (the footer that prints "Showing 100 of 1,240" and then stops).
- **What is wrong:** there is no offset control anywhere on the screen. The footer is
  *honest* about the gap — which is why this is a UX finding and not a data-integrity one
  — but honesty about an unreachable 92% of the client's CRM is not a resolution.
  `lensQuery`/`lensKey` already accept `{limit, offset}` (`lib/api/leads.ts:270,301,340,348`),
  so the server side is done.
- **Why it is wrong:** PAGE — a list of items a user must navigate through is exactly the
  case the pattern exists for. The board view compounds it: a stage column silently shows
  "+412 more not on this page" (`:1010-1016`) with no route to those 412.
- **Fix:** add `const [offset, setOffset] = useState(0)`, pass it into the lens, reset it
  in the same `useEffect` that clears the selection on a lens change (`:295-298` — the
  offset is part of the lens contract for the same reason the selection is). Render
  `components/interior/pagination.tsx` under the footer bar. Two constraints inherited from
  this screen's own doctrine: the page-scoped select-all checkbox (`:879-890`) must clear
  on a page change, and the bulk bar's `pageSize={items.length}` sentence (`:808`) must
  keep meaning "this page".

### L2 — eight bands of chrome before the first row; nothing is primary · **major**

- **Where:** `leads/page.tsx:544-833`, in DOM order: header + count (`:544`), search /
  view toggle / column chooser / export (`:560`), status chips (`:664`), owner chips
  (`:684`), `FacetPanel` (`:711`), `SavedViewBar` (`:722`), the CSV sentence (`:752`), the
  dispatch-agent sentence (`:764`), `RestrictionNote` (`:797`), `BulkActionBar` (`:802`),
  then four `ProblemNotice` slots (`:835-847`) — and only then the table (`:852`).
- **What is wrong:** the primary task on this screen is *scan and work leads*. Every band
  above is configuration of that scan, and each is given the same visual weight as the
  others and more vertical priority than the data.
- **Why it is wrong:** PD — advanced and rarely-used controls belong on request, with a
  visible way to unhide them; VH — a stack of equally-weighted rows gives the eye no order.
  Facets and saved views are power features (correctly built, see Good) used a fraction as
  often as the status chips beside them.
- **Fix, without removing any capability:**
  1. Keep on first paint: the count, the search box, the status chips, and the table.
  2. Collapse `FacetPanel` + `SavedViewBar` + `ColumnChooser` behind one **Filters** toggle
     that carries a count of active refinements ("Filters · 3"), using
     `components/interior/collapsible-banner.tsx`. Auto-expand when a saved view is applied
     or any facet is set, so a returning user never loses sight of an active filter.
  3. Demote the two permanent paragraphs — see L3.
  4. Leave `BulkActionBar` and the notices exactly where they are: both are conditional and
     both are correctly anchored to the set they concern.

### L3 — two permanent instruction paragraphs sit above the data · **minor**

- **Where:** `leads/page.tsx:752-758` (what the CSV contains) and `:764-792` (which agent
  dials, and that every call still passes the gate).
- **What is wrong:** both are always-on prose that the daily user reads once and then
  scrolls past forever. The CSV sentence in particular describes a button that is 200px
  above it and already carries the same information in its `title` (`:645-653`).
- **Why it is wrong:** PD — the sentences are *good copy for the moment of use*, and the
  moment of use is the click, not the page load.
- **Fix:** move the CSV sentence into the export confirmation — the toast at `:637-643`
  already fires on success and can carry the row count instead. Move the dispatch sentence
  into a `<details>` or into the per-row `CallControl`'s disabled/hover copy. Keep both
  strings byte-identical; this is a placement change only.

### L4 — board view silently loses bulk actions and selection · **major**

- **Where:** the row checkbox renders only inside the list branch
  (`leads/page.tsx:904-915`); the board branch (`:943-1029`) renders no checkbox. The
  `BulkActionBar` (`:802`) renders above both and is driven by `selection`, which nothing
  in board view can populate.
- **What is wrong:** switching the view toggle from List to Board removes bulk reassign,
  bulk stage change and select-all-matching, with nothing said. The reverse switch does not
  restore a selection either, because `currentLens` does not change and the selection was
  never made.
- **Why it is wrong:** the two views are presented as equivalent lenses on one dataset
  (`:110-111`, `:574-575` both say so), so a capability that exists in one and not the
  other is a trap rather than a design. This is the same class as the screen's own
  well-reasoned decision to put `ownerCell` and `callCell` on the board cards precisely
  because "a feature reachable only from the other tab is a feature half the users never
  find" (`:990-993`) — the rule was applied to two controls and not the third.
- **Fix:** add the checkbox to the board card, top-right of the card header, gated on the
  same `maySelect`. `toggleRow` needs no change; `pageIds` is already view-independent.
  Alternatively — and cheaper — disable the view toggle's Board option while a selection is
  live and say why; but the card checkbox is the answer the screen's own comment argues for.

---

## `/c/[slug]/leads/[leadId]`

### LD1 — no way to change a lead's stage from its own page · **major**

- **Where:** `leads/[leadId]/page.tsx:155-169` — the only control on the header card is
  `AssigneeSelect` (owner). `StatusBadge` at `:142` is display-only.
- **What is wrong:** the table and the board both carry a `StatusSelect`
  (`leads/page.tsx:479-488`, `:983-989`); the detail page does not. Someone who opens a
  lead, reads its history, rings the customer and wants to mark them `won` must navigate
  back to the table and find the row.
- **Why it is wrong:** the detail page is where the decision is made and the decision has
  no control. FREE — the user must retrace their steps to complete the task the page led
  them to.
- **Fix:** the mutation is already imported (`useEditLead`, `:113`) and already handles
  `status` (`leads.ts` row-edit shape). Render the same `StatusSelect` beside the badge,
  gated on the same `mayAssign`/`leads:write` (`:115`). Lift `StatusSelect` out of
  `leads/page.tsx:1119` into a shared module so both screens use one control — otherwise
  this becomes the third spelling of the status list.

### LD2 — notes are rendered but cannot be written · **major**

- **Where:** `leads/[leadId]/page.tsx:86-89` styles a `note` event type with a `StickyNote`
  icon and an amber medallion. Nothing on this screen — or anywhere in `/c/**` — creates one.
- **What is wrong:** the single most frequent action on a CRM lead record ("rang them, they
  want a callback Tuesday") has no input. The timeline is a read-only projection of what
  six backend producers wrote; the human working the lead cannot add to it.
- **Why it is wrong:** the screen presents a complete-looking history that structurally
  cannot include the user's own knowledge, which is how a CRM stops being used. The styling
  for a note already existing is evidence the intent was there and the seam was left
  half-wired.
- **Fix:** needs one endpoint (`POST /v1/leads/{id}/notes` writing a `lead_events` row with
  `type: "note"`, `actor_kind: "member"`). Front end: a two-row textarea + Save above the
  `<ol>` at `:218`, gated on `leads:write` via the existing `useWriteAccess`, optimistically
  appended and reconciled on the timeline query. This is an engineering task, not an
  external blocker.

### LD3 — no callback control · **minor**

- **Where:** `leads/[leadId]/page.tsx` — no `useCallLead`.
- **What is wrong:** "Call with AI" exists on the leads table (`leads/page.tsx:1072`) and
  "Call back with AI" on the call detail (`calls/[callId]/page.tsx:261-269`), but not on the
  lead's own page.
- **Fix:** reuse `CallControl` from `leads/page.tsx:1072` (lift it alongside `StatusSelect`
  per LD1). Same `leads:dispatch` gate, same per-lead result slot, same amber treatment for
  a 200-with-`blocked`.

### LD4 — the history stops at 50 with no way to read further · **major**

- **Where:** `leads/[leadId]/page.tsx:98` (`TIMELINE_LIMIT = 50`), `:199-201` which prints
  "The 50 most recent of 312".
- **What is wrong:** same shape as L1 — an honest sentence about an unreachable remainder.
  For a repeat caller with a long campaign history, the origin of the relationship is the
  part that is cut off.
- **Why it is wrong:** PAGE. For a reverse-chronological feed the load-more form is the
  right one rather than numbered pages.
- **Fix:** `useLeadTimeline` already takes `limit` (`lib/api/leads.ts:82-87`). Render
  `components/interior/load-more.tsx` under the `<ol>`, raising the limit in steps of 50 up
  to the API's cap of 100 and then paging by offset.

---

## `/c/[slug]/calls`

### CL1 — the count describes our query and reads as a fact about the business · **major**

- **Where:** `calls/page.tsx:104` — `formatCount(calls.data.length)` rendered as
  "**100** calls".
- **What is wrong:** `calls.data.length` is the size of the page we asked for
  (`:89`, `limit: 100`), not the number of calls the account has. Any account past 100
  calls reads "100 calls" forever, and "100 matching 'no answer'" when a filter is on.
- **Why it is wrong:** this is precisely the defect the leads screen's own docstring names
  as the thing it fixed — "a statement about our query read as a statement about their
  business" (`leads/page.tsx:69-71`) — reintroduced one route over. It is also the class
  `tests/surfaceStatesGuard.test.ts` exists for.
- **Fix:** the honest short-term rendering is "Showing the 100 most recent" (the exact
  shape `attention/page.tsx:255-259` uses and justifies). The correct fix is to have
  `/v1/calls` return a `{items, total}` envelope like `/v1/leads` and `/v1/attention`
  already do, and print the server's total. Do not compute a total client-side.

### CL2 — no pagination · **blocker**

- **Where:** `calls/page.tsx:89`.
- **What is wrong / why / fix:** identical to L1. The call log is the screen a receptionist
  opens to find *yesterday's* call; with a busy day's volume, yesterday is off the end of
  the list and there is no control that reaches it. `useCalls` currently accepts only
  `{status, limit}` (`lib/api/hooks.ts:150-155`) so this needs an `offset` on both sides.
  Use `load-more` for a reverse-chronological log rather than numbered pages.

### CL3 — no date, agent or direction filter · **major**

- **Where:** `calls/page.tsx:111-121` — the filter row offers status only.
- **What is wrong:** the three questions actually asked of a call log are "what happened
  today", "what did *this* agent do", and "show me only the outbound campaign calls". None
  is expressible. `CallSummary` already carries `agent_name`, `direction` and `started_at`
  and the row prints all three (`:174-200`), so the user can *see* the axes they cannot
  filter on.
- **Why it is wrong:** task-oriented IA — the screen is organised around the one field the
  API happened to accept as a query parameter rather than around what the reader is trying
  to do.
- **Fix:** add `agent_id` and `direction` to the `/v1/calls` query and render them as a
  second and third `role="group"` chip row (the pattern `leads/page.tsx:664`/`:684` already
  establishes — separate groups with separate `aria-label`s, not one group of mixed axes).
  Add a date range as a `Today / 7 days / 30 days / All` chip group; this is a far cheaper
  first cut than a date picker and covers the frequent cases. Every one of these must be a
  **server-side** filter for L1/CL2's reason — a client-side filter over a capped page is
  the defect class this repo has fixed four times.

### CL4 — no search · **minor**

- **Where:** `calls/page.tsx` has no search input; `/leads` has one (`:563-571`).
- **What is wrong:** finding a specific caller's call means scrolling. The leads table can
  search by "name or last digits"; the call log cannot.
- **Fix:** the same debounced POST-body search the leads lens uses (`:178-182` — note the
  300ms debounce and the deliberate "a number never goes into a URL" rule at `:99-101`,
  which must be preserved here). Lower priority than CL2/CL3 because reaching the call via
  the lead's timeline (`leads/[leadId]/page.tsx:287-293`) is an existing route to it.

---

## `/c/[slug]/calls/[callId]`

### CD1 — "View the lead this call created" opens the leads list · **major**

- **Where:** `calls/[callId]/page.tsx:301-308`:

  ```tsx
  {detail.lead_id && (
    <Link
      href={href(`/c/${slug}/leads`)}
      className="mt-3 inline-block text-sm font-medium text-brand-strong hover:underline"
    >
      View the lead this call created
    </Link>
  )}
  ```

- **What is wrong:** the link is gated on `detail.lead_id` being present and then does not
  use it. The reader lands on an unfiltered, uncapped-at-100 table and has to find the lead
  by hand. `/c/[slug]/leads/[leadId]` exists and is linked correctly from three other places
  (`leads/page.tsx:469`, `:972`, `leads/[leadId]` itself).
- **Why it is wrong:** PROMISE — a link's text is a promise about its destination, and this
  one names a specific record and delivers a list. It is also the most-followed link on the
  screen: reading a call and then working the lead is the core loop of the product.
- **Fix:** `href(`/c/${slug}/leads/${detail.lead_id}`)`. One token. Add a
  `tests/callDetail.test.tsx` assertion on the resolved href so it cannot regress.

### CD2 — no previous/next call navigation · **minor**

- **Where:** `calls/[callId]/page.tsx:159-165` — the only navigation is "back to Call logs".
- **What is wrong:** reviewing a morning's calls means detail → back → scroll → next → detail,
  losing scroll position each time (the list has no scroll restoration and, per CL2, no
  offset to restore).
- **Fix:** lower priority than CL2/CL3 and dependent on them — a prev/next pair needs a
  defined ordering, which is the filtered list's ordering. Once `/v1/calls` returns an
  envelope, pass the neighbouring ids through the query cache and render `‹ Previous call /
  Next call ›` beside the back link. Do not build this before CL2.

---

## `/c/[slug]/attention`

This is the highest-value screen in the console for a busy owner and the most under-built.

### A1 — the summary chips look like filters and are not · **major**

- **Where:** `attention/page.tsx:141-161` — `<span>`s with `rounded-full px-2.5 py-1`, a
  lucide icon and a count, in a `role="group" aria-label="Queue summary"`.
- **What is wrong:** they are visually indistinguishable from `FilterChip`
  (`components/ui.tsx:637`) as used on `/leads` (`:669`), `/calls` (`:112`),
  `/performance` (`:93`) and `/quality` (`:118`) — a rounded pill with a label, sometimes a
  count, in a labelled group. On four screens that shape filters the list; here it does
  nothing. A user will click it.
- **Why it is wrong:** one visual pattern with two behaviours is the inconsistency class
  the audit brief names; PROMISE applies to controls as well as links.
- **Fix:** make them real filters. `data.items` carries `kind`, `counts` carries the
  totals, and the whole payload is already client-side — but per CL3's reasoning the filter
  must be server-side once A3's paging lands, so add `kind` to `/v1/attention` now and wire
  the chips to it. If filtering is genuinely not wanted, restyle them as a plain
  `dl`/definition row so they stop imitating a control.

### A2 — the queue is read-only; nothing can be cleared · **major**

- **Where:** `attention/page.tsx:228-236` — the only per-row action is an `Open` link.
- **What is wrong:** every item is derived from a backend condition, so an item leaves the
  queue only when the underlying condition resolves. A `kb_rejected` item the owner has read
  and accepted, or a `delivery_failed` from a form vendor that has since been fixed, sits in
  the list and in the header bell's badge indefinitely. A counter that never returns to zero
  is a counter users learn to ignore — which the shell's own comment already argues about the
  hardcoded "3" it replaced (`layout.tsx:333-337`).
- **Why it is wrong:** FREE — there is no exit from a state the user has finished with.
- **Fix:** an acknowledge action (`POST /v1/attention/{kind}/{id}/ack` writing a dismissal
  row scoped to tenant + kind + id + occurred_at), with the row moving to a collapsed
  "Acknowledged" section rather than vanishing — a compliance-adjacent queue must not
  support silent deletion. Exclude acknowledged items from `counts`/`total` so the bell
  reaches zero. Gate on `leads:read` like the rest of the screen (`:113`).

### A3 — the oldest 28 of 78 items are unreachable · **major**

- **Where:** `attention/page.tsx:255-259`, the (excellent, correct) sentence "Showing the
  50 most recent of 78. Older items are not listed."
- **What is wrong:** third instance of the L1 shape. Here it is sharpest, because the API
  sorts newest-first before slicing — so the items that fall off are the ones that have been
  waiting longest, which on a queue of things the platform *stopped* is precisely the wrong
  end to drop.
- **Fix:** `load-more` against a `limit`/`offset` on `/v1/attention`. Keep the sentence; it
  becomes a description of the current page rather than of a ceiling.

---

## `/c/[slug]/performance`

Well-built; the chart doctrine (relative heights, every bar labelled, zero-fill preserved,
`data.days` rather than the requested period) is a model — see Good. Three findings.

### P1 — one tile's hint omits the window the tile is measured over · **minor**

- **Where:** `performance/page.tsx:144-149`:

  ```tsx
  <StatTile
    label="Average call length"
    value={formatDuration(data.avg_duration_s)}
    icon={<Clock className="h-5 w-5" />}
    hint="Completed calls only"
  />
  ```

- **What is wrong:** on a screen whose whole point is a switchable 7/30/90-day period, this
  tile's hint does not say which. It reads identically at all three settings.
- **Why it is wrong:** the dashboard fixed this exact tile for this exact reason and
  documented it at `c/[slug]/page.tsx:103-107` — "THE WINDOW IS PART OF THE NUMBER". Here
  the window is not merely unstated but *variable*, so the omission is worse.
- **Fix:** ``hint={`Completed calls, last ${data.days} days`}`` — `data.days` (the server's
  measured period, not the requested one) is already the value used for the sentence at
  `:88`, so this stays correct across an in-flight switch. The three neighbouring tiles'
  hints (`:130`, `:141`, `:154`) should be checked the same way; "Calls received vs calls
  made" has the same silence.

### P2 — no export and no period-over-period comparison · **minor**

- **Where:** `performance/page.tsx` — no export control anywhere.
- **What is wrong:** the two things an owner does with a performance report are send it to
  someone and compare it to last month. Neither is possible. `/leads` has a fully-audited
  CSV export (`leads/page.tsx:632-658`) that establishes the pattern including the
  permission gate.
- **Fix:** lower priority than the daily-work findings above. A "vs previous period"
  delta needs one API change (return the prior window's figures alongside); a CSV needs the
  same audited-fetch shape as `useExportLeads`. Note that this screen carries no raw PII, so
  it does not need `calls:read_raw` — `calls:read` is the correct gate.

### P3 — chart accessibility · (covered by D1) · **major**

Same finding as D1; the funnel (`:231`) and hour histogram (`:341`) carry their detail in
`title` only. Fix once, in the shared chart component D1 proposes.

---

## `/c/[slug]/quality`

### Q1 — six equally-weighted cards, four of them static prose · **major**

- **Where:** `quality/page.tsx:144-306` — `NoticeBox` verdict (`:147`), three `StatTile`s
  (`:185`), two loose paragraphs (`:199`, `:204`), then `Card` "What we tested" (`:208`),
  `Card` "Deliberate attacks" (`:240`), `Card` "Known limits" (`:249`), `Card` "What this
  report does not tell you" (`:287`).
- **What is wrong:** the answer the reader came for is "how many defects" and it is in the
  first box — correctly (`:186-188` argues this well). Everything after it is flat: a table
  they may want, a paragraph of fixed marketing-adjacent copy they will read once, a table
  that is usually empty, and a three-bullet disclaimer. All four are the same card at the
  same weight in the same column.
- **Why it is wrong:** CARD — card layouts de-emphasise ranking, and the usability cost
  lands when everything gets equal emphasis; VH — after the headline there is no second
  level. PD — "Deliberate attacks" and "What this report does not tell you" are exactly the
  "read once, then never" content that belongs behind a disclosure.
- **Fix:** keep the verdict box, the three tiles, and "Known limits" (the only card whose
  content changes month to month and the only one an owner acts on) at full weight. Put
  "What we tested", "Deliberate attacks" and "What this report does not tell you" into
  `components/interior/collapsible-banner.tsx`, collapsed, with their headings as the
  triggers. Do not cut a word of the copy — it is good and it is doing legal-adjacent work;
  PD requires only that it be *available*, and a heading is a visible way to unhide.

### Q2 — the month picker grows without bound · **minor**

- **Where:** `quality/page.tsx:111-126` — one `FilterChip` per report, all of them, forever.
- **What is wrong:** at two years this is 24 chips wrapping over four lines above the report.
- **Fix:** show the newest six as chips and put the rest behind a `<select>` labelled
  "Earlier months", or switch the whole control to a `<select>` once `all.length > 12`.
  Keep the `as_of`-string selection key (`:62`) — the reasoning there is right.

---

## `/c/[slug]/campaigns`

2,152 lines — the largest route in the repo by 470 lines. Five findings; CP1 is the blocker.

### CP1 — a campaign has no URL · **blocker**

- **Where:** `campaigns/page.tsx:667` — `const [campaignId, setCampaignId] = useState<string | null>(null)`.
  Every campaign-scoped hook keys off it (`:710-717`), the list rows open it with a
  `<button onClick={() => setCampaignId(campaign.id)}>` (`:964-970`, `:998-1004`), and the
  back control clears it (`:847`).
- **What is wrong:** a running campaign — the thing an owner checks several times a day
  while it dials — cannot be bookmarked, linked in a message, opened in a second tab, or
  returned to with the browser Back button. Back from a campaign detail navigates *out of
  the campaigns screen entirely*, because as far as the browser is concerned nothing
  happened. Refresh drops the user back to the list.
- **Why it is wrong:** DEEP — interior states should be linkable because links relate to
  users' goals; FREE — Back is the emergency exit users expect and here it overshoots. It
  also breaks the console's own contract: `/leads/[leadId]`, `/calls/[callId]` and
  `/agents/[agentId]` are all routes, so this is the second way of doing one thing. And it
  degrades `/attention`: a `campaign_stalled` item's `href` (`attention/page.tsx:228-236`)
  can only land the reader on the list, not on the stalled campaign.
- **Fix:** promote to `campaigns/[campaignId]/page.tsx`. The split is mechanical because the
  file already branches cleanly on `!campaignId` at `:917`, `:929`, `:941`, `:1014`:
  everything in the falsy arm is the list route, everything in the truthy arm is the detail
  route. `setCampaignId(x)` becomes a `<Link href={href(...)}>`; `setCampaignId(null)`
  (`:847`) becomes the back link the other detail screens already use
  (`calls/[callId]/page.tsx:159-165`). Preserve the audited-answer clearing that `:831-847`
  performs on exit — move it to a `useEffect` cleanup or refetch on mount. Add the nav
  highlight: `lib/nav.ts::currentNavItem` matches by longest prefix, so `/campaigns/{id}`
  will light "Campaigns" with no change.

### CP2 — one route holds a list, a create form and a full detail screen · **major**

- **Where:** `campaigns/page.tsx`, 2,152 lines; 19 form controls; 20+ `useState` calls
  (`:667-733`).
- **What is wrong:** unreadable and unreviewable, and it is the reason CP3/CP4 have not been
  addressed — nobody can change one part of this screen with confidence.
- **Why it is wrong:** it is the structural cause of CP1 rather than a separate aesthetic
  complaint; the two fixes are the same commit.
- **Fix:** falls out of CP1. After the route split, extract `ContactListCard`,
  `RepeatCard`, `ScheduleCard`, `LaunchCard` and `LaunchedCard` as siblings of the existing
  `LaunchConfirm.tsx` (229 lines, already extracted and a good model). Target: no file over
  400 lines, matching the rest of `/c/**`.

### CP3 — the create form presents every field at once, permanently · **major**

- **Where:** `campaigns/page.tsx:1015-1316` — a `Card title="New campaign"` rendered
  unconditionally below the list whenever no campaign is open. Fields: name (`:1041`),
  agent (`:1057`), classification radios (`:1088`), calling-from number (`:1128`), DLT
  template (`:1160`), concurrency (`:1199`), restrict-hours checkbox + two time inputs
  (`:1223`), consent source + consent date (`ConsentProvenanceFields`, `:1983`).
- **What is wrong:** nine to eleven inputs, spanning naming, telecom compliance, consent
  provenance and dialer tuning, all visible at once — and shown to every visitor to the
  screen, including the returning user whose only intent is to check a campaign that is
  already running. The most frequent task (open a running campaign) is a plain text button
  in a list *above* this wall.
- **Why it is wrong:** PD — this is the canonical case, a large set of specialised options
  that should be offered on request; VH — the create form outweighs the list by an order of
  magnitude in screen area while being the rarer task.
- **Fix, keeping every field:**
  1. Replace the always-open form with a primary **New campaign** button in the list card's
     `action` slot. This alone fixes the hierarchy.
  2. Behind it, run the existing fields through `components/interior/wizard-steps.tsx`
     (424 lines, already built, currently unused) in three steps that match how the
     compliance gate actually reads a campaign: **What and who** (name, agent) → **How it
     dials** (classification, number, DLT template, calling hours, concurrency) → **Where
     the list came from** (consent source + date). This is also the order
     `campaign-review/page.tsx:289-292` tells the client we read them in, so the form would
     finally match the explanation.
  3. Default concurrency out of step 2's visible surface into an "Advanced" disclosure —
     see CP6.

### CP4 — the contact list is a raw CSV textarea · **major**

- **Where:** `campaigns/page.tsx:1362-1413` — a `<textarea>` with placeholder
  `phone,name\n9876543210,Priya`.
- **What is wrong:** the actual user has a `.csv` or `.xlsx` exported from Tally, a WhatsApp
  Business export, or a spreadsheet. Asking an SMB owner to open the file in a text editor
  and paste its contents is a task-shaped mismatch, and paste has practical limits on a
  phone.
- **Why it is wrong:** task-oriented IA — the screen is built around the wire format the
  API accepts rather than around the artefact the user has in hand. Note that the *result*
  reporting here is excellent (`:1397-1411`, added/duplicate/malformed each named) and
  should be kept exactly as is.
- **Fix:** add a file input + drop zone that reads the file client-side with the File API
  and populates the same `csv` state — no API change at all, since `parsed` already does
  the parsing. Keep the textarea visible as the "or paste" alternative; both feed one
  `addContacts.mutate(parsed)`. Accept `.csv` and `.txt`; do not attempt `.xlsx` in this
  pass, and say so in the accept hint rather than failing silently on one.

### CP5 — list rows are buttons, so no middle-click, no new tab, no copy link · **minor**

- **Where:** `campaigns/page.tsx:964-970` and `:998-1004`.
- **Fix:** resolved for free by CP1 — they become `<Link>`s. Listed separately because if
  CP1 is deferred, this is still worth fixing on its own with a `role`/`href` shim.

### CP6 — dialer concurrency is a top-level field on the create form · **minor**

- **Where:** `campaigns/page.tsx:672` (`useState(3)`), rendered at `:1199` under the label
  "Calls at the same time".
- **What is wrong:** an infrastructure tuning parameter given the same visual weight, and a
  more prominent position, than the DLT template — which is a legal precondition for the
  campaign existing. Most clients have no basis for changing it from 3.
- **Why it is wrong:** VH/PD — equal weight for unequal importance, and a rarely-changed
  expert control on the default path.
- **Fix:** move into an "Advanced" `<details>` at the foot of CP3's step 2, defaulted and
  labelled with what raising it costs. Keep it reachable — power must stay available.

---

## `/c/[slug]/campaign-review`

### CR1 — a permanent nav entry for a once-per-account screen · **minor**

- **Where:** `layout.tsx:92` puts it in the **Operations** group beside `Needs attention`;
  `campaign-review/page.tsx:124-131` handles the `never_applied` state, which is every
  account onboarded by a human — i.e. most of them today.
- **What is wrong:** for a released or never-applied account the entire screen resolves to
  "this does not apply to you", and it holds a permanent slot in the primary operations
  group, adjacent to the daily triage queue.
- **Why it is wrong:** VH/IA — nav position should track frequency of use.
- **Fix:** part of C2's regrouping — move it to `Reports & reviews`. Better: render the nav
  entry conditionally on the `useFirstCampaignHold` state the shell can already reach,
  hiding it for `never_applied` and `released`. If it is hidden, the campaigns screen's own
  blocker copy must still link to it directly so a newly-held account can reach it.

### CR2 — four stacked prose cards after the verdict · **minor**

- **Where:** `campaign-review/page.tsx:178-183` — `WhatIsHeld`, `WhileYouWait` /
  `AfterARefusal`, `WhoDecides`, all `Card`s of bullet lists, all equal weight.
- **What is wrong:** same shape as Q1. The verdict box (`:172`) is correctly the headline;
  everything after it is undifferentiated.
- **Why it is wrong:** CARD/VH.
- **Fix:** keep `WhatIsHeld` open — it answers the misconception the file itself identifies
  as the one that loses the client (`:40-43`). Collapse `WhoDecides` behind its own heading.
  Leave `WhileYouWait`/`AfterARefusal` open; they are the next action. Do not cut copy.

---

## `/c/[slug]/knowledge`

### K1 — knowledge can be added but never edited or retired · **major**

- **Where:** `knowledge/page.tsx:283-352` — a source row offers exactly one control,
  `Preview`/`Hide` (`:302-314`).
- **What is wrong:** a client whose prices changed can submit a new version (the form says
  so, `:239-242`), but a client whose *service no longer exists* has no way to take the live
  answer down. The agent keeps saying it to callers. `SourceBadge` can render an `archived`
  state (`:93-97`), so the state exists and only the transition is missing from the UI.
- **Why it is wrong:** the screen's stated job is "what your agent knows"; a knowledge base
  that only accumulates is one where correctness decays, and the failure is audible to the
  client's customers. FREE — no exit from a state the user created.
- **Fix:** needs one endpoint (`POST /v1/kb/sources/{id}/retire`, going through the same
  approval queue as a submission — a retirement is a change to what the agent says under
  the client's PE registration and must not bypass review). Front end: a `Retire` secondary
  button on rows where `is_active`, with a confirmation naming what callers will stop
  hearing, gated on the same `kb:write` (`:113`). Also add "Edit" as a prefill of the form
  with the source's name and body, which needs no new endpoint at all — it is a submission
  with an existing name, which `:239-242` already documents as the versioning path.

### K2 — the submitted list has no filter, no search, and no stated cap · **minor**

- **Where:** `knowledge/page.tsx:274-361`.
- **What is wrong:** every source for every agent in one undivided list. A client with two
  agents and thirty topics scrolls. The agent name is present but only as trailing muted
  text (`:295`), so it cannot be scanned. And unlike `/attention` and `/leads/[leadId]`,
  there is no sentence about whether the list is complete.
- **Fix:** a `FilterChip` group for agent (when `agentOptions.length > 1`) and one for state
  (Live / In review / Not accepted), reusing the shared chip. If `list_sources` caps, say so
  in the footer using `attention/page.tsx:255-259`'s wording.

### K3 — the input form holds the prime slot over the more frequent read · **minor**

- **Where:** `knowledge/page.tsx:160-364` — `lg:col-span-5` form on the left, `lg:col-span-7`
  list on the right; on mobile the form is entirely above the list.
- **What is wrong:** submitting knowledge is a set-up-then-occasional task; checking whether
  a submission went live is the recurring one. On a phone the recurring task is below a
  form with an eight-row textarea.
- **Why it is wrong:** VH — top-and-left is read as most important.
- **Fix:** swap the columns (list left/wide, form right/narrow) and on mobile put the list
  first with the form behind an "Add knowledge" disclosure. Keep the form fully expanded on
  desktop — it is only three fields and PD's cost/benefit does not favour hiding it there.

---

## `/c/[slug]/lead-sources`

### LS1 — four unranked cards; the daily question is third · **major**

- **Where:** `lead-sources/page.tsx:246` (`Try a sample lead`), `:349` (`Meta Lead Ads`),
  `:408` (`Recent deliveries`), `:648` (`Your lead sources`).
- **What is wrong:** the recurring question on this screen is "are my leads arriving?" —
  answered by **Recent deliveries**, which is third. The two setup cards, used once during
  integration and then never, are first and second. `Your lead sources` — the inventory the
  other three refer to — is last.
- **Why it is wrong:** VH/CARD — four equal cards in DOM order with no ranking, ordered by
  when they were built rather than by how often they are needed.
- **Fix:** reorder to `Your lead sources` → `Recent deliveries` → then put `Try a sample
  lead` and `Meta Lead Ads` into `components/interior/tabs.tsx` under one "Set up a source"
  panel, collapsed by default once at least one source exists and has a delivery, expanded
  when the account has none (an empty account's primary task genuinely *is* setup — the
  hierarchy should follow the state).

### LS2 — 1,334 lines in one route · **minor**

- **Where:** `lead-sources/page.tsx`.
- **Fix:** extract the four cards named in LS1 into siblings. Mechanical, and LS1's reorder
  is much safer once done.

---

## What is genuinely good — preserve this, and copy it to other lanes

These are not consolation items. Several are better than industry-default and should be
propagated deliberately.

1. **The "§52" three-state discipline, everywhere.** Loading is a skeleton, failure is a
   refusal with a retry, and an empty state renders *only* where the server said zero —
   including the `!data` arm for a TanStack query that is `paused` (offline) and therefore
   has `isLoading === false` and `error === null`. See `c/[slug]/page.tsx:81-88` and its
   comment, `calls/page.tsx:130-145`, `quality/page.tsx:80-101`, `campaigns/page.tsx:929-939`,
   `attention/page.tsx:166-178`. **This is the single strongest property of the codebase.**
   Any new screen in any lane must inherit it; `tests/surfaceStatesGuard.test.ts` is the gate.

2. **No number is rendered that the server did not send.** The dashboard docstring
   (`c/[slug]/page.tsx:34-49`) records a design mock's invented figures being refused
   outright, and the leads stage tally reads `status_counts_matching_search` rather than
   counting the loaded page (`leads/page.tsx:320`). CL1 is the one place this slipped.

3. **Refusals are pre-empted, never discovered on click.** `useWriteAccess` folds
   permission + D-22 impersonation + the failed-`/v1/me` case into one `{allowed, reason}`,
   and controls render disabled *with the sentence* rather than 403-ing
   (`leads/page.tsx:235-266`, `knowledge/page.tsx:113`, `calls/[callId]/page.tsx:271-292`).
   The distinction it keeps — "you cannot" vs "we could not find out" — is better than most
   commercial SaaS manages.

4. **One nav list feeds both the sidebar highlight and the page title**
   (`layout.tsx:152-157`, `lib/nav.ts::currentNavItem`), and no screen renders its own
   `<h1>`. Four separate route files document *why* (`calls/page.tsx:29-32`,
   `leads/page.tsx:94-96`, `quality/page.tsx:49-51`, `attention/page.tsx:75`). Keep this.

5. **Touch targets and the iOS-zoom floor are handled at the token level.** `touch:min-h-11`
   scoped to `@media (pointer: coarse)` so desktop density is not sacrificed
   (`leads/page.tsx:118-142` — read that comment before touching any dense control), and
   the 16px input rule in `globals.css` pinned by `tests/responsive.test.ts:64-80`.

6. **The skip link exists in every shell state, including the Suspense fallback**, with a
   focusable `tabIndex={-1}` target in both (`layout.tsx:492-527`). Most apps get this wrong
   in exactly the loading state where it matters most.

7. **`lookup()` instead of bare object indexing on every server-chosen string** — copy
   tables, status maps, facet keys (`lib/lookup.ts`, used at `leads/page.tsx:1150-1158`,
   `attention/page.tsx:188`, `campaigns/page.tsx:960` where it prevented a *clickable button
   with no label* on a compliance row). Guarded by `tests/wireLookupGuard.test.ts`.

8. **Every filter on `/leads` is server-side**, so the count, the facet counts, the stage
   badges and the CSV cannot disagree with the rows (`leads/page.tsx:204-216`). Any new
   filter on any screen must follow this; a client-side filter over a capped page is the
   defect class this repo has already fixed four times.

9. **The bento grid on `/calls/[callId]`** (`calls/[callId]/page.tsx:191-211`) —
   `auto-rows-min grid-flow-row-dense`, short panels paired, long-form reading and the
   assistant input spanning full width, one column on mobile in DOM order. The comment
   explains the reasoning including why dense flow is safe here. **This is the layout answer
   to the flat-card problem and should be the first thing copied to `/quality`, `/lead-sources`
   and `/campaign-review`.**

10. **Chart honesty.** Heights relative to the busiest bucket rather than an invented axis,
    every bar printing its own value so the picture is checkable without a tooltip, zero
    buckets rendered rather than dropped, and IST calendar dates formatted without
    constructing a `Date` (`c/[slug]/page.tsx:291-375`, `performance/page.tsx:311-383`,
    `quality/page.tsx:309-366`). Only the a11y layer is missing (D1).

11. **Copy written for a business owner, not for the schema.** "Call blocked" not
    `lead_blocked` (`attention/page.tsx:31-59`); "12 midnight" not "0000 IST"
    (`performance/page.tsx:297-309`); `TermGloss` for `DLT`
    (`campaign-review/page.tsx:295`). Keep this standard.

12. **Failures are attributed to the row they belong to.** `RowFailure` renders an inline
    edit's error in the first cell of its own row, with the reasoning for *first cell*
    rather than *edited cell* written down (`leads/page.tsx:434-449`). A page-level notice
    on a 100-row table would say an edit failed without saying which.

---

## Appendix — findings index

| ID | Route | Severity |
| --- | --- | --- |
| C1 | cross-cutting | major |
| C2 | shell nav | major |
| AP1 | `/c` | major |
| D1 | `/c/[slug]` | major |
| D2 | `/c/[slug]` | minor |
| L1 | `/leads` | **blocker** |
| L2 | `/leads` | major |
| L3 | `/leads` | minor |
| L4 | `/leads` | major |
| LD1 | `/leads/[leadId]` | major |
| LD2 | `/leads/[leadId]` | major |
| LD3 | `/leads/[leadId]` | minor |
| LD4 | `/leads/[leadId]` | major |
| CL1 | `/calls` | major |
| CL2 | `/calls` | **blocker** |
| CL3 | `/calls` | major |
| CL4 | `/calls` | minor |
| CD1 | `/calls/[callId]` | major |
| CD2 | `/calls/[callId]` | minor |
| A1 | `/attention` | major |
| A2 | `/attention` | major |
| A3 | `/attention` | major |
| P1 | `/performance` | minor |
| P2 | `/performance` | minor |
| P3 | `/performance` | major — cross-reference to D1, not counted separately |
| Q1 | `/quality` | major |
| Q2 | `/quality` | minor |
| CP1 | `/campaigns` | **blocker** |
| CP2 | `/campaigns` | major |
| CP3 | `/campaigns` | major |
| CP4 | `/campaigns` | major |
| CP5 | `/campaigns` | minor |
| CP6 | `/campaigns` | minor |
| CR1 | `/campaign-review` | minor |
| CR2 | `/campaign-review` | minor |
| K1 | `/knowledge` | major |
| K2 | `/knowledge` | minor |
| K3 | `/knowledge` | minor |
| LS1 | `/lead-sources` | major |
| LS2 | `/lead-sources` | minor |

**3 blocker · 21 major · 15 minor.**
