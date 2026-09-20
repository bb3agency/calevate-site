"""The client's recorded exception to the ordinary-DID refusal.

TRAI direction RG-25/(18)/2023-QoS (E-10291), 18 Jun 2024 forbids a sender from making
promotional, service or transactional voice calls from any other 10-digit number, and names
the delegation chain — "channel partners, DSAs, BPO partner, in-house or outsourced Call
Centre" — so the obligation cannot be handed to a vendor. Under Model B the client is the
sender, so the refusal is the default and the exception is theirs to record.

What this file pins is that the exception is NARROW: it never reaches promotional, it never
survives a wording change, it is per number, and nobody but the client can make it.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns.sender_attestation import (
    ATTESTABLE_CLASSIFICATIONS,
    SENDER_STATEMENT,
    SENDER_STATEMENT_VERSION,
    AttestationState,
    latest_attestation,
    record_attestation,
)
from apps.api.campaigns.service import SERIES_FOR_CLASSIFICATION
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = pytest.mark.rls


async def _tenant_with_number(series: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An organisation, one phone number of `series`, and a user who can attest."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Sender Properties",
        slug=f"sender-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    number_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                "dlt_status, created_at, updated_at) VALUES (:id, :tid, :aid, :e, :s, "
                "'registered', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": f"+91{uuid.uuid4().int % 10**10:010d}",
                "s": series,
            },
        )
    # `users` is GLOBAL and joins a tenant through `memberships`, so an owner is made
    # rather than looked up — a fresh organisation has no member until somebody accepts an
    # invitation, and `attested_by` is NOT NULL.
    user_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": user_id, "e": f"owner-{uuid.uuid4().hex[:8]}@example.test"},
        )
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, "
                "updated_at) VALUES (:id, :t, :u, 'owner', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "u": user_id},
        )
    return tenant_id, number_id, user_id


async def test_a_number_with_no_row_is_not_attested() -> None:
    """Absence is a refusal, not an unknown. The gate has to answer for a number nobody
    has ever looked at."""
    tenant_id, number_id, _ = await _tenant_with_number("standard")
    async with tenant_session(tenant_id) as session:
        state = await latest_attestation(session, phone_number_id=number_id)
    assert state == AttestationState(attested=False, statement_version=None)
    assert not state.current


async def test_an_attestation_then_a_withdrawal_leaves_the_number_refused() -> None:
    """Both rows survive (hard rule 4) and the LATEST one decides."""
    tenant_id, number_id, user_id = await _tenant_with_number("standard")
    async with tenant_session(tenant_id) as session:
        await record_attestation(
            session,
            tenant_id=tenant_id,
            phone_number_id=number_id,
            user_id=user_id,
            statement_version=SENDER_STATEMENT_VERSION,
        )
        assert (await latest_attestation(session, phone_number_id=number_id)).current

        await record_attestation(
            session,
            tenant_id=tenant_id,
            phone_number_id=number_id,
            user_id=user_id,
            statement_version=SENDER_STATEMENT_VERSION,
            withdraw=True,
        )
        assert not (await latest_attestation(session, phone_number_id=number_id)).current

        kept = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbound_sender_attestations WHERE phone_number_id = :n"
                ),
                {"n": number_id},
            )
        ).scalar_one()
    assert kept == 2, "a withdrawal must append, never replace"


async def test_the_ledger_refuses_an_update_and_a_delete() -> None:
    """Hard rule 4 at the DATABASE, not in this module. A fix is a compensating row."""
    tenant_id, number_id, user_id = await _tenant_with_number("standard")
    async with tenant_session(tenant_id) as session:
        await record_attestation(
            session,
            tenant_id=tenant_id,
            phone_number_id=number_id,
            user_id=user_id,
            statement_version=SENDER_STATEMENT_VERSION,
        )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(Exception, match=r"(?i)append.only|immutable|not allowed"):
            await session.execute(
                text(
                    "UPDATE outbound_sender_attestations SET state = 'withdrawn' "
                    "WHERE phone_number_id = :n"
                ),
                {"n": number_id},
            )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(Exception, match=r"(?i)append.only|immutable|not allowed"):
            await session.execute(
                text("DELETE FROM outbound_sender_attestations WHERE phone_number_id = :n"),
                {"n": number_id},
            )


async def test_another_tenant_sees_zero_rows() -> None:
    """Hard rule 1's cross-tenant clause, over the new table."""
    owner, number_id, user_id = await _tenant_with_number("standard")
    async with tenant_session(owner) as session:
        await record_attestation(
            session,
            tenant_id=owner,
            phone_number_id=number_id,
            user_id=user_id,
            statement_version=SENDER_STATEMENT_VERSION,
        )
    stranger, _, _ = await _tenant_with_number("standard")
    async with tenant_session(stranger) as session:
        visible = (
            await session.execute(text("SELECT count(*) FROM outbound_sender_attestations"))
        ).scalar_one()
        # The neighbour's own number must also read as unattested, not as someone else's yes.
        assert not (await latest_attestation(session, phone_number_id=number_id)).current
    assert visible == 0


async def test_a_stale_statement_version_is_refused_on_the_way_in() -> None:
    """The wording someone ticked is half the evidence, so a console left open across a
    change must reload rather than have today's version recorded against yesterday's click."""
    tenant_id, number_id, user_id = await _tenant_with_number("standard")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await record_attestation(
                session,
                tenant_id=tenant_id,
                phone_number_id=number_id,
                user_id=user_id,
                statement_version="1999-01-01",
            )
    assert raised.value.code == "sender_statement_not_current"


async def test_a_withdrawal_is_accepted_from_a_stale_page() -> None:
    """Refusing this would hold someone to an obligation they are trying to leave."""
    tenant_id, number_id, user_id = await _tenant_with_number("standard")
    async with tenant_session(tenant_id) as session:
        await record_attestation(
            session,
            tenant_id=tenant_id,
            phone_number_id=number_id,
            user_id=user_id,
            statement_version="1999-01-01",
            withdraw=True,
        )
        assert not (await latest_attestation(session, phone_number_id=number_id)).current


def test_a_stale_attestation_does_not_satisfy_the_gate() -> None:
    """Pure state logic, so it is readable without a database."""
    assert AttestationState(attested=True, statement_version=SENDER_STATEMENT_VERSION).current
    assert not AttestationState(attested=True, statement_version="1999-01-01").current
    assert not AttestationState(attested=False, statement_version=SENDER_STATEMENT_VERSION).current


def test_promotional_can_never_be_attested_open() -> None:
    """140 is the only series that may carry a promotional call, and no client declaration
    changes that. This is the one widening the feature must never allow."""
    assert "promotional" not in ATTESTABLE_CLASSIFICATIONS
    assert frozenset({"service", "transactional"}) == ATTESTABLE_CLASSIFICATIONS
    assert SERIES_FOR_CLASSIFICATION["promotional"] == ("140",)


def test_the_statement_says_what_is_being_accepted() -> None:
    """A confirmation that does not name the obligation is not evidence of accepting it."""
    lowered = SENDER_STATEMENT.lower()
    assert "sender" in lowered
    assert "140" in SENDER_STATEMENT and "160" in SENDER_STATEMENT
    assert "responsibility" in lowered
