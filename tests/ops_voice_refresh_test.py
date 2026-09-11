"""`POST /v1/ops/voices/refresh` — the operator's own trigger for the catalogue sync (D-585).

WHY THIS ROUTE NEEDS A TEST OF ITS OWN, rather than resting on
`voice_catalogue_sync_test`'s coverage of the functions it calls.

Three of its claims are properties of the ROUTE and would survive every unit test passing:

1. **`ops:manage`, admin realm.** The catalogue decides what every client's voice picker
   offers, platform-wide. A client principal reaching it would be one tenant editing a list
   the other tenants read.
2. **It is audited.** The cache carries no history — it is refreshed whole — so the audit
   row is the only place "the catalogue changed at 14:02 because someone pressed refresh"
   exists. A route that synced without writing one would look identical from the outside.
3. **No step-up, deliberately**, and that asymmetry with `outbox/replay` is worth pinning:
   if someone later adds `X-Confirm-Action` here out of symmetry, operators get trained to
   type confirmations on a read-and-cache, which is what makes them worthless on the route
   where the blast radius is real.

`sync_voice_catalogue` itself is exercised in `voice_catalogue_sync_test`; this file does
not re-prove upsert or prune, only that the route is wired, guarded and recorded.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.models import PlatformVoiceCatalogEntry
from apps.api.agents.voices import install_voice_catalogue
from apps.api.db.session import untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, text

ROUTE = "/v1/ops/voices/refresh"


@pytest.fixture(autouse=True)
def _restore_seed() -> Any:
    """The route installs into a process-wide snapshot; put it back so this module cannot
    decide what the rest of the run's voice picker offers."""
    yield
    install_voice_catalogue(None)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> tuple[str, UUID]:
    """A real admin row plus the dev-token realm credential (`ops_outbox_replay_test`'s
    idiom — one way per problem)."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}", admin_id


async def _refresh(token: str | None) -> Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with _client() as http:
        return await http.post(ROUTE, headers=headers)


async def test_an_unauthenticated_caller_cannot_refresh_the_catalogue() -> None:
    """The list every tenant's picker is built from is not anonymous to rebuild."""
    assert (await _refresh(None)).status_code in {401, 403}


async def test_a_client_principal_cannot_refresh_the_catalogue() -> None:
    """`ops:manage` is an ADMIN permission and this is a PLATFORM-wide cache. A client
    holding it would be one tenant rewriting a list every other tenant reads."""
    response = await _refresh(f"dev:client:{uuid.uuid4()}")

    assert response.status_code in {401, 403}, (
        "a client principal reached a platform-wide cache rebuild"
    )


async def test_an_operator_refresh_syncs_and_leaves_an_audit_row() -> None:
    """The route's own three facts: it runs, it answers with the counts, and it RECORDS
    who ran it.

    The engine here is whatever `get_engine()` resolves to under test — the fake, which
    lists a catalogue by design. What is asserted is therefore the ROUTE's behaviour
    (200, a coherent body, an audit row naming this actor), never the fake's voice list,
    which `engine_conformance` owns.
    """
    token, admin_id = await _make_admin()
    async with untenanted_session() as session:
        await session.execute(delete(PlatformVoiceCatalogEntry))
        await session.commit()

    try:
        response = await _refresh(token)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["in_force"] > 0, (
            "the refresh reported no voices in force; the picker would fall back to the "
            "seed with nothing saying why"
        )
        assert body["written"] == body["in_force"]
        assert body["note"], "an operator pressing this gets no sentence back"

        async with untenanted_session() as session:
            actors = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE action = "
                        "'ops.voice_catalogue_refresh' AND actor_id = :actor"
                    ),
                    {"actor": admin_id},
                )
            ).scalar_one()
        assert actors == 1, (
            "no audit row names this operator; the cache keeps no history of its own, so "
            "this row is the only record the catalogue was rebuilt and by whom"
        )
    finally:
        async with untenanted_session() as session:
            await session.execute(delete(PlatformVoiceCatalogEntry))
            await session.commit()
