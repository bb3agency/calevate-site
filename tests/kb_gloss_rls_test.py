"""Hard rule 1 on the gloss columns: a neighbour's English rendering is unreachable.

WHY THIS FILE EXISTS WHEN NO TABLE WAS CREATED. `kb_documents` already carries its FORCEd
`tenant_isolation` policy and a column is not a separate security object, so the new columns
inherit it — which is an ARGUMENT, and hard rule 1 asks for a cross-tenant zero-rows test
rather than an argument. Migration `c7e2b4f019ad` set the precedent for exactly this shape
when it added `structured_script` to an existing table.

It is also not purely ceremonial here, for a reason particular to this feature: the gloss is
reached through a SECOND read path (`kb.service.live_glosses`) that the original chunk text
is not, and that function re-states `tenant_id` as a predicate on top of RLS. A predicate
that named the wrong column, or a policy that did not reach a column added later, would both
show up here and nowhere else.

Marked `rls` so it runs with `-k rls` alongside the rest of the tenancy suite.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb.gloss import GLOSS_READY
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

pytestmark = pytest.mark.rls

_TELUGU = "సన్‌రైజ్ క్లినిక్ ఆదివారం ఉదయం 9 నుండి మధ్యాహ్నం 12 వరకు తెరిచి ఉంటుంది."


async def _glossed_tenant(gloss: str) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Hours", body=_TELUGU
        )
        await session.execute(
            text(
                "UPDATE kb_documents SET gloss = :g, gloss_model = 'test-model', "
                "gloss_state = :s WHERE source_id = :sid"
            ),
            {"g": gloss, "s": GLOSS_READY, "sid": submitted["id"]},
        )
        await kb_service.approve_source(session, source_id=submitted["id"], approved_by=None)
        await kb_service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(submitted["id"]))
        )
    return uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))


async def test_a_tenant_cannot_read_a_neighbours_gloss() -> None:
    """The zero-rows direction. B's session, selecting glosses with no tenant predicate at
    all, sees none of A's — RLS is the control and this is what proves it reaches a column
    added after the policy was written."""
    tenant_a, _ = await _glossed_tenant("Open Sunday 9 am to 12 noon.")
    tenant_b, _ = await _glossed_tenant("Open Monday 8 am to 8 pm.")

    async with tenant_session(tenant_b) as session:
        rows = (
            await session.execute(text("SELECT gloss FROM kb_documents WHERE gloss IS NOT NULL"))
        ).all()
    glosses = {str(r[0]) for r in rows}
    assert glosses == {"Open Monday 8 am to 8 pm."}
    assert not any("Sunday" in g for g in glosses)
    assert tenant_a != tenant_b


async def test_naming_a_neighbours_tenant_id_on_your_own_session_returns_nothing() -> None:
    """The predicate direction — the one mistake RLS cannot see as a mistake.

    `live_glosses` re-states `s.tenant_id = :tid` on top of RLS precisely so that a caller
    passing tenant A's id on a session opened for tenant B gets NOTHING rather than B's
    rows under A's name. Without the predicate this returns B's gloss and looks like a
    successful answer about A.
    """
    tenant_a, _ = await _glossed_tenant("Open Sunday 9 am to 12 noon.")
    tenant_b, _ = await _glossed_tenant("Open Monday 8 am to 8 pm.")

    async with tenant_session(tenant_b) as session:
        assert await kb_service.live_glosses(session, tenant_id=tenant_a) == []
        own = await kb_service.live_glosses(session, tenant_id=tenant_b)
    assert [gloss for _agent, _name, gloss in own] == ["Open Monday 8 am to 8 pm."]


async def test_a_neighbours_gloss_cannot_be_written_either() -> None:
    """An UPDATE from the wrong session touches zero rows rather than silently rewriting
    what another business's agent can be found by."""
    tenant_a, _ = await _glossed_tenant("Open Sunday 9 am to 12 noon.")
    tenant_b, _ = await _glossed_tenant("Open Monday 8 am to 8 pm.")

    async with tenant_session(tenant_b) as session:
        result = await session.execute(
            text("UPDATE kb_documents SET gloss = 'tampered' WHERE tenant_id = :tid"),
            {"tid": tenant_a},
        )
        assert result.rowcount == 0

    async with tenant_session(tenant_a) as session:
        rows = (
            await session.execute(text("SELECT gloss FROM kb_documents WHERE gloss IS NOT NULL"))
        ).all()
    assert {str(r[0]) for r in rows} == {"Open Sunday 9 am to 12 noon."}
