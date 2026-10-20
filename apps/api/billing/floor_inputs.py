"""The moving inputs of a ThinnestAI cost floor, resolved once per caller (D-840).

`rates.cost_floor_inr_per_min` is pure and sync; on ThinnestAI it is struck at a
`rates.FloorInputs` this module reads: the fleet's measured speaking rate
(`tts_speaking_rate.fleet_speaking_rate`, the assumed top of TRD §10.1's band until enough calls
are measured), the USD->INR rate the ladder gives now (`core/fx.usd_inr_rate_now`), and the
attested wallet top-up fee and gateway fee (`cost_attestations`). One read per screen or per
refusal, so every cell judged in it shares one basis.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.cost_attestations import (
    GATEWAY_FEE_SUBJECT,
    WALLET_TOPUP_FEE_SUBJECTS,
    attested_costs,
)
from apps.api.billing.rates import FloorInputs
from apps.api.billing.tts_speaking_rate import fleet_speaking_rate
from apps.api.core.fx import UsdInrRate, usd_inr_rate_now


async def floor_inputs(
    session: AsyncSession, *, engine: str, at: datetime, fx: UsdInrRate | None = None
) -> FloorInputs:
    """The floor inputs in force at `at` for `engine`'s wallet. Any session: none of the
    tables read carries a tenant. `fx` is the rate a caller already resolved for the rest of
    its response, so one screen converts at one rate."""
    costs = await attested_costs(session, at=at)
    subject = WALLET_TOPUP_FEE_SUBJECTS.get(engine)
    wallet = costs.get(subject) if subject is not None else None
    gateway = costs.get(GATEWAY_FEE_SUBJECT)
    fx = fx or usd_inr_rate_now()
    return FloorInputs(
        speaking_rate=(await fleet_speaking_rate(session)).basis(),
        usd_inr=fx.rate,
        usd_inr_source=fx.source,
        wallet_fee=Decimal(0) if subject is None else (None if wallet is None else wallet.value),
        gateway_fee=None if gateway is None else gateway.value,
    )


__all__ = ["floor_inputs"]
