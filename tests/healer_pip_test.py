"""D-776: Pip works the auto-healer — its reads, its three actions, the money evidence, and
the healer fixes that came with it (no reopening a just-closed problem, escalated repairs
re-checked on their own cadence, money problems that close when the calls show it).

SHARED DATABASE DISCIPLINE: every tenant, incident and alarm is minted here and every
assertion is scoped to its own ids.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.engine_minutes import EngineMinutePrice
from apps.api.copilot import admin_actions, service, tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.core.context import Principal
from apps.api.core.logging import MAX_FREE_TEXT
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.healer import decisions, incidents, ledger, money, wording
from apps.api.healer.incidents import Incident
from apps.api.main import app
from apps.workers import healer as healer_jobs
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.smoke_pipeline_test import _seed_tenant

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


# --- helpers ------------------------------------------------------------------------------


def _admin(token: str, role: str = "superadmin") -> Principal:
    return Principal(
        realm="admin", user_id=UUID(token.rsplit(":", 1)[1]), tenant_id=None, role=role
    )


async def _open(
    playbook: str = "money_review",
    code: str = "engine_charge_mismatch",
    *,
    state: str = "open",
    tenant_id: UUID | None = None,
) -> Incident:
    async with untenanted_session() as session:
        incident_id, opened = await incidents.open_incident(
            session,
            key=incidents.dedupe_key(playbook, code, uuid.uuid4()),
            playbook=playbook,
            trigger_code=code,
            scope="tenant" if tenant_id else "platform",
            tenant_id=tenant_id,
        )
        assert opened
        if state != "open":
            await session.execute(
                text(
                    "UPDATE heal_incidents SET state = CAST(:s AS text), escalated_at = CASE WHEN "
                    "CAST(:s AS text) = 'escalated' THEN now() END, "
                    "next_attempt_at = now() + interval '1 day' "
                    "WHERE id = :id"
                ),
                {"s": state, "id": incident_id},
            )
        found = await incidents.read_incident(session, incident_id)
    assert found is not None
    return found


async def _read(incident_id: UUID) -> Incident:
    async with untenanted_session() as session:
        found = await incidents.read_incident(session, incident_id)
    assert found is not None
    return found


async def _steps(incident_id: UUID) -> list[ledger.ActionRow]:
    async with untenanted_session() as session:
        return await ledger.list_actions(session, incident_id=incident_id, limit=50)


def _call(
    *,
    at: datetime,
    metered: str | None,
    charged: str,
    minutes: str = "2",
    rate_key: str = "premium",
    stamped: str = "2.50",
    fee: str = "0.0236",
) -> money.ChargedCall:
    charge = Decimal(charged)
    return money.ChargedCall(
        tenant_id=uuid.uuid4(),
        client="acme",
        call_id=uuid.uuid4(),
        at=at,
        rate_key=rate_key,
        billed_minutes=Decimal(minutes),
        stamped_rate=Decimal(stamped),
        metered_inr=None if metered is None else Decimal(metered),
        charged_inr=charge,
        expected_inr=(charge * (1 + Decimal(fee))).quantize(Decimal("0.0001")),
    )


def _price(rate: str, attested_at: datetime) -> EngineMinutePrice:
    return EngineMinutePrice(
        engine="thinnest",
        rate_key="premium",
        inr_per_min=Decimal(rate),
        effective_from=attested_at,
        attested_at=attested_at,
        attested_by="op",
        source_note="console pricing page",
    )


def _evidence(
    calls: list[money.ChargedCall],
    *,
    open_alarms: frozenset[str] = frozenset(),
    rates: dict[str, EngineMinutePrice] | None = None,
) -> money.MoneyEvidence:
    return money.MoneyEvidence(
        engine="thinnest",
        fee=Decimal("0.0236"),
        since=NOW - timedelta(days=2),
        calls=tuple(calls),
        rates=rates if rates is not None else {"premium": _price("2.50", NOW - timedelta(days=9))},
        uncharged=0,
        open_alarms=open_alarms,
        read_at=NOW,
    )


# --- the money evidence, without a database ----------------------------------------------


def test_differing_calls_on_one_rate_read_as_one_cause() -> None:
    # Metered at ₹2.50/min with the fee; charged ₹2.75/min, so ₹5.50 for two minutes.
    differing = [
        _call(at=NOW - timedelta(hours=h), metered="5.1180", charged="5.50") for h in (1, 2, 3)
    ]
    matching = _call(at=NOW - timedelta(hours=30), metered="5.1180", charged="5.00")
    evidence = _evidence([*differing, matching])
    assert len(evidence.differing) == 3 and len(evidence.matching) == 1
    cause = evidence.one_cause()
    assert cause is not None
    assert (cause.rate_key, cause.implied, cause.in_force) == (
        "premium",
        (Decimal("2.75"),),
        Decimal("2.50"),
    )
    explained = evidence.explain()
    assert "4 charged call(s), 1 match what we metered, 3 differ" in explained
    assert "we hold ₹2.50/min; the charges imply ₹2.75/min before the 2.36% top-up fee" in explained
    assert "One cause explains every difference: the premium rate." in explained
    summary = evidence.summary()
    assert summary.startswith("3 of 4 charged calls differ since")
    assert "premium: we hold ₹2.50/min, charges imply ₹2.75/min. One rate explains all." in summary
    assert len(summary) <= MAX_FREE_TEXT


def test_two_implied_rates_are_not_called_one_cause() -> None:
    evidence = _evidence(
        [
            _call(at=NOW, metered="5.1180", charged="5.50"),
            _call(at=NOW, metered="5.1180", charged="6.00"),
        ]
    )
    assert evidence.one_cause() is None
    assert "One cause" not in evidence.explain()
    assert "More than one rate differs." in evidence.summary()


def test_a_money_problem_settles_only_on_calls_after_the_newest_attestation() -> None:
    attested = NOW - timedelta(hours=5)
    rates = {"premium": _price("2.75", attested)}
    before = _call(at=attested - timedelta(hours=1), metered="5.1180", charged="5.50")
    after = _call(at=attested + timedelta(hours=1), metered="5.6298", charged="5.50")
    opened = NOW - timedelta(days=1)
    assert _evidence([before, after], rates=rates).settled("engine_charge_mismatch", after=opened)
    # The alarm is still open: not over, whatever the calls say.
    assert not _evidence(
        [after], rates=rates, open_alarms=frozenset({"engine_charge_mismatch"})
    ).settled("engine_charge_mismatch", after=opened)
    # No call since the attestation: nothing shows it is over yet.
    assert not _evidence([before], rates=rates).settled("engine_charge_mismatch", after=opened)
    # Unmatched settles as soon as any call since it opened carries a charge.
    assert _evidence([before], rates=rates).settled("engine_charge_unmatched", after=opened)
    assert not _evidence([], rates=rates).settled("engine_charge_unmatched", after=opened)


def test_progress_words_for_a_problem_closed_after_hand_over() -> None:
    assert (
        wording.progress(
            playbook="engine_webhooks",
            automatic=True,
            state="resolved",
            attempts=3,
            last_outcome="verified",
            escalated=True,
        )
        == "Cleared on its own after it was handed to you"
    )
    assert wording.progress(
        playbook="money_review",
        automatic=False,
        state="resolved",
        attempts=0,
        last_outcome="verified",
        escalated=True,
    ).startswith("Closed automatically")


def test_a_short_ref_is_the_random_tail() -> None:
    incident_id = uuid7()
    assert incidents.short_ref(incident_id) == incident_id.hex[-8:]


# --- the healer's own fixes --------------------------------------------------------------


async def _alarm(code: str, tenant_id: UUID, *, seen_ago: timedelta) -> UUID:
    alert_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_alerts (id, fingerprint, code, stage, severity, service, "
                "detail, ids, first_seen_at, last_seen_at, occurrences) VALUES (:id, :fp, "
                ":code, 'WORKER_TERMINAL', 'attention', 'workers', 'test', CAST(:ids AS jsonb), "
                "now() - :ago, now() - :ago, 1)"
            ),
            {
                "id": alert_id,
                "fp": f"WORKER_TERMINAL:{code}:{alert_id}",
                "code": code,
                "ids": json.dumps({"tenant_id": str(tenant_id)}),
                "ago": seen_ago,
            },
        )
    return alert_id


async def _clear(alert_id: UUID) -> None:
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_alerts SET cleared_at = now() WHERE id = :id"), {"id": alert_id}
        )


async def test_a_problem_closed_after_its_alarm_last_fired_is_not_reopened() -> None:
    """FAILS IF the episode's quiet hour reopens a problem the healer just closed."""
    tenant_id, _agent = await _seed_tenant(f"pip_{uuid.uuid4().hex[:10]}")
    code = "engine_workspace_provisioning_failed"
    key = incidents.dedupe_key("workspace_retry", code, tenant_id)
    alert_id = await _alarm(code, tenant_id, seen_ago=timedelta(minutes=30))
    try:
        async with untenanted_session() as session:
            incident_id, _ = await incidents.open_incident(
                session,
                key=key,
                playbook="workspace_retry",
                trigger_code=code,
                scope="tenant",
                tenant_id=tenant_id,
            )
            await incidents.close_by_person(session, incident_id)
        await healer_jobs._open_from_alarms(Counter())
        async with untenanted_session() as session:
            assert await incidents.open_for(session, key) is None
            await session.execute(
                text("UPDATE platform_alerts SET last_seen_at = now() WHERE id = :id"),
                {"id": alert_id},
            )
        # The alarm fired again after the close: that is a new problem.
        await healer_jobs._open_from_alarms(Counter())
        async with untenanted_session() as session:
            assert await incidents.open_for(session, key) is not None
    finally:
        await _clear(alert_id)


async def test_an_escalated_repair_is_rechecked_on_its_cooldown_and_quietly() -> None:
    """FAILS IF a handed-over repair waits six hours to notice it cleared (the ~7-hour
    "fixed after 3 tries" problem), or ledgers every failed re-check."""
    incident = await _open("engine_webhooks", "engine_webhook_sweep_incomplete", state="escalated")

    async def act(_i: Incident) -> str:
        raise AssertionError("an escalated incident is never repaired again")

    async def still_failing(_i: Incident) -> bool:
        return False

    async def cleared(_i: Incident) -> bool:
        return True

    await healer_jobs._generic(act, still_failing)(incident)
    held = await _read(incident.id)
    assert held.state == "escalated" and held.next_attempt_at is not None
    wait = held.next_attempt_at - datetime.now(UTC)
    assert timedelta(minutes=15) < wait <= timedelta(minutes=20)
    assert await _steps(incident.id) == []
    await healer_jobs._generic(act, cleared)(held)
    done = await _read(incident.id)
    assert (done.state, done.last_outcome) == ("resolved", "verified")
    assert [(s.step, s.outcome) for s in await _steps(incident.id)] == [("verify", "ok")]


async def test_a_money_problem_is_handed_over_with_its_evidence_then_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident = await _open()
    differing = [_call(at=datetime.now(UTC), metered="5.1180", charged="5.50")]
    current = {"evidence": _evidence(differing, open_alarms=frozenset({incident.trigger_code}))}

    async def fake_gather(**_: Any) -> money.MoneyEvidence:
        return current["evidence"]

    monkeypatch.setattr(money, "gather", fake_gather)
    monkeypatch.setattr(healer_jobs, "alert", lambda *a, **k: None)
    await healer_jobs._money_review(incident)
    escalated = await _read(incident.id)
    assert escalated.state == "escalated"
    assert escalated.next_attempt_at is not None
    assert escalated.next_attempt_at - datetime.now(UTC) <= timedelta(hours=1)
    steps = await _steps(incident.id)
    assert steps[0].step == "escalate" and "charges imply ₹2.75/min" in (steps[0].detail or "")
    # The same reading again writes nothing new.
    await healer_jobs._money_review(escalated)
    assert len(await _steps(incident.id)) == 1
    # The alarm closed and a call after the newest attestation matches: it closes itself.
    current["evidence"] = _evidence([_call(at=datetime.now(UTC), metered="5.1180", charged="5.00")])
    await healer_jobs._money_review(await _read(incident.id))
    closed = await _read(incident.id)
    assert (closed.state, closed.last_outcome) == ("resolved", "verified")
    assert (await _steps(incident.id))[0].outcome == "ok"


async def test_the_evidence_reads_our_own_rows() -> None:
    tenant_id, agent_id = await _seed_tenant(f"pip_{uuid.uuid4().hex[:10]}")
    rows = (("5.50", "5.1180"), ("5.00", "5.1180"))
    ids = []
    async with tenant_session(tenant_id) as session:
        for charged, metered in rows:
            call_id = uuid7()
            ids.append(call_id)
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, engine_charged_inr, created_at, updated_at) VALUES (:id, :t, :a, "
                    ":e, 'outbound', 'completed', :c, now(), now())"
                ),
                {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"out_{call_id}", "c": charged},
            )
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                    "'platform_min', 1, :p, now(), CAST(:m AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "p": metered,
                    "m": json.dumps(
                        {"engine_rate_key": "premium", "billed_minutes": "2", "inr_per_min": "2.5"}
                    ),
                },
            )
    evidence = await money.gather(
        since=datetime.now(UTC) - timedelta(hours=1), tenant_ids=[tenant_id]
    )
    by_id = {c.call_id: c for c in evidence.calls}
    assert set(by_id) == set(ids)
    first = by_id[ids[0]]
    assert (first.rate_key, first.metered_inr, first.charged_inr) == (
        "premium",
        Decimal("5.1180"),
        Decimal("5.50"),
    )
    assert first.implied_rate == Decimal("2.75")
    # The fake engine is not paid from a wallet, so its fee is zero.
    assert evidence.fee == 0 and first.matches is False and by_id[ids[1]].matches is False


# --- the screen's two buttons, through `decisions` -----------------------------------------


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def test_check_again_is_refused_where_the_healer_never_acts() -> None:
    incident = await _open()
    assert decisions.retry_refusal(incident) is not None
    headers = {"Authorization": f"Bearer {await _make_admin()}"}
    async with _client() as client:
        response = await client.post(
            f"/v1/ops/healer/incidents/{incident.id}/retry", headers=headers
        )
    assert response.status_code == 409, response.text
    assert response.json()["type"].endswith("/heal_incident_not_retryable")


def test_a_paused_repair_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    incident = Incident(
        id=uuid7(),
        dedupe_key="k",
        playbook="outbox_replay",
        trigger_code="outbox_dead_letter",
        scope="platform",
        tenant_id=None,
        agent_id=None,
        state="escalated",
        attempts=2,
        next_attempt_at=None,
        component=None,
        public=False,
        public_title=None,
        last_outcome="escalated",
        opened_at=NOW,
        mitigated_at=None,
        escalated_at=NOW,
        resolved_at=None,
    )
    assert decisions.retry_refusal(incident) is None
    monkeypatch.setattr(get_settings(), "healer_paused_playbooks", "outbox_replay")
    assert "switched off" in (decisions.retry_refusal(incident) or "")


# --- Pip's reads -------------------------------------------------------------------------


async def _pip_read(name: str, role: str = "superadmin", **args: Any) -> str:
    return await tools.run_read_tool(
        name,
        json.dumps(args),
        context=tools.ToolContext(tenant_id=None, role=role),
        registry=service._read_tool_registry("admin"),
    )


async def test_pip_lists_the_healers_problems_with_refs() -> None:
    incident = await _open(state="escalated")
    listed = await _pip_read("healer_incidents", include_closed=None)
    assert f"[ref {incidents.short_ref(incident.id)}]" in listed
    assert "Call charges don't match our records" in listed
    assert listed.startswith("Auto-healer: ")
    assert (await _pip_read("healer_incidents", role="operator", include_closed=None)).startswith(
        "Refused"
    )


async def test_pip_reads_one_problem_and_says_what_it_may_propose() -> None:
    incident = await _open(state="escalated")
    detail = await _pip_read("healer_incident", incident=incidents.short_ref(incident.id))
    assert "What it means:" in detail
    assert "not healer_retry" in detail and "healer_attest_rate" in detail
    missing = await _pip_read("healer_incident", incident="ffffffff")
    assert missing.startswith("No healer problem")


async def test_pip_money_review_marks_an_implied_rate_as_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _open(state="escalated")
    call = _call(at=datetime.now(UTC), metered="5.1180", charged="5.50")

    async def fake_gather(**_: Any) -> money.MoneyEvidence:
        return _evidence([call])

    monkeypatch.setattr(money, "gather", fake_gather)
    review = await _pip_read("healer_money_review")
    assert f"[call {call.call_id}]" in review
    assert "implies ₹2.75/min" in review
    assert "NOT an attested figure" in review


# --- Pip's actions -----------------------------------------------------------------------


async def _plan(name: str, token: str, args: dict[str, Any], role: str = "superadmin") -> Any:
    return await admin_actions.plan_admin_action(
        name, json.dumps(args), principal=_admin(token, role), viewing_tenant_id=None
    )


async def _confirm(token: str, proposal: Any) -> tuple[Any, list[str]]:
    asked: list[str] = []
    async with untenanted_session() as session:
        done = await admin_actions.confirm_admin(
            session,
            proposal.token,
            principal=_admin(token),
            require_step_up=asked.append,
            ip=None,
        )
    return done, asked


async def _audited(action: str, object_id: str) -> list[tuple[str, UUID | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT actor_type, actor_id FROM audit_log WHERE action = :a "
                    "AND object_id = :o"
                ),
                {"a": action, "o": object_id},
            )
        ).all()
    return [(str(r[0]), r[1]) for r in rows]


def test_the_healer_tools_reach_the_admin_realm_only() -> None:
    admin = json.dumps(service.tool_array("admin"))
    client = json.dumps(service.tool_array("client"))
    for name in ("healer_retry", "healer_attest_rate", "healer_money_review"):
        assert f'"{name}"' in admin and f'"{name}"' not in client


async def test_pip_will_not_retry_money_and_an_operator_may_not_ask() -> None:
    token = await _make_admin()
    money_problem = await _open(state="escalated")
    with pytest.raises(WriteRefusedError) as refused:
        await _plan("healer_retry", token, {"incident": incidents.short_ref(money_problem.id)})
    assert "never acts" in refused.value.reason
    operator = await _make_admin(role="operator")
    with pytest.raises(WriteRefusedError) as role:
        await _plan(
            "healer_retry",
            operator,
            {"incident": incidents.short_ref(money_problem.id)},
            role="operator",
        )
    assert "role may not" in role.value.reason


async def test_pip_retries_a_repair_after_a_click() -> None:
    token = await _make_admin()
    incident = await _open("outbox_replay", "outbox_dead_letter", state="escalated")
    proposal = await _plan("healer_retry", token, {"incident": incidents.short_ref(incident.id)})
    assert proposal.confirm_action is None
    assert (await _read(incident.id)).next_attempt_at > datetime.now(UTC)  # type: ignore[operator]
    done, asked = await _confirm(token, proposal)
    assert done.applied and asked == []
    due = (await _read(incident.id)).next_attempt_at
    assert due is not None and due <= datetime.now(UTC)
    assert len(await _audited("healer.incident_retried", str(incident.id))) == 1


async def test_pip_closes_a_problem_with_the_operators_reason_and_step_up() -> None:
    token = await _make_admin()
    incident = await _open(state="escalated")
    with pytest.raises(WriteRefusedError):
        await _plan("healer_resolve", token, {"incident": str(incident.id), "reason": "  "})
    proposal = await _plan(
        "healer_resolve", token, {"incident": str(incident.id), "reason": "Checked with vendor"}
    )
    assert proposal.confirm_action == f"resolve_heal_incident:{incident.id}"
    assert "No money moves" in proposal.summary
    done, asked = await _confirm(token, proposal)
    assert done.applied and asked == [f"resolve_heal_incident:{incident.id}"]
    closed = await _read(incident.id)
    assert (closed.state, closed.last_outcome) == ("resolved", "restored_by_person")
    decided = [s for s in await _steps(incident.id) if s.step == "decide"]
    assert decided and decided[0].actor_type == "admin"
    assert "Checked with vendor" in (decided[0].detail or "")
    assert await _audited("healer.incident_resolved", str(incident.id)) == [
        ("admin", _admin(token).user_id)
    ]


async def test_pip_never_attests_a_rate_the_operator_did_not_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await _make_admin()
    args = {
        "rate_key": "premium",
        "inr_per_min": "2.75",
        "effective_from": None,
        "source_note": "Pricing page in the console",
        "operator_typed_it": False,
        "resolve": [],
    }
    # This deployment's engine is the fake one, which is not priced by the minute.
    with pytest.raises(WriteRefusedError) as wrong_engine:
        await _plan("healer_attest_rate", token, {**args, "operator_typed_it": True})
    assert "not priced by the minute" in wrong_engine.value.reason
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    with pytest.raises(WriteRefusedError) as untyped:
        await _plan("healer_attest_rate", token, args)
    assert "operator read" in untyped.value.reason
    with pytest.raises(WriteRefusedError):
        await _plan(
            "healer_attest_rate", token, {**args, "operator_typed_it": True, "inr_per_min": "x"}
        )


async def test_one_confirmed_attestation_closes_the_money_problems_it_explains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    token = await _make_admin()
    mismatch = await _open(state="escalated")
    variance = await _open(code="engine_call_cost_variance", state="escalated")
    webhook = await _open("engine_webhooks", "engine_webhook_sweep_incomplete", state="escalated")
    # A future instant, so no other test meters at this figure.
    effective = datetime(2099, 1, 1, tzinfo=UTC) + timedelta(seconds=uuid.uuid4().int % 10**6)
    args = {
        "rate_key": "premium",
        "inr_per_min": "2.75",
        "effective_from": effective.isoformat(),
        "source_note": "Pricing page in the console",
        "operator_typed_it": True,
        "resolve": [incidents.short_ref(mismatch.id), str(variance.id)],
    }
    with pytest.raises(WriteRefusedError) as not_money:
        await _plan(
            "healer_attest_rate", token, {**args, "resolve": [incidents.short_ref(webhook.id)]}
        )
    assert "only money problems" in not_money.value.reason
    proposal = await _plan("healer_attest_rate", token, args)
    assert proposal.confirm_action == "attest_engine_minute_price:thinnest:premium"
    assert proposal.proposed == "₹2.75/min" and "Closes 2 money problem(s)" in proposal.summary
    done, asked = await _confirm(token, proposal)
    assert done.applied and asked == ["attest_engine_minute_price:thinnest:premium"]
    for incident in (mismatch, variance):
        assert (await _read(incident.id)).state == "resolved"
    assert (await _read(webhook.id)).state == "escalated"
    async with untenanted_session() as session:
        stored = (
            await session.execute(
                text(
                    "SELECT inr_per_min FROM platform_engine_minute_prices WHERE engine = "
                    "'thinnest' AND rate_key = 'premium' AND effective_from = :ef"
                ),
                {"ef": effective},
            )
        ).scalar_one()
    assert stored == Decimal("2.75")
    assert "2 money problem(s) are closed" in done.detail
    audited = await _audited("platform.engine_minute_price_attested", "thinnest:premium")
    assert ("admin", _admin(token).user_id) in audited
