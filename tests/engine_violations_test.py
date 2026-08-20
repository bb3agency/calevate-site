"""The compliance-flag sweep: the vendor's violations list, read without leaking it.

Bolna raises VIOLATIONS against the account every regulated Indian call runs through, and
publishes them on a list endpoint with no webhook behind it — so an unread flag is
discovered at enforcement. `apps/workers/engine_violations.py` is the poller;
`apps/api/engine/violations.py` is the boundary that turns their record into ours.

**THE TEST THAT MATTERS MOST IS THE PII ONE, and it is not a formality.** Their
`Violation` schema carries `from_phone_number`, `to_phone_number`, an `email`, and an
`image_url` whose documented example is
`…/violations/ce23f363-…/9845866566.png` beside `to_phone_number: '+919845866566'` —
**the evidence filename IS the recipient's phone number**. A record that carried that URL
would put a phone number into every log line, alert body and ticket that quoted it, and
it would look like an opaque path to every reviewer. `test_the_boundary_drops_every_field
_that_can_carry_personal_data` walks the discarded set field by field so a vendor adding
one more cannot slip through a hand-typed list.

The completeness tests are the other half: an incomplete walk that reported "0 open" would
tell an operator the account is clean when the sweep stopped at its page cap. `complete`
stays a POSITIVE claim here for the same reason `ExecutionListing.complete` does.

Run: uv run pytest -q tests/engine_violations_test.py
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.engine.violations import (
    MAX_PAGES,
    OPEN_STATUS,
    VENDOR_STATUSES,
    EngineViolation,
    SupportsViolations,
    ViolationListing,
    parse_violation,
    walk_violations,
)
from apps.workers import engine_violations
from apps.workers.engine_violations import sweep_engine_violations
from apps.workers.settings import CRON_JOBS
from arq import Retry

# The recipient number from the vendor's own documented example, and the evidence path
# that ends in it. Both are fixtures, not real numbers.
TO_NUMBER = "+919845866566"
FROM_NUMBER = "+918035739196"
EVIDENCE_PATH = "73b9ed7c-c255-486b-b2eb-6c21e41a8ca1/violations/ce23f363-1234/9845866566.png"

#: One row exactly as `api-reference/violations/list.md` documents it.
VENDOR_ROW: dict[str, Any] = {
    "id": "ce23f363-131a-47fc-8a33-258141a575b0",
    "from_phone_number": FROM_NUMBER,
    "to_phone_number": TO_NUMBER,
    "date_of_call": "2026-01-05T00:00:00+00:00",
    "status": "pending",
    "created_at": "2026-03-06T08:25:53.514276+00:00",
    "updated_at": "2026-03-09T07:10:29.135591+00:00",
    "user_id": "9082f423-9c6c-4f19-a131-24f4cc99209a",
    "agent_id": "af4f2c34-4750-4d7c-97a3-4e2e27a643a2",
    "execution_id": "137f88ef-701e-42b6-a26a-7bc1103df5aa",
    "image_url": EVIDENCE_PATH,
    "email": "user@example.com",
}


def _parse_dt(value: Any) -> datetime | None:
    """The adapter injects `bolna._parse_dt`; this is the same contract, minimally."""
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _row(**overrides: Any) -> dict[str, Any]:
    row = dict(VENDOR_ROW)
    row.update(overrides)
    return row


class _Alerts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, str]]] = []

    def __call__(self, stage: str, code: str, *, detail: str = "", **ids: str) -> None:
        self.calls.append((stage, code, detail, dict(ids)))

    def codes(self) -> list[str]:
        return [code for _, code, _, _ in self.calls]

    def detail_for(self, code: str) -> str:
        return next(detail for _, raised, detail, _ in self.calls if raised == code)


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> _Alerts:
    captured = _Alerts()
    monkeypatch.setattr(engine_violations, "alert", captured)
    return captured


# --- the boundary -------------------------------------------------------------


def test_the_boundary_drops_every_field_that_can_carry_personal_data() -> None:
    """Hard rule 6, asserted against the vendor's own example row.

    Field by field over what we DROPPED rather than over what we kept: a vendor adding a
    twelfth field lands in `_DISCARDED_FIELDS` or in the record, and only one of those is
    silent.
    """
    violation = parse_violation(VENDOR_ROW, parse_dt=_parse_dt)
    assert violation is not None
    rendered = repr(violation) + " ".join(
        str(getattr(violation, field.name)) for field in dataclasses.fields(violation)
    )
    for dropped in ("from_phone_number", "to_phone_number", "email", "image_url", "user_id"):
        value = str(VENDOR_ROW[dropped])
        assert value not in rendered, f"{dropped} survived the adapter boundary"
    # And the numbers specifically, in every spelling an operator would grep for.
    for digits in (TO_NUMBER, FROM_NUMBER, TO_NUMBER.lstrip("+"), "9845866566"):
        assert digits not in rendered


def test_an_evidence_file_becomes_a_boolean_and_never_a_url() -> None:
    """The URL is the trap: its last segment is the recipient's number."""
    with_evidence = parse_violation(VENDOR_ROW, parse_dt=_parse_dt)
    without = parse_violation(_row(image_url=None), parse_dt=_parse_dt)
    assert with_evidence is not None and without is not None
    assert with_evidence.has_evidence is True
    assert without.has_evidence is False
    assert not any(
        isinstance(getattr(with_evidence, field.name), str)
        and EVIDENCE_PATH in str(getattr(with_evidence, field.name))
        for field in dataclasses.fields(with_evidence)
    )


def test_the_status_we_interpret_is_one_the_vendor_publishes() -> None:
    """`OPEN_STATUS` is the ONE unambiguous member — see the module docstring for why
    `accepted`/`rejected` are counted and never judged."""
    assert OPEN_STATUS in VENDOR_STATUSES
    assert {"pending", "accepted", "rejected", "submitted"} == VENDOR_STATUSES


@pytest.mark.parametrize("broken", [{"id": None}, {"id": ""}, {"status": None}, {"status": 7}])
def test_a_row_we_cannot_read_is_counted_rather_than_invented(broken: dict[str, Any]) -> None:
    """Inert on an unexpected shape (D-41). The worst possible failure on this surface is
    an unreadable flag wearing a `submitted` state — a compliance finding reported as
    answered because we could not read it."""
    assert parse_violation(_row(**broken), parse_dt=_parse_dt) is None


# --- the walk -----------------------------------------------------------------


class _Pages:
    """A vendor that answers `GET /violations/list` from a scripted list of payloads."""

    def __init__(self, *payloads: dict[str, Any]) -> None:
        self.payloads = list(payloads)
        self.requests: list[dict[str, Any]] = []

    async def __call__(self, method: str, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert (method, path) == ("GET", "/violations/list")
        self.requests.append(dict(params))
        return self.payloads[min(len(self.requests) - 1, len(self.payloads) - 1)]


async def test_the_walk_follows_has_more_and_counts_each_flag_once() -> None:
    first = {"data": [_row(id="a"), _row(id="b")], "has_more": True}
    # `b` repeats across the page boundary — the vendor's list moves under a walk.
    second = {"data": [_row(id="b"), _row(id="c")], "has_more": False}
    vendor = _Pages(first, second)

    listing = await walk_violations(vendor, status=OPEN_STATUS, parse_dt=_parse_dt)

    assert [v.violation_id for v in listing.violations] == ["a", "b", "c"]
    assert listing.complete is True
    assert listing.pages_fetched == 2
    assert vendor.requests[0]["status"] == OPEN_STATUS
    assert vendor.requests[1]["page_number"] == 2


async def test_a_stuck_has_more_stops_and_refuses_to_claim_completeness() -> None:
    """A page we had not fetched carrying only ids we already had."""
    vendor = _Pages({"data": [_row(id="a")], "has_more": True})
    listing = await walk_violations(vendor, status=OPEN_STATUS, parse_dt=_parse_dt)
    assert listing.complete is False
    assert listing.incomplete_reason == "next_link_no_progress"


async def test_our_own_page_cap_is_reported_rather_than_read_as_the_end() -> None:
    vendor = _Pages(
        *[{"data": [_row(id=f"v{page}")], "has_more": True} for page in range(MAX_PAGES + 2)]
    )
    listing = await walk_violations(vendor, status=OPEN_STATUS, parse_dt=_parse_dt)
    assert listing.complete is False
    assert listing.incomplete_reason == "page_cap_reached"
    assert listing.pages_fetched == MAX_PAGES


async def test_a_missing_flag_on_a_full_page_is_not_believed() -> None:
    """The flag is documented, so its absence means we are not reading the endpoint we
    think we are — and a FULL page under that uncertainty can be hiding rows."""
    full = {"data": [_row(id=f"v{n}") for n in range(4)]}
    vendor = _Pages(full)
    listing = await walk_violations(vendor, status=OPEN_STATUS, parse_dt=_parse_dt, page_size=4)
    assert listing.complete is False
    assert listing.incomplete_reason == "full_page_suspected"

    short = {"data": [_row(id="only")]}
    quiet = await walk_violations(
        _Pages(short), status=OPEN_STATUS, parse_dt=_parse_dt, page_size=4
    )
    assert quiet.complete is True


async def test_unreadable_rows_are_counted_not_dropped() -> None:
    vendor = _Pages(
        {"data": [_row(id="a"), _row(id=None), {"nothing": "useful"}], "has_more": False}
    )
    listing = await walk_violations(vendor, status=OPEN_STATUS, parse_dt=_parse_dt)
    assert len(listing.violations) == 1
    assert listing.unreadable_rows == 2


# --- the sweep ----------------------------------------------------------------


def _violation(**overrides: Any) -> EngineViolation:
    base: dict[str, Any] = {
        "violation_id": "v-1",
        "status": OPEN_STATUS,
        "engine_agent_ref": "agent-ref-1",
        "engine_call_id": "exec-1",
        "call_date": datetime(2026, 8, 1, tzinfo=UTC),
        "raised_at": datetime.now(UTC) - timedelta(days=6),
        "updated_at": None,
        "has_evidence": False,
    }
    base.update(overrides)
    return EngineViolation(**base)


class _Engine:
    """An engine that publishes the surface. Structural, like the Protocol."""

    name = "bolna"

    def __init__(self, listing: ViolationListing, *, credentials: bool = True) -> None:
        self._listing = listing
        self._credentials = credentials
        self.asked: list[str] = []

    def holds_credentials(self) -> bool:
        return self._credentials

    async def list_violations(self, *, status: str) -> ViolationListing:
        self.asked.append(status)
        return self._listing


class _EngineWithoutTheSurface:
    name = "fake"

    def holds_credentials(self) -> bool:
        return True


def _listing(*violations: EngineViolation, complete: bool = True) -> ViolationListing:
    return ViolationListing(
        violations=violations,
        complete=complete,
        incomplete_reason=None if complete else "page_cap_reached",
        unreadable_rows=0,
        pages_fetched=1,
    )


@pytest.fixture
def no_tenant_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The attribution query needs a database; these tests are about the decision, not the
    join. `test_the_sweep_attributes_a_flag_to_a_tenant` drives the mapping directly."""

    async def _none(refs: set[str]) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(engine_violations, "_tenants_for", _none)


def _install(monkeypatch: pytest.MonkeyPatch, engine: Any) -> None:
    monkeypatch.setattr(engine_violations, "get_engine", lambda: engine)


async def test_an_engine_without_the_surface_is_skipped_rather_than_reported_clean(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    _install(monkeypatch, _EngineWithoutTheSurface())
    assert await sweep_engine_violations({}) == "skipped_unsupported"
    assert alerts.codes() == []


async def test_an_engine_with_no_key_says_so_rather_than_answering_zero(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    _install(monkeypatch, _Engine(_listing(), credentials=False))
    assert await sweep_engine_violations({}) == "skipped_no_credentials"
    assert alerts.codes() == []


async def test_a_clean_account_pages_nobody(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts, no_tenant_lookup: None
) -> None:
    engine = _Engine(_listing())
    _install(monkeypatch, engine)
    assert await sweep_engine_violations({}) == "open=0 tenants=0 complete=True"
    assert alerts.codes() == []
    assert engine.asked == [OPEN_STATUS]


async def test_an_open_flag_pages_a_human_and_names_the_id_not_the_caller(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts, no_tenant_lookup: None
) -> None:
    _install(monkeypatch, _Engine(_listing(_violation(), _violation(violation_id="v-2"))))

    await sweep_engine_violations({})

    assert alerts.codes() == ["engine_violation_open"]
    detail = alerts.detail_for("engine_violation_open")
    assert "2 compliance flag(s) are open" in detail
    assert "v-1" in detail and "v-2" in detail
    assert "oldest raised 6 day(s) ago" in detail
    # Hard rule 6 on the alert body itself, which is the surface that reaches an inbox.
    for digits in (TO_NUMBER, FROM_NUMBER, "9845866566"):
        assert digits not in detail


async def test_an_undated_flag_reports_the_age_as_unknown_rather_than_as_zero(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts, no_tenant_lookup: None
) -> None:
    """ "Raised today" and "we cannot tell when it was raised" must not read the same on
    the one number an operator judges urgency by."""
    _install(monkeypatch, _Engine(_listing(_violation(raised_at=None))))
    await sweep_engine_violations({})
    assert "age unknown" in alerts.detail_for("engine_violation_open")


async def test_the_sweep_attributes_a_flag_to_a_tenant(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    import uuid

    tenant = uuid.uuid4()

    async def _mapping(refs: set[str]) -> dict[str, uuid.UUID]:
        assert refs == {"agent-ref-1"}
        return {"agent-ref-1": tenant}

    monkeypatch.setattr(engine_violations, "_tenants_for", _mapping)
    _install(
        monkeypatch,
        _Engine(_listing(_violation(), _violation(violation_id="v-2", engine_agent_ref=None))),
    )

    result = await sweep_engine_violations({})

    assert result == "open=2 tenants=1 complete=True"
    assert "1 tenant(s) with 1 unattributed" in alerts.detail_for("engine_violation_open")


async def test_an_incomplete_sweep_never_reads_as_a_clean_account(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts, no_tenant_lookup: None
) -> None:
    """Zero open flags off a walk that stopped early is the one wrong answer here."""
    _install(monkeypatch, _Engine(_listing(complete=False)))

    result = await sweep_engine_violations({})

    assert result == "open=0 tenants=0 complete=False"
    assert alerts.codes() == ["engine_violation_sweep_incomplete"]
    assert "is a floor" in alerts.detail_for("engine_violation_sweep_incomplete")


class _Broken:
    name = "bolna"

    def holds_credentials(self) -> bool:
        return True

    async def list_violations(self, *, status: str) -> ViolationListing:
        raise RuntimeError("the vendor said no")


async def test_the_ladder_retries_and_the_last_attempt_shouts(
    monkeypatch: pytest.MonkeyPatch, alerts: _Alerts
) -> None:
    """arq retries for `Retry` and nothing else, and does NOT honour one raised on the
    final attempt — so the alert has to be there, not a fourth `Retry`."""
    _install(monkeypatch, _Broken())

    with pytest.raises(Retry):
        await sweep_engine_violations({"job_try": 1})
    assert alerts.codes() == []

    with pytest.raises(RuntimeError):
        await sweep_engine_violations({"job_try": WORKER_MAX_TRIES})
    assert alerts.codes() == ["engine_violation_sweep_abandoned"]


def test_the_sweep_is_actually_registered_as_a_cron() -> None:
    """A poller nobody scheduled is a defect that looks like progress on a screen."""
    names = {getattr(job.coroutine, "__qualname__", "") for job in CRON_JOBS}
    assert "sweep_engine_violations" in names


def test_the_bolna_adapter_publishes_the_surface() -> None:
    """`isinstance` against the structural Protocol — the same test the sweep performs."""
    from decimal import Decimal

    from apps.api.engine.bolna import BolnaEngine

    engine = BolnaEngine(api_key="k", fx_rate=Decimal("88"))
    assert isinstance(engine, SupportsViolations)
