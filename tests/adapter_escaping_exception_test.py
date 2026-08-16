"""Two exceptions that escaped the engine adapter, and the class they belong to.

Hard rule 2 makes `apps/api/engine/` the only place vendor payload shapes are seen, which
means it is also the only place that can turn a vendor's misbehaviour into OUR vocabulary.
An exception that escapes it is a vendor shape reaching code that has no idea what to do
with one — a raw 500 on a route, or a DLQ'd job on a worker.

Both findings here are the same mistake in two spellings: **an exception type that is not
in any `except` clause on the path.**

* **P2.2** — `_request` called `response.json()` unguarded. The `>= 400` branch raises
  first, so the exposure is a **2xx with a non-JSON body**: a WAF challenge, a proxy
  interstitial, a CDN maintenance page. `json.JSONDecodeError` is a `ValueError` — not a
  `ProblemError`, not an `httpx.HTTPError` — so it was caught by nothing. It reached
  `create_agent` as a raw 500 with no code and no remediation, made `verify_publish`'s
  "never raises for a vendor-side failure" docstring false, and DLQ'd both the post-call
  pipeline and the reconciliation poller.
* **P2.3** — `_next_link` called `httpx.URL(candidate)` on a vendor-supplied string,
  unguarded. `httpx.InvalidURL`'s MRO does **not** include `httpx.HTTPError`, which the
  first test below measures rather than assumes, so `_request`'s handler could not have
  caught it even if the call were inside one. `list_executions`' only caller is
  `reconcile_executions`, which under D-31 IS the guarantee of record.

**THE STRUCTURAL TEST IS THE ONE THAT MATTERS.** The two behavioural tests cover the two
call sites somebody remembered. The scan covers the adapters and the call sites that do
not exist yet — and this repository had ALREADY solved P2.2 twice, in
`billing/payments.py` and in `engine/cartesia.py`, before the adapter actually going to
production missed it. A defect that recurs across three modules is a defect a per-instance
test cannot hold.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.bolna import BolnaEngine

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = REPO_ROOT / "apps" / "api" / "engine"
BASE_URL = "https://api.bolna.test"


def _engine(handler: Any) -> BolnaEngine:
    return BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


# ============================================================================
# The measurement both findings rest on
# ============================================================================


def test_the_two_escaping_types_are_in_neither_family_the_adapter_catches() -> None:
    """Pinned as a measurement, because both fixes are only necessary while it holds.

    If a future httpx made `InvalidURL` an `HTTPError`, or a future Python made
    `JSONDecodeError` something other than a `ValueError`, the reasoning in both comments
    would be wrong and this test says so on the day it happens rather than leaving two
    paragraphs that quietly stopped being true.
    """
    assert not issubclass(httpx.InvalidURL, httpx.HTTPError), (
        "httpx.InvalidURL is now an HTTPError — `_next_link`'s comment explains the guard "
        "by the fact that it is not"
    )
    assert issubclass(json.JSONDecodeError, ValueError)
    assert not issubclass(json.JSONDecodeError, httpx.HTTPError)


# ============================================================================
# P2.2 — a 2xx that is not JSON
# ============================================================================


async def test_a_success_with_a_non_json_body_becomes_our_problem_not_a_500() -> None:
    """The WAF-challenge case. 200, `text/html`, and nothing to parse."""
    engine = _engine(
        lambda request: httpx.Response(
            200, text="<html><body>Attention Required! | Cloudflare</body></html>"
        )
    )

    with pytest.raises(ProblemError) as caught:
        await engine.get_agent("agent_1")

    assert caught.value.code == "engine_bad_response"
    assert caught.value.kind == "dependency"


async def test_the_vendors_body_is_not_echoed_to_the_caller() -> None:
    """A vendor error body is not our vocabulary and is not user-safe — the `>= 400`
    branch already says so about itself, and this path must hold to the same rule."""
    secret_ish = "Ray ID 8f3a2b1c — origin 10.0.0.7 — token abcdef"
    engine = _engine(lambda request: httpx.Response(200, text=secret_ish))

    with pytest.raises(ProblemError) as caught:
        await engine.get_agent("agent_1")

    rendered = f"{caught.value.detail} {caught.value.title} {caught.value.code}"
    assert "Ray ID" not in rendered and "10.0.0.7" not in rendered


async def test_an_empty_success_is_still_not_an_error() -> None:
    """The control, and the reason the guard could not simply be "parse or raise": a
    successful DELETE may answer 204 with no body, and `response.json()` raises on that
    too. The empty-body branch runs first and must keep running first."""
    engine = _engine(lambda request: httpx.Response(204))

    assert await engine.delete_agent("agent_1") is None or True  # must not raise


# ============================================================================
# P2.3 — a `next` link that is not a URL
# ============================================================================


async def test_an_unparseable_next_link_is_dropped_rather_than_raised() -> None:
    """The docstring already promised this: "anything else is dropped — dropping degrades
    to `explicit_more`, which is loud".

    A zero-width space inside the host is enough to make `httpx.URL` raise, and it is
    exactly the shape a copy-pasted or mangled vendor field takes. The listing must come
    back — incomplete and SAYING so — rather than taking the reconciliation poller down
    with it.
    """
    page = {
        "data": [{"id": f"exec_{i}", "agent_id": "a", "status": "completed"} for i in range(10)],
        "next": "http://a​.com/executions?page=2",
    }
    engine = _engine(lambda request: httpx.Response(200, json=page))

    listing = await engine.list_executions(since=datetime.now(UTC) - timedelta(minutes=30))

    assert len(listing.snapshots) == 10
    assert listing.complete is False, (
        "a dropped continuation must leave the listing INCOMPLETE — the poller reads that "
        "flag to decide whether it saw the whole window"
    )


# ============================================================================
# The scan — the adapters that do not exist yet
# ============================================================================


def _unguarded_json_calls(path: Path) -> list[int]:
    """Line numbers of `<expr>.json()` calls that are not inside a `try`.

    Deliberately crude in the safe direction: a `.json()` inside ANY `try` counts as
    guarded, because narrowing that to "a try whose handler names ValueError" would make
    this scan reject the `contextlib.suppress` and re-raise idioms a future adapter might
    reasonably use. What it catches is the case all three instances of this defect took —
    a bare call with no handler anywhere above it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "json"
                ):
                    guarded.add(child.lineno)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "json"
        and node.lineno not in guarded
    ]


def test_no_adapter_parses_a_vendor_response_without_a_handler() -> None:
    """Every adapter, including ones written after this test.

    `apps/api/engine/` is the only directory allowed to see a vendor payload (hard rule
    2), which makes it the only place that can convert a malformed one into our
    vocabulary. A bare `.json()` here is a `ValueError` on its way to a route or a worker.
    """
    offenders = {
        path.name: lines
        for path in sorted(ENGINE_DIR.glob("*.py"))
        if (lines := _unguarded_json_calls(path))
    }
    assert offenders == {}, (
        f"unguarded response.json() in the engine layer: {offenders}. A 2xx with a "
        "non-JSON body raises json.JSONDecodeError, which is a ValueError — not a "
        "ProblemError and not an httpx.HTTPError, so nothing on the path catches it "
        "(P2.2). `engine/cartesia.py` and `billing/payments.py` both already guard this."
    )
