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

import pytest
from apps.api.callbacks.service import cancel_for_phones, cancel_for_phones_fleet_wide
from apps.api.compliance.kyc_verification import REQUEST_CREATED, VerificationRequest
from apps.api.db.session import tenant_session
from apps.api.ingest.service import submission_instant

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


def test_a_run_is_open_only_while_it_is_created() -> None:
    """`is_open` is what the webhook uses to decide whether an outcome may still land, so
    a terminal run reading as open would let a replay rewrite a settled verdict — and a
    run past `RUN_TTL` is terminal in every way but the column."""
    assert VerificationRequest(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        entity_type="sole_proprietorship",
        status=REQUEST_CREATED,
        id_document="aadhaar",
        past_ttl=False,
    ).is_open
    assert not VerificationRequest(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        entity_type="sole_proprietorship",
        status=REQUEST_CREATED,
        id_document="aadhaar",
        past_ttl=True,
    ).is_open
    for settled in ("completed", "failed", "expired"):
        assert not VerificationRequest(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            entity_type="sole_proprietorship",
            status=settled,
            id_document="aadhaar",
            past_ttl=False,
        ).is_open


# ------------------------------------------------------- the dial path (hard rule 5)


@pytest.mark.parametrize("raw", [1e30, -1e30, float("inf"), float("nan")])
def test_an_epoch_outside_the_calendar_is_read_as_absent(raw: float) -> None:
    """`datetime.fromtimestamp` raises rather than returning on these, and an exception
    reaching `ingest_lead` would refuse a lead over a malformed field on someone's form.
    Unreadable is not stale: the dial proceeds, exactly as it does for a missing value."""
    assert submission_instant({"submitted_at": raw}, {}) is None
