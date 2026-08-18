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

  **P2.3's CALL SITE IS NOW GONE, AND THE TEST BECAME A SCAN (D-353).** `_next_link` was
  written because Bolna was believed to publish no pagination contract; it publishes one,
  and the adapter now builds its own paged URLs. So no adapter parses a URL it did not
  build, the `InvalidURL` exposure is unreachable rather than handled, and the vendor can
  no longer name a destination that receives our `Authorization` header. The scan holds
  that property for the adapter written next — see the P2.3 test below.

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


def test_no_adapter_turns_a_vendor_supplied_string_into_a_request_url() -> None:
    """P2.3 IS NOW STRUCTURAL, BECAUSE THE CALL SITE IT GUARDED NO LONGER EXISTS (D-353).

    The original test drove `BolnaEngine._next_link` with a zero-width space in the host
    and asserted the listing came back incomplete rather than raising. That function is
    gone: Bolna's real listing contract is `page_number`/`page_size`/`has_more`
    (VERIFIED-OAS), not a continuation URL, so the adapter constructs every URL it fetches
    from its own base and its own parameters and never GETs a string the vendor chose.

    Deleting the old test outright would have quietly given back the property it bought.
    `httpx.InvalidURL` escaping an adapter was only ever REACHABLE because some adapter
    parsed a vendor-supplied URL — so the strongest statement available now is that none
    of them does, which is also a real SSRF surface (a vendor-controlled destination
    receiving our `Authorization` header) that this tree no longer has at all.

    Written as a scan rather than as a behavioural test for the same reason the module
    docstring gives for the P2.2 scan: this has to cover the adapter somebody writes next,
    not the two that exist today. A future adapter whose vendor DOES hand out continuation
    links may legitimately need this — and then it fails here, which is the point: it is a
    decision with an SSRF story to write down, not a line to slip in.
    """
    offenders: dict[str, list[str]] = {}
    for path in sorted(ENGINE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = [
            f"line {node.lineno}: httpx.URL(...)"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "URL"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "httpx"
        ]
        if hits:
            offenders[path.name] = hits

    assert not offenders, (
        f"an adapter parses a URL it did not build: {offenders}. `httpx.URL()` raises "
        "`httpx.InvalidURL`, whose MRO excludes `httpx.HTTPError` (measured above), so no "
        "`except` clause on the listing path catches it — and a vendor-chosen destination "
        "would carry our Authorization header. Build request URLs from the configured "
        "base and typed parameters instead."
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
