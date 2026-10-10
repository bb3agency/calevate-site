"""IST is the platform's standard time (D-709), and moving to it moved no stored instant.

Stored data is `timestamptz`, an absolute instant, so nothing in the database changed. What
D-709 changed is every place a ZONE is chosen: what a person reads, what a log line says,
which calendar day or month an instant belongs to, and which clock a cron field is read
against. Each of those is pinned here, together with the one place that stays UTC on
purpose (the app's own database session, so every datetime in Python is a UTC-aware
instant whatever the server's default is).

The boundary instant throughout is 2026-10-31 19:00 UTC: 00:30 IST on 1 November, so a
UTC reading puts it in October and an IST reading in November.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from apps.api.billing.plans import IST, ist_billing_month
from apps.api.billing.service import _IST_MONTH
from apps.api.core.logging import LOG_TIMEZONE, JsonFormatter
from apps.api.crm.performance import IST_DAY_SQL, IST_HOUR_SQL
from apps.api.db.session import APP_SESSION_TIMEZONE, migration_connect_args, untenanted_session
from apps.api.quality.sampling import _IST_WEEK_SQL
from apps.workers.settings import CRON_TIMEZONE, WorkerSettings
from arq.cron import next_cron
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent

BOUNDARY = datetime(2026, 10, 31, 19, 0, tzinfo=UTC)
BOUNDARY_SQL = "timestamptz '2026-10-31 19:00:00+00'"


# --- the database ---------------------------------------------------------------------


async def test_app_sessions_run_in_utc_and_hand_back_utc_instants() -> None:
    """The connect-time pin, read back off a live session. psycopg returns a timestamptz in
    the SESSION's zone, so this is what keeps a production server whose default is IST from
    turning every datetime in Python into a +05:30 one."""
    assert APP_SESSION_TIMEZONE == "UTC"
    async with untenanted_session() as session:
        zone = (await session.execute(text("SHOW timezone"))).scalar()
        instant = (await session.execute(text(f"SELECT {BOUNDARY_SQL}"))).scalar()
    assert zone == "UTC"
    assert instant == BOUNDARY
    assert instant.utcoffset() is not None and instant.utcoffset().total_seconds() == 0


def test_migration_sessions_run_in_utc_too() -> None:
    from apps.api.core.settings import get_settings
    from sqlalchemy import create_engine

    url = get_settings().database_url.replace("+asyncpg", "+psycopg")
    engine = create_engine(url, connect_args=migration_connect_args())
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SHOW timezone").scalar() == "UTC"
    finally:
        engine.dispose()


async def test_ist_calendar_sql_answers_the_same_under_either_server_default() -> None:
    """Every IST month, day, hour and week in SQL names its zone, so the server default the
    founder set for psql (Asia/Kolkata) and the one CI runs (UTC) give the same answer.
    `SET LOCAL`, so the change dies with this transaction."""
    month = _IST_MONTH.replace("occurred_at", BOUNDARY_SQL)
    day = IST_DAY_SQL.replace("started_at", BOUNDARY_SQL)
    hour = IST_HOUR_SQL.replace("started_at", BOUNDARY_SQL)
    week = _IST_WEEK_SQL.replace("started_at", BOUNDARY_SQL)
    for zone in ("UTC", "Asia/Kolkata"):
        async with untenanted_session() as session:
            await session.execute(text(f"SET LOCAL TimeZone = '{zone}'"))
            row = (
                await session.execute(
                    text(f"SELECT {month}, ({day})::text, {hour}::int, ({week})::text")
                )
            ).one()
        assert tuple(row) == ("2026-11", "2026-11-01", 0, "2026-10-26"), zone


def test_the_python_billing_month_agrees_with_the_sql_one() -> None:
    assert ist_billing_month(BOUNDARY) == "2026-11"


# --- logs -----------------------------------------------------------------------------


def test_every_log_line_is_stamped_in_ist_with_the_offset_printed() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "event_token", None, None)
    record.created = BOUNDARY.timestamp()
    line = json.loads(JsonFormatter().format(record))
    assert LOG_TIMEZONE.key == "Asia/Kolkata"
    assert line["ts"] == "2026-11-01T00:30:00.000+05:30"


# --- crons ----------------------------------------------------------------------------

#: The before/after D-709 records: each IST slot, and the UTC slot it replaced. Every job
#: moved 30 minutes earlier in absolute time and kept its order against every other job.
IST_SLOTS: dict[str, tuple[int, int, str]] = {
    "cron:meter_number_rentals": (7, 28, "02:28 UTC"),
    "cron:draw_qa_samples": (7, 20, "02:20 UTC"),
    "cron:reconcile_razorpay": (7, 25, "02:25 UTC"),
    "cron:sweep_trials": (7, 33, "02:33 UTC"),
    "cron:reconcile_engine_numbers": (7, 35, "02:35 UTC"),
    "cron:renew_number_rentals": (7, 46, "02:46 UTC"),
    "cron:retry_engine_workspaces": (7, 52, "02:52 UTC"),
    "cron:sweep_engine_workspaces": (8, 8, "03:08 UTC"),
    "cron:sweep_expired": (8, 17, "03:17 UTC"),
    "cron:apply_retention": (8, 40, "03:40 UTC"),
    "cron:check_tls_expiry": (9, 5, "04:05 UTC"),
    "cron:prune_reliability_tables": (9, 10, "04:10 UTC"),
    "cron:sweep_abandoned_owner_ids": (9, 17, "04:17 UTC"),
    "cron:sweep_kb_orphans": (9, 40, "04:40 UTC"),
    "cron:sweep_knowledge_packs": (10, 7, "05:07 UTC"),
    "cron:send_agent_knowledge_digests": (12, 22, "07:22 UTC"),
}


def test_the_worker_reads_every_cron_field_as_ist() -> None:
    """On a real `arq.worker.Worker`: without `timezone`, arq takes the host's zone, and the
    image's `TZ=Asia/Kolkata` would then have moved every job by five and a half hours."""
    from arq.worker import Worker

    assert CRON_TIMEZONE.key == "Asia/Kolkata"
    worker = Worker(
        functions=WorkerSettings.functions,
        cron_jobs=WorkerSettings.cron_jobs,
        redis_settings=WorkerSettings.redis_settings,
        timezone=WorkerSettings.timezone,
        burst=True,
        ctx={},
    )
    assert worker.timezone is CRON_TIMEZONE


def test_every_daily_or_weekly_cron_sits_at_its_documented_ist_slot() -> None:
    timed = {job.name: job for job in WorkerSettings.cron_jobs if job.hour is not None}
    assert set(timed) == set(IST_SLOTS), (
        "a cron with an hour was added or removed; give it a row in IST_SLOTS and in D-709"
    )
    for name, (hour, minute, _was) in IST_SLOTS.items():
        assert timed[name].hour == {hour} and timed[name].minute == {minute}, name


def test_each_slot_is_thirty_minutes_before_the_utc_instant_it_replaced() -> None:
    after = datetime(2026, 10, 10, 0, 0, tzinfo=CRON_TIMEZONE)
    for name, (hour, minute, was) in IST_SLOTS.items():
        old_hour, old_minute = (int(part) for part in was.removesuffix(" UTC").split(":"))
        fired = next_cron(after, hour={hour}, minute={minute}, microsecond=0)
        assert fired.astimezone(UTC).hour * 60 + fired.astimezone(UTC).minute == (
            (old_hour * 60 + old_minute - 30) % (24 * 60)
        ), name


def test_the_weekly_qa_draw_fires_on_monday_morning_ist() -> None:
    job = next(j for j in WorkerSettings.cron_jobs if j.name == "cron:draw_qa_samples")
    fired = next_cron(
        datetime(2026, 10, 10, 12, 0, tzinfo=CRON_TIMEZONE),
        weekday=job.weekday,
        hour=job.hour,
        minute=job.minute,
        microsecond=0,
    )
    assert fired == datetime(2026, 10, 12, 7, 20, tzinfo=IST)


# --- the host -------------------------------------------------------------------------


def test_every_systemd_timer_names_its_zone() -> None:
    """A bare `OnCalendar=*-*-* 02:30:00` is read in the HOST's zone, so the day the VPS
    moved to IST it would have moved the backups. Each one names Asia/Kolkata."""
    timers = sorted(REPO_ROOT.glob("infra/**/*.timer"))
    calendars = [
        (path.name, match.group(1))
        for path in timers
        for match in re.finditer(r"^OnCalendar=(.+)$", path.read_text(encoding="utf-8"), re.M)
    ]
    assert calendars, "no OnCalendar= found; the glob is looking in the wrong place"
    for name, spec in calendars:
        assert spec.endswith(" Asia/Kolkata"), f"{name}: {spec}"


def test_the_app_image_runs_on_ist_and_carries_the_zone_file() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split(" AS runtime", 1)[1]
    assert "TZ=Asia/Kolkata" in runtime
    assert re.search(r"apt-get install[^\n]*\btzdata\b", runtime)
