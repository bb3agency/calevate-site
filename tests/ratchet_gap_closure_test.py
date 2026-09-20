"""The branches the ratchet found uncovered on four hard-rule surfaces.

WHY ONE FILE. Each of these is a REFUSAL or an EARLY RETURN on a hard-rule surface —
tenancy (rule 1), the compliance gate (rule 5), the dial path (rule 5) and the
voice-runtime ack (rule 3). They belong together because they share one property: each
is the arm that runs when something is missing or malformed, which is exactly the arm a
happy-path suite never drives and the arm that matters when it fires in production.

Run: uv run pytest -q tests/ratchet_gap_closure_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from apps.api.callbacks.service import cancel_for_phones, cancel_for_phones_fleet_wide
from apps.api.compliance.autodialer import (
    MAX_NOTICE_REFERENCE_CHARS,
    MAX_OBJECTIVE_CHARS,
    record_autodialer_notice,
)
from apps.api.compliance.kyc_verification import REQUEST_CREATED, VerificationRequest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.ingest.service import submission_instant
from sqlalchemy import text

# --------------------------------------------------------------- tenancy (hard rule 1)


@pytest.mark.asyncio
async def test_cancelling_no_phones_touches_nothing() -> None:
    """The empty-sequence arm, which exists so a caller with nothing to cancel does not
    build an `IN ()` that no database accepts. It must not open a statement at all."""
    async with tenant_session(uuid.uuid4()) as session:
        assert await cancel_for_phones(session, phones=[], reason="none") == 0


@pytest.mark.asyncio
async def test_the_fleet_wide_cancel_refuses_an_empty_walk() -> None:
    """Same arm on the cross-tenant walk, and it matters more here: the walk SETS the
    tenant GUC per step, so an empty one must return before touching it rather than
    leave the caller's session pointed at whichever tenant it reached last."""
    async with tenant_session(uuid.uuid4()) as session:
        assert (
            await cancel_for_phones_fleet_wide(session, phones=[], tenant_ids=[], reason="none")
            == 0
        )
        assert (
            await cancel_for_phones_fleet_wide(
                session, phones=["+919000000001"], tenant_ids=[], reason="none"
            )
            == 0
        )


# ------------------------------------------------- the compliance gate (hard rule 5)


@pytest.mark.asyncio
async def test_a_notice_reference_longer_than_the_column_is_refused() -> None:
    """The reference is the client's own letter number, and it is bounded because it
    reaches a TEXT column and a screen. Refused with its own code, not the objective's:
    the two fields fail for different reasons and a client fixing the wrong one learns
    nothing."""
    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await record_autodialer_notice(
                session,
                tenant_id=tenant_id,
                access_provider="A Provider",
                objective="Reminders",
                notified_on=date(2026, 1, 1),
                notice_reference="x" * (MAX_NOTICE_REFERENCE_CHARS + 1),
                recorded_by=uuid.uuid4(),
            )
    assert refused.value.code == "autodialer_notice_reference_invalid"


@pytest.mark.asyncio
async def test_an_objective_longer_than_the_column_is_refused() -> None:
    """Its own refusal beside the one above, so the pair cannot collapse into one code."""
    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await record_autodialer_notice(
                session,
                tenant_id=tenant_id,
                access_provider="A Provider",
                objective="y" * (MAX_OBJECTIVE_CHARS + 1),
                notified_on=date(2026, 1, 1),
                notice_reference=None,
                recorded_by=uuid.uuid4(),
            )
    assert refused.value.code == "autodialer_notice_objective_invalid"


def test_a_run_is_open_only_while_it_is_created() -> None:
    """`is_open` is what the webhook uses to decide whether an outcome may still land, so
    a terminal run reading as open would let a replay rewrite a settled verdict."""
    assert VerificationRequest(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        entity_type="sole_proprietorship",
        status=REQUEST_CREATED,
    ).is_open
    for settled in ("completed", "failed", "expired"):
        assert not VerificationRequest(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            entity_type="sole_proprietorship",
            status=settled,
        ).is_open


# ------------------------------------------------------- the dial path (hard rule 5)


@pytest.mark.parametrize("raw", [1e30, -1e30, float("inf"), float("nan")])
def test_an_epoch_outside_the_calendar_is_read_as_absent(raw: float) -> None:
    """`datetime.fromtimestamp` raises rather than returning on these, and an exception
    reaching `ingest_lead` would refuse a lead over a malformed field on someone's form.
    Unreadable is not stale: the dial proceeds, exactly as it does for a missing value."""
    assert submission_instant({"submitted_at": raw}, {}) is None


@pytest.mark.asyncio
async def test_an_account_with_a_live_notice_gets_no_autodialler_row() -> None:
    """The other arm of the readiness check, and the one a happy account actually takes.

    Without it the screen would only ever be proved to COMPLAIN; this proves it goes
    quiet when the paperwork is in order, which is what a client sees the day they fix it.
    """
    from apps.api.legal.readiness import readiness_rows

    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:t, 'Notice Co', :slug, 'active', now(), now())"
            ),
            {"t": tenant_id, "slug": f"notice-{uuid.uuid4().hex[:8]}"},
        )
        user_id = uuid.uuid4()
        await session.execute(
            text("INSERT INTO users (id, email, name) VALUES (:u, :e, 'Notice User')"),
            {"u": user_id, "e": f"notice-{uuid.uuid4().hex[:8]}@example.invalid"},
        )
        await record_autodialer_notice(
            session,
            tenant_id=tenant_id,
            access_provider="A Provider",
            objective="Delivery reminders",
            notified_on=(datetime.now(UTC) - timedelta(days=30)).date(),
            notice_reference="REF-1",
            recorded_by=user_id,
        )
        rows = await readiness_rows(
            session,
            tenant_id=tenant_id,
            platform=SimpleNamespace(outbound_halted=False),
        )

    assert not [r for r in rows if r.rule.startswith("autodialer_notice")], (
        "a live, effective notice must leave the screen silent about it"
    )
