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
