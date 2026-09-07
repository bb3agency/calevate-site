"""THE OPS CONSOLE'S CARD WRITE: preview every margin, refuse a card that would lose money.

`ops/config_routes._record_card` runs when an operator saves `self_serve_inr_per_min`. Since
D-547 that write dates the WHOLE credit-pack card (`billing/list_rates.record_card`) rather
than one number, and before it writes anything it does two things:

1. **Previews all twelve margins**, one log line each, thin rows at `warning`. The operator
   who pressed Save gets the number beside the act — the whole Sarvam column is deliberately
   under the 20% target (`tests/cost_floor_test.py` says by how much), so "thin" is the
   normal state and the console must say so rather than imply a problem.
2. **Refuses a card that breaks a cost floor or invariant 6**, with a problem+json an
   operator can act on, and writes NOTHING.

⚠ **WHY A SECOND GATE AT ALL, WHEN THE CARD IS A CODE CONSTANT CI ALREADY SCORES.** Because
the two gates fail differently: CI's `credit_packs_test` refuses a bad card at review time,
and this refuses it at WRITE time — the moment it would enter append-only history and start
pricing lots that can never be re-priced. `admin/routes.py` applies exactly this posture to
a committed bundle's rates for the same reason. A refusal here means the first gate was
bypassed, which is precisely when a second one earns its keep.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.credit_packs import PACK_CATALOGUE, CreditPack
from apps.api.billing.list_rates import SELF_SERVE_PER_MIN
from apps.api.core.errors import ProblemError
from apps.api.db.session import untenanted_session
from apps.api.ops import config_routes
from apps.api.ops.config_service import WriteResult
from sqlalchemy import text
from tests.list_rate_card_test import _purge


@pytest.fixture(autouse=True)
async def _isolated_history() -> AsyncIterator[None]:
    """`platform_list_rates` is a GLOBAL append-only table, and the happy path below writes
    a real card into it. Left behind, it would change what every other suite's
    `self_serve_rate_at` and `card_at` resolve. The owner-role purge lives in
    `tests/list_rate_card_test.py` and is imported rather than copied — one way per
    problem, and a second copy would be the one that forgets to restore a trigger mode.
    """
    await _purge()
    yield
    await _purge()


async def _admin() -> UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


def _save() -> WriteResult:
    return WriteResult(key=SELF_SERVE_PER_MIN, old=None, new="5.00", version=1, revision=1)


async def _card_rows() -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM platform_list_rates WHERE rate_key LIKE 'pack:%'")
                )
            ).scalar_one()
        )


async def test_a_card_that_sells_below_cost_is_refused_and_writes_nothing() -> None:
    """The veto. A ₹3.00 Sarvam rate is under the ₹4.1211 floor; the operator gets a
    problem+json naming the pack and the append-only history is untouched — which matters
    more than the refusal itself, because a card recorded in error cannot be edited out."""
    admin = await _admin()
    before = await _card_rows()
    broken = (
        CreditPack(
            pack_id="starter",
            amount_inr=Decimal("2000"),
            sarvam_inr_per_min=Decimal("3.00"),
            cartesia_inr_per_min=Decimal("8.00"),
        ),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config_routes, "PACK_CATALOGUE", broken)
        async with untenanted_session() as session:
            with pytest.raises(ProblemError) as raised:
                await config_routes._record_card(
                    session, _save(), actor_id=admin, reason="a bad card"
                )
    assert raised.value.code == "rate_card_below_floor"
    assert "starter" in (raised.value.detail or "")
    assert "below cost" in (raised.value.detail or "")
    assert await _card_rows() == before


async def test_a_card_that_breaks_invariant_6_is_refused() -> None:
    """A bigger pack that buys a dearer minute is arbitrageable by buying the smaller one
    twice, and a Cartesia rate under its Sarvam rate sells the dearer voice cheaper. Both
    are refusals, not warnings: the card is wrong rather than thin."""
    admin = await _admin()
    inverted = (
        CreditPack(
            pack_id="starter",
            amount_inr=Decimal("2000"),
            sarvam_inr_per_min=Decimal("5.00"),
            cartesia_inr_per_min=Decimal("8.00"),
        ),
        CreditPack(
            pack_id="max",
            amount_inr=Decimal("50000"),
            sarvam_inr_per_min=Decimal("5.50"),
            cartesia_inr_per_min=Decimal("8.50"),
        ),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config_routes, "PACK_CATALOGUE", inverted)
        async with untenanted_session() as session:
            with pytest.raises(ProblemError) as raised:
                await config_routes._record_card(
                    session, _save(), actor_id=admin, reason="an inverted ladder"
                )
    assert "invariant 6" in (raised.value.detail or "")


async def test_the_approved_card_is_written_and_every_margin_is_previewed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The happy path, and the preview that goes with it: twelve log lines, one per cell,
    each carrying the rate, the floor it was judged against and whether it is thin. The
    Sarvam rows are thin by design, so they are the ones logged at WARNING — an operator
    reading only warnings still sees the whole column that is under target."""
    admin = await _admin()
    with caplog.at_level(logging.INFO, logger=config_routes.log.name):
        async with untenanted_session() as session:
            await config_routes._record_card(
                session, _save(), actor_id=admin, reason="the founder's card"
            )
    previews = [r for r in caplog.records if r.msg == "rate_card_margin_preview"]
    assert len(previews) == len(PACK_CATALOGUE) * 2
    thin = [r for r in previews if r.levelno == logging.WARNING]
    assert {r.pack_id for r in thin} == {pack.pack_id for pack in PACK_CATALOGUE}
    assert {r.voice_tier for r in thin} == {"sarvam"}
    # Money in a log line is a STRING (hard rule 7): a float here is a float somebody
    # quotes back.
    assert all(isinstance(r.inr_per_min, str) for r in previews)
    assert all(isinstance(r.cost_floor_inr_per_min, str) for r in previews)


async def test_a_write_of_another_key_records_no_card() -> None:
    """Only the self-serve price write dates a card. Another setting's Save is not a
    pricing event and must not put a row into an append-only history."""
    admin = await _admin()
    before = await _card_rows()
    async with untenanted_session() as session:
        await config_routes._record_card(
            session,
            WriteResult(key="db_pool_size", old=None, new="12", version=2, revision=1),
            actor_id=admin,
            reason="not a price",
        )
    assert await _card_rows() == before
