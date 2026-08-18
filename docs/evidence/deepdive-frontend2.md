# Frontend deep-dive — `apps/web`, both realms, second pass

18 Aug 2026. A find-AND-FIX pass over the whole client console and operator console,
after the Clerk deletion and the first-party auth screens landed. Everything below is
either **PROVEN** (a test driven red, a `next build` failure, or axe in a real browser) or
**REASONED** (read only, and said so).

Ten findings across twelve sites, all fixed. Four decision-log entries: **D-208, D-209, D-210, D-211**.
One backend referral, in its own section at the end. Two sub-surfaces came back clean and
are recorded as such.

---

## 0. A staleness correction worth recording

This pass began on a worktree branched **136 commits behind** the session head — before
the Clerk deletion. Six findings held at that point were re-checked against the updated
tree and **discarded**, because a sibling had already fixed them:

| Discarded finding | Why it no longer applies |
|---|---|
| `useRawTranscript` (`/v1/calls/{id}/transcript/raw`) served a re-open from cache, writing no second `audit_log` row | Already a `useMutation` on the current tree. **Its two siblings were not moved with it** — that became finding F-1 below. |
| No skip link in either shell (WCAG 2.4.1) | `SkipLink` + `MAIN_CONTENT_ID` exist. Its TARGET is missing in two states — finding F-5. |
| Both shells answered "you are here" twice (longest-prefix header vs exact-match sidebar), so no `aria-current` on any detail route | Fixed: `const active = item === current`, one definition per shell. |
| Ten horizontally-scrolling containers no keyboard could reach | Fixed: `ScrollRegion`, plus a source guard in `tests/responsive.test.ts`. |
| The leads search box put a customer's phone number in a GET query string | Fixed: every lens route takes a POST body, and `lensQuery` now **throws** if a `search` reaches it. |
| A non-route export (`deliveryRowKeys`) in a page module | Moved to `@/lib/leadSourceRows`. The premise that `next build` guards it is false for a client layout — finding F-10. |

Recorded because a sibling fixing a thing is the best possible outcome, and because three
of the six turned out to be **half**-fixed — which is where F-1, F-5 and F-10 came from.

---

## Findings

### F-1 · Two audited GETs still served from the query cache, so a second look wrote no second row — **PROVEN** — HIGH

Hard rule 5 lets raw transcript text and unredacted delivery bodies out of the API only
behind a role check **and** an `audit_log` write; SEC-COMP §5 says an admin read of a
client's call is always audited. The row is the route's purpose, so "who looked, and how
often" has to be answerable from `audit_log` alone.

`useRawTranscript` had been moved to a `useMutation` for exactly this. Two siblings had
not:

| Route | Hook | What happened on the second open |
|---|---|---|
| `GET /v1/integrations/deliveries/{id}/payload` (unredacted customer body, audited in `integrations/routes.py`) | `useQuery`, `staleTime: Infinity`, all three implicit refetches off | Served from memory. No request, no row. Its docstring read *"same shape, same reasoning, as `useRawTranscript`"*. |
| `GET /v1/admin/qa-samples/{id}` (one tenant's call shown to somebody outside that tenant, audited in `quality/sampling_routes.py`) | `useQuery`, `staleTime: Infinity`, `refetchOnWindowFocus: false` | Same. A reviewer working two samples and returning to the first was served the cache. |

No staleness policy a query offers is right for a read that records itself: refetching
automatically forges rows naming somebody who did not ask, and the setting that stops it
means the deliberate second read is free.

**Proof.** Both tests drive two opens and count requests, and both failed first:
`expected 1 to be 2` on the delivery payload; `expected 1 to be 2` on the QA sample. The
QA test renders through ONE `QueryClient` across two mounts, because a fresh client per
render is a fresh cache and would pass whatever the hook did.

**Fix.** The delivery payload becomes a mutation, matching the two hooks on either side of
it, and the caller `reset()`s it on close and on a switch between rows — which also stops
the panel printing the previous customer's body under the new row's heading. The QA sample
stays a query (it is a screen's whole payload, not a panel) and gains
`refetchOnMount: "always"`: TanStack reads `true` as "on mount if stale", which under an
infinite staleTime is never, while `"always"` is per mount regardless — so a navigation
costs a row and a timer still costs none.

**Sabotage.** Removing `refetchOnMount: "always"` turns the QA test red again. Decision log
**D-208**.

---

### F-2 · Focus fell to `<body>` when the sign-in code step was abandoned — **PROVEN** — MEDIUM

`SignInForm` moves focus to the code field when the step changes forward, with a comment
saying why: *"without this, focus falls to `<body>` and a keyboard or screen-reader user is
dropped at the top of a page that changed under them."* The same is true in reverse — "Use
a different email address" unmounts the whole code form **including the button that was
just pressed** — and that half was missing.

**Proof.** A new test presses the button and asserts `document.activeElement` is the email
field; it timed out on the unfixed form (focus was on `<body>`).

**Fix.** The effect handles both directions, with a `stepChanged` ref so first paint does
not steal focus — auto-focusing on arrival would scroll a small screen past the heading and
interrupt a screen reader.

---

### F-3 · A wrong-code refusal survived a successful "Send a new code" — **PROVEN** — MEDIUM

`AuthProblemNotice error={submitCode.error ?? resend.error}`, and `resend`'s `onSuccess`
cleared the field and restarted the cooldown but not the previous refusal. So: wrong code →
"That code is not right."; press "Send a new code" → it succeeds, a fresh code is on its
way, the field is empty — and the red sentence is still there, attached to a code the
server has already retired. On a step whose only other feedback is a countdown, that reads
as the *resend* having failed, and the person presses again into a cooldown that refuses
them.

**Proof.** A test drives a wrong code, advances past the 60s cooldown with fake timers,
clicks the real resend button, and asserts no `role="alert"` remains. It failed with the
literal `That code is not right.` still in the DOM.

**Fix.** `submitCode.reset()` in `resend.onSuccess`.

---

### F-4 · Both consoles' session gate left the document with no `main` landmark — **PROVEN in a real browser** — HIGH

`SessionGate` replaces the WHOLE shell — sidebar, header and `<main>` alike. While it is on
screen the document therefore has no main landmark, no level-one heading, and its content
sits outside every landmark.

**Proof.** axe-core in Chromium over the built app:

```
=== admin shell (/admin) — 3 violation(s)
  [moderate] landmark-one-main  — Document should have one main landmark
  [moderate] page-has-heading-one — Page should contain a level-one heading
  [moderate] region — All page content should be contained by landmarks
=== client shell (/c/acme) — 2 violation(s)
  [moderate] region …
  [moderate] skip-link — The skip-link target should exist and be focusable
```

jsdom cannot see any of this: all five are DOCUMENT-level rules and `tests/a11y.ts` scans a
detached container, which is why that file lists them as inapplicable and says
"CLOSED BY: a browser-mode run".

**Fix.** A `landmark` prop on `SessionGate`, threaded through `AdminSessionGate` and
`ClientSessionGate` and set by the two shells. Off by default, because `/auth/account` and
`/auth/admin` render the same gate INSIDE `AuthPageFrame`'s `<main>` and under their own
`<h1>` — a second landmark there would be this defect one level up. The heading is
`sr-only`: each branch already carries a visible title, and a second visible heading over
"We could not reach Calevate" would be noise.

**Re-run: both shells report zero.** Decision log **D-210**.

---

### F-5 · The skip link pointed at nothing in exactly the state it was added for — **PROVEN in a real browser** — HIGH

The sharpest of the four. The client shell renders `SkipLink` **outside** its session
provider on purpose, and the comment says why: *"so a reader can bypass the navigation
while the session is still resolving"*. The `#main-content` it points at lives **inside**
that provider. So while the session is resolving, or gated, or unreachable, the control
exists and its target does not: pressing Enter moves nothing, and the next Tab resumes in
the sidebar.

**Proof.** axe: `skip-link — The skip-link target should exist and be focusable`. And after
the fix, driven by keyboard in Chromium:

```
/c/acme
  first Tab  -> {"tag":"A","text":"Skip to main content","href":"#main-content","visible":true}
  after Enter -> {"tag":"MAIN","id":"main-content","insideMain":true}
```

**Fix.** F-4's `landmark` prop covers the gate branches; the Suspense fallback gets its own
`<main id={MAIN_CONTENT_ID} tabIndex={-1}>`, since it is the one non-gate state the skip
link also outlives.

*Honest limit:* the admin shell's skip link sits INSIDE its gate, so the browser drive
above shows "Try again" as the first Tab on a gated `/admin` — correct, because there is no
sidebar to skip. Its ready-state behaviour is pinned in jsdom by
`tests/shellNavigation.test.tsx` and rests on it being the same component and the same
target id as the client shell's, which is verified end to end above.

---

### F-6 · `--text-faint` was 2.56:1 — **PROVEN in a real browser** — HIGH

The token this console writes every hint, caption and secondary label in, at
`text-xs`/`text-[11px]`, for SMB staff on low-end Android. WCAG 1.4.3 AA wants 4.5:1 for
text that size; nothing in the app uses these tokens at 24px or 18.66px bold, so the 3:1
large-text allowance never applies.

Measured:

| Token | Value | On `--surface` | On `--app` |
|---|---|---|---|
| light `--text-faint` | `#94a3b8` | **2.56:1** | 2.46:1 |
| dark `--text-faint` | `#64748b` | **3.75:1** | 4.24:1 |
| light `--text-muted` | `#64748b` | 4.76:1 | 4.56:1 (passing) |

axe flagged it on **seven of nine documents**.

**Fix, and why it moved two tokens.** The smallest passing value for light `faint` is
exactly light `muted`, which would collapse two tokens into one — a hierarchy the design no
longer has, which the next person restores by picking a lighter grey and putting this
straight back. So both move down the same slate ramp: light muted → `#475569` (7.58:1),
light faint → `#64748b` (4.76/4.56). Dark faint moves UP the ramp (on a dark ground
"fainter" is lighter) to `#7c8a9c` (5.08/5.74), staying dimmer than muted.

Two legal-document tone labels also move from `--ink-faint` to `--ink-muted`: they sit on
tinted callout grounds where even the raised faint does not clear, and a label whose whole
job is to carry the meaning colour cannot should not be the dimmest text on the page.

---

### F-7 · Fifteen call sites put white text on `--brand` (3.38:1) — **PROVEN in a real browser** — MEDIUM

`components/ui.tsx` already states the rule in prose above `PRIMARY_BUTTON`: *"#16A05D
(brand) is the medallion and fill colour, not a button"*, and *"the design's primary button
rests at #0F6B3D and DARKENS to #0c5932 on hover"*. Fifteen hand-written class strings had
drifted from both halves — four marketing CTAs resting on `bg-brand`, eleven console
buttons hovering onto it.

**Fix.** Labelled controls rest on `--brand-strong` (6.58:1) and hover to `--brand-deep`.
Fills keep `--brand`: the bar chart, the toggle knob and the shell's icon medallion carry
no text, so WCAG 1.4.11's 3:1 applies and 3.38 clears.

---

### F-8 · `tests/contrast.test.ts` — the gate the a11y suite asked for — **NEW GUARD**

`tests/a11y.ts` says contrast "is checked once against the palette rather than per render —
either in a browser-mode run … or by hand against the tokens". A browser run cannot be a
gate: it needs a build, a port and a Chromium binary, none of which `make web-check` has.
The arithmetic needs none of them.

The test reads `globals.css` rather than restating it (a copy would pass forever after
somebody edited the real one), computes the WCAG ratio for every ink/surface pair in both
themes at 4.5:1, refuses a palette in which the three inks collapse into one, and scans the
source for white on an unsuffixed `bg-brand` with one reasoned exemption (the shell
medallion) plus a staleness check on that exemption.

**Driven red** on the old palette — four failures, quoting the ratios in F-6.

---

### F-9 · Mutations whose failure has nowhere to go — **NEW GUARD, class currently clean** — MEDIUM

`tests/surfaceStatesGuard.test.ts` covered five shapes, all about a query envelope, and
said why a mutation's `undefined` data is honestly "not asked yet". The mutation's defect
is on the other side of the click: `mutate()` never throws, never rejects and renders
nothing, so a component that fires one and never reads `.error` shows a control that goes
silent on a 403, a 409 and a timeout alike — and the user presses it again. For a dial, a
top-up or a campaign launch that is the worst available outcome, and the API has written a
`title`, a `detail` and a `remediation` for exactly that moment.

Rule 6 fires on a mutation TRIGGERED in the function that declared it while nothing there
consults its failure, gated by the same `refusesSomewhere` rules 3–5 use so "handed to a
child" is tolerated by one code path rather than two.

**Measured across `src/`: zero live hits** — a real negative result, and the reason it ships
with an empty `EXEMPT`. **Sabotage, twice**: a planted fixture, and deleting the real
`add.error` refusal from `/c/<slug>/do-not-call`, where it named the declaration and quoted
the fix. Decision log **D-209**.

---

### F-10 · Route-module exports: `next build` does not check a client-component layout — **PROVEN** — MEDIUM

Next reads a route module's export list as CONFIGURATION, so an unrecognised name is a
build error. That is how `deliveryRowKeys` died in CI. `admin/layout.tsx` carried
`export const MFA_PROBLEM_CODES` four lines below a comment asserting that Next rejects
exactly that, and the build was green.

**Measured.** Comparing `src/app/**` with the validators Next emits into
`.next/types/app/**`:

```
every page.tsx              -> validator emitted
src/app/layout.tsx          -> validator emitted
src/app/admin/layout.tsx    -> NONE
src/app/c/[slug]/layout.tsx -> NONE
```

The two without one are the two carrying `"use client"`. Deleting that directive from
`admin/layout.tsx` and rebuilding makes `.next/types/app/admin/layout.ts` appear. **Next
15.5.21 emits no route-type validator for a client-component LAYOUT while emitting one for
a client-component PAGE** — so the two files every screen in the product renders inside are
precisely the ones the build will not check.

**Sabotage, both directions.** An extra export on `c/[slug]/attention/page.tsx` fails
`next build` with `"sabotageRowKeys" is not a valid Page export field`; the same export on
`c/[slug]/layout.tsx` builds green, and the new `tests/routeExportsGuard.test.ts` catches
both.

**Where the fix landed.** A sibling shipped `tests/routeModuleExports.test.ts` (D-196) in
the interim, and it already covers layouts — sabotage-verified here: an extra export on
`c/[slug]/layout.tsx` makes it fail with `c/[slug]/layout.tsx exports \`sabotageNavKeys\``.
So a second guard would be the duplicate CLAUDE.md forbids, and mine is not re-applied.

What IS re-applied is the measurement, because that file's header states the opposite as a
premise: *"`next build` type-checks page and layout modules against a fixed export shape"*.
It does not, for the only two layouts this repo has, and a guard believed to be a faster
copy of the build is a guard somebody deletes to save a second. The correction and both
sabotage results are now in its header. Decision log **D-211**.

---

## Examined and found clean — negative results from real attempts

**Query keys and cross-tenant cache bleed.** Every one of the 189 `queryKey` sites in the
tree was read. Every client-realm key carries `session.orgSlug`, including the ones keyed on
a UUID (`["campaign", session.orgSlug, campaignId]`, `["callback-check", session.orgSlug,
callId]`) where the id alone would already have been unique. The two keys with no tenant
discriminator are both correct and both say so in their own comment:
`["billing","topup-capability"]` is deployment-level (`payment_capability()` reads settings,
not a tenant) and `[...QA_SAMPLES_QUERY_KEY, sampleId]` is an admin-realm cross-tenant read.
Invalidation after mutations was read alongside: nothing global, nothing narrower than the
lists a write moves. **No finding.**

**Silent mutation failures, as a class.** Before writing the guard, an AST scan over `src/`
looked for every mutation envelope triggered in the function that declared it and never
consulted for failure. **Zero.** The one near-miss (`leads.ts:174`) hands the envelope to
the row renderer, which surfaces it. The guard exists to keep that true, not to fix
anything.

**Phone numbers in URLs.** `lensQuery` now throws if a `search` term reaches it, and every
lens route takes a POST body. No `href`, no query string and no browser URL in either realm
carries a phone number.

**Modal focus traps.** Three modals (`navDrawer`, `aiExtraDialog`,
`adminIdleTimeoutModal`), all three on the one `useFocusTrap`. The idle-timeout modal's
no-op `onEscape` is deliberate — a session-expiry warning is not dismissible.

**Scroll regions.** All eighteen wide containers are `ScrollRegion`; the two remaining raw
`overflow-x-auto` mentions are the component's own definition and a documented waiver for a
vertically-scrolling `<pre>`. Guarded at source by `tests/responsive.test.ts`.

---

## BACKEND — found, NOT touched

One item, for whoever owns `apps/api`.

### B-1 · `GET /v1/leads` matches the `search` term against `phone_e164`, and the term reaches the server in a request line

- **Where:** `apps/api/crm/service.py:471` —
  `clauses.append("(l.name ILIKE :search OR l.phone_e164 LIKE :phone_suffix)")`, with
  `params["phone_suffix"] = f"%{search}"`.
- **What happens:** a user typing a customer's number into the leads search box is
  performing a phone-number lookup. The frontend has already moved every lens route it can
  onto a POST body (`lensBody`), and `lensQuery` throws if a `search` reaches it — so
  **nothing in `apps/web` puts a search term in a URL today**. What remains is whether every
  server-side route that accepts `search` does so in a body, and whether anything in front
  of the API logs request lines.
- **Why it is a backend/infra item and not mine:** the frontend cannot make a GET route
  stop existing, and hard rule 6 ("never log phone numbers") is enforced at the API and at
  the edge. Worth confirming: (a) no `search`-accepting route is still a GET, and (b) the
  nginx templates in `infra/` do not log `$request` or `$query_string` for
  `api.calevate.tech`. I did not change either, and did not verify (b) — `infra/` is outside
  this brief's fence.
- **Severity:** medium. Not a live leak from the console; a latent one from any other client
  of that API, and a logging question.

---

## What was proved versus reasoned

**PROVEN** (a test driven red, a build failure, or axe in Chromium): F-1, F-2, F-3, F-4,
F-5, F-6, F-7, F-8, F-9, F-10, and all five "clean" results in the negative-results section
except the nginx half of B-1.

**REASONED** (read only): the nginx logging half of B-1, and the admin shell's ready-state
skip link, whose browser behaviour is inferred from the client shell's — same component,
same target id.

## How to redo the browser run

Not committed, because it cannot be a gate — but it is four commands:

```
pnpm -C apps/web build
PORT=3114 pnpm -C apps/web start &
# then, in a script: playwright-core chromium at /opt/pw-browsers/chromium-1194/chrome-linux/chrome,
# page.addScriptTag({ content: readFileSync("node_modules/axe-core/axe.min.js") }),
# await window.axe.run(document, { resultTypes: ["violations"] })
```

Nine documents were swept: `/`, `/auth/sign-in`, `/auth/admin/sign-in`,
`/auth/forgot-password`, `/auth/accept-invitation`, `/legal/privacy`, `/signup`, `/c/acme`,
`/admin`. Twelve violations before, **zero** after.
