"""The series vocabulary a number is recorded under, and the 140/160 prefix rule it is checked by.

No launch or dial gate matches a number's series to a campaign's classification (D-692,
D-775). The series is still recorded and validated against the number's own prefix
(`number_series_mismatch`), so an operator's typed word cannot mislabel a number.
"""

from __future__ import annotations

from apps.api.agents.models import NUMBER_SERIES


def test_standard_survives_as_a_recordable_series() -> None:
    """An ordinary DID is still what an inbound-only client hands us, and still what an
    operator records."""
    assert "standard" in NUMBER_SERIES


def test_the_1601_series_validates_as_160() -> None:
    """TRAI operationalised 1601 for service and transactional voice calls by entities
    outside BFSI. Nothing new is needed for it: the prefix check is a startswith, so a
    1601 number recorded as `160` passes, and a 1600-series number does too."""
    from apps.api.agents.models import _REGULATED_PREFIXES

    assert "1601234567".startswith(_REGULATED_PREFIXES["160"])
    assert "1600123456".startswith(_REGULATED_PREFIXES["160"])
