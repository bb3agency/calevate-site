# UX audit — entry, auth, and product-wide cross-cutting

**Lane:** entry/auth journey + navigation & IA + shared primitive library + global states +
a11y/responsive posture.
**Date read/audited:** 25 August 2026.
**Method:** read-only. Nothing in this lane was edited. Every claim below cites a file and
line in this tree as it stood on 25 Aug 2026, or an external source with the URL and the
date it was read.

## Evidence classes used here

Per CLAUDE.md hard rule 11, external claims carry their source; repo-internal claims are
labelled as observations of this tree, not as facts about the world.

- **MEASURED-IN-TREE** — I ran the grep/find myself this session; the command is stated.
- **EXTERNAL, READ 25 Aug 2026** — a design-guidance source I retrieved this session.
- **UNKNOWN** — stated as unknown, never filled with a guess.

⚠ **Egress limits, stated rather than hidden.** Direct fetches to
`design-system.service.gov.uk`, `www.nngroup.com`, `www.w3.org`, `pages.nist.gov` and
`technology.blog.gov.uk` are **blocked by this machine's egress proxy** (each returned
`EGRESS_BLOCKED`, measured 25 Aug 2026). Where a source is cited below it was obtained via
web SEARCH, which returns the search engine's synthesis of those pages rather than the page
itself. That is a weaker evidence class than reading the page, and it is marked as such at
each use. Nothing below states a statistic, a percentage or a study result — only the
directional guidance the search results reported, which is what the findings actually lean
on.

---

## Top 5 to fix first

1. **The acquisition funnel dead-ends on a default deployment — there is no way to contact
   Calevate.** (F-1, blocker)
2. **There is no `not-found.tsx`, no `error.tsx` and no `global-error.tsx` anywhere under
   `app/` — 71 routes with no error boundary and no styled 404.** (F-21, blocker)
3. **`ui.tsx` has no field primitive, so 176 raw `<input>` elements across 46 files
   hand-roll label/description/error wiring. This is the root cause of the product's
   inconsistency.** (F-15, blocker)
4. **`components/interior/` is 5,855 lines across 19 modules and 18 of them have zero
   importers** — a whole design system built and never wired, while routes hand-roll the
   same jobs. (F-14, blocker)
5. **`EmptyState` has no action slot, so all 51 empty states in the product are
   structurally dead ends** — the primitive cannot express "and here is the button that
   creates the first one". (F-18, major)

**Count by severity:** 4 blocker · 14 major · 9 minor (27 findings).

---

## (a) Entry and auth routes

### F-1 — BLOCKER — the whole acquisition funnel ends with no way to reach a human

**Where:** `apps/web/.env.example:70,73` · `apps/web/src/lib/api/signup.ts:126,132` ·
`apps/web/src/app/signup/page.tsx` (`SignupClosed`, `NeedsAnAccount`) ·
`apps/web/src/app/page.tsx:448,1017,1064`

**What is wrong.** The shipped defaults are

```
NEXT_PUBLIC_SELF_SERVE_SIGNUP_ENABLED=false      # .env.example:70
NEXT_PUBLIC_SIGNUP_CONTACT_EMAIL=                # .env.example:73 — EMPTY
```

and `signup.ts:132` reads `?? ""`. Every contact affordance in the product is guarded on
that value being non-empty:

- `app/page.tsx:1047` — `{!SIGNUP_OPEN && SIGNUP_CONTACT_EMAIL && …}`
- `app/page.tsx:1069` — `{SIGNUP_CONTACT_EMAIL && …}`
- `app/signup/page.tsx` `NeedsAnAccount` — `{SIGNUP_CONTACT_EMAIL && …}`
- `app/signup/page.tsx` `SignupClosed` — `{!deferred && SIGNUP_CONTACT_EMAIL && …}`

MEASURED-IN-TREE: `grep -rn "mailto:" src/app src/components` returns **four hits, all four
of them that same variable**. There is no `/contact` route (`find app -name page.tsx`
returns 71 files, none of them contact), no phone number, no enquiry form.

So on a default-configured build the journey is: homepage hero CTA "Get a workspace"
(`page.tsx:448`) → `/signup` → a Card that says *"Calevate does not open accounts online
yet… Talk to us and we will set your workspace up with you."* — and then nothing. The
sentence names an action the screen provides no means to take. The one remaining link on
that panel is `/c/your-slug` rendered as inert `<code>`, addressed to people who already
have a workspace.

**Why.** A closed door is fine; a closed door with no bell is a dead end, and this is the
dead end at the top of the only funnel the business has. The page's own docstring
(`signup/page.tsx:66-79`) argues correctly that a closed deployment must say so *before*
the form rather than after it — that reasoning is right and is undone by the contact half
being optional. NN/g's empty-state guidance (EXTERNAL, via web search 25 Aug 2026,
nngroup.com "Designing Empty States in Complex Applications: 3 Guidelines") is that a
state with no content must still *provide a direct path to the next meaningful action*;
here the next meaningful action exists in prose only.

**Fix.**
1. Add `apps/web/src/app/contact/page.tsx` — a real route in the marketing language with
   whatever channels genuinely exist (email, WhatsApp number, a form posting to an
   existing API endpoint). It is in-repo and needs no vendor.
2. Make the closed/stranger panels link to it **unconditionally**; keep the mailto as an
   additional affordance when `SIGNUP_CONTACT_EMAIL` is set, not as the only one.
3. Add a guard to `apps/web/tests/signupClosed.test.tsx`: with `SIGNUP_OPEN=false` **and
   `SIGNUP_CONTACT_EMAIL` unset**, assert the rendered panel contains at least one
   `<a href>` or `<button>`. That is the assertion whose absence let this ship.

This is an "ours" task end to end — no legal entity, no vendor, no regulator gates it.

---

### F-2 — MAJOR — a signed-in user cannot change their own password

**Where:** `apps/api/authn/routes.py` (route summaries, lines 345-649) ·
`apps/web/src/app/(auth)/auth/account/page.tsx` ·
`apps/web/src/app/(auth)/auth/admin/page.tsx`

**What is wrong.** MEASURED-IN-TREE: `grep -n 'summary="' apps/api/authn/routes.py`
enumerates 14 routes — sign-in, OTP, refresh, logout, logout-everywhere, reset-request,
reset-confirm, email-verify send/spend, step-up send/answer, bootstrap, invitation-accept.
There is **no authenticated change-password route**, and
`grep -rn "changePassword\|change-password" apps/web/src/lib/authn/` returns nothing.

The consequence on screen: `/auth/account` offers *Sign out*, *Sign out everywhere* and
email verification, and nothing else. A person who wants to change their password — because
staff turned over, because they typed it into the wrong window, because a phone was lost —
must sign out, use "I have forgotten my password", wait for an email, and spend a link that
`reset-password/page.tsx:44-46` correctly warns *"also signs you out everywhere else, on
every device."*

**Why.** Changing a password is a routine, non-incident task; routing it through the
account-recovery path makes a routine task cost a mass logout of every colleague on the
account. For the target user — an SMB owner whose receptionist shares the console — that is
a disincentive to rotate a credential, which inverts the security intent. It is also a
task users go looking for: its absence from the one page named "Your account" reads as a
missing feature, not a policy.

**Fix.** `POST /v1/auth/{realm}/password` taking `{current_password, new_password}`,
re-verifying the current password with the same Argon2id path, revoking **other** sessions
but keeping the caller's; a `Card` on both account pages using the existing
`SetPasswordForm` shape plus a current-password field. Reuse `lib/authn/password.ts`
bounds so the third form cannot drift from the other two.

---

### F-3 — MAJOR — the two account pages are flat card stacks whose top card carries no task, and both are dead ends

**Where:** `apps/web/src/app/(auth)/auth/account/page.tsx:67-131` (133 lines) ·
`apps/web/src/app/(auth)/auth/admin/page.tsx` (160 lines) ·
`apps/web/src/components/authPage.tsx:31-48`

**What is wrong.** Three `Card`s of identical visual weight, in this order:

1. A `Card` wrapping a `NoticeBox` wrapping the sentence "You are signed in" and the
   session lifetimes (lines 69-82). **Zero actions.** It occupies the most valuable
   position on the page.
2. Email verification — the only card that is ever urgent, and it is second.
3. Sign out / Sign out everywhere.

This is the founder-flagged "flat undifferentiated `Card` stack" defect, in miniature and
in my lane. It is also a double border: a `NoticeBox` (which has its own border and tone
background, `ui.tsx:359-392`) nested directly inside a `Card` (which has `border-line` too,
`ui.tsx:46-49`).

Separately, **there is no route back to the console from either page.** `AuthPageFrame`'s
only outbound link is the wordmark → `/` (`authPage.tsx:35`), the *marketing* homepage. A
signed-in owner who lands on `/auth/account` has to know to type `/c` or use the back
button. The repo already fixed exactly this shape of bug twice — `/c/page.tsx:9-13` and
`admin/sign-in/page.tsx:44-49` both record "the reward for signing in was a dead end" — and
the fix was applied to the sign-in destinations, not to the account pages themselves.

**Why.** Cards of equal weight give the reader no ranking, so the eye has to read all three
to find the one that matters. A page whose only exits are "sign out" and "the public
website" is a dead end by the plain definition.

**Fix.**
1. Reorder: verification first (and only render it at all when `email_verified === false`
   — a green "verified" panel is a status line, not a card).
2. Demote card 1 to a single `text-sm text-ink-muted` line under the `<h1>`.
3. Add an optional `backTo` prop to `AuthPageFrame` and pass `/c` (client) / `/admin`
   (admin) from the two account pages and the two reset pages. `/c` already resolves the
   slug (`app/c/page.tsx`), so no new lookup is needed.
4. Fold the nested `NoticeBox`-in-`Card` into one container (see F-19).

---

### F-4 — MAJOR — no show/hide password control anywhere; three forms ask for the password twice instead

**Where:** `apps/web/src/components/authn/setPasswordForm.tsx:131-151` (used by
`/auth/reset-password`, `/auth/admin/reset-password`, `/auth/accept-invitation`,
`/auth/admin/bootstrap`) · `apps/web/src/components/authn/fields.tsx:32-82`

**What is wrong.** `AuthField` renders a bare `<input type="password">`. MEASURED-IN-TREE:
no reveal control exists in `src/components/` — and `components/interior/floating-label.tsx`
(280 lines, with a reveal-shaped input abstraction) has **zero importers**. Every password
form compensates with a "Type it again" confirmation field.

**Why.** EXTERNAL, via web search 25 Aug 2026 (results for the GOV.UK Design System
passwords pattern, `design-system.service.gov.uk/patterns/passwords/`; the page itself is
egress-blocked here): the show-password component *"is now live on GOV.UK Accounts and has
allowed them to remove all 'confirm password' inputs"*, and the reported motivation is that
users asked for it and that it particularly helps *"users who experience difficulty when
typing"*. That is the exact population BRD names — an SMB owner on a low-end Android
keyboard, typing a 12-character minimum.

The confirmation field is the more expensive half of the trade: it doubles the typing on a
touch keyboard, and this codebase's own docstring (`setPasswordForm.tsx:22-29`) justifies it
only as insurance against an unrecoverable typo — which a reveal toggle removes more
directly.

**Fix.** Add `PasswordField` to `ui.tsx`: `AuthField` plus a `<button type="button">`
toggling `type` between `password` and `text`, with `aria-pressed`, a label that changes
("Show password" / "Hide password"), and a distinct accessible name per field on any page
carrying two of them. Then delete the confirmation field from `setPasswordForm.tsx` and its
`mismatch` state. This also removes F-5.

---

### F-5 — MAJOR — the confirmation field errors on the first keystroke, while the field above it correctly waits for submit

**Where:** `apps/web/src/components/authn/setPasswordForm.tsx:98,140,150`

```ts
const mismatch = confirmation !== "" && confirmation !== password;   // :98
…
error={attempted ? lengthProblem : null}                             // :140  ← waits
error={mismatch ? "These two do not match." : null}                  // :150  ← does not
```

**What is wrong.** Typing the first character of "Type it again" produces a red
`role="alert"` message — announced immediately by a screen reader, on every keystroke until
the two strings converge. The password field directly above it gets this right (`attempted`
gates it, and line 80's comment explains exactly why: *"so the field is not red before it
is touched"*). One component, two validation timings, four characters apart.

**Why.** WCAG 2.2 SC 3.3.3 Error Suggestion (Level AA) — EXTERNAL, via web search 25 Aug
2026 for the W3C Understanding document; w3.org is egress-blocked here — requires that when
an input error is detected, *suggestions for correction are provided*. An error fired
mid-entry is not describing an error the user has made; it is describing an entry they have
not finished. It also fights the `role="alert"` on `fields.tsx:76`, which exists to announce
real failures and is here spending itself on noise.

**Fix.** Track a `confirmationBlurred` flag (or reuse `attempted`) and gate line 150 the
same way line 140 is gated. If F-4 is taken, the field and this finding both disappear.

---

### F-6 — MAJOR — every auth submit button is `disabled` until the form validates

**Where:** `signInForm.tsx:258,266,330` · `setPasswordForm.tsx:158` ·
`resetRequestForm.tsx:100` · `account/page.tsx:107,119`

**What is wrong.** e.g. `disabled={signIn.isPending || email.trim() === "" || password === ""}`
and `disabled={submit.isPending || !canSend}` where `canSend` requires the confirmation
field to be non-empty *and* matching. A person who cannot work out why the button will not
respond is given no sentence explaining it.

**Why.** EXTERNAL, via web search 25 Aug 2026 (GOV.UK Design System button guidance /
GOV.UK practitioner guidance): GOV.UK avoids disabling buttons — if the user submits a form
with a problem they get a useful error message telling them how to fix it, because disabled
buttons are hard to make accessible for people with low vision and cannot easily be focused
with a keyboard. The repo's own `contrast.test.ts` (which measures the token palette at
4.5:1) does **not** measure the disabled state of `PRIMARY_BUTTON` (`ui.tsx:408`), so the
contrast of these buttons in their disabled costume is UNKNOWN in this tree.

The *pending* half of these guards is different and correct — a button disabled while a
request is in flight is describing a real, momentary system state, and the forms also carry
the belt-and-braces `if (isPending) return` single-flight guard (`signInForm.tsx:210`),
which is the right pattern.

**Fix.** Split the two conditions. Keep `disabled` for `isPending` only. For validity, let
the button submit and render the reason: `setAttempted(true)` already happens on submit in
`setPasswordForm.tsx:113`, so the field-level messages are one line away from being the
whole answer. On `signInForm` add a summary sentence ("Enter your email address and
password.") through the existing `AuthProblemNotice` slot.

---

### F-7 — MINOR — `/invite` strands a live single-use credential if JavaScript does not run

**Where:** `apps/web/src/app/invite/page.tsx:43-60`

**What is wrong.** The redirect happens only inside `useEffect`. If hydration fails, if the
JS bundle 404s, or if a corporate mail client's in-app browser blocks scripts, the holder of
a working invitation sees `<Skeleton rows={3} label="Opening your invitation…" />` forever —
a pulsing placeholder with no link, no explanation and no timeout.

**Why.** The module docstring (`invite/page.tsx:16-19`) is explicit that this file exists
*precisely* because "a 404 would tell somebody holding a live, single-use credential that
their invitation is broken". An infinite skeleton says the same thing more slowly. The page
already accepts a small, one-off cost to protect that credential; a `<noscript>` is cheaper
than the cost it already paid.

**Fix.** Render a real anchor under the skeleton — `<a href={inviteLink(token)}>Continue to
your invitation</a>` — visually de-emphasised, plus the same link inside `<noscript>`. The
token is read from `location` in the same tick, so no extra state is needed. Add a 3-second
`setTimeout` that swaps the skeleton for the link if `replace` has not navigated.

---

### F-8 — MINOR — the six-digit code field is a plain text input, while a purpose-built OTP component sits unused

**Where:** `apps/web/src/components/authn/signInForm.tsx:238-250` ·
`apps/web/src/components/interior/otp-input.tsx` (481 lines, **0 importers**)

**What is wrong.** The OTP step renders `<AuthField label="Six-digit code" inputMode="numeric"
autoComplete="one-time-code" maxLength={16} …>`. `maxLength={16}` on a field the copy calls
"six-digit" is a small honesty gap of its own. Meanwhile `interior/otp-input.tsx` exports
`useOtpInput` / `OtpInput` with per-cell rendering, paste handling, arrow-key navigation and
an `OtpStatus` — MEASURED-IN-TREE:
`grep -rl "interior/otp-input" src tests` → **no files**.

**Why.** CLAUDE.md's "one way per problem, and migrate rather than accumulate". Two answers
exist; the screen uses neither deliberately — it uses the generic one because the specific
one was never wired.

**Fix.** Either adopt `OtpInput` at this one call site (it is the only OTP surface in the
product, so the migration is one file), or delete `otp-input.tsx`. Do not leave the third
state. Whichever way, set the length bound to 6 and stop advertising 16.

---

### F-9 — MINOR — no legal link on any auth, signup or console screen

**Where:** `apps/web/src/components/authPage.tsx` · `app/signup/page.tsx` ·
`app/c/[slug]/layout.tsx` · `app/admin/layout.tsx`

**What is wrong.** MEASURED-IN-TREE: `grep -rn "/legal" src/app src/components` outside
`lib/legal` returns **two** link sites — `app/legal/page.tsx:50` (the index linking its own
children) and `app/page.tsx:1108` (the marketing footer). Nothing else in the product links
to the privacy policy, terms, DPA or grievance page. Not the sign-in frame, not the signup
form where a person is about to create a workspace, not either console shell.

**Why.** `app/legal/page.tsx:10-13` names the audience precisely: *"a payment gateway's
onboarding reviewer, a client's procurement team and a regulator all land on"* it — and
none of them start from the marketing hero. The signup form in particular takes a business
name and a billing email with no terms link in view.

**Fix.** Add a small footer row to `AuthPageFrame` and to both shell layouts: `Privacy ·
Terms · Grievance`, sourced from `LEGAL_DOCUMENTS` so it cannot drift from the index.

---

## (b) Navigation and information architecture

### F-10 — MAJOR — 22 client nav items, all expanded, on day one

**Where:** `apps/web/src/app/c/[slug]/layout.tsx:74-138`

**What is wrong.** Four groups, no collapse, no state-dependence:

| group | items |
|---|---|
| (unnamed) | Dashboard, Campaigns, Agents, Call logs, Leads, Knowledge base, Performance, Quality |
| Operations | Needs attention, Campaign review |
| Compliance & data | Do not call, Messaging consent, Lead sources, Data rights, Your privacy notice |
| Settings & account | Team, Alerts, AI model, Integrations, Usage, Spend, AI help, Invoice, Verification |

An owner who has just redeemed an invitation (`accept-invitation/page.tsx:93` sends them
straight to `/c/<slug>`) sees all 22 at once, including *Messaging consent*, *Campaign
review*, *Data rights* and *Invoice*, before a single agent exists. The dashboard itself has
only two empty states (`c/[slug]/page.tsx:241,318`) and no first-run guidance —
MEASURED-IN-TREE: `grep -n "onboard\|checklist\|getting started\|Welcome"` over that file
returns nothing.

**Why.** Progressive disclosure: the first-run screen should teach what belongs here and
offer the one next action, not present the finished product's full surface. NN/g's
empty-state guidance (EXTERNAL, via web search 25 Aug 2026) frames the empty first screen as
the teachable moment — *communicate status, teach what belongs, give a direct path to the
next action*. Twenty-two equally-weighted destinations is the opposite: it makes the first
question "which of these is my job?" rather than "what do I do first?".

The individual placement decisions here are *well argued* — the comments at lines 109-135
reason carefully about why Alerts is not under Compliance and why Spend is not inside Usage,
and each argument is sound. The defect is not any one placement; it is that all of them are
visible simultaneously to someone with no basis to choose.

**Fix.** Two changes, both local to this file:
1. A first-run set. While the account has no published agent, render Dashboard, Agents,
   Knowledge base, Team — plus a persistent "Set up your first agent" primary action — and
   reveal the rest on first publish. The publish state is already known to this shell.
2. Make "Compliance & data" and "Settings & account" `<details>`-backed disclosure groups,
   closed by default, remembering their state. The heading markup already exists
   (line 264-271); only the wrapper changes.

---

### F-11 — MINOR — two sidebar rows share one icon

**Where:** `app/c/[slug]/layout.tsx:85` (`Quality`, `ShieldCheck`) and `:136`
(`Verification`, `ShieldCheck`)

**What is wrong.** Identical glyph, two destinations, same sidebar. In the collapsed
sidebar state (`isCollapsed`, line 197 hides the label and line 185 moves it to `title`) the
icon is the *only* differentiator, so the two rows become indistinguishable to a sighted
user scanning them.

**Fix.** `Verification` → `BadgeCheck` or `FileBadge`; leave `Quality` on `ShieldCheck`.
Add a one-line test asserting the icon set across `navigation(slug)` has no duplicates —
this is the class of defect that recurs every time a nav item is added.

---

### F-12 — MAJOR — the two realms are visually near-identical

**Where:** `app/admin/layout.tsx:779` vs `app/c/[slug]/layout.tsx:487` — both
`<div data-app-shell className="fixed inset-0 flex overflow-hidden bg-app font-sans">` ·
`components/authPage.tsx:38-41`

**What is wrong.** Same shell class string, same sidebar structure, same `NavDrawer`, same
tokens, same typography. On the auth screens the only difference is a 12px
`text-ink-faint` label reading "Client console" or "Operator console"
(`authPage.tsx:38-41`), sitting beside an identical lock glyph. There is no colour, no
badge, no title difference and no favicon difference between a realm that reads one
business's leads and a realm that can change money, switch off outbound calling and
impersonate a tenant.

**Why.** An operator working with both consoles open in adjacent tabs has almost nothing to
key on. The blast-radius asymmetry is already recognised elsewhere in this code — the admin
realm alone gets MFA (`signInForm.tsx:14-18`), step-up (`stepUpPrompt.tsx`) and a 30-minute
idle timeout against the client realm's 12 hours (`account/page.tsx:6-10`, quoting
"*because their blast radii differ by an order of magnitude*"). Every one of those controls
is invisible until it fires. The realm you are *in* should be visible before you act, not
after.

**Fix.** Give the admin shell a persistent, unmistakable marker: a 3px top rail in a
dedicated `--realm-admin` token, the word "Operator" in the header at readable size (not
`text-xs text-ink-faint`), a distinct `<title>` prefix, and a distinct favicon. Carry the
same rail into `AuthPageFrame` via the existing `realmLabel` prop — it already knows which
realm it is, it just does not spend the knowledge.

---

### F-13 — MINOR — `/c/[slug]/settings` is a segment with no page

**Where:** `app/c/[slug]/settings/{alerts,models,team}/page.tsx` — MEASURED-IN-TREE: no
`app/c/[slug]/settings/page.tsx` exists.

**What is wrong.** Three children under a parent segment that renders nothing. Today
nothing links to the bare path — but `accept-invitation/page.tsx:70` tells invitees in prose
to look under *"Settings → Team"*, which is the mental model that produces the URL guess,
and any stale bookmark or hand-edited URL lands on the unstyled default Next 404 (F-21).

**Fix.** `app/c/[slug]/settings/page.tsx` that `redirect()`s to `settings/team`. Three
lines, and it also makes the nav's mental model true.

---

## (c) Shared primitive library — what is missing, what is duplicated, what is dead

### F-14 — BLOCKER — an 5,855-line component library that nothing imports

**Where:** `apps/web/src/components/interior/` (19 modules)

MEASURED-IN-TREE (`grep -rl "interior/<name>" src tests`, excluding the directory itself):

| module | lines | importers |
|---|---:|---:|
| `toaster.tsx` | 416 | **7** |
| `otp-input.tsx` | 481 | 0 |
| `live-activity.tsx` | 474 | 0 |
| `dropdown.tsx` | 429 | 0 |
| `wizard-steps.tsx` | 424 | 0 |
| `tree-view.tsx` | 371 | 0 |
| `load-more.tsx` | 349 | 0 |
| `tabs.tsx` | 310 | 0 |
| `collapsible-banner.tsx` | 306 | 0 |
| `loading-button.tsx` | 282 | 0 |
| `pagination.tsx` | 281 | 0 |
| `floating-label.tsx` | 280 | 0 |
| `streaming-text.tsx` | 269 | 0 |
| `show-more.tsx` | 253 | 0 |
| `task-steps.tsx` | 232 | 0 |
| `new-items-pill.tsx` | 224 | 0 |
| `sticky-header.tsx` | 182 | 0 |
| `skeleton-swap.tsx` | 176 | 0 |
| `progress-bar.tsx` | 116 | 0 |

**18 of 19 are dead**, ~5,440 lines. No test imports them either. There is no barrel file
(`find src/components/interior -name "index*"` → nothing), so this is not an
export-indirection artefact.

**Why this is a blocker rather than a tidy-up.** CLAUDE.md: *"A route nobody mounted, a job
nobody registered, a column nobody reads and a migration nobody applied are not progress —
they are defects that look like progress on a screen."* This is the frontend instance, at
scale. It is actively harmful in two ways: it makes the library look richer than it is to
the next agent reading the tree, and it means the components routes *do* hand-roll
(F-15..F-20) get written next to working, tested, unused answers.

**Fix.** For each module, in the same change: **adopt it at its call sites, or delete it.**
Concretely — `tabs` into `admin/ops/page.tsx` (2,030 lines, hand-rolled panels),
`pagination` + `load-more` into `c/[slug]/leads` and `c/[slug]/calls`, `wizard-steps` into
`admin/new/IntakeStep.tsx` (1,004 lines), `otp-input` into `signInForm` (F-8),
`loading-button` everywhere a `{isPending ? "…" : "…"}` ternary appears (MEASURED-IN-TREE:
that pattern occurs on every mutation button in this lane alone). What is left after that
pass should be deleted, with the decision recorded.

---

### F-15 — BLOCKER — no field primitive; 176 raw `<input>` across 46 files

**Where:** `apps/web/src/components/ui.tsx:394-397` (only class *constants*, no component) ·
`apps/web/src/components/authn/fields.tsx:32-82` (`AuthField` — the right component, scoped
to auth)

MEASURED-IN-TREE: `grep -rc '<input' src/app` → **176 occurrences across 46 files**;
`<select>` → **64**.

**What is wrong.** `ui.tsx` exports `FIELD`, `FIELD_LABEL`, `FIELD_HINT` — three Tailwind
strings. It does not export a component that *wires them together*. So every one of those
176 inputs re-implements, by hand:

- `<label htmlFor>` ↔ `id` pairing (or does not — `tests/a11y.ts` says at length that axe
  **passes** an input whose only accessible name is a placeholder, so the green sweep is
  not evidence these are all labelled);
- `aria-describedby` composition across hint and error;
- `aria-invalid`;
- error placement, error styling, and whether the error waits for submit (see F-5, which is
  this defect appearing inside the one component that got it right).

`AuthField` does all four correctly in 50 lines, and it lives in `components/authn/` where
only six forms can reach it. `app/signup/page.tsx:70-77` contains a written-down admission
of the same problem one level down: *"THE FOLLOW-UP IS: move `FIELD`, `FIELD_LABEL`,
`FIELD_HINT`, `PRIMARY_BUTTON` and `SECONDARY_BUTTON` into `ui.tsx` and delete both
copies."* That follow-up was done for the constants and **not** for the component.

**Why this is the root cause the brief asked about.** The product has no design doctrine
doc, and the mechanism by which that absence becomes visible inconsistency is exactly this:
when the library offers a *class string* instead of a *component*, consistency becomes a
thing each author must remember rather than a thing the type system supplies. 176 chances
to remember.

**Fix.** Promote `AuthField` to `ui.tsx` as `Field` (unchanged behaviour, unchanged tests),
add `SelectField` and `TextAreaField` and `PasswordField` (F-4) on the same shape, re-export
`AuthField = Field` from `authn/fields.tsx` so the auth forms do not churn, then migrate the
46 files. Add a source guard in the style of `tests/responsive.test.ts`: a raw `<input>` in
`src/app/**` that is not `type="hidden"`/`type="checkbox"`/`type="radio"` is a violation
with a named exemption list, so the count can only go down.

---

### F-16 — MAJOR — no `Modal` primitive; three byte-identical dialog shells

**Where:** `components/authn/stepUpPrompt.tsx:132-137` ·
`components/authn/adminIdleTimeoutModal.tsx:118-123` · `components/aiExtraDialog.tsx:78-83`

All three open with the identical string
`"fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"` and then each
separately declares `role`, `aria-modal="true"`, `aria-labelledby`, and calls
`useFocusTrap`. MEASURED-IN-TREE: `grep -rn "fixed inset-0" src/app src/components` finds
exactly these three plus the two app shells and the nav drawer.

**Credit where due:** all three are currently *correct* — `role="alertdialog"` on the two
that interrupt, `role="dialog"` on the one that does not, labelled headings, focus traps.
This is not a bug report; it is a durability report.

**Why it still matters.** `components/navDrawer.tsx:59-65` records what happened last time:
the focus-trap idiom lived inline in the drawer, the header said the next modal should
borrow it, and *"The second one — `AcceptChargeDialog`, the control that debits a wallet —
did not, and shipped with no Tab cycling and no restore."* The hook was extracted; the
**shell** was not. Three copies of the shell is three chances for the fourth to be written
from the wrong one.

**Fix.** `Modal` in `ui.tsx`: props `{open, onClose, title, tone?: "dialog" | "alert",
children, footer}`; owns the overlay, the `role`, `aria-modal`, the generated
`aria-labelledby` id, `useFocusTrap`, and Escape. Migrate the three, delete the strings.

---

### F-17 — MAJOR — a strictly-enforced state rule with no primitive to satisfy it

**Where:** `apps/web/tests/surfaceStatesGuard.test.ts` (the rule) vs `components/ui.tsx`
(no helper)

**What is wrong.** `surfaceStatesGuard.test.ts` is an AST guard implementing BUILD-LOG §52 —
*"loading is a skeleton, failure is a refusal, and neither is a number, a state, or an empty
state"* — with six rules, and its docstring names nine real defects it exists to prevent
(an ops screen reporting "Outbound calling: running" off a read that failed; a campaigns
screen saying "no campaigns yet" over a 503; a dashboard showing 5,430 calls to a client
whose calls had stopped). It is one of the best pieces of engineering in this tree.

And there is **no component that implements the correct ladder.** MEASURED-IN-TREE:
`grep -rn "QueryState\|useEnvelope\|AsyncBoundary\|renderQuery" src` → **nothing**;
`isLoading` appears **137 times across 49 files**, and `.error`/`isError` **413 times**.
Every screen re-derives loading / failed / **paused-because-offline** / empty / ready by
hand.

The offline arm is the tell. Ten separate files carry separately-written prose explaining
the same TanStack behaviour:

- `admin/access.ts:175` — *"browser is offline reports `isLoading` false, so an offline console gets the screen and…"*
- `admin/health/page.tsx:116`, `admin/holds/page.tsx:123`, `admin/qa-sampling/page.tsx:90`,
  `admin/new/page.tsx:783`, `admin/operators/page.tsx:166,177`,
  `admin/tenants/[tenantId]/page.tsx:282`,
  `admin/tenants/[tenantId]/first-campaign-review/page.tsx:478`,
  `admin/tenants/[tenantId]/agents/[agentId]/prompt/page.tsx:185`

Ten authors independently rediscovering one vendor behaviour is the definition of a missing
abstraction.

**Fix.** `useEnvelope(query)` in `lib/` returning a discriminated union
`{kind: "loading" | "failed" | "paused" | "empty" | "ready", …}` — with `paused` derived
once, in one place, from `isPending && !isFetching && fetchStatus === "paused"` — plus an
`<Async>` component in `ui.tsx` taking `{query, skeletonLabel, empty, children}`. Then the
guard's six rules become mostly unreachable rather than merely enforced, and the ten
comments collapse to one.

---

### F-18 — MAJOR — `EmptyState` cannot hold an action, so all 51 empty states are dead ends

**Where:** `apps/web/src/components/ui.tsx:562-569`

```tsx
export function EmptyState({ title, hint }: { title: string; hint?: string }) {
```

`hint` is typed `string`, not `ReactNode`, so a caller cannot even smuggle a link in. There
is no `action`, no `icon`. MEASURED-IN-TREE: `<EmptyState` appears **51 times** in
`src/app`.

**Why.** NN/g's empty-state guidance (EXTERNAL, via web search 25 Aug 2026) is that an empty
state does three jobs: communicate system status, teach what belongs here, and *provide a
direct path to the next meaningful action*. This primitive can do the first two and is
structurally incapable of the third. Fifty-one screens therefore tell a new user that
nothing is there and stop — including `c/[slug]/page.tsx:241,318`, the very first screen an
invited owner sees.

This is also, mechanically, a large part of the "buried primary tasks" defect the founder
flagged: the moment when the primary task is most obvious to the *system* (there are no
agents; the task is "create an agent") is the exact moment the component cannot say so.

**Fix.**

```tsx
export function EmptyState({ title, hint, icon, action }: {
  title: string; hint?: ReactNode; icon?: ReactNode; action?: ReactNode;
})
```

then walk the 51 sites and give each one its next action. Where a site genuinely has none
(a filtered table with no matches), pass none — and that becomes a visible, reviewable
decision rather than a silent default.

---

### F-19 — MAJOR — no `PageHeader` and no card hierarchy; `Card` is the only container

**Where:** `apps/web/src/components/ui.tsx:32-80` · used in **68 files** (MEASURED-IN-TREE)

**What is wrong.** `Card` takes `{title, action, children, className, bodyClassName}` and
renders one visual weight. There is no `PageHeader`, no `Section`, no way to mark one panel
as the primary task. Every screen is therefore a vertical stack of same-weight boxes, and
the reader's only ranking signal is source order. `/auth/account` (F-3) is the small,
in-lane instance; `admin/ops/page.tsx` (2,030 lines) and
`admin/tenants/[tenantId]/page.tsx` (1,530 lines) are the large ones.

The `NoticeBox`-inside-`Card` pattern (`account/page.tsx:69-82`,
`reset-password/page.tsx:52-59`, `bootstrap/page.tsx:55-62`, `accept-invitation:84-88`) is
the symptom: authors reach for a second bordered container *inside* the first because they
need emphasis the first cannot express, and get a double border for it.

**Fix.** Add to `ui.tsx`:
- `PageHeader({ title, description, primaryAction, breadcrumb })` — one per screen, so the
  primary task has a fixed, learnable home above the fold.
- `emphasis?: "primary" | "default" | "quiet"` on `Card`, changing border/shadow/background
  weight only. `primary` is limited to one per screen (assert it in a test if that is worth
  the wiring).
- A `Stack`/`Section` with a heading, so a screen with nine cards can be three named groups
  of three.

This is the single highest-leverage change for the founder's flagged defect, and it belongs
in whatever design-doctrine doc the sibling lane is writing as rule one.

---

### F-20 — MINOR — no `DataTable`; 17 files hand-roll `<table>`

**Where:** MEASURED-IN-TREE: `grep -rl '<table' src/app` → **17 files**

`tests/responsive.test.ts:13-22` records that a real Chromium measurement found *"an
unwrapped table whose third column was unreachable"*. The rule that fixes it is enforced
statically; the component that would make it unforgettable does not exist. Each of the 17
also re-decides sticky headers, zebra striping, sort affordances and the mobile fallback.

**Fix.** `DataTable<T>({ columns, rows, empty, caption })` owning the
`overflow-x-auto` wrapper, `<caption>`, `scope="col"` headers, and one mobile strategy.
`interior/pagination.tsx` and `interior/load-more.tsx` (both dead, F-14) are its natural
companions.

---

## (d) Global states

### F-21 — BLOCKER — no error boundary and no 404 page anywhere in the app

**Where:** MEASURED-IN-TREE —
`find src/app -name "not-found.tsx" -o -name "error.tsx" -o -name "loading.tsx" -o -name "global-error.tsx" -o -name "template.tsx"`
returns **nothing**. The only special files under `src/app` are three `layout.tsx`
(root, `admin`, `c/[slug]`).

**Three consequences, all live:**

1. **404.** `app/legal/[slug]/page.tsx:38` calls `notFound()` — its docstring says *"An
   unknown slug is a 404 rather than a redirect: `/legal/gdpr` should tell the reader there
   is no such document"* — and what it actually renders is Next.js's built-in default 404:
   no header, no wordmark, no nav, no link back, none of the app's typography or tokens, no
   realm. Same for `/c/<slug>/settings` (F-13) and every mistyped URL. A regulator or a
   procurement reviewer following a stale legal link lands there.
2. **Uncaught render error.** With no `error.tsx` in any segment and no `global-error.tsx`,
   any thrown error in any of 71 routes takes down the whole tree to Next's default error
   screen — in production, "Application error: a client-side exception has occurred" — with
   no recovery affordance, no support route, no realm context, and the sidebar gone.
3. **No route-level Suspense fallback.** No `loading.tsx`, so a navigation shows the old
   screen until the new client component mounts and its own skeleton appears.

**Why this is a blocker.** This app has spent enormous effort on *anticipated* failure —
`ProblemNotice` (213 uses), `NoticeBox` (140), `Skeleton` (118), `RestrictionNote` (99), an
AST guard enforcing that no screen ever states a fact it does not have. The *unanticipated*
failure path has nothing at all. CLAUDE.md: *"Errors are part of the interface. Every
failure path a user can reach has a message they can act on, and every failure path they
cannot reach has a log line an operator can act on."* Both halves are currently absent for
the one failure class that reaches every route.

**Fix.**
1. `src/app/not-found.tsx` — app language, wordmark, and three real exits: `/` (marketing),
   `/c` (the junction that already resolves a signed-in user's console), `/legal`.
2. `src/app/error.tsx` + `src/app/global-error.tsx` — `NoticeBox tone="stop"` with the
   `reset()` button as "Try again", the Next `error.digest` rendered in a `MonoValue` so a
   client can quote it, and a `console.error`/Sentry hand-off (the repo already installs
   `sentry-sdk` per CLAUDE.md's mypy note) so an operator gets the log line.
3. `src/app/c/[slug]/error.tsx` and `src/app/admin/error.tsx` — so a crash inside a screen
   keeps the shell, the sidebar and the way out.
4. Add all four to the a11y sweep (`tests/a11y.test.tsx`) — they are screens.

---

### F-22 — MINOR — offline is handled ten times per-screen and never once globally

**Where:** the ten files listed in F-17. MEASURED-IN-TREE:
`grep -rn "navigator.onLine" src` → **no hits**. Nothing ever reads the browser's own online
state; every screen infers it from TanStack's paused-query shape.

**What is wrong.** A user whose connection dropped is told, at most, that *this panel* could
not establish something — in different words on each screen (`admin/operators/page.tsx:166`
says *"The console has not been able to establish what you may do here — you may be offline.
The controls stay closed until it can."*, which is excellent; nine other screens each say it
differently). Nobody ever says once, plainly, "you are offline".

**Fix.** `OfflineBanner` in `ui.tsx`, mounted in both shell layouts and in `AuthPageFrame`,
driven by `navigator.onLine` plus the `online`/`offline` events, rendering a
`role="status"` strip. Then the ten per-screen sentences can shrink to "waiting for a
connection" and stop each carrying their own diagnosis.

---

### F-23 — MAJOR — 429 `dark:` variants and no way to enter dark mode

**Where:** `apps/web/src/app/globals.css:57-64,80` — MEASURED-IN-TREE:
`grep -rno "dark:" src --include=*.tsx | wc -l` → **429**;
`grep -rn 'add("dark")\|classList.toggle\|documentElement.class' src` → **nothing**.

`globals.css:57-62` is honest about it: *"Dark mode is CLASS-based (`@custom-variant dark`),
not `prefers-color-scheme`… sets `.dark` on `<html>` by hand. It is defined anyway so a
screen written today is [ready]"* — and nothing sets it. So 429 dark variants are
unreachable, and `contrast.test.ts`'s dark-theme half is measuring a theme no user can
enter.

**Why it matters here rather than as cosmetics.** BRD's user is on a low-end Android; a
console that cannot follow the OS theme is a console that is bright white at 11pm. And 429
unreachable variants are 429 lines that no gate, no sweep and no reviewer can validate
against reality — they will rot.

**Fix.** Decide, and finish the seam either way:
- **Ship it:** a no-flash inline script in `app/layout.tsx` that reads
  `localStorage.theme ?? matchMedia("(prefers-color-scheme: dark)")` and stamps `.dark`
  before paint, plus a toggle in both shells and in `AuthPageFrame`. Add one dark-mode case
  to the a11y sweep.
- **Or delete the variants** and say in `globals.css` that the product is light-only.

Leaving it in the third state is the half-wired defect CLAUDE.md names.

---

## (e) Accessibility and responsive posture, and sweep-coverage gaps

### The enforced floor is genuinely strong — say so before the gaps

Read this session: `tests/a11y.test.tsx`, `tests/a11y.ts`, `tests/contrast.test.ts`,
`tests/responsive.test.ts`, `tests/navDrawer.test.tsx`, `tests/surfaceStatesGuard.test.ts`.

- **Coverage is disk-derived, not hand-listed.** `a11y.ts::routePagesOnDisk` walks
  `src/app` for every `page.tsx` **and** `layout.tsx`, and `a11y.test.tsx` fails if one is
  neither swept nor excused. MEASURED-IN-TREE: **71 screens are swept**, and
  `UNSWEPT_SCREENS` (`a11y.ts:273-283`) holds **exactly one** entry — the root `layout.tsx`
  — with an argued reason and a named condition that closes it. Both guards also assert a
  non-empty walk so a wrong cwd cannot produce a vacuous pass (`a11y.ts:314`,
  `responsive.test.ts:49`, `contrast.test.ts` premise checks). **All ten routes in my lane
  are swept** (`a11y.test.tsx:2448-2516`), each in a deliberately chosen state — signed-out
  for the guest doors, token-in-URL for the three link-spending pages, signed-in for the two
  account pages.
- **Contrast is measured against the palette in both themes at 4.5:1**, with the large-text
  allowance deliberately withheld (`contrast.test.ts:38-44`), and the file records the real
  Chromium finding that produced it (`--text-faint` at `#94a3b8` = **2.56:1** on
  `--surface`).
- **Responsive rules are the residue of a real measurement** at 320/360/414/1280
  (`responsive.test.ts:13-22`), including the iOS 16px zoom floor and 44px tap targets, and
  the file states plainly what the static-rule trade cannot catch.
- **The nav drawer uses `inert` correctly**, with the React 19 boolean-prop trap documented
  and the test counting tabbable elements rather than reading the attribute
  (`navDrawer.tsx:18-51`).
- **All four modal surfaces** carry `role`/`aria-modal`/`aria-labelledby` + `useFocusTrap`
  (F-16 verified each).
- **`Skeleton`** is a `role="status" aria-live="polite"` container with an `sr-only` label
  and `aria-hidden` bars, and its docstring correctly rejects `aria-busy` on the skeleton
  itself (`ui.tsx:610-635`).
- **`SkipLink`** targets a `tabIndex={-1}` main (`ui.tsx:531-560`).

That is well above the industry floor. The findings below are where it is merely met.

---

### F-24 — MAJOR (coverage gap) — every screen is swept in exactly one state: populated and permitted

**Where:** `apps/web/tests/a11y.test.tsx:96-107` (the design decision) and the 71 screen
entries

The sweep renders each screen with a full owner/superadmin permission set and a populated
fixture. Its docstring argues this correctly against the alternative — *"most of those 266
renders are of empty, loading or error states, which is not where the barriers are: a table
with no rows has no unlabelled header"*.

**The consequence still stands, and it is precisely the components this audit is about.**
`Skeleton`'s live region (118 sites), `ProblemNotice`'s alert wiring (213 sites),
`EmptyState` (51) and `RestrictionNote` (99) are **never axe-scanned in situ on any
screen** — only, at most, in their own unit tests. The premise "the barriers are in the
populated state" is true of *tables*; it is false of live regions and of
permission-restricted control sets, where the whole question is what is announced when the
content changes.

**Fix.** A second, smaller sweep pass — a dozen representative screens rendered three more
ways: `routes: {}` with a `problem()` response (failure), an empty-collection fixture
(empty), and a reduced-permission `ME` (restricted). Reuse the existing `Screen` type; the
harness already supports all three.

---

### F-25 — MAJOR (coverage gap) — no axe pass over any modal in its open state

**Where:** `components/authn/stepUpPrompt.tsx`, `components/authn/adminIdleTimeoutModal.tsx`,
`components/aiExtraDialog.tsx`, and `NavDrawer` in its `isModal` costume

The sweep renders *pages*; all four of these appear only after an interaction or a timer, so
none is ever handed to axe while open. They are the highest-stakes surfaces in the app for
focus management (one of them is a step-up prompt gating an irreversible action, one is an
idle-timeout warning), and F-16 records that this exact class already shipped broken once.

Additionally: `aria-modal="true"` does not remove the background from the accessibility tree
in every engine, and there is no test asserting the page behind any of these is inert. The
drawer solves this for itself with `inert`; the three dialogs do not.

**Fix.** Four interaction-driven axe cases in `a11y.test.tsx` (open the dialog, then
`expectNoA11yViolations`), plus one assertion per dialog that background content is not
tabbable while it is open — the same "count tabbable elements" technique `navDrawer.test.tsx`
already uses, reused rather than reinvented.

---

### F-26 — MINOR — the four notice tones are Tailwind literals no contrast gate measures

**Where:** `apps/web/src/components/ui.tsx:359-392` (`NOTICE_TONES`), 140 `<NoticeBox` sites

`contrast.test.ts:50-56` scopes itself out honestly: *"Ink on a non-token background —
`bg-rose-50`, `bg-emerald-100`, the status badges — is out of scope, because those are
Tailwind palette literals chosen per site rather than tokens."* But `NOTICE_TONES` is not
"per site" — it is a four-entry table in the shared library, applied 140 times, carrying
every compliance verdict in the product, in both a light and a dark spelling. It is exactly
the kind of shared palette the file's own argument says should be a token.

The measured ratios of e.g. `text-emerald-900` on `bg-emerald-50` are **UNKNOWN in this
tree** — no gate computes them, and I did not compute them this session.

**Fix.** Move the four tones into `globals.css` as `--notice-ok-*` / `-warn-` / `-stop-` /
`-neutral-` token pairs and extend `contrast.test.ts`'s ink×background matrix over them.
Four tokens, one loop, and 140 sites become measured.

---

### F-27 — MINOR — the tap-target and zoom floors are met by constant, so hand-rolled controls escape them

**Where:** `ui.tsx:394-425` (`FIELD`, `PRIMARY_BUTTON`, `FilterChip`'s `touch:min-h-11`) ·
`tests/responsive.test.ts`

`responsive.test.ts` enforces the 16px/44px floors on the shared constants, and
`authn/fields.tsx:10-13` explicitly notes that importing `FIELD` from `ui.tsx` rather than
copying it is what *"keeps these inside the tap-target guarantee"*. That is exactly right —
and it means the guarantee holds for controls built from the constants, and says nothing
about the 176 raw `<input>` (F-15) and the hand-rolled buttons alongside them, except
insofar as those also use `FIELD`.

**Fix.** This closes as a side effect of F-15: once a `Field` component owns the class
string, the guarantee attaches to the component rather than to the author's memory. Add the
raw-`<input>` source guard described there so the escape hatch is visible.

---

## What the shared primitive library must gain

For the design-doctrine lane. These are the specific additions that, in this tree, would
let every other lane stop hand-rolling. Ordered by how much hand-rolling each removes,
with the measured count it addresses.

**Tier 1 — the four that account for most of the inconsistency**

1. **`Field` / `SelectField` / `TextAreaField` / `PasswordField`** — promote
   `authn/fields.tsx::AuthField` into `ui.tsx` and add the three siblings. Owns
   `label htmlFor`↔`id`, `aria-describedby` across hint+error, `aria-invalid`, error
   placement, and one validation *timing* (on submit / on blur-after-touch, never
   per-keystroke). **Removes 176 raw `<input>` across 46 files and 64 raw `<select>`.**
   Also closes F-4, F-5, F-27.
2. **`useEnvelope(query)` + `<Async>`** — one discriminated
   `loading | failed | paused(offline) | empty | ready`, derived once. **Removes 137
   hand-rolled `isLoading` ladders across 49 files** and the ten independently-written
   offline explanations. Turns `surfaceStatesGuard.test.ts` from a rule people must obey
   into a rule the API makes hard to break.
3. **`PageHeader` + `Card emphasis` + `Section`** — the missing hierarchy. `Card` is the
   only container in **68 files** and has exactly one weight, which is mechanically why
   every screen is a flat stack and why primary tasks are buried. `PageHeader{title,
   description, primaryAction}` gives the primary task a fixed home above the fold;
   `emphasis: "primary" | "default" | "quiet"` lets a stack have a subject.
4. **`EmptyState` with `action` and `icon`, and `hint: ReactNode`** — the smallest change
   with the largest first-run effect. **51 sites**, every one of them currently incapable of
   offering the next step.

**Tier 2 — the surfaces that are correct today and will not stay correct**

5. **`Modal`** — `{open, onClose, title, tone: "dialog" | "alert", children, footer}` owning
   the overlay, role, `aria-modal`, generated `aria-labelledby`, `useFocusTrap`, Escape, and
   background inertness. **Replaces 3 byte-identical shells**; the repo has already shipped
   one dialog without a trap.
6. **`DataTable<T>`** — the `overflow-x-auto` wrapper, `<caption>`, `scope="col"`, one
   mobile strategy, and slots for the (currently dead) `Pagination` / `LoadMore`.
   **Replaces 17 hand-rolled `<table>`**; the measured Chromium run already found one
   unreachable column.
7. **`LoadingButton`** — `interior/loading-button.tsx` already exists and is unused. Every
   mutation button in this repo carries its own `{isPending ? "Saving…" : "Save"}` ternary
   and its own `disabled` policy; F-6 shows the policy is currently wrong in one direction
   across all of them. One component fixes the policy once.

**Tier 3 — global surfaces that exist nowhere**

8. **`app/not-found.tsx`, `app/error.tsx`, `app/global-error.tsx`, per-shell `error.tsx`** —
   not strictly `ui.tsx` members, but the primitive they need is a shared `FailureScreen`
   in the app's language with a `reset` action and a quotable digest. **Currently 71 routes
   with none.**
9. **`OfflineBanner`** — one `role="status"` strip in both shells and `AuthPageFrame`.
   Nothing in this app reads `navigator.onLine` today.
10. **`RealmMark`** — the visible realm identity (rail token + header word + title prefix +
    favicon), consumed by both shells and `AuthPageFrame`. The realm is currently 12px of
    `text-ink-faint`.

**And one deletion, which is part of the same job**

11. **Resolve `components/interior/`.** 18 of 19 modules, ~5,440 lines, have zero
    importers. Several of them (`otp-input`, `loading-button`, `tabs`, `pagination`,
    `load-more`, `wizard-steps`) are *exactly* the tier-1/2 answers above, already written
    and already tested. Adopt each at its call sites or delete it, in the same change. A
    doctrine document that describes a library while a second, better, unused library sits
    next to it will be ignored by the next agent, and rightly.

---

## Sources

External guidance cited above, all retrieved 25 August 2026 **via web search** because
direct fetches to these hosts are blocked by this machine's egress proxy (measured, same
date). The synthesis is the search engine's; the pages themselves were not read here, and
no statistic from any of them is repeated.

- [Passwords — GOV.UK Design System](https://design-system.service.gov.uk/patterns/passwords/) — show-password component; removal of confirm-password inputs on GOV.UK Accounts. (F-4)
- [Simple things are complicated: making a show password option — GDS Technology blog, 19 Apr 2021](https://technology.blog.gov.uk/2021/04/19/simple-things-are-complicated-making-a-show-password-option/) — rationale for the toggle. (F-4)
- [Button — GOV.UK Design System](https://design-system.service.gov.uk/components/button/) and GOV.UK practitioner guidance on avoiding disabled buttons. (F-6)
- [Understanding SC 3.3.3: Error Suggestion — W3C WAI](https://www.w3.org/WAI/WCAG21/Understanding/error-suggestion.html) — Level AA; suggestions for correction when an input error is detected. (F-5)
- [Designing Empty States in Complex Applications: 3 Guidelines — Nielsen Norman Group](https://www.nngroup.com/articles/empty-state-interface-design/) — empty states communicate status, teach what belongs, and give a direct path to the next action. (F-1, F-10, F-18)

Repo-internal references are cited inline by `file:line` as the tree stood on 25 August
2026; all counts marked MEASURED-IN-TREE were produced by the greps and `find` invocations
named at the point of use.
