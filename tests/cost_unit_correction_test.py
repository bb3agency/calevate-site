"""Rows metered under the wrong cost-UNIT divisor, restated by APPENDING (D-411).

`engine/bolna.py` now refuses a currency whose unit nothing tells it — so no NEW row can
be metered at a hundredth of cost. Refusing does not reach backwards: rows written before
the fix are still in the ledger, still wrong, and `usage_events` is INSERT-only (hard rule
4). The remedy is a compensating row per call, and this file is its contract.

What the tests below hold, in the order a reviewer would ask them:

0. that the ROW carries what a restatement needs — `pipeline._meter` writes the vendor's
   own figure, the capture-time fx rate and whether the currency was STATED or assumed,
   and it writes them for a zero-cost call too;
1. the arithmetic (`restatement_delta`) — including that it refuses a divisor that would
   make a division undefined, because a money function that returns nonsense on bad input
   is worse than one that stops;
2. that the correction MOVES the margin by exactly the delta, and moves nothing else —
   the original rows are untouched, the client's minutes are untouched;
3. that it is IDEMPOTENT, because the tool is an operator's and gets re-run, and that its
   DEFAULT mode — every tenant, not one — reaches the fleet a unit error is spread over;
4. that it cannot reach another tenant's rows, which hard rule 1 requires of anything
   that touches a tenant-scoped table.

Run: uv run pytest -q tests/cost_unit_correction_test.py
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.cost_unit import (
    COST_UNIT_CORRECTION_META_KIND,
    correction_ref,
    mis_metered_calls,
    record_cost_unit_correction,
    restatement_delta,
)
from apps.api.billing.service import margin_for_tenant, usage_summary
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.pipeline import _meter
from calevate_shared.engine import CostBreakdown, ExecutionSnapshot
from scripts import correct_cost_unit
from sqlalchemy import text
from tests.conftest import accept_agreements

#: 120 seconds of telephony at ₹0.0125/s = ₹1.50, plus a ₹0.30 platform leg. Under the
#: divisor bug these are one hundredth of what the vendor charged.
_SECONDS = Decimal(120)
_TELEPHONY_UNIT_COST = Decimal("0.0125")
_PLATFORM_LEG = Decimal("0.3000")
_METERED = _SECONDS * _TELEPHONY_UNIT_COST + _PLATFORM_LEG  # ₹1.80


async def _published_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with an agent AND its `engine_agent_routes` row.

    Both, because production writes both in one transaction (`publish_agent`) and because
    the route is how `scripts/correct_cost_unit` finds the tenant at all — a fixture with
    only one of them would be testing a state the platform cannot reach.
    """
    created = await admin_service.create_organization(
        name="Divisor Dental",
        slug=f"cu-{uuid.uuid4().hex[:8]}",
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
    ref = f"fakeagent_cu_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', engine_agent_ref = :r WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _metered_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, source_currency: str
) -> uuid.UUID:
    """One completed call with the rows `pipeline._meter` writes, meta and all."""
    call_id = uuid7()
    meta = json.dumps(
        {
            "engine": "bolna",
            "source_currency": source_currency,
            "source_amount": "1.80",
            "fx_rate": "1",
            "tts_tier": "value",
            "tts_tier_source": "agent_config",
        }
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
        for unit_type, qty, cost in (
            ("telephony_s", _SECONDS, _TELEPHONY_UNIT_COST),
            # qty 0 on purpose: `_ROW_COST_SQL` carries a zero-qty row's WHOLE leg cost
            # (D-370), and a restatement computed against a second spelling of that rule
            # would silently drop this leg.
            ("platform_min", Decimal(0), _PLATFORM_LEG),
        ):
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, :u, :q, "
                    ":p, now(), CAST(:m AS jsonb), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "u": unit_type,
                    "q": qty,
                    "p": cost,
                    "m": meta,
                },
            )
    return call_id


async def _our_cost(tenant_id: uuid.UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id)
    return Decimal(str(margin["cost_inr"]))


async def _rows(tenant_id: uuid.UUID) -> list[dict[str, object]]:
    async with tenant_session(tenant_id) as session:
        result = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, meta FROM usage_events "
                    "WHERE tenant_id = :t ORDER BY created_at, unit_type"
                ),
                {"t": tenant_id},
            )
        ).mappings()
        return [dict(row) for row in result]


# --- 0. what the row records, because a restatement can only use what is on it ---
#
# `_metered_call` above hand-writes the meta a real call carries, so it cannot notice the
# day `_meter` stops writing one of those keys. These two go through `_meter` itself.


async def _real_call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, vendor_figure: str, stated: bool
) -> uuid.UUID:
    """One call metered by the REAL `pipeline._meter`, from a `CostBreakdown` an adapter
    could have produced."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500002', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    total = Decimal(vendor_figure)
    await _meter(
        tenant_id,
        call_id,
        ExecutionSnapshot(
            engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
            status="completed",
            raw_status="completed",
            terminal=True,
            billable_ready=True,
            duration_s=120,
            cost=CostBreakdown(
                total_inr=total,
                platform_inr=total,
                network_inr=Decimal("0.0000"),
                llm_inr=None,
                tts_inr=None,
                stt_inr=None,
                source_currency="USD",
                currency_stated=stated,
                source_amount=total,
                fx_rate=Decimal("88.00"),
            ),
            engine="fake",
        ),
    )
    return call_id


async def test_a_zero_cost_call_still_records_the_vendor_figure_it_was_given() -> None:
    """`source_amount` is written on `is not None`, never on truthiness.

    A vendor figure of ZERO is an answer — that execution was not charged for — and
    writing `null` for it makes the row indistinguishable from one captured before the key
    existed, which is a row no restatement can safely scale. The falsy test was invisible
    on every priced call and wrong on exactly the cheap ones.
    """
    tenant_id, agent_id = await _published_tenant()
    await _real_call(tenant_id, agent_id, vendor_figure="0", stated=True)

    metas = [row["meta"] for row in await _rows(tenant_id)]
    assert metas, "the call metered something"
    for meta in metas:
        assert isinstance(meta, dict)
        assert meta["source_amount"] == "0", (
            "a zero vendor figure is recorded as zero, not as 'we did not record one'"
        )
        assert meta["fx_rate"] == "88.00"
        assert meta["source_currency"] == "USD"


async def test_every_row_says_whether_the_payload_named_the_currency() -> None:
    """`currency_stated` is not re-derivable from a row: `source_currency` reads `USD`
    whether the vendor said so or we assumed it, and which one it was is what gate 7
    scores and what `runbooks/vendor-cost-unit.md` triages on."""
    tenant_id, agent_id = await _published_tenant()
    stated_call = await _real_call(tenant_id, agent_id, vendor_figure="1.50", stated=True)
    assumed_call = await _real_call(tenant_id, agent_id, vendor_figure="1.50", stated=False)

    by_call: dict[uuid.UUID, set[object]] = {stated_call: set(), assumed_call: set()}
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT call_id, meta ->> 'currency_stated' FROM usage_events "
                    "WHERE tenant_id = :t AND call_id IN (:s, :a)"
                ),
                {"t": tenant_id, "s": stated_call, "a": assumed_call},
            )
        ).all()
    for call_id, flag in rows:
        by_call[uuid.UUID(str(call_id))].add(flag)

    assert by_call[stated_call] == {"true"}
    assert by_call[assumed_call] == {"false"}, (
        "a house assumption must not read as the vendor's own word"
    )


# --- 1. the arithmetic --------------------------------------------------------


def test_a_hundredfold_under_read_is_restated_a_hundredfold_up() -> None:
    """₹1.80 metered when the vendor charged ₹180: the delta is the ₹178.20 missing, not
    the ₹180 total — the original row keeps its money and the correction adds the rest."""
    assert restatement_delta(Decimal("1.80"), from_divisor=Decimal(100), to_divisor=Decimal(1)) == (
        Decimal("178.2000")
    )


def test_the_other_direction_is_a_negative_delta() -> None:
    """Major read as minor. Our recorded cost basis was inflated and comes back down."""
    assert restatement_delta(Decimal(180), from_divisor=Decimal(1), to_divisor=Decimal(100)) == (
        Decimal("-178.2000")
    )


def test_a_divisor_that_cannot_be_one_is_refused() -> None:
    """A zero or negative divisor is not a number this can be sensible about, and money
    arithmetic that quietly returns something on nonsense input is how a wrong figure
    reaches a ledger nobody can edit."""
    with pytest.raises(ValueError, match="positive"):
        restatement_delta(Decimal(1), from_divisor=Decimal(100), to_divisor=Decimal(0))
    with pytest.raises(ValueError, match="positive"):
        restatement_delta(Decimal(1), from_divisor=Decimal(-1), to_divisor=Decimal(1))


def test_a_non_terminating_ratio_lands_on_a_whole_paisa() -> None:
    """100/3 does not terminate, and `unit_cost_paid` is NUMERIC(12,4) — a delta the ledger
    cannot store is a delta it cannot honour. The quantization is what makes the returned
    figure a column value rather than a 28-digit tail, so this pins the value rather than
    the order of the arithmetic (which, measured, agrees either way at these magnitudes)."""
    delta = restatement_delta(Decimal(3), from_divisor=Decimal(100), to_divisor=Decimal(3))
    assert delta == Decimal("97.0000")
    assert delta.as_tuple().exponent == -4


# --- 2. what a correction moves ----------------------------------------------


async def test_the_correction_moves_our_cost_by_the_delta_and_nothing_else() -> None:
    tenant_id, agent_id = await _published_tenant()
    call_id = await _metered_call(tenant_id, agent_id, source_currency="INR")

    assert await _our_cost(tenant_id) == _METERED

    async with tenant_session(tenant_id) as session:
        before = await usage_summary(session, tenant_id=tenant_id)
        candidates = await mis_metered_calls(session, source_currency="INR")
        assert [c.call_id for c in candidates] == [call_id]
        assert candidates[0].metered_inr == _METERED
        delta = await record_cost_unit_correction(
            session,
            tenant_id=tenant_id,
            call=candidates[0],
            source_currency="INR",
            from_divisor=Decimal(100),
            to_divisor=Decimal(1),
        )

    assert delta == Decimal("178.2000")
    assert await _our_cost(tenant_id) == _METERED + delta, "the margin reprices by itself"

    async with tenant_session(tenant_id) as session:
        after = await usage_summary(session, tenant_id=tenant_id)
    assert after["minutes_used"] == before["minutes_used"], (
        "a supplier-cost restatement must not move what the client is billed — the "
        "invoice is priced off MINUTES at the plan's rate (D-373's lesson)"
    )


async def test_the_original_rows_are_untouched_and_the_fix_is_an_append() -> None:
    """Hard rule 4 in the one place it costs something. The wrong rows stay wrong; they
    are the evidence of what we believed when we metered them."""
    tenant_id, agent_id = await _published_tenant()
    await _metered_call(tenant_id, agent_id, source_currency="INR")
    before = await _rows(tenant_id)

    await correct_cost_unit.run(
        currency="INR",
        from_divisor=Decimal(100),
        to_divisor=Decimal(1),
        apply=True,
        only_tenant=tenant_id,
    )

    after = await _rows(tenant_id)
    assert len(after) == len(before) + 1
    assert after[: len(before)] == before, "not one original row moved"

    correction = after[-1]
    assert correction["unit_type"] == "other", (
        "'other' is outside `ux_usage_events_tenant_call_unit`'s five metered types, "
        "which is what lets a correction be appended at all"
    )
    assert correction["qty"] == Decimal(1)
    assert correction["unit_cost_paid"] == Decimal("178.2000")
    meta = correction["meta"]
    assert isinstance(meta, dict)
    assert meta["kind"] == COST_UNIT_CORRECTION_META_KIND
    assert meta["tts_tier"] == "value", (
        "carried forward so the money lands on the rung the call ran on rather than in "
        "`tier_usage.cost_unattributed_inr`"
    )
    assert "source_currency" not in meta, (
        "a correction that carried this key would be read back as more mis-metered cost "
        "on the next run and compound itself"
    )


async def test_a_dry_run_writes_nothing() -> None:
    """The default. An operator's first command must not be able to change the ledger."""
    tenant_id, agent_id = await _published_tenant()
    await _metered_call(tenant_id, agent_id, source_currency="INR")

    counted = await correct_cost_unit.run(
        currency="INR",
        from_divisor=Decimal(100),
        to_divisor=Decimal(1),
        apply=False,
        only_tenant=tenant_id,
    )

    assert counted == 1, "it still reports what it would do"
    assert len(await _rows(tenant_id)) == 2, "and it did none of it"
    assert await _our_cost(tenant_id) == _METERED


async def test_rows_metered_in_another_currency_are_left_alone() -> None:
    """The population is `meta.source_currency`, not "every row". A USD-metered call was
    priced by a divisor the vendor's OAS does support and must not be restated."""
    tenant_id, agent_id = await _published_tenant()
    await _metered_call(tenant_id, agent_id, source_currency="USD")

    counted = await correct_cost_unit.run(
        currency="INR",
        from_divisor=Decimal(100),
        to_divisor=Decimal(1),
        apply=True,
        only_tenant=tenant_id,
    )

    assert counted == 0
    assert await _our_cost(tenant_id) == _METERED


# --- 3. idempotency -----------------------------------------------------------


async def test_running_it_twice_corrects_once() -> None:
    """The tool is an operator's and will be re-run — after an interruption, or by a
    second person who did not know the first had. A ledger that cannot be edited makes a
    double correction as permanent as the error it was meant to fix."""
    tenant_id, agent_id = await _published_tenant()
    await _metered_call(tenant_id, agent_id, source_currency="INR")

    first = await correct_cost_unit.run(
        currency="INR",
        from_divisor=Decimal(100),
        to_divisor=Decimal(1),
        apply=True,
        only_tenant=tenant_id,
    )
    after_first = await _our_cost(tenant_id)
    second = await correct_cost_unit.run(
        currency="INR",
        from_divisor=Decimal(100),
        to_divisor=Decimal(1),
        apply=True,
        only_tenant=tenant_id,
    )

    assert (first, second) == (1, 0)
    assert await _our_cost(tenant_id) == after_first
    assert len(await _rows(tenant_id)) == 3, "one correction row, not two"


async def test_a_flip_that_moves_nothing_writes_no_row() -> None:
    """A ₹0 correction is not evidence of anything and would only add noise to a ledger
    a human reads."""
    tenant_id, agent_id = await _published_tenant()
    await _metered_call(tenant_id, agent_id, source_currency="INR")

    async with tenant_session(tenant_id) as session:
        candidates = await mis_metered_calls(session, source_currency="INR")
        delta = await record_cost_unit_correction(
            session,
            tenant_id=tenant_id,
            call=candidates[0],
            source_currency="INR",
            from_divisor=Decimal(100),
            to_divisor=Decimal(100),
        )

    assert delta is None
    assert len(await _rows(tenant_id)) == 2


async def test_the_default_run_walks_every_tenant_the_bridge_names() -> None:
    """`--tenant` is the exception; NO `--tenant` is what an operator actually types.

    A cost-unit error is a property of the adapter, so it is fleet-wide by construction —
    the mode that corrects one tenant is for a rehearsal, and the mode that corrects all
    of them is the repair. `_tenants()` is the enumeration behind it, and it reads the
    same globally-readable bridge `retention._due_tenants` reads: no admin role, no RLS
    exemption. Untested, it is a walk that could quietly reach one tenant and report a
    clean fleet.
    """
    first_id, first_agent = await _published_tenant()
    second_id, second_agent = await _published_tenant()
    await _metered_call(first_id, first_agent, source_currency="INR")
    await _metered_call(second_id, second_agent, source_currency="INR")

    walked = await correct_cost_unit._tenants()
    assert {first_id, second_id} <= set(walked)
    assert walked == sorted(walked), (
        "a stable order, so 'which tenants did an interrupted run reach?' has an answer"
    )

    corrected = await correct_cost_unit.run(
        currency="INR",
        from_divisor=Decimal(100),
        to_divisor=Decimal(1),
        apply=True,
        only_tenant=None,
    )

    assert corrected >= 2
    assert await _our_cost(first_id) == _METERED + Decimal("178.2000")
    assert await _our_cost(second_id) == _METERED + Decimal("178.2000"), (
        "the second tenant is corrected by the same run, not left for a second command"
    )


def test_the_reference_names_the_flip_it_applies() -> None:
    """It is the idempotency key, so it has to be derived from the change and not minted
    per run — and a LATER, different flip must derive a different one so it gets its own
    correction rather than colliding with the first."""
    first = correction_ref(source_currency="INR", from_divisor=Decimal(100), to_divisor=Decimal(1))
    second = correction_ref(source_currency="INR", from_divisor=Decimal(1), to_divisor=Decimal(100))
    assert first != second
    assert "INR" in first


def test_the_cli_refuses_a_flip_that_is_not_one(capsys: pytest.CaptureFixture[str]) -> None:
    """An operator who typed the same divisor twice asked for something they did not mean.
    A clean "0 calls corrected" would read as "there was nothing wrong"."""
    code = correct_cost_unit.main(["--currency", "INR", "--from", "100", "--to", "100"])
    assert code == 2
    assert "nothing to restate" in capsys.readouterr().out


def test_the_cli_refuses_a_divisor_that_is_not_a_positive_number() -> None:
    parser = correct_cost_unit.build_parser()
    for bad in ("0", "-1", "paise"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--currency", "INR", "--from", bad, "--to", "1"])


# --- 4. tenancy ---------------------------------------------------------------


async def test_one_tenants_correction_cannot_reach_another_tenants_rows() -> None:
    """Hard rule 1's cross-tenant zero-rows check for this path. `mis_metered_calls` names
    no `tenant_id` — it relies on the session's RLS policy — so the thing to prove is that
    the policy really is what scopes it, and that a fleet walk corrects each tenant's rows
    exactly once inside that tenant's own session.
    """
    first_id, first_agent = await _published_tenant()
    second_id, second_agent = await _published_tenant()
    await _metered_call(first_id, first_agent, source_currency="INR")
    await _metered_call(second_id, second_agent, source_currency="INR")

    async with tenant_session(first_id) as session:
        seen = await mis_metered_calls(session, source_currency="INR")
    assert len(seen) == 1, "a tenant session sees its own call and no other tenant's"

    # The correction run scoped to ONE tenant must leave the other exactly where it was.
    await correct_cost_unit.run(
        currency="INR",
        from_divisor=Decimal(100),
        to_divisor=Decimal(1),
        apply=True,
        only_tenant=first_id,
    )
    assert await _our_cost(first_id) == _METERED + Decimal("178.2000")
    assert await _our_cost(second_id) == _METERED, "the other tenant did not move"


async def test_an_untenanted_session_sees_none_of_it() -> None:
    """The fail-closed property the whole design leans on: this script's fleet walk reads
    the tenant LIST from the global bridge and everything else from inside
    `tenant_session`, because `usage_events` yields zero rows without the GUC."""
    tenant_id, agent_id = await _published_tenant()
    await _metered_call(tenant_id, agent_id, source_currency="INR")

    async with untenanted_session() as session:
        visible = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert visible == 0
