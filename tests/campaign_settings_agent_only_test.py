"""D-1027: a campaign sets only its script language; every other call setting is its agent's."""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.campaigns.settings import apply_overrides, clean_overrides
from apps.api.core.errors import ProblemError

#: What a campaign saved before D-1027 could hold.
STORED = {
    "language_primary": "hi-IN",
    "speaking_speed": "1.3",
    "max_call_duration_s": 300,
    "nudge_after_seconds": 5,
}


def test_a_stored_speed_or_call_setting_no_longer_reaches_the_campaigns_calls() -> None:
    agent = {
        "language_primary": "te-IN",
        "voice_tuning": (Decimal("0.9"), None, None, None, None),
        "max_call_duration_s": 900,
        "call_settings": None,
    }
    row = apply_overrides(agent, STORED)
    assert row["language_primary"] == "hi-IN"
    assert row["voice_tuning"] == agent["voice_tuning"]
    assert row["max_call_duration_s"] == 900
    assert row["call_settings"] is None
    assert row["campaign_overrides"] == {"language_primary": "hi-IN"}


@pytest.mark.parametrize("key", ["speaking_speed", "max_call_duration_s", "nudge_after_seconds"])
def test_a_save_of_a_call_setting_on_a_campaign_is_refused(key: str) -> None:
    with pytest.raises(ProblemError) as refused:
        clean_overrides({key: STORED[key]})
    assert refused.value.code == "campaign_setting_invalid"
