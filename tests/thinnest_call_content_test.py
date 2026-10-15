"""ThinnestAI call content, call retention and the two workspace events, at the adapter (D-798).

Shapes are the 15 Oct 2026 mirror's, `thinnest-findings/mirror/snapshots/2026-10-15/pages/
api-reference/`: `post-call/delete-call-content.md:443-589` (200 `{contentDeleted,
contentDeletedAt, recordingsPending, call}`, 403 not a full key, 404 no such call, 409 live or
booked, 410 workspace deleted, 429/503 try again), `workspace/update-workspace.md:528-599`
(`callRetentionDays`, `planRetentionDays`), `calls/get-call.md:1014-1027` (`contentDeleted`)
and `webhooks.md:536-597` (`contact.erased`, `byok.changed`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.engine.thinnest_customer_data import CallContentDeletion, ThinnestCustomerData
from apps.api.engine.vendor_http import EngineRateLimitedError, EngineRejectedError

WS = "org_content-client"


class Vendor:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body = body
        self.seen: list[tuple[str, str, str | None, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().removeprefix("/api/v1")
        sent = json.loads(request.content) if request.content else None
        self.seen.append((request.method, path, request.headers.get("Thinnest-Workspace"), sent))
        return httpx.Response(self.status, json=self.body)


def _client(vendor: Vendor) -> ThinnestCustomerData:
    return ThinnestCustomerData(
        api_key="ta_live_test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(vendor), base_url=BASE_URL),
    )


_DELETED = {
    "contentDeleted": True,
    "contentDeletedAt": "2026-10-15T10:00:00Z",
    "recordingsPending": 2,
    "call": None,
}


# --- DELETE /calls/{id}/content -----------------------------------------------------------


async def test_a_deletion_answers_its_time_and_the_files_still_queued() -> None:
    vendor = Vendor(200, _DELETED)
    answer = await _client(vendor).delete_call_content(WS, "out_1")
    assert answer == CallContentDeletion(
        outcome="deleted",
        deleted_at=datetime(2026, 10, 15, 10, tzinfo=UTC),
        recordings_pending=2,
    )
    assert not answer.settled
    assert vendor.seen == [("DELETE", "/calls/out_1/content", WS, None)]


async def test_a_call_in_our_developer_workspace_is_deleted_with_no_header() -> None:
    vendor = Vendor(200, {**_DELETED, "recordingsPending": 0, "contentDeletedAt": None})
    answer = await _client(vendor).delete_call_content(None, "out 2/x")
    assert answer.settled and answer.deleted_at is None
    assert vendor.seen[0][1:3] == ("/calls/out%202%2Fx/content", None)


@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [
        (404, {"error": "No such call.", "code": "not_found"}, "absent"),
        (410, {"error": "Deleted.", "code": "workspace_deleted"}, "workspace_deleted"),
        (409, {"error": "Still live.", "code": "call_live"}, "busy"),
    ],
)
async def test_the_documented_refusals_map_to_our_outcomes(
    status: int, body: dict[str, str], outcome: str
) -> None:
    answer = await _client(Vendor(status, body)).delete_call_content(WS, "out_1")
    assert answer.outcome == outcome
    assert answer.settled is (outcome != "busy")


async def test_a_key_that_is_not_full_is_a_permanent_refusal() -> None:
    with pytest.raises(ProblemError) as refused:
        await _client(Vendor(403, {"error": "no", "code": "key_scope_build"})).delete_call_content(
            WS, "out_1"
        )
    assert refused.value.code == "engine_key_not_full"
    assert refused.value.kind == "business_rule"


async def test_an_unknown_workspace_and_a_transient_failure_are_raised() -> None:
    gone_workspace = Vendor(404, {"error": "Workspace not found.", "code": "workspace_not_found"})
    with pytest.raises(EngineRejectedError):
        await _client(gone_workspace).delete_call_content(WS, "out_1")
    with pytest.raises(EngineRejectedError) as down:
        await _client(Vendor(503, {"error": "later", "code": "unavailable"})).delete_call_content(
            WS, "out_1"
        )
    assert down.value.vendor_status == 503


async def test_a_throttle_is_raised_for_the_jobs_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    import apps.api.engine.vendor_http as vendor_http

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(vendor_http.asyncio, "sleep", _no_sleep)
    with pytest.raises(EngineRateLimitedError):
        await _client(Vendor(429, {"error": "slow", "code": "rate_limited"})).delete_call_content(
            WS, "out_1"
        )


async def test_an_answer_without_content_deleted_is_not_taken_as_done() -> None:
    with pytest.raises(ProblemError) as bad:
        await _client(Vendor(200, {"call": None})).delete_call_content(WS, "out_1")
    assert bad.value.code == "engine_bad_response"


# --- callRetentionDays --------------------------------------------------------------------


async def test_retention_is_read_and_set_in_the_workspace() -> None:
    vendor = Vendor(200, {"id": WS, "callRetentionDays": None, "planRetentionDays": 30})
    client = _client(vendor)
    held = await client.read_retention(WS)
    assert (held.call_retention_days, held.plan_retention_days) == (None, 30)
    vendor.body = {"id": WS, "callRetentionDays": 30, "planRetentionDays": 30}
    after = await client.set_retention(WS, 30)
    assert after.call_retention_days == 30
    assert vendor.seen == [
        ("GET", "/workspace", WS, None),
        ("PATCH", "/workspace", WS, {"callRetentionDays": 30}),
    ]


async def test_retention_refuses_a_non_day_and_an_answer_without_the_plan() -> None:
    client = _client(Vendor(200, {"id": WS, "callRetentionDays": 30}))
    for days in (0, True):
        with pytest.raises(ValueError):
            await client.set_retention(WS, days)
    with pytest.raises(ProblemError) as bad:
        await client.read_retention(None)
    assert bad.value.code == "engine_bad_response"


# --- contentDeleted on a call ---------------------------------------------------------------


def _engine(body: dict[str, Any]) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=body)),
            base_url=BASE_URL,
        ),
    )


_CALL = {
    "id": "out_1",
    "status": "completed",
    "direction": "outbound",
    "startedAt": "2026-10-01T10:00:00Z",
    "endedAt": "2026-10-01T10:01:00Z",
    "seconds": 60,
    "analysedAt": "2026-10-01T10:02:00Z",
    "transcript": [],
    "recording": None,
}


async def test_a_call_whose_content_was_deleted_is_read_as_such_and_never_fetched() -> None:
    engine = _engine({**_CALL, "contentDeleted": True, "contentDeletedAt": "2026-10-10T00:00:00Z"})
    snapshot = await engine.get_execution(f"out_1@{WS}")
    assert snapshot.content_deleted is True
    assert snapshot.transcript == []
    assert engine.recording_source(snapshot) is None

    kept = await _engine(_CALL).get_execution("out_1")
    assert kept.content_deleted is False
    assert engine.recording_source(kept) is not None


async def test_a_listed_call_carries_content_deleted_too() -> None:
    engine = _engine(
        {"items": [{**_CALL, "contentDeleted": True}, {**_CALL, "id": "out_2"}], "nextCursor": None}
    )
    listing = await engine.list_executions(since=datetime(2026, 10, 1, tzinfo=UTC))
    assert [s.content_deleted for s in listing.snapshots] == [True, False]


# --- the two workspace events ----------------------------------------------------------------


def test_contact_erased_is_read_with_its_ids_only() -> None:
    engine = _engine({})
    event = engine.parse_contact_erased(
        {
            "id": "evt_1",
            "event": "contact.erased",
            "data": {"contactId": "cust_1", "erasedAt": "2026-10-06T11:42:05Z"},
        }
    )
    assert event is not None
    assert (event.event_id, event.contact_id, event.workspace) == ("evt_1", "cust_1", None)
    assert event.erased_at == datetime(2026, 10, 6, 11, 42, 5, tzinfo=UTC)
    named = engine.parse_contact_erased(
        {"id": "evt_2", "event": "contact.erased", "data": {"contactId": "c", "workspaceId": WS}}
    )
    assert named is not None and named.workspace == WS
    assert engine.parse_contact_erased({"id": "evt_3", "event": "contact.erased"}) is None
    assert engine.parse_contact_erased({"event": "byok.changed", "id": "e", "data": {}}) is None


def test_byok_changed_is_read_with_enums_and_the_state_after() -> None:
    engine = _engine({})
    event = engine.parse_byok_changed(
        {
            "id": "evt_1",
            "event": "byok.changed",
            "data": {
                "change": "key_replaced",
                "kind": "tts",
                "provider": "cartesia",
                "byokEnabled": True,
                "scope": "voice",
            },
        }
    )
    assert event is not None
    assert (event.change, event.kind, event.provider, event.byok_enabled, event.scope) == (
        "key_replaced",
        "tts",
        "cartesia",
        True,
        "voice",
    )
    loose = engine.parse_byok_changed(
        {"id": "e", "event": "byok.changed", "data": {"change": "byok_disabled", "byokEnabled": 1}}
    )
    assert loose is not None and loose.byok_enabled is None and loose.kind is None
    assert (
        engine.parse_byok_changed({"id": "e", "event": "byok.changed", "data": {"change": "x"}})
        is None
    )
    assert engine.parse_byok_changed({"id": "e", "event": "contact.erased", "data": {}}) is None
