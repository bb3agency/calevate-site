"""The carrier switch (D-662): one setting picks the carrier, and everything follows it."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from apps.api.compliance.carrier_application import current_carrier
from apps.api.compliance.models import CARRIER_APPLICATION_CARRIERS
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.carrier import CARRIER_ADAPTER_MODULES, build_carrier, get_carrier
from apps.api.engine.pipecat import (
    PIPECAT_CAPABILITIES,
    PIPECAT_VOBIZ_CAPABILITIES,
    PipecatEngine,
    capabilities_for_carrier,
)
from apps.api.engine.plivo_carrier import PlivoCarrier
from apps.api.engine.vobiz import VobizCarrier
from calevate_shared.carrier import CARRIERS, DEFAULT_CARRIER

pytestmark = pytest.mark.anyio


@pytest.fixture
def carrier_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _select(monkeypatch: pytest.MonkeyPatch, carrier: str) -> None:
    monkeypatch.setenv("CARRIER", carrier)
    get_settings.cache_clear()


def test_vobiz_is_the_default_and_every_carrier_has_an_adapter_module() -> None:
    assert DEFAULT_CARRIER == "vobiz"
    assert set(CARRIER_ADAPTER_MODULES) == set(CARRIERS)
    assert set(CARRIER_APPLICATION_CARRIERS) == set(CARRIERS)


def test_the_switch_picks_the_carrier(carrier_env: pytest.MonkeyPatch) -> None:
    _select(carrier_env, "vobiz")
    assert isinstance(get_carrier(), VobizCarrier)
    assert current_carrier() == "vobiz"
    assert PipecatEngine(store=object()).capabilities == PIPECAT_VOBIZ_CAPABILITIES  # type: ignore[arg-type]

    _select(carrier_env, "plivo")
    assert isinstance(get_carrier(), PlivoCarrier)
    assert current_carrier() == "plivo"
    assert PipecatEngine(store=object()).capabilities == PIPECAT_CAPABILITIES  # type: ignore[arg-type]


def test_a_named_carrier_overrides_the_switch(carrier_env: pytest.MonkeyPatch) -> None:
    _select(carrier_env, "plivo")
    assert isinstance(build_carrier(get_settings(), "vobiz"), VobizCarrier)


def test_the_two_profiles_differ_only_in_the_carrier_half() -> None:
    assert capabilities_for_carrier("plivo") == PIPECAT_CAPABILITIES
    vobiz = capabilities_for_carrier("vobiz")
    assert vobiz.caller_id and vobiz.inbound_binding
    assert not PIPECAT_CAPABILITIES.caller_id and not PIPECAT_CAPABILITIES.inbound_binding
    assert vobiz.model_copy(update={"caller_id": False, "inbound_binding": False}) == (
        PIPECAT_CAPABILITIES
    )


async def test_every_plivo_operation_refuses_with_the_unread_evidence() -> None:
    carrier = PlivoCarrier()
    assert carrier.name == "plivo"
    assert carrier.configured() is False
    calls = [
        carrier.place_call(
            from_e164="+911140000000",
            to_e164="+919876543210",
            answer_url="a",
            hangup_url="h",
            ring_url="r",
            time_limit_s=60,
        ),
        carrier.hang_up("c"),
        carrier.transfer("c", redirect_url="u"),
        carrier.fetch_cdr("c"),
        carrier.bind_number("+911140000000", answer_url="a", hangup_url="h", label="l"),
        carrier.unbind_number("+911140000000"),
        carrier.probe(),
    ]
    for call in calls:
        with pytest.raises(ProblemError) as raised:
            await call
        assert raised.value.code == "engine_capability_unverified"
        assert "pre-build-blockers" in (raised.value.remediation or "")
    with pytest.raises(ProblemError):
        carrier.parse_event({"CallUUID": "c"})


def test_one_engine_instance_follows_the_switch_without_a_restart(
    carrier_env: pytest.MonkeyPatch,
) -> None:
    """`get_engine` caches one adapter per process, so the carrier is read per operation:
    `core/platform_config` says a moved switch dials on the new carrier at once."""
    _select(carrier_env, "vobiz")
    engine = PipecatEngine(store=object())  # type: ignore[arg-type]
    assert engine.capabilities == PIPECAT_VOBIZ_CAPABILITIES
    assert isinstance(engine._carrier, VobizCarrier)

    _select(carrier_env, "plivo")
    assert engine.capabilities == PIPECAT_CAPABILITIES
    assert isinstance(engine._carrier, PlivoCarrier)


def test_an_injected_carrier_and_a_set_descriptor_stay_pinned(
    carrier_env: pytest.MonkeyPatch,
) -> None:
    _select(carrier_env, "plivo")
    pinned = VobizCarrier(auth_id=None, auth_token=None, base_url="https://api.example/api/v1")
    engine = PipecatEngine(store=object(), carrier=pinned)  # type: ignore[arg-type]
    assert engine._carrier is pinned
    assert engine.capabilities == PIPECAT_VOBIZ_CAPABILITIES

    engine.capabilities = PIPECAT_CAPABILITIES
    assert engine.capabilities == PIPECAT_CAPABILITIES
