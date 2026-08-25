# UX audit — ADMIN (operator/founder) realm

**Date:** 25 Aug 2026
**Scope:** every route under `apps/web/src/app/admin/**` (13 top-level screens + 11
`/admin/tenants/[tenantId]/**` screens), read against `apps/web/src/components/ui.tsx`,
`apps/web/src/components/interior/**` and `apps/web/src/lib/nav.ts`.
**Method:** read-only. No file outside this one was written. No Python, no git, no tests run.

## How this realm was judged

This is an **internal expert tool** used daily by the founder and a small operator team,
so the usual client-facing tradeoffs are inverted and that inversion is applied
throughout below:

- **Information density is a feature, not a defect.** A nine-column latency table and an
  eight-panel operations screen are not "cluttered" here. None of the findings below asks
  for anything to be removed from a screen; the progressive-disclosure findings all
  preserve every capability and only change what is open on arrival.
- **Discoverability matters less than speed.** A trained operator learns where things are.
  So "this control is hard to find" is downgraded almost everywhere — with one exception
  that is not about discovery at all: an operator arriving mid-incident from a runbook is
  a *first-time* user of that screen, every time, because they arrive rarely and under
  stress. Screens reached from `runbooks/` are judged as if unfamiliar.
- **Consequence beats convenience.** The one axis that gets *stricter* on an internal tool
  is blast radius. These operators can stop a client's phone line, reprice a contract and
  destroy a tenant's caller records. A mis-click here has no support queue behind it.

**What this realm gets right is the headline finding.** The console's stated doctrine —
never render a default over a failed read, gate on the permission the route declares,
state the blast radius above the button, take a typed confirmation bound to the specific
act — is unusually strong and is *argued in the code*, at length, with the rejected
alternative recorded. Most of the findings below are not "this was never thought about".
They are **the doctrine not yet reaching every screen**: patterns invented in
`app/admin/ops/**` that never propagated to `app/admin/tenants/**`.

## Evidence and its limits (hard rule 11)

The lane brief asked for cited UX research. **Most primary design sources are
egress-blocked from this machine**, re-measured today: `www.nngroup.com`, `www.w3.org`,
`w3c.github.io`, `design-system.service.gov.uk`, `m3.material.io` and `webaim.org` all
return `EGRESS_BLOCKED` at the proxy, and `developer.apple.com` returns a page with no
body text. I did not read them, so I do not quote them.

What I **did** read this session, and cite accordingly:

| # | Claim | Source | Class |
|---|---|---|---|
| S1 | WCAG 2.2 SC 3.3.4 *Error Prevention (Legal, Financial, Data)*, Level AA: for pages that "cause legal commitments or financial transactions … or that modify or delete user-controllable data", at least one of **reversible**, **checked**, or **confirmed** must hold — where "confirmed" is "a mechanism is available for reviewing, confirming, and correcting information before finalizing the submission". | Search-result summary of <https://www.w3.org/WAI/WCAG22/Understanding/error-prevention-legal-financial-data.html>, read 25 Aug 2026. **The W3C host itself is egress-blocked here**, so this is the criterion text as returned by search, not a page I opened. | REPORTED (criterion text is stable and widely quoted; treat the wording as indicative, the criterion number as certain) |
| S2 | Hick's law: decision time rises with the number of options, steeply from ~2 to ~7–8 alternatives and flattening after; past a threshold people stop comparing rather than choosing better. | Search-result summary, read 25 Aug 2026, over <https://deviq.com/laws/hicks-law/> and <https://dovetail.com/ux/hicks-law/> | REPORTED |
| S3 | Refactoring UI on destructive actions: a destructive button "doesn't have to always look red and big" — give it secondary or tertiary treatment when it is not the page's primary action, and "save the big, red, and bold styling for when that negative action actually is the primary action in the interface, like in a confirmation dialog." | Search-result summary of Refactoring UI guidance, read 25 Aug 2026, via <https://cieden.com/book/atoms/button/how-to-create-button-hierarchy> and <https://jacobshannon.com/blog/books/refactoring-ui/hierarchy-is-everything/> | REPORTED (secondary source describing the book, not the book) |
| S4 | This console's own doctrine on danger styling, confirmation, failed reads and one-way-per-problem. | `apps/web/src/components/ui.tsx:418-426`, `apps/web/src/app/admin/ops/page.tsx:113-172`, `apps/web/src/app/admin/layout.tsx:44-73`, read in full 25 Aug 2026 | **PRIMARY — read this session** |

**S4 is the strongest evidence class available here and most findings lean on it.** Where
this console's own written rule and this console's own code disagree, the finding does not
depend on any outside authority at all.

---

## Top 5 to fix first

Ranked by operational risk × frequency.

### 1. BLOCKER · cross-tenant ambiguity — three tenant-scoped screens never name the tenant

`/admin/tenants/[tenantId]/spend`, `/admin/tenants/[tenantId]/invoice`, and
`/admin/tenants/[tenantId]/agents/[agentId]/prompt` contain **no occurrence of the
client's name anywhere on the page**, and the shell header does not supply one either.
Full finding: [F-1](#f-1). This is a blocker and the single highest-value fix in the realm.

### 2. BLOCKER · dangerous tenant-scoped actions are styled identically to routine ones

`DANGER_BUTTON` exists, is documented as the console's answer to exactly this, and is used
in **zero** of the eleven `/admin/tenants/**` screens. The most destructive request in the
product — DPDP tenant erasure — ships a **brand-green** submit button. Full finding:
[F-2](#f-2), [F-3](#f-3).

### 3. MAJOR · "Reject" on a client's knowledge fires from one unconfirmed click, with a reason the operator never wrote

`/admin/tenants/[tenantId]` line 319-330: a single click sends `decision: "reject"` with a
hardcoded `reason: "Not suitable for the agent"`. No confirmation, no reason field, no
undo. Full finding: [F-4](#f-4).

### 4. MAJOR · `/admin/tenants/[tenantId]` is 11 undifferentiated chips over 7 undifferentiated cards

The realm's most-visited screen has no primary action and no grouping. Eleven identically
styled `NavLink` chips wrap in one row (Hick's law territory, S2), and below them seven
`Card`s of equal visual weight — a knowledge queue, a publish queue, agents, margin, spend
cap, campaign setup and WhatsApp alerts — with nothing saying which one the operator opened
this page for. Full finding: [F-5](#f-5), [F-6](#f-6).

### 5. MAJOR · onboarding ends in a silent hand-off to a queue

`/admin/new` finishes with three equal-weight **secondary** buttons and a "still manual"
checklist that names two items and **omits the three gates the account is about to be held
on** (KYC, commercial terms, first-campaign release). The founder does this for every
client; the wizard's last screen is the one place the next three steps could be named and
it names none of them. Full finding: [F-7](#f-7).

---

## Dangerous-action findings (called out distinctly)

These are the findings where a mis-click costs a client's phone line, their data, or a
wrong price. **Every one of them is a case of the ops realm's own pattern not having
travelled**, not of a pattern never having been invented.

### <a id="f-2"></a>F-2 · The DPDP erasure button is brand green · BLOCKER

- **Route:** `/admin/tenants/[tenantId]/lifecycle`
- **File:** `apps/web/src/app/admin/tenants/[tenantId]/lifecycle/page.tsx:410-416`
- **What is wrong:** the submit for "Erase this client's data" is
  `className={PRIMARY_BUTTON}`. `PRIMARY_BUTTON` is `bg-brand-strong` — the same green as
  "Create client", "Approve", "Publish" and "Record a payment". The panel's own copy two
  screens up says this "destroys every caller record … and cannot be undone."
- **Why:** this console wrote the rule itself. `components/ui.tsx:418-426` defines
  `DANGER_BUTTON` with the sentence *"The button that does something a person cannot undo.
  Rose, deliberately not `PRIMARY_BUTTON` … An operator's eye should refuse to find it
  there."* (S4). The most irreversible control in the product is the one that ignores it.
  S3 supports the same conclusion from the other direction: inside a confirmation step, the
  destructive action **is** the primary action, and that is precisely when red-and-bold is
  correct.
- **Fix:** `className={DANGER_BUTTON}` at line 413. One token. Nothing else on the panel
  needs to change — the typed confirmation, the reason field and the blast-radius
  `NoticeBox` are all already right.
- **Severity:** blocker (one-line fix, unbounded consequence).

### <a id="f-3"></a>F-3 · `LIFECYCLE_COPY.tone` is authored and never read — "Close the account" looks like "Reactivate" · BLOCKER

- **Route:** `/admin/tenants/[tenantId]/lifecycle`
- **Files:** `apps/web/src/lib/api/commercials.ts:206-228` (the data),
  `apps/web/src/app/admin/tenants/[tenantId]/lifecycle/page.tsx:216-218` (the render),
  `apps/web/src/components/actionButton.tsx:70-80` (the unconditional green gradient)
- **What is wrong:** `LIFECYCLE_COPY` carries a `tone` field — `ok` for Reactivate, `warn`
  for Suspend, `stop` for "Close the account" — and **nothing reads it**. The form renders
  `<ActionButton>` unconditionally, whose `style` hardcodes
  `linear-gradient(180deg, var(--brand-strong), var(--brand-deep))`. So the control that
  ends a client relationship, locks their users out and (per its own `consequence` string)
  "cannot be undone here" is pixel-identical to the control that turns dialling back on.
- **Also:** closing an account requires only a `<select>` change plus a 3-character reason.
  Halting outbound *for the whole platform* — a **reversible** act — requires a typed
  `HALT` (`app/admin/ops/page.tsx:449-450`). The friction is inverted with respect to
  reversibility. S1's three routes are reversible / checked / confirmed; closing an account
  is none of the three today (the reason field is checked, but for length, not for intent).
- **Fix, two parts:**
  1. Read the field that already exists: pass `LIFECYCLE_COPY[status].tone` down and render
     the `stop` arm with `DANGER_BUTTON` instead of `ActionButton`. The data is there; this
     is wiring, not design.
  2. Require a typed confirmation for `churned` only — reuse
     `app/admin/ops/opsLanguage.tsx:472 TypeToConfirm` rather than writing a fourth one
     (see [F-9](#f-9)). Leave Suspend exactly as it is: it is reversible and its current
     friction is correctly calibrated.
- **Severity:** blocker.

### <a id="f-4"></a>F-4 · One-click "Reject" on client knowledge, with a hardcoded reason · MAJOR

- **Route:** `/admin/tenants/[tenantId]`
- **File:** `apps/web/src/app/admin/tenants/[tenantId]/page.tsx:319-330`
- **What is wrong:**
  ```
  onClick={() => decide.mutate({ sourceId: source.id, decision: "reject",
                                 reason: "Not suitable for the agent" })}
  ```
  A single click, no confirmation, no undo, and a rejection reason the operator did not
  write and cannot see before it is sent. The button sits ~8px from "Approve" in the same
  `flex flex-wrap` row, so on a narrow viewport the two can reflow relative to each other
  between renders.
- **Why:** this is exactly S1's "modify or delete user-controllable data" case with none of
  the three mitigations — not reversible, not checked, not confirmed. And the console
  already knows the fix: `app/admin/ops/dnc/page.tsx:498-560` is the gold-standard shape —
  a quiet **secondary** "Release" that *reveals* a confirmation panel naming the specific
  row, with the blast radius, a typed word, and only then a `DANGER_BUTTON`. That is also
  exactly S3's recommendation (secondary until confirmation; red inside it).
- **Fix:** copy the `EntryRow` two-stage pattern. Secondary "Reject" → reveals a panel
  carrying the source name, a **required reason textarea** (this text is an operator's
  words about a client's document — it should never be a constant), and a `DANGER_BUTTON`
  submit. No typed word needed: the reason field is already the deliberate act, and adding
  a typed word to a routine review decision is how operators learn to type past them (the
  argument `app/admin/ops/page.tsx:133-136` makes for the audit-chain read).
- **Severity:** major.

### <a id="f-5"></a>F-5 · Eleven identical chips, one of which is the account-killer · MAJOR

- **Route:** `/admin/tenants/[tenantId]`
- **File:** `apps/web/src/app/admin/tenants/[tenantId]/page.tsx:147-247`
- **What is wrong:** eleven `NavLink`s in one `flex flex-wrap` row, all identically styled:
  Identity (KYC) · Campaign review · Invoice · Spend · Commercials · Credits · Feature flags
  · Language model · **Account state** · View as client. "Account state" — the screen that
  suspends and closes the account — is visually indistinguishable from "Invoice". Its own
  code comment at line 222-223 says it is *"Separate from everything above because it is the
  one control here that stops a client's outbound dialling outright"*, and then renders it
  in the same component as the other ten.
- **Why:** S2 — eleven equal-weight options is past the range where scanning stays cheap,
  and the cost lands on the item with the worst consequence. The screen's own comment states
  the intent and the markup does not carry it (S4: the code's stated reason is the evidence).
- **Fix (capability-preserving, no removals):** group the row into three labelled clusters
  in the existing wrap container — **Compliance** (KYC, Campaign review), **Money**
  (Invoice, Spend, Commercials, Credits), **Configuration** (Feature flags, Language model)
  — then pull **Account state** out of the row entirely and give it the console's existing
  `DangerZone` shell (`app/admin/ops/opsLanguage.tsx:530`, currently **zero users**, see
  [F-9](#f-9)) at the foot of the page. "View as client (read-only)" stays where it is: it
  is the most-used and it is already labelled read-only in text, which is right.
- **Severity:** major.

---

## Cross-tenant safety findings (called out distinctly)

### <a id="f-1"></a>F-1 · Three tenant-scoped screens never name the tenant · BLOCKER

- **Routes:** `/admin/tenants/[tenantId]/spend`, `/admin/tenants/[tenantId]/invoice`,
  `/admin/tenants/[tenantId]/agents/[agentId]/prompt`
- **Files:**
  - `apps/web/src/app/admin/tenants/[tenantId]/spend/page.tsx:60-97` — back link reads the
    literal string `Back to client`; no `<h1>`; `useTenant` is never called; no field on
    `TenantSpend` carrying a name is rendered.
  - `apps/web/src/app/admin/tenants/[tenantId]/invoice/page.tsx:39-41` — same literal
    `Back to client`, no `<h1>`. (The *printed sheet* names the org at
    `components/invoiceDocument.tsx:90`, but only once it has loaded, and never in the
    chrome the operator drives the month picker from.)
  - `apps/web/src/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page.tsx:111-116` —
    back link reads the literal word `Client`, `<h1>` reads `Agent prompt`. **`useTenant`
    IS called at line 83** and `tenant.data.name` is never rendered; only `.slug` is used,
    and only to build API calls. The agent's name is not shown either.
- **And the shell cannot cover for them.** `lib/nav.ts:48-59` picks the nav entry by
  longest-prefix; the longest `NAV` href matching `/admin/tenants/<id>/spend` is `/admin`,
  so `layout.tsx:628-630` prints **"Clients"** as the `<h1>` on every tenant sub-route. The
  layout is aware of this class of problem — its own docstring at lines 60-67 argues that
  an operator with cross-client reach "must never be one glance away from believing they
  are inside a client's own dashboard" (S4) — but the mechanism it built for it is the
  realm medallion, not the tenant identity.
- **Why this is a blocker and not a polish item:** the prompt screen is a **write** surface
  whose output is read aloud on a live phone line, and the entry path to the spend screen
  is `/admin/spend` → click a client name, i.e. the operator arrives having just been
  looking at *eight other clients' rows*. Every sibling screen already gets this right
  (`kyc`, `lifecycle`, `feature-flags`, `credits`, `commercials`, `llm-model`,
  `first-campaign-review` all render `{tenant.name}` as the back link, one consistent
  pattern), which makes these three a drift rather than a design position.
- **Fix:** adopt the sibling pattern verbatim on all three — `useTenant(tenantId)`, back
  link = `{tenant.name}`, `<h1>` = the screen name. On the prompt page also render the agent
  name beside the `<h1>`; a tenant with four agents makes "Agent prompt" ambiguous *within*
  the correct tenant. This is roughly six lines per screen and needs no new component.
- **Severity:** blocker.

### <a id="f-1b"></a>F-1b · A step further: the shell could guarantee this · MAJOR

- **Route:** all `/admin/tenants/[tenantId]/**`
- **File:** `apps/web/src/app/admin/layout.tsx:126-262, 612-646`
- **What is wrong:** F-1 is fixable per screen, but the *class* of defect recurs every time
  someone adds a tenant sub-route, because nothing structurally requires the tenant to be
  named. The shell already carries a persistent cross-client marker ("Cross-client · every
  action is audited") at `layout.tsx:637-641` — the exact slot where a *which client*
  marker belongs when one is in scope.
- **Why:** the layout's own argument (S4, lines 60-67) is that the operator must never be
  one glance from believing they are inside a client. Naming the realm answers half of
  that; naming the client answers the other half, and it is the half the audit log will be
  asked about.
- **Fix:** when `pathname` matches `/admin/tenants/<id>`, swap the cross-client pill for a
  tenant pill (name + `/c/slug`, linking to the account) fed by the same `useTenant` query
  key the pages already use, so it costs no extra request. Keep the cross-client pill
  everywhere else. This makes F-1 unrepeatable rather than merely fixed.
- **Severity:** major.

---

## Per-route findings

### `/admin` — client directory

**Good.** Count rendered only from a list that arrived (`page.tsx:113-115`); failed read
gets its own third branch rather than an empty table (`:151-157`); hold badges link to the
queue that clears them (`:215-224`). Nothing to fix.

- **F-8 · minor · the "View as" affordance is a lone action column.** `page.tsx:238-250`.
  Each row's only action is "View as", while the far more common operator move — open the
  account — is the client-name link at the other end of an 880px-min table. On a laptop the
  operator's eye travels the full row width for the primary action. **Fix:** make the
  Actions cell carry both ("Open" primary-weight, "View as" secondary), or move "View as"
  next to the name. Low risk, small win, high frequency.

### `/admin/health` — client health board

**Good, and worth copying to other lanes.** Four properties argued at `page.tsx:39-56` and
all four actually held: only what is wrong appears; every signal ends in a control
(`remedies()` at `:242-260`, deduped by href); a trend is only shown on a basis that earned
it (`trendClaim`); empty is the *good* state and says so. The headline
"N accounts need attention · M broken now" at `:87-102` is exactly the foregrounded
diagnostic number the brief asks for. **No findings.**

### `/admin/holds` — hold queue

**Good.** Wait rendered as a banded duration rather than a date to subtract
(`page.tsx:207-216`); headline count + "N waiting over a week"; unknown rules keep their
row and still route somewhere real (`:249-257`). **No findings.**

### `/admin/spend` — money board

**Good.** Nothing summed in the browser; a losing month is marked with a triangle *and* an
`sr-only` "Losing money:" so colour is not the only signal (`page.tsx:172-177`) — this is
the one screen in the realm that handles the colour-alone problem explicitly, and it should
be the pattern other lanes copy.

- **F-9a · minor · month picker has no bounds.** `page.tsx:60-66`. A bare
  `<input type="month">` with no `max`, so an operator can ask for 2027-03 and get a
  legitimately empty board that reads like a failure. **Fix:** `max={currentISTMonth}`.
  Same one-liner applies to `/admin/tenants/[id]/spend:76-82` and
  `/admin/tenants/[id]/invoice:43-49`.

### `/admin/qa-sampling` and `/admin/qa-sampling/[sampleId]`

- **F-10 · minor · hand-rolled tone classes.** `qa-sampling/page.tsx:76` builds the
  "N marked as a defect" badge from `border-red-200 bg-red-50 … text-red-800`. The two
  screens with the structurally identical badge — `health/page.tsx:93-100` and
  `holds/page.tsx:93-100` — both use `NOTICE_TONES.stop`, which is **rose**, not red. Three
  screens, one badge, two palettes. `ui.tsx:356-365` exists precisely to stop this (S4:
  *"two screens describing the same four states in two colour tables is where the drift
  starts"*). **Fix:** `NOTICE_TONES.stop`.
- **F-11 · minor · a derived percentage on a screen whose doctrine forbids derivation.**
  `qa-sampling/page.tsx:189`: `Math.round((row.target / row.population) * 100)`. Every other
  board in this realm renders the server's own figures and says so. This one divides two
  wire fields in the browser; a `population` of 0 renders `Infinity%` or `NaN%`. **Fix:**
  either take the percentage from the server or guard `population > 0`. Low impact, but it
  is the only derived statistic in the realm and it is the kind that ages badly.

### `/admin/new` — new-client wizard

- <a id="f-7"></a>**F-7 · major · the flow ends without naming the next three steps.**
  `new/page.tsx:866-887`. The final screen offers three **secondary** buttons — "Back to the
  intake", "Open client", "Back to clients" — so there is no primary action at all, and the
  operator's next real move is unstated. The "Still manual for this client" card
  (`:696-715`) names two items (number/DLT registration, test-call sign-off) and **omits**
  the three gates the freshly created account is immediately held on and which all have
  working screens: **KYC** (`/admin/tenants/<id>/kyc`), **commercial terms**
  (`/admin/tenants/<id>/commercials`), and **first-campaign release**
  (`/admin/tenants/<id>/first-campaign-review`). The account therefore drops silently into
  `/admin/holds` — discovered later, from a queue, instead of continued now, from the flow
  that created it. This is the founder's highest-frequency task in the realm.
  **Fix:** make "Open client" the single primary action, and turn the "still manual" card
  into a **what happens next** checklist that links those three screens in order alongside
  the two genuinely-manual items. Nothing new is built; three `Link`s and a promotion.
- **F-12 · minor · the step indicator is a text line while a `WizardSteps` component sits
  unused.** `new/page.tsx:259-265` renders `"Step 1 of 3 — account details"` as a
  `text-xs uppercase` paragraph. `apps/web/src/components/interior/wizard-steps.tsx` exists
  and has **zero importers** (see [F-13](#f-13)). Not worth building a component for; worth
  using the one that is already paid for.
- **Good:** `mustChooseSlug` (`:242-250`) refuses to let the server substitute a constant
  for a Telugu business name — a genuinely excellent piece of India-first product thinking,
  and it converts a post-submit refusal into a pre-submit question. Worth copying.

### `/admin/operators`

Uses `DANGER_BUTTON` correctly at `:797` (`danger ? DANGER_BUTTON : PRIMARY_BUTTON_SM`).
**No findings** beyond the shared [F-9](#f-9).

### `/admin/ops` — incident surface

The strongest screen in the product, and the source of most of the doctrine cited above.
Genuinely good and worth copying: the `boolean | null` platform state with no default
(`page.tsx:96-103`); blast radius stated **above** the button in the order
what-it-does → what-it-does-not → it-is-recorded (`:505-529`); the load-shed form seeded to
**no change** so "click the obvious button" cannot release someone else's shed
(`:606-614`); and the honest copy admitting `reduced` and `emergency` shed the identical
set today (`:229-239`) — a screen refusing to let an operator spend an escalation for
nothing.

- **F-14 · major · 2,030 lines and eight stacked panels with no way to move within them.**
  `apps/web/src/app/admin/ops/page.tsx` — 2,030 lines / 98,095 bytes, the largest route in
  the realm. Eight panels stack vertically: outbound halt, load-shed, TM registration,
  outbox replay, engine drift, KB drift, audit chain, "what is never shed". An operator
  arriving from `runbooks/calls-stopped.md` scrolls past the load-shed form to reach the
  drift panels. Per the density principle above, **nothing should be removed** — but an
  incident-time reader is a first-time reader.
  **Fix:** a sticky in-page jump list at the top (six anchors), or adopt
  `components/interior/tabs.tsx` (unused — [F-13](#f-13)) with the halt panel outside the
  tabset so it is never one click away. Do **not** collapse panels by default: on this
  screen "closed" and "nothing wrong" are indistinguishable, which is the exact failure
  `UnknownStatePanel` (`:405-431`) exists to prevent.
- <a id="f-9"></a>**F-9 · major · `TypeToConfirm` / `confirmMatches` / `DangerZone` are
  written, exported, and used almost nowhere.** `app/admin/ops/opsLanguage.tsx:472, 517,
  530`. `TypeToConfirm` has exactly **two** importers (`ConfigPanel.tsx`, `ops/dnc/page.tsx`).
  `DangerZone` has **zero**. Meanwhile `ops/page.tsx:555-563` and `:739-747` hand-roll the
  same confirm input — *inside the very module that exports the component* — and
  `lifecycle/page.tsx:387-408` hand-rolls a third. That is three spellings of one control,
  on the three surfaces where the control's job is to make an operator stop and read.
  **Why it matters beyond tidiness:** a typed confirmation is a *habit*. Three shapes means
  the muscle memory does not transfer, and the screen where it does not transfer is the one
  the operator visits least. This is the CLAUDE.md "one way per problem, and migrate rather
  than accumulate" rule against a control whose entire value is consistency.
  **Fix:** move `TypeToConfirm` / `confirmMatches` / `DangerZone` out of `ops/opsLanguage`
  into `components/ui.tsx` (they carry no ops-specific state) and migrate all five call
  sites in the same change, including the two inside `ops/page.tsx`.

### `/admin/ops/config`

**Good.** Per-panel permission gating rather than per-screen (`config/page.tsx:52-60`);
panels *not mounted* for a refused session so no request fires whose only outcome is a 403;
the `identityAnswerPending` guard so nothing appears, populates, and is then withdrawn.
**No findings.**

### `/admin/ops/dnc`

**The best dangerous-action pattern in the codebase.** `dnc/page.tsx:498-560`: quiet
secondary trigger → reveals a confirmation bound to *this row* → blast radius in plain
words → reason-on-file echoed back → typed `RELEASE` → `DANGER_BUTTON` → explicit cancel.
Plus `aria-label={"Release the platform-wide suppression on " + phone}` at `:487-489`, so
forty buttons are forty *distinct* announcements. **This is the pattern F-3 and F-4 should
copy.** No findings.

### `/admin/ops/engine-latency`

- **F-15 · major · the diagnostic number is not foregrounded on an incident screen.**
  `engine-latency/page.tsx:195-217`. The three header `StatTile`s are "Target for the first
  reply", "Rows in this window", and "Window". None of them answers the question the
  operator arrived with. `runbooks/alarm-index.md`'s `engine_llm_ttft_degraded` entry sends
  them here to find out **whether anything is over target**, and to learn that they must
  scan the ninth column of a nine-column table.
  **Why:** `/admin/health` and `/admin/holds` both solve this identically — a derived count
  above the table, argued in `health/page.tsx:84-86` as *"the number an operator carries
  away … a number that only exists as a row you scroll to is a number nobody has"* (S4).
  This screen is the one where that argument is worth the most and it is the one that does
  not do it.
  **Fix:** a fourth tile, "N of M rows over target", counting rows whose **server-supplied**
  verdict (`budgetVerdict(group)`, already computed per row at `:336`) is `over`, with the
  `unknown` rows named separately so "we could not tell" never reads as "fine". This counts
  verdicts, it does not derive a percentile — the screen's no-derivation doctrine (`:50-56`)
  is preserved exactly, and it is the same class of client-side count `health` already does.
- **Good:** three-state `budget_breached` rendered as three states, with the unknown arm
  deliberately not muted into invisibility (`:296-314`); every column header carries a
  plain-English gloss for a non-engineer operator (`HeadCell`, `:316-333`). Copy both.

### `/admin/tenants/[tenantId]` — account detail

Findings [F-4](#f-4) and [F-5](#f-5) above, plus:

- <a id="f-6"></a>**F-6 · major · seven equal `Card`s and nothing is primary.**
  `page.tsx:250-448`: stat tiles, then Knowledge queue, Approved-awaiting-publish, Agents,
  Margin, Spend cap, Campaign setup, WhatsApp alerts — all `<Card>`, all the same weight,
  in an order nothing on screen explains. This is the flat-stack defect the founder flagged
  on the client agents pages, and this is its worst instance in the admin realm.
  **Fix, capability-preserving:** the screen already knows what is urgent —
  `HoldsBanner` (`:568-597`) renders only when something is blocking, and the Knowledge
  queue is only actionable when non-empty. Promote the **actionable** cards (a non-empty
  knowledge queue, a non-empty publish queue, a breached spend cap) to the top with a
  count in the title, and demote the reference panels (WhatsApp alerts, campaign setup)
  below a `<details>`-style divider or the unused
  `components/interior/collapsible-banner.tsx`. Nothing is removed and no click is added
  for the common path.
- **F-16 · major · the screen re-implements four `ui.tsx` primitives locally.**
  `page.tsx:476-554` defines its own `BUTTON_BASE`, `PrimaryButton`, `SecondaryButton`,
  `DangerButton` and `FIELD`, duplicating `ui.tsx`'s `PRIMARY_BUTTON_SM`,
  `SECONDARY_BUTTON_SM`, `DANGER_BUTTON` and `FIELD`. They have already drifted: the local
  `DangerButton` is a rose **outline** (`border-rose-300 text-rose-700`) while the shared
  `DANGER_BUTTON` is a rose **fill**, so "Reject" on this screen and "Release" on
  `/admin/ops/dnc` claim two different danger levels for two comparably serious acts.
  `ui.tsx:367-383` argues this exact case (S4: *"five identical string literals stay
  identical only until someone improves one"*). **Fix:** delete the four locals and import
  the shared ones. The local `FIELD`'s `min-w-0` note at `:544-552` is a real fix and should
  be **promoted into the shared `FIELD`**, not kept as a reason to keep the fork.
- **Good:** `HoldsBanner` (`:556-597`) is exactly right — renders nothing when nothing
  holds them, and its docstring names the failure it prevents (*"the panels below all read
  as 'this client is nearly ready'"*). The eleven-chip row's per-chip comments explaining
  *why each screen is its own screen* are the best in-code design rationale in the repo.

### `/admin/tenants/[tenantId]/commercials`

**Good, and the most careful money screen in the realm.** Form **withheld** (not merely
unpopulated) when the current agreement is unreadable, with the reason stated (`:99-113`);
the loosening confirmation is sent **only** when a write loosens a ceiling
(`lib/api/commercials.ts:248-251` — *"a confirmation header attached to every request would
be a confirmation of nothing"*); fees through `formatINR` and rates unrounded through a
separate `rate()` so `qty × unit = amount` still holds (`:155-165`). **No findings.**

### `/admin/tenants/[tenantId]/credits`

- **F-17 · major · three always-open write forms over an append-only ledger.**
  `credits/page.tsx:387` (Record a payment), `:715` (Correct a wrong entry), `:1097`
  (A payment was for more than we recorded), plus five more cards — eight in total, nothing
  primary. Two of the three forms are **exception paths**; on the overwhelmingly common
  visit the operator wants only the first. All three are open, at full height, in a screen
  whose own header says *"Every line is permanent"*.
  **Why:** S2 — three structurally similar money forms presented simultaneously is where a
  correction gets typed into a restatement. The screen already has the right container for
  it: `CorrectionCard` at `:1568` ("If a credit was wrong") is a card that *explains* the
  two exception paths and sits at the bottom.
  **Fix:** keep "Record a payment" open and primary; collapse "Correct a wrong entry" and
  "A payment was for more than we recorded" into the `CorrectionCard` as two disclosure
  triggers. Capability is unchanged, the double-entry confirmation on each is unchanged,
  and the two rare paths gain the deliberate act of opening them.
- **Good:** the three-state `LedgerState` (`:280-292`) — *"a balance of ₹0 and a balance we
  could not read are OPPOSITE facts"* — and `CorrectionCard` rendered on **every** branch
  including the unreadable one, because *"the operator most likely to need it is the one who
  has just credited the wrong account and come back to a screen that will not load"*
  (`:262-265`). That is first-class incident thinking. Copy it.

### `/admin/tenants/[tenantId]/feature-flags`

**Good.** Three facts per flag (platform default, this client's override, resolved answer);
controls withheld when the current state is unreadable, with the reason (`:141-153`); the
`key={flag|override|reason}` remount rule so a poll cannot wipe a half-typed reason
(`:165-171`); and the "What these are not" box (`:111-131`) whose third bullet —
*"Never a compliance control … If someone asks for that, the answer is no and the reason is
that those checks are the law, not a preference"* — is the best piece of copy in the realm.
**No findings.**

### `/admin/tenants/[tenantId]/kyc`, `/first-campaign-review`, `/llm-model`

All three follow the sibling pattern correctly: `{tenant.name}` back link, screen-name
`<h1>`, tenant name threaded into the child panels. **No findings** beyond the shared
[F-9](#f-9) (hand-rolled confirmations) where they apply.

### `/admin/tenants/[tenantId]/lifecycle`

Findings [F-2](#f-2) and [F-3](#f-3) above.
**Good:** the erasure read-ladder at `:256-286` — the panel refuses to render the erasure
*form* while the "has one already been filed" read is in flight or failed, because *"a
screen that offers an irreversible, tenant-wide DPDP erasure while stating that none has
been filed is worse than a blank one"*. That is the highest-stakes §52 application in the
codebase and it is correct.

### `/admin/tenants/[tenantId]/spend`, `/invoice`, `/agents/[agentId]/prompt`

Finding [F-1](#f-1) above (blocker). Otherwise:

- **Good (invoice):** Print is disabled until a statement exists (`:52-56`) — *"printing a
  skeleton or an error box produces a sheet of paper that looks like an invoice and is not
  one."*
- **Good (spend):** the unconditional honesty note about `cost_currency_stated`
  (`:51-58`) — the screen refuses to let an operator quote a margin whose denominator is an
  assumption.

---

## Cross-cutting findings

### <a id="f-13"></a>F-13 · 18 of 19 `components/interior/**` components have zero importers · MAJOR

`apps/web/src/components/interior/`: `collapsible-banner`, `dropdown`, `floating-label`,
`live-activity`, `load-more`, `loading-button`, `new-items-pill`, `otp-input`, `pagination`,
`progress-bar`, `show-more`, `skeleton-swap`, `sticky-header`, `streaming-text`, `tabs`,
`task-steps`, `tree-view`, `wizard-steps` — **none** is imported anywhere in
`apps/web/src`. Only `toaster` is used (7 sites, 1 of them admin).

This is a half-wired design system, and it is why several findings above describe building
something that already exists: `/admin/new` hand-writes a step counter beside an unused
`wizard-steps`; `/admin/ops` stacks eight panels beside an unused `tabs`;
`/admin/tenants/[id]` and `/credits` want progressive disclosure beside an unused
`collapsible-banner` and `show-more`.

**Fix (and it is a decision, not a refactor):** either adopt them in the places this audit
names, or delete the ones nothing will ever use. The CLAUDE.md rule that applies is
"leave no half-wired feature — a column nobody reads is not progress". This lane cannot
tell which of the two is right without knowing what they were built for; that is a
one-sentence answer from whoever wrote them, and then a small change either way.
**Severity:** major (as a set; individually minor).

### F-18 · accessibility · minor

The realm is unusually strong here — `SkipLink`, `ScrollRegion` on every wide table, the
`role="status"` skeleton with an `sr-only` label, `aria-current` from a single nav rule,
`touch:min-h-11` on every control, and `sr-only` text alongside colour on `/admin/spend`.
Two gaps found:

1. **Colour-only signalling outside `/admin/spend`.** `/admin/tenants/[id]/spend:113-119`
   and `/admin/spend:83-91` colour a negative margin rose with no text alternative on the
   *header tile* (the table row has one; the tile does not). Same for
   `engine-latency`'s `VERDICT_COPY.over` — that one is fine, it carries the word "over
   target". **Fix:** add the `sr-only "Losing money: "` prefix to the margin tiles, copying
   `spend/page.tsx:172-177`.
2. **Dead nav entries announce as `aria-disabled` `<span>`s** (`layout.tsx:372-394`). This
   is deliberate and well argued, and the visible reason paragraph is rendered beside them —
   but the `<span>` is not focusable, so a keyboard user tabbing the sidebar never reaches
   the entry *or* its explanation, and only encounters the gap. **Fix:** `tabIndex={0}` plus
   `aria-describedby` pointing at the reason paragraph, so the refusal is reachable by the
   same route as the links around it.

### F-19 · oversized routes · informational

| Route file | Lines | Bytes |
|---|---:|---:|
| `admin/ops/page.tsx` | 2,030 | 98,095 |
| `admin/tenants/[tenantId]/agents/[agentId]/prompt/page.tsx` | 1,681 | 71,147 |
| `admin/tenants/[tenantId]/credits/page.tsx` | 1,668 | 72,233 |
| `admin/tenants/[tenantId]/page.tsx` | 1,530 | 67,973 |
| `admin/ops/ConfigPanel.tsx` | 1,193 | 51,299 |
| `admin/new/IntakeStep.tsx` | 1,004 | 41,284 |
| `admin/operators/page.tsx` | 951 | 37,641 |
| `admin/new/page.tsx` | 889 | 39,905 |
| `admin/layout.tsx` | 806 | 38,424 |

A large share of every one of these is docstring, and that is a deliberate and valuable
property of this repo — **this is not a finding, it is context for F-14 and F-6.** The four
files over 1,500 lines are all screens this audit found to have a structure problem, which
is the correlation worth noting: the panels grew and the page never got a spine.

---

## What is genuinely good — copy these to other lanes

1. **Never render a default over a failed read.** The `boolean | null` platform state
   (`ops/page.tsx:96-103`), the three-state `LedgerState` (`credits/page.tsx:280-292`), and
   the `|| !query.data` arm that catches TanStack's *paused* (offline) state on five
   screens. "Zero" and "we could not read it" are opposite facts and this realm never
   conflates them. **This is the single most transferable idea in the codebase.**
2. **Blast radius above the button, in a fixed order** — what it does, what it does *not*
   do, that it is recorded (`ops/page.tsx:505-529`). The middle clause is the one most
   products omit and the one operators most need.
3. **The two-stage dangerous action** — `ops/dnc/page.tsx:498-560`. Secondary trigger,
   revealed confirmation bound to the specific row, blast radius, typed word, `DANGER_BUTTON`,
   explicit cancel, per-row `aria-label`. Matches S3's guidance exactly.
4. **Every work-list row ends in a control** — `holds.remedies` and `health.remedies`, both
   deduped by href so one row never offers the same screen twice.
5. **Empty is the good state, and it says so** — `/admin/holds`, `/admin/health`,
   `/admin/qa-sampling` all distinguish success-empty from failed-read, in three branches.
6. **One list drives the sidebar, the header title and the `aria-current` highlight**
   (`lib/nav.ts` + `layout.tsx:126-262`). A renamed screen cannot keep its old name.
7. **The permission the *route* declares, previewed before the click**, with the reason
   rendered *beside* the dead control rather than in a `title` (`app/admin/access.ts`,
   `RestrictionNote`). Plus the deliberate fail-**open** on unknown: `refused`, never
   `!allowed`, so a slow `/v1/admin/me` cannot lock an operator out of an incident.
8. **Copy written for the reader's actual job.** `LOAD_SHED`'s admission that `reduced` and
   `emergency` shed the same set; feature-flags' "Never a compliance control"; the
   engine-latency column glosses. This is the register the whole product should be in.

---

## Severity counts

| Severity | Count | Findings |
|---|---:|---|
| **Blocker** | 3 | F-1, F-2, F-3 |
| **Major** | 11 | F-1b, F-4, F-5, F-6, F-7, F-9, F-13, F-14, F-15, F-16, F-17 |
| **Minor** | 6 | F-8, F-9a, F-10, F-11, F-12, F-18 |

- **Dangerous-action findings:** F-2 (blocker), F-3 (blocker), F-4 (major), F-5 (major),
  F-9 (major), F-16 (major), F-17 (major).
- **Cross-tenant-ambiguity findings:** F-1 (blocker), F-1b (major).

The three blockers are between one line and six lines of code each. None of them requires a
new component, a new endpoint, or a design decision that has not already been made and
written down somewhere in this repo.
