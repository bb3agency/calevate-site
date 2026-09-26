"""Request-edge hardening: the unbounded inputs an outside caller controls.

Suffix `_security_test` per BACKEND-PATTERNS §9. Each test here fails against the code
as it stood before the fix beside it, and each failure was driven rather than reasoned
about:

1. **A Meta object id is a durable key, so it has to be bounded.** `leadgen_id` becomes
   `webhook_inbox_events.event_key`, which carries a UNIQUE btree index; an id past the
   ~2704-byte index-tuple ceiling made Postgres answer `index row size N exceeds btree
   version 4 maximum` and the request became an unhandled 500 — with the catch-all
   `unhandled_exception:OperationalError` alert, whose fingerprint `alerting._admit` then
   suppresses for fifteen minutes. That is the same defect `engine_intake._keyable`
   already refuses on the voice-runtime side, live on this one.
2. **A batch is an unbounded loop over caller-supplied items.** One signed megabyte holds
   ~20,000 minimal `leadgen` changes and `_absorb_leadgen` costs a Graph round trip plus
   up to three transactions each.

Run: uv run pytest -q tests/request_edge_security_test.py
"""

from __future__ import annotations

import base64
import os
import uuid
from typing import Any

import pytest
from apps.api.ingest import meta
from apps.api.ingest import routes as ingest_routes
from apps.api.main import app as api_app
from httpx import ASGITransport, AsyncClient
from tests.meta_lead_ads_test import (
    _client,
    _daytime,  # noqa: F401 — pins the compliance clock
    _signed,
    _tenant_with_meta_source,
)

def _incompressible(length: int) -> str:
    """A string of `length` characters that Postgres cannot compress away.

    Not `"9" * 3000`: an index tuple of repeated bytes compresses under the ceiling and
    the insert succeeds, which is how this defect stayed invisible to a first probe.
    """
    return base64.b64encode(os.urandom(length)).decode()[:length]


def _leadgen_body(*ids: Any, page_id: int = 153125381133) -> dict[str, Any]:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": 1438292065,
                "changes": [
                    {"field": "leadgen", "value": {"leadgen_id": lid, "page_id": page_id}}
                    for lid in ids
                ],
            }
        ],
    }


async def test_an_unstorable_leadgen_id_is_skipped_rather_than_crashing_the_delivery() -> None:
    """A signed delivery naming a 3 KiB id must not reach the unique index.

    The id is refused at the boundary (`meta.MAX_OBJECT_ID_LEN`), which makes the
    notification unkeyable — the answer `extract_lead_notifications` already gives a
    change that names no id at all — so the delivery is answered rather than raised, and
    the sibling in the same batch is still absorbed.
    """
    _, _, webhook_id = await _tenant_with_meta_source()
    good = str(uuid.uuid4().int)[:15]
    raw, headers = _signed(_leadgen_body(_incompressible(3000), good))

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )

    assert response.status_code == 200, response.text
    body = response.json()
    # The over-long id never becomes a notification; the well-formed sibling still does.
    assert body["received"] == 1, body


async def test_a_control_character_in_an_id_never_reaches_a_durable_key() -> None:
    """A NUL cannot be stored in a Postgres text column at all, and the rest of the C0
    range is key- and log-injection material for a value we copy verbatim into a dedupe
    key. Refused at the same boundary, and refused as a UNIT — a scan of the parsed
    notification proves the character did not survive into our shape."""
    assert meta._as_id("lead\x00id") == ""
    assert meta._as_id("lead\nid") == ""
    assert meta._as_id("9" * meta.MAX_OBJECT_ID_LEN) == "9" * meta.MAX_OBJECT_ID_LEN
    assert meta._as_id("9" * (meta.MAX_OBJECT_ID_LEN + 1)) == ""

    found = meta.extract_lead_notifications(_leadgen_body("lead\x00id"))
    assert found == [], "an id we refuse to store became a unit of work"


async def test_a_batch_past_the_cap_is_deferred_rather_than_walked() -> None:
    """One delivery may not put us to work for an unbounded number of leads.

    The overflow is DEFERRED, not dropped: the response is the 503 that tells Meta to
    redeliver, so nothing is acked that was not done. What is asserted is the bound — the
    number of notifications the handler actually absorbed — because a 503 alone would
    also be produced by a transient Graph failure.
    """
    _, _, webhook_id = await _tenant_with_meta_source()
    over = ingest_routes.MAX_LEADGEN_PER_DELIVERY + 5
    ids = [str(900000000000000 + i) for i in range(over)]
    raw, headers = _signed(_leadgen_body(*ids))

    absorbed: list[str] = []
    real = ingest_routes._absorb_leadgen

    async def counting(**kwargs: Any) -> Any:
        absorbed.append(kwargs["notification"].leadgen_id)
        return await real(**kwargs)

    ingest_routes._absorb_leadgen = counting  # type: ignore[assignment]
    try:
        async with _client() as http:
            response = await http.post(
                f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
            )
    finally:
        ingest_routes._absorb_leadgen = real  # type: ignore[assignment]

    assert len(absorbed) == ingest_routes.MAX_LEADGEN_PER_DELIVERY, (
        f"the handler walked {len(absorbed)} notifications for one delivery"
    )
    assert response.status_code == 503, response.text
    assert response.json()["type"].endswith("/meta_lead_retrieval_deferred")
