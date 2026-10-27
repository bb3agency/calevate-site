"""A call's English, asked for again, and the one-time backfill (founder decisions 2 and 3,
11 Oct 2026); and saving a recording (founder, 11 Oct 2026).

What is pinned: "Try again" is owner-gated, quota-gated, idempotent and RLS-scoped; the job
translates from the REDACTED words and bills the payer it was given; the backfill takes the
newest untranslated calls of the last 30 days, once each, at our cost; the download link is
the same audited, owner-only object as playback, with its own audit action and a filename
that never carries the caller's number.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest import mock
from uuid import UUID

import pytest
from apps.api.billing import ai_quota, rates
from apps.api.billing.models import (
    ABSORBED_ASSIST_FEATURES,
    ASSIST_FEATURE_CALL_LANGUAGE,
    ASSIST_FEATURE_CALL_TRANSLATION,
)
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.crm import recording_download, translation
from apps.api.crm.translation import TRANSLATE_CALL_JOB
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import call_language, call_translation, chat
from apps.workers.call_language import LanguagePass
from calevate_shared.engine import SARVAM_DEFAULT_LLM
from sqlalchemy import text
from tests.lead_dial_routes_test import (
    _client,
    _dialable_tenant,
    _finished_call,
    _lead,
    _staff_of,
)

PHONE_SAID = "9876543210"
TELUGU_LINE = f"నా నంబర్ {PHONE_SAID} అండి"
TELUGU_REDACTED = "నా నంబర్ [phone ••10] అండి"


@pytest.fixture(autouse=True)
def _brake_released(monkeypatch: pytest.MonkeyPatch) -> None:
    """`platform_ai_spend` is shared with every suite on this database; `call_assist_test`
    severs the same dependency for the same reason."""

    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


async def _telugu_call(
    *, state: str = "failed", started: datetime | None = None
) -> tuple[UUID, UUID, str, dict[str, str]]:
    tenant_id, agent_id, slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET translation_state = :s, started_at = :at, "
                "summary_local = NULL WHERE id = :c"
            ),
            {"s": state, "at": started or datetime.now(UTC), "c": call_id},
        )
        for idx, (speaker, raw, red) in enumerate(
            [("agent", "నమస్కారం అండి", "నమస్కారం అండి"), ("caller", TELUGU_LINE, TELUGU_REDACTED)]
        ):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:id, :tid, :cid, :idx, "
                    ":speaker, :raw, :red, now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "idx": idx,
                    "speaker": speaker,
                    "raw": raw,
                    "red": red,
                },
            )
    return tenant_id, call_id, slug, headers


async def _state(tenant_id: UUID, call_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT translation_state FROM calls WHERE id = :c"), {"c": call_id}
                )
            ).scalar()
        )


async def _outbox_rows(call_id: UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'call_id' = :cid"
                    ),
                    {"job": TRANSLATE_CALL_JOB, "cid": str(call_id)},
                )
            ).scalar()
            or 0
        )


async def _audits(action: str, call_id: UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE action = :a AND object_id = :o"),
                    {"a": action, "o": str(call_id)},
                )
            ).scalar()
            or 0
        )


def _stub_pass(
    monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any], *, failed: bool = False
) -> None:
    async def _pass(**kwargs: Any) -> LanguagePass:
        seen.update(kwargs)
        return LanguagePass(
            turns_en={idx: f"english {idx}" for idx, _ in kwargs["turns"]},
            summary_local="తెలుగు సారాంశం" if kwargs["summary_en"] else "",
            failed=failed,
        )

    monkeypatch.setattr(call_language, "run_language_pass", _pass)
    monkeypatch.setattr(
        call_translation, "get_settings", lambda: SimpleNamespace(sarvam_api_key="k")
    )


# --- "Try again" ---------------------------------------------------------------------


async def test_try_again_queues_once_and_a_second_press_queues_nothing() -> None:
    tenant_id, call_id, _slug, headers = await _telugu_call()
    async with _client() as http:
        first = await http.post(f"/v1/calls/{call_id}/translation", headers=headers)
        second = await http.post(f"/v1/calls/{call_id}/translation", headers=headers)

    assert first.status_code == 202, first.text
    assert first.json() == {"translation_state": "pending"}
    assert second.status_code == 202 and second.json() == {"translation_state": "pending"}
    assert await _state(tenant_id, call_id) == "pending"
    assert await _outbox_rows(call_id) == 1, "a double press must not queue twice"
    assert await _audits("call.translation_requested", call_id) == 1


async def test_try_again_on_a_translated_call_answers_its_state_and_queues_nothing() -> None:
    _tenant_id, call_id, _slug, headers = await _telugu_call(state="ready")
    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/translation", headers=headers)
    assert response.status_code == 202 and response.json() == {"translation_state": "ready"}
    assert await _outbox_rows(call_id) == 0


async def test_staff_cannot_spend_the_allowance_on_a_translation() -> None:
    tenant_id, call_id, slug, _headers = await _telugu_call()
    staff = await _staff_of(tenant_id, slug)
    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/translation", headers=staff)
    assert response.status_code == 403, response.text
    assert await _state(tenant_id, call_id) == "failed"
    assert await _outbox_rows(call_id) == 0


async def test_at_the_ceiling_nothing_is_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, call_id, _slug, headers = await _telugu_call()

    async def _refuse(*args: Any, **kwargs: Any) -> None:
        raise ProblemError.business_rule("ai_quota_exceeded", "This account is at its limit.")

    monkeypatch.setattr(translation, "require_ai_assist", _refuse)
    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/translation", headers=headers)
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("ai_quota_exceeded")
    assert await _state(tenant_id, call_id) == "failed"
    assert await _outbox_rows(call_id) == 0


async def test_another_clients_call_is_not_found() -> None:
    _tenant_id, call_id, _slug, _headers = await _telugu_call()
    _other, _agent, _other_slug, other_headers = await _dialable_tenant()
    async with _client() as http:
        response = await http.post(f"/v1/calls/{call_id}/translation", headers=other_headers)
    assert response.status_code == 404, response.text
    assert await _outbox_rows(call_id) == 0


# --- the job -------------------------------------------------------------------------


async def test_the_job_translates_redacted_words_and_bills_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id, _slug, headers = await _telugu_call()
    async with _client() as http:
        await http.post(f"/v1/calls/{call_id}/translation", headers=headers)
    seen: dict[str, Any] = {}
    _stub_pass(monkeypatch, seen)
    billed: list[str] = []

    async def _meter(*args: Any, feature: str, **kwargs: Any) -> None:
        billed.append(feature)

    monkeypatch.setattr(call_translation, "meter_language_pass", _meter)
    # The stub reports no usage, so the meter is asserted through a usage-bearing pass.
    original = call_language.run_language_pass

    async def _with_usage(**kwargs: Any) -> LanguagePass:
        done = await original(**kwargs)
        done.usage = SimpleNamespace(prompt_tokens=10, output_tokens=5, cached_prompt_tokens=0)  # type: ignore[assignment]
        return done

    monkeypatch.setattr(call_language, "run_language_pass", _with_usage)

    payload = {"tenant_id": str(tenant_id), "call_id": str(call_id), "payer": "client"}
    assert await call_translation.translate_call_job({"job_try": 1}, payload) == "ready"

    assert all(PHONE_SAID not in body for _, body in seen["turns"]), "redacted text only"
    assert billed == [ASSIST_FEATURE_CALL_TRANSLATION]
    assert ASSIST_FEATURE_CALL_TRANSLATION not in ABSORBED_ASSIST_FEATURES
    async with tenant_session(tenant_id) as session:
        turns = (
            await session.execute(
                text("SELECT idx, text_en FROM transcript_turns WHERE call_id = :c ORDER BY idx"),
                {"c": call_id},
            )
        ).all()
    assert [t[1] for t in turns] == ["english 0", "english 1"]
    assert await _state(tenant_id, call_id) == "ready"
    # A second delivery of the same message finds nothing pending and spends nothing.
    assert await call_translation.translate_call_job({"job_try": 1}, payload) == "skipped"
    assert billed == [ASSIST_FEATURE_CALL_TRANSLATION]


async def test_the_charge_commits_with_the_english_or_not_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the pass is metered in a transaction of its own. A result write that then
    fails sends the job round again, the pass runs again under a fresh ref, and the owner
    is charged twice for one translation."""
    tenant_id, call_id, _slug, headers = await _telugu_call()
    async with _client() as http:
        await http.post(f"/v1/calls/{call_id}/translation", headers=headers)
    _stub_pass(monkeypatch, {})
    original = call_language.run_language_pass

    async def _with_usage(**kwargs: Any) -> LanguagePass:
        done = await original(**kwargs)
        done.usage = SimpleNamespace(prompt_tokens=10, output_tokens=5, cached_prompt_tokens=0)  # type: ignore[assignment]
        return done

    monkeypatch.setattr(call_language, "run_language_pass", _with_usage)
    seen: dict[str, Any] = {}

    async def _meter(session: Any, *args: Any, feature: str, **kwargs: Any) -> None:
        sql = "SELECT count(text_en) FROM transcript_turns WHERE call_id = :c"
        seen["inside"] = (await session.execute(text(sql), {"c": call_id})).scalar()
        async with tenant_session(tenant_id) as other:
            seen["outside"] = (await other.execute(text(sql), {"c": call_id})).scalar()

    monkeypatch.setattr(call_translation, "meter_language_pass", _meter)
    payload = {"tenant_id": str(tenant_id), "call_id": str(call_id), "payer": "client"}
    assert await call_translation.translate_call_job({"job_try": 1}, payload) == "ready"
    assert seen == {"inside": 2, "outside": 0}, "metered in the transaction writing the English"


async def test_a_provider_failure_leaves_try_again_on_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id, _slug, headers = await _telugu_call()
    async with _client() as http:
        await http.post(f"/v1/calls/{call_id}/translation", headers=headers)
    _stub_pass(monkeypatch, {}, failed=True)
    payload = {"tenant_id": str(tenant_id), "call_id": str(call_id), "payer": "client"}
    assert await call_translation.translate_call_job({"job_try": 1}, payload) == "failed"
    assert await _state(tenant_id, call_id) == "failed"


async def test_the_last_attempt_of_a_crashing_job_says_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id, _slug, headers = await _telugu_call()
    async with _client() as http:
        await http.post(f"/v1/calls/{call_id}/translation", headers=headers)

    async def _crash(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("database went away")

    monkeypatch.setattr(call_translation, "translate_call", _crash)
    payload = {"tenant_id": str(tenant_id), "call_id": str(call_id), "payer": "client"}
    with pytest.raises(call_translation.Retry):
        await call_translation.translate_call_job({"job_try": 1}, payload)
    assert await _state(tenant_id, call_id) == "pending"
    assert await call_translation.translate_call_job({"job_try": 3}, payload) == "failed"
    assert await _state(tenant_id, call_id) == "failed"


# --- the backfill --------------------------------------------------------------------


async def test_the_backfill_queues_the_newest_untranslated_calls_once_at_our_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    tenant_id, newest, _slug, _headers = await _telugu_call(state="unavailable", started=now)
    _t2, older, _s2, _h2 = await _telugu_call(state="failed", started=now - timedelta(days=3))
    _t3, too_old, _s3, _h3 = await _telugu_call(state="failed", started=now - timedelta(days=31))
    _t4, done, _s4, _h4 = await _telugu_call(state="ready", started=now)
    queued: list[dict[str, str]] = []

    async def _enqueue(job: str, payload: dict[str, str], *, job_id: str) -> str:
        assert job == TRANSLATE_CALL_JOB
        queued.append(payload)
        return job_id

    monkeypatch.setattr(call_translation, "enqueue", _enqueue)
    monkeypatch.setattr(call_translation, "BACKFILL_BATCH", 500)
    for call_id in (newest, older):
        await get_redis().delete(f"call_translation:backfilled:{call_id}")

    await call_translation.backfill_call_translations({})
    ids = [p["call_id"] for p in queued]
    assert str(newest) in ids and str(older) in ids
    assert ids.index(str(newest)) < ids.index(str(older)), "newest first"
    assert str(too_old) not in ids and str(done) not in ids
    assert {p["payer"] for p in queued if p["call_id"] in (str(newest), str(older))} == {"platform"}

    seen: dict[str, Any] = {}
    _stub_pass(monkeypatch, seen)
    billed: list[str] = []

    async def _meter(*args: Any, feature: str, **kwargs: Any) -> None:
        billed.append(feature)

    monkeypatch.setattr(call_translation, "meter_language_pass", _meter)
    payload = next(p for p in queued if p["call_id"] == str(newest))
    assert await call_translation.translate_call_job({"job_try": 1}, payload) == "ready"
    assert ASSIST_FEATURE_CALL_LANGUAGE in ABSORBED_ASSIST_FEATURES
    # The same call queued again is refused by the claim: once per call, ever.
    assert await call_translation.translate_call_job({"job_try": 1}, payload) == "skipped"
    assert await _state(tenant_id, newest) == "ready"

    queued.clear()
    await call_translation.backfill_call_translations({})
    assert str(newest) not in [p["call_id"] for p in queued]


# --- the call's language -------------------------------------------------------------


async def test_the_call_detail_names_the_calls_language() -> None:
    _tenant_id, call_id, _slug, headers = await _telugu_call()
    async with _client() as http:
        response = await http.get(f"/v1/calls/{call_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["language"] == "te-IN"


# --- downloading the recording -------------------------------------------------------


def _presign_capture(captured: dict[str, Any]) -> Any:
    def _presign(key: str, *, ttl_s: int, disposition: str = "attachment") -> str:
        captured.update(key=key, ttl_s=ttl_s, disposition=disposition)
        return f"https://s3/{key}?X-Amz-Signature=x"

    return _presign


async def test_the_download_is_an_attachment_with_a_safe_name_and_its_own_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id, slug, headers = await _telugu_call()
    started = datetime(2026, 10, 11, 12, 16, tzinfo=UTC)  # 17:46 IST
    key = f"recordings/{tenant_id}/{call_id}.mp3"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET recording_url = :k, started_at = :at WHERE id = :i"),
            {"k": key, "at": started, "i": call_id},
        )
        phone = (
            await session.execute(text("SELECT to_e164 FROM calls WHERE id = :i"), {"i": call_id})
        ).scalar()
    captured: dict[str, Any] = {}
    monkeypatch.setattr("apps.workers.storage.presigned_url", _presign_capture(captured))
    staff = await _staff_of(tenant_id, slug)

    async with _client() as http:
        refused = await http.get(f"/v1/calls/{call_id}/recording/download", headers=staff)
        assert refused.status_code == 403, refused.text
        assert not captured, "the gate refuses before anything is signed"
        response = await http.get(f"/v1/calls/{call_id}/recording/download", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"] == "dial-clinic-call-2026-10-11-1746.mp3"
    assert captured["disposition"] == f'attachment; filename="{body["filename"]}"'
    assert captured["key"] == key
    assert 0 < body["expires_in_s"] <= 300 and captured["ttl_s"] == body["expires_in_s"]
    assert str(phone).lstrip("+") not in response.text, "no caller number in the name"
    assert await _audits("recording.download", call_id) == 1
    assert await _audits("recording.read", call_id) == 0, "a download is not a listen"


async def test_a_deleted_recording_says_it_is_no_longer_kept() -> None:
    _tenant_id, call_id, _slug, headers = await _telugu_call(
        started=datetime.now(UTC) - timedelta(days=91)
    )
    _t2, never, _s2, headers2 = await _telugu_call()
    with mock.patch.dict(
        os.environ,
        {"AWS_ACCESS_KEY_ID": "test-access-key", "AWS_SECRET_ACCESS_KEY": "test-secret-key"},
    ):
        async with _client() as http:
            expired = await http.get(f"/v1/calls/{call_id}/recording/download", headers=headers)
            missing = await http.get(f"/v1/calls/{never}/recording/download", headers=headers2)
    assert expired.status_code == 404, expired.text
    assert expired.json()["type"].endswith("recording_expired")
    assert "90 days" in expired.json()["detail"]
    assert missing.status_code == 404 and missing.json()["title"] == "Recording not found"
    assert await _audits("recording.download", call_id) == 0


def test_the_filename_falls_back_to_the_slug_and_never_trusts_the_key() -> None:
    at = datetime(2026, 10, 11, 0, 0, tzinfo=UTC)
    name = recording_download.download_filename(
        business="రాఘవ ఆర్గానిక్స్", slug="raghava", at=at, key="recordings/x/y.mp3"
    )
    assert name == "raghava-call-2026-10-11-0530.mp3"
    odd = recording_download.download_filename(
        business='Shop "A"; x', slug="s", at=at, key=f"recordings/{uuid.uuid4()}"
    )
    assert odd == "shop-a-x-call-2026-10-11-0530.audio"
    assert '"' not in odd and ";" not in odd


async def test_the_backfill_reaches_past_calls_it_has_already_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backfill tries each call once and reads newest first. Calls it has already
    tried stay `failed`, so a page of them used to fill every read and the older calls it
    had never tried were never reached."""
    now = datetime.now(UTC)
    tenant_id, untried, _slug, _headers = await _telugu_call(
        state="failed", started=now - timedelta(days=2)
    )
    async with tenant_session(tenant_id) as session:
        agent_id, lead_id, phone = (
            await session.execute(
                text("SELECT agent_id, lead_id, to_e164 FROM calls WHERE id = :c"),
                {"c": untried},
            )
        ).one()
    tried = []
    for hours in (1, 2, 3):
        call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)
        tried.append(call_id)
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE calls SET translation_state = 'failed', started_at = :at WHERE id = :c"
                ),
                {"at": now - timedelta(hours=hours), "c": call_id},
            )
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:id, :tid, :cid, 0, "
                    "'caller', :t, :t, now(), now())"
                ),
                {"id": uuid7(), "tid": tenant_id, "cid": call_id, "t": TELUGU_REDACTED},
            )
        await get_redis().set(f"call_translation:backfilled:{call_id}", "1", ex=3600)
    await get_redis().delete(f"call_translation:backfilled:{untried}")
    queued: list[str] = []

    async def _enqueue(job: str, payload: dict[str, str], *, job_id: str) -> str:
        queued.append(payload["call_id"])
        return job_id

    monkeypatch.setattr(call_translation, "enqueue", _enqueue)
    monkeypatch.setattr(call_translation, "BACKFILL_BATCH", 1)
    monkeypatch.setattr(call_translation, "_CANDIDATE_PAGE", 2)
    monkeypatch.setattr(
        call_translation,
        "_LIVE_TENANTS_SQL",
        f"SELECT id FROM organizations WHERE id = '{tenant_id}'",
    )

    await call_translation.backfill_call_translations({})

    assert queued == [str(untried)]


async def test_a_chunk_cut_off_at_the_token_cap_is_split_and_every_line_still_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a chunk Sarvam cuts off at `max_tokens` (its reasoning counts toward the cap)
    fails the whole call's English, or a split loses the summary or a line."""

    asked: list[tuple[list[int], bool]] = []

    async def _complete(leg: chat.ChatLeg, messages: Any, **kw: Any) -> chat.ChatOutcome:
        prompt = str(messages[0]["content"])
        lines = [
            json.loads(row)
            for row in prompt.split("one JSON object per line):\n")[1].split("\n")
            if row
        ]
        idxs = [int(row["i"]) for row in lines]
        summaries = '"summary_local"' in prompt
        asked.append((idxs, summaries))
        if len(idxs) > 10:
            return chat.ChatOutcome(content='{"turns": [', finish_reason="length", usage=None)
        body: dict[str, Any] = {"turns": [{"i": i, "en": f"line {i}"} for i in idxs]}
        if summaries:
            body["summary_local"] = "సారాంశం"
        return chat.ChatOutcome(content=json.dumps(body), finish_reason="stop", usage=None)

    monkeypatch.setattr(chat, "complete", _complete)
    turns = [(i, f"పంక్తి {i}") for i in range(call_language.TURNS_PER_REQUEST)]
    done = await call_language.run_language_pass(
        api_key="k", language="te-IN", turns=turns, summary_en="Summary.", summary_local=""
    )
    assert done.failed is False
    assert sorted(done.turns_en) == list(range(call_language.TURNS_PER_REQUEST))
    assert done.summary_local == "సారాంశం"
    # 40 lines cut off, then the first 20, then the first 10 answers: the summary rides the
    # first half each time and is asked for nowhere else.
    assert [summaries for _, summaries in asked].count(True) == 3


async def test_a_single_line_cut_off_at_the_token_cap_still_says_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a line that cannot be split any further reads as translated."""

    async def _complete(leg: chat.ChatLeg, messages: Any, **kw: Any) -> chat.ChatOutcome:
        return chat.ChatOutcome(content='{"turns": [', finish_reason="length", usage=None)

    monkeypatch.setattr(chat, "complete", _complete)
    done = await call_language.run_language_pass(
        api_key="k", language="te-IN", turns=[(0, "పంక్తి")], summary_en="", summary_local=""
    )
    assert done.failed is True
    assert done.turns_en == {}


async def test_a_pass_over_its_time_budget_keeps_what_it_has_and_says_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a provider that answers the first chunk and then hangs runs the pass past
    its budget, which inside the post-call job is arq's cancellation of the whole call."""
    turns = [(i, f"పంక్తి {i}") for i in range(call_language.TURNS_PER_REQUEST + 1)]
    answered = 0

    async def _complete(leg: chat.ChatLeg, messages: Any, **kw: Any) -> chat.ChatOutcome:
        nonlocal answered
        if answered:
            await asyncio.sleep(3600)
        answered += 1
        body = {"turns": [{"i": 0, "en": "Line zero."}], "summary_local": "సారాంశం"}
        return chat.ChatOutcome(content=json.dumps(body), finish_reason="stop", usage=None)

    monkeypatch.setattr(chat, "complete", _complete)
    monkeypatch.setattr(call_language, "LANGUAGE_PASS_BUDGET_S", 0.05)
    done = await call_language.run_language_pass(
        api_key="k", language="te-IN", turns=turns, summary_en="Summary.", summary_local=""
    )
    assert done.failed is True
    assert done.turns_en == {0: "Line zero."}
    assert done.summary_local == "సారాంశం"


async def test_the_pass_asks_with_reasoning_off_and_the_wire_carries_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the language pass leaves `reasoning_effort` unset. Sarvam then thinks at its
    default and bills the thinking as output: 19.5k output tokens for 2.2k in on one
    1.5-minute call (24 Oct 2026)."""
    asked: list[dict[str, Any]] = []

    async def _complete(leg: chat.ChatLeg, messages: Any, **kw: Any) -> chat.ChatOutcome:
        asked.append(kw)
        body = {"turns": [{"i": 0, "en": "Hello."}], "summary_local": "సారాంశం"}
        return chat.ChatOutcome(content=json.dumps(body), finish_reason="stop", usage=None)

    monkeypatch.setattr(chat, "complete", _complete)
    done = await call_language.run_language_pass(
        api_key="k", language="te-IN", turns=[(0, "నమస్కారం")], summary_en="Hi.", summary_local=""
    )

    assert done.failed is False
    assert [kw["reasoning_effort"] for kw in asked] == ["off"]
    leg = chat.ChatLeg(
        url="https://x.test", api_key="k", wire_model="sarvam-105b", dialect="sarvam"
    )
    wire = chat._request_body(
        leg,
        [],
        temperature=0,
        response_format=None,
        tools=None,
        tool_choice=None,
        stream=False,
        reasoning_effort=call_language.REASONING_EFFORT,
    )
    assert "reasoning_effort" in wire and wire["reasoning_effort"] is None


async def test_an_unreadable_answer_says_failed_rather_than_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an answer with no `turns` list (prose, or a broken object) reads as a pass
    that found every line already English, so the call says `ready` with no English."""

    async def _complete(leg: chat.ChatLeg, messages: Any, **kw: Any) -> chat.ChatOutcome:
        return chat.ChatOutcome(
            content="Here is the translation.", finish_reason="stop", usage=None
        )

    monkeypatch.setattr(chat, "complete", _complete)
    done = await call_language.run_language_pass(
        api_key="k", language="te-IN", turns=[(0, "పంక్తి")], summary_en="", summary_local=""
    )
    assert done.failed is True
    assert done.turns_en == {}


async def test_the_language_pass_is_metered_with_its_call_its_source_and_its_tokens() -> None:
    """FAILS IF: a language pass row loses the call it was for, or the step that ran it, so
    per-call AI cost and a second pass on one call cannot be read from the ledger."""
    tenant_id, call_id, _slug, _headers = await _telugu_call()
    rates.install_inr_llm_price_attestations(
        lambda: {
            SARVAM_DEFAULT_LLM: rates.InrLlmPriceAttestation(
                model=SARVAM_DEFAULT_LLM,
                in_inr_per_mtok=Decimal("15"),
                cached_in_inr_per_mtok=None,
                out_inr_per_mtok=Decimal("60"),
                attested_by="founder",
                source="test",
            )
        }
    )
    try:
        async with tenant_session(tenant_id) as session:
            await call_translation.meter_language_pass(
                session,
                tenant_id,
                call_id,
                chat.TokenUsage(prompt_tokens=1_720, output_tokens=1_100),
                feature=ASSIST_FEATURE_CALL_LANGUAGE,
                source="call_reading",
            )
    finally:
        rates.install_inr_llm_price_attestations(None)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, call_id, meta FROM usage_events "
                    "WHERE tenant_id = :t AND meta->>'call_id' = :c ORDER BY unit_type"
                ),
                {"t": tenant_id, "c": str(call_id)},
            )
        ).all()
    assert [(r[0], Decimal(str(r[1]))) for r in rows] == [
        ("ai_assist_ktok_in", Decimal("1.72")),
        ("ai_assist_ktok_out", Decimal("1.1")),
    ]
    # The column stays NULL so the ref keeps the row idempotent (`UsageEvent`).
    assert all(r[3] is None for r in rows)
    for row in rows:
        meta = row[4] if isinstance(row[4], dict) else json.loads(row[4])
        assert meta["feature"] == ASSIST_FEATURE_CALL_LANGUAGE
        assert (meta["source"], meta["reasoning_effort"]) == ("call_reading", "off")
    cost = sum((Decimal(str(r[1])) * Decimal(str(r[2])) for r in rows), Decimal("0"))
    assert cost == Decimal("0.0918")
