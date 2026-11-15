"""The company training page's routes (D-995), driven over HTTP as the owner.

The rules themselves are in `company_training_test.py`; this covers the seam: what each route
answers, that a kept Pip draft is settled by the same save, and that a file is held in the
knowledge. SHARED DATABASE DISCIPLINE: every organisation is minted here.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import company_training
from apps.api.db.session import tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_starters_test import _tenant
from tests.conftest import FakeS3

pytestmark = pytest.mark.rls

BASE = "/v1/company-training"


async def _call(token: str, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.request(
            method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
    return response.status_code, response.json() if response.content else None


async def test_the_owner_writes_the_overview_adds_materials_and_removes_one() -> None:
    _tenant_id, token = await _tenant("custom", "Sunrise Homes")
    code, empty = await _call(token, "GET", "")
    assert code == 200, empty
    assert (empty["overview"], empty["training"], empty["version"]) == ("", "", 0)
    assert empty["training_max"] == company_training.TRAINING_MAX

    code, saved = await _call(token, "PUT", "/overview", json={"overview": " We build flats. "})
    assert code == 200, saved
    assert saved["overview"] == "We build flats."

    code, note = await _call(
        token, "POST", "/materials", json={"kind": "note", "title": "Prices", "note": "60 lakh"}
    )
    assert code == 201, note
    code, link = await _call(
        token,
        "POST",
        "/materials",
        json={"kind": "link", "title": "Website", "url": "https://example.com"},
    )
    assert code == 201, link
    code, _ = await _call(token, "POST", f"/materials/{note['id']}/archive")
    assert code == 204
    code, read = await _call(token, "GET", "")
    assert [m["title"] for m in read["materials"]] == ["Website"]


async def test_a_file_goes_into_the_knowledge_and_onto_the_training(s3: FakeS3) -> None:
    del s3
    tenant_id, token = await _tenant("custom", "Sunrise Homes Files")
    code, material = await _call(
        token,
        "POST",
        "/materials/upload",
        files={"file": ("prices.txt", b"Flats from 60 lakh in Kompally.", "text/plain")},
    )
    assert code == 201, material
    assert (material["kind"], material["title"]) == ("file", "prices.txt")
    async with tenant_session(tenant_id) as session:
        held = (
            await session.execute(
                text("SELECT 1 FROM kb_uploads WHERE id = :u"), {"u": material["kb_upload_id"]}
            )
        ).first()
    assert held is not None


async def test_keeping_pips_draft_saves_it_and_settles_the_draft() -> None:
    tenant_id, token = await _tenant("custom", "Sunrise Homes Pip")
    code, refused = await _call(token, "POST", "/proposal")
    assert code == 422, refused
    assert refused["type"].endswith("/overview_required")

    await _call(token, "PUT", "/overview", json={"overview": "We build flats in Kompally."})
    code, asked = await _call(token, "POST", "/proposal")
    assert code == 202, asked
    assert asked["status"] == "drafting"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE company_trainings SET proposal = proposal || "
                "jsonb_build_object('status', 'ready', 'training', 'We build flats.')"
            )
        )

    code, kept = await _call(
        token,
        "PUT",
        "/training",
        json={"training": "We build flats.", "proposal_id": asked["id"]},
    )
    assert code == 200, kept
    assert (kept["training"], kept["version"], kept["proposal"]) == ("We build flats.", 1, None)


async def test_stopping_a_draft_clears_it_and_a_second_stop_finds_nothing() -> None:
    _tenant_id, token = await _tenant("custom", "Sunrise Homes Stop")
    await _call(token, "PUT", "/overview", json={"overview": "We build flats."})
    _code, asked = await _call(token, "POST", "/proposal")
    code, _ = await _call(token, "DELETE", f"/proposal/{asked['id']}")
    assert code == 204
    code, _ = await _call(token, "DELETE", f"/proposal/{asked['id']}")
    assert code == 404
    code, unknown = await _call(token, "DELETE", f"/proposal/{uuid.uuid4()}")
    assert code == 404, unknown
