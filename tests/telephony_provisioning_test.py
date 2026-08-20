"""The number-provisioning provider set, held against the engine's own carrier table.

`campaigns/provisioning.py::KNOWN_PROVIDERS` is the tuple that decides which refusal an
operator sees when they set `NUMBER_PROVIDER`. A name inside it means "supported vendor,
no adapter yet" (`no_provisioning_adapter`); a name outside it means "we do not support
that vendor at all" (`provider_not_implemented`). Those are different operator problems
with different fixes, which is the whole reason the module keeps two reason codes — so
the membership of that tuple is a behavioural claim and not a note.

WHY THIS IS PINNED TO THE VENDOR RATHER THAN TO ITSELF. `NUMBER_SERIES` enumerates the
DLT number classes we model (`agents/models.py:44`). Bolna maps each regulated class onto
exactly one Indian carrier, in a table rather than in prose — `bolna-findings/mirror/
pages/guides/inbound/obtaining-regulated-phone-numbers.md:13-16`:

    | Number Series  | Use Case                                     | Telephony Provider |
    | **140-series** | Telemarketing and promotional calls          | Vobiz              |
    | **160-series** | Transactional and service calls (banking...) | Plivo              |

A series we accept at the purchase route whose carrier we refuse to be configured with is
a request that cannot be satisfied however the deployment is set up, and it fails at the
worst moment: after KYC has passed, with an operator-facing reason ("unsupported vendor")
that names the wrong problem. `plivo` was missing for exactly that reason and this test is
what would have caught it.

It asserts a SUPERSET, not equality: `exotel` is legitimately in the tuple without being
in that table — Bolna integrates it as bring-your-own-account rather than as a series
carrier — and pinning the tuple exactly would turn adding a vendor into editing a test
that has no opinion about it.
"""

from __future__ import annotations

import pytest
from apps.api.agents.models import NUMBER_SERIES
from apps.api.campaigns.provisioning import (
    KNOWN_PROVIDERS,
    NO_ADAPTER_REASON,
    PROVIDER_NOT_IMPLEMENTED_REASON,
    number_provisioning_capability,
)
from apps.api.core.settings import get_settings

#: The engine's regulated-series carrier table, transcribed from the citation above.
#: Keys are checked against `NUMBER_SERIES` below so a series renamed in our enum breaks
#: this map rather than silently dropping out of the check.
SERIES_CARRIER = {"140": "vobiz", "160": "plivo"}


def test_the_carrier_map_only_names_series_we_model() -> None:
    """Guard on the guard: a `NUMBER_SERIES` edit must not orphan a row of the table."""
    assert set(SERIES_CARRIER) <= set(NUMBER_SERIES), (
        "the vendor's carrier table names a series our own enum does not"
    )


def test_every_regulated_series_carrier_is_a_configurable_provider() -> None:
    """The refusal an operator gets must name the real problem.

    Naming the carrier that allocates a series we sell has to resolve to "no adapter
    yet", never to "unsupported vendor" — the second sends them to change a setting that
    was already right.
    """
    missing = sorted(
        {carrier for carrier in SERIES_CARRIER.values() if carrier not in KNOWN_PROVIDERS}
    )
    assert not missing, (
        f"carriers Bolna allocates regulated numbers through are not configurable: {missing}"
    )


@pytest.mark.parametrize(("series", "carrier"), sorted(SERIES_CARRIER.items()))
def test_a_carrier_resolves_to_the_missing_adapter_and_not_to_an_unknown_vendor(
    monkeypatch: pytest.MonkeyPatch, series: str, carrier: str
) -> None:
    """The membership above, observed through the ONE selector rather than asserted twice.

    A tuple can contain a name and the selector still classify it wrongly; this reads the
    reason string every surface actually shows.
    """
    monkeypatch.setattr(get_settings(), "number_provider", carrier)
    capability = number_provisioning_capability()

    assert capability.available is False, f"{series}: no adapter exists for any vendor"
    assert capability.reason == f"{NO_ADAPTER_REASON}:{carrier}", (
        f"{series}-series carrier {carrier!r} must refuse as a missing adapter, "
        f"got {capability.reason!r}"
    )
    assert not str(capability.reason).startswith(PROVIDER_NOT_IMPLEMENTED_REASON), (
        f"{series}-series carrier {carrier!r} reported as an unsupported vendor"
    )
