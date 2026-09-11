"""Give every alarm a row, and tell the delivery path whether this one is NEW (D-591).

WHAT THIS IS FOR. `core/alerting.py` bounded HOW OFTEN an alarm was mailed and never
asked WHETHER it should be, and there was nowhere at all to read alarm history from. The
founder's instruction — *"failures in admin panel only, high priority things only through
mail"* — needs both halves: a table `/admin/ops/alerts` can read, and a rule that lets an
email out. This module is the table half, and it happens to be the cheapest place to
compute the second half honestly.

**THE ONSET/CLEAR TRANSITION, AND WHY IT LIVES IN ONE STATEMENT.** `fx_rate_stale` sent
twenty-six messages in an evening because the repeat window asks "have I mailed this in the
last fifteen minutes", and an ongoing condition answers "no" four times an hour forever. The
question worth asking is *"is this condition already known"*, and `platform_alerts` answers
it structurally: `uq_platform_alerts_open_fingerprint` is a partial unique index on
`fingerprint WHERE cleared_at IS NULL`, so

    INSERT ... ON CONFLICT (fingerprint) WHERE cleared_at IS NULL DO UPDATE ...
    RETURNING (xmax = 0) AS opened

opens the episode or extends it, and `xmax = 0` — Postgres' own tell for "this tuple was
inserted, not updated, by this statement" — says which happened. Only an OPENING occurrence
may mail. An ongoing condition is then one email at onset and one at clear, however many
times it fires in between, and a condition that comes back after going quiet is a genuinely
new episode and mails again.

**IT MUST NEVER TURN AN OUTAGE INTO A SILENCE, SO IT FAILS OPEN.** `core/alerting.py`
deliberately keeps the alert path off the transactional outbox, because the alarms that
matter most are "the thing that delivers work is broken"; adding a database to that path
would recreate the same trap one component over. So the contract here is one-directional:
this module may TELL the delivery thread not to mail a repeat, and it may never be the
reason a first occurrence goes unmailed. If the connection fails, the statement errors, or
the DSN is absent, `record()` returns `None` and the caller reads that as "I do not know
whether this is new" — and mails. The cost of a database outage is duplicate mail, never a
missed page.

**WHY SYNCHRONOUS psycopg AND NOT THE APP'S SESSION.** This runs on `alerting`'s single
daemon delivery thread, which is not inside an event loop and is reached from a SIGTERM
handler and from voice-runtime's 500ms ack path (the queue hop is what keeps it off both).
`db/session.py` is `create_async_engine` all the way down and there is no loop here to
await it in. `psycopg` (sync) is already a dependency of all three services, the connection
is short-lived and carries an explicit `connect_timeout`, and nothing holds it between
alerts — a pool on a daemon thread that spends its life blocked on SMTP would be a pool of
idle connections against the database this alarm may be reporting on.

**HARD RULE 6.** `detail` and `ids` are redacted HERE, with `core/logging.redact_mapping` —
the same call `alerting._body` makes before an email leaves the building, for the same
reason: `detail` is authored by us but routinely carries an upstream error string, and an
id kwarg is whatever the call site passed. A row in this table is read on a screen, exported
by an operator and quoted into an incident note; it is the last place to trust a caller.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import uuid_utils

from apps.api.core.logging import get_logger, redact_mapping

log = get_logger("calevate.alert")

#: How long the writer waits for a connection and for the statement. Short on purpose: the
#: delivery thread has a `flush_alerts` deadline in front of it and an atexit drain behind
#: it, and a database that cannot answer in three seconds is one we are not going to wait
#: for while an alarm is outstanding.
RECORD_TIMEOUT_S = 3

#: `detail` is authored prose plus, often, a vendor's error string. The email caps it
#: through `redact_mapping`; the column is capped again here so one pathological upstream
#: message cannot make a console row unreadable.
MAX_DETAIL_CHARS = 2_000

#: `statement_timeout` goes on the CONNECTION and not in a `SET LOCAL`, because these
#: connections are `autocommit` and `SET LOCAL` outside a transaction block does nothing
#: at all — it would have been a timeout that looked configured and was not. libpq's
#: `options` reaches the backend at startup, so it covers every statement on the session.
_CONNECT_KWARGS: dict[str, Any] = {
    "connect_timeout": RECORD_TIMEOUT_S,
    "autocommit": True,
    "options": f"-c statement_timeout={RECORD_TIMEOUT_S * 1000}",
}

_UPSERT = """
INSERT INTO platform_alerts (
    id, fingerprint, code, stage, severity, service, detail, ids,
    first_seen_at, last_seen_at, occurrences
)
VALUES (
    %(id)s, %(fingerprint)s, %(code)s, %(stage)s, %(severity)s, %(service)s,
    %(detail)s, %(ids)s, now(), now(), %(occurrences)s
)
ON CONFLICT (fingerprint) WHERE cleared_at IS NULL DO UPDATE SET
    last_seen_at = now(),
    occurrences  = platform_alerts.occurrences + EXCLUDED.occurrences,
    -- The LATEST detail wins. An episode is one condition, and the most recent
    -- observation of it is the one an operator wants on the screen; keeping the first
    -- would pin a screen to an error message that has since changed.
    detail       = EXCLUDED.detail,
    ids          = EXCLUDED.ids,
    severity     = EXCLUDED.severity,
    service      = EXCLUDED.service
RETURNING id, (xmax = 0) AS opened, platform_alerts.emailed AS already_emailed
"""

_MARK_EMAILED = """
UPDATE platform_alerts SET emailed = true, emailed_at = now() WHERE id = %(id)s
"""


@dataclass(frozen=True)
class RecordOutcome:
    """What the row said. `opened` is the whole point: it is the ONSET transition."""

    alert_id: str
    opened: bool
    #: Has this episode ALREADY been mailed successfully? A repeat is withheld only when
    #: it has: an episode opened by a `page` whose transport then failed twice is still an
    #: alarm nobody has been told about, and silencing its next occurrence would let one
    #: SMTP blip swallow the incident — the property `alerting._forget` exists to protect,
    #: which the onset rule would otherwise have quietly repealed.
    already_emailed: bool


def _dsn() -> str | None:
    """The sync DSN, or None when this process has no database (tests, a bare script).

    `+asyncpg` is stripped for `alembic/env.py`'s reason one line at a time: the URL in
    settings names the async driver and psycopg is the sync one. A DSN that names neither
    is passed through untouched — libpq reads plain `postgresql://` fine.
    """
    from apps.api.core.settings import get_settings

    url = get_settings().database_url
    if not url:
        return None
    return url.replace("+asyncpg", "").replace("+psycopg", "")


def record(
    *,
    stage: str,
    code: str,
    severity: str,
    service: str,
    detail: str | None,
    ids: dict[str, str],
    occurrences: int,
) -> RecordOutcome | None:
    """Open or extend this alarm's episode. `None` means "I could not tell" — mail anyway.

    Runs on the delivery thread only. Never raises: this is the alerting path, and a
    failure to WRITE ABOUT a failure must not become a second failure.
    """
    safe = redact_mapping({"detail": detail or "", **ids})
    safe_detail = str(safe.pop("detail", ""))[:MAX_DETAIL_CHARS] or None
    params: dict[str, Any] = {
        # Generated here rather than by a column default: `RETURNING id` has to name a
        # value on the UPDATE arm too, and a client-side uuid keeps this one statement.
        "id": str(uuid.UUID(bytes=uuid_utils.uuid7().bytes)),
        "fingerprint": f"{stage}:{code}",
        "code": code,
        "stage": stage,
        "severity": severity,
        "service": service,
        "detail": safe_detail,
        "ids": json.dumps(safe, default=str) if safe else None,
        "occurrences": max(1, occurrences),
    }
    dsn = _dsn()
    if not dsn:
        return None
    try:
        import psycopg

        with psycopg.connect(dsn, **_CONNECT_KWARGS) as conn, conn.cursor() as cur:
            cur.execute(_UPSERT, params)
            row = cur.fetchone()
    except Exception as exc:
        # FAIL OPEN. The caller reads None as "unknown" and mails a `page` anyway.
        #
        # BROAD ON PURPOSE, AND DELIBERATELY UNLIKE `forget_all` BELOW — do not "fix"
        # this one to match it. There, narrowing is right because the helper is entitled
        # to ignore exactly two conditions and must not hide a third. Here the arm is not
        # ignoring anything: whatever goes wrong, the answer is "I could not tell whether
        # this episode is new", which is reported at WARNING and then makes the alarm
        # MAIL. A narrower catch would let an unanticipated exception escape into
        # `_drain`, where the notice is lost along with the send — the one outcome this
        # module exists to prevent.
        log.warning("alert_record_failed", extra={"code": code, "reason": type(exc).__name__})
        return None
    if row is None:  # pragma: no cover - RETURNING always yields on a successful upsert
        return None
    return RecordOutcome(alert_id=str(row[0]), opened=bool(row[1]), already_emailed=bool(row[2]))


def mark_emailed(alert_id: str) -> None:
    """Stamp the episode that actually went out. Best effort, for `record`'s reason.

    A SEPARATE STATEMENT rather than a column set optimistically in the upsert, because
    "we tried to mail this" and "this was mailed" are different facts and the screen
    promises the second. A `page` whose transport failed twice keeps `emailed = false`,
    which is exactly the row an operator needs to see.
    """
    dsn = _dsn()
    if not dsn:
        return
    try:
        import psycopg

        with psycopg.connect(dsn, **_CONNECT_KWARGS) as conn:
            conn.execute(_MARK_EMAILED, {"id": alert_id})
    except Exception as exc:
        log.warning("alert_mark_emailed_failed", extra={"reason": type(exc).__name__})


def forget_all() -> None:
    """TEST SEAM. Empty `platform_alerts` so a suite's episodes do not leak between tests.

    Called from `alerting.reset_alerts()`, which is already declared as the test seam for
    the suppression window and the token bucket — and since D-591 the EPISODE is a third
    piece of the same state: a test that fires a `page` after another test has already
    opened that code's episode watches its email vanish for a reason nothing in its own
    file explains. Exactly the argument `reset_alerts` makes for resetting the shared
    Redis half.
    """
    dsn = _dsn()
    if not dsn:
        return
    try:
        import psycopg
    except ImportError:  # pragma: no cover - psycopg absent
        return

    # NARROWED RATHER THAN SILENCED, and split so each arm catches only what it can
    # raise. A bare `except Exception` around both also swallowed a NameError or a typo
    # in the DELETE — on the one module whose whole job is that a failure reaches
    # somebody, and it read green. The two failures this helper IS entitled to ignore
    # are a missing driver and a missing database or table: a suite with no database has
    # no episodes to forget. Debug rather than warning, because this is a test-path
    # helper and an operator is never its reader.
    try:
        with psycopg.connect(dsn, **_CONNECT_KWARGS) as conn:
            conn.execute("DELETE FROM platform_alerts")
    except psycopg.Error as exc:  # pragma: no cover - no database, or no table yet
        log.debug("alert_forget_all_skipped", extra={"reason": type(exc).__name__})
        return


__all__ = [
    "MAX_DETAIL_CHARS",
    "RECORD_TIMEOUT_S",
    "RecordOutcome",
    "forget_all",
    "mark_emailed",
    "record",
]
