"""Hard rule 6, driven rather than asserted: the flows voice-runtime's twin cannot reach.

`tests/voice_runtime_pii_logging_test.py` proves the receiver, which is the service a
vendor POSTs raw call data at. Everything AFTER the ack was covered by unit tests on the
redactor and by docstrings claiming the redactor is applied — and a docstring is not a
control. These tests run the real post-call pipeline, the real extraction, the real lead
upsert and a real crash through the real ASGI app, with the production log formatter
attached to the ROOT logger at DEBUG, and read the bytes.

**Read by capturing FORMATTED output, never `caplog.records`.** Redaction lives in
`JsonFormatter.format`, so an assertion over record attributes tests the wrong object: it
would pass on a service that emits a transcript to stdout on every call. The handler here
is the real one with the real formatter.

**Both directions, always.** "The phone number is absent" also passes when nothing was
logged, when the flow never ran, and when the handler was detached. Every test below
carries a positive control naming a line that path is known to emit.

The four fields this file exists to hold down, one per historical hole:

1. the record's EXTRAS — the original `REDACT_KEYS`/`redact_mapping` pair,
2. the rendered MESSAGE — `record.getMessage()`, which went out verbatim until the
   formatter started redacting it,
3. the EXCEPTION text — where a DBAPI error quotes its bound parameters, and
4. an extra whose value is not a `str`/`dict`/`list` — a model, a tuple, a `bytes` blob:
   the branch that used to hand the object to `json.dumps(default=str)` and log its
   `repr()`.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from apps.api.core.logging import JsonFormatter
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import SAMPLE_TURNS
from apps.workers.pipeline import ingest_engine_event, run_post_call_pipeline
from httpx import ASGITransport, AsyncClient

# AT MODULE SCOPE, and this is load-bearing rather than tidy. `create_app` runs
# `configure_logging`, which does `root.handlers = [handler]` — so importing the app
# inside a test would silently DETACH the capture handler the `logs` fixture just
# attached, and every assertion below would pass against an empty list. Importing here
# means the app is built once, at collection, before any fixture exists.
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text

# SAME REASON, AND IT BIT WHILE SECTION 5 WAS BEING WRITTEN: this import pulls in
# `apps.api.main`, whose `create_app` also runs `configure_logging`. Imported inside a
# test it detached the capture handler mid-run and every assertion below passed against
# an empty list — which the `logs.lines` positive control is what caught.
from tests.api_security_test import _make_tenant

# What the fixture call actually says out loud. `SAMPLE_TURNS` is read rather than
# retyped: a fixture edited to stop saying a phone number would silently turn every
# assertion below into a tautology.
SPOKEN_PHONE = "9876543210"
SPOKEN_NAME = "Ravi"

#: Section 5's fixture. A DIFFERENT number from `SPOKEN_PHONE`, so a leak can be
#: attributed to the surface it came out of rather than to the pipeline above.
UNMASKED_PHONE = "+919812345678"
UNMASKED_EMAIL = "priya.sharma@sunriseclinic.example"
TRANSCRIPT_FRAGMENTS = tuple(text_ for _speaker, text_ in SAMPLE_TURNS)

CLINIC_SCHEMA: list[dict[str, Any]] = [
    {"key": "name", "label": "Caller name", "type": "text", "reason": "who is calling"},
    {
        "key": "intent",
        "label": "Intent",
        "type": "enum",
        "enum_values": ["book", "reschedule", "enquiry"],
        "reason": "what they want",
    },
]


class _Capture(logging.Handler):
    """Every record any logger emits, rendered exactly as production renders it."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def logs() -> Iterator[_Capture]:
    """On the ROOT logger: the point is to catch a line from a logger nobody thought to
    check — SQLAlchemy's, arq's, a library's — not only from ours."""
    capture = _Capture()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    try:
        yield capture
    finally:
        root.removeHandler(capture)
        root.setLevel(previous_level)


def _assert_no_caller_data(logs: _Capture, *, context: str) -> None:
    leaked = [
        fragment
        for fragment in (SPOKEN_PHONE, SPOKEN_NAME, *TRANSCRIPT_FRAGMENTS)
        if fragment in logs.text
    ]
    assert not leaked, (
        f"{context}: hard rule 6 — caller data reached the log stream: {leaked}\n"
        f"lines:\n{logs.text[:4000]}"
    )


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recording copy needs a bucket; nothing here is about object storage."""

    async def _fake_copy(*, source_url: str, tenant_id: uuid.UUID, call_id: uuid.UUID) -> str:
        return f"recordings/{tenant_id}/{call_id}.wav"

    monkeypatch.setattr("apps.workers.pipeline.copy_recording", _fake_copy)


async def _seed_tenant(agent_ref: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    schema_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Sunrise Clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"clinic-{tenant_id.hex[:10]}"},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, engine_agent_ref, "
                "created_at, updated_at) VALUES (:id, :tid, 'Receptionist', 'inbound', 'Idi AI "
                "assistant. Call record avutundi.', 'Idi AI assistant. Call record avutundi.', "
                "'This call is being recorded.', 'live', 'fake', :ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": agent_ref},
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "published_at, created_at, updated_at) VALUES (:id, :tid, :aid, 1, "
                "CAST(:fields AS jsonb), now(), now(), now())"
            ),
            {
                "id": schema_id,
                "tid": tenant_id,
                "aid": agent_id,
                "fields": json.dumps(CLINIC_SCHEMA),
            },
        )
        await session.execute(
            text("UPDATE agents SET extraction_schema_id = :sid WHERE id = :aid"),
            {"sid": schema_id, "aid": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) VALUES ('fake', :ref, :tid, :aid, "
                "true, now(), now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
                "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true"
            ),
            {"ref": agent_ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id


# --- 1. the post-call pipeline: ingest, redaction, extraction, lead upsert -----


async def test_a_whole_post_call_pipeline_run_leaves_no_caller_data_in_the_logs(
    logs: _Capture,
) -> None:
    """The richest flow this codebase has. One call carries a transcript that speaks a
    phone number and a name out loud, an extraction payload built from it, a lead row
    keyed on the caller's number and five metered usage events — and every one of those
    steps logs.

    Driven through the real voice-runtime app and the real worker jobs, because the
    thing under test is what the CODE emits, and a hand-built payload would exercise a
    pipeline nobody runs.
    """
    reset_engine_cache()
    engine = get_engine()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    caller = f"+91{SPOKEN_PHONE}"
    agent_ref = "fakeagent_pii_" + uuid.uuid4().hex[:8]
    tenant_id = await _seed_tenant(agent_ref)

    engine.seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id, agent_ref=agent_ref, from_e164=caller, to_e164="+911140000000"
    )

    async with AsyncClient(
        transport=ASGITransport(app=voice_app), base_url="http://runtime"
    ) as client:
        response = await client.post(
            "/hooks/v1/engine/fake",
            json={"execution_id": execution_id, "status": "completed", "agent_id": agent_ref},
        )
    assert response.status_code == 202, response.text

    assert (
        await ingest_engine_event(
            {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
        )
        == "pipeline_enqueued"
    )
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    assert call_id is not None
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )

    # The flow really ran and really held the data — otherwise the absence below is a
    # statement about an empty database.
    async with tenant_session(tenant_id) as session:
        raw_turns = (
            await session.execute(
                text("SELECT text FROM transcript_turns WHERE call_id = :c"), {"c": call_id}
            )
        ).scalars()
        lead_phone = (
            await session.execute(
                text("SELECT phone_e164 FROM leads WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert any(SPOKEN_PHONE in turn for turn in raw_turns), "fixture must speak a number"
    assert lead_phone == caller, "the pipeline must have written the caller's number to a row"

    assert logs.lines, "no log output captured — the assertion below would prove nothing"
    _assert_no_caller_data(logs, context="post-call pipeline")


# --- 2. the crash path, which is where redaction is forgotten -----------------


async def test_a_crash_carrying_the_transcript_neither_leaks_it_nor_loses_the_diagnosis(
    logs: _Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two failures in one place, pulling opposite ways.

    `install_error_handlers` logs unhandled exceptions with `log.exception`. The
    exception MESSAGE is prose assembled upstream — this one holds a transcript turn,
    and `pydantic.ValidationError` renders `input_value=…` into its own message by
    design — so it must not survive. But the traceback is ALSO the only durable record
    of a 500 on a deployment with no Sentry DSN, and it used to be run through
    `redact_text` whole: a 200-character cap measured from the START of a multi-frame
    string. A twelve-frame traceback was cut off inside frame three, so the alert's
    "search the logs for code=… for the full context" pointed at ASGI middleware.

    Both halves are asserted here because fixing either one alone is easy and wrong: a
    cap that happens to hide the message is not a control, and a message kept for
    debuggability is a DPDP incident waiting for the right exception.
    """
    spoken = SAMPLE_TURNS[3][1]

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError(f"claim failed while holding {spoken}")

    import webhook_routes

    monkeypatch.setattr(webhook_routes, "claim_inbox_event", _boom)

    async with AsyncClient(
        transport=ASGITransport(app=voice_app, raise_app_exceptions=False),
        base_url="http://runtime",
    ) as client:
        response = await client.post(
            "/hooks/v1/engine/fake",
            json={"execution_id": f"exec_{uuid.uuid4().hex[:12]}", "status": "completed"},
        )
    assert response.status_code == 500

    _assert_no_caller_data(logs, context="unhandled exception")

    crashed = [line for line in logs.lines if '"msg": "unhandled_exception"' in line]
    assert crashed, "the crash must be logged at all"
    rendered = json.loads(crashed[0])["exc"]
    assert "Traceback (most recent call last)" in rendered
    # WHAT CLASS: kept, because a type name is ours and is what the alert fingerprints on.
    assert "ValueError: [message withheld]" in rendered
    # The transcript the message was carrying is gone with it — `_assert_no_caller_data`
    # above is the whole-stream version of this, asserted again on the field itself.
    assert spoken not in rendered
    assert SPOKEN_NAME not in rendered
    # WHERE: the frames, which the character cap used to eat — including the `raise`
    # line itself, which is what makes a withheld message survivable.
    assert rendered.count('  File "') >= 3, "the stack is still a stack"
    assert "webhook_routes.py" in rendered, "and the frames that led there"
    # Every frame keeps its indented SOURCE line, which is what makes a withheld message
    # survivable — the reader sees the statement that raised. Asserted structurally
    # rather than by quoting a source line, because CPython renders frames from the file
    # on disk and a test that quotes one is pinned to its own line numbers.
    lines = rendered.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith('File "'):
            assert lines[index + 1].startswith("  ") and lines[index + 1].strip()

    # And the alarm this crash raises is fingerprinted on the exception CLASS.
    # `alerting._admit` holds a fingerprint for fifteen minutes, so one `code` shared by
    # every crash in the service means the first class to fire silences the rest for a
    # quarter of an hour — the availability hole D-147 found one instance of
    # (`ClientDisconnect`, free from anywhere) and closed at one call site.
    alerted = [json.loads(line) for line in logs.lines if '"msg": "alert"' in line]
    codes = [entry.get("code") for entry in alerted]
    assert "unhandled_exception:ValueError" in codes, f"crash alarm not class-specific: {codes}"


async def test_a_database_error_logs_its_constraint_and_not_its_parameters(
    logs: _Capture,
) -> None:
    """The production spelling of the leak. `str(sqlalchemy.exc.IntegrityError)` renders
    the bound parameters unless the engine hides them, and a transcript insert's
    parameters ARE the transcript.

    `hide_parameters=True` on `get_engine()` is the control, and it holds twice over:
    `str(exc)` carries `[SQL parameters hidden due to hide_parameters=True]` instead of
    the values, and the formatter withholds the driver's message anyway. Measured while
    writing this: psycopg keeps the server's `DETAIL:  Key (phone_e164)=(…)` line — which
    carries the conflicting VALUE and which no parameter flag can suppress — on
    `exc.orig.diag`, NOT in `str(exc)`, so the primary message is clean. That is the
    property the whole control rests on, and it is asserted rather than assumed.

    What is deliberately NOT asserted is the constraint name: the message is withheld,
    so `speaker_enum` is gone from the log line. That is the acknowledged cost of failing
    closed (`core/logging.redact_exception`), and the frames carry the failing statement's
    call site in its place.
    """
    tenant_id = uuid.uuid4()
    log = logging.getLogger("calevate.test.dberror")
    async with tenant_session(tenant_id) as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, lang) VALUES (:id, :tid, :cid, 0, 'not-a-speaker', :text, "
                    "'[redacted]', 'te')"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "cid": uuid.uuid4(),
                    "text": SAMPLE_TURNS[3][1],
                },
            )
        except Exception:
            log.exception("transcript_insert_failed", extra={"tenant_id": str(tenant_id)})
        else:  # pragma: no cover - the insert must fail for this test to mean anything
            pytest.fail("the constraint did not reject the row")

    _assert_no_caller_data(logs, context="IntegrityError")
    rendered = json.loads(
        next(line for line in logs.lines if '"transcript_insert_failed"' in line)
    )["exc"]
    assert "sqlalchemy.exc.IntegrityError: [message withheld]" in rendered
    assert "pii_logging_sweep_test.py" in rendered, "the calling frame still names itself"
    # The `[SQL: …]` / `[SQL parameters hidden …]` block is part of the message and goes
    # with it. It carried no values, but it is prose from a library and is not judged
    # line by line — the rule is the message, not a per-line exemption list.
    assert "[SQL:" not in rendered


# --- 3. the three record fields that are not extras ---------------------------


def test_an_interpolated_log_message_is_redacted_like_everything_else(
    logs: _Capture,
) -> None:
    """`record.getMessage()` is the field no key-based rule can reach: there is no key.

    Nothing in `apps/` interpolates a value into a log message today
    (`test_every_log_message_in_the_tree_is_a_static_token` holds that line), which is
    exactly why this needs a test — the rule is currently kept by everyone remembering
    it, and the formatter is where it stops depending on memory.
    """
    logging.getLogger("calevate.test.msg").warning(
        "delivering to %s for %s", f"+91{SPOKEN_PHONE}", SPOKEN_NAME
    )

    (line,) = logs.lines
    assert SPOKEN_PHONE not in line
    assert "[phone]" in line
    assert "delivering to" in line, "the event name survives; only the values are taken"


def test_an_extra_that_is_not_a_string_cannot_log_its_own_repr(logs: _Capture) -> None:
    """The branch that used to hand the object to `json.dumps(default=str)`.

    A tuple of turns serialized as a JSON array of raw strings; a Pydantic model — which
    this repo puts at every boundary — rendered as `role='user' text='<the turn>'`. Both
    reached the log stream with no masking and no cap at all.
    """
    from pydantic import BaseModel

    class Turn(BaseModel):
        speaker: str
        text: str

    spoken = SAMPLE_TURNS[3][1]
    log = logging.getLogger("calevate.test.types")
    log.info("model", extra={"turn": Turn(speaker="caller", text=spoken)})
    log.info("tuple", extra={"turns": (spoken, spoken)})
    log.info("bytes", extra={"blob": spoken.encode()})

    blob = logs.text
    assert SPOKEN_PHONE not in blob, "a non-string extra carried a phone number out"
    assert '"turns": "[2 items]"' in blob, "a sequence collapses to a count, not its elements"


def test_the_leak_detector_bites(logs: _Capture) -> None:
    """The control on the control. Every assertion above is an ABSENCE, and an absence
    proves nothing unless the search would have found the thing if it were there."""
    logging.getLogger("calevate.test.control").info("planted", extra={"note": SPOKEN_NAME})

    with pytest.raises(AssertionError, match="caller data reached the log stream"):
        _assert_no_caller_data(logs, context="control")


# --- 4. the discipline the formatter now backstops ----------------------------


def test_every_log_message_in_the_tree_is_a_static_token() -> None:
    """A log MESSAGE is an event name, and its values belong in `extra` where the
    key-based redaction can see them.

    The formatter redacts the message too, so this is no longer the only defence — but
    a masked interpolation is a degraded log line, and `redact_text` cannot recognise a
    caller's NAME or a Telugu sentence in one. Keeping messages static is what keeps the
    formatter a backstop rather than the guard.

    What is refused is every spelling of "a value was interpolated into the message":
    an f-string, a `%`/`+` expression, a `.format()` call, and printf-style positional
    args after the message. A bare NAME is allowed — `workers/retention.py` passes an
    event name down as a parameter and all three call sites hand it a literal — which
    leaves the residual "somebody assigns an f-string to a variable first". That
    residual is why the formatter redacts the message too: this guard keeps the log
    lines READABLE, the formatter is what keeps them safe.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    methods = {"debug", "info", "warning", "error", "exception", "critical"}
    offenders: list[str] = []
    for path in sorted(root.glob("apps/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in methods or not node.args:
                continue
            receiver = node.func.value
            name = getattr(receiver, "id", None) or getattr(receiver, "attr", None) or ""
            if "log" not in name.lower():
                continue
            first = node.args[0]
            where = f"{path.relative_to(root)}:{node.lineno}"
            if isinstance(first, ast.Constant | ast.Name):
                if len(node.args) > 1:
                    offenders.append(f"{where} interpolates positional args into the message")
            else:
                offenders.append(f"{where} message is computed, not an event name")
    assert not offenders, (
        "a log message must be a static event name; put the values in `extra=` where "
        "REDACT_KEYS can see them:\n  " + "\n  ".join(offenders)
    )


def test_only_one_database_engine_exists_and_it_hides_its_parameters() -> None:
    """`hide_parameters=True` is a hard-rule-6 control, and it is a property of ONE
    engine object. A second `create_async_engine` anywhere in `apps/` would be a second
    engine with SQLAlchemy's default — parameters rendered into every DBAPI error
    string — and nothing about the first engine's flag would say so.

    Scoped to `apps/` on purpose. `alembic/env.py` builds its own engine deliberately
    (migration review keeps its parameter echo) and `scripts/check_*.py` read catalogs
    with no bound user data; neither serves a request.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    builders = {"create_async_engine", "create_engine"}
    found: list[tuple[str, bool]] = []
    for path in sorted(root.glob("apps/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in builders:
                continue
            hides = any(
                kw.arg == "hide_parameters"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            )
            found.append((f"{path.relative_to(root)}:{node.lineno}", hides))

    assert found, "no engine found — this guard is watching the wrong tree"
    assert len(found) == 1, f"more than one engine is built in apps/: {found}"
    (where, hides) = found[0]
    assert hides, f"{where} builds an engine without hide_parameters=True"


# --- 5. the read surfaces D-436 unmasked --------------------------------------
#
# EVERYTHING ABOVE IS THE WRITE PATH. D-436 changed the READ path: `LeadOut.phone_masked`
# became `phone_e164`, `CallSummaryOut.caller_masked` became `caller_e164`,
# `DncEntryOut.phone_masked` became `phone_e164`, `PendingInvitation.email_masked` became
# `email`, and `crm.attention` stopped masking the number it titles a blocked lead with.
# That decision is about RESPONSES and hard rule 6 is untouched by it — but removing the
# `mask_phone` call sites is exactly the change after which a full number can reach a log
# line by accident, because the handler now holds one where it used to hold six dots.
#
# So the same method as every test above: run the real routes through the real ASGI app
# with the production formatter on the ROOT logger, and read the bytes.


def _api_client(*, raise_app_exceptions: bool = True) -> AsyncClient:
    """The monolith over ASGI. Its own helper rather than `api_security_test._client`
    because the crash test needs `raise_app_exceptions=False` — without it httpx re-raises
    and the 500 the error handler composed (and logged) is never observed."""
    from apps.api.main import app as api_app

    return AsyncClient(
        transport=ASGITransport(app=api_app, raise_app_exceptions=raise_app_exceptions),
        base_url="http://api",
    )


async def _unmasked_read_fixture() -> tuple[dict[str, str], uuid.UUID, uuid.UUID, str]:
    """One tenant whose every newly-unmasked surface has something to render.

    The lead is deliberately NAMELESS: `crm.attention.blocked_leads` titles a blocked
    lead with its captured name and falls back to the raw number, so a named lead would
    make the attention queue's title a name and the number would never be in scope at
    all — the assertion would hold for the wrong reason.
    """
    tenant_id, slug, token = await _make_tenant("owner")
    lead_id, call_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, status, source, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :p, 'new', 'inbound_call', "
                "now(), now())"
            ),
            {"id": lead_id, "tid": tenant_id, "aid": agent_id, "p": UNMASKED_PHONE},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, "
                "direction, status, from_e164, started_at, duration_s, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :lid, :e, 'inbound', 'completed', :p, now(), 30, "
                "now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "lid": lead_id,
                "e": f"unmasked_{call_id.hex[:12]}",
                "p": UNMASKED_PHONE,
            },
        )
        # A blocked-dial note, which is what puts the lead on the needs-attention queue.
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'note', CAST(:p AS jsonb), "
                "'system', now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "lid": lead_id,
                "p": json.dumps({"kind": "blocked", "rule": "dnc"}),
            },
        )
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:id, :tid, :p, 'tenant', 'manual', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "p": UNMASKED_PHONE},
        )
        await session.execute(
            text(
                "INSERT INTO invitations (id, tenant_id, email, role, token_hash, expires_at, "
                "created_at, updated_at) VALUES (:id, :tid, :email, 'staff', :hash, "
                "now() + interval '3 days', now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "email": UNMASKED_EMAIL,
                "hash": uuid.uuid4().hex * 2,
            },
        )
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    return headers, lead_id, call_id, slug


async def test_reading_every_newly_unmasked_screen_logs_no_contact_identifier(
    logs: _Capture,
) -> None:
    """Nine responses that now carry a full number, name or address, and one log stream.

    THE POSITIVE CONTROLS ARE THE POINT, twice over. Each response is asserted to have
    actually rendered the identifier — otherwise "the number is not in the logs" is a
    statement about a 403 — and the log stream is asserted non-empty, because a detached
    handler passes every absence.
    """
    headers, lead_id, call_id, _slug = await _unmasked_read_fixture()
    rendered: dict[str, str] = {}
    async with _api_client() as http:
        for path in (
            "/v1/calls",
            f"/v1/calls/{call_id}",
            "/v1/leads",
            f"/v1/leads/{lead_id}",
            "/v1/attention",
            "/v1/dnc",
            "/v1/invitations",
        ):
            response = await http.get(path, headers=headers)
            assert response.status_code == 200, (path, response.text[:300])
            rendered[path] = response.text
        # `search` is matched against `phone_e164`, which is why it is a POST and not a
        # query string (`crm.routes._SEARCH_MOVED_TO_POST`) — so a number in a REQUEST is
        # covered here too, not only one in a response.
        search = await http.post(
            "/v1/leads/search", headers=headers, json={"search": UNMASKED_PHONE[-6:]}
        )
        assert search.status_code == 200, search.text[:300]
        rendered["/v1/leads/search"] = search.text
        # The audited bulk extract: the one route that takes the whole list out, and the
        # one whose handler writes an `audit_log` row with a summary that goes to the log
        # stream. `searched` must be a BOOLEAN there and never its text.
        export = await http.post(
            "/v1/leads/export.csv", headers=headers, json={"search": UNMASKED_PHONE[-6:]}
        )
        assert export.status_code == 200, export.text[:300]
        rendered["/v1/leads/export.csv"] = export.text

    # Each surface really did render what D-436 says it renders.
    assert UNMASKED_PHONE in rendered["/v1/leads"], "the leads list is masked again"
    assert UNMASKED_PHONE in rendered[f"/v1/calls/{call_id}"], "the call detail is masked again"
    assert UNMASKED_PHONE in rendered["/v1/dnc"], "the suppression list is masked again"
    assert UNMASKED_PHONE in rendered["/v1/attention"], (
        "the blocked-lead title fell back to something other than the number, so this "
        "test is not exercising the fallback D-436 changed"
    )
    assert UNMASKED_EMAIL in rendered["/v1/invitations"], "the invite list is masked again"
    assert UNMASKED_PHONE in rendered["/v1/leads/export.csv"], "the export lost its column"

    assert logs.lines, "no log output captured — the assertion below would prove nothing"
    leaked = [
        fragment
        for fragment in (UNMASKED_PHONE, UNMASKED_PHONE.removeprefix("+91"), UNMASKED_EMAIL)
        if fragment in logs.text
    ]
    assert not leaked, (
        "hard rule 6: D-436 unmasked the RESPONSE, and one of these surfaces then put the "
        f"identifier in a log line too: {leaked}\nlines:\n{logs.text[:4000]}"
    )


async def test_a_crash_inside_a_handler_holding_a_full_contact_list_leaks_nothing(
    logs: _Capture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crash path for the READ side, which is where the removed masking bites.

    `LeadPage` now holds real numbers, so `raise ValueError(f"... {page!r}")` — or any
    library that renders what it was handed — puts a whole contact list in the exception
    message. `redact_exception` withholds the message and keeps the frames; this asserts
    that on the shape D-436 created rather than on the pipeline's.
    """
    from apps.api.crm import service as crm

    headers, _lead_id, _call_id, _slug = await _unmasked_read_fixture()
    real = crm.list_leads_page

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        page = await real(*args, **kwargs)
        raise ValueError(f"serialization failed holding {page!r}")

    monkeypatch.setattr(crm, "list_leads_page", _boom)
    async with _api_client(raise_app_exceptions=False) as http:
        response = await http.get("/v1/leads", headers=headers)
    assert response.status_code == 500

    crashed = [line for line in logs.lines if '"msg": "unhandled_exception"' in line]
    assert crashed, "the crash must be logged at all"
    assert "ValueError: [message withheld]" in json.loads(crashed[0])["exc"]
    for spelling in (UNMASKED_PHONE, UNMASKED_PHONE.removeprefix("+91")):
        assert spelling not in logs.text, f"a contact list left through a 500 as {spelling!r}"
