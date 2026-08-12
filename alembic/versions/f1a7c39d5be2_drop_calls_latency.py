"""drop calls.latency — a column that promised a measurement nobody can make yet

Revision ID: f1a7c39d5be2
Revises: c4d9e18a72b6
Create Date: 2026-08-12 15:00:00.000000

`calls.latency JSONB` was declared in the first migration (05bba2f3c19c) to hold
`{stt_ms, llm_ttft_ms, tts_ttfa_ms, turn_p50, turn_p95}`. It has never been written.
`scripts/check_wiring.py` has recorded it in `UNWIRED_BASELINE` since that guard landed,
TRD §4 says in as many words that "the rule stands and the mechanism does not exist",
and every `calls` row in every environment reads NULL for it.

This migration removes it. What follows is why removing beat filling, because the
opposite case got stronger since the column was declared and deserves to be answered
rather than ignored.

THE CASE FOR FILLING IT, WHICH IS REAL
--------------------------------------
Distributed tracing shipped end to end (`apps/api/core/observability.py`): a W3C
traceparent rides the ARQ payload, `apps/workers/pipeline.py` opens a named span per
stage, and voice-runtime stamps its ack. So SOMETHING is now measured that was not
before, and three properties a column has and a span does not are all genuinely in play
here:

* **Queryable in SQL, beside the call it describes.** "p95 turn latency for this tenant's
  agent last week" is a join in Postgres and a support ticket in a trace UI.
* **It survives sampling.** `init_tracing` samples at `ParentBased(TraceIdRatioBased)`
  with a default ratio of 0.1 — nine calls in ten have NO span at all, so a per-call
  latency read off traces is a latency for a tenth of the calls.
* **It outlives trace retention.** Spans age out on the backend's schedule; a call row is
  kept to the tenant's retention policy.

If the numbers TRD §4 asks for existed anywhere in this system, those three would settle
it and the column would stay and be filled.

WHY IT STILL GOES: THE SPANS MEASURE A DIFFERENT SYSTEM
-------------------------------------------------------
Every span this repo opens is on OUR side of the call. `pipeline.call_upsert`,
`pipeline.extract`, `pipeline.lead_upsert`, `webhook.fastpath`, the ack timer — that is
the POST-CALL path, and the SLO it exists for is "lead visible within 2 minutes of
hangup" (OPERATIONS §5). The in-call audio path — caller stops speaking, STT finalises,
LLM emits a first token, TTS emits first audio — happens entirely inside the rented
engine (D-31), in a process we do not run, on a machine we do not own. No span of ours
is inside it and none can be. Writing pipeline-stage timings into a column called
`latency` on a voice call would be a lie with a plausible name on it, and the next
person's dashboard would report a 40-second "latency" that is the engine's own 2–3
minute wait for `completed` (TRD §5) rather than anything a caller experienced.

WHAT THE ENGINE ACTUALLY REPORTS — AND THE FINDING THAT CHANGES A GATE
----------------------------------------------------------------------
`ExecutionSnapshot` (packages/shared/src/calevate_shared/engine.py) carries no timing
finer than `duration_s`, and `BolnaEngine._snapshot` maps nothing finer: `transcript`
comes from `parse_transcript`, which reads prefix-tagged plain text and leaves
`TranscriptTurn.start_ms` / `end_ms` NULL for every Bolna turn. So today nothing reaches
this column even if it stayed.

But the adapter's standing claim — "per-turn timings are not exposed" — is NO LONGER
TRUE OF THE VENDOR'S DOCUMENTATION, and that is a finding, not a footnote. Bolna
documents a `latency_data` object on the Get Execution response
(bolna.ai/docs/concepts/call-latencies, last updated 2026-07-01), holding `stream_id`,
`region`, `time_to_first_audio`, and per-component `transcriber` / `llm` / `synthesizer`
blocks with a `time_to_connect` and a `turns` array; the published sample values
(130.84, 20.12) read as milliseconds, and their OSS engine's `LatencyData`
(bolna/llms/types.py: `first_token_latency_ms`, `total_stream_duration_ms`) uses
millisecond floats, which corroborates it.

That still does not make this column fillable today, for three reasons that are about
correctness rather than effort:

1. **It is not the same set of numbers.** `time_to_first_audio` is the FIRST greeting
   after pickup — the cold-start number OPERATIONS §2 gate 4 says to record SEPARATELY —
   not per-turn responsiveness. `audio_to_text_latency` is documented as one entry per
   partial refinement, which is not "STT finalisation" as TRD §4 budgets it. And nothing
   there is voice-to-voice: `turn_p50` / `turn_p95` would be OUR arithmetic aligning
   three components by `sequence_id`, which is a model of the engine's pipeline, not a
   measurement of it.
2. **There is nothing to validate that arithmetic against.** D-39(b) is explicit: zero
   real-PSTN measurements, sequence is measure → budget → optimise. A derived p95 that
   has never been checked against gate 4's stopwatch is precisely the guesswork that
   decision forbids, and it would be indistinguishable from a measurement once it is
   sitting in a column named `latency`.
3. **The object carries transcript text.** The documented `transcriber.turns` entries
   include the recognised `text`. A mapper that stored `latency_data` as it arrives would
   put raw caller utterances into a JSONB column with no `text_redacted` counterpart —
   hard rules 5 and 6 — which is the same trap `KbRetrievalLog.query` is deferred for.

So the honest sequence is the one this repo already uses for every other unverified
vendor claim (D-31/D-32, and the adapter's own standing warning that every field name is
a claim until a payload is captured): **capture `latency_data` as an adapter fixture at
pilot gate 4, beside the stopwatch that can falsify it, and decide the column's SHAPE
from the payload** — very likely typed `INT` columns rather than a JSONB bag, since the
whole point is to aggregate them in SQL. Re-adding a column is one migration. Removing a
number people have already trusted is not.

DOCS THIS CONTRADICTS (owned elsewhere; flagged, not edited)
------------------------------------------------------------
* TRD §4 describes `calls.latency` as "declared and deliberately unwired" — it is now
  dropped, and the gate-4 capture above is the mechanism sentence that replaces it.
* DATA-MODEL §4's `calls` DDL still lists `latency JSONB`.
* OPERATIONS §4's dashboard list keeps "latency stage breakdown (stt/llm_ttft/tts_ttfa/
  turn p50/p95)" — a dashboard with no source, which is what this drop makes visible.
* OPERATIONS §2 gate 4 should gain: capture `latency_data` from Get Execution alongside
  the stopwatch, and record whether the two agree.

LOCKING (hard rule 8)
---------------------
`DROP COLUMN` is a catalogue write in Postgres — the column is marked dropped, no table
rewrite — but it takes ACCESS EXCLUSIVE on `calls`, which conflicts with every reader.
`calls` is written by the post-call pipeline and read by both dashboards, so the lock is
taken under `lock_timeout` and the migration fails fast rather than queueing in front of
every query on the busiest table in the schema. The same applies to the downgrade's ADD
COLUMN, which is likewise catalogue-only (no default, so no rewrite).

REVERSIBILITY
-------------
The downgrade restores `latency JSONB NULL` exactly as it was, and — uniquely for a
column drop — loses nothing at all, because the column never held a value in any
environment. Proven by upgrade → downgrade → upgrade on a scratch database, not assumed.

TWO-STEP DEPRECATION (hard rule 8)
----------------------------------
Rule 8 forbids dropping in the same release that stops WRITING a column. Both halves are
in this one change because there is no writer and no reader to stage: the wiring guard's
baseline is the standing evidence that no code in `apps/` or `packages/` touches the name
at all, and `tests/call_latency_column_test.py` re-establishes that from the tree rather
than from the registry. The registry entry goes with the column — the baseline may only
shrink.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a7c39d5be2"
down_revision: str | None = "c4d9e18a72b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("calls", "latency")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "calls",
        sa.Column("latency", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
