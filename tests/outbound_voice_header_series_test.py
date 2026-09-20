"""An outbound commercial campaign may only dial from a registered voice header.

TRAI direction RG-25/(18)/2023-QoS (E-10291), 18 June 2024, in its own words: *"Senders
shall not use any other 10-digit fixed line/ mobile number for making Promotional/ Service/
Transactional voice calls to their customers, either directly or through their employees or
channel partners, DSAs, BPO partner, in-house or outsourced Call Centre, etc."* — read
20 September 2026 from the copy TRAI's circular is reproduced at on the access provider's
site, and relayed by the founder with the quoted text.

`standard` satisfied the launch gate for the service and transactional classifications
until that direction was read. This file is the guard that keeps it out, because the
widening is a one-word edit whose consequence is a regulated dial from an unregistered
number.

**INBOUND IS DELIBERATELY UNGOVERNED HERE.** A receptionist answering a call the customer
placed is not a sender making one, and `SERIES_FOR_CLASSIFICATION` is only ever consulted on
the campaign launch path.
"""

from __future__ import annotations

from apps.api.agents.models import NUMBER_SERIES
from apps.api.campaigns.service import SERIES_FOR_CLASSIFICATION

#: The two series TRAI's direction names as the ones a sender registers and dials on.
REGISTERED_VOICE_HEADER_SERIES = frozenset({"140", "160"})


def test_no_classification_may_dial_from_an_ordinary_did() -> None:
    """The whole rule, asserted over every classification rather than the two that moved."""
    for classification, series in SERIES_FOR_CLASSIFICATION.items():
        assert "standard" not in series, (
            f"{classification!r} may dial from an ordinary 10-digit number, which the "
            "18 Jun 2024 TRAI voice direction forbids for promotional, service and "
            "transactional calls alike"
        )


def test_every_allowed_series_is_a_registered_voice_header() -> None:
    """Stated as a subset rather than three equalities, so a fourth classification added
    later is covered the day it is written."""
    for classification, series in SERIES_FOR_CLASSIFICATION.items():
        assert set(series) <= REGISTERED_VOICE_HEADER_SERIES, (
            f"{classification!r} allows a series that is not a registered voice header"
        )


def test_promotional_stays_on_140_alone() -> None:
    """160 is the service and transactional header; a promotional call on it is the
    mismatch the DLT trail is designed to catch."""
    assert SERIES_FOR_CLASSIFICATION["promotional"] == ("140",)


def test_service_and_transactional_share_160() -> None:
    assert SERIES_FOR_CLASSIFICATION["service"] == ("160",)
    assert SERIES_FOR_CLASSIFICATION["transactional"] == ("160",)


def test_standard_survives_as_a_recordable_series() -> None:
    """Removing it from the launch gate is not removing it from the product: an ordinary
    DID is still what an inbound-only client hands us, and still what an operator records."""
    assert "standard" in NUMBER_SERIES


def test_the_1601_series_validates_as_160() -> None:
    """TRAI operationalised 1601 for service and transactional voice calls by entities
    outside BFSI. Nothing new is needed for it: the prefix check is a startswith, so a
    1601 number recorded as `160` passes, and a 1600-series number does too."""
    from apps.api.agents.models import _REGULATED_PREFIXES

    assert "1601234567".startswith(_REGULATED_PREFIXES["160"])
    assert "1600123456".startswith(_REGULATED_PREFIXES["160"])
