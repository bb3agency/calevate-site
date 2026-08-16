"""A signing engine the receiver cannot verify must be refused, and the refusal must be
visible. Suffix `_security_test` per BACKEND-PATTERNS §9.

D-93 made `cartesia` selectable as `ENGINE=` and D-103 made the voice-runtime receiver
stop keeping its own copy of the engine set, so `cartesia` is now a name the receiver
answers for. Answering for a name and admitting its payloads are different things, and the
gap between them is the whole subject of this file.

WHY IT IS ITS OWN FILE. `voice_runtime_security_test.py` §12 already asserts that the
`hmac` branch refuses. What it cannot assert is the property D-103 introduced a way to
break: the branch below it now reads `if method == "none": if get_settings().engine ==
engine`, generalised off the literal `"fake"`. That generalisation is correct — it removes
the last hard-coded vendor name from the latency-critical receiver — and it puts a new
sentence one branch away from the signature check: *this engine is the one we run, so let
it in*. The tests here are the ones that fail if that sentence ever moves up.

WHAT A WAVE-THROUGH WOULD ACTUALLY COST, since "we refuse it anyway" reads like a
formality until you follow the write. `webhook_routes._claim_and_enqueue` takes
`signed=verdict.method == "hmac"` and writes it into `webhook_deliveries.signature_valid`.
That column is the forensic record of what evidence we HAD. So a receiver that accepted an
`hmac` delivery it never checked would not merely accept a forgery: it would file the
forgery under our strongest evidence class, and the investigation six months later would
read `signature_valid = true` next to a payload nobody verified.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
import webhook_routes
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from calevate_shared.config import SELECTABLE_ENGINES
from calevate_shared.engine import WEBHOOK_AUTH_BY_ENGINE
from engine_intake import KNOWN_ENGINES, verify_source
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text

# RFC 5737 documentation ranges — unroutable, so a copy-paste into a real config is inert.
ENGINE_EGRESS_IP = "198.51.100.7"
ATTACKER_IP = "203.0.113.9"
EDGE_PROXY_IP = "127.0.0.1"  # inside TRUSTED_PROXY_CIDRS — our own nginx

#: Derived, never listed. A fifth adapter that declares `hmac` is covered by these tests
#: the day it is added, which is the only way a guard keeps up with the thing it guards.
SIGNING_ENGINES = sorted(n for n, method in WEBHOOK_AUTH_BY_ENGINE.items() if method == "hmac")


@pytest.fixture(autouse=True)
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    """Point the Bolna allowlist at a documentation address.

    Present so the source-IP evidence a genuine Bolna delivery would carry is available to
    these tests — the point being that it buys a signing engine exactly nothing.
    """
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client(peer_ip: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444)),
        base_url="http://runtime",
    )


def _event() -> tuple[str, str, dict[str, Any]]:
    token = uuid.uuid4().hex[:12]
    execution_id = f"exec_{token}"
    status = f"completed-{token}"
    return execution_id, status, {"execution_id": execution_id, "status": status}


# --- 1. the refusal, from every direction it could be softened from ------------


@pytest.mark.parametrize("engine", SIGNING_ENGINES)
def test_a_signing_engine_is_refused_from_every_source_address(engine: str) -> None:
    """No source address is signature evidence, including the good one.

    Three callers: the allowlisted egress address a genuine Bolna delivery arrives from,
    a stranger, and a delivery whose client IP could not be established at all. The verdict
    must be byte-identical across all three — if it is not, some source-IP reasoning has
    leaked into the signature branch, and the allowlist it leaked from describes a
    DIFFERENT vendor's egress.
    """
    allowlisted = verify_source(engine, ENGINE_EGRESS_IP)
    assert allowlisted.ok is False
    assert allowlisted.method == "hmac"
    assert allowlisted.reason == "signature verification not implemented"
    assert verify_source(engine, ATTACKER_IP) == allowlisted
    assert verify_source(engine, None) == allowlisted


@pytest.mark.parametrize("engine", SIGNING_ENGINES)
def test_a_signing_engine_is_refused_even_on_the_deployment_that_runs_it(
    engine: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE ONE THIS FILE EXISTS FOR.

    `verify_source`'s `none` branch opens the door when `get_settings().engine == engine`
    — correct there, because an engine that declares no authenticity control has nothing
    to check and the fake engine is how the pipeline runs offline. Applied one branch
    earlier it would be a catastrophe with a plausible sentence attached: "we are running
    Cartesia, so a Cartesia webhook is expected, so admit it". Expected is not
    authenticated. The engine being ours makes a forged delivery MORE useful to an
    attacker, not less — it is the configuration in which our workers will act on it.

    Only engines that are actually selectable can be in this state, so the fixture adapter
    is skipped rather than pretended into a deployment it can never reach.
    """
    if engine not in SELECTABLE_ENGINES:
        pytest.skip(f"{engine} is deliberately not selectable as ENGINE=")

    monkeypatch.setattr(get_settings(), "engine", engine)
    verdict = verify_source(engine, ENGINE_EGRESS_IP)
    assert verdict.ok is False, (
        f"a deployment running ENGINE={engine} admitted an unverified signed delivery — "
        "the `none` branch's 'this engine is ours' gate has reached the `hmac` branch"
    )
    assert verdict.method == "hmac"


async def test_a_cartesia_delivery_is_refused_over_http_and_files_nothing() -> None:
    """The unit verdict honoured by the whole stack, and the forensic table left empty.

    A unit-level refusal the route does not honour is not a refusal, and the assertion
    that matters is not the 401 — it is the zero. `webhook_deliveries` is where
    `signature_valid` lives, so "no row" is the proof that nothing was filed under an
    evidence class we cannot produce.

    Sent from the allowlisted edge with a well-formed body: everything a genuine delivery
    would have except the one thing this engine's authenticity rests on.
    """
    execution_id, status, body = _event()
    async with _client(EDGE_PROXY_IP) as http:
        response = await http.post(
            "/hooks/v1/engine/cartesia",
            json=body,
            headers={"CF-Connecting-IP": ENGINE_EGRESS_IP},
        )

    assert response.status_code == 401, response.text
    async with untenanted_session() as session:
        inbox = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_inbox_events "
                    "WHERE provider = 'cartesia' AND event_key = :k"
                ),
                {"k": f"{execution_id}:{status}"},
            )
        ).scalar()
        filed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_deliveries "
                    "WHERE source = 'cartesia' AND event_type = :e AND direction = 'in'"
                ),
                {"e": status},
            )
        ).scalar()
    assert (inbox, filed) == (0, 0)


async def test_no_delivery_has_ever_been_filed_as_signed() -> None:
    """The invariant behind the row count above, asserted over the whole table.

    `signature_valid = true` is reachable only through `verdict.ok and verdict.method ==
    "hmac"`, and no adapter in this tree can produce that pair. This is the assertion that
    notices if one starts to — including through a path no test in this file walks, which
    is the kind of path that gets added later by someone solving a different problem.
    """
    async with untenanted_session() as session:
        signed = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_deliveries "
                    "WHERE direction = 'in' AND signature_valid IS TRUE"
                )
            )
        ).scalar()
    assert signed == 0, (
        "a delivery is recorded as signature-verified, but no engine in this tree "
        "implements a signature verifier — either one landed without this test being "
        "updated, or the receiver is filing unverified payloads as signed"
    )


# --- 2. the refusal is attributable, which is the half that was broken ---------


def test_a_refused_cartesia_delivery_is_labelled_cartesia_and_not_unknown() -> None:
    """The observability defect the drift actually caused (D-103).

    `_refuse` bounds the URL's `{engine}` segment to `KNOWN_ENGINES` before it becomes a
    metric label, because on the refusal path that segment is a stranger's string and an
    unbounded label blinds our own monitoring. While `KNOWN_ENGINES` was the receiver's own
    stale copy, `cartesia` fell outside it — so on a deployment running `ENGINE=cartesia`
    every single delivery would 401 and every one of those 401s would be attributed to
    `unknown`, i.e. to a prober rather than to our own unimplemented verifier.

    That is the exact failure `_refuse` was written to prevent for Bolna: its docstring
    argues that unmeasured refusals make `webhook_ack_ms` go SILENT rather than spike, and
    a silent graph is indistinguishable from a quiet night. A MISATTRIBUTED graph is worse
    — it points at the wrong incident.

    The bound still holds where it must: a name nothing in the tree ships is still
    collapsed to `unknown`.
    """
    labels: list[str] = []
    # Driven through a spy METER, not by patching the module's recorder: which SERIES an
    # ack lands in became a property of the `AckMeter` an endpoint carries when the in-call
    # tool endpoint stopped sharing the receiver's `webhook_ack_ms` (D-147), so the meter is
    # the seam that decides the label and therefore the one a test has to drive.
    spy = replace(
        webhook_routes.WEBHOOK_ACK,
        record=lambda elapsed, *, provider: labels.append(provider),
    )
    for engine in ("cartesia", "bolna", "twilio"):
        webhook_routes._refuse(time.perf_counter(), engine, meter=spy)

    assert labels == ["cartesia", "bolna", "unknown"]


def test_the_set_the_receiver_labels_is_the_set_it_authenticates() -> None:
    """`KNOWN_ENGINES` and `verify_source` must partition the same way.

    They were two answers to one question: the metric bound came from a local `Literal` and
    the authenticity decision came from `WEBHOOK_AUTH_BY_ENGINE`. That is how a name could
    be authenticated as a signing engine and labelled `unknown` in the same request.

    Asserted in both directions over the live table, so neither a name added to the table
    nor one dropped from it can leave the two disagreeing.
    """
    for engine in sorted(KNOWN_ENGINES):
        assert verify_source(engine, ENGINE_EGRESS_IP).reason != "unknown engine", (
            f"{engine} is labelled as an engine we run but the receiver has no "
            "authenticity story for it"
        )

    for stranger in ("twilio", "vapi", "retell", ""):
        assert stranger not in KNOWN_ENGINES
        verdict = verify_source(stranger, ENGINE_EGRESS_IP)
        assert verdict.ok is False
        assert verdict.reason == "unknown engine"


__all__: list[Any] = []
