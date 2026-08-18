"""The spend cap has to TELL somebody, not just refuse (R-2, OPERATIONS §4).

`docs/OPERATIONS.md` §4 lists "cap approaching (80%) / breached" as an alert trigger and
`billing/caps.py` contained no `alert(` at all. What that meant in practice: a tenant's
usage crossed the ceiling, `compliance.check_dispatch` began refusing every dial with
`rule="spend_cap"`, the dispatcher wrote `record_compliance_block(rule="spend_cap")` —
a log line with no consumer — and the client's campaign stopped dialling with the console
still reading "running". Nobody was told. The asymmetry that makes it an omission rather
than a decision: D-140 built exactly this 80%/100% alarm for the platform's OWN AI spend.

Every test here asserts the ALARM FIRES AT THE THRESHOLD, not that a function exists —
the two that matter drive it through the real meter (`pipeline._meter`) on a real tenant,
so a wiring that computes the fullness and never announces it fails here.

WHY `caplog` AND NOT THE TRANSPORT. `alert()` writes its structured ERROR record FIRST
and unconditionally (D-49); delivery is best-effort on top, deduplicated per fingerprint
for 15 minutes and rate-limited by a shared token bucket. Asserting on delivery would
therefore make these tests depend on what a concurrent suite alerted about in the same
window. The log record is the durable half and the one the contract is written on.

CONCURRENCY: every test mints its own tenant and its own far-future month where a month
is needed, and touches no global row, so this file runs beside the other suites on the
shared Postgres.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.billing import caps
from apps.api.billing.caps import CAP_WARN_AT, announce_cap_headroom, cap_fullness
from apps.api.billing.service import current_billing_month
from tests.spend_caps_test import THIS_MONTH, _bill, _gate, _plan, _tenant


@pytest.fixture(autouse=True)
def _gate_reaches_the_spend_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two pins `tests/spend_caps_test.py` explains, for the same reason: calling
    hours is checked AFTER the spend cap (so a run at 22:00 IST would fail every "can
    still dial" assertion for a reason that has nothing to do with caps) and the big red
    switch is global state a concurrent suite can flip. Neither weakens anything asserted
    here — the alarm codes come out of the meter, which no stub in this fixture touches."""
    from apps.api.core.loadshed import PlatformStatus

    async def _running(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=False)

    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _running)
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)


def _cap_alerts(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The cap alarm codes fired during the block, in order.

    Codes rather than messages: the message is prose an operator edits and the code is
    the contract (the same discipline `tests/ai_quota_test.py` states). Filtered to the
    `tenant_spend_` prefix because the metering path this drives can legitimately raise
    other CORE_LOGIC alerts, and a test that asserted on the whole stream would be
    measuring its neighbours.
    """
    return [
        str(record.__dict__.get("code"))
        for record in caplog.records
        if record.message == "alert"
        and str(record.__dict__.get("code")).startswith("tenant_spend_")
    ]


# --- the fullness fraction ----------------------------------------------------


def test_the_fullest_ceiling_decides_not_the_average() -> None:
    """`over_cap_sql` is a disjunction — EITHER ceiling closes the gate — so the fraction
    that decides when to speak is the LARGER of the two. A tenant at 95% of their minutes
    and 10% of their rupees is at 95% of being stopped; an average would say 52% and stay
    quiet through the whole approach."""
    full = cap_fullness(
        minutes_used=Decimal("95"),
        billed_inr=Decimal("100"),
        cap_min=Decimal("100"),
        cap_spend=Decimal("1000"),
    )
    assert full == Decimal("0.95")

    assert (
        cap_fullness(
            minutes_used=Decimal("5"),
            billed_inr=Decimal("0"),
            cap_min=None,
            cap_spend=None,
        )
        is None
    ), "no ceiling on either side is no constraint, never a full one"

    assert cap_fullness(
        minutes_used=Decimal("0"),
        billed_inr=Decimal("0"),
        cap_min=Decimal("0"),
        cap_spend=None,
    ) == Decimal("1"), "a ceiling of zero is a tenant that may not dial, not a ZeroDivisionError"


# --- the crossing -------------------------------------------------------------


def test_the_operator_is_told_at_80_percent_while_the_tenant_can_still_dial(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The warning that has a fifth of the allowance left to act in.

    Driven at the crossing itself, so the assertion is about the THRESHOLD and not about
    a function being reachable.
    """
    tenant_id = uuid.uuid4()

    with caplog.at_level("ERROR"):
        announce_cap_headroom(
            tenant_id=tenant_id,
            month="2098-03",
            before=Decimal("0.50"),
            after=CAP_WARN_AT - Decimal("0.01"),
        )
    assert _cap_alerts(caplog) == [], "an alarm fired with a fifth of the cap left"

    caplog.clear()
    with caplog.at_level("ERROR"):
        announce_cap_headroom(
            tenant_id=tenant_id,
            month="2098-03",
            before=CAP_WARN_AT - Decimal("0.01"),
            after=CAP_WARN_AT,
        )
    assert _cap_alerts(caplog) == ["tenant_spend_cap_approaching"], (
        "80% reached exactly must announce: `over_cap_sql` caps on `>=`, so the boundary "
        "is inside the alarm's range for the same reason it is inside the gate's"
    )

    # Already past it: NOT said again. Every later call in a capped month would otherwise
    # re-fire, which is how an alert channel gets muted by the people it is for.
    caplog.clear()
    with caplog.at_level("ERROR"):
        announce_cap_headroom(
            tenant_id=tenant_id, month="2098-03", before=CAP_WARN_AT, after=Decimal("0.9")
        )
    assert _cap_alerts(caplog) == [], "the warning repeated while nothing changed"


def test_crossing_the_cap_itself_says_the_campaign_has_stopped_and_says_it_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """100% is a different alarm from 80% because it is a different fact: dialling has
    already stopped. One event, one alarm — a call large enough to cross both lines says
    the more severe thing only, because two messages about one event is noise at the
    moment it most needs to be legible."""
    tenant_id = uuid.uuid4()

    with caplog.at_level("ERROR"):
        announce_cap_headroom(
            tenant_id=tenant_id, month="2098-04", before=Decimal("0.1"), after=Decimal("1.4")
        )
    assert _cap_alerts(caplog) == ["tenant_spend_capped"], "one event, the severe half of it"

    caplog.clear()
    with caplog.at_level("ERROR"):
        announce_cap_headroom(
            tenant_id=tenant_id, month="2098-04", before=Decimal("1.4"), after=Decimal("2.0")
        )
    assert _cap_alerts(caplog) == [], "the trip alert repeated after the cap was already on"


def test_a_tenant_arriving_under_a_new_ceiling_already_over_it_is_a_crossing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`before is None` means "nothing bound before" — an unlimited plan, a plan row
    minted mid-month. That reads as EMPTY rather than as silent, or a ceiling arriving
    below the spend it is meant to stop would announce nothing at all."""
    with caplog.at_level("ERROR"):
        announce_cap_headroom(
            tenant_id=uuid.uuid4(), month="2098-05", before=None, after=Decimal("1.2")
        )
    assert _cap_alerts(caplog) == ["tenant_spend_capped"]


def test_a_tenant_with_no_ceiling_is_never_announced(caplog: pytest.LogCaptureFixture) -> None:
    """`after is None` is an unlimited plan. There is no line to cross and no operator
    action available, so saying anything would be pure noise."""
    with caplog.at_level("ERROR"):
        announce_cap_headroom(
            tenant_id=uuid.uuid4(), month="2098-06", before=Decimal("0.9"), after=None
        )
    assert _cap_alerts(caplog) == []


# --- through the real meter ---------------------------------------------------


async def test_the_meter_announces_the_approach_and_then_the_stop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE ONE THAT PROVES THE WIRING. Real tenant, real plan, real `_meter` — the same
    call path the post-call pipeline takes — and the alarm has to come out of the write
    that crosses the line.

    A 10-minute ceiling with no allowance, so the minutes ARE the fullness: 8 minutes is
    exactly 80%, 11 is over. Nothing here stubs the announcer, so a fullness computed and
    never announced fails on the empty list.
    """
    tenant_id, agent_id, _ = await _tenant("capalarm")
    await _plan(tenant_id, cap_min=10, included_min=0)

    # 6 minutes: well inside, and silent.
    with caplog.at_level("ERROR"):
        await _bill(tenant_id, agent_id, seconds=360, spend="12.0000", ended=THIS_MONTH)
    assert _cap_alerts(caplog) == [], "an alarm fired at 60% of the ceiling"
    assert (await _gate(tenant_id, agent_id)).allowed, "and the tenant can still dial"

    # 8 minutes: the approach, announced ONCE, while dialling still works.
    caplog.clear()
    with caplog.at_level("ERROR"):
        await _bill(tenant_id, agent_id, seconds=120, spend="4.0000", ended=THIS_MONTH)
    assert _cap_alerts(caplog) == ["tenant_spend_cap_approaching"], (
        "the 80% warning must come out of the metering write itself — this is the alarm "
        "OPERATIONS §4 promised and nothing implemented"
    )
    assert (await _gate(tenant_id, agent_id)).allowed, "80% is a warning, not a stop"

    # 9 minutes: still between the lines, and silent — the alarm is on the CROSSING.
    caplog.clear()
    with caplog.at_level("ERROR"):
        await _bill(tenant_id, agent_id, seconds=60, spend="2.0000", ended=THIS_MONTH)
    assert _cap_alerts(caplog) == [], "the warning repeated on every call past 80%"

    # 11 minutes: the gate closes, and the operator is told THAT rather than left to
    # infer it from a client's phone call.
    caplog.clear()
    with caplog.at_level("ERROR"):
        await _bill(tenant_id, agent_id, seconds=120, spend="4.0000", ended=THIS_MONTH)
    assert _cap_alerts(caplog) == ["tenant_spend_capped"]
    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is False and decision.rule == "spend_cap", (
        "the alarm and the refusal must be the same event, or the alert is about "
        f"something that did not happen: {decision.rule}"
    )

    # And a call metered while already capped says nothing more.
    caplog.clear()
    with caplog.at_level("ERROR"):
        await _bill(tenant_id, agent_id, seconds=60, spend="2.0000", ended=THIS_MONTH)
    assert _cap_alerts(caplog) == [], "the stop alarm re-fired for a tenant already stopped"


async def test_a_tenant_with_no_ceiling_meters_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The common case, and the one an over-eager alarm would ruin: most tenants have no
    cap at all, and every completed call of theirs must pass without a word."""
    tenant_id, agent_id, _ = await _tenant("capalarmnone")
    await _plan(tenant_id, included_min=0)

    with caplog.at_level("ERROR"):
        await _bill(tenant_id, agent_id, seconds=600, spend="120.0000", ended=THIS_MONTH)
    assert _cap_alerts(caplog) == []


async def test_the_announcement_carries_ids_and_a_percentage_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 6, and the commercial half of hard rule 7's neighbourhood: the alert
    body an operator gets by email carries the tenant id, the billing month and how full
    the ceiling is. No phone number, no call id, no lead — and no rupee figure, because
    the ceiling is commercial and the fraction is what an operator acts on."""
    tenant_id = uuid.uuid4()
    with caplog.at_level("ERROR"):
        announce_cap_headroom(
            tenant_id=tenant_id,
            month=current_billing_month(),
            before=Decimal("0"),
            after=Decimal("1.0"),
        )
    record = next(r for r in caplog.records if r.message == "alert")
    assert record.__dict__["tenant_id"] == str(tenant_id)
    assert record.__dict__["month"] == current_billing_month()
    assert record.__dict__["used_pct"] == "100"
    assert "to_e164" not in record.__dict__ and "cap_spend" not in record.__dict__


def test_the_warning_threshold_is_the_platform_brakes(caplog: pytest.LogCaptureFixture) -> None:
    """One number, one reason, two places that must not drift: D-140 chose 80% for the
    platform's own AI brake on the argument that a fifth of the budget is the difference
    between a decision and an incident. The client-facing cap is the same argument, so it
    is the same constant rather than a second opinion about the same question."""
    from apps.api.billing.ai_quota import PLATFORM_BRAKE_WARN_AT

    assert caps.CAP_WARN_AT == PLATFORM_BRAKE_WARN_AT
