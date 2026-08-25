# UX-DOCTRINE.md — how a Calevate screen is built

**Status: binding, not advisory.** This is to `apps/web` what `docs/BACKEND-PATTERNS.md`
is to `apps/api`. A screen that departs from a numbered rule below needs a decision-log
entry saying what the departure buys, in the same change.

**Who we are building for.** A small-business owner in India — a clinic, a coaching
centre, a builder's office — on a mid-range Android phone, in Telugu or Hindi or English,
with no training, no onboarding call and no patience for a tour. They open a screen with
one thing in mind and they are paying for the minutes while they look for it. That is the
same user profile GOV.UK designs for (high stakes, low training, get it done and leave),
which is why GOV.UK is the house reference below and not a SaaS dashboard.

**The founder's brief, in one line: _maximum control, minimum complexity._** §9 says what
that does and does not license. It is not a licence to delete features.

---

## §0 The evidence this rests on

Every rule below either cites a primary source read on **25 August 2026**, or is a
repo-internal convention and says so. Per CLAUDE.md hard rule 11, sources are named at the
point of use so the next reader inherits the evidence rather than the conclusion, and
anything I could not read at source is marked.

Read at source this session:

- **GOV.UK Design System**, component guidance, from the authoring repository
  `github.com/alphagov/govuk-design-system` (`main`): `src/components/details/index.md`,
  `src/components/accordion/index.md`, `src/components/tabs/index.md`,
  `src/components/button/index.md`, `src/components/task-list/index.md`,
  `src/components/summary-list/index.md`.
- **W3C WCAG 2.2 Understanding documents**, from `github.com/w3c/wcag` (`main`):
  `understanding/22/target-size-minimum.html`, `understanding/20/headings-and-labels.html`,
  `understanding/20/info-and-relationships.html`.

**Could not be read at source — EGRESS-BLOCKED from this session, and labelled everywhere
they are used:** `www.nngroup.com`, `design-system.service.gov.uk` (the published form of
the GOV.UK guidance above — the repository was read instead), `www.w3.org` (likewise),
`m3.material.io`, `m1.material.io`, `developer.mozilla.org`,
`www.interaction-design.org`. Where a claim from one of those matters below it is marked
**REPORTED (search reading, 25 Aug 2026)** and no rule depends on it alone.

The cognitive-psychology results everyone quotes are cited by their papers, not by a
design blog: **Hick (1952), "On the rate of gain of information", Quarterly Journal of
Experimental Psychology** — choice reaction time grows *logarithmically* with the number of
equally likely alternatives; and **Miller (1956), "The Magical Number Seven, Plus or Minus
Two"**. Both are REPORTED here (search reading, 25 Aug 2026); the full texts were not
fetched. Two consequences we actually rely on, and one trap:

- Hick's law is about **choosing among alternatives**, so it bites on menus, pickers and
  rows of equally-weighted panels — exactly the defect §1 exists to prevent. It says
  nothing about the cost of scrolling past something already ruled out, which is why our
  answer is **hierarchy**, not deletion.
- Miller is about **immediate memory**, not about how many things may appear on a page.
  Later work put the practical limit lower still (Cowan, 2001 — four chunks; REPORTED).
- **Do not use "7±2" to justify a limit.** No rule here caps a section at seven of
  anything. Where a number appears below it is a size budget with a measured cause, not a
  psychology citation.

---

## §1 The hierarchy rule — every screen has ONE primary job

**Name the job in one sentence before writing any markup.** Not "the agent detail page" —
*"write what this agent says."* If you cannot name it, the screen is two screens.

**Primacy is expressed on four channels, and the primary surface is the only thing allowed
to use more than one:**

| Channel | How it reads | Rule |
|---|---|---|
| **Position** | First block under the page header | The primary surface is never below the fold on a 360px phone |
| **Size** | Hero heading + `PRIMARY_BUTTON_LG` | Exactly one `PRIMARY_BUTTON_LG` per screen |
| **Weight** | `border-2 border-brand` | Every other panel keeps the 1px `--line` border |
| **Colour** | The brand medallion and the one brand-strong call to action | Never `bg-brand` + `text-white` (3.38:1 — `tests/contrast.test.ts`) |

**What must NOT compete with it:**

- No second hero. No second `PRIMARY_BUTTON_LG`.
- No panel above it except the page header (identity + state), which is prose and facts,
  not a control cluster.
- No brand-bordered or brand-filled panel anywhere else on the screen.
- Nothing that is merely *urgent* (a warning banner, a pending-changes notice) may be
  styled larger than the primary surface. Urgency is a tone, not a rank.

**The defect this replaces, stated so it is recognisable:** `/c/[slug]/agents/[agentId]`
was nine `Card`s of equal size, equal border, equal heading weight, in DOM order. The
script — the product — was a small text link inside the fifth. *Everything equal means
nothing primary*, and the most-edited control in the product was the hardest to find.

### Kill the "everything is a Card" default

A `Card` is **a container for a panel: a bounded job with its own controls and its own
outcome.** It is not the default wrapper for content.

**Use a `Card` when** the block is a self-contained job (a form that saves, a list with
actions, a verdict with a next step) *and* it needs a heading in the page's heading
outline.

**Use a plain `<section>` — no card — when:**

- it is the page's own header or identity (that is what the page IS, not a panel on it);
- it is prose, a single fact, or a `<dl>` of facts with no controls;
- it is one item in a homogeneous list. Material's own guidance makes this call: a card's
  chrome surrounds the data and makes a reader jump box-to-box instead of scanning down a
  list. **REPORTED (search reading of Material's cards guidance, 25 Aug 2026 —
  `m3.material.io` / `m1.material.io` are egress-blocked here).** The repo-internal
  evidence is stronger and is enough on its own: `Roster.tsx` renders agents as
  `<li>` rows inside **one** card, and it reads as a status board; the same data as one
  card per agent read as a document, which is why it was changed.

**Never nest a `Card` inside a `Card`.** If a panel needs internal structure, use
`SectionHeading` (an `h3` — see §2).

---

## §2 Heading structure is real structure, not typography

The levels are fixed by the PRIMITIVE, not chosen per call site:

- `<h1>` — what this screen is about, and **at most one**. A screen whose subject is
  already named by the shell's navigation does not add one (`/c/<slug>/agents` is "Agents"
  in the sidebar, and `agents.test.tsx` pins that it prints no `h1` of its own — a second
  heading there is a visible duplicate and the copy that drifts when the nav is renamed).
  A screen about ONE named thing does add one: the agent's name, the campaign's name.
- `<h2>` — `Card title`, and `Disclosure title` (which renders a real `h2` inside its
  `<summary>`, so a disclosed panel is in the heading list rather than reachable only by
  tabbing). A disclosure is a PEER of a card, never nested inside one.
- `<h3>` — `SectionHeading`, a block within a panel.

Never skip a level, and never express a heading with a styled `<span>`.

This is WCAG 2.2 **1.3.1 Info and Relationships (Level A)** — "information and
relationships that are implied by visual or auditory formatting are preserved when the
presentation format changes" — and **2.4.6 Headings and Labels (Level AA)** — "when
headings are clear and descriptive, users can find the information they seek more easily"
(w3c/wcag `understanding/20/`, read 25 Aug 2026). `tests/a11y.test.tsx` runs axe's
`heading-order` on every swept screen, so this one is enforced.

**Write headings as the user's question, not as our schema.** "What it says on a call",
not "Prompt configuration". "What callers hear right now", not "Publishing state". The
label is what makes a scan work.

---

## §3 Progressive disclosure — the decision test

Three places a thing can live. Decide with **frequency × consequence**, and write the
answer down in the component's doc comment.

| | **Low consequence** | **High consequence** |
|---|---|---|
| **Touched often** | Foreground | **PRIMARY** — hero, and usually its own route |
| **Touched rarely** | **Disclosed** — `<Disclosure>`, closed | Foreground, or its own route with a confirm step |

Read the table's one asymmetry out loud: **high consequence never discloses.** Rarity buys
a click only when getting it wrong is cheap. A control that stops a client's phone line, or
one that carries a legal obligation, stays visible however seldom it is used.

**Its own route** when the thing has its own unsaved state, its own save/apply ladder, or
enough controls to be a screen (the script builder, campaign creation, an invoice).
GOV.UK's advice when a page has too much on it is to "simplify and reduce the amount of
content" or "split the content across multiple pages" *before* reaching for a device that
hides it (`src/components/tabs/index.md`, read 25 Aug 2026). Splitting beats hiding.

**What may never be disclosed** (this is §8 and it is absolute): a compliance control or
the sentence that qualifies it; the screen's primary job; anything a first-time owner must
find without being told it exists; an error, refusal or `ProblemNotice`.

**How to disclose.** `<Disclosure>` (`components/ui.tsx`) — a native `<details>/<summary>`.
It is keyboard-operable, announces its own state, needs no focus management, and survives a
JS failure. It is **the one disclosure mechanism in this console**; do not hand-roll a
second (CLAUDE.md: one way per problem).

**A disclosure must advertise what is inside it.** Always pass `subtitle`, and make it a
fact, not a tease: *"Currently gpt-4o-mini. Changing it changes what a minute of this
agent's calls costs you."* GOV.UK's own research on the Details component records "evidence
that some users avoid clicking the link to show more details" (`src/components/details/index.md`,
read 25 Aug 2026). The closed state carries the FACT; the click buys the CONTROL.

**Tabs and accordions: not without a decision-log entry.** GOV.UK's guidance is that both
"hide content from users and not everyone will notice them or understand how they work",
and that tabs must not be used "as a form of page navigation" or where users "read through
all of the content in order" (`src/components/tabs/index.md`, `src/components/accordion/index.md`,
read 25 Aug 2026). A workspace where an owner scans down to see the state of one agent is
the read-in-order case. Use `<Disclosure>` on a section, or split the route.

---

## §4 Action hierarchy

- **One HERO action per screen** — `PRIMARY_BUTTON_LG`, in the primary surface. This is
  the GOV.UK rule: "Avoid using multiple default buttons on a single page. Having more than
  one main call to action reduces their impact, and makes it harder for users to know what
  to do next" (`src/components/button/index.md`, read 25 Aug 2026).
- **Section actions are `PRIMARY_BUTTON`, and every one is bound to a form it submits, and
  sits inside that form.** A workspace legitimately has several forms (save the identity,
  save the variables, submit a fact); a GOV.UK page usually has one, and we say plainly
  that we are departing: our screens are workspaces, not one-thing-per-page flows. The
  discipline that makes it safe is the binding — a primary button that is not a form's
  submit is a hero, and there is only one of those.
- **A section action never appears above the hero.**
- **`SECONDARY_BUTTON` for everything else.** GOV.UK again: "Pages with too many calls to
  action make it hard for users to know what to do next" (same file, same date).
- **Destructive and irreversible: `DANGER_BUTTON`, and never adjacent to the hero.** Rose,
  never brand — "an operator's eye should refuse to find it there" (`components/ui.tsx`).
  GOV.UK's warning-button rule is the same: "Only use warning buttons for actions with
  serious destructive consequences that cannot be easily undone" and "they only work if
  used very sparingly" (same file, same date).
- **Consequences go ABOVE the control, not in a modal after it.** State what will happen,
  then offer the button whose label is the consequence ("Archive this agent", not "OK").
  `AgentLifecycle` is the worked example, and the ceremony scales to the blast radius: a
  campaign launch asks you to type a word, archiving restates four consequences, switching
  off does neither.
- **A control that would 403 is not rendered disabled and silent.** Use `useWriteAccess`
  and put the reason on the control (`title`) *and* on the screen (`RestrictionNote`). "A
  button that would 403 is worse than no button at all."
- **One target per row.** A list row that is a link is a link *once*; no nested anchors, no
  20px "Open" chevron competing with the row.

---

## §5 Task-oriented information architecture

**Group by what the owner is trying to do, never by API resource.** The server's nouns
(`agents`, `pending`, `kb_sources`, `action_tools`, `llm_model`) are our schema, not their
mental model.

The bands the agent workspace uses, in order, are the template:

1. **"Is it working, and what is it?"** — page header: identity, live state, the two facts
   that differ (our status vs. the engine's).
2. **"Get it saying the right thing"** — the primary surface.
3. **"What is it doing right now / what did it do"** — live state, staged changes, what it
   could not answer.
4. **"Things I set once"** — disclosed.

**Two spellings of one fact is a defect even when both are true.** If a value appears
twice, one of them is the source and the other must be deleted, not kept in sync.

**Copy is part of the IA.** Plain language, the owner's words. A technical or legal term
(DLT, PE/TM, DND, DPDP, 140/160-series) appears only inside `<TermGloss>`, which explains it
in place on hover, keyboard focus and tap.

---

## §6 Size budget — a big file is a hierarchy nobody could see

These are smells with named remedies, not style points. A file this size is one nobody
reads before editing, which is how nine equal cards accumulate.

| Thing | Budget | Remedy when it is exceeded |
|---|---|---|
| A route module (`app/**/page.tsx`) | **150 lines** | It may export only `default` (D-196), so it cannot be split by extraction — move the screen into a sibling component and keep the route thin |
| Any other component module | **400 lines** | Extract by SUBJECT (not by "top half / bottom half"), split the route, or disclose |
| One component function | **~120 lines of JSX** | It is doing two jobs; name the second one |
| A shared-primitive catalogue (`components/ui.tsx`) | bounded by cohesion, not lines | A primitive over ~120 lines gets its own file under `components/interior/` — the convention this repo already follows |

**Extract by subject.** `panels.tsx` was 46KB because four unrelated subjects shared a
filename. It is now `panels/publishing.tsx`, `panels/openingNotices.tsx`,
`panels/extraction.tsx` (+ `extractionRow.tsx`, + the React-free `extractionDraft.ts`) and
`panels/training.tsx`. `Actions.tsx` was 28KB and is now `actions/` with one subject per
file and a React-free `params.ts`. `ScriptBuilder.tsx` was 737 lines and is now the
save/apply shell plus `ScriptSections.tsx` and `AssistPanel.tsx`.

**A route module keeps the chrome and hands off.** `[agentId]/page.tsx` (43 lines) unwraps
its params, renders the back link and mounts `AgentWorkspace`; `agents/new/page.tsx` (35)
mounts `BuildAgent`; `agents/page.tsx` (95) mounts `Roster`, `Archive` and the disclosed
`LaneGuide`. That is what the 150-line budget is for — it is not achievable by writing
smaller JSX, only by moving the screen out of the route.

**Pull the arithmetic out of the JSX.** Key derivation, dirty comparison, validation and
wire mapping belong in a plain `.ts` module beside the component. It halves the component
and it is the half a test can drive without a render.

---

## §7 Consistency contract

**Reuse these. Do not hand-roll an equivalent.**

`components/ui.tsx` — `Card`, `SectionHeading`, `Fact`, `Disclosure`, `ToggleSwitch`,
`StatTile`, `Avatar`, `StatusBadge`, `MonoValue`, `TermGloss`, `ProblemNotice`,
`RestrictionNote`, `NoticeBox`, `NOTICE_TONES`, `ScrollRegion`, `SkipLink`,
`MAIN_CONTENT_ID`, `EmptyState`, `Skeleton`, `FilterChip`; the class constants `FIELD`,
`FIELD_LABEL`, `FIELD_HINT`, `PRIMARY_BUTTON_LG`, `PRIMARY_BUTTON`, `PRIMARY_BUTTON_SM`,
`SECONDARY_BUTTON`, `SECONDARY_BUTTON_SM`, `DANGER_BUTTON`; and the formatters
`formatINR`, `formatRupeeRate`, `formatIST`, `formatISTInput`, `istInputToInstant`,
`formatDuration`, `formatCallCap`, `formatCount`.

`components/interior/**` — the behavioural primitives, each with a headless hook and a
rendered component: `Tabs`, `Dropdown`, `Pagination`, `LoadMore`, `ShowMore`,
`CollapsibleBanner`, `StickyHeader`, `WizardSteps`, `TaskSteps`, `TreeView`, `OtpInput`,
`FloatingLabelInput`, `LoadingButton`, `ProgressBar`, `SkeletonSwap`, `StreamingText`,
`LiveActivity`, `NewItemsPill`, `ToastProvider`/`useToast`.

Also shared, and equally binding: `components/llmModelPicker.tsx` for any model choice,
`components/deployButton.tsx`, `components/actionButton.tsx`, `components/navDrawer.tsx`,
`lib/lookup.ts` (`lookup`/`hasKey`) for **every** map keyed by a wire string.

**The rule:** a new primitive is added to `components/ui.tsx` (small) or
`components/interior/` (behavioural) — **never duplicated per route**. If a route needs a
variant, add the prop there; if two routes have written the same thing twice, hoist it and
**move both callers in the same change**. Two ways of doing one thing is a defect even
when both work (CLAUDE.md), and the second one is where the drift starts.

Worked example, from this change: the 400-character `peer-checked:` switch expression was
written out three times and had already diverged — two copies disabled the track while a
request was in flight and the third did not, so a switch mid-write looked live. It is now
`ToggleSwitch`, and all three callers moved onto it.

---

## §8 Accessibility floor — non-negotiable, and already gated

These are not aspirations; `apps/web/tests/a11y.test.tsx` (axe over every swept screen),
`tests/contrast.test.ts` + `tests/contrastTokens.test.ts` (the palette, and the pairings
axe cannot see under jsdom) and `tests/responsive.test.ts` (tap targets, scroll
containers, phone widths) fail the build on them.

1. **Every control has a real name.** Wrap the control in its own `<label>` (implicit
   association) rather than inventing ids — two editors of two records on one screen
   collide on any id scheme. A `placeholder` is **not** a label: it satisfies axe and fails
   the user, because it vanishes on typing (this is stated in `tests/a11y.ts` and was
   confirmed there by experiment). WCAG 3.3.2 Labels or Instructions (Level A).
2. **Keyboard operability, with no exceptions.** Native elements first: `<button>`,
   `<input type="checkbox" role="switch">`, `<details>`. Anything that scrolls must be
   focusable and named — there is no key that scrolls a non-focusable `<div>` — which is
   what `ScrollRegion` exists for.
3. **Focus is visible and is never moved without cause.** Where a control mutates into its
   own confirmation (`AgentLifecycle`), keeping it as ONE button in ONE slot means React
   reuses the DOM node and the keyboard stays put; `agentDetail.test.tsx` pins that,
   because a later refactor into two sibling buttons would silently take it away.
4. **Contrast: 4.5:1 for all our text.** Nothing in this console uses type at 24px or
   18.66px-bold, so the large-text allowance never applies and is not offered. Two pairings
   are banned by test: `text-white` on `bg-brand` (3.38:1) and `text-brand` on
   `bg-brand-soft` (3.08:1). Use `bg-brand-strong` / `text-brand-strong`.
5. **Touch targets.** WCAG 2.2 **2.5.8 Target Size (Minimum), Level AA** requires 24×24 CSS
   px, with five exceptions (spacing, equivalent, inline, user-agent control, essential) —
   and the Understanding document itself says "for important links/controls, consider
   aiming for the stricter 2.5.5 Target Size (Enhanced)" (w3c/wcag
   `understanding/22/target-size-minimum.html`, read 25 Aug 2026). We do: every shared
   control class carries `touch:min-h-11` (44px under `pointer: coarse`), so desktop
   density is untouched and a finger gets the taller box.
6. **A phone is the design target, not a breakpoint.** Nothing is pinned wider than 320px
   unless it scrolls in a `ScrollRegion` or waits for a breakpoint; card padding is
   `p-4 sm:p-6`; text-entry controls reach 16px on a coarse pointer so iOS does not zoom.
7. **Compliance controls are part of the accessibility floor, not a separate topic.** The
   AI-disclosure switch, the recording-notice switch, the server's truthful-answer sentence,
   the publish/verification state and every `ProblemNotice`:
   - are **never** placed inside a `<Disclosure>`, a tab, or below the fold of the section
     that owns them;
   - keep their **order** — the guarantee is rendered ABOVE the switches, because a reader
     who meets two "off" positions first infers the opposite;
   - are rendered in the **server's own words** where the server owns the wording
     (`truthful_answer_rule`, `opening_line`, problem `remediation`) — a paraphrase is a
     second implementation of a compliance rule, and the second one is where the drift
     starts;
   - say what "off" does **not** do. "Calls are still recorded — this only stops the agent
     announcing it." A setting that omits that sentence is a trap, not a setting.

---

## §9 "Maximum control, minimum complexity"

**Power stays reachable. Deleting a feature is not a simplification — it is a different,
worse product.** The complexity the founder is objecting to is not the number of controls;
it is that they were all shouting at once.

The four moves that are allowed, in order of preference:

1. **Rank it.** Give the screen a primary and let everything else be visibly secondary.
   This is the whole of §1 and it costs the user nothing.
2. **Group it by intent.** §5. Also free.
3. **Disclose it.** One click, closed by default, with the fact still readable in the
   closed state. Costs one click, for the rarely-used.
4. **Move it to its own route.** Costs one navigation, buys a whole screen — the right
   answer when the thing has its own state.

**Never: remove the control, or hide it behind a support request.** If a control is
genuinely wrong for clients, that is a D-21 boundary decision with a decision-log entry —
and even then the screen states the fact and says who moves it, rather than showing a dead
input or nothing at all.

**Test it the way the user meets it:** a first-time owner, told nothing, must find the
screen's primary job in seconds. On the agent workspace that is now a brand-bordered panel
headed "What it says on a call" with the only large green button on the page. It was a
text link in the fifth card.

---

## §10 What a new screen must ship with

- Named primary job, in the component's doc comment.
- §52 handled as three mutually exclusive branches, never a fall-through ladder: loading is
  a `Skeleton`, failure is a `ProblemNotice` with a retry, and "you have none" is stated
  **only** where the server said so. A failed read is not evidence about a client's
  account, and `tests/surfaceStatesGuard.test.ts` type-checks that no fallback (`?? []`,
  `?? 0`) stands in for an answer that may never have arrived.
- Every wire-string map read through `lookup`, so an unknown value fails **visible** rather
  than crashing or vanishing.
- Money as strings, formatted by `formatINR` and never parsed (`Number("10159.00")` is how
  ₹10,159.00 becomes ₹10,158.999999999998 — hard rule 7). Times through `formatIST`.
- No PII in any log line (hard rule 6).
- A test that fails if the hierarchy regresses — not only that the content renders. The
  agent workspace's is `agentDetail.test.tsx` → "the script is the screen's primary
  surface", which asserts position, size and singularity, so a future refactor that demotes
  it back into a card goes red.
