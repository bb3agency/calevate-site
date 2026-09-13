"""Cross-tenant zero rows on the two config-version tables (hard rule 1, `d4e1c7a09b35`).

Both carry `tenant_id` and the FORCEd `tenant_isolation` policy. What leaks if they do not
is not obvious from the column names, so it is worth stating: `prompt_sha256` is the digest
of one business's composed script and `model_config_sha256` of the model stack it runs on —
a competitor who can read another tenant's rows learns when their script changed, how often,
and can confirm a guessed script by composing it and comparing digests. The attestation
table adds when that business's agents were actually running.

The WRITE direction matters more than usual here. These rows are the witness `get_agent`
answers from on an `owned_runtime` engine, so a neighbour able to insert an attestation
against somebody else's agent could manufacture agreement — turning the one control that
detects a drifted worker into a control that reports whatever an attacker wants. The
append-only clauses are in `tests/agent_config_versions_test.py`; this file is isolation.

SHARED DATABASE DISCIPLINE: two organisations minted by this module, every assertion scoped
to their own ids, and nothing counts rows globally.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = [pytest.mark.rls]

_TABLES = ("agent_config_versions", "agent_config_attestations")


async def _org() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Config RLS",
        slug=f"config-rls-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id, uuid.UUID(str(created["agent_id"]))


async def _plant(tenant_id: uuid.UUID, agent_id: uuid.UUID, marker: bytes) -> uuid.UUID:
    """A real version and a real attestation, so "zero rows" below is a refusal rather than
    an empty table."""
    version_id = uuid7()
    digest = hashlib.sha256(marker).hexdigest()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_config_versions "
                "(id, tenant_id, agent_id, prompt_sha256, model_config_sha256) "
                "VALUES (:id, :tid, :aid, :prompt, :model)"
            ),
            {
                "id": version_id,
                "tid": tenant_id,
                "aid": agent_id,
                "prompt": digest,
                "model": hashlib.sha256(marker + b":models").hexdigest(),
            },
        )
        await session.execute(
            text(
                "INSERT INTO agent_config_attestations "
                "(id, tenant_id, agent_id, agent_config_version_id, prompt_sha256, observed_at) "
                "VALUES (:id, :tid, :aid, :vid, :prompt, now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "vid": version_id,
                "prompt": digest,
            },
        )
    return version_id


async def test_one_tenant_sees_none_of_anothers_config_rows() -> None:
    """The clause hard rule 1 asks for, on both tables, in both directions."""
    first_tenant, first_agent = await _org()
    second_tenant, second_agent = await _org()
    await _plant(first_tenant, first_agent, b"first")
    await _plant(second_tenant, second_agent, b"second")

    for tenant_id, own_agent, other_agent in (
        (first_tenant, first_agent, second_agent),
        (second_tenant, second_agent, first_agent),
    ):
        async with tenant_session(tenant_id) as session:
            for table in _TABLES:
                own = (
                    await session.execute(
                        text(f"SELECT count(*) FROM {table} WHERE agent_id = :aid"),
                        {"aid": own_agent},
                    )
                ).scalar()
                assert own == 1, f"{table}: a tenant cannot see its own row"
                theirs = (
                    await session.execute(
                        text(f"SELECT count(*) FROM {table} WHERE agent_id = :aid"),
                        {"aid": other_agent},
                    )
                ).scalar()
                assert theirs == 0, (
                    f"{table}: this tenant can read another business's agent configuration "
                    "history — when their script changed, and how often"
                )


async def test_an_untenanted_session_sees_neither_tables_rows() -> None:
    """The fail-closed property: no GUC, no rows. A sweep or an ops query that forgets to
    enter a tenant reads nothing rather than reading everyone. Neither table has an
    untenanted reader to widen for — the worker attests inside its own tenant's session."""
    tenant_id, agent_id = await _org()
    await _plant(tenant_id, agent_id, b"untenanted")

    async with untenanted_session() as session:
        for table in _TABLES:
            rows = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE agent_id = :aid"),
                    {"aid": agent_id},
                )
            ).scalar()
            assert rows == 0, f"{table}: an untenanted session read a tenant's rows"


async def test_a_neighbour_cannot_manufacture_an_attestation() -> None:
    """THE WRITE HALF, and on this table it is the one that matters.

    `get_agent` on an `owned_runtime` engine answers from the newest attestation. A
    neighbour able to insert one against somebody else's agent could manufacture agreement
    — making the control that detects a drifted worker report whatever they chose. The
    policy has no `WITH CHECK`, so the INSERT is judged by the USING clause and a row whose
    `tenant_id` is not this session's is refused outright.
    """
    victim_tenant, victim_agent = await _org()
    attacker_tenant, attacker_agent = await _org()
    victim_version = await _plant(victim_tenant, victim_agent, b"victim")
    await _plant(attacker_tenant, attacker_agent, b"attacker")

    async with tenant_session(attacker_tenant) as session:
        with pytest.raises(Exception) as raised:
            await session.execute(
                text(
                    "INSERT INTO agent_config_attestations "
                    "(id, tenant_id, agent_id, agent_config_version_id, prompt_sha256, "
                    " observed_at) "
                    "VALUES (:id, :tid, :aid, :vid, :prompt, now())"
                ),
                {
                    "id": uuid7(),
                    "tid": victim_tenant,
                    "aid": victim_agent,
                    "vid": victim_version,
                    "prompt": hashlib.sha256(b"whatever they chose").hexdigest(),
                },
            )
        assert "row-level security" in str(raised.value).lower()

    async with tenant_session(victim_tenant) as session:
        held = (
            await session.execute(
                text("SELECT count(*) FROM agent_config_attestations WHERE agent_id = :aid"),
                {"aid": victim_agent},
            )
        ).scalar()
    assert held == 1, "a neighbour planted an attestation on another business's agent"
