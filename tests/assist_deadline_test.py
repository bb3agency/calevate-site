"""The user-triggered assist must finish before nginx gives up on it.

THE DEFECT THIS FILE PINS. `run_assist` runs two provider legs IN SERIES — Azure, then
the disclosed Sarvam fallback — and both used `EXTRACTION_TIMEOUT_S` (30s). That is ~60s
of provider wait before the route's own idempotency claim, quota gate, transcript load,
metering and audit write, behind `location /` on the `api.` vhost, whose effective
`proxy_read_timeout` comes from `infra/nginx/snippets/calevate-proxy.conf` and is 60s. The
edge gave up first, so the client got a 504 INSTEAD OF the fallback's answer — the one
outcome the fallback exists to prevent — while a pooled Postgres connection was held for
the whole minute.

WHY A TEST AND NOT A COMMENT. The budget is two numbers, in two languages, in two files
that no build step relates: raising the Python timeout or lowering the nginx one is a
one-line edit that looks locally correct and re-opens the collision silently. Only an
assertion that reads BOTH can keep them honest.

WHY THE FIX IS NOT `proxy_read_timeout 120s`. That directive sits on a catch-all over
every API route, so buying headroom for one path lengthens how long every slow upstream
holds an edge connection on the box that also runs Postgres. The budget belongs to the
client that knows it is making two calls.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from apps.workers.extraction import (
    ASSIST_ROUTE_RESERVE_S,
    ASSIST_TIMEOUT_S,
    EXTRACTION_TIMEOUT_S,
)
from calevate_shared.extraction import ExtractionSchemaSpec

SNIPPET = (
    Path(__file__).resolve().parents[1] / "infra" / "nginx" / "snippets" / "calevate-proxy.conf"
)

#: `proxy_read_timeout 60s;` -> "60s". nginx accepts a bare number as seconds and a suffix
#: for other units; only the two forms we actually write are parsed, and anything else
#: fails loudly rather than being coerced into a number that would weaken the assertion.
_READ_TIMEOUT = re.compile(r"^\s*proxy_read_timeout\s+(\d+)(s|m)?\s*;", re.MULTILINE)


def _proxy_read_timeout_s() -> float:
    """The `proxy_read_timeout` every API location inherits from the shared snippet.

    THE SNIPPET AND NOT THE VHOST, deliberately. `include` is textual, so these three
    lines land at LOCATION scope in every block that includes them and beat anything the
    enclosing `server` says — which is the sibling defect `tests/nginx_hooks_vhost_test.py`
    pins. For the `api.` vhost there is no restatement at all, so the snippet's value IS
    the deadline the assist route runs under.
    """
    matches = _READ_TIMEOUT.findall(SNIPPET.read_text(encoding="utf-8"))
    assert len(matches) == 1, (
        f"expected exactly one proxy_read_timeout in {SNIPPET.name}, found {len(matches)}: "
        "the assist budget is computed against it and cannot be computed against two"
    )
    value, unit = matches[0]
    return float(value) * (60.0 if unit == "m" else 1.0)


def test_two_assist_legs_and_the_route_reserve_fit_inside_the_edge_deadline() -> None:
    """The headline arithmetic: `2 * leg + reserve < proxy`.

    FAILS IF: `ASSIST_TIMEOUT_S` is raised, `ASSIST_ROUTE_RESERVE_S` is raised, or
    `proxy_read_timeout` in `calevate-proxy.conf` is lowered — any of which puts the
    two-leg path back over the edge deadline and turns the disclosed Sarvam fallback into
    a 504.
    """
    proxy = _proxy_read_timeout_s()
    worst_case = 2 * ASSIST_TIMEOUT_S + ASSIST_ROUTE_RESERVE_S
    assert worst_case < proxy, (
        f"a two-leg assist can take {worst_case}s (Azure {ASSIST_TIMEOUT_S}s + Sarvam "
        f"{ASSIST_TIMEOUT_S}s + {ASSIST_ROUTE_RESERVE_S}s of route work) behind a {proxy}s "
        "proxy_read_timeout: the client gets a 504 instead of the fallback's answer"
    )


def test_the_azure_strict_schema_retry_also_fits() -> None:
    """The worst case is three requests, not two, and it still has to fit.

    `AzureOpenAIExtractor.run` re-asks ONCE with plain `json_object` when the strict
    Structured Outputs request earns a 400, and httpx's timeout is per-request — so the
    Azure leg alone can be two full budgets before Sarvam gets its own. The retry is
    documented as cheap (a 400 is refused at request validation, no model time), which is
    why this is a second assertion rather than the headline one, but "cheap" is a vendor
    behaviour nobody here has measured and the arithmetic should not depend on it.

    FAILS IF: the per-leg budget is raised to a value that only works when Azure never
    degrades — e.g. 20s, which passes the test above and blows the deadline the first time
    a deployment refuses `json_schema`.
    """
    proxy = _proxy_read_timeout_s()
    worst_case = 3 * ASSIST_TIMEOUT_S + ASSIST_ROUTE_RESERVE_S
    assert worst_case <= proxy, (
        f"an assist whose Azure leg degrades to json_object can take {worst_case}s behind "
        f"a {proxy}s proxy_read_timeout"
    )


def test_the_post_call_budget_is_not_the_user_facing_one() -> None:
    """The two numbers exist because the two paths have different waiters.

    FAILS IF: somebody collapses them back to one constant. The ARQ post-call path holds
    no HTTP connection and no pooled Postgres connection across the provider call, so 30s
    a leg is right there and nothing at the edge is counting; the dashboard path is behind
    a proxy deadline and a person. One number cannot be correct for both.
    """
    assert ASSIST_TIMEOUT_S < EXTRACTION_TIMEOUT_S, (
        "the user-triggered budget must be tighter than the post-call one — it is the "
        "path with a browser and a proxy waiting on it"
    )


@pytest.mark.parametrize(
    "constant", [ASSIST_TIMEOUT_S, ASSIST_ROUTE_RESERVE_S, EXTRACTION_TIMEOUT_S]
)
def test_every_budget_is_a_positive_number_of_seconds(constant: float) -> None:
    """A zero or negative budget is an httpx client that times out immediately, which
    would present as "the assistant never answers" rather than as a misconfiguration.

    FAILS IF: a constant is set to 0 to disable a timeout — the way to do that in httpx is
    `None`, and none of these three may be `None`, because every one of them is an
    argument in the arithmetic above.
    """
    assert isinstance(constant, float) and constant > 0


# --- the budget actually reaching the two legs --------------------------------
#
# The arithmetic above is worthless if `run_assist` still hands both extractors the
# post-call number. These two assert the wiring rather than the constants.


async def test_both_assist_legs_are_built_with_the_user_facing_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Azure first, Sarvam second, both at `ASSIST_TIMEOUT_S`.

    FAILS IF: either construction site in `run_assist` drops the keyword and falls back to
    the 30s default — which is the defect, and which no assertion about the constants
    themselves would catch.
    """
    from apps.api.core.settings import get_settings
    from apps.workers import extraction

    monkeypatch.setattr(extraction, "azure_credentials", lambda: ("resource", "key", "deployment"))
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    built: list[tuple[str, float]] = []

    class _RecordingSarvam(extraction.SarvamExtractor):
        def __init__(self, api_key: str, *args: object, **kwargs: object) -> None:
            super().__init__(api_key, *args, **kwargs)  # type: ignore[arg-type]
            built.append(("sarvam", self._timeout_s))

        async def run(self, spec: object, transcript: str) -> dict[str, object]:
            return {"summary": "answered"}

    monkeypatch.setattr(extraction, "SarvamExtractor", _RecordingSarvam)

    def _spy_azure(*, timeout_s: float = extraction.EXTRACTION_TIMEOUT_S) -> None:
        # Recorded, then None — which sends `run_assist` down the fallback leg, so one
        # call exercises both construction sites.
        built.append(("azure", timeout_s))
        return None

    monkeypatch.setattr(extraction, "azure_extractor", _spy_azure)

    spec = ExtractionSchemaSpec.model_validate({"version": 1, "fields": []})
    await extraction.run_assist(spec, "Caller asked about opening hours.")

    assert built == [("azure", ASSIST_TIMEOUT_S), ("sarvam", ASSIST_TIMEOUT_S)]


def test_the_post_call_extractor_still_gets_the_post_call_budget() -> None:
    """The other half of "one number per waiter": nothing user-facing may leak into the
    ARQ path, whose 30s is correct and whose retry arithmetic in `pipeline.py` assumes it.

    FAILS IF: a future edit makes `ASSIST_TIMEOUT_S` the default on either constructor
    instead of the value `run_assist` passes in.
    """
    from apps.workers.extraction import AzureOpenAIExtractor, SarvamExtractor

    assert SarvamExtractor("k")._timeout_s == EXTRACTION_TIMEOUT_S
    assert AzureOpenAIExtractor("resource", "key", "deployment")._timeout_s == EXTRACTION_TIMEOUT_S
