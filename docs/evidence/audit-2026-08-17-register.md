# Full-codebase audit, 17 Aug 2026 — the consolidated register

Five independent passes ran concurrently over the tree, each in its own worktree, each
forbidden from reading the others' notes so that agreement between two of them means two
readers found the same thing rather than one reader repeating themselves. This file is the
index and the fix order; the reports are the evidence and each finding's full argument
lives there.

| Pass | Report | Findings |
|---|---|---|
| Correctness and concurrency | `audit-correctness.md` | 2 High · 2 Medium · 3 Low |
| Security, tenancy, egress | `audit-security.md` | 3 Medium · 1 Low |
| Frontend | `audit-frontend.md` | 5 Medium · 4 Low · 1 info |
| Reliability and operations | `audit-reliability.md` | 2 High · 4 Medium · 3 Low |
| Docs against the code | `audit-docs-truth.md` | 2 High · 6 Medium · 4 Low |

**41 findings. No Critical. Nothing found is a live customer-data exposure** — the tenancy
boundary, the money core, the reliability triad, the redaction invariant and every dial
gate came back clean under deliberate hunts, and the reports say so at length. What the
passes found is concentrated in three places: the dial path's ordering, the gap between
what a document promises and what an alert or a role actually does, and the frontend's
keyboard.

## Where two passes agree

Corroboration is the strongest signal here, because the passes could not see each other.

- **The dial write happens after the engine call.** Correctness (2, HIGH) and reliability
  (R-1, HIGH) found this independently, from different directions — one from the docstring
  that promises the opposite ordering, one from the campaign contact that gets re-dialled
  when the response is lost. Two readers, one defect: **a real person's phone rings twice.**
  This is the first thing to fix.
- **A tenant transaction is held across a vendor round trip.** Correctness (4) and
  reliability (R-5), same two call sites, and correctness adds the `max_overflow=0`
  invariant (3) that makes the consequence pool starvation rather than mere slowness.
- **A phone number rides in a GET query string.** Security (S-3) and frontend (5), from
  the two ends of the same request. `?search=` on `/v1/leads` reaches nginx's access log,
  and this repo already made the opposite call twice (`POST /v1/dnc/check` — "the
  identifier IS the personal data").

## Fix order

**First — the two HIGHs that reach a caller or a payment.**

1. Dial ordering (correctness 2 / reliability R-1). The `calls` row cannot precede the
   engine call while its conflict key IS the engine's return value, so the fix is a
   pre-dial intent row, not a re-order.
2. The `Idempotency-Key` that rolls back with the payment it guards (correctness 1). The
   repo already solved this once in `billing/payment_routes.py` and argued why — this is
   the second way of doing one thing, and it is the one that does not work.

**Second — the promises with nothing behind them.**

3. The alarms OPERATIONS §4 lists and `billing/caps.py` does not raise (reliability R-2).
4. The residency claim still in `docs/BRD.md` and `docs/README.md` after being scrubbed
   from the landing page (docs-truth F-1, F-2). Sales reading a claim engineering removed
   is the same defect as shipping it, one step further from the code.
5. Staff can download raw call audio while being refused the raw transcript drawn from it
   (security S-1). Whether that is a decision or an oversight is the founder's to say; the
   report does not assume.

**Third — the keyboard and the audit row.**

6. Re-opening a raw transcript is served from cache, so the second read writes no
   `audit_log` row (frontend 1). Hard rule 5 says opening it writes the row.
7. Skip link, focusable scroll containers, `aria-current` (frontend 2, 3, 4).

**Fourth — the rest**, in the reports, each with its own argument.

## What is NOT here

Three things the passes could not settle, recorded rather than guessed:

- Whether the nginx source-IP allowlist SECURITY-COMPLIANCE §5 describes is a doc error or
  a config omission — no decision entry chooses (docs-truth F-3).
- Whether S-1's recording role is deliberate.
- Anything about the auth surface from the frontend pass: it read the tree mid-flight,
  while `lib/auth/**` was still Clerk. What replaced it is `lib/authn/**`, and it has its
  own tests. **That surface is unaudited and should be swept again**, which is the one
  coverage gap this register carries.

Two of the passes also reported premises in their own briefs that turned out false — a
teardown file that did not exist under the name they were given, and a test file that does
not exist. They are noted here because a brief that misdescribes the tree is how an audit
comes to clear something it never read.

---

# Second wave, 18 Aug 2026 — six agents, hunting where the first pass had not

The first wave audited. This one attacked, executed, and FIXED. Six agents, each fenced to
a surface the first wave had cleared or never reached, each told what was already cleared
so it would hunt new ground, and each required to label every finding PROVEN (executed) or
REASONED (read).

| Pass | Report | Outcome |
|---|---|---|
| Money and metering | `deepdive-money.md` | 5 fixed, all proven · 2 founder/tax decisions raised |
| Voice path and engine seam | `deepdive-voice.md` | 4 fixed, all proven · 1 inert defect recorded, not invented a consumer for |
| Deploy readiness | `deploy-readiness.md` | 4 blockers, 3 ours and fixed · 10 external, named |
| User journeys | `deepdive-journeys.md` | 3 fixed, all proven · 2 found, one externally blocked |
| Adversarial security | `deepdive-attack.md` | 1 cross-tenant hole, proven over HTTP, fixed |
| Schema and migrations | `deepdive-schema.md` | see report |

## The five that mattered most

Each was PROVEN by execution, and each had survived every previous pass.

1. **The production image had no Python packages in it.** A bare `uv sync` in the
   `Dockerfile` installed nothing and **exited 0** — indistinguishable from a cache hit.
   `site-packages`: 3 files. The first deploy would have died at `vps-deploy.sh` step 7
   with `ModuleNotFoundError`, after the build and before the swap, so nothing downstream
   had ever been exercised. The README, the CI workflow and DEPLOYMENT §3/§8 all state the
   `--all-packages` rule; the one file that builds the production artefact did not.

2. **A cross-tenant reference the tenancy boundary cannot see.** `POST /v1/campaigns` and
   `POST /v1/compliance/messaging-consent` took caller-supplied foreign keys without an
   ownership check, and **PostgreSQL runs referential-integrity checks with row security
   bypassed** — so RLS, which is otherwise sound here, never applied. Three attacks
   returned `201 Created` from a valid tenant-B session. The consent case is the serious
   one: `consent_ledger` is append-only, so a DPDP consent record evidenced by another
   tenant's conversation could never be corrected.

3. **A caller's "stop calling me" was deletable by the account it was made against.**
   `ON CONFLICT DO NOTHING` left an existing `manual` row's source unchanged when the same
   person later opted out on a call, so the UI offered delete and honoured it — returning
   the number to the dial pool with a `consent_ledger` row saying they had withdrawn. That
   defeats TCCCPR's 90-day bar on re-soliciting an opted-out subscriber.

4. **An erased tenant kept collecting callers.** Erasure never withdrew
   `engine_agent_routes`, the bridge from the engine's id space into ours. Measured: a new
   `calls` row with a raw caller number inserted AFTER a successful erasure, under a
   certificate asserting the account was erased.

5. **The meter had a second, wrong spelling of the IST billing month.** `strftime` renders
   a value's own fields rather than converting, so a call stamped `23:00+05:30` on the 31st
   metered into the next month while its own `usage_events` rows sat in the current one.
   Two more money defects fell out of the same hunt: a late-settling call wiped the open
   month's spend counters, and the live spend counter priced a month by a different rule
   than the invoice — measured **₹880.00 vs ₹520.00** on adjacent cards, with the cap
   enforced against the larger.

## What the passes could NOT break

Recorded because a negative result from a real attempt is evidence, and because it is what
makes the findings above credible:

- All **76** request-body models forbid extra fields; all **54** admin routes pin
  `realm="admin"`; six `{id}` routes the existing IDOR sweep never drove already refused
  correctly (now in the sweep).
- The 100ms in-call budget is measured with its own series and asserted in CI. The <500ms
  ack path was walked call by call for blocking waits and is clean.
- The normalized-model boundary holds: every vendor field and status string in `apps/**`
  and `apps/web/src` is prose.
- The truthful-answer floor survives publish, variants, the drift sweep and `user_data`.
- A full charge was re-derived by hand from raw duration to invoice line — unit conversion,
  per-rung allocation, allowance, overage, GST — and every step agreed.
- Mid-batch DNC propagation, the scheduled-launch gate, append-only ledgers under both
  erasure paths, and the retention countdown surviving offboarding.

## What is still open, and whose it is

**Ours, named rather than implied:** `publish_agent` asks nothing about the organisation's
lifecycle, so an operator with a hand-typed uuid can put a churned client's agent back on
the phone; three OPERATIONS §4 alarms still have no call site; the runtime image stage has
never been built anywhere; a full rollback deploy is unrun.

**External — no amount of engineering closes these:** the VPS itself; nginx ≥1.25.1 (stock
Ubuntu ships 1.18/1.24, both of which fail to load our config); DNS and the Cloudflare zone;
R2 buckets including a separate backup bucket with its own scoped token; **a non-Cloudflare
offsite target**, because that is the copy that survives a Cloudflare account event; Resend
with a verified sender domain; a Sentry project; secrets generated into a manager; and the
restore drill — until it runs there is backup CODE, not backups.
