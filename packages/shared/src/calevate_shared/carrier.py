"""Telephony names shared by the deployables: who holds a number, and the carriers of old rows.

The platform carries no telephony of its own: the engine places and answers every call on
its own numbers (D-678). What remains here is the vocabulary rows and logs still use.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal, get_args

#: `calls.carrier` values, from which its CHECK constraint is built. Historical values;
#: dropped with the D-763 drop migration.
CarrierName = Literal["vobiz", "plivo"]

CARRIERS: Final[tuple[CarrierName, ...]] = get_args(CarrierName)

#: Who holds a recorded calling number (`phone_numbers.provider`): an engine that rents and
#: attaches numbers on its own account. `vobiz` and `plivo` are historical values; dropped
#: with the D-763 drop migration.
NumberProvider = Literal["vobiz", "plivo", "thinnest"]

#: The providers an operator may record a NEW number under: a client's own Plivo connection
#: (Model B) or a number held on the engine.
RecordableNumberProvider = Literal["plivo", "thinnest"]

#: The provider a number must carry to be presented on an engine that dials on its own
#: account. ThinnestAI calls go out only on ThinnestAI numbers (founder decision, D-678).
ENGINE_NUMBER_PROVIDER: Final[Mapping[str, NumberProvider]] = {"thinnest": "thinnest"}

#: The query parameter that carried a shared callback secret on the URLs registered with a
#: carrier (D-673). Kept so the log redactor (`core/logging._URL_SECRET_PARAMS`) still masks
#: it in any URL that arrives carrying one.
CALLBACK_SECRET_PARAM: Final = "callback_key"


__all__ = [
    "CALLBACK_SECRET_PARAM",
    "CARRIERS",
    "ENGINE_NUMBER_PROVIDER",
    "CarrierName",
    "NumberProvider",
    "RecordableNumberProvider",
]
