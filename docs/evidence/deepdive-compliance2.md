# Deep dive — the compliance surface, attacked as a whole

**Date:** 18 Aug 2026 · **Base:** the session head (`e860fa2`, the engine-hosting slice)
· **Decision-log rows:** D-310 … D-313.

Previous waves proved individual pieces — the dial gate (D-56, D-117), DNC propagation
(D-189), erasure (D-44, D-122, D-179), the complaint spike (D-149), the truthful-answer
floor (D-163, D-282). This pass took the surface as ONE system and went looking for the
seams between those pieces: the places where two correct mechanisms, running
concurrently, produce a wrong outcome that neither owns.

Every claim below is **PROVEN** (executed against the live schema on a replay database,
red before the fix and green after) or **REASONED** (read, not run). The negatives are
here in full, because a list of four findings with no account of what was tried and held
is a list nobody can weigh.

---

## Findings

| # | Area | Finding | State | Evidence |
|---|---|---|---|---|
| C-1 | DPDP erasure | A call still IN FLIGHT when an erasure ran had its transcript, summary, extraction, recording pointer, archived vendor document and a `leads` row written back **after** the certificate was signed | **FIXED** (D-310) | PROVEN |
| C-2 | DPDP erasure | An erased call is orphaned from its subject forever — the erasure clears the only two columns it locates calls by — so no later erasure can reach anything that lands on it | **FIXED** (D-310, migration `c1e9a4f7d302`) | PROVEN |
| C-3 | Calling hours | The window was inclusive at 21:00, so a dial placed at 21:00:00 IST passed the gate | **FIXED** (D-311) | PROVEN |
| C-4 | Audit chain | `audit_log.ip` — the field that answers *where did this act come from* — was the only one of SEC-COMP §5's four not covered by the hash | **FIXED** (D-312) | PROVEN |
| C-5 | National DND | A scrub's own suppressions left headroom for exactly that many unscrubbed contacts, and the launch/dispatch gate stayed green | **FIXED** (D-313) | PROVEN |

---

## C-1 / C-2 — the erasure certificate that was false within two minutes

**PROVEN.** `tests/erasure_late_arrival_test.py`.

The sequence needs no adversary and no unusual state. A caller is on the phone —
`calls` row committed by `dispatch_call` before the ring, or by an inbound `ringing`
event. Somebody at the clinic files that caller's DPDP §12 erasure, which is *when people
actually ask*: while they are talking to the business. `execute_deletion_request` runs.
The only thing that exists for the live call is the row, so it clears the numbers, writes
the proof and the client hands over a certificate. The call ends. The **ordinary**
post-call pipeline — no replay, no poller, no retry — then writes everything:

```
AFTER ERASURE   to_e164: (None,)   certificate signed: True
AFTER PIPELINE  turns:  ['naa peru Ravi', 'dhanyavaadalu']
AFTER PIPELINE  call:   (None, None, None, 'agent: dhanyavaadalu')   # summary is back
AFTER PIPELINE  leads for subject: ['+919876520066']                 # the number is back
```

That is DPDP §12 unfulfilled and §8(7) breached, under a document asserting the opposite,
inside the pipeline's own two-minute SLO.

**Then the fix found the deeper one.** Re-filing the erasure was not enough:
the second run reported `calls=0`. `execute_deletion_request` locates a subject's calls
with `from_e164 = :phone OR to_e164 = :phone` and then CLEARS both columns, so after one
erasure that call is unreachable to every future erasure of the same person — the lead was
found, the call was not. That is a standing defect the race merely exposed; it is the same
shape as the orphaned-recording defect SEC-COMP §4 already records ("an erasure made the
audio permanently undeletable").

**What was built.** `calls.erased_subject_ref` (migration `c1e9a4f7d302`) — the one-way
handle the erasure leaves behind when it clears the numbers, the same construction and for
the same reason as `deletion_requests.subject_ref`. The erasure writes it and reads it.
And `compliance/deletion.refile_erasure_for_late_records`, called as STEP 9 of the
pipeline inside the transaction holding its own last writes: if a COMPLETED erasure covers
this call it files a fresh request through the existing producer, with its outbox job.

**The boundary is the call's own start**, and it is the half a careless fix breaks:
`completed_at >= COALESCE(started_at, created_at)`. `request_erasure` already argues that
erasure is not terminal for a phone number — the same person may ring next month and
generate fresh, lawful data — so a rule keyed on the subject alone would destroy records
nobody asked us to destroy. Both halves are tests.

**Sabotage matrix**

| sabotage | expected | observed |
|---|---|---|
| remove the STEP 9 call from `_post_call_stages` | late-arrival test red, later-call test green | exactly that (1 failed, 1 passed) |
| drop `OR erased_subject_ref = :ref` from the erasure's call lookup | late-arrival test red | exactly that |
| drop the `completed_at >= …started_at` clause | later-call test red (over-erasure) | exactly that |

**Residual, named.** The outbound CRM fan-out (step 8) posts the call summary to the
client's own endpoint before step 9 runs. It is not suppressed: the client is the
Fiduciary who received the instruction and already holds the person's record, so this is
their copy returning to them — and suppressing it would leave `crm_notified_at` NULL,
which `_expected_artifacts` reads as an unfinished pipeline and the poller would re-drive
forever. Stated in SEC-COMP §4 rather than left to a reader.

---

## C-3 — 21:00:00 was inside the gate and outside the law

**PROVEN** (`tests/calling_window_boundary_test.py`, 9 cases at the second).

`within_calling_hours` answered `start <= t <= end`, so every dial in the 21:00:00 second
passed. TCCCPR states the rule as a PROHIBITION — no commercial communication *between
2100 hours and 0900 hours* — which makes 21:00:00 the first forbidden instant, not the
last permitted one. The campaign's own narrowed window (`campaign_window_open`) had the
same operator, so a campaign restricted to 09:00–12:00 could dial at 12:00:00.

It also ended a two-convention drift: `agents/business_hours.is_after_hours` has always
used `opens <= t < closes`. One concept, two spellings, disagreeing in the unsafe
direction.

Size stated honestly: one second per window per day. Fixed because the cost is a
comparison operator and the artefact of getting it wrong is a subscriber complaint
timestamped 21:00 — a violation on its face whatever our operator thought.

**Sabotage:** restoring `<=` in `within_calling_hours` reddens 2 tests; restoring it in
`campaign_window_open` reddens 2 others.

---

## C-4 — the hash chain did not cover the address

**PROVEN** (`tests/audit_chain_ip_test.py`, 5 tests).

SEC-COMP §5 asks each audit row for "actor, tenant, at, ip". `scripts/check_audit_ip.py`
exists because that fourth field is the one an impersonation dispute (D-22, D-210) or a
breach timeline turns on, and D-131/D-139 spent a whole sweep making it true. It was not
in the hashed payload — so the row that says an operator entered a client's account from
one address could be rewritten to say another, and `verify_chain` would report the log
clean.

`ip` is now signed. Entries written before it still verify, because `audit_log` is
append-only (hard rule 4) and a change that turned the existing log red would be
indistinguishable from tampering on the day it deployed — the argument `_key_ring` already
makes for keys. Accepting the old payload shape lets an attacker KEEP a row that omits the
ip; it does not let them PRODUCE one, because either shape needs the secret, and the
generation floor that bounds the public generation-0 key is untouched.

`at` is deliberately still outside, stated rather than omitted: it is stamped by
`clock_timestamp()` inside the chain lock and does not exist until the INSERT. An edited
`at` still surfaces as a `link` break in the replay order; an edited `ip` surfaced as
nothing.

**Sabotage matrix**

| sabotage | expected | observed |
|---|---|---|
| drop `"ip": ip` from the hashed payload | the writer test red, the rest green | exactly that |
| drop the legacy-shape fallback from `_matching_generation` | the pre-D-312 test red | exactly that |

---

## C-5 — a scrub that suppressed three admitted three unscrubbed numbers

**PROVEN** (probe, then `tests/national_dnd_test.py::test_the_scrubs_own_suppressions_do_not_make_room_for_unscrubbed_contacts`).

`national_dnd_blocker` refused a list whose live pending count EXCEEDED the scrub's
`submitted_count`. But `submitted_count` is measured BEFORE the provider's blocked numbers
are marked `dnc_blocked`, so a run that suppressed three leaves pending three below the
number it is compared against. Measured on ten contacts:

```
SCRUB RECORDED: submitted_count=10 suppressed=3
ADDED AFTER THE SCRUB: {'added': 3, ...}          # three numbers the register never saw
GATE AFTER ADDING 3 UNSCRUBBED: None              # green
CONTACT COUNTS: [('dnc_blocked', 3), ('pending', 10)]
```

Every other way pending falls — a dial consuming one, the launch DNC pass, an erasure —
widens the same gap. SEC-COMP §3 already stated the rule the code was approximating:
`national_dnd_scrub_incomplete` is for "contacts were added after it ran". It now asks
exactly that, off `campaign_contacts.created_at` against `scrubbed_at` (the instant the
provider fixed the list, not the instant we typed the reference in), and KEEPS the count
comparison as a backstop for the one case a timestamp cannot see: `created_at` is `now()`,
i.e. transaction-start time, so an upload whose transaction opened before the scrub and
committed after it back-dates itself.

The pre-existing growth test was adjusted to add its contacts in a **separate
transaction** — the only shape an upload has in production, and without it the test was
asserting the new rule against a back-dated row.

**Sabotage:** neutering the `created_at > :scrubbed` predicate reddens both the new test
and the pre-existing growth test.

---

## What did NOT break — attacked and refused

Each of these was driven or read against the current tree. None yielded.

**The dial gate cannot be skipped (PROVEN by the guardrail + read).**
`check_compliance_invariants` reports *4 dial sites all gated and obeying the decision, 3
engine reaches all accounted for*. The guard is structural over the enclosing-function
chain and over the live registry, not over a remembered list of surfaces; the two
`scripts/pilot/*` exemptions still name real reaches with reviewable reasons. The engine
port's outbound start remains the single vendor-facing dial, and `VoiceEngine.transfer` —
the other way a phone could ring — **has no caller anywhere in `apps/`**, so there is no
second path to gate today.

**The truthful-answer floor survives the new engine-hosting shapes (REASONED, freshly
verified upstream).** `require_call_compliance_floor` is asked what the ADAPTER PUTS ON
THE WIRE rather than what it received; `_call_prompt_for` composes that string through
`compose_engine_prompt` and nowhere else, and returns `None` only for engines that host
the agent (where `publish_agent` wrote it and `verification.judge` scored it). An
`external_deployment` adapter with no prompt field passes `None` and refuses every dial.
The invariants script now counts *5 adapter modules holding the rule in the home their
declared agent hosting gives it*. No dial could be produced whose prompt lacks the floor.

**A global DNC suppression cannot be destroyed by the tenant it was made against
(PROVEN).** As a tenant session against a `scope='global'` row: the row is VISIBLE (by
design — a client should know a number is suppressed), the ORM path refuses it by name,
and the raw statements are refused by the database:

```
TENANT SEES GLOBAL ROW: [(…, 'global', None)]
TENANT RAW DELETE rowcount: 0
TENANT scope=global INSERT refused: ProgrammingError
TENANT scope UPDATE refused: InternalError
GLOBAL ROW AFTER ATTACKS: [('global', None)]
```

**`consent_ledger` is INSERT-only against the app role (PROVEN).** `UPDATE` and `DELETE`
both refused by the trigger; a wrong entry can only be compensated by a later row.
`check_ledger_immutability` verifies all 8 ledgers' triggers are `ENABLE ALWAYS` and
raising.

**The recording retention floor cannot be lowered (PROVEN).** `ttl_days` of 1, 30 and 89
on the `recording` category are all refused by the DB CHECK; `apply_retention` clamps to
`RECORDING_FLOOR_DAYS` independently.

**DNC propagation before the next tick (REASONED, and re-read at the code).**
`_dispatch_for_campaign` commits the claim and then re-reads `campaign_dialable_now` AND
`check_dispatch` per contact, each in its own transaction — so an opt-out committed by
another connection mid-batch blocks the very next contact, not the next tick. The DNC read
is uncached by construction and covers tenant and global rows in one statement.

**A caller's opt-out cannot be downgraded (REASONED, D-189's fix re-read).**
`add_to_dnc`'s `ON CONFLICT` upgrade is stated in both directions, so a `manual` add can
never weaken a `call_optout` row, and `REMOVABLE_SOURCES` has one definition re-exported
rather than copied.

**The 90-day re-solicitation bar (REASONED).** It is enforced structurally rather than by
a clock: a `call_optout` suppression is permanent and non-removable, which is stricter than
the ninety days TCCCPR requires, and `compliance/optout.py` carries the sourcing.

**Campaign contacts cannot be swapped under a scrub (PROVEN by inventory).** There is no
`DELETE FROM campaign_contacts` anywhere in `apps/`, and `add_contacts` refuses anything
past `scheduled` — so a list cannot be quietly exchanged for a different one of the same
size, which was the first attack tried against C-5's fix.

**Hard rule 6 on this surface (PROVEN by sweep).** Every `log.*`, `alert`, `span` and
metric call in `apps/api/compliance`, `apps/api/campaigns` and `apps/workers` was walked
by AST for arguments carrying a number, transcript text, extraction payload or a lead
name. The only hits are ids, counts, hashes (`subject_ref`), engine names and email
DOMAINS. The one call that logs a full subject line is `ConsoleTransport`, which the
transport factory refuses outside `local`.

**Impersonation attribution on entry and renewal (REASONED).** D-210's grant carries
`auth_time`; `admin.impersonation_started` records `auth_time`, `renews` and `window_s`,
so the ledger distinguishes an operator walking through the door from a session extending
itself, and `admin.impersonation_read` joins to it by `grant_id`. 15 tests already drive
it; nothing here weakened and nothing new was found.

**Erasure vs. the retention floor (REASONED, deliberately untouched).** SEC-COMP §4
forbids making the pointer-clear conditional on age before the founder's decision is
taken. Nothing in this pass narrows the certificate's limitations text or moves
`erase_after`.

---

## Named, not taken: an in-call opt-out does not withdraw MESSAGING consent

**REASONED, and deliberately not fixed here — it is a founder's call, not an engineering
gap.** `record_call_optout` writes a `dnc_list` suppression (which is what actually stops
the dial) and a `consent_ledger` row under `purpose='marketing'`. The WhatsApp path reads
`purpose='messaging'` and the dial gate reads `purpose='callback'`, so a caller who says
*"naa number teeseyandi"* on a call is un-dialable immediately and, if they had previously
opted in to messaging, still receives the campaign follow-up.

The repo's own doctrine says this is correct: SEC-COMP §4 and `compliance/consent.py`
argue at length that messaging consent "is its own permission and is never inferred", that
DPDP §6 binds consent to the purpose it was given for, and that "a person may accept a
call and refuse a message, and both answers are theirs". The mechanism to do otherwise
exists — `WITHDRAWAL_ONLY_CONSENT_SOURCES` is there precisely so a withdrawal can be
recorded on a customer's behalf — so this is one line, not a project.

What stops it being taken here: writing a `messaging` withdrawal the caller did not utter
puts words in their mouth in an APPEND-ONLY legal register (hard rule 4) that can never be
corrected, only compensated. "Stop calling me" and "stop contacting me" are different
sentences and the phrase list cannot reliably tell them apart. Both readings are
defensible; the choice is a commitment about how this product interprets a consumer, which
is the founder's, and it is recorded here rather than decided.

## The gate run behind this pass

`ruff check`, `ruff format --check`, `mypy apps packages` (with the error-reporting group
installed — without it the Sentry hook's `type: ignore` reads as unused, which is an
environment artefact rather than a finding), and the six guardrails:
`check_compliance_invariants`, `check_ledger_immutability`, `check_rls_coverage`,
`check_docs_drift`, `check_metadata_columns`, `check_audit_ip` — all OK.

The FULL suite: **5589 passed, 1 skipped, 2 xfailed, 3 failed** in 11m23s, and the three
are accounted for rather than waved past:

* `docs_drift_guard_test::test_catches_a_dangling_reference_in_a_doc` — a real break
  caused by this pass and FIXED here. Its negative control asserted that a real citation
  was not reported, as a SUBSTRING test, and the number it derives from the live log grew
  into the same first three characters. Whole-token now.
* `pilot_cli_test::test_preflight_names_the_gates_each_missing_item_blocks` — environment.
  It asserts the preflight reports a MISSING `BOLNA_API_KEY`; this worktree's `.env` is a
  copy of the real one and carries a key, which `Settings` reads. Fails identically
  without any change from this pass.
* `engine_readiness_credentials_test::test_bolna_still_answers_exactly_as_it_did` — passes
  standalone and in its own file (9/9); a state leak from a neighbour under
  `-p no:randomly`, not a regression here.

## Still open, and what closes each

* **Whether the engine honours a deletion.** `engine_deletion` stays
  `unconfirmed_pending_vendor_api`. External: a Bolna account and the written erasure
  commitment (pilot gate 12(f)).
* **Whether a recorded national-DND scrub was actually performed.** The reference is taken
  from an operator and never queried back (`UNVERIFIED_SCRUB_EVIDENCE`). External: a
  Registered Telemarketer relationship and a DLT platform login — the same one
  `tm_registration_missing` already blocks on.
* **The retention-defaults divergence and the under-floor recording question.** Both are
  founder decisions recorded in SEC-COMP §4; this pass deliberately did not take either.
* **A data principal holding certificate #1 is not told about certificate #2.** The client
  (the Fiduciary who hands the document on) sees both requests and both proofs; wiring the
  second certificate back to the first request's status page is a product decision about
  what a client forwards, not a defect — named here so it is not lost.
