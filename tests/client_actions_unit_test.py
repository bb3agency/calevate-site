"""Client in-call actions (D-700) — DB-free tests of the wire builders, the OAuth legs, the
executor's guards and the spoken answers.

Every vendor shape asserted here is the one cited in the module under test, read on the
vendor's own page on 9 Oct 2026; a change to a wire field fails here by name.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.actions import crm, execution, in_call, oauth, payment_links
from apps.api.actions import sheets as gsheets
from apps.api.actions.credentials import ResolvedCredential
from apps.api.actions.execution import CallFacts, ExecutionResult
from apps.api.actions.schema import (
    CrmConfig,
    CustomApiConfig,
    PaymentLinkConfig,
    SheetsConfig,
)
from apps.api.actions.service import LoadedTool
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.integrations import egress_guard
from pydantic import ValidationError

CALLER = "+919876500011"


def _tool(**kw: Any) -> LoadedTool:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "kind": "custom_api",
        "provider": None,
        "name": "look_up_order",
        "description": "Look up an order by its number.",
        "pre_call_message": None,
        "trigger": "during_call",
        "enabled": True,
        "credential_id": None,
        "config": {},
        "params": [],
    }
    base.update(kw)
    return LoadedTool(**base)


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _public(host: str, port: int) -> tuple[str, ...]:
        return ("142.250.183.10",)

    monkeypatch.setattr(egress_guard, "resolve_addresses", _public)


def _cred(secret: str, kind: str, **non_secret: Any) -> Any:
    async def _resolve(session: Any, *, tenant_id: Any, credential_id: Any) -> ResolvedCredential:
        return ResolvedCredential(kind=kind, secret=secret, non_secret=non_secret, version=1)

    return _resolve


# --- schema ---------------------------------------------------------------------------


def test_a_custom_api_must_be_https() -> None:
    with pytest.raises(ValidationError):
        CustomApiConfig(url="http://api.shop.example/orders")
    assert CustomApiConfig(url="https://api.shop.example/orders").url.startswith("https://")


def _payment(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "max_amount_inr": "5000",
        "description": "Consultation fee",
        "message": {
            "provider": "aisensy",
            "credential_id": str(uuid.uuid4()),
            "template": "payment_link",
            "body_values": ["amount", "link"],
        },
    }
    base.update(kw)
    return base


def test_a_payment_link_needs_exactly_one_amount_source_inside_its_range() -> None:
    with pytest.raises(ValidationError):
        PaymentLinkConfig.model_validate(_payment())
    with pytest.raises(ValidationError):
        PaymentLinkConfig.model_validate(_payment(fixed_amount_inr="10", amount_param="amount"))
    with pytest.raises(ValidationError):
        PaymentLinkConfig.model_validate(_payment(fixed_amount_inr="9000"))
    ok = PaymentLinkConfig.model_validate(_payment(fixed_amount_inr="499.50"))
    assert ok.fixed_amount_inr == Decimal("499.50")


def test_a_payment_message_must_carry_the_link() -> None:
    bad = _payment(fixed_amount_inr="10")
    bad["message"]["body_values"] = ["amount"]
    with pytest.raises(ValidationError):
        PaymentLinkConfig.model_validate(bad)


def test_sheet_operations_need_their_fields() -> None:
    with pytest.raises(ValidationError):
        SheetsConfig(operation="record", spreadsheet_id="a" * 44, worksheet="Calls")
    with pytest.raises(ValidationError):
        SheetsConfig(operation="lookup", spreadsheet_id="a" * 44, worksheet="Calls")
    with pytest.raises(ValidationError):
        SheetsConfig(
            operation="lookup",
            spreadsheet_id="../../etc",
            worksheet="Calls",
            match_header="Phone",
            return_headers=["Name"],
        )


# --- Razorpay ---------------------------------------------------------------------------


def test_rupees_become_whole_paise_without_a_float() -> None:
    assert payment_links.paise(Decimal("499.50")) == 49950
    assert payment_links.paise(Decimal("0.995")) == 100
    assert payment_links.paise(Decimal("1")) == 100


def test_the_payment_link_request_is_the_documented_shape() -> None:
    now = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    req = payment_links.create_link(
        key_id="rzp_test_abc",
        key_secret="sekrit",
        amount_inr=Decimal("250"),
        description="Consultation fee",
        reference_id="cv-" + "x" * 60,
        contact_e164=CALLER,
        expire_minutes=60,
        now=now,
    )
    assert req.method == "POST"
    assert req.url == "https://api.razorpay.com/v1/payment_links/"
    assert req.headers["Authorization"].startswith("Basic ")
    body = req.json_body
    assert body is not None
    assert body["amount"] == 25000 and body["currency"] == "INR"
    assert len(str(body["reference_id"])) == 40
    assert body["notify"] == {"sms": False, "email": False}
    assert body["customer"] == {"contact": CALLER}
    assert body["expire_by"] == int((now + timedelta(minutes=60)).timestamp())


# --- the CRMs ---------------------------------------------------------------------------


def test_zoho_upsert_matches_on_phone_and_uses_the_zoho_token_scheme() -> None:
    req = crm.zoho_upsert(
        api_domain="https://www.zohoapis.in", token="tok", module="Leads", record={"Phone": CALLER}
    )
    assert req.url == "https://www.zohoapis.in/crm/v8/Leads/upsert"
    assert req.headers["Authorization"] == "Zoho-oauthtoken tok"
    assert req.json_body == {"data": [{"Phone": CALLER}], "duplicate_check_fields": ["Phone"]}


def test_a_zoho_api_domain_outside_zoho_is_refused() -> None:
    assert crm.zoho_api_domain("https://www.zohoapis.in") == "https://www.zohoapis.in"
    assert crm.zoho_api_domain("https://evil.example") is None
    assert crm.zoho_api_domain("http://www.zohoapis.in") is None


def test_hubspot_search_drops_the_country_code() -> None:
    req = crm.hubspot_search(token="tok", phone_e164=CALLER)
    assert req.url == "https://api.hubapi.com/crm/objects/2026-09/contacts/search"
    body = req.json_body
    assert body is not None
    flt = body["filterGroups"][0]["filters"][0]  # type: ignore[index]
    assert flt == {"propertyName": "phone", "operator": "EQ", "value": "9876500011"}


# --- OAuth ------------------------------------------------------------------------------


@pytest.fixture
def oauth_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    for prefix in ("google", "zoho", "hubspot"):
        monkeypatch.setattr(s, f"{prefix}_oauth_client_id", f"{prefix}-id")
        monkeypatch.setattr(s, f"{prefix}_oauth_client_secret", f"{prefix}-secret")
        monkeypatch.setattr(s, f"{prefix}_oauth_redirect_uri", f"https://app.test/oauth/{prefix}")


def test_each_consent_url_asks_for_offline_access_with_its_own_scopes(oauth_apps: None) -> None:
    google = oauth.authorize_url("google_calendar", state="s")
    zoho = oauth.authorize_url("zoho_crm", state="s")
    hubspot = oauth.authorize_url("hubspot", state="s")
    assert google.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in google and "prompt=consent" in google
    assert zoho.startswith("https://accounts.zoho.in/oauth/v2/auth?")
    assert "ZohoSearch.securesearch.READ" in zoho and "access_type=offline" in zoho
    assert hubspot.startswith("https://app.hubspot.com/oauth/authorize?")
    assert "crm.objects.contacts.write" in hubspot


def test_our_secret_goes_only_to_a_zoho_accounts_server(oauth_apps: None) -> None:
    good = oauth.exchange_request("zoho_crm", code="c", accounts_server="https://accounts.zoho.eu")
    assert good.url == "https://accounts.zoho.eu/oauth/v2/token"
    forged = oauth.exchange_request("zoho_crm", code="c", accounts_server="https://evil.example")
    assert forged.url == "https://accounts.zoho.in/oauth/v2/token"


def test_a_state_for_one_provider_does_not_complete_another(oauth_apps: None) -> None:
    tenant, user = uuid.uuid4(), uuid.uuid4()
    state = oauth.mint_state("zoho_crm", tenant_id=tenant, user_id=user)
    oauth.verify_state(
        "zoho_crm", state, tenant_id=tenant, user_id=user, refusal=oauth.state_refused("zoho_crm")
    )
    with pytest.raises(ProblemError):
        oauth.verify_state(
            "hubspot", state, tenant_id=tenant, user_id=user, refusal=oauth.state_refused("hubspot")
        )
    with pytest.raises(ProblemError):
        oauth.verify_state(
            "zoho_crm",
            state,
            tenant_id=tenant,
            user_id=uuid.uuid4(),
            refusal=oauth.state_refused("zoho_crm"),
        )


def test_an_unregistered_app_is_refused_in_the_clients_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "hubspot_oauth_client_id", None)
    assert oauth.configured("hubspot") is False
    with pytest.raises(ProblemError) as caught:
        oauth.authorize_url("hubspot", state="s")
    assert caught.value.code == "hubspot_not_configured"


# --- the executor -----------------------------------------------------------------------


def test_free_slots_skip_busy_time_and_respect_the_exclusive_end() -> None:
    start = datetime(2027, 1, 4, 10, 0, tzinfo=UTC)
    busy = [(start, start + timedelta(minutes=30))]
    slots = execution.free_slots(
        window_start=start, window_end=start + timedelta(hours=2), minutes=30, busy=busy
    )
    assert slots[0] == start + timedelta(minutes=30)
    assert len(slots) == execution.FREE_SLOTS_OFFERED


def test_a_slot_is_spoken_in_india_time() -> None:
    at = datetime(2027, 1, 4, 10, 30, tzinfo=UTC)
    assert execution.spoken_time(at) == "Monday 4 January, 4:00 PM"


def test_what_the_model_reads_is_redacted() -> None:
    out = execution.for_model({"note": "call me on 9876543210 or ravi@example.com", "n": 3})
    assert "9876543210" not in out["note"] and "ravi@example.com" not in out["note"]
    assert out["n"] == 3


async def test_a_redirect_is_reported_not_followed(public_dns: None) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest"})

    tool = _tool(
        config=CustomApiConfig(method="GET", url="https://api.shop.example/x").model_dump()
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execution.execute_action(
            object(),  # type: ignore[arg-type]
            tool=tool,
            received={},
            source="test",
            client=client,
            audit=False,
        )
    assert seen == ["https://api.shop.example/x"]
    assert result.status == "http_302"


async def test_a_huge_answer_is_read_only_to_the_cap(public_dns: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (execution.MAX_RESPONSE_BYTES * 4))

    tool = _tool(
        config=CustomApiConfig(method="GET", url="https://api.shop.example/x").model_dump()
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execution.execute_action(
            object(),  # type: ignore[arg-type]
            tool=tool,
            received={},
            source="test",
            client=client,
            audit=False,
        )
    assert result.ok is True
    assert len(json.dumps(result.payload)) <= execution.MAX_ANSWER_CHARS + 100


async def test_a_slow_action_answers_within_the_budget(public_dns: None) -> None:
    import asyncio

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    tool = _tool(
        config=CustomApiConfig(method="GET", url="https://api.shop.example/x").model_dump()
    )
    loop = asyncio.get_running_loop()
    started = loop.time()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execution.execute_action(
            object(),  # type: ignore[arg-type]
            tool=tool,
            received={},
            source="in_call",
            client=client,
            audit=False,
            budget_s=0.2,
        )
    assert result.status == "timeout"
    assert loop.time() - started < 1.0


async def test_a_lead_variable_is_ours_not_the_models(public_dns: None) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    tool = _tool(
        config=CustomApiConfig(
            method="POST",
            url="https://api.shop.example/leads",
            body=[{"key": "phone", "param": "caller"}],
        ).model_dump(),
        params=[{"name": "caller", "source": "lead_var", "lead_var": "caller_phone"}],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await execution.execute_action(
            object(),  # type: ignore[arg-type]
            tool=tool,
            received={"caller": "+910000000000"},
            source="in_call",
            client=client,
            audit=False,
            call=CallFacts(call_ref="in_1", caller_e164=CALLER, direction="inbound"),
        )
    assert json.loads(seen[0].content) == {"phone": CALLER}


async def test_crm_push_creates_a_zoho_lead_matched_on_the_callers_number(
    public_dns: None, oauth_apps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution.reset_access_cache()
    monkeypatch.setattr(
        execution,
        "resolve_credential",
        _cred("refresh", "zoho_crm", api_domain="https://www.zohoapis.in", accounts_server=""),
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(
                200, json={"access_token": "at", "api_domain": "https://www.zohoapis.in"}
            )
        return httpx.Response(
            200, json={"data": [{"code": "SUCCESS", "action": "insert", "details": {"id": "1"}}]}
        )

    tool = _tool(
        kind="crm",
        provider="zoho",
        credential_id=uuid.uuid4(),
        config=CrmConfig(
            module="Leads", fields=[{"crm_field": "First_Name", "param": "name"}]
        ).model_dump(),
        params=[{"name": "name", "source": "ai", "description": "The caller's first name"}],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execution.execute_action(
            object(),  # type: ignore[arg-type]
            tool=tool,
            received={"name": "Ravi"},
            source="background",
            client=client,
            audit=False,
            call=CallFacts(call_ref="in_1", caller_e164=CALLER, direction="inbound"),
        )
    assert result.status == "crm_saved"
    upsert = json.loads(seen[-1].content)
    assert upsert["data"][0] == {
        "Last_Name": crm.UNNAMED_CALLER,
        "First_Name": "Ravi",
        "Phone": CALLER,
    }
    assert seen[-1].headers["Authorization"] == "Zoho-oauthtoken at"


async def test_a_deleted_connection_is_a_spoken_cannot_not_a_crash(
    public_dns: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _gone(session: Any, *, tenant_id: Any, credential_id: Any) -> None:
        return None

    monkeypatch.setattr(execution, "resolve_credential", _gone)
    tool = _tool(
        kind="crm", provider="hubspot", credential_id=uuid.uuid4(), config={"module": "contacts"}
    )
    result = await execution.execute_action(
        object(),  # type: ignore[arg-type]
        tool=tool,
        received={},
        source="in_call",
        audit=False,
        call=CallFacts(call_ref="in_1", caller_e164=CALLER),
    )
    assert result.status == "no_credential"
    assert in_call.say_for(result) == in_call.NOT_AVAILABLE_SAY
    assert "Do NOT tell the caller it is done" in in_call.say_for(result)


def test_every_success_and_known_refusal_has_platform_words() -> None:
    for status in ("delivered", "link_sent", "booked", "checked", "found", "not_found"):
        assert in_call.say_for(ExecutionResult(ok=True, payload={}, status=status))
    for status in ("not_opted_in", "slot_taken", "trial_payment_links", "amount_outside_rules"):
        said = in_call.say_for(ExecutionResult(ok=False, payload={}, status=status))
        assert said != in_call.NOT_AVAILABLE_SAY


def test_a_crm_push_and_a_sheet_row_run_in_the_background() -> None:
    assert in_call.runs_in_background(
        _tool(kind="crm", provider="zoho", config={"module": "Leads"})
    )
    record = SheetsConfig(
        operation="record",
        spreadsheet_id="a" * 44,
        worksheet="Calls",
        columns=[{"header": "Name", "param": "name"}],
    ).model_dump()
    lookup = SheetsConfig(
        operation="lookup",
        spreadsheet_id="a" * 44,
        worksheet="Calls",
        match_header="Phone",
        return_headers=["Name"],
    ).model_dump()
    assert in_call.runs_in_background(_tool(kind="sheets", config=record))
    assert not in_call.runs_in_background(_tool(kind="sheets", config=lookup))
    assert not in_call.runs_in_background(_tool(kind="calendar"))


def test_a_sheet_row_is_matched_on_the_last_ten_digits() -> None:
    rows = [["Name", "Phone"], ["Asha", "98765 00012"], ["Ravi", "+91-98765-00011"]]
    assert gsheets.find_row(rows, column=1, phone_e164=CALLER) == 2
    assert gsheets.find_row(rows, column=1, phone_e164="+911234") is None


# --- caller lookup before the dial ------------------------------------------------------


def test_a_found_caller_becomes_the_calls_name_and_variables() -> None:
    from apps.api.actions import pre_dial

    found = pre_dial.prefill_from(
        {
            "found": True,
            "details": {"First_Name": "Ravi", "Last_Name": "Kumar", "Lead_Status": "Hot"},
        }
    )
    assert found.name == "Ravi Kumar"
    assert found.variables[pre_dial.CALLER_NAME_VARIABLE] == "Ravi Kumar"
    assert "Lead_Status: Hot" in found.variables[pre_dial.CALLER_DETAILS_VARIABLE]
    assert all(len(v) <= pre_dial.VARIABLE_MAX for v in found.variables.values())
    assert pre_dial.prefill_from({"found": False}) == pre_dial.CallerPrefill()


async def test_the_dial_waits_for_no_lookup_when_the_agent_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.actions import pre_dial

    async def _none(session: Any, *, agent_id: Any) -> list[LoadedTool]:
        return [_tool(kind="calendar")]

    monkeypatch.setattr(pre_dial, "in_call_tools", _none)
    got = await pre_dial.pre_dial_lookup(
        object(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        phone_e164=CALLER,
    )
    assert got == pre_dial.CallerPrefill()
