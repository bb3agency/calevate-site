"""The founder's decisions of 25 Nov 2026 ("go with all your recommendations").

1. "Give callers time" is on a campaign's or line's engine agent when its script asks the
   caller to act on their phone, over the settings left at Calevate's level; the owner's
   choice for that holder is kept and the script no longer decides.
2. Acknowledgements are off by default, end to end, and a console row holding the old default
   follows the new one.
3. Spread retries are switched on for existing campaigns left at the default retry settings.
4. A new second opening starts its test from nothing: earlier calls do not count.
5. Setting up a campaign's WhatsApp follow-up takes the WhatsApp screen's template permission.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents import give_callers_time as gct
from apps.api.agents import live_apply
from apps.api.agents import service as agents_service
from apps.api.agents.call_handling import platform_settings
from apps.api.agents.script_lint import asks_caller_to_act
from apps.api.campaigns import learning
from apps.api.campaigns.workspace_routes import router as workspace_router
from apps.api.copilot import write_tools
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session
from apps.api.follow_ups.campaign_routes import router as follow_up_router
from apps.api.inbound.routes import router as inbound_router
from apps.api.whatsapp.templates import TEMPLATE_PERMISSION
from calevate_shared.call_script import (
    CallScript,
    ConversationStage,
    FaqEntry,
    ProcedureStep,
)
from calevate_shared.config import Settings
from calevate_shared.engine import AgentConfig
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.call_notices_repair_migration_test import load_revision, rls_bound_owner
from tests.campaign_controls_test import Account, _account, _campaign
from tests.campaign_improve_test import OWN_OPENING, SECOND_OPENING, _opening_trial, _with_test
from tests.notes_per_job_test import _line
from tests.thinnest_publish_limits_test import _agent_with_script, _selected, _thinnest

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    for router in (workspace_router, inbound_router, follow_up_router):
        application.include_router(router)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


def _stage(**kw: Any) -> ConversationStage:
    return ConversationStage(**{"id": "s1", "name": "Install", "instruction": "Help them.", **kw})


#: A guided install: a step-by-step list of what the caller does on their phone.
GUIDED = CallScript(
    schema_version=2,
    opening_line="Hello.",
    goal="Get the app installed.",
    stages=[
        _stage(
            procedure=[
                ProcedureStep(action="Open the Play Store", wait_for="They see the store"),
                ProcedureStep(action="Search for the app"),
            ]
        )
    ],
)
#: Only books a visit: nothing for the caller to do on their phone.
BOOKING = CallScript(
    schema_version=2,
    opening_line="Hello.",
    goal="Book a visit.",
    stages=[_stage(name="Book", instruction="Ask which day suits them, then confirm the time.")],
)


# --- 1. Give callers time on a holder -------------------------------------------------------


def test_a_step_list_or_a_spoken_on_screen_action_asks_the_caller_to_act() -> None:
    assert asks_caller_to_act(GUIDED)
    spoken = _stage(scripts={"en-IN": "Great. Now tap Register at the bottom."})
    assert asks_caller_to_act(BOOKING.model_copy(update={"stages": [spoken]}))
    stacked = _stage(instruction="Ask them to open the app and tap Register.")
    assert asks_caller_to_act(BOOKING.model_copy(update={"stages": [stacked]}))
    faq = FaqEntry(question="How do I pay?", answer="Open the app. Tap Pay.")
    assert asks_caller_to_act(BOOKING.model_copy(update={"faqs": [faq]}))


def test_a_booking_script_or_a_raw_one_does_not() -> None:
    assert not asks_caller_to_act(BOOKING)
    assert not asks_caller_to_act(CallScript(raw_override="Open with a greeting. Tap into it."))


def test_the_owners_choice_beats_the_script() -> None:
    assert gct.holder_gives_time(None, GUIDED)
    assert not gct.holder_gives_time(None, BOOKING)
    assert not gct.holder_gives_time(None, None)
    assert not gct.holder_gives_time(False, GUIDED)
    assert gct.holder_gives_time(True, BOOKING)


def _preset_in(config: AgentConfig) -> None:
    assert config.nudge_after_seconds == gct.NUDGE_AFTER_S
    assert config.nudge_count == gct.NUDGE_COUNT
    assert config.end_after_silence_seconds == gct.END_AFTER_SILENCE_S
    assert config.reask_after_ms == gct.REASK_AFTER_MS
    assert config.max_call_duration_s == gct.preset_call_cap_s()
    phrase = gct.NUDGE_PHRASES.get(config.language_primary)
    if phrase:
        assert config.nudge_phrase == phrase


def _platform_in(config: AgentConfig) -> None:
    platform = platform_settings()
    assert config.nudge_after_seconds == platform.nudge_after_seconds
    assert config.end_after_silence_seconds == platform.end_after_silence_seconds
    assert config.max_call_duration_s == agents_service.effective_call_cap(None)


async def _campaign_config(
    tenant_id: uuid.UUID, campaign_id: uuid.UUID, script: CallScript
) -> AgentConfig:
    with _selected(_thinnest()):
        async with tenant_session(tenant_id) as session:
            return await agents_service.campaign_config(
                session, tenant_id=tenant_id, campaign_id=campaign_id, script=script
            )


async def _line_config(tenant_id: uuid.UUID, line_id: uuid.UUID, script: CallScript) -> AgentConfig:
    with _selected(_thinnest()):
        async with tenant_session(tenant_id) as session:
            return await agents_service.line_config(
                session, tenant_id=tenant_id, line_id=line_id, script=script
            )


async def _holder_choice(tenant_id: uuid.UUID, table: str, holder_id: uuid.UUID, on: bool) -> None:
    sql = {
        "campaigns": "UPDATE campaigns SET give_callers_time = :on WHERE id = :h",
        "inbound_lines": "UPDATE inbound_lines SET give_callers_time = :on WHERE id = :h",
    }[table]
    async with tenant_session(tenant_id) as session:
        await session.execute(text(sql), {"on": on, "h": holder_id})


async def test_a_guided_campaign_and_line_carry_the_preset_and_a_booking_one_does_not() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    tid, aid = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    from tests.notes_per_job_test import _campaign as _dlt_campaign

    campaign_id = await _dlt_campaign(tid, aid)
    _preset_in(await _campaign_config(tid, campaign_id, GUIDED))
    _platform_in(await _campaign_config(tid, campaign_id, BOOKING))
    line_id = await _line(tid, aid)
    _preset_in(await _line_config(tid, line_id, GUIDED))
    _platform_in(await _line_config(tid, line_id, BOOKING))

    # The owner turned it off on the campaign and on for the line: kept whatever the script.
    await _holder_choice(tid, "campaigns", campaign_id, False)
    await _holder_choice(tid, "inbound_lines", line_id, True)
    _platform_in(await _campaign_config(tid, campaign_id, GUIDED))
    _preset_in(await _line_config(tid, line_id, BOOKING))


async def test_a_value_the_owner_chose_on_the_agent_is_kept_on_the_holder() -> None:
    tenant_id, agent_id = await _agent_with_script("Greet, then help.")
    tid, aid = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    async with tenant_session(tid) as session:
        await session.execute(
            text(
                "UPDATE agents SET nudge_after_seconds = 30, max_call_duration_s = 300 "
                "WHERE id = :a"
            ),
            {"a": aid},
        )
    line_id = await _line(tid, aid)
    config = await _line_config(tid, line_id, GUIDED)
    assert config.nudge_after_seconds == 30
    assert config.max_call_duration_s == 300
    assert config.end_after_silence_seconds == gct.END_AFTER_SILENCE_S


async def _guided_campaign(account: Account) -> uuid.UUID:
    campaign_id = await _campaign(account)
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c"),
            {"s": GUIDED.model_dump_json(), "c": campaign_id},
        )
    return campaign_id


async def test_the_campaign_route_reads_the_script_and_keeps_the_owners_choice() -> None:
    account = await _account()
    campaign_id = await _guided_campaign(account)
    url = f"/v1/campaigns/{campaign_id}/give-callers-time"
    async with _client() as client:
        read = await client.get(url, headers=account.headers)
        off = await client.put(url, json={"on": False}, headers=account.headers)
        again = await client.get(url, headers=account.headers)
    assert read.status_code == 200, read.text
    assert (read.json()["on"], read.json()["owner_choice"], read.json()["script_asks"]) == (
        True,
        None,
        True,
    )
    assert read.json()["end_after_silence_seconds"] == gct.END_AFTER_SILENCE_S
    assert off.status_code == 200, off.text
    assert (off.json()["on"], off.json()["owner_choice"]) == (False, False)
    assert again.json()["on"] is False and again.json()["script_asks"] is True
    async with tenant_session(account.tenant_id) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'campaign.give_callers_time' "
                    "AND object_id = :c"
                ),
                {"c": str(campaign_id)},
            )
        ).scalar_one()
    assert audited == 1


async def test_the_line_route_switches_it_for_the_line() -> None:
    account = await _account()
    line_id = await _line(account.tenant_id, account.agent_id)
    url = f"/v1/inbound-lines/{line_id}/give-callers-time"
    async with _client() as client:
        read = await client.get(url, headers=account.headers)
        on = await client.put(url, json={"on": True}, headers=account.headers)
    assert read.status_code == 200, read.text
    assert read.json()["owner_choice"] is None
    assert on.status_code == 200, on.text
    assert (on.json()["on"], on.json()["owner_choice"]) == (True, True)


def test_the_preset_is_in_the_platform_revision_so_live_holders_are_republished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = live_apply.platform_prompt_revision()
    monkeypatch.setattr(gct, "END_AFTER_SILENCE_S", gct.END_AFTER_SILENCE_S + 10)
    assert live_apply.platform_prompt_revision() != before


# --- 2. Acknowledgements off ----------------------------------------------------------------


def test_acknowledgements_default_off_end_to_end() -> None:
    assert Settings.model_fields["thinnest_acknowledgements"].default is False
    assert AgentConfig.model_fields["acknowledgements"].default is False
    # A deploy that moves the default walks the fleet once.
    assert "thinnest_acknowledgements" in live_apply.ENGINE_CONSOLE_DEFAULT_KEYS


ACK_MIGRATION = "d0f6b2c4a5e7_acknowledgements_console_row_follows_new_default"


def _console_row(connection: Any, admin_id: uuid.UUID, value: str) -> None:
    connection.execute(
        text(
            "INSERT INTO platform_settings (key, value, updated_by, note) "
            "VALUES ('thinnest_acknowledgements', CAST(:v AS jsonb), :by, 'test') "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"v": value, "by": admin_id},
    )


def _stored(connection: Any) -> Any:
    return connection.execute(
        text("SELECT value FROM platform_settings WHERE key = 'thinnest_acknowledgements'")
    ).scalar()


async def test_a_console_row_holding_the_old_default_follows_the_new_one() -> None:
    migration = load_revision(ACK_MIGRATION)
    with rls_bound_owner() as (connection, _become):
        admin_id = uuid.uuid4()
        connection.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ack Test', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
        with Operations.context(MigrationContext.configure(connection)):
            _console_row(connection, admin_id, "true")
            migration.upgrade()
            assert _stored(connection) is None
            _console_row(connection, admin_id, "false")
            migration.upgrade()
            assert _stored(connection) is False


# --- 3. Spread retries on existing campaigns ------------------------------------------------

SPREAD_MIGRATION = "c9e5a1b3f4d6_spread_retries_on_existing_campaigns"
OLD_DEFAULT = {"max_attempts": 3, "backoff_minutes": [30, 120]}


def _policy(connection: Any, campaign_id: uuid.UUID) -> Any:
    raw = connection.execute(
        text("SELECT retry_policy FROM campaigns WHERE id = :c"), {"c": campaign_id}
    ).scalar()
    return raw if raw is None or isinstance(raw, dict) else json.loads(raw)


async def test_spread_turns_on_only_where_the_retry_settings_were_never_changed() -> None:
    account = await _account()
    untouched, nulled, owner_off, changed, archived = [await _campaign(account) for _ in range(5)]
    migration = load_revision(SPREAD_MIGRATION)
    with rls_bound_owner() as (connection, become):
        arranged = {
            untouched: OLD_DEFAULT,
            nulled: None,
            owner_off: {**OLD_DEFAULT, "spread": False},
            changed: {"max_attempts": 4, "backoff_minutes": [60, 240]},
            archived: OLD_DEFAULT,
        }
        for campaign_id, policy in arranged.items():
            connection.execute(
                text("UPDATE campaigns SET retry_policy = CAST(:p AS jsonb) WHERE id = :c"),
                {"p": None if policy is None else json.dumps(policy), "c": campaign_id},
            )
        connection.execute(
            text(
                "UPDATE campaigns SET archived_at = now(), archived_by_realm = 'client' "
                "WHERE id = :c"
            ),
            {"c": archived},
        )
        become()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            connection.execute(text("RESET ROLE"))
            for campaign_id in (untouched, nulled):
                policy = _policy(connection, campaign_id)
                assert policy["spread"] is True
                assert (policy["max_attempts"], policy["backoff_minutes"]) == (3, [30, 120])
            assert _policy(connection, owner_off)["spread"] is False
            assert "spread" not in _policy(connection, changed)
            assert "spread" not in _policy(connection, archived)

            become()
            migration.downgrade()
            connection.execute(text("RESET ROLE"))
            assert _policy(connection, untouched) == OLD_DEFAULT
            assert _policy(connection, nulled) == OLD_DEFAULT
            assert _policy(connection, owner_off) == {**OLD_DEFAULT, "spread": False}


# --- 4. A new second opening starts fresh ---------------------------------------------------


async def test_a_new_second_opening_counts_only_calls_after_it_was_saved() -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    await _with_test(account, campaign_id)
    # The earlier test's calls, each person labelled with their opening.
    await _opening_trial(account, campaign_id, side="a", answered=5, stayed=3, first=0)
    await _opening_trial(account, campaign_id, side="b", answered=5, stayed=4, first=100)
    async with tenant_session(account.tenant_id) as session:
        earlier = await learning.opening_results(session, campaign_id)
    assert [r.people for r in earlier] == [5, 5], "a test with no start counts every call"

    new_line = f"{SECOND_OPENING} A fresh one."
    assert new_line != OWN_OPENING
    async with _client() as client:
        saved = await client.put(
            f"/v1/campaigns/{campaign_id}/opening-b",
            json={"opening_b": new_line},
            headers=account.headers,
        )
    assert saved.status_code == 204, saved.text
    async with tenant_session(account.tenant_id) as session:
        fresh = await learning.opening_results(session, campaign_id)
    assert [r.people for r in fresh] == [0, 0]

    # Saving the same line again is the same test: its start does not move.
    async with tenant_session(account.tenant_id) as session:
        started = (
            await session.execute(
                text("SELECT opening_test_started_at FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
    async with _client() as client:
        await client.put(
            f"/v1/campaigns/{campaign_id}/opening-b",
            json={"opening_b": new_line},
            headers=account.headers,
        )
    async with tenant_session(account.tenant_id) as session:
        kept = (
            await session.execute(
                text("SELECT opening_test_started_at FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
    assert started is not None and kept == started

    # A call placed in the new test counts.
    await _opening_trial(account, campaign_id, side="b", answered=2, stayed=1, first=500)
    async with tenant_session(account.tenant_id) as session:
        counted = await learning.opening_results(session, campaign_id)
    assert [r.people for r in counted] == [0, 2]


# --- 5. The WhatsApp follow-up's set-up is the owner's --------------------------------------


def _permission(method: str, path: str) -> object:
    route = next(
        r
        for r in follow_up_router.routes
        if isinstance(r, APIRoute) and r.path == path and method in r.methods
    )
    return (route.openapi_extra or {}).get("x-calevate-permission")


def test_setting_up_takes_the_template_permission_and_switching_stays_with_dispatch() -> None:
    assert TEMPLATE_PERMISSION == "org:manage"
    base = "/v1/campaigns/{campaign_id}/whatsapp-follow-up"
    assert _permission("POST", base) == TEMPLATE_PERMISSION
    assert _permission("POST", f"{base}/switch") == "leads:dispatch"
    assert _permission("GET", base) == "leads:read"
    tool = write_tools.tool_named("follow_up_campaign_whatsapp")
    assert tool is not None and tool.permission == TEMPLATE_PERMISSION
