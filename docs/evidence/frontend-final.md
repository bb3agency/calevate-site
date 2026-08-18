# Frontend, last pass before production — `apps/web`

Fix-first pass, August 2026. Unlike `audit-frontend.md`, **everything in the Findings
section below is fixed in this branch**, each with a test that fails without it, and each
sabotage-verified. What is not fixed is in **Backend referrals** or **Still open**, by
name.

Gates, before and after:

| | before | after |
|---|---|---|
| `make web-check` | 89 files, 1148 tests, 167s | 91 files, **1172 tests**, 207s |
| `pnpm -C apps/web build` | exit 0 | exit 0 |
| `uv run python -m scripts.check_openapi_fresh` | OK (175 paths, 292 schemas) | OK |
| `uv run python -m scripts.check_docs_drift` | OK | OK |

---

## Three premises in the brief this tree does not carry

Recorded first, because they bound what could be checked — and because the previous
frontend audit opened the same way, which suggests the briefs and the tree are drifting
apart rather than one pass being unlucky.

- **`docs/evidence/deepdive-frontend2.md` does not exist.** `docs/evidence/` holds 20
  files and no second frontend deep-dive. The prior pass's findings were read out of
  `audit-frontend.md` instead, and every one of its ten is accounted for below under
  "What the previous pass left, and where it stands".
- **`avg_duration_s` has not been renamed to `avg_duration_s_7d`.** The field is
  `avg_duration_s` in `apps/api/crm/schemas.py:706` and `:785`, in the committed OpenAPI
  snapshot, in `schema.d.ts:5244`/`:7789`, and at both render sites
  (`c/[slug]/page.tsx:103`, `c/[slug]/performance/page.tsx:146`). This is not a stale
  snapshot: `check_openapi_fresh` regenerates the contract from the live app in memory
  and reports OK, so the console and the API agree. **PROVEN** (guardrail run).
- **No engine capability governs whether an agent may be published.**
  `EngineCapabilityName` (`packages/shared/src/calevate_shared/engine.py:60-68`) is a
  closed set of seven — `stt`, `tts`, `llm`, `campaigns`, `knowledge_base`, `numbers`,
  `transfer` — and none of them is "hosts agents". `publish_agent` can be refused for a
  missing script, a closed account (D-194), `engine_not_configured` or an adapter error,
  and each of those renders through `ProblemNotice`, which prints `detail` **and**
  `remediation`. So the screen does explain why; there is no capability refusal on that
  path to explain. One copy problem on it is a backend referral, below. **PROVEN** (read
  of the closed `Literal` plus the publish route).

---

## Findings — all fixed

### FF-1 · The step-up prompt did not exist, so twelve confirmed admin writes answered "confirm it is still you" with two curl calls — HIGH

`apps/api/core/stepup.py:107,110` raises `reauthentication_required` for any confirmed
admin mutation whose session has not proved a second factor inside `REAUTH_MAX_AGE`
(5 minutes, D-178). Its `remediation` (`apps/api/authn/stepup.py:114-118`) is:

```
POST /v1/auth/admin/step-up to have a code emailed, POST the code to
/v1/auth/admin/step-up/verify, then repeat this request with X-Confirm-Action: <action>
```

`ProblemNotice` (`components/ui.tsx:219`) renders `remediation` verbatim, so that string
was what an operator saw. **The console had already decided this was wrong and written
the replacement**: `lib/authn/problems.ts:148-152` carries the
`reauthentication_required` copy under a comment reading *"NOT the server's `detail`,
which prints the two curl calls that clear it — correct for an operator reading a log,
wrong on a screen where the button is what does it."* Nothing rendered it —
`signInMessage` was called from the sign-in surfaces and nowhere else, and
`grep -rn "reauthentication_required" apps/web/src` returned two hits, both inside
`problems.ts`.

Reach: every site that sends `X-Confirm-Action` (twelve, from
`grep -rn confirmAction apps/web/src/lib/api/`) across six screens — the ops console's
halt / load-shed / TM registration / outbox replay / spend-cap recompute, the
platform-wide do-not-call list, `ops/ConfigPanel`, `ops/SecretsPanel`, a credit
adjustment, a top-up restatement, a spend ceiling, and the tenant erasure.

**Proven or reasoned:** PROVEN — driven in `tests/adminStepUp.test.tsx`, which renders
the real do-not-call screen, stages the real 403 body, and asserts the curl string is
absent from the document.

**Fixed** (D-340) by `app/admin/stepUpPrompt.tsx` plus `requestStepUp`/`verifyStepUp` on
`adminAuthn`, routed from `WriteFailure`, which moved out of `ops/` and is now the one
renderer for a failed confirmed write on all six screens. Three properties are worth
naming because each was a decision:

- **`verifyStepUp` rotates the session**, so it calls `adminAuthn.reset()` and goes
  through the realm's rotation barrier exactly as `submitSecondFactor` does. Without
  that, any request still carrying the retired cookie is `reuse_detected` and
  `verify_session` revokes the whole family (RFC 9700 §4.14.2) — an operator who typed
  the *right* code signed out of everything.
- **It does not replay the refused action.** `onRetry` is optional; where a call site
  cannot cheaply re-issue the exact request the operator confirmed, the prompt says to
  press the control again. A dangerous mutation a component re-sends from memory after an
  unexpected interstitial is a second irreversible write nobody pressed a button for, and
  the tenant erasure is on this list.
- **`step_up_required` keeps its own panel.** Intent and presence are separate
  obligations with opposite remedies (reload for a build skew / prove a factor), and the
  test asserts the skew panel still wins for its own code.

The four sub-cases the brief named:

| case | behaviour | evidence |
|---|---|---|
| refusal arrives mid-flight | the prompt renders attached to the mutation error it came from, in place; the rest of the screen is untouched | PROVEN (test 1) |
| prompt "dismissed" | there is no dismiss control by design — the prompt IS the error rendering, so it clears when the error does (a new attempt, or a successful one). A dismissible prompt would leave a screen with a refused write and nothing on it | REASONED |
| a wrong code | stays in the code step with the API's own sentence beside the field, and the *original* refusal still on screen: two failures, two remedies | PROVEN (test 2) |
| the mail never leaves | stays in the "Email me a code" step. A code field nobody can satisfy is worse than a button that failed | PROVEN (test 3) |
| two tabs | the credential is an `HttpOnly` cookie no tab reads, so a step-up in tab A silently freshens tab B as well; two *simultaneous* verifies race one live challenge and the loser gets `invalid_second_factor`, which is honest and recoverable | REASONED — proving it needs two browser contexts against a live API |

**Sabotage:** removing the `reauthentication_required` branch from `WriteFailure` turns
3 of the 4 tests red; the 4th is the skew-panel control and stays green, which is what
makes it a control.

---

### FF-2 · The delivery payload's audit row still escaped through the cache — the raw transcript's fix did not follow its sibling — MEDIUM

`useDeliveryPayload` (`lib/api/integrations.ts`) was a `useQuery` with
`staleTime: Infinity` and all three implicit refetches off, under a comment claiming
*"Same shape, same reasoning, as `useRawTranscript`"* — which had stopped being true.
`useRawTranscript` moved to a `useMutation` precisely because
`GET /v1/calls/{id}/transcript/raw` writes an `audit_log` row in the same transaction as
the read. `GET /v1/integrations/deliveries/{id}/payload` does the same
(`apps/api/integrations/routes.py:727`) for the same reason — the body is unredacted
personal data under hard rule 5 — and was left on the old shape.

Consequence: View → Close → View served the customer's details out of cache with no
network call and **no second `audit_log` row**, and so did leaving the screen and coming
back inside `gcTime`. A second effect the mutation also fixes: `enabled: false` keeps the
observer subscribed, so the unredacted body stayed in the JS heap for the life of the
page after the reader said they were done with it.

**Proven or reasoned:** PROVEN — both doors driven at the network seam in
`tests/integrationsPayload.test.tsx`, the second sharing one `QueryClient` across two
mounts (a fresh client has no cache to restore from, so the test would pass against the
broken version and prove nothing).

**Fixed:** the hook is a mutation taking `deliveryId` as its variable; the screen gained
a `togglePayload` in the shape of the call-detail screen's `toggleRaw`, so there is one
mechanism for one rule.

**Sabotage:** reverting the hook to a cached query fails exactly the two new tests and no
others.

**This closes the audited-read sweep.** Every route in the tree that writes an
`audit_log` row inside a read was enumerated (`write_audit` in `crm/routes.py` and
`integrations/routes.py`, cross-checked against every `@router.get`): the raw transcript,
the recording link, the delivery payload, and the CSV export. The first two were already
mutations; the export is a POST that the console calls as one; this was the last query.

---

### FF-3 · Ninety WCAG AA contrast failures, on every route, invisible to the gate by construction — HIGH

`tests/a11y.ts:79-101` disables axe's `color-contrast` rule with a correct reason: jsdom
has no layout, so axe cannot resolve a computed colour. The consequence is that the one
accessibility failure that is **pure arithmetic** was the one the 1148-test suite could
not see.

Measured with Chromium (`/opt/pw-browsers/chromium-1194`) + axe-core 4.13 over the eleven
routes reachable without an API, `wcag2a wcag2aa wcag21a wcag21aa wcag22aa`:

| token | pair | measured | AA needs |
|---|---|---|---|
| `--text-faint` `#94a3b8` | on `--surface` `#ffffff` | **2.56:1** | 4.5:1 |
| `--text-faint` | on `--app` `#fafafa` | 2.45:1 | 4.5:1 |
| `--text-faint` | on the legal parchment `#fdfbef` | 2.46:1 | 4.5:1 |
| `--brand` `#16a05d` | white text on it | **3.38:1** | 4.5:1 |
| `--brand` | as text on a card | 3.38:1 | 4.5:1 |
| dark `--text-faint` `#64748b` | on dark `--surface` `#0f172a` | 3.75:1 | 4.5:1 |

Not decoration: `text-ink-faint` carries the hint under every form input, the
"Operator console" / "Nothing here places a call" chips in both auth shells, and the
definition labels in the privacy notice and the terms — 18 nodes on the privacy notice
alone. `bg-brand` is 69 call sites (every primary button, including the landing page's
only call to action) and `text-brand` 35, which is why the fix is the token and not the
classes.

Also **WCAG 2.2 SC 2.5.8 Target Size**: 78 `target-size` nodes, all one shape — an
anchor that is the whole content of an `<li>` in a navigation list, so its box is exactly
its line box (11px in the marketing footer, 17px in a legal document's table of
contents). The SC's "inline" exception covers a link inside a sentence of running prose;
a list of policy links is navigation.

**Proven or reasoned:** PROVEN in a real browser, twice — before and after.

**Fixed** (D-341): each text tier moved down one slate step rather than collapsing into
its neighbour (`--text-muted` `#475569` 7.58:1, `--text-faint` `#64748b` 4.76:1 on white
and 4.58:1 on parchment); `--brand` → `#128050` (4.97:1 both directions, 4.54:1 on
`--brand-soft`, still a clear step lighter than `--brand-strong`); the dark palette moved
the same two steps; the legal callout's tone label moved from the faint tier to the muted
one, because it is the one place the faint tier sits on a tinted panel and that cost it
the last tenth (4.43:1); and `inline-block py-1` on the four navigation anchors.

There is no lighter value available — 4.5:1 against white bottoms out around `#697586` —
so "a bit fainter" does not exist at AA, and pretending it did is what put `#94a3b8`
there.

**After:** all eleven routes clean under the full AA sweep, both `colorScheme` settings.

```
light / clean            light /legal/privacy clean       light /auth/sign-in clean
light /signup clean      light /legal/terms clean         light /auth/forgot-password clean
light /invite clean      light /legal/acceptable-use clean light /auth/admin/forgot-password clean
light /legal clean       light /auth/admin/sign-in clean
(and the same eleven under dark)
```

One report was **not** a defect and is recorded rather than chased: the landing page's
call demo reported `#308058` on `#edf9f2` (4.46:1) while its GSAP opacity tween was still
running, and settles clean. The probe now waits for it.

**Guards:** `tests/contrastTokens.test.ts` computes the ratios from `globals.css` itself
rather than from a palette copied into a test — a copied palette passes forever after
somebody edits the stylesheet, which is the defect class `check_openapi_fresh` and
`wireFixtureGuard` exist for. The SC 2.5.8 rule joins `tests/responsive.test.ts`, which
already argues at length that the browser is the *instrument* and what it teaches is
written down as a rule that runs everywhere.

**Sabotage:** restoring `--text-faint: #94a3b8` fails exactly the three ink-faint tests;
restoring `--brand: #16a05d` fails exactly the brand test; removing `inline-block py-1`
from the two `document.tsx` anchors names both lines in the failure message.

---

### FF-4 · The route-module-export guard, re-verified — CLEAN

Not a finding; the brief asked for it to be sabotaged. `export const sabotageProbe = 1;`
appended to `c/[slug]/integrations/page.tsx`:

- `tests/routeModuleExports.test.ts` → red, naming
  `` c/[slug]/integrations/page.tsx exports `sabotageProbe` ``.
- `pnpm -C apps/web build` → red, `"sabotageProbe" is not a valid Page export field.`

So the fast guard and the slow gate agree, which is the property that makes the guard a
floor rather than a substitute. **PROVEN.**

---

## Backend referrals — not mine to change

1. **`engine_not_configured`'s remediation is written for a client and is shown to an
   operator.** `apps/api/engine/capabilities.py:164` sets
   `remediation="Contact us — this is a configuration problem on our side, not yours."`
   That is right on a client dashboard. The agent publish button is on
   `/admin/tenants/{id}/agents/{id}/prompt`, where the reader **is** "us", so an operator
   whose deployment is missing an engine credential is told to contact themselves. The
   frontend cannot fix this without deciding what a code means per screen, which is the
   thing `problems.ts` exists to prevent. Low severity, one string.

2. **`/v1/auth/**` ignores `Idempotency-Key`.** `lib/authn/transport.ts:63-75` documents
   that it sends the header, that `core/middleware.py` allows it through CORS and
   `reliability/service.py` implements the store, and that `/v1/auth/**` takes no such
   dependency — so the header is inert on exactly the forms (password reset request,
   reset confirm) that must not act twice. Already recorded on the frontend side; carried
   here so it is in one list.

Neither is a blocker for this branch.

---

## What the previous pass left, and where it stands

Checked one by one, because "fixed by a sibling" and "still there" look identical from
outside.

| | status | evidence |
|---|---|---|
| F-1 raw transcript served from cache | **closed** | `useRawTranscript` is a `useMutation`; `callDetail.test.tsx` drives both doors |
| F-2 seventeen unreachable scroll containers | **closed** | `ScrollRegion` in `components/ui.tsx`, enforced by `responsive.test.ts` with a two-entry exemption list that still demands focusability |
| F-3 no skip link | **closed** | `SkipLink` + `MAIN_CONTENT_ID` + `tabIndex={-1}` on both shells' `<main>` |
| F-4 `aria-current` on no element on detail routes | **closed** | one `lib/nav.currentNavItem` read by both the title and the highlight, in both shells |
| F-5 phone number in a GET query string | **closed** | D-181/D-191 moved the lens to `POST /v1/leads/search` and `/facets`; `lensQuery` now **throws** if a search term reaches it, which is a runtime guard and not a convention |
| F-6 20px inline edit controls | **closed** (not re-measured here) | `responsive.test.ts` owns tap-target rules now |
| F-7 no `tests/responsive.test.ts` | **closed** | the file exists and is the home FF-3's target-size rule joined |
| F-8 delivery-log row key collision | **closed** | no duplicate-key warning in the 1172-test run |
| F-9 three query keys without an org slug | **closed** | `tests/queryKeys.test.ts` scans all of `src/` |
| F-10 unresolvable brief references | **recurs** — see the three premises at the top |

---

## Examined and clean

Stated so an absence of findings is a claim rather than a gap.

**Silent mutation failures — none.** All 86 mutation hooks in `lib/` were resolved to
their call sites and each result's `.error` traced. Two candidates fell out of the scan
and both are false positives: `ops/dnc/page.tsx` renders `suppress.error` through a
prop rename (`<WriteFailure error={mutation.error}>`), and the `leads.ts` hit is a local
inside a hook wrapper. Every user-reachable mutation renders its refusal.

**4xx / 5xx / timeout / remediation.** `ProblemNotice` prints `title`, `remediation`,
field errors, and offers retry only when the server says `retryable` **or** when no HTTP
response happened at all — the second clause is what keeps a train-tunnel failure from
being a dead end. `remediation` is rendered at every one of the 277 sites because they
all go through that component; the two places that deliberately do not (`WriteFailure`'s
skew panel, `StepUpPrompt`) both print or replace it on purpose, with the reason written
above the code.

**Audited reads.** Enumerated exhaustively; see FF-2's closing paragraph.

**Redaction at the edge.** Every `URLSearchParams` and template-literal query in
`lib/api/` was read: the parameters are limits, offsets, months, day counts, statuses,
uuids and job names. No phone number, no transcript, no search term. `lensQuery` throws
rather than trusting the convention. `LeadOut` carries `phone_masked` only.

**Query keys.** `tests/queryKeys.test.ts` scans every `useQuery` in `src/` and requires
the org slug on any key whose `queryFn` closes over a tenant session, with the
admin/platform keys correctly exempt. It is a source scan, so it covers the hook nobody
remembered to stage.

**Fail-open defaults.** `tests/surfaceStatesGuard.test.ts` makes BUILD-LOG §52 executable
over five rules and is the reason the `?? false` / `?? []` / `{q.data && <button/>}`
shapes could not be re-introduced while this pass ran. The one place a control is offered
while an answer is missing — the publish button when the version history has not answered
— is argued in place (`hasAScript === false` disables; `undefined` leaves the server
authoritative and the refusal renders), and that is the correct direction for a control
whose server-side gate is unconditional.

**Skip link, `aria-current`, focus.** Both shells put `SkipLink` first, both `<main>`
carry `MAIN_CONTENT_ID` and `tabIndex={-1}` (without which a fragment scrolls but does
not move focus, the classic reason skip links do nothing), and both derive the highlight
and the page title from one `currentNavItem`.

---

## Still open

- **Real-browser coverage stops at the eleven unauthenticated routes.** Driving the
  console itself needs a booted API, a seeded tenant and a minted first-party cookie;
  that is a session's worth of setup and it was spent on the contrast sweep instead,
  which is where the browser found something the gate could not. The console screens
  therefore have their contrast checked by `contrastTokens.test.ts` at the token level
  (which is where all six failures lived) and **not** at the composited level, where a
  tinted panel can still cost a tenth — exactly the case FF-3's callout label was. Not an
  external blocker; it is the next browser run.
- **Focus after a client-side route change is not asserted anywhere.** Next's App Router
  ships a route announcer, and this pass did not confirm which of the two shells' `<main>`
  it names. Nothing observed is wrong; nothing is pinned either.
