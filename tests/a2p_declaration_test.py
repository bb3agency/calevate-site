"""The calling-number declaration (D-941): the record, the date that arms it, and the gate.

TCCCPR amendment of 18 Sep 2026, new reg 4: an automated call from a number not declared in
advance to the originating access provider is unsolicited commercial communication, from
about 17 Nov 2026 (`docs/research/research_notes/Calevate market and technology edge/
india_regulation.md`; Gazette date not verified, hence the live setting).

Pinned here: nothing is refused before `a2p_declaration_enforced_from`; from it every
outbound voice dial needs a live declaration covering every number the agent can present;
an owner's test call to their own number, a WhatsApp send and inbound are untouched; every
outbound path reaches the gate; the record is tenant-isolated and append-only.
"""

from __future__ import annotations

import ast
import hashlib
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from apps.api.announcements.service import active_for
from apps.api.campaigns import service as campaigns
from apps.api.compliance import autodialer
from apps.api.compliance.autodialer import (
    A2P_DECLARATION_MISSING_REASON,
    A2P_DECLARATION_MISSING_RULE,
    A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE,
    A2P_NUMBER_UNDECLARED_RULE,
    A2P_TEST_CALL_OWN_NUMBER_RULE,
    DECLARATION_TEXT_SHA256,
    DECLARATION_VERSION,
    a2p_dial_blocker,
    declared_cli,
    read_declaration,
    record_declaration,
)
from apps.api.compliance.service import DispatchDecision, check_dispatch
from apps.api.core import platform_config
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.legal.readiness import a2p_readiness_row, readiness_rows
from apps.api.main import app
from calevate_shared.config import Settings
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.outbound_consent_policy_test import _fresh_phone, _tenant

pytestmark = pytest.mark.rls

PATH = "/v1/compliance/autodialer-notice"
BEFORE = date(2026, 11, 16)
ENFORCED = date(2026, 11, 17)
#: 11:00 IST, so the calling-hours rule is never what refuses.
_PINNED_IST = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _PINNED_IST)


def _today(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    monkeypatch.setattr(autodialer, "ist_today", lambda: day)


async def _member(tenant_id: uuid.UUID, role: str = "owner") -> uuid.UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": user_id, "e": f"{user_id}@example.test"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, :r, now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": user_id, "r": role},
        )
    return user_id


async def _agent_numbers(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        return await autodialer.agent_calling_numbers(session, agent_id=agent_id)


async def _declare(
    tenant_id: uuid.UUID,
    numbers: list[str],
    *,
    notified_on: date = date(2026, 10, 1),
    withdraw: bool = False,
) -> uuid.UUID:
    user_id = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        return await record_declaration(
            session,
            tenant_id=tenant_id,
            notified_on=notified_on,
            recorded_by=user_id,
            attestation_version=DECLARATION_VERSION,
            attestation_sha256=DECLARATION_TEXT_SHA256,
            declared_clis=numbers,
            withdraw=withdraw,
        )


# --- the attestation (D-941 amended 30 Oct 2026) -------------------------------------------

_V2_TEXT = (
    "On behalf of this business I confirm that our agents place automated calls only from "
    "the numbers listed, and I authorise Calevate to declare these numbers to the telephone "
    "company on our behalf. We will add any new number here before it places an automated "
    "call."
)


def test_the_attestation_is_version_2_the_authorisation_and_its_hash_is_pinned() -> None:
    """The client authorises us to declare; it no longer swears it declared them itself."""
    assert DECLARATION_VERSION == 2
    assert autodialer.DECLARATION_TEXT == _V2_TEXT
    assert hashlib.sha256(_V2_TEXT.encode("utf-8")).hexdigest() == DECLARATION_TEXT_SHA256
    assert "on the date shown" not in autodialer.DECLARATION_TEXT


async def _version_1_row(tenant_id: uuid.UUID, numbers: list[str]) -> None:
    user_id = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO autodialer_notices (id, tenant_id, state, notified_on, "
                "notice_reference, declared_clis, recorded_by, attestation_version, "
                "attestation_sha256) VALUES (:id, :t, 'notified', '2026-10-01', 'OAP-1', :c, "
                ":u, 1, :sha)"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "c": numbers, "u": user_id, "sha": "b" * 64},
        )


async def test_a_version_1_row_covers_no_dial_and_the_screen_asks_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-v1")
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _version_1_row(tenant_id, numbers)
    assert (await _gate(tenant_id, agent_id)).rule == A2P_DECLARATION_MISSING_RULE
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        body = (await http.get(PATH, headers=headers)).json()
    assert body["recorded"] is True
    assert body["attested"] is False
    assert body["attested_version"] == 1
    assert body["effective"] is False
    assert body["undeclared_clis"] == numbers
    assert body["blocker"]["rule"] == A2P_DECLARATION_MISSING_RULE

    # Confirming once more on version 2 covers the same numbers.
    await _declare(tenant_id, numbers)
    assert (await _gate(tenant_id, agent_id)).allowed is True


async def test_a_version_1_row_does_not_carry_numbers_under_a_later_dated_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-v1-carry")
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _version_1_row(tenant_id, numbers)
    await _declare(tenant_id, numbers, notified_on=date(2026, 11, 20))
    assert (await _gate(tenant_id, agent_id)).rule == A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE


async def _gate(tenant_id: uuid.UUID, agent_id: uuid.UUID, **kwargs: Any) -> DispatchDecision:
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=_fresh_phone(), **kwargs
        )


# --- the enforcement date ------------------------------------------------------------------


async def test_before_the_date_an_undeclared_account_still_dials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, BEFORE)
    tenant_id, agent_id = await _tenant("a2p-before")
    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is True, decision.rule


async def test_from_the_date_an_undeclared_account_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-missing")
    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is False
    assert decision.rule == A2P_DECLARATION_MISSING_RULE
    assert decision.reason == A2P_DECLARATION_MISSING_REASON


async def test_the_date_is_the_live_setting_not_a_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Moving the setting later re-opens calling on a day that would otherwise refuse."""
    _today(monkeypatch, ENFORCED)
    later = Settings().model_copy(update={"a2p_declaration_enforced_from": date(2026, 12, 1)})
    monkeypatch.setattr(autodialer, "get_settings", lambda: later)
    tenant_id, agent_id = await _tenant("a2p-moved")
    assert (await _gate(tenant_id, agent_id)).allowed is True


def test_the_setting_defaults_to_17_nov_and_refuses_a_day_that_does_not_exist() -> None:
    assert Settings().a2p_declaration_enforced_from == date(2026, 11, 17)
    assert platform_config.validate_value("a2p_declaration_enforced_from", "2026-12-01") == (
        "2026-12-01"
    )
    with pytest.raises(ValidationError):
        platform_config.validate_value("a2p_declaration_enforced_from", "2026-02-30")


def test_the_config_bounds_gate_accepts_a_calendar_day_as_bounded() -> None:
    """`scripts/check_config_applies` is a CI gate; a date field is bounded by its format."""
    from scripts import check_config_applies

    assert check_config_applies._unbounded_reason("a2p_declaration_enforced_from") is None


# --- declared and undeclared numbers -------------------------------------------------------


async def test_a_declaration_covering_the_agents_number_lets_the_dial_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-covered")
    numbers = await _agent_numbers(tenant_id, agent_id)
    assert numbers, "the fixture binds one number to the agent"
    await _declare(tenant_id, numbers)
    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is True, decision.rule


async def test_a_number_missing_from_the_declaration_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-other")
    await _declare(tenant_id, ["+919848022338"])
    decision = await _gate(tenant_id, agent_id)
    assert decision.rule == A2P_NUMBER_UNDECLARED_RULE


async def test_an_agent_with_no_number_cannot_show_a_declared_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-none")
    await _declare(tenant_id, await _agent_numbers(tenant_id, agent_id))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET agent_id = NULL WHERE agent_id = :a"), {"a": agent_id}
        )
    assert (await _gate(tenant_id, agent_id)).rule == A2P_NUMBER_UNDECLARED_RULE


async def test_a_future_dated_declaration_counts_from_its_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-future")
    await _declare(
        tenant_id, await _agent_numbers(tenant_id, agent_id), notified_on=date(2026, 11, 20)
    )
    decision = await _gate(tenant_id, agent_id)
    assert decision.rule == A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE
    assert decision.reason is not None and "2026-11-20" in decision.reason


async def test_a_future_dated_addition_keeps_the_numbers_already_declared_calling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adding a number declared next week must not stop the number declared last month."""
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-addition")
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _declare(tenant_id, numbers)
    await _declare(tenant_id, [*numbers, "+919848022338"], notified_on=date(2026, 11, 20))
    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is True, decision.rule


async def test_a_future_dated_row_carries_nothing_past_a_withdrawal_or_a_dropped_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-carry-stops")
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _declare(tenant_id, numbers)
    await _declare(tenant_id, [], withdraw=True)
    await _declare(tenant_id, numbers, notified_on=date(2026, 11, 20))
    assert (await _gate(tenant_id, agent_id)).rule == A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE

    tenant_id, agent_id = await _tenant("a2p-carry-dropped")
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _declare(tenant_id, numbers)
    await _declare(tenant_id, ["+919848022338"], notified_on=date(2026, 11, 20))
    assert (await _gate(tenant_id, agent_id)).rule == A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE


async def test_a_withdrawal_is_a_new_row_and_stops_the_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-withdrawn")
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _declare(tenant_id, numbers)
    await _declare(tenant_id, [], withdraw=True)
    assert (await _gate(tenant_id, agent_id)).rule == A2P_DECLARATION_MISSING_RULE
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(text("SELECT count(*) FROM autodialer_notices"))
        ).scalar_one()
    assert count == 2


async def test_a_d637_notice_without_an_attestation_covers_no_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-legacy")
    user_id = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO autodialer_notices (id, tenant_id, state, access_provider, "
                "objective, notified_on, declared_clis, recorded_by) VALUES "
                "(:id, :t, 'notified', 'Airtel', 'Reminders', '2026-09-01', :c, :u)"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "c": await autodialer.agent_calling_numbers(session, agent_id=agent_id),
                "u": user_id,
            },
        )
    assert (await _gate(tenant_id, agent_id)).rule == A2P_DECLARATION_MISSING_RULE


# --- what is never gated -------------------------------------------------------------------


async def test_whatsapp_is_not_a_call_and_is_not_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-wa")
    decision = await _gate(tenant_id, agent_id, places_call=False)
    assert decision.rule not in {A2P_DECLARATION_MISSING_RULE, A2P_NUMBER_UNDECLARED_RULE}


async def test_an_owners_test_call_to_their_own_number_is_exempt_and_any_other_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-test")
    async with tenant_session(tenant_id) as session:
        own = await a2p_dial_blocker(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            trial_call=True,
            own_number_attested=True,
        )
        other = await a2p_dial_blocker(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            trial_call=True,
            own_number_attested=False,
        )
    assert own is None
    assert other is not None and other[0] == A2P_TEST_CALL_OWN_NUMBER_RULE


async def test_inbound_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """An answering-only account has nothing to declare and is never told to; an inbound
    agent is refused a dial for being inbound, never for the declaration."""
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-inbound")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE tenant_id = :t"), {"t": tenant_id}
        )
        assert await autodialer.outbound_in_use(session) is False
        assert await a2p_readiness_row(session, tenant_id=tenant_id) is None
    assert (await _gate(tenant_id, agent_id)).rule == "agent_inbound_only"


# --- every outbound path goes through it ---------------------------------------------------


_MESSAGING_CALLERS = {
    "apps/api/actions/whatsapp.py",
    "apps/workers/whatsapp.py",
    "apps/workers/forwarding.py",
}


def test_only_messaging_paths_skip_the_declaration() -> None:
    """Every `check_dispatch` call site asks the declaration, except the three that send a
    WhatsApp message. Campaign dispatch, new-lead calls, call-backs, the CRM call button,
    the swipe and Pip's dial and test-call plans are all in the first set by construction."""
    root = Path(__file__).resolve().parents[1]
    skipping: set[str] = set()
    callers: set[str] = set()
    for path in [*root.joinpath("apps").rglob("*.py")]:
        relative = path.relative_to(root).as_posix()
        if relative.endswith("_test.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "check_dispatch"
            ):
                callers.add(relative)
                for keyword in node.keywords:
                    if keyword.arg == "places_call":
                        skipping.add(relative)
    assert skipping == _MESSAGING_CALLERS
    assert {
        "apps/workers/campaign_dispatch.py",
        "apps/api/ingest/service.py",
        "apps/workers/callbacks.py",
        "apps/api/crm/lead_dial.py",
        "apps/api/copilot/console_actions.py",
        "apps/api/agents/trial_calls.py",
    } <= callers - skipping


async def test_a_campaign_launch_names_the_refusal_the_dials_would_meet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-launch")
    async with tenant_session(tenant_id) as session:
        campaign_id = (
            await session.execute(
                text(
                    "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, "
                    "classification, created_at, updated_at) VALUES (gen_random_uuid(), :t, "
                    ":a, 'Reminders', 'draft', 'service', now(), now()) RETURNING id"
                ),
                {"t": tenant_id, "a": agent_id},
            )
        ).scalar_one()
        blockers = await campaigns.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert A2P_DECLARATION_MISSING_RULE in {b.rule for b in blockers}


# --- readiness, before and after -----------------------------------------------------------


async def test_readiness_lists_the_declaration_as_due_before_the_date_and_blocking_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.loadshed import PlatformStatus

    platform = PlatformStatus(mode="normal", outbound_halted=False)
    tenant_id, _agent = await _tenant("a2p-ready")
    _today(monkeypatch, BEFORE)
    async with tenant_session(tenant_id) as session:
        due = await a2p_readiness_row(session, tenant_id=tenant_id)
        rows = await readiness_rows(session, tenant_id=tenant_id, platform=platform)
    assert due is not None and due[1] is False
    assert due[0].title == "Confirm your calling numbers before 17 Nov"
    assert A2P_DECLARATION_MISSING_RULE not in {r.rule for r in rows}

    _today(monkeypatch, ENFORCED)
    async with tenant_session(tenant_id) as session:
        rows = await readiness_rows(session, tenant_id=tenant_id, platform=platform)
    assert A2P_DECLARATION_MISSING_RULE in {r.rule for r in rows}


# --- the record ----------------------------------------------------------------------------


def test_a_header_and_a_mobile_normalise_and_junk_is_refused() -> None:
    assert declared_cli("98480 22338") == "+919848022338"
    assert declared_cli("+91 98480 22338") == "+919848022338"
    assert declared_cli("not a number") is None
    # A bare 140-series header is accepted as issued, which `normalize_phone` alone refuses.
    assert declared_cli("1401234567") == "+911401234567"


async def test_numbers_are_kept_once_in_the_order_given_and_cover_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, ENFORCED)
    tenant_id, agent_id = await _tenant("a2p-dedupe")
    numbers = await _agent_numbers(tenant_id, agent_id)
    await _declare(tenant_id, [*numbers, numbers[0], "+919848022338"])
    async with tenant_session(tenant_id) as session:
        declaration = await read_declaration(session, tenant_id=tenant_id)
        assert declaration.declared_clis == (*numbers, "+919848022338")
        assert await a2p_readiness_row(session, tenant_id=tenant_id) is None


async def test_the_health_board_warns_before_the_date_and_stops_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.admin.health import _declaration_signal

    tenant_id, agent_id = await _tenant("a2p-board")
    _today(monkeypatch, BEFORE)
    async with tenant_session(tenant_id) as session:
        warned = await _declaration_signal(session, tenant_id=tenant_id)
    _today(monkeypatch, ENFORCED)
    async with tenant_session(tenant_id) as session:
        stopped = await _declaration_signal(session, tenant_id=tenant_id)
    assert warned is not None and warned.severity == "warn"
    assert warned.rule == "calling_numbers_undeclared"
    assert warned.causes == (A2P_DECLARATION_MISSING_RULE,)
    assert stopped is not None and stopped.severity == "stop"

    await _declare(tenant_id, await _agent_numbers(tenant_id, agent_id))
    async with tenant_session(tenant_id) as session:
        assert await _declaration_signal(session, tenant_id=tenant_id) is None


async def test_an_operator_in_view_as_cannot_declare_for_the_client() -> None:
    from types import SimpleNamespace

    from apps.api.compliance.autodialer_routes import CallingNumberDeclarationIn, record_notice
    from starlette.requests import Request

    tenant_id, _agent = await _tenant("a2p-viewas")
    principal: Any = SimpleNamespace(tenant_id=tenant_id, client_user_id=None)
    body = CallingNumberDeclarationIn(
        declared_clis=["+919848022338"],
        attestation_version=DECLARATION_VERSION,
        attestation_sha256=DECLARATION_TEXT_SHA256,
    )
    request = Request({"type": "http", "method": "POST", "path": PATH, "headers": []})
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await record_notice(body, request, session, principal)
    assert refused.value.code == "a2p_declaration_is_the_senders_own_act"


async def test_a_stale_attestation_and_an_empty_list_are_refused() -> None:
    tenant_id, _agent = await _tenant("a2p-stale")
    user_id = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as stale:
            await record_declaration(
                session,
                tenant_id=tenant_id,
                notified_on=date(2026, 10, 1),
                recorded_by=user_id,
                attestation_version=DECLARATION_VERSION,
                attestation_sha256="0" * 64,
                declared_clis=["+919848022338"],
            )
        assert stale.value.code == "a2p_declaration_version_stale"
        with pytest.raises(ProblemError) as empty:
            await record_declaration(
                session,
                tenant_id=tenant_id,
                notified_on=date(2026, 10, 1),
                recorded_by=user_id,
                attestation_version=DECLARATION_VERSION,
                attestation_sha256=DECLARATION_TEXT_SHA256,
                declared_clis=[" "],
            )
        assert empty.value.code == "a2p_declaration_numbers_missing"
        with pytest.raises(ProblemError) as junk:
            await record_declaration(
                session,
                tenant_id=tenant_id,
                notified_on=date(2026, 10, 1),
                recorded_by=user_id,
                attestation_version=DECLARATION_VERSION,
                attestation_sha256=DECLARATION_TEXT_SHA256,
                declared_clis=["call me"],
            )
        assert junk.value.code == "a2p_declaration_number_invalid"
        with pytest.raises(ProblemError) as many:
            await record_declaration(
                session,
                tenant_id=tenant_id,
                notified_on=date(2026, 10, 1),
                recorded_by=user_id,
                attestation_version=DECLARATION_VERSION,
                attestation_sha256=DECLARATION_TEXT_SHA256,
                declared_clis=[f"+91984802{n:04d}" for n in range(21)],
            )
        assert many.value.code == "a2p_declaration_numbers_too_many"
        with pytest.raises(ProblemError) as old_version:
            await record_declaration(
                session,
                tenant_id=tenant_id,
                recorded_by=user_id,
                attestation_version=1,
                attestation_sha256=DECLARATION_TEXT_SHA256,
                declared_clis=["+919848022338"],
            )
        assert old_version.value.code == "a2p_declaration_version_stale"


async def test_the_record_is_tenant_isolated() -> None:
    tenant_a, _ = await _tenant("a2p-rls-a")
    tenant_b, _ = await _tenant("a2p-rls-b")
    await _declare(tenant_a, ["+919848022338"])
    async with tenant_session(tenant_b) as session:
        seen = (await session.execute(text("SELECT count(*) FROM autodialer_notices"))).scalar_one()
        assert seen == 0
        assert (await read_declaration(session, tenant_id=tenant_a)).recorded is False


async def test_the_record_is_append_only() -> None:
    tenant_id, _ = await _tenant("a2p-append")
    row_id = await _declare(tenant_id, ["+919848022338"])
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE autodialer_notices SET notice_reference = 'x' WHERE id = :i"),
                {"i": row_id},
            )
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("DELETE FROM autodialer_notices WHERE id = :i"), {"i": row_id}
            )


# --- the route and the announcement --------------------------------------------------------


async def _org_headers(tenant_id: uuid.UUID, role: str = "owner") -> dict[str, str]:
    async with tenant_session(tenant_id) as session:
        slug = (
            await session.execute(
                text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    user_id = await _member(tenant_id, role)
    return {"Authorization": f"Bearer dev:client:{user_id}", "X-Org-Slug": str(slug)}


async def test_the_route_reads_prefills_and_records_and_the_gate_agrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _today(monkeypatch, BEFORE)
    tenant_id, agent_id = await _tenant("a2p-route")
    numbers = await _agent_numbers(tenant_id, agent_id)
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        readiness = (await http.get("/v1/legal/readiness", headers=headers)).json()
        assert [row["rule"] for row in readiness["upcoming"]] == [A2P_DECLARATION_MISSING_RULE]
        assert A2P_DECLARATION_MISSING_RULE not in {row["rule"] for row in readiness["blockers"]}
        before = (await http.get(PATH, headers=headers)).json()
        assert before["recorded"] is False
        assert before["applies"] is True
        assert before["enforced"] is False
        assert before["enforced_from"] == "2026-11-17"
        assert before["rented_numbers"] == numbers
        assert before["undeclared_clis"] == numbers
        assert before["blocker"]["rule"] == A2P_DECLARATION_MISSING_RULE

        assert before["attestation_version"] == 2
        assert "notice_reference" not in before

        stale = await http.post(
            PATH,
            headers=headers,
            json={
                "declared_clis": numbers,
                "attestation_version": before["attestation_version"],
                "attestation_sha256": "0" * 64,
            },
        )
        assert stale.status_code == 422, stale.text

        # The client files nothing itself, so it gives no date and no reference.
        for extra in ({"notified_on": "2026-10-30"}, {"notice_reference": "OAP-1"}):
            refused = await http.post(
                PATH,
                headers=headers,
                json={
                    "declared_clis": numbers,
                    "attestation_version": before["attestation_version"],
                    "attestation_sha256": before["attestation_sha256"],
                    **extra,
                },
            )
            assert refused.status_code == 422, refused.text

        recorded = await http.post(
            PATH,
            headers=headers,
            json={
                "declared_clis": numbers,
                "attestation_version": before["attestation_version"],
                "attestation_sha256": before["attestation_sha256"],
            },
        )
        assert recorded.status_code == 201, recorded.text
        body = recorded.json()
    # Dated the day it was confirmed, in IST.
    assert body["notified_on"] == BEFORE.isoformat()
    assert body["effective"] is True
    assert body["undeclared_clis"] == []
    assert body["blocker"] is None
    assert body["attested_version"] == DECLARATION_VERSION

    _today(monkeypatch, ENFORCED)
    assert (await _gate(tenant_id, agent_id)).allowed is True
    async with tenant_session(tenant_id) as session:
        audit = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'a2p_declaration.recorded' "
                    "AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert audit == 1


async def test_an_outbound_account_sees_the_announcement_and_an_answering_one_does_not() -> None:
    """Its own row rather than the migration's, which `announcements_test` may have ended."""
    tenant_id, _agent = await _tenant("a2p-news")
    link = f"/verify-business#calling-numbers-{uuid.uuid4().hex[:8]}"
    now = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_announcements (id, message, link_url, tone, audience, "
                "starts_at, created_at, updated_at) VALUES (gen_random_uuid(), 'Declare', :l, "
                "'warning', 'outbound', '2026-10-30T00:00:00+00:00', now(), now())"
            ),
            {"l": link},
        )
    async with tenant_session(tenant_id) as session:
        shown = await active_for(session, tenant_id=tenant_id, limit=500, now=now)
        assert any(item.link_url == link for item in shown)
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE tenant_id = :t"), {"t": tenant_id}
        )
        hidden = await active_for(session, tenant_id=tenant_id, limit=500, now=now)
    assert not any(item.link_url == link for item in hidden)


async def test_the_migration_sent_the_announcement_to_the_outbound_audience() -> None:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT audience, link_url, tone, message, link_label "
                    "FROM platform_announcements "
                    "WHERE id = '019a33c0-d941-7000-8000-0000000d0941'"
                )
            )
        ).first()
    assert row is not None
    assert tuple(row) == (
        "outbound",
        "/verify-business#calling-numbers",
        "warning",
        "From 17 Nov, the law needs the numbers your agent calls from to be registered. "
        "Confirm your calling numbers so your calls keep going.",
        "Confirm numbers",
    )
