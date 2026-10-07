"""What an engine says it actually CHARGED for each call, in our vocabulary.

An engine priced by attested minute (`billing/engine_minutes.py`) is metered at call end
from the operator's rate. Where the vendor also publishes its own per-call charge, the
reconciliation sweep (`workers/engine_charges.py`) compares the two, so a rate that has
drifted from the invoice is seen within the hour rather than at month end.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class EngineCharge:
    """One call's charge. `charged_inr` None means the vendor charged nothing for it."""

    engine_call_id: str
    engine_agent_ref: str | None
    charged_inr: Decimal | None


@dataclass(frozen=True, slots=True)
class EngineChargeListing:
    charges: list[EngineCharge]
    #: False when the listing stopped short (a cursor that repeated, our page cap) or a row
    #: was in a currency we do not meter; the sweep then says so rather than reading a
    #: partial list as the whole day.
    complete: bool
    #: Rows skipped because they were not in INR.
    other_currency: int = 0


@runtime_checkable
class ReportsCharges(Protocol):
    """An adapter whose engine publishes what it charged per call."""

    async def list_call_charges(self, *, since: date) -> EngineChargeListing: ...


__all__ = ["EngineCharge", "EngineChargeListing", "ReportsCharges"]
