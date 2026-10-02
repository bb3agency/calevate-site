"""The Vobiz transfer provider: off by default, and what it sends when an operator turns it on."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from urllib.parse import unquote

import pytest
from apps.api.agents.transfer_providers import (
    PROVIDER_CONTRACT_UNVERIFIED,
    TransferContractUnverifiedError,
    TransferRefusedError,
    TransferRequest,
    available_transfer,
)
from apps.api.agents.transfer_providers.vobiz import (
    TRANSFER_TIME_LIMIT_S,
    TRANSFER_TOKEN_PURPOSE,
    VobizTransfers,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.pipecat import PipecatEngine
from apps.api.engine.plivo_carrier import PlivoCarrier
from calevate_shared.carrier_token import open_sealed

pytestmark = pytest.mark.anyio

SECRET = "s" * 40
HOOKS = "https://hooks.example.test"


@pytest.fixture
def transfer_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setenv("CARRIER", "vobiz")
    monkeypatch.setenv("CARRIER_CLAIM_SECRET", SECRET)
    monkeypatch.setenv("WEBHOOK_BASE_URL", HOOKS)
    monkeypatch.delenv("CARRIER_TRANSFER_ENABLED", raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARRIER_TRANSFER_ENABLED", "true")
    get_settings.cache_clear()


class _Carrier:
    def __init__(self, *, fail: bool = False) -> None:
        self.transfers: list[tuple[str, str]] = []
        self._fail = fail

    async def transfer(self, carrier_call_id: str, *, redirect_url: str) -> None:
        if self._fail:
            raise ProblemError(kind="dependency", code="engine_rejected", title="x", detail="x")
        self.transfers.append((carrier_call_id, redirect_url))


REQUEST = TransferRequest(
    call_ref="vz-call-1",
    to_e164="+919000000042",
    present_as="+911140000000",
    whisper="A caller about an appointment. Press 1 to accept.",
    accept_key="1",
    ring_timeout_s=25,
    whisper_timeout_s=10,
)


async def test_off_by_default_the_in_call_path_is_not_available(
    transfer_env: pytest.MonkeyPatch,
) -> None:
    provider = VobizTransfers(carrier=_Carrier())  # type: ignore[arg-type]
    assert provider.name == "vobiz"
    assert provider.contract_verified is False
    with pytest.raises(TransferContractUnverifiedError):
        await provider.start_transfer(REQUEST)

    capability = available_transfer(PipecatEngine(store=object()))  # type: ignore[arg-type]
    assert capability.provider is None
    assert capability.reason == PROVIDER_CONTRACT_UNVERIFIED


async def test_on_it_is_selected_and_still_reports_its_ending_late(
    transfer_env: pytest.MonkeyPatch,
) -> None:
    _enable(transfer_env)
    capability = available_transfer(PipecatEngine(store=object()))  # type: ignore[arg-type]
    assert isinstance(capability.provider, VobizTransfers)
    # The `<Dial>` ending arrives on its own callback, after the caller has left the stream.
    assert capability.provider.settles_synchronously is False


async def test_the_switch_selects_plivo_and_plivo_stays_unverified(
    transfer_env: pytest.MonkeyPatch,
) -> None:
    transfer_env.setenv("CARRIER", "plivo")
    _enable(transfer_env)
    engine = PipecatEngine(store=object(), carrier=PlivoCarrier())  # type: ignore[arg-type]
    capability = available_transfer(engine)
    assert capability.provider is None
    assert capability.reason == PROVIDER_CONTRACT_UNVERIFIED


async def test_a_transfer_redirects_the_leg_to_a_sealed_dial_document(
    transfer_env: pytest.MonkeyPatch,
) -> None:
    _enable(transfer_env)
    carrier = _Carrier()
    started = await VobizTransfers(carrier=carrier).start_transfer(REQUEST)  # type: ignore[arg-type]

    assert started.outcome is None
    assert started.provider_ref == "vobiz:vz-call-1"
    ((call_id, url),) = carrier.transfers
    assert call_id == "vz-call-1"
    prefix = f"{HOOKS}/carrier/v1/vobiz/transfer/"
    assert url.startswith(prefix)
    token = unquote(url[len(prefix) :])
    assert "+91" not in url, "the destination must not be readable in the URL"
    payload = open_sealed(SECRET, TRANSFER_TOKEN_PURPOSE, token)
    assert payload is not None
    assert payload["to"] == REQUEST.to_e164
    assert payload["caller_id"] == REQUEST.present_as
    assert payload["timeout_s"] == REQUEST.ring_timeout_s
    assert payload["time_limit_s"] == TRANSFER_TIME_LIMIT_S
    assert payload["call"] == "vz-call-1"


@pytest.mark.parametrize("call_ref", ["", "pipecat:tenant:call"])
async def test_a_call_the_carrier_never_named_is_refused(
    transfer_env: pytest.MonkeyPatch, call_ref: str
) -> None:
    _enable(transfer_env)
    carrier = _Carrier()
    request = replace(REQUEST, call_ref=call_ref)
    with pytest.raises(TransferRefusedError):
        await VobizTransfers(carrier=carrier).start_transfer(request)  # type: ignore[arg-type]
    assert carrier.transfers == []


async def test_a_carrier_refusal_and_missing_config_are_refusals(
    transfer_env: pytest.MonkeyPatch,
) -> None:
    _enable(transfer_env)
    with pytest.raises(TransferRefusedError):
        await VobizTransfers(carrier=_Carrier(fail=True)).start_transfer(REQUEST)  # type: ignore[arg-type]

    transfer_env.delenv("CARRIER_CLAIM_SECRET", raising=False)
    get_settings.cache_clear()
    with pytest.raises(TransferRefusedError):
        await VobizTransfers(carrier=_Carrier()).start_transfer(REQUEST)  # type: ignore[arg-type]
