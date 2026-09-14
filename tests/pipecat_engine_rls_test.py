"""Cross-tenant zero rows on the two `pipecat` tables (hard rule 1, migration `e2f5a91c8d47`).

WHAT LEAKS IF THEY DO NOT, stated because the column names do not say it.
`pipecat_agents.resolved_config` is a whole `AgentConfig` — one business's SCRIPT, its
opening line and the model stack it runs on — so a neighbour who can read it does not learn
a digest, they learn the script itself. `pipecat_kb_objects` carries the handle that
addresses one client's knowledge object and the id of the source it came from.

THE WRITE DIRECTION MATTERS MORE THAN THE READ, and on both tables. A neighbour able to
UPDATE `pipecat_agents` could repoint another client's agent at a config version of their
choosing; one able to DELETE from `pipecat_kb_objects` could make another client's document
vanish from the account listing, which is the one instrument that can find a stranded
document at all.

`pipecat_kb_objects` CARRIES A DELIBERATE GLOBAL-READ EXEMPTION and this file is where that
is held to its stated shape: the exemption is for SELECT only, and for the UNTENANTED
session only, on `engine_kb_routes`' pattern, because `list_account_kb`'s question ("which
objects does no tenant of ours claim?") cannot be asked from a tenant session. So the
clauses below assert the exemption's NARROWNESS in both of its dimensions — an untenanted
session may read and may not write, and a NEIGHBOUR may do neither — rather than treating
it as a table without tenancy. The second dimension is new: the policy was
`FOR SELECT USING (true)`, which is OR'd into every session's SELECT, so a tenant session
could read a neighbour's handle; migration `d7c2f4a91b83` narrowed it to `<guc> IS NULL`.
`pipecat_agents` has no exemption and is plain FORCEd isolation.

SHARED DATABASE DISCIPLINE: two organisations minted here, every assertion scoped to their
own ids, nothing counted globally.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.pipecat import PipecatEngine
from calevate_shared.engine import AgentConfig, KBSourceRef, ModelConfig
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = [pytest.mark.rls]


async def _org(label: str) -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name=f"Pipecat RLS {label}",
        slug=f"pipecat-rls-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id, uuid.UUID(str(created["agent_id"]))


async def _plant(label: str, marker: str) -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """A real agent record and a real knowledge object, so "zero rows" below is a REFUSAL
    rather than an empty table."""
    tenant_id, agent_id = await _org(label)
    engine = PipecatEngine()
    cfg = AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        name=f"Receptionist {marker}",
        direction="inbound",
        language_primary="te-IN",
        system_prompt=f"Receptionist. {marker}",
        opening_line="Idi AI assistant. Ee call record avutundi.",
        models=ModelConfig(tts_provider="sarvam", tts_model="bulbul:v3", tts_voice="anushka"),
    )
    ref = await engine.create_agent(cfg)
    handle = await engine.attach_kb(
        ref, KBSourceRef(kb_id=str(uuid.uuid4()), title="Fees", text="A consultation costs 500.")
    )
    return tenant_id, agent_id, ref, handle


async def test_one_tenant_sees_none_of_anothers_engine_rows() -> None:
    """The whole of hard rule 1 on both tables, in the direction that leaks a script."""
    _, _, mine_ref, mine_handle = await _plant("A", "marker-a")
    theirs_tenant, _, theirs_ref, theirs_handle = await _plant("B", "marker-b")

    async with tenant_session(theirs_tenant) as session:
        agents = (
            await session.execute(
                text(
                    "SELECT count(*) FROM pipecat_agents WHERE engine_agent_ref IN (:mine, :theirs)"
                ),
                {"mine": mine_ref, "theirs": theirs_ref},
            )
        ).scalar_one()
        assert agents == 1, "a tenant session saw another tenant's engine agent record"
        # THE KB OBJECT IS COUNTED THE SAME WAY NOW, and this line used to say it could
        # not be. Its read exemption was `FOR SELECT USING (true)`, which is OR'd into
        # EVERY session's SELECT and therefore let a neighbour read the handle too;
        # migration `d7c2f4a91b83` narrowed it to `<guc> IS NULL`, so the exemption still
        # answers `list_account_kb`'s untenanted question and answers nobody else's.
        objects = (
            await session.execute(
                text("SELECT count(*) FROM pipecat_kb_objects WHERE handle IN (:mine, :theirs)"),
                {"mine": mine_handle, "theirs": theirs_handle},
            )
        ).scalar_one()
        assert objects == 1, "a tenant session saw another tenant's knowledge object handle"

        script = (
            await session.execute(
                text(
                    "SELECT resolved_config->>'system_prompt' FROM pipecat_agents "
                    "WHERE engine_agent_ref = :ref"
                ),
                {"ref": mine_ref},
            )
        ).scalar()
    assert script is None, "one client's script was readable from another client's session"
    assert mine_handle != theirs_handle


async def test_an_untenanted_session_sees_no_agent_record_and_every_kb_object() -> None:
    """THE EXEMPTION'S EXACT SHAPE, both halves in one clause.

    `pipecat_agents` has no exemption, so an untenanted session sees nothing — which is
    what keeps a whole `AgentConfig` out of every global sweep. `pipecat_kb_objects` has
    one, and it is needed: `list_account_kb` asks a question no tenant session can, and an
    account listing that answered EMPTY under RLS would be a positive claim that the
    account holds nothing stranded.
    """
    _, _, ref, handle = await _plant("C", "marker-c")

    async with untenanted_session() as session:
        agents = (
            await session.execute(
                text("SELECT count(*) FROM pipecat_agents WHERE engine_agent_ref = :ref"),
                {"ref": ref},
            )
        ).scalar_one()
        objects = (
            await session.execute(
                text("SELECT count(*) FROM pipecat_kb_objects WHERE handle = :handle"),
                {"handle": handle},
            )
        ).scalar_one()
    assert agents == 0, "an untenanted session read a client's published agent configuration"
    assert objects == 1, (
        "the account-level object is invisible without a tenant, so `list_account_kb` "
        "would report a clean account while a client's document sits unclaimed"
    )


async def test_the_global_read_exemption_does_not_carry_a_write() -> None:
    """`engine_kb_routes`' lesson, applied before it can be repeated (migration
    `b8e2d47f0c19` had to remove an `OR <guc> IS NULL` that let any untenanted session
    delete or re-tenant any claim). The policy here is `tenant_id = <guc>` and nothing
    else, so a session with no tenant matches no row to write."""
    _, _, _, handle = await _plant("D", "marker-d")

    async with untenanted_session() as session:
        deleted = await session.execute(
            text("DELETE FROM pipecat_kb_objects WHERE handle = :handle"), {"handle": handle}
        )
        assert deleted.rowcount == 0, (
            "an untenanted session deleted a client's knowledge object — the exemption is "
            "for READS and the write policy has widened"
        )

    async with untenanted_session() as session:
        still_there = (
            await session.execute(
                text("SELECT count(*) FROM pipecat_kb_objects WHERE handle = :handle"),
                {"handle": handle},
            )
        ).scalar_one()
    assert still_there == 1


async def test_a_neighbour_cannot_repoint_or_delete_another_tenants_engine_rows() -> None:
    """The write half on both tables, from a session that HAS a tenant — the case a
    global-read exemption makes easy to get wrong, because the read succeeds."""
    _, _, victim_ref, victim_handle = await _plant("E", "marker-e")
    attacker_tenant, _, _, _ = await _plant("F", "marker-f")

    async with tenant_session(attacker_tenant) as session:
        repointed = await session.execute(
            text("UPDATE pipecat_agents SET name = 'seized' WHERE engine_agent_ref = :ref"),
            {"ref": victim_ref},
        )
        dropped = await session.execute(
            text("DELETE FROM pipecat_kb_objects WHERE handle = :handle"),
            {"handle": victim_handle},
        )
    assert repointed.rowcount == 0, "a neighbour rewrote another client's engine agent record"
    assert dropped.rowcount == 0, "a neighbour deleted another client's knowledge object"
