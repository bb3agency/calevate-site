# Deep dive — the five end-to-end journeys, walked as a person

**Date:** 18 Aug 2026 · **Scope:** the five journeys named in the brief, walked step by
step rather than module by module, hunting the SEAMS between steps: the states a journey
can get stuck in, and what the product tells a person when it cannot proceed.
**Decision-log row:** D-189.

Prior passes cleared, and this one deliberately did not re-report: every dial path
calling `check_dispatch`, the truthful-answer floor and the two D-163 announcement
toggles, the redaction invariant on egress, the tenancy boundary and all 41
`tenant_session` call sites, and D-185's named residual (the invitation token returned
to the inviter rather than emailed — being handled elsewhere).

Every finding below is marked **PROVEN** (driven against the live schema, red before the
fix and green after) or **READ** (reasoned from the tree, not executed).

---

## Severity summary

| # | Journey | Finding | State | Evidence |
|---|---|---|---|---|
| J-1 | 3 — "stop calling me" | A caller's opt-out landing on a pre-existing `manual` DNC row kept that row's source, so the CLIENT could delete it | **FIXED** | PROVEN |
| J-2 | 5 + 4 — offboarding / DPDP | An ERASED tenant kept ingesting new inbound calls; the certificate was false within minutes of being signed | **FIXED** | PROVEN |
| J-3 | 5 — offboarding | The owner of a closed account is told "You are not a member of this account" — on their own account | **FIXED** | PROVEN |
| J-4 | 2 — first campaign | Consent provenance accepts `scheduled`; the summary, the docstring and the refusal all said "draft only" | **FIXED** | PROVEN (behaviour), READ (wording) |
| J-5 | 2 — first campaign | `docs/FLOWS.md` §5 said "Recurrence is NOT built"; it is built, routed and reachable | **FIXED (doc)** | READ |
| J-6 | 5 — offboarding | Churn (without erasure) leaves the engine agent live and the account still answering; the number is never released | **FOUND, part-fixed** | PROVEN (mechanism), see below |
| J-7 | 1 — zero to live agent | `POST …/agents/{id}/publish` asks no question about the account's lifecycle | **FOUND, not fixed** | READ |

---

## J-1 — A caller's "stop calling me" was deletable by the account it was made against

**Journey 3, PROVEN.** Hard rule 5 says a DNC addition "can never be removed by anyone",
and `dnc.REMOVABLE_SOURCES = ("manual",)` is how the repo holds that: a suppression a
human at the client typed in is theirs to undo (a mistyped digit has to be fixable), and
one that records a CONSUMER's request is not.

The sequence that breaks it needs no adversary and no unusual state:

1. Somebody at the clinic pastes a number into the do-not-call page. Source `manual`,
   removable, correctly.
2. That same person later rings the clinic and says *"stop calling me"*. Either detector
   fires — the in-call tool or the post-call transcript pass — and both funnel into
   `compliance.optout.record_call_optout`, which calls `compliance.service.add_to_dnc`.
3. `add_to_dnc` was `INSERT … ON CONFLICT (tenant_id, phone_e164) DO NOTHING`. The row
   already exists, so **nothing changes**. `newly_suppressed` is False (correctly — they
   were already suppressed) and the `consent_ledger` evidence row is written (correctly).
4. The `dnc_list` row still says `source = 'manual'`. `dnc.is_removable` therefore returns
   True, the client's screen renders the delete affordance, and `dnc.remove_entry`
   honours it.

Measured on the live schema before the fix:

```
BULK ADD:            AddResult(added=1, already_suppressed=0, malformed=0)
OPTOUT:              OptOutRecord(suppressed=True, newly_suppressed=False, evidence_written=True)
ROW AFTER OPTOUT:    (…, 'manual')
IS_REMOVABLE:        True
REMOVED:             Removal(source='manual', subject_ref=…)
ROWS LEFT:           0
```

The number is back in the dial pool with a `consent_ledger` row saying the caller
withdrew — a ledger entry contradicted by the live list, which is worse than either fact
alone. `compliance/optout.py`'s own docstring names the rule this defeats: TCCCPR bars a
sender from re-soliciting an opted-out subscriber for ninety days, and `REMOVABLE_SOURCES`
excluding `call_optout` was the whole mechanism.

**Fix.** The conflict now UPGRADES: an existing row whose source is client-deletable is
rewritten to the incoming non-deletable one, and nothing else is ever rewritten. The
predicate is stated in both directions so the write is monotone — a `manual` add can never
weaken a `call_optout` row, which an unconditional `DO UPDATE` would have allowed.
`added_at` is untouched: the suppression has been continuous since the number was first
typed in, and moving it forward would misdate a fact a client may have to show a TSP.

`DNC_REMOVABLE_SOURCES` moved to `compliance/models.py` beside `DncEntry`, because
`compliance/service.py` now needs it and cannot import `compliance/dnc.py`
(`dnc` → `ingest.service` → `compliance.service`). `dnc.REMOVABLE_SOURCES` re-exports it,
so there is still exactly one definition and the routes keep their vocabulary.

**Tests** (`tests/call_optout_test.py`): the walked sequence above, and a monotonicity
guard covering `add_to_dnc` in both orders plus the bulk console path. The first is red
without the fix.

---

## J-2 — An erased organisation went on collecting callers, and the certificate said otherwise

**Journeys 5 and 4, PROVEN.** `POST /v1/admin/tenants/{id}/erasure` is thorough about
what the tenant HELD — calls, turns, extractions, leads, campaign contacts, recordings
past the TRAI floor, delivered CRM bodies, archived engine payloads — and its certificate
enumerates what it deliberately does not touch. Nothing anywhere stopped the account
ACQUIRING more.

`engine_agent_routes` is the one bridge from the voice platform's id space into ours
(`workers/pipeline._resolve_agent`). The erasure never touched it. The vendor's agent
object is still configured, the client's DID is still pointed at it, and the tenant's
RLS policies key on the GUC rather than on `organizations.deleted_at` — so the first
inbound call after the certificate was issued re-created a `calls` row and everything
hanging off it.

Measured before the fix, after a full successful erasure:

```
WORKER:                     tenant erased calls=0 leads=0 turns=0 …
RESOLVED AFTER ERASURE:     (UUID('01a01266-…'), UUID('01a01266-…'))
NEW CALL ROW AFTER ERASURE: ('+919812345678',)
```

Three things make this worse than an ordinary leak. The certificate's `actions` block
says `"marked deleted; no membership resolves and no dial is permitted"` — true of
OUTBOUND, and inbound is where the new records come from. The client's own people are
locked out (`core/auth.py` refuses a churned org), so this is personal data with no
purpose, no reader and no route to a subject-access answer — DPDP §8(7) on its own. And
the document that says the data is gone is false within minutes of being signed.

**Fix.** The erasure withdraws the tenant's routing in its own transaction, so it commits
with `deleted_at` and the proof or not at all, and the count goes on the certificate's
`actions` (the same placement `engine_payloads_erased` already uses).

What it deliberately does NOT do is stop the vendor answering the phone. Only removing
the agent at the voice platform and releasing the number with the telephony provider does
that, and both are outside this repository. `VoiceEngine.delete_agent` exists and is
idempotent by contract, and was **rejected here**: it is a third-party round trip inside
the one transaction that must not half-commit, and its failure mode would be an erasure
rolled back because a vendor was slow. So the certificate now says, in words a client can
hand on, that the agents are still configured, the numbers still route to them, and a
caller dialling the old number still reaches an answering agent until somebody performs
those two manual steps.

The operator's signal is automatic and had to be made legible. A ref that was never
mapped and a ref whose routing was WITHDRAWN are the same silence to `_resolve_agent` and
completely different jobs: the first is a mis-provisioned agent, the second is a live
telephone number somebody has to go and release — a fact nothing else in the system can
discover, because the only symptom is a stranger ringing it.
`engine_agent_route_withdrawn` names it and carries the tenant id (an id: hard rule 6 is
intact — the number that is still routed is not ours to log).

**Checked rather than assumed:** the retention sweep and the outbox dispatcher enumerate
tenants with `SELECT DISTINCT tenant_id FROM engine_agent_routes`, deliberately
unfiltered on `active` (`workers/retention._tenants` argues it), so the countdown FLOWS
§9 promises keeps running for an erased tenant. The agent and KB drift sweeps DO stop —
they read `WHERE active` — and that is right for agents being abandoned to the vendor,
which is now stated on the certificate rather than left to a reader.

**Test** (`tests/tenant_erasure_test.py::test_an_erased_tenant_records_no_further_inbound_call`):
asserts through the real resolver, because the resolver is what decides whether a record
gets written. Red without the fix with the exact message above.

---

## J-3 — The owner of a closed account is told they are a stranger to it

**Journey 5, PROVEN.** `core/auth.py::_load_client_principal` resolves memberships with
`o.deleted_at IS NULL AND o.status <> 'churned'` and answers an empty result with
`ProblemError.forbidden("You are not a member of this account.")`.

Walked as a person: the owner has been signing in for months. An operator closes the
account on Friday. On Monday they open the dashboard and are told they are not a member
of their own account — in a product whose offboarding flow (FLOWS §9) hands them an
export bundle of the very data that screen shows. The sentence is false and it names
nothing they can act on.

`admin.service.assert_account_open` cites this exact symptom as the reason an invitation
into a closed account is refused (D-65/D-185). Nobody had walked it for the people
already inside.

**Fix.** Zero rows is two different facts. On the empty path only, a second read — inside
the same `user_session`, so it can see nothing but this caller's own memberships — asks
whether a membership exists on a closed or deleted org, and answers `account_closed`
with a remediation. The name is the one `assert_account_open` and the dial gate already
give this state. A genuine stranger still gets the neutral refusal, which is the branch a
careless fix would swallow.

**Tests** (`tests/tenant_birth_test.py`): the owner's Monday morning (red without the
fix), and the stranger's neutral answer (must stay green).

**What this fix does NOT decide.** Whether a churned tenant's owner should keep READ
access — or a bounded export window — so the FLOWS §9 export bundle can actually be
taken after the switch is flipped is a **product decision, not a defect I should take**.
Today the ordering is implicit: export first, churn second, and nothing enforces it. The
message now at least tells the person who to ask.

---

## J-4 — Consent provenance said "draft only" and accepted `scheduled`

**Journey 2, PROVEN behaviour / READ wording.**
`campaigns.service.record_consent_provenance`'s UPDATE carries
`AND status IN ('draft', 'scheduled')` — correct, and the reason is stated in
`campaigns/scheduling.py` decision 3: a client who set a Monday start on Friday has
dialled nobody, and the gate that reads this column runs when the schedule FIRES. But the
route summary, the docstring and the refusal all said "draft", so a client with a
scheduled campaign missing its provenance was told to do something they did not need to
do (cancel the start) to reach a state they were already allowed to write from.

**Fix.** The three strings now describe the rule the statement enforces, and the refusal
gained a remediation naming both admissible states and why a started campaign is not one.
OpenAPI snapshot and the generated TypeScript client regenerated.

---

## J-5 — FLOWS §5 said recurrence is not built

**Journey 2, READ.** `docs/FLOWS.md` §5 carried "**Recurrence is NOT built.** … the
dispatcher refuses any value but `one_time`". `POST /v1/campaigns/{id}/recurrence` is
mounted, `campaigns/scheduling.py` fires occurrences, `complete_or_rearm` re-arms them
and `GET /v1/campaigns/{id}` renders the rule and the next occurrence. A client's screen
and the authoritative document disagreed about a shipped feature.

Rewritten to describe what is there and the three bounds that go with it (weekday+time
rather than RRULE; a missed occurrence is skipped and never caught up; an occurrence
outside the platform calling window is refused at creation), and to keep the true half of
the old sentence: the `kind` discriminator still refuses any value it has no reader for.

---

## J-6 — Churn alone leaves the agent live, and the number is never released

**Journey 5. FOUND; the erasure half is fixed, the churn half is NOT, and here is why.**

`POST /v1/admin/tenants/{id}/status` → `churned` stops outbound at the dial gate
(`account_closed`), locks every member out, and starts the retention countdown. It does
not unpublish the agent, does not withdraw the routing and does not touch
`phone_numbers`. So an offboarded clinic's AI receptionist keeps answering the clinic's
public line, keeps recording strangers and keeps writing calls, transcripts, extractions
and leads into an account nobody can open. FLOWS §9's "number released or ported per
client wish" has **no implementation anywhere**: `provision_number` is the only writer of
`phone_numbers` and there is no release path, at the vendor or in our table.

**Why I fixed the erasure and not the churn.** They differ in what a wrong answer costs.
An erasure is an instruction to destroy everything and comes with a document asserting it
was carried out — continuing to collect makes that document false, so withdrawing the
routing is unambiguously right. Churn is the commercial relationship ending; the data
stays for its retention period by design, a notice period during which the number still
forwards is a normal commercial arrangement, and withdrawing the routing there would mean
a caller still talks to an AI while we keep no record of it — a worse position, not a
better one, and the choice is the founder's rather than mine.

**What actually closes it** is not code in this repo: a telephony-provider account and a
voice-platform account (OPERATIONS §2's pilot gates), so that "release the number" and
"remove the agent" become API calls an offboarding job can make instead of runbook steps.
Until then, the erasure path names both as manual steps on the certificate and the
`engine_agent_route_withdrawn` alarm is what makes an outstanding one visible.

---

## J-7 — Publish asks nothing about the account's lifecycle

**Journey 1, READ, NOT FIXED.** `POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish`
takes the tenant in the path (correctly — D-22 makes impersonation read-only) and calls
`publish_agent`, which checks the AGENT's `deleted_at` and never the ORGANISATION's
status. So an operator can put a churned or erased client's agent live on the phone, and
on the erased path that also re-mints the routing row J-2 withdraws.

Not fixed here for one reason and it is an import graph, not a judgement:
`admin.service.assert_account_open` is the one definition of "may this account be acted
on" and `apps/api/agents/service.py` cannot reach it without either a new import edge
through `admin/` (which imports `compliance.service`, `admin.holds` and
`compliance.disclosure` — a cycle risk I could not clear inside this pass) or a second
copy of the predicate, which is exactly the drift CLAUDE.md forbids. The honest fix is
to move `assert_account_open` to a module both realms already depend on, migrating its
two existing callers in the same change. That is a small, self-contained piece of work
and it is **the next thing to do**, not a deferral — it is named here so it is not lost.

Mitigating, and the reason this is not a live hole today: the admin console cannot reach
an erased tenant (every directory route filters `deleted_at IS NULL`), so a publish
against one requires a hand-typed uuid.

---

## Examined and found clean

* **The DNC propagation deadline, mid-batch.** `_dispatch_for_campaign` commits the
  claim, then re-reads the campaign's live facts AND runs `check_dispatch` per contact in
  its own transaction — so an opt-out committed by another connection while a batch is in
  flight blocks the very next contact, not the next tick. The comment says so and the
  code does it.
* **The scheduled-launch gate.** `fire_schedule` calls `launch_campaign`, the same
  function the button calls; there is no scheduled variant of the gate. A start the gate
  refuses is retried for 24h and then returned to `draft` rather than starting late.
* **The recurrence occurrence claim.** `_claim_occurrence` locks on the occurrence
  instant, so the two ticks the lease deliberately allows contend on the occurrence's
  identity rather than on the wall clock.
* **The KB approval seam.** Client submits → "In review" with the reason on screen;
  admin has BOTH queues (`pending_approval` and approved-awaiting-publish), each with a
  distinct loading/error/empty rendering so a failed fetch cannot read as "nothing
  waiting". Approve is idempotent and audits only a real approval.
* **The retention countdown after offboarding.** Deliberately unfiltered on
  `organizations.status` and on `deleted_at`, and now also verified to survive the route
  withdrawal this pass adds.
* **`_erase_tenant_*` vs the append-only ledgers.** Nothing in `APPEND_ONLY_TABLES` is
  touched; the certificate says which of them still carry caller numbers rather than
  hiding it.
* **The erasure/backup clause.** The certificate claims the erasure is re-applied on
  restore; `runbooks/database-restore.md` §8 makes it a mandatory step with a count
  recorded in the incident record, so the claim is backed.

## What this pass could not determine

* **Whether the vendor honours a deletion at all.** `engine_deletion` stays
  `unconfirmed_pending_vendor_api`. Externally blocked: no Bolna account, and the written
  erasure commitment is a contract term (pilot gate 12(f)).
* **What a released number actually costs or requires.** No telephony-provider account
  exists, so J-6's real fix cannot be written against an API nobody can call.
* **Whether the `engine_agent_route_withdrawn` alarm reaches a human.** `SENTRY_DSN` is
  unset and `check_observability_ready` skips it by design; the alert is a log line and an
  in-process notice until OPERATIONS §8's unfinished business is done.
