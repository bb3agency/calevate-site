"""One voice quality, one TTS rate, metered onto one overage rung.

The single-tier voice decision (superseding D-36/D-35/D-34) withdrew the Bulbul v2 "value"
voice rung: there is one voice quality now (Sarvam Bulbul v3), one TTS rate (₹30/10k chars),
and one client rate. The old two-rung honesty machinery — `billable_tier`, `TtsTier`,
`tts_tier_source`, `record_tier_correction` — is gone, because with one voice a call can
never run on the wrong rung and can never be billed the "wrong" rate.

What survives and is pinned here:

* the engine still reports NOTHING about which voice ran (`ENGINE_REPORTS_TTS_MODEL` is a
  true capability fact, not a billing lever any more);
* the TTS rate is one scalar and metering stamps every call onto the plan's BASE overage
  rung, so `tier_usage` and the usage panel still agree to the paisa.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import rates
from apps.api.billing import service as billing
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from calevate_shared.engine import CostBreakdown, ExecutionSnapshot
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

# --- the finding ---------------------------------------------------------------


def test_the_engine_tells_us_nothing_about_which_voice_ran() -> None:
    """`ENGINE_REPORTS_TTS_MODEL` is still a true statement about the engine.

    It no longer guards a bill — there is one voice quality, so a synthesizer we could not
    identify would price identically anyway — but if this ever fails the vendor started
    reporting the synthesizer model and the constant should be revisited (D-358)."""
    snapshot_fields = set(ExecutionSnapshot.model_fields)
    cost_fields = set(CostBreakdown.model_fields)
    suspects = {"tts_model", "tts_voice", "synthesizer_model", "voice", "tts_chars", "chars"}
    assert not suspects & (snapshot_fields | cost_fields), (
        "the engine now reports the voice or a character count — revisit "
        "rates.ENGINE_REPORTS_TTS_MODEL"
    )
    assert rates.ENGINE_REPORTS_TTS_MODEL is False


# --- the single rate card (TRD §10.1) ------------------------------------------


def test_the_rate_card_is_one_numeric_scalar() -> None:
    """One voice quality, one rate — a scalar, not a per-tier mapping."""
    assert Decimal("30.0000") == rates.TTS_INR_PER_10K_CHARS
    assert isinstance(rates.TTS_INR_PER_10K_CHARS, Decimal)
    assert not isinstance(rates.TTS_INR_PER_10K_CHARS, float)


def test_tts_cost_takes_only_a_character_count() -> None:
    assert rates.tts_cost_inr(10_000) == Decimal("30.0000")
    assert rates.tts_cost_inr(5_000) == Decimal("15.0000")
    assert isinstance(rates.tts_cost_inr(10_000), Decimal)
    # The old `TtsTier` argument is gone; there is nothing to select.
    with pytest.raises(TypeError):
        rates.tts_cost_inr("premium", 10_000)  # type: ignore[call-arg]


def test_a_negative_character_count_is_refused_rather_than_priced() -> None:
    """A negative count would price to a NEGATIVE cost, and a negative cost recorded as a
    usage event is a credit issued by an arithmetic accident. Zero is NOT an error — a call
    that synthesized nothing costs nothing."""
    with pytest.raises(ValueError, match="negative"):
        rates.tts_cost_inr(-1)
    with pytest.raises(ValueError):
        rates.tts_cost_inr(-10_000)
    assert rates.tts_cost_inr(0) == Decimal("0.0000")


# --- metering stamps the base rung ---------------------------------------------


def _snapshot(*, duration_s: int = 120, tts_inr: str = "2.0000") -> ExecutionSnapshot:
    return ExecutionSnapshot(
        engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        duration_s=duration_s,
        cost=CostBreakdown(
            total_inr=Decimal("6.0000"),
            platform_inr=Decimal("3.0000"),
            network_inr=Decimal("0.8000"),
            llm_inr=Decimal("0.0000"),
            tts_inr=Decimal(tts_inr),
            stt_inr=Decimal("1.0000"),
            source_currency="INR",
            source_amount=Decimal("6.0000"),
            fx_rate=Decimal("1"),
        ),
        engine="fake",
    )


async def _tenant_with_call(label: str, *, voice: str | None) -> tuple[UUID, UUID]:
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{label}_{uuid.uuid4().hex[:8]}")
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        if voice is not None:
            await session.execute(
                text("UPDATE agents SET tts_voice = :v, tts_provider = 'sarvam' WHERE id = :a"),
                {"v": voice, "a": agent_id},
            )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    return tenant_id, call_id


async def _usage_rows(tenant_id: UUID, call_id: UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, meta FROM usage_events "
                    "WHERE tenant_id = :t AND call_id = :c ORDER BY unit_type"
                ),
                {"t": tenant_id, "c": call_id},
            )
        ).all()
    return [
        {"unit_type": r[0], "qty": r[1], "unit_cost_paid": r[2], "meta": r[3] or {}} for r in rows
    ]


async def test_every_usage_row_records_the_base_rung_and_the_voice() -> None:
    tenant_id, call_id = await _tenant_with_call("v3", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot())
    rows = await _usage_rows(tenant_id, call_id)
    assert rows, "the call metered something"
    for row in rows:
        # One voice quality → the plan's base overage rung on every call.
        assert row["meta"]["tts_tier"] == billing.BASE_OVERAGE_RUNG
        assert row["meta"]["tts_voice"] == "bulbul:v3"
        # `tts_tier_source` is gone: there is no honesty rule left to record.
        assert "tts_tier_source" not in row["meta"]


async def test_a_call_with_no_configured_voice_still_meters_on_the_base_rung() -> None:
    """An agent row that was never given a voice still bills at the one rate — the rung is
    a constant now, not a function of the (absent) voice."""
    tenant_id, call_id = await _tenant_with_call("novoice", voice=None)
    await _meter(tenant_id, call_id, _snapshot())
    rows = await _usage_rows(tenant_id, call_id)
    assert {row["meta"]["tts_tier"] for row in rows} == {billing.BASE_OVERAGE_RUNG}
    assert all(row["meta"]["tts_voice"] is None for row in rows)


async def test_tier_metering_does_not_change_what_the_call_cost() -> None:
    """The money on the row is the money the engine reported — a rung label is meta."""
    tenant_id, call_id = await _tenant_with_call("nomove", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot())
    async with tenant_session(tenant_id) as session:
        total = (
            await session.execute(
                text(
                    "SELECT SUM(qty * COALESCE(unit_cost_paid, 0)) FROM usage_events "
                    "WHERE tenant_id = :t AND call_id = :c"
                ),
                {"t": tenant_id, "c": call_id},
            )
        ).scalar()
    # 120s telephony + 2 platform-min + 120s stt + one tts leg + one llm leg.
    assert Decimal(str(total)) == Decimal("6.8000")


# --- the split both panels read ------------------------------------------------


async def test_the_split_counts_minutes_and_cost_on_the_base_rung() -> None:
    tenant_id, call_id = await _tenant_with_call("split", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot(duration_s=180))

    async with tenant_session(tenant_id) as session:
        split = await billing.tier_usage(session, tenant_id=tenant_id)

    # All minutes land on the base (premium) rung; the value rung is dormant.
    assert split["minutes_premium"] == Decimal("3.00")
    assert split["minutes_value"] == Decimal("0.00")
    assert split["minutes_unattributed"] == Decimal("0.00")
    assert split["cost_premium_inr"] > Decimal("0")
    assert isinstance(split["cost_premium_inr"], Decimal)

    async with tenant_session(tenant_id) as session:
        margin = await billing.margin_for_tenant(session, tenant_id=tenant_id)
    assert (
        split["cost_premium_inr"] + split["cost_value_inr"] + split["cost_unattributed_inr"]
        == margin["cost_inr"]
    )


async def test_a_row_with_no_rung_is_reported_separately_and_billed_as_the_cheaper_side() -> None:
    """Rows written before rung attribution existed carry no rung. They are NOT relabelled
    (hard rule 4): the split reports them as unattributed and the billable side folds them
    into the cheaper slot, never the dearer one."""
    tenant_id, call_id = await _tenant_with_call("legacy", voice="bulbul:v3")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'telephony_s', "
                "120, 0.0100, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
        split = await billing.tier_usage(session, tenant_id=tenant_id)

    assert split["minutes_unattributed"] == Decimal("2.00")
    assert split["minutes_billable_premium"] == Decimal("0.00")
    assert split["minutes_billable_value"] == Decimal("2.00"), "unattributed bills as the cheaper"


async def test_the_split_totals_agree_with_the_usage_panel() -> None:
    tenant_id, call_id = await _tenant_with_call("agree", voice="bulbul:v3")
    await _meter(tenant_id, call_id, _snapshot(duration_s=150))
    async with tenant_session(tenant_id) as session:
        summary = await billing.usage_summary(session, tenant_id=tenant_id)
        split = await billing.tier_usage(session, tenant_id=tenant_id)
    total = split["minutes_premium"] + split["minutes_value"] + split["minutes_unattributed"]
    assert total == summary["minutes_used"] == Decimal("2.50")


async def test_the_split_never_leaks_across_tenants() -> None:
    a_tenant, a_call = await _tenant_with_call("iso-a", voice="bulbul:v3")
    b_tenant, b_call = await _tenant_with_call("iso-b", voice="bulbul:v3")
    await _meter(a_tenant, a_call, _snapshot(duration_s=60))
    await _meter(b_tenant, b_call, _snapshot(duration_s=120))
    async with tenant_session(a_tenant) as session:
        a_split = await billing.tier_usage(session, tenant_id=a_tenant)
    assert a_split["minutes_premium"] == Decimal("1.00")


# --- the OTHER capability flag, and the register that describes it -------------
#
# `ENGINE_TTS_MODEL_GENERATION_VERIFIED` is a different question from
# `ENGINE_REPORTS_TTS_MODEL` pinned at the top of this file, and the readiness register
# conflated them for months: it recorded the flag as "the margin panel splits cost by rung;
# the mapping from engine model name to rung is not confirmed", which was wrong in both
# halves. There is no engine model name — the snapshot carries no synthesizer field, which
# the first test in this file asserts — and the rung is a constant this repository stamps
# (`BASE_OVERAGE_RUNG`), not a mapping from anything a vendor reports. The register's own
# §P1.7 then prescribed a FIX (`meta->>'tts_tier_source'` in `_tier_totals`' GROUP BY)
# against machinery that had already been deleted, on a money path, where `docs/` wins over
# code by house rule — so the next session to read it would have built a column no writer
# fills. Both were corrected on 10 Sep 2026 and both are pinned here, because a stale
# register is exactly the defect class hard rule 11 names: a repo-internal claim believed
# because it is written down.


def test_the_model_generation_flag_is_false_and_ci_guards_every_sentence_about_it() -> None:
    """The flag is not a comment: it is a DISCOVERED capability constant.

    `scripts/check_docs_drift.py` §5 finds every module-level `NAME = <bool literal>` by
    AST and fails CI when prose states a value the constant does not have — so this flag
    already has a consumer, and the answer to "is it read?" is yes, by the guard rather
    than by a request path. That is the right consumer: no bill and no margin figure
    depends on it (see the module docstring), so a runtime caveat on the margin panel would
    assert an inaccuracy that is not there.

    Flipping it needs a captured execution payload from a funded Bolna account (OPERATIONS
    §2 gate 7, D-358) and cannot be done from this repository.
    """
    from scripts import check_docs_drift as guard

    assert rates.ENGINE_TTS_MODEL_GENERATION_VERIFIED is False

    fact = guard.capability_constants()["ENGINE_TTS_MODEL_GENERATION_VERIFIED"]
    assert fact.module == "apps/api/billing/rates.py"
    assert fact.value is False

    stated = {
        (claim.doc, claim.stated)
        for claim in guard.value_claims()
        if claim.name == "ENGINE_TTS_MODEL_GENERATION_VERIFIED"
    }
    assert stated, (
        "no prose anywhere states this flag's value, so the drift guard is judging nothing "
        "— the readiness register is meant to carry the claim it guards"
    )
    assert all(value is False for _, value in stated), (
        "prose claims this flag is True; only a live capture can flip it (gate 7, D-358)"
    )


def test_the_deleted_two_rung_machinery_has_not_come_back() -> None:
    """`billable_tier` and `tts_tier_source` are gone from every shipped module.

    This is the assertion that catches §P1.7's withdrawn FIX being implemented by a session
    that read the register and not this note. It scans SOURCE rather than importing,
    because the failure it guards against is a new definition or a new stamp appearing
    anywhere in `apps/`, not a particular module's API.
    """
    from pathlib import Path

    apps = Path(__file__).resolve().parents[1] / "apps"
    offenders: list[str] = []
    for module in sorted(apps.rglob("*.py")):
        text_ = module.read_text(encoding="utf-8")
        if "def billable_tier" in text_ or "tts_tier_source" in text_:
            offenders.append(str(module))
    assert not offenders, (
        "the withdrawn two-rung machinery is back in "
        f"{offenders} — with one voice quality a call cannot run on the wrong rung, so a "
        "per-row 'source' key records an honesty rule that no longer exists. If a second "
        "voice-derived rung is genuinely returning, that is a decision-log entry and this "
        "test changes with it (docs/PRODUCTION-READINESS.md §P1.7)"
    )


def test_the_readiness_register_still_carries_both_corrections() -> None:
    """The register is authoritative here (house rule: `docs/` wins), so its correctness on
    a money path is a testable property, not a matter of trust.

    Pinned as two short markers rather than whole paragraphs: prose may be improved, but a
    register that stops warning off the withdrawn FIX, or goes back to claiming a rung is
    mapped from an engine model name, is a regression on the axis that moves money.
    """
    from pathlib import Path

    register = (Path(__file__).resolve().parents[1] / "docs/PRODUCTION-READINESS.md").read_text(
        encoding="utf-8"
    )

    assert "**WITHDRAWN — DO NOT IMPLEMENT (D-466 / D-547)." in register, (
        "§P1.7's prescribed FIX (`tts_tier_source` in `_tier_totals`' GROUP BY) is no "
        "longer marked withdrawn — a reader will implement it against deleted machinery"
    )
    # Whitespace-normalised: this register is hard-wrapped, so the quoted claim spans a
    # line break in §P1.7 and a plain `count` on the raw text finds nothing at all — an
    # assertion that passes because it is looking for a string the file cannot contain.
    stale = "the mapping from engine model name to rung is not confirmed"
    occurrences = " ".join(register.split()).count(stale)
    assert occurrences == 1, (
        f"the corrected claim appears {occurrences} times; it may appear exactly ONCE, "
        "inside §P1.7 where it is QUOTED as the earlier wrong claim. No engine model name "
        "enters this system at all (`ExecutionSnapshot` has no synthesizer field)"
    )
