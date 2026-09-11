"""Only the loud ones mail; everything else is a row an operator can read (D-591).

The founder's inbox was the alert console and it had stopped working as one: four
ordinary deploys' `signal_received`, a visitor's browser extension tripping
`csp_violation` and twenty-six observations of one already-diagnosed `fx_rate_stale`
arrived looking exactly like the operational failure in the same evening that was worth
reading. Their instruction was *"I need to see about failures in admin panel only. I want
high priority things only through mail."*

These tests pin the six properties that sentence turns into, each of which is a way the
change could silently be undone:

1. **The severity gates the email.** A `page` mails; an `attention` and a `record` do not.
2. **A recorded-only alert still reaches the table** — it is not merely un-mailed, it is
   somewhere an operator can find it, which is the whole of the second half of the ask.
3. **An ongoing condition does not re-mail**, however many times it fires — and when it
   clears, that is said once.
4. **The registry is exhaustive**, so a new alarm code cannot be added without choosing a
   severity, and an unclassified one is loud rather than invisible.
5. **Hard rule 6 holds on the STORED fields**, not only on the emailed ones: a planted
   phone number must not survive into `platform_alerts.detail` or `.ids`.
6. **The emergency path still works.** The codes that would wake somebody at 3am are
   still the codes that mail.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from apps.api.core import alert_admission, alerting
from apps.api.core.alarm_severity import (
    ALARM_SEVERITY,
    DEFAULT_SEVERITY,
    EMAILED_SEVERITIES,
    SEVERITIES,
    severity_of,
)
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from sqlalchemy import text

OPERATOR = "sri@calevate.tech"
PLANTED_PHONE = "+919876543210"

#: One code per rung, chosen from the real registry rather than invented, so a
#: re-classification of any of the three fails this file rather than passing silently
#: against a made-up vocabulary.
A_PAGE = "razorpay_money_unapplied"
AN_ATTENTION = "fx_rate_stale"
A_RECORD = "signal_received"


class RecordingTransport:
    """The same double `tests/alert_delivery_test.py` uses, for the same reason."""

    name = "recording"

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.arrived = threading.Event()

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        self.arrived.set()
        return True


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    from apps.api.core import transport as transport_module

    alerting.reset_alerts()
    recorder = RecordingTransport()
    monkeypatch.setattr(transport_module, "get_transport", lambda: recorder)
    monkeypatch.setattr(get_settings(), "alerts_email", OPERATOR)
    monkeypatch.setattr(alerting, "DELIVERY_RETRY_DELAY_S", 0.0)
    yield recorder
    alerting.reset_alerts()


async def _episodes(code: str) -> list[Any]:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT code, stage, severity, service, detail, ids, occurrences, "
                    "emailed, cleared_at FROM platform_alerts WHERE code = :code"
                ),
                {"code": code},
            )
        ).all()


def _drain() -> None:
    assert alerting.flush_alerts(timeout=5.0), "alert delivery did not drain"


# --- 1 + 2: the severity decides the inbox, never the table -------------------


@pytest.mark.asyncio
async def test_a_page_severity_alarm_still_reaches_the_operators_inbox(transport: Any) -> None:
    """THE EMERGENCY PATH. A client was debited and their wallet did not move."""
    alerting.alert("ROUTE_HANDLER", A_PAGE, detail="capture could not be applied")
    _drain()

    (message,) = transport.sent
    assert message["to"] == OPERATOR
    assert A_PAGE in message["subject"]
    # The rung is in the body so the reader knows why they were woken and where to argue.
    assert "severity: page" in message["body"]


@pytest.mark.asyncio
async def test_an_attention_alarm_is_recorded_and_never_mailed(transport: Any) -> None:
    """THE FOUNDER'S 26-MESSAGE THREAD, one occurrence of it.

    Nothing is broken — costs convert at a documented fallback ladder (D-589) — so it
    belongs on a screen. The assertion that matters is the SECOND one: un-mailed must not
    mean unrecorded, or this change would have traded an unusable inbox for no alerting.
    """
    alerting.alert("CORE_LOGIC", AN_ATTENTION, detail="every published source is stale")
    _drain()

    assert transport.sent == []
    (row,) = await _episodes(AN_ATTENTION)
    assert row.severity == "attention"
    assert row.emailed is False
    assert row.occurrences == 1
    assert row.cleared_at is None, "a fresh episode is OPEN"


@pytest.mark.asyncio
async def test_an_ordinary_deploy_is_recorded_and_never_mailed(transport: Any) -> None:
    """FOUR DEPLOYS IN ONE EVENING. A container stopping because an operator deployed is
    not an incident — and the restarts that are NOT ordinary (OOM, a hard crash) never
    reach the SIGTERM handler at all, so every signal that gets here is an orderly stop."""
    alerting.alert("PROCESS_RESTART", A_RECORD, detail="SIGTERM")
    _drain()

    assert transport.sent == []
    (row,) = await _episodes(A_RECORD)
    assert row.severity == "record"
    assert row.detail == "SIGTERM"


# --- 3: an ongoing condition, and the end of one ------------------------------


@pytest.mark.asyncio
async def test_an_ongoing_condition_mails_once_and_counts_the_rest(
    transport: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shape of the defect: one condition, many observations, ONE message.

    The repeats are not thrown away — `occurrences` carries every one of them onto the
    row, which is what makes "still broken, 199 times" legible somewhere other than an
    inbox. The clock is moved past the recording window so the second flush is a genuine
    delivery-thread visit and not a suppressed one, which is exactly the case that used to
    produce message number two.
    """
    clock = {"t": 1_000.0}
    monkeypatch.setattr(alerting, "_now", lambda: clock["t"])
    monkeypatch.setattr(alert_admission, "_now_ms", lambda: clock["t"] * 1000.0)

    for _ in range(30):
        alerting.alert("ROUTE_HANDLER", A_PAGE, detail="still unapplied")
    _drain()
    clock["t"] += alerting.ALERT_REPEAT_INTERVAL_S + 1
    alerting.alert("ROUTE_HANDLER", A_PAGE, detail="still unapplied")
    _drain()

    assert len(transport.sent) == 1, "an ongoing condition mails once"
    (row,) = await _episodes(A_PAGE)
    assert row.occurrences == 31, "every occurrence reaches the row"
    assert row.emailed is True


@pytest.mark.asyncio
async def test_a_condition_that_clears_says_so_once_and_only_if_it_had_mailed(
    transport: Any,
) -> None:
    """A condition ending is worth a line — and only from the rung that woke somebody.

    The sweep is driven by `last_seen_at`, so the row is aged by hand rather than by
    sleeping an hour. Both an emailed `page` and an un-mailed `attention` are aged in the
    same tick, which is the whole point of the second assertion: closing the quiet one
    silently is what `attention` MEANS, and mailing a clear for something whose onset was
    never mailed would be the noise this decision removes, arriving backwards.
    """
    from apps.workers.alerts import sweep_alert_clears

    alerting.alert("ROUTE_HANDLER", A_PAGE, detail="capture could not be applied")
    alerting.alert("CORE_LOGIC", AN_ATTENTION, detail="every published source is stale")
    _drain()
    assert len(transport.sent) == 1

    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_alerts SET last_seen_at = now() - interval '3 hours'")
        )
        await session.commit()

    await sweep_alert_clears({})

    assert len(transport.sent) == 2, "the page's clear is announced"
    assert "cleared" in transport.sent[1]["subject"]
    assert A_PAGE in transport.sent[1]["subject"]
    for code in (A_PAGE, AN_ATTENTION):
        (row,) = await _episodes(code)
        assert row.cleared_at is not None, f"{code} should be closed"


@pytest.mark.asyncio
async def test_a_condition_that_comes_back_after_clearing_mails_again(
    transport: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The onset rule must not become a permanent mute.

    A cleared episode releases the partial unique index, so the next occurrence opens a
    NEW episode — which is a genuine onset and does mail. Without this, one page would
    silence a code for the life of the deployment.
    """
    from apps.workers.alerts import sweep_alert_clears

    # THE IN-PROCESS WINDOW IS MOVED PAST TOO, and it has to be. An episode only clears
    # after an hour of quiet, so in production the 15-minute recording window has long
    # since expired by the time a recurrence arrives — but a test that ages only the ROW
    # would have the second occurrence swallowed by `_last_sent` and would read as "a
    # cleared episode still cannot mail", which is the opposite of what it proves.
    # BOTH CLOCKS, for `alert_delivery_test._freeze_clock`'s stated reason: the
    # in-process window is stamped at `alert()` time and the SHARED (Redis) one at send
    # time, and advancing only the first leaves the alarm suppressed cross-process by a
    # marker the test cannot see.
    clock = {"t": 1_000.0}
    monkeypatch.setattr(alerting, "_now", lambda: clock["t"])
    monkeypatch.setattr(alert_admission, "_now_ms", lambda: clock["t"] * 1000.0)

    alerting.alert("ROUTE_HANDLER", A_PAGE, detail="first time")
    _drain()
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE platform_alerts SET last_seen_at = now() - interval '3 hours'")
        )
        await session.commit()
    await sweep_alert_clears({})
    clock["t"] += alerting.ALERT_CLEAR_AFTER_S + 1

    alerting.alert("ROUTE_HANDLER", A_PAGE, detail="and again")
    _drain()

    onsets = [m for m in transport.sent if "cleared" not in m["subject"]]
    assert len(onsets) == 2, "a genuine recurrence is a new episode and mails"
    assert len(await _episodes(A_PAGE)) == 2


# --- 4: the registry is exhaustive and fails loud ------------------------------


class TestTheRegistryCannotBeSkipped:
    """A new alarm code must choose a severity, and an unclassified one is LOUD."""

    def test_an_unclassified_code_defaults_to_the_loudest_rung(self) -> None:
        """FAIL LOUD, NOT CLOSED. The two mistakes are not symmetric: an alarm mailed
        when it should not have been costs one message and a one-line diff, while one
        silently demoted to a console row nobody watches costs the outage it exists for.
        """
        assert DEFAULT_SEVERITY == "page"
        assert severity_of("a_code_nobody_has_classified_yet") == "page"

    def test_every_code_the_tree_can_raise_is_classified(self) -> None:
        """The guard's own answer, asserted here so a `pytest` run catches it too."""
        from scripts.check_alarm_wiring import severity_failures

        assert severity_failures() == []

    def test_a_new_code_with_no_severity_fails_the_guard(self) -> None:
        """THE NEGATIVE CONTROL. A guard that has never been seen to fail is a guard
        nobody can trust; this shows it refusing the exact diff it exists to refuse."""
        from scripts.check_alarm_wiring import severity_failures

        failures = severity_failures({"a_brand_new_alarm": {"apps/api/somewhere.py"}})
        assert any("UNCLASSIFIED: `a_brand_new_alarm`" in failure for failure in failures)

    def test_only_one_rung_leaves_the_building(self) -> None:
        assert frozenset({"page"}) == EMAILED_SEVERITIES
        assert set(SEVERITIES) == {"page", "attention", "record"}

    def test_the_codes_that_still_mail_read_like_an_emergency_list(self) -> None:
        """A SANITY CHECK ON THE CLASSIFICATION ITSELF, not on the mechanism.

        These eight are the ones the brief and the hard rules single out by name: a client
        debited with no credit applied (hard rule 7), an erasure past its statutory
        deadline, a halt that cannot be proven to have stopped the dials, the pipeline the
        whole system exists to run, an unrestorable database, and the meta-alarm that says
        the alerting path itself is broken. If a future change quietly demotes one of
        these, this is where it stops.
        """
        for code in (
            "razorpay_money_unapplied",
            "erasure_requests_overdue",
            "dial_recall_unstopped",
            "postcall_pipeline_stalled",
            "outbox_dead_letter",
            "no_base_backup",
            "alert_delivery_unconfigured",
            "platform_secret_unreadable",
        ):
            assert ALARM_SEVERITY[code] == "page", f"{code} must still wake somebody"

    def test_the_four_codes_that_spammed_the_founder_no_longer_mail(self) -> None:
        for code in ("signal_received", "csp_violation", "fx_rate_stale", "fx_source_degraded"):
            assert ALARM_SEVERITY[code] not in EMAILED_SEVERITIES


# --- 5: hard rule 6, on the STORED fields --------------------------------------


class TestHardRuleSix:
    @pytest.mark.asyncio
    async def test_a_planted_phone_number_does_not_survive_into_the_stored_row(
        self, transport: Any
    ) -> None:
        """The email path was already redacted; the TABLE is a second copy of the same
        text, read on a screen, exported, and pasted into an incident note. It goes
        through the same `redact_mapping` at the write, so there is no unredacted version
        of the field anywhere — which is what `scripts/check_redaction_exposure.py`'s
        acknowledgement of `AlertEpisode.ids` rests on.
        """
        alerting.alert(
            "WORKER_TERMINAL",
            "post_call_abandoned",
            detail=f"could not reach {PLANTED_PHONE}",
            tenant_id="019f-abc",
            caller_phone=PLANTED_PHONE,
        )
        _drain()

        (row,) = await _episodes("post_call_abandoned")
        blob = f"{row.detail} {row.ids}"
        assert PLANTED_PHONE not in blob
        assert "9876543210" not in blob
        assert "019f-abc" in blob, "ids must survive — they are the whole point"

    @pytest.mark.asyncio
    async def test_a_transcript_shaped_detail_is_capped_in_the_row(self, transport: Any) -> None:
        from apps.api.core.alert_records import MAX_DETAIL_CHARS

        transcript = "caller said: " + ("i want an appointment tomorrow morning please " * 200)
        alerting.alert("CORE_LOGIC", A_RECORD, detail=transcript, call_id="019f-aaa")
        _drain()

        (row,) = await _episodes(A_RECORD)
        assert row.detail is not None
        # The cap is what is asserted, not the absence of the words: `redact_mapping`
        # truncates the tail and marks it, so the head of an upstream string survives by
        # design — a `detail` an operator cannot read at all is not the goal. What must
        # not happen is an unbounded transcript becoming a column.
        assert len(row.detail) <= MAX_DETAIL_CHARS
        assert len(row.detail) < len(transcript)
        assert "truncated" in row.detail


# --- 6: the table is reachable from the console --------------------------------


@pytest.mark.asyncio
async def test_the_console_read_returns_the_recorded_alert(transport: Any) -> None:
    """The seam, end to end: an `attention` alarm nobody was mailed about is on the board.

    `GET /v1/ops/alerts` is the screen's only read, so this is the assertion that "failures
    in the admin panel" is a fact rather than a plan.
    """
    from apps.api.ops.alerts_service import alert_report

    alerting.alert("CORE_LOGIC", AN_ATTENTION, detail="every published source is stale")
    _drain()

    async with untenanted_session() as session:
        report = await alert_report(session)

    codes = {episode.code: episode for episode in report.episodes}
    assert AN_ATTENTION in codes
    episode = codes[AN_ATTENTION]
    assert episode.severity == "attention"
    assert episode.emailed is False
    assert episode.cleared_at is None
    assert report.open_by_severity.get("attention", 0) >= 1
    assert report.open_unmailed_pages == 0, "an attention alarm is not an unmailed page"
    assert report.complete is True


# --- 7: the table does not grow without bound --------------------------------


@pytest.mark.asyncio
async def test_a_long_closed_episode_is_pruned_and_an_open_one_never_is(transport: Any) -> None:
    """`platform_alerts` grows with every alarm forever unless something forgets.

    It is pruned by `prune_reliability_tables`, beside the outbox and the inbox, on the
    SAME 90-day floor — one clock for the three never-tenant-scoped infra tables rather
    than a second nightly job for one DELETE. The second half is the one worth pinning:
    an OPEN episode is never pruned however old it is, for the reason the outbox's
    `status <> 'published'` exclusion gives — a row that still has a job to do is not old,
    it is outstanding, and deleting it would let the next occurrence re-mail a condition
    nobody has fixed.
    """
    from apps.workers.retention import prune_reliability_tables

    alerting.alert("CORE_LOGIC", AN_ATTENTION, detail="stale")
    alerting.alert("PROCESS_RESTART", A_RECORD, detail="SIGTERM")
    _drain()

    async with untenanted_session() as session:
        # One closed a year ago; the other left OPEN and aged just as far.
        await session.execute(
            text(
                "UPDATE platform_alerts SET cleared_at = now() - interval '400 days', "
                "last_seen_at = now() - interval '400 days' WHERE code = :code"
            ),
            {"code": A_RECORD},
        )
        await session.execute(
            text(
                "UPDATE platform_alerts SET last_seen_at = now() - interval '400 days' "
                "WHERE code = :code"
            ),
            {"code": AN_ATTENTION},
        )
        await session.commit()

    await prune_reliability_tables({})

    assert await _episodes(A_RECORD) == [], "a long-closed episode is forgotten"
    assert len(await _episodes(AN_ATTENTION)) == 1, "an OPEN episode is never pruned"
