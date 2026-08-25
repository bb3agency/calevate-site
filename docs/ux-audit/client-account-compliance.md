# UX audit — client account, money, settings and compliance screens

**Date:** 25 Aug 2026
**Lane:** `apps/web/src/app/c/[slug]/` — `/settings/alerts`, `/settings/models`, `/settings/team`,
`/usage`, `/spend`, `/invoice`, `/integrations`, `/ai-assist`, `/verification`,
`/caller-notice`, `/data-rights`, `/do-not-call`, `/messaging-consent`
**Method:** read-only source audit. No file in this tree was edited; this document is the only write.
**Scope note:** these are low-frequency, high-consequence screens — money, legal duties, and
settings set once that must be right. Judgements are graded on *consequence × confusion*, not on
how often a screen is opened.

## Evidence classes used here

Every claim below is either (a) a line of source in this repo that I read this session, cited
`file:line`, or (b) a design principle from a primary source I read this session, cited with URL
and date. Where I could not verify something I say so in those words. Two numeric contrast claims
are taken from **this repo's own measured values** in `apps/web/src/app/globals.css:39,88` — a
prior session's browser axe-core run — and are labelled REPO-MEASURED rather than re-measured by me.

**Sources read 25 Aug 2026:**

- [W3C WAI — Understanding SC 2.4.7 Focus Visible (Level AA)](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html)
- [W3C WAI — F78: Failure of SC 2.4.7 due to styling that removes the visual focus indicator](https://www.w3.org/TR/WCAG20-TECHS/F78.html)
- [W3C WAI — Understanding SC 2.4.13 Focus Appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html)
- [GOV.UK Design System — Check answers pattern](https://design-system.service.gov.uk/patterns/check-answers/)
- [GOV.UK Design System — Button (warning button / confirming destructive actions)](https://design-system.service.gov.uk/components/button/)
- [NN/g — Confirmation Dialogs Can Prevent User Errors](https://www.nngroup.com/articles/confirmation-dialog/)
- [NN/g — Preventing User Errors: Avoiding Conscious Mistakes](https://www.nngroup.com/articles/user-mistakes/)
- [NN/g — Dangerous UX: Consequential Options Close to Benign Options](https://www.nngroup.com/articles/proximity-consequential-options/)
- [NN/g — Progressive Disclosure](https://www.nngroup.com/videos/progressive-disclosure/)

---

## Headline

This lane is, on the whole, **better than the industry standard it is being measured against.**
The §52 discipline (loading is a skeleton, failure is a refusal, **and neither is a zero**) is
applied consistently and correctly across `/usage`, `/spend`, `/invoice`, `/ai-assist`,
`/do-not-call`, `/data-rights`, `/settings/team` and `/settings/alerts`. The money screens do no
arithmetic on money. The compliance screens distinguish "the server said none" from "the server
did not answer" — which is the single most valuable property a compliance console can have. See
**What is genuinely good** at the end; several of these patterns should be copied to other lanes
rather than merely preserved.

The defects that remain cluster into three shapes:

1. **One route was left behind by the design-token and heading migration** (`/integrations`) and
   carries two verified WCAG AA contrast failures plus a destructive control that is mislabelled
   and irreversible.
2. **Confirmation friction is inverted.** The two genuinely reversible actions in the lane are the
   ones with the heaviest ceremony; four irreversible or high-consequence actions fire on a single
   unconfirmed click.
3. **A keyboard focus indicator is missing from the two custom radio groups**, which are the
   controls for choosing an AI model (money) and recording a consent answer (law).

**Counts by severity: 4 blocker · 9 major · 7 minor (20 findings).**
**Compliance-visibility findings: 5** — flagged 🔒 and listed together in the section below so no
later redesign can weaken them by accident.

---

## Top 5 to fix first (ranked by consequence × confusion)

| # | Route | Finding | Severity |
|---|---|---|---|
| 1 | `/integrations` | "Turn off" is a one-click, unconfirmed `DELETE` with **no way back in the UI** — it silently stops the client's live CRM feed and the label promises a switch that does not exist | blocker |
| 2 | `/integrations` | Twelve `text-slate-500` and five `text-slate-400` spans bypass the token system; REPO-MEASURED at **3.75:1 (dark)** and **2.56:1 (light)** against a 4.5:1 requirement — including the sentence warning that deliveries will fail | blocker |
| 3 | `/settings/models`, `/messaging-consent` | `sr-only` radios inside styled labels with **no focus ring** — a keyboard user cannot see which AI model (money) or which consent answer (law) is focused. WCAG 2.4.7 AA, failure technique F78 | blocker |
| 4 | `/settings/team` | Changing a colleague's role fires on `<select>` change and "Remove" fires on one click — **no confirmation on either**, on the screen that controls who can see billing and who can remove *you* | blocker |
| 5 | `/do-not-call` | "Remove" un-suppresses a number with **no confirmation**, putting a person back in the dial pool. Compare `/data-rights`, which makes you type `ERASE` | major 🔒 |

---

## Compliance-visibility findings (🔒) — do not weaken in any redesign

These five concern controls that carry real Indian legal duties (DPDP / TRAI / DLT). **A redesign
may make any of these more prominent; none may be made less visible, more collapsed, more deeply
nested, or moved behind progressive disclosure.**

- **C-1** 🔒 `/do-not-call` — un-suppressing a number has no confirmation (finding 5 above, DNC-1).
- **C-2** 🔒 `/settings/alerts` — withdrawing consent is styled as a red destructive action while
  granting it is a friendly primary (ALERT-1). Withdrawal must never look more dangerous than grant.
- **C-3** 🔒 `/verification` sits under **"Settings & account"**, not "Compliance & data", even
  though it is the screen a client reaches when outbound calling is legally blocked (NAV-2).
- **C-4** 🔒 `/messaging-consent` — the consent answer radios have no visible keyboard focus
  (finding 3 above, MC-1).
- **C-5** 🔒 `/data-rights` — the irreversible erasure form asks for a phone number with no
  "check your answers" step and no way to see *whose* record is about to be destroyed (DR-1).

Everything in the lane that is currently working *for* compliance visibility is listed under
**What is genuinely good**; that list is also a do-not-weaken list.

---

# Per-route findings

## `/integrations` — `apps/web/src/app/c/[slug]/integrations/page.tsx` (878 lines, 40,301 bytes)

**This is the one route in the lane that the design-token and page-heading migration did not
reach.** Every other file in this lane returned `0` for raw Tailwind colour literals; this one
returns **74**. It is also the largest file in the lane and the only one whose destructive control
is unlabelled and irreversible. It should be treated as a single remediation job, not twelve.

### INT-1 · "Turn off" is a one-click, unconfirmed, irreversible `DELETE` — **blocker**

- **file:line** — `integrations/page.tsx:276-285` (the button); `apps/web/src/lib/api/integrations.ts:259-264`
  (the mutation is `DELETE /v1/integrations/endpoints/{id}`); `apps/api/integrations/routes.py:667`
  (the only endpoint-scoped route is that `DELETE` — I found no re-activate route).
- **What is wrong** — three compounding problems in one control:
  1. It fires immediately on click. No dialog, no typed confirmation, no undo.
  2. The label says **"Turn off"**, which promises a reversible switch. The row it acts on then
     renders an `off` badge (`:250-254`) with **no control to turn it back on** and no delete
     control either. The only route back is registering a new endpoint — which issues a **new
     signing secret**, so the client must also reconfigure their CRM.
  3. The consequence is invisible from the button: this silently stops the client's live lead
     feed into their own CRM, and nothing on the screen says so.
- **Why** — NN/g: confirmation dialogs exist precisely for "irreversible actions", and undo is the
  preferred complement ([Confirmation Dialogs Can Prevent User Errors](https://www.nngroup.com/articles/confirmation-dialog/),
  read 25 Aug 2026). GOV.UK is more specific still: where an action "cannot easily be undone or
  might have serious consequences", use a normal button for the call to action and a **warning
  button** for the final confirmation ([Button](https://design-system.service.gov.uk/components/button/),
  read 25 Aug 2026). A label that describes a toggle when the operation is a delete is also a
  match-between-system-and-real-world failure independent of the missing confirmation.
- **Proposed fix**
  1. Rename the control to **"Stop sending events"** and give it `aria-label={`Stop sending events to ${endpoint.url}`}`
     (see INT-3 — every row's button currently has the identical accessible name).
  2. Route it through a confirmation modal reusing the **existing** accessible dialog in
     `apps/web/src/components/aiExtraDialog.tsx:81-82` (`role="dialog"` + `aria-modal` + labelled
     by its heading + focus trap). The dialog names the endpoint URL, states "your CRM will stop
     receiving leads immediately", and states that this cannot be undone from this screen and that
     re-adding it issues a new signing secret. Style the confirm with `DANGER_BUTTON`
     (`components/ui.tsx:425`), whose docstring already reserves it for exactly this.
  3. Render the `off` rows with a plain sentence — "stopped; add a new endpoint to resume" — so
     the dead state explains itself rather than looking like a missing button.
- **Severity** — **blocker**. One mis-click, no confirmation, no undo, and a support call to
  re-key a secret.

### INT-2 · Two verified WCAG 1.4.3 AA contrast failures from raw colour literals — **blocker**

- **file:line** — `text-slate-500` with no `dark:` variant at `:142, :163, :260, :321, :349, :418,
  :503, :614, :635, :663, :790, :844` (12 spans). `text-slate-400` at `:269, :369, :499` plus two
  inside colour maps at `:56, :346`.
- **What is wrong** — REPO-MEASURED, from this repo's own axe-core browser run recorded in
  `apps/web/src/app/globals.css`:
  - `#94a3b8` (= Tailwind `slate-400`) is **2.56:1 on `--surface`** in light theme
    (`globals.css:39`), against a 4.5:1 requirement. Used at `:269` for the string
    *"not connected to Google yet — deliveries will fail until we connect it"* — a warning about a
    broken integration, rendered at roughly half the required separation.
  - `#64748b` (= Tailwind `slate-500`) is **3.75:1 on `--surface`** in dark theme
    (`globals.css:88`). That is exactly why the dark `--text-faint` token was moved to `#7c8a9c`.
    These twelve spans carry no `dark:` variant, so they render at the failing value the token
    system already fixed everywhere else.
- **Why this survived both gates** — and this is the part worth recording:
  - `tests/contrast.test.ts` checks **the token palette**, by its own statement: *"Ink on a
    non-token background … is out of scope."* Raw `slate-*` literals are invisible to it.
  - `tests/a11y.ts` **disables axe's `color-contrast` rule** under jsdom (no layout, no
    `createRange`). `/integrations` *is* in `a11y.test.tsx:54`, so it passes the suite while
    failing the criterion.
  So the enforced floor genuinely cannot see this file. That is a gate gap, not just a styling
  lapse. WCAG 1.4.3 Contrast (Minimum), Level AA.
- **Proposed fix** — replace all 74 literals with the tokens the rest of the lane already uses:
  `text-slate-900 dark:text-slate-50` → `text-ink`; `text-slate-700 dark:text-slate-300` →
  `text-ink-muted`; `text-slate-500` / `text-slate-400` → `text-ink-faint` (which is token-checked
  in both themes); `border-slate-300 dark:border-slate-600` → `border-line`; `bg-slate-100
  dark:bg-slate-800` → `bg-surface-muted`; `divide-slate-100 dark:divide-slate-800` →
  `divide-line`. Then extend `contrast.test.ts` with a **source-level rule** that fails on any
  `text-slate-`/`text-gray-`/`text-zinc-` under `src/app/c/` and `src/app/admin/`, so the next
  file cannot repeat this. That grep is the cheap half of the fix and is what makes it stay fixed.
- **Severity** — **blocker**. A verified AA failure on a warning message, in a gate blind spot.

### INT-3 · Duplicate `<h1>` and duplicate accessible names — **major**

- **file:line** — `integrations/page.tsx:141` renders `<h1>Integrations</h1>`; the app shell
  already prints the page title from the nav list (`layout.tsx:331`). Every other file in the lane
  removed theirs and left a comment explaining why (`settings/alerts/page.tsx:57`,
  `settings/models/page.tsx:70`, `usage/page.tsx:58`, `verification/page.tsx:72`,
  `do-not-call/page.tsx:72`, `messaging-consent/page.tsx:85`). `caller-notice/page.tsx:74` is the
  only other survivor (see CN-1).
- **What is wrong** — two `<h1>`s with the same words. Beyond the duplication, it is a drift trap
  the other files call out explicitly: rename the nav entry and this screen keeps arguing with it.
  Separately, the "Turn off" buttons at `:277` have no `aria-label`, so a screen reader on a list
  of five endpoints hears "Turn off, button" five times — the exact defect `do-not-call/page.tsx:541`
  and `settings/team/page.tsx:411` already fixed on their own list rows.
- **Why** — heading structure is how screen-reader users navigate a page; two competing top-level
  headings for one page is a "Headings and Labels" (SC 2.4.6) problem, and identical accessible
  names on distinct destructive controls is a "Name, Role, Value" one. The repo has already
  decided the right answer twice; this file just missed it.
- **Proposed fix** — delete the `<h1>` at `:141`, keep the description paragraph, add the per-row
  `aria-label` from INT-1's fix.
- **Severity** — major.

### INT-4 · Route is oversized and mixes three unrelated jobs — **minor**

- **file:line** — `integrations/page.tsx`, **878 lines / 40,301 bytes** — the largest file in the
  lane by 13% over `/usage` (788 lines) and more than 2× the lane median (355 lines).
- **What is wrong** — one client component holds the endpoint list, the delivery log with an
  expandable raw-payload viewer, the webhook registration form, the Sheets form and the
  Sheets-unavailable state (`:473, :516, :696, :749`).
- **Proposed fix** — split into an `endpoints/`, `deliveries/` and `forms/` trio of colocated
  components as `agents/` already does (`agents/panels.tsx`, `AgentIdentity.tsx`, `AgentModel.tsx`).
  Behaviour unchanged; the token migration in INT-2 becomes reviewable.
- **Severity** — minor. Do this *with* INT-2, not instead of it.

---

## `/settings/team` — `settings/team/page.tsx` (475 lines)

### TEAM-1 · Role change and member removal both fire unconfirmed — **blocker**

- **file:line** — role `<select>` at `:399-410` mutates directly in `onChange`; "Remove" at
  `:411-422` calls `onRemove()` on a single click and is styled `SECONDARY_BUTTON_SM` — the same
  visual class as a benign action.
- **What is wrong** — on the screen that governs who can sign in to the business:
  - Selecting "Owner" in a dropdown immediately grants a colleague `billing:read` **and**
    `org:manage` — the ability to see the invoice and to remove other members. A dropdown that
    performs an irreversible privilege escalation on change has no "are you sure" moment at all.
  - "Remove" revokes access instantly. The page even reports afterwards how many leads were left
    stranded (`:387-395`) — useful, but that is a *consequence disclosed after the fact* that
    should have been disclosed before it.
  - The page's own comment at `:391-393` says the API refuses self-directed changes "so that a
    mis-click cannot cost somebody their own access." The reasoning is right and is applied to
    exactly one row; a mis-click can still cost *someone else* theirs.
- **Why** — NN/g: consequential and benign options must not sit in the same visual class or the
  same interaction cost ([Dangerous UX: Consequential Options Close to Benign Options](https://www.nngroup.com/articles/proximity-consequential-options/),
  read 25 Aug 2026). GOV.UK's check-answers pattern exists so a user confirms before a transaction
  completes ([Check answers](https://design-system.service.gov.uk/patterns/check-answers/), read
  25 Aug 2026).
- **Proposed fix**
  1. Make the role `<select>` a staged control: change it, then a "Save role" button appears
     beside it naming the change ("Make Priya an owner — they will be able to see your invoice and
     remove people, including you"). The CAS `expectedRole` guard already in place at `:378-384`
     is preserved unchanged.
  2. Route "Remove" through the `aiExtraDialog` pattern, naming the person and stating the
     lead-reassignment consequence **before** the click rather than after; style the confirm
     `DANGER_BUTTON`.
- **Severity** — **blocker**.

### TEAM-2 · The "Invite a colleague" card disappears entirely for non-owners — **minor**

- **file:line** — `:110` gates the whole `<Card>` on `write.allowed`.
- **What is wrong** — a staff member sees no invite affordance at all. `RestrictionNote` at `:108`
  does explain, so this is not silent — but the lane's own better pattern is *disabled control with
  the reason at the control* (`usage/page.tsx:381-418`, `data-rights/page.tsx:335-337`), which
  teaches capability rather than hiding it.
- **Proposed fix** — render the card disabled with the reason inline, matching `/usage`. Same
  argument applies to `do-not-call/page.tsx:283` and `messaging-consent/page.tsx:283`, which hide
  their write cards the same way. Pick one of the two behaviours lane-wide.
- **Severity** — minor, but it is a **one way per problem** violation: the lane currently does both.

---

## `/settings/models` — `settings/models/page.tsx` (346 lines)

### MOD-1 · The model radio group has no visible keyboard focus — **blocker**

- **file:line** — `apps/web/src/components/llmModelPicker.tsx:221-238`. The `<label>` className at
  `:223-229` styles `checked` (`border-brand bg-brand-soft`) and `hover`, but contains **no
  `focus-within:` treatment**; the `<input type="radio">` at `:231-234` is `className="sr-only"`,
  which removes the browser's own focus ring.
- **What is wrong** — a keyboard user tabbing into this group and arrowing between models sees
  **nothing move**. The only visual state is `checked`. For a native radio group, arrowing does
  move the selection, so focus and checked coincide — but the moment the group is disabled or the
  user tabs in without arrowing, there is no indicator at all. I confirmed with a repo-wide grep
  that `focus-within` appears in exactly **one** file (`agents/panels.tsx`), so the codebase knows
  the pattern and these two call sites simply missed it.
- **Why** — WCAG 2.4.7 Focus Visible (Level AA): "any keyboard operable user interface has a mode
  of operation where the keyboard focus indicator is visible"
  ([W3C](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html), read 25 Aug 2026).
  Technique **F78** names this exact failure — styling that renders the visual focus indicator
  non-visible without an author-supplied replacement
  ([W3C F78](https://www.w3.org/TR/WCAG20-TECHS/F78.html), read 25 Aug 2026). This is also why
  axe passing is not evidence: axe cannot evaluate focus indicators, and `a11y.test.tsx` runs in
  jsdom with no layout at all.
- **Proposed fix** — add to the `<label>` className:
  `has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand has-[:focus-visible]:ring-offset-2`
  (or `focus-within:` for wider browser support). Apply the identical change at
  `messaging-consent/page.tsx:677-686` (MC-1) so both custom radio groups gain the ring from one
  decision. Then add a `tests/` assertion that no `sr-only` input exists inside a label whose
  className lacks a focus treatment — a five-line source grep in the spirit of `contrast.test.ts`,
  which is what would keep it fixed.
- **Severity** — **blocker**. Money control, keyboard-invisible, in a gate blind spot.

### MOD-2 · The price is per-minute only; nothing states the monthly impact — **major**

- **file:line** — `settings/models/page.tsx:246-251` ("It adds ₹X to every minute you are charged
  for"); the picker's hint at `:270`.
- **What is wrong** — the screen is scrupulous about the *rate* and says nothing about the
  *bill*. The decision the owner is actually making is "what will this do to my monthly invoice",
  and answering it requires them to know their own minute volume and do the multiplication in
  their head. `/usage` has the volume (`data.minutes_used`) one nav item away.
- **Why** — this is the same argument the file itself makes for showing the rate at all (`:63`:
  "Show a model without its price" is listed as a thing the screen must not do). A per-minute rate
  with no volume anchor is a price a small-business owner cannot evaluate. NN/g's progressive
  disclosure guidance is the right shape: keep the primary answer brief, let the consequence be
  discoverable before commitment ([Progressive Disclosure](https://www.nngroup.com/videos/progressive-disclosure/),
  read 25 Aug 2026).
- **Proposed fix** — beside the selected row, when the surcharge differs from the one in force,
  render a server-computed illustration: "At last month's {minutes_used} minutes this would have
  added about ₹X." **The multiplication must happen server-side** — hard rule 7 forbids the browser
  doing decimal arithmetic on money, and `/usage:238-247` already sets the precedent that a total
  is the server's. If the server cannot supply it, say "your account manager can tell you what this
  means for your monthly bill" rather than inventing a figure.
- **Severity** — major. Consequence is high, confusion is high, and the fix is additive.

### MOD-3 · Save has no confirmation of a bill-increasing change — **minor**

- **file:line** — `:285-293`.
- **What is wrong** — moving from a ₹0 surcharge model to a paid one is one click on "Save model".
  It is reversible (one click back) and takes effect only on the next call (`:298-301`), so this is
  *not* the same class as TEAM-1 — but it is the one action in the lane that raises a recurring
  charge with no acknowledgement.
- **Proposed fix** — when and only when the new surcharge is **higher** than the one in force,
  change the button to a two-step: the confirm dialog states the new per-minute figure and the
  MOD-2 monthly illustration. When the surcharge is equal or lower, save directly — adding friction
  to a cost-*reducing* change would be the inverted-friction defect this audit is otherwise
  complaining about.
- **Severity** — minor. Do it after MOD-2, since it needs the same number.

---

## `/messaging-consent` — `messaging-consent/page.tsx` (688 lines)

### MC-1 🔒 · Consent-answer radios have no visible keyboard focus — **blocker**

- **file:line** — `:665-688`. The `Choice` component's `<label>` className (`:678-682`) has
  `checked` and `hover` states and **no focus treatment**; the input at `:684` is `className="sr-only"`.
  Repo-wide, this and `llmModelPicker.tsx:234` are the only two `sr-only` form inputs.
- **What is wrong** — identical to MOD-1, on the control that decides whether a record says a
  person **agreed** to be messaged or **refused**. A keyboard user cannot see which of the two is
  focused.
- **Why** — WCAG 2.4.7 (AA), technique F78, as cited in MOD-1. Marked 🔒 because it is a consent
  control: the record this radio produces is the client's evidence under TCCCPR if a number is
  challenged (the screen says so at `:490-495`).
- **Proposed fix** — the same `has-[:focus-visible]:ring-2 ring-brand ring-offset-2` as MOD-1.
  Consider replacing the local `Choice` with a shared primitive so there is one radio-card in the
  codebase rather than two that must both be remembered.
- **Severity** — **blocker**, 🔒 compliance-visibility.

### MC-2 · A third private copy of the form-field primitives — **major**

- **file:line** — `messaging-consent/page.tsx:124-127` defines `FIELD_BASE` / `FIELD` /
  `FIELD_ICON`; `do-not-call/page.tsx:152-156` defines the **byte-identical** trio, and the comment
  at `messaging-consent:115-116` admits it ("see the same constants … on the do-not-call screen").
  Meanwhile `components/ui.tsx:394-397` exports `FIELD`, `FIELD_LABEL`, `FIELD_HINT`, which
  `data-rights/page.tsx` and `settings/team/page.tsx` do use. A local `Field` wrapper is then
  defined **three** separate times: `data-rights:784`, `messaging-consent:646`, `usage:455`.
- **What is wrong** — the shared `FIELD` is *shadowed* by a local constant of the same name in two
  files. A future edit to the exported token silently does not reach them; a reader who greps
  `FIELD` finds four definitions. The `Row` component is duplicated the same way, verbatim, between
  `usage/page.tsx:773-788` and `ai-assist/page.tsx:261-276`.
- **Why** — CLAUDE.md's "one way per problem, and migrate rather than accumulate: two ways of doing
  one thing is a defect even when both work, and the second one is where the drift starts." This is
  the textbook case, including the same-name shadowing that makes the drift invisible.
- **Proposed fix** — move `FIELD_ICON` and the touch-target/`min-w-0` refinements **into**
  `components/ui.tsx` beside the existing `FIELD` (they are genuine improvements and belong to
  everyone), delete the two local trios, and promote one `Field` wrapper — `data-rights:784` is
  the best of the three, since it is the only one with the `aria-describedby` hint wiring — into
  `ui.tsx`. Move `Row` there too. Migrate all call sites in the same change.
- **Severity** — major (as a defect class; no user-visible symptom today).

### MC-3 · The recording form is a long linear stack with no summary — **minor**

- **file:line** — `:291-438`.
- **What is wrong** — number, answer, kind-of-no, source, call id, then a variable number of
  evidence fields, then submit. On a phone this is a long scroll and the submit button's blocked
  reason (`:431-436`) sits at the bottom, far from the field that caused it.
- **Why** — GOV.UK's check-answers pattern exists for exactly this shape of multi-fact record
  ([Check answers](https://design-system.service.gov.uk/patterns/check-answers/), read 25 Aug 2026).
- **Proposed fix** — keep the form as-is (its conditional logic is genuinely good — see the
  good-practice list) and add a compact summary line above the submit button restating what is
  about to be written: "Recording: **{number}** agreed to be messaged, evidenced by {source}."
  Do **not** convert this to a wizard; the branching is the value.
- **Severity** — minor.

---

## `/do-not-call` — `do-not-call/page.tsx` (556 lines)

### DNC-1 🔒 · Removing a suppression has no confirmation — **major**

- **file:line** — `:534-546`. One click on "Remove" calls `remove.mutate(entry.id)`.
- **What is wrong** — the consequence is that agents will dial that person again. The screen's own
  header (`:192-196`) says the list "is checked live before every single call, so anything added
  here takes effect straight away" — the same is true of removal, and nothing says so at the
  button. The asymmetry with `/data-rights` is stark: erasing a person's data requires typing
  `ERASE`; putting a person back into the dial pool requires one click.
- **Why** — NN/g on preventing conscious mistakes: irreversible or consequential operations warrant
  confirmation, and the confirmation should describe the *consequence*, not restate the command
  ([Preventing User Errors](https://www.nngroup.com/articles/user-mistakes/), read 25 Aug 2026).
  Under TRAI's TCCCPR regime a wrongly-removed suppression is a call that should not have happened.
- **Proposed fix** — an inline two-step on the row (click "Remove" → the row swaps to
  "Un-suppress {number}? Agents will be able to call them again. [Un-suppress] [Cancel]"), rather
  than a modal — the list is scannable and a modal per row would be heavy. `aria-live="polite"` on
  the swapped row so the change is announced. Keep the existing per-row `aria-label` at `:541`.
- **Severity** — major, 🔒 compliance-visibility.

### DNC-2 · The irreversible "Reason" choice is a bare `<select>` with a detached hint — **major**

- **file:line** — `:306-325`. The `<select id="dnc-source">` at `:310`; the consequence note at
  `:322-324` is a `<span class="text-xs text-ink-faint">` sitting *beside* the select with **no
  `aria-describedby` linking it**.
- **What is wrong** — three of the four options are **permanent** (`SOURCE_OPTIONS` at `:115-136`
  marks `customer_request`, `call_optout` and `regulator` "Permanent"). Picking the wrong one on a
  2,000-number paste creates 2,000 entries that cannot be removed from this screen. Yet:
  - the permanence is communicated only by a faint 12px span the screen reader never associates
    with the control;
  - the note is rendered by a `.find()` on every render rather than being part of the option;
  - there is no confirmation before a bulk write whose reversibility depends on this field.
- **Why** — WCAG 3.3.2 Labels or Instructions and 4.1.2 Name, Role, Value: an instruction that
  changes the meaning of a control must be programmatically associated with it. The
  `data-rights/page.tsx:784-810` `Field` wrapper in this same lane does exactly this correctly and
  its docstring explains why — so the pattern exists and this control does not use it.
- **Proposed fix**
  1. Give the select `aria-describedby="dnc-source-note"` and give the span that id.
  2. Promote permanence to a visible badge on the option row, not a footnote — e.g. render the
     reason as radio cards with "Reversible" / "Permanent" pills, which also removes the `.find()`.
  3. When the chosen reason is permanent **and** `parsed.length > 1`, require confirmation before
     the write, naming the count and the permanence.
- **Severity** — major.

### DNC-3 · Add and Check are two forms doing one job — **minor**

- **file:line** — Check at `:203-281`, Add at `:284-396`.
- **What is wrong** — a client who checks a number, learns it is *not* suppressed, and wants to
  suppress it must retype it into a second field 300px lower.
- **Proposed fix** — when the check verdict is "not suppressed" and the session has write access,
  add a "Suppress this number" action **inside** the verdict box that pre-fills the paste box and
  scrolls to it. Capability unchanged, one retype removed.
- **Severity** — minor. This is a genuine quality-of-life win on the screen people arrive at in a
  hurry.

---

## `/data-rights` — `data-rights/page.tsx` (810 lines)

### DR-1 🔒 · The erasure has a typed confirmation but no "check your answers" — **major**

- **file:line** — `:339-397`. `armed` at `:311` requires `phone.trim().length >= 8 && confirmation === "ERASE"`.
- **What is wrong** — the ceremony is right in *shape* and incomplete in *content*. The user types
  a number and the word ERASE and clicks; at no point are they shown **whose record** is about to
  be destroyed. `minLength={8}` accepts any eight characters, so a transposed digit in a ten-digit
  Indian mobile passes every check on the screen and erases a different real customer, irreversibly.
  The hint at `:360` says "Check it twice" — which is an instruction to the user to do manually the
  thing the screen could do for them.
- **Why** — GOV.UK's check-answers pattern is precisely "let users check their answers before
  submitting … make it clear the transaction will not be complete until a user confirms"
  ([Check answers](https://design-system.service.gov.uk/patterns/check-answers/), read 25 Aug 2026).
  NN/g adds that confirmation copy should let the user "find out more about the consequences of
  their command before they commit" ([Confirmation Dialogs](https://www.nngroup.com/articles/confirmation-dialog/),
  read 25 Aug 2026). A typed keyword confirms *intent*; it does not confirm *target*.
- **Proposed fix** — the mechanism already exists on this very screen. The export card
  (`:229-292`) fetches counts for a number *without disclosing the record*: calls, transcript
  turns, CRM records, consent records. Before arming the erasure, run the same count read and
  render it above the confirmation field: "We hold **12 calls, 340 transcript turns, 1 CRM record**
  for this number. All of it will be erased." Zero counts are equally informative — "we hold
  nothing for this number" is the strongest possible signal that the digits are wrong. This adds a
  target check to an intent check without weakening either, and reuses a read the screen already
  makes. **Do not** replace the typed `ERASE` with this; add it.
- **Severity** — major, 🔒 compliance-visibility. (Not blocker only because the typed confirmation
  does already stop the accidental click; the residual risk is the mistyped digit.)

### DR-2 · Route is oversized — **minor**

- **file:line** — 810 lines / 33,533 bytes, holding the export card, the erasure card, the
  register, the row, the panel, the detail, the certificate and two shared helpers.
- **Proposed fix** — extract `Certificate` (`:668-749`) and the register trio
  (`RegisterCard`/`RegisterRow`/`RequestPanel`, `:432-593`) into colocated components.
  `Fact` (`:764`) and `Field` (`:784`) should go to `ui.tsx` per MC-2.
- **Severity** — minor.

---

## `/settings/alerts` — `settings/alerts/page.tsx` (304 lines)

### ALERT-1 🔒 · Withdrawing consent is styled as destructive; granting it is styled as friendly — **major**

- **file:line** — `GrantControl:249` uses `ActionButton` (the brand-green primary,
  `ui.tsx:408-413`). `WithdrawControl:283-291` uses `DANGER_BUTTON` (`ui.tsx:425`, rose-600).
- **What is wrong** — a direct self-contradiction inside one file. The `WithdrawControl` docstring
  at `:264-268` states the principle correctly: *"consent that can be given more easily than it can
  be taken back is not consent."* The code then makes withdrawal the only red button on the screen,
  while the same component's own body text (`:292-295`) confirms the action is **fully reversible**
  ("You can turn WhatsApp back on here whenever you like"). And `DANGER_BUTTON`'s own docstring
  (`ui.tsx:419-424`) reserves it for "something a person cannot undo" — so this use also violates
  the constant's stated contract.
- **Why** — red is a deterrent signal. Applying it to a privacy-protective, reversible action makes
  the safe choice look dangerous, which is the inverse of NN/g's guidance that visual signals should
  differentiate consequential from benign actions in proportion to their consequence
  ([Dangerous UX](https://www.nngroup.com/articles/proximity-consequential-options/), read 25 Aug 2026).
- **Proposed fix** — change `WithdrawControl` to `SECONDARY_BUTTON` (`ui.tsx:416`). Grant and
  withdraw then sit in the same weight class, which is exactly what the docstring asks for. Free
  `DANGER_BUTTON` for the erasure and the endpoint deletion, where it belongs.
- **Severity** — major, 🔒 compliance-visibility. **Never make withdrawal harder or more visually
  discouraged than grant in any redesign.**

### ALERT-2 · Otherwise exemplary — no other findings

The three-way separation of *consent* / *channel availability* / *permission* (`:133-146`,
`:150-185`) and the server-supplied notice text with a version handshake (`:167`, `:179-182`) are
the best consent implementation in the lane. See the good-practice list.

---

## `/usage` — `usage/page.tsx` (788 lines)

### USG-1 · Four money surfaces are split across four nav entries — **major** (see also NAV-1)

- **file:line** — `usage/page.tsx` (this month's charge + cap + wallet), `spend/page.tsx` (per-agent
  and per-call attribution), `invoice/page.tsx` (the statement), `ai-assist/page.tsx` (the console
  AI wallet). All four are nav siblings under "Settings & account" (`layout.tsx:121, 128, 134, 135`).
- **What is wrong** — the *split itself is well-argued* (the nav comments at `:122-133` make a good
  case, and I agree with keeping four screens). The defect is that they are not **grouped or
  cross-linked as a set**. `/usage` links out to `/settings/models` (`:262-267`) but not to
  `/spend` or `/invoice`; `/spend` links to agents and calls but not to `/usage` or `/invoice`;
  `/invoice` links nowhere. A client asking "what do I owe and why" has to know all four names.
- **Why** — Hick's law is the wrong lens here (nine items is not overload); the right lens is
  information scent. Four screens answering one question with no scent between them is a wayfinding
  gap. Grouping is the cheap fix and costs no capability.
- **Proposed fix**
  1. Give the four their own nav group heading — **"Billing"** — in `layout.tsx:105-138`, leaving
     Team / Alerts / AI model / Integrations / Verification under "Settings & account". This
     reduces the largest group from 9 to 5 and 4.
  2. Add a small consistent cross-link row at the top of each of the four: *Usage · Spend · AI help
     · Invoice*, with the current one inert. Reuse `components/interior/tabs.tsx` rather than
     hand-rolling.
- **Severity** — major, as an IA defect. Nothing is hidden; it is just hard to assemble.

### USG-2 · Two independent "spending limit" concepts on one screen — **minor**

- **file:line** — `SpendLimit` (`:336-443`) writes the client's own cap; the `data.capped` banner
  (`:115-125`) and the "Calling credit" card (`:284-299`) each describe a *different* mechanism
  that stops outbound calls.
- **What is wrong** — three separate stop-outbound mechanisms (client cap, plan cap, wallet
  exhaustion) are explained in three places on one scroll, each with its own "incoming calls are
  unaffected" reassurance (`:118-123`, `:291`, `:360-362`). The reassurance is correct and welcome;
  saying it three times in three wordings makes a reader wonder whether they are three different
  facts.
- **Proposed fix** — one "What can stop your outgoing calls" panel listing the three causes and the
  current state of each, with "incoming calls are never affected" said **once**, prominently, at
  the top of it. No capability removed; the `SpendLimit` form stays exactly where it is.
- **Severity** — minor.

### USG-3 · Route is oversized — **minor**

- 788 lines / 35,100 bytes holding the usage panel, the spend-limit form, the top-up flow and the
  credit-pack table. Extract `SpendLimit` (`:336`), `TopUp` (`:523`) and `PacksTable` (`:675`) into
  colocated components. Severity: minor.

---

## `/spend` — `spend/page.tsx` (355 lines)

### SPD-1 · The month picker is an unlabelled-by-sight native `<input type="month">` — **minor**

- **file:line** — `:113-119` (also `invoice/page.tsx:69-75`).
- **What is wrong** — `aria-label="Billing month"` is present, so screen readers are fine, but
  there is **no visible label**. The control's purpose is inferable only from its rendered value,
  and native month inputs render very differently across browsers (Firefox desktop has no picker
  UI at all). On a screen whose entire meaning depends on which month is selected, that is a
  meaningful ambiguity.
- **Why** — WCAG 3.3.2 Labels or Instructions; and `data-rights/page.tsx:773-783`'s own docstring
  argues this exact point about persistent visible labels ("a placeholder 'label' passes the gate
  and still disappears").
- **Proposed fix** — add a visible `<label>Billing month</label>` above or beside it in both files,
  and drop the now-redundant `aria-label`. Consider whether Aug 2026 (a live month) should say
  "this month so far" beside it, since a mid-month figure is not a final one.
- **Severity** — minor.

### SPD-2 · Otherwise excellent — the `Residual` panel is a model to copy

`Residual` (`:278-295`) explains *why the rows do not add up to the total* and renders only when
the server says there is something to explain. This is the single best money-honesty pattern in
the repo. See the good-practice list.

---

## `/invoice` — `invoice/page.tsx` (100 lines)

### INV-1 · The screen's only outbound affordance is `window.print()` — **minor**

- **file:line** — `:76-86`.
- **What is wrong** — the invoice is a document a client's accountant needs as a **file**. "Print"
  reaches PDF only via the browser's print-to-PDF, which on Android Chrome is several taps deep and
  on some Indian budget browsers is absent. There is no "Download PDF" and no email-to-me.
- **Proposed fix** — I could not verify from this lane whether a server-side PDF exists; the client
  hook is `useClientInvoice` returning structured data rendered by `components/invoiceDocument.tsx`.
  **UNKNOWN — I have not verified whether the API can emit a PDF.** If it can, add a Download
  control. If it cannot, that is an API task, and the honest interim is to label the button
  "Print or save as PDF", which at least names the outcome the user wants.
- **Severity** — minor.

### INV-2 · Good: `disabled={!data}` on Print — worth copying

`:80` disables printing until a statement exists, with the comment "printing a skeleton or an error
box produces a sheet of paper that looks like an invoice and is not one." Exactly right.

---

## `/ai-assist` — `ai-assist/page.tsx` (276 lines)

### AI-1 · The ceiling is only visible *after* it is hit — **major**

- **file:line** — `StateNotice` (`:163-193`) returns `null` for the normal state; the only banners
  are `platform_paused`, `exhausted` and `ceiling_reached`.
- **What is wrong** — the module docstring at `:29-31` states the screen's purpose: *"this screen
  exists to make the ceiling visible BEFORE it is reached."* It does not currently do that. In the
  normal state the client sees three tiles and a billing explainer; there is no "you are at 85% of
  this month's allowance" signal, here or anywhere else in the console. The first notice a user
  gets is `ceiling_reached` — i.e. AI help has already stopped.
- **Why** — this is the file's own stated goal, unmet. NN/g's error-prevention framing applies:
  the cheapest intervention is the one that happens before the wall, not at it.
- **Proposed fix** — add a fourth `StateNotice` arm for an approaching ceiling. The threshold must
  come from the **server** (a `state` value, e.g. `"approaching"`), not from a browser comparison
  of two rupee strings — `/usage:314` and this file's own `:39-41` both establish that the browser
  does not do decimal arithmetic on money. If the API cannot yet supply it, that is a one-field API
  change, not a reason to compute it here. Additionally, surface the approaching state where AI
  help is *used* (the call-detail assist card), not only on this screen — a client who never opens
  `/ai-assist` never sees it at all.
- **Severity** — major.

### AI-2 · `Row` is duplicated verbatim from `/usage` — **minor**

- **file:line** — `ai-assist/page.tsx:261-276` and `usage/page.tsx:773-788` are identical. See MC-2
  for the consolidated fix.
- **Severity** — minor.

---

## `/verification` — `verification/page.tsx` (680 lines)

### VER-1 🔒 · Filed under "Settings & account", not "Compliance & data" — **major**

- **file:line** — `layout.tsx:136` places it in the settings group; `:95-104` is the "Compliance &
  data" group it is not in.
- **What is wrong** — this is the screen a client reaches when `check_dispatch` has refused their
  outbound calling with `kyc_missing` / `kyc_not_verified`, and it covers **two statutory
  obligations** (subscriber verification under the Telecom Act 2023, and DLT PE registration). Its
  own opening sentence (`:100-105`) says "Indian telecom rules require two separate things of a
  business before it may place calls." That is a compliance screen by any reading, sitting eight
  items down a nine-item settings list.
- **Compounding** — `layout.tsx:85` gives `/quality` the `ShieldCheck` icon and `:136` gives
  `/verification` **the same `ShieldCheck` icon**. Two nav entries with one glyph defeats the
  icon's purpose, and the duplicate is between the two most compliance-shaped labels in the list.
- **Proposed fix** — move `/verification` into the "Compliance & data" group, and change its icon
  to something distinct (`BadgeCheck` or `FileBadge`; `BadgeCheck` is already imported in this lane
  at `messaging-consent:4` so it is in the icon set). This makes it *more* visible, which is the
  only permitted direction for a 🔒 finding.
- **Severity** — major, 🔒 compliance-visibility.

### VER-2 · Route is oversized — **minor**

680 lines / 29,974 bytes covering two independent verification regimes. Split
`SubscriberVerification` and `DltRegistration` into colocated components — they already take
`session` and share nothing, so the split is mechanical. Severity: minor.

---

## `/caller-notice` — `caller-notice/page.tsx` (294 lines)

### CN-1 · Duplicate `<h1>` — **minor**

- **file:line** — `:74` renders `<h1>Your privacy notice</h1>`; `layout.tsx:102` already names the
  nav entry "Your privacy notice" and `layout.tsx:331` renders it as the page title. This and
  `/integrations` are the only two survivors of the heading migration.
- **Proposed fix** — delete the `<h1>` and keep the `<p>` at `:75-80`, matching every other file in
  the lane.
- **Severity** — minor.

### CN-2 · The copy button's failure is silent — **minor**

- **file:line** — `:260-265`. `navigator.clipboard?.writeText(...).then(...).catch(() => setCopied(false))`.
- **What is wrong** — when the clipboard API is absent (insecure context) or the write is rejected,
  the button simply does nothing: `copied` stays `false` and the label stays "Copy". The user
  clicks, sees no change, and cannot tell whether it worked. The comment at `:258-259` correctly
  identifies the fallback ("the textarea below … the text is selectable") but the *user* is never
  told that.
- **Why** — CLAUDE.md: "Errors are part of the interface. Every failure path a user can reach has a
  message they can act on." A no-op click is the specific case of swallowing a failure to make a
  path look green.
- **Proposed fix** — on failure set a `failed` state and render "Could not copy — select the text
  below and copy it yourself" in an `aria-live="polite"` region. `components/interior/toaster.tsx`
  is already available in the client realm layout and is the lane's existing mechanism.
- **Severity** — minor. (Small, but it is a one-line fix on a legal document a client is trying to
  publish.)

### CN-3 · Good: the draft warning travels with the text

`:99-106` renders the server's disclaimer above the document **and** it is inside the markdown that
gets copied, "because a warning that lives only in the envelope stops travelling the moment the
text is pasted into a website." That is a genuinely sophisticated compliance-UX decision and should
be copied wherever this product emits a document.

---

## Navigation (`layout.tsx`) — affects the whole lane

### NAV-1 · "Settings & account" carries nine items across four unrelated intents — **major**

- **file:line** — `layout.tsx:105-138`.
- **What is wrong** — Team (people), Alerts (consent), AI model (money + behaviour), Integrations
  (data plumbing), Usage / Spend / AI help / Invoice (money), Verification (legal status). Four of
  the nine are billing; one is a statutory obligation.
- **Why** — Hick's law is a weak argument at n=9 and I am not going to overstate it. The real
  argument is that the group **heading is a promise the contents do not keep**: a user looking for
  their invoice does not look under "Settings", and a user looking for a setting has to scan past
  four money screens. Grouping by user intent rather than by "everything that isn't operational" is
  the standard IA move.
- **Proposed fix** — three groups where there is now one:
  - **Billing** — Usage, Spend, AI help, Invoice
  - **Settings** — Team, Alerts, AI model, Integrations
  - move **Verification** into "Compliance & data" (VER-1)
  Nothing is hidden, nothing is nested, no click is added. This is the cheapest high-value change
  in the audit.
- **Severity** — major.

### NAV-2 🔒 · Compliance obligations are split across two groups — **major**

- Covered as VER-1. Recorded here too so a nav redesign sees it: **"Compliance & data" must remain
  a visible top-level group with no collapse-by-default behaviour.** Five statutory surfaces live
  in it (`layout.tsx:95-104`) plus Verification once moved. 🔒

### NAV-3 · `ShieldCheck` is used for two different nav entries — **minor**

- `layout.tsx:85` (`/quality`) and `:136` (`/verification`). Covered in VER-1's fix.

---

# What is genuinely good — copy these to other lanes

These are not padding. Several are better than what most commercial SaaS ships, and the other audit
lanes should adopt them rather than invent alternatives.

1. **§52: loading is a skeleton, failure is a refusal, and neither is a zero.** Applied without
   exception across the lane. The strongest statements of it:
   - `spend/page.tsx:124-126` — *"'You spent nothing this month' is a claim about a month's
     business, and a 503 is not evidence for it."*
   - `settings/team/page.tsx:51-56` — the empty state is a **security claim**, so it is reachable
     only through a list the server actually sent.
   - `data-rights/page.tsx:422-431` — a failed read of the erasure register renders the refusal and
     **nothing that could be read as a register**, because "this account has been asked to erase
     nobody" is a sentence a client might repeat to a regulator.
   - `do-not-call/page.tsx:426-430`, `alerts:87-89`, `integrations:232-238`.
   **This should be the house rule for every screen in the product.**

2. **`.data`, never `.data ?? []`.** `do-not-call:184-185` and `settings/team:94-95` both call this
   out explicitly: the `??` is what erases the difference between "the server said none" and "the
   server did not answer." Cheap, invisible, and the foundation of point 1.

3. **Money is a decimal string from the wire to the DOM, and the browser never does arithmetic on
   it.** `usage:41-54` (including the correct distinction between `formatINR` for amounts and
   `formatRupeeRate` for rates — rounding ₹7.1250/min to ₹7.12 would break `qty × unit = amount` on
   an invoice); `spend:56-60`; `usage:236-247` uses the **server's** total rather than summing three
   rows in the browser, explicitly to keep "what this costs me" and "what we earn" from disagreeing.

4. **`Residual` — explaining why the parts do not sum.** `spend/page.tsx:270-295`. Renders only when
   the server says there is something to explain, states both figures and the difference, and falls
   back to the raw reason code so a client can quote it. Best money-honesty pattern in the repo.

5. **Server-supplied consent notice text with a version handshake.** `alerts:35-41, 167, 179-182` —
   the wording shown is the wording sent back, so a cached build agreeing to last quarter's text is
   *refused* rather than recorded. *"A `notice_version` in a database row is only evidence if the
   wording it names can be reproduced years later, and a string that lives in a React component
   cannot be."* This is the correct architecture for any versioned legal text.

6. **The disclaimer travels with the copied document.** `caller-notice:99-106` (CN-3).

7. **Counts without disclosure.** `data-rights:243-259` renders the subject-export **counts** so a
   client can check they have the right person, and deliberately never renders the document —
   *"the fewer copies of it exist, the better."* `do-not-call:364-393` reports totals, not which
   number went where, because "a list of who asked us to stop calling them is itself personal data."

8. **The number is never in a URL.** `do-not-call:61-64`, `messaging-consent:186-192`,
   `data-rights:70-74` — checks are POSTs with the number in the body, and export filenames are
   dated, never named for the subject. Hard rule 6, enforced at the UI layer, with the reasoning
   recorded.

9. **Per-row accessible names on repeated destructive controls.** `do-not-call:538-541` and
   `settings/team:409-411, 458` — *"forty buttons called 'Remove' are forty identical announcements
   to a screen reader."* (`/integrations` is the one place this was missed — INT-3.)

10. **Refusals rendered where the control is, distinguishing "you may not" from "we could not find
    out."** `useWriteAccess` + `RestrictionNote` throughout, and `integrations:304` is the subtlest
    use: the explanation renders **only** when the uncertainty is ours, because a genuine permission
    refusal already has its own affordance.

11. **`lookup()` instead of bracket-indexing a wire string.** `messaging-consent:581-592` records an
    actual production crash: a `source` of `"constructor"` walked the prototype chain, returned
    `Object`, and `.label.toLowerCase()` blanked the entire verdict box. Every copy-table read in the
    lane now goes through `lookup()`. **Every lane should adopt this.**

12. **Verdicts come from the server's predicate, never re-derived.** `messageable` on
    `/messaging-consent`, `is_verified` on `/verification`, `state` on `/ai-assist`, `removable` on
    `/do-not-call:528-531`. Each file states the same reason: two implementations of one rule drift,
    and the direction this one drifts in is a Remove button on a consumer opt-out.

13. **The form's shape follows the law's shape.** `messaging-consent:52-65` — the answer is asked
    *first* because it determines which sources may carry it; evidence fields change with the
    source; there is no "assumed" or "implied" option and none is reachable by leaving fields blank.
    This is domain modelling done in the UI, and it is very good.

14. **Capabilities that do not exist are stated, not offered.** `usage:488-521` (no checkout, so no
    pay button — *"a client believes they have paid, keeps not being able to dial, and calls support
    about a payment that was never taken"*), `verification:56-61` (no purchase form), `alerts:42-47`
    (no opt-in while the channel cannot deliver). Consistently applied and consistently explained.

---

## Suggested order of work

1. **INT-1 + INT-2 + INT-3** together — one file, three findings, two of them blockers.
2. **MOD-1 + MC-1** together — one CSS pattern, both blockers, plus the source-grep test that keeps
   it fixed.
3. **TEAM-1** — confirmation on role change and removal.
4. **NAV-1 + VER-1** together — one file, both nav findings, and VER-1 is 🔒.
5. **DNC-1, DNC-2, DR-1** — the confirmation-parity set.
6. **ALERT-1** — a one-constant change with a real compliance meaning.
7. **AI-1** — needs a server field; start the API side now.
8. **MC-2** — the primitive consolidation. Do it last: it touches many files and blocks nothing.

## What I could not verify

- **INV-1** — whether the API can emit a server-rendered PDF invoice. UNKNOWN; I did not read the
  billing routes this session and will not guess.
- **Rendered contrast on `/integrations`** — the two ratios quoted in INT-2 are REPO-MEASURED
  values from `globals.css:39,88` for the hex codes `#94a3b8` and `#64748b`. Tailwind's `slate-400`
  and `slate-500` are those hex codes in current Tailwind, but I did not run a browser to measure
  the rendered page. The remedy (use the tokens) is correct either way.
- **Whether any of these screens has been usability-tested with a real client.** Nothing in the tree
  indicates so. Everything above is expert review, not observed behaviour.
