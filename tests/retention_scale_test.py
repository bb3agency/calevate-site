"""The retention tick: what it COSTS, and what it actually erases (SEC-COMP §1/§4).

Two audits landed on the same job.

**Cost.** `apply_retention` opened a session per organization — ~16k of them on this
database — so the nightly tick's price was the client list, not the data. A platform
that signs its 200th client must not thereby make its legal obligation slower to
discharge. The tests here measure the SHAPE, not the clock: which tenants get visited,
how many sessions are opened, how many write statements are issued. Wall time on a
shared box is not evidence.

**Derived copies.** `calls.summary` and `call_extractions.data` are both written FROM
the transcript. When the transcript aged out, they stayed — so "transcripts are
retained for N days" was true of a table and false of a person. The policy this suite
pins, in a compliance reviewer's words:

  - The summary is a retelling of the call. It carries the same personal data as the
    turns it paraphrases, so it expires ON THE TRANSCRIPT CLOCK.
  - The extraction payload is the client's CRM — name, callback number, captured fields
    — the same class of record as `leads.data`. It survives the transcript, as the
    client needs it to, and expires ON THE LEAD CLOCK. Not never.
  - Both facts come from the tenant's own `retention_policies` rows, by `data_category`.
    Remove the row and the sweep does nothing: there is no hardcoded erasure.

Every tenant here is created by this module, because other suites run against the same
database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.session import get_engine, tenant_session, untenanted_session
from apps.workers import retention
from apps.workers.retention import REDACTED_MARK, sweep_tenant, sweep_tenants
from sqlalchemy import event, text
from tests.conftest import FakeS3, accept_agreements

SUMMARY = "Caller asked to reschedule Tuesday's appointment"
EXTRACTED: str = '{"name": "Ravi", "callback": "+919876500099", "intent": "book"}'


# ------------------------------------------------------------------ fixtures/helpers


async def _org(*, published: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with the default retention policies. `published` writes the engine
    route — the bridge row `publish_agent` writes for every agent that can take a call,
    and therefore the marker that this tenant can hold call data at all."""
    created = await admin_service.create_organization(
        name="Retention Scale",
        slug=f"rsc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    if published:
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, created_at, updated_at) VALUES ('fake', :ref, :t, :a, "
                    "true, now(), now())"
                ),
                {"ref": f"rsc_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
            )
    return tenant_id, agent_id


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    days_ago: int,
    summary: str | None = SUMMARY,
    extraction_days_ago: int | None = None,
) -> uuid.UUID:
    """One completed call with a transcript turn, and optionally its extraction."""
    call_id = uuid.uuid4()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', "
                "'+919876500021', '+911140000000', :w, :w, 90, 'recordings/x.wav', :s, :w, :w)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{call_id.hex[:10]}",
                "w": when,
                "s": summary,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, 0, 'caller', "
                "'naaku appointment kavali', 'naaku appointment kavali', :w, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id, "w": when},
        )
        if extraction_days_ago is not None:
            stamp = datetime.now(UTC) - timedelta(days=extraction_days_ago)
            await session.execute(
                text(
                    "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                    "model, valid, created_at, updated_at) VALUES (:i, :t, :c, 1, "
                    "CAST(:d AS jsonb), 'sarvam-105b', true, :w, :w)"
                ),
                {"i": uuid.uuid4(), "t": tenant_id, "c": call_id, "d": EXTRACTED, "w": stamp},
            )
    return call_id


async def _leads(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, count: int, days_ago: int) -> None:
    when = datetime.now(UTC) - timedelta(days=days_ago)
    async with tenant_session(tenant_id) as session:
        for _ in range(count):
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, data, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Ravi', "
                    "'inbound_call', 'new', '{\"intent\": \"book\"}'::jsonb, :w, :w)"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": tenant_id,
                    "a": agent_id,
                    "p": f"+9198{uuid.uuid4().int % 100000000:08d}",
                    "w": when,
                },
            )


async def _row(tenant_id: uuid.UUID, sql: str, params: dict[str, Any]) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


@contextmanager
def _statements() -> Iterator[list[str]]:
    """Every SQL statement the sweep sends, in order. The honest unit of cost."""
    seen: list[str] = []
    engine = get_engine().sync_engine

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        seen.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _writes(statements: list[str]) -> list[str]:
    return [s for s in statements if s.upper().startswith(("UPDATE", "DELETE"))]


@contextmanager
def _counting_sessions(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[uuid.UUID]]:
    """Records which tenants the sweep actually enters."""
    visited: list[uuid.UUID] = []
    real = retention.tenant_session

    @asynccontextmanager
    async def counting(tenant_id: uuid.UUID) -> AsyncIterator[Any]:
        visited.append(tenant_id)
        async with real(tenant_id) as session:
            yield session

    monkeypatch.setattr(retention, "tenant_session", counting)
    yield visited


# ----------------------------------------------------------------- 1. the cost shape


async def test_the_tick_visits_tenants_with_data_not_the_client_directory() -> None:
    """The regression, stated as a set: adding organizations that can hold no call data
    must not add a single tenant to the sweep's worklist.

    Asserted as a difference rather than a total, because other suites are creating
    tenants against this database at the same time.
    """
    with_data, agent_id = await _org()
    await _call(with_data, agent_id, days_ago=400)

    before = set(await retention._due_tenants())
    newcomers = [(await _org(published=False))[0] for _ in range(5)]
    after = set(await retention._due_tenants())

    assert with_data in after, "a tenant that can hold call data must be swept"
    assert not (set(newcomers) & after), "five new clients added five sessions to the tick"
    assert set(newcomers).isdisjoint(before | after)


async def test_the_sweep_opens_exactly_one_session_per_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, agent = await _org()
    await _call(first, agent, days_ago=400)
    second, _ = await _org()
    third, _ = await _org()

    with _counting_sessions(monkeypatch) as visited:
        await sweep_tenants([first, second, third])

    assert visited == [first, second, third]


async def test_a_tenant_with_nothing_expired_costs_a_probe_and_no_writes() -> None:
    """The old shape issued four blind UPDATEs per tenant per tick — writes against
    tables where nothing had aged out. Now a tenant is asked once."""
    tenant_id, agent_id = await _org()
    await _call(tenant_id, agent_id, days_ago=5, extraction_days_ago=5)
    await _leads(tenant_id, agent_id, count=2, days_ago=5)

    with _statements() as statements:
        counts = await sweep_tenant(tenant_id)

    assert not any(counts.values()), "nothing was old enough to sweep"
    assert _writes(statements) == [], "an idle tenant paid for writes that matched no rows"
    probes = [s for s in statements if "retention_policies" in s]
    assert len(probes) == 1, "the tenant's policies and its backlog are one question"


async def test_work_is_proportional_to_the_rows_that_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Statement count tracks the data, not the tenant count: a busy tenant issues
    write statements, its idle neighbours issue none."""
    busy, busy_agent = await _org()
    await _call(busy, busy_agent, days_ago=400)
    idle = [(await _org())[0] for _ in range(3)]

    with _statements() as statements:
        await sweep_tenants([*idle, busy])

    assert len(_writes(statements)) > 0
    # 3 idle tenants + 1 busy one: the writes belong to the busy one alone, and the
    # idle ones cost one probe each.
    probes = [s for s in statements if "retention_policies" in s]
    assert len(probes) == 4


async def test_one_enormous_tenant_cannot_starve_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A churned client with years of leads must not own the whole tick. The budget cuts
    them off, reports the remainder as deferred, and the next tenant is still swept."""
    huge, huge_agent = await _org()
    await _leads(huge, huge_agent, count=5, days_ago=1200)
    small, small_agent = await _org()
    await _leads(small, small_agent, count=1, days_ago=1200)

    monkeypatch.setattr(retention, "TENANT_ROW_BUDGET", 2)
    monkeypatch.setattr(retention, "SWEEP_BATCH_ROWS", 1)

    first_tick = await sweep_tenants([huge, small])
    assert first_tick["leads"] == 3, "2 from the huge tenant (its budget) + 1 from the small one"
    assert first_tick["deferred"] >= 1, "the remainder must be reported, not forgotten"

    # ...and the remainder is picked up by later ticks rather than sitting past its TTL.
    second = await sweep_tenants([huge, small])
    third = await sweep_tenants([huge, small])
    assert second["leads"] + third["leads"] == 3

    remaining = await _row(
        huge,
        "SELECT count(*) FROM leads WHERE left(phone_e164, 9) <> :anon",
        {"anon": retention.ANONYMIZED_PHONE[:9]},
    )
    assert remaining is not None and remaining[0] == 0


async def test_the_sweep_never_leaves_its_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cheap way to make this fast would be the admin role or an RLS exemption.
    Neither is available to a data-touching job (hard rule 1): the tenant list comes
    from the global routing bridge, and every row it touches is touched inside that
    tenant's session."""
    mine, agent = await _org()
    await _call(mine, agent, days_ago=400)
    neighbour, neighbour_agent = await _org()
    neighbour_call = await _call(neighbour, neighbour_agent, days_ago=400)

    # Not a style point: the enumeration this job used to do went through
    # `admin_session`, and the tempting "make it fast" fix is to widen that further.
    # The module must not hold a handle to any cross-tenant data path at all.
    assert "admin_session" not in vars(retention), "the sweep reacquired a directory-wide session"

    await sweep_tenants([mine])

    survived = await _row(
        neighbour, "SELECT summary FROM calls WHERE id = :c", {"c": neighbour_call}
    )
    assert survived is not None and survived[0] == SUMMARY, "the sweep reached another tenant"


# --------------------------------------------------- 2. the derived copies (policy)


async def test_the_summary_written_from_a_transcript_ages_out_with_the_transcript() -> None:
    """SEC-COMP §4 promises a transcript retention limit. `calls.summary` is model-written
    prose about what the caller said — the same personal data in fewer words — so a
    sweep that anonymized the turns and left the summary made that promise false."""
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=400)

    counts = await sweep_tenant(tenant_id)

    row = await _row(
        tenant_id,
        "SELECT c.summary, t.text FROM calls c JOIN transcript_turns t ON t.call_id = c.id "
        "WHERE c.id = :c",
        {"c": call_id},
    )
    assert row is not None
    assert row[1] == REDACTED_MARK, "the transcript aged out"
    assert row[0] is None, "the summary of that transcript outlived it"
    assert counts["summaries"] == 1


async def test_crm_fields_outlive_the_transcript_and_expire_on_the_lead_clock() -> None:
    """The other half of the decision, and the one that protects the client: the
    extraction payload is their CRM. It must NOT vanish when the raw transcript does —
    that is much of what they bought — and it must not live forever either. It expires
    under the `lead` policy, the category that already governs this class of record.
    """
    tenant_id, agent_id = await _org()
    # Past the transcript TTL (365d), well inside the lead TTL (1095d).
    call_id = await _call(tenant_id, agent_id, days_ago=400, extraction_days_ago=400)

    await sweep_tenant(tenant_id)

    kept = await _row(
        tenant_id, "SELECT data FROM call_extractions WHERE call_id = :c", {"c": call_id}
    )
    assert kept is not None and kept[0].get("callback"), (
        "the client's CRM fields were deleted on the transcript clock"
    )

    # Now age the same row past the lead TTL and sweep again.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE call_extractions SET updated_at = now() - interval '1200 days' "),
        )
    counts = await sweep_tenant(tenant_id)

    gone = await _row(
        tenant_id, "SELECT data FROM call_extractions WHERE call_id = :c", {"c": call_id}
    )
    assert gone is not None and gone[0] == {}, (
        "the caller's name and callback number outlived every retention promise made about them"
    )
    assert counts["extractions"] == 1


async def test_the_derived_copies_follow_the_policy_row_not_a_hardcoded_rule(
    s3: FakeS3,
) -> None:
    """`data_category` is the vocabulary. A tenant whose transcript policy is absent (a
    BFSI overlay, a bespoke DPA) keeps its summaries — the sweep has no opinion of its
    own about what to erase."""
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=400)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM retention_policies WHERE data_category = 'transcript'")
        )

    counts = await sweep_tenant(tenant_id)

    row = await _row(
        tenant_id,
        "SELECT c.summary, t.text FROM calls c JOIN transcript_turns t ON t.call_id = c.id "
        "WHERE c.id = :c",
        {"c": call_id},
    )
    assert row is not None and row[0] == SUMMARY and row[1] != REDACTED_MARK
    assert counts["summaries"] == 0 and counts["transcripts"] == 0
    # And the categories the tenant DOES have a policy for still ran.
    assert counts["recordings"] == 1


async def test_every_derived_copy_is_governed_by_a_category_a_tenant_actually_has() -> None:
    """`DERIVED_COPIES` is the declaration a compliance reviewer reads. It is only true
    if every category it names is a real `retention_policies` category with a seeded
    default — a copy filed under a category no tenant has would be a copy nothing ever
    expires. (This is also the guard on inventing a `summary` category: the CHECK
    constraint enumerates the four, so a fifth is a migration, not a constant.)"""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        categories = {
            str(row[0])
            for row in (
                await session.execute(text("SELECT data_category FROM retention_policies"))
            ).all()
        }

    assert set(retention.DERIVED_COPIES) <= categories
    assert retention.DERIVED_COPIES["transcript"] == (
        "calls.summary",
        # The knowledge-gap quote columns hold the caller's own sentences, copied out of
        # `transcript_turns.text_redacted` by the gap detector. They were in NO category,
        # which is exactly the condition this test names: a copy nothing expires. Filed
        # under `transcript` because that is the category owning the words they came from,
        # not a fifth category — see this test's own docstring on why a fifth is a
        # migration rather than a constant.
        "knowledge_gap_occurrences.question_redacted",
        "knowledge_gaps.example_question_redacted",
    )
    assert retention.DERIVED_COPIES["lead"] == (
        "call_extractions.data",
        # The delivered webhook body (D-23): the client's CRM payload in object storage,
        # governed by the `lead` policy the tenant already has.
        "webhook_deliveries.payload_ref",
    )


async def test_a_longer_transcript_ttl_keeps_the_summary_for_exactly_as_long() -> None:
    """The summary's clock IS the transcript policy's ttl_days, not a constant that
    happens to match the default."""
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=400)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE retention_policies SET ttl_days = 730 WHERE data_category = 'transcript'")
        )

    await sweep_tenant(tenant_id)
    row = await _row(tenant_id, "SELECT summary FROM calls WHERE id = :c", {"c": call_id})
    assert row is not None and row[0] == SUMMARY, "a 730-day policy erased a 400-day-old call"
