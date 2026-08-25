"""The onboarding setup fee: issued on a schedule, printed by the invoice (D-63).

`plans.setup_fee` was a column nothing read. These tests are the argument that it is now
billed EXACTLY ONCE — under regeneration, under a plan change, under two concurrent
issuers — and that a plan quoting no fee produces no line at all rather than a ₹0.00 one.
The money assertions are the arithmetic a client checks by hand.

The follow-on slice moved WHO writes the row. It used to be whoever rendered the
invoice, so a tenant nobody looked at was never charged and a GET carried a write;
`apps/workers/billing.py::issue_one_time_charges` is the writer now and `build_invoice`
is a pure read. The tests under the last heading are about that seam specifically:
rendering bills nothing at all, the job charges a tenant whose invoice was never opened,
it is safe to run twice and to run beside another writer in flight, the month it stamps
is the tenant's own IST onboarding month whatever night the job runs, and it is actually
registered in the worker's schedule with the retry ladder every job here has.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.billing.charges import (
    SETUP_FEE_KIND,
    SETUP_FEE_REF,
    issue_setup_fee,
    one_time_charge_lines,
)
from apps.api.billing.invoice import build_invoice
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.service import current_billing_month
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import billing as billing_worker
from apps.workers.billing import issue_one_time_charges, owed_setup_fees
from arq import Retry
from sqlalchemy import text

SETUP_LINE = "One-time onboarding & setup"


async def _tenant(
    *,
    setup_fee: str | None = "25000.00",
    monthly_fee: str | None = "9999.00",
) -> uuid.UUID:
    """A tenant onboarded NOW (so the current billing month is their onboarding month)
    with one plan row, effective-dated open on both ends like every real one."""
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Setup Fee Clinic",
        slug=f"setup-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, setup_fee, monthly_fee, included_min, "
                "overage_rate, concurrency_ceiling, created_at, updated_at) VALUES (:i, :t, "
                ":setup, :fee, 100, 8.0000, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "setup": Decimal(setup_fee) if setup_fee is not None else None,
                "fee": Decimal(monthly_fee) if monthly_fee is not None else None,
            },
        )
    return tenant_id


async def _onboarded_at(tenant_id: uuid.UUID) -> datetime:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT created_at FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar_one()


async def _issue(tenant_id: uuid.UUID) -> bool:
    """Issue this tenant's fee the way the nightly job does: the same function, on the
    same tenant-scoped session, differing only in that the job finds the tenant itself.
    Used where the point of the test is the CHARGE rather than the scan."""
    onboarded_at = await _onboarded_at(tenant_id)
    async with tenant_session(tenant_id) as session:
        return await issue_setup_fee(session, tenant_id=tenant_id, onboarded_at=onboarded_at)


async def _charge_rows(tenant_id: uuid.UUID) -> list[tuple[str, Decimal, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT kind, amount, billing_month FROM one_time_charges "
                    "WHERE tenant_id = :t ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(k), Decimal(str(a)), str(m)) for k, a, m in rows]


def _setup_lines(invoice: dict[str, object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = invoice["line_items"]  # type: ignore[assignment]
    return [item for item in items if item["description"] == SETUP_LINE]


async def test_the_setup_fee_lands_on_the_onboarding_month_invoice() -> None:
    """₹25,000 setup + ₹9,999 plan = ₹34,999 subtotal, GST ₹6,299.82, total ₹41,298.82 —
    and the ledger holds exactly one row, in the tenant's onboarding month."""
    tenant_id = await _tenant()
    await _issue(tenant_id)
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    (line,) = _setup_lines(invoice)
    assert line["qty"] == Decimal("1")
    assert line["unit_inr"] == Decimal("25000.00")
    # STRING equality, not Decimal: `Decimal("25000.0000") == Decimal("25000.00")` is
    # True, so a line that skipped `to_paise` and printed the storage precision would
    # pass a numeric assertion and reach the client as "₹25000.0000".
    assert str(line["amount_inr"]) == "25000.00"
    assert str(line["unit_inr"]) == "25000.00"
    assert invoice["subtotal_inr"] == Decimal("34999.00")
    assert invoice["gst_inr"] == Decimal("6299.82")
    assert invoice["total_inr"] == Decimal("41298.82")

    assert await _charge_rows(tenant_id) == [
        (SETUP_FEE_KIND, Decimal("25000.0000"), current_billing_month())
    ]


async def test_regenerating_the_invoice_does_not_charge_the_setup_fee_twice() -> None:
    """Invoices are DERIVED — rendering one is not billing again, and since the follow-on
    slice it is not billing at all. Three renders across three transactions still leave
    one ledger row and one line."""
    tenant_id = await _tenant()
    await _issue(tenant_id)
    totals = []
    for _ in range(3):
        async with tenant_session(tenant_id) as session:
            invoice = await build_invoice(session, tenant_id=tenant_id)
        assert len(_setup_lines(invoice)) == 1
        totals.append(invoice["total_inr"])

    assert totals[0] == totals[1] == totals[2] == Decimal("41298.82")
    assert len(await _charge_rows(tenant_id)) == 1


async def test_two_concurrent_issuers_produce_one_setup_charge() -> None:
    """The race is FORCED, not hoped for: B's transaction is opened and driven into the
    write while A's is still uncommitted, which is the only interleaving that tells the
    designs apart.

    `asyncio.gather` of two issuers does not: they usually serialize, and a
    read-then-write implementation passes it. Here B is started with A's charge inserted
    and unconflicted-with, so B is inside the window where a `SELECT … WHERE NOT EXISTS`
    reads "not charged yet". With the guard in the WRITE, B's speculative insert waits on
    A's index entry and writes nothing when A commits.

    Two issuers is the shape that survived the follow-on slice: the second writer used to
    be a second RENDER, and rendering no longer writes. The pair that can now collide is
    the nightly job and anything else calling `issue_setup_fee` — which is what this is."""
    tenant_id = await _tenant()
    onboarded_at = await _onboarded_at(tenant_id)
    second: dict[str, bool] = {}

    async def issue_second() -> None:
        async with tenant_session(tenant_id) as session:
            second["recorded"] = await issue_setup_fee(
                session, tenant_id=tenant_id, onboarded_at=onboarded_at
            )

    async with tenant_session(tenant_id) as session:
        first = await issue_setup_fee(session, tenant_id=tenant_id, onboarded_at=onboarded_at)
        task = asyncio.create_task(issue_second())
        # Long enough for B to issue its own insert and block on the index entry A holds
        # uncommitted. If it were NOT blocked there, this test would be proving nothing.
        await asyncio.sleep(0.3)
        assert not task.done(), "B finished without ever contending — the race did not happen"
    await asyncio.wait_for(task, timeout=5)

    # Both callers answer honestly about what THEY did, and the ledger holds one row.
    assert first is True
    assert second["recorded"] is False
    assert len(await _charge_rows(tenant_id)) == 1

    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
    assert len(_setup_lines(invoice)) == 1
    assert invoice["total_inr"] == Decimal("41298.82")


async def test_a_plan_change_never_creates_a_second_setup_charge() -> None:
    """A new plan row quoting its own (larger) setup fee supersedes the old one for
    pricing, and bills no second onboarding: the ledger key is the TENANT's onboarding,
    not the plan's. The rendered line keeps the amount actually billed."""
    tenant_id = await _tenant()
    await _issue(tenant_id)
    async with tenant_session(tenant_id) as session:
        before = await build_invoice(session, tenant_id=tenant_id)
    assert len(_setup_lines(before)) == 1

    async with tenant_session(tenant_id) as session:
        # Effective from an hour ago, so it is the row in effect for "now" — the same
        # gesture an operator makes to re-terms a client (billing/plans.py).
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, setup_fee, monthly_fee, included_min, "
                "overage_rate, concurrency_ceiling, effective_from, created_at, updated_at) "
                "VALUES (:i, :t, 99000.0000, 9999.0000, 100, 8.0000, 10, "
                "now() - interval '1 hour', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id},
        )
    # The nightly job runs again after the re-terming, and must still find nothing to do.
    assert await _issue(tenant_id) is False
    async with tenant_session(tenant_id) as session:
        after = await build_invoice(session, tenant_id=tenant_id)

    (line,) = _setup_lines(after)
    # STRING equality, not Decimal: `Decimal("25000.0000") == Decimal("25000.00")` is
    # True, so a line that skipped `to_paise` and printed the storage precision would
    # pass a numeric assertion and reach the client as "₹25000.0000".
    assert str(line["amount_inr"]) == "25000.00"
    assert str(line["unit_inr"]) == "25000.00", "the amount billed is frozen in the ledger"
    assert await _charge_rows(tenant_id) == [
        (SETUP_FEE_KIND, Decimal("25000.0000"), current_billing_month())
    ]


async def test_a_month_that_is_not_the_onboarding_month_carries_no_setup_line() -> None:
    """The fee belongs to the month the client was onboarded in. Rendering an earlier
    month must neither print it nor bill it — otherwise which month it lands on would
    depend on which statement somebody happened to open first."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id, month="2026-01")

    assert _setup_lines(invoice) == []
    assert await _charge_rows(tenant_id) == [], "rendering a statement bills nothing, ever"

    # And once it IS issued, it still lands on the onboarding month and not on the one
    # somebody happened to open.
    await _issue(tenant_id)
    assert [month for _, _, month in await _charge_rows(tenant_id)] == [current_billing_month()]


async def test_a_billed_setup_fee_does_not_follow_the_client_into_later_months() -> None:
    """The charge is stamped with the statement it belongs to, and the invoice reads
    charges FOR THAT MONTH. A tenant already billed the fee must not see it again on
    every subsequent invoice — which is the failure a ledger read without a month filter
    produces, and the one an unbilled tenant's empty ledger would hide."""
    tenant_id = await _tenant()
    await _issue(tenant_id)
    async with tenant_session(tenant_id) as session:
        onboarding = await build_invoice(session, tenant_id=tenant_id)
    assert len(_setup_lines(onboarding)) == 1

    # A month the tenant was NOT onboarded in, chosen after the fact so the row exists.
    later = "2027-03" if current_billing_month() < "2027-03" else "2029-03"
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id, month=later)

    assert _setup_lines(invoice) == []
    assert len(await _charge_rows(tenant_id)) == 1


@pytest.mark.parametrize("setup_fee", [None, "0.0000", "-500.0000"])
async def test_no_setup_fee_produces_no_line_and_no_ledger_row(setup_fee: str | None) -> None:
    """NULL, zero and negative all mean "there is nothing to charge". A ₹0.00 line on an
    invoice invites a dispute about nothing, and a negative fee is a discount nobody
    designed — neither may reach a client's statement."""
    tenant_id = await _tenant(setup_fee=setup_fee)
    assert await _issue(tenant_id) is False
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert _setup_lines(invoice) == []
    assert invoice["subtotal_inr"] == Decimal("9999.00"), "only the monthly fee"
    assert await _charge_rows(tenant_id) == []


async def test_a_tenant_with_no_plan_at_all_is_never_charged_a_setup_fee() -> None:
    """No plan row means unpriced (billing/plans.py) — including no onboarding fee."""
    tenant_id = await _tenant(setup_fee=None, monthly_fee=None)
    async with tenant_session(tenant_id) as session:
        # Remove the plan row this fixture writes, so the tenant genuinely has none.
        await session.execute(text("DELETE FROM plans WHERE tenant_id = :t"), {"t": tenant_id})
    assert await _issue(tenant_id) is False
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)

    assert invoice["line_items"] == []
    assert await _charge_rows(tenant_id) == []


async def test_a_reversal_row_prints_as_a_credit_on_the_same_statement() -> None:
    """Hard rule 4's escape hatch: a setup fee that has to be undone is a NEW row under
    its own `ref`, never an edit. The invoice reads every charge for the month, so the
    correction reaches the client's statement and nets the subtotal back to the plan
    fee."""
    tenant_id = await _tenant()
    await _issue(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO one_time_charges (id, tenant_id, kind, ref, description, amount, "
                "billing_month, occurred_at, created_at) VALUES (:i, :t, :kind, "
                "'reversal:onboarding', 'Onboarding fee waived', -25000.0000, :m, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "kind": SETUP_FEE_KIND, "m": current_billing_month()},
        )
        invoice = await build_invoice(session, tenant_id=tenant_id)

    descriptions = [item["description"] for item in invoice["line_items"]]
    assert descriptions == ["Monthly plan fee", SETUP_LINE, "Onboarding fee waived"]
    assert invoice["subtotal_inr"] == Decimal("9999.00")


async def test_the_charge_ledger_refuses_updates_and_deletes() -> None:
    """Append-only (hard rule 4), enforced by the trigger and not by convention."""
    tenant_id = await _tenant()
    await _issue(tenant_id)

    for statement in (
        "UPDATE one_time_charges SET amount = 1 WHERE tenant_id = :t",
        "DELETE FROM one_time_charges WHERE tenant_id = :t",
    ):
        with pytest.raises(Exception, match=r"append-only|immutable|forbidden"):
            async with tenant_session(tenant_id) as session:
                await session.execute(text(statement), {"t": tenant_id})


async def test_one_tenants_charges_are_invisible_to_another() -> None:
    """Hard rule 1: RLS, not a WHERE clause. A session scoped to B sees zero rows of A's
    charges even when it names A's id, and cannot write one for A either."""
    a = await _tenant()
    b = await _tenant()
    await _issue(a)

    async with tenant_session(b) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM one_time_charges WHERE tenant_id = :t"), {"t": a}
            )
        ).scalar()
        assert rows == 0
        # And the invoice builder, handed A's id on B's session, prints nothing of A's:
        # every read it makes is fenced by the same policy.
        lines = await one_time_charge_lines(session, tenant_id=a, month=current_billing_month())
        assert lines == []

        # Nor can B ISSUE one for A. It does not even reach the insert: the plan lookup
        # is fenced by the same policy, so the writer sees a tenant with no plan and
        # declines — and if it ever did reach the insert, the WITH CHECK half would
        # refuse a row filed under a tenant this session is not scoped to.
        assert await issue_setup_fee(session, tenant_id=a, onboarded_at=datetime.now(UTC)) is False

    # A's own ledger is untouched by B's attempt: still exactly the one charge.
    assert await _charge_rows(a) == [
        (SETUP_FEE_KIND, Decimal("25000.0000"), current_billing_month())
    ]
    assert SETUP_FEE_REF == "onboarding"


def test_a_billing_month_needs_an_aware_instant() -> None:
    """A naive datetime would be read in the process's local timezone, so the same row
    would bill in two different months on a UTC container and an IST laptop."""
    with pytest.raises(ValueError, match="aware instant"):
        ist_billing_month(datetime(2026, 8, 14, 23, 30))

    # 23:30 UTC on 31 July is 05:00 IST on 1 August — the shift is the point.
    assert ist_billing_month(datetime(2026, 7, 31, 23, 30, tzinfo=UTC)) == "2026-08"


# --------------------------------------------------------------------------------------
# The scheduled half: the fee stops depending on somebody opening a screen.
# --------------------------------------------------------------------------------------


async def test_rendering_an_invoice_bills_nothing_at_all() -> None:
    """The regression this slice exists to prevent coming back. `build_invoice` used to
    append the setup charge on the first render of the onboarding month, which is how a
    GET came to carry a write and how a tenant nobody looked at went unbilled. Rendering
    the onboarding month three times must now leave the ledger empty."""
    tenant_id = await _tenant()
    for _ in range(3):
        async with tenant_session(tenant_id) as session:
            invoice = await build_invoice(session, tenant_id=tenant_id)
        assert _setup_lines(invoice) == []
    assert await _charge_rows(tenant_id) == []


async def test_the_job_charges_a_tenant_whose_invoice_nobody_ever_opened() -> None:
    """THE POINT OF THE SLICE. No render happens anywhere in this test: the tenant is
    onboarded, the nightly job runs, and the fee is on their statement."""
    tenant_id = await _tenant()
    assert await _charge_rows(tenant_id) == []

    await issue_one_time_charges({})

    assert await _charge_rows(tenant_id) == [
        (SETUP_FEE_KIND, Decimal("25000.0000"), current_billing_month())
    ]
    async with tenant_session(tenant_id) as session:
        invoice = await build_invoice(session, tenant_id=tenant_id)
    (line,) = _setup_lines(invoice)
    assert str(line["amount_inr"]) == "25000.00"
    assert invoice["total_inr"] == Decimal("41298.82")


async def test_running_the_job_again_charges_nobody_twice() -> None:
    """A cron runs every night for the life of the platform, so "idempotent" is not a
    nicety here — it is the difference between one setup fee and one per night. Three
    ticks, one row; and the tick reports honestly that it issued nothing the second
    time, which is what makes a real run's counters readable."""
    tenant_id = await _tenant()
    first = json.loads(await issue_one_time_charges({}))
    second = json.loads(await issue_one_time_charges({}))
    await issue_one_time_charges({})

    assert first["issued"] >= 1, "the tick that should have charged our tenant charged nobody"
    assert second["issued"] == 0
    assert second["failed"] == 0
    assert len(await _charge_rows(tenant_id)) == 1


async def test_the_job_racing_an_in_flight_charge_still_charges_once() -> None:
    """The job's scan is a COST FILTER, not a guard, and this is what says so.

    The tick is started while another writer's charge for the same tenant is inserted
    and uncommitted. The scan therefore sees "not charged yet" — the exact window a
    `SELECT … WHERE NOT EXISTS` implementation would step through — and the tick's own
    insert then blocks on the index entry the other writer holds, and writes nothing
    once it commits. Put the guard in front of the write instead and this test bills the
    onboarding fee twice.
    """
    tenant_id = await _tenant()
    onboarded_at = await _onboarded_at(tenant_id)

    async with tenant_session(tenant_id) as session:
        assert await issue_setup_fee(session, tenant_id=tenant_id, onboarded_at=onboarded_at)
        tick = asyncio.create_task(issue_one_time_charges({}))
        # The scan runs against the pre-commit snapshot: our tenant looks unbilled.
        await asyncio.sleep(0.3)
        assert not tick.done(), "the tick finished before the contended write — no race happened"
    totals = json.loads(await asyncio.wait_for(tick, timeout=30))

    assert totals["failed"] == 0, "a contended insert must WAIT, never fail"
    assert len(await _charge_rows(tenant_id)) == 1


async def test_the_job_stamps_the_ist_onboarding_month_not_the_utc_one() -> None:
    """A tenant created at 23:30 UTC on 30 June was onboarded on 1 July in the only
    timezone this business bills in, and their fee belongs to JULY.

    The instant is chosen where UTC and IST disagree about the month, and the job is the
    thing under test rather than the helper: the stamp is derived from the tenant's own
    `created_at`, so it cannot depend on the night the tick happens to run — which is
    the property that let this be a daily cron in the first place.
    """
    tenant_id = await _tenant()
    onboarded = datetime(2026, 6, 30, 23, 30, tzinfo=UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET created_at = :at WHERE id = :t"),
            {"at": onboarded, "t": tenant_id},
        )
    assert onboarded.strftime("%Y-%m") == "2026-06", "the UTC month is the one that must LOSE"

    await issue_one_time_charges({})

    assert [month for _, _, month in await _charge_rows(tenant_id)] == ["2026-07"]
    async with tenant_session(tenant_id) as session:
        july = await build_invoice(session, tenant_id=tenant_id, month="2026-07")
        june = await build_invoice(session, tenant_id=tenant_id, month="2026-06")
    assert len(_setup_lines(july)) == 1
    assert _setup_lines(june) == []


async def test_the_scan_asks_each_tenant_under_that_tenants_own_policies() -> None:
    """`unbilled_setup_fees()` loops tenants inside ONE session, re-scoping `app.tenant_id`
    per iteration (migration e3f9c2a71d84). This is the same assertion
    `dispatch_scan_rls_test` makes of its sibling, on data rather than on that sentence:
    two tenants in different states must come back with their OWN answers, which a
    leaked or plan-cached GUC could not produce."""
    unbilled = await _tenant()
    billed = await _tenant()
    await _issue(billed)

    owed = {tenant_id for tenant_id, _ in await owed_setup_fees()}
    assert unbilled in owed, "a tenant owed a fee was invisible to the scan"
    assert billed not in owed, "a tenant already charged came back as owing one"

    # And the onboarding instant travels with the id, so the writer never has to ask a
    # second time (and can never ask under the wrong session).
    onboarded = dict(await owed_setup_fees())
    assert onboarded[unbilled] == await _onboarded_at(unbilled)


def test_the_job_is_registered_in_the_workers_schedule() -> None:
    """A cron nobody registered is the defect that looks like progress: the module would
    import, the tests would pass, and no fee would ever be issued in production.

    `max_tries` is asserted alongside, because `arq.cron()` defaults it to 1 and
    `WorkerSettings.max_tries` does NOT apply to a function that carries its own — so
    the retry ladder every other job in this repo has would be silently absent here.
    """
    from apps.workers.settings import CRON_JOBS

    (entry,) = [job for job in CRON_JOBS if job.coroutine.__name__ == "issue_one_time_charges"]
    assert entry.max_tries == WORKER_MAX_TRIES
    assert entry.hour and entry.minute, "a daily cron needs an hour and a minute, or it is hourly"


async def test_a_tenant_that_cannot_be_charged_takes_the_retry_ladder_then_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errors are part of the interface. A tick that could not issue a fee asks for
    another attempt (arq retries `Retry` and nothing else — `WorkerSettings.retry_jobs`),
    and when the ladder is exhausted it alerts an operator AND fails, so the run lands in
    the DLQ instead of being filed as a green tick with a zero in it."""
    await _tenant()

    async def refuses(*args: object, **kwargs: object) -> bool:
        raise RuntimeError("plan row is unreadable")

    monkeypatch.setattr(billing_worker, "issue_setup_fee", refuses)
    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        billing_worker,
        "alert",
        lambda stage, code, **kw: alerts.append((stage, code)),
    )

    with pytest.raises(Retry):
        await issue_one_time_charges({"job_try": 1})
    assert alerts == [], "an alert on the first attempt is a page nobody needed"

    with pytest.raises(RuntimeError, match="could not be issued"):
        await issue_one_time_charges({"job_try": WORKER_MAX_TRIES})
    assert alerts == [("WORKER_TERMINAL", "setup_fees_unissued")]


@pytest.fixture(autouse=True)
def _gst_registered_supplier(monkeypatch: pytest.MonkeyPatch):
    """Register a specimen GST supplier for this suite.

    These tests assert the TAX-INVOICE arithmetic (18% GST split into heads), which is only
    lawful once Calevate is GST-registered. An UNregistered supplier now issues a bill of
    supply with no tax (CGST s.32, Rule 49; billing/invoice.py), so without a registered
    supplier ``gst_inr`` would be zero and these arithmetic assertions would test nothing.
    The specimen GSTIN is Telangana (36) so an intra-State supply splits into CGST+SGST.
    """
    from apps.api.core.settings import get_settings

    monkeypatch.setenv("GST_SUPPLIER_LEGAL_NAME", "Calevate Technologies Private Limited")
    monkeypatch.setenv("GST_SUPPLIER_ADDRESS", "Plot 42, Madhapur, Hyderabad 500081")
    monkeypatch.setenv("GST_SUPPLIER_GSTIN", "36AABCC1234D1Z5")
    monkeypatch.setenv("GST_SUPPLY_SAC", "998315")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
