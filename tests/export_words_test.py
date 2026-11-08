"""The CSV exports say what the screens say (audit 8 Nov 2026, E-01).

A lead's stage is "Goal reached", not `hot`; its source "Incoming call", not `inbound_call`;
its next step the owner's own instruction; its dates in India time. The word maps are the
server's twin of the web's, and the last test holds the two in step.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from apps.api.crm import export_words
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.lead_columns_test import _client, _lead, _rows, _tenant

pytestmark = [pytest.mark.rls]

WEB = Path(__file__).resolve().parents[1] / "apps" / "web" / "src" / "lib"


async def test_the_lead_export_writes_the_owners_words_and_india_time() -> None:
    t = await _tenant()
    lead_id = await _lead(t, name="Lakshmi")
    call_id = uuid.uuid4()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, direction, "
                "status, next_step, created_at, updated_at) VALUES (:id, :t, :a, :l, :e, "
                "'inbound', 'completed', 'The business needs to call them back.', now(), now())"
            ),
            {
                "id": call_id,
                "t": t.tenant_id,
                "a": t.agent_id,
                "l": lead_id,
                "e": f"exp-{call_id.hex[:10]}",
            },
        )
        await session.execute(
            text(
                "UPDATE leads SET status = 'hot', last_call_id = :c, created_at = :at WHERE id = :l"
            ),
            {"c": call_id, "l": lead_id, "at": datetime(2026, 11, 8, 4, 33, tzinfo=UTC)},
        )
    async with _client() as http:
        exported = await http.get(
            f"/v1/leads/export.csv?agent_id={t.agent_id}"
            "&columns=status,source,next_step,created_at",
            headers=t.headers,
        )
    assert exported.status_code == 200, exported.text
    rows = _rows(exported.text)
    at = {label: i for i, label in enumerate(rows[0])}
    row = rows[1]
    assert row[at["Status"]] == "Goal reached"
    assert row[at["Source"]] == "Incoming call"
    assert row[at["Next step"]] == "Call them back."
    assert row[at["Created"]] == "2026-11-08T10:03:00+05:30"


def test_an_unknown_key_is_written_as_it_came_not_dropped() -> None:
    assert export_words.lead_source("whatsapp_form") == "Whatsapp form"
    assert export_words.call_status(None) is None


def _ts_map(source: str, const: str) -> dict[str, str]:
    """The `key: "Label"` (or `key: { label: "Label" }`) pairs of one web constant."""
    body = source.split(f"const {const}", 1)[1].split("\n};", 1)[0]
    pairs = re.findall(r"^\s{2}(\w+):\s*(?:\{\s*label:\s*)?\"([^\"]+)\"", body, re.MULTILINE)
    return dict(pairs)


def test_the_word_maps_match_the_screens() -> None:
    labels = (WEB / "leadLabels.ts").read_text(encoding="utf-8")
    review = (WEB / "callReview.ts").read_text(encoding="utf-8")
    assert _ts_map(labels, "SOURCE_LABELS") == export_words.SOURCE_WORDS
    assert _ts_map(review, "OUTCOME_WORDS") == export_words.OUTCOME_WORDS
    status = _ts_map(review, "STATUS_WORDS")
    assert status == {k: v for k, v in export_words.CALL_STATUS_WORDS.items() if k != "completed"}
