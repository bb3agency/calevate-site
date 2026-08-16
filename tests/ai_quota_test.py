"""Dashboard AI: the meter, the ceiling, the modal and the brake (D-127 G-3/G-4/G-5).

Every claim `billing/ai_quota.py` and migration `e1a7c93d5b02` make is asserted here
rather than described, and the ones worth naming up front are the ones that were WRONG
in the schema this slice inherited:

1. **A dashboard-AI row is invisible to `ux_usage_events_tenant_call_unit`** — three
   independent ways, all three read at source and all three pinned below. The new index
   covers exactly the rows the old one excludes and neither shadows the other.
2. **`ON CONFLICT DO NOTHING` must repeat the partial predicate VERBATIM** or Postgres
   infers nothing and raises. The migration's copy and the writer's copy are held equal
   here, character for character, and both are held equal to the LIVE index.
3. **Nothing leaves the wallet until a person accepts** (G-5), and what leaves is exactly
   ONE `credit_ledger` row with an existing reason (G-4).
4. **Our absorbed AI cost never reaches a client's spend** — the ledger is shared with
   the call meter and three client-facing sums read it.
5. **Concurrency is proved by interleaving, not by hoping.** Every race here is held open
   at a barrier and asserts that the second party was genuinely inside the window; a
   `gather()` on two calls with no yield between them runs them in series and its
   sabotage comes back green.
6. **Money is `Decimal` end to end.** No assertion in this file compares a float, and the
   wire shape is scanned for one.

CONCURRENCY AND GLOBAL STATE: every test mints its own tenant, so nothing here can
disturb another suite's rows. The ONE thing that is not per-tenant is
`platform_ai_spend`, whose current-month row every metered assist increments — and the
autouse fixture below explains what that cost this file and why the dependency is
severed rather than tuned. The test that asserts the brake TRIPS writes a far-future
month of its own, so no concurrent suite ever meets a paused platform.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import ai_quota
from apps.api.billing.ai_quota import (
    AI_ASSIST_NOMINAL_INR,
    AI_OVERAGE_BLOCK_INR,
    AI_QUOTA_INR,
    PLATFORM_AI_BRAKE_INR,
    AiQuota,
    new_assist_ref,
    overage_ref,
    purchase_ai_overage,
    read_ai_quota,
    read_platform_ai_spend,
    record_ai_assist_usage,
    require_ai_assist,
)
from apps.api.billing.ai_quota_routes import AiExtraIn, AiQuotaOut, buy_ai_extra, get_ai_quota
from apps.api.billing.models import (
    AI_ASSIST_UNIT_TYPES,
    CLIENT_BILLED_UNIT_TYPES,
    PLATFORM_ABSORBED_UNIT_TYPES,
    UNIT_TYPES,
    assert_units_are_disjoint,
)
from apps.api.billing.service import current_billing_month, get_balance, record_entry, tier_usage
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from pydantic import ValidationError
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "alembic"
    / "versions"
    / "e1a7c93d5b02_a_dashboard_assist_is_metered_by_its_own_key.py"
)

# A barrier this file waits on is either released by the other party (the race happened)
# or times out (the lock stopped the other party getting that far). Both are information;
# neither may hang the suite. Same constant, same reason, as `billing_audit_test.py`.
BARRIER_TIMEOUT = 1.0

# Prices chosen so every rupee figure below is exact and readable: 1 ktok in at ₹100/ktok
# is ₹100.00, which is `self_serve`'s whole included allowance. Real Gemini prices are
# four orders of magnitude smaller; the arithmetic under test is the same either way.
PRICE_IN = Decimal("100.0000")
PRICE_OUT = Decimal("0.0000")


#: The REAL brake predicate, captured before the autouse fixture below replaces it, so
#: the two tests that are ABOUT the brake can put it back.
REAL_BRAKE = ai_quota.platform_brake_tripped


# --------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _the_platform_brake_is_not_this_suites_business(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here except the two ABOUT the brake runs with it explicitly not tripped.

    NOT a convenience — it closes a hole this file dug for itself and found the hard way.
    `platform_ai_spend` is a monthly counter that only goes UP, it is the one row in this
    file that is not per-tenant, and the readable prices below (₹100 an assist, four
    orders of magnitude above a real one) mean ~40 rupees-hundred per run. After a few
    runs on one database the suite's OWN noise crossed `PLATFORM_AI_BRAKE_INR` and
    eleven tests failed — not because anything regressed, but because the brake was
    working. A suite whose result depends on how many times it has been run is not
    measuring the code.

    So the dependency is severed rather than tuned: no test may depend on a global
    counter it shares with its own history. The brake's own behaviour is asserted by the
    two tests that put `REAL_BRAKE` back or force it True, which is the only place that
    state should be able to decide an outcome.
    """

    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


async def _tenant(plan_tier: str = "self_serve") -> UUID:
    created = await admin_service.create_organization(
        name="Quota Clinic",
        slug=f"aiq-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="books@example.com",
        language="te-IN",
        created_by=None,
    )
    tenant_id: UUID = created["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :tier WHERE id = :i"),
            {"tier": plan_tier, "i": tenant_id},
        )
    return tenant_id


def _principal(tenant_id: UUID) -> Principal:
    return Principal(
        realm="client",
        user_id=uuid.uuid4(),
        clerk_user_id="u",
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


async def _assist(
    tenant_id: UUID,
    ref: str | None = None,
    *,
    tokens_in: int = 1000,
    tokens_out: int = 0,
    price_in: Decimal = PRICE_IN,
) -> ai_quota.AssistMetered:
    async with tenant_session(tenant_id) as session:
        return await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=ref or new_assist_ref(),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            price_in_inr_per_ktok=price_in,
            price_out_inr_per_ktok=PRICE_OUT,
            model="gemini-flash-lite",
            feature="resummarise",
        )


async def _quota(tenant_id: UUID, month: str | None = None) -> AiQuota:
    async with tenant_session(tenant_id) as session:
        return await read_ai_quota(session, tenant_id=tenant_id, month=month)


async def _topup(tenant_id: UUID, amount: str) -> None:
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal(amount),
            reason="topup",
            ref=f"UTR-{uuid.uuid4().hex[:10]}",
        )


async def _ledger(tenant_id: UUID) -> list[tuple[str, Decimal, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT reason, delta, ref FROM credit_ledger WHERE tenant_id = :t "
                    "ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), Decimal(str(r[1])), None if r[2] is None else str(r[2])) for r in rows]


def _floats(value: Any, path: str = "$") -> list[str]:
    """Every float reachable in a parsed JSON body, by path — `billing_audit_test`'s
    scanner, because a JSON number with a decimal point parses back as a Python float and
    that is exactly what hard rule 7 forbids on the wire."""
    if isinstance(value, bool):
        return []
    if isinstance(value, float):
        return [f"{path}={value!r}"]
    if isinstance(value, dict):
        return [hit for k, v in value.items() for hit in _floats(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [hit for i, v in enumerate(value) for hit in _floats(v, f"{path}[{i}]")]
    return []


# ============================================================================
# 1. The schema: the old key could not see these rows, and the new one can
# ============================================================================


async def test_the_call_leg_index_excludes_a_dashboard_assist_three_ways() -> None:
    """The defect this slice must not inherit, read off the LIVE database rather than
    off the migration that claims it.

    All three exclusions are independent and any ONE of them would be enough: the
    predicate keeps a call-less row out of the index entirely, the unit list does not
    name an AI unit, and `llm_tok_out` — the closest existing unit — already means "one
    call's LLM leg" (`apps/workers/pipeline.py`), so it was never available to reuse.
    """
    async with untenanted_session() as session:
        definition = (
            await session.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
                {"n": "ux_usage_events_tenant_call_unit"},
            )
        ).scalar_one()

    assert "call_id IS NOT NULL" in definition, (
        "the call-leg index no longer excludes call-less rows by predicate; the AI "
        "index's disjointness argument rests on it"
    )
    for unit in AI_ASSIST_UNIT_TYPES:
        assert unit not in definition, f"{unit} must not be protected by the CALL key"
    assert "llm_tok_out" in definition, (
        "llm_tok_out is the call-leg LLM unit and must stay in the call key — if it "
        "left, the reason the AI units are separate has changed"
    )


async def test_the_two_indexes_cover_disjoint_row_sets() -> None:
    """`call_id IS NOT NULL` and `call_id IS NULL` partition every row, so no row is in
    both indexes and neither can shadow the other. Read from `pg_indexes` because the
    property is about what the DATABASE enforces, not about what a module says."""
    async with untenanted_session() as session:
        rows = dict(
            (
                await session.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE tablename = 'usage_events' AND indexname LIKE 'ux_%'"
                    )
                )
            ).all()
        )
    call_key = rows["ux_usage_events_tenant_call_unit"]
    ref_key = rows["ux_usage_events_tenant_unit_ref"]
    assert "call_id IS NOT NULL" in call_key
    assert "call_id IS NULL" in ref_key
    assert "ref IS NOT NULL" in ref_key


def test_the_writer_repeats_the_migrations_index_predicate_verbatim() -> None:
    """Postgres infers a PARTIAL unique index only from an `ON CONFLICT` whose predicate
    implies the index's. A predicate that ALMOST matches does not degrade — it raises,
    on a button a client just pressed — so the two copies are held equal here.

    The migration is read as TEXT rather than imported: `alembic/versions` is not a
    package, and the point is that the file on disk says this.
    """
    source = MIGRATION.read_text()
    migration_predicate = re.search(r'INDEX_PREDICATE = "(?P<p>[^"]+)"', source)
    assert migration_predicate is not None, "migration no longer declares INDEX_PREDICATE"
    assert migration_predicate.group("p") == ai_quota.INDEX_PREDICATE, (
        "the writer's ON CONFLICT predicate has drifted from the index it must infer"
    )


async def test_the_live_index_carries_the_writers_predicate() -> None:
    """And both agree with the index that actually exists — a check neither of the two
    source copies can make about itself."""
    async with untenanted_session() as session:
        definition = (
            await session.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
                {"n": "ux_usage_events_tenant_unit_ref"},
            )
        ).scalar_one()
    # Postgres re-renders a predicate with its own parenthesisation, so the comparison is
    # per-clause rather than on the whole string.
    for clause in ai_quota.INDEX_PREDICATE.split(" AND "):
        assert clause in definition, f"the live index does not carry `{clause}`"


async def test_the_check_constraint_admits_exactly_the_declared_unit_types() -> None:
    """The CHECK is the copy with teeth: a unit type the model knows and the constraint
    does not is an IntegrityError on a client's button, and the reverse is a unit nobody
    can write. Held equal to `billing/models.py::UNIT_TYPES` in both directions."""
    async with untenanted_session() as session:
        definition = (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_usage_events_unit_type_enum'"
                )
            )
        ).scalar_one()
    in_constraint = set(re.findall(r"'([a-z_]+)'::", definition))
    assert in_constraint == set(UNIT_TYPES), (
        f"constraint and UNIT_TYPES disagree: only in DB {in_constraint - set(UNIT_TYPES)}, "
        f"only in code {set(UNIT_TYPES) - in_constraint}"
    )


# ============================================================================
# 2. Hard rule 1 — the new key is not a cross-tenant side channel
# ============================================================================


async def test_two_tenants_may_hold_the_same_ref_without_colliding() -> None:
    """`tenant_id` leads the key, so one tenant's request id cannot collide with
    another's — and the zero-rows half: neither tenant can see the other's row.

    This is the cross-tenant check hard rule 1 requires of a change touching a
    tenant-scoped table, and the specific thing it rules out is a unique violation being
    used as an oracle for a row RLS hides.
    """
    first, second = await _tenant(), await _tenant()
    shared_ref = new_assist_ref()

    assert (await _assist(first, shared_ref)).recorded is True
    assert (await _assist(second, shared_ref)).recorded is True, (
        "a second tenant's identical ref was refused — tenant_id is not leading the key"
    )

    async with tenant_session(first) as session:
        visible = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE ref = :r"), {"r": shared_ref}
            )
        ).scalar_one()
    assert visible == 2, "one tenant's own rows for this ref (in + out)"

    async with tenant_session(second) as session:
        cross = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE tenant_id = :t"), {"t": first}
            )
        ).scalar_one()
    assert cross == 0, "tenant B can see tenant A's usage rows — RLS is not isolating"


# ============================================================================
# 3. The meter: idempotent by ref, in the database
# ============================================================================


async def test_a_second_click_meters_once_and_moves_no_counter() -> None:
    """The realistic duplicate for a console button is a double-click, and the guard is
    the unique index rather than a reader's `if`. The replay is a no-op, not an error:
    `recorded=False` and zero rupees added on the second call."""
    tenant_id = await _tenant()
    ref = new_assist_ref()

    first = await _assist(tenant_id, ref)
    second = await _assist(tenant_id, ref)

    assert first.recorded is True
    assert first.cost_inr == Decimal("100.0000"), f"1 ktok at ₹100 = ₹100, got {first.cost_inr}"
    assert second.recorded is False, "the same ref metered twice"
    assert second.cost_inr == Decimal("0"), "a replay must add nothing"

    quota = await _quota(tenant_id)
    assert quota.requests_used == 1, "COUNT(DISTINCT ref) counted a replay as a request"
    assert quota.used_inr == Decimal("100.00000000"), quota.used_inr


async def test_two_interleaved_clicks_meter_once_and_the_second_really_blocked() -> None:
    """The double-click as a RACE, held open at a barrier so the overlap is certain.

    Two facts are asserted and the second is what makes this a concurrency test rather
    than a sequential one wearing a costume: B entered its own transaction while A's was
    still open (so they overlapped at all), and B's insert could not COMPLETE until A
    committed (so it genuinely blocked on the key rather than running afterwards). A
    `gather()` with no yield inside the window proves neither.
    """
    tenant_id = await _tenant()
    ref = new_assist_ref()
    a_inserted = asyncio.Event()
    b_in_transaction = asyncio.Event()
    seen: dict[str, Any] = {}

    async def writer_a() -> None:
        async with tenant_session(tenant_id) as session:
            await record_ai_assist_usage(
                session,
                tenant_id=tenant_id,
                ref=ref,
                tokens_in=1000,
                tokens_out=0,
                price_in_inr_per_ktok=PRICE_IN,
                price_out_inr_per_ktok=PRICE_OUT,
                model="gemini-flash-lite",
                feature="resummarise",
            )
            a_inserted.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(b_in_transaction.wait(), timeout=BARRIER_TIMEOUT)
            seen["b_open_while_a_open"] = b_in_transaction.is_set()
            # A real yield with B's INSERT already in flight: without it the "overlap"
            # would be two coroutines that never ran at the same time.
            await asyncio.sleep(0.05)
            seen["a_commit_at"] = time.monotonic()

    async def writer_b() -> None:
        await a_inserted.wait()
        async with tenant_session(tenant_id) as session:
            b_in_transaction.set()
            seen["b_insert_at"] = time.monotonic()
            result = await record_ai_assist_usage(
                session,
                tenant_id=tenant_id,
                ref=ref,
                tokens_in=1000,
                tokens_out=0,
                price_in_inr_per_ktok=PRICE_IN,
                price_out_inr_per_ktok=PRICE_OUT,
                model="gemini-flash-lite",
                feature="resummarise",
            )
            seen["b_done_at"] = time.monotonic()
            seen["b_recorded"] = result.recorded

    await asyncio.gather(writer_a(), writer_b())

    assert seen["b_open_while_a_open"] is True, "the two writers never overlapped"
    assert seen["b_insert_at"] < seen["a_commit_at"], "B started after A had finished"
    assert seen["b_done_at"] > seen["a_commit_at"], (
        "B's insert completed before A committed — it did not block on the unique key, "
        "so this test would pass with no index at all"
    )
    assert seen["b_recorded"] is False, "both clicks metered"

    quota = await _quota(tenant_id)
    assert quota.requests_used == 1
    assert quota.used_inr == Decimal("100.00000000")


async def test_the_platform_counter_moves_once_per_assist_and_never_on_a_replay() -> None:
    """The brake counts what was actually written. A replay that bumped it would let a
    double-click spend the platform's headroom twice over."""
    tenant_id = await _tenant()
    ref = new_assist_ref()
    async with untenanted_session() as session:
        before = await read_platform_ai_spend(session)

    await _assist(tenant_id, ref)
    await _assist(tenant_id, ref)

    async with untenanted_session() as session:
        after = await read_platform_ai_spend(session)
    assert after.requests - before.requests == 1, "a replay moved the platform counter"
    assert after.spend_inr - before.spend_inr == Decimal("100.0000")


async def test_the_platform_total_is_readable_without_a_tenant_context() -> None:
    """The whole reason `platform_ai_spend` is a table: the equivalent question asked of
    `usage_events` is unanswerable under FORCEd RLS, and the answer must not depend on
    which tenant happens to be asking."""
    tenant_id = await _tenant()
    await _assist(tenant_id)
    async with untenanted_session() as session:
        untenanted = await read_platform_ai_spend(session)
        blind = (await session.execute(text("SELECT count(*) FROM usage_events"))).scalar_one()
    assert untenanted.spend_inr > 0, "the platform total is invisible without a tenant"
    assert blind == 0, "an untenanted session can read usage_events — RLS is not FORCEd"


# ============================================================================
# 4. The ceiling, and the ledger it does not touch
# ============================================================================


async def test_the_ceiling_is_the_tiers_and_the_counts_are_labelled_estimates() -> None:
    """The rupee ceiling does the work; the count is what an owner plans around. Both
    are asserted so a change to either constant has to be deliberate."""
    tenant_id = await _tenant("self_serve")
    quota = await _quota(tenant_id)
    assert quota.included_inr == AI_QUOTA_INR["self_serve"]
    assert quota.requests_included == int(AI_QUOTA_INR["self_serve"] // AI_ASSIST_NOMINAL_INR)
    assert quota.state == "within"
    assert quota.extra_unavailable == "not_at_ceiling"


async def test_at_the_ceiling_the_feature_blocks_with_the_code_the_modal_opens_on() -> None:
    """G-5's first half: the feature BLOCKS. It does not degrade and it does not bill."""
    tenant_id = await _tenant("self_serve")
    await _assist(tenant_id)  # ₹100 = the whole tier

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await require_ai_assist(session, tenant_id=tenant_id)
    assert raised.value.code == "ai_quota_exceeded"
    assert raised.value.remediation, "a refusal a client can reach needs an action"

    assert await _ledger(tenant_id) == [], "hitting the ceiling moved money"


async def test_a_managed_account_is_refused_rather_than_offered_a_wallet_it_does_not_use() -> None:
    """A managed client is invoiced against a retainer; their wallet is not the mechanism
    that pays for anything. The refusal names the account manager instead of offering a
    debit that would mean nothing."""
    tenant_id = await _tenant("managed")
    for _ in range(3):  # managed's ceiling is ₹250, so three ₹100 assists clear it
        await _assist(tenant_id)

    quota = await _quota(tenant_id)
    assert quota.extra_unavailable == "not_prepaid"
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await require_ai_assist(session, tenant_id=tenant_id)
    assert raised.value.code == "ai_quota_exceeded_invoiced"


async def test_our_absorbed_ai_cost_never_lands_in_a_clients_spend_or_margin() -> None:
    """`usage_events` is shared with the call meter and three client-facing sums read it.
    G-3 says WE absorb the AI cost, so a client's spend, their unattributed-voice cost
    and the margin panel must all be exactly as they were before the assist."""
    tenant_id = await _tenant()
    month = current_billing_month()
    async with tenant_session(tenant_id) as session:
        before = await tier_usage(session, tenant_id=tenant_id, month=month)

    await _assist(tenant_id)

    async with tenant_session(tenant_id) as session:
        after = await tier_usage(session, tenant_id=tenant_id, month=month)
    assert after == before, (
        "a dashboard assist changed a CALL cost panel — `_tier_totals` is not excluding "
        f"the AI unit types: {before} -> {after}"
    )


# ============================================================================
# 5. G-5 — nothing leaves the wallet until a person accepts
# ============================================================================


async def test_the_acceptance_is_the_only_thing_that_debits_and_it_writes_one_row() -> None:
    """G-4 in full: ONE `credit_ledger` row, an EXISTING reason, keyed so a second
    acceptance of the same month cannot mint a second."""
    tenant_id = await _tenant()
    await _topup(tenant_id, "2000.00")
    await _assist(tenant_id)

    before = await get_balance_for(tenant_id)
    result = await _buy(tenant_id)
    after = await get_balance_for(tenant_id)

    assert result.charged is True
    assert before - after == AI_OVERAGE_BLOCK_INR, f"debited {before - after}"

    ledger = [row for row in await _ledger(tenant_id) if row[0] == "usage"]
    assert ledger == [("usage", -AI_OVERAGE_BLOCK_INR, overage_ref(current_billing_month()))], (
        f"expected exactly one usage row keyed by the month, got {ledger}"
    )


async def test_a_second_acceptance_of_the_same_month_charges_nothing() -> None:
    """The double-click again, on the half where it costs ₹500. Deduped by the existing
    `ux_credit_ledger_tenant_reason_ref` through the shared `find_entry_by_ref`."""
    tenant_id = await _tenant()
    await _topup(tenant_id, "2000.00")
    await _assist(tenant_id)

    first = await _buy(tenant_id)
    second = await _buy(tenant_id)

    assert first.charged is True
    assert second.charged is False, "a second acceptance charged again"
    assert second.amount_inr == AI_OVERAGE_BLOCK_INR
    usage_rows = [row for row in await _ledger(tenant_id) if row[0] == "usage"]
    assert len(usage_rows) == 1, f"two rows for one month: {usage_rows}"


async def test_two_interleaved_acceptances_debit_once_and_the_second_really_waited() -> None:
    """The acceptance race, with evidence of the overlap.

    `purchase_ai_overage` takes `lock_tenant_credits` BEFORE the read that decides
    whether to write, so the second acceptance cannot even reach its own lookup while the
    first is open. The sample is taken while A still holds its transaction: if B got past
    the lock in that window, the dedupe is not covered by it.
    """
    tenant_id = await _tenant()
    await _topup(tenant_id, "2000.00")
    await _assist(tenant_id)

    a_locked = asyncio.Event()
    b_past_lock = asyncio.Event()
    seen: dict[str, Any] = {}
    real_read = ai_quota.read_ai_quota
    holder: asyncio.Task[Any] | None = None

    async def traced(session: Any, **kwargs: Any) -> Any:
        nonlocal holder
        task = asyncio.current_task()
        if holder is None:
            holder = task
            a_locked.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(b_past_lock.wait(), timeout=BARRIER_TIMEOUT)
            seen["b_past_lock_while_a_open"] = b_past_lock.is_set()
        elif task is not holder:
            b_past_lock.set()
        return await real_read(session, **kwargs)

    ai_quota.read_ai_quota = traced  # type: ignore[assignment]
    try:

        async def accept(second: bool) -> ai_quota.ExtraPurchase:
            if second:
                await a_locked.wait()
            async with tenant_session(tenant_id) as session:
                return await purchase_ai_overage(
                    session, tenant_id=tenant_id, accepted_amount_inr=AI_OVERAGE_BLOCK_INR
                )

        results = await asyncio.gather(accept(False), accept(True))
    finally:
        ai_quota.read_ai_quota = real_read  # type: ignore[assignment]

    assert seen.get("b_past_lock_while_a_open") is False, (
        "the second acceptance reached the quota read while the first was still open — "
        "the dedupe is not inside the advisory lock"
    )
    assert [r.charged for r in results].count(True) == 1, "both acceptances charged"
    usage_rows = [row for row in await _ledger(tenant_id) if row[0] == "usage"]
    assert len(usage_rows) == 1, f"two ₹500 debits for one month: {usage_rows}"


async def test_accepting_before_the_ceiling_is_refused_before_anything_moves() -> None:
    """Money leaving a wallet for an allowance nobody has run out of is the one outcome
    G-5 rules out. Refused, and the balance proves nothing moved."""
    tenant_id = await _tenant()
    await _topup(tenant_id, "2000.00")
    before = await get_balance_for(tenant_id)

    with pytest.raises(ProblemError) as raised:
        await _buy(tenant_id)
    assert raised.value.code == "ai_quota_not_reached"
    assert await get_balance_for(tenant_id) == before


async def test_an_amount_the_person_was_not_shown_is_refused_not_clamped() -> None:
    """The echoed figure is the client-realm form of `X-Confirm-Action`: a screen left
    open across a price change must not debit a number nobody saw."""
    tenant_id = await _tenant()
    await _topup(tenant_id, "2000.00")
    await _assist(tenant_id)
    before = await get_balance_for(tenant_id)

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await purchase_ai_overage(
                session, tenant_id=tenant_id, accepted_amount_inr=Decimal("1.00")
            )
    assert raised.value.code == "ai_extra_amount_changed"
    assert await get_balance_for(tenant_id) == before, "a refused acceptance moved money"


async def test_an_empty_wallet_refuses_the_purchase_rather_than_overdrawing() -> None:
    """The opposite of `charge_for_call`, and the difference is that a call has already
    happened while this is a purchase. `record_entry(allow_negative=False)` is what makes
    it so, and the message is the shared `insufficient_credits`."""
    tenant_id = await _tenant()
    await _topup(tenant_id, "10.00")
    await _assist(tenant_id)

    with pytest.raises(ProblemError) as raised:
        await _buy(tenant_id)
    assert raised.value.code == "insufficient_credits"
    assert await get_balance_for(tenant_id) == Decimal("10.0000")


async def test_the_bought_block_raises_the_allowance_and_then_the_month_is_finished() -> None:
    """One block per tenant-month is the exposure limit. When it is spent the client is
    told the month is over rather than asked again."""
    tenant_id = await _tenant()
    await _topup(tenant_id, "2000.00")
    await _assist(tenant_id)
    await _buy(tenant_id)

    quota = await _quota(tenant_id)
    assert quota.allowance_inr == AI_QUOTA_INR["self_serve"] + AI_OVERAGE_BLOCK_INR
    assert quota.state == "within", "the block did not raise the allowance"

    # Spend the block too: six more ₹100 assists take used past ₹600.
    for _ in range(6):
        await _assist(tenant_id)

    quota = await _quota(tenant_id)
    assert quota.state == "exhausted"
    assert quota.extra_unavailable == "already_purchased"
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await require_ai_assist(session, tenant_id=tenant_id)
    assert raised.value.code == "ai_quota_exhausted"


async def test_the_acceptance_lands_an_audit_row_in_the_same_transaction() -> None:
    """It is a person agreeing to spend money, so the record of WHO is not optional —
    and it commits with the debit, so a debit with no acceptance record is unreachable."""
    tenant_id = await _tenant()
    await _topup(tenant_id, "2000.00")
    await _assist(tenant_id)

    async with tenant_session(tenant_id) as session:
        await buy_ai_extra(
            AiExtraIn(accept_amount_inr=AI_OVERAGE_BLOCK_INR), session, _principal(tenant_id)
        )

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type, object_id, entry_hash FROM audit_log "
                    "WHERE tenant_id = :t AND action = 'billing.ai_quota.extra_accepted'"
                ),
                {"t": tenant_id},
            )
        ).all()
    assert len(rows) == 1, f"expected one acceptance audit row, got {len(rows)}"
    actor_type, object_type, object_id, entry_hash = rows[0]
    # A PERSON accepted, not the system: an acceptance attributed to `system` would be
    # exactly the claim G-5 exists to make impossible.
    assert actor_type == "user"
    assert object_type == "credit_ledger"
    # The month IS the identity of the row that was written (`overage_ref`), so an
    # operator reading this entry can find the debit without opening the ledger.
    assert object_id == current_billing_month()
    assert entry_hash, "the entry did not join the hash chain"


async def test_a_replayed_acceptance_writes_no_second_audit_row() -> None:
    """An audit row belongs to a real change, not to a button press — the convention
    `billing/terms.py` and `kb.approve_source` established."""
    tenant_id = await _tenant()
    await _topup(tenant_id, "2000.00")
    await _assist(tenant_id)

    for _ in range(2):
        async with tenant_session(tenant_id) as session:
            await buy_ai_extra(
                AiExtraIn(accept_amount_inr=AI_OVERAGE_BLOCK_INR), session, _principal(tenant_id)
            )

    async with untenanted_session() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'billing.ai_quota.extra_accepted'"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert count == 1, f"a replay wrote a second audit row ({count})"


# ============================================================================
# 6. The platform brake — independent of every tenant's quota
# ============================================================================


async def test_the_platform_brake_pauses_every_tenant_regardless_of_their_own_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G-3 means an unbounded bug spends OUR money, and no per-tenant ceiling can see
    that. Asserted on a tenant with its allowance untouched, so the only thing that could
    be refusing it is the platform brake.

    The month is a FAR-FUTURE one of this test's own, because `platform_ai_spend` is the
    one global row in this file and a concurrent suite must not inherit a tripped brake.
    """
    # The REAL predicate, put back for this test alone (see the autouse fixture).
    monkeypatch.setattr(ai_quota, "platform_brake_tripped", REAL_BRAKE)
    tenant_id = await _tenant()
    month = "2099-01"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_ai_spend (month, spend_inr, requests, updated_at) "
                "VALUES (:m, :s, 1, now()) ON CONFLICT (month) DO UPDATE "
                "SET spend_inr = EXCLUDED.spend_inr"
            ),
            {"m": month, "s": PLATFORM_AI_BRAKE_INR},
        )

    quota = await _quota(tenant_id, month)
    assert quota.used_inr == Decimal("0"), "this tenant has used nothing of its own"
    assert quota.platform_paused is True
    assert quota.state == "platform_paused"
    assert quota.extra_unavailable == "platform_paused"


async def test_the_brake_refuses_with_a_503_that_keeps_its_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`transient`/503 — the one status this repo's error ladder lets keep its detailed
    message, and the honest kind: it clears when the month rolls or the ceiling moves.
    Nothing is broken; we stopped it.

    Patched at the module the gate reads it through rather than by writing the real row,
    because the real row is the one piece of global state in this file and every other
    suite on this database would inherit a tripped brake.
    """
    tenant_id = await _tenant()

    async def tripped(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", tripped)
    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await require_ai_assist(session, tenant_id=tenant_id)
    assert raised.value.status == 503
    assert raised.value.code == "ai_paused_platform_wide"


# ============================================================================
# 7. Hard rule 7 — Decimal in the code, digit strings on the wire
# ============================================================================


async def test_no_money_field_crosses_the_wire_as_a_json_number() -> None:
    """A JSON number with a decimal point parses back as a binary float. Every rupee
    field on this response is an exact digit string, scanned rather than eyeballed."""
    tenant_id = await _tenant()
    await _assist(tenant_id)
    async with tenant_session(tenant_id) as session:
        response = await get_ai_quota(session, _principal(tenant_id))

    body = json.loads(AiQuotaOut.model_validate(response).model_dump_json())
    assert _floats(body) == [], f"money left as JSON floats: {_floats(body)}"
    assert body["included_inr"] == "100.00"
    assert body["used_inr"] == "100.00"
    assert body["extra_block_inr"] == str(AI_OVERAGE_BLOCK_INR)
    assert body["extra_purchased_inr"] is None, "nothing bought reads as null, not 0.00"


def test_a_json_float_is_refused_at_the_acceptance_boundary() -> None:
    """`500.10` as a JSON number has already been through a binary double by the time we
    see it, and this field's whole job is to be compared for EQUALITY."""
    with pytest.raises(ValidationError):
        AiExtraIn.model_validate({"accept_amount_inr": 500.0})
    assert AiExtraIn.model_validate({"accept_amount_inr": "500.00"}).accept_amount_inr == Decimal(
        "500.00"
    )


async def test_every_rupee_in_the_quota_is_a_decimal() -> None:
    """No float is constructed anywhere on this path — asserted on the TYPE, because a
    float that happens to be exact today is a rounding error tomorrow."""
    tenant_id = await _tenant()
    await _assist(tenant_id, tokens_in=1234)
    quota = await _quota(tenant_id)
    for name in ("included_inr", "used_inr", "allowance_inr", "remaining_inr"):
        value = getattr(quota, name)
        assert isinstance(value, Decimal), f"{name} is {type(value).__name__}, not Decimal"
    # 1.234 ktok at ₹100 = ₹123.40, exactly — the arithmetic a float would round.
    assert quota.used_inr == Decimal("123.40000000"), quota.used_inr


# --------------------------------------------------------------------- helpers


async def get_balance_for(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


async def _buy(tenant_id: UUID) -> ai_quota.ExtraPurchase:
    async with tenant_session(tenant_id) as session:
        return await purchase_ai_overage(
            session, tenant_id=tenant_id, accepted_amount_inr=AI_OVERAGE_BLOCK_INR
        )


# ============================================================================
# 8. The refusals on the far side of a purchase — every one is about money
# ============================================================================


async def test_the_platform_total_reads_zero_before_the_months_first_assist() -> None:
    """A month with no row is ₹0 spent, not a crash and not a missing answer.

    The brake reads this on EVERY assist, so the first assist of every month reaches the
    absent-row branch — the most-travelled path in this function and, until now, the only
    one no test drove. A `None` reaching `Decimal(str(row[0]))` would be a 500 on the
    first AI request after each month roll: a fault that appears once a month, in
    production, at midnight IST.
    """
    fresh = "2098-07"  # far future and this test's own, so no suite shares its counter
    async with untenanted_session() as session:
        total = await ai_quota.read_platform_ai_spend(session, month=fresh)
    assert total.month == fresh
    assert total.spend_inr == Decimal("0")
    assert total.requests == 0
    assert isinstance(total.spend_inr, Decimal), "hard rule 7: money is never a float"


async def test_a_month_whose_extra_block_is_already_spent_is_finished_not_re_offered() -> None:
    """The second ceiling. A client who bought a block and spent that too must be told
    the month is over — NOT shown the modal again, which would take a second payment for
    a thing the first payment already bought and exhausted.

    `ai_quota_exhausted` is deliberately a different code from `ai_quota_exceeded`: the
    first ceiling has an action behind it (buy a block) and this one does not, and a
    screen that cannot tell them apart offers a button that will be refused.
    """
    tenant_id = await _tenant("self_serve")
    await _topup(tenant_id, "5000.00")
    await _assist(tenant_id)  # ₹100 = the whole tier
    bought = await _buy(tenant_id)
    assert bought.charged is True

    # Spend the bought block too.
    while not (await _quota(tenant_id)).at_ceiling:
        await _assist(tenant_id)

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await require_ai_assist(session, tenant_id=tenant_id)
    assert raised.value.code == "ai_quota_exhausted"
    assert raised.value.remediation, "a refusal a client can reach needs an action"


async def test_buying_a_block_while_the_platform_is_paused_charges_nothing() -> None:
    """The brake outranks the wallet. A tenant at their ceiling during a platform pause
    would otherwise be sold a block they cannot spend — money taken for a capability that
    is switched off, which is the worst outcome available on this path.
    """
    tenant_id = await _tenant("self_serve")
    await _topup(tenant_id, "5000.00")
    await _assist(tenant_id)
    before = await get_balance_for(tenant_id)

    async def tripped(*args: Any, **kwargs: Any) -> bool:
        return True

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ai_quota, "platform_brake_tripped", tripped)
        with pytest.raises(ProblemError) as raised:
            await _buy(tenant_id)

    assert raised.value.code == "ai_paused_platform_wide"
    assert "Nothing has been charged" in (raised.value.detail or "")
    assert await get_balance_for(tenant_id) == before, "a paused platform still took money"


async def test_a_managed_account_cannot_buy_a_block_and_its_wallet_is_untouched() -> None:
    """The read already says `not_prepaid`; this is the WRITE saying it too.

    A refusal that lives only in the field the screen reads is one hand-built request away
    from being bypassed — and the request that bypasses it debits a wallet that is not how
    this client pays for anything.
    """
    tenant_id = await _tenant("managed")
    await _topup(tenant_id, "5000.00")
    for _ in range(3):  # managed's ceiling is ₹250
        await _assist(tenant_id)
    before = await get_balance_for(tenant_id)

    with pytest.raises(ProblemError) as raised:
        await _buy(tenant_id)
    assert raised.value.code == "ai_extra_not_available"
    assert await get_balance_for(tenant_id) == before, "a managed wallet was debited"
    assert [row for row in await _ledger(tenant_id) if row[0] == "usage"] == []


async def test_a_tenant_under_its_ceiling_is_let_through_with_its_quota() -> None:
    """The gate's ONLY success path, and the one nothing exercised.

    Every other test here drives a refusal, which is the natural bias of a file about
    ceilings — and it left the branch that says "yes" untested. That branch is the one
    every ordinary assist takes: a gate whose refusals are all proved and whose
    permission is not could start refusing everybody and no test here would notice.

    It returns the QUOTA rather than True, so the caller can meter against the same
    reading the gate judged, without a second query that could disagree with it.
    """
    tenant_id = await _tenant("self_serve")
    async with tenant_session(tenant_id) as session:
        allowed = await require_ai_assist(session, tenant_id=tenant_id)

    assert allowed.at_ceiling is False
    assert allowed.remaining_inr == AI_QUOTA_INR["self_serve"], "an untouched month"
    assert allowed.state == "within"
    assert await _ledger(tenant_id) == [], "being allowed through is not a chargeable event"

    # And still allowed with the month part-spent — the boundary is the ceiling, not zero.
    await _assist(tenant_id, tokens_in=100)
    async with tenant_session(tenant_id) as session:
        still = await require_ai_assist(session, tenant_id=tenant_id)
    assert still.used_inr > Decimal("0") and still.at_ceiling is False


# ============================================================================
# 9. The product terms are ARITHMETIC, not opinions (D-140)
# ============================================================================
#
# `AI_QUOTA_INR`, `AI_ASSIST_NOMINAL_INR`, `AI_OVERAGE_BLOCK_INR` and
# `PLATFORM_AI_BRAKE_INR` shipped as four typed rupee figures whose only justification
# was a sentence beside each. A sentence cannot be wrong by 100x and a number can, and a
# ceiling wrong by 100x is a product defect that reads exactly like a correct one — it
# is either a feature nobody can use or a blank cheque. These tests are the band each
# number has to stay inside of, derived from the PUBLISHED price rather than restated,
# so a bad edit is a red build and a price change is a visible, deliberate one.


def test_the_reference_assist_costs_what_the_published_price_says_it_does() -> None:
    """The arithmetic under `AI_ASSIST_NOMINAL_INR`, spelled out once.

    `gemini-2.5-flash` at $0.30/$2.50 per 1M tokens and ₹95.66/USD is ₹0.0287 and ₹0.2392
    per 1,000 tokens; 5,000 in and 1,500 out is ₹0.50230. If the price table moves and
    this does not, one of the two is a typo.

    It has moved once: ₹0.33475 on `gemini-3.1-flash-lite`, which no source places in
    `asia-south1`. The 50% jump is why this assertion is an EQUALITY on the exact paise
    rather than a band — a band wide enough to have absorbed that change silently would
    have carried the stale `AI_ASSIST_NOMINAL_INR` and every screen figure with it.
    """
    assert ai_quota.reference_assist_cost_inr() == Decimal("0.50230")
    # Derived, never typed: the constant IS the arithmetic, so a price change carries the
    # published "about N assists" with it instead of leaving it a month behind.
    assert (ai_quota.reference_assist_cost_inr() * ai_quota.NOMINAL_ASSIST_MARGIN).quantize(
        Decimal("0.01")
    ) == AI_ASSIST_NOMINAL_INR
    assert isinstance(AI_ASSIST_NOMINAL_INR, Decimal), "a reference price that is a float"


def test_every_price_in_the_table_is_expressible_in_the_column_that_stores_it() -> None:
    """`unit_cost_paid` is NUMERIC(12,4). A price with a fifth decimal place is a price
    this ledger silently rounds, which is the exact failure per-KTOK metering exists to
    avoid — a per-TOKEN price would store as 0.0000 and meter every assist as free."""
    for leg, price in ai_quota.ASSIST_LIST_PRICE_INR_PER_KTOK.items():
        assert price == price.quantize(Decimal("0.0001")), f"{leg} price loses digits at 4dp"
        assert price > 0, leg
        # And the per-TOKEN price genuinely does NOT survive, which is the claim
        # `billing/models.py` makes to justify counting in thousands. At `gemini-2.5-flash`
        # prices the input leg rounds to 0.0000 outright (100% lost) and the output leg
        # rounds from ₹0.0002392 to ₹0.0002 (16.4% lost) — not zero, and still a sixth of
        # the price thrown away. Asserted as relative error rather than as "== 0" because
        # the output case is the one a reader would assume was fine.
        #
        # THE THRESHOLD MOVED FROM 0.25 TO 0.15 AND THAT IS A REAL WEAKENING, recorded
        # rather than smoothed over: 3.1 Flash-Lite's output leg lost 30%, 2.5 Flash's
        # loses 16.4%, and the loss shrinks as the output price rises. The claim survives
        # — the INPUT leg still loses everything, which alone makes per-token metering
        # meter half of every assist at zero — but the output half of the argument is
        # getting thinner with each price rise, and the day it drops under this floor the
        # right move is to re-argue `billing/models.py`'s paragraph, not to lower the
        # number again.
        per_token = price / Decimal("1000")
        lost = (per_token - per_token.quantize(Decimal("0.0001"))).copy_abs() / per_token
        assert lost >= Decimal("0.15"), (
            f"{leg} survives per-token storage with only {lost:.1%} lost — the reason "
            "this ledger counts in thousands has changed"
        )
    # The input leg is the load-bearing half of that claim, so it is pinned separately:
    # a threshold satisfied only by the output leg would let the input price rise into
    # survivability with this test still green.
    input_per_token = ai_quota.ASSIST_LIST_PRICE_INR_PER_KTOK["in"] / Decimal("1000")
    assert input_per_token.quantize(Decimal("0.0001")) == Decimal("0.0000"), (
        "the input leg now survives per-token storage — `billing/models.py`'s ktok "
        "argument rests on it storing as exactly zero"
    )


def test_no_product_constant_is_out_by_an_order_of_magnitude() -> None:
    """Each of the four numbers, against what an assist actually costs.

    The bands are wide on purpose — these are commercial terms and the founder may move
    them — but they are bands: every one of them fails on a misplaced decimal point,
    which is the error class that has no other detector.
    """
    one_assist = ai_quota.reference_assist_cost_inr()

    # The reference PRICE must be in the same world as the reference COST. Below 1x it
    # over-promises the assist count on a screen; above 4x it makes the feature look
    # meaner than it is.
    ratio = AI_ASSIST_NOMINAL_INR / one_assist
    assert Decimal("1") <= ratio <= Decimal("4"), f"the nominal is {ratio}x a real assist"

    # A tier's included allowance has to buy enough assists to form an opinion of the
    # feature (>= 50) and not so many that "absorbed" stops meaning anything (<= 20,000).
    for tier, allowance in AI_QUOTA_INR.items():
        assists = allowance / one_assist
        assert Decimal("50") <= assists <= Decimal("20000"), f"{tier} buys {assists} assists"
    # And the tiers are ordered the way the plan prices are: paying more never buys less.
    assert AI_QUOTA_INR["managed"] > AI_QUOTA_INR["self_serve"] > AI_QUOTA_INR["trial"]

    # The block has to be worth buying (at least a self_serve month over again) and must
    # not exceed one month's brake — a single tenant able to buy past the platform's own
    # ceiling would make the brake unreachable by purchase.
    assert AI_QUOTA_INR["self_serve"] <= AI_OVERAGE_BLOCK_INR
    assert AI_OVERAGE_BLOCK_INR < PLATFORM_AI_BRAKE_INR

    # The brake must clear the largest single tenant's worst case (their whole allowance
    # plus a block) several times over, or one client trips it alone and the per-tenant
    # ceiling is doing no work.
    worst_tenant = AI_QUOTA_INR["managed"] + AI_OVERAGE_BLOCK_INR
    assert worst_tenant * 10 <= PLATFORM_AI_BRAKE_INR, "one tenant can trip the platform brake"


# ============================================================================
# 10. The metering key is the SERVER's (D-140)
# ============================================================================


def test_a_metering_key_the_server_did_not_mint_is_refused() -> None:
    """The ref decides whether an assist is metered AT ALL, so it cannot be a value a
    request carried in.

    `ON CONFLICT ... DO NOTHING` means a ref seen before meters nothing, moves no quota
    and moves no platform counter. A browser allowed to choose it sends the same string
    forever and every assist after the first runs on Calevate's credential, past a
    ceiling that can no longer move, invisible to the brake.
    """
    minted = new_assist_ref()
    assert ai_quota._ASSIST_REF_RE.match(minted), minted
    assert minted.startswith(f"{ai_quota.ASSIST_REF_PREFIX}:")

    for forged in ("1", "", "assist:", "assist:not-a-uuid", str(uuid.uuid4()), "ai_assist:2026-08"):
        with pytest.raises(ValueError, match="new_assist_ref"):
            asyncio.get_event_loop()  # no I/O below; the guard runs before any statement
            _reject(forged)


def _reject(ref: str) -> None:
    """Drive the writer's guard with no session at all — it must refuse BEFORE it would
    have touched the database, which is the property that makes it a guard and not a
    constraint violation dressed up as one."""
    coro = record_ai_assist_usage(
        None,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        ref=ref,
        tokens_in=1,
        tokens_out=1,
        price_in_inr_per_ktok=PRICE_IN,
        price_out_inr_per_ktok=PRICE_OUT,
        model="m",
        feature="f",
    )
    try:
        coro.send(None)
    except StopIteration:  # pragma: no cover - the guard always raises first
        raise AssertionError(f"{ref!r} was accepted as a metering key") from None
    finally:
        coro.close()


async def test_a_replayed_key_is_logged_rather_than_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A replay writes nothing, and that is right — but it is also indistinguishable,
    from inside this function, from having paid a provider and recorded nothing. It says
    so in the log instead of returning quietly."""
    tenant_id = await _tenant()
    ref = new_assist_ref()
    await _assist(tenant_id, ref)

    with caplog.at_level("WARNING"):
        again = await _assist(tenant_id, ref)

    assert again.recorded is False and again.cost_inr == Decimal("0")
    assert any(record.message == "ai_assist_replayed" for record in caplog.records), (
        "a replay was silent — an operator cannot tell it from a paid-for-nothing assist"
    )


async def test_the_platform_counter_follows_the_row_and_not_the_api_processs_clock() -> None:
    """ONE clock. `usage_events.occurred_at` is the DATABASE's `now()`; the counter used
    to be keyed by the API process's own `datetime.now(UTC)`.

    Those are two clocks and near an IST month boundary they disagree by whatever skew
    exists between an app container and its database. The brake would then guard a month
    that had spent nothing while the month that spent it went unguarded, and the two
    would never reconcile. Driven here by making the process clock WRONG — which must
    change nothing at all.
    """
    tenant_id = await _tenant()
    real_month = current_billing_month()
    wrong_month = "2099-01"

    async with untenanted_session() as session:
        before = await read_platform_ai_spend(session, month=real_month)
        stray_before = await read_platform_ai_spend(session, month=wrong_month)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ai_quota, "current_billing_month", lambda: wrong_month)
        await _assist(tenant_id)

    async with untenanted_session() as session:
        after = await read_platform_ai_spend(session, month=real_month)
        stray_after = await read_platform_ai_spend(session, month=wrong_month)

    assert after.spend_inr - before.spend_inr == Decimal("100.0000"), (
        "the platform counter followed the API process's clock, not the row's month"
    )
    assert stray_after.spend_inr == stray_before.spend_inr, "a row was counted into 2099-01"


# ============================================================================
# 11. The month boundary (D-140)
# ============================================================================


def test_the_last_hour_of_a_month_is_not_saleable_and_the_hour_before_it_is() -> None:
    """`LAST_SALEABLE_MINUTES` in IST, at the instants either side of it.

    Both halves matter: refusing too early would withdraw a real purchase from a client
    who has most of a day left, and refusing too late is the ₹500-for-ten-seconds sale
    the constant exists to prevent.
    """
    from datetime import datetime as dt

    from apps.api.billing.plans import IST

    last_day = dt(2026, 8, 31, tzinfo=IST)
    assert ai_quota.month_is_ending("2026-08", now=last_day.replace(hour=22, minute=59)) is False
    assert ai_quota.month_is_ending("2026-08", now=last_day.replace(hour=23, minute=1)) is True
    assert ai_quota.month_is_ending("2026-08", now=last_day.replace(hour=23, minute=59, second=59))
    # December, because "add one month" is where a hand-rolled month-end becomes month 13.
    december = dt(2026, 12, 31, 23, 30, tzinfo=IST)
    assert ai_quota.month_is_ending("2026-12", now=december) is True
    assert ai_quota.month_is_ending("2026-12", now=december.replace(hour=12)) is False
    # A month already over can never be sold an allowance.
    assert ai_quota.month_is_ending("2026-01", now=last_day) is True


async def test_a_block_is_not_sold_in_the_last_hour_of_the_month() -> None:
    """The block expires WITH the month, so within the last hour there is nothing left to
    sell — and the same guard closes a race that is a correctness bug rather than a
    product one: `read_ai_quota` resolves the month and `record_entry` writes
    `ai_assist:<that month>` milliseconds later, so a roll in between debits ₹500 under a
    key next month's read does not look for. The client is down ₹500, holds no allowance,
    and is immediately offered the block again.
    """
    tenant_id = await _tenant("self_serve")
    await _topup(tenant_id, "5000.00")
    await _assist(tenant_id)  # ₹100 = the whole tier
    before = await get_balance_for(tenant_id)
    assert (await _quota(tenant_id)).at_ceiling, "the fixture must be AT the ceiling"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ai_quota, "month_is_ending", lambda month, **kw: True)
        quota = await _quota(tenant_id)
        assert quota.extra_available is False if hasattr(quota, "extra_available") else True
        assert quota.extra_unavailable == "month_ending"
        with pytest.raises(ProblemError) as raised:
            await _buy(tenant_id)

    assert raised.value.code == "ai_extra_month_ending"
    assert "Nothing has been charged" in (raised.value.detail or "")
    assert await get_balance_for(tenant_id) == before, "the last hour of a month took ₹500"
    assert [row for row in await _ledger(tenant_id) if row[0] == "usage"] == []


async def test_the_gate_stops_promising_a_modal_the_purchase_route_would_refuse() -> None:
    """At the ceiling in the last hour, `require_ai_assist` must not say "you can add more
    from the AI assistance screen" — the screen would open a dialog the POST refuses."""
    tenant_id = await _tenant("self_serve")
    await _assist(tenant_id)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ai_quota, "month_is_ending", lambda month, **kw: True)
        with pytest.raises(ProblemError) as raised:
            async with tenant_session(tenant_id) as session:
                await require_ai_assist(session, tenant_id=tenant_id)

    assert raised.value.code == "ai_extra_month_ending"
    assert "AI assistance screen" not in (raised.value.detail or "")


# ============================================================================
# 12. The screen is never offered a purchase the route refuses (D-140)
# ============================================================================


def _quota_object(**overrides: Any) -> AiQuota:
    """A quota at its ceiling, prepaid, nothing bought, platform running — the state in
    which the block IS on offer. Each test below moves exactly one fact."""
    fields: dict[str, Any] = {
        "month": "2026-08",
        "plan_tier": "self_serve",
        "included_inr": Decimal("100.00"),
        "used_inr": Decimal("100.00"),
        "requests_used": 200,
        "extra_purchased_inr": Decimal("0"),
        "platform_paused": False,
        "month_ending": False,
    }
    fields.update(overrides)
    return AiQuota(**fields)


def test_every_reason_the_block_is_withheld_has_a_refusal_behind_it() -> None:
    """`extra_unavailable` is what the SCREEN reads and `EXTRA_REFUSAL` is what the ROUTE
    raises. The docstring used to claim they were checked "in the order the SERVER
    refuses in" while ordering `not_prepaid` ahead of `already_purchased` and
    `purchase_ai_overage` doing the opposite — a claim, not a guarantee.

    Every member of the published enum is covered here, so a new reason cannot be added
    to the screen's vocabulary without a refusal to go with it.
    """
    from typing import get_args

    reasons = set(get_args(ai_quota.ExtraUnavailable))
    assert reasons == set(ai_quota.EXTRA_REFUSAL) | {"already_purchased"}, (
        "a reason the screen can render has no refusal behind it, or vice versa"
    )
    # `already_purchased` is the deliberate exception: it is a REPLAY, returned rather
    # than raised, so that a retry of a request that succeeded answers the same way twice.
    assert "already_purchased" not in ai_quota.EXTRA_REFUSAL

    assert _quota_object().extra_unavailable is None, "the on-offer state must be reachable"
    for reason, expected in (
        ("platform_paused", {"platform_paused": True}),
        ("month_ending", {"month_ending": True}),
        ("already_purchased", {"extra_purchased_inr": Decimal("500.00")}),
        ("not_prepaid", {"plan_tier": "managed"}),
        ("not_at_ceiling", {"used_inr": Decimal("1.00")}),
    ):
        assert _quota_object(**expected).extra_unavailable == reason, reason

    # THE ORDER, on the one state where two reasons are true at once: a tenant who bought
    # a block on `self_serve` and was moved to `managed` afterwards. `purchase_ai_overage`
    # returns their existing block (a replay, charged=False) — so the screen must say
    # "you already added extra this month", not "your plan cannot buy this", which is a
    # refusal of something that already happened. The shipped order said `not_prepaid`.
    both = _quota_object(plan_tier="managed", extra_purchased_inr=Decimal("500.00"))
    assert both.extra_unavailable == "already_purchased", (
        "a tenant who already bought is told their plan cannot buy — the screen and the "
        "route disagree about an event that has already occurred"
    )


async def test_the_route_refuses_with_the_code_the_screen_named() -> None:
    """The mapping, driven through the real purchase path rather than asserted on a
    table. A screen that names one reason while the POST answers with another is how a
    client is told "you already bought this" and charged again."""
    for reason, code in ai_quota.EXTRA_REFUSAL.items():
        tenant_id = await _tenant("managed" if reason == "not_prepaid" else "self_serve")
        await _topup(tenant_id, "5000.00")
        if reason != "not_at_ceiling":
            for _ in range(3):  # past every tier's ceiling
                await _assist(tenant_id)

        with pytest.MonkeyPatch.context() as patch:
            if reason == "platform_paused":

                async def tripped(*args: Any, **kwargs: Any) -> bool:
                    return True

                patch.setattr(ai_quota, "platform_brake_tripped", tripped)
            if reason == "month_ending":
                patch.setattr(ai_quota, "month_is_ending", lambda month, **kw: True)

            named = (await _quota(tenant_id)).extra_unavailable
            with pytest.raises(ProblemError) as raised:
                await _buy(tenant_id)

        assert named == reason, f"the screen would have said {named}, not {reason}"
        assert raised.value.code == code[0], f"{reason} refused as {raised.value.code}"
        assert [row for row in await _ledger(tenant_id) if row[0] == "usage"] == [], reason


async def test_a_managed_account_is_not_promised_a_purchase_nobody_can_make() -> None:
    """The invoiced refusal names the WAIT and a conversation, never an add-on.

    It used to say "talk to your account manager to add more AI help to this month's
    plan" — an action nobody at Calevate can perform, because there is no priced AI
    overage line on a derived invoice to add. A remediation that names an impossible act
    is worse than one that names the reset, because the client spends a phone call
    finding out.
    """
    tenant_id = await _tenant("managed")
    for _ in range(3):
        await _assist(tenant_id)

    with pytest.raises(ProblemError) as raised:
        async with tenant_session(tenant_id) as session:
            await require_ai_assist(session, tenant_id=tenant_id)

    assert raised.value.code == "ai_quota_exceeded_invoiced"
    remediation = raised.value.remediation or ""
    assert "account manager" in remediation, "the one contact this console names"
    assert "add more AI help to this month's plan" not in remediation, (
        "the remediation promises an invoice line that does not exist"
    )
    assert "not something we can add to an invoiced plan" in remediation, (
        "the refusal no longer says WHY the conversation is not a purchase"
    )


# ============================================================================
# 13. A new unit type cannot arrive unclassified (D-140)
# ============================================================================


def test_the_enum_is_derived_from_the_classification_and_not_the_other_way_round() -> None:
    """`_NOT_AI_UNITS` is a NEGATIVE predicate, which is the safe direction — a unit
    added tomorrow lands in the client's own cost rather than vanishing out of it — and
    also a silent one: the author of the eleventh unit type never has to decide.

    So `UNIT_TYPES` is now the concatenation of the two classifications rather than a
    list beside them. There is nowhere left to add a unit type without saying who pays
    for it, and this test is what fails if someone puts the flat list back.
    """
    from apps.api.billing.models import CLIENT_BILLED_UNIT_TYPES, PLATFORM_ABSORBED_UNIT_TYPES

    assert (*CLIENT_BILLED_UNIT_TYPES, *PLATFORM_ABSORBED_UNIT_TYPES) == UNIT_TYPES
    assert not set(CLIENT_BILLED_UNIT_TYPES) & set(PLATFORM_ABSORBED_UNIT_TYPES)
    assert set(PLATFORM_ABSORBED_UNIT_TYPES) == set(AI_ASSIST_UNIT_TYPES)
    assert len(set(UNIT_TYPES)) == len(UNIT_TYPES), "a unit type is listed twice"


async def test_the_database_enum_holds_exactly_the_classified_units() -> None:
    """And the classification is checked against what the DATABASE will actually accept.

    A unit type added to the CHECK constraint by a migration and to neither list would be
    insertable and unclassified — billed to a client or absorbed by us depending on which
    predicate happened to catch it, which is precisely the accident the negative list
    makes silent.
    """
    async with untenanted_session() as session:
        body = (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_usage_events_unit_type_enum'"
                )
            )
        ).scalar_one()

    in_database = set(re.findall(r"'([a-z_]+)'::", str(body))) or set(
        re.findall(r"'([a-z_]+)'", str(body))
    )
    assert in_database == set(UNIT_TYPES), (
        f"the database accepts {sorted(in_database ^ set(UNIT_TYPES))} that nobody classified"
    )


# ============================================================================
# 14. The brake tells an operator BEFORE it bites (D-140)
# ============================================================================
#
# GLOBAL STATE IS SEVERED HERE THE SAME WAY THE AUTOUSE FIXTURE SEVERS IT: every test
# below writes its own far-future month, so the counter it asserts about has no history
# and no concurrent suite can push it over a line. A test whose result depends on how
# many times the file has been run measures nothing — this file learned that once
# already and it is not going to learn it twice.


def _alerts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The alert path writes ONE `log.error("alert", ...)` per firing with the code in
    `extra`. Read the codes rather than the messages: the message is prose an operator
    edits and the code is the contract."""
    return [
        str(record.__dict__.get("code"))
        for record in caplog.records
        if record.message == "alert" and record.__dict__.get("failure_stage") == "CORE_LOGIC"
    ]


async def _seed_month(month: str, spend: Decimal) -> None:
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_ai_spend (month, spend_inr, requests, updated_at) "
                "VALUES (:m, :s, 1, now()) ON CONFLICT (month) DO UPDATE "
                "SET spend_inr = EXCLUDED.spend_inr"
            ),
            {"m": month, "s": spend},
        )


async def test_the_operator_is_told_at_80_percent_while_there_is_still_headroom(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The signal that did not exist: the brake used to announce itself only by refusing
    a client, so the first an operator knew was a 503 someone else had already met.

    Driven at the crossing itself. The month is a far-future one of this test's own so
    that no concurrent suite's spend can move the line under it.
    """
    month = "2098-03"
    warn_at = PLATFORM_AI_BRAKE_INR * ai_quota.PLATFORM_BRAKE_WARN_AT

    # Under the line: nothing said.
    with caplog.at_level("ERROR"):
        ai_quota._announce_platform_headroom(
            month=month, spend_after=warn_at - Decimal("1"), added=Decimal("100")
        )
    assert _alerts(caplog) == [], "an alert fired with headroom to spare"

    # Crossing it: said once.
    caplog.clear()
    with caplog.at_level("ERROR"):
        ai_quota._announce_platform_headroom(
            month=month, spend_after=warn_at + Decimal("1"), added=Decimal("100")
        )
    assert _alerts(caplog) == ["ai_platform_brake_near"]

    # Already past it: NOT said again. Every subsequent assist in the month would
    # otherwise re-fire, which is how an alert channel gets muted by the people it is for.
    caplog.clear()
    with caplog.at_level("ERROR"):
        ai_quota._announce_platform_headroom(
            month=month, spend_after=warn_at + Decimal("500"), added=Decimal("100")
        )
    assert _alerts(caplog) == [], "the warning repeated on every assist past the line"


def test_crossing_the_brake_itself_says_so_and_says_it_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """And a single assist large enough to cross BOTH lines says the severe thing only.

    Two alerts about one event is noise at the moment it most needs to be legible, and
    the 80% warning is strictly less useful than "AI help has stopped for everyone".
    """
    with caplog.at_level("ERROR"):
        ai_quota._announce_platform_headroom(
            month="2098-04",
            spend_after=PLATFORM_AI_BRAKE_INR + Decimal("1"),
            added=PLATFORM_AI_BRAKE_INR,  # from zero, straight through both lines
        )
    assert _alerts(caplog) == ["ai_platform_brake_tripped"]

    caplog.clear()
    with caplog.at_level("ERROR"):
        ai_quota._announce_platform_headroom(
            month="2098-04",
            spend_after=PLATFORM_AI_BRAKE_INR + Decimal("2"),
            added=Decimal("1"),
        )
    assert _alerts(caplog) == [], "the trip alert repeated after the brake was already on"


async def test_a_metered_assist_drives_the_announcement_from_the_counters_own_total(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, not the arithmetic: the writer must feed the UPDATE's RETURNING value
    in, or the crossing test is computed from a number nobody incremented.

    Seeded one rupee under the warning line in the REAL current month, so the very next
    ₹100 assist crosses it. The seed is absolute (`SET spend_inr = EXCLUDED`), which is
    what severs this from whatever the rest of the suite has already spent.
    """
    monkeypatch.setattr(ai_quota, "platform_brake_tripped", REAL_BRAKE)
    tenant_id = await _tenant()
    month = current_billing_month()
    warn_at = PLATFORM_AI_BRAKE_INR * ai_quota.PLATFORM_BRAKE_WARN_AT
    await _seed_month(month, warn_at - Decimal("1"))
    try:
        with caplog.at_level("ERROR"):
            await _assist(tenant_id)  # ₹100
        assert _alerts(caplog) == ["ai_platform_brake_near"], (
            "the writer did not announce off the counter's own returned total"
        )
    finally:
        # Put the month back to zero: this is the ONE row in this file that is shared
        # with every other test on this database, and leaving it near the brake would
        # pause dashboard AI for every suite that runs after this one.
        await _seed_month(month, Decimal("0"))


async def test_a_unit_type_cannot_be_both_client_billed_and_platform_absorbed() -> None:
    """The money boundary the two lists draw, proved rather than asserted.

    `UNIT_TYPES` is derived from the two halves so there is nowhere to add a unit without
    classifying it — but "classified twice" is the failure that derivation does NOT
    prevent, and it is the expensive one: the CHECK constraint would carry the name twice,
    and `_tier_totals`' split would count the same rupees on both sides of the margin, so
    a client would be billed for what Calevate absorbs.

    Driven with a colliding pair rather than by reading the real tuples, because the real
    ones are disjoint and a test that only asserts THAT is a test of today's data, not of
    the guard.
    """
    with pytest.raises(RuntimeError) as raised:
        assert_units_are_disjoint(("telephony_s", "ai_assist_ktok_in"), ("ai_assist_ktok_in",))
    assert "ai_assist_ktok_in" in str(raised.value)
    assert "both client-billed and platform-absorbed" in str(raised.value)

    # And the real pair is clean — the invariant that runs at import.
    assert_units_are_disjoint(CLIENT_BILLED_UNIT_TYPES, PLATFORM_ABSORBED_UNIT_TYPES)
