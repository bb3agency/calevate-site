"""Vobiz — a live transfer by redirecting the caller's leg to a sealed `<Dial>` document.

The mechanism is read from Vobiz's own documentation (`vobiz-findings/mirror/pages/`):

1. `POST /Account/{auth_id}/Call/{call_uuid}/` with `legs=aleg` and `aleg_url` interrupts
   the live flow and runs the XML at that URL immediately (`call/transfer-call.md:9-110`);
2. that URL is `calevate_shared.carrier.transfer_path("vobiz", token)`, served by
   voice-runtime, which answers a `<Dial callerId=… timeout=… timeLimit=…>` document
   (`xml/dial.md:12-14,44-60`). voice-runtime may not read the database (hard rule 3), so the
   destination travels in the token, sealed by `calevate_shared/carrier_token.py`.

WHY IT IS OFF BY DEFAULT (`Settings.carrier_transfer_enabled`). The founder's pattern is
whisper, then ACCEPT, then bridge (`base.py`). Vobiz plays a private message to the called
party (`confirmSound`) but says of the accept step: "`confirmKey` … enforcement as an
acceptance gate is currently unverified, so do not depend on a keypress to control whether
the B-leg connects" (`xml/dial.md:55-57`). So nothing here depends on a keypress, and the
contract counts as verified only when an operator switches it on.

AND IT DOES NOT SETTLE SYNCHRONOUSLY. The ending of the second leg arrives later, on the
`<Dial>` callbacks (`xml/dial.md:77-104`), and the redirect takes the caller off the
agent's stream the moment it lands — so the agent never hears an outcome. The transfer
registry therefore selects no provider for it (`outcome_arrives_late`), and the client's
handover screen says the platform cannot transfer, until a hand-off mode exists that tells
the caller first.
"""

from __future__ import annotations

from typing import Final

from calevate_shared.carrier import transfer_path
from calevate_shared.carrier_token import seal, usable_secret

from apps.api.agents.transfer_providers.base import (
    TransferContractUnverifiedError,
    TransferRefusedError,
    TransferRequest,
    TransferStarted,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.engine.carrier import CarrierClient, get_carrier

log = get_logger(__name__)

#: The `carrier_token` purpose the voice-runtime transfer route opens.
TRANSFER_TOKEN_PURPOSE: Final = "transfer"
#: How long the redirect URL stays valid. Vobiz fetches it the moment the transfer lands,
#: so a short window costs nothing and bounds a leaked URL.
TRANSFER_TOKEN_TTL_S: Final = 120
#: Our ceiling on the bridged leg, which the carrier bills for as long as it is up. Below
#: Vobiz's own `timeLimit` default of 14400 s (`xml/dial.md:51`).
TRANSFER_TIME_LIMIT_S: Final = 3_600

_NOT_ENABLED = (
    "Vobiz transfers are switched off (CARRIER_TRANSFER_ENABLED). Vobiz itself calls the "
    "accept-by-keypress step unverified (xml/dial.md:55-57), so a transfer is enabled by an "
    "operator after a live test, not by default."
)


class VobizTransfers:
    """`CallTransferProvider` over the Vobiz carrier seam."""

    def __init__(self, *, carrier: CarrierClient | None = None) -> None:
        self._carrier = carrier

    @property
    def name(self) -> str:
        return "vobiz"

    @property
    def contract_verified(self) -> bool:
        return get_settings().carrier_transfer_enabled

    @property
    def settles_synchronously(self) -> bool:
        return False

    async def start_transfer(self, request: TransferRequest) -> TransferStarted:
        if not self.contract_verified:
            raise TransferContractUnverifiedError(_NOT_ENABLED)
        settings = get_settings()
        secret = usable_secret(settings.carrier_claim_secret)
        base_url = (settings.webhook_base_url or "").rstrip("/")
        if secret is None or not base_url:
            raise TransferRefusedError(
                "a transfer needs CARRIER_CLAIM_SECRET and WEBHOOK_BASE_URL to build its URL"
            )
        if not request.call_ref or ":" in request.call_ref:
            # Our own `pipecat:<tenant>:<call>` handle, not the carrier's call id: the
            # carrier cannot address a call by a name it never issued.
            raise TransferRefusedError("the call has no carrier call id to transfer")
        token = seal(
            secret,
            TRANSFER_TOKEN_PURPOSE,
            {
                "to": request.to_e164,
                "caller_id": request.present_as,
                "timeout_s": request.ring_timeout_s,
                "time_limit_s": TRANSFER_TIME_LIMIT_S,
                "call": request.call_ref,
            },
            ttl_s=TRANSFER_TOKEN_TTL_S,
        )
        carrier = self._carrier if self._carrier is not None else get_carrier("vobiz")
        try:
            await carrier.transfer(
                request.call_ref, redirect_url=base_url + transfer_path("vobiz", token)
            )
        except ProblemError as exc:
            log.warning("carrier_transfer_refused", extra={"code": exc.code})
            raise TransferRefusedError(f"the carrier refused the transfer ({exc.code})") from exc
        return TransferStarted(
            provider_ref=f"vobiz:{request.call_ref}",
            outcome=None,
            raw_status="transfer_requested",
        )


__all__ = [
    "TRANSFER_TIME_LIMIT_S",
    "TRANSFER_TOKEN_PURPOSE",
    "TRANSFER_TOKEN_TTL_S",
    "VobizTransfers",
]
