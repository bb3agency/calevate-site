"""D-1021: the account's notice switches reach every opening a call speaks, not only an
agent's own: an Inbound line's and a campaign's own script are re-woven when a switch moves,
and a campaign's second opening (D-992) carries the switch on every dial.

Pip's writer is replaced by a stub that returns a fixed line, so what is asserted is the
seam: the flip queues the rewrite, the worker saves it into the holder's own script with the
notice record, and the first words follow the account's switch.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents.opening_notices import HOLDER_WEAVE_JOB
from apps.api.agents.publishing import set_account_notices
from apps.api.campaigns import service as campaigns
from apps.api.db.session import tenant_session
from apps.api.inbound import lines as inbound_lines
from apps.workers import opening_line
from apps.workers import opening_notices as weave_worker
from calevate_shared.call_script import SCRIPT_SCHEMA_VERSION, CallScript
from calevate_shared.invisible_text import plain_joins
from calevate_shared.opening_notices import NONE_SAID, OpeningNotices, SaidNotices
from sqlalchemy import text
from tests.dispatch_budget_test import _dlt_rows, _tenant

pytestmark = pytest.mark.anyio

AI_WORDS = "I am an AI assistant"
WOVEN = f"Namaskaram, {AI_WORDS} from Budget Motors, calling about your booking."
PLAIN = "Namaskaram, Budget Motors here, calling about your booking."
SECOND = "Hello, a quick call about the offer you asked for."


def _woven_script() -> dict[str, Any]:
    return json.loads(
        CallScript(
            schema_version=SCRIPT_SCHEMA_VERSION,
            opening_line=WOVEN,
            opening_notices=OpeningNotices(line=WOVEN, ai=AI_WORDS),
            goal="Confirm the booking.",
        ).model_dump_json()
    )


async def _switch(tenant_id: uuid.UUID, *, ai: bool) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET notice_ai_enabled = :ai WHERE id = :t"),
            {"ai": ai, "t": tenant_id},
        )


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Booking reminders",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb), opening_b = :b WHERE id = :c"),
            {"s": json.dumps(_woven_script()), "b": SECOND, "c": campaign_id},
        )
    return campaign_id


async def _line(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await inbound_lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Bookings",
            script=CallScript.model_validate(_woven_script()),
            created_by=None,
        )


async def _jobs(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE job = :j ORDER BY created_at"),
                {"j": HOLDER_WEAVE_JOB},
            )
        ).all()
    payloads = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]
    return [p for p in payloads if p["tenant_id"] == str(tenant_id)]


def _stub_writer(monkeypatch: pytest.MonkeyPatch, line: str, said: SaidNotices) -> list[Any]:
    briefs: list[Any] = []

    async def fake_write(brief: Any, **kwargs: Any) -> Any:
        briefs.append((brief, kwargs.get("placed")))
        value = opening_line.WrittenOpening(line=line, said=said)
        return SimpleNamespace(value=value, capability=None, earlier=(), model=None)

    async def no_meter(_tenant_id: uuid.UUID, _spends: Any) -> None:
        return None

    monkeypatch.setattr(weave_worker, "write_opening", fake_write)
    monkeypatch.setattr(weave_worker, "_meter", no_meter)
    return briefs


async def _script(tenant_id: uuid.UUID, table: str, holder_id: uuid.UUID) -> CallScript:
    async with tenant_session(tenant_id) as session:
        raw = (
            await session.execute(
                text(f"SELECT script FROM {table} WHERE id = :h"),
                {"h": holder_id},
            )
        ).scalar_one()
    return CallScript.model_validate(raw)


async def test_switching_the_ai_notice_off_rewrites_a_campaigns_own_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    await _switch(tenant_id, ai=True)
    campaign_id = await _campaign(tenant_id, agent_id)

    await set_account_notices(
        tenant_id=tenant_id, ai_disclosure_enabled=False, recording_notice_enabled=None
    )
    jobs = [j for j in await _jobs(tenant_id) if j["kind"] == "campaign"]
    assert [j["holder_id"] for j in jobs] == [str(campaign_id)]

    briefs = _stub_writer(monkeypatch, PLAIN, NONE_SAID)
    assert await weave_worker.weave_holder_opening_notices({}, jobs[0]) == "woven"
    # A campaign only places calls, so its opening is written as a placed call's.
    assert briefs[0][1] is True
    script = await _script(tenant_id, "campaigns", campaign_id)
    assert script.opening_line == PLAIN
    assert script.opening_notices.ai == "" and script.opening_notices.before == WOVEN
    # Said once more is the only cost of a stale job: a second run finds nothing to do.
    assert await weave_worker.weave_holder_opening_notices({}, jobs[0]) == "stale"


async def test_switching_the_ai_notice_off_rewrites_an_inbound_lines_own_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    await _switch(tenant_id, ai=True)
    line_id = await _line(tenant_id, agent_id)

    await set_account_notices(
        tenant_id=tenant_id, ai_disclosure_enabled=False, recording_notice_enabled=None
    )
    jobs = [j for j in await _jobs(tenant_id) if j["kind"] == "line"]
    assert [j["holder_id"] for j in jobs] == [str(line_id)]

    briefs = _stub_writer(monkeypatch, PLAIN, NONE_SAID)
    assert await weave_worker.weave_holder_opening_notices({}, jobs[0]) == "woven"
    assert briefs[0][1] is False, "a line answers calls"
    assert (await _script(tenant_id, "inbound_lines", line_id)).opening_line == PLAIN


async def test_switching_on_rewrites_a_campaign_opening_that_does_not_say_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    await _switch(tenant_id, ai=False)
    campaign_id = await _campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c"),
            {
                "s": CallScript(
                    schema_version=SCRIPT_SCHEMA_VERSION, opening_line=PLAIN, goal="Confirm."
                ).model_dump_json(),
                "c": campaign_id,
            },
        )

    await set_account_notices(
        tenant_id=tenant_id, ai_disclosure_enabled=True, recording_notice_enabled=None
    )
    jobs = [j for j in await _jobs(tenant_id) if j["kind"] == "campaign"]
    _stub_writer(monkeypatch, WOVEN, SaidNotices(ai=AI_WORDS))
    assert await weave_worker.weave_holder_opening_notices({}, jobs[0]) == "woven"
    script = await _script(tenant_id, "campaigns", campaign_id)
    assert script.opening_line == WOVEN and script.opening_notices.ai == AI_WORDS


async def test_a_campaigns_second_opening_follows_the_account_switch_on_every_dial() -> None:
    """The second opening is the owner's own line, never woven: its notice is joined to it
    on each dial from the account's switch (`campaign_first_words`), so it cannot go stale."""
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)

    async def first_words() -> tuple[str, str]:
        async with tenant_session(tenant_id) as session:
            speaker = await agents_service.campaign_agent_row(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        return (
            agents_service.campaign_first_words(speaker, SECOND, call_is_recorded=True),
            plain_joins(str(speaker["ai_disclosure_line"]).strip()),
        )

    await _switch(tenant_id, ai=True)
    said, ai_line = await first_words()
    # A greeting after the introduction is dropped (`join_first_words`), the rest is said.
    assert ai_line in said and "a quick call about the offer" in said
    await set_account_notices(
        tenant_id=tenant_id, ai_disclosure_enabled=False, recording_notice_enabled=None
    )
    said, ai_line = await first_words()
    assert ai_line not in said and SECOND in said
