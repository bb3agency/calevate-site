"""The announcement bar and the bell's feed (D-869).

1. An operator composes, edits and ends; each change is an audit row.
2. A client sees exactly its audience's messages: all, trial (never paid), paid, or itself.
3. Dismissing hides a message for that account only, and the dismissal is tenant data:
   another account's session reads zero rows of it (hard rule 1).
4. A client cannot reach the composer.
5. The bell merges the needs-attention queue and announcements, and the read mark moves
   forward only; marks are per account, invisible across tenants.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.conftest import mark_paid_for_tests

BASE = "/v1/admin/announcements"


@pytest.fixture(autouse=True)
async def _end_every_announcement_afterwards() -> AsyncIterator[None]:
    """An announcement for `all` reaches every account in the shared test database, so each
    test ends what it showed rather than leaving it on other tests' bells."""
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_announcements SET ended_at = now() WHERE ended_at IS NULL")
        )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _operator() -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


def _code(response: httpx.Response) -> str:
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _audit_actions(object_id: str) -> list[str]:
    async with untenanted_session() as session:
        rows = await session.execute(
            text("SELECT action FROM audit_log WHERE object_id = :id ORDER BY at"),
            {"id": object_id},
        )
        return [str(r[0]) for r in rows]


async def _shown(http: httpx.AsyncClient, headers: dict[str, str]) -> list[str]:
    response = await http.get("/v1/announcements", headers=headers)
    assert response.status_code == 200, response.text
    return [item["message"] for item in response.json()["items"]]


async def test_audiences_dismissal_and_the_composer_lifecycle() -> None:
    ops = await _operator()
    trial_id, trial_slug, trial_token = await _make_tenant()
    paid_id, paid_slug, paid_token = await _make_tenant()
    await mark_paid_for_tests(paid_id)
    trial = {"Authorization": f"Bearer {trial_token}", "X-Org-Slug": trial_slug}
    paid = {"Authorization": f"Bearer {paid_token}", "X-Org-Slug": paid_slug}
    tag = uuid.uuid4().hex[:6]

    async with _client() as http:
        everyone = await http.post(
            BASE,
            headers=ops,
            json={
                "message": f"All {tag}",
                "tone": "info",
                "link_url": "/billing",
                "link_label": "See billing",
            },
        )
        assert everyone.status_code == 201, everyone.text
        for audience in ("trial", "paid"):
            made = await http.post(
                BASE, headers=ops, json={"message": f"{audience} {tag}", "audience": audience}
            )
            assert made.status_code == 201, made.text
        just_paid = await http.post(
            BASE,
            headers=ops,
            json={
                "message": f"Only you {tag}",
                "tone": "critical",
                "audience": "tenant",
                "target_tenant_id": str(paid_id),
            },
        )
        later = await http.post(
            BASE,
            headers=ops,
            json={
                "message": f"Later {tag}",
                "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        assert later.json()["state"] == "scheduled"

        trial_sees = [m for m in await _shown(http, trial) if tag in m]
        paid_sees = [m for m in await _shown(http, paid) if tag in m]

        assert set(trial_sees) == {f"All {tag}", f"trial {tag}"}
        assert set(paid_sees) == {f"All {tag}", f"paid {tag}", f"Only you {tag}"}
        # Most urgent first.
        assert paid_sees[0] == f"Only you {tag}"

        # Edit, then end — each audited with what moved.
        everyone_id = everyone.json()["id"]
        edited = await http.patch(f"{BASE}/{everyone_id}", headers=ops, json={"tone": "warning"})
        assert edited.status_code == 200 and edited.json()["tone"] == "warning"
        ended = await http.post(f"{BASE}/{everyone_id}/end", headers=ops)
        assert ended.json()["state"] == "ended"
        refused = await http.patch(f"{BASE}/{everyone_id}", headers=ops, json={"tone": "info"})
        assert refused.status_code == 409
        assert f"All {tag}" not in await _shown(http, trial)

        # Dismissal is per account.
        paid_only_id = just_paid.json()["id"]
        gone = await http.post(f"/v1/announcements/{paid_only_id}/dismiss", headers=paid)
        assert gone.status_code == 204
        assert f"Only you {tag}" not in await _shown(http, paid)
        # A message for another account is not dismissable from this one: it was never shown.
        stranger = await http.post(f"/v1/announcements/{paid_only_id}/dismiss", headers=trial)
        assert stranger.status_code == 404

        # The composer is admin-realm only.
        client_try = await http.post(BASE, headers=paid, json={"message": "hi"})
        assert client_try.status_code in (401, 403)
        # A bad shape is refused before it reaches the table.
        bad = await http.post(BASE, headers=ops, json={"message": "x", "audience": "tenant"})
        assert bad.status_code == 422
        bad_link = await http.post(
            BASE, headers=ops, json={"message": "x", "link_url": "javascript:alert(1)"}
        )
        assert bad_link.status_code == 422

    assert await _audit_actions(everyone_id) == [
        "announcement.created",
        "announcement.updated",
        "announcement.ended",
    ]
    assert await _audit_actions(paid_only_id) == ["announcement.created", "announcement.dismissed"]

    # Hard rule 1: the dismissal row is the paid account's, and invisible to the trial one.
    async with tenant_session(trial_id) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM announcement_dismissals"))
        ).scalar() == 0
    async with tenant_session(paid_id) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM announcement_dismissals"))
        ).scalar() == 1


async def test_a_patch_cannot_blank_the_start() -> None:
    """`starts_at` is not one of the fields a PATCH may clear: a null is refused as a
    validation problem, never written into the NOT NULL column."""
    ops = await _operator()
    async with _client() as http:
        made = await http.post(
            BASE,
            headers=ops,
            json={
                "message": "Scheduled",
                "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        assert made.status_code == 201, made.text
        refused = await http.patch(
            f"{BASE}/{made.json()['id']}", headers=ops, json={"starts_at": None}
        )
        assert refused.status_code == 422, refused.text
        assert _code(refused) == "announcement_invalid"


async def test_the_bell_merges_sources_and_its_read_mark_only_moves_forward() -> None:
    ops = await _operator()
    tenant_id, slug, token = await _make_tenant()
    other_id, _other_slug, _other_token = await _make_tenant()
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    tag = uuid.uuid4().hex[:6]

    async with _client() as http:
        made = await http.post(
            BASE,
            headers=ops,
            json={
                "message": f"Bell {tag}",
                "audience": "tenant",
                "target_tenant_id": str(tenant_id),
            },
        )
        assert made.status_code == 201
        first = await http.get("/v1/notifications", headers=headers)
        assert first.status_code == 200, first.text
        body = first.json()
        mine = [n for n in body["items"] if n["source"] == "announcement" and tag in n["title"]]
        assert [n["title"] for n in mine] == [f"Bell {tag}"]
        assert mine[0]["unread"] is True
        assert body["seen_through"] is None

        seen = await http.post("/v1/notifications/seen", headers=headers, json={})
        assert seen.status_code == 200
        mark = seen.json()["seen_through"]
        earlier = await http.post(
            "/v1/notifications/seen",
            headers=headers,
            json={"through": (datetime.now(UTC) - timedelta(days=3)).isoformat()},
        )
        assert earlier.json()["seen_through"] == mark  # never backwards

        after = (await http.get("/v1/notifications", headers=headers)).json()
        assert after["unread"] == 0
        assert all(n["unread"] is False for n in after["items"])

    async with tenant_session(other_id) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM notification_reads"))
        ).scalar() == 0
    async with tenant_session(tenant_id) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM notification_reads"))
        ).scalar() == 1
