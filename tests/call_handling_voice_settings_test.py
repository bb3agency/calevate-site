"""The client's voice settings (founder decisions F3, F9, 12 Oct 2026) on the D-751 pattern.

If the caller goes quiet (ask after N seconds or never, how many times, in whose words, and
when to hang up), the lines said while the agent looks something up, and a background office
sound: resolved agent -> account -> Calevate, stored in range, refused in plain words, carried
into the published config, and a change queues the live apply.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.agents import prompts
from apps.api.agents.call_handling import (
    PLATFORM_SETTINGS,
    SETTING_FIELDS,
    CallSettings,
    resolve_settings,
)
from apps.api.agents.call_handling_routes import _audit_summary
from apps.api.agents.service import _load_agent, _to_config
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.call_handling_test import _client, _make_live, _operator, _runs, _tenant

# --- resolution ----------------------------------------------------------------------


def test_calevates_defaults_are_the_founders() -> None:
    """F9: ask once after 8 seconds, hang up after 20; the platform's question and lines; no
    background sound, at 15% once switched on."""
    p = PLATFORM_SETTINGS
    assert (p.nudge_after_seconds, p.nudge_count, p.end_after_silence_seconds) == (8, 1, 20)
    assert (p.nudge_phrase, p.filler_lines) == ("", ())
    assert (p.ambience, p.ambience_volume_pct) == ("off", 15)
    assert set(SETTING_FIELDS) == set(CallSettings.__dataclass_fields__)


def test_a_choice_that_means_the_platforms_own_still_wins_over_the_account() -> None:
    """0, '' and [] are choices, not absences: an agent saying "never ask", "the standard
    question" or "the standard lines" beats an account that says otherwise."""
    account = CallSettings(
        nudge_after_seconds=30, nudge_phrase="Hello?", filler_lines=("One moment",)
    )
    own = CallSettings(nudge_after_seconds=0, nudge_phrase="", filler_lines=())
    resolved = resolve_settings(own, account)
    assert resolved.values.nudge_after_seconds == 0
    assert resolved.values.nudge_phrase == ""
    assert resolved.values.filler_lines == ()
    assert resolved.sources["nudge_after_seconds"] == "agent"
    inherited = resolve_settings(CallSettings(), account)
    assert inherited.values.nudge_phrase == "Hello?"
    assert inherited.sources["nudge_phrase"] == "organization"
    assert resolve_settings(CallSettings(), CallSettings()).sources["ambience"] == "platform"


# --- storage -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "bad"),
    [
        ("nudge_after_seconds", 4),
        ("nudge_after_seconds", 181),
        ("nudge_count", 0),
        ("nudge_count", 6),
        ("nudge_phrase", "x" * 121),
        ("end_after_silence_seconds", 4),
        ("end_after_silence_seconds", 181),
        ("filler_lines", ["a"] * 9),
        ("ambience", "beach"),
        ("ambience_volume_pct", 4),
        ("ambience_volume_pct", 101),
    ],
)
async def test_the_columns_hold_the_vendor_ranges(column: str, bad: object) -> None:
    tenant_id, agent_id, _ = await _tenant()
    for table, name, row_id in (
        ("agents", column, agent_id),
        ("organizations", f"default_{column}", tenant_id),
    ):
        with pytest.raises(IntegrityError):
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(f"UPDATE {table} SET {name} = :v WHERE id = :id"),
                    {"v": bad, "id": row_id},
                )


async def test_never_ask_and_the_edges_of_each_range_are_stored() -> None:
    tenant_id, agent_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET nudge_after_seconds = 0, nudge_count = 5, "
                "end_after_silence_seconds = 180, filler_lines = :lines, ambience = 'off', "
                "ambience_volume_pct = 100, nudge_phrase = '' WHERE id = :id"
            ),
            {"lines": ["x" * 60] * 8, "id": agent_id},
        )


# --- routes --------------------------------------------------------------------------


async def test_an_agent_takes_each_setting_and_says_where_it_comes_from() -> None:
    _tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        first = (await client.get(f"/v1/agents/{agent_id}/call-handling", headers=headers)).json()
        assert first["nudge_after_seconds"] is None
        assert first["nudge_after_seconds_effective"] == 8
        assert first["nudge_after_seconds_source"] == "platform"
        assert first["filler_lines_effective"] == []
        assert first["ambience_effective"] == "off"
        assert first["bounds"]["nudge_after_max_s"] == 180
        assert first["bounds"]["ambiences"] == ["off", "office", "office-quiet"]

        org = await client.put(
            "/v1/organization/call-handling",
            headers=headers,
            json={
                "turn_silence_ms": None,
                "end_call_on_finish": None,
                "nudge_after_seconds": 12,
                "ambience": "office",
                "ambience_volume_pct": 30,
            },
        )
        assert org.status_code == 200, org.text
        assert org.json()["nudge_after_seconds_effective"] == 12
        assert org.json()["ambience_effective"] == "office"

        patched = await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={
                "nudge_count": 2,
                "nudge_phrase": "  Are you there?  ",
                "filler_lines": [" One moment please ", "", "Let me check"],
                "end_after_silence_seconds": 45,
            },
        )
        assert patched.status_code == 200, patched.text
        got = patched.json()
        assert got["nudge_count"] == 2 and got["nudge_count_source"] == "agent"
        assert got["nudge_after_seconds_source"] == "organization"
        assert got["organization_nudge_after_seconds"] == 12
        assert got["filler_lines"] == ["One moment please", "Let me check"]
        assert got["nudge_phrase"] == "Are you there?"
        assert got["ambience_effective"] == "office"
        assert got["ambience_source"] == "organization"
        assert got["end_after_silence_seconds_effective"] == 45

        # A blank phrase is the platform's own, never a phrase of spaces.
        blank = await client.patch(
            f"/v1/agents/{agent_id}/call-handling", headers=headers, json={"nudge_phrase": "   "}
        )
        assert blank.status_code == 200, blank.text
        assert blank.json()["nudge_phrase"] == ""

        # A field left out of the account PUT is kept.
        kept = await client.put(
            "/v1/organization/call-handling",
            headers=headers,
            json={"turn_silence_ms": 400, "end_call_on_finish": None},
        )
        assert kept.json()["ambience"] == "office"
        assert kept.json()["nudge_after_seconds"] == 12
    # The client's own words are counted in the audit summary (which reaches the log
    # stream), never copied.
    summary = _audit_summary(
        {"nudge_phrase": "Are you there?", "filler_lines": ["One moment"], "nudge_count": 2},
        ("nudge_phrase",),
    )
    assert summary == {
        "nudge_count": 2,
        "nudge_phrase_chars": 14,
        "filler_lines_count": 1,
        "changed": ["nudge_phrase"],
    }


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"nudge_after_seconds": 3}, "nudge_after_seconds"),
        ({"nudge_after_seconds": 181}, "nudge_after_seconds"),
        ({"nudge_count": 6}, "nudge_count"),
        ({"nudge_phrase": "x" * 121}, "nudge_phrase"),
        ({"end_after_silence_seconds": 2}, "end_after_silence_seconds"),
        ({"filler_lines": ["a"] * 9}, "filler_lines"),
        ({"filler_lines": ["x" * 61]}, "filler_lines"),
        ({"ambience_volume_pct": 2}, "ambience_volume_pct"),
    ],
)
async def test_an_out_of_range_setting_is_a_plain_problem(
    body: dict[str, object], field: str
) -> None:
    _tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        for method, path, payload in (
            ("PATCH", f"/v1/agents/{agent_id}/call-handling", body),
            (
                "PUT",
                "/v1/organization/call-handling",
                {"turn_silence_ms": None, "end_call_on_finish": None, **body},
            ),
        ):
            response = await client.request(method, path, headers=headers, json=payload)
            assert response.status_code == 422, response.text
            assert response.headers["content-type"].startswith("application/problem+json")
            problem = response.json()
            assert problem["type"].endswith("/call_setting_out_of_range")
            assert problem["detail"]
            assert "thinnest" not in response.text.lower()


async def test_an_unknown_sound_is_refused() -> None:
    _tenant_id, agent_id, headers = await _tenant()
    async with _client() as client:
        response = await client.patch(
            f"/v1/agents/{agent_id}/call-handling", headers=headers, json={"ambience": "beach"}
        )
    assert response.status_code == 422


async def test_a_new_setting_queues_the_live_apply_once() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    async with _client() as client:
        await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"filler_lines": ["One moment"]},
        )
        assert await _runs(tenant_id) == [("agent", agent_id, ["call_handling"])]
        await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"filler_lines": ["One moment "]},
        )
        assert len(await _runs(tenant_id)) == 1, "the same line again moves nothing"


async def test_an_account_sound_queues_the_client_when_a_live_agent_inherits_it() -> None:
    tenant_id, agent_id, headers = await _tenant()
    await _make_live(tenant_id, agent_id)
    async with _client() as client:
        await client.put(
            "/v1/organization/call-handling",
            headers=headers,
            json={"turn_silence_ms": None, "end_call_on_finish": None, "ambience": "office"},
        )
    assert await _runs(tenant_id) == [("tenant", None, ["call_handling"])]


async def test_an_operator_sets_them_through_the_admin_door() -> None:
    tenant_id, agent_id, _ = await _tenant()
    headers = await _operator()
    async with _client() as client:
        set_ = await client.patch(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/call-handling",
            headers=headers,
            json={"nudge_after_seconds": 0},
        )
        assert set_.status_code == 200, set_.text
        assert set_.json()["nudge_after_seconds_effective"] == 0


# --- the published config ------------------------------------------------------------


async def test_the_published_config_carries_the_resolved_settings() -> None:
    tenant_id, agent_id, headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and take their order.",
            notes=None,
            created_by=None,
        )

    async def config() -> tuple[object, ...]:
        async with tenant_session(tenant_id) as session:
            row = await _load_agent(session, tenant_id, agent_id)
        cfg = _to_config(tenant_id, row, engine=get_engine())
        return (
            cfg.nudge_after_seconds,
            cfg.nudge_count,
            cfg.nudge_phrase,
            cfg.end_after_silence_seconds,
            cfg.filler_lines,
            cfg.ambience,
            cfg.ambience_volume_pct,
            cfg.has_phone_number,
        )

    # No lines of the client's own: ours in the agent's language (founder, 23 Oct 2026), so a
    # Telugu call is never covered by the engine's English filler.
    assert await config() == (8, 1, None, 20, ("ఒక్క సెకండ్ అండి",), None, 15, False)
    async with _client() as client:
        await client.put(
            "/v1/organization/call-handling",
            headers=headers,
            json={
                "turn_silence_ms": None,
                "end_call_on_finish": None,
                "nudge_after_seconds": 0,
                "ambience": "office-quiet",
                "ambience_volume_pct": 40,
            },
        )
        await client.patch(
            f"/v1/agents/{agent_id}/call-handling",
            headers=headers,
            json={"nudge_phrase": "Hello, are you there?", "filler_lines": ["One moment"]},
        )
    # Never asking is no `nudge_after_seconds`; the client's question and lines travel.
    assert await config() == (
        None,
        1,
        "Hello, are you there?",
        20,
        ("One moment",),
        "office-quiet",
        40,
        False,
    )


async def test_an_attached_engine_number_is_reported_to_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1 reads it: an agent gets the phone surface only once the platform holds one of its
    numbers for it, as its line or lent to call out on (D-789). A released number, a number
    in another workspace, or a carrier number does not count."""
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, agent_id, _ = await _tenant()

    async def attached() -> bool:
        async with tenant_session(tenant_id) as session:
            row = await _load_agent(session, tenant_id, agent_id)
        return bool(row.get("has_phone_number"))

    assert await attached() is False
    number_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, provider, "
                "engine_number_ref, released_at, created_at, updated_at) VALUES (:id, :tid, "
                ":aid, :e164, 'thinnest', :ref, now(), now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e164": f"+9180{uuid.uuid4().int % 10**8:08d}",
                "ref": f"{uuid.uuid4().int % 10**10}",
            },
        )
    assert await attached() is False, "a released number is not attached"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET released_at = NULL WHERE id = :id"), {"id": number_id}
        )
    # Not live yet: the platform has not attached it, so the agent does not answer on it.
    assert await attached() is False
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'inbound', "
                "engine_agent_ref = :ref WHERE id = :aid"
            ),
            {"ref": f"ag_{agent_id.hex[:12]}", "aid": agent_id},
        )
    assert await attached() is True
    # An outbound-only agent is lent the number to call out on, and the platform places calls
    # only from an agent with the phone surface (D-789).
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'outbound' WHERE id = :aid"), {"aid": agent_id}
        )
    assert await attached() is True
    # A number in another workspace than the agent's answers nobody.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'both', engine_agent_ref = :ref WHERE id = :aid"),
            {"ref": f"ag_{agent_id.hex[:12]}@org_{uuid.uuid4().hex[:16]}", "aid": agent_id},
        )
    assert await attached() is False


def test_the_platform_filler_lines_follow_the_agents_languages_and_the_clients_win() -> None:
    from apps.api.agents.call_handling import CallSettings
    from apps.api.agents.service import _call_settings_fields

    def lines(own: tuple[str, ...] | None, languages: tuple[str, ...]) -> object:
        row = {"call_settings": CallSettings(filler_lines=own)}
        return _call_settings_fields(row, languages=languages)["filler_lines"]  # type: ignore[arg-type]

    assert lines(None, ("te-IN", "hi-IN")) == ("ఒక్క సెకండ్ అండి", "एक minute जी")
    # The client's "the standard lines" ([]) is ours too; their own lines win.
    assert lines((), ("hi-IN",)) == ("एक minute जी",)
    assert lines(("One moment",), ("te-IN",)) == ("One moment",)
    # English has no line of ours: the engine keeps its own English filler.
    assert lines(None, ("en-IN",)) == ()
