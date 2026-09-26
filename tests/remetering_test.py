"""Re-metering: an attested price reaching the calls that were waiting for it.

THE DEFECT THIS FILE PINS (founder audit, 19 Sep 2026). `settle_call` records a
`call_metering_refusals` row for a leg no attested rate covers, and both that table and
`usage_events` are append-only (hard rule 4) — so entering the price in the ops console a
week later billed every call from that moment on and none of the calls already refused. The
spend was real, absorbed and permanently uninvoiceable.

WHAT THESE TESTS ASSERT, IN THE ORDER THE MONEY MOVES

1. A refusal an attestation can answer parks the MEASUREMENT, in the settlement's own
   transaction, exactly once (`remeter:{call}:{leg}`).
2. A refusal an attestation can NEVER answer parks nothing, so the worklist holds no item
   that cannot be closed.
3. Once the price is attested, the sweep meters the old call — at the rate now on file and
   stamped with the SETTLEMENT's instant, which is what files it in its own IST month
   (D-250) rather than in the month the operator typed.
4. **IT CANNOT BILL TWICE.** Run twice, run concurrently, and run against a re-delivered
   settlement: one `usage_events` row. The guarantee is the database's — the unique indexes
   on `(tenant_id, call_id, unit_type)` plus `ON CONFLICT DO NOTHING` — and
   `test_the_double_bill_guard_is_the_database` is the one that fails if that insert ever
   loses its conflict clause.

SHARED DATABASE DISCIPLINE: the sweep is deliberately global (it must find every tenant's
debt), so every assertion here is scoped to the call this file created and nothing counts
rows across the fleet.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from apps.api.billing.rates import LlmPriceAttestation, install_llm_price_attestations
from apps.api.db.session import tenant_session
from apps.api.worker.service import REMETER_JOB
from apps.workers import remetering
from apps.workers.remetering import remeter_refused_legs
from calevate_shared.worker_api import (
    MeteredQuantity,
    SettlementRefusal,
    SettlementRequest,
)
from sqlalchemy import text
from tests.worker_api_harness import (
    call_ref,
    declare_pipecat_engine,
    published_agent,
    worker_client,
)

pytestmark = [pytest.mark.rls]

#: A model identifier the catalogue has never heard of, so `llm_inr_per_ktok` refuses it on
#: hard rule 7's own terms until an operator attests one — which is precisely the state a
#: real deployment is in for `gemini-2.5-flash-lite` today. An unknown id rather than a real
#: one so the test cannot start passing because somebody attested a shipped model.
UNPRICED_MODEL = "a-model-nobody-has-attested"

#: What the worker measured on the leg nobody could price. A quantity, never a price.
TOKENS = Decimal("12.5")


@pytest.fixture(autouse=True)
def _pipecat_deployment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`/v1/worker` refuses any other engine (D-627); declared per file, as the harness says."""
    yield from declare_pipecat_engine(monkeypatch)


@pytest.fixture(autouse=True)
def _no_ambient_attestations() -> Iterator[None]:
    """No attestation on file to begin with, and none left behind.

    `install_llm_price_attestations` is process-wide state (its own docstring argues why), so
    a test that installed one and walked away would price another file's leg.
    """
    install_llm_price_attestations(None)
    yield
    install_llm_price_attestations(None)


def _attest(price: str) -> None:
    install_llm_price_attestations(
        lambda: {
            UNPRICED_MODEL: LlmPriceAttestation(
                model=UNPRICED_MODEL,
                input_usd_per_mtok=Decimal(price),
                output_usd_per_mtok=Decimal(price),
                read_on=date(2026, 9, 19),
                attested_by="ops@calevate.test",
                source="vendor invoice INV-2026-09",
            )
        }
    )


def _settlement(agent_id: uuid.UUID, *, carrier_refusal: bool = True) -> SettlementRequest:
    """One leg we CAN measure and cannot price, beside the leg nobody witnessed at all.

    Both shapes in one body on purpose: D-625 made a settlement carry a refusal per leg and a
    quantity per leg, and the two refusals that come out of it are the two classes this fix
    distinguishes — one an attestation can answer, one it never can.
    """
    return SettlementRequest(
        final_status="completed",
        direction="inbound",
        agent_id=agent_id,
        refusals=(
            [
                SettlementRefusal(
                    leg="carrier",
                    code="meter_carrier_cdr_missing",
                    detail="no carrier CDR was supplied, so the connected duration has no witness.",
                    remediation="Retrieve the CDR from the carrier and meter again.",
                )
            ]
            if carrier_refusal
            else []
        ),
        quantities=[
            MeteredQuantity(
                leg="llm",
                unit_type="llm_ktok_in",
                qty=TOKENS,
                meta={"model": UNPRICED_MODEL, "total_tokens": "12500"},
            )
        ],
    )


async def _settled_call(*, carrier_refusal: bool = True) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A real settlement through the real route. Returns `(tenant, call row id, ref)`."""
    tenant_id, agent_id, _agent_ref = await published_agent()
    _call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        answer = await api.post_settlement(
            ref, _settlement(agent_id, carrier_refusal=carrier_refusal)
        )
    assert answer.already_settled is False
    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
    return tenant_id, uuid.UUID(str(row_id)), ref


async def _usage(tenant_id: uuid.UUID, call_row_id: uuid.UUID) -> list[tuple[str, Decimal, object]]:
    async with tenant_session(tenant_id) as db:
        return [
            (str(unit), Decimal(str(qty)), occurred_at)
            for unit, qty, occurred_at in (
                await db.execute(
                    text(
                        "SELECT unit_type, unit_cost_paid, occurred_at FROM usage_events "
                        "WHERE call_id = :c ORDER BY unit_type"
                    ),
                    {"c": call_row_id},
                )
            ).tuples()
        ]


async def _demand_keys(tenant_id: uuid.UUID, call_row_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as db:
        return [
            str(key)
            for (key,) in (
                await db.execute(
                    text(
                        "SELECT dedupe_key FROM outbox_messages "
                        "WHERE job = :j AND dedupe_key LIKE :like ORDER BY dedupe_key"
                    ),
                    {"j": REMETER_JOB, "like": f"remeter:{call_row_id}:%"},
                )
            ).tuples()
        ]


async def _refusal_instant(tenant_id: uuid.UUID, call_row_id: uuid.UUID) -> object:
    async with tenant_session(tenant_id) as db:
        return (
            await db.execute(
                text(
                    "SELECT occurred_at FROM call_metering_refusals "
                    "WHERE call_id = :c AND leg = 'llm'"
                ),
                {"c": call_row_id},
            )
        ).scalar_one()


# ---------------------------------------------------------------------------------------
# 1. The demand is parked, and only for the legs an attestation can answer.
# ---------------------------------------------------------------------------------------


async def test_a_leg_refused_for_want_of_a_price_parks_its_measurement(
    worker_token: None,
) -> None:
    """The fix's whole premise: without this row there is no number to apply a price to.

    The refusal itself records `leg`/`code`/`detail`/`remediation` and no quantity, and the
    settlement body is persisted nowhere — so a re-metering worker written against today's
    schema alone would have nothing to read.
    """
    tenant_id, call_row_id, _ref = await _settled_call()
    assert await _demand_keys(tenant_id, call_row_id) == [f"remeter:{call_row_id}:llm"]
    assert await _usage(tenant_id, call_row_id) == [], "an unpriced leg must never meter a zero"


async def test_a_leg_no_attestation_can_ever_answer_parks_nothing(worker_token: None) -> None:
    """The carrier's connected minute is the CDR's, not the rate card's (§1.2).

    A demand for it would be a work item nothing can ever close, and a worklist full of those
    is one an operator stops reading. Asserted as an EQUALITY on the keys, so a future code
    added to `REMETERABLE_CODES` has to be thought about here.
    """
    tenant_id, call_row_id, _ref = await _settled_call()
    keys = await _demand_keys(tenant_id, call_row_id)
    assert f"remeter:{call_row_id}:carrier" not in keys


async def test_a_redelivered_settlement_parks_no_second_demand(worker_token: None) -> None:
    """A retry after a timed-out POST is answered, never re-applied — demands included."""
    tenant_id, agent_id, _agent_ref = await published_agent()
    _call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        first = await api.post_settlement(ref, _settlement(agent_id))
        second = await api.post_settlement(ref, _settlement(agent_id))
    assert first.already_settled is False
    assert second.already_settled is True
    async with tenant_session(tenant_id) as db:
        row_id = (
            await db.execute(text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref})
        ).scalar_one()
    assert await _demand_keys(tenant_id, uuid.UUID(str(row_id))) == [f"remeter:{row_id}:llm"]


# ---------------------------------------------------------------------------------------
# 2. The attestation reaches the calls that were waiting for it.
# ---------------------------------------------------------------------------------------


async def test_the_sweep_does_nothing_while_the_price_is_still_unattested(
    worker_token: None,
) -> None:
    """Hard rule 7 is unweakened: no price, no row — and no second refusal either.

    `call_metering_refusals` carries no unique index, so a sweep that recorded its verdict
    every hour would append one row per unattested leg per tick for ever.
    """
    tenant_id, call_row_id, _ref = await _settled_call()
    await remeter_refused_legs({})
    assert await _usage(tenant_id, call_row_id) == []
    async with tenant_session(tenant_id) as db:
        refusals = (
            await db.execute(
                text("SELECT count(*) FROM call_metering_refusals WHERE call_id = :c"),
                {"c": call_row_id},
            )
        ).scalar_one()
    assert refusals == 2, "the sweep appended a verdict to an append-only table"


async def test_an_attested_price_meters_the_call_that_was_waiting_for_it(
    worker_token: None,
) -> None:
    """The founder's finding, closed: the console entry bills the OLD call too.

    And it bills it in the RIGHT MONTH. `occurred_at` is the settlement's instant and not the
    sweep's, which is what every IST month window in `billing/service.py` groups on — the
    defect D-250 already fixed once for a late-settling call and which a re-metering stamped
    `now()` would have reintroduced.
    """
    tenant_id, call_row_id, _ref = await _settled_call()
    settled_at = await _refusal_instant(tenant_id, call_row_id)

    _attest("1.00")
    await remeter_refused_legs({})

    rows = await _usage(tenant_id, call_row_id)
    assert len(rows) == 1
    unit, unit_cost, occurred_at = rows[0]
    assert unit == "llm_ktok_in"
    # $1.00 per MILLION tokens at `LIST_PRICE_USD_INR`, per THOUSAND: 1.00 * 95.66 / 1000,
    # quantized by the NUMERIC(12,4) column. Asserted as a number rather than re-derived
    # through the module under test.
    assert unit_cost == Decimal("0.0957")
    assert occurred_at == settled_at, "a re-metered row was filed in the wrong month"


# ---------------------------------------------------------------------------------------
# 3. It cannot bill twice. Three races, one row.
# ---------------------------------------------------------------------------------------


async def test_running_the_sweep_twice_bills_once(worker_token: None) -> None:
    tenant_id, call_row_id, _ref = await _settled_call()
    _attest("1.00")
    await remeter_refused_legs({})
    await remeter_refused_legs({})
    assert len(await _usage(tenant_id, call_row_id)) == 1


async def test_two_sweeps_at_once_bill_once(worker_token: None) -> None:
    """The guard is the unique index, so it holds without a lock and under real concurrency.

    `return_exceptions=True`: the loser of a unique-index race is entitled to abort, and what
    is under test is the ROW COUNT, not which coroutine won.
    """
    tenant_id, call_row_id, _ref = await _settled_call()
    _attest("1.00")
    await asyncio.gather(remeter_refused_legs({}), remeter_refused_legs({}), return_exceptions=True)
    assert len(await _usage(tenant_id, call_row_id)) == 1


async def test_a_late_settlement_after_a_remetering_bills_once(worker_token: None) -> None:
    """The worker's retry arriving AFTER the sweep has already billed the leg.

    Two mechanisms converge on one row: the settlement is answered `already_settled` by the
    outbox marker, and the insert behind it could not have written a second row anyway.
    """
    tenant_id, agent_id, _agent_ref = await published_agent()
    _call_id, ref = call_ref(tenant_id)
    async with worker_client() as api:
        await api.post_settlement(ref, _settlement(agent_id))
    async with tenant_session(tenant_id) as db:
        row_id = uuid.UUID(
            str(
                (
                    await db.execute(
                        text("SELECT id FROM calls WHERE engine_call_id = :c"), {"c": ref}
                    )
                ).scalar_one()
            )
        )
    _attest("1.00")
    await remeter_refused_legs({})
    async with worker_client() as api:
        late = await api.post_settlement(ref, _settlement(agent_id))
    assert late.already_settled is True
    assert len(await _usage(tenant_id, row_id)) == 1


async def test_the_double_bill_guard_is_the_database(worker_token: None) -> None:
    """The negative control, and the reason this file can claim a GUARANTEE rather than a habit.

    `_write_usage` ends `ON CONFLICT DO NOTHING` with no conflict target, so it catches all
    three partial unique indexes on `(tenant_id, call_id, unit_type)`. Remove that clause and
    a second sweep raises `UniqueViolation` instead of silently writing a second row — which
    is the outcome `b8d3f47c2a19` argues for at length on an append-only ledger. This test
    asserts the INDEX is really there and really covers this unit type, by inserting the same
    key twice through a statement with no conflict clause at all.
    """
    tenant_id, call_row_id, _ref = await _settled_call()
    _attest("1.00")
    await remeter_refused_legs({})
    from apps.api.db.base import uuid7

    insert = (
        "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid, "
        "occurred_at, meta, created_at) "
        "VALUES (:id, :tid, :cid, 'llm_ktok_in', 1, 1, now(), '{}'::jsonb, now())"
    )
    with pytest.raises(Exception) as caught:
        async with tenant_session(tenant_id) as db:
            await db.execute(text(insert), {"id": uuid7(), "tid": tenant_id, "cid": call_row_id})
    assert "ux_usage_events_tenant_call_ktok" in str(caught.value)


async def test_the_insert_itself_is_idempotent_without_the_pre_check(
    worker_token: None,
) -> None:
    """The guard the two sweeps above never actually reach, exercised on its own.

    **THIS TEST EXISTS BECAUSE A SABOTAGE RUN SHOWED THE OTHERS DID NOT COVER IT.** Deleting
    `ON CONFLICT DO NOTHING` from `_INSERT_USAGE_SQL` left every other test in this file
    green: `remeter`'s "already metered" read short-circuits the second pass, and two sweeps
    handed to `asyncio.gather` serialise on one event loop rather than interleaving inside a
    transaction. A check-then-write is correct only for as long as every caller remembers to
    take a lock — the argument `enqueue_outbox_once` makes about the probe it replaced, and
    `b8d3f47c2a19` about `lock_call_writes` — so the property that actually stops a double
    bill is the INSERT's, and it has to be asserted where nothing else can answer first.

    Drives `_write_usage` directly, twice, with the same `(tenant, call, unit_type)`. One row.
    """
    from apps.api.worker.service import _Priced, _write_usage

    tenant_id, call_row_id, _ref = await _settled_call()
    row = _Priced(unit_type="llm_ktok_in", qty=TOKENS, unit_cost_inr=Decimal("0.0957"), meta={})
    async with tenant_session(tenant_id) as db:
        at = await _refusal_instant(tenant_id, call_row_id)
        await _write_usage(db, tenant_id, call_row_id, (row,), at=at)  # type: ignore[arg-type]
        await _write_usage(db, tenant_id, call_row_id, (row,), at=at)  # type: ignore[arg-type]
    assert len(await _usage(tenant_id, call_row_id)) == 1


# ---------------------------------------------------------------------------------------
# 4. The sweep reaches every demand, however many settled ones sit in front of it.
# ---------------------------------------------------------------------------------------


async def test_settled_demands_do_not_starve_the_newer_ones(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demands stay in the store for their 90-day window after they are metered, so a sweep
    that read only the oldest page re-read the same settled rows every hour and never reached
    a newer one. A page of ONE makes that page the oldest demand in the database, which the
    first call below guarantees is not the second."""
    monkeypatch.setattr(remetering, "SWEEP_BATCH", 1)
    older_tenant, older_call, _ = await _settled_call()
    newer_tenant, newer_call, _ = await _settled_call()
    _attest("1.00")
    await remeter_refused_legs({})
    assert len(await _usage(older_tenant, older_call)) == 1
    assert len(await _usage(newer_tenant, newer_call)) == 1


async def test_a_tick_that_runs_out_of_time_stops_and_says_so(
    worker_token: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Out of budget between pages, and out of budget between tenants inside a page: both
    stop the walk, meter nothing further and log the truncation."""
    tenant_id, call_row_id, _ref = await _settled_call()
    _attest("1.00")

    monkeypatch.setattr(remetering, "SWEEP_BUDGET_S", 0.0)
    assert (await remeter_refused_legs({})).startswith("metered=0 ")

    clock = iter([0.0, 0.0])
    monkeypatch.setattr(remetering, "SWEEP_BUDGET_S", 1.0)
    monkeypatch.setattr(remetering.time, "monotonic", lambda: next(clock, 5.0))
    assert (await remeter_refused_legs({})).startswith("metered=0 ")
    assert await _usage(tenant_id, call_row_id) == []
    assert "remetering_sweep_truncated" in caplog.text


async def test_a_tenant_whose_metered_legs_cannot_be_read_is_counted_unreached(
    worker_token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One tenant's failed read is that tenant's demands unreached, never the tick's failure."""
    await _settled_call()
    _attest("1.00")

    async def _broken(*_args: object, **_kwargs: object) -> set[tuple[uuid.UUID, str]]:
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr(remetering, "_metered_legs", _broken)
    summary = await remeter_refused_legs({})
    assert "metered=0 " in summary
    assert "unreached=0" not in summary
