"""The auto-healer's registry, its scoring and its words (D-701), without a database.

The registry is the one answer to "what fixes itself", so these tests hold it to the rest
of the tree: every alarm a playbook answers is a real, classified code; every absorbed
repair sweep is registered on the worker WRAPPED as its playbook, so the kill switches
and the ledger apply to it; the one sweep that also enforces hard rule 5 cannot be paused;
and the copy a client reads names nothing internal.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from apps.api.core.alarm_severity import ALARM_SEVERITY
from apps.api.core.settings import get_settings
from apps.api.healer import health, notices, playbooks, proposals
from apps.workers import healer as healer_jobs
from apps.workers.settings import CRON_JOBS


def test_every_trigger_is_a_classified_alarm() -> None:
    for playbook in playbooks.PLAYBOOKS:
        for code in playbook.triggers:
            assert code in ALARM_SEVERITY, f"{playbook.key} answers {code}, which no alarm is"


def test_the_healers_own_codes_are_classified() -> None:
    for code in (
        playbooks.AGENT_HEALTH_DEGRADED,
        playbooks.AGENT_LINE_BROKEN,
        playbooks.ENGINE_PLATFORM_OUTAGE,
        "healer_needs_person",
        "healer_line_relapsed",
        "healer_line_hold_failed",
    ):
        assert code in ALARM_SEVERITY


def test_one_playbook_per_trigger_and_per_key() -> None:
    keys = [p.key for p in playbooks.PLAYBOOKS]
    assert len(keys) == len(set(keys))
    triggers = [code for p in playbooks.PLAYBOOKS for code in p.triggers]
    assert len(triggers) == len(set(triggers))


def test_every_absorbed_sweep_runs_wrapped_as_its_playbook() -> None:
    """The absorption is real only if the worker boots the wrapped coroutine: a sweep
    registered bare would escape both kill switches and the ledger."""
    by_name = {job.name: job for job in CRON_JOBS}
    for job_name, playbook in playbooks.PLAYBOOK_BY_JOB.items():
        cron = by_name.get(f"cron:{job_name}")
        assert cron is not None, f"{playbook.key}'s sweep {job_name} is not on the schedule"
        assert getattr(cron.coroutine, "healer_playbook", None) == playbook.key, (
            f"{job_name} is scheduled without `healer_sweep`, so no kill switch reaches it"
        )
        assert cron.coroutine.__name__ == job_name


def test_the_healer_crons_are_registered() -> None:
    names = {job.name for job in CRON_JOBS}
    assert "cron:run_healer" in names
    assert "cron:score_agent_health" in names


def test_every_incident_playbook_has_a_step() -> None:
    """A playbook that can own an incident must have a step to advance it with."""
    for playbook in playbooks.PLAYBOOKS:
        if playbook.job is None or playbook.triggers:
            assert playbook.key in healer_jobs._STEPS, playbook.key


def test_the_drift_sweep_cannot_be_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    """It also silences an agent proven to have lost its truthful-answer rule (hard rule
    5), so neither kill switch may stop it."""
    settings = get_settings()
    monkeypatch.setattr(settings, "healer_enabled", False)
    monkeypatch.setattr(settings, "healer_paused_playbooks", "engine_drift,engine_webhooks")
    assert playbooks.may_run("engine_drift") is True
    assert playbooks.may_run("engine_webhooks") is False


def test_the_kill_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "healer_enabled", True)
    monkeypatch.setattr(settings, "healer_paused_playbooks", " outbox_replay , nonsense ")
    assert playbooks.may_run("line_protection") is True
    assert playbooks.may_run("outbox_replay") is False
    assert playbooks.unknown_paused_keys() == ("nonsense",)
    monkeypatch.setattr(settings, "healer_enabled", False)
    assert playbooks.may_run("line_protection") is False


@pytest.mark.asyncio
async def test_a_paused_sweep_is_skipped_and_ledgered(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []

    async def reconcile_engine_charges(ctx: dict[str, Any]) -> str:
        ran.append("ran")
        return "ok"

    recorded: list[dict[str, Any]] = []

    async def _record(**kwargs: Any) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(healer_jobs, "_record", _record)
    wrapped = healer_jobs.healer_sweep(reconcile_engine_charges)
    monkeypatch.setattr(get_settings(), "healer_paused_playbooks", "charge_reconcile")
    assert await wrapped({"job_try": 1}) == "skipped:healer_paused"
    assert ran == []
    assert recorded[-1]["outcome"] == "skipped"
    monkeypatch.setattr(get_settings(), "healer_paused_playbooks", "")
    assert await wrapped({"job_try": 1}) == "ok"
    assert recorded[-1]["outcome"] == "ok"
    assert wrapped.__name__ == "reconcile_engine_charges"


# --- scoring ----------------------------------------------------------------------------


def _counts(**kw: int) -> health.WindowCounts:
    base = {
        "calls": 10,
        "short_calls": 0,
        "failed_calls": 0,
        "slow_starts": 0,
        "escalations": 0,
        "knowledge_misses": 0,
        "action_failures": 0,
        "language_misses": 0,
    }
    base.update(kw)
    return health.WindowCounts(agent_id=uuid.uuid4(), **base)


def test_a_clean_window_scores_a_hundred() -> None:
    assert health.score(_counts()) == Decimal("100.00")
    assert health.score(_counts(calls=0)) == Decimal("100")


def test_each_signal_takes_its_weight_times_its_share() -> None:
    assert health.score(_counts(failed_calls=5)) == Decimal("75.00")
    assert health.score(_counts(knowledge_misses=10)) == Decimal("85.00")
    # A share never exceeds one, however many action failures a call had.
    assert health.score(_counts(action_failures=40)) == Decimal("90.00")


def test_never_on_too_few_calls() -> None:
    assert health.deviates(Decimal("0"), None, calls=1) is False


def test_deviation_is_against_the_agents_own_baseline() -> None:
    assert health.deviates(Decimal("70"), Decimal("95"), calls=5) is True
    assert health.deviates(Decimal("78"), Decimal("95"), calls=5) is False
    # A low-baseline agent is judged against itself, not against the absolute floor.
    assert health.deviates(Decimal("45"), Decimal("55"), calls=5) is False
    assert health.deviates(Decimal("55"), None, calls=5) is True


def _row(
    calls: int, short: int = 0, failed: int = 0, kb: int = 0, deviating: bool = False
) -> tuple[Any, ...]:
    return (datetime.now(UTC), calls, short, failed, 0, 0, kb, 0, 0, deviating)


def test_degraded_needs_three_judged_windows_in_a_row() -> None:
    agent = uuid.uuid4()
    two = [_row(4, deviating=True), _row(4, deviating=True), _row(4)]
    assert health.judge(agent, two).degraded is False
    three = [_row(4, kb=3, deviating=True)] * 3
    verdict = health.judge(agent, three)
    assert verdict.degraded is True
    assert verdict.worst_signal == "knowledge"


def test_broken_needs_enough_calls_and_most_of_them_broken() -> None:
    agent = uuid.uuid4()
    assert health.judge(agent, [_row(2, failed=2), _row(2, short=2)]).broken is False
    assert health.judge(agent, [_row(3, failed=3), _row(3, short=2)]).broken is True
    assert health.judge(agent, [_row(5, failed=2), _row(5, short=1)]).broken is False


def test_window_start_floors_to_the_quarter_hour() -> None:
    at = datetime(2026, 10, 9, 10, 44, 59, 999, tzinfo=UTC)
    assert health.window_start(at) == datetime(2026, 10, 9, 10, 30, tzinfo=UTC)


# --- words -------------------------------------------------------------------------------

#: The internal-references guard's client rules, restated for text that is not a problem
#: response (`tests/internal_references_guard_test.py`).
_BANNED = re.compile(
    r"hard rule|\bD-\d{2,4}\b|§|\btenants?\b|\bRLS\b|\bschemas?\b|\bthe API\b(?! key)|"
    r"\bendpoints?\b|\bpayloads?\b|\bwebhooks?\b|sarvam|cartesia|gnani|vobiz|plivo|pipecat|"
    r"thinnest|bolna|exotel|playbook|incident",
    re.IGNORECASE,
)


@pytest.mark.parametrize(
    ("kind", "protection", "state"),
    [
        ("line_protected", "paused", "open"),
        ("line_protected", "forwarded", "open"),
        ("line_protected", "none", "open"),
        ("line_protected", "paused", "resolved"),
        ("platform_outage", "paused", "open"),
        ("agent_unwell", "none", "open"),
    ],
)
def test_client_notices_name_nothing_internal(kind: str, protection: str, state: str) -> None:
    notice = notices.line_notice(
        kind=kind,
        protection=protection,
        agent_name="Reception",
        campaigns_paused=2,
        fallback_phone="+919876543210",
        state=state,
        missed_calls=3,
        requeued=1,
        worst_signal="knowledge",
        has_proposal=True,
    )
    for text in (notice.headline, notice.what_happened, notice.what_we_did, notice.your_part):
        assert not _BANNED.search(text), text
        assert "9876543210" not in text, "a full number in a notice"


def test_signal_words_and_proposal_copy_name_nothing_internal() -> None:
    for sentence in notices.SIGNAL_WORDS.values():
        assert not _BANNED.search(sentence), sentence
    for copy in proposals.COPY.values():
        for field in ("title", "body", "action"):
            assert not _BANNED.search(copy[field]), copy[field]
