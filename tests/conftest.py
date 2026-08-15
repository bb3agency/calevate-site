"""Shared pytest config.

Windows dev machines: psycopg async cannot run on the default ProactorEventLoop —
pytest-asyncio picks up this policy fixture and uses the selector loop instead.
Linux (CI, VPS) is unaffected.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from sqlalchemy import text


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    policy = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        policy = asyncio.WindowsSelectorEventLoopPolicy()
    return policy


#: Credentials a library will silently find on the machine — botocore searches the
#: environment and `~/.aws`, and pydantic reads `.env`. A test that needs one must SAY
#: so; see `_no_ambient_credentials`.
AMBIENT_CREDENTIALS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
)


@pytest.fixture(scope="session", autouse=True)
def _no_ambient_credentials() -> Iterator[None]:
    """Make the machine's credentials invisible to the suite, so local matches CI.

    TWO TESTS PASSED EVERYWHERE AND FAILED IN CI, and both failed the same way: they
    asserted about an environment they had BORROWED rather than one they declared. The
    precedence test used `COHERE_API_KEY` because this repo's `.env` happened to carry
    it. The presign test needed botocore to find an access key, and it found one in an
    exported `AWS_*` or in `~/.aws`. CI has neither, so nine consecutive runs were red —
    and because every guardrail is a later step in the same job, all twelve were
    reported `skipped` for two days.

    Detecting that by grepping test sources was tried and thrown away: it flagged three
    files that merely NAME a credential in an assertion and caught neither real
    offender. So this removes the ambient values instead. Borrowing stops being a
    mistake you can make rather than one we notice afterwards.

    `HOME` is redirected too, because botocore reads `~/.aws/credentials` and
    `~/.aws/config` and would otherwise find a profile the environment no longer names.

    A test that legitimately needs a credential declares it with
    `mock.patch.dict(os.environ, ...)` — which is now the ONLY way to have one, and
    makes the dependency visible in the test that has it.
    """
    saved = {name: os.environ.pop(name, None) for name in AMBIENT_CREDENTIALS}
    saved_home = os.environ.get("HOME")
    empty_home = tempfile.mkdtemp(prefix="calevate-no-aws-")
    os.environ["HOME"] = empty_home
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value
        if saved_home is not None:
            os.environ["HOME"] = saved_home
        shutil.rmtree(empty_home, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
async def platform_tm_registration_is_live() -> None:
    """This test database's platform is a REGISTERED telemarketer (SEC-COMP §3).

    Migration d7f2a3c9b410 gave `platform_state` Calevate's own DLT telemarketer
    registration and seeded it `not_registered` — the honest value, since R-01 is
    exactly that our TM registration is still being obtained — and
    `campaigns.service.launch_blockers` now refuses EVERY tenant's campaign while it is
    not live. That is the point of the blocker: a campaign dialled without it is not a
    client with a paperwork gap, it is Calevate dialling India's network as an
    unregistered telemarketer.

    It is therefore a fact every launch test needs and none of them can invent per
    tenant, because there is exactly one row for the whole platform. Supplied HERE,
    once, rather than in each suite's fixtures: the fixtures that already supply the
    per-tenant PE registration cannot supply a global one without every file writing
    the same row, and a suite that forgot would fail depending on which other suite had
    run first on the shared database.

    This SUPPLIES the fact; it does not soften the gate. Production still has to record
    the registration through the audited ops surface
    (`POST /v1/ops/platform/tm-registration`), and `tests/tm_registration_test.py`
    proves the refusal is real by taking the fact away again — inside a transaction it
    rolls back, so no other pytest process ever sees a platform that cannot dial.

    Concurrency: idempotent, one UPDATE, and only ever in the PERMISSIVE direction. The
    predicate makes it a no-op on every run after the first, so concurrent suites do
    not queue on the row, and nothing here can halt another run's dialling.
    """
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE platform_state SET tm_registration_status = 'active', "
                "tm_id = COALESCE(tm_id, 'TM-TEST-0000000001'), "
                "tm_registered_at = COALESCE(tm_registered_at, :reg), "
                "tm_verified_at = now() "
                "WHERE id = 1 AND tm_registration_status <> 'active'"
            ),
            {"reg": datetime.now(UTC) - timedelta(days=365)},
        )


@pytest.fixture
def source_ip_allowlist(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Point the Bolna webhook source-IP allowlist at documentation addresses.

    Every receiver suite needs this: a test must never encode the vendor's CURRENT
    egress address, which is a value they change without asking us.

    It sets the ENVIRONMENT VARIABLE rather than patching a module attribute, because
    `BOLNA_WEBHOOK_SOURCE_IPS` is now the single source of truth that both
    `engine_intake.verify_source` and `BolnaEngine.verify_webhook` resolve through
    (`calevate_shared.config.bolna_source_ips`). The old fixtures patched
    `engine_intake.BOLNA_SOURCE_IPS`, which is precisely why they could never have
    caught the two halves disagreeing: they moved one of them.

    `get_settings` is `lru_cache`d, so the cache is cleared on the way in and out — and
    PRIMED on the way in, so no test measuring the ack budget or the per-request import
    surface pays for the first `Settings()` construction inside its own request.
    """

    def _set(*ips: str) -> None:
        monkeypatch.setenv("BOLNA_WEBHOOK_SOURCE_IPS", ",".join(ips))
        get_settings.cache_clear()
        get_settings()

    yield _set
    get_settings.cache_clear()
