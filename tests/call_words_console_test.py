"""Ops > Call words, end to end against the database (G-C2).

1. Only `ops:manage` reads it; a save takes the step-up string bound to the entry.
2. Every entry of `call_words.json` is listed, with what the founder is asked to write.
3. A save is refused in plain words when a pattern does not compile, does not keep the
   shipped shape, matches every call, breaks the check it is joined into, or cannot be read
   by PostgreSQL where the database searches with it.
4. A save is audited, versioned, and reaches a running check after a refresh with no
   restart; putting the shipped entry back undoes it.

The table is append-only, so `_clean` removes this suite's rows as the OWNER.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.db.session import untenanted_session
from apps.api.insights import detection
from apps.api.main import app
from apps.api.ops import call_words_store
from apps.api.ops.call_words_routes import change_confirmation
from calevate_shared import call_words
from calevate_shared.config import Settings
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.model_pricing_test import _purge_table

STALLS = "detection.stalls"
HOURS = "teach_questions._HOURS_PATTERN"
BASE = "/v1/ops/call-words"
#: A word no transcript holds, so a match can only come from this suite's edit.
MARKER = "zzqcalevatestall"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _auth(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


async def _make_admin(role: str = "superadmin") -> tuple[str, uuid.UUID]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Words', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}", admin_id


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    call_words_store.reset_for_test()
    yield
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: the table is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            await _purge_table(conn, "call_word_revisions", "entry_key", [STALLS, HOURS])
    finally:
        await engine.dispose()
    call_words_store.reset_for_test()


async def _put(http: AsyncClient, token: str, key: str, body: dict[str, object]) -> Response:
    return await http.put(
        f"{BASE}/{key}", headers=_auth(token, change_confirmation(key)), json=body
    )


async def test_only_ops_manage_may_read_it_and_every_entry_is_listed() -> None:
    operator, _ = await _make_admin("operator")
    async with _client() as http:
        refused = await http.get(BASE, headers=_auth(operator))
    assert refused.status_code == 403

    token, _ = await _make_admin()
    async with _client() as http:
        listed = await http.get(BASE, headers=_auth(token))
        unknown = await http.get(f"{BASE}/nothing.here", headers=_auth(token))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    rows = {row["key"]: row for row in body["entries"]}
    assert set(rows) == set(call_words.shipped())
    assert body["about"]
    stalls = rows[STALLS]
    assert (stalls["shape"], stalls["group"], stalls["edited"]) == ("pattern", "detection", False)
    assert stalls["asked_for"] and stalls["value"] == stalls["shipped"]
    assert stalls["confirmation"] == change_confirmation(STALLS)
    # The `missing` section's wildcard reaches every topic.
    assert rows["detection.topic.pricing"]["asked_for"]
    assert rows["detection.topic.pricing"]["shape"] == "list"
    assert rows["optout.patterns"]["shape"] == "table"
    assert rows["optout.patterns"]["note"]
    assert unknown.status_code == 404


async def test_a_bad_entry_is_refused_in_plain_words() -> None:
    token, _ = await _make_admin()
    async with _client() as http:
        unconfirmed = await http.put(
            f"{BASE}/{STALLS}", headers=_auth(token), json={"value": MARKER}
        )
        broken = await _put(http, token, STALLS, {"value": "(unclosed"})
        wrong_shape = await _put(http, token, STALLS, {"value": [MARKER]})
        everything = await _put(http, token, STALLS, {"value": "x*"})
        # Compiles alone; a global flag in the middle of the joined pattern does not.
        joined = await _put(http, token, STALLS, {"value": f"(?i){MARKER}"})
        # A named group compiles in Python; PostgreSQL, which searches with it, refuses it.
        postgres = await _put(http, token, HOURS, {"value": "(?P<x>timings)"})
        unchanged = await _put(http, token, STALLS, {"value": None})
    assert unconfirmed.status_code == 403
    for response, code in (
        (broken, "call_words_invalid"),
        (wrong_shape, "call_words_invalid"),
        (everything, "call_words_invalid"),
        (joined, "call_words_breaks_check"),
        (postgres, "call_words_postgres_refused"),
    ):
        assert response.status_code == 422, response.text
        assert response.json()["type"].endswith(f"/{code}")
    assert "pattern" in broken.json()["detail"]
    assert unchanged.status_code == 409
    async with untenanted_session() as session:
        assert await call_words_store.history(session, key=STALLS) == []


async def test_a_save_reaches_the_running_check_and_can_be_undone() -> None:
    token, admin_id = await _make_admin()
    shipped = call_words.shipped()[STALLS]
    assert detection._NONANSWER_RE.search(f"well {MARKER} now") is None
    async with _client() as http:
        saved = await _put(
            http, token, STALLS, {"value": f"{shipped}|{MARKER}", "note": "  a test word  "}
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["edited"] is True and body["value"] == f"{shipped}|{MARKER}"
        assert body["history"][0]["note"] == "a test word"

        await call_words_store.refresh_call_words()
        assert detection._NONANSWER_RE.search(f"well {MARKER} now") is not None

        listed = (await http.get(BASE, headers=_auth(token))).json()
        assert next(r for r in listed["entries"] if r["key"] == STALLS)["edited"] is True

        reset = await _put(http, token, STALLS, {"value": None})
        assert reset.status_code == 200, reset.text
        undone = reset.json()
    assert undone["edited"] is False and undone["value"] == shipped
    assert [h["value"] for h in undone["history"]] == [None, f"{shipped}|{MARKER}"]

    await call_words_store.refresh_call_words()
    assert detection._NONANSWER_RE.search(f"well {MARKER} now") is None

    async with untenanted_session() as session:
        audits = (
            (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE object_type = 'call_word_revisions' "
                        "AND actor_id = :actor ORDER BY at, created_at"
                    ),
                    {"actor": admin_id},
                )
            )
            .scalars()
            .all()
        )
    assert audits == ["platform.call_words_changed", "platform.call_words_reset"]
