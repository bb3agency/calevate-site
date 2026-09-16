<!-- EVIDENCE CLASS: DESIGN, grounded in facts verified in this tree on 16 Sep 2026 and cited
     inline. This is the contract two halves are built against — `apps/voice-worker` (the
     client) and `apps/api` (the server) — and it exists so the two cannot drift apart while
     they are written. It is NOT a vendor claim: nothing here is about Pipecat Cloud's API,
     only about ours. -->

# The worker→API contract (D-621): what replaces the worker's database connection

> **STATUS: BUILT, 16 Sep 2026.** Both halves exist — `apps/api/worker/` serves the three
> endpoints and `apps/voice-worker/voice_worker/api_client.py` + `sink.py` + `config.py`
> speak to them. `DEPLOYMENT.md` §12.5 gate 6 is closed. Every item under *What must be
> true when this is finished* is asserted by a test named in the list below; two things
> in the design as first written turned out to be wrong and are corrected in place, each
> marked ⚠ where it stood.

## Why this exists

`docs/DEPLOYMENT.md` §12.5 **gate 6**: the voice worker runs on Pipecat Cloud (box 1) and
**cannot reach our Postgres at all** — that database runs on the VPS host and is reached
only over the Docker bridge (`compose.prod.yml:36`, `DEPLOYMENT.md:102`). Found by running
`voice-worker-setup.sh sources` on the deploy host, where `psql` could not translate
`host.docker.internal`.

Of the four options recorded at gate 6, this builds the third: **the worker stops touching
Postgres and speaks HTTP to `apps/api`.** It is the only one that does not put the database
holding every client's caller data on the public internet, and the only one whose fix is
entirely ours — the other three wait on vendor egress ranges, a database migration, or a
private-link feature nobody has confirmed exists.

There is precedent in this tree and it is not a new shape: `voice_worker/memory.py` already
reads caller memory over HTTP rather than from the database the container was connected to,
and its stated reason generalises to everything below — *"Installing the platform's master
key there to save a network hop on the RING, where nobody is waiting, is not a trade worth
making."*

## The facts this design rests on, each verified rather than assumed

| Fact | Where it was checked |
| --- | --- |
| The worker writes **no money rows today**. `CallMeter.metered_rows` raises `CarrierFactsMissingError` on a missing CDR *before* pricing anything, and there is no CDR (BLOCKER-1). Every production call settles as ONE `call_metering_refusals` row. | `voice_worker/meter.py:686-704`, `runtime.py`'s own "⚠ Today both are `None` on every production call" |
| A rate card reaches the worker only as a constructor argument, never from the environment — hard rule 7 showing through the bootstrap. | `runtime.WorkerRuntime.from_env` |
| `transcript_turns` is UNIQUE on `(call_id, idx)`. | `alembic/versions/05bba2f3c19c…:489`, `crm/models.py:213` |
| Settlement's three writes — call row, ledger-or-refusal, and the outbox row that triggers the post-call pipeline — are ONE transaction, and that is D-607's whole guarantee. | `voice_worker/sink.py`, the `settle` transaction |
| Turns are buffered and flushed in batches, so the write surface is already batch-shaped. | D-620, this session |
| Nothing reads a transcript turn while the call is running. | Every reader is post-call; no `refetchInterval` on any transcript surface in `apps/web` |
| The worker already authenticates to `apps/api` with a Bearer token from `Settings`. | `compliance/caller_data_routes.py:107-126`, `voice_worker/memory.py:205` |

## The shape, and the one rule that decides it

**THE WORKER SENDS WHAT IT OBSERVED. THE SERVER DECIDES WHAT THAT MEANS.**

The worker is compute on a third party's infrastructure. It may report quantities, turns and
statuses; it may not compute money, hold a rate card, resolve a tenant, or name a row id. The
server prices, applies RLS, mints ids and writes. This is not defensive styling — it is what
lets `PLATFORM_KEK` and the database credential stay on our side of the wall, which is the
entire point of choosing option 3.

Two consequences that look like restrictions and are the design:

* **Idempotency is the server's job, keyed on facts the worker already has.** Turns key on
  `(call, idx)` — a constraint that already exists. A retried batch inserts nothing twice.
  Settlement keys on the call: it is applied once and a repeat is reported, not re-applied.
* **The worker never sees a `calls.id`.** It knows its own `engine_call_id`
  (`pipecat_call_ref(tenant, call_id)`), which the server resolves under RLS. A worker that
  could name a row id could name somebody else's.

## The endpoints

All under `/v1/worker`, all Bearer-authenticated, none in the public OpenAPI surface a
browser client consumes.

### `GET /v1/worker/session/{engine_agent_ref}`

Replaces `config.load_session_config`'s SELECT. Answers the published agent's config version,
prompt, resolved `ModelConfig`, language, disclosure lines and `knowledge_pack_sha256`.

Refuses with `404` when the ref names no published agent — the same answer
`carrier_routes.plivo_answer` gives for an unknown ref, and for the same reason: a stranger
who guesses learns nothing.

### `POST /v1/worker/calls/{engine_call_id}/observations`

One batch, mixed: call status events and transcript turns. Both are things the worker
*witnessed*.

⚠ **THE BATCH ALSO CARRIES `agent_id` AND `direction`, WHICH THIS DESIGN OMITTED.** They
are session facts, and without them the FIRST batch of a call — routinely a flush of turns,
because Pipecat dispatches every handler as its own task and a turn can beat the event that
opened the call — names nothing the server can mint a `calls` row from. `TranscriptTurn`
carries neither and `CallEvent` declares `agent_id` nullable. The in-process sink never had
this problem because it held the session's four ids; the wire model now does the same.

⚠ **AND THE SERVER REDACTS.** Not stated here at all when this was written, and it is the
one behaviour change the move makes rather than relocates: `text_redacted` is the column
every content reader in this repository names, so its value may not be one computed by a
container a vendor's runtime operates. `apps/workers/redaction.redact` is still the one
redactor; it now runs where the row is written, and a `text_redacted` arriving in the body
is ignored. The server upserts the call row, inserts turns `ON CONFLICT DO NOTHING`, and
moves status forward only (never backward — the existing rule).

Batched because turns already are (D-620), and because one authenticated round trip per
flush is the number this design is trying to keep small.

### `POST /v1/worker/calls/{engine_call_id}/settlement`

The terminal write, and the one that carries D-607. The worker sends either the refusal it
reached (leg, code, detail) or the metered quantities; the server writes the call row, the
ledger-or-refusal and the outbox row **in one transaction**, exactly as `sink.settle` does
today. The guarantee is relocated, not weakened — and it moves to the side that owns the
database, which is where a transaction belongs.

## What must be true when this is finished

1. `DATABASE_URL` is **gone** from the worker's environment contract, and `--preflight`
   no longer asks for it. That is the pass condition for gate 6.
2. There is **one** way the worker records a call. `DatabaseEventSink` does not survive
   alongside an HTTP one — "migrate rather than accumulate", and two writers of one ledger
   is the drift this repository keeps guards for.
3. Nothing in `apps/voice-worker` imports SQLAlchemy.
4. A retried batch and a retried settlement both leave the database exactly as one delivery
   would, proven by a test that sends each twice.
5. The endpoints refuse an unauthenticated caller, and refuse a `engine_call_id` whose
   tenant does not match the token's deployment.

## Where each of those five is asserted

| # | Clause |
| --- | --- |
| 1 | `tests/voice_worker_sink_test.py::test_the_worker_declares_no_database_driver`; `boot.load_worker_config` names neither a DSN nor `DATABASE_URL` (`tests/voice_worker_boot_test.py`) |
| 2 | `voice_worker/sink.py` holds ONE sink class; `tests/voice_worker_sink_test.py::test_the_client_is_the_only_way_the_worker_reaches_the_platform` |
| 3 | `tests/voice_worker_sink_test.py::test_nothing_in_this_container_imports_sqlalchemy` |
| 4 | `tests/worker_api_test.py::test_the_same_observation_batch_twice_leaves_exactly_one_row_per_turn` and `::test_the_same_settlement_twice_writes_one_refusal_and_answers_already_settled`, plus their client-side twins in `voice_worker_sink_test.py`. Both sabotage-checked. |
| 5 | `tests/worker_api_test.py::test_every_route_refuses_a_caller_with_no_token`, `::test_an_unconfigured_deployment_authenticates_nobody`, `::test_a_call_ref_naming_another_tenant_cannot_be_written_through` |

**A SIXTH PROPERTY THIS DESIGN DID NOT NAME AND SHOULD HAVE**, because it is the one a
reviewer asks about first: what stops a token holder reaching another client's call? Not the
token — the REF. The tenant is parsed out of `pipecat:<tenant>:<call>`
(`tenant_of_pipecat_ref`) and every statement then runs under that tenant's RLS, so a leaked
token reaches exactly the calls whose refs it holds and no others. That is why the worker
never sends a `calls.id`, and it is asserted by the tenancy clause above.
