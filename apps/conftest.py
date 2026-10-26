"""The suite's environment for the tests that live beside the code in `apps/`.

`tests/conftest.py` sets up the facts and isolation every DB-backed test relies on: the
platform is a registered telemarketer and offers voices, the machine's credentials are
hidden, each test has its own rate-limit keys, reserved test domains resolve, the IST
month boundary is pinned, and process-wide catalogue state is restored after each test.
A conftest only reaches the tests below its own directory, so without this file a test
under `apps/` got those facts only when some test under `tests/` happened to run first on
the same database, and failed when it did not.

The fixtures are imported rather than copied, so there is still one definition of each.
The session-scoped ones then run once for each tree; every one is idempotent or restores
what it changed, so running twice is harmless. `packages/` is left out on purpose: its
tests need no database, and these fixtures would make them need one.
"""

import sys

from tests.conftest import (  # noqa: F401  (fixtures are found by name)
    _ist_month_boundary_is_pinned,
    _no_ambient_credentials,
    _own_rate_limit_buckets,
    _reserved_test_domains_resolve,
    _tts_price_reader_is_restored,
    _voice_catalogue_snapshot_is_restored,
    platform_offers_voices,
    platform_tm_registration_is_live,
)

if sys.platform == "win32":
    from tests.conftest import pytest_asyncio_loop_factories  # noqa: F401
