"""Numbers rented in ThinnestAI's console: record, price, attach, reconcile (D-691).

The vendor is a mock built from `thinnest-findings/mirror/snapshots/2026-10-08/pages/
api-reference/phone-numbers/`: `GET /phone-numbers/{number}` carries `agent` and
`callingAgent` (`get-phone-number.md:405-418`); `PATCH` applies `label`, `agent`,
`callingAgent` in that order and "a refusal stops there with the earlier changes kept"
(`update-phone-number.md:7`); `GET /phone-numbers/business-details` reports the workspace's
application (`get-business-details.md:412-470`).
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Iterator, Sequence
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import engine_numbers, number_catalog
from apps.api.campaigns.number_pricing import record_attested_price_inr
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.api.engine.thinnest_numbers import ThinnestNumbers, set_thinnest_numbers
from apps.api.main import app
from apps.workers import number_rental
from calevate_shared.engine import ProvisionedNumber
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

PRICE = Decimal("499.00")


def _number() -> str:
    """A rented Indian number as the vendor spells it: digits with the country code."""
    return f"9180{secrets.randbelow(10**8):08d}"


class FakeVendor:
    """ThinnestAI's numbers, in memory."""

    def __init__(self) -> None:
        self.numbers: dict[str, dict[str, Any]] = {}
        self.patches: list[tuple[str, dict[str, Any]]] = []
        self.refuse_calling_agent = False
        self.business: dict[str, Any] = {"status": "accepted", "canRent": True}

    def hold(self, number: str, *, rented: bool = True, agent: str | None = None) -> None:
        self.numbers[number] = {
            "number": number,
            "label": None,
            "source": "rented" if rented else "brought",
            "agent": agent,
            "since": "2026-10-08T07:15:40Z",
            "provider": None,
            "callingAgent": None,
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path == "/phone-numbers/business-details":
            return httpx.Response(200, json=self.business)
        number = path.removeprefix("/phone-numbers/")
        row = self.numbers.get(number)
        if row is None:
            return httpx.Response(404, json={"error": "Not found.", "code": "not_found"})
        if request.method == "GET":
            return httpx.Response(200, json=row)
        body = json.loads(request.content)
        self.patches.append((number, body))
        if "agent" in body:
            row["agent"] = body["agent"]
        if "callingAgent" in body:
            if self.refuse_calling_agent:
                return httpx.Response(409, json={"error": "Turn voice on.", "code": "conflict"})
            row["callingAgent"] = body["callingAgent"]
        return httpx.Response(200, json=row)


class _ListingEngine(FakeEngine):
    name = "thinnest"

    def __init__(self, vendor: FakeVendor) -> None:
        super().__init__()
        self._vendor = vendor

    async def list_engine_numbers(self) -> Sequence[ProvisionedNumber]:
        return [
            ProvisionedNumber(
                e164=f"+{row['number']}",
                provider="thinnest",
                engine_number_ref=row["number"],
                engine_owned=row["source"] == "rented",
                answering_agent_ref=row["agent"],
            )
            for row in self._vendor.numbers.values()
        ]


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeVendor]:
    import apps.api.engine as engine_module

    fake = FakeVendor()
    set_thinnest_numbers(
        ThinnestNumbers(
            api_key="ta_live_test",
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(fake.handler),
                base_url="https://app.thinnest.ai/api/v1",
            ),
        )
    )
    previous = dict(engine_module._instances)
    engine_module._instances["thinnest"] = _ListingEngine(fake)
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    try:
        yield fake
    finally:
        set_thinnest_numbers(None)
        engine_module._instances.clear()
        engine_module._instances.update(previous)


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    raised: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        engine_numbers, "alert", lambda _kind, code, **kw: raised.append((code, kw))
    )
    return raised


async def _admin() -> tuple[uuid.UUID, dict[str, str]]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id, {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def _attested(admin_id: uuid.UUID) -> None:
    async with untenanted_session() as session:
        await record_attested_price_inr(
            session, inr_per_month=PRICE, source="console, D-681", attested_by=admin_id
        )


async def _client_with_agent(direction: str = "inbound") -> tuple[uuid.UUID, uuid.UUID, str]:
    created = await admin_service.create_organization(
        name="Console Numbers",
        slug=f"cn-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    ref = f"ag_{uuid.uuid4()}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET engine = 'thinnest', engine_agent_ref = :r, status = 'live', "
                "direction = :d WHERE id = :a"
            ),
            {"r": ref, "a": agent_id, "d": direction},
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, agent_id, ref


async def _post(path: str, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as client:
        return await client.post(path, json=body, headers=headers)


async def _get(path: str, headers: dict[str, str]) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as client:
        return await client.get(path, headers=headers)


def _code(response: httpx.Response) -> str:
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def _row(tenant_id: uuid.UUID, number_id: str) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT provider, engine_number_ref, engine_owned, client_inr_per_month, "
                    "agent_id, series FROM phone_numbers WHERE id = :id"
                ),
                {"id": number_id},
            )
        ).one()


# --- record this number ----------------------------------------------------------------


async def test_record_this_number_prices_it_attaches_it_and_it_renews(vendor: FakeVendor) -> None:
    admin_id, headers = await _admin()
    await _attested(admin_id)
    tenant_id, agent_id, ref = await _client_with_agent()
    number = _number()
    vendor.hold(number)

    page = await _get(f"/v1/admin/numbers/tenants/{tenant_id}/engine", headers)
    listed = {n["e164"]: n for n in page.json()["numbers"]}
    assert listed[f"+{number}"]["number_id"] is None

    recorded = await _post(
        f"/v1/admin/numbers/tenants/{tenant_id}/engine/record",
        {"e164": f"+{number}", "direction": "both", "agent_id": str(agent_id)},
        headers,
    )

    assert recorded.status_code == 201, recorded.text
    body = recorded.json()
    assert Decimal(body["client_inr_per_month"]) == PRICE
    assert body["platform_attachment"] == "applied"
    assert body["series"] == "standard"
    provider, engine_ref, owned, inr, bound, _series = await _row(tenant_id, body["number_id"])
    assert (provider, engine_ref, owned, inr, bound) == ("thinnest", number, True, PRICE, agent_id)
    # Our binding is the vendor's now: the agent's own line, lent to nobody else.
    assert (vendor.numbers[number]["agent"], vendor.numbers[number]["callingAgent"]) == (ref, None)

    page = await _get(f"/v1/admin/numbers/tenants/{tenant_id}/engine", headers)
    listed = {n["e164"]: n for n in page.json()["numbers"]}
    assert listed[f"+{number}"]["number_id"] == body["number_id"]
    async with tenant_session(tenant_id) as session:
        renewing = {str(r[0]) for r in (await session.execute(text(number_rental._RENEWING))).all()}
    assert body["number_id"] in renewing


async def test_a_brought_number_is_recorded_unpriced(vendor: FakeVendor) -> None:
    _admin_id, headers = await _admin()
    tenant_id, _agent_id, _ref = await _client_with_agent()
    number = _number()
    vendor.hold(number, rented=False)

    recorded = await _post(
        f"/v1/admin/numbers/tenants/{tenant_id}/engine/record", {"e164": f"+{number}"}, headers
    )

    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["client_inr_per_month"] is None
    assert recorded.json()["platform_attachment"] == "unchanged"


async def test_a_number_the_platform_does_not_hold_or_another_client_answers_is_refused(
    vendor: FakeVendor,
) -> None:
    admin_id, headers = await _admin()
    await _attested(admin_id)
    tenant_id, _agent_id, _ref = await _client_with_agent()
    _neighbour, _their_agent, their_ref = await _client_with_agent()
    theirs = _number()
    vendor.hold(theirs, agent=their_ref)

    absent = await _post(
        f"/v1/admin/numbers/tenants/{tenant_id}/engine/record", {"e164": f"+{_number()}"}, headers
    )
    taken = await _post(
        f"/v1/admin/numbers/tenants/{tenant_id}/engine/record", {"e164": f"+{theirs}"}, headers
    )

    assert (absent.status_code, _code(absent)) == (422, "engine_number_not_held")
    assert (taken.status_code, _code(taken)) == (409, "engine_number_answered_by_other_client")
    assert vendor.patches == []


async def test_the_record_route_refuses_off_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    _admin_id, headers = await _admin()
    tenant_id, _agent_id, _ref = await _client_with_agent()
    monkeypatch.setattr(get_settings(), "engine", "fake")
    refused = await _post(
        f"/v1/admin/numbers/tenants/{tenant_id}/engine/record", {"e164": f"+{_number()}"}, headers
    )
    assert _code(refused) == "number_provider_not_on_this_engine"


async def test_a_hand_entered_number_is_checked_against_the_platforms_list(
    vendor: FakeVendor,
) -> None:
    admin_id, headers = await _admin()
    await _attested(admin_id)
    tenant_id, _agent_id, _ref = await _client_with_agent()
    number = _number()
    vendor.hold(number)
    base = {"series": "standard", "provider": "thinnest", "direction": "both"}
    path = f"/v1/admin/tenants/{tenant_id}/numbers"

    absent = await _post(path, {**base, "e164": f"+{_number()}"}, headers)
    wrong_ref = await _post(
        path, {**base, "e164": f"+{number}", "engine_number_ref": "9100000000"}, headers
    )
    recorded = await _post(path, {**base, "e164": f"+{number}"}, headers)

    assert _code(absent) == "engine_number_not_held"
    assert _code(wrong_ref) == "engine_number_ref_mismatch"
    assert recorded.status_code == 201, recorded.text
    _provider, engine_ref, owned, inr, _bound, _series = await _row(
        tenant_id, recorded.json()["id"]
    )
    assert (engine_ref, owned, inr) == (number, True, PRICE)


# --- attaching ---------------------------------------------------------------------------


async def test_attaching_points_the_platform_and_a_partial_apply_alarms(
    vendor: FakeVendor, alerts: list[tuple[str, dict[str, Any]]]
) -> None:
    _admin_id, headers = await _admin()
    tenant_id, agent_id, ref = await _client_with_agent()
    number = _number()
    vendor.hold(number, rented=False)
    number_id = (
        await _post(
            f"/v1/admin/numbers/tenants/{tenant_id}/engine/record", {"e164": f"+{number}"}, headers
        )
    ).json()["number_id"]
    # Somebody lent it to a stranger in the console, and the vendor will now refuse the
    # `callingAgent` half: `agent` is applied first and kept.
    vendor.numbers[number]["callingAgent"] = "ag_stranger"
    vendor.refuse_calling_agent = True

    attached = await _post(
        f"/v1/admin/tenants/{tenant_id}/numbers/{number_id}/agent",
        {"agent_id": str(agent_id)},
        headers,
    )

    assert attached.status_code == 200, attached.text
    assert attached.json()["platform_attachment"] == "partial"
    assert vendor.numbers[number]["agent"] == ref
    assert vendor.patches[-1] == (number, {"agent": ref, "callingAgent": None})
    [(code, fields)] = alerts
    assert code == "engine_number_attachment_failed"
    assert fields["number_id"] == number_id

    vendor.refuse_calling_agent = False
    async with tenant_session(tenant_id) as session:
        routing = await number_catalog.assign_number_to_agent(
            session, tenant_id=tenant_id, number_id=uuid.UUID(number_id), agent_id=None
        )
    assert routing.failed == 0
    assert (vendor.numbers[number]["agent"], vendor.numbers[number]["callingAgent"]) == (
        None,
        None,
    )


async def test_an_outbound_only_agent_is_lent_the_number_and_answers_nothing(
    vendor: FakeVendor,
) -> None:
    _admin_id, headers = await _admin()
    tenant_id, agent_id, ref = await _client_with_agent(direction="outbound")
    number = _number()
    vendor.hold(number, rented=False)

    recorded = await _post(
        f"/v1/admin/numbers/tenants/{tenant_id}/engine/record",
        {"e164": f"+{number}", "direction": "outbound", "agent_id": str(agent_id)},
        headers,
    )

    assert recorded.json()["platform_attachment"] == "applied"
    assert (vendor.numbers[number]["agent"], vendor.numbers[number]["callingAgent"]) == (
        None,
        ref,
    )


@pytest.mark.parametrize(
    ("released", "direction", "status", "ref", "archived", "wanted"),
    [
        (False, "inbound", "live", "ag_1", False, ("ag_1", None)),
        (False, "both", "live", "ag_1", False, ("ag_1", None)),
        (False, "outbound", "live", "ag_1", False, (None, "ag_1")),
        (True, "inbound", "live", "ag_1", False, (None, None)),
        (False, "inbound", "paused", "ag_1", False, (None, None)),
        (False, "inbound", "live", None, False, (None, None)),
        (False, "inbound", "live", "ag_1", True, (None, None)),
        (False, None, None, None, False, (None, None)),
    ],
)
def test_the_wanted_attachment_follows_our_binding(
    released: bool,
    direction: str | None,
    status: str | None,
    ref: str | None,
    archived: bool,
    wanted: tuple[str | None, str | None],
) -> None:
    assert (
        engine_numbers.wanted_attachment(
            released=released,
            direction=direction,
            status=status,
            engine_agent_ref=ref,
            archived=archived,
        )
        == wanted
    )


async def test_a_number_on_another_engine_is_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "fake")
    async with untenanted_session() as session:
        outcome = await engine_numbers.sync_number_attachment(session, number_id=uuid.uuid4())
    assert outcome == "not_applicable"


async def test_an_unreachable_platform_counts_as_refused_and_alarms(
    vendor: FakeVendor, alerts: list[tuple[str, dict[str, Any]]]
) -> None:
    _admin_id, headers = await _admin()
    tenant_id, agent_id, _ref = await _client_with_agent()
    number = _number()
    vendor.hold(number, rented=False)
    number_id = (
        await _post(
            f"/v1/admin/numbers/tenants/{tenant_id}/engine/record", {"e164": f"+{number}"}, headers
        )
    ).json()["number_id"]
    del vendor.numbers[number]  # the GET now answers 404

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET agent_id = :a WHERE id = :n"),
            {"a": agent_id, "n": number_id},
        )
        outcome = await engine_numbers.sync_number_attachment(
            session, number_id=uuid.UUID(number_id)
        )
    assert outcome == "refused"
    assert [code for code, _ in alerts] == ["engine_number_attachment_failed"]


# --- the daily reconciliation ------------------------------------------------------------


async def _only(monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID) -> None:
    """The directory narrowed to one client: the shared test database holds thousands."""

    async def _directory() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(engine_numbers, "live_tenants", _directory)


async def test_the_sweep_alarms_both_ways_repairs_drift_and_adopts_nothing(
    vendor: FakeVendor,
    alerts: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _admin_id, headers = await _admin()
    tenant_id, agent_id, ref = await _client_with_agent()
    await _only(monkeypatch, tenant_id)
    drifted, gone, stray = _number(), _number(), _number()
    for number in (drifted, gone):
        vendor.hold(number, rented=False)
        recorded = await _post(
            f"/v1/admin/numbers/tenants/{tenant_id}/engine/record",
            {"e164": f"+{number}", "agent_id": str(agent_id)},
            headers,
        )
        assert recorded.status_code == 201, recorded.text
    vendor.numbers[drifted]["agent"] = "ag_console_edit"
    del vendor.numbers[gone]
    vendor.hold(stray)
    vendor.business = {"status": "suspended", "canRent": False}

    summary = await number_rental.reconcile_engine_numbers({})

    assert vendor.numbers[drifted]["agent"] == ref
    codes = {code for code, _ in alerts}
    assert {
        "engine_number_unrecorded",
        "engine_number_missing_at_vendor",
        "engine_number_attachment_repaired",
        "engine_business_details_lapsed",
    } <= codes
    assert "'business_details': 'suspended'" in summary
    async with tenant_session(tenant_id) as session:
        adopted = (
            await session.execute(
                text("SELECT count(*) FROM phone_numbers WHERE engine_number_ref = :n"),
                {"n": stray},
            )
        ).scalar_one()
    assert adopted == 0


async def test_the_sweep_survives_an_unreadable_business_details_read(
    vendor: FakeVendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.core.errors import ProblemError

    async def _down() -> None:
        raise ProblemError.not_found("Business details")

    monkeypatch.setattr(number_rental, "read_business_details", _down)
    await _only(monkeypatch, uuid.uuid4())
    assert "'business_details': 'unreadable'" in await number_rental.reconcile_engine_numbers({})


# --- business details --------------------------------------------------------------------


async def test_the_business_details_status_is_shown_and_a_lapse_is_flagged(
    vendor: FakeVendor,
) -> None:
    _admin_id, headers = await _admin()
    vendor.business = {
        "status": "rejected",
        "businessName": "Sunrise Clinic Private Limited",
        "gstRegistered": True,
        "documentKind": "gst",
        "submittedAt": "2026-10-08T09:41:12.380Z",
        "reviewNote": "The name on the certificate does not match.",
        "canRent": False,
    }

    body = (await _get("/v1/admin/numbers/engine/business-details", headers)).json()

    assert body["available"] is True and body["platform"] == "ThinnestAI"
    assert (body["status"], body["can_rent"], body["lapsed"]) == ("rejected", False, True)
    assert body["review_note"] == "The name on the certificate does not match."
    assert body["submitted_at"].startswith("2026-10-08T09:41:12")

    vendor.business = {"status": "accepted", "canRent": True, "submittedAt": "not a time"}
    accepted = (await _get("/v1/admin/numbers/engine/business-details", headers)).json()
    assert (accepted["status"], accepted["lapsed"], accepted["submitted_at"]) == (
        "accepted",
        False,
        None,
    )
    vendor.business = {"status": "renamed_by_vendor"}
    assert (await _get("/v1/admin/numbers/engine/business-details", headers)).json()[
        "status"
    ] == "unknown"


async def test_the_business_details_read_is_empty_off_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _admin_id, headers = await _admin()
    monkeypatch.setattr(get_settings(), "engine", "fake")
    body = (await _get("/v1/admin/numbers/engine/business-details", headers)).json()
    assert body["available"] is False and body["status"] is None


async def test_a_rented_number_recorded_unpriced_is_priced_from_its_next_renewal(
    vendor: FakeVendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A number recorded by hand before recording priced it: the sweep prices it, and the
    period already under way is not charged (`rental_charged_from`, D-665's rule)."""
    from apps.api.billing.number_rental import today_ist

    admin_id, _headers = await _admin()
    await _attested(admin_id)
    tenant_id, _agent_id, _ref = await _client_with_agent()
    await _only(monkeypatch, tenant_id)
    number = _number()
    vendor.hold(number)
    number_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, provider, direction, "
                "dlt_status, engine_number_ref, engine_owned, created_at, updated_at) VALUES "
                "(:id, :tid, :e, 'standard', 'thinnest', 'both', 'pending', :ref, false, "
                "now() - interval '40 days', now())"
            ),
            {"id": number_id, "tid": tenant_id, "e": f"+{number}", "ref": number},
        )

    summary = await number_rental.reconcile_engine_numbers({})

    assert "'priced': 1" in summary
    async with tenant_session(tenant_id) as session:
        inr, owned, starts = (
            await session.execute(
                text(
                    "SELECT client_inr_per_month, engine_owned, rental_charged_from "
                    "FROM phone_numbers WHERE id = :id"
                ),
                {"id": number_id},
            )
        ).one()
    assert (inr, owned) == (PRICE, True)
    assert starts > today_ist()
    async with tenant_session(tenant_id) as session:
        assert not await engine_numbers.price_recorded_number(session, number_id=number_id)


@pytest.mark.parametrize(
    ("anchor", "today", "expected"),
    [
        ("2026-08-31", "2026-10-08", "2026-10-31"),
        ("2026-10-08", "2026-10-08", "2026-11-08"),
        ("2026-01-31", "2026-02-27", "2026-02-28"),
    ],
)
def test_the_next_renewal_is_the_first_period_start_after_today(
    anchor: str, today: str, expected: str
) -> None:
    from datetime import date

    assert engine_numbers._next_renewal(
        date.fromisoformat(anchor), date.fromisoformat(today)
    ) == date.fromisoformat(expected)
