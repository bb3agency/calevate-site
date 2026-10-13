"""`is_public_callback_base`: the one predicate for "a vendor on the internet can call us back".

Readiness, the deploy preflight and the engine webhook, action and lookup registrations
all ask it, so a loopback or plain-http base that passed here would be registered with
the engine and every delivery would go nowhere.
"""

from __future__ import annotations

import pytest
from apps.api.core.settings import is_public_callback_base


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8100",
        "http://hooks.calevate.tech",
        "https://localhost",
        "https://api.localhost",
        "https://127.0.0.1",
        "https://127.8.0.1:8443",
        "https://[::1]",
        "https://0.0.0.0",
        "https://",
        "",
        None,
    ],
)
def test_a_callback_base_a_vendor_cannot_reach_is_refused(url: str | None) -> None:
    assert is_public_callback_base(url) is False


@pytest.mark.parametrize(
    "url",
    ["https://hooks.calevate.tech", "https://hooks.calevate.tech:8443/", "https://203.0.113.7"],
)
def test_a_public_https_callback_base_is_accepted(url: str) -> None:
    assert is_public_callback_base(url) is True
