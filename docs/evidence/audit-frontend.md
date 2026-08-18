# Frontend audit — `apps/web` in full

Find-and-document pass, August 2026. **Nothing here is fixed.** Every entry names a
file:line, the consequence a user meets, whether it was proven or reasoned, and the shape
of a fix — described, never applied.

Baseline for the whole pass: `apps/web` suite green at the time of writing —
**83 files, 1050 tests, 134s** (`pnpm exec vitest run`), and
`uv run python -m scripts.check_docs_drift` OK.

## Two premises in the brief that this repository does not carry

Recorded first, because they bound what this audit could actually check.

- **`docs/evidence/raghava-platform-teardown.md` does not exist.** `docs/evidence/`
  holds five files: `bolna-pilot-scorecard.md`, `cartesia-byoc-question.md`,
  `extraction-provider-scorecard.md`, `outpero-research-log.md`,
  `outpero-teardown-aug2026.md`. The teardown that does exist has no §5.7 — its §5 is
  "CRM, results & analytics" — and names no frontend defects anywhere. So **"the nine
  frontend defects we designed out" could not be checked against anything**, and this
  report makes no claim about them. (`raghava` appears in this repo only as the
  production playbook `docs/DEPLOYMENT.md` and `docs/BACKEND-PATTERNS.md` are adapted
  from.)
- **`apps/web/tests/responsive.test.ts` does not exist** — see F-7. Nothing in the suite
  renders at a viewport width or inspects `min-w-`, so the mobile findings below are not
  regression-protected by anything.

## The auth surface is in flight and carries no findings

The brief names `lib/authn/**`; the path is `lib/auth/**` and it is still entirely Clerk
(`lib/auth/clerkRuntime.tsx`, `lib/auth/clientRealm.tsx`, `lib/auth/adminRealm.tsx`,
`@clerk/nextjs 7.7.4` in `apps/web/package.json`). `docs/AUTH-MIGRATION.md` does not exist
yet. A sibling agent is moving the realm layouts onto first-party auth and deleting Clerk,
so **no finding is recorded against session handling, the single-flight refresh, the
restore deadline, or the realm guards** — reporting the Clerk shape as settled state would
be reporting work that is being deleted as it is read. What was read and found sound *as
Clerk code* is listed under "Examined and clean".

---

## Findings

Count by severity: **Medium 5 · Low 4 · Informational 1 · High 0.**
Ranked. Nothing is padded — the codebase is heavily and honestly commented, and most of
the defect classes the brief lists (fail-open server verdicts, money through `Number()`,
empty-list-on-failure, silent mutations, optimistic updates without rollback) were looked
for specifically and **not found**; see "Examined and clean".

### F-1 · Re-opening a raw transcript is served from cache, so the second read writes no `audit_log` row — MEDIUM

`apps/web/src/app/c/[slug]/calls/[callId]/page.tsx:711-731` (`useRawTranscript`), driven
by `:103-104` and toggled at `:325`.

`GET /v1/calls/{id}/transcript/raw` writes an `audit_log` row *in the same transaction as
the read* — the file's own docstring says so at `:700-710`, and hard rule 5 plus
SURFACES §3.1 ("opening it writes an `audit_log` row … 'who listened to this call' is
answerable") are what that row exists for. But the read is a `useQuery` with
`staleTime: Infinity`, `refetchOnMount: false`, `refetchOnWindowFocus: false`,
`refetchOnReconnect: false`, keyed `["call-transcript-raw", orgSlug, callId]`. Those are
all correct choices for *not* re-exposing data on an automatic refetch. Their combined
side effect is that a **deliberate** re-open is also not a request.

User-visible consequence: an owner presses "Show full transcript" (audit row written),
presses "Hide full transcript", presses "Show" again — the unredacted text reappears with
no network call and **no second audit row**. The same holds for navigating to another call
and back within the QueryClient's `gcTime` (5 minutes, unset here so the library default
applies). The audit trail therefore records the first opening of a raw transcript and
under-reports every one after it, which is precisely the question a DPDP enquiry asks. A
lesser second effect: after "Hide", the unredacted turns stay in the JS heap for the life
of the page, because `enabled: false` keeps the observer subscribed rather than releasing
the entry.

This is also a **one-way-per-problem break inside one file**: the other audited read on
this same screen — `useRecordingLink`, `:734-742` — is correctly a `useMutation`, so it
cannot be cached and every press mints a fresh link and a fresh audit row. Two mechanisms
for one rule, and the older one is the one that lost the row.

**Proven or reasoned:** reasoned, from the query options and TanStack Query v5's documented
`staleTime`/`enabled` semantics. Proving it needs a test asserting a second fetch, which
this pass is not permitted to add.

**What would fix it:** make the raw transcript a mutation, exactly like `useRecordingLink`
— the request has a side effect, so it is not a query. Failing that, `gcTime: 0` plus an
explicit `refetch()` on each toggle-on, which keeps the shape but restores one request per
opening.

---

### F-2 · Seventeen of eighteen horizontal scroll containers cannot be reached by a keyboard — MEDIUM

Exactly one scroll container in the app is focusable: `src/lib/legal/document.tsx:115-128`,
which carries `tabIndex={0}` + `role="region"` + `aria-label`, with a comment calling it
"THE ONE PLACE a non-interactive element must take focus" and citing axe's
`scrollable-region-focusable` rule and the WAI technique behind it. Every other
`overflow-x-auto` in the product is a bare `<div>`:

| file:line | what scrolls |
|---|---|
| `src/app/c/[slug]/leads/page.tsx:822` | the leads table — the product's most-used screen |
| `src/app/c/[slug]/leads/page.tsx:911` | the leads board (`min-w-[960px]`) |
| `src/app/admin/page.tsx:163` | the client directory (`min-w-[880px]`) |
| `src/app/admin/health/page.tsx:137` | the client health board (`min-w-[760px]`) |
| `src/app/admin/holds/page.tsx:145` | the hold queue (`min-w-[760px]`) |
| `src/app/admin/qa-sampling/page.tsx:117` | the QA queue (`min-w-[860px]`) |
| `src/app/c/[slug]/quality/page.tsx:207`, `:253` | QA reports |
| `src/app/c/[slug]/integrations/page.tsx:280` | the delivery log (`min-w-[500px]`) |
| `src/app/c/[slug]/lead-sources/page.tsx:423` | the ingest activity view (`min-w-[820px]`) |
| `src/app/c/[slug]/performance/page.tsx:334` | the busiest-hours chart (`min-w-[620px]`) |
| `src/app/admin/tenants/[tenantId]/commercials/page.tsx:503` | plan-row history |
| `src/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/page.tsx:1375` | prompt version history |
| `src/app/admin/tenants/[tenantId]/credits/page.tsx:1418`, `:1478` | the credit ledger |
| `src/components/invoiceDocument.tsx:124` | the invoice line items (`min-w-[600px]`) |

User-visible consequence: a keyboard-only user on any viewport narrower than the table
(every phone, and a 1280px laptop on the 960px board with the sidebar open) **cannot reach
the right-hand columns of any table in the product**. There is no key that scrolls a
non-focusable div. On the credit ledger and the invoice that is the money columns; on the
leads table it is whatever the column chooser put on the right.

axe cannot see this: `tests/a11y.ts:79-101` disables `color-contrast` because jsdom has no
layout, and the same absence of layout means axe cannot determine that any of these
containers *is* scrollable, so `scrollable-region-focusable` never fires. The gate is green
on all eighteen.

**Proven or reasoned:** proven by exhaustive grep — the table above is every
`overflow-x-auto`/`overflow-auto` in `src/`, cross-checked against every `tabIndex` in
`src/` (five sites: two modal panels, one drawer, one comment, and `document.tsx`).

**What would fix it:** the pattern already exists and is argued in `document.tsx`. One
shared `<ScrollRegion>` wrapper carrying `role="region"` + `tabIndex={0}` + an
`aria-label` from the table's caption, with every one of the seventeen sites moved onto it
in the same change.

---

### F-3 · No skip link, in either shell — MEDIUM

`src/app/c/[slug]/layout.tsx:398-418` and `src/app/admin/layout.tsx:601` both render
`Sidebar` → `ViewAsBanner` → `TopHeader` → `<main>`. There is no "skip to content" control
anywhere in `apps/web` (`grep -rn "skip"` across `src/app/layout.tsx`,
`src/app/globals.css` and both shells returns nothing but an unrelated prose match).

User-visible consequence: the client sidebar is 21 links across four groups, the admin
sidebar 7, plus the collapse and drawer buttons and the notification bell. A keyboard or
screen-reader user pays that Tab cost on **every page navigation**, on every one of ~30
screens. WCAG 2.4.1 Bypass Blocks is Level A.

`tests/a11y.ts:70-73` names this explicitly as something the gate cannot check: `bypass`,
`region`, `landmark-one-main` and `page-has-heading-one` are document-level rules and the
sweep scans a detached container, so axe reports them inapplicable.

**Proven or reasoned:** proven by absence; the routing shape is read directly from both
layouts.

**What would fix it:** one visually-hidden-until-focused anchor as the first child of each
shell, targeting an `id` on the existing `<main>`. Both shells, same change — the client
realm's `<main>` is `layout.tsx:413`, the admin realm's is in the same position.

---

### F-4 · The sidebar's "you are here" is exact-match while the header title is longest-prefix, so no nav entry is current on any detail route — MEDIUM

Client realm: `src/app/c/[slug]/layout.tsx:128-137` computes the header title by
longest-prefix match (`pathname === item.href || pathname.startsWith(item.href + "/")`),
and `:155` computes the sidebar highlight as `pathname === item.href`.
Admin realm: the identical split at `src/app/admin/layout.tsx:183-191` versus `:225`.

The `aria-current="page"` attribute is bound to the exact-match variable
(`src/app/c/[slug]/layout.tsx:163`, `src/app/admin/layout.tsx:266`).

User-visible consequence, on every detail route in the product:

- `/c/<slug>/calls/<callId>` — header reads "Call logs", sidebar highlights nothing.
- `/c/<slug>/leads/<leadId>` — header reads "Leads", sidebar highlights nothing.
- `/admin/tenants/<id>` and its seven children (`/kyc`, `/credits`, `/commercials`,
  `/invoice`, `/lifecycle`, `/feature-flags`, `/first-campaign-review`,
  `/agents/<id>/prompt`) — header reads "Clients", sidebar highlights nothing.
- `/admin/qa-sampling/<sampleId>` — header reads "QA sampling", sidebar highlights nothing.

A sighted user loses the location cue exactly on the deep screens where it is most needed;
a screen-reader user gets **no `aria-current="page"` on any element in the document**, so
"where am I" is unanswerable from the navigation. The client layout's own header comment
(`:47-51`) states the doctrine this breaks: "the nav is ONE list that both the sidebar and
the page title read (a second copy is how a renamed screen keeps its old title in the
header)". It is one list read two different ways, which is the same defect one level down.

The admin file even relies on the prefix rule in prose — `:159-160` explains that
`/admin/ops/dnc` "keeps this name instead of inheriting 'Operations'" — while the
highlight beside that title is computed by the other rule.

**Proven or reasoned:** proven by reading both files; the two expressions are four lines
apart in each.

**What would fix it:** one `currentItem(pathname)` helper per shell returning the winner,
with both the title and the highlight reading it — so `aria-current` and the heading can
never name different screens. Note the helper cannot be exported from a `layout.tsx`
(Next's route typing forbids it, as the admin file's own comment at `:178-181` records), so
it wants a sibling module both layouts import.

---

### F-5 · The leads search box puts a customer's phone number into a GET query string — MEDIUM

`src/app/c/[slug]/leads/page.tsx:535-543` is an input whose placeholder is
**"Name or last digits"**. It feeds `lensQuery` (`src/lib/api/leads.ts:246-268`), which
writes it as `search=` into three request URLs: `GET /v1/leads?search=…`
(`leads.ts:279`), `GET /v1/leads/facets?search=…` (`:300`), and — a write —
`POST /v1/leads/bulk?search=…` (`:388`).

The server side confirms this is a phone field, not merely a name field:
`apps/api/crm/service.py:468-473` builds
`(l.name ILIKE :search OR l.phone_e164 LIKE :phone_suffix)` with
`phone_suffix = "%" + search`. A client who pastes a full E.164 number into that box gets a
hit, and the full number is then in the request line.

User-visible consequence: the number lands in nginx access logs, in Cloudflare's logs and
in any proxy between — the exact hazard SURFACES §2c's closing paragraph names as the
reason `POST /v1/dnc/check` and `POST /v1/compliance/messaging-consent/lookup` take the
number in a **body**: "a number in a URL lands in access logs, proxy logs, referrers and
browser history (hard rule 6)". `lib/api/messagingConsent.ts:12-17` makes the same argument
in the console's own words. This one screen is the exception, and it is the screen a client
uses all day.

Two mitigations that are already right and worth stating so the finding is not overstated:
the search term is held in React state and never written to the browser URL, so history and
`Referer` are clean; and the term reaches the TanStack cache key only in memory
(`leads.ts:279`). The leak is server-side request logging only.

**Proven or reasoned:** the URL construction is proven by reading; the phone-matching
half is proven from `apps/api/crm/service.py:471`. That the deployment's access logs
retain full request lines is reasoned from the standard nginx `combined` format, not
verified against `infra/nginx/`.

**What would fix it:** three shapes, in descending order of how much they move. Give the
leads lens the same POST-with-body treatment the two compliance lookups already have
(consistent with the stated doctrine, largest change); or split the box into a name term
and a digits term and send the digits as a salted suffix hash the server can match; or
leave the API alone and redact `search` from the access-log format in `infra/nginx/`,
which fixes the leak without fixing the inconsistency. This one is **shared with the API's
route shape** and is not purely a frontend decision.

---

### F-6 · The leads table's two inline edit controls are about 20 CSS px tall — LOW

`src/app/c/[slug]/leads/page.tsx:458` (the status `<select>`) and `:464` (the owner
`<select>`) are both styled
`rounded-md border border-transparent bg-transparent px-1 py-0.5 text-xs`. `text-xs` is
12px text on a 16px line box; `py-0.5` adds 2px each side. Rendered height ≈ **20px**, under
WCAG 2.2 SC 2.5.8 Target Size (Minimum), which is 24×24 at Level AA.

User-visible consequence: on a phone, the two controls a client uses most — move a lead's
stage, reassign its owner — are a 20px-tall tap target inside a horizontally scrolling
table. Mis-taps on a status select change a lead's stage, which is a write, and the row's
failure surface (`RowFailure`) only speaks after a *failed* write, not after a wrong one.

SC 2.5.8 has a spacing exception: the target passes if a 24px circle centred on it does not
intersect another target's circle. Whether these two qualify depends on the rendered cell
padding, which nothing in this repo measures — see F-7.

**Proven or reasoned:** the class strings are proven; the rendered height and the spacing
question are reasoned, not measured.

**What would fix it:** `py-1.5` on both (28px, clears the minimum) with the visual
compactness preserved by the transparent border the class already carries, or an explicit
`min-h-[24px]`. Either wants the measurement in F-7 to keep it.

---

### F-7 · There is no `tests/responsive.test.ts`, so nothing guards the mobile surface — LOW

`apps/web/tests/` contains 83 suites and none of them renders at a viewport width, sets
`window.innerWidth`, or inspects `min-w-` classes. `grep -rn "320\|overflow-x\|min-w-"
apps/web/tests/` matches two files, both on unrelated substrings. Nothing in `docs/`
references such a test either.

Consequence: the fifteen `min-w-[…]` sites in `src/` are unguarded, F-2's seventeen bare
scroll containers are unguarded, and F-6 cannot be settled because nothing measures a
rendered target. The next wide table added is free to ship without a scroll container at
all — which is what already happened to `src/app/admin/ops/page.tsx:1180`, `:1367` and
`:1616`, three tables with no `overflow-x-auto` around them. (Those three are **not** a
finding on their own: each has two or three narrow numeric columns and fits at 320px. They
are evidence that the rule is not enforced.)

**Proven or reasoned:** proven by exhaustive listing of `apps/web/tests/`.

**What would fix it:** the test the brief already describes — assert that every `min-w-`
in a rendered screen sits inside an ancestor carrying `overflow-x`, and (once F-2 lands)
that the ancestor is focusable. jsdom can answer both from the class strings without
layout, which is why this is cheap.

---

### F-8 · Delivery-log rows are keyed on a pair that is not their identity, and the suite already renders the collision — LOW

`src/app/c/[slug]/lead-sources/page.tsx:441` keys each row
`` `${item.lead_source_id}-${item.event_key}` ``, above a comment asserting "one inbox row
per (source, sender's id) by unique constraint".

That is not what the server sends. `apps/api/ingest/routes.py:747-751` maps **both**
`ingest:{id}` and `meta:{id}` provider keyspaces onto the *same* `lead_source_id` and the
*same* source name, and `IngestActivityItemOut` (`:766-772`) carries neither the provider
string nor the prefix. So the row's real identity is `(provider, event_key)` and the
console is handed only the half that cannot distinguish the two keyspaces.

`apps/web/tests/leadSources.test.tsx:161-175` renders it: the run prints
`Encountered two children with the same key,
018f3c00-0000-7000-8000-000000000002-lead.created:website_form` and passes anyway. React's
documented behaviour on duplicate keys is that children "may be duplicated and/or omitted"
— on the delivery log that is a row a client is looking at to find out whether their form
reached us.

In production a collision needs an `ingest:` body digest equal to a Meta `leadgen_id`,
which will not happen. So this is ranked LOW on likelihood, not on consequence — but the
fix is one field and the fixture proves the render path is unguarded.

**Proven or reasoned:** proven — the warning is emitted by the green suite run recorded at
the top of this document.

**What would fix it:** add the keyspace prefix (or the raw `provider` string) to
`IngestActivityItemOut` and key the row on it. The route already has the value in hand at
`:748`; it is discarded on the way out.

---

### F-9 · Three client-realm query keys omit the org slug — LOW

`src/lib/api/hooks.ts:222` (`["callback-check", callId]`), `src/lib/api/campaigns.ts:176`
(`["campaign-check", campaignId]`) and `:184` (`["campaign", campaignId]`). Every other
client-realm key in `src/lib/api/` carries `session.orgSlug` — `firstCampaign.ts:234` even
states the reason in a comment: "Keyed by org slug, like every other client-realm query, so
a D-22 operator switching accounts never reads the previous tenant's answer out of the
cache."

Consequence today: none. Call ids and campaign ids are uuid_v7, so two tenants cannot
collide, and this is **not** a live hard-rule-1 failure. What it costs is that the
impossibility rests on the id generator rather than on the cache key, in a QueryClient that
genuinely does hold more than one tenant's data at a time — an operator following
"View as client" from `/admin` into tenant A, back out and into tenant B, does so inside
one `QueryClient` instance (`src/app/providers.tsx:16`, created once per shell mount).

**Proven or reasoned:** proven by reading all 118 `queryKey` sites; these three are the
only client-realm keys without a tenant discriminator. (Admin-realm and platform-scoped
keys — `["admin","me"]`, `OPS_*`, `voiceKeys.catalogue`, `QA_SAMPLES_QUERY_KEY` — are
correctly global and are not counted.)

**What would fix it:** the same `(org, id)` shape the other keys already use, and the
matching change at the four `invalidateQueries` sites that reference them
(`hooks.ts:240`, `campaigns.ts:127-128, 165-166, 209-211, 230-233, 310-312, 348-350,
402-404`).

---

### F-10 · The brief's evidence references cannot be resolved — INFORMATIONAL

Recorded above under "Two premises". Not a defect in `apps/web`; it is stated as a finding
because it means **this audit cannot claim to have verified the nine designed-out frontend
defects**, and a reader would otherwise assume it did.

---

## Examined and found clean

Listed so the absence of a finding is a statement rather than a gap.

**Correctness against the API.** Every `?? false` / `?? true` in `src/` was read
(13 sites). All but one are *comments explaining why the coalesce is absent* — the pattern
is a named defect class here (BUILD-LOG §52) and is actively hunted. The two live ones are
`aiQuota.ts:57` (`options.enabled ?? true`, a hook option) and `focusTrap.ts:117` (a DOM
containment test). Server verdicts govern everywhere they were checked: `is_verified`
(`c/[slug]/verification/page.tsx:387,391,409,450`), `messageable`
(`c/[slug]/messaging-consent/page.tsx:497`, `settings/alerts/page.tsx:98`), `held`
(`lib/api/firstCampaign.ts`, fails closed on an unrecognised rule), `blockers`
(`c/[slug]/campaigns/page.tsx:700`, `admin/new/IntakeStep.tsx:759-766`), `published`
(never inferred from `status`), `stops_dialling`, and the bulk-action `scope` and counts
(`leads/BulkActionBar.tsx:400-409`, which derives `failed` from the server's invariant
rather than from an optional array's length).

**Money.** No money value is parsed. Every `Number(` in `src/` was read: they are on
minute counts, concurrency, percentages, a range input, and two comparisons that decide
which header to send (`commercials.ts:166`, argued in place, with the server repeating the
comparison in `Decimal`). `formatINR` reads digits off the string. Six separate files carry
the `Number("10159.00") → 10158.999999999998` warning. Hard rule 7's frontend shadow holds.

**Error and empty states.** Loading is a `Skeleton` (which announces itself —
`ui.tsx:435`), failure is a `ProblemNotice` (277 sites), and the "failure renders as an
empty list" defect is specifically defended against: `do-not-call/page.tsx:174`,
`settings/team/page.tsx:95`, `admin/ops/dnc/page.tsx:126` and `knowledge/page.tsx:49` all
read `.data` rather than `.data ?? []` with the reasoning written beside them, and
`leads/page.tsx:482` guards on `Boolean(leads.data)` so a failed first load shows no rows.
`useWriteAccess` (`hooks.ts:110-136`) and `adminAccess` (`admin/access.ts:114-137`)
distinguish "the server refused" from "we could not ask", and fail in opposite directions
for controls versus navigation, on purpose.

**Optimistic updates.** There are none — zero `onMutate` in `src/`. The two `setQueryData`
calls (`caps.ts:63`, `aiQuota.ts:85`) write the server's own response body through, so
there is nothing to roll back.

**Refetch loops and requests in render.** No `useEffect` in `src/app` depends on a query
result; the six dependency arrays are on local state (`[search]`, `[lensKey]`,
`[selection]`, `[editing]`, `[contacts]`). No `fetch` outside `lib/api/client.ts`.

**Leaks.** Zero `localStorage`, `sessionStorage`, `document.cookie`, `console.*` and
analytics calls in `src/`. No token, code, email or phone in any log. The CSV export is
fetched with session headers and handed over as a blob rather than linked
(`leads.ts:403+`), so no credential rides a URL. `LeadOut` carries only `phone_masked` and
the table renders nothing else (`leads/page.tsx:446-450`). The engine's recording URL never
reaches the browser; the player takes a presigned link and re-mints once on expiry
(`callAudioPlayer.tsx:161-183`).

**Modals and focus.** Both modals — `navDrawer.tsx` and `aiExtraDialog.tsx` — use the one
`useFocusTrap` (`lib/focusTrap.ts`), which moves focus in, cycles Tab/Shift+Tab against a
re-queried list, handles Escape from a `document` listener, and restores focus to the
opener with `isConnected`/`!== body` guards. Its own known limit (the page behind is not
`inert`) is stated rather than hidden. No third overlay exists.

**Icon-only controls.** Every icon button read carries an `aria-label` — the drawer's
close/collapse/expand, the notification bell, and all six player controls, with every
decorative icon `aria-hidden`. `StatusBadge` (`ui.tsx:176-188`) prints the status text
beside the colour, so colour is not the only signal there.

**Live regions.** Every `role="status"` / `role="alert"` site was checked for being
conditionally mounted; all are. Nothing announces continuously and nothing announces
nothing.

**Auth, as Clerk code.** `lib/auth/mode.ts` guards the dev credential twice and refuses an
unknown mode rather than defaulting; `lib/api/client.ts:151-162` re-checks at credential
time; `sendRequest` fails closed when `impersonateOrg` is set without a grant
(`:300-306`); both credentials are resolved per request rather than captured. Recorded as
sound *for the code that exists*, and superseded by whatever the migration lands.

---

## What was proved versus reasoned

**Proved** (observed in a run, or exhaustive over the source): F-2 (every scroll container
and every `tabIndex` in `src/`), F-3 (absence), F-4 (both expressions, both files), F-7
(absence across 83 suites), F-8 (React warning emitted by the green suite), F-9 (all 118
`queryKey` sites), F-10, and the whole "Examined and clean" section.

**Reasoned** (read carefully, consequence derived rather than executed): F-1 (from
TanStack Query v5 caching semantics — a proving test is exactly the fix's own regression
test and this pass may not add files), F-5 (URL construction and the SQL are both proven;
the access-log retention is inferred, not read out of `infra/nginx/`), F-6 (class strings
proven; rendered geometry and the SC 2.5.8 spacing exception not measured).
