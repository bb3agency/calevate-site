"""Work left in flight for ever, or failing without anybody hearing (backend audit lane T8,
8 Nov 2026). Each test fails on the tree before its fix:

1. A call's English whose pass died past the job limit said "Translating…" for ever.
2. A naming of the core lead details whose worker stopped mid-run was never done.
3. A client's standard WhatsApp templates not submitted for want of a key raised no alarm,
   and a template check that could not read the key never checked again.
4. A founder page whose record could not be written was sent again every minute.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.healer import ledger
from apps.api.whatsapp import accounts as wa_accounts
from apps.workers import call_translation, healer, whatsapp, whatsapp_meta
from apps.workers import core_labels as core_worker
from apps.workers.fleet_walk import WalkBudget
from arq import Retry
from sqlalchemy import text
from tests.call_translation_test import _state, _telugu_call
from tests.core_labels_test import _answer, _with_services
from tests.lead_fields_test import _tenant
from tests.whatsapp_template_check_test import _payload, _template, wired  # noqa: F401

# --- 1. a call's English ----------------------------------------------------------------


async def _call_in(
    translation_state: str, *, summary_state: str, touched_ago: timedelta
) -> tuple[UUID, UUID]:
    tenant_id, call_id, _slug, _headers = await _telugu_call(state=translation_state)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET summary_state = :s, updated_at = now() - :ago WHERE id = :c"),
            {"s": summary_state, "ago": touched_ago, "c": call_id},
        )
    return tenant_id, call_id


async def test_a_translation_whose_pass_died_says_failed_and_is_tried_again() -> None:
    tenant_id, died = await _call_in(
        "pending", summary_state="ready", touched_ago=timedelta(hours=2)
    )
    assert await call_translation._settle_interrupted(tenant_id) == 1
    assert await _state(tenant_id, died) == "failed", "the owner is offered Try again"
    await get_redis().delete(f"call_translation:backfilled:{died}")
    candidates = await call_translation._untried_candidates(tenant_id, WalkBudget())
    assert died in [call_id for _at, call_id in candidates], "the backfill tries it once more"


async def test_a_translation_still_running_or_never_queued_is_left_alone() -> None:
    tenant_id, running = await _call_in(
        "pending", summary_state="ready", touched_ago=timedelta(minutes=10)
    )
    other_tenant, unread = await _call_in(
        "pending", summary_state="pending", touched_ago=timedelta(hours=2)
    )
    assert await call_translation._settle_interrupted(tenant_id) == 0
    assert await call_translation._settle_interrupted(other_tenant) == 0
    assert await _state(tenant_id, running) == "pending"
    # The column default on a call the pipeline has not read: no pass was ever queued, so the
    # backfill must not be handed it to pay for.
    assert await _state(other_tenant, unread) == "pending"


async def test_the_backfill_tick_settles_a_died_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, died = await _call_in(
        "pending", summary_state="ready", touched_ago=timedelta(hours=2)
    )

    async def _enqueue(job: str, payload: dict[str, str], *, job_id: str) -> str:
        return job_id

    monkeypatch.setattr(call_translation, "enqueue", _enqueue)
    await call_translation.backfill_call_translations({})
    assert await _state(tenant_id, died) == "failed"


# --- 2. the one naming of the core lead details ----------------------------------------


async def _drafted_at(tenant_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT core_labels_drafted_at FROM organizations WHERE id = :t"),
                {"t": tenant_id},
            )
        ).scalar()


@pytest.mark.rls
async def test_a_naming_cut_off_mid_run_is_done_by_the_next_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _ = await _tenant("custom")
    await _with_services(tenant_id)
    payload = {"tenant_id": str(tenant_id)}

    async def cancelled(*_a: Any, **_kw: Any) -> Any:
        raise asyncio.CancelledError

    monkeypatch.setattr(core_worker, "ask_json", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await core_worker.name_core_details({}, payload)
    assert await _drafted_at(tenant_id) is None, "nothing marks it named"

    monkeypatch.setattr(core_worker, "ask_json", _answer({"need": "Crop issue"}))
    assert await core_worker.name_core_details({}, payload) == "named"
    assert await _drafted_at(tenant_id) is not None
    assert await core_worker.name_core_details({}, payload) == "not_needed"


@pytest.mark.rls
async def test_a_run_finding_another_in_flight_comes_back_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _ = await _tenant("custom")
    await _with_services(tenant_id)
    # A killed run's lease: held until it frees, then the business is named.
    assert await core_worker._take_lease(tenant_id)
    monkeypatch.setattr(core_worker, "ask_json", _answer({"need": "Crop issue"}))
    with pytest.raises(Retry):
        await core_worker.name_core_details({}, {"tenant_id": str(tenant_id)})
    await core_worker._drop_lease(tenant_id)
    assert await core_worker.name_core_details({}, {"tenant_id": str(tenant_id)}) == "named"


# --- 3. WhatsApp templates and an unreadable key ----------------------------------------


async def test_templates_not_submitted_for_want_of_a_key_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alarms: list[tuple[str, dict[str, Any]]] = []

    async def _account(*_a: Any, **_kw: Any) -> Any:
        return SimpleNamespace(status="connected", waba_id="1")

    async def _no_key(*_a: Any, **_kw: Any) -> str:
        raise ProblemError.business_rule("whatsapp_reconnect", "Reconnect.")

    monkeypatch.setattr(wa_accounts, "get_account", _account)
    monkeypatch.setattr(wa_accounts, "account_token", _no_key)
    monkeypatch.setattr(whatsapp_meta, "alert", lambda _st, code, **kw: alarms.append((code, kw)))
    payload = {"tenant_id": str(uuid.uuid4()), "account_id": str(uuid.uuid4())}
    assert await whatsapp_meta.seed_whatsapp_templates({}, payload) == "no_token"
    assert [code for code, _ in alarms] == ["whatsapp_templates_not_submitted"]
    assert alarms[0][1]["reason"] == "no_token"


async def test_a_template_check_without_a_key_checks_again(
    wired: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_key(*_a: Any, **_kw: Any) -> str:
        raise ProblemError.business_rule("whatsapp_reconnect", "Reconnect.")

    monkeypatch.setattr(wa_accounts, "account_token", _no_key)
    tenant_id, template_id = await _template(submitted_hours_ago=200)
    assert await whatsapp_meta.check_whatsapp_template({}, _payload(tenant_id, template_id)) == (
        "still_pending"
    )
    assert [check for _job, check, _due in wired["scheduled"]] == [1]
    last = _payload(tenant_id, template_id, check=whatsapp_meta.TEMPLATE_CHECKS - 1)
    await whatsapp_meta.check_whatsapp_template({}, last)
    assert wired["alarms"] == ["whatsapp_templates_stuck_pending"]


# --- 4. the founder's page ------------------------------------------------------------


async def test_a_page_whose_record_fails_is_not_sent_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = f"t8_page_{uuid.uuid4().hex[:8]}"
    alert_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_alerts (id, fingerprint, code, stage, severity, service, "
                "detail, ids, first_seen_at, last_seen_at, occurrences) VALUES (:id, :fp, "
                ":code, 'WORKER_TERMINAL', 'page', 'workers', 'test', '{}'::jsonb, "
                "now() - interval '50 minutes', now(), 1)"
            ),
            {"id": alert_id, "fp": f"WORKER_TERMINAL:{code}", "code": code},
        )
    sent: list[str] = []

    class _Transport:
        async def send(self, message: Any) -> whatsapp.SendResult:
            sent.append(str(message.variables[0]))
            return whatsapp.SendResult(status=whatsapp.SendStatus.DELIVERED)

    async def _founder() -> whatsapp.Destination:
        return whatsapp.Destination(to_e164="+919000000000", opt_in_at=datetime.now(UTC))

    async def _record_fails(session: Any, **kwargs: Any) -> None:
        if kwargs.get("alarm_code") == code:
            raise RuntimeError("ledger write failed")

    monkeypatch.setattr(
        healer,
        "get_settings",
        lambda: SimpleNamespace(
            whatsapp_enabled=True,
            whatsapp_template_healer_page="healer_page",
            whatsapp_template_locale="en",
            app_env="test",
        ),
    )
    monkeypatch.setattr(healer, "_founder_destination", _founder)
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: _Transport())
    monkeypatch.setattr(ledger, "record", _record_fails)
    try:
        with pytest.raises(RuntimeError):
            await healer._page_founder(Counter())
        await healer._page_founder(Counter())
        assert sent.count(code) == 1, "the founder is paged once"
    finally:
        await get_redis().delete(healer._PAGE_CLAIM_KEY.format(alert_id=alert_id))
        async with untenanted_session() as session:
            await session.execute(
                text("UPDATE platform_alerts SET cleared_at = now() WHERE id = :id"),
                {"id": alert_id},
            )


async def test_a_released_page_claim_may_be_taken_again() -> None:
    alert_id = uuid.uuid4()
    assert await healer._claim_page(alert_id)
    assert not await healer._claim_page(alert_id)
    await healer._release_page(alert_id)
    assert await healer._claim_page(alert_id)
    await healer._release_page(alert_id)
