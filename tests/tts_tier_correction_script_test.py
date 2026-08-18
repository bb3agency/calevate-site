"""The compensating entry for a mis-tiered call has a production entrypoint (P1.6).

`billing.service.record_tier_correction` is the ONLY lawful repair for a call metered on
the wrong TTS rung — `usage_events` carries an immutability trigger, so the row cannot be
edited and hard rule 4 forbids trying. Its only callers were in `tests/`, which means a
mis-billed call in production had no remedy short of hand-written psql against an
append-only table. `scripts/correct_tts_tier.py` is that caller, and this file is what
makes it one: a script nothing exercises is the same defect one directory over.

Three properties, and each is a way an operator-driven correction goes wrong:

* it does NOT write on a dry run — the default;
* it reads `billed_tier` OFF THE LEDGER rather than taking the operator's word for it;
* the same file re-run after a crash corrects nothing twice, and corrects every call in a
  batch exactly once.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from apps.api.billing import rates
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from scripts import correct_tts_tier as script
from sqlalchemy import text
from tests.tts_tier_metering_test import _meter, _snapshot, _tenant_with_call


async def _corrections(tenant_id: uuid.UUID) -> list[dict[str, object]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_cost_paid, meta FROM usage_events WHERE tenant_id = :t "
                    "AND meta->>'kind' = 'tts_tier_correction' ORDER BY id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [{"cost": row[0], "meta": row[1]} for row in rows]


def test_the_cli_vocabulary_is_the_rate_card_and_cannot_drift_from_it() -> None:
    """A rung priced by `rates` that an operator cannot name is a call nobody can correct;
    a rung an operator CAN name that has no price is a KeyError on a money path."""
    assert set(script.TIER_CHOICES) == set(rates.TTS_INR_PER_10K_CHARS)


async def test_a_dry_run_reports_the_correction_and_writes_nothing() -> None:
    tenant_id, call_id = await _tenant_with_call("cliDry", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot())

    rows = await script.correct(
        tenant_id=tenant_id,
        ref="sarvam-dry",
        entries=[(call_id, 10_000, "value")],
    )

    assert [row.status for row in rows] == ["pending"]
    assert rows[0].billed_tier == "premium"
    # ₹30 assumed against ₹15 actually incurred on 10,000 characters.
    assert rows[0].delta_inr == Decimal("-15.0000")
    assert await _corrections(tenant_id) == [], "a dry run is the default and it writes nothing"
    report = script.format_report(rows, applied=False, ref="sarvam-dry")
    assert "DRY RUN" in report and "--apply" in report


async def test_the_billed_rung_comes_off_the_ledger_and_not_off_the_operator() -> None:
    """The operator supplies what they can KNOW — the characters and the rung that ran,
    both from the vendor's usage export. What the call was BILLED at is a fact this system
    already holds, and asking a human to restate it is how a correction ends up writing the
    delta between two rungs the call was never on.

    The call below was metered on the VALUE rung, so a correction to premium is a charge
    UP, and the delta must be computed from `value`, not from anything typed in.
    """
    tenant_id, call_id = await _tenant_with_call("cliLedger", voice="bulbul:v2")
    await _meter(tenant_id, call_id, _snapshot())

    rows = await script.correct(
        tenant_id=tenant_id, ref="sarvam-up", entries=[(call_id, 10_000, "premium")], apply=True
    )

    assert rows[0].billed_tier == "value"
    assert rows[0].delta_inr == Decimal("15.0000")
    written = await _corrections(tenant_id)
    assert len(written) == 1
    assert Decimal(str(written[0]["cost"])) == Decimal("15.0000")
    assert written[0]["meta"]["billed_tier"] == "value"  # type: ignore[index]


async def test_a_call_already_on_that_rung_is_skipped_rather_than_zero_billed() -> None:
    tenant_id, call_id = await _tenant_with_call("cliNoop", voice="bulbul:v2")
    await _meter(tenant_id, call_id, _snapshot())
    rows = await script.correct(
        tenant_id=tenant_id, ref="sarvam-noop", entries=[(call_id, 10_000, "value")], apply=True
    )
    assert [row.status for row in rows] == ["already_on_that_rung"]
    assert await _corrections(tenant_id) == []


async def test_a_call_this_tenant_does_not_have_is_reported_and_exits_nonzero() -> None:
    """A file naming a call from the wrong account must not read as a clean run. Under RLS
    "no such call" and "another tenant's call" are the same answer, deliberately."""
    tenant_id, _ = await _tenant_with_call("cliMissing", voice="bulbul:v3")
    stranger = uuid7()
    rows = await script.correct(
        tenant_id=tenant_id, ref="sarvam-miss", entries=[(stranger, 100, "value")], apply=True
    )
    assert [row.status for row in rows] == ["no_such_call"]


async def test_one_reference_over_two_calls_corrects_both_and_replays_neither() -> None:
    """A vendor export covers a batch. Re-running it after a crash must correct nothing
    twice — a second compensating entry can never be deleted, only compensated again.
    """
    tenant_id, first = await _tenant_with_call("cliBatch", voice="bulbul:v3")
    second = uuid7()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT agent_id FROM calls WHERE id = :c"), {"c": first})
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": second, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    await _meter(tenant_id, first, _snapshot())
    await _meter(tenant_id, second, _snapshot())

    entries: list[tuple[uuid.UUID, int, str]] = [
        (first, 10_000, "value"),
        (second, 20_000, "value"),
    ]
    written = await script.correct(
        tenant_id=tenant_id,
        ref="sarvam-batch",
        entries=entries,  # type: ignore[arg-type]
        apply=True,
    )
    assert [row.status for row in written] == ["written", "written"]

    replayed = await script.correct(
        tenant_id=tenant_id,
        ref="sarvam-batch",
        entries=entries,  # type: ignore[arg-type]
        apply=True,
    )
    assert [row.status for row in replayed] == ["already_corrected", "already_corrected"]

    costs = [Decimal(str(row["cost"])) for row in await _corrections(tenant_id)]
    assert sorted(costs) == [Decimal("-30.0000"), Decimal("-15.0000")], (
        "every call in the batch is corrected exactly once, at its own character count"
    )


def test_the_csv_reader_refuses_a_malformed_line_rather_than_skipping_it(
    tmp_path: Path,
) -> None:
    """A correction file whose bad rows are silently dropped is a batch that reports
    success having corrected some of it — the half-applied shape hard rule 4 keeps out of
    the ledger."""
    good = tmp_path / "good.csv"
    good.write_text(f"call_id,chars,actual_tier\n{uuid7()},10000,value\n", encoding="utf-8")
    assert len(script.read_csv(good)) == 1

    short = tmp_path / "short.csv"
    short.write_text(f"{uuid7()},10000\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected call_id"):
        script.read_csv(short)

    bad_tier = tmp_path / "tier.csv"
    bad_tier.write_text(f"{uuid7()},10000,bulbul:v2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not one of"):
        script.read_csv(bad_tier)


def test_the_two_argument_shapes_are_alternatives_and_neither_is_optional() -> None:
    with pytest.raises(SystemExit):
        script.parse_args(["--tenant", str(uuid7()), "--ref", "r"])
    with pytest.raises(SystemExit):
        script.parse_args(
            ["--tenant", str(uuid7()), "--ref", "r", "--from-csv", "f.csv", "--call", str(uuid7())]
        )
    args = script.parse_args(
        [
            "--tenant",
            str(uuid7()),
            "--ref",
            "r",
            "--call",
            str(uuid7()),
            "--chars",
            "10",
            "--actual-tier",
            "value",
        ]
    )
    assert args.apply is False, "writing is never the default"
