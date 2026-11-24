"""The company training page's routes (D-995), driven over HTTP as the owner.

The rules themselves are in `company_training_test.py` and `company_training_background_test.
py`; this covers the seam: what each route answers. SHARED DATABASE DISCIPLINE: every
organisation is minted here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import company_training
from apps.api.db.session import tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from tests.agent_starters_test import _tenant

pytestmark = pytest.mark.rls

BASE = "/v1/company-training"


async def _call(token: str, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.request(
            method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
    return response.status_code, response.json() if response.content else None


async def test_the_owner_writes_the_overview() -> None:
    _tenant_id, token = await _tenant("custom", "Sunrise Homes")
    code, empty = await _call(token, "GET", "")
    assert code == 200, empty
    assert (empty["overview"], empty["training"], empty["version"]) == ("", "", 0)
    assert empty["training_max"] == company_training.TRAINING_MAX

    code, saved = await _call(token, "PUT", "/overview", json={"overview": " We build flats. "})
    assert code == 200, saved
    assert saved["overview"] == "We build flats."


async def test_rewrite_now_starts_pips_write_and_the_owners_save_is_their_edit() -> None:
    tenant_id, token = await _tenant("custom", "Sunrise Homes Pip")
    code, asked = await _call(token, "POST", "/proposal")
    assert code == 202, asked
    assert (asked["status"], asked["reasons"][-1]) == ("queued", "owner_asked")
    assert asked["due_at"] is not None

    code, saved = await _call(token, "PUT", "/training", json={"training": "We build flats."})
    assert code == 200, saved
    assert (saved["training"], saved["version"], saved["owner_edited"]) == (
        "We build flats.",
        1,
        True,
    )
    # The owner's save leaves Pip's write queued: it carries the owner's edit.
    assert saved["proposal"]["id"] == asked["id"]
    assert saved["last_write"] is None
    async with tenant_session(tenant_id) as session:
        assert (await company_training.read_training(session, tenant_id)).owner_edited


async def test_an_edit_begun_before_pips_background_save_does_not_replace_it() -> None:
    """FAILS IF: the owner's editor, opened on version 1, saves over the version Pip wrote in
    the background meanwhile, so Pip's rewrite is lost without anyone seeing it."""
    tenant_id, token = await _tenant("custom", "Sunrise Homes Stale")
    code, first = await _call(token, "PUT", "/training", json={"training": "We build flats."})
    assert code == 200, first
    async with tenant_session(tenant_id) as session:
        pips = await company_training.save_written(
            session,
            tenant_id,
            training="We build flats and villas.",
            base_version=first["version"],
            owner_edits={},
            last_write={},
        )
    assert pips == first["version"] + 1

    stale = {"training": "We build flats near the lake.", "version": first["version"]}
    code, refused = await _call(token, "PUT", "/training", json=stale)
    assert code == 409, refused
    assert refused["type"].endswith("/company_training_changed")
    code, now = await _call(token, "GET", "")
    assert (now["training"], now["version"]) == ("We build flats and villas.", pips)

    code, saved = await _call(token, "PUT", "/training", json={**stale, "version": pips})
    assert code == 200, saved
    assert saved["training"] == "We build flats near the lake."


async def test_stopping_a_draft_clears_it_and_a_second_stop_finds_nothing() -> None:
    _tenant_id, token = await _tenant("custom", "Sunrise Homes Stop")
    _code, asked = await _call(token, "POST", "/proposal")
    code, _ = await _call(token, "DELETE", f"/proposal/{asked['id']}")
    assert code == 204
    code, _ = await _call(token, "DELETE", f"/proposal/{asked['id']}")
    assert code == 404
    code, unknown = await _call(token, "DELETE", f"/proposal/{uuid.uuid4()}")
    assert code == 404, unknown
