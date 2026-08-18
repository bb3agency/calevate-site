"""`/healthz/live` answers 200 when Redis AND Postgres are unreachable (D-195).

Its whole contract is that it touches no dependency, because `compose.prod.yml` polls it
to decide whether to KILL the container. A liveness probe that fails when a dependency
does is not a liveness probe — it is a restart loop with extra steps: dependency wobbles,
probe 500s, orchestrator restarts the container, the container comes back into the same
wobble, repeat. The restart also takes down the process that would have recovered on its
own once the dependency returned.

The handler was always innocent — it returns a literal dict. The failure was in
`LoadShedMiddleware`, which called `get_platform_status()` on EVERY request before
`is_shed` could apply the allowlist. That function reads Redis (guarded) and falls back to
`_read_durable`, a database read that is NOT guarded, so with both dependencies gone the
middleware raised before any exemption was consulted.

Found by the D-188 deploy audit, which observed the 500 with Redis unreachable, traced the
instance it saw to a different defect, and said plainly it could not prove no other path
produced it. This is the other path.
"""

from __future__ import annotations

import httpx
import pytest
from apps.api.core import loadshed, middleware

pytestmark = pytest.mark.asyncio


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


class _TotalOutageError(RuntimeError):
    """What a dead Redis and a dead Postgres look like from inside the middleware."""


@pytest.fixture
def everything_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the platform-status lookup raise, the way a real double outage does.

    Patched at `get_platform_status` rather than at the Redis and DB clients because THAT
    is the seam under test: the question is whether the middleware asks it at all for an
    exempt path, not how it fails. Patching deeper would also make this test pass for the
    wrong reason the day somebody adds a `try` inside the function — which would hide the
    outage rather than exempt the probe, and is exactly the fix this one is not.
    """
    monkeypatch.setattr(loadshed, "_memo", None)

    async def _dead(*_args: object, **_kwargs: object) -> object:
        raise _TotalOutageError("redis and postgres are both unreachable")

    monkeypatch.setattr(middleware, "get_platform_status", _dead)


@pytest.mark.usefixtures("everything_down")
async def test_liveness_answers_while_every_dependency_is_down() -> None:
    async with _client() as http:
        response = await http.get("/healthz/live")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"


@pytest.mark.usefixtures("everything_down")
async def test_the_other_always_allowed_prefixes_answer_too() -> None:
    """The exemption is a LIST, and every entry on it exists for an outage.

    `/hooks` in particular: a dropped engine webhook is a call whose lead never appears,
    and an outage is when the poller is most needed. Asserting only `/healthz/live` would
    pass just as well against a fix that special-cased one string.
    """
    async with _client() as http:
        # 404 is a fine answer here and is the POINT: the request reached routing rather
        # than being turned into a 500 by the middleware. What must not happen is a 5xx.
        for path in ("/healthz/live", "/hooks/does-not-exist", "/openapi.json"):
            response = await http.get(path)
            assert response.status_code < 500, f"{path} → {response.status_code}"


async def test_a_shed_able_path_still_consults_the_status() -> None:
    """The control, and the one that stops this becoming a global bypass.

    Without it, `is_always_allowed` returning True for everything would satisfy every
    assertion above while switching load shedding off entirely.
    """
    assert not loadshed.is_always_allowed("/v1/leads")
    assert not loadshed.is_always_allowed("/v1/campaigns")
    assert loadshed.is_always_allowed("/healthz/live")
