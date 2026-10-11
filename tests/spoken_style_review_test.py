"""Ops > Spoken style, end to end against the database (D-744).

1. Only `ops:manage` reads or changes it, and publishing takes the step-up string.
2. An entry change is audited and touches only the working copy; nothing reaches an agent
   until the language is published.
3. Publishing stamps the reviewer, queues a platform live-apply in the same transaction, and
   the published layer is what `calevate_shared.spoken_style` serves after a refresh.

Written against Odia (`or-IN`), whose table is short, so a run never changes the Telugu
words another suite reads. The tables are append-only, so `_clean` removes this suite's
rows as the OWNER (`tests/model_pricing_test._purge_table`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops import spoken_style_store
from apps.api.ops.spoken_style_routes import publish_confirmation
from calevate_shared.config import Settings
from calevate_shared.spoken_style import style_for
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.model_pricing_test import _purge_table

LANGUAGE = "or-IN"
BASE = f"/v1/ops/spoken-style/{LANGUAGE}"


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
                "VALUES (:id, 'Style', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}", admin_id


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    spoken_style_store.reset_for_test()
    yield
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: the tables are append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            for table in ("spoken_style_publications", "spoken_style_revisions"):
                await _purge_table(conn, table, "language", [LANGUAGE])
            await conn.execute(
                text("DELETE FROM live_apply_runs WHERE reasons ? :reason"),
                {"reason": f"spoken_style:{LANGUAGE}"},
            )
    finally:
        await engine.dispose()
    spoken_style_store.reset_for_test()


async def test_only_ops_manage_may_read_it() -> None:
    operator, _ = await _make_admin("operator")
    async with _client() as http:
        refused = await http.get("/v1/ops/spoken-style", headers=_auth(operator))
    assert refused.status_code == 403

    token, _ = await _make_admin()
    async with _client() as http:
        listed = await http.get("/v1/ops/spoken-style", headers=_auth(token))
        unknown = await http.get("/v1/ops/spoken-style/xx-XX", headers=_auth(token))
    assert listed.status_code == 200, listed.text
    rows = {row["language"]: row for row in listed.json()["languages"]}
    assert rows["te-IN"]["review"] == "needs_native_review"
    assert rows["te-IN"]["total"] > 100 and rows["te-IN"]["approved"] == 0
    assert unknown.status_code == 404


async def test_review_then_publish_reaches_the_prompt_layer() -> None:
    token, admin_id = await _make_admin()
    async with _client() as http:
        view = (await http.get(BASE, headers=_auth(token))).json()
        assert view["publish_confirmation"] == publish_confirmation(LANGUAGE)
        register = next(e for e in view["entries"] if e["kind"] == "register")
        assert register["status"] == "needs_review" and register["origin"] == "file"

        approved = await http.post(
            f"{BASE}/entries",
            headers=_auth(token),
            json={"kind": "register", "key": "line", "action": "approve"},
        )
        assert approved.status_code == 200, approved.text
        added = await http.post(
            f"{BASE}/entries",
            headers=_auth(token),
            json={
                "kind": "swap",
                "action": "add",
                "value": {"formal": "ଧନ୍ୟବାଦ", "spoken": "thanks", "in_prompt": True},
            },
        )
        assert added.status_code == 200, added.text
        again = await http.post(
            f"{BASE}/entries",
            headers=_auth(token),
            json={"kind": "swap", "action": "add", "value": {"formal": "ଧନ୍ୟବାଦ", "spoken": "x"}},
        )
        assert again.status_code == 422
        retired = await http.post(
            f"{BASE}/entries",
            headers=_auth(token),
            json={"kind": "register", "key": "line", "action": "retire"},
        )
        assert retired.status_code == 422
        body = added.json()
        swap = next(e for e in body["entries"] if e["kind"] == "swap")
        assert (swap["status"], swap["origin"], swap["unpublished"]) == ("approved", "added", True)
        assert swap["published_value"] is None
        assert body["unpublished_changes"] == 2

        # Nothing has reached an agent yet.
        await spoken_style_store.refresh_spoken_style()
        assert style_for(LANGUAGE).word_swaps == ()  # type: ignore[union-attr]

        unconfirmed = await http.post(
            f"{BASE}/publish", headers=_auth(token), json={"reviewer_name": "Sri"}
        )
        assert unconfirmed.status_code == 403
        published = await http.post(
            f"{BASE}/publish",
            headers=_auth(token, publish_confirmation(LANGUAGE)),
            json={"reviewer_name": "  Sri  J ", "note": "first pass"},
        )
        assert published.status_code == 200, published.text
        nothing_new = await http.post(
            f"{BASE}/publish",
            headers=_auth(token, publish_confirmation(LANGUAGE)),
            json={"reviewer_name": "Sri"},
        )
        assert nothing_new.status_code == 409

    stamp = published.json()
    assert stamp["reviewed_by"] == "Sri J" and stamp["reviewed_on"]
    assert stamp["unpublished_changes"] == 0
    assert stamp["history"][0]["note"] == "first pass"
    # The examples are not approved yet, so the language is still awaiting review.
    assert stamp["review"] == "needs_native_review"

    async with untenanted_session() as session:
        runs = (
            await session.execute(
                text("SELECT scope FROM live_apply_runs WHERE reasons ? :reason"),
                {"reason": f"spoken_style:{LANGUAGE}"},
            )
        ).all()
        audits = (
            (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE object_type IN "
                        "('spoken_style_revisions', 'spoken_style_publications') "
                        "AND actor_id = :actor ORDER BY at, created_at"
                    ),
                    {"actor": admin_id},
                )
            )
            .scalars()
            .all()
        )
    assert [r[0] for r in runs] == ["platform"]
    assert audits[-3:] == [
        "platform.spoken_style_approve",
        "platform.spoken_style_add",
        "platform.spoken_style_published",
    ]

    await spoken_style_store.refresh_spoken_style()
    style = style_for(LANGUAGE)
    assert style is not None
    assert style.word_swaps == (("ଧନ୍ୟବାଦ", "thanks"),)
    assert style.prompt_swaps == (("ଧନ୍ୟବାଦ", "thanks"),)
