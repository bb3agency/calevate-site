"""Error paths that told someone a thing happened when it had not (audit round 3, lane V6)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.ingest import routes as ingest_routes
from apps.api.main import app as api_app
from apps.api.whatsapp import hook_routes
from sqlalchemy import text
from tests.meta_lead_ads_test import (
    _client,
    _daytime,  # noqa: F401 — the autouse clock fixture; the gate refuses to dial at night
    _notification,
    _retriever,
    _tenant_with_meta_source,
    _wire,
)
from tests.meta_lead_ads_test import _signed as _meta_signed
from tests.whatsapp_embedded_signup_test import APP_SECRET, _delivery, _signed, _waba


@pytest.fixture
def meta_app(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "meta_app_secret", APP_SECRET)


async def test_a_whatsapp_event_the_queue_refused_is_taken_by_metas_redelivery(
    meta_app: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim commits before its job is queued. When the queue refuses the job, the 503
    makes Meta redeliver; that redelivery must queue the event, not be answered 200 as a
    duplicate of a claim nobody is working on."""
    queued: list[dict[str, Any]] = []
    refuse = {"left": 1}

    async def flaky_enqueue(job: str, payload: dict[str, Any], **kw: Any) -> str:
        if "inbox_id" in payload and refuse["left"]:
            refuse["left"] -= 1
            raise ConnectionError("queue unreachable")
        queued.append(payload)
        return "job"

    monkeypatch.setattr(hook_routes, "enqueue", flaky_enqueue)
    body = json.dumps(_delivery(_waba())).encode()
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as http:
        first = await http.post("/hooks/v1/meta/whatsapp", content=body, headers=_signed(body))
        again = await http.post("/hooks/v1/meta/whatsapp", content=body, headers=_signed(body))
    assert first.status_code == 503
    assert again.status_code == 200
    assert again.json() == {"received": 2, "accepted": 2, "duplicate": 0}
    assert len(queued) == 2


async def test_a_meta_lead_whose_handling_broke_off_lands_on_metas_redelivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure that is not a verdict (a database error mid-write) used to escape with the
    claim still `processing`, so Meta's redelivery inside the lease was answered as a
    duplicate and the lead never landed."""
    tenant_id, _agent, webhook_id = await _tenant_with_meta_source()
    _wire(monkeypatch, _retriever(phone="9876512301", name="Broke Off", consent=None))
    real_ingest = ingest_routes.ingest_lead
    broken = {"left": 1}

    async def ingest_once_broken(*args: Any, **kwargs: Any) -> Any:
        if broken["left"]:
            broken["left"] -= 1
            raise ConnectionError("database went away")
        return await real_ingest(*args, **kwargs)

    monkeypatch.setattr(ingest_routes, "ingest_lead", ingest_once_broken)
    raw, headers = _meta_signed(_notification(leadgen_id="900000000000777"))
    path = f"/hooks/v1/ingest/meta/{webhook_id}"
    async with _client() as http:
        first = await http.post(path, content=raw, headers=headers)
        again = await http.post(path, content=raw, headers=headers)
    assert first.status_code == 503
    assert again.status_code == 200
    assert again.json()["accepted"] == 1
    async with tenant_session(tenant_id) as session:
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
    assert leads == 1
