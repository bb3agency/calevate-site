"""In-call tools on ThinnestAI: custom actions registered at publish, verified per agent, and
ending in the same writes the Pipecat worker's tools make (D-678 phase 2).

The vendor is an `httpx.MockTransport` built from the documented shapes in
`thinnest-findings/mirror/snapshots/2026-10-07/pages/api-reference/`: an action is created
OFF and `enabled` on create is refused (actions/create-action.md:7, :93-98); headers are
write-only, only `headerNames` come back (:457, :7); `PATCH` with headers replaces the set
(actions/update-action.md:7); list is `{items, nextCursor}` (actions/list-actions.md:133-147);
`test` answers `{ok, status, result}` (actions/test-action.md:99-118). An action call names
its call in the `X-Call-Id` header and the body's `{{call.id}}`
(snapshots/2026-10-08/pages/agent/custom-api.md:84-119), read back with `GET /calls/{id}`.

SHARED DATABASE DISCIPLINE: every row is minted here and every assertion is scoped to it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_actions import (
    CALL_ID_FIELD,
    CALL_ID_HEADER,
    CALL_ID_PLACEHOLDER,
    SECRET_HEADER,
    ThinnestActions,
    set_thinnest_actions,
)
from apps.api.main import app as api_app
from apps.api.reliability.engine_actions import (
    ACTION_NAMES,
    action_secret_context,
    check_agent_actions,
    definitions,
    ensure_agent_actions,
    envelope_of,
    open_action_secret,
    retire_agent_actions,
)
from apps.api.worker.engine_actions import NOT_MATCHED_SAY, UNAVAILABLE_SAY
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant

pytestmark = [pytest.mark.rls]

ENGINE = "thinnest"
BASE = "https://api.calevate.example"
IST = ZoneInfo("Asia/Kolkata")


class FakeThinnest:
    """Their actions collections and live-call list, in memory."""

    def __init__(self) -> None:
        self.actions: dict[str, dict[str, dict[str, Any]]] = {}
        #: The header VALUES the vendor sealed, which its API never returns.
        self.sealed: dict[str, dict[str, str]] = {}
        self.live: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.calls_fail = False
        self.test_ok = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ta_live_test"
        path = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))
        if path.startswith("/calls/") and request.method == "GET":
            if self.calls_fail:
                return httpx.Response(500, json={"error": "boom"})
            wanted = path.removeprefix("/calls/")
            row = next((c for c in self.live if c["id"] == wanted), None)
            if row is None:
                return httpx.Response(404, json={"error": "No such call.", "code": "not_found"})
            return httpx.Response(200, json=row)
        parts = path.strip("/").split("/")
        assert parts[0] == "agents" and parts[2] == "actions"
        agent = parts[1]
        held = self.actions.setdefault(agent, {})
        if len(parts) == 3 and request.method == "GET":
            return httpx.Response(200, json={"items": list(held.values()), "nextCursor": None})
        if len(parts) == 3 and request.method == "POST":
            assert body is not None
            if "enabled" in body:
                return httpx.Response(400, json={"error": "Actions are created switched off."})
            if any(a["name"] == body["name"] for a in held.values()):
                return httpx.Response(409, json={"error": "An action with that name exists."})
            action_id = f"act_{uuid.uuid4().hex[:12]}"
            headers = body.pop("headers", {})
            self.sealed[action_id] = dict(headers)
            row = {
                "id": action_id,
                "agent": agent,
                **body,
                "headerNames": sorted(headers),
                "speakBefore": None,
                "speakAfter": None,
                "enabled": False,
                "createdAt": "2026-10-07T09:41:00Z",
                "updatedAt": "2026-10-07T09:41:00Z",
            }
            held[action_id] = row
            return httpx.Response(201, json=row)
        action_id = parts[3]
        row = held.get(action_id)
        if row is None:
            return httpx.Response(404, json={"error": "That action was not found."})
        if len(parts) == 5 and parts[4] == "test":
            return httpx.Response(
                200,
                json={"ok": self.test_ok, "status": 200 if self.test_ok else 401, "result": "."},
            )
        if request.method == "PATCH":
            assert body is not None
            if "headers" in body:
                headers = body.pop("headers")
                self.sealed[action_id] = dict(headers)
                row["headerNames"] = sorted(headers)
            row.update(body)
            return httpx.Response(200, json=row)
        if request.method == "DELETE":
            del held[action_id]
            return httpx.Response(204)
        return httpx.Response(405)

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.requests if m != "GET" and not p.endswith("/test")]


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeThinnest]:
    fake = FakeThinnest()
    client = ThinnestActions(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(fake.handler),
            base_url="https://app.thinnest.ai/api/v1",
            headers={"Authorization": "Bearer ta_live_test"},
        ),
    )
    set_thinnest_actions(client)
    monkeypatch.setattr(get_settings(), "engine_actions_base_url", BASE)
    monkeypatch.setattr(get_settings(), "engine", ENGINE)
    yield fake
    set_thinnest_actions(None)


async def _route(*, active: bool = True) -> tuple[uuid.UUID, uuid.UUID, str]:
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, :act, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id, "act": active},
        )
    return tenant_id, agent_id, ref


async def _ensure(tenant_id: uuid.UUID, ref: str) -> Any:
    async with tenant_session(tenant_id) as session:
        return await ensure_agent_actions(session, engine=ENGINE, engine_agent_ref=ref)


async def _held_secret(tenant_id: uuid.UUID, ref: str) -> str | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT action_secret_ciphertext, action_secret_nonce, "
                    "action_secret_dek_wrapped, action_secret_dek_nonce, "
                    "action_secret_kek_version FROM engine_agent_routes "
                    "WHERE engine = 'thinnest' AND engine_agent_ref = :ref"
                ),
                {"ref": ref},
            )
        ).one()
    envelope = envelope_of(tuple(row))
    return (
        None
        if envelope is None
        else open_action_secret(envelope, engine=ENGINE, engine_agent_ref=ref)
    )


async def _published(vendor: FakeThinnest) -> tuple[uuid.UUID, uuid.UUID, str, str]:
    tenant_id, agent_id, ref = await _route()
    await _ensure(tenant_id, ref)
    secret = await _held_secret(tenant_id, ref)
    assert secret
    return tenant_id, agent_id, ref, secret


def _live(
    ref: str, *, phone: str, direction: str = "inbound", reference: str | None = None
) -> tuple[str, dict[str, Any]]:
    call_id = f"out_{uuid.uuid4()}" if direction == "outbound" else f"in_{uuid.uuid4()}"
    return call_id, {
        "id": call_id,
        "status": "connected",
        "direction": direction,
        "phone": phone,
        "reference": reference,
        "agent": {"id": ref, "name": "x"},
    }


async def _post(
    tool: str,
    ref: str,
    secret: str | None,
    body: dict[str, Any],
    engine: str = ENGINE,
    *,
    call_id: str | None = None,
) -> httpx.Response:
    """One action call as the platform makes it: our secret, and the call it was made on in
    `X-Call-Id` and in the body's `call_id` (both filled by the platform, never the model)."""
    headers = {SECRET_HEADER: secret} if secret is not None else {}
    if call_id is not None:
        headers[CALL_ID_HEADER] = call_id
        body = {CALL_ID_FIELD: call_id, **body}
    transport = httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as raw:
        return await raw.post(
            f"/v1/worker/engine-actions/{engine}/{tool}?agent={ref}",
            content=json.dumps(body),
            headers={**headers, "Content-Type": "application/json"},
        )


# --- the wire shape ------------------------------------------------------------


def test_every_action_is_a_documented_shape_with_quoted_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine_actions_base_url", BASE)
    for definition in definitions(ENGINE, "ag_x"):
        wire = definition.wire()
        assert wire["method"] == "POST" and wire["url"].startswith(f"{BASE}/v1/worker/")
        assert wire["url"].endswith("?agent=ag_x") and "{{" not in wire["url"]
        assert 3 <= len(wire["name"]) <= 40 and wire["name"].replace("_", "").isalnum()
        assert len(wire["description"]) >= 10 and len(wire["parameters"]) <= 20
        template = json.loads(wire["bodyTemplate"])
        # Every body names its call with the platform-filled `{{call.id}}`, which is not a
        # parameter the model sees (agent/custom-api.md:84-96).
        assert template == {
            CALL_ID_FIELD: CALL_ID_PLACEHOLDER,
            **{p["name"]: "{{" + p["name"] + "}}" for p in wire["parameters"]},
        }
        assert all(p["name"] != "caller_number" for p in wire["parameters"])
        assert "enabled" not in wire and "headers" not in wire
    names = {d.name for d in definitions(ENGINE, "ag_x")}
    assert names == set(ACTION_NAMES.values())
    # The vendor's reserved built-ins (agent/custom-api.md:87-88).
    assert not names & {"search_knowledge", "capture_lead", "escalate_to_human"}


def test_the_agent_body_switches_off_the_vendors_own_callback_and_escalation() -> None:
    from apps.api.engine.thinnest import ThinnestEngine
    from tests.thinnest_engine_test import _cfg

    body = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg())
    assert body["scheduleCallbacks"] is False
    assert body["escalation"] == {"onNoAnswer": False, "onRequest": False}


# --- lifecycle -----------------------------------------------------------------


async def test_publish_registers_four_actions_off_then_on_with_our_sealed_header(
    vendor: FakeThinnest,
) -> None:
    tenant_id, _agent, ref = await _route()
    result = await _ensure(tenant_id, ref)
    assert (result.created, result.repaired, result.reenabled) == (4, 0, 0)
    secret = await _held_secret(tenant_id, ref)
    assert secret and len(secret) >= 32
    held = vendor.actions[ref]
    assert {a["name"] for a in held.values()} == set(ACTION_NAMES.values())
    assert all(a["enabled"] is True for a in held.values())
    assert all(vendor.sealed[i] == {SECRET_HEADER: secret} for i in held)
    # Created off, enabled by PATCH: no POST body carried `enabled` (the fake refuses one).
    posts = [b for m, p, b in vendor.requests if m == "POST" and p.endswith("/actions")]
    assert len(posts) == 4 and all("enabled" not in (b or {}) for b in posts)
    # Sealed under PLATFORM_KEK, bound to this route: the AAD names the agent.
    assert action_secret_context(ENGINE, ref).endswith(ref)


async def test_republish_converges_without_duplicates_or_writes(vendor: FakeThinnest) -> None:
    tenant_id, _agent, ref = await _route()
    await _ensure(tenant_id, ref)
    before = vendor.writes()
    again = await _ensure(tenant_id, ref)
    assert (again.created, again.repaired, again.reenabled, again.rekeyed) == (0, 0, 0, False)
    assert vendor.writes() == before
    assert len(vendor.actions[ref]) == 4


async def test_drift_is_repaired_and_reported(vendor: FakeThinnest) -> None:
    tenant_id, _agent, ref = await _route()
    await _ensure(tenant_id, ref)
    rows = list(vendor.actions[ref].values())
    rows[0]["description"] = "Edited in the console by somebody."
    rows[1]["enabled"] = False
    verdict = await check_agent_actions(tenant_id=tenant_id, engine=ENGINE, engine_agent_ref=ref)
    assert verdict == "repaired"
    assert all(a["enabled"] for a in vendor.actions[ref].values())
    wanted = {d.name: d.description for d in definitions(ENGINE, ref)}
    assert all(a["description"] == wanted[a["name"]] for a in vendor.actions[ref].values())
    assert (
        await check_agent_actions(tenant_id=tenant_id, engine=ENGINE, engine_agent_ref=ref)
        == "in_sync"
    )


async def test_a_failed_probe_is_reported_as_unreachable(vendor: FakeThinnest) -> None:
    tenant_id, _agent, ref = await _route()
    await _ensure(tenant_id, ref)
    vendor.test_ok = False
    verdict = await check_agent_actions(tenant_id=tenant_id, engine=ENGINE, engine_agent_ref=ref)
    assert verdict == "probe_failed"


async def test_a_lost_secret_is_replaced_on_every_action(vendor: FakeThinnest) -> None:
    tenant_id, _agent, ref = await _route()
    await _ensure(tenant_id, ref)
    old = await _held_secret(tenant_id, ref)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET action_secret_ciphertext = NULL, "
                "action_secret_nonce = NULL, action_secret_dek_wrapped = NULL, "
                "action_secret_dek_nonce = NULL, action_secret_kek_version = NULL "
                "WHERE engine_agent_ref = :ref"
            ),
            {"ref": ref},
        )
    result = await _ensure(tenant_id, ref)
    new = await _held_secret(tenant_id, ref)
    assert result.rekeyed and new and new != old
    assert all(
        v == {SECRET_HEADER: new} for k, v in vendor.sealed.items() if k in vendor.actions[ref]
    )
    assert len(vendor.actions[ref]) == 4


async def test_publish_refuses_without_a_public_actions_address(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _agent, ref = await _route()
    monkeypatch.setattr(get_settings(), "engine_actions_base_url", None)
    with pytest.raises(ProblemError) as caught:
        await _ensure(tenant_id, ref)
    assert caught.value.code == "engine_actions_url_not_public"
    assert vendor.requests == []


async def test_other_engines_are_untouched(vendor: FakeThinnest) -> None:
    tenant_id, _agent, ref = await _route()
    async with tenant_session(tenant_id) as session:
        result = await ensure_agent_actions(session, engine="pipecat", engine_agent_ref=ref)
    assert result.outcome == "not_applicable"
    assert await retire_agent_actions(engine="pipecat", engine_agent_ref=ref) == 0
    assert (
        await check_agent_actions(tenant_id=tenant_id, engine="pipecat", engine_agent_ref=ref)
        is None
    )
    assert vendor.requests == []


async def test_unpublish_removes_ours_and_leaves_a_console_action(vendor: FakeThinnest) -> None:
    tenant_id, _agent, ref = await _route()
    await _ensure(tenant_id, ref)
    vendor.actions[ref]["act_theirs"] = {
        "id": "act_theirs",
        "agent": ref,
        "name": "get_order",
        "description": "theirs",
        "method": "GET",
        "url": "https://x.example/o",
        "parameters": [],
        "bodyTemplate": None,
        "headerNames": [],
        "enabled": True,
    }
    assert await retire_agent_actions(engine=ENGINE, engine_agent_ref=ref) == 4
    assert list(vendor.actions[ref]) == ["act_theirs"]


# --- the endpoint: authentication ------------------------------------------------


async def test_unknown_agent_wrong_secret_and_no_header_are_one_401(vendor: FakeThinnest) -> None:
    _t, _a, ref, secret = await _published(vendor)
    answers = [
        await _post("opt-out", ref, "not-the-secret", {}),
        await _post("opt-out", ref, None, {}),
        await _post("opt-out", f"ag_{uuid.uuid4()}", secret, {}),
        await _post("opt-out", ref, secret, {}, engine="bolna"),
    ]
    assert {r.status_code for r in answers} == {401}
    assert {r.text for r in answers} == {answers[0].text}
    # Refused before parsing: the vendor was never asked about a call.
    assert not any(p.startswith("/calls") for _m, p, _b in vendor.requests)


async def test_one_agents_secret_cannot_act_for_another_tenants_agent(
    vendor: FakeThinnest,
) -> None:
    _ta, _aa, _ref_a, secret_a = await _published(vendor)
    _tb, _ab, ref_b, _secret_b = await _published(vendor)
    answer = await _post("handoff", ref_b, secret_a, {})
    assert answer.status_code == 401


async def test_an_inactive_route_is_refused(vendor: FakeThinnest) -> None:
    tenant_id, _agent, ref, secret = await _published(vendor)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE engine_agent_routes SET active = false WHERE engine_agent_ref = :r"),
            {"r": ref},
        )
    assert (await _post("handoff", ref, secret, {})).status_code == 401


async def test_a_deployment_on_another_engine_refuses_after_the_credential(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    _t, _a, ref, secret = await _published(vendor)
    monkeypatch.setattr(get_settings(), "engine", "pipecat")
    assert (await _post("handoff", ref, secret, {})).status_code == 409


# --- the endpoint: identifying the call --------------------------------------------


async def test_opt_out_suppresses_the_vendor_reported_number_once_on_replay(
    vendor: FakeThinnest,
) -> None:
    tenant_id, agent_id, ref, secret = await _published(vendor)
    call_id, row = _live(ref, phone="919876511101")
    vendor.live.append(row)
    body = {"reason": "stop calling", "language": "{{language}}"}
    first = await _post("opt-out", ref, secret, body, call_id=call_id)
    second = await _post("opt-out", ref, secret, body, call_id=call_id)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "recorded"
    assert set(first.json()) == {"status", "say"}
    # The call was read by its id, never found by a number.
    assert ("GET", f"/calls/{call_id}", None) in vendor.requests
    async with tenant_session(tenant_id) as session:
        dnc = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = '+919876511101'")
            )
        ).scalar_one()
        calls = (
            await session.execute(
                text(
                    "SELECT agent_id, direction, from_e164, status FROM calls "
                    "WHERE engine_call_id = :e"
                ),
                {"e": call_id},
            )
        ).all()
    assert dnc == 1
    assert calls == [(agent_id, "inbound", "+919876511101", "in_progress")]


async def test_no_call_an_unknown_call_and_a_contradicting_body_get_the_same_answer(
    vendor: FakeThinnest,
) -> None:
    tenant_id, _agent, ref, secret = await _published(vendor)
    call_id, row = _live(ref, phone="919876511103")
    vendor.live.append(row)
    no_header = await _post("opt-out", ref, secret, {})
    unknown = await _post("opt-out", ref, secret, {}, call_id=f"in_{uuid.uuid4()}")
    # A body naming another call than the header is not trusted either way.
    headers = {SECRET_HEADER: secret, CALL_ID_HEADER: call_id, "Content-Type": "application/json"}
    transport = httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as raw:
        contradicting = await raw.post(
            f"/v1/worker/engine-actions/{ENGINE}/opt-out?agent={ref}",
            content=json.dumps({CALL_ID_FIELD: "in_other"}),
            headers=headers,
        )
    for answer in (no_header, unknown, contradicting):
        assert answer.status_code == 200
        assert answer.json() == {"status": "caller_not_matched", "say": NOT_MATCHED_SAY}
    async with tenant_session(tenant_id) as session:
        dnc = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = '+919876511103'")
            )
        ).scalar_one()
    assert dnc == 0


async def test_a_call_that_has_ended_is_not_acted_on(vendor: FakeThinnest) -> None:
    _t, _a, ref, secret = await _published(vendor)
    call_id, row = _live(ref, phone="919876511104")
    vendor.live.append({**row, "status": "completed"})
    answer = await _post("callback-cancel", ref, secret, {}, call_id=call_id)
    assert answer.json()["status"] == "caller_not_matched"


async def test_another_agents_call_is_not_reachable(vendor: FakeThinnest) -> None:
    _ta, _aa, ref_a, secret_a = await _published(vendor)
    _tb, _ab, ref_b, _sb = await _published(vendor)
    call_id, row = _live(ref_b, phone="919876511105")
    vendor.live.append(row)
    answer = await _post("opt-out", ref_a, secret_a, {}, call_id=call_id)
    assert answer.json()["status"] == "caller_not_matched"


async def test_a_vendor_outage_is_an_honest_unavailable(vendor: FakeThinnest) -> None:
    _t, _a, ref, secret = await _published(vendor)
    vendor.calls_fail = True
    answer = await _post("opt-out", ref, secret, {}, call_id=f"in_{uuid.uuid4()}")
    assert answer.status_code == 200
    assert answer.json() == {"status": "unavailable", "say": UNAVAILABLE_SAY}


# --- the endpoint: the tools ---------------------------------------------------------


async def test_a_callback_on_an_outbound_call_confirms_then_books_our_dialled_number(
    vendor: FakeThinnest,
) -> None:
    tenant_id, agent_id, ref, secret = await _published(vendor)
    ours = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:id, :tid, :aid, :local, "
                "'outbound', '+919876511107', 'in_progress', now(), now())"
            ),
            {"id": ours, "tid": tenant_id, "aid": agent_id, "local": f"local-{ours}"},
        )
    vendor_call, row = _live(ref, phone="919876511107", direction="outbound", reference=str(ours))
    vendor.live.append(row)
    day = (datetime.now(UTC).astimezone(IST) + timedelta(days=2)).date().isoformat()
    ask = {"callback_date": day, "callback_time": "11:00"}
    first = await _post("callback", ref, secret, {**ask, "confirmed": "no"}, call_id=vendor_call)
    assert first.json()["status"] == "needs_confirmation" and first.json()["booked_for"]
    second = await _post(
        "callback", ref, secret, {**ask, "confirmed": "yes", "note": "price"}, call_id=vendor_call
    )
    assert second.json()["status"] == "booked"
    async with tenant_session(tenant_id) as session:
        booked = (
            await session.execute(
                text(
                    "SELECT phone_e164, source_call_id, source_execution_id "
                    "FROM scheduled_callbacks WHERE agent_id = :a"
                ),
                {"a": agent_id},
            )
        ).all()
    assert booked == [("+919876511107", ours, vendor_call)]


async def test_cancel_with_nothing_booked_says_so(vendor: FakeThinnest) -> None:
    _t, _a, ref, secret = await _published(vendor)
    call_id, row = _live(ref, phone="919876511108")
    vendor.live.append(row)
    answer = await _post("callback-cancel", ref, secret, {}, call_id=call_id)
    assert answer.json()["status"] == "cancelled"


async def test_handoff_tells_the_truth_without_asking_for_the_number(
    vendor: FakeThinnest,
) -> None:
    _t, _a, ref, secret = await _published(vendor)
    answer = await _post("handoff", ref, secret, {"reason": "wants a person"})
    assert answer.status_code == 200
    assert answer.json()["status"] == "not_available"
    assert not any(p.startswith("/calls") for _m, p, _b in vendor.requests)


async def test_an_unknown_tool_and_an_unreadable_body_are_refused_after_auth(
    vendor: FakeThinnest,
) -> None:
    _t, _a, ref, secret = await _published(vendor)
    assert (await _post("transfer", ref, secret, {})).status_code == 404
    transport = httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as raw:
        bad = await raw.post(
            f"/v1/worker/engine-actions/{ENGINE}/opt-out?agent={ref}",
            content=b"[1, 2]",
            headers={SECRET_HEADER: secret},
        )
    assert bad.status_code == 422


# --- the sweeps and the lifecycle -------------------------------------------------------


async def test_the_drift_sweep_alarms_on_repaired_and_unreachable_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from apps.api.agents.reconciliation import DriftCandidate
    from apps.workers import engine_reconciliation as sweep

    async def _drift(**_kw: Any) -> Any:
        return SimpleNamespace(
            state="applied",
            truthful_answer_applied=True,
            own_voice_key_applied=True,
            own_voice_key_expected=None,
        )

    async def _record(*_a: Any, **_kw: Any) -> bool:
        return True

    async def _inbound(*_a: Any, **_kw: Any) -> str:
        return "unchanged"

    raised: list[str] = []
    monkeypatch.setattr(sweep, "engine_drift_for", _drift)
    monkeypatch.setattr(sweep, "record_drift", _record)
    monkeypatch.setattr(sweep, "reconcile_inbound_truthful_answer", _inbound)

    async def _no_settings(**_kw: Any) -> None:
        return None

    monkeypatch.setattr(sweep, "check_agent_settings", _no_settings)
    monkeypatch.setattr(sweep, "alert", lambda _stage, code, **_kw: raised.append(code))
    candidate = DriftCandidate(
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        engine_agent_ref="ag_x",
        drift_checked_at=None,
    )
    for verdict, code in (
        ("repaired", "engine_actions_repaired"),
        ("probe_failed", "engine_actions_unreachable"),
        ("in_sync", None),
        (None, None),
    ):
        raised.clear()

        async def _check(_v: Any = verdict, **_kw: Any) -> Any:
            return _v

        monkeypatch.setattr(sweep, "check_agent_actions", _check)
        assert await sweep._reconcile_one(ENGINE, candidate) == "applied"
        assert raised == ([code] if code else [])


async def test_pausing_an_agent_retires_its_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.agents import lifecycle

    tenant_id, agent_id = await _seed_tenant(f"ag_{uuid.uuid4()}")
    retired: list[tuple[uuid.UUID, str | None]] = []

    async def _retire(*, agent_id: uuid.UUID, ref: str | None) -> int:
        retired.append((agent_id, ref))
        return 4

    monkeypatch.setattr(lifecycle, "retire_in_call_actions", _retire)
    async with tenant_session(tenant_id) as session:
        result = await lifecycle.deactivate_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert result.changed and retired == [(agent_id, ref)]


# --- live transfer (D-690) -------------------------------------------------------------


async def test_an_agent_that_transfers_live_holds_no_handover_action_of_ours(
    vendor: FakeThinnest,
) -> None:
    """With a destination on duty the platform's own `escalate_to_human` puts the caller
    through, so our record-only hand-over action is removed rather than left to contradict
    it; the drift sweep (`live_handover=None`) neither recreates nor removes it."""
    tenant_id, _agent, ref = await _route()
    await _ensure(tenant_id, ref)
    handoff = ACTION_NAMES["handoff"]
    assert handoff in {a["name"] for a in vendor.actions[ref].values()}
    async with tenant_session(tenant_id) as session:
        await ensure_agent_actions(session, engine=ENGINE, engine_agent_ref=ref, live_handover=True)
    names = {a["name"] for a in vendor.actions[ref].values()}
    assert handoff not in names and len(names) == 3
    verdict = await check_agent_actions(tenant_id=tenant_id, engine=ENGINE, engine_agent_ref=ref)
    assert verdict == "in_sync"
    assert handoff not in {a["name"] for a in vendor.actions[ref].values()}


async def test_the_drift_probe_identifies_no_call_and_writes_nothing(vendor: FakeThinnest) -> None:
    """The probe is the call-back cancel action: a vendor test sends no call id
    (agent/custom-api.md:111-114), so our endpoint finds no call and changes nothing."""
    _t, _a, ref, secret = await _published(vendor)
    tested = [p for m, p, _b in vendor.requests if p.endswith("/test")]
    assert tested == []
    await check_agent_actions(tenant_id=_t, engine=ENGINE, engine_agent_ref=ref)
    probe_id = next(
        i for i, a in vendor.actions[ref].items() if a["name"] == ACTION_NAMES["callback-cancel"]
    )
    assert any(p.endswith(f"/actions/{probe_id}/test") for _m, p, _b in vendor.requests)
    answer = await _post("callback-cancel", ref, secret, {})
    assert answer.json()["status"] == "caller_not_matched"
