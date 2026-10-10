"""Calling setup (D-716, 10 Oct 2026).

1. **The lead plan's clock.** Wait, hours, days, holidays and the four after-hours answers,
   pure arithmetic in IST.
2. **The plan as data.** Refusals in words; RLS (hard rule 1); a hold and its release.
3. **Retries.** Keys, booking only up to the plan's count, and standing down once answered.
4. **The caller lookup.** The signature, the variables (never a number), the endpoint's one
   401 and its empty answer, and the vendor secret's capture and rotation.
5. **Call settings on ThinnestAI.** The machine switch and ring time reach the agent body;
   web and WhatsApp surfaces are drift that cannot be repaired from here; the call cap is
   clamped to the engine's 20 minutes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.crm import caller_lookup
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import (
    RING_SECONDS,
    SURFACES_LABEL,
    ThinnestEngine,
    unsanctioned_surfaces,
)
from apps.api.engine.thinnest_actions import ThinnestActions, parse_call_start, set_thinnest_actions
from apps.api.ingest import lead_policy
from apps.api.ingest.lead_policy import DEFAULT_PLAN, LeadCallPlan, when_to_call
from apps.api.main import app as api_app
from apps.api.reliability import engine_lookups
from apps.api.worker.engine_lookups import verify_lookup_signature
from calevate_shared.webhook_signature import timestamped_sha256_signature
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant
from tests.thinnest_engine_test import _cfg

pytestmark = [pytest.mark.rls]

BASE = "https://api.calevate.example"


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    """An IST wall-clock moment in October 2026 as a UTC instant (10 Oct is a Saturday)."""
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC) - timedelta(hours=5, minutes=30)


# --- 1. the clock -------------------------------------------------------------------------


def test_the_default_plan_calls_at_once_inside_the_platform_window() -> None:
    assert when_to_call(DEFAULT_PLAN, ist(10, 11)).kind == "now"
    late = when_to_call(DEFAULT_PLAN, ist(10, 22))
    assert late.kind == "later" and late.at == ist(11, 9)


def test_a_wait_books_the_call_for_later_inside_hours() -> None:
    plan = LeadCallPlan(wait_seconds=120)
    timing = when_to_call(plan, ist(10, 11))
    assert timing.kind == "later" and timing.reason == "wait"
    assert timing.at == ist(10, 11, 2)


def test_after_hours_answers() -> None:
    base = LeadCallPlan(hours_start=time(10), hours_end=time(18))
    arrived = ist(10, 20)  # Saturday evening
    assert when_to_call(base, arrived).at == ist(11, 10)
    plus = when_to_call(
        LeadCallPlan(hours_start=time(10), hours_end=time(18), after_hours="open_plus_3h"), arrived
    )
    assert plus.at == ist(11, 13)
    early = ist(11, 7)  # Sunday before opening: "next day" skips today's opening
    nxt = when_to_call(
        LeadCallPlan(hours_start=time(10), hours_end=time(18), after_hours="next_day"), early
    )
    assert nxt.at == ist(12, 10)
    assert when_to_call(base, early).at == ist(11, 10)
    held = when_to_call(
        LeadCallPlan(hours_start=time(10), hours_end=time(18), after_hours="hold"), arrived
    )
    assert held.kind == "hold"


def test_closed_days_and_holidays_are_skipped() -> None:
    plan = LeadCallPlan(days=("mon", "tue", "wed", "thu", "fri"), holidays=(date(2026, 10, 12),))
    timing = when_to_call(plan, ist(10, 11))  # Saturday
    assert timing.kind == "later" and timing.at == ist(13, 9)  # Mon 12 is a holiday


def test_three_hours_after_a_short_day_moves_to_the_next_opening() -> None:
    plan = LeadCallPlan(hours_start=time(9), hours_end=time(11), after_hours="open_plus_3h")
    assert when_to_call(plan, ist(10, 20)).at == ist(12, 9)


def test_refusals_name_the_field() -> None:
    for bad, field in (
        (LeadCallPlan(hours_start=time(8)), "hours_start"),
        (LeadCallPlan(hours_start=time(12), hours_end=time(11)), "hours_start"),
        (LeadCallPlan(days=()), "days"),
        (LeadCallPlan(retry_attempts=4), "retry_attempts"),
        (LeadCallPlan(retry_interval_minutes=5), "retry_interval_minutes"),
    ):
        with pytest.raises(ProblemError) as caught:
            lead_policy.validated(bad)
        assert caught.value.fields and caught.value.fields[0]["field"] == field
    assert lead_policy.validated(LeadCallPlan(days=("sun", "mon"))).days == ("mon", "sun")


# --- 2/3. the plan as data, holds and retries -----------------------------------------------


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, agent_id = await _seed_tenant(f"plan_{uuid.uuid4().hex[:10]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'outbound' WHERE id = :a"), {"a": agent_id}
        )
    return tenant_id, agent_id


async def _lead(tenant_id: uuid.UUID, agent_id: uuid.UUID, **data: Any) -> uuid.UUID:
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:id, :t, :a, :p, :n, 'webhook', 'new', "
                "CAST(:d AS jsonb), now(), now())"
            ),
            {
                "id": lead_id,
                "t": tenant_id,
                "a": agent_id,
                "p": data.pop("phone", "+919876543210"),
                "n": data.pop("name", None),
                "d": json.dumps(data),
            },
        )
    return lead_id


async def test_a_saved_plan_is_the_tenants_own() -> None:
    tenant_id, agent_id = await _tenant()
    other, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        stored, changed = await lead_policy.save_plan(
            session,
            tenant_id=tenant_id,
            plan=LeadCallPlan(calling_agent_id=agent_id, detect_machines=True, retry_attempts=2),
            user_id=None,
        )
    assert changed and stored.retry_attempts == 2 and stored.calling_agent_id == agent_id
    async with tenant_session(tenant_id) as session:
        assert await lead_policy.machine_detection_on(session)
    async with tenant_session(other) as session:
        assert await lead_policy.load_plan(session) == DEFAULT_PLAN
        assert (
            await session.execute(text("SELECT count(*) FROM lead_call_policies"))
        ).scalar() == 0


async def test_an_answer_only_agent_cannot_call_new_leads() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
        with pytest.raises(ProblemError) as caught:
            await lead_policy.save_plan(
                session,
                tenant_id=tenant_id,
                plan=LeadCallPlan(calling_agent_id=agent_id),
                user_id=None,
            )
    assert caught.value.code == "lead_agent_cannot_call"


async def test_a_held_lead_is_held_once_and_released_as_a_call_back() -> None:
    tenant_id, agent_id = await _tenant()
    other, _ = await _tenant()
    lead_id = await _lead(tenant_id, agent_id, name="Asha")
    async with tenant_session(tenant_id) as session:
        hold = await lead_policy.hold_lead(
            session, tenant_id=tenant_id, lead_id=lead_id, agent_id=agent_id, source="website_form"
        )
        again = await lead_policy.hold_lead(
            session, tenant_id=tenant_id, lead_id=lead_id, agent_id=agent_id, source="website_form"
        )
    assert hold is not None and again is None
    async with tenant_session(other) as session:
        assert await lead_policy.list_held(session) == []
    async with tenant_session(tenant_id) as session:
        held = await lead_policy.list_held(session)
        assert [h.lead_name for h in held] == ["Asha"]
        callback_id, _due = await lead_policy.release_held(
            session, tenant_id=tenant_id, hold_id=hold, user_id=None
        )
        key = (
            await session.execute(
                text("SELECT source_execution_id FROM scheduled_callbacks WHERE id = :c"),
                {"c": callback_id},
            )
        ).scalar()
        assert key == f"lead-release:{hold}"
        assert await lead_policy.count_held(session) == 0
        with pytest.raises(ProblemError) as settled:
            await lead_policy.drop_held(session, hold_id=hold, user_id=None)
        assert settled.value.detail == (
            "Someone on your team already had it released, and its call is booked."
        )
        second = await lead_policy.hold_lead(
            session, tenant_id=tenant_id, lead_id=lead_id, agent_id=agent_id, source="website_form"
        )
        assert second is not None
        me = uuid.uuid4()
        await lead_policy.drop_held(session, hold_id=second, user_id=me)
        with pytest.raises(ProblemError) as mine:
            await lead_policy.release_held(
                session, tenant_id=tenant_id, hold_id=second, user_id=me
            )
        assert mine.value.detail == "You already had it taken off the list."


async def _holds(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (await session.execute(text("SELECT count(*) FROM lead_call_holds"))).scalar() or 0
        )


async def test_both_erasures_take_a_held_lead_off_the_queue() -> None:
    """A hold left behind could be released into a call-back after the certificate."""
    from apps.api.compliance import tenant_erasure
    from apps.workers.retention import execute_deletion_request, execute_tenant_erasure

    tenant_id, agent_id = await _tenant()
    phone = "+919876500231"
    lead_id = await _lead(tenant_id, agent_id, phone=phone)
    kept = await _lead(tenant_id, agent_id, phone="+919876500232")
    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        for lead in (lead_id, kept):
            await lead_policy.hold_lead(
                session, tenant_id=tenant_id, lead_id=lead, agent_id=agent_id, source="webhook"
            )
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, scope, requested_at, "
                "created_at) VALUES (:i, :t, :p, 'all', now(), now())"
            ),
            {"i": request_id, "t": tenant_id, "p": phone},
        )
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})
    assert await _holds(tenant_id) == 1

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = :s WHERE id = :t"),
            {"s": tenant_erasure.REQUIRED_STATUS, "t": tenant_id},
        )
    async with tenant_session(tenant_id) as session:
        record = await tenant_erasure.request_tenant_erasure(
            session, tenant_id=tenant_id, reason="engagement ended"
        )
    await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})
    assert await _holds(tenant_id) == 0


def test_retry_keys_parse_back() -> None:
    assert lead_policy.new_lead_attempt("lead-ingest:abc:2026") == (0, "abc:2026")
    assert lead_policy.new_lead_attempt("lead-release:h1") == (0, "h1")
    assert lead_policy.new_lead_attempt(lead_policy.retry_key(2, "r")) == (2, "r")
    assert lead_policy.new_lead_attempt("exec_123") is None
    assert lead_policy.new_lead_attempt(None) is None


async def test_retries_are_booked_up_to_the_plan_and_stand_down_once_answered() -> None:
    tenant_id, agent_id = await _tenant()
    lead_id = await _lead(tenant_id, agent_id)
    plan = LeadCallPlan(retry_attempts=1, retry_interval_minutes=30)
    now = ist(10, 11)
    async with tenant_session(tenant_id) as session:
        first = await lead_policy.book_retry(
            session,
            tenant_id=tenant_id,
            plan=plan,
            lead_id=lead_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            attempt=0,
            root="r1",
            now=now,
        )
        assert first == ist(10, 11, 30)
        none = await lead_policy.book_retry(
            session,
            tenant_id=tenant_id,
            plan=plan,
            lead_id=lead_id,
            agent_id=agent_id,
            phone_e164="+919876543210",
            attempt=1,
            root="r1",
            now=now,
        )
        assert none is None
        verdict = await lead_policy.retry_still_wanted(
            session, lead_id=lead_id, phone_e164="+919876543210", booked_at=datetime.now(UTC)
        )
        assert verdict == "dial"
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:id, :t, :a, :l, :e, "
                "'outbound', '+919876543210', 'completed', now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "a": agent_id,
                "l": lead_id,
                "e": f"c_{uuid.uuid4()}",
            },
        )
        answered = await lead_policy.retry_still_wanted(
            session,
            lead_id=lead_id,
            phone_e164="+919876543210",
            booked_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    assert answered == "answered"


# --- 4. the caller lookup -------------------------------------------------------------------


def test_cleaning_keeps_letters_and_drops_numbers_and_emails() -> None:
    assert caller_lookup.clean_name("Asha  Menon 98765") == "Asha Menon"
    assert caller_lookup.clean_name("రాఘవ") == "రాఘవ"
    assert caller_lookup.clean_name("12345") is None
    cleaned = caller_lookup.clean_text("chilli, call 98765 43210 or a@b.com", 80)
    assert cleaned is not None and "98765" not in cleaned and "@" not in cleaned
    many = {f"k{i}": "x" * 200 for i in range(30)}
    bounded = caller_lookup.bounded(many)
    assert len(bounded) == caller_lookup.MAX_VALUES
    assert all(len(v) == caller_lookup.MAX_VALUE_CHARS for v in bounded.values())
    assert caller_lookup.spoken_when(ist(11, 16)) == "Sun 11 Oct, 4:00 PM"


async def test_variables_carry_name_and_interest_and_history_only_with_memory() -> None:
    tenant_id, agent_id = await _tenant()
    phone = "+919811122233"
    await _lead(
        tenant_id,
        agent_id,
        phone=phone,
        name="Ravi Kumar",
        need="Red chilli 5 kg",
        language="Telugu",
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = false WHERE id = :a"), {"a": agent_id}
        )
        plain = await caller_lookup.caller_variables(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )
    assert plain["name"] == "Ravi Kumar" and plain["first_name"] == "Ravi"
    assert plain["product_interest"].startswith("Red chilli")
    assert plain["caller_known"] == "yes" and plain["callback_allowed"] == "yes"
    assert not set(plain) & caller_lookup.MEMORY_KEYS
    assert phone not in json.dumps(plain) and "9811122233" not in json.dumps(plain)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = true WHERE id = :a"), {"a": agent_id}
        )
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, created_at) "
                "VALUES (:id, :t, :p, 'tenant', 'manual', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "p": phone},
        )
        remembered = await caller_lookup.caller_variables(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )
    assert remembered["preferred_language"] == "Telugu"
    assert remembered["callback_allowed"] == "no"


async def test_an_unknown_caller_gets_nothing_personal() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        values = await caller_lookup.caller_variables(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000001"
        )
    assert values == {"caller_known": "no", "callback_allowed": "yes"}


def _signed(body: bytes, secret: str, *, at: datetime | None = None) -> dict[str, str]:
    stamp = (at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    return {
        "x-thinnest-signature-v2": timestamped_sha256_signature(body, secret, signed_at=stamp),
        "x-thinnest-delivered-at": stamp,
        "content-type": "application/json",
    }


def test_the_signature_is_the_v2_webhook_rule() -> None:
    body = b'{"event":"call.started"}'
    good = _signed(body, "s3cret")
    kwargs = {
        "header": good["x-thinnest-signature-v2"],
        "delivered_at": good["x-thinnest-delivered-at"],
    }
    assert verify_lookup_signature(body, secret="s3cret", **kwargs)
    assert not verify_lookup_signature(body, secret="other", **kwargs)
    assert not verify_lookup_signature(body + b" ", secret="s3cret", **kwargs)
    assert not verify_lookup_signature(body, secret=None, **kwargs)
    stale = _signed(body, "s3cret", at=datetime.now(UTC) - timedelta(minutes=6))
    assert not verify_lookup_signature(
        body,
        secret="s3cret",
        header=stale["x-thinnest-signature-v2"],
        delivered_at=stale["x-thinnest-delivered-at"],
    )


def test_only_an_inbound_phone_or_whatsapp_lookup_is_answerable() -> None:
    def body(**over: Any) -> bytes:
        return json.dumps(
            {
                "event": "call.started",
                "agentId": "ag_1",
                "from": "+9198",
                "direction": "inbound",
                "surface": "phone",
                **over,
            }
        ).encode()

    assert parse_call_start(body()).answerable  # type: ignore[union-attr]
    assert parse_call_start(body(surface="whatsapp")).answerable  # type: ignore[union-attr]
    assert not parse_call_start(body(surface="web")).answerable  # type: ignore[union-attr]
    assert not parse_call_start(body(direction="outbound")).answerable  # type: ignore[union-attr]
    assert parse_call_start(b"[]") is None


class FakeVendor:
    """`GET`/`PATCH /agents/{id}`'s voice object, minting a secret the way the docs say."""

    def __init__(self) -> None:
        self.url: str | None = None
        self.minted = 0
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"id": "x", "voice": {"callStartUrl": self.url}})
        body = json.loads(request.content)
        self.requests.append(body)
        voice = body["voice"]
        new = voice["callStartUrl"] != self.url or voice.get("callStartSecret") == "rotate"
        self.url = voice["callStartUrl"]
        out: dict[str, Any] = {"callStartUrl": self.url}
        if new:
            self.minted += 1
            out["callStartSecret"] = f"cs_{self.minted}"
        return httpx.Response(200, json={"id": "x", "voice": out})


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeVendor]:
    fake = FakeVendor()
    set_thinnest_actions(
        ThinnestActions(
            api_key="ta_live_test",
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(fake.handler),
                base_url="https://app.thinnest.ai/api/v1",
            ),
        )
    )
    monkeypatch.setattr(get_settings(), "engine_actions_base_url", BASE)
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    yield fake
    set_thinnest_actions(None)


async def _route(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return ref


async def _ensure(tenant_id: uuid.UUID, ref: str) -> str:
    async with tenant_session(tenant_id) as session:
        return await engine_lookups.ensure_call_start(
            session, engine="thinnest", engine_agent_ref=ref
        )


async def _secret(tenant_id: uuid.UUID, ref: str) -> str | None:
    async with tenant_session(tenant_id) as session:
        _exists, secret, _t, _a = await engine_lookups.read_call_start_secret(
            session, engine="thinnest", engine_agent_ref=ref
        )
    return secret


async def test_the_lookup_is_set_kept_and_rotated_when_the_secret_is_lost(
    vendor: FakeVendor,
) -> None:
    tenant_id, agent_id = await _tenant()
    ref = await _route(tenant_id, agent_id)
    assert await _ensure(tenant_id, ref) == "set"
    assert vendor.url == f"{BASE}/v1/worker/engine-lookups/thinnest?agent={ref}"
    assert await _secret(tenant_id, ref) == "cs_1"
    assert await _ensure(tenant_id, ref) == "in_sync"
    assert len(vendor.requests) == 1
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET call_start_secret_ciphertext = NULL, "
                "call_start_secret_nonce = NULL, call_start_secret_dek_wrapped = NULL, "
                "call_start_secret_dek_nonce = NULL, call_start_secret_kek_version = NULL "
                "WHERE engine_agent_ref = :r"
            ),
            {"r": ref},
        )
    assert await _ensure(tenant_id, ref) == "rotated"
    assert vendor.requests[-1]["voice"]["callStartSecret"] == "rotate"
    assert await _secret(tenant_id, ref) == "cs_2"
    vendor.url = "https://elsewhere.example/lookup"
    assert (
        await engine_lookups.check_call_start(
            tenant_id=tenant_id, engine="thinnest", engine_agent_ref=ref
        )
        == "repaired"
    )


async def test_the_endpoint_answers_signed_lookups_and_refuses_the_rest(vendor: FakeVendor) -> None:
    tenant_id, agent_id = await _tenant()
    ref = await _route(tenant_id, agent_id)
    await _ensure(tenant_id, ref)
    phone = "+919822233344"
    await _lead(tenant_id, agent_id, phone=phone, name="Meena")
    body = json.dumps(
        {
            "event": "call.started",
            "callId": "CA1",
            "surface": "phone",
            "agentId": ref,
            "from": phone,
            "to": "+918000000000",
            "direction": "inbound",
            "contact": None,
            "sentAt": "2026-10-10T10:00:00Z",
        }
    ).encode()

    async def post(
        headers: dict[str, str], content: bytes = body, agent: str = ref
    ) -> httpx.Response:
        transport = httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444))
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as raw:
            return await raw.post(
                f"/v1/worker/engine-lookups/thinnest?agent={agent}",
                content=content,
                headers=headers,
            )

    ok = await post(_signed(body, "cs_1"))
    assert ok.status_code == 200
    assert ok.json()["variables"]["first_name"] == "Meena"
    assert phone not in ok.text
    assert (await post(_signed(body, "wrong"))).status_code == 401
    assert (await post({"content-type": "application/json"})).status_code == 401
    other = json.dumps({**json.loads(body), "agentId": "ag_other"}).encode()
    assert (await post(_signed(other, "cs_1"), other)).status_code == 401
    web = json.dumps({**json.loads(body), "surface": "web"}).encode()
    answered = await post(_signed(web, "cs_1"), web)
    assert answered.status_code == 200 and answered.json() == {"variables": {}}


# --- 5. call settings on ThinnestAI ---------------------------------------------------------


def test_the_machine_switch_and_ring_time_reach_the_agent_body() -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    off = engine._agent_body(_cfg())["voice"]
    on = engine._agent_body(_cfg(detect_machines=True))["voice"]
    assert off["detectMachines"] is False and on["detectMachines"] is True
    assert off["ringSeconds"] == RING_SECONDS == 30
    assert off["recordCalls"] is True
    assert "detect_machines" not in _cfg(detect_machines=True).model_dump()


def test_web_and_whatsapp_surfaces_are_unsanctioned() -> None:
    assert unsanctioned_surfaces({"voice": {"surfaces": ["phone"]}}) == []
    assert unsanctioned_surfaces({"voice": {"surfaces": ["phone", "web", "whatsapp"]}}) == [
        "web",
        "whatsapp",
    ]
    assert unsanctioned_surfaces({"voice": {}}) == []


async def test_surfaces_drift_is_reported_and_not_called_repaired() -> None:
    cfg = _cfg()
    engine = ThinnestEngine(api_key="ta_live_test")
    held = engine._agent_body(cfg)
    held["voice"]["surfaces"] = ["phone", "whatsapp"]
    held["voice"]["ringSeconds"] = 45

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=engine.built_in_tools_body(cfg))
        if request.method == "GET":
            return httpx.Response(200, json=held)
        return httpx.Response(200, json={})

    engine._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://app.thinnest.ai/api/v1"
    )
    drifted = await engine.settings_drift("ag_1", cfg)
    assert "ring_seconds" in drifted and SURFACES_LABEL in drifted
    with pytest.raises(ProblemError) as caught:
        await engine.repair_settings("ag_1", cfg, ["ring_seconds", SURFACES_LABEL])
    assert caught.value.code == "engine_surfaces_not_sanctioned"


def test_the_call_cap_is_clamped_to_twenty_minutes_on_thinnest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.agents import service

    monkeypatch.setattr(service, "get_engine", lambda: ThinnestEngine(api_key="ta_live_test"))
    assert service.call_cap_max_s() == 1200
    service.refuse_call_cap_out_of_range(1200)
    service.refuse_call_cap_out_of_range(None)
    with pytest.raises(ProblemError) as caught:
        service.refuse_call_cap_out_of_range(1260)
    assert caught.value.code == "call_cap_out_of_range"
