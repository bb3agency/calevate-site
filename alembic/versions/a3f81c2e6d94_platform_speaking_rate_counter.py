"""platform_speaking_rate: the fleet's agent characters per call-minute, as a counter

Revision ID: a3f81c2e6d94
Revises: f7c2a94e18b3
Create Date: 2026-09-09

**THE COST MODEL'S BIGGEST UNMEASURED LEVER, WIRED TO SOMETHING THAT MOVES (D-557).**
`rates.TTS_ASSUMED_CHARS_PER_CALL_MINUTE` is TRD §10.1's 360-540 band, which the doc itself
calls unmeasured (pilot gate 12), and it swings the Clear cost floor between ₹3.70 and
₹4.12 a minute. `billing/tts_speaking_rate.py` has measured the real figure from our own
transcripts for weeks — and NOTHING CONSUMED IT: every floor, margin and break-even still
divided by 540 while the measurement sat on an operator's board. This table is what closes
that loop.

**WHY A COUNTER AND NOT THE WALK THAT ALREADY EXISTS.** The measurement's fleet reader
(`spend_routes.fleet_tts_speaking_rate`) walks the client book — one `tenant_session` per
account — because `calls` and `transcript_turns` FORCE RLS and an untenanted read of either
returns zero rows and reports success. That shape is right for a board an operator OPENS
(it is the only way to get p50/p95 at all, since percentiles need per-call samples) and it
is wrong for anything a page renders: measured on this repository's own development
database, 8,480 organizations, the identical shape turned ONE rate-card read into 8,480
session checkouts (`f7c2a94e18b3`, D-556). The cost model needs the POOLED figure and
nothing else, and a pooled figure is three running totals — so it is a counter, moved in
one statement by the meter that already writes the per-tenant rows.

**THREE INDEPENDENT TOTALS, NONE DERIVED FROM ANOTHER.** `agent_chars` is what the agent
actually said (`transcript_turns`, agent turns only), `call_seconds` is what those same
calls actually lasted, and `calls` is how many there were. Pooled rate = chars x 60 /
seconds, exactly `tts_speaking_rate.summarize`'s arithmetic; `calls` is what the
publication threshold is judged against, and without it the same twenty-call bar could not
be applied to this reader.

**IT COUNTS EVERY VOICE, WHICH IS WHY IT IS NOT A COLUMN ON `platform_tts_volume`.** That
table is a BILLING volume: Cartesia characters, only for calls whose leg could be priced,
because it prices a subscription. A speaking rate is a fact about how our AGENTS talk — the
same fact whichever vendor synthesizes it — and it is applied to the Clear floor, which is
the Sarvam-voiced one. Different population, different key (no provider), different
question. Adding a row to that table would have made `fleet_cartesia_volume` mean something
else.

THE BACKFILL IS THE ONE THING A MIGRATION CAN DO THAT THE APPLICATION CANNOT: it runs as
the table OWNER and is not subject to RLS, so the calls already in the archive can be
summed once, across every tenant, here. Its predicate is the walk's own predicate — a call
with a transcript and a positive duration — so on the day this lands the counter and the
walk are two spellings of one measurement (`tests/tts_speaking_rate_loop_test.py` scores
them against each other rather than trusting that).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3f81c2e6d94"
down_revision = "f7c2a94e18b3"
branch_labels = None
depends_on = None

TABLE = "platform_speaking_rate"

#: The IST cut, as SQL because a migration cannot import the application.
#: `billing/plans.ist_billing_month` is the Python twin the meter uses, and
#: `tests/tts_speaking_rate_loop_test.py` scores the two spellings against each other.
#: `ended_at` first because that is the instant the meter attributes a call by
#: (`workers/pipeline._meter` passes `snapshot.ended_at`); `started_at` for a row the engine
#: never closed, and `created_at` for one that has neither.
_IST_MONTH = (
    "to_char(COALESCE(c.ended_at, c.started_at, c.created_at) AT TIME ZONE 'Asia/Kolkata', "
    "'YYYY-MM')"
)

#: **THE WALK'S OWN PREDICATE, SPELLED ONCE MORE.** `billing/tts_speaking_rate
#: ._AGENT_CHARS_PER_CALL` samples every call with a transcript and `duration_s > 0`, one
#: sample per call, agent turns only, reading `COALESCE(text_redacted, text)` — an aggregate
#: `length()` returns no character of text, so hard rule 5 is not engaged, and reading the
#: default-redacted column keeps this inside that rule's default. A call whose transcript
#: holds only caller turns still counts, as a zero: it IS a call with a transcript and its
#: agent spoke nothing, which is a rate too.
_BACKFILL = f"""
INSERT INTO {TABLE} (month, calls, agent_chars, call_seconds, updated_at)
SELECT month, count(*), SUM(agent_chars), SUM(duration_s), now()
  FROM (
        SELECT {_IST_MONTH} AS month,
               c.duration_s AS duration_s,
               COALESCE(SUM(length(COALESCE(t.text_redacted, t.text)))
                        FILTER (WHERE t.speaker = 'agent'), 0) AS agent_chars
          FROM calls c
          JOIN transcript_turns t ON t.call_id = c.id
         WHERE c.duration_s > 0
         GROUP BY c.id, c.duration_s, month
       ) per_call
 GROUP BY month
ON CONFLICT (month) DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        TABLE,
        # IST billing month, 'YYYY-MM' — `billing/plans.ist_billing_month`'s own cut.
        sa.Column("month", sa.Text(), nullable=False),
        # How many calls the three totals below were pooled over. The publication threshold
        # (`tts_speaking_rate.TTS_SPEAKING_RATE_MIN_CALLS`) is judged against the SUM of
        # this column over the window a reader asks for.
        sa.Column("calls", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        # Characters of AGENT speech. A count of characters is an integer; it is BIGINT
        # rather than NUMERIC because nothing here divides before summing.
        sa.Column("agent_chars", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        # Seconds of CALL those characters were spoken across — the denominator, in the unit
        # every duration in this codebase already lives in (`ExecutionSnapshot.duration_s`,
        # `pipeline._billable_seconds`). NUMERIC because the meter's own duration is a
        # Decimal and rounding it on the way in would move the rate it divides into.
        sa.Column("call_seconds", sa.Numeric(18, 4), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("month", name=op.f(f"pk_{TABLE}")),
        # A total that can go backwards is a speaking rate a bug can talk down, and a LOWER
        # speaking rate is the flattering direction: it makes the TTS leg, and so the floor
        # every rate card is judged against, cheaper than it is.
        sa.CheckConstraint(
            "calls >= 0 AND agent_chars >= 0 AND call_seconds >= 0",
            name=op.f(f"ck_{TABLE}_non_negative"),
        ),
    )
    # NO RLS AND NO POLICY, deliberately, exactly as `platform_tts_volume` and
    # `platform_ai_spend`: this table has no `tenant_id` and could not have one — the whole
    # question it answers is cross-tenant. It holds three aggregates and no text, so nothing
    # a policy protects is in it (hard rule 6: it cannot hold a phone number or a turn).
    op.execute(_BACKFILL)


def downgrade() -> None:
    # Safe to drop outright: every figure here is re-derivable from `calls` and
    # `transcript_turns`, which is exactly what the backfill above does.
    op.drop_table(TABLE)
