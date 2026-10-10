# UI redesign #2: brief

Started 10 Oct 2026. The founder's verdict on the client console: it "looks like AI slop".
Their example was the agent Advanced tab, "Actions during the call", and its New action
form. They said most client-facing screens look the same way. Client panels come first,
then admin.

## Founder decisions (binding)

| Topic | Decision |
| --- | --- |
| Direction | **Calm and plain**, in the style of the Stripe Dashboard and Notion. Lots of white space, plain sentences, one clear primary action per screen, few borders and cards. Settings read as label–value rows with a "Change" link. |
| Brand | **Keep it.** The green family (`--brand` #16a05d …) and PP Mori stay. Layout, spacing, hierarchy, copy and components are redesigned. The marketing site stays consistent. |
| Depth | **Overhaul flows too.** Technical forms become guided flows. The API and data contracts do not change; machine values (an action's `name`, param bindings, triggers) are derived behind the scenes. |
| Process | **Pilot, then fan out.** First the design system plus four client screens. Then STOP for the founder's review. Then the rest of the client side. Admin follows, with its direction confirmed first. |

The calendar action as the founder approved it:

```
Book appointments
Your agent can check your Google Calendar and book callers in.
 Calendar      Google · sri@…   Change
 Length        1 hour
 Hours         9 am – 6 pm
                         [ Turn on booking ]
```

Who the client is: an Indian small business owner (clinic, property office, school,
shop). Not technical, often on a phone, English as a working language.

## Skills to use (vendored in `.claude/skills`, see the `*-PIN.md` files)

1. **`web-design-engineer`** (garden) is the workflow:
   - fact check;
   - a Design Read with the five dials;
   - declare the system;
   - build;
   - the 5-dimension critique.

   Use `references/redesign-protocol.md` (this is a **Redesign · Overhaul** of
   interaction with **Preserve** of brand), `failure-patterns.md`, `critique-guide.md`,
   and the style recipes `stripe-press` and `notion-pre-ai`. Ignore its CDN/Babel
   prototype advice: this is a Next.js app (see `DESIGN-SKILLS-PIN.md`).
2. **`no-ai-design-slop`** (MengTo) is the passive gate on every component, using its
   removal test. **`audit-ai-design-slop`** is the self-review before reporting.
3. Owl-Listener skills, by job:
   - **`form-design`, `error-handling-ux`, `loading-states`, `feedback-patterns`:** every form and state;
   - **`ux-writing`:** every word;
   - **`visual-hierarchy`, `spacing-system`, `typography-scale`, `readable-measure`:** the system;
   - **`navigation-patterns`, `onboarding-design`:** shells and first-run;
   - **`critique-information-density`, `critique-visual-hierarchy`, `critique-typography`:** checking.
4. **Emil Kowalski** (`emil-design-eng`, `animate`, `review-animations`): motion only where it
   explains state. **`beautiful-shadows`:** elevation, used sparingly.

## What does not change (read before designing)

- **`docs/UX-DOCTRINE.md`**:
  - D-655: tabs only for peer views of the same data;
  - D-657: one-line hints, with the reason behind an ⓘ;
  - D-661: the admin layout and Cmd+K.
- **`docs/design/UI-COMPONENTS.md`**: the kit is `components/ui.tsx` and
  `components/console/` (the interior.dev and Pixel Perfect verdicts). **Extend or replace
  in place.** Never add a second way of doing one thing; when a primitive is replaced, every
  caller moves in the same change.
- **Copy rules:**
  - Client text speaks from the client's point of view.
  - It never names a vendor for telephony, voice or AI (D-679).
  - Compliance sentences, the AI-disclosure and recording-notice lines, money warnings and confirm steps stay **verbatim**. `lib/marketing/compliance.ts` and the copy guards pin them.
- **Mobile rules** (rememory "Mobile rules for the web app"):
  - `touch:min-h-11` tap targets;
  - `dvh`, never `vh`;
  - `ScrollRegion` for wide tables;
  - `MODAL_*` bottom sheets;
  - `FileDrop` for uploads;
  - no horizontal scroll at 320 px.
- **Both palettes** (light and dark) and real-Chromium axe pass. Use tokens only, no raw colours.
- **No new npm dependency** without asking the founder. No CDN scripts. No CSP change.
- **The API and OpenAPI client do not change.** If a guided flow needs a value the form
  used to ask for, derive it in the web layer (for example, an action `name` slugged from
  the job, with a suffix if it is taken).
- **Tests:** about 244 web test files guard copy, formatters, surface states, a11y and the
  nav inventory. `lib/clientNav.ts` is also parsed by `apps/api/copilot/screens_test.py`.
  Change a test only when the behaviour it pins has deliberately changed, and say which.

## Pilot (stop after this)

1. **The system, written down first:** add a "Design Read and system" section at the end of
   this file. Include:
   - the five dials;
   - the type roles mapped to the existing scale;
   - the spacing rhythm, surfaces and borders, radius, elevation and states;
   - the patterns: page header, label–value settings rows, empty states, inline edit, the guided chooser, the primary-action rule.

   Implement it as tokens in `globals.css` and as primitives in the shared kit.
2. **Four screens:**
   - **Dashboard** (`/c/[slug]`);
   - **The agent page** (`/c/[slug]/agents/[agentId]`), including **Actions**, rebuilt as a guided flow: pick a job → connect if needed → two or three plain settings → turn on, with the "Run test" moment folded in. The machine name, "AI decides" parameter rows and trigger select disappear from the default path; an "Advanced" disclosure may keep them for the custom-API case;
   - **Integrations** (`/c/[slug]/integrations`);
   - **Calls** (the list and one call's detail).
3. **Verify:**
   - `pnpm -C apps/web typecheck`, `lint`, and vitest on the touched areas;
   - a rendered check in the Browser pane at 375 px and 1280 px, light and dark, using the throwaway node API mock from the rememory mobile memory;
   - then run `audit-ai-design-slop` on your own result and fix the P0 and P1 findings.
4. **Report:**
   - what changed, screen by screen;
   - the system you declared;
   - anything you could not verify;
   - the decisions the founder must make before the fan-out.

## Working rules for the agent

- Never run Python, `uv`, `pytest` or `docker` on this machine. The founder runs the backend
  suite separately, and a full suite is running in the background now. Keep test runs light:
  no full vitest suite during the pilot.
- No git commits, pushes, resets or stashes. No destructive commands.
- Do not touch `apps/api`, `apps/workers`, `admin/**` or marketing pages in the pilot.
- The working tree holds uncommitted fixes made on 10 Oct: the OAuth popup hand-off, the
  calendar test-form time picker in `ToolRow.tsx`, and the action outcome labels in
  `lib/api/actions.ts`. **Build on them; do not revert them.**

## Design Read and system (pilot, 10 Oct 2026)

```yaml
Design Read:
  artifact: client console (operational product UI), four pilot screens
  audience: Indian small-business owner, non-technical, often on a phone, English as a working language
  visual-language: calm and plain (Stripe Dashboard settings, pre-AI Notion): ink on white, hairlines, one green action
  mode: Redesign · Overhaul of interaction, Preserve of brand (green family, PP Mori, marketing untouched)
  visual-variance: 2    # one layout grammar everywhere; nothing decorative
  motion-intensity: 2   # existing state motion only (press, section fade, value flash); nothing added
  information-density: 5 # figures and rows scan; no cards around them
  asset-dependence: 1   # no imagery; lucide icons only where a list needs a marker
  brand-fidelity: 9     # tokens unchanged except the additions below
```

Recipes used as references, not copied: `stripe-press` for restraint and label–value settings,
`notion-pre-ai` for the plain chooser and conversational microcopy. Neither recipe's palette or
serif was taken (the brand decision wins).

### Tokens (`apps/web/src/app/globals.css`)

- **Type roles** (`@theme`): `text-title` 22/28 600 (a thing's name: an agent, a caller),
  `text-heading` 17/24 600 (a section), `text-body` 14/22 (rows, prose), `text-meta` 13/20
  (hints, secondary lines), `text-figure` 26/32 600 (a dashboard number; `Metric` already uses
  this size). Weight travels with the role.
- **Chart fills**: `chart-warn`, `chart-danger`, `chart-neutral` (marks only, beside a text
  legend), replacing raw amber/rose/slate in the daily-calls chart and sentiment bar.
- **Ground**: the client content area is `--surface` (white). `--app` stays the shell's recessed
  colour behind the sidebar. Resting content takes no shadow; only overlays (menus, sheets,
  dialogs) keep `shadow-overlay`.
- Status colour is always a token role: brand (done), warn (missed), danger (failed), ink at
  6% (still moving). Call status badges and delivery badges moved onto these.

### Rhythm, surfaces, radius, states

- Spacing on the 4px grid: rows `py-3.5`, blocks inside a section `space-y-4`, sections
  `space-y-10`, two-column gaps `gap-10`/`lg:gap-12`. Content columns cap at `max-w-2xl` for
  settings and `max-w-4xl` for a page of lists, so a label never sits 900px from its value.
- Surfaces: no box by default. Grouping is whitespace, then a hairline (`border-y border-line`
  around a list, `divide-y` between rows). A `Card` is kept only for a bounded job with its own
  controls and outcome (the trial panel, the setup checklist, a modal).
- Radius: 6px controls (`rounded-md`), 14px cards and sheets (`rounded-card`), pills fully round.
- States: hover is a 3% ink wash on rows; focus is the brand ring; disabled is 50% opacity with
  the reason in words beside the primary action ("Connect a Google Calendar first.").

### Patterns (all in the shared kit)

- **Page header**: `console/pageHeader` unchanged: name, state, one line.
- **Section**: `console/section` `Section`, a heading (h2, or h3 inside a settings section),
  one-line description, optional ⓘ and one quiet action. Not a landmark (as `Card` is not).
- **Text actions**: `TEXT_ACTION` / `TEXT_ACTION_DANGER` for "Change", "View all", "Remove".
- **Label–value rows**: `console/settingRow` gained `action` (the "Change" link). A read-only row
  stays on one line on a phone; a row with a control stacks.
- **Guided chooser**: `console/chooser` `Chooser`/`ChooserItem`, a list of jobs between
  hairlines, icon, title, one line, chevron. For picking a job; `choiceCard` stays for picking
  an option inside a form.
- **Empty states**: `console/emptyState` unchanged; the chooser doubles as the Actions empty
  state ("What should your agent do on calls? Pick one.").
- **Inline edit**: summary rows with "Change" open the same setup form prefilled, in place of
  the list, with "← All actions" and Cancel to return.
- **Primary-action rule**: one filled button per view, bound to the form it submits, bottom
  right of that form, its label the consequence ("Turn on booking", "Save changes"). Everything
  else is a secondary (bordered) button or a text action.
- **Account sign-in**: `integrations/useAccountSignIn` is the one popup sign-in hand-off, used by
  Integrations and by a job that needs an account it does not have yet.

### Fan-out additions (10 Oct 2026, after the founder approved the pilot)

- **Booking hours are server rules.** Both calendar tools carry `opens`, `closes` and
  `open_days`; the setup has Hours and Days (default Mon – Sat, 9 am – 6 pm). The same sentence
  stays in the agent's instructions so it can say the hours. Older actions are read from their
  instructions and show "Any time" with a prompt to set hours.
- **Notices on tokens.** `NOTICE_TONES` maps ok/warn/stop/neutral to brand-soft, warn, danger
  and an ink wash; `NoticeBox` is `rounded-md px-4 py-3 text-body`.
- **No resting shadows in the console kit** (`Card`, `StatTile`, card `Disclosure`, the live
  call panel and pill, the step flow). Marketing keeps `shadow-card`.
- **`Fact`** is a plain muted label over a medium-weight value; the uppercase tracked label is
  gone.
- **The assistant.** The client header launcher is a quiet bordered "Ask" button with a question
  bubble (the admin realm keeps its slate tile). The panel keeps every consequence sentence
  verbatim; the composer is one bordered field with Ask inside it; the person's words sit in a
  right-aligned bubble; fills, receipts and jobs are a left rule rather than boxes; the
  workspace's approvals, tasks and routines are divided lists. Every screen declares its
  copilot surface with real fields.
- **Service logos** (`components/console/serviceLogo.tsx`): official full-colour icons, small,
  always beside the service's name, never for our own vendors.
- **No bottom tab bar** on phones; the menu button opens the sidebar.
- **Competitor context.** Use the Outpero teardown to judge what a voice-agent SaaS client
  needs: rememory "outpero teardown" (parts 1–7), `docs/evidence/outpero-teardown-aug2026.md`,
  and the gap report of 9 Oct 2026. Useful patterns: agents treated like staff with clear tabs,
  a "talk to your agent" test moment, credit shown as a runway, one-form campaign setup with
  sensible defaults, a plain post-call webhook description, and the narrow Google Calendar
  privacy pattern. Do not copy their identity.
- **Two agents, one per realm, no sub-agents** (the founder's rule). The client agent owns
  `app/c/**`, the client auth pages, `components/copilot/**`, the shared kit (`ui.tsx`,
  `components/console/**`, `globals.css`) and `lib/clientNav.ts`. The admin agent owns
  `app/admin/**`, `components/admin/**`, `adminNav.ts` and any backend it adds. It consumes the
  shared kit as it is, and builds admin-local primitives to promote later. Each agent keeps a
  route checklist that goes in its report.
