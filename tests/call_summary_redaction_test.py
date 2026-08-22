"""`calls.summary` is transcript-derived prose, and it was shipping RAW (hard rule 5).

The chain these tests pin, end to end:

1. the extractor writes a summary that can contain — and in the offline case IS —
   transcript text verbatim (`apps/workers/extraction.py`);
2. the pipeline stores it unredacted in `calls.summary`
   (`apps/workers/pipeline._persist_extraction`);
3. the CRM list and detail returned that column verbatim to anyone holding plain
   `calls:read` (`apps/api/crm/service.py`).

Step 3 is the breach: `staff` is the role DATA-MODEL §2 defines as "no raw transcripts",
and it could read transcript content — a phone number a caller read out loud — off the
ordinary calls list, with no `calls:read_raw` check and no `audit_log` row. Every OTHER
surface that carries this same column already redacts it on the way out (the outbound
`call.completed` webhook, the hot-lead notification, the DPDP subject export); the
screen the client actually looks at was the one that did not.

The line these tests draw is the one hard rule 5 draws: `text` vs `text_redacted`. The
default view of a summary must be no more revealing than the default view of the
transcript it came from — same `redact()` pass, same result — and the raw summary stays
where the raw transcript already is, behind `calls:read_raw` plus an audit write.
"""

from __future__ import annotations

import uuid

from apps.api.crm import service as crm
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.extraction import OfflineExtractor
from apps.workers.redaction import redact
from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec
from sqlalchemy import text
from tests.api_security_test import _client, _make_tenant

# A number shaped exactly like the one a Telugu caller reads out at the end of a call:
# 10 digits, leading 9. `redact()` keeps the last two so staff can still recognise it.
CALLER_NUMBER = "9876500123"
LAST_TURN = f"caller: Naa number {CALLER_NUMBER}, malli call cheyandi."
TRANSCRIPT = (
    "agent: Namaskaram, Sunrise Clinic. Cheppandi.\n"
    "caller: Naa peru Ravi. Repu appointment kavali.\n"
    f"{LAST_TURN}"
)


async def _call_with_summary(tenant_id: uuid.UUID, summary: str) -> uuid.UUID:
    """One completed call carrying `summary`, plus the transcript it was derived from."""
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, summary, sentiment, outcome_tag, started_at, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :ecid, 'inbound', 'completed', :from_e, :summary, "
                "'neutral', 'needs_follow_up', now(), now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"sum_{call_id.hex[:10]}",
                "from_e": f"+91{CALLER_NUMBER}",
                "summary": summary,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:id, :tid, :cid, 0, 'caller', "
                ":raw, :redacted, now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "cid": call_id,
                "raw": LAST_TURN,
                "redacted": redact(LAST_TURN).text,
            },
        )
    return call_id


async def _audit_rows_for(call_id: uuid.UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE object_id = :cid"),
                    {"cid": str(call_id)},
                )
            ).scalar()
            or 0
        )


# --- 1. provenance: the summary really is transcript text ----------------------


async def test_the_offline_extractors_summary_is_a_transcript_line_verbatim() -> None:
    """Not a paraphrase, not an abstraction: the last line of the transcript, copied.

    This is why the read path cannot treat `summary` as a derived-and-therefore-harmless
    field. `get_extractor()` returns this extractor whenever no provider key is
    configured — every local run and all of CI — and the model path is no guarantee
    either: the prompt asks for two sentences of prose with nothing constraining what
    may appear inside them, which is exactly what `compliance/export.py` says about this
    same column when it masks foreign numbers out of it.
    """
    spec = ExtractionSchemaSpec(
        fields=[ExtractionField(key="name", label="Name", type="text", description="caller name")]
    )

    result = await OfflineExtractor().run(spec, TRANSCRIPT)

    assert result["summary"] == LAST_TURN
    assert CALLER_NUMBER in result["summary"], "a raw phone number, straight off the transcript"


# --- 2. the breach: reachable with plain `calls:read` --------------------------


async def test_staff_cannot_read_transcript_content_through_the_calls_list() -> None:
    """The ordinary calls list, the most-used screen in the product, for the role that
    is explicitly barred from raw transcripts."""
    tenant_id, slug, token = await _make_tenant(role="staff")
    call_id = await _call_with_summary(tenant_id, LAST_TURN)

    async with _client() as http:
        response = await http.get(
            "/v1/calls", headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
        )

    assert response.status_code == 200
    # The E.164 contact field is stripped before the search, not exempted from it: since
    # D-436 `caller_e164` carries the other party's number IN FULL and deliberately, so a
    # whole-body substring scan now finds that rather than the leak it was written for.
    # The invariant here was always about TRANSCRIPT CONTENT reaching a reader without
    # `calls:read_raw`, and that is what this still asserts — `summary` and the turns.
    # The idiom is this file's own (see the raw-export test below).
    assert CALLER_NUMBER not in response.text.replace(f"+91{CALLER_NUMBER}", ""), (
        "a reader without calls:read_raw pulled raw transcript content out of `summary`"
    )
    assert await _audit_rows_for(call_id) == 0, "...and nothing recorded that they had"

    listed = next(item for item in response.json() if item["id"] == str(call_id))
    # The fix must not be "blank the column": the summary is what makes this list
    # scannable, and a list of empty cells is a broken screen, not a safe one.
    assert "malli call cheyandi" in listed["summary"]
    assert listed["summary"] == redact(LAST_TURN).text


async def test_staff_cannot_read_transcript_content_through_the_call_detail() -> None:
    """Same column, same role, one screen deeper — where the redacted transcript is
    already on display, and the summary sat above it unredacted."""
    tenant_id, slug, token = await _make_tenant(role="staff")
    call_id = await _call_with_summary(tenant_id, LAST_TURN)

    async with _client() as http:
        response = await http.get(
            f"/v1/calls/{call_id}",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"][0]["redacted"] is True, "the transcript view was already redacted"
    # `caller_e164` stripped for the reason given in the list test above (D-436).
    assert CALLER_NUMBER not in response.text.replace(f"+91{CALLER_NUMBER}", ""), (
        "...but the summary above it was not"
    )
    assert await _audit_rows_for(call_id) == 0


async def test_the_summary_never_says_more_than_the_redacted_transcript_it_came_from() -> None:
    """The property, stated once: same `redact()` pass, so the default summary cannot
    disclose anything the default transcript would have withheld."""
    tenant_id, slug, token = await _make_tenant(role="staff")
    call_id = await _call_with_summary(tenant_id, LAST_TURN)

    async with _client() as http:
        detail = await http.get(
            f"/v1/calls/{call_id}",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    body = detail.json()
    assert body["summary"] == body["transcript"][0]["text"] == redact(LAST_TURN).text


# --- 3. the raw view is still reachable, where it always was -------------------


async def test_the_audited_raw_view_still_returns_the_unredacted_summary() -> None:
    """Redaction by default is not redaction always. An owner reading the allowlisted
    raw-transcript route — role-checked AND audit-logged in the same transaction — gets
    the summary the model actually wrote, because the whole point of that route is that
    somebody may look, on the record. Without this the fix would be a data loss."""
    tenant_id, slug, token = await _make_tenant(role="owner")
    call_id = await _call_with_summary(tenant_id, LAST_TURN)

    async with _client() as http:
        raw = await http.get(
            f"/v1/calls/{call_id}/transcript/raw",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert raw.status_code == 200
    assert raw.json()["summary"] == LAST_TURN
    assert CALLER_NUMBER in raw.text
    assert await _audit_rows_for(call_id) == 1, "role check AND audit row (hard rule 5)"


# --- 4. the other things this column feeds -------------------------------------


async def test_the_callback_context_note_carries_no_raw_pii() -> None:
    """`plan_callback` renders the summary into an outbound agent's PROMPT.

    SEC-COMP §4 puts redaction before anything transcript-derived leaves the system, and
    this leaves twice: to the engine as prompt text, and then out of the AI's mouth to
    the person being rung. A follow-up call that reads a caller's own Aadhaar back to
    them is the worst rendering of this column we can produce.
    """
    tenant_id, _, _ = await _make_tenant(role="owner")
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("UPDATE agents SET direction = 'outbound' RETURNING id"))
        ).scalar()
        lead_id = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).scalar()
    call_id = await _call_with_summary(tenant_id, LAST_TURN)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET lead_id = :lid, agent_id = :aid WHERE id = :cid"),
            {"lid": lead_id, "aid": agent_id, "cid": call_id},
        )
        plan = await crm.plan_callback(session, call_id)

    assert CALLER_NUMBER not in plan.context_note
    assert "malli call cheyandi" in plan.context_note, "the context itself survives"


async def test_the_lead_csv_export_carries_no_call_summary_column() -> None:
    """The export is the widest read in the product (full phone numbers, owner-only),
    so its column list is worth pinning: it is built from the tenant's extraction schema
    and the lead row, and `calls.summary` is in neither. If a future export grows a
    summary column it must grow the redaction with it — this test is where that
    conversation starts."""
    tenant_id, slug, token = await _make_tenant(role="owner")
    await _call_with_summary(tenant_id, LAST_TURN)

    async with _client() as http:
        response = await http.get(
            "/v1/leads/export.csv",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )

    assert response.status_code == 200
    header = response.text.splitlines()[0]
    assert "summary" not in header.lower()
    assert CALLER_NUMBER not in response.text.replace(f"+91{CALLER_NUMBER}", ""), (
        "the export's own phone column is deliberate and audited; a summary would not be"
    )
